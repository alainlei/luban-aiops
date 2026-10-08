"""HTTP service-check connector (SPEC-058).

Two bounded tools over a **model-supplied URL**:

  read tier   http.get
  write tier  http.post

A model-supplied URL is ``web.navigate``'s shape, not ``adding-a-tool.md``'s
config-base-URL ``cmdb.lookup`` shape, so both tools inherit the browser
connector's origin discipline (R-2): a server-side allowlist that is
deny-by-default, redirects that halt when they leave it, and scheme /
userinfo / loopback / link-local / multicast refusals. Credentials enter by
``credential_set`` reference only (R-4) — neither tool ships a ``headers``
parameter, so a secret can never be a model-supplied literal by construction.

All bounds live in the connector, not in the tool classes: ``_request`` is the
single transport call site both verbs share, so a future verb inherits the
allowlist, redirect, destination and credential rules without a
re-implementation, and the test seam is single (R-8).

An upstream 4xx/5xx is returned as a **successful tool result carrying that
status** — "the service answered 503" is the fact a health check exists to
report — not as a tool error. ``UPSTREAM_ERROR`` is reserved for a response the
gateway itself could not complete.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import time
from urllib.parse import parse_qsl, urljoin, urlsplit

import httpx

from tool_gateway.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolResult,
    build_evidence,
    make_error_result,
)
from tool_gateway.tools.auth_resolution import resolve_outbound_auth
from tool_gateway.tools.browser_connector import origin_of
from tool_gateway.tools.credential_sets import CredentialSetStore
from tool_gateway.tools.oauth_client import OAuth2TokenClient
from tool_gateway.tools.registry import ToolRegistry
from tool_gateway.tools.url_redaction import is_secret_param, redact_secret_query

LOGGER = logging.getLogger(__name__)

SOURCE_SYSTEM = "http"
CATEGORY = "http"

DEFAULT_TIMEOUT_MS = 10000
MAX_TIMEOUT_MS = 30000
_MAX_REDIRECTS = 3
_MAX_BODY_KEYS = 32
_MAX_BODY_DEPTH = 2
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

# Response headers projected into a result — **never** the upstream's header
# set (R-1). ``set-cookie`` is a credential and ``authorization`` echoes one,
# and neither the redaction engine's value patterns nor its sensitive-key
# vocabulary would catch them sitting under those names, so both are absent
# from this set and the set is not configurable: the only way to add them is to
# edit this constant, which is the point (a test asserts their suppression with
# a response that carries them).
_PROJECTED_HEADERS = frozenset({
    "content-type",
    "content-length",
    "location",
    "server",
    "date",
    "cache-control",
})


def _json_depth(value: object) -> int:
    """Nesting depth of a JSON value: a scalar is 0, ``{"a": 1}`` is 1."""
    if isinstance(value, dict):
        return 1 + max((_json_depth(v) for v in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_json_depth(v) for v in value), default=0)
    return 0


def _count_keys(value: object) -> int:
    """Total object-key count across every nesting level."""
    total = 0
    if isinstance(value, dict):
        total += len(value)
        for item in value.values():
            total += _count_keys(item)
    elif isinstance(value, list):
        for item in value:
            total += _count_keys(item)
    return total


def _validate_destination(
    url: object,
    allow_origins: frozenset[str],
    forbid_secret_query: bool = False,
) -> tuple[str | None, tuple[str, str, str] | None]:
    """Validate a model-supplied URL before any socket is opened (R-2/R-3).

    Returns ``(origin, None)`` on success or ``(None, (code, message, status))``
    on refusal, where ``status`` is ``"denied"`` for an allowlist/destination
    refusal and ``"error"`` for a parameter problem. Never raises.
    """
    if not isinstance(url, str) or not url.strip():
        return None, (
            "INVALID_PARAMETERS", "Parameter 'url' is required.", "error"
        )
    candidate = url.strip()
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None, (
            "INVALID_PARAMETERS",
            f"Parameter 'url' is not a parseable URL: {url!r}.",
            "error",
        )
    if parsed.scheme not in {"http", "https"}:
        return None, (
            "HTTP_SCHEME_NOT_ALLOWED",
            f"URL scheme {parsed.scheme or '(none)'!r} is not allowed; "
            "only http and https are accepted.",
            "error",
        )
    # A credential in ``scheme://user:pass@host`` is a literal secret in a
    # model-supplied argument; R-4 exists so that never happens.
    if parsed.username or parsed.password:
        return None, (
            "INVALID_PARAMETERS",
            "URL userinfo (user:password@host) is not allowed; authenticate "
            "with the 'credential_set' parameter instead.",
            "error",
        )
    host = parsed.hostname
    if not host:
        return None, (
            "INVALID_PARAMETERS", "URL has no host component.", "error"
        )
    # Loopback / link-local (incl. 169.254.169.254) / multicast are refused
    # even if listed: an allowlist entry is not a considered decision to reach
    # the node's own metadata service. A hostname that is not an IP literal is
    # never refused on this ground — ``http://acme-admin:8080`` is the intended
    # in-cluster shape, and private ranges are deliberately not refused.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_loopback or ip.is_link_local or ip.is_multicast
    ):
        return None, (
            "HTTP_ORIGIN_NOT_ALLOWED",
            f"Destination {host} is a loopback, link-local or multicast "
            "address and is refused regardless of the allowlist.",
            "denied",
        )
    origin = origin_of(candidate)
    if origin is None or origin not in allow_origins:
        return None, (
            "HTTP_ORIGIN_NOT_ALLOWED",
            f"Origin {origin if origin is not None else candidate!r} is not "
            "in GATEWAY_HTTP_ALLOW_ORIGINS (deny-by-default).",
            "denied",
        )
    if forbid_secret_query:
        for key, _value in parse_qsl(parsed.query, keep_blank_values=True):
            if is_secret_param(key):
                return None, (
                    "HTTP_URL_SECRET_NOT_ALLOWED",
                    f"A POST URL may not carry the secret-bearing query "
                    f"parameter {key!r}; put the value in the body instead.",
                    "error",
                )
    return origin, None


def _validate_body(
    body: object, max_bytes: int
) -> tuple[str, str] | None:
    """Bound a POST body before the transport is touched (R-3)."""
    if not isinstance(body, dict):
        return (
            "INVALID_PARAMETERS",
            "Parameter 'body' must be a JSON object.",
        )
    depth = _json_depth(body)
    if depth > _MAX_BODY_DEPTH:
        return (
            "INVALID_PARAMETERS",
            f"Parameter 'body' nests {depth} levels deep; the maximum is "
            f"{_MAX_BODY_DEPTH}.",
        )
    keys = _count_keys(body)
    if keys > _MAX_BODY_KEYS:
        return (
            "INVALID_PARAMETERS",
            f"Parameter 'body' carries {keys} keys; the maximum is "
            f"{_MAX_BODY_KEYS}.",
        )
    try:
        serialized = json.dumps(body).encode("utf-8")
    except (TypeError, ValueError):
        return (
            "INVALID_PARAMETERS",
            "Parameter 'body' is not JSON-serializable.",
        )
    if len(serialized) > max_bytes:
        return (
            "HTTP_BODY_TOO_LARGE",
            f"Parameter 'body' serializes to {len(serialized)} bytes; the "
            f"maximum is {max_bytes} (GATEWAY_HTTP_MAX_REQUEST_BYTES).",
        )
    return None


def _coerce_timeout(value: object, default: int) -> tuple[int, str | None]:
    if value is None:
        return default, None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default, (
            f"Parameter 'timeout_ms' must be an integer, got {value!r}."
        )
    if parsed < 1:
        return default, (
            f"Parameter 'timeout_ms' must be at least 1, got {parsed}."
        )
    return min(parsed, MAX_TIMEOUT_MS), None


def _coerce_max_bytes(value: object, ceiling: int) -> tuple[int, str | None]:
    """Clamp ``max_bytes`` into [1, ceiling]; the configured cap is the max."""
    if value is None:
        return ceiling, None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return ceiling, (
            f"Parameter 'max_bytes' must be an integer, got {value!r}."
        )
    if parsed < 1:
        return ceiling, (
            f"Parameter 'max_bytes' must be at least 1, got {parsed}."
        )
    return min(parsed, ceiling), None


def _project_response(
    response: httpx.Response,
    final_url: str,
    elapsed_ms: int,
    max_bytes: int,
) -> dict:
    """The fixed-key response projection shared by both verbs (R-1)."""
    headers: dict[str, str] = {}
    for key, value in response.headers.items():
        lowered = key.lower()
        if lowered in _PROJECTED_HEADERS:
            # `location` is itself a URL: a login bounce carrying a token or a
            # ticket in its query would otherwise reach the result, the
            # evidence frame and the durable record in plaintext, defeating
            # the masking `url` receives (R-6). The other projected headers
            # carry no query string, so only this one is redacted.
            if lowered == "location":
                value = redact_secret_query(value)
            headers[lowered] = value
    content_type = headers.get("content-type", "").split(";")[0].strip().lower()
    raw = response.content
    content_length = len(raw)
    truncated = content_length > max_bytes
    cut = raw[:max_bytes] if truncated else raw
    data: dict = {
        "url": redact_secret_query(str(final_url)),
        "status": response.status_code,
        "elapsed_ms": elapsed_ms,
        "headers": headers,
        "content_type": content_type,
        "content_length": content_length,
        "truncated": truncated,
    }
    if content_type.startswith("text/"):
        data["body"] = cut.decode("utf-8", errors="replace")
    elif content_type == "application/json" or content_type.endswith("+json"):
        if truncated:
            # A cut JSON document is not parseable; report the text honestly.
            data["body"] = cut.decode("utf-8", errors="replace")
        else:
            try:
                data["body"] = json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError:
                data["body"] = raw.decode("utf-8", errors="replace")
    # else: binary / octet-stream / image — body omitted, content_type and
    # content_length reported so the agent can say what it found without
    # receiving bytes it cannot reason about.
    return data


def _refusal(
    tool_name: str,
    status: str,
    code: str,
    message: str,
    risk_level: str,
    duration_ms: int,
) -> ToolResult:
    """A structured ``denied``/``error`` envelope carrying the evidence."""
    return ToolResult(
        tool_name=tool_name,
        status=status,
        evidence=build_evidence(risk_level, SOURCE_SYSTEM, duration_ms),
        error={"code": code, "message": message},
    )


class HttpConnector:
    """Registers the HTTP tools and owns the shared request discipline."""

    def __init__(
        self,
        allow_origins: tuple[str, ...] = (),
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        max_response_bytes: int = 65536,
        max_request_bytes: int = 4096,
        credential_sets_path: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # Normalize each configured origin through ``origin_of`` so a trailing
        # slash or a stray uppercase host cannot make an entry unmatchable;
        # the URL side is normalized identically in ``_validate_destination``.
        self._allow_origins = frozenset(
            (origin_of(o) or o.strip().lower())
            for o in allow_origins
            if o and o.strip()
        )
        self._timeout_ms = timeout_ms
        self._max_response_bytes = max_response_bytes
        self._max_request_bytes = max_request_bytes
        self._credentials = CredentialSetStore(credential_sets_path)
        # SPEC-068 R-2/R-3: the connector owns one OAuth2 token client so its
        # in-memory token cache persists across calls. It shares the injected
        # transport, so a test's MockTransport can serve both the token endpoint
        # and the target API.
        self._tokens = OAuth2TokenClient(transport=transport)
        # Test seam: an injected transport (httpx.MockTransport) replaces the
        # real one at the single call site below. None uses httpx's default.
        self._transport = transport

    def register_tools(self, registry: ToolRegistry) -> None:
        """Register both tools.

        ``http.post`` is offered unconditionally here; the registry's risk-tier
        admission (SPEC-021 R-1) refuses it when GATEWAY_MUTATING_TOOLS_ENABLED
        is off — the same division of labour ``k8s_connector`` uses, so the
        flag semantics stay in one place.
        """
        registry.register(HttpGetTool(self))
        registry.register(HttpPostTool(self))

    async def _resolve_auth(
        self, credential_set: object
    ) -> tuple[httpx.Auth | None, tuple[str, str, str] | None]:
        """Resolve a named credential set into outbound auth (R-4).

        Delegates the scheme dispatch to the reusable SPEC-068 R-3 resolver
        (``basic`` / ``bearer`` / ``oauth2_client_credentials``). Only the set
        **name** ever surfaces; a credential value or acquired token flows
        straight into the client and never into a result, evidence field or log
        line.
        """
        if not credential_set:
            return None, None
        name = str(credential_set)
        if not self._credentials.configured:
            return None, (
                "CREDENTIAL_SET_NOT_FOUND",
                f"No credential-set store is configured "
                f"(GATEWAY_HTTP_CREDENTIAL_SETS), so '{name}' cannot be "
                f"resolved.",
                "error",
            )
        entry = self._credentials.get(name)
        if entry is None:
            return None, (
                "CREDENTIAL_SET_NOT_FOUND",
                f"Credential set '{name}' was not found.",
                "error",
            )
        resolved, err = await resolve_outbound_auth(
            set_name=name, entry=entry, token_client=self._tokens
        )
        if err is not None:
            return None, err
        return (resolved.auth if resolved is not None else None), None

    async def _request(
        self,
        method: str,
        url: object,
        timeout_ms: int,
        credential_set: object = None,
        json_body: object = None,
    ) -> tuple[httpx.Response | None, str | None, tuple[str, str, str] | None]:
        """Issue the request with destination + redirect discipline.

        Returns ``(response, final_url, None)`` on success or
        ``(None, None, (code, message, status))`` on refusal/transport failure.
        This is the single transport call site both verbs share.
        """
        forbid_secret = method == "POST"
        origin, err = _validate_destination(
            url, self._allow_origins, forbid_secret_query=forbid_secret
        )
        if err is not None:
            return None, None, err
        auth, err = await self._resolve_auth(credential_set)
        if err is not None:
            return None, None, err

        timeout = timeout_ms / 1000.0
        current = str(url).strip()
        client_kwargs: dict = {"follow_redirects": False, "timeout": timeout}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                for _hop in range(_MAX_REDIRECTS + 1):
                    request_kwargs: dict = {}
                    if auth is not None:
                        request_kwargs["auth"] = auth
                    if json_body is not None:
                        request_kwargs["json"] = json_body
                    response = await client.request(
                        method, current, **request_kwargs
                    )
                    if response.status_code in _REDIRECT_STATUSES:
                        # A write verb never follows a redirect. The allowlist
                        # re-check below bounds the *origin* of every hop, but
                        # not the path — so following one would let an approved
                        # mutation execute at a URL the approver never saw on
                        # the card (and a 303 would even change the verb's
                        # meaning). Refusing keeps the approved URL and the
                        # executed URL identical; a read verb may hop.
                        if method == "POST":
                            return None, None, (
                                "HTTP_REDIRECT_NOT_ALLOWED",
                                "http.post does not follow redirects: the "
                                "approved mutation must execute at the URL "
                                "the approver was shown.",
                                "error",
                            )
                    if response.status_code not in _REDIRECT_STATUSES:
                        return response, current, None
                    location = response.headers.get("location")
                    if not location:
                        # A 3xx with no Location is a terminal fact, not a hop.
                        return response, current, None
                    nxt = urljoin(current, location)
                    _nxt_origin, nxt_err = _validate_destination(
                        nxt,
                        self._allow_origins,
                        forbid_secret_query=forbid_secret,
                    )
                    if nxt_err is not None:
                        _code, message, status = nxt_err
                        return None, None, (
                            "HTTP_REDIRECT_NOT_ALLOWED",
                            f"A redirect attempted to leave the allowlist: "
                            f"{message}",
                            status,
                        )
                    current = nxt
                return None, None, (
                    "HTTP_REDIRECT_NOT_ALLOWED",
                    f"Too many redirects (limit {_MAX_REDIRECTS}).",
                    "error",
                )
        except httpx.TimeoutException:
            return None, None, (
                "HTTP_TIMEOUT",
                f"Request timed out after {timeout_ms}ms.",
                "error",
            )
        except httpx.ConnectError as exc:
            LOGGER.warning("http transport connect error: %s", exc.__class__.__name__)
            return None, None, (
                "TOOL_EXECUTION_ERROR",
                f"Could not connect to {origin}: {exc.__class__.__name__}.",
                "error",
            )
        except httpx.HTTPError as exc:
            LOGGER.warning("http transport error: %s", exc.__class__.__name__)
            return None, None, (
                "UPSTREAM_ERROR",
                f"The HTTP request could not be completed: "
                f"{exc.__class__.__name__}.",
                "error",
            )


# --- Tool implementations ---


class HttpGetTool(BaseTool):
    """A read-tier bounded response check (R-1)."""

    def __init__(self, connector: HttpConnector) -> None:
        self._connector = connector

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="http.get",
            description=(
                "Fetch a URL over HTTP/HTTPS and report its status, projected "
                "headers and body. Read-only: use it to check whether a "
                "service is healthy and what its API returns. The URL's origin "
                "must be allowlisted; an upstream 4xx/5xx is reported as the "
                "status, not as a tool failure."
            ),
            risk_level="read",
            category=CATEGORY,
            parameters_schema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {
                        "type": "string",
                        "description": (
                            "Absolute http/https URL on an allowlisted origin."
                        ),
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_TIMEOUT_MS,
                        "default": DEFAULT_TIMEOUT_MS,
                        "description": (
                            f"Request timeout (default {DEFAULT_TIMEOUT_MS}, "
                            f"max {MAX_TIMEOUT_MS})."
                        ),
                    },
                    "max_bytes": {
                        "type": "integer",
                        "minimum": 1,
                        "description": (
                            "Response-body cap; defaults to and is capped by "
                            "GATEWAY_HTTP_MAX_RESPONSE_BYTES."
                        ),
                    },
                    "credential_set": {
                        "type": "string",
                        "description": (
                            "Optional named credential set resolved "
                            "server-side into HTTP Basic auth; never a "
                            "literal secret."
                        ),
                    },
                },
            },
        )

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()
        timeout_ms, err = _coerce_timeout(
            parameters.get("timeout_ms"), self._connector._timeout_ms
        )
        if err:
            return make_error_result(
                "http.get", "INVALID_PARAMETERS", err,
                source_system=SOURCE_SYSTEM,
            )
        max_bytes, err = _coerce_max_bytes(
            parameters.get("max_bytes"), self._connector._max_response_bytes
        )
        if err:
            return make_error_result(
                "http.get", "INVALID_PARAMETERS", err,
                source_system=SOURCE_SYSTEM,
            )
        response, final_url, rerr = await self._connector._request(
            "GET",
            parameters.get("url"),
            timeout_ms,
            credential_set=parameters.get("credential_set"),
        )
        duration_ms = int((time.perf_counter() - start) * 1000)
        if rerr is not None or response is None or final_url is None:
            code, message, status = rerr  # type: ignore[misc]
            return _refusal(
                "http.get", status, code, message, "read", duration_ms
            )
        data = _project_response(response, final_url, duration_ms, max_bytes)
        return ToolResult(
            tool_name="http.get",
            status="success",
            data=data,
            evidence=build_evidence("read", SOURCE_SYSTEM, duration_ms),
        )


class HttpPostTool(BaseTool):
    """A write-tier bounded JSON mutation (R-3)."""

    def __init__(self, connector: HttpConnector) -> None:
        self._connector = connector

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="http.post",
            description=(
                "POST a small JSON body to a URL on an allowlisted origin. "
                "Mutating: requires operator confirmation. One URL per "
                "invocation; the body is a JSON object bounded to depth 2, 32 "
                "keys and GATEWAY_HTTP_MAX_REQUEST_BYTES. A non-2xx response "
                "is reported with mutation_confirmed=false."
            ),
            risk_level="write",
            category=CATEGORY,
            parameters_schema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {
                        "type": "string",
                        "description": (
                            "Absolute http/https URL on an allowlisted origin. "
                            "May not carry a secret-bearing query parameter."
                        ),
                    },
                    "body": {
                        "type": "object",
                        "description": (
                            "JSON object; depth <= 2, <= 32 keys, "
                            "<= GATEWAY_HTTP_MAX_REQUEST_BYTES serialized."
                        ),
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_TIMEOUT_MS,
                        "default": DEFAULT_TIMEOUT_MS,
                        "description": (
                            f"Request timeout (default {DEFAULT_TIMEOUT_MS}, "
                            f"max {MAX_TIMEOUT_MS})."
                        ),
                    },
                    "credential_set": {
                        "type": "string",
                        "description": (
                            "Optional named credential set resolved "
                            "server-side into HTTP Basic auth; never a "
                            "literal secret."
                        ),
                    },
                },
            },
        )

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()
        timeout_ms, err = _coerce_timeout(
            parameters.get("timeout_ms"), self._connector._timeout_ms
        )
        if err:
            return make_error_result(
                "http.post", "INVALID_PARAMETERS", err,
                risk_level="write", source_system=SOURCE_SYSTEM,
            )
        body = parameters.get("body")
        if body is not None:
            body_err = _validate_body(body, self._connector._max_request_bytes)
            if body_err is not None:
                code, message = body_err
                return make_error_result(
                    "http.post", code, message,
                    risk_level="write", source_system=SOURCE_SYSTEM,
                )
        response, final_url, rerr = await self._connector._request(
            "POST",
            parameters.get("url"),
            timeout_ms,
            credential_set=parameters.get("credential_set"),
            json_body=body,
        )
        duration_ms = int((time.perf_counter() - start) * 1000)
        if rerr is not None or response is None or final_url is None:
            code, message, status = rerr  # type: ignore[misc]
            return _refusal(
                "http.post", status, code, message, "write", duration_ms
            )
        data = _project_response(
            response, final_url, duration_ms,
            self._connector._max_response_bytes,
        )
        # A non-2xx POST is a fact, not a tool error, but a skill must not read
        # a rejection as a success (R-3).
        data["mutation_confirmed"] = 200 <= response.status_code < 300
        return ToolResult(
            tool_name="http.post",
            status="success",
            data=data,
            evidence=build_evidence("write", SOURCE_SYSTEM, duration_ms),
        )
