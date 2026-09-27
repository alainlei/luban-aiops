"""Kernel middleware tests (SPEC-018 R-1/R-2/R-3/R-4/R-5).

Middlewares are exercised through their hook signatures with stub
``next_handler``s — no live agentscope agent is required.
"""

import asyncio
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import jsonschema

from prometheus_client import REGISTRY

from agent_service.core.metrics import LLM_TOKEN_DIRECTIONS
from agent_service.services.kernel_middleware import (
    AUTO_ALLOW_ENV,
    AUTO_ALLOW_EXTRA_ENV,
    COMPRESS_CONTEXT_TOOL_NAME,
    PENDING_RELEASE_DELIVERIES,
    STREAM_PENDING_DELIVERIES,
    TASK_TOOL_NAMES,
    STRUCTURED_OUTPUT_TOOL_NAME,
    TOOL_EVIDENCE_SINK,
    GatewayPermissionMiddleware,
    TokenUsageMiddleware,
    ToolEvidenceMiddleware,
    _load_auto_allowed_tools,
    _make_data_summary,
    _make_full_data,
)

SCHEMAS_DIR = (
    Path(__file__).resolve().parents[3] / "shared" / "shared-contracts" / "schemas"
)


def _run(coro):
    return asyncio.run(coro)


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


# --- Stubs -----------------------------------------------------------------


class _StubTool:
    def __init__(self, name, gateway_tool_name=None, is_read_only=True):
        self.name = name
        self.is_read_only = is_read_only
        if gateway_tool_name is not None:
            self.gateway_tool_name = gateway_tool_name


class _StubAgent:
    """Minimal agent stand-in exposing only the toolkit lookup surface."""

    def __init__(self, tools):
        self.toolkit = SimpleNamespace(
            tool_groups=[SimpleNamespace(tools=tools)],
        )


def _permission_next(decision, calls):
    async def next_handler(**kwargs):
        calls.append(kwargs)
        return decision

    return next_handler


def _acting_next(*items):
    async def next_handler(**kwargs):
        for item in items:
            yield item

    return next_handler


def _drain(gen):
    async def _collect():
        items = []
        async for item in gen:
            items.append(item)
        return items

    return asyncio.run(_collect())


def _tool_call_block(tool_name, parameters, call_id="call-1"):
    from agentscope.message import ToolCallBlock

    return ToolCallBlock(
        id=call_id,
        name=tool_name,
        input=json.dumps(parameters),
    )


# --- R-2 helper: data_summary truncation ------------------------------------


class DataSummaryTests(unittest.TestCase):
    """Test data_summary truncation (SPEC-011 R-2, Q-1)."""

    def test_none_data_returns_none(self) -> None:
        self.assertIsNone(_make_data_summary(None))

    def test_small_data_returned_unchanged(self) -> None:
        data = {"pods": [{"name": "web-1"}]}
        result = _make_data_summary(data)
        self.assertEqual(result, data)

    def test_large_data_truncated_with_marker(self) -> None:
        data = {"logs": "x" * 5000}
        result = _make_data_summary(data, max_chars=100)
        self.assertTrue(result["_truncated"])
        self.assertEqual(len(result["_preview"]), 100)
        self.assertGreater(result["_original_length"], 100)

    def test_exact_boundary_not_truncated(self) -> None:
        data = {"key": "val"}
        serialized = json.dumps(data, default=str)
        result = _make_data_summary(data, max_chars=len(serialized))
        self.assertEqual(result, data)

    def test_empty_match_skills_payload_passes_through(self) -> None:
        """SPEC-014 R-5 empty-match contract: a skills.search success with
        no hits keeps its exact shape through the evidence panel pipeline."""
        data = {"matches": [], "total": 0}
        self.assertEqual(_make_data_summary(data), data)

    def test_empty_catalog_skills_payload_passes_through(self) -> None:
        """Same contract for skills.list: an empty catalog keeps its exact
        shape through the evidence panel pipeline."""
        data = {"skills": [], "total": 0}
        self.assertEqual(_make_data_summary(data), data)


class FullDataTests(unittest.TestCase):
    """Test the size-guarded full-payload passthrough (stream schema v5)."""

    def test_none_data_returns_none(self) -> None:
        self.assertIsNone(_make_full_data(None))

    def test_data_within_cap_returned_unchanged(self) -> None:
        data = {"logs": "\n".join(f"line-{i}" for i in range(50))}
        self.assertEqual(_make_full_data(data), data)

    def test_oversized_data_returns_none(self) -> None:
        data = {"logs": "x" * 5000}
        self.assertIsNone(_make_full_data(data, max_chars=100))

    def test_exact_boundary_included(self) -> None:
        data = {"key": "val"}
        serialized = json.dumps(data, default=str)
        self.assertEqual(_make_full_data(data, max_chars=len(serialized)), data)


# --- R-1: permission middleware ---------------------------------------------


class AllowListTests(unittest.TestCase):
    def test_default_allow_list_normalized_to_sanitized_names(self) -> None:
        allow = _load_auto_allowed_tools()
        self.assertIn("k8s_list_pods", allow)
        self.assertIn("skills_search", allow)
        self.assertIn("incidents_get", allow)
        self.assertNotIn("k8s.list_pods", allow)

    def test_env_override_replaces_default(self) -> None:
        with patch.dict(os.environ, {AUTO_ALLOW_ENV: "k8s.get_pod"}):
            self.assertEqual(_load_auto_allowed_tools(), frozenset({"k8s_get_pod"}))

    def test_env_override_empty_approves_nothing(self) -> None:
        with patch.dict(os.environ, {AUTO_ALLOW_ENV: ""}):
            self.assertEqual(_load_auto_allowed_tools(), frozenset())

    def test_extra_var_unions_with_default(self) -> None:
        """``AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA`` is additive: it opts a single
        tool back into auto-approval without restating the vetted default
        (v0.39.1 hardening — this is how the dev cluster keeps ``http.get``
        card-free after it left ``DEFAULT_AUTO_ALLOWED_TOOLS``)."""
        with patch.dict(os.environ, {AUTO_ALLOW_EXTRA_ENV: "http.get"}):
            allow = _load_auto_allowed_tools()
        self.assertIn("http_get", allow)
        self.assertIn("k8s_list_pods", allow)  # default still present
        self.assertIn("web_navigate", allow)

    def test_extra_var_unions_with_replacement_var(self) -> None:
        """When both are set, EXTRA unions with the *replacement* set, not the
        built-in default — so the restrict-via-replacement posture (the HITL
        demo dropping ``k8s.get_pod_logs``) still composes with an opt-in."""
        with patch.dict(
            os.environ,
            {AUTO_ALLOW_ENV: "k8s.get_pod", AUTO_ALLOW_EXTRA_ENV: "http.get"},
        ):
            allow = _load_auto_allowed_tools()
        self.assertEqual(allow, frozenset({"k8s_get_pod", "http_get"}))

    def test_extra_var_empty_changes_nothing(self) -> None:
        with patch.dict(os.environ, {AUTO_ALLOW_EXTRA_ENV: ""}):
            allow = _load_auto_allowed_tools()
        self.assertNotIn("http_get", allow)
        self.assertIn("k8s_list_pods", allow)

    def test_browser_read_tools_in_default_list_but_not_write_tools(
        self,
    ) -> None:
        """SPEC-049: read-class browser probes are auto-allowed; the
        write-class web_click/web_type are deliberately never listed.
        web_evaluate is write-tier too (arbitrary JS can mutate the DOM and
        read masked secrets), so it is likewise never auto-allowed."""
        allow = _load_auto_allowed_tools()
        self.assertIn("web_navigate", allow)
        self.assertIn("web_snapshot", allow)
        self.assertIn("web_screenshot", allow)
        self.assertIn("web_fill_credential", allow)
        self.assertNotIn("web_click", allow)
        self.assertNotIn("web_type", allow)
        self.assertNotIn("web_evaluate", allow)

    def test_http_read_tool_not_in_default_list_and_write_tool_never(self) -> None:
        """v0.39.1 hardening: ``http.get`` is no longer in the built-in default
        — outbound-egress HITL bypass is opt-in via
        ``AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA`` (see the union tests above).
        ``http.post`` is write-tier and can never be auto-allowed. The gateway
        still enforces the origin allowlist and the structural refusals on
        every ``http.get`` call, so this is defence-in-depth, not the primary
        egress control."""
        allow = _load_auto_allowed_tools()
        self.assertNotIn("http_get", allow)
        self.assertNotIn("http_post", allow)


class GatewayPermissionMiddlewareTests(unittest.TestCase):
    def _decide(self, middleware, tool, next_decision=None, tool_call=None):
        from agentscope.permission import PermissionBehavior, PermissionDecision

        if next_decision is None:
            next_decision = PermissionDecision(
                behavior=PermissionBehavior.ASK, message="stub-ask",
            )
        calls = []
        input_kwargs = {
            "tool": tool, "tool_call": tool_call, "tool_input": {},
        }
        decision = _run(
            middleware.on_check_permission(
                None, input_kwargs, _permission_next(next_decision, calls),
            )
        )
        return decision, calls

    def test_allow_listed_read_only_tool_allowed_without_delegation(self) -> None:
        from agentscope.permission import PermissionBehavior

        mw = GatewayPermissionMiddleware()
        tool = _StubTool("k8s_list_pods", is_read_only=True)
        decision, calls = self._decide(mw, tool)
        self.assertEqual(decision.behavior, PermissionBehavior.ALLOW)
        self.assertEqual(calls, [])  # built-in resolution bypassed

    def test_read_only_tool_outside_allow_list_asks_without_delegation(self) -> None:
        """Auto-approval is allow-listed, not blanket: unvetted read-only
        tools get an explicit ASK. Delegation to the built-in engine is
        bypassed because its read-only fast path auto-allows read-only
        invocations in every mode, silently skipping the allow-list."""
        from agentscope.permission import PermissionBehavior

        mw = GatewayPermissionMiddleware()
        tool = _StubTool("k8s_list_secrets", is_read_only=True)
        decision, calls = self._decide(mw, tool)
        self.assertEqual(decision.behavior, PermissionBehavior.ASK)
        self.assertEqual(calls, [])  # engine fast path never reached

    def test_non_read_only_tool_asks_even_if_name_listed(self) -> None:
        from agentscope.permission import PermissionBehavior

        mw = GatewayPermissionMiddleware(
            auto_allowed=frozenset({"k8s_restart_pod"}),
        )
        tool = _StubTool("k8s_restart_pod", is_read_only=False)
        decision, calls = self._decide(mw, tool)
        self.assertEqual(decision.behavior, PermissionBehavior.ASK)
        self.assertEqual(calls, [])

    def test_http_get_parks_by_default_and_allows_only_when_opted_in(self) -> None:
        """v0.39.1: the two HTTP tools sit on opposite sides of the gate, and
        ``http.get`` now needs an explicit opt-in. With the built-in default a
        read-tier ``http.get`` parks an ``action`` card; once the environment
        opts it in (``AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA=http.get``, mirrored
        here by adding it to the allow-list) it auto-allows. ``http.post``
        parks regardless — forcing its name onto the allow-list changes nothing
        because the read-only half of the gate refuses it."""
        from agentscope.permission import PermissionBehavior

        # Default posture: http.get is not vetted any more, so it parks.
        mw_default = GatewayPermissionMiddleware()
        parked_decision, parked_calls = self._decide(
            mw_default,
            _StubTool("http_get", gateway_tool_name="http.get", is_read_only=True),
        )
        self.assertEqual(parked_decision.behavior, PermissionBehavior.ASK)
        self.assertEqual(parked_calls, [])

        # Opted-in posture: http.get auto-allows; http.post still parks even
        # when its name is forced onto the list.
        mw_opted = GatewayPermissionMiddleware(
            auto_allowed=_load_auto_allowed_tools() | {"http_get", "http_post"},
        )
        read_decision, read_calls = self._decide(
            mw_opted,
            _StubTool("http_get", gateway_tool_name="http.get", is_read_only=True),
        )
        self.assertEqual(read_decision.behavior, PermissionBehavior.ALLOW)
        self.assertEqual(read_calls, [])

        write_decision, write_calls = self._decide(
            mw_opted,
            _StubTool("http_post", gateway_tool_name="http.post", is_read_only=False),
        )
        self.assertEqual(write_decision.behavior, PermissionBehavior.ASK)
        self.assertEqual(write_calls, [])

    def test_browser_write_tools_never_auto_allowed_even_if_forced(
        self,
    ) -> None:
        """SPEC-049 invariant: even if web_click/web_type were forced onto
        the allow-list, they cannot pass the read-only invariant and must
        still park on ASK."""
        from agentscope.permission import PermissionBehavior

        mw = GatewayPermissionMiddleware(
            auto_allowed=frozenset({"web_click", "web_type"}),
        )
        for name in ("web_click", "web_type"):
            decision, calls = self._decide(
                mw, _StubTool(name, is_read_only=False),
            )
            self.assertEqual(decision.behavior, PermissionBehavior.ASK)
            self.assertEqual(calls, [])

    def test_missing_tool_still_delegates_to_builtin(self) -> None:
        """Without a tool surface there is nothing to policy-check; the
        built-in resolution is preserved."""
        from agentscope.permission import PermissionBehavior

        mw = GatewayPermissionMiddleware()
        decision, calls = self._decide(mw, None)
        self.assertEqual(decision.behavior, PermissionBehavior.ASK)
        self.assertEqual(len(calls), 1)

    def test_allowed_state_call_delegates_instead_of_re_asking(self) -> None:
        """SPEC-020 resume regression: agentscope re-traverses the
        middleware chain for calls the operator already confirmed (state
        ALLOWED). The middleware must delegate so the built-in resolution
        short-circuits them to ALLOW — an explicit ASK here would re-park
        the resumed reply forever (live check: approve loop on
        k8s.get_pod_logs)."""
        from agentscope.message import ToolCallState
        from agentscope.permission import (
            PermissionBehavior,
            PermissionDecision,
        )

        mw = GatewayPermissionMiddleware()
        tool = _StubTool("k8s_list_secrets", is_read_only=True)
        tool_call = SimpleNamespace(state=ToolCallState.ALLOWED)
        already_allowed = PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="Already allowed by user confirmation.",
        )
        decision, calls = self._decide(
            mw, tool, next_decision=already_allowed, tool_call=tool_call,
        )
        self.assertEqual(decision.behavior, PermissionBehavior.ALLOW)
        self.assertEqual(len(calls), 1)

    def test_pending_state_call_still_asks(self) -> None:
        """Only the ALLOWED state short-circuits; fresh calls (PENDING)
        keep the explicit ASK even when the tool_call block is present."""
        from agentscope.message import ToolCallState
        from agentscope.permission import PermissionBehavior

        mw = GatewayPermissionMiddleware()
        tool = _StubTool("k8s_list_secrets", is_read_only=True)
        tool_call = SimpleNamespace(state=ToolCallState.PENDING)
        decision, calls = self._decide(mw, tool, tool_call=tool_call)
        self.assertEqual(decision.behavior, PermissionBehavior.ASK)
        self.assertEqual(calls, [])

    def _stopped_guard(self):
        from agent_service.services.execution_run_guard import (
            RunGuard,
            RunIdentity,
            RunStopLatch,
        )

        latch = RunStopLatch()
        guard = RunGuard(RunIdentity("run-stopped", "s", "o"), latch=latch)
        guard.mark_stopped("wait_expired")
        return guard

    def test_stopped_run_denies_mutating_call_before_allowed_shortcut(self) -> None:
        """SPEC-063 R-4: a stopped run's mutating call is DENIED before the
        ALLOWED shortcut, so a stale confirmation carried into a resumed stream
        cannot auto-execute. The built-in resolution is never reached."""
        from agentscope.message import ToolCallState
        from agentscope.permission import PermissionBehavior
        from agent_service.services.execution_run_guard import CURRENT_RUN_GUARD

        mw = GatewayPermissionMiddleware()
        tool = _StubTool("k8s_restart_pod", is_read_only=False)
        tool_call = SimpleNamespace(state=ToolCallState.ALLOWED)
        token = CURRENT_RUN_GUARD.set(self._stopped_guard())
        try:
            decision, calls = self._decide(mw, tool, tool_call=tool_call)
        finally:
            CURRENT_RUN_GUARD.reset(token)
        self.assertEqual(decision.behavior, PermissionBehavior.DENY)
        self.assertEqual(calls, [])  # ALLOWED shortcut never delegated

    def test_stopped_run_leaves_read_only_and_task_tools_on_their_path(self) -> None:
        """Read-tier and kernel-local tools stay governed on their existing path;
        only mutating calls are denied by the stop."""
        from agentscope.permission import PermissionBehavior
        from agent_service.services.execution_run_guard import CURRENT_RUN_GUARD

        mw = GatewayPermissionMiddleware()
        token = CURRENT_RUN_GUARD.set(self._stopped_guard())
        try:
            ro_decision, _ = self._decide(
                mw, _StubTool("k8s_list_pods", is_read_only=True),
            )
            task_decision, _ = self._decide(
                mw, _StubTool("TaskCreate", is_read_only=False),
            )
        finally:
            CURRENT_RUN_GUARD.reset(token)
        self.assertEqual(ro_decision.behavior, PermissionBehavior.ALLOW)
        self.assertEqual(task_decision.behavior, PermissionBehavior.ALLOW)

    def test_no_bound_guard_is_inert(self) -> None:
        """With no guard bound (every non-execution turn) the ALLOWED shortcut
        behaves exactly as before: it delegates to the built-in resolution."""
        from agentscope.message import ToolCallState
        from agentscope.permission import (
            PermissionBehavior,
            PermissionDecision,
        )

        mw = GatewayPermissionMiddleware()
        tool = _StubTool("k8s_restart_pod", is_read_only=False)
        tool_call = SimpleNamespace(state=ToolCallState.ALLOWED)
        already_allowed = PermissionDecision(
            behavior=PermissionBehavior.ALLOW, message="Already allowed.",
        )
        decision, calls = self._decide(
            mw, tool, next_decision=already_allowed, tool_call=tool_call,
        )
        self.assertEqual(decision.behavior, PermissionBehavior.ALLOW)
        self.assertEqual(len(calls), 1)

    def test_task_tools_always_allowed(self) -> None:
        """R-5: state-local task tools must never hit the interactive ASK
        gate on a headless stream."""
        from agentscope.permission import PermissionBehavior

        mw = GatewayPermissionMiddleware()
        for name in TASK_TOOL_NAMES:
            tool = _StubTool(name, is_read_only=False)
            decision, calls = self._decide(mw, tool)
            self.assertEqual(decision.behavior, PermissionBehavior.ALLOW)
            self.assertEqual(calls, [])

    def test_structured_output_tool_always_allowed(self) -> None:
        """response_schema turns deliver via the kernel's built-in
        GenerateStructuredOutput tool; parking it wedges every structured
        turn (incident triage) on a headless stream."""
        from agentscope.permission import PermissionBehavior

        mw = GatewayPermissionMiddleware()
        tool = _StubTool(STRUCTURED_OUTPUT_TOOL_NAME, is_read_only=False)
        decision, calls = self._decide(mw, tool)
        self.assertEqual(decision.behavior, PermissionBehavior.ALLOW)
        self.assertEqual(calls, [])

    def test_compress_context_tool_always_allowed(self) -> None:
        """SPEC-064 R-2: the opt-in agent-driven CompressContext tool only
        summarizes the agent's own working context into state.summary /
        state.context and never touches an external system, so it joins the
        task tools and GenerateStructuredOutput as a kernel-local always-allow.
        Parking it on the headless ASK gate would wedge compression."""
        from agentscope.permission import PermissionBehavior

        mw = GatewayPermissionMiddleware()
        tool = _StubTool(COMPRESS_CONTEXT_TOOL_NAME, is_read_only=False)
        decision, calls = self._decide(mw, tool)
        self.assertEqual(decision.behavior, PermissionBehavior.ALLOW)
        self.assertEqual(calls, [])

    def test_compress_context_tool_is_kernel_local(self) -> None:
        """SPEC-064 R-2: CompressContext must be a KERNEL-local name so the
        permission gate short-circuits it before the read-only allow-list and
        the run-stop DENY path (it is not a mutating gateway call)."""
        from agent_service.services.kernel_middleware import (
            KERNEL_LOCAL_TOOL_NAMES,
        )

        self.assertIn(COMPRESS_CONTEXT_TOOL_NAME, KERNEL_LOCAL_TOOL_NAMES)

    def test_env_override_scopes_auto_approval(self) -> None:
        from agentscope.permission import PermissionBehavior

        with patch.dict(os.environ, {AUTO_ALLOW_ENV: "k8s.get_pod"}):
            mw = GatewayPermissionMiddleware()
        allowed, _ = self._decide(mw, _StubTool("k8s_get_pod"))
        asked, _ = self._decide(mw, _StubTool("k8s_list_pods"))
        self.assertEqual(allowed.behavior, PermissionBehavior.ALLOW)
        self.assertEqual(asked.behavior, PermissionBehavior.ASK)

    def test_headless_no_stall_parity_for_vetted_tools(self) -> None:
        """Regression: AgentScope 2.x defaults custom function tools to ASK,
        which stalls a headless SSE stream at RequireUserConfirmEvent. Every
        vetted default allow-list entry must resolve to ALLOW through the
        middleware so invocations actually run."""
        from agentscope.permission import PermissionBehavior

        mw = GatewayPermissionMiddleware()
        for sanitized in _load_auto_allowed_tools():
            decision, _ = self._decide(
                mw, _StubTool(sanitized, is_read_only=True),
            )
            self.assertEqual(decision.behavior, PermissionBehavior.ALLOW)


# --- SPEC-051 R-1: browser-flow unlock --------------------------------------


class FlowUnlockPermissionTests(unittest.TestCase):
    """One HITL gate per mutating browser flow (SPEC-051 R-1).

    The middleware admits a mutating ``web.*`` call inside an already-approved
    flow via the optional ``flow_signer`` (the kernel's ``_sign_flow_execution``)
    and ALLOWs it only when the signer returns an envelope; every other path
    keeps the explicit ASK. The signer is a stub here — its real approval /
    identity / execution-state gating is exercised in ``test_runtime_kernel``.
    """

    def _decide(self, middleware, tool, tool_call=None, next_decision=None):
        from agentscope.permission import PermissionBehavior, PermissionDecision

        if next_decision is None:
            next_decision = PermissionDecision(
                behavior=PermissionBehavior.ASK, message="stub-ask",
            )
        calls = []
        input_kwargs = {"tool": tool, "tool_call": tool_call, "tool_input": {}}
        decision = _run(
            middleware.on_check_permission(
                None, input_kwargs, _permission_next(next_decision, calls),
            )
        )
        return decision, calls

    @staticmethod
    def _pending_call(call_id="call-1", name="web_click"):
        from agentscope.message import ToolCallState

        return SimpleNamespace(
            id=call_id, name=name, input='{"ref": 12}',
            state=ToolCallState.PENDING,
        )

    @staticmethod
    def _recording_signer(result):
        """A ``flow_signer`` stub returning ``result`` and recording its calls."""
        seen = []

        def signer(tool_call, gateway_tool_name):
            seen.append((tool_call, gateway_tool_name))
            return result

        return signer, seen

    def test_browser_write_unlocked_by_flow_authority_allows(self) -> None:
        """Recorded approval + armed execution state ⇒ the signer returns an
        envelope ⇒ ALLOW, consulted with the canonical gateway tool name; the
        built-in engine is bypassed so the unlocked write never re-parks."""
        from agentscope.permission import PermissionBehavior

        envelope = {"execution_id": "e1", "tool_name": "web.click", "signature": "s"}
        signer, seen = self._recording_signer(envelope)
        mw = GatewayPermissionMiddleware(flow_signer=signer)
        tool = _StubTool(
            "web_click", gateway_tool_name="web.click", is_read_only=False,
        )
        tool_call = self._pending_call()

        decision, calls = self._decide(mw, tool, tool_call=tool_call)

        self.assertEqual(decision.behavior, PermissionBehavior.ALLOW)
        self.assertEqual(calls, [])  # built-in resolution never reached
        self.assertEqual(seen, [(tool_call, "web.click")])

    def test_browser_write_without_flow_authority_asks(self) -> None:
        """No live authority ⇒ the signer returns None ⇒ the write parks (ASK)."""
        from agentscope.permission import PermissionBehavior

        signer, seen = self._recording_signer(None)
        mw = GatewayPermissionMiddleware(flow_signer=signer)
        tool = _StubTool(
            "web_click", gateway_tool_name="web.click", is_read_only=False,
        )

        decision, calls = self._decide(mw, tool, tool_call=self._pending_call())

        self.assertEqual(decision.behavior, PermissionBehavior.ASK)
        self.assertEqual(calls, [])
        self.assertEqual(len(seen), 1)  # signer consulted, returned None

    def test_non_browser_write_never_consults_flow_signer(self) -> None:
        """A ``k8s.*`` write is not a browser write: even with a signer that
        would unlock it, the ``BROWSER_WRITE_TOOLS`` guard short-circuits, so
        flow-unlock can never admit a non-browser mutation (signer uncalled)."""
        from agentscope.permission import PermissionBehavior

        envelope = {"execution_id": "e1", "tool_name": "k8s.delete_pod"}
        signer, seen = self._recording_signer(envelope)
        mw = GatewayPermissionMiddleware(flow_signer=signer)
        tool = _StubTool(
            "k8s_delete_pod", gateway_tool_name="k8s.delete_pod", is_read_only=False,
        )

        decision, _ = self._decide(mw, tool, tool_call=self._pending_call())

        self.assertEqual(decision.behavior, PermissionBehavior.ASK)
        self.assertEqual(seen, [])  # never consulted for a non-browser write

    def test_browser_write_fails_safe_when_signer_returns_none(self) -> None:
        """Fail-safe: the kernel signer returns None when ``EXECUTION_REQUESTS``
        is not armed for the turn, so an unlocked-looking write (web.evaluate)
        still parks rather than running unsigned."""
        from agentscope.permission import PermissionBehavior

        signer, seen = self._recording_signer(None)
        mw = GatewayPermissionMiddleware(flow_signer=signer)
        tool = _StubTool(
            "web_evaluate", gateway_tool_name="web.evaluate", is_read_only=False,
        )

        decision, _ = self._decide(mw, tool, tool_call=self._pending_call())

        self.assertEqual(decision.behavior, PermissionBehavior.ASK)
        self.assertEqual(len(seen), 1)

    def test_read_only_browser_probe_uses_allow_list_not_flow_signer(self) -> None:
        """A read-tier probe (web.navigate) is auto-allowed by the static
        read-only allow-list before the flow branch; the signer is never
        consulted, so flow-unlock cannot widen read-tier behavior.

        SPEC-055 R-2 rides on the same fact: the authoring-trace append lives
        *inside* the kernel signer, so an allow-listed read path can never
        reach it and a read-tier call is never captured. The trace-side half
        of that chain (no authority ⇒ the signer fails safe ⇒ nothing
        appended) is asserted in ``test_runtime_kernel``'s
        ``TestAuthoringTraceCapture``."""
        from agentscope.permission import PermissionBehavior

        signer, seen = self._recording_signer(None)
        mw = GatewayPermissionMiddleware(flow_signer=signer)
        tool = _StubTool(
            "web_navigate", gateway_tool_name="web.navigate", is_read_only=True,
        )

        decision, calls = self._decide(mw, tool, tool_call=self._pending_call())

        self.assertEqual(decision.behavior, PermissionBehavior.ALLOW)
        self.assertEqual(calls, [])
        self.assertEqual(seen, [])  # allow-listed read path, signer untouched


# --- R-2: evidence middleware ------------------------------------------------


class ToolEvidenceMiddlewareTests(unittest.TestCase):
    def _gateway_result(self, status="success"):
        result = {
            "tool_name": "k8s.list_pods",
            "status": status,
            "data": {"pods": []},
            "evidence": {
                "executed_at": "2026-08-05T00:00:00+00:00",
                "duration_ms": 42,
                "risk_level": "read",
                "source_system": "kubernetes",
            },
        }
        if status == "error":
            result["error"] = {"code": "K8S_API_ERROR", "message": "timeout"}
        return result

    def _run_on_acting(self, mw, agent, tool_call, items):
        input_kwargs = {"tool_call": tool_call}
        gen = mw.on_acting(agent, input_kwargs, _acting_next(*items))
        return _drain(gen)

    def _with_sink(self, fn):
        queue = asyncio.Queue()

        async def _scope():
            token = TOOL_EVIDENCE_SINK.set(queue)
            try:
                return await fn(queue)
            finally:
                TOOL_EVIDENCE_SINK.reset(token)

        return asyncio.run(_scope())

    def _emit(self, mw, agent, tool_call, items):
        async def _scope(queue):
            gen = mw.on_acting(
                agent, {"tool_call": tool_call}, _acting_next(*items),
            )
            async for _ in gen:
                pass
            events = []
            while not queue.empty():
                events.append(queue.get_nowait())
            return events

        return self._with_sink(_scope)

    def _emit_with_pending(self, mw, agent, tool_call, items, *, held=(), execution_requests=None):
        """Run ``on_acting`` with the delivery buffers armed as the kernel does.

        SPEC-062 R-3 reveal-on-commit: returns ``(events, stream_pending,
        release)`` so a test can assert both what was emitted and what was
        withheld for a deferred reveal. ``held`` pre-loads PENDING_RELEASE (the
        deliveries a prior park carried into a resumed stream); ``execution_requests``
        arms the call_id-keyed approved-execution map the release trigger reads.
        """
        from agent_service.tools.gateway_tools import EXECUTION_REQUESTS

        async def _scope(queue):
            pending_token = STREAM_PENDING_DELIVERIES.set([])
            release_token = PENDING_RELEASE_DELIVERIES.set(list(held))
            requests_token = EXECUTION_REQUESTS.set(execution_requests)
            try:
                gen = mw.on_acting(
                    agent, {"tool_call": tool_call}, _acting_next(*items),
                )
                async for _ in gen:
                    pass
                events = []
                while not queue.empty():
                    events.append(queue.get_nowait())
                return (
                    events,
                    list(STREAM_PENDING_DELIVERIES.get() or []),
                    list(PENDING_RELEASE_DELIVERIES.get() or []),
                )
            finally:
                EXECUTION_REQUESTS.reset(requests_token)
                STREAM_PENDING_DELIVERIES.reset(pending_token)
                PENDING_RELEASE_DELIVERIES.reset(release_token)

        return self._with_sink(_scope)

    def test_emits_tool_call_and_tool_result_frames(self) -> None:
        from agentscope.message import TextBlock
        from agentscope.tool import ToolChunk, ToolResponse

        result = self._gateway_result()
        tool = _StubTool("k8s_list_pods", gateway_tool_name="k8s.list_pods")
        agent = _StubAgent([tool])
        tool_call = _tool_call_block(
            "k8s_list_pods", {"namespace": "test"},
        )
        items = [
            ToolChunk(
                content=[TextBlock(text=json.dumps(result, default=str))],
                metadata={"gateway_result": result},
            ),
            ToolResponse(metadata={"gateway_result": result}),
        ]
        events = self._emit(
            ToolEvidenceMiddleware(), agent, tool_call, items,
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["type"], "tool_call")
        self.assertEqual(events[0]["tool_name"], "k8s.list_pods")
        self.assertEqual(events[0]["parameters"], {"namespace": "test"})
        self.assertIn("call_id", events[0])

        self.assertEqual(events[1]["type"], "tool_result")
        self.assertEqual(events[1]["tool_name"], "k8s.list_pods")
        self.assertEqual(events[1]["status"], "success")
        self.assertEqual(events[1]["call_id"], events[0]["call_id"])
        self.assertEqual(events[1]["evidence"]["duration_ms"], 42)
        self.assertEqual(events[1]["data_summary"], {"pods": []})

    def test_tool_call_frame_masks_a_secret_in_the_arguments(self) -> None:
        """SPEC-049 R-5: the frame is streamed to the portal's evidence panel
        *and* persisted into the evidence store, so a secret the model put in
        an argument (the password-reset demo navigates with ``?newpw=...``)
        must not ride along in plaintext — while the URL shape that makes the
        frame evidence does.
        """
        from agentscope.message import TextBlock
        from agentscope.tool import ToolChunk, ToolResponse

        secret_url = (
            "https://acme-admin/reset?user=alice&newpw=TempPass123%21"
        )
        result = self._gateway_result()
        tool = _StubTool("web_navigate", gateway_tool_name="web.navigate")
        agent = _StubAgent([tool])
        tool_call = _tool_call_block("web_navigate", {"url": secret_url})
        items = [
            ToolChunk(
                content=[TextBlock(text=json.dumps(result, default=str))],
                metadata={"gateway_result": result},
            ),
            ToolResponse(metadata={"gateway_result": result}),
        ]
        events = self._emit(ToolEvidenceMiddleware(), agent, tool_call, items)

        frame = events[0]
        self.assertEqual(frame["type"], "tool_call")
        self.assertEqual(
            frame["parameters"],
            {"url": "https://acme-admin/reset?user=alice&newpw=***"},
        )
        self.assertNotIn("TempPass123", json.dumps(events, default=str))
        # The projection is a copy: the raw ``tool_call`` the resume path
        # digests into ``args_digest`` still carries the real value, so a
        # gateway's signature check is unaffected by what the panel shows.
        self.assertIn("newpw=TempPass123%21", tool_call.input)

    def test_result_projection_mutation_is_detected(self) -> None:
        """R-8: bypass both layers of the result projection, in memory only."""
        from unittest.mock import patch
        from agent_service.services import kernel_middleware

        with (
            patch.object(kernel_middleware, "redact_result_data", lambda name, data: data),
            patch.object(kernel_middleware, "redact_structure", lambda data, literals: data),
            self.assertRaises(AssertionError),
        ):
            self.test_generation_masks_evidence_but_preserves_model_result()

    def test_generation_masks_evidence_but_preserves_model_result(self) -> None:
        from agentscope.tool import ToolResponse
        from agent_service.api.v2.routes import _normalize_stream_event
        from agent_service.services.prose_redaction import CURRENT_PROSE_REDACTOR, StreamingProseRedactor
        from test_contract_adapter import load_schema
        import jsonschema

        secret = "aZ8***&+randomValue"
        result = {
            "tool_name": "secrets.generate_password", "status": "success",
            "data": {
                "generated_password": secret, "note": secret,
                "delivery_id": "51b1935c-60ed-4eec-926b-8bff529df501",
                "channel": "portal_copy", "expires_at": "2099-01-01T00:00:00+00:00",
            },
        }
        agent = _StubAgent([_StubTool("secrets_generate_password", gateway_tool_name="secrets.generate_password")])
        token = CURRENT_PROSE_REDACTOR.set(StreamingProseRedactor())
        try:
            events, stream_pending, release = self._emit_with_pending(
                ToolEvidenceMiddleware(data_max_chars=1), agent,
                _tool_call_block("secrets_generate_password", {}),
                [ToolResponse(metadata={"gateway_result": result})],
            )
            self.assertIn(secret, CURRENT_PROSE_REDACTOR.get().literals)
        finally:
            CURRENT_PROSE_REDACTOR.reset(token)
        self.assertEqual(result["data"]["generated_password"], secret)
        self.assertEqual(events[1]["data_summary"]["generated_password"], "***")
        self.assertNotIn(secret, json.dumps(events))
        self.assertNotIn("data", events[1])
        # SPEC-062 R-3 reveal-on-commit: generation NO LONGER emits the frame
        # inline. Only tool_call + tool_result are streamed; the portal_copy
        # handle is withheld into the per-stream buffer for a deferred reveal,
        # and the buffered handle carries metadata only, never the value.
        self.assertEqual([e["type"] for e in events], ["tool_call", "tool_result"])
        self.assertEqual(
            stream_pending,
            [{
                "delivery_id": "51b1935c-60ed-4eec-926b-8bff529df501",
                "channel": "portal_copy",
                "expires_at": "2099-01-01T00:00:00+00:00",
            }],
        )
        self.assertEqual(release, [])
        self.assertNotIn(secret, json.dumps(stream_pending))
        # The deferred frame the buffer will eventually emit is schema-valid and
        # carries only delivery metadata.
        deferred = {"type": "secret_delivery", **stream_pending[0]}
        wire = _normalize_stream_event(deferred, "ses", "req").model_dump(exclude_none=True)
        jsonschema.validate(wire, load_schema("agent-stream-event.schema.json"))
        self.assertEqual(wire["type"], "secret_delivery")
        for event in events:
            wire = _normalize_stream_event(event, "ses", "req").model_dump(exclude_none=True)
            jsonschema.validate(wire, load_schema("agent-stream-event.schema.json"))

    def test_held_delivery_released_on_gated_success(self) -> None:
        """SPEC-062 R-3 reveal-on-commit: a successful tool_result whose call_id
        is in the approved EXECUTION_REQUESTS map releases the held delivery as a
        secret_delivery frame and clears the buffer."""
        from agentscope.tool import ToolResponse

        held = {
            "delivery_id": "51b1935c-60ed-4eec-926b-8bff529df501",
            "channel": "portal_copy",
            "expires_at": "2099-01-01T00:00:00+00:00",
        }
        result = {"tool_name": "web.click", "status": "success", "data": {"ok": True}}
        agent = _StubAgent([_StubTool("web_click", gateway_tool_name="web.click")])
        events, stream_pending, release = self._emit_with_pending(
            ToolEvidenceMiddleware(), agent,
            _tool_call_block("web_click", {}, call_id="gated-1"),
            [ToolResponse(metadata={"gateway_result": result})],
            held=[held],
            execution_requests={"gated-1": {"call_id": "gated-1"}},
        )
        self.assertEqual(
            [e for e in events if e["type"] == "secret_delivery"],
            [{"type": "secret_delivery", **held}],
        )
        self.assertEqual(release, [])  # cleared after release
        self.assertEqual(stream_pending, [])

    def test_held_delivery_not_released_on_gated_failure(self) -> None:
        """A gated call that FAILS reveals nothing; the delivery stays held (and
        burns at expiry) — the deny/failure posture."""
        from agentscope.tool import ToolResponse

        held = {
            "delivery_id": "51b1935c-60ed-4eec-926b-8bff529df501",
            "channel": "portal_copy",
            "expires_at": "2099-01-01T00:00:00+00:00",
        }
        result = {
            "tool_name": "web.click", "status": "error",
            "error": {"code": "UPSTREAM_ERROR", "message": "reset failed"},
        }
        agent = _StubAgent([_StubTool("web_click", gateway_tool_name="web.click")])
        events, _stream_pending, release = self._emit_with_pending(
            ToolEvidenceMiddleware(), agent,
            _tool_call_block("web_click", {}, call_id="gated-1"),
            [ToolResponse(metadata={"gateway_result": result})],
            held=[held],
            execution_requests={"gated-1": {"call_id": "gated-1"}},
        )
        self.assertFalse(any(e["type"] == "secret_delivery" for e in events))
        self.assertEqual(release, [held])  # still held, not released

    def test_held_delivery_not_released_when_call_not_gated(self) -> None:
        """A successful call that is NOT in the approved execution map (e.g. a
        read-tier probe during the resumed turn) reveals nothing."""
        from agentscope.tool import ToolResponse

        held = {
            "delivery_id": "51b1935c-60ed-4eec-926b-8bff529df501",
            "channel": "portal_copy",
            "expires_at": "2099-01-01T00:00:00+00:00",
        }
        result = {"tool_name": "web.snapshot", "status": "success", "data": {}}
        agent = _StubAgent([_StubTool("web_snapshot", gateway_tool_name="web.snapshot")])
        events, _stream_pending, release = self._emit_with_pending(
            ToolEvidenceMiddleware(), agent,
            _tool_call_block("web_snapshot", {}, call_id="probe-1"),
            [ToolResponse(metadata={"gateway_result": result})],
            held=[held],
            execution_requests={"gated-1": {"call_id": "gated-1"}},
        )
        self.assertFalse(any(e["type"] == "secret_delivery" for e in events))
        self.assertEqual(release, [held])

    def test_tool_result_frame_includes_error_on_failure(self) -> None:
        from agentscope.tool import ToolResponse

        result = self._gateway_result(status="error")
        tool = _StubTool("k8s_list_pods", gateway_tool_name="k8s.list_pods")
        agent = _StubAgent([tool])
        tool_call = _tool_call_block("k8s_list_pods", {})
        events = self._emit(
            ToolEvidenceMiddleware(),
            agent,
            tool_call,
            [ToolResponse(metadata={"gateway_result": result})],
        )
        self.assertEqual(events[1]["status"], "error")
        self.assertEqual(events[1]["error"]["code"], "K8S_API_ERROR")

    def test_data_summary_truncated_in_tool_result_frame(self) -> None:
        from agentscope.tool import ToolResponse

        result = {
            "tool_name": "k8s.list_pods",
            "status": "success",
            "data": {"pods": [{"name": "web-1"}] * 20},
        }
        tool = _StubTool("k8s_list_pods", gateway_tool_name="k8s.list_pods")
        agent = _StubAgent([tool])
        tool_call = _tool_call_block("k8s_list_pods", {})
        mw = ToolEvidenceMiddleware(data_summary_max_chars=50)
        events = self._emit(
            mw, agent, tool_call,
            [ToolResponse(metadata={"gateway_result": result})],
        )
        summary = events[1]["data_summary"]
        self.assertTrue(summary["_truncated"])
        self.assertEqual(len(summary["_preview"]), 50)

    def test_tool_result_frame_carries_full_data_within_cap(self) -> None:
        from agentscope.tool import ToolResponse

        result = self._gateway_result()
        tool = _StubTool("k8s_list_pods", gateway_tool_name="k8s.list_pods")
        agent = _StubAgent([tool])
        tool_call = _tool_call_block("k8s_list_pods", {})
        events = self._emit(
            ToolEvidenceMiddleware(), agent, tool_call,
            [ToolResponse(metadata={"gateway_result": result})],
        )
        self.assertEqual(events[1]["data"], {"pods": []})

    def test_tool_result_frame_omits_full_data_when_oversized(self) -> None:
        from agentscope.tool import ToolResponse

        result = self._gateway_result()
        result["data"] = {"logs": "x" * 5000}
        tool = _StubTool("k8s_list_pods", gateway_tool_name="k8s.list_pods")
        agent = _StubAgent([tool])
        tool_call = _tool_call_block("k8s_list_pods", {})
        events = self._emit(
            ToolEvidenceMiddleware(data_max_chars=100), agent, tool_call,
            [ToolResponse(metadata={"gateway_result": result})],
        )
        # The frame stays bounded: no full payload, truncated summary only.
        self.assertNotIn("data", events[1])
        self.assertTrue(events[1]["data_summary"]["_truncated"])

    def test_no_frames_when_sink_unset(self) -> None:
        """Blocking turns (reply_text) never set the sink: the middleware
        passes items through and emits nothing."""
        from agentscope.tool import ToolResponse

        result = self._gateway_result()
        tool = _StubTool("k8s_list_pods", gateway_tool_name="k8s.list_pods")
        agent = _StubAgent([tool])
        tool_call = _tool_call_block("k8s_list_pods", {})
        items = [ToolResponse(metadata={"gateway_result": result})]
        yielded = self._run_on_acting(
            ToolEvidenceMiddleware(), agent, tool_call, items,
        )
        self.assertEqual(yielded, items)

    def test_non_gateway_tool_passes_through_silently(self) -> None:
        """Task tools and builtins emit no evidence frames (parity: only
        gateway closures traced before the middleware migration)."""
        from agentscope.tool import ToolResponse

        tool = _StubTool("TaskCreate", is_read_only=False)
        agent = _StubAgent([tool])
        tool_call = _tool_call_block("TaskCreate", {})
        items = [ToolResponse()]
        events = self._emit(
            ToolEvidenceMiddleware(), agent, tool_call, items,
        )
        self.assertEqual(events, [])

    def test_missing_gateway_result_keeps_frame_schema_valid(self) -> None:
        from agentscope.tool import ToolResponse

        tool = _StubTool("k8s_list_pods", gateway_tool_name="k8s.list_pods")
        agent = _StubAgent([tool])
        tool_call = _tool_call_block("k8s_list_pods", {})
        events = self._emit(
            ToolEvidenceMiddleware(), agent, tool_call, [ToolResponse()],
        )
        self.assertEqual(events[1]["status"], "error")
        self.assertIsNone(events[1]["data_summary"])


class EvidenceFrameSchemaParityTests(unittest.TestCase):
    """Emitted frames validate against agent-stream-event.schema.json
    (SPEC-018 R-2 contract test; the schema file is unmodified)."""

    def test_frames_conform_to_stream_event_schema(self) -> None:
        from agentscope.tool import ToolResponse

        schema = _load_schema("agent-stream-event.schema.json")
        result = {
            "tool_name": "k8s.list_pods",
            "status": "success",
            "data": {"pods": []},
            "evidence": {
                "executed_at": "2026-08-05T00:00:00+00:00",
                "duration_ms": 42,
                "risk_level": "read",
                "source_system": "kubernetes",
            },
        }
        tool = _StubTool("k8s_list_pods", gateway_tool_name="k8s.list_pods")
        agent = _StubAgent([tool])
        tool_call = _tool_call_block("k8s_list_pods", {"namespace": "test"})

        mw = ToolEvidenceMiddleware()

        async def _scope(queue):
            token = TOOL_EVIDENCE_SINK.set(queue)
            try:
                gen = mw.on_acting(
                    agent, {"tool_call": tool_call},
                    _acting_next(ToolResponse(
                        metadata={"gateway_result": result},
                    )),
                )
                async for _ in gen:
                    pass
            finally:
                TOOL_EVIDENCE_SINK.reset(token)

        queue = asyncio.Queue()
        asyncio.run(_scope(queue))

        # stream_events decorates each frame with request/session ids.
        while not queue.empty():
            frame = queue.get_nowait()
            decorated = {
                **frame, "request_id": "req-1", "session_id": "ses-1",
            }
            jsonschema.validate(decorated, schema)


# --- R-3/R-4/R-5: settings-driven middleware + task tool composition --------


class MiddlewareCompositionTests(unittest.TestCase):
    def _kernel(self, **overrides):
        from agent_service.runtime_kernel import AgentKernel
        from agent_service.runtime_settings import RuntimeSettings

        return AgentKernel(
            settings=RuntimeSettings(api_key="test-key", **overrides),
        )

    def test_default_stack_is_permission_evidence_and_tokens(self) -> None:
        kernel = self._kernel()
        middlewares = kernel._build_middlewares()
        # SPEC-065 R-1: the always-on token middleware joins the two SPEC-018
        # base middlewares (permission + evidence) with no opt-in knob.
        self.assertEqual(len(middlewares), 3)
        self.assertIsInstance(middlewares[0], GatewayPermissionMiddleware)
        self.assertIsInstance(middlewares[1], ToolEvidenceMiddleware)
        self.assertIsInstance(middlewares[2], TokenUsageMiddleware)

    def test_kernel_tracing_adds_tracing_middleware(self) -> None:
        from agentscope.middleware import TracingMiddleware

        kernel = self._kernel(kernel_tracing=True)
        middlewares = kernel._build_middlewares()
        self.assertTrue(
            any(isinstance(mw, TracingMiddleware) for mw in middlewares),
        )

    def test_budget_adds_reply_budget_middleware(self) -> None:
        from agentscope.middleware import ReplyBudgetControlMiddleware

        kernel = self._kernel(
            reply_token_budget=1000.0,
            reply_input_token_weight=0.5,
            reply_output_token_weight=2.0,
        )
        middlewares = kernel._build_middlewares()
        budget = [
            mw for mw in middlewares
            if isinstance(mw, ReplyBudgetControlMiddleware)
        ]
        self.assertEqual(len(budget), 1)
        self.assertEqual(budget[0].token_budget, 1000.0)
        self.assertEqual(budget[0].input_token_weight, 0.5)
        self.assertEqual(budget[0].output_token_weight, 2.0)

    def test_budget_unset_adds_no_budget_middleware(self) -> None:
        from agentscope.middleware import ReplyBudgetControlMiddleware

        kernel = self._kernel()
        self.assertFalse(
            any(
                isinstance(mw, ReplyBudgetControlMiddleware)
                for mw in kernel._build_middlewares()
            ),
        )

    def test_task_tools_registered_when_enabled(self) -> None:
        kernel = self._kernel(task_tools_enabled=True)
        names = {tool.name for tool in kernel._build_task_tools()}
        self.assertEqual(names, TASK_TOOL_NAMES)

    def test_task_tools_absent_when_disabled(self) -> None:
        kernel = self._kernel()
        self.assertFalse(kernel.settings.task_tools_enabled)

    def test_evidence_middleware_receives_summary_limit(self) -> None:
        kernel = self._kernel(tool_data_summary_max_chars=123)
        evidence = [
            mw for mw in kernel._build_middlewares()
            if isinstance(mw, ToolEvidenceMiddleware)
        ][0]
        self.assertEqual(evidence._max_chars, 123)

    def test_evidence_middleware_receives_full_data_limit(self) -> None:
        kernel = self._kernel(tool_data_max_chars=456)
        evidence = [
            mw for mw in kernel._build_middlewares()
            if isinstance(mw, ToolEvidenceMiddleware)
        ][0]
        self.assertEqual(evidence._data_max_chars, 456)


class SecretReleasePermitGateTests(unittest.TestCase):
    """SPEC-063 R-4: ``ToolEvidenceMiddleware._permit_secret_release`` gates a
    held portal_copy reveal. Legacy (no bound guard) releases on the existing
    status+membership trigger; v3 (guard bound) additionally requires consuming
    a single-use permit minted from a durably accepted original success, with a
    final run-latch re-check immediately before emission."""

    def _gate(self, call_id="call-1"):
        return ToolEvidenceMiddleware._permit_secret_release(call_id)

    def _guard(self, *, stopped=False):
        from agent_service.services.execution_run_guard import (
            RunGuard,
            RunIdentity,
            RunStopLatch,
        )

        latch = RunStopLatch()
        guard = RunGuard(RunIdentity("run-1", "ses-1", "alice"), latch=latch)
        if stopped:
            guard.mark_stopped("wait_expired")
        return guard

    def _permit(self):
        class _Permit:
            def __init__(self):
                self.consumed = False

            def consume(self):
                if self.consumed:
                    raise TypeError("secret-release permit is single-use")
                self.consumed = True

        return _Permit()

    def test_no_guard_releases_on_the_legacy_trigger(self) -> None:
        # No CURRENT_RUN_GUARD bound => the permit gate is inert and the
        # status+membership trigger alone decides (legacy path unchanged).
        self.assertTrue(self._gate())

    def test_v3_without_a_permit_withholds(self) -> None:
        from agent_service.services.execution_run_guard import CURRENT_RUN_GUARD
        from agent_service.services.kernel_middleware import RELEASE_PERMITS

        gtoken = CURRENT_RUN_GUARD.set(self._guard())
        ptoken = RELEASE_PERMITS.set({})
        try:
            self.assertFalse(self._gate())
        finally:
            RELEASE_PERMITS.reset(ptoken)
            CURRENT_RUN_GUARD.reset(gtoken)

    def test_v3_with_a_permit_consumes_once_and_releases(self) -> None:
        from agent_service.services.execution_run_guard import CURRENT_RUN_GUARD
        from agent_service.services.kernel_middleware import RELEASE_PERMITS

        permit = self._permit()
        gtoken = CURRENT_RUN_GUARD.set(self._guard())
        ptoken = RELEASE_PERMITS.set({"call-1": permit})
        try:
            self.assertTrue(self._gate())
            self.assertTrue(permit.consumed)
            self.assertNotIn("call-1", RELEASE_PERMITS.get())
            # Spent and popped: a second reveal for the same call withholds.
            self.assertFalse(self._gate())
        finally:
            RELEASE_PERMITS.reset(ptoken)
            CURRENT_RUN_GUARD.reset(gtoken)

    def test_v3_stopped_run_withholds_and_does_not_consume(self) -> None:
        from agent_service.services.execution_run_guard import CURRENT_RUN_GUARD
        from agent_service.services.kernel_middleware import RELEASE_PERMITS

        permit = self._permit()
        gtoken = CURRENT_RUN_GUARD.set(self._guard(stopped=True))
        ptoken = RELEASE_PERMITS.set({"call-1": permit})
        try:
            self.assertFalse(self._gate())
            # The latch re-check precedes consumption, so the permit survives.
            self.assertFalse(permit.consumed)
            self.assertIn("call-1", RELEASE_PERMITS.get())
        finally:
            RELEASE_PERMITS.reset(ptoken)
            CURRENT_RUN_GUARD.reset(gtoken)

    def test_v3_spent_permit_withholds(self) -> None:
        from agent_service.services.execution_run_guard import CURRENT_RUN_GUARD
        from agent_service.services.kernel_middleware import RELEASE_PERMITS

        permit = self._permit()
        permit.consume()  # already spent before the reveal is attempted
        gtoken = CURRENT_RUN_GUARD.set(self._guard())
        ptoken = RELEASE_PERMITS.set({"call-1": permit})
        try:
            self.assertFalse(self._gate())
        finally:
            RELEASE_PERMITS.reset(ptoken)
            CURRENT_RUN_GUARD.reset(gtoken)


# --- SPEC-065 R-1: LLM token usage middleware -------------------------------


def _usage(
    input_tokens=0,
    output_tokens=0,
    cache_input_tokens=0,
    cache_creation_input_tokens=0,
):
    """Stand-in for agentscope's ChatUsage (attribute names match 2.0.8)."""
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_input_tokens=cache_input_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
    )


def _model_next_response(response):
    """A ``next_handler`` returning a non-streaming ChatResponse stand-in."""

    async def next_handler(**kwargs):
        return response

    return next_handler


def _model_next_stream(chunks):
    """A ``next_handler`` returning an async generator of chunks (streaming)."""

    async def next_handler(**kwargs):
        async def _gen():
            for chunk in chunks:
                yield chunk

        return _gen()

    return next_handler


class _StubCatalog:
    """Minimal ``MODEL_CATALOG`` stand-in: ``get(model_id) -> entry | None``."""

    def __init__(self, entries):
        self._entries = entries  # model_id -> (provider, model_name)

    def get(self, model_id):
        hit = self._entries.get(model_id)
        if hit is None:
            return None
        provider, model_name = hit
        return SimpleNamespace(provider=provider, model_name=model_name)


def _tokens(provider, model, direction):
    return REGISTRY.get_sample_value(
        "agent_llm_tokens_total",
        {"provider": provider, "model": model, "direction": direction},
    ) or 0.0


class TokenUsageMiddlewareTests(unittest.TestCase):
    """SPEC-065 R-1: ``agent_llm_tokens_total`` via the ``on_model_call`` hook."""

    def setUp(self):
        self.catalog = _StubCatalog({"qwen-plus": ("dashscope", "qwen-plus")})
        self.model = SimpleNamespace(model="qwen-plus")
        self.agent = SimpleNamespace()
        self.mw = TokenUsageMiddleware(catalog=self.catalog)

    def _drive(self, next_handler, current_model=None):
        """Run ``on_model_call`` and drain a stream in ONE loop.

        Returns ``(result, drained_items_or_None)``.
        """
        model = self.model if current_model is None else current_model

        async def _go():
            result = await self.mw.on_model_call(
                self.agent, {"current_model": model}, next_handler,
            )
            if hasattr(result, "__aiter__"):
                return result, [item async for item in result]
            return result, None

        return asyncio.run(_go())

    def test_non_streaming_records_all_directions(self):
        response = SimpleNamespace(
            usage=_usage(input_tokens=5352, output_tokens=1, cache_input_tokens=5120),
        )
        before = {
            d: _tokens("dashscope", "qwen-plus", d)
            for d in ("input", "output", "cache_input", "cache_creation")
        }
        result, drained = self._drive(_model_next_response(response))
        self.assertIs(result, response)  # passthrough, unaltered
        self.assertIsNone(drained)
        self.assertEqual(_tokens("dashscope", "qwen-plus", "input"), before["input"] + 5352)
        self.assertEqual(_tokens("dashscope", "qwen-plus", "output"), before["output"] + 1)
        self.assertEqual(_tokens("dashscope", "qwen-plus", "cache_input"), before["cache_input"] + 5120)
        # A zero cache_creation count records nothing (no empty-series churn).
        self.assertEqual(_tokens("dashscope", "qwen-plus", "cache_creation"), before["cache_creation"])

    def test_streaming_records_terminal_chunk_usage(self):
        chunks = [
            SimpleNamespace(usage=None),
            SimpleNamespace(usage=None),
            SimpleNamespace(usage=_usage(input_tokens=100, output_tokens=7)),
        ]
        before_in = _tokens("dashscope", "qwen-plus", "input")
        before_out = _tokens("dashscope", "qwen-plus", "output")
        result, drained = self._drive(_model_next_stream(chunks))
        self.assertIsNotNone(drained)
        self.assertEqual(len(drained), 3)  # every chunk passed through
        self.assertEqual(drained, chunks)
        self.assertEqual(_tokens("dashscope", "qwen-plus", "input"), before_in + 100)
        self.assertEqual(_tokens("dashscope", "qwen-plus", "output"), before_out + 7)

    def test_streaming_naive_nongenerator_read_records_nothing(self):
        # The chat path streams: a naive read that treats the returned stream
        # like a ChatResponse sees no ``.usage`` and records zero. Only draining
        # the generator books the terminal-chunk usage.
        chunks = [SimpleNamespace(usage=_usage(input_tokens=42, output_tokens=3))]
        before = _tokens("dashscope", "qwen-plus", "input")

        async def _go():
            stream = await self.mw.on_model_call(
                self.agent, {"current_model": self.model}, _model_next_stream(chunks),
            )
            naive = getattr(stream, "usage", None)  # the mistake
            undrained = _tokens("dashscope", "qwen-plus", "input")
            items = [chunk async for chunk in stream]  # the fix
            return naive, undrained, len(items)

        naive, undrained, count = asyncio.run(_go())
        self.assertIsNone(naive)
        self.assertEqual(undrained, before)  # nothing recorded before draining
        self.assertEqual(count, 1)
        self.assertEqual(_tokens("dashscope", "qwen-plus", "input"), before + 42)

    def test_usage_less_response_records_nothing(self):
        response = SimpleNamespace(usage=None)
        before = {
            d: _tokens("dashscope", "qwen-plus", d)
            for d in ("input", "output", "cache_input", "cache_creation")
        }
        self._drive(_model_next_response(response))
        for d in ("input", "output", "cache_input", "cache_creation"):
            self.assertEqual(_tokens("dashscope", "qwen-plus", d), before[d])

    def test_uncatalogued_model_uses_unknown_sentinel(self):
        rogue = SimpleNamespace(model="some-uncatalogued-model")
        response = SimpleNamespace(usage=_usage(input_tokens=9, output_tokens=1))
        before = _tokens("unknown", "unknown", "input")
        self._drive(_model_next_response(response), current_model=rogue)
        self.assertEqual(_tokens("unknown", "unknown", "input"), before + 9)
        # The uncatalogued model name must NOT leak into a label value.
        self.assertEqual(_tokens("unknown", "some-uncatalogued-model", "input"), 0.0)

    def test_model_without_a_name_is_unknown(self):
        nameless = SimpleNamespace()  # no ``.model`` attribute
        response = SimpleNamespace(usage=_usage(input_tokens=4, output_tokens=1))
        before = _tokens("unknown", "unknown", "input")
        self._drive(_model_next_response(response), current_model=nameless)
        self.assertEqual(_tokens("unknown", "unknown", "input"), before + 4)

    def test_label_set_is_bounded_and_carries_no_ids(self):
        # Drive one recording so the family has a child series to introspect.
        self._drive(_model_next_response(SimpleNamespace(usage=_usage(input_tokens=1))))
        label_names = set()
        directions = set()
        for family in REGISTRY.collect():
            for sample in family.samples:
                if sample.name == "agent_llm_tokens_total":
                    label_names = set(sample.labels.keys())
                    directions.add(sample.labels["direction"])
        # Exactly the bounded label set — and never a high-cardinality id.
        self.assertEqual(label_names, {"provider", "model", "direction"})
        for forbidden in ("session_id", "user_id", "request_id"):
            self.assertNotIn(forbidden, label_names)
        # Every emitted direction stays inside the declared enum.
        self.assertTrue(directions.issubset(set(LLM_TOKEN_DIRECTIONS)))

    def test_no_cost_metric_is_emitted(self):
        # SPEC-065 Stage-0: cost is deferred; no cost counter may exist.
        sample_names = {s.name for m in REGISTRY.collect() for s in m.samples}
        self.assertFalse(
            any(name.startswith("agent_llm_cost_usd") for name in sample_names),
            "a cost metric must not be emitted (deferred per SPEC-065 Stage-0)",
        )


if __name__ == "__main__":
    unittest.main()
