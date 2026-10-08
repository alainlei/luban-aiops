"""HTTP service-check connector tests (SPEC-058 R-1..R-4, R-7).

Modelled on ``test_skills_connector.py``: a **single transport seam**. The
connector accepts an injected ``httpx.MockTransport`` at its one ``_request``
call site, so every test drives the real destination-validation, projection,
redirect and body-bound logic and only the socket is faked. Where a criterion
spans a layer the connector does not own — output redaction (the
``gateway_service`` choke point) or the mutating-tier policy gate — the test
composes the connector result with that layer's real function rather than
re-implementing it.
"""

import asyncio
import base64
import contextlib
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from tool_gateway.core.config import GatewaySettings
from tool_gateway.tools.http_connector import (
    DEFAULT_TIMEOUT_MS,
    MAX_TIMEOUT_MS,
    HttpConnector,
    _MAX_BODY_DEPTH,
    _MAX_BODY_KEYS,
    _PROJECTED_HEADERS,
    _coerce_max_bytes,
    _coerce_timeout,
    _count_keys,
    _json_depth,
    _validate_body,
    _validate_destination,
)
from tool_gateway.tools.redaction import REDACTION_MARKER, redact_result
from tool_gateway.tools.registry import ToolRegistry

ALLOWED = "http://acme-admin:8080"
OTHER = "http://other:9090"


def _run(coro):
    return asyncio.run(coro)


class _Router:
    """A ``MockTransport`` handler routing on ``(method, path)``.

    Records every request so a test can assert the transport was never reached
    (a pre-transport refusal) or count redirect hops. A route value may be an
    ``httpx.Response`` (single-hit), a callable ``request -> Response`` (fresh
    instance per hit, for a route reached more than once), or an ``Exception``
    instance to raise (simulating a transport failure).
    """

    def __init__(self, routes: dict) -> None:
        self.routes = routes
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        entry = self.routes.get((request.method, request.url.path))
        if entry is None:
            entry = self.routes.get(request.url.path)
        if entry is None:
            return httpx.Response(
                404, json={"error": "no route", "path": request.url.path}
            )
        if isinstance(entry, Exception):
            raise entry
        if callable(entry):
            return entry(request)
        return entry

    @property
    def call_count(self) -> int:
        return len(self.calls)


def _connector(router: _Router, allow=(ALLOWED,), **kwargs) -> HttpConnector:
    return HttpConnector(
        allow_origins=allow,
        transport=httpx.MockTransport(router),
        **kwargs,
    )


def _call(connector, tool, params, *, allow_mutating=True, identity=None):
    """Register into a fresh registry and invoke one tool."""
    registry = ToolRegistry(allow_mutating=allow_mutating)
    connector.register_tools(registry)
    return _run(registry.invoke(tool, params, identity or {}))


@contextlib.contextmanager
def _env(overrides: dict):
    """Patch os.environ to ``overrides`` plus every non-GATEWAY_ var."""
    base = {k: v for k, v in os.environ.items() if not k.startswith("GATEWAY_")}
    base.update(overrides)
    with patch.dict(os.environ, base, clear=True):
        yield


def _write_credentials(path: Path, mapping: dict) -> None:
    path.write_text(json.dumps(mapping), encoding="utf-8")


# --- Registration and risk tier (R-3, R-7) ---


class RegistrationTests(unittest.TestCase):
    def test_registers_both_tools_when_mutating_allowed(self) -> None:
        registry = ToolRegistry(allow_mutating=True)
        HttpConnector().register_tools(registry)
        self.assertEqual(
            {d.name for d in registry.list_definitions()},
            {"http.get", "http.post"},
        )

    def test_post_absent_when_mutating_disabled(self) -> None:
        """The registry's risk-tier admission is the only gate on http.post."""
        router = _Router({("POST", "/lock"): lambda r: httpx.Response(200, json={})})
        connector = _connector(router)
        registry = ToolRegistry(allow_mutating=False)
        connector.register_tools(registry)
        names = {d.name for d in registry.list_definitions()}
        self.assertEqual(names, {"http.get"})
        # Invoking the unregistered write tool is a structured TOOL_NOT_FOUND.
        result = _run(registry.invoke("http.post", {"url": ALLOWED + "/lock"}, {}))
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "TOOL_NOT_FOUND")
        self.assertEqual(router.call_count, 0)

    def test_risk_levels_and_category(self) -> None:
        registry = ToolRegistry(allow_mutating=True)
        HttpConnector().register_tools(registry)
        tiers = {d.name: d.risk_level for d in registry.list_definitions()}
        self.assertEqual(tiers["http.get"], "read")
        self.assertEqual(tiers["http.post"], "write")
        for defn in registry.list_definitions():
            self.assertEqual(defn.category, "http")

    def test_neither_schema_exposes_a_headers_property(self) -> None:
        """R-4: no ``headers`` parameter, so a secret can never be a literal."""
        registry = ToolRegistry(allow_mutating=True)
        HttpConnector().register_tools(registry)
        for defn in registry.list_definitions():
            props = defn.parameters_schema.get("properties", {})
            self.assertNotIn("headers", props, defn.name)


# --- Destination validation and redirects (R-2) ---


class DestinationValidationTests(unittest.TestCase):
    def test_empty_allowlist_denies_and_transport_uncalled(self) -> None:
        router = _Router({("GET", "/x"): lambda r: httpx.Response(200, json={})})
        connector = _connector(router, allow=())
        result = _call(connector, "http.get", {"url": ALLOWED + "/x"})
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error["code"], "HTTP_ORIGIN_NOT_ALLOWED")
        self.assertEqual(router.call_count, 0)

    def test_non_http_scheme_refused(self) -> None:
        router = _Router({})
        connector = _connector(router)
        for url in ("file:///etc/passwd", "ftp://acme-admin/x"):
            result = _call(connector, "http.get", {"url": url})
            self.assertEqual(result.status, "error", url)
            self.assertEqual(
                result.error["code"], "HTTP_SCHEME_NOT_ALLOWED", url
            )
        self.assertEqual(router.call_count, 0)

    def test_missing_url_is_invalid_parameters(self) -> None:
        connector = _connector(_Router({}))
        result = _call(connector, "http.get", {})
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "INVALID_PARAMETERS")

    def test_userinfo_refused(self) -> None:
        router = _Router({})
        # Allowlist the origin so the userinfo check is what fires, not the
        # allowlist.
        connector = _connector(router, allow=("http://user:pass@acme-admin:8080",))
        result = _call(
            connector, "http.get", {"url": "http://user:pass@acme-admin:8080/x"}
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "INVALID_PARAMETERS")
        self.assertIn("credential_set", result.error["message"])
        self.assertEqual(router.call_count, 0)

    def test_link_local_metadata_refused_regardless_of_allowlist(self) -> None:
        router = _Router({})
        connector = _connector(router, allow=("http://169.254.169.254",))
        result = _call(
            connector, "http.get",
            {"url": "http://169.254.169.254/latest/meta-data/"},
        )
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error["code"], "HTTP_ORIGIN_NOT_ALLOWED")
        self.assertEqual(router.call_count, 0)

    def test_loopback_refused_regardless_of_allowlist(self) -> None:
        router = _Router({})
        connector = _connector(router, allow=("http://127.0.0.1:8080",))
        result = _call(
            connector, "http.get", {"url": "http://127.0.0.1:8080/admin"}
        )
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error["code"], "HTTP_ORIGIN_NOT_ALLOWED")
        self.assertEqual(router.call_count, 0)

    def test_multicast_refused(self) -> None:
        router = _Router({})
        connector = _connector(router, allow=("http://224.0.0.1",))
        result = _call(connector, "http.get", {"url": "http://224.0.0.1/x"})
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error["code"], "HTTP_ORIGIN_NOT_ALLOWED")
        self.assertEqual(router.call_count, 0)

    def test_port_is_significant(self) -> None:
        router = _Router({("GET", "/x"): lambda r: httpx.Response(200, json={})})
        connector = _connector(router, allow=(ALLOWED,))
        result = _call(connector, "http.get", {"url": OTHER + "/x"})
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error["code"], "HTTP_ORIGIN_NOT_ALLOWED")
        self.assertEqual(router.call_count, 0)


class RedirectTests(unittest.TestCase):
    def test_three_hop_in_allowlist_chain_succeeds(self) -> None:
        router = _Router({
            ("GET", "/hop1"): lambda r: httpx.Response(302, headers={"location": "/hop2"}),
            ("GET", "/hop2"): lambda r: httpx.Response(302, headers={"location": "/hop3"}),
            ("GET", "/hop3"): lambda r: httpx.Response(302, headers={"location": "/final"}),
            ("GET", "/final"): lambda r: httpx.Response(200, json={"ok": True}),
        })
        connector = _connector(router)
        result = _call(connector, "http.get", {"url": ALLOWED + "/hop1"})
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["status"], 200)
        self.assertEqual(result.data["url"], ALLOWED + "/final")
        self.assertEqual(router.call_count, 4)

    def test_hop_leaving_allowlist_halts_and_names_origin(self) -> None:
        router = _Router({
            ("GET", "/start"): lambda r: httpx.Response(
                302, headers={"location": OTHER + "/evil"}
            ),
        })
        connector = _connector(router)
        result = _call(connector, "http.get", {"url": ALLOWED + "/start"})
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error["code"], "HTTP_REDIRECT_NOT_ALLOWED")
        self.assertIn(OTHER, result.error["message"])
        # Only the first hop was requested; the off-allowlist target never was.
        self.assertEqual(router.call_count, 1)

    def test_too_many_redirects_halts(self) -> None:
        router = _Router({
            ("GET", f"/r{i}"): (lambda i: (lambda r: httpx.Response(
                302, headers={"location": f"/r{i + 1}"})))(i)
            for i in range(1, 6)
        })
        connector = _connector(router)
        result = _call(connector, "http.get", {"url": ALLOWED + "/r1"})
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "HTTP_REDIRECT_NOT_ALLOWED")
        self.assertIn("Too many redirects", result.error["message"])
        # Limit is 3 hops: r1..r4 requested, r5 validated but never fetched.
        self.assertEqual(router.call_count, 4)

    def test_post_never_follows_a_redirect(self) -> None:
        # An approved write must execute at the URL the approver was shown.
        # The per-hop allowlist re-check bounds a hop's origin but not its
        # path, so following a 302 would let the mutation land somewhere the
        # card never named. Exactly one request: the redirect is refused,
        # not followed, and /moved is never touched.
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                router = _Router({
                    ("POST", "/lock"): lambda r: httpx.Response(
                        status, headers={"location": "/moved"}
                    ),
                    ("POST", "/moved"): lambda r: httpx.Response(
                        200, json={"locked": True}
                    ),
                })
                connector = _connector(router)
                result = _call(
                    connector, "http.post",
                    {"url": ALLOWED + "/lock", "body": {"locked": True}},
                )
                self.assertEqual(result.status, "error")
                self.assertEqual(result.error["code"], "HTTP_REDIRECT_NOT_ALLOWED")
                self.assertIn("does not follow redirects", result.error["message"])
                self.assertEqual(router.call_count, 1)


# --- http.get projection and error ladder (R-1) ---


class HttpGetTests(unittest.TestCase):
    def test_json_endpoint_projects_status_headers_and_parsed_body(self) -> None:
        router = _Router({
            ("GET", "/health"): lambda r: httpx.Response(
                200, json={"status": "ok", "count": 3}
            ),
        })
        connector = _connector(router)
        result = _call(connector, "http.get", {"url": ALLOWED + "/health"})
        self.assertEqual(result.status, "success")
        data = result.data
        self.assertEqual(data["status"], 200)
        self.assertEqual(data["content_type"], "application/json")
        self.assertEqual(data["body"], {"status": "ok", "count": 3})
        self.assertFalse(data["truncated"])
        self.assertIsInstance(data["elapsed_ms"], int)
        self.assertGreaterEqual(data["elapsed_ms"], 0)
        self.assertEqual(result.evidence["source_system"], "http")
        self.assertEqual(result.evidence["risk_level"], "read")

    def test_text_body_decoded(self) -> None:
        router = _Router({
            ("GET", "/t"): lambda r: httpx.Response(200, text="hello world"),
        })
        connector = _connector(router)
        result = _call(connector, "http.get", {"url": ALLOWED + "/t"})
        self.assertEqual(result.data["content_type"], "text/plain")
        self.assertEqual(result.data["body"], "hello world")

    def test_binary_body_omitted_but_content_type_reported(self) -> None:
        router = _Router({
            ("GET", "/img"): lambda r: httpx.Response(
                200, content=b"\x89PNG\r\n", headers={"content-type": "image/png"}
            ),
        })
        connector = _connector(router)
        result = _call(connector, "http.get", {"url": ALLOWED + "/img"})
        self.assertEqual(result.status, "success")
        self.assertNotIn("body", result.data)
        self.assertEqual(result.data["content_type"], "image/png")
        self.assertEqual(result.data["content_length"], 6)

    def test_body_over_max_bytes_is_cut_and_flagged(self) -> None:
        router = _Router({
            ("GET", "/big"): lambda r: httpx.Response(200, text="x" * 100),
        })
        connector = _connector(router)
        result = _call(
            connector, "http.get", {"url": ALLOWED + "/big", "max_bytes": 10}
        )
        self.assertEqual(result.data["content_length"], 100)
        self.assertTrue(result.data["truncated"])
        self.assertEqual(len(result.data["body"]), 10)

    def test_truncated_json_reports_text_not_a_parse(self) -> None:
        """A cut JSON document is not parseable; report the text honestly."""
        payload = json.dumps({"k": "v" * 60}).encode()
        router = _Router({
            ("GET", "/j"): lambda r: httpx.Response(
                200, content=payload, headers={"content-type": "application/json"}
            ),
        })
        connector = _connector(router)
        result = _call(
            connector, "http.get", {"url": ALLOWED + "/j", "max_bytes": 8}
        )
        self.assertTrue(result.data["truncated"])
        self.assertIsInstance(result.data["body"], str)

    def test_response_headers_are_filtered_to_the_allowlist(self) -> None:
        router = _Router({
            ("GET", "/h"): lambda r: httpx.Response(
                200,
                content=b'{"ok": true}',
                headers=[
                    ("content-type", "application/json"),
                    ("server", "acme"),
                    ("set-cookie", "sid=super-secret"),
                    ("authorization", "Basic Zm9vOmJhcg=="),
                    ("x-custom-trace", "abc"),
                ],
            ),
        })
        connector = _connector(router)
        result = _call(connector, "http.get", {"url": ALLOWED + "/h"})
        headers = result.data["headers"]
        self.assertIn("content-type", headers)
        self.assertIn("server", headers)
        self.assertNotIn("set-cookie", headers)
        self.assertNotIn("authorization", headers)
        self.assertNotIn("x-custom-trace", headers)
        self.assertTrue(set(headers) <= _PROJECTED_HEADERS)
        # The suppressed cookie value must not leak anywhere in the envelope.
        self.assertNotIn("super-secret", json.dumps(result.to_dict()))

    def test_projected_header_allowlist_excludes_credentials(self) -> None:
        """Mutation spot-check pin: adding set-cookie/authorization breaks it."""
        self.assertNotIn("set-cookie", _PROJECTED_HEADERS)
        self.assertNotIn("authorization", _PROJECTED_HEADERS)

    def test_upstream_503_is_success_carrying_the_status(self) -> None:
        router = _Router({
            ("GET", "/down"): lambda r: httpx.Response(503, json={"error": "unavailable"}),
        })
        connector = _connector(router)
        result = _call(connector, "http.get", {"url": ALLOWED + "/down"})
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["status"], 503)

    def test_timeout_maps_to_http_timeout(self) -> None:
        router = _Router({("GET", "/slow"): httpx.ConnectTimeout("timed out")})
        connector = _connector(router)
        result = _call(connector, "http.get", {"url": ALLOWED + "/slow"})
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "HTTP_TIMEOUT")

    def test_connect_error_maps_to_tool_execution_error(self) -> None:
        router = _Router({("GET", "/refused"): httpx.ConnectError("refused")})
        connector = _connector(router)
        result = _call(connector, "http.get", {"url": ALLOWED + "/refused"})
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "TOOL_EXECUTION_ERROR")

    def test_get_masks_a_secret_query_param_in_the_reported_url(self) -> None:
        """GET tolerates a secret query (read-only) but masks it in evidence."""
        router = _Router({
            ("GET", "/reset"): lambda r: httpx.Response(200, json={"ok": True}),
        })
        connector = _connector(router)
        result = _call(
            connector, "http.get", {"url": ALLOWED + "/reset?newpw=hunter2"}
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["url"], ALLOWED + "/reset?newpw=***")
        self.assertNotIn("hunter2", json.dumps(result.to_dict()))

    def test_location_header_secret_query_is_masked_like_the_url(self) -> None:
        """`location` is the one projected header that is itself a URL.

        A terminal response may carry it (a 201 Created, a 300 Multiple
        Choices); a login bounce that puts a ticket in its query must not
        reach the result, the evidence frame or the durable record in
        plaintext while `url` is masked. Non-secret params survive verbatim.
        """
        router = _Router({
            ("GET", "/bounce"): lambda r: httpx.Response(
                201,
                headers={"location": ALLOWED + "/admin/?token=s3cret&next=users"},
                json={"created": True},
            ),
        })
        connector = _connector(router)
        result = _call(connector, "http.get", {"url": ALLOWED + "/bounce"})
        self.assertEqual(result.status, "success")
        location = result.data["headers"]["location"]
        self.assertIn("token=***", location)
        self.assertIn("next=users", location)
        self.assertNotIn("s3cret", json.dumps(result.to_dict()))

    def test_json_body_token_is_redacted_by_the_gateway_choke_point(self) -> None:
        """R-1 cross-layer: the connector projects the body; gateway_service's
        ``redact_result`` masks the ``token`` key before release."""
        router = _Router({
            ("GET", "/cfg"): lambda r: httpx.Response(
                200, json={"token": "abc123", "status": "ok"}
            ),
        })
        connector = _connector(router)
        result = _call(connector, "http.get", {"url": ALLOWED + "/cfg"})
        self.assertEqual(result.data["body"]["token"], "abc123")
        redacted, stats = redact_result(result)
        self.assertEqual(redacted.data["body"]["token"], REDACTION_MARKER)
        self.assertEqual(redacted.data["body"]["status"], "ok")
        self.assertGreaterEqual(stats.spans, 1)


# --- http.post bounds and mutation semantics (R-3) ---


class HttpPostTests(unittest.TestCase):
    def test_2xx_sets_mutation_confirmed_and_forwards_body(self) -> None:
        router = _Router({
            ("POST", "/lock"): lambda r: httpx.Response(200, json={"locked": True}),
        })
        connector = _connector(router)
        result = _call(
            connector, "http.post",
            {"url": ALLOWED + "/lock", "body": {"locked": True}},
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["status"], 200)
        self.assertTrue(result.data["mutation_confirmed"])
        self.assertEqual(result.evidence["risk_level"], "write")
        self.assertEqual(json.loads(router.calls[0].content), {"locked": True})

    def test_409_is_success_with_mutation_confirmed_false(self) -> None:
        router = _Router({
            ("POST", "/lock"): lambda r: httpx.Response(409, json={"error": "conflict"}),
        })
        connector = _connector(router)
        result = _call(
            connector, "http.post",
            {"url": ALLOWED + "/lock", "body": {"locked": True}},
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["status"], 409)
        self.assertFalse(result.data["mutation_confirmed"])

    def test_body_depth_over_two_refused_transport_uncalled(self) -> None:
        router = _Router({("POST", "/x"): lambda r: httpx.Response(200, json={})})
        connector = _connector(router)
        deep = {"a": {"b": {"c": 1}}}
        self.assertEqual(_json_depth(deep), _MAX_BODY_DEPTH + 1)
        result = _call(
            connector, "http.post", {"url": ALLOWED + "/x", "body": deep}
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "INVALID_PARAMETERS")
        self.assertEqual(router.call_count, 0)

    def test_body_over_key_cap_refused_transport_uncalled(self) -> None:
        router = _Router({("POST", "/x"): lambda r: httpx.Response(200, json={})})
        connector = _connector(router)
        wide = {f"k{i}": i for i in range(_MAX_BODY_KEYS + 1)}
        self.assertEqual(_count_keys(wide), _MAX_BODY_KEYS + 1)
        result = _call(
            connector, "http.post", {"url": ALLOWED + "/x", "body": wide}
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "INVALID_PARAMETERS")
        self.assertEqual(router.call_count, 0)

    def test_body_over_request_cap_refused_transport_uncalled(self) -> None:
        router = _Router({("POST", "/x"): lambda r: httpx.Response(200, json={})})
        connector = _connector(router, max_request_bytes=16)
        result = _call(
            connector, "http.post",
            {"url": ALLOWED + "/x", "body": {"data": "x" * 50}},
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "HTTP_BODY_TOO_LARGE")
        self.assertEqual(router.call_count, 0)

    def test_non_dict_body_refused(self) -> None:
        router = _Router({("POST", "/x"): lambda r: httpx.Response(200, json={})})
        connector = _connector(router)
        result = _call(
            connector, "http.post", {"url": ALLOWED + "/x", "body": "not-an-object"}
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "INVALID_PARAMETERS")
        self.assertEqual(router.call_count, 0)

    def test_post_url_secret_query_refused_while_get_tolerates_it(self) -> None:
        router = _Router({
            ("POST", "/reset"): lambda r: httpx.Response(200, json={"ok": True}),
            ("GET", "/reset"): lambda r: httpx.Response(200, json={"ok": True}),
        })
        connector = _connector(router)
        url = ALLOWED + "/reset?newpw=hunter2"
        post = _call(connector, "http.post", {"url": url, "body": {"a": 1}})
        self.assertEqual(post.status, "error")
        self.assertEqual(post.error["code"], "HTTP_URL_SECRET_NOT_ALLOWED")
        get = _call(connector, "http.get", {"url": url})
        self.assertEqual(get.status, "success")
        self.assertEqual(get.data["url"], ALLOWED + "/reset?newpw=***")


# --- Credentials by reference only (R-4) ---


class CredentialTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = __import__("tempfile").TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cred_path = Path(self._tmp.name) / "creds.json"

    def _auth_header(self, request: httpx.Request) -> str | None:
        return request.headers.get("authorization")

    def test_basic_auth_applied_and_value_absent_from_result(self) -> None:
        _write_credentials(
            self.cred_path, {"acme": {"username": "svc", "password": "s3cret"}}
        )
        router = _Router({
            ("GET", "/health"): lambda r: httpx.Response(200, json={"ok": True}),
        })
        connector = _connector(
            router, credential_sets_path=str(self.cred_path)
        )
        result = _call(
            connector, "http.get",
            {"url": ALLOWED + "/health", "credential_set": "acme"},
        )
        self.assertEqual(result.status, "success")
        header = self._auth_header(router.calls[0])
        self.assertIsNotNone(header)
        self.assertTrue(header.startswith("Basic "))
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode()
        self.assertEqual(decoded, "svc:s3cret")
        # The resolved secret never rides the result or evidence.
        self.assertNotIn("s3cret", json.dumps(result.to_dict()))

    def test_no_credential_set_sends_no_auth_header(self) -> None:
        router = _Router({
            ("GET", "/health"): lambda r: httpx.Response(200, json={"ok": True}),
        })
        connector = _connector(router)
        result = _call(connector, "http.get", {"url": ALLOWED + "/health"})
        self.assertEqual(result.status, "success")
        self.assertIsNone(self._auth_header(router.calls[0]))

    def test_secret_value_never_reaches_a_log_record(self) -> None:
        _write_credentials(
            self.cred_path, {"acme": {"username": "svc", "password": "s3cret"}}
        )
        router = _Router({("GET", "/down"): httpx.ConnectError("refused")})
        connector = _connector(
            router, credential_sets_path=str(self.cred_path)
        )
        with self.assertLogs(
            "tool_gateway.tools.http_connector", level="WARNING"
        ) as captured:
            result = _call(
                connector, "http.get",
                {"url": ALLOWED + "/down", "credential_set": "acme"},
            )
        self.assertEqual(result.error["code"], "TOOL_EXECUTION_ERROR")
        self.assertNotIn("s3cret", "\n".join(captured.output))

    def test_unknown_credential_set_names_the_set(self) -> None:
        _write_credentials(
            self.cred_path, {"acme": {"username": "svc", "password": "s3cret"}}
        )
        router = _Router({("GET", "/health"): lambda r: httpx.Response(200, json={})})
        connector = _connector(
            router, credential_sets_path=str(self.cred_path)
        )
        result = _call(
            connector, "http.get",
            {"url": ALLOWED + "/health", "credential_set": "ghost"},
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "CREDENTIAL_SET_NOT_FOUND")
        self.assertIn("ghost", result.error["message"])
        self.assertEqual(router.call_count, 0)

    def test_unconfigured_store_has_a_distinct_message(self) -> None:
        router = _Router({("GET", "/health"): lambda r: httpx.Response(200, json={})})
        connector = _connector(router, credential_sets_path="")
        result = _call(
            connector, "http.get",
            {"url": ALLOWED + "/health", "credential_set": "acme"},
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "CREDENTIAL_SET_NOT_FOUND")
        self.assertIn("No credential-set store", result.error["message"])
        self.assertEqual(router.call_count, 0)

    def test_rotating_the_file_changes_the_value_without_a_restart(self) -> None:
        _write_credentials(
            self.cred_path, {"acme": {"username": "svc", "password": "first"}}
        )
        router = _Router({
            ("GET", "/health"): lambda r: httpx.Response(200, json={"ok": True}),
        })
        connector = _connector(
            router, credential_sets_path=str(self.cred_path)
        )
        registry = ToolRegistry(allow_mutating=True)
        connector.register_tools(registry)
        _run(registry.invoke(
            "http.get",
            {"url": ALLOWED + "/health", "credential_set": "acme"},
            {},
        ))
        first = self._auth_header(router.calls[0])
        # Rotate and bump mtime so the store's reload is deterministic.
        _write_credentials(
            self.cred_path, {"acme": {"username": "svc", "password": "second"}}
        )
        stat = os.stat(self.cred_path)
        os.utime(self.cred_path, (stat.st_atime + 10, stat.st_mtime + 10))
        _run(registry.invoke(
            "http.get",
            {"url": ALLOWED + "/health", "credential_set": "acme"},
            {},
        ))
        second = self._auth_header(router.calls[1])
        self.assertNotEqual(first, second)
        self.assertEqual(
            base64.b64decode(second.split(" ", 1)[1]).decode(), "svc:second"
        )

    # --- SPEC-068 R-3: bearer + oauth2 resolve to an Authorization header ---

    def test_bearer_set_sends_bearer_header(self) -> None:
        _write_credentials(
            self.cred_path, {"snow": {"scheme": "bearer", "token": "static-tok"}}
        )
        router = _Router({
            ("GET", "/health"): lambda r: httpx.Response(200, json={"ok": True}),
        })
        connector = _connector(
            router, credential_sets_path=str(self.cred_path)
        )
        result = _call(
            connector, "http.get",
            {"url": ALLOWED + "/health", "credential_set": "snow"},
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(self._auth_header(router.calls[0]), "Bearer static-tok")
        # The bearer token never rides the result or evidence.
        self.assertNotIn("static-tok", json.dumps(result.to_dict()))

    def test_oauth2_set_acquires_token_then_sends_bearer(self) -> None:
        _write_credentials(self.cred_path, {
            "snow": {
                "scheme": "oauth2_client_credentials",
                "token_url": ALLOWED + "/oauth_token.do",
                "client_id": "cid",
                "client_secret": "csec-SUPERSECRET",
            }
        })
        router = _Router({
            ("POST", "/oauth_token.do"): lambda r: httpx.Response(
                200,
                json={
                    "access_token": "TOK123",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            ),
            ("GET", "/health"): lambda r: httpx.Response(200, json={"ok": True}),
        })
        connector = _connector(
            router, credential_sets_path=str(self.cred_path)
        )
        result = _call(
            connector, "http.get",
            {"url": ALLOWED + "/health", "credential_set": "snow"},
        )
        self.assertEqual(result.status, "success")
        # One token fetch + one target call, both via the single transport.
        self.assertEqual(router.call_count, 2)
        target = next(c for c in router.calls if c.url.path == "/health")
        self.assertEqual(target.headers.get("authorization"), "Bearer TOK123")
        body = json.dumps(result.to_dict())
        self.assertNotIn("csec-SUPERSECRET", body)
        self.assertNotIn("TOK123", body)

    def test_oauth2_token_failure_is_a_gateway_error_and_target_uncalled(
        self,
    ) -> None:
        _write_credentials(self.cred_path, {
            "snow": {
                "scheme": "oauth2_client_credentials",
                "token_url": ALLOWED + "/oauth_token.do",
                "client_id": "cid",
                "client_secret": "csec-SUPERSECRET",
            }
        })
        router = _Router({
            ("POST", "/oauth_token.do"): lambda r: httpx.Response(
                401, json={"error": "invalid_client"}
            ),
            ("GET", "/health"): lambda r: httpx.Response(200, json={"ok": True}),
        })
        connector = _connector(
            router, credential_sets_path=str(self.cred_path)
        )
        result = _call(
            connector, "http.get",
            {"url": ALLOWED + "/health", "credential_set": "snow"},
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "CREDENTIAL_ACQUISITION_FAILED")
        self.assertIn("snow", result.error["message"])
        # Only the token endpoint was hit: a token failure never falls back to
        # an unauthenticated call of the target (the SPEC-058 inverse).
        self.assertEqual(router.call_count, 1)
        self.assertEqual(router.calls[0].url.path, "/oauth_token.do")
        self.assertNotIn("csec-SUPERSECRET", json.dumps(result.to_dict()))


# --- Configuration (R-7) ---


class ConfigTests(unittest.TestCase):
    def test_from_env_defaults_are_the_closed_position(self) -> None:
        with _env({}):
            settings = GatewaySettings.from_env()
        self.assertFalse(settings.http_enabled)
        self.assertEqual(settings.http_allow_origins, ())
        self.assertEqual(settings.http_timeout_ms, DEFAULT_TIMEOUT_MS)
        self.assertEqual(settings.http_max_response_bytes, 65536)
        self.assertEqual(settings.http_max_request_bytes, 4096)
        self.assertEqual(settings.http_credential_sets_path, "")

    def test_allow_origins_parses_and_strips(self) -> None:
        with _env({
            "GATEWAY_HTTP_ENABLED": "true",
            "GATEWAY_HTTP_ALLOW_ORIGINS": " http://a:1 , ,http://b:2 ",
        }):
            settings = GatewaySettings.from_env()
        self.assertTrue(settings.http_enabled)
        self.assertEqual(
            settings.http_allow_origins, ("http://a:1", "http://b:2")
        )

    def test_credential_sets_falls_back_to_the_browser_path(self) -> None:
        with _env({"GATEWAY_BROWSER_CREDENTIAL_SETS": "/run/browser.json"}):
            settings = GatewaySettings.from_env()
        self.assertEqual(
            settings.http_credential_sets_path, "/run/browser.json"
        )

    def test_http_credential_sets_wins_over_the_browser_fallback(self) -> None:
        with _env({
            "GATEWAY_BROWSER_CREDENTIAL_SETS": "/run/browser.json",
            "GATEWAY_HTTP_CREDENTIAL_SETS": "/run/http.json",
        }):
            settings = GatewaySettings.from_env()
        self.assertEqual(settings.http_credential_sets_path, "/run/http.json")


# --- Pure helper bounds (R-1/R-3) ---


class HelperTests(unittest.TestCase):
    def test_json_depth(self) -> None:
        self.assertEqual(_json_depth(1), 0)
        self.assertEqual(_json_depth({"a": 1}), 1)
        self.assertEqual(_json_depth({"a": {"b": 1}}), 2)
        self.assertEqual(_json_depth([{"a": {"b": 1}}]), 3)

    def test_count_keys_is_recursive(self) -> None:
        self.assertEqual(_count_keys({"a": {"b": 1}, "c": 2}), 3)
        self.assertEqual(_count_keys([{"a": 1}, {"b": 2}]), 2)

    def test_coerce_timeout_defaults_and_clamps(self) -> None:
        self.assertEqual(_coerce_timeout(None, DEFAULT_TIMEOUT_MS),
                         (DEFAULT_TIMEOUT_MS, None))
        self.assertEqual(_coerce_timeout(MAX_TIMEOUT_MS + 999, DEFAULT_TIMEOUT_MS),
                         (MAX_TIMEOUT_MS, None))
        _, err = _coerce_timeout("abc", DEFAULT_TIMEOUT_MS)
        self.assertIn("must be an integer", err)
        _, err = _coerce_timeout(0, DEFAULT_TIMEOUT_MS)
        self.assertIn("at least 1", err)

    def test_coerce_max_bytes_clamps_to_ceiling(self) -> None:
        self.assertEqual(_coerce_max_bytes(None, 65536), (65536, None))
        self.assertEqual(_coerce_max_bytes(999999, 65536), (65536, None))
        self.assertEqual(_coerce_max_bytes(10, 65536), (10, None))
        _, err = _coerce_max_bytes(-1, 65536)
        self.assertIn("at least 1", err)

    def test_validate_body_accepts_a_small_object(self) -> None:
        self.assertIsNone(_validate_body({"a": 1}, 4096))

    def test_validate_destination_returns_origin_on_success(self) -> None:
        origin, err = _validate_destination(
            ALLOWED + "/x", frozenset({ALLOWED})
        )
        self.assertEqual(origin, ALLOWED)
        self.assertIsNone(err)


if __name__ == "__main__":
    unittest.main()
