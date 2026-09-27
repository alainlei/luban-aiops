"""Kernel middleware aligning AgentScope with the platform contract (SPEC-018).

All cross-cutting kernel behavior lives on the supported ``MiddlewareBase``
surface instead of private agentscope internals:

- ``GatewayPermissionMiddleware`` (R-1) owns the permission gate for a
  headless SSE runtime: vetted read-only gateway tools and the built-in
  task tools are ALLOWed; every other tool is answered with an explicit
  ASK instead of delegating to agentscope's PermissionEngine, whose
  read-only fast path auto-allows read-only invocations in every mode and
  would silently bypass the platform allow-list. The ASK parks the batch
  on ``RequireUserConfirmEvent`` for the SPEC-020 confirmation bridge.
- ``ToolEvidenceMiddleware`` (R-2) emits the ``tool_call`` / ``tool_result``
  evidence frames (SPEC-011 R-2 contract) into a request-scoped sink set by
  the runtime kernel; blocking turns with no sink emit nothing.
- ``TokenUsageMiddleware`` (SPEC-065 R-1) records provider-reported LLM token
  usage as ``agent_llm_tokens_total`` on the supported ``on_model_call`` hook —
  always-on, streaming-aware, and pure observation (no cost; deferred per the
  SPEC-065 Stage-0 finding that agentscope 2.0.8 exposes no provider cost).

Admission, policy, and audit remain enforced by the tool-gateway on every
invocation; this module only shapes kernel-local decisions and evidence.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncGenerator, Callable
from contextvars import ContextVar
from typing import Any

from agentscope.message import ToolCallBlock, ToolCallState
from agentscope.middleware import MiddlewareBase
from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.tool import ToolResponse

from agent_service.core.metrics import record_llm_tokens
from agent_service.services.flow_approvals import BROWSER_WRITE_TOOLS
from agent_service.services.secret_params import redact_evidence_parameters, redact_result_data
from agent_service.services.prose_redaction import (
    CURRENT_PROSE_REDACTOR, generated_credential_literals, observe_generated_result,
    redact_structure,
)

LOGGER = logging.getLogger(__name__)

# Request-scoped evidence sink (SPEC-018 R-2): an asyncio.Queue set by
# ``AgentKernel.stream_events`` around each streamed turn. Unset (None) for
# blocking turns, so the evidence middleware stays inert there.
TOOL_EVIDENCE_SINK: ContextVar[Any | None] = ContextVar(
    "TOOL_EVIDENCE_SINK",
    default=None,
)

# SPEC-062 R-3 reveal-on-commit: two per-stream buffers that decouple a
# generated portal_copy secret from the moment its ``secret_delivery`` frame is
# emitted. Both are set/reset by the runtime kernel around each streamed turn
# (mirroring ``TOOL_EVIDENCE_SINK``) and stay ``None`` for blocking turns, so the
# evidence middleware buffers nothing there.
#
# - ``STREAM_PENDING_DELIVERIES`` collects deliveries GENERATED in *this* stream.
#   The kernel drains it onto the parked card at an ASK park (so the held secret
#   rides the approval), or flushes it as ``secret_delivery`` frames at a normal
#   stream end (the standalone generate-and-copy path — no gate follows, so the
#   Copy button appears at turn end).
# - ``PENDING_RELEASE_DELIVERIES`` carries deliveries from a PRIOR park into a
#   resumed stream. Set only on an approved resume, it is released as
#   ``secret_delivery`` frames the instant a gated mutating call in the approved
#   batch returns success — never at a normal stream end, so a denied or failed
#   mutation burns the secret silently.
STREAM_PENDING_DELIVERIES: ContextVar[list | None] = ContextVar(
    "STREAM_PENDING_DELIVERIES",
    default=None,
)
PENDING_RELEASE_DELIVERIES: ContextVar[list | None] = ContextVar(
    "PENDING_RELEASE_DELIVERIES",
    default=None,
)
# SPEC-063 R-4 secret-release permits: a per-stream map of call_id -> the typed
# single-use ``SecretReleasePermit`` minted by the v3 invocation coordinator from
# a durably accepted original successful response. When a run guard is bound
# (admission enabled), ``ToolEvidenceMiddleware`` releases a held portal_copy
# delivery only after consuming the permit for that call and re-checking the run
# latch — a tool frame's ``status: success`` plus ``EXECUTION_REQUESTS``
# membership is no longer sufficient. ``None`` (legacy/admission-disabled) keeps
# the existing status+membership trigger unchanged.
RELEASE_PERMITS: ContextVar[dict | None] = ContextVar(
    "RELEASE_PERMITS",
    default=None,
)

# Built-in agentscope task tools (SPEC-018 R-5). Names match the kernel's
# tool names; these tools mutate only session-local agent state and are
# always allowed — they must never hit the interactive ASK gate on a
# headless stream.
TASK_TOOL_NAMES = frozenset({
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
})

# Kernel-built-in tool that delivers response_schema turns (SPEC-017 R-2):
# it only shapes the final reply into the caller-provided schema and never
# touches external systems, so it must never park on the ASK gate either.
STRUCTURED_OUTPUT_TOOL_NAME = "GenerateStructuredOutput"

# Kernel-built-in agent-driven context compression tool (SPEC-064 R-2): it
# only summarizes the agent's own working context into state.summary /
# state.context and never touches external systems, so — like the task tools
# and GenerateStructuredOutput — it must never park on the headless ASK gate.
# Opt-in via AGENTSCOPE_COMPRESS_CONTEXT_ENABLED; agentscope only registers the
# tool when ContextConfig.compression_tool_enabled is set, so this membership is
# inert when the knob is off.
COMPRESS_CONTEXT_TOOL_NAME = "CompressContext"

KERNEL_LOCAL_TOOL_NAMES = TASK_TOOL_NAMES | {
    STRUCTURED_OUTPUT_TOOL_NAME,
    COMPRESS_CONTEXT_TOOL_NAME,
}

# Vetted tool names that may bypass the permission gate. Only read-only
# tools on this explicit allow-list are auto-approved; every other tool is
# answered with an explicit ASK and parks for operator confirmation
# (SPEC-020). Admission and policy are still enforced by the tool-gateway
# on every invocation.
DEFAULT_AUTO_ALLOWED_TOOLS = frozenset({
    "k8s.list_pods",
    "k8s.get_pod",
    "k8s.get_events",
    "k8s.get_pod_logs",
    "skills.search",
    "skills.get",
    "skills.list",
    "incidents.list",
    "incidents.get",
    "secrets.generate_password",
    # SPEC-049/SPEC-050: read-class browser probes may run without an extra
    # gate; the gateway still enforces the origin allowlist and flow guards
    # on every call. web.click/web.type/web.select/web.press_key/web.upload_file
    # are intentionally absent — they can never satisfy the read-only
    # invariant below. web.evaluate is also absent: arbitrary JS can mutate
    # the DOM and read masked secrets, so it inherits the write-tier HITL gate.
    "web.navigate",
    "web.snapshot",
    "web.screenshot",
    "web.fill_credential",
    "web.extract",
    "web.wait_for",
    "web.hover",
    "web.scroll",
    "web.switch_frame",
    # SPEC-058 R-1 originally vetted ``http.get`` here on the same footing as
    # the read-class browser probes. v0.39.1 (post-SPEC-061 hardening) removes
    # it from the built-in default: outbound network egress is a different risk
    # class from in-cluster reads, so its HITL bypass is now opt-in. An
    # environment that wants a read-tier ``http.get`` to park no card names it
    # in ``AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA`` (additive) or
    # ``AGENT_GATEWAY_TOOL_AUTO_ALLOW`` (replacement). The gateway still
    # enforces the origin allowlist, the response-byte bound, the
    # loopback/link-local/multicast refusal and the secret-bearing-URL refusal
    # on every call regardless of the allow-list, so this is defence-in-depth
    # over an already deny-by-default egress path, not the primary control.
    #
    # ``http.post`` is intentionally absent and can never be auto-allowed: it
    # is write-tier, so the ``is_read_only`` half of the gate below refuses it
    # even if an operator names it, and its single per-action card is the point
    # of the tool.
})
AUTO_ALLOW_ENV = "AGENT_GATEWAY_TOOL_AUTO_ALLOW"
AUTO_ALLOW_EXTRA_ENV = "AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA"


def _load_auto_allowed_tools() -> frozenset[str]:
    """Resolve the auto-approve allow-list (env override or vetted default).

    ``AGENT_GATEWAY_TOOL_AUTO_ALLOW`` accepts a comma-separated list of
    gateway tool names and *replaces* the vetted default; an empty string
    auto-approves nothing. ``AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA`` is
    *additive*: its entries are unioned with the resolved set, so an
    environment can opt a single tool (e.g. ``http.get``) back into
    auto-approval without restating the whole list. Entries in both are
    normalized to the sanitized tool names used by AgentScope (dots become
    underscores), matching ``FunctionTool.name``.
    """
    raw = os.environ.get(AUTO_ALLOW_ENV)
    base = DEFAULT_AUTO_ALLOWED_TOOLS if raw is None else {
        part.strip() for part in raw.split(",") if part.strip()
    }
    extra_raw = os.environ.get(AUTO_ALLOW_EXTRA_ENV)
    extra = (
        {part.strip() for part in extra_raw.split(",") if part.strip()}
        if extra_raw is not None else set()
    )
    return frozenset(name.replace(".", "_") for name in base | extra)


def _make_data_summary(
    data: Any, max_chars: int = 2000,
) -> dict | None:
    """Build a bounded data_summary for trace events (SPEC-011 R-2).

    Serializes ``data`` to JSON and truncates if it exceeds ``max_chars``.
    Returns None when data is None or empty.
    """
    if data is None:
        return None
    serialized = json.dumps(data, default=str)
    if len(serialized) <= max_chars:
        return data
    # Truncate the serialized form and return a marker dict.
    return {"_truncated": True, "_preview": serialized[:max_chars], "_original_length": len(serialized)}


def _make_full_data(data: Any, max_chars: int = 128000) -> Any:
    """Return the full tool payload for evidence frames, size-guarded.

    Streams stay bounded: when the serialized payload exceeds
    ``max_chars`` the field is omitted from the frame entirely — the
    truncated ``data_summary`` still surfaces and the full result stays
    in the audit trail. Returns None when data is None.

    The default limit (128KB) accommodates base64-encoded screenshots
    from web.screenshot (up to 64KB raw → ~87KB base64).
    """
    if data is None:
        return None
    serialized = json.dumps(data, default=str)
    if len(serialized) > max_chars:
        return None
    return data


def _portal_copy_delivery(gateway_result: dict) -> dict | None:
    """Extract a valid portal_copy handle from a generate_password result.

    SPEC-062 R-3: returns the opaque ``{delivery_id, channel, expires_at}``
    triple (never the plaintext) that the evidence middleware buffers for a
    deferred ``secret_delivery`` frame, or ``None`` when the result carries no
    portal_copy handoff or the handle is malformed. The delivery_id must be a
    canonical UUID and expires_at a tz-aware ISO-8601 timestamp — the same
    validity gate the inline emit used, so a bad handle is dropped, not surfaced.
    """
    from datetime import datetime
    from uuid import UUID

    data = gateway_result.get("data")
    if not isinstance(data, dict) or data.get("channel") != "portal_copy":
        return None
    delivery_id, expires_at = data.get("delivery_id"), data.get("expires_at")
    try:
        valid = (
            isinstance(delivery_id, str)
            and str(UUID(delivery_id)) == delivery_id
            and isinstance(expires_at, str)
            and datetime.fromisoformat(expires_at).tzinfo is not None
        )
    except ValueError:
        valid = False
    if not valid:
        return None
    return {
        "delivery_id": delivery_id,
        "channel": "portal_copy",
        "expires_at": expires_at,
    }


class GatewayPermissionMiddleware(MiddlewareBase):
    """Owns AgentScope's permission gate for a headless kernel (R-1).

    The platform allow-list is the only auto-approval surface (deny by
    default): tools that are read-only AND vetted are pre-approved, and
    state-local task tools always run — the tool-gateway still enforces
    admission and policy on every invocation and each call is
    audit-logged. Every other tool is answered with an explicit ASK
    rather than delegated to agentscope's PermissionEngine: the engine
    auto-allows read-only invocations in every mode (read-only fast
    path), which would silently skip the allow-list. The ASK parks the
    batch on RequireUserConfirmEvent, which the kernel bridges to the
    operator portal (SPEC-020).

    Calls already approved through that bridge traverse the middleware
    chain again on resume (state ALLOWED); they are delegated to the
    built-in resolution, which short-circuits ALLOWED calls — re-ASKing
    them would park the resumed reply forever.

    SPEC-051 R-1 adds one narrow runtime exception for browser flows: a
    mutating ``web.*`` call inside a flow the operator already approved is
    ALLOWed and auto-signed via the optional ``flow_signer`` (scoped to the
    session and the approved flow's identity), so a multi-step mutating flow
    parks a single card instead of one per write. This is runtime flow
    authority, not an allow-list entry — the read-only auto-allow invariant
    is unchanged, and the tool-gateway deviation guard still bounds the write.
    """

    def __init__(
        self,
        auto_allowed: frozenset[str] | None = None,
        flow_signer: Callable[[Any, str], dict | None] | None = None,
    ) -> None:
        self._allow_list = (
            auto_allowed if auto_allowed is not None else _load_auto_allowed_tools()
        )
        # SPEC-051 R-1: optional callback the kernel arms to auto-sign an
        # unlocked browser write. ``flow_signer(tool_call, gateway_tool_name)``
        # returns a signed execution envelope when the session holds a live
        # flow authority whose identity still matches the bound flow, else
        # ``None`` (→ the write parks as before). Never set for non-browser
        # writes; the static read-only allow-list above is untouched.
        self._flow_signer = flow_signer

    async def on_check_permission(
        self,
        agent: Any,
        input_kwargs: dict,
        next_handler: Any,
    ) -> PermissionDecision:
        tool = input_kwargs.get("tool")
        name = getattr(tool, "name", None)
        tool_call = input_kwargs.get("tool_call")
        # SPEC-063 R-4: consult the run stop BEFORE the ALLOWED shortcut. A
        # stopped run's mutating call is denied outright — a fresh confirmation
        # alone must never clear a stop, and a stale ALLOWED state carried into a
        # resumed stream must not auto-execute. Read-only and kernel-local tools
        # stay on their existing governed path. Inert when no guard is bound
        # (every non-execution turn), so existing behavior is unchanged.
        if (
            name not in KERNEL_LOCAL_TOOL_NAMES
            and not (tool is not None and getattr(tool, "is_read_only", False))
        ):
            from agent_service.services.execution_run_guard import current_guard

            guard = current_guard()
            if guard is not None and guard.stopped():
                return PermissionDecision(
                    behavior=PermissionBehavior.DENY,
                    message=(
                        "execution run is stopped; refusing mutating call "
                        "(SPEC-063 R-4). A new confirmation cannot clear a stop."
                    ),
                )
        if getattr(tool_call, "state", None) == ToolCallState.ALLOWED:
            # SPEC-020 resume: the operator already confirmed this exact
            # call. Agentscope re-traverses the middleware chain for
            # confirmed calls and expects the built-in resolution to
            # short-circuit the ALLOWED state; re-ASKing here would
            # re-park the resumed reply indefinitely.
            return await next_handler(**input_kwargs)
        if name in KERNEL_LOCAL_TOOL_NAMES:
            # State-local kernel built-ins (task tools, structured-output
            # delivery) never touch external systems.
            return PermissionDecision(
                behavior=PermissionBehavior.ALLOW,
                message=f"{name} mutates only session-local agent state.",
            )
        if (
            tool is not None
            and getattr(tool, "is_read_only", False)
            and name in self._allow_list
        ):
            # SPEC-021 R-3 invariant: the allow-list is read-only by
            # construction. Mutating tools carry is_read_only=False, so
            # naming one in AGENT_GATEWAY_TOOL_AUTO_ALLOW can never grant
            # auto-execution — it falls through to the ASK below and parks
            # for HITL confirmation regardless of configuration.
            return PermissionDecision(
                behavior=PermissionBehavior.ALLOW,
                message=(
                    "Vetted read-only gateway tool; admission and policy "
                    "are enforced by the tool-gateway."
                ),
            )
        if tool is None:
            # No tool surface to reason about; keep the built-in resolution.
            return await next_handler(**input_kwargs)
        # SPEC-051 R-1: one HITL gate per mutating browser flow. A browser
        # write (web.click/type/select/press_key/upload_file/evaluate) inside a
        # flow the operator already approved is admitted here and auto-signed
        # by ``flow_signer`` under the approving card's authority — never via
        # the static read-only allow-list above, and never for non-browser
        # writes (k8s.*, etc.). The signer returns None (fail-safe → ASK) when
        # no live authority exists, the signing key/execution state is unset,
        # the bound flow's identity no longer matches the approval (a rebind),
        # or the tool name is outside BROWSER_WRITE_TOOLS — the same set this
        # branch tests, checked again there so the scope does not rest on this
        # call site staying the only one (SPEC-055 R-5). The tool-gateway
        # deviation guard still bounds the write.
        gateway_tool_name = getattr(tool, "gateway_tool_name", None)
        if (
            self._flow_signer is not None
            and gateway_tool_name in BROWSER_WRITE_TOOLS
            and not getattr(tool, "is_read_only", False)
        ):
            envelope = self._flow_signer(tool_call, gateway_tool_name)
            if envelope is not None:
                return PermissionDecision(
                    behavior=PermissionBehavior.ALLOW,
                    message=(
                        f"{gateway_tool_name} is unlocked by an approved "
                        "browser flow (SPEC-051 R-1); auto-signed under the "
                        "approving card and still bounded by the gateway "
                        "deviation guard."
                    ),
                )
        # Explicit ASK instead of delegating to agentscope's
        # PermissionEngine: its read-only fast path auto-allows read-only
        # invocations in every mode, which would silently bypass the
        # platform allow-list for unvetted read-only gateway tools. The
        # ASK parks the batch on RequireUserConfirmEvent for the SPEC-020
        # confirmation bridge.
        return PermissionDecision(
            behavior=PermissionBehavior.ASK,
            message=(
                f"{name} is outside the auto-approve allow-list; "
                "operator confirmation is required."
            ),
        )


class ToolEvidenceMiddleware(MiddlewareBase):
    """Emits tool_call / tool_result evidence frames for streamed turns (R-2).

    Frames keep the exact SPEC-011 R-2 field contract consumed by
    ``agent-stream-event.schema.json``. Only gateway-backed tools emit
    frames (identified by the ``gateway_tool_name`` attribute set at toolkit
    construction); built-in task tools and other kernel tools pass through
    silently, matching pre-middleware behavior. The gateway result dict is
    carried on ``ToolChunk``/``ToolResponse`` metadata by the tool closures
    so no JSON re-parse is needed.

    Besides the bounded ``data_summary``, each tool_result frame carries
    the full ``data`` payload when its serialized size stays within
    ``data_max_chars`` so the portal can offer a full-output view of a
    tool run regardless of how the model chooses to phrase its reply.
    Oversized payloads are omitted from the frame (the truncated summary
    still surfaces, and the full result remains in the audit trail).
    """

    def __init__(
        self,
        data_summary_max_chars: int = 2000,
        data_max_chars: int = 128000,
    ) -> None:
        self._max_chars = data_summary_max_chars
        self._data_max_chars = data_max_chars

    async def on_acting(
        self,
        agent: Any,
        input_kwargs: dict,
        next_handler: Any,
    ):
        sink = TOOL_EVIDENCE_SINK.get()
        tool_call = input_kwargs.get("tool_call")
        gateway_tool_name = None
        if tool_call is not None:
            tool = self._resolve_tool(agent, tool_call.name)
            gateway_tool_name = getattr(tool, "gateway_tool_name", None)

        if sink is None or not gateway_tool_name:
            # Blocking turn, or a non-gateway tool (task tools, builtins):
            # pass through without emitting evidence frames.
            async for item in next_handler(**input_kwargs):
                yield item
            return

        call_id = tool_call.id
        # SPEC-037 R-3: bind the in-flight invocation to its parked call
        # id so the tool closure can match it against the signed execution
        # request set by the resume path.
        from agent_service.tools.gateway_tools import (
            CURRENT_CALL_ID,
            EXECUTION_REQUESTS,
        )

        call_token = CURRENT_CALL_ID.set(call_id)
        try:
            await sink.put({
                "type": "tool_call",
                "tool_name": gateway_tool_name,
                "call_id": call_id,
                # A display + at-rest projection, never a signing input: the
                # frame is streamed to the portal's evidence panel and
                # persisted, so a secret the model put in an argument (the
                # password-reset demo navigates with ``?newpw=...``) would
                # otherwise be readable in both even though every gateway-side
                # representation of the same call masks it (SPEC-049 R-5).
                # The resume path digests a fresh raw payload, so masking here
                # cannot shift an ``args_digest``.
                "parameters": redact_structure(
                    redact_evidence_parameters(
                        gateway_tool_name, self._parse_parameters(tool_call),
                    ),
                    CURRENT_PROSE_REDACTOR.get().literals if CURRENT_PROSE_REDACTOR.get() else (),
                ),
            })

            gateway_result = None
            async for item in next_handler(**input_kwargs):
                if isinstance(item, ToolResponse):
                    gateway_result = (item.metadata or {}).get("gateway_result")
                yield item

            frame: dict[str, Any] = {
                "type": "tool_result",
                "tool_name": gateway_tool_name,
                "call_id": call_id,
            }
            if isinstance(gateway_result, dict):
                observe_generated_result(gateway_result)
                redactor = CURRENT_PROSE_REDACTOR.get()
                literals = redactor.literals if redactor else generated_credential_literals(gateway_result)
                safe_result = redact_structure(
                    redact_result_data(gateway_tool_name, gateway_result), literals,
                )
                frame["status"] = safe_result.get("status", "error")
                evidence = safe_result.get("evidence")
                if evidence:
                    frame["evidence"] = evidence
                frame["data_summary"] = _make_data_summary(
                    safe_result.get("data"), self._max_chars,
                )
                full_data = _make_full_data(
                    safe_result.get("data"), self._data_max_chars,
                )
                if full_data is not None:
                    frame["data"] = full_data
                error = safe_result.get("error")
                if error:
                    frame["error"] = error
            else:
                # The tool failed before the gateway returned a result; keep the
                # frame schema-valid.
                frame["status"] = "error"
                frame["data_summary"] = None
            await sink.put(frame)
            # SPEC-062 R-3 reveal-on-commit: a generated portal_copy secret is
            # no longer emitted inline. Buffer the opaque handle into this
            # stream's pending set so the kernel can defer the secret_delivery
            # frame — onto the parked card when a gate follows, or to a normal
            # stream end when none does. Frame shape is unchanged; only timing.
            if (
                gateway_tool_name == "secrets.generate_password"
                and frame["status"] == "success"
                and isinstance(gateway_result, dict)
            ):
                delivery = _portal_copy_delivery(gateway_result)
                pending = STREAM_PENDING_DELIVERIES.get()
                if delivery is not None and pending is not None:
                    pending.append(delivery)
            # Release trigger: an approved gated mutating call just committed.
            # EXECUTION_REQUESTS is keyed by call_id and populated only on an
            # approved resume (SPEC-037 R-2), so a success whose call_id is in
            # that map is exactly the bound reset flow's gated write succeeding
            # — the moment the held Copy-password button is revealed. On a deny,
            # a gated-call failure, or an expiry nothing is emitted and the
            # delivery burns silently.
            #
            # SPEC-063 R-4: when a run guard is bound (durable admission enabled)
            # the status+membership trigger is necessary but NOT sufficient —
            # release additionally requires consuming the single-use permit the
            # v3 coordinator minted from a durably accepted original success, and
            # a final run-latch check immediately before emission. The legacy
            # (no-guard) path is unchanged.
            release = PENDING_RELEASE_DELIVERIES.get()
            if (
                release
                and frame["status"] == "success"
                and call_id in (EXECUTION_REQUESTS.get() or {})
                and self._permit_secret_release(call_id)
            ):
                for held in list(release):
                    await sink.put({"type": "secret_delivery", **held})
                release.clear()
        finally:
            CURRENT_CALL_ID.reset(call_token)

    @staticmethod
    def _permit_secret_release(call_id: str) -> bool:
        """SPEC-063 R-4 secret-release gate for one committed gated call.

        Legacy path (no bound guard): the existing status+membership trigger is
        the whole gate, so return True. v3 path (guard bound): require a typed
        single-use permit for this ``call_id``, re-check the run latch
        immediately before emission, and consume the permit exactly once. A
        missing permit, a spent permit, or a stopped run releases nothing — the
        held delivery burns.
        """
        from agent_service.services.execution_run_guard import current_guard

        guard = current_guard()
        if guard is None:
            return True
        permits = RELEASE_PERMITS.get() or {}
        permit = permits.get(call_id)
        if permit is None:
            return False
        # Re-check the latch immediately before emission (R-4): a stop that
        # landed after the permit was minted still bars the reveal.
        if guard.stopped():
            return False
        try:
            permit.consume()
        except TypeError:
            # Already spent, or forged across a process boundary — never emit.
            return False
        permits.pop(call_id, None)
        return True

    @staticmethod
    def _resolve_tool(agent: Any, name: str) -> Any:
        """Find the registered tool instance for a tool call name."""
        toolkit = getattr(agent, "toolkit", None)
        for group in getattr(toolkit, "tool_groups", None) or []:
            for tool in getattr(group, "tools", None) or []:
                if getattr(tool, "name", None) == name:
                    return tool
        return None

    @staticmethod
    def _parse_parameters(tool_call: ToolCallBlock) -> dict:
        """Parse the tool call's raw JSON input into a parameters dict."""
        raw = getattr(tool_call, "input", "") or ""
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}


class TokenUsageMiddleware(MiddlewareBase):
    """Records provider-reported LLM token usage as a metric (SPEC-065 R-1).

    A pure-observation ``on_model_call`` middleware — always-on (no knob), since
    reading a token count is not a mutation and needs no gate. It resolves a
    bounded ``{provider, model}`` from ``current_model`` via the credential-gated
    catalog (an uncatalogued model → the ``unknown`` sentinel, so label
    cardinality stays bounded), delegates to ``next_handler``, then increments
    ``agent_llm_tokens_total{provider,model,direction}`` from the provider's own
    ``usage`` — the four token counts agentscope's ``ChatUsage`` exposes.

    It is **streaming-aware**: the platform chat path streams, so ``next_handler``
    returns an ``AsyncGenerator`` whose terminal chunk carries the cumulative
    usage. A naive non-generator read would record zero, so the generator is
    wrapped and usage read off the last chunk that carries it — mirroring the
    tracing middleware's generator wrapper. A response with no ``usage`` records
    nothing; tokens are never synthesized or estimated.

    **No cost is recorded.** agentscope 2.0.8 exposes no provider-derived cost
    and the platform holds no price table, so the dollar metric is deferred
    rather than fabricated (SPEC-065 Stage-0 finding).
    """

    def __init__(self, catalog: Any | None = None) -> None:
        # ``catalog`` exposes ``get(model_id) -> entry | None`` where an entry
        # carries ``.provider`` (a bounded RuntimeProvider) and ``.model_name``.
        # Defaults to the platform ``MODEL_CATALOG`` singleton; injectable so
        # tests need no live catalog.
        self._catalog = catalog

    def _resolve_labels(self, current_model: Any) -> tuple[str, str]:
        """Bounded ``{provider, model}`` labels for a model instance (R-1)."""
        model_name = getattr(current_model, "model", None)
        if not isinstance(model_name, str) or not model_name:
            return ("unknown", "unknown")
        catalog = self._catalog
        if catalog is None:
            from agent_service.services.model_catalog import MODEL_CATALOG

            catalog = MODEL_CATALOG
        entry = catalog.get(model_name)
        if entry is None:
            # Uncatalogued model → sentinel, keeping cardinality bounded to the
            # credential-gated catalog rather than any string a provider echoes.
            return ("unknown", "unknown")
        return (str(entry.provider), str(entry.model_name))

    async def on_model_call(
        self,
        agent: Any,
        input_kwargs: dict,
        next_handler: Any,
    ) -> Any:
        provider, model = self._resolve_labels(input_kwargs.get("current_model"))
        result = await next_handler(**input_kwargs)
        if isinstance(result, AsyncGenerator):
            # Streaming chat path: usage lands on the terminal chunk, so wrap the
            # generator and record once it is consumed (see class docstring).
            return self._record_stream(result, provider, model)
        self._record(getattr(result, "usage", None), provider, model)
        return result

    async def _record_stream(
        self,
        stream: AsyncGenerator,
        provider: str,
        model: str,
    ) -> AsyncGenerator:
        """Pass every chunk through untouched; record the last usage seen.

        Recording in ``finally`` means an early close or a mid-stream error still
        books whatever usage arrived (and nothing when none did) — the stream is
        never altered, only observed.
        """
        last_usage = None
        try:
            async for chunk in stream:
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    last_usage = usage
                yield chunk
        finally:
            self._record(last_usage, provider, model)

    @staticmethod
    def _record(usage: Any, provider: str, model: str) -> None:
        """Increment the token counter from a provider ``usage``, or nothing."""
        if usage is None:
            # Never synthesize a zero-fill estimate when a provider reports no
            # usage (some streaming/edge responses omit it).
            return
        record_llm_tokens(
            provider, model, "input", getattr(usage, "input_tokens", 0) or 0,
        )
        record_llm_tokens(
            provider, model, "output", getattr(usage, "output_tokens", 0) or 0,
        )
        record_llm_tokens(
            provider, model, "cache_input",
            getattr(usage, "cache_input_tokens", 0) or 0,
        )
        record_llm_tokens(
            provider, model, "cache_creation",
            getattr(usage, "cache_creation_input_tokens", 0) or 0,
        )
