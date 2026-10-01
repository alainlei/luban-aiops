"""Drive the real agent invocation seam against a live worker, without an LLM.

This probe launches the *actual* product code paths that a resumed mutating turn
exercises when durable admission is enabled:

* ``gateway_tools._make_tool_fn`` -> ``tool_fn`` -> ``_invoke_v3``
* ``execution_invocation.coordinate_v3_invocation`` (register -> handoff_original
  -> durably accept -> mint the single-use secret-release permit)
* ``ToolEvidenceMiddleware.on_acting`` including the SPEC-063 R-4 secret-release
  permit gate (``_permit_secret_release``).

Nothing about policy/HITL or the middleware release seam is mocked away; the only
substitution is the model, replaced by one deterministic scripted tool call. Only
bounded, safe facts leave this process (counts, closed enums, ids, digests) — never
raw tool output, secret material, or exception text — so the parent test can assert
on them and write an allowlisted evidence record.

It is the cross-product sibling of ``agent_ledger_probe.py`` (pure ledger ops) and
``agent_release_probe.py`` (middleware release predicate in isolation).
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from types import SimpleNamespace
from uuid import uuid4

os.environ["OTEL_SDK_DISABLED"] = "true"
logging.disable(logging.CRITICAL)

from agentscope.message import ToolCallBlock
from agentscope.tool import ToolResponse

from agent_service.services.execution_protocol import ProtocolError, iso
from agent_service.services.execution_recovery import ExecutionRecovery
from agent_service.services.execution_run_guard import CURRENT_RUN_GUARD, bind_run
from agent_service.services.execution_signing import build_requests, sign_envelope
from agent_service.services.execution_worker_client import handoff_original
from agent_service.services.hitl_confirmations import ConfirmationRegistry
from agent_service.services.kernel_middleware import (
    PENDING_RELEASE_DELIVERIES, RELEASE_PERMITS, TOOL_EVIDENCE_SINK,
    ToolEvidenceMiddleware,
)
from agent_service.tools.gateway_tools import (
    DELEGATED_TOKEN, EXECUTION_AUDIT_CONTEXT, EXECUTION_REQUESTS, _make_tool_fn,
)

# Launched as a script, so its own directory is already sys.path[0]; the explicit
# insert also keeps this import working under ``python -m``. host_clock is
# stdlib-only at import time, so sharing it costs the agent venv nothing.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import host_clock


def _settings(data):
    return SimpleNamespace(
        execution_signing_key=data["key"],
        execution_handoff_token=data["key"],
        execution_worker_url=data.get("worker_url", ""),
        execution_worker_timeout_seconds=data.get("timeout", 10),
        execution_gateway_url=data.get("gateway_url", ""),
    )


def _sign(data, recovery, run_id, session_id, owner, decider, call_id):
    """Sign one action envelope through the real preparation path."""
    tool_name = data.get("tool_name", "test.increment")
    parameters = data.get("parameters", {})
    pending = ConfirmationRegistry().register(
        session_id, owner, "probe-reply",
        [ToolCallBlock(id=call_id, name=tool_name, input=json.dumps(parameters))], 600)
    envelope = build_requests(pending, decider, data["key"], run_id=run_id,
                              admission_epoch=data["epoch"], lifetime_seconds=900)[0]
    # Admission compares requested_at against the DATABASE clock, so a
    # host-stamped requested_at reads as request_not_yet_valid on a live
    # cross-product run. Measure that offset instead of budgeting for it. This
    # probe runs in its own interpreter under the agent venv, so it cannot
    # inherit the harness-wide clock and measures against its own dsn, which is
    # the live store; the outage legs pass an unreachable recovery_dsn instead.
    # Lifetime stays under the 900s max.
    offset = host_clock.measure(host_clock.dsn_query(data["dsn"]))
    database_now = datetime.now(timezone.utc) + timedelta(seconds=offset)
    backdated = database_now - timedelta(seconds=data.get("backdate_seconds", 30))
    envelope["requested_at"] = iso(backdated)
    envelope["expires_at"] = iso(backdated + timedelta(seconds=600))
    envelope["signature"] = sign_envelope(envelope, data["key"])
    return envelope, tool_name, parameters


async def _invoke(data):
    log_probe = None
    if data.get("canaries"):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from support.processes import CanaryLogProbe
        log_probe = CanaryLogProbe(data["canaries"])
        log_probe.install()
    dsn = data.get("recovery_dsn", data["dsn"])
    recovery = ExecutionRecovery(dsn, data["key"], data["epoch"], admission_enabled=True)
    session_id = data.get("session_id") or str(uuid4())
    owner = data.get("owner_user_id", "test-owner")
    decider = data.get("decider_user_id", "test-decider")
    call_id = data.get("call_id") or str(uuid4())
    attempt_request_id = data.get("attempt_request_id", "agent-original")
    # The disposable harness uses one token for the handoff auth, the signing
    # key, and the gateway/target auth, so the delegated credential defaults to
    # it (mirroring support.ledger.body). A test may still override it.
    delegated = data.get("delegated_token", data["key"])
    read_only = bool(data.get("read_only"))

    run_id = data.get("run_id")
    execution_id = None
    if read_only:
        # A read-tier call keeps its existing direct gateway path: no run, no
        # admission, no ledger. F-18 proves reads stay available during an outage.
        envelope = None
        tool_name = data.get("tool_name", "test.increment")
        parameters = data.get("parameters", {})
        guard = None
    else:
        if run_id is None:
            run_id = recovery.create_run(session_id, owner)
        envelope, tool_name, parameters = _sign(data, recovery, run_id, session_id,
                                                owner, decider, call_id)
        execution_id = envelope["execution_id"]
        guard = bind_run(recovery, session_id, owner, run_id=run_id)
        if data.get("pre_stopped"):
            guard.durable_stop("run_stopped")

    settings = _settings(data)
    observe_original = None
    trace = None
    if data.get("authoring"):
        from agent_service import runtime_kernel
        from agent_service.services.authoring_trace import PostgresAuthoringTraceStore, make_trace_step
        trace = PostgresAuthoringTraceStore(data["dsn"])
        trace.initialize()
        assert trace.append_step(make_trace_step(
            session_id=session_id, tool_name=tool_name, args=parameters,
            execution_id=execution_id, confirm_id=envelope["confirm_id"],
            captured_at=envelope["requested_at"]))
        runtime_kernel.AUTHORING_TRACE_STORE = trace
        from agent_service.runtime_settings import RuntimeSettings
        kernel = runtime_kernel.AgentKernel(settings=RuntimeSettings(execution_signing_key=data["key"]))
        observe_original = kernel._observe_original_step_origin
    # F-23 replay: prime the claim+receipt through the *real* coordinator steps
    # (register, then one durable handoff) so the middleware pass below re-hands
    # the same envelope and the worker answers metadata-only (status_only). The
    # agent then classifies metadata_replay -> uncertainty, mints no permit, and
    # the held delivery is never released. Inert unless ``replay`` is requested.
    if data.get("replay") and guard is not None:
        guard.recovery.register(envelope, attempt_request_id)
        await handoff_original(envelope, parameters, delegated, settings, attempt_request_id)
    frames = []

    class Sink:
        async def put(self, frame):
            frames.append(frame)

    held = {"delivery_id": data.get("delivery_id") or str(uuid4()), "channel": "portal_copy",
            "expires_at": "2099-01-01T00:00:00Z"}
    tool_fn = _make_tool_fn(data.get("gateway_url") or data.get("worker_url", ""),
                            tool_name, "probe tool", is_read_only=read_only)
    call = ToolCallBlock(id=call_id, name=tool_name, input=json.dumps(parameters))
    agent = SimpleNamespace(toolkit=SimpleNamespace(tool_groups=[
        SimpleNamespace(tools=[SimpleNamespace(name=tool_name, gateway_tool_name=tool_name)])]))

    original_results = []
    signing_input = json.dumps(parameters, sort_keys=True)

    async def next_handler(**_kwargs):
        chunk = await tool_fn(**parameters)
        if data.get("canaries"):
            original_results.append((chunk.metadata or {}).get("gateway_result"))
        # F-23 release_race: the tool durably succeeded and _invoke_v3 stashed a
        # real single-use permit, but a stop lands before the middleware emits the
        # held delivery. The permit gate re-checks the latch immediately before
        # emission, so the reveal is barred and the permit burns unconsumed.
        if data.get("stop_before_release") and guard is not None:
            guard.mark_stopped("wait_expired")
        yield ToolResponse(content=chunk.content, metadata=chunk.metadata)

    permits: dict = {}
    tokens = [
        (TOOL_EVIDENCE_SINK, TOOL_EVIDENCE_SINK.set(Sink())),
        (PENDING_RELEASE_DELIVERIES, PENDING_RELEASE_DELIVERIES.set([held] if data.get("held") else [])),
        (RELEASE_PERMITS, RELEASE_PERMITS.set(permits)),
        (DELEGATED_TOKEN, DELEGATED_TOKEN.set(delegated)),
        (EXECUTION_REQUESTS, EXECUTION_REQUESTS.set({call_id: envelope} if envelope else {})),
        (EXECUTION_AUDIT_CONTEXT, EXECUTION_AUDIT_CONTEXT.set({
            "settings": settings, "request_id": attempt_request_id,
            "observe_original": observe_original,
            "confirm_id": envelope["confirm_id"] if envelope else None,
            "session_id": session_id, "owner_user_id": owner, "decider_user_id": decider})),
    ]
    if guard is not None:
        tokens.append((CURRENT_RUN_GUARD, CURRENT_RUN_GUARD.set(guard)))
    try:
        async for _ in ToolEvidenceMiddleware().on_acting(agent, {"tool_call": call}, next_handler):
            pass
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)

    result_frame = next((f for f in frames if f.get("type") == "tool_result"), {})
    release_count = sum(1 for f in frames if f.get("type") == "secret_delivery")
    facts = {
        "run_id": run_id, "execution_id": execution_id, "call_id": call_id,
        "session_id": session_id, "request_id": attempt_request_id,
        "frame_status": result_frame.get("status"),
        "error_code": (result_frame.get("error") or {}).get("code"),
        "release_count": release_count,
        "permit_remaining": len(permits),
        "guard_stopped": bool(guard.stopped()) if guard is not None else False,
    }
    if trace is not None:
        from agent_service.services.skill_graduation import revalidate_blast_radius
        steps = trace.load_for_session(session_id)
        assert len(steps) == 1
        assert "origin-query-canary" not in json.dumps(steps)
        facts["origin_recorded"] = steps[0]["flow_origin"] == "https://admin.test"
        facts["graduable"] = revalidate_blast_radius(
            steps, target="https://admin.test",
            recovery_page=recovery.owner_session_recovery(session_id, owner)).graduable
    if execution_id is not None:
        view = recovery.lookup(execution_id)
        facts.update({
            "recovery_availability": view["availability"],
            "recovery_state": view["state"],
            "recovery_run_stopped": view["run_stopped"],
            "receipt_status": (view.get("receipt") or {}).get("status"),
            "target_verification_required": view["target_verification_required"],
            "observation_kinds": sorted({f["kind"] for f in view["observations"]}),
        })
    if log_probe is not None:
        from agent_service.services.execution_signing import canonical_digest
        facts.update(
            frames_canary_free=not any(value in json.dumps(frames) for value in data["canaries"]),
            logs_canary_free=log_probe.leaked == 0, logs_scanned=log_probe.seen,
            signing_input_unchanged=json.dumps(parameters, sort_keys=True) == signing_input,
            args_digest_matches=envelope["args_digest"] == canonical_digest(parameters),
            original_digest_matches=(view["receipt"] is None or (
                len(original_results) == 1 and canonical_digest(original_results[0]) == view["receipt"]["outcome_digest"])),
        )
    return facts


def main(data):
    operation = data.get("operation", "invoke")
    if operation == "invoke":
        return asyncio.run(_invoke(data))
    if operation == "recover":
        recovery = ExecutionRecovery(data.get("recovery_dsn", data["dsn"]), data["key"],
                                     data["epoch"], admission_enabled=True)
        view = recovery.lookup(data["execution_id"])
        return {"recovery_availability": view["availability"], "recovery_state": view["state"],
                "recovery_run_stopped": view["run_stopped"],
                "receipt_status": (view.get("receipt") or {}).get("status"),
                "target_verification_required": view["target_verification_required"],
                "observation_kinds": sorted({f["kind"] for f in view["observations"]})}
    raise AssertionError("unsupported probe operation")


if __name__ == "__main__":
    import sys
    try:
        result = {"ok": True, **main(json.load(sys.stdin))}
    except ProtocolError as exc:
        result = {"ok": False, "reason": exc.reason}
    result["pid"] = os.getpid()
    print(json.dumps(result))
