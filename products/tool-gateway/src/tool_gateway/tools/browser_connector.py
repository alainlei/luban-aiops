"""Browser connector: bounded web-check tool surface (SPEC-049 R-1..R-6).

Drives the pod's chromium-headless-shell sidecar over CDP through a
stateful session pool and registers a small, fixed tool surface:

  read tier   web.navigate, web.snapshot, web.screenshot,
              web.fill_credential, web.extract, web.wait_for,
              web.hover, web.scroll, web.switch_frame
  write tier  web.click, web.type, web.select, web.press_key,
              web.upload_file, web.evaluate

The per-tool ``risk_level`` beside each ``ToolDefinition`` is the authority;
this list is orientation. The write tier is the same six names as
agent-platform's ``flow_approvals.BROWSER_WRITE_TOOLS``, which is what gates
flow-unlock and what SPEC-055's graduation re-validation derives read-tier
from — so the two must not drift. A seventh write tool added here without
being added there degrades safe in both consumers, but not silently:
graduation re-validation refuses the draft because it cannot explain a
``web.*`` step outside the write set, and upstream the tool loses flow-unlock
so its writes park per-action instead of riding one gate. It can never be
auto-allowed by drifting: the allow-list branch is gated on ``is_read_only``
(the SPEC-021 R-3 invariant), which a mutating tool cannot satisfy.

Enforcement surfaces (all server-side, never model-trusted):

- Origin allowlist (R-2): navigation to an origin outside
  ``GATEWAY_BROWSER_ALLOW_ORIGINS`` is denied; redirects landing outside
  halt the page and error, and every read-tier capture re-checks the live
  origin first, so a post-load client-side redirect can't be snapshotted
  or screenshotted off-allowlist (or off the bound flow). An empty
  allowlist denies everything.
- Flow binding + deviation guard (R-4): ``web.navigate`` with a
  ``skill_id`` validates the skill's ``web_target``/``risk_class``
  declaration against skills-hub and binds the flow to the session.
  Inside a bound flow an interaction only executes on-origin, under a
  ``write`` ``risk_class`` if it is write-tier, and within the step budget —
  anything else is denied, never run silently. Since SPEC-054 R-2 an
  *unbound* interaction is not a hard deny either: it re-checks the live
  origin and the signed envelope's authority provenance
  (``_gate_unbound_interaction``), so an ad-hoc write executes once its
  per-action card was approved. Write-tier interactions ride the SPEC-020
  confirmation bridge and SPEC-037 signed execution upstream of the gateway
  either way; read-tier ones are auto-allowed with no operator decision.
  That includes ``web.fill_credential``, which nonetheless shares the write
  tier's step accounting — so ``flow.approved`` is neither set by every
  write-tier tool (``web.evaluate`` rides ``gate_capture`` and accounts
  nothing) nor evidence of a decision for every tool that sets it. No guard
  reads the flag; see ``FlowState`` for the two sets and why that is safe.
- Credential sets (R-5): login values resolve from a secret-mounted file
  at fill time; they never appear in results, snapshots, or logs.

Identity note: sessions key on the caller's chat session id (SPEC-049
R-1) so one stateful browser context spans a whole web-check flow —
including the owner→approver identity switch the SPEC-020/037 write path
introduces, where the resumed write-tier interaction legitimately arrives
under the approver's subject. The chat session id is a correlation handle
forwarded by trusted internal callers (the kernel and the execution
worker), never a model-supplied parameter; authority still rides the
verified bearer token. When no chat session id is present (a non-chat
caller) the connector falls back to the verified subject.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from urllib.parse import urlparse

import httpx

from tool_gateway.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolResult,
    build_evidence,
    make_error_result,
)
from tool_gateway.tools.browser_sessions import (
    BrowserNotReady,
    BrowserSessionEntry,
    BrowserSessionPool,
    FlowState,
)
from tool_gateway.tools.credential_sets import CredentialSetStore
from tool_gateway.tools.registry import ToolRegistry
from tool_gateway.tools.url_redaction import redact_secret_query

LOGGER = logging.getLogger(__name__)

SOURCE_SYSTEM = "browser"
CATEGORY = "browser"

NAVIGATION_TIMEOUT_MS = 30_000
REQUEST_TIMEOUT_SECONDS = 10.0
MAX_SNAPSHOT_ELEMENTS = 200
SNAPSHOT_MAX_CHARS = 16_000
SCREENSHOT_QUALITIES = (70, 55, 40, 25, 15)
SCREENSHOT_CLIP_FRACTIONS = (0.75, 0.5, 0.35, 0.25)
SKILL_PATH_TEMPLATE = "/api/v1/skills/{skill_id}"
# Same contract pattern as the skills connector: the id is interpolated
# into the upstream URL path, so anything else is untrusted input.
_SKILL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*(/[a-z0-9][a-z0-9-]*)+$")
# Interactive elements addressable by snapshot refs.
INTERACTIVE_SELECTOR = (
    "a, button, input, select, textarea, "
    "[role=button], [role=link], [role=tab], [role=checkbox], [onclick]"
)
_ELEMENT_INSPECT_JS = """
el => ({
    tag: el.tagName.toLowerCase(),
    type: el.getAttribute("type") || "",
    role: el.getAttribute("role") || "",
    name: ((el.getAttribute("aria-label") || el.getAttribute("name")
        || el.getAttribute("placeholder") || "")).slice(0, 120),
    text: ((el.innerText || "")).trim().slice(0, 120),
    value: (typeof el.value === "string") ? el.value : "",
    disabled: Boolean(el.disabled),
})
"""
CREDENTIAL_FIELDS = ("username", "password")
# Password-tier values are masked out of screenshots (R-5): a legacy target
# may render a password into a ``type=text`` field a raw capture would leak
# into evidence. A fixed-length dot mask avoids revealing the value's length;
# a filled username is never masked here (it is the visible sign-in evidence).
_SCREENSHOT_MASK_JS = """
(vals) => {
    let n = 0;
    document.querySelectorAll("input,textarea").forEach(el => {
        if (typeof el.value === "string" && vals.includes(el.value)) {
            el.setAttribute("data-cv-mask", el.value);
            el.value = "••••••••";
            n += 1;
        }
    });
    return n;
}
"""
_SCREENSHOT_UNMASK_JS = """
() => {
    document.querySelectorAll("[data-cv-mask]").forEach(el => {
        el.value = el.getAttribute("data-cv-mask");
        el.removeAttribute("data-cv-mask");
    });
}
"""


def _path_under(url_path: str, target_path: str) -> bool:
    """True when ``url_path`` equals ``target_path`` or sits under it as
    whole path segments — a declared ``/login`` admits ``/login`` and
    ``/login/sso`` but not ``/loginfoo``. A trailing slash on the declared
    target is insignificant (``/login/`` still admits ``/login``), and a
    root target (``/``) admits every path on the origin."""
    target = target_path.rstrip("/")
    if not target:  # a root target ("/") admits every path on the origin
        return True
    return url_path == target or url_path.startswith(target + "/")


def origin_of(url: str) -> str | None:
    """Return the normalized ``scheme://host[:port]`` origin, or None."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".lower()


def _evidence_url(entry: BrowserSessionEntry) -> str:
    """The URL to report for a result: the live frame's, secret values masked.

    Every browser result reports ``entry.active_target.url`` — the frame the
    call actually landed on, not the top-level page, so evidence matches a
    frame-switched session (SPEC-050 R-9). That URL is also where a secret
    lands when a target carries one in its query string (the password-reset
    demo's ``?newpw=...``), and the reported value is persisted into results,
    evidence frames, and the audit trail, so it goes through
    ``redact_secret_query`` first (SPEC-049 R-5).

    Masking here is what makes the navigate-only redaction hold: navigating to
    a secret-bearing URL is followed by snapshots, clicks, and screenshots on
    that same URL, and each of those results re-serializes it. The page keeps
    the real value — only the reported copy is masked.
    """
    return redact_secret_query(entry.active_target.url)


def _denied(tool_name: str, code: str, message: str, risk_level: str) -> ToolResult:
    """Denial envelope with a connector-specific code (R-2/R-4)."""
    return ToolResult(
        tool_name=tool_name,
        status="denied",
        evidence=build_evidence(risk_level, SOURCE_SYSTEM, 0),
        error={"code": code, "message": message},
    )


class _SessionSerializedTool(BaseTool):
    """Runs one browser tool at a time per chat session.

    A model may emit several ``web.*`` calls in a single turn and the
    kernel dispatches them concurrently, but one chat session owns exactly
    one browser context and one active page. Playwright interactions are
    not mutually isolated on a shared page: ``fill()`` focuses its element
    and then inserts text into whatever holds focus at that moment, so two
    concurrent ``web.fill_credential`` calls can both land in the same
    field — the loser reports ``success`` with its value silently absent.
    The same shared state covers ``refs``/``frame_stack`` (a snapshot or
    navigation invalidates refs another in-flight call is about to use) and
    ``flow.steps_used`` (concurrent increments lose budget accounting).

    So each call takes the session key's ``interaction_lock`` for its whole
    duration. The lock is applied here, at the registration boundary, rather
    than at the fifteen call sites: a tool added later inherits the guarantee
    instead of having to remember to opt in.

    The lock is looked up by key rather than by resolving a session, and no
    failure is intercepted here: a call with no identity, an unreachable
    sidecar, or an off-allowlist URL reaches the wrapped tool untouched and
    still produces its own ``BROWSER_NO_IDENTITY`` / ``BROWSER_NOT_READY`` /
    ``BROWSER_ORIGIN_NOT_ALLOWED`` envelope — so the error surface is
    unchanged and a refused call still creates no browser context.
    """

    def __init__(self, inner: BaseTool, connector: BrowserConnector) -> None:
        self._inner = inner
        self._connector = connector

    @property
    def definition(self) -> ToolDefinition:
        return self._inner.definition

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        session_key = self._connector._session_key(identity)
        if not session_key:
            return await self._inner.execute(parameters, identity)
        # No await between the lookup and the acquire: the pool prunes locks
        # that are neither held nor backed by a session, and an unheld lock
        # observed in between would let a second caller take a fresh one.
        async with self._connector.pool.interaction_lock(session_key):
            return await self._inner.execute(parameters, identity)


class BrowserConnector:
    """Registers the bounded web.* tool surface behind the browser flag."""

    def __init__(
        self,
        cdp_endpoint: str,
        allow_origins: tuple[str, ...] = (),
        session_ttl_seconds: int = 600,
        max_sessions: int = 4,
        flow_max_steps: int = 20,
        credential_sets_path: str = "",
        screenshot_max_bytes: int = 65536,
        skills_service_url: str = "",
        skills_client_id: str = "",
        skills_client_secret: str = "",
        playwright_factory=None,
        upload_dir: str = "/tmp/browser-uploads",
    ) -> None:
        # Origins compare normalized and lowercase; patterns in config are
        # trusted operator input but normalized defensively.
        self._allow_origins = frozenset(
            origin.strip().lower() for origin in allow_origins if origin.strip()
        )
        self._flow_max_steps = flow_max_steps
        self._screenshot_max_bytes = screenshot_max_bytes
        self._upload_dir = upload_dir
        self._skills_url = skills_service_url
        self._skills_client_id = skills_client_id
        self._skills_client_secret = skills_client_secret
        self.pool = BrowserSessionPool(
            cdp_endpoint=cdp_endpoint,
            ttl_seconds=session_ttl_seconds,
            max_sessions=max_sessions,
            playwright_factory=playwright_factory,
        )
        self.credentials = CredentialSetStore(credential_sets_path)

    # --- Lifecycle (wired to app startup/shutdown when the flag is on) ---

    async def start(self) -> bool:
        return await self.pool.start()

    async def stop(self) -> None:
        await self.pool.stop()

    def register_tools(self, registry: ToolRegistry) -> None:
        """Register all web.* tools with the given registry.

        The write-tier interaction tools are offered unconditionally; the
        registry's risk-tier admission (SPEC-021 R-1) refuses them when
        GATEWAY_MUTATING_TOOLS_ENABLED is off, exactly like k8s.delete_pod.
        SPEC-050 adds nine more tools (web.select, web.press_key,
        web.upload_file, web.evaluate as write; web.extract, web.wait_for,
        web.hover, web.scroll, web.switch_frame as read).

        Each one is registered behind ``_SessionSerializedTool``, so a chat
        session's single page is driven by one call at a time even when the
        model emits several in one turn.
        """
        tools: list[BaseTool] = [
            # Original six (SPEC-049).
            WebNavigateTool(self),
            WebSnapshotTool(self),
            WebScreenshotTool(self),
            WebFillCredentialTool(self),
            WebClickTool(self),
            WebTypeTool(self),
            # SPEC-050: write-tier interaction tools. web.evaluate is
            # write-tier because arbitrary JS can mutate the DOM and read
            # back masked secrets, so it inherits the HITL gate (SPEC-050
            # R-6).
            WebSelectTool(self),
            WebPressKeyTool(self),
            WebUploadFileTool(self),
            WebEvaluateTool(self),
            # SPEC-050: read-tier observation tools.
            WebExtractTool(self),
            WebWaitForTool(self),
            WebHoverTool(self),
            WebScrollTool(self),
            WebSwitchFrameTool(self),
        ]
        for tool in tools:
            registry.register(_SessionSerializedTool(tool, self))

    # --- Enforcement surfaces ---

    def is_origin_allowed(self, url: str) -> bool:
        """Deny-by-default: an empty allowlist denies every origin."""
        origin = origin_of(url)
        return origin is not None and origin in self._allow_origins

    def _session_key(self, identity: dict) -> str | None:
        """Chat session id is the pool key (SPEC-049 R-1); subject is the
        fallback for callers that forward no chat session.

        Keying on the chat session id — not the verified subject — keeps
        one browser context bound to a whole web-check flow across the
        owner→approver HITL identity switch: the read-tier setup and the
        resumed write-tier interaction share a chat session but carry
        different subjects, and the flow (and its bound skill) must
        survive that switch. The chat session id is injected by trusted
        internal callers, never taken from model-controlled parameters.
        """
        chat_session_id = identity.get("chat_session_id")
        if chat_session_id:
            return str(chat_session_id)
        subject = identity.get("sub")
        return str(subject) if subject else None

    async def _resolve_session(
        self, tool_name: str, identity: dict, risk_level: str
    ) -> tuple[BrowserSessionEntry | None, ToolResult | None]:
        """Shared front door: identity key + pool readiness + session get."""
        session_key = self._session_key(identity)
        if not session_key:
            return None, make_error_result(
                tool_name, "BROWSER_NO_IDENTITY",
                "No verified caller identity is available for a browser "
                "session.", risk_level=risk_level, source_system=SOURCE_SYSTEM,
            )
        try:
            entry = await self.pool.get_or_create(session_key)
        except BrowserNotReady as exc:
            return None, make_error_result(
                tool_name, "BROWSER_NOT_READY", str(exc),
                risk_level=risk_level, source_system=SOURCE_SYSTEM,
            )
        return entry, None

    async def fetch_skill(self, skill_id: str) -> tuple[dict | None, str, str]:
        """Fetch one skill from skills-hub for flow validation (R-4).

        Returns ``(record, error_code, error_message)``; the record is
        None on any failure and the caller surfaces the structured error.
        """
        if not self._skills_url:
            return None, "SKILLS_NOT_CONFIGURED", (
                "Flow binding needs the skills connector "
                "(GATEWAY_SKILLS_SERVICE_URL) to validate the skill "
                "declaration."
            )
        if not _SKILL_ID_PATTERN.match(skill_id):
            return None, "INVALID_PARAMETERS", (
                "Parameter 'skill_id' is not a valid namespaced skill id."
            )
        path = SKILL_PATH_TEMPLATE.format(skill_id=skill_id)
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.get(
                    f"{self._skills_url.rstrip('/')}{path}",
                    auth=(self._skills_client_id, self._skills_client_secret),
                )
        except httpx.HTTPError as exc:
            LOGGER.warning("skill lookup transport error: %s", exc)
            return None, "SKILLS_UNAVAILABLE", "skills-hub is unreachable."
        if response.status_code == 404:
            return None, "SKILL_NOT_FOUND", (
                f"Skill '{skill_id}' was not found in the skills hub."
            )
        if response.status_code != 200:
            return None, "SKILLS_UNAVAILABLE", (
                f"skills-hub returned HTTP {response.status_code}."
            )
        payload = response.json()
        return (payload if isinstance(payload, dict) else None), "", ""

    def bind_flow(
        self, entry: BrowserSessionEntry, skill_id: str, url: str, skill: dict
    ) -> ToolResult | None:
        """Validate the declaration and bind the flow; error result or None.

        The navigated URL must land on the declared ``web_target``'s
        origin and on (or under) its path; the declared ``risk_class``
        defaults to ``read`` when absent.
        """
        web_target = skill.get("web_target")
        if not web_target:
            return make_error_result(
                "web.navigate", "SKILL_NOT_WEB_FLOW",
                f"Skill '{skill_id}' does not declare a web_target and "
                "cannot bind a browser flow.",
                source_system=SOURCE_SYSTEM,
            )
        risk_class = skill.get("risk_class") or "read"
        target_origin = origin_of(str(web_target))
        url_origin = origin_of(url)
        if (
            target_origin is None
            or url_origin != target_origin
            or not _path_under(
                urlparse(url).path, urlparse(str(web_target)).path
            )
        ):
            return _denied(
                "web.navigate", "BROWSER_FLOW_TARGET_MISMATCH",
                f"URL '{url}' does not match skill '{skill_id}' declared "
                f"web_target '{web_target}'.", "read",
            )
        entry.flow = FlowState(
            skill_id=skill_id,
            origin=url_origin,
            risk_class=risk_class,
            max_steps=self._flow_max_steps,
            # SPEC-051 R-6: carry the skill's human-readable frontmatter so the
            # flow dict riding web.navigate's result can headline the kernel's
            # confirmation card with the workflow intent (e.g. "Reset a user's
            # password"), not a bare tool action like web.click.
            title=str(skill.get("title") or ""),
            description=str(skill.get("description") or ""),
            # SPEC-053 R-2: carry the author-written gated-step intent so the
            # kernel renders it as the card's lead decision line (display-only).
            flow_intent=str(skill.get("flow_intent") or ""),
            approved=(risk_class == "read"),
        )
        entry.reset_page_state()
        return None

    async def gate_interaction(
        self,
        entry: BrowserSessionEntry,
        tool_name: str,
        require_write_class: bool,
        approval_kind: str | None = None,
    ) -> ToolResult | None:
        """Deviation guard (R-4): an interaction never executes silently.

        Returns a denial result when a bound flow is denied, off-origin,
        read-only but asked for a write-tier action, or exhausted; None when
        the interaction may proceed. Write-tier calls additionally pass the
        SPEC-020/037 gate upstream before they ever reach this check.

        SPEC-054 R-2: an absent flow is no longer a hard deny. An ad-hoc
        interaction with no bound flow is gated by ``_gate_unbound_interaction``
        — a live-origin re-check plus the signed authority-provenance backstop
        (ADR-0010) — so an allowlisted ad-hoc write parks a per-action card
        upstream and executes here once approved, while a stale flow-provenance
        execution is refused. ``approval_kind`` is the provenance the execution
        worker forwarded from the signed envelope; it is untrusted input whose
        only permitted effect is a refusal, never a widening.
        """
        risk_level = "write" if require_write_class else "read"
        flow = entry.flow
        if flow is None:
            return await self._gate_unbound_interaction(
                entry, tool_name, risk_level, approval_kind
            )
        if flow.denied:
            return _denied(
                tool_name, "BROWSER_FLOW_DENIED",
                "The bound web-check flow was denied; further interactions "
                "are refused.", risk_level,
            )
        # R-4 deviation guard: the interaction must land on the origin the
        # flow was bound to (and the operator approved). A plain navigate to
        # another allowlisted origin leaves the flow bound, so re-check the
        # live origin here — an off-origin interaction is refused, never run
        # under an approval that named a different target. Uses
        # ``entry.active_target`` so a frame-switched session checks the
        # frame's origin, not the top-level page's (SPEC-050 R-9).
        current_origin = origin_of(entry.active_target.url)
        if current_origin is None or current_origin != flow.origin:
            return _denied(
                tool_name, "BROWSER_FLOW_ORIGIN_DEVIATED",
                "The current page origin does not match the bound flow's "
                f"approved origin '{flow.origin}'; the interaction is "
                "refused. Navigate back to the flow's target first.",
                risk_level,
            )
        if require_write_class and flow.risk_class != "write":
            return _denied(
                tool_name, "BROWSER_FLOW_READ_ONLY",
                f"The bound flow declares risk_class 'read'; write-tier "
                "interactions are refused.", risk_level,
            )
        if flow.steps_used >= flow.max_steps:
            return _denied(
                tool_name, "BROWSER_FLOW_EXHAUSTED",
                f"The bound flow exceeded its step budget "
                f"({flow.max_steps} steps); further interactions are "
                "refused.", risk_level,
            )
        return None

    async def _gate_unbound_interaction(
        self,
        entry: BrowserSessionEntry,
        tool_name: str,
        risk_level: str,
        approval_kind: str | None,
    ) -> ToolResult | None:
        """Substitute guards for an interaction with no bound flow (SPEC-054 R-2).

        With no flow the origin-match, ``risk_class``, and step-budget guards
        are all inapplicable, so this lifts the live-origin re-check
        ``gate_capture`` performs for the read tier into the unbound write path:
        an off-allowlist page is halted and refused, so a client-side redirect
        between ``web.navigate`` and the interaction cannot land an approved
        write on a drifted page. On an allowlisted origin the interaction
        proceeds — the kernel's per-action ASK is what gated it, and no step
        budget bounds it (per-action consent *is* the bound; SPEC-055 budgets an
        accumulated sequence at graduation) — unless the signed envelope claims
        a flow provenance that no longer exists.

        ADR-0010 staleness backstop: a ``flow``-provenance execution presented
        with no flow bound means the authority outlived the gateway's binding
        (the flow was cleared on a redirect, on a denial, or on a failed
        just-bound navigate). It is refused ``BROWSER_FLOW_AUTHORITY_STALE``
        rather than reinterpreted as a per-action approval — the explicit
        replacement for the backstop ``BROWSER_FLOW_NOT_BOUND`` accidentally
        provided. One-directional and fail-closed: an ``action`` or absent
        provenance never triggers this refusal, and the check can only ever add
        a refusal, never remove one — the guard set applied is still selected by
        the gateway's own flow binding, never by this forwarded value.
        """
        live_url = entry.active_target.url
        if not self.is_origin_allowed(live_url):
            offending = origin_of(live_url) or live_url
            try:
                await entry.page.goto("about:blank")
            except Exception:  # noqa: BLE001 - halt is best effort
                pass
            entry.reset_page_state()
            return make_error_result(
                tool_name, "BROWSER_REDIRECT_NOT_ALLOWED",
                f"The current page ('{offending}') is not on the browser "
                "origin allowlist; the page was halted and the interaction "
                "refused. Navigate to an allowed target first.",
                risk_level=risk_level, source_system=SOURCE_SYSTEM,
            )
        if approval_kind == "flow":
            return _denied(
                tool_name, "BROWSER_FLOW_AUTHORITY_STALE",
                "This execution was signed under a browser-flow authority, but "
                "no web-check flow is bound to this session any more; the "
                "approval is stale and the interaction is refused.",
                risk_level,
            )
        return None

    async def gate_capture(
        self, entry: BrowserSessionEntry, tool_name: str
    ) -> ToolResult | None:
        """Read-tier origin re-check (R-2/R-4): a snapshot/screenshot never
        captures a page that drifted off the allowlist or off the bound
        flow's origin.

        ``web.navigate`` re-checks the landing origin at goto time, but a
        post-load client-side redirect is not otherwise caught before the
        next navigate — so the read tier re-validates the live origin here,
        the mirror of the write-tier deviation guard (``gate_interaction``).
        An off-allowlist page is halted (as the navigate redirect guard
        does) and refused; an off-flow but allowlisted page is refused
        without a halt. Returns None when the capture may proceed.

        Uses ``entry.active_target`` so frame-switched reads check the
        frame's URL (SPEC-050 R-9).
        """
        live_url = entry.active_target.url
        if not self.is_origin_allowed(live_url):
            offending = origin_of(live_url) or live_url
            try:
                await entry.page.goto("about:blank")
            except Exception:  # noqa: BLE001 - halt is best effort
                pass
            entry.reset_page_state()
            entry.flow = None
            return make_error_result(
                tool_name, "BROWSER_REDIRECT_NOT_ALLOWED",
                f"The current page ('{offending}') is not on the browser "
                "origin allowlist; the page was halted and the capture "
                "refused. Navigate to an allowed target first.",
                risk_level="read", source_system=SOURCE_SYSTEM,
            )
        flow = entry.flow
        if flow is not None and origin_of(live_url) != flow.origin:
            return _denied(
                tool_name, "BROWSER_FLOW_ORIGIN_DEVIATED",
                "The current page origin does not match the bound flow's "
                f"approved origin '{flow.origin}'; the capture is refused. "
                "Navigate back to the flow's target first.",
                "read",
            )
        return None


def _invalid_ref(tool_name: str, ref: object) -> ToolResult:
    return make_error_result(
        tool_name, "BROWSER_REF_UNKNOWN",
        f"Parameter 'ref' must be a snapshot element reference (1-based "
        f"integer), got {ref!r}. Take a web.snapshot to obtain refs.",
        risk_level="write", source_system=SOURCE_SYSTEM,
    )


def _resolve_ref(
    entry: BrowserSessionEntry, tool_name: str, ref: object
) -> tuple[object | None, ToolResult | None]:
    try:
        index = int(ref)
    except (TypeError, ValueError):
        return None, _invalid_ref(tool_name, ref)
    if index < 1 or index > len(entry.refs):
        return None, make_error_result(
            tool_name, "BROWSER_REF_UNKNOWN",
            f"Snapshot ref {index} is not valid for the current page; take "
            "a fresh web.snapshot.", risk_level="write",
            source_system=SOURCE_SYSTEM,
        )
    return entry.refs[index - 1], None


# --- Tool implementations ---


class WebNavigateTool(BaseTool):
    def __init__(self, connector: BrowserConnector) -> None:
        self._connector = connector

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web.navigate",
            description=(
                "Open a URL in the session's browser and wait for load. "
                "Targets must be on the platform's origin allowlist. Pass "
                "the skill_id of a web-check skill to bind its declared "
                "flow (web_target/risk_class) to the session."
            ),
            risk_level="read",
            category=CATEGORY,
            parameters_schema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Absolute http(s) URL to open.",
                    },
                    "skill_id": {
                        "type": "string",
                        "description": (
                            "Namespaced skill id declaring this web-check "
                            "flow (web_target/risk_class frontmatter)."
                        ),
                    },
                },
            },
        )

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()
        connector = self._connector
        url = parameters.get("url")
        if not isinstance(url, str) or origin_of(url) is None:
            return make_error_result(
                "web.navigate", "INVALID_PARAMETERS",
                "Parameter 'url' must be an absolute http(s) URL.",
                source_system=SOURCE_SYSTEM,
            )
        # R-2: server-side allowlist check before any navigation.
        if not connector.is_origin_allowed(url):
            return _denied(
                "web.navigate", "BROWSER_ORIGIN_NOT_ALLOWED",
                f"Origin '{origin_of(url)}' is not on the browser origin "
                "allowlist.", "read",
            )

        entry, error = await connector._resolve_session(
            "web.navigate", identity, "read"
        )
        if error is not None:
            return error
        assert entry is not None

        # R-4: flow binding validates the skill declaration upstream of
        # any page interaction.
        skill_id = parameters.get("skill_id")
        bound_here = False
        if skill_id is not None:
            skill, code, message = await connector.fetch_skill(str(skill_id))
            if skill is None:
                return make_error_result(
                    "web.navigate", code, message, source_system=SOURCE_SYSTEM,
                )
            bind_error = connector.bind_flow(entry, str(skill_id), url, skill)
            if bind_error is not None:
                return bind_error
            bound_here = True

        try:
            await entry.page.goto(
                url, wait_until="load", timeout=NAVIGATION_TIMEOUT_MS
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            LOGGER.warning("web.navigate failed: %s", exc)
            if bound_here:
                # The flow bound on this call never reached its target; drop
                # it so a stale binding can't be interacted with (R-4). A
                # pre-existing flow is left intact — the page did not move.
                entry.flow = None
                entry.reset_page_state()
            return make_error_result(
                "web.navigate", "BROWSER_NAVIGATION_ERROR",
                # A Playwright navigation error interpolates the target URL,
                # which for the password-reset demo carries ``?newpw=<value>``
                # (and a DSN-style target could carry it in the userinfo). The
                # message rides into results, evidence and the audit trail, so
                # the secret is masked before it leaves (SPEC-049 R-5).
                redact_secret_query(str(exc)),
                source_system=SOURCE_SYSTEM, duration_ms=duration_ms,
            )
        duration_ms = int((time.perf_counter() - start) * 1000)

        # R-2: redirect coverage — the landing origin is re-checked.
        final_url = entry.page.url
        if not connector.is_origin_allowed(final_url):
            offending = origin_of(final_url) or final_url
            try:
                await entry.page.goto("about:blank")
            except Exception:  # noqa: BLE001 - halt is best effort
                pass
            entry.reset_page_state()
            entry.flow = None
            return make_error_result(
                "web.navigate", "BROWSER_REDIRECT_NOT_ALLOWED",
                f"Navigation landed outside the allowlist on origin "
                f"'{offending}'; the session page was halted.",
                source_system=SOURCE_SYSTEM, duration_ms=duration_ms,
            )

        entry.reset_page_state()
        # Redact secret-bearing query params (e.g. the demo's ``?newpw=...``)
        # so a plaintext credential never enters results/evidence/audit
        # (SPEC-049 R-5). The page still navigated with the real value; only
        # the reported URL is masked.
        data: dict = {
            "url": redact_secret_query(final_url),
            "title": await entry.page.title(),
        }
        if entry.flow is not None:
            data["flow"] = entry.flow.to_dict()
        return ToolResult(
            tool_name="web.navigate",
            status="success",
            data=data,
            evidence=build_evidence("read", SOURCE_SYSTEM, duration_ms),
        )


class WebSnapshotTool(BaseTool):
    def __init__(self, connector: BrowserConnector) -> None:
        self._connector = connector

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web.snapshot",
            description=(
                "Return a bounded text snapshot of the current page with "
                "interactive elements enumerated as refs (1-based) usable "
                "by web.click / web.type / web.fill_credential."
            ),
            risk_level="read",
            category=CATEGORY,
            parameters_schema={"type": "object", "properties": {}},
        )

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()
        connector = self._connector
        entry, error = await connector._resolve_session(
            "web.snapshot", identity, "read"
        )
        if error is not None:
            return error
        assert entry is not None
        # C-2: re-check the live origin before capturing. A post-load
        # client-side redirect could otherwise produce a snapshot of a
        # page that drifted off the allowlist or off the bound flow.
        gate = await connector.gate_capture(entry, "web.snapshot")
        if gate is not None:
            return gate
        try:
            snapshot_text, count = await _build_snapshot(entry)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            LOGGER.warning("web.snapshot failed: %s", exc)
            return make_error_result(
                "web.snapshot", "BROWSER_SNAPSHOT_ERROR", str(exc),
                source_system=SOURCE_SYSTEM, duration_ms=duration_ms,
            )
        duration_ms = int((time.perf_counter() - start) * 1000)
        return ToolResult(
            tool_name="web.snapshot",
            status="success",
            data={
                "url": _evidence_url(entry),
                "title": await entry.active_target.title(),
                "elements": count,
                "snapshot": snapshot_text,
            },
            evidence=build_evidence("read", SOURCE_SYSTEM, duration_ms),
        )


async def _build_snapshot(entry: BrowserSessionEntry) -> tuple[str, int]:
    """Enumerate interactive elements into addressable, masked refs (R-5).

    Uses ``entry.active_target`` so a frame-switched session snapshots the
    frame's interactive elements rather than the main page (SPEC-050 R-9).
    """
    target = entry.active_target
    elements = await target.query_selector_all(INTERACTIVE_SELECTOR)
    elements = elements[:MAX_SNAPSHOT_ELEMENTS]
    entry.refs = elements
    # The header URL rides into ``data["snapshot"]`` alongside ``data["url"]``,
    # so it is masked too — masking one and not the other would leave the
    # secret readable in the same result (SPEC-049 R-5).
    lines = [f"URL: {redact_secret_query(target.url)}", ""]
    for index, element in enumerate(elements, start=1):
        info = await element.evaluate(_ELEMENT_INSPECT_JS)
        if not isinstance(info, dict):
            info = {}
        label = info.get("name") or info.get("text") or ""
        bits = [str(info.get("tag", "element")).lower()]
        elem_type = str(info.get("type") or "").lower()
        if elem_type:
            bits.append(f"type={elem_type}")
        if info.get("role"):
            bits.append(f"role={info['role']}")
        line = f"[{index}] <{' '.join(bits)}>"
        if label:
            line += f' "{label}"'
        value = info.get("value") or ""
        if value:
            # R-5: filled credential values (and any password field) are
            # masked in every downstream representation.
            masked = (
                elem_type == "password" or value in entry.filled_values
            )
            line += f" value={'***' if masked else repr(value)}"
        if info.get("disabled"):
            line += " (disabled)"
        lines.append(line)
    text = "\n".join(lines)
    if len(text) > SNAPSHOT_MAX_CHARS:
        text = text[:SNAPSHOT_MAX_CHARS] + "\n[truncated]"
    return text, len(elements)


class WebScreenshotTool(BaseTool):
    def __init__(self, connector: BrowserConnector) -> None:
        self._connector = connector

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web.screenshot",
            description=(
                "Capture a bounded JPEG screenshot of the current page, "
                "returned base64-encoded beside the page title and URL."
            ),
            risk_level="read",
            category=CATEGORY,
            parameters_schema={"type": "object", "properties": {}},
        )

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()
        connector = self._connector
        entry, error = await connector._resolve_session(
            "web.screenshot", identity, "read"
        )
        if error is not None:
            return error
        assert entry is not None
        # C-2: re-check the live origin before capturing.
        gate = await connector.gate_capture(entry, "web.screenshot")
        if gate is not None:
            return gate
        try:
            raw = await _capture_screenshot(
                entry.page, connector._screenshot_max_bytes,
                frozenset(entry.secret_values),
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            LOGGER.warning("web.screenshot failed: %s", exc)
            return make_error_result(
                "web.screenshot", "BROWSER_SCREENSHOT_ERROR", str(exc),
                source_system=SOURCE_SYSTEM, duration_ms=duration_ms,
            )
        duration_ms = int((time.perf_counter() - start) * 1000)
        if raw is None:
            return make_error_result(
                "web.screenshot", "BROWSER_SCREENSHOT_TOO_LARGE",
                "The screenshot could not be compressed within the byte "
                "cap.", source_system=SOURCE_SYSTEM, duration_ms=duration_ms,
            )
        return ToolResult(
            tool_name="web.screenshot",
            status="success",
            data={
                "title": await entry.active_target.title(),
                "url": _evidence_url(entry),
                "format": "jpeg",
                "bytes": len(raw),
                "screenshot": base64.b64encode(raw).decode("ascii"),
            },
            evidence=build_evidence("read", SOURCE_SYSTEM, duration_ms),
        )


async def _capture_screenshot(
    page, max_bytes: int, secret_values: frozenset[str] = frozenset()
) -> bytes | None:
    """JPEG under the byte cap: quality loop, then shrinking clip (R-6).

    Password-tier credential values are masked out of the capture first
    (R-5). Masking is fail-closed: if the mask injection raises, the
    exception propagates and no screenshot is taken rather than risk
    leaking a plaintext password a legacy ``type=text`` field rendered.
    """
    masked = False
    if secret_values:
        masked = bool(
            await page.evaluate(_SCREENSHOT_MASK_JS, list(secret_values))
        )
    try:
        raw = b""
        for quality in SCREENSHOT_QUALITIES:
            raw = await page.screenshot(type="jpeg", quality=quality)
            if len(raw) <= max_bytes:
                return raw
        viewport = getattr(page, "viewport_size", None) or {}
        width, height = viewport.get("width", 0), viewport.get("height", 0)
        if width and height:
            for fraction in SCREENSHOT_CLIP_FRACTIONS:
                clip = {
                    "x": 0,
                    "y": 0,
                    "width": int(width * fraction),
                    "height": int(height * fraction),
                }
                raw = await page.screenshot(type="jpeg", quality=40, clip=clip)
                if len(raw) <= max_bytes:
                    return raw
        return raw if len(raw) <= max_bytes else None
    finally:
        if masked:
            try:
                await page.evaluate(_SCREENSHOT_UNMASK_JS)
            except Exception as exc:  # noqa: BLE001 - unmask is best effort
                # The secret stays masked (fail-safe) but the page keeps its
                # dot mask; log the class only (never a value) so a stuck
                # mask is visible.
                LOGGER.warning(
                    "screenshot credential unmask failed: %s",
                    exc.__class__.__name__,
                )


class _WebInteractionTool(BaseTool):
    """Shared plumbing for ref-addressed interaction tools."""

    tool_name = ""
    risk_level = "read"

    def __init__(self, connector: BrowserConnector) -> None:
        self._connector = connector

    async def _guarded_handle(
        self,
        entry: BrowserSessionEntry,
        parameters: dict,
        approval_kind: str | None = None,
    ) -> tuple[object | None, ToolResult | None]:
        """Deviation guard first, then ref resolution."""
        gate = await self._connector.gate_interaction(
            entry, self.tool_name,
            require_write_class=(self.risk_level == "write"),
            approval_kind=approval_kind,
        )
        if gate is not None:
            return None, gate
        return _resolve_ref(entry, self.tool_name, parameters.get("ref"))

    def _step_result(
        self, entry: BrowserSessionEntry, start: float, extra: dict | None = None
    ) -> ToolResult:
        duration_ms = int((time.perf_counter() - start) * 1000)
        data = {
            # Report the frame the interaction actually landed on, not the
            # top-level page, so evidence matches a frame-switched session
            # (SPEC-050 R-9), with secret query values masked (SPEC-049 R-5).
            "url": _evidence_url(entry),
        }
        flow = entry.flow
        if flow is not None:
            # Bound flow: account the step against its budget (SPEC-051).
            # Every ref-addressed interaction is accounted whatever its tier,
            # so ``web.fill_credential`` — read-tier for *approval* (D-3) but
            # still touching the page — spends budget too. That is the
            # conservative direction (a flow gets fewer writes than its budget
            # advertises, never more), and it means the credential-reference
            # steps a human adds when merging a SPEC-055 graduated draft come
            # out of the same ``GATEWAY_BROWSER_FLOW_MAX_STEPS`` the mutations
            # do. ``approved`` records the execution as evidence of a decision;
            # see ``FlowState`` for why that reading holds for the write tier
            # and is merely harmless for this one read-tier subclass.
            flow.steps_used += 1
            flow.approved = True
            data["steps_used"] = flow.steps_used
            data["steps_budget"] = flow.max_steps
        # SPEC-054 R-2: an unbound ad-hoc interaction has no flow to account
        # against — per-action consent is the bound, so no step budget applies
        # and none is reported.
        if extra:
            data.update(extra)
        return ToolResult(
            tool_name=self.tool_name,
            status="success",
            data=data,
            evidence=build_evidence(self.risk_level, SOURCE_SYSTEM, duration_ms),
        )


class WebClickTool(_WebInteractionTool):
    tool_name = "web.click"
    risk_level = "write"

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web.click",
            description=(
                "Click the element identified by a web.snapshot ref. "
                "Write tier: the click is the submitting interaction — it "
                "commits whatever the page's fields already hold, so it "
                "requires operator confirmation either under a bound, "
                "approved write-class web-check flow, or ad-hoc with no flow "
                "bound, where the call parks its own per-action approval "
                "card. The live page origin must stay on the allowlist."
            ),
            risk_level="write",
            category=CATEGORY,
            parameters_schema={
                "type": "object",
                "required": ["ref"],
                "properties": {
                    "ref": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Element ref from the latest web.snapshot.",
                    },
                },
            },
        )

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()
        entry, error = await self._connector._resolve_session(
            self.tool_name, identity, "write"
        )
        if error is not None:
            return error
        assert entry is not None
        handle, guard = await self._guarded_handle(
            entry, parameters, identity.get("approval_kind")
        )
        if guard is not None:
            return guard
        try:
            await handle.click()
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            LOGGER.warning("web.click failed: %s", exc)
            return make_error_result(
                self.tool_name, "BROWSER_ACTION_ERROR", str(exc),
                risk_level="write", source_system=SOURCE_SYSTEM,
                duration_ms=duration_ms,
            )
        return self._step_result(entry, start)


class WebTypeTool(_WebInteractionTool):
    tool_name = "web.type"
    risk_level = "write"

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web.type",
            description=(
                "Type text into the element identified by a web.snapshot "
                "ref. Write tier, though typing submits nothing: the text is "
                "model-chosen and is the payload of the change, so the gate "
                "belongs here — a later submitting click would not reveal "
                "what was submitted. Requires operator confirmation either "
                "under a bound, approved write-class web-check flow, or "
                "ad-hoc with no flow bound, where the call parks its own "
                "per-action approval card. The live page origin must stay on "
                "the allowlist. Never type credentials with this tool — use "
                "web.fill_credential."
            ),
            risk_level="write",
            category=CATEGORY,
            parameters_schema={
                "type": "object",
                "required": ["ref", "text"],
                "properties": {
                    "ref": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Element ref from the latest web.snapshot.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to type into the element.",
                    },
                },
            },
        )

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()
        entry, error = await self._connector._resolve_session(
            self.tool_name, identity, "write"
        )
        if error is not None:
            return error
        assert entry is not None
        text = parameters.get("text")
        if not isinstance(text, str):
            return make_error_result(
                self.tool_name, "INVALID_PARAMETERS",
                "Parameter 'text' must be a string.",
                risk_level="write", source_system=SOURCE_SYSTEM,
            )
        handle, guard = await self._guarded_handle(
            entry, parameters, identity.get("approval_kind")
        )
        if guard is not None:
            return guard
        try:
            await handle.fill(text)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            LOGGER.warning("web.type failed: %s", exc)
            return make_error_result(
                self.tool_name, "BROWSER_ACTION_ERROR", str(exc),
                risk_level="write", source_system=SOURCE_SYSTEM,
                duration_ms=duration_ms,
            )
        return self._step_result(entry, start)


class WebFillCredentialTool(_WebInteractionTool):
    """Fill a login field from a named credential set (R-5, read tier).

    Read tier by design (D-3): filling a form field submits nothing; the
    write-class flow's gate lands on the submitting interaction. The
    credential value only ever flows into the Playwright fill call — it
    never appears in results, snapshots, evidence, or logs.
    """

    tool_name = "web.fill_credential"
    risk_level = "read"

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web.fill_credential",
            description=(
                "Fill a username or password field (web.snapshot ref) from "
                "a platform-managed named credential set. Read tier by "
                "design: filling a field submits nothing, so it needs no "
                "operator confirmation — the write gate lands on the "
                "submitting interaction (web.click / web.press_key). The "
                "credential value only ever reaches the page; it never "
                "appears in skills, results, snapshots, evidence, or logs."
            ),
            risk_level="read",
            category=CATEGORY,
            parameters_schema={
                "type": "object",
                "required": ["ref", "credential_set", "field"],
                "properties": {
                    "ref": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Element ref from the latest web.snapshot.",
                    },
                    "credential_set": {
                        "type": "string",
                        "description": "Name of the configured credential set.",
                    },
                    "field": {
                        "type": "string",
                        "enum": list(CREDENTIAL_FIELDS),
                        "description": "Which credential value to fill.",
                    },
                },
            },
        )

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()
        connector = self._connector
        entry, error = await connector._resolve_session(
            self.tool_name, identity, "read"
        )
        if error is not None:
            return error
        assert entry is not None

        set_name = parameters.get("credential_set")
        field = parameters.get("field")
        if not isinstance(set_name, str) or not set_name:
            return make_error_result(
                self.tool_name, "INVALID_PARAMETERS",
                "Parameter 'credential_set' is required.",
                source_system=SOURCE_SYSTEM,
            )
        if field not in CREDENTIAL_FIELDS:
            return make_error_result(
                self.tool_name, "INVALID_PARAMETERS",
                "Parameter 'field' must be one of: "
                + ", ".join(CREDENTIAL_FIELDS) + ".",
                source_system=SOURCE_SYSTEM,
            )
        credential = connector.credentials.get(set_name)
        if credential is None:
            # W-3: do not enumerate available set names to the model — the
            # list is an information disclosure that lets the model probe
            # which sets exist. A generic message is sufficient.
            return make_error_result(
                self.tool_name, "CREDENTIAL_SET_NOT_FOUND",
                f"Credential set '{set_name}' is not configured.",
                source_system=SOURCE_SYSTEM,
            )
        # SPEC-068 R-1: a non-`basic` set (bearer/oauth2) carries no
        # username/password to fill. Fail closed *before* acquiring the
        # guarded handle rather than filling a blank or raising KeyError;
        # the message stays generic per W-3 (no scheme disclosure).
        value = credential.get(field)
        if not isinstance(value, str) or not value:
            return make_error_result(
                self.tool_name, "CREDENTIAL_SET_NOT_FOUND",
                f"Credential set '{set_name}' cannot fill the "
                f"'{field}' field.",
                source_system=SOURCE_SYSTEM,
            )

        handle, guard = await self._guarded_handle(
            entry, parameters, identity.get("approval_kind")
        )
        if guard is not None:
            return guard
        try:
            await handle.fill(value)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            # Log the exception class only: messages can echo input state
            # and must never leak the credential value.
            LOGGER.warning(
                "web.fill_credential failed: %s", exc.__class__.__name__
            )
            return make_error_result(
                self.tool_name, "BROWSER_ACTION_ERROR",
                "Filling the credential field failed.",
                source_system=SOURCE_SYSTEM, duration_ms=duration_ms,
            )
        entry.filled_values.add(value)
        if field == "password":
            # Track the password separately so screenshots can mask it even
            # when a legacy target renders it into a non-password field.
            entry.secret_values.add(value)
        return self._step_result(
            entry, start, {"filled": field, "credential_set": set_name}
        )


# --- SPEC-050: write-tier interaction tools ---------------------------------


class WebSelectTool(_WebInteractionTool):
    """Select a dropdown option by snapshot ref (SPEC-050 R-1)."""

    tool_name = "web.select"
    risk_level = "write"

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web.select",
            description=(
                "Select an option from a <select> element identified by a "
                "web.snapshot ref. Write tier, though choosing an option "
                "submits nothing: the value is model-chosen and is the "
                "payload of the change, so the gate belongs here rather than "
                "on a later submitting click that would not reveal what was "
                "submitted. Requires operator confirmation either under a "
                "bound, approved write-class web-check flow, or ad-hoc with "
                "no flow bound, where the call parks its own per-action "
                "approval card."
            ),
            risk_level="write",
            category=CATEGORY,
            parameters_schema={
                "type": "object",
                "required": ["ref", "value"],
                "properties": {
                    "ref": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Element ref from the latest web.snapshot.",
                    },
                    "value": {
                        "type": "string",
                        "description": (
                            "Option value or visible text to select."
                        ),
                    },
                },
            },
        )

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()
        entry, error = await self._connector._resolve_session(
            self.tool_name, identity, "write"
        )
        if error is not None:
            return error
        assert entry is not None
        value = parameters.get("value")
        if not isinstance(value, str) or not value:
            return make_error_result(
                self.tool_name, "INVALID_PARAMETERS",
                "Parameter 'value' must be a non-empty string.",
                risk_level="write", source_system=SOURCE_SYSTEM,
            )
        handle, guard = await self._guarded_handle(
            entry, parameters, identity.get("approval_kind")
        )
        if guard is not None:
            return guard
        try:
            await handle.select_option(value)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            msg = str(exc)
            code = "BROWSER_ACTION_ERROR"
            if "not a select" in msg.lower():
                code = "BROWSER_SELECT_NOT_A_SELECT"
            elif "not found" in msg.lower():
                code = "BROWSER_SELECT_OPTION_NOT_FOUND"
            LOGGER.warning("web.select failed: %s", exc)
            return make_error_result(
                self.tool_name, code, msg,
                risk_level="write", source_system=SOURCE_SYSTEM,
                duration_ms=duration_ms,
            )
        return self._step_result(
            entry, start, {"selected": value},
        )


class WebPressKeyTool(BaseTool):
    """Press a keyboard key (SPEC-050 R-4).

    Write tier: parks a HITL confirmation card. Accepts an optional ref;
    when present the element is focused first. Without a ref the key is
    pressed on the active page/frame target.
    """

    tool_name = "web.press_key"
    risk_level = "write"

    def __init__(self, connector: BrowserConnector) -> None:
        self._connector = connector

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web.press_key",
            description=(
                "Press a keyboard key or combination, optionally focusing "
                "an element by snapshot ref first. Write tier: Enter and Tab "
                "are submitting interactions that commit whatever the page's "
                "fields already hold, so each call requires operator "
                "confirmation either under a bound, approved write-class "
                "web-check flow, or ad-hoc with no flow bound, where the "
                "call parks its own per-action approval card."
            ),
            risk_level="write",
            category=CATEGORY,
            parameters_schema={
                "type": "object",
                "required": ["key"],
                "properties": {
                    "key": {
                        "type": "string",
                        "description": (
                            "Playwright key name (e.g. Enter, Escape, Tab)."
                        ),
                    },
                    "ref": {
                        "type": "integer",
                        "minimum": 1,
                        "description": (
                            "Optional element ref to focus before pressing."
                        ),
                    },
                },
            },
        )

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()
        connector = self._connector
        entry, error = await connector._resolve_session(
            self.tool_name, identity, "write"
        )
        if error is not None:
            return error
        assert entry is not None
        key = parameters.get("key")
        if not isinstance(key, str) or not key:
            return make_error_result(
                self.tool_name, "INVALID_PARAMETERS",
                "Parameter 'key' must be a non-empty string.",
                risk_level="write", source_system=SOURCE_SYSTEM,
            )
        # Deviation guard (flow binding, origin, step budget) or, when unbound,
        # the live-origin re-check + provenance backstop (SPEC-054 R-2).
        gate = await connector.gate_interaction(
            entry, self.tool_name, require_write_class=True,
            approval_kind=identity.get("approval_kind"),
        )
        if gate is not None:
            return gate
        ref = parameters.get("ref")
        if ref is not None:
            handle, ref_error = _resolve_ref(entry, self.tool_name, ref)
            if ref_error is not None:
                return ref_error
            try:
                await handle.focus()
            except Exception:  # noqa: BLE001 - focus is best-effort
                pass
        target = entry.active_target
        try:
            # Keyboard input always dispatches through the Page object;
            # it reaches the focused element regardless of frame context.
            # Playwright Frame objects do not expose .keyboard.
            await entry.page.keyboard.press(key)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            LOGGER.warning("web.press_key failed: %s", exc)
            return make_error_result(
                self.tool_name, "BROWSER_ACTION_ERROR", str(exc),
                risk_level="write", source_system=SOURCE_SYSTEM,
                duration_ms=duration_ms,
            )
        duration_ms = int((time.perf_counter() - start) * 1000)
        data = {"url": redact_secret_query(target.url), "key": key}
        flow = entry.flow
        if flow is not None:
            # Bound flow: account the step (SPEC-051). An unbound ad-hoc
            # keypress has no budget to account against (SPEC-054 R-2).
            flow.steps_used += 1
            flow.approved = True
            data["steps_used"] = flow.steps_used
            data["steps_budget"] = flow.max_steps
        return ToolResult(
            tool_name=self.tool_name,
            status="success",
            data=data,
            evidence=build_evidence("write", SOURCE_SYSTEM, duration_ms),
        )


class WebUploadFileTool(_WebInteractionTool):
    """Upload a file via an <input type=file> (SPEC-050 R-8).

    The filename is resolved against the configured upload directory;
    path traversal is denied.
    """

    tool_name = "web.upload_file"
    risk_level = "write"

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web.upload_file",
            description=(
                "Upload a file to an <input type=file> element identified "
                "by a web.snapshot ref. The file must reside in the "
                "configured upload directory. Write tier, though setting the "
                "input submits nothing: the filename is model-chosen and is "
                "the payload of the change, so the gate belongs here rather "
                "than on a later submitting click. Requires operator "
                "confirmation either under a bound, approved write-class "
                "web-check flow, or ad-hoc with no flow bound, where the "
                "call parks its own per-action approval card."
            ),
            risk_level="write",
            category=CATEGORY,
            parameters_schema={
                "type": "object",
                "required": ["ref", "filename"],
                "properties": {
                    "ref": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Element ref from the latest web.snapshot.",
                    },
                    "filename": {
                        "type": "string",
                        "description": (
                            "Name of a file in the configured upload directory."
                        ),
                    },
                },
            },
        )

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()
        entry, error = await self._connector._resolve_session(
            self.tool_name, identity, "write"
        )
        if error is not None:
            return error
        assert entry is not None
        filename = parameters.get("filename")
        if not isinstance(filename, str) or not filename:
            return make_error_result(
                self.tool_name, "INVALID_PARAMETERS",
                "Parameter 'filename' must be a non-empty string.",
                risk_level="write", source_system=SOURCE_SYSTEM,
            )
        if "/" in filename or "\\" in filename or ".." in filename:
            return make_error_result(
                self.tool_name, "BROWSER_UPLOAD_PATH_NOT_ALLOWED",
                "Filename must not contain path separators or traversal.",
                risk_level="write", source_system=SOURCE_SYSTEM,
            )
        handle, guard = await self._guarded_handle(
            entry, parameters, identity.get("approval_kind")
        )
        if guard is not None:
            return guard
        # Verify the element is a file input.
        info = await handle.evaluate(_ELEMENT_INSPECT_JS)
        if not isinstance(info, dict) or info.get("type") != "file":
            return make_error_result(
                self.tool_name, "BROWSER_UPLOAD_NOT_A_FILE_INPUT",
                "The referenced element is not an <input type=file>.",
                risk_level="write", source_system=SOURCE_SYSTEM,
            )
        upload_dir = self._connector._upload_dir
        if not upload_dir:
            return make_error_result(
                self.tool_name, "BROWSER_UPLOAD_NOT_CONFIGURED",
                "No upload directory is configured.",
                risk_level="write", source_system=SOURCE_SYSTEM,
            )
        file_path = os.path.realpath(
            os.path.join(upload_dir, filename)
        )
        allowed_dir = os.path.realpath(upload_dir)
        if not file_path.startswith(allowed_dir + os.sep) and file_path != allowed_dir:
            return make_error_result(
                self.tool_name, "BROWSER_UPLOAD_PATH_NOT_ALLOWED",
                "The file path escapes the configured upload directory.",
                risk_level="write", source_system=SOURCE_SYSTEM,
            )
        if not os.path.isfile(file_path):
            return make_error_result(
                self.tool_name, "BROWSER_UPLOAD_FILE_NOT_FOUND",
                f"File '{filename}' was not found in the upload directory.",
                risk_level="write", source_system=SOURCE_SYSTEM,
            )
        try:
            await handle.set_input_files(file_path)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            LOGGER.warning("web.upload_file failed: %s", exc)
            return make_error_result(
                self.tool_name, "BROWSER_ACTION_ERROR", str(exc),
                risk_level="write", source_system=SOURCE_SYSTEM,
                duration_ms=duration_ms,
            )
        return self._step_result(
            entry, start, {"uploaded": filename},
        )


# --- SPEC-050: read-tier observation tools ----------------------------------


class WebExtractTool(BaseTool):
    """Extract structured data from DOM elements (SPEC-050 R-2)."""

    tool_name = "web.extract"
    risk_level = "read"

    def __init__(self, connector: BrowserConnector) -> None:
        self._connector = connector

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web.extract",
            description=(
                "Extract structured data from DOM elements matching a CSS "
                "selector. For <table> elements returns headers and rows; "
                "for other elements returns a list of text items."
            ),
            risk_level="read",
            category=CATEGORY,
            parameters_schema={
                "type": "object",
                "required": ["selector"],
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector for the elements to extract.",
                    },
                    "max_rows": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 500,
                        "description": (
                            "Maximum rows to extract (default 100, cap 500)."
                        ),
                    },
                },
            },
        )

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()
        connector = self._connector
        entry, error = await connector._resolve_session(
            self.tool_name, identity, "read"
        )
        if error is not None:
            return error
        assert entry is not None
        selector = parameters.get("selector")
        if not isinstance(selector, str) or not selector:
            return make_error_result(
                self.tool_name, "INVALID_PARAMETERS",
                "Parameter 'selector' must be a non-empty string.",
                source_system=SOURCE_SYSTEM,
            )
        max_rows = min(
            int(parameters.get("max_rows", 100) or 100), 500
        )
        gate = await connector.gate_capture(entry, self.tool_name)
        if gate is not None:
            return gate
        target = entry.active_target
        try:
            elements = await target.query_selector_all(selector)
            elements = elements[:max_rows]
            if not elements:
                data = {"items": [], "count": 0}
            else:
                # Check if the first element is a table.
                first_info = await elements[0].evaluate(_ELEMENT_INSPECT_JS)
                tag = (
                    first_info.get("tag", "")
                    if isinstance(first_info, dict) else ""
                )
                if tag == "table":
                    data = await _extract_table(elements[0], max_rows)
                else:
                    items = []
                    for el in elements:
                        info = await el.evaluate(_ELEMENT_INSPECT_JS)
                        text = (
                            info.get("text", "")
                            if isinstance(info, dict) else ""
                        )
                        items.append(text[:200])
                    data = {"items": items, "count": len(items)}
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            LOGGER.warning("web.extract failed: %s", exc)
            return make_error_result(
                self.tool_name, "BROWSER_EXTRACT_ERROR", str(exc),
                source_system=SOURCE_SYSTEM, duration_ms=duration_ms,
            )
        duration_ms = int((time.perf_counter() - start) * 1000)
        return ToolResult(
            tool_name=self.tool_name,
            status="success",
            data=data,
            evidence=build_evidence("read", SOURCE_SYSTEM, duration_ms),
        )


async def _extract_table(table_el, max_rows: int) -> dict:
    """Extract headers and rows from a <table> element."""
    extract_js = """
    table => {
        const headers = [];
        const rows = [];
        const ths = table.querySelectorAll('thead th, tr:first-child th');
        ths.forEach(th => headers.push((th.innerText || '').trim().slice(0, 200)));
        const trs = table.querySelectorAll('tbody tr, tr');
        let count = 0;
        for (const tr of trs) {
            if (count >= %MAX_ROWS%) break;
            const cells = tr.querySelectorAll('td');
            if (cells.length === 0) continue;
            const row = [];
            cells.forEach(td => row.push((td.innerText || '').trim().slice(0, 200)));
            rows.push(row);
            count++;
        }
        return {headers, rows, count};
    }
    """.replace("%MAX_ROWS%", str(max_rows))
    result = await table_el.evaluate(extract_js)
    if not isinstance(result, dict):
        return {"headers": [], "rows": [], "count": 0}
    # Bound columns to 50.
    headers = result.get("headers", [])[:50]
    rows = [row[:50] for row in result.get("rows", [])]
    return {
        "headers": headers,
        "rows": rows,
        "count": result.get("count", len(rows)),
    }


class WebWaitForTool(BaseTool):
    """Wait for an element state (SPEC-050 R-3)."""

    tool_name = "web.wait_for"
    risk_level = "read"

    def __init__(self, connector: BrowserConnector) -> None:
        self._connector = connector

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web.wait_for",
            description=(
                "Wait for an element matching a CSS selector to reach a "
                "specific state (attached, detached, visible, hidden). "
                "Useful for pages that load data asynchronously."
            ),
            risk_level="read",
            category=CATEGORY,
            parameters_schema={
                "type": "object",
                "required": ["selector"],
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector to wait for.",
                    },
                    "state": {
                        "type": "string",
                        "enum": ["attached", "detached", "visible", "hidden"],
                        "description": (
                            "Element state to wait for (default: visible)."
                        ),
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "minimum": 100,
                        "maximum": 30000,
                        "description": (
                            "Timeout in milliseconds (default 5000, cap 30000)."
                        ),
                    },
                },
            },
        )

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()
        connector = self._connector
        entry, error = await connector._resolve_session(
            self.tool_name, identity, "read"
        )
        if error is not None:
            return error
        assert entry is not None
        selector = parameters.get("selector")
        if not isinstance(selector, str) or not selector:
            return make_error_result(
                self.tool_name, "INVALID_PARAMETERS",
                "Parameter 'selector' must be a non-empty string.",
                source_system=SOURCE_SYSTEM,
            )
        state = parameters.get("state", "visible")
        if state not in ("attached", "detached", "visible", "hidden"):
            return make_error_result(
                self.tool_name, "INVALID_PARAMETERS",
                "Parameter 'state' must be one of: attached, detached, "
                "visible, hidden.",
                source_system=SOURCE_SYSTEM,
            )
        timeout_ms = min(
            int(parameters.get("timeout_ms", 5000) or 5000), 30000
        )
        gate = await connector.gate_capture(entry, self.tool_name)
        if gate is not None:
            return gate
        target = entry.active_target
        try:
            handle = await target.wait_for_selector(
                selector, state=state, timeout=timeout_ms,
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            LOGGER.warning("web.wait_for timed out: %s", exc)
            return make_error_result(
                self.tool_name, "BROWSER_WAIT_TIMEOUT",
                f"Element '{selector}' did not reach state '{state}' "
                f"within {timeout_ms}ms.",
                source_system=SOURCE_SYSTEM, duration_ms=duration_ms,
            )
        duration_ms = int((time.perf_counter() - start) * 1000)
        text = ""
        if handle is not None:
            info = await handle.evaluate(_ELEMENT_INSPECT_JS)
            if isinstance(info, dict):
                text = info.get("text", "")[:200]
        return ToolResult(
            tool_name=self.tool_name,
            status="success",
            data={
                "selector": selector,
                "state": state,
                "text": text,
            },
            evidence=build_evidence("read", SOURCE_SYSTEM, duration_ms),
        )


class WebHoverTool(BaseTool):
    """Hover over an element (SPEC-050 R-5)."""

    tool_name = "web.hover"
    risk_level = "read"

    def __init__(self, connector: BrowserConnector) -> None:
        self._connector = connector

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web.hover",
            description=(
                "Hover over an element identified by a web.snapshot ref "
                "to reveal tooltips, dropdown menus, or popover actions."
            ),
            risk_level="read",
            category=CATEGORY,
            parameters_schema={
                "type": "object",
                "required": ["ref"],
                "properties": {
                    "ref": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Element ref from the latest web.snapshot.",
                    },
                },
            },
        )

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()
        connector = self._connector
        entry, error = await connector._resolve_session(
            self.tool_name, identity, "read"
        )
        if error is not None:
            return error
        assert entry is not None
        gate = await connector.gate_capture(entry, self.tool_name)
        if gate is not None:
            return gate
        handle, ref_error = _resolve_ref(entry, self.tool_name, parameters.get("ref"))
        if ref_error is not None:
            return ref_error
        try:
            await handle.hover()
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            LOGGER.warning("web.hover failed: %s", exc)
            return make_error_result(
                self.tool_name, "BROWSER_ACTION_ERROR", str(exc),
                source_system=SOURCE_SYSTEM, duration_ms=duration_ms,
            )
        duration_ms = int((time.perf_counter() - start) * 1000)
        info = await handle.evaluate(_ELEMENT_INSPECT_JS)
        tag = info.get("tag", "element") if isinstance(info, dict) else "element"
        return ToolResult(
            tool_name=self.tool_name,
            status="success",
            data={
                "url": _evidence_url(entry),
                "tag": tag,
            },
            evidence=build_evidence("read", SOURCE_SYSTEM, duration_ms),
        )


class WebEvaluateTool(BaseTool):
    """Execute JavaScript in the page context (SPEC-050 R-6).

    Write tier: arbitrary JS can mutate the DOM and read back masked
    credential values, so every invocation inherits the SPEC-020/037 HITL
    gate — the operator confirms before any script runs. The pre-execution
    mutation guard below is defense-in-depth only: it rejects expressions
    containing known state-changing DOM APIs to steer the agent toward the
    dedicated ref-addressed write tools, but it is NOT the security
    boundary (a regex denylist over arbitrary JS source cannot be).
    """

    tool_name = "web.evaluate"
    risk_level = "write"

    # Patterns that indicate a mutating operation. Checked case-insensitively
    # against the raw expression before execution as defense-in-depth (the
    # write-tier HITL gate is the real boundary). Deliberately broad: a
    # false-positive (rejecting a benign read) is safe and merely steers the
    # agent to the dedicated write tools.
    _MUTATION_PATTERNS: tuple[str, ...] = (
        # DOM action methods
        r"\.click\s*\(",
        r"\.submit\s*\(",
        r"\.requestSubmit\s*\(",
        r"\.focus\s*\(",
        r"\.blur\s*\(",
        r"\.reset\s*\(",
        r"\.remove\s*\(",
        r"\.appendChild\s*\(",
        r"\.append\s*\(",
        r"\.prepend\s*\(",
        r"\.insertBefore\s*\(",
        r"\.insertAdjacentHTML\s*\(",
        r"\.insertAdjacentElement\s*\(",
        r"\.replaceChild\s*\(",
        r"\.replaceWith\s*\(",
        r"\.setAttribute\s*\(",
        r"\.removeAttribute\s*\(",
        # Assignment patterns: single = only (not == or ===)
        r"\.value\s*=(?!=)",
        r"\.checked\s*=(?!=)",
        r"\.disabled\s*=(?!=)",
        r"\.selected\s*=(?!=)",
        r"\.selectedIndex\s*=(?!=)",
        r"\.innerHTML\s*=(?!=)",
        r"\.outerHTML\s*=(?!=)",
        r"\.textContent\s*=(?!=)",
        r"\.innerText\s*=(?!=)",
        r"\.href\s*=(?!=)",
        r"\.src\s*=(?!=)",
        r"\.action\s*=(?!=)",
        r"\.className\s*=(?!=)",
        r"\.id\s*=(?!=)",
        r"\.title\s*=(?!=)",
        # classList mutating methods only (contains/item are reads)
        r"\.classList\.(add|remove|toggle|replace)\s*\(",
        # Network / side-effect APIs
        r"\bfetch\s*\(",
        r"\bXMLHttpRequest\b",
        r"\bsendBeacon\s*\(",
        r"\.dispatchEvent\s*\(",
        # Scroll methods (mutate viewport)
        r"\.scrollTo\s*\(",
        r"\.scrollBy\s*\(",
        r"\.scrollIntoView\s*\(",
        # Navigation
        r"\bwindow\.location\s*=(?!=)",
        r"\blocation\.assign\s*\(",
        r"\blocation\.replace\s*\(",
        r"\blocation\.reload\s*\(",
        r"\bhistory\.(pushState|replaceState|go|back|forward)\s*\(",
        r"\bwindow\.open\s*\(",
        # Document mutation
        r"\bdocument\.write\s*\(",
        r"\bdocument\.writeln\s*\(",
        # Dialogs (block execution, social engineering vector)
        r"\balert\s*\(",
        r"\bconfirm\s*\(",
        r"\bprompt\s*\(",
        # Dynamic code execution
        r"\bnew\s+Function\b",
        r"\beval\s*\(",
        r"\bsetTimeout\s*\(",
        r"\bsetInterval\s*\(",
        r"\brequestAnimationFrame\s*\(",
        r"\bimport\s*\(",
        # Storage writes
        r"\blocalStorage\.(setItem|removeItem|clear)\s*\(",
        r"\bsessionStorage\.(setItem|removeItem|clear)\s*\(",
        r"\bdocument\.cookie\s*=(?!=)",
    )

    def __init__(self, connector: BrowserConnector) -> None:
        self._connector = connector
        self._mutation_re = re.compile(
            "|".join(self._MUTATION_PATTERNS), re.IGNORECASE
        )

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web.evaluate",
            description=(
                "Execute a JavaScript expression in the page context and "
                "return the result (bounded to 16000 chars). Write tier: "
                "arbitrary JS can mutate the DOM and read masked secrets, "
                "so each call requires operator confirmation."
            ),
            risk_level="write",
            category=CATEGORY,
            parameters_schema={
                "type": "object",
                "required": ["expression"],
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "JavaScript expression to evaluate.",
                    },
                },
            },
        )

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()
        connector = self._connector
        entry, error = await connector._resolve_session(
            self.tool_name, identity, self.risk_level
        )
        if error is not None:
            return error
        assert entry is not None
        expression = parameters.get("expression")
        if not isinstance(expression, str) or not expression:
            return make_error_result(
                self.tool_name, "INVALID_PARAMETERS",
                "Parameter 'expression' must be a non-empty string.",
                risk_level=self.risk_level, source_system=SOURCE_SYSTEM,
            )
        # Pre-execution mutation guard (defense-in-depth): reject expressions
        # that contain known state-changing DOM APIs so the agent is steered
        # to the dedicated ref-addressed write tools. The write-tier HITL
        # gate — not this regex — is the actual security boundary.
        match = self._mutation_re.search(expression)
        if match:
            return make_error_result(
                self.tool_name, "BROWSER_EVAL_MUTATION_BLOCKED",
                f"Expression rejected: contains mutating operation "
                f"'{match.group(0).strip()}'. Use the dedicated write-tier "
                f"tools (web.click, web.type, etc.) for DOM mutations so "
                f"the action is ref-addressed and auditable.",
                risk_level=self.risk_level, source_system=SOURCE_SYSTEM,
            )
        gate = await connector.gate_capture(entry, self.tool_name)
        if gate is not None:
            return gate
        target = entry.active_target
        try:
            raw = await target.evaluate(expression)
        except TypeError:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return make_error_result(
                self.tool_name, "BROWSER_EVAL_NOT_SERIALIZABLE",
                "The expression result is not JSON-serializable.",
                risk_level=self.risk_level, source_system=SOURCE_SYSTEM,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            LOGGER.warning("web.evaluate failed: %s", exc)
            return make_error_result(
                self.tool_name, "BROWSER_EVAL_ERROR", str(exc),
                risk_level=self.risk_level, source_system=SOURCE_SYSTEM,
                duration_ms=duration_ms,
            )
        # Serialize and bound the result.
        try:
            serialized = json.dumps(raw, default=str)
        except (TypeError, ValueError):
            duration_ms = int((time.perf_counter() - start) * 1000)
            return make_error_result(
                self.tool_name, "BROWSER_EVAL_NOT_SERIALIZABLE",
                "The expression result could not be serialized to JSON.",
                risk_level=self.risk_level, source_system=SOURCE_SYSTEM,
                duration_ms=duration_ms,
            )
        if len(serialized) > SNAPSHOT_MAX_CHARS:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return make_error_result(
                self.tool_name, "BROWSER_EVAL_RESULT_TOO_LARGE",
                f"The result ({len(serialized)} chars) exceeds the "
                f"{SNAPSHOT_MAX_CHARS}-char cap.",
                risk_level=self.risk_level, source_system=SOURCE_SYSTEM,
                duration_ms=duration_ms,
            )
        duration_ms = int((time.perf_counter() - start) * 1000)
        return ToolResult(
            tool_name=self.tool_name,
            status="success",
            data={
                "url": _evidence_url(entry),
                "result": raw,
                "bytes": len(serialized),
            },
            evidence=build_evidence(self.risk_level, SOURCE_SYSTEM, duration_ms),
        )


class WebScrollTool(BaseTool):
    """Scroll the page (SPEC-050 R-7)."""

    tool_name = "web.scroll"
    risk_level = "read"

    def __init__(self, connector: BrowserConnector) -> None:
        self._connector = connector

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web.scroll",
            description=(
                "Scroll the page by the given pixel offsets."
            ),
            risk_level="read",
            category=CATEGORY,
            parameters_schema={
                "type": "object",
                "properties": {
                    "delta_x": {
                        "type": "integer",
                        "description": "Horizontal scroll offset (default 0).",
                    },
                    "delta_y": {
                        "type": "integer",
                        "description": "Vertical scroll offset (default 300).",
                    },
                },
            },
        )

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()
        connector = self._connector
        entry, error = await connector._resolve_session(
            self.tool_name, identity, "read"
        )
        if error is not None:
            return error
        assert entry is not None
        delta_x = parameters.get("delta_x", 0)
        delta_y = parameters.get("delta_y", 300)
        if not isinstance(delta_x, int) or not isinstance(delta_y, int):
            return make_error_result(
                self.tool_name, "INVALID_PARAMETERS",
                "Parameters 'delta_x' and 'delta_y' must be integers.",
                source_system=SOURCE_SYSTEM,
            )
        gate = await connector.gate_capture(entry, self.tool_name)
        if gate is not None:
            return gate
        target = entry.active_target
        try:
            # A Page-level mouse wheel scrolls whatever is under the cursor.
            # When an iframe is the active target, move the cursor to the
            # frame's center first so the wheel scrolls the frame rather than
            # the top-level page. Playwright Frame objects do not expose
            # .mouse, so both the move and the wheel dispatch via the Page.
            if entry.frame_stack:
                frame_element = await target.frame_element()
                box = await frame_element.bounding_box()
                if box:
                    await entry.page.mouse.move(
                        box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2,
                    )
            await entry.page.mouse.wheel(delta_x, delta_y)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            LOGGER.warning("web.scroll failed: %s", exc)
            return make_error_result(
                self.tool_name, "BROWSER_ACTION_ERROR", str(exc),
                source_system=SOURCE_SYSTEM, duration_ms=duration_ms,
            )
        duration_ms = int((time.perf_counter() - start) * 1000)
        return ToolResult(
            tool_name=self.tool_name,
            status="success",
            data={
                "url": _evidence_url(entry),
                "delta_x": delta_x,
                "delta_y": delta_y,
            },
            evidence=build_evidence("read", SOURCE_SYSTEM, duration_ms),
        )


class WebSwitchFrameTool(BaseTool):
    """Switch into an iframe (SPEC-050 R-9)."""

    tool_name = "web.switch_frame"
    risk_level = "read"

    def __init__(self, connector: BrowserConnector) -> None:
        self._connector = connector

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web.switch_frame",
            description=(
                "Switch the browser context into an iframe identified by "
                "a CSS selector. Subsequent operations target the frame's "
                "document. A web.navigate call resets to the main frame."
            ),
            risk_level="read",
            category=CATEGORY,
            parameters_schema={
                "type": "object",
                "required": ["selector"],
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector for the iframe element.",
                    },
                },
            },
        )

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()
        connector = self._connector
        entry, error = await connector._resolve_session(
            self.tool_name, identity, "read"
        )
        if error is not None:
            return error
        assert entry is not None
        selector = parameters.get("selector")
        if not isinstance(selector, str) or not selector:
            return make_error_result(
                self.tool_name, "INVALID_PARAMETERS",
                "Parameter 'selector' must be a non-empty string.",
                source_system=SOURCE_SYSTEM,
            )
        gate = await connector.gate_capture(entry, self.tool_name)
        if gate is not None:
            return gate
        target = entry.active_target
        try:
            frame_el = await target.query_selector(selector)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            LOGGER.warning("web.switch_frame failed: %s", exc)
            return make_error_result(
                self.tool_name, "BROWSER_FRAME_NOT_FOUND",
                f"No element matching '{selector}' was found.",
                source_system=SOURCE_SYSTEM, duration_ms=duration_ms,
            )
        if frame_el is None:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return make_error_result(
                self.tool_name, "BROWSER_FRAME_NOT_FOUND",
                f"No element matching '{selector}' was found.",
                source_system=SOURCE_SYSTEM, duration_ms=duration_ms,
            )
        try:
            frame = await frame_el.content_frame()
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            LOGGER.warning("web.switch_frame: not a frame element: %s", exc)
            return make_error_result(
                self.tool_name, "BROWSER_FRAME_NOT_FOUND",
                "The matched element does not contain a frame.",
                source_system=SOURCE_SYSTEM, duration_ms=duration_ms,
            )
        if frame is None:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return make_error_result(
                self.tool_name, "BROWSER_FRAME_NOT_FOUND",
                "The matched element does not contain a frame.",
                source_system=SOURCE_SYSTEM, duration_ms=duration_ms,
            )
        # Check the frame's origin against the flow's bound origin.
        frame_url = frame.url
        frame_origin = origin_of(frame_url)
        flow = entry.flow
        if (
            flow is not None
            and frame_origin is not None
            and frame_origin != flow.origin
        ):
            duration_ms = int((time.perf_counter() - start) * 1000)
            return _denied(
                self.tool_name, "BROWSER_FRAME_ORIGIN_MISMATCH",
                f"Frame origin '{frame_origin}' does not match the bound "
                f"flow's origin '{flow.origin}'.",
                "read",
            )
        entry.reset_page_state()  # drop stale refs (clears frame_stack too)
        entry.frame_stack.append(frame)
        duration_ms = int((time.perf_counter() - start) * 1000)
        return ToolResult(
            tool_name=self.tool_name,
            status="success",
            data={
                "url": redact_secret_query(frame_url),
                "frame_depth": len(entry.frame_stack),
            },
            evidence=build_evidence("read", SOURCE_SYSTEM, duration_ms),
        )
