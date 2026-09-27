import asyncio
import json
import logging
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime, timezone

from agent_service.core.metrics import (
    record_agent_state_error,
    record_evidence_write,
)
from agent_service.providers import get_provider
from agent_service.runtime_settings import RuntimeSettings
from agent_service.services.agent_state_store import AGENT_STATE_STORE
from agent_service.services.audit_emitter import (
    build_audit_event,
    emit_audit_event,
)
from agent_service.services.authoring_trace import (
    AUTHORING_TRACE_STORE,
    make_trace_step,
    origin_of_url,
)
from agent_service.services.confirmation_records import (
    CONFIRMATION_RECORD_STORE,
    make_record as make_confirmation_record,
)
from agent_service.services.evidence_store import (
    EVIDENCE_FRAME_TYPES,
    EVIDENCE_STORE,
    prepare_frames,
)
from agent_service.services.execution_records import (
    EXECUTION_RECORD_STORE,
    make_execution_record,
)
from agent_service.services.execution_recovery import ExecutionRecovery
from agent_service.services.execution_signing import (
    REASON_ARGS_DIGEST_MISMATCH,
    REASON_REQUEST_MISSING,
    REASON_SIGNING_UNAVAILABLE,
    build_flow_request,
    build_receipt,
    build_requests,
)
from agent_service.services.flow_approvals import (
    BROWSER_WRITE_TOOLS,
    FLOW_APPROVALS,
    FLOW_CONTEXTS,
    FLOW_KILLING_ERROR_CODES,
)
from agent_service.services.hitl_confirmations import (
    CONFIRMATION_REGISTRY,
    PendingConfirmation,
    RISK_LEVEL_ACTIONS,
    curated_effect_sentence,
    redact_pending_calls,
)
from agent_service.services.model_catalog import MODEL_CATALOG
from agent_service.services.prose_redaction import (
    CURRENT_PROSE_REDACTOR,
    StreamingProseRedactor,
    credential_literals,
    generated_credential_literals,
    redact_assistant_text,
    redact_structure,
    redact_user_text,
)
from agent_service.services.secret_params import parameterize_for_trace

LOGGER = logging.getLogger(__name__)
MAX_CACHED_AGENTS = 1000


class UnknownModelError(ValueError):
    """A requested model id is absent from the credential-gated catalog.

    Selection fails closed (SPEC-024 R-1): routes map this to 4xx; the
    kernel never silently falls back to the default model.
    """


TEXT_DELTA_EVENTS = {
    "message_delta",
    "text_block_start",
    "text_block_delta",
    "thinking_block_start",
    "thinking_block_delta",
}

# Frames that settle a turn for the portal: it marks the turn complete and
# never rewrites the accumulated reply text afterwards, so a streaming prose
# redactor must release its held-back tail *before* one of these is yielded.
# Mirrors the portal decoder's own TERMINAL_EVENT_TYPES.
TERMINAL_STREAM_EVENTS = frozenset({"message_end", "reply_end"})

# Deterministic guard injected into the turn when a tool gateway is configured
# but no tool could be registered. A standing system prompt is only a
# probabilistic hint; when the toolkit is empty the model has no real data to
# ground in and tends to fabricate, so this explicit per-turn notice is added
# by code exactly when the risk exists.
NO_TOOLS_NOTICE = (
    "[SYSTEM NOTICE] No operational tools are currently reachable. Tool "
    "discovery returned no available tools, so you have NO live cluster, log, "
    "or metric data. Do NOT report, estimate, or imply any infrastructure "
    "status, health, counts, or metrics. Tell the user that operational "
    "tooling is currently unavailable and that you cannot perform the "
    "requested check right now."
)

# Deterministic guard for the HITL-disabled posture (SPEC-021 R-3): when
# confirmation bridging is off, mutating tools are excluded from the toolkit
# entirely; this notice keeps that posture honest instead of letting the
# model imply it could act.
MUTATING_TOOLS_UNAVAILABLE_NOTICE = (
    "[SYSTEM NOTICE] Mutating operational actions (e.g. deleting or "
    "restarting workloads) are currently unavailable in this workspace; only "
    "read-only diagnostics can be executed. Human confirmation bridging is "
    "disabled, so do NOT propose, promise, or imply that you can perform any "
    "mutating action. If the user asks for one, say it requires operator "
    "enablement of HITL confirmation."
)


def make_serializable(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [make_serializable(item) for item in value]
    if isinstance(value, tuple):
        return [make_serializable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): make_serializable(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return make_serializable(value.model_dump())
    if hasattr(value, "__dict__"):
        return make_serializable(
            {
                key: item
                for key, item in vars(value).items()
                if not key.startswith("_")
            }
        )
    return str(value)


def extract_text(value: object) -> str:
    normalized = make_serializable(value)
    if normalized is None:
        return ""
    if isinstance(normalized, str):
        return normalized
    if isinstance(normalized, list):
        parts = [extract_text(item) for item in normalized]
        return " ".join(part for part in parts if part).strip()
    if isinstance(normalized, dict):
        for key in ("text", "delta", "message", "content"):
            if key in normalized:
                text = extract_text(normalized[key])
                if text:
                    return text
        return json.dumps(normalized, default=str)
    return str(normalized)


def extract_stream_text(value: object) -> str:
    normalized = make_serializable(value)
    if normalized is None:
        return ""
    if isinstance(normalized, str):
        return normalized
    if isinstance(normalized, list):
        parts = [extract_stream_text(item) for item in normalized]
        return " ".join(part for part in parts if part).strip()
    if isinstance(normalized, dict):
        for key in ("text", "delta", "message", "content"):
            if key in normalized:
                text = extract_stream_text(normalized[key])
                if text:
                    return text
        return ""
    return ""


def flush_prose_frames(
    redactor: StreamingProseRedactor,
    request_id: str,
    session_id: str,
) -> list[dict[str, object]]:
    """A redactor's held-back tail as a final ``message_delta`` frame.

    Streaming prose redaction withholds the last characters of a chunk until
    it knows they are not the start of a credential, so every stream exit has
    to release them. The portal accumulates deltas (``turn.replyText +=
    frame.text``) and has no handler that overwrites them from a
    complete-message frame, so a tail that is never flushed is dropped from
    the live view rather than merely arriving late.

    ``flush`` empties the buffer, which makes this safe to call at more than
    one exit point on the same stream: only the first returns a frame.
    """
    tail = redactor.flush()
    if not tail:
        return []
    return [
        {
            "event": "message_delta",
            "request_id": request_id,
            "session_id": session_id,
            "delta": tail,
        }
    ]


class AgentKernel:
    def __init__(
        self,
        settings: RuntimeSettings | None = None,
        max_cached_agents: int = MAX_CACHED_AGENTS,
    ) -> None:
        self.settings = settings or RuntimeSettings.from_env()
        self._provider = get_provider(self.settings.provider)
        self._agents: OrderedDict[str, tuple[object, type]] = OrderedDict()
        self._max_cached_agents = max_cached_agents
        # Ephemeral masking knowledge survives context compaction, never a snapshot.
        self._generated_literals: OrderedDict[str, set[str]] = OrderedDict()
        self._last_error: str | None = None
        # Per-token toolkit cache (SPEC-008 R-5): a toolkit is built per owning
        # user's delegated token so discovery runs once per token. Tool
        # closures read the current token from the DELEGATED_TOKEN contextvar
        # at call time (SPEC-018 R-2), so cached toolkits keep working across
        # portal token refresh.
        self._toolkits: dict[str, object] = {}
        self._toolkit_lock = asyncio.Lock()
        self._agent_lock = asyncio.Lock()
        # SPEC-021 R-3: set when a toolkit build excluded mutating tools
        # because HITL bridging is disabled, so streamed turns surface the
        # mutating-unavailable posture honestly.
        self._mutating_tools_excluded = False
        # SPEC-063 R-2: agent-side durable execution recovery/admission store,
        # built lazily and only when admission is enabled. ``None`` (the
        # default) keeps the legacy in-process handoff path byte-identical, so
        # a partially upgraded mutation path is never enabled by construction.
        self._recovery: ExecutionRecovery | None = None
        self._recovery_built = False

    def _execution_recovery(self) -> ExecutionRecovery | None:
        """The agent-side durable recovery store, or ``None`` when disabled.

        Admission is disabled by default (SPEC-063 R-2a): with the flag off the
        kernel returns ``None`` and every execution seam stays on the legacy
        path. When enabled, ``RuntimeSettings.__post_init__`` has already
        guaranteed a ledger DSN and epoch at startup, so this builds the store
        once and caches it. Construction never connects (the connection factory
        is per-call and bounded), so building is cheap and side-effect free.
        """
        if not self.settings.execution_admission_enabled:
            return None
        if not self._recovery_built:
            self._recovery = ExecutionRecovery(
                self.settings.execution_state_db_url,
                self.settings.execution_signing_key,
                self.settings.execution_admission_epoch,
                admission_enabled=True,
            )
            self._recovery_built = True
        return self._recovery

    def _resolve_run_id(
        self, recovery, session_id, owner_user_id, flow_approval=None
    ) -> str | None:
        """The durable run identity for this human root turn (SPEC-063 R-4).

        A reused flow authority inherits its originating run across later turns;
        otherwise a new human root turn mints one via the ledger. Returns
        ``None`` when the identity cannot be established (store unavailable), so
        the mutation lane fails closed rather than proceeding without a durable
        run — a missing identity is never silently replaced.
        """
        inherited = getattr(flow_approval, "run_id", None) if flow_approval else None
        if inherited:
            return str(inherited)
        from agent_service.services.execution_protocol import ProtocolError

        try:
            return recovery.create_run(session_id, owner_user_id)
        except ProtocolError as exc:
            LOGGER.warning(
                "execution run creation failed for session %s: %s",
                session_id,
                exc.reason,
            )
            return None

    def _bind_guard(self, recovery, run_id, session_id, owner_user_id):
        """Build the turn's ``RunGuard`` bound to a resolved run identity."""
        from agent_service.services.execution_run_guard import RunGuard, RunIdentity

        return RunGuard(
            RunIdentity(str(run_id), session_id, owner_user_id), recovery=recovery
        )

    def mode(self) -> str:
        return "agentscope" if self.is_configured() else "placeholder"

    def is_configured(self) -> bool:
        return self.settings.is_configured()

    def runtime_state(self) -> str:
        if not self.is_configured():
            return "not_configured"
        if self._last_error:
            return "provider_error"
        return "ready"

    def provider_name(self) -> str:
        return self._provider.provider_name

    def provider_description(self) -> str:
        return self._provider.describe(self.settings)

    def last_error(self) -> str | None:
        return self._last_error

    def runtime_metadata(self) -> dict[str, object]:
        return {
            "runtime_mode": self.mode(),
            "runtime_state": self.runtime_state(),
            "agentscope_enabled": self.is_configured(),
            "profile": self.settings.profile,
            "provider": self.provider_name(),
            "provider_description": self.provider_description(),
            "model_name": self._provider.resolved_model_name(self.settings),
            "base_url": self._provider.resolved_base_url(self.settings),
            "provider_options": make_serializable(self.settings.provider_options),
            "hint": self.configuration_hint(),
            "last_error": self.last_error(),
        }

    def configuration_hint(self) -> str:
        if not self.is_configured():
            return (
                "AgentScope runtime is not configured. "
                "Set AGENTSCOPE_API_KEY to enable the runtime kernel."
            )
        if self._last_error:
            return (
                "AgentScope runtime is configured through the "
                f"{self.provider_name()} provider, but the last provider call failed: "
                f"{self._last_error}"
            )
        return f"AgentScope runtime ready through {self.provider_description()}."

    def remember_error(self, exc: Exception, turn_literals=()) -> None:
        literals = set(turn_literals).union(*self._generated_literals.values())
        self._last_error = redact_assistant_text(str(exc), literals)

    def clear_error(self) -> None:
        self._last_error = None

    def _build_model(self, model_id: str | None = None):
        """Build the AgentScope model for a turn (SPEC-024 R-3).

        ``model_id=None`` keeps the deploy-time settings path untouched.
        A concrete id derives a replaced RuntimeSettings from the catalog
        entry and reuses the existing provider adapters; an unknown id
        raises ``UnknownModelError`` (fail-closed). Bare provider names
        alias to the provider's default entry (SPEC-026 R-3).
        """
        if model_id is None:
            return self._provider.build_model(self.settings)
        entry = MODEL_CATALOG.get(model_id)
        if entry is None:
            raise UnknownModelError(f"Unknown model id: {model_id!r}.")
        if entry.provider == self.settings.provider:
            # Active provider: keep the deploy-time credentials/options
            # and swap only the model name, so non-default series entries
            # build against the same provider (SPEC-026 R-1).
            settings = replace(self.settings, model_name=entry.model_name)
        else:
            settings = replace(
                self.settings,
                provider=entry.provider,
                api_key=entry.api_key,
                model_name=entry.model_name,
                base_url=entry.base_url,
                provider_options=RuntimeSettings.default_provider_options(
                    entry.provider
                ),
            )
        return get_provider(entry.provider).build_model(settings)

    def _normalize_model_id(self, model_id: str | None) -> str:
        """Canonical id bound to a turn (SPEC-026 R-3).

        Legacy provider-name ids resolve through the catalog alias map to
        the concrete default-model entry; unknown ids pass through verbatim
        (explicit-request paths reject them upstream, so they only surface
        as the deploy-time provider fallback marker).
        """
        if model_id:
            entry = MODEL_CATALOG.get(model_id)
            if entry is not None:
                return entry.id
            return model_id
        return self.settings.provider

    async def _ensure_toolkit(
        self, bearer_token: str | None = None, read_only: bool = False
    ):
        """Build (once per token) and return the Toolkit with gateway tools.

        Toolkits are cached per delegated token so discovery runs once per
        token; tool closures read the current token from ``DELEGATED_TOKEN``
        at call time, so a cached toolkit keeps working across portal token
        refresh (SPEC-018 R-2). Empty discovery results are intentionally NOT
        cached: the next caller retries discovery instead of being poisoned.

        ``read_only`` selects a separate cache entry whose toolkit is
        restricted to read-level tools (automated diagnostic turns).
        """
        cache_key = (bearer_token or "") + ("::read-only" if read_only else "")
        cached = self._toolkits.get(cache_key)
        if cached is not None:
            return cached

        from agentscope.tool import Toolkit

        async with self._toolkit_lock:
            # Re-check: a concurrent caller may have built it while we waited.
            cached = self._toolkits.get(cache_key)
            if cached is not None:
                return cached

            task_tools = (
                self._build_task_tools()
                if self.settings.task_tools_enabled
                else []
            )

            if self.settings.tool_gateway_url:
                from agent_service.tools.gateway_tools import (
                    build_gateway_toolkit,
                    discover_tools,
                )

                try:
                    definitions = await discover_tools(
                        self.settings.tool_gateway_url, bearer_token
                    )
                    if definitions:
                        definitions = self._filter_mutating_for_hitl(
                            definitions
                        )
                    if definitions and read_only:
                        definitions = self._filter_read_only(definitions)
                    if definitions:
                        toolkit = build_gateway_toolkit(
                            definitions,
                            self.settings.tool_gateway_url,
                        )
                        if task_tools:
                            toolkit.tool_groups[0].tools.extend(task_tools)
                        self._toolkits[cache_key] = toolkit
                        return toolkit
                except Exception as exc:
                    LOGGER.warning("failed to build gateway toolkit: %s", exc)

            # No gateway (or nothing discovered): task tools only, returned
            # uncached so a later turn can retry discovery.
            return Toolkit(tools=task_tools)

    def _filter_mutating_for_hitl(self, definitions: list[dict]) -> list[dict]:
        """Drop non-read tools when HITL bridging is disabled (SPEC-021 R-3).

        A mutating tool can never execute without a human confirmation; when
        ``AGENT_HITL_CONFIRM_TIMEOUT=0`` there is no confirmation surface, so
        non-read tools are excluded from the toolkit entirely instead of
        parking silently. Read tools are untouched.
        """
        if self.settings.hitl_confirm_timeout > 0:
            return definitions
        kept = [
            definition
            for definition in definitions
            if definition.get("risk_level", "read") == "read"
        ]
        excluded = len(definitions) - len(kept)
        if excluded:
            self._mutating_tools_excluded = True
            LOGGER.warning(
                "HITL bridging disabled (AGENT_HITL_CONFIRM_TIMEOUT=0); "
                "excluded %d mutating tool(s) from the agent toolkit",
                excluded,
            )
        return kept

    def _filter_read_only(self, definitions: list[dict]) -> list[dict]:
        """Restrict the toolkit to read-level tools for read-only turns.

        Automated diagnostic turns (incident triage) must never invoke — or
        silently park on — a mutating tool, regardless of what the model
        decides, so non-read tools are excluded structurally instead of
        relying on prompt discipline alone.
        """
        kept = [
            definition
            for definition in definitions
            if definition.get("risk_level", "read") == "read"
        ]
        excluded = len(definitions) - len(kept)
        if excluded:
            LOGGER.info(
                "read-only turn: excluded %d mutating tool(s) from the "
                "agent toolkit",
                excluded,
            )
        return kept

    def _build_task_tools(self) -> list:
        """Built-in agentscope task tools, opt-in (SPEC-018 R-5).

        These mutate only session-local agent state, so the SPEC-017
        snapshot/restore persists them with no extra work.
        """
        from agentscope.tool import TaskCreate, TaskGet, TaskList, TaskUpdate

        return [TaskCreate(), TaskGet(), TaskList(), TaskUpdate()]

    def _build_middlewares(self) -> list:
        """Compose the kernel middleware stack (SPEC-018).

        Permission, evidence, and LLM-token (SPEC-065 R-1) middlewares are
        always registered; OTel kernel tracing (R-3) and the reply token budget
        (R-4) are opt-in via settings and stay absent when unconfigured.
        """
        from agent_service.services.kernel_middleware import (
            GatewayPermissionMiddleware,
            TokenUsageMiddleware,
            ToolEvidenceMiddleware,
        )

        settings = self.settings
        middlewares: list = [
            GatewayPermissionMiddleware(flow_signer=self._sign_flow_execution),
            ToolEvidenceMiddleware(
                data_summary_max_chars=settings.tool_data_summary_max_chars,
                data_max_chars=settings.tool_data_max_chars,
            ),
            # SPEC-065 R-1: always-on LLM token observation (no knob) — a pure
            # ``on_model_call`` mirror of the provider's own usage into
            # ``agent_llm_tokens_total``. Streaming-aware; records no cost.
            TokenUsageMiddleware(),
        ]
        if settings.kernel_tracing:
            from agentscope.middleware import TracingMiddleware

            middlewares.append(TracingMiddleware())
        if settings.reply_token_budget is not None:
            from agentscope.middleware import ReplyBudgetControlMiddleware

            middlewares.append(
                ReplyBudgetControlMiddleware(
                    token_budget=settings.reply_token_budget,
                    input_token_weight=settings.reply_input_token_weight,
                    output_token_weight=settings.reply_output_token_weight,
                )
            )
        return middlewares

    def _count_gateway_tools(self, toolkit) -> int:
        """Count gateway-backed tools in a toolkit.

        Task tools and builtins are excluded: only gateway tools ground the
        model in live data, which is what the no-tools guard cares about
        (SPEC-018 R-5).
        """
        count = 0
        for group in getattr(toolkit, "tool_groups", None) or []:
            for tool in getattr(group, "tools", None) or []:
                if getattr(tool, "gateway_tool_name", None):
                    count += 1
        return count

    def _build_kernel_configs(self):
        """Settings-driven kernel configs (SPEC-017 R-1).

        Defaults mirror agentscope's own defaults, so unset deployments
        behave exactly as before the settings existed.
        """
        from agentscope.agent import (
            ContextConfig,
            InjectionConfig,
            ModelConfig,
            ReActConfig,
        )

        settings = self.settings
        return {
            "model_config": ModelConfig(max_retries=settings.model_max_retries),
            # SPEC-064 R-2: ``compression_tool_enabled`` adds the opt-in
            # ``CompressContext`` tool (default off). Deliberately no
            # ``offloader`` is wired into the Agent: the offloader would write
            # compressed context to a Workspace filesystem path, which breaches
            # the read-only posture (gate point 3) and lands pod-local state on
            # the emptyDir workspace volume — invisible to other replicas and
            # lost on reschedule. Compression state stays in
            # ``state.summary``/``state.context`` and rides the SPEC-017
            # snapshot, which is shared and durable across replicas.
            "context_config": ContextConfig(
                trigger_ratio=settings.context_trigger_ratio,
                tool_result_limit=settings.tool_result_limit,
                compression_tool_enabled=settings.compress_context_enabled,
            ),
            "react_config": ReActConfig(max_iters=settings.max_iters),
            "injection_config": InjectionConfig(
                inject_runtime_state=True,
                timezone=settings.timezone,
            ),
        }

    def _restore_state(self, session_id: str):
        """Load a persisted AgentState for the session, if any (SPEC-017 R-3).

        A missing row returns None (fresh agent); a corrupt row is discarded
        with a WARNING and a counter so a poisoned snapshot can never wedge
        a session.
        """
        try:
            raw = AGENT_STATE_STORE.load_state(session_id)
        except Exception as exc:
            record_agent_state_error("restore")
            LOGGER.warning(
                "agent state restore failed for session %s: %s", session_id, type(exc).__name__
            )
            return None
        if raw is None:
            return None
        try:
            from agentscope.state import AgentState

            return AgentState.model_validate_json(raw)
        except Exception as exc:
            record_agent_state_error("restore")
            LOGGER.warning(
                "discarding corrupt persisted agent state for session %s: %s",
                session_id,
                type(exc).__name__,
            )
            return None

    def _snapshot_state(self, session_id: str, agent, turn_literals=()) -> None:
        """Persist the agent state after a completed turn (SPEC-017 R-3).

        Never raises: a failed snapshot degrades durability, not the turn.
        """
        try:
            state = json.loads(agent.state.model_dump_json())
            literals = set(self._generated_literals.get(session_id, ()))
            literals.update(turn_literals)
            literals.update(generated_credential_literals(state))
            # Only the serialized projection changes; live tool/signing inputs stay raw.
            state_json = json.dumps(redact_structure(state, literals))
            AGENT_STATE_STORE.save_state(session_id, state_json)
        except Exception as exc:
            record_agent_state_error("snapshot")
            LOGGER.warning(
                "agent state snapshot failed for session %s: %s", session_id, type(exc).__name__
            )

    @staticmethod
    def _count_user_turns(agent) -> int:
        """User-message count in the agent context (SPEC-025 turn index).

        The replay path attaches persisted evidence groups to the assistant
        turn at this ordinal, so the index is captured from the context
        before the streamed turn appends to it. Counting user messages (not
        assistant) keeps the index stable across HITL park/resume: parking
        may add a partial assistant message but never a user one.
        """
        try:
            context = getattr(agent.state, "context", None) or []
            return sum(
                1 for msg in context if getattr(msg, "role", None) == "user"
            )
        except Exception:  # pragma: no cover - defensive index fallback
            return 0

    def _user_text_literals(self, agent, message: str) -> frozenset[str]:
        """Credential literals the operator typed in this session's prose.

        Harvested from every user turn in the agent context plus the message
        being sent now, which the context does not yet hold: ``stream_events``
        captures its turn ordinal before the turn mutates the context, so the
        current message is appended only as the reply runs. Including it is
        what lets the very first turn mask its own echoed password, and
        walking the rest is what catches a cross-turn echo.

        Best-effort by design — a context this cannot read yields the current
        message's literals alone, which is still the turn that matters.
        """
        texts = [message]
        try:
            for msg in getattr(agent.state, "context", None) or []:
                if getattr(msg, "role", None) != "user":
                    continue
                texts.append(extract_text(getattr(msg, "content", "")))
        except Exception as exc:  # pragma: no cover - defensive harvest
            LOGGER.debug("prose literal harvest from context failed: %s", type(exc).__name__)
        literals: set[str] = set()
        for text in texts:
            literals |= credential_literals(text)
        return frozenset(literals)

    def _prose_redactor(self, agent, message: str, session_id: str) -> StreamingProseRedactor:
        generated = self._generated_literals.setdefault(session_id, set())
        generated.update(generated_credential_literals(make_serializable(getattr(agent, "state", None))))
        self._generated_literals.move_to_end(session_id)
        # A live agent may retain a compacted prose copy after its tool block
        # disappears. Never evict its masking knowledge on an independent LRU.
        protected = {key.removesuffix("::read-only") for key in self._agents}
        protected.add(session_id)
        for key in list(self._generated_literals):
            if len(self._generated_literals) <= max(1, self._max_cached_agents):
                break
            if key not in protected:
                self._generated_literals.pop(key)
        return StreamingProseRedactor(self._user_text_literals(agent, message), generated)

    def forget_session(self, session_id: str) -> None:
        """Drop ephemeral agents and literal knowledge after an owner deletion."""
        self._agents.pop(session_id, None)
        self._agents.pop(f"{session_id}::read-only", None)
        # In-flight redactors retain their own reference until the turn ends.
        self._generated_literals.pop(session_id, None)

    def _persist_evidence(
        self,
        session_id: str,
        request_id: str,
        turn_index: int,
        frames: list[dict[str, object]],
    ) -> None:
        """Persist a turn's evidence frames best-effort (SPEC-025 R-1).

        Never raises: a failed write degrades replay parity, not the turn.
        Entry caps apply before insert; the session budget is enforced by
        the store itself.
        """
        if not frames:
            return
        try:
            prepared = prepare_frames(
                frames, self.settings.evidence_entry_max_chars
            )
            EVIDENCE_STORE.save_turn(
                session_id,
                request_id,
                turn_index,
                prepared,
                self.settings.evidence_session_max_bytes,
            )
            record_evidence_write("ok")
        except Exception as exc:
            record_evidence_write("error")
            LOGGER.warning(
                "evidence persistence failed for session %s: %s",
                session_id,
                type(exc).__name__,
            )

    async def _build_agent(
        self,
        session_id: str,
        bearer_token: str | None = None,
        model_id: str | None = None,
        read_only: bool = False,
    ):
        from agentscope.agent import Agent
        from agentscope.message import UserMsg

        toolkit = await self._ensure_toolkit(bearer_token, read_only)
        configs = self._build_kernel_configs()
        state = self._restore_state(session_id)
        agent = Agent(
            name=self.settings.agent_name,
            system_prompt=self.settings.system_prompt,
            model=self._build_model(model_id),
            toolkit=toolkit,
            middlewares=self._build_middlewares(),
            state=state,
            **configs,
        )
        LOGGER.info(
            "kernel agent constructed",
            extra={
                "session_id": session_id,
                "model_id": self._normalize_model_id(model_id),
                "max_iters": self.settings.max_iters,
                "context_trigger_ratio": self.settings.context_trigger_ratio,
                "tool_result_limit": self.settings.tool_result_limit,
                "timezone": self.settings.timezone,
                "model_max_retries": self.settings.model_max_retries,
                "state_restored": state is not None,
            },
        )
        return agent, UserMsg, self._normalize_model_id(model_id)

    async def ensure_agent(
        self,
        session_id: str,
        bearer_token: str | None = None,
        model_id: str | None = None,
        read_only: bool = False,
    ):
        """Return the agent bound to `session_id`, creating it on first use.

        Agents are keyed by session so conversation memory never crosses
        sessions; the cache is LRU-bounded to match the session store.
        Creation is serialised because it awaits: without the lock two
        concurrent turns on the same session would each build an agent and
        one would be discarded along with its memory.

        ``read_only`` turns use a distinct cache key for the same session so
        a restricted toolkit never leaks into interactive turns (and vice
        versa); both entries restore the same persisted memory.

        Model switching (SPEC-024 R-3): the cache tracks the bound model
        id; a turn whose resolved model differs evicts and rebuilds, and
        ``_restore_state`` rebuilds memory — the same path as a pod
        restart, so the switch never loses conversation history.
        """
        bound_id = self._normalize_model_id(model_id)
        agent_key = f"{session_id}::read-only" if read_only else session_id
        cached = self._agents.get(agent_key)
        if cached is not None:
            # Gateway tools recovered after this agent was built with an
            # empty toolkit (discovery failure): rebuild so the turn can see
            # them. Persisted state (SPEC-017 R-3) restores the memory.
            agent, _user_msg_cls, cached_model_id = cached
            if cached_model_id != bound_id:
                LOGGER.info(
                    "model switch for session %s: %s -> %s; rebuilding "
                    "agent with restored state",
                    session_id,
                    cached_model_id,
                    bound_id,
                )
                self._agents.pop(agent_key, None)
            else:
                current_toolkit = await self._ensure_toolkit(
                    bearer_token, read_only
                )
                if (
                    self._count_gateway_tools(getattr(agent, "toolkit", None)) == 0
                    and self._count_gateway_tools(current_toolkit) > 0
                ):
                    LOGGER.info(
                        "gateway tools recovered; rebuilding kernel agent for "
                        "session %s",
                        session_id,
                    )
                    self._agents.pop(agent_key, None)
                else:
                    # Re-check membership: the await above opens a preemption
                    # window where a concurrent turn's recovery branch may pop
                    # this entry, or LRU eviction may remove it. A vanished
                    # entry falls through to the locked path, which re-checks
                    # the cache before building.
                    if agent_key in self._agents:
                        self._agents.move_to_end(agent_key)
                        return cached
        async with self._agent_lock:
            cached = self._agents.get(agent_key)
            if cached is not None and cached[2] == bound_id:
                self._agents.move_to_end(agent_key)
                return cached
            agent, user_msg_cls, cached_model_id = await self._build_agent(
                session_id, bearer_token, model_id, read_only
            )
            self._agents[agent_key] = (agent, user_msg_cls, cached_model_id)
            while len(self._agents) > self._max_cached_agents:
                self._agents.popitem(last=False)
            return agent, user_msg_cls, cached_model_id

    def build_unconfigured_message(self, message: str, session_id: str) -> str:
        # The operator's own text is interpolated into a kernel-authored
        # string, so it carries a typed credential exactly as the prompt did.
        # This is user-authored text inside a display projection, which is the
        # scope ``prose_redaction`` allows its heuristic to run in.
        return (
            "Platform baseline placeholder response. "
            f"AgentScope runtime not configured for session {session_id}. "
            f"Received '{redact_user_text(message)}'."
        )

    def build_provider_error_message(
        self,
        message: str,
        session_id: str,
        model_id: str | None = None,
    ) -> str:
        detail = self._last_error or "Unknown provider error."
        # Name the provider that actually served (attempted) the turn:
        # a resolved catalog entry carries its own provider, so a
        # dashscope model failure never blames the deepseek profile.
        entry = MODEL_CATALOG.get(model_id) if model_id else None
        if entry is not None:
            attribution = f"{entry.provider} (model {entry.id})"
        elif model_id:
            attribution = f"{self.provider_name()} (model {model_id})"
        else:
            attribution = self.provider_name()
        return (
            "Platform runtime fallback response. "
            f"AgentScope provider {attribution} failed for session {session_id}. "
            f"Received '{redact_user_text(message)}'. Last error: {detail}"
        )

    async def fallback_stream(
        self,
        request_id: str,
        session_id: str,
        delta: str,
    ) -> AsyncIterator[dict[str, object]]:
        yield {
            "event": "message_start",
            "request_id": request_id,
            "session_id": session_id,
        }
        yield {
            "event": "message_delta",
            "request_id": request_id,
            "session_id": session_id,
            "delta": delta,
        }
        yield {
            "event": "message_end",
            "request_id": request_id,
            "session_id": session_id,
            "message": "complete",
        }

    async def reply_text(
        self,
        message: str,
        session_id: str,
        user_name: str,
        bearer_token: str | None = None,
        response_schema: dict | None = None,
        model_id: str | None = None,
        read_only: bool = False,
    ) -> tuple[str, dict | None]:
        """Run one blocking turn.

        Returns the reply text and, when ``response_schema`` was supplied,
        the kernel-validated structured output carried on the final message
        (SPEC-017 R-2) — ``None`` when the turn ended without producing one.

        ``model_id`` selects the catalog entry for this turn (SPEC-024 R-3);
        callers validate it against the catalog first, so an unknown id
        never reaches ``_build_model`` here.

        ``read_only`` restricts the turn's toolkit to read-level tools
        (automated diagnostic turns such as incident triage).
        """
        if not self.is_configured():
            return self.build_unconfigured_message(message, session_id), None

        from agent_service.tools.gateway_tools import (
            CHAT_SESSION_ID,
            DELEGATED_TOKEN,
        )

        serving_model: str | None = None
        prose: StreamingProseRedactor | None = None
        try:
            agent, user_msg_cls, serving_model = await self.ensure_agent(
                session_id, bearer_token, model_id, read_only
            )
            # Prose redaction for a blocking turn: no streaming, so the reply
            # is masked whole and no hold-back is needed.
            prose = self._prose_redactor(agent, message, session_id)
            # Expose the turn's delegated token to the cached tool closures
            # (SPEC-018 R-2). No evidence sink is set: blocking turns emit
            # no trace frames.
            prose_var = CURRENT_PROSE_REDACTOR.set(prose)
            token_var = DELEGATED_TOKEN.set(bearer_token)
            session_var = CHAT_SESSION_ID.set(session_id)
            try:
                reply_msg = await agent.reply(
                    user_msg_cls(name=user_name, content=message),
                    structured_schema=response_schema,
                )
            finally:
                CURRENT_PROSE_REDACTOR.reset(prose_var)
                DELEGATED_TOKEN.reset(token_var)
                CHAT_SESSION_ID.reset(session_var)
            self.clear_error()
            structured = getattr(reply_msg, "structured_output", None)
            if not isinstance(structured, dict):
                structured = None
            self._snapshot_state(session_id, agent, prose.literals)
            return (
                redact_assistant_text(
                    extract_text(getattr(reply_msg, "content", reply_msg)),
                    prose.literals,
                ),
                redact_structure(structured, prose.literals),
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            self.remember_error(exc, prose.literals if prose is not None else ())
            LOGGER.error("AgentScope reply failed; falling back to runtime error response: %s", self._last_error)
            return (
                self.build_provider_error_message(
                    message, session_id, serving_model or model_id
                ),
                None,
            )

    def normalize_event(
        self,
        event: object,
        request_id: str,
        session_id: str,
        redactor: StreamingProseRedactor | None = None,
    ) -> dict[str, object]:
        """One AgentScope event as a normalized stream frame.

        ``redactor`` carries the turn's harvested credential literals and the
        held-back tail of a stream in progress (SPEC-049 R-5 applied to chat
        prose). Callers that pass one own flushing it: a delta boundary can
        fall inside a credential, so the redactor withholds a tail that the
        caller must emit at every stream exit.
        """
        payload = make_serializable(event)
        event_type = "agentscope_event"
        if isinstance(payload, dict) and "type" in payload:
            event_type = str(payload["type"]).lower()
        else:
            raw_type = getattr(event, "type", None)
            if raw_type is not None:
                event_type = str(getattr(raw_type, "name", raw_type)).lower()

        data: dict[str, object] = {
            "event": event_type,
            "request_id": request_id,
            "session_id": session_id,
            "payload": payload,
        }

        text = extract_stream_text(payload)
        if event_type in TEXT_DELTA_EVENTS and text:
            if redactor is None:
                data["delta"] = text
            else:
                masked = redactor.feed(text)
                # An empty result means the whole chunk was held back. Omit
                # the key rather than send "": that is the shape this already
                # produces for a text-block start with no text, and the
                # portal's decoder gates on a truthy delta either way.
                if masked:
                    data["delta"] = masked
                # The payload is the same text again in raw event form. It
                # reaches no wire today — the v2 contract strips it as an
                # AgentScope internal and the v1 stream helper has no caller
                # — so this is a chunk-local mask of a duplicate, not the
                # guarantee: the hold-back lives in ``delta`` above.
                data["payload"] = {"type": event_type, "delta": masked}
        elif redactor is not None:
            data["payload"] = redact_structure(payload, redactor.literals)
        return data

    async def stream_events(
        self,
        message: str,
        request_id: str,
        session_id: str,
        user_name: str,
        bearer_token: str | None = None,
        model_id: str | None = None,
    ) -> AsyncIterator[dict[str, object]]:
        # SPEC-024 R-3: an unknown model id fails closed before any agent
        # work — a deterministic error frame, never a silent default.
        if model_id is not None and MODEL_CATALOG.get(model_id) is None:
            LOGGER.warning(
                "stream rejected unknown model %r for session %s",
                model_id,
                session_id,
            )
            yield {
                "event": "error",
                "request_id": request_id,
                "session_id": session_id,
                "error": {
                    "code": "unknown_model",
                    "message": f"unknown model id: {model_id}",
                },
            }
            return

        if not self.is_configured():
            async for event in self.fallback_stream(
                request_id=request_id,
                session_id=session_id,
                delta=self.build_unconfigured_message(message, session_id),
            ):
                yield event
            return

        from agent_service.services.kernel_middleware import (
            PENDING_RELEASE_DELIVERIES,
            RELEASE_PERMITS,
            STREAM_PENDING_DELIVERIES,
            TOOL_EVIDENCE_SINK,
        )
        from agent_service.services.execution_run_guard import CURRENT_RUN_GUARD
        from agent_service.tools.gateway_tools import (
            CHAT_SESSION_ID,
            DELEGATED_TOKEN,
            EXECUTION_AUDIT_CONTEXT,
            EXECUTION_REQUESTS,
        )

        bound_model_id: str | None = None
        prose: StreamingProseRedactor | None = None
        try:
            # Ensure the agent (with the token-cached toolkit) exists.
            agent, user_msg_cls, bound_model_id = await self.ensure_agent(
                session_id, bearer_token, model_id
            )

            # SPEC-025 R-1: the replay turn ordinal for this stream's
            # evidence, captured before the turn mutates the context.
            turn_index = self._count_user_turns(agent)
            evidence_frames: list[dict[str, object]] = []
            # SPEC-049 R-5 applied to chat prose: harvest what the operator
            # typed so the model's own reply cannot restate it. Built from the
            # raw message rather than effective_message — the notices injected
            # below are kernel text and carry no credential.
            prose = self._prose_redactor(agent, message, session_id)

            # Deterministic anti-hallucination guard: with a gateway
            # configured but zero gateway tools registered the model has no
            # real data to ground in, so inject an explicit notice for this
            # turn instead of relying on the standing system prompt. Task
            # tools never count: they provide no live data (SPEC-018 R-5).
            effective_message = message
            if (
                self.settings.tool_gateway_url
                and self._count_gateway_tools(agent.toolkit) == 0
            ):
                LOGGER.warning(
                    "tool gateway configured but no tools registered; "
                    "injecting no-tools notice to prevent fabrication"
                )
                effective_message = f"{NO_TOOLS_NOTICE}\n\n{message}"
            elif self._mutating_tools_excluded:
                effective_message = (
                    f"{MUTATING_TOOLS_UNAVAILABLE_NOTICE}\n\n{message}"
                )

            # SPEC-018 R-2: a request-scoped evidence sink consumed by
            # ToolEvidenceMiddleware replaces the per-request toolkit
            # rebuild; the delegated token is exposed the same way for the
            # cached tool closures.
            trace_queue: asyncio.Queue = asyncio.Queue()
            # SPEC-051 R-1: arm the same execution plumbing the resume path uses
            # so a browser write unlocked by a flow authority recorded in an
            # EARLIER turn can auto-sign, execute, and receipt here. Both are
            # inert for turns without a live flow authority: the empty requests
            # map is never consulted (mutating tools still park) and the audit
            # context stays None, so the common hot path is behavior-preserving.
            execution_requests: dict[str, dict] = {}
            flow_approval = FLOW_APPROVALS.get(session_id)
            # SPEC-063 R-4: resolve this root turn's durable run identity and
            # bind the shared in-process guard BEFORE the reply stream runs, so
            # the permission middleware's stop check and the mutation lane see
            # it. Inert when admission is disabled (recovery is None): no run is
            # minted, no guard is bound, and the legacy path is unchanged.
            recovery = self._execution_recovery()
            run_id = (
                self._resolve_run_id(
                    recovery, session_id, user_name, flow_approval
                )
                if recovery is not None
                else None
            )
            flow_audit_context = (
                {
                    "settings": self.settings,
                    "confirm_id": flow_approval.confirm_id,
                    "session_id": session_id,
                    "request_id": request_id,
                    "decider_user_id": flow_approval.decider_user_id,
                    "observe_original": self._observe_original_step_origin,
                }
                if flow_approval is not None
                else None
            )
            sink_var = TOOL_EVIDENCE_SINK.set(trace_queue)
            # SPEC-062 R-3 reveal-on-commit: arm the per-stream delivery buffers.
            # A fresh turn generates into STREAM_PENDING (flushed at a normal end
            # or drained onto a parked card); PENDING_RELEASE stays empty here —
            # only an approved resume carries held deliveries into it, so the
            # middleware's release branch can never fire on a non-resumed turn.
            pending_deliveries_var = STREAM_PENDING_DELIVERIES.set([])
            release_deliveries_var = PENDING_RELEASE_DELIVERIES.set([])
            # SPEC-063 R-4: arm the per-stream secret-release permit map the v3
            # invocation coordinator writes into and ToolEvidenceMiddleware
            # consumes before revealing a held portal_copy delivery. Unused and
            # never consulted when admission is disabled (no guard is bound).
            permits_var = RELEASE_PERMITS.set({})
            prose_var = CURRENT_PROSE_REDACTOR.set(prose)
            token_var = DELEGATED_TOKEN.set(bearer_token)
            session_var = CHAT_SESSION_ID.set(session_id)
            requests_var = EXECUTION_REQUESTS.set(execution_requests)
            audit_var = EXECUTION_AUDIT_CONTEXT.set(flow_audit_context)
            guard_var = (
                CURRENT_RUN_GUARD.set(
                    self._bind_guard(recovery, run_id, session_id, user_name)
                )
                if recovery is not None and run_id is not None
                else None
            )
            try:
                async for event in agent.reply_stream(
                    user_msg_cls(name=user_name, content=effective_message)
                ):
                    self.clear_error()
                    # Drain any accumulated trace events before yielding text.
                    drained = list(
                        self._drain_trace_queue(
                            trace_queue,
                            request_id,
                            session_id,
                            evidence_frames,
                            execution_requests,
                        )
                    )
                    if drained:
                        # SPEC-035 R-2: the portal opens a new paragraph on the
                        # first delta following a tool frame. A tail the
                        # redactor is still holding belongs to the segment
                        # *before* that tool call, so release it first — left
                        # held, it rides out in the same delta as the new
                        # segment's opening text, the portal prepends "\n\n" to
                        # the whole frame, and the paragraph break lands one
                        # hold-length early, mid-word.
                        for flushed in flush_prose_frames(
                            prose, request_id, session_id
                        ):
                            yield flushed
                    for decorated in drained:
                        yield decorated
                    # SPEC-020 R-2: a kernel ASK park surfaces as a
                    # confirmation_request frame and ends the stream without
                    # message_end; the confirm endpoint resumes it.
                    frame = self._build_confirmation_frame(
                        event,
                        session_id,
                        user_name,
                        agent.toolkit,
                        turn_index=turn_index,
                        evidence_frames=evidence_frames,
                        run_id=run_id,
                    )
                    if frame is not None:
                        # A parked stream ends without message_end, so this is
                        # its only chance to release the held-back tail.
                        for flushed in flush_prose_frames(
                            prose, request_id, session_id
                        ):
                            yield flushed
                        yield {
                            **frame,
                            "request_id": request_id,
                            "session_id": session_id,
                        }
                        break
                    frame = self.normalize_event(
                        event, request_id, session_id, redactor=prose
                    )
                    if frame.get("event") in TERMINAL_STREAM_EVENTS:
                        # Release the tail before the terminal frame: the
                        # portal settles the turn here and never rewrites
                        # replyText afterwards.
                        for flushed in flush_prose_frames(
                            prose, request_id, session_id
                        ):
                            yield flushed
                    if frame.get("event") == "message_end":
                        # SPEC-024 R-3: attribute the turn to the model that
                        # actually served it (resolved or session default).
                        frame["model"] = bound_model_id
                    yield frame

                # Release the tail before the closing trace frames, for the
                # same paragraph reason as in the loop, and as a safety net for
                # a provider that closes without message_end. flush is
                # idempotent, so the paths above add nothing here.
                for flushed in flush_prose_frames(
                    prose, request_id, session_id
                ):
                    yield flushed
                # SPEC-062 R-3 reveal-on-commit: a normal (unparked) end flushes
                # any portal_copy deliveries generated this turn as secret_delivery
                # frames — the standalone generate-and-copy path, where no gate
                # follows so the Copy button appears at turn end. A turn that
                # parked already drained these onto its card (and broke out above),
                # so the buffer is empty and this is a no-op there.
                self._flush_pending_deliveries(trace_queue)
                # Drain any remaining trace events after the stream completes.
                for decorated in self._drain_trace_queue(
                    trace_queue,
                    request_id,
                    session_id,
                    evidence_frames,
                    execution_requests,
                ):
                    yield decorated
            finally:
                CURRENT_PROSE_REDACTOR.reset(prose_var)
                DELEGATED_TOKEN.reset(token_var)
                CHAT_SESSION_ID.reset(session_var)
                EXECUTION_REQUESTS.reset(requests_var)
                EXECUTION_AUDIT_CONTEXT.reset(audit_var)
                if guard_var is not None:
                    CURRENT_RUN_GUARD.reset(guard_var)
                STREAM_PENDING_DELIVERIES.reset(pending_deliveries_var)
                PENDING_RELEASE_DELIVERIES.reset(release_deliveries_var)
                RELEASE_PERMITS.reset(permits_var)
                TOOL_EVIDENCE_SINK.reset(sink_var)

            # Persist the turn's evidence frames best-effort (SPEC-025 R-1)
            # alongside the conversation snapshot; also covers the park
            # path, which breaks out of the loop above.
            self._persist_evidence(
                session_id, request_id, turn_index, evidence_frames
            )

            # Persist conversation state after the completed turn so it
            # survives restarts (SPEC-017 R-3). Fail-open by design.
            self._snapshot_state(session_id, agent, prose.literals)
        except Exception as exc:  # pragma: no cover - defensive fallback
            self.remember_error(exc, prose.literals if prose is not None else ())
            LOGGER.error("AgentScope streaming failed; falling back to runtime error response: %s", self._last_error)
            async for event in self.fallback_stream(
                request_id=request_id,
                session_id=session_id,
                delta=self.build_provider_error_message(
                    message, session_id, bound_model_id or model_id
                ),
            ):
                yield event

    # --- HITL confirmation bridging (SPEC-020 R-2) ---

    def _flush_pending_deliveries(self, trace_queue: asyncio.Queue) -> None:
        """Emit this stream's buffered portal_copy deliveries as frames.

        SPEC-062 R-3 reveal-on-commit: the standalone generate-and-copy path.
        Drains ``STREAM_PENDING_DELIVERIES`` onto the trace queue so the frames
        are decorated, persisted as evidence, and yielded like any other frame.
        A turn that parked already drained the buffer onto its card, so this is a
        no-op there. ``PENDING_RELEASE_DELIVERIES`` is deliberately NOT flushed:
        a held delivery releases only on a gated commit, so an ungated turn end
        burns it silently (the deny/failure posture).
        """
        from agent_service.services.kernel_middleware import (
            STREAM_PENDING_DELIVERIES,
        )

        pending = STREAM_PENDING_DELIVERIES.get()
        if not pending:
            return
        for delivery in list(pending):
            trace_queue.put_nowait({"type": "secret_delivery", **delivery})
        pending.clear()

    async def _discard_burned_deliveries(
        self, deliveries: list[dict], owner_token: str | None
    ) -> None:
        """Actively discard held portal_copy deliveries that burned (SPEC-062 R-3).

        The deny/failure counterpart to ``_flush_pending_deliveries``: rather than
        reveal a held delivery, destroy it at the gateway so the handle is not
        redeemable — even by a direct owner-scoped fetch — during the hold TTL.
        Best-effort and never fatal: a missing gateway/token or a transport
        failure degrades to the expiry burn. Only the opaque ``delivery_id`` rides
        the call, never the plaintext, and ``owner_token`` is the requester's, so
        the gateway discard is owner-scoped exactly like a redemption.
        """
        delivery_ids = [
            delivery_id
            for delivery_id in (
                delivery.get("delivery_id")
                for delivery in deliveries
                if isinstance(delivery, dict)
            )
            if delivery_id
        ]
        if not delivery_ids:
            return
        from agent_service.tools.gateway_tools import discard_deliveries

        await discard_deliveries(
            self.settings.tool_gateway_url, delivery_ids, owner_token
        )

    def _drain_held_deliveries(self) -> tuple[dict, ...]:
        """Drain both per-stream delivery buffers into a tuple for a parked card.

        SPEC-062 R-3 reveal-on-commit: called from ``_build_confirmation_frame``
        so the held portal_copy handles ride the park across resume. Combines the
        deliveries generated in this stream (``STREAM_PENDING_DELIVERIES``) with
        any carried in from a prior park and not yet released
        (``PENDING_RELEASE_DELIVERIES`` — non-empty only on a re-park that happens
        before a gated commit). Clears both so a later normal-end flush cannot
        double-emit them. Only the opaque handles ride along, never the plaintext.
        """
        from agent_service.services.kernel_middleware import (
            PENDING_RELEASE_DELIVERIES,
            STREAM_PENDING_DELIVERIES,
        )

        held: list[dict] = []
        for buffer in (
            STREAM_PENDING_DELIVERIES.get(),
            PENDING_RELEASE_DELIVERIES.get(),
        ):
            if buffer:
                held.extend(buffer)
                buffer.clear()
        return tuple(held)

    def _build_confirmation_frame(
        self,
        event: object,
        session_id: str,
        user_name: str,
        toolkit: object | None = None,
        turn_index: int = 0,
        evidence_frames: list[dict[str, object]] | None = None,
        run_id: str | None = None,
    ) -> dict[str, object] | None:
        """Register a kernel ASK park and build its confirmation_request frame.

        Returns None for non-park events and when bridging is disabled
        (``hitl_confirm_timeout == 0``), preserving the legacy silent-park
        posture. A parked reply is registered per session and the stream
        ends without ``message_end``; the confirm endpoint resumes it.
        """
        if self.settings.hitl_confirm_timeout <= 0:
            return None
        from agentscope.event import RequireUserConfirmEvent

        if not isinstance(event, RequireUserConfirmEvent):
            return None
        # SPEC-050 follow-up: extract browser element map from the last
        # web.snapshot so confirmation cards show what element will be
        # clicked/typed into, not just the raw ref number.
        browser_element_map = self._extract_browser_element_map(
            evidence_frames or []
        )
        # SPEC-051 R-6: render the card from the maintained session FlowContext
        # (populated by _drain_trace_queue from web.navigate), not a park-time
        # frame walk — authoritative and correct across turns and frame order.
        # Empty when no flow is bound, so the card falls back to tool-level.
        #
        # The headline must describe *this parked batch*: attach the bound
        # flow's summary only when the batch actually carries a browser write —
        # the same predicate (_tool_names_have_browser_write) that arms
        # flow-unlock in _record_flow_approval, so framing and authority can
        # never disagree. A non-browser batch (k8s.*, etc.) parked while a
        # browser flow lingers in the session falls back to action-level
        # rendering instead of inheriting the stale flow headline (the
        # reset-password headline leaking onto a k8s.delete_pod card).
        tool_calls = list(getattr(event, "tool_calls", None) or [])
        gateway_names = self._toolkit_gateway_name_map(toolkit)
        flow_context = FLOW_CONTEXTS.get(session_id)
        browser_flow = (
            flow_context.summary()
            if flow_context is not None
            and self._tool_names_have_browser_write(
                [str(getattr(tc, "name", "") or "") for tc in tool_calls],
                gateway_names,
            )
            else {}
        )
        # SPEC-054 R-1: the card's declared kind comes from the SAME branch as
        # the flow headline, so ``approval_kind`` and ``flow_summary`` can never
        # disagree — ``"flow"`` exactly when a browser-write batch has a bound
        # flow (``browser_flow`` non-empty), ``"action"`` otherwise. This
        # subsumes the v0.34.1 headline-leak patch: a non-browser batch parked
        # while a flow lingers is ``"action"`` and carries no headline, so the
        # leak class is structurally impossible rather than merely gated.
        approval_kind = "flow" if browser_flow else "action"
        pending = CONFIRMATION_REGISTRY.register(
            session_id=session_id,
            user_id=user_name,
            reply_id=str(getattr(event, "reply_id", "") or ""),
            tool_calls=tool_calls,
            timeout=self.settings.hitl_confirm_timeout,
            risk_levels=self._toolkit_risk_map(toolkit),
            gateway_names=gateway_names,
            browser_element_map=browser_element_map,
            browser_flow=browser_flow,
            approval_kind=approval_kind,
            run_id=run_id,
        )
        # SPEC-054 R-3/R-4: assemble the parked payload and the card message
        # ONCE here, so the live frame below and the durable record are fed
        # from a single value and the two paths can never diverge.
        from agent_service.tools.gateway_tools import generation_bearer_token

        pending.requester_delegated_token = generation_bearer_token()
        pending.email_recipient_allowlist = self.settings.email_recipient_allowlist
        # SPEC-062 R-3 reveal-on-commit: attach this stream's held portal_copy
        # deliveries so they ride the park across resume and are released only
        # when the approved gated mutation commits. Ephemeral (like the requester
        # token above): never persisted to the durable record below, so a
        # mid-approval restart drops it and the delivery expires unreleased.
        pending.pending_deliveries = self._drain_held_deliveries()
        pending_calls = pending.pending_calls_payload()
        message = self._confirmation_message(pending_calls)
        # SPEC-055 R-7: redact secret-bearing raw parameter values on the
        # single payload that feeds BOTH the durable record below and the
        # live frame, so an action card never persists or streams a plaintext
        # secret alongside its masked change_request. Runs AFTER the message
        # (which reads raw parameters via curated_effect_sentence) and never
        # touches the fresh payload build_requests re-reads at resume, so the
        # signed args_digest stays byte-identical. flow/legacy cards are left
        # as-is (the helper gates on the action kind).
        redact_pending_calls(pending, pending_calls)
        redactor = CURRENT_PROSE_REDACTOR.get()
        flow_summary = pending.flow_summary()
        if redactor is not None:
            pending_calls = redact_structure(pending_calls, redactor.literals)
            message = redact_assistant_text(message, redactor.literals)
            flow_summary = redact_structure(flow_summary, redactor.literals)
        # SPEC-031 R-1: the durable record is written before the frame
        # below reaches the client, so the card survives re-login and
        # restarts. Best-effort: a store failure degrades to live-only
        # cards, never blocks the park.
        try:
            CONFIRMATION_RECORD_STORE.save_parked(
                make_confirmation_record(
                    confirm_id=pending.confirm_id,
                    session_id=session_id,
                    owner_user_id=user_name,
                    pending_calls=pending_calls,
                    action=pending.highest_action(),
                    # SPEC-033 R-1: anchor the durable card under the
                    # parking turn (same ordinal convention as evidence).
                    turn_index=turn_index,
                    # SPEC-051 R-6: persist the flow headline so the inbox
                    # and session detail replay the same workflow framing.
                    flow_summary=flow_summary,
                    # SPEC-054 R-1/R-4: persist the declared kind and the
                    # card message from the same values the live frame below
                    # carries, so a replayed card states its own kind and
                    # shows the message the operator saw.
                    approval_kind=approval_kind,
                    message=message,
                )
            )
        except Exception as exc:
            LOGGER.warning(
                "confirmation record persistence failed for session %s: %s",
                session_id,
                exc,
            )
        LOGGER.info(
            "kernel confirmation parked",
            extra={
                "session_id": session_id,
                "confirm_id": pending.confirm_id,
                "tool_names": pending.tool_names(),
            },
        )
        frame: dict[str, object] = {
            "type": "confirmation_request",
            "confirm_id": pending.confirm_id,
            "pending_calls": pending_calls,
            "message": message,
            # SPEC-054 R-1: the declared kind rides the live frame so the
            # operator card renders the flow headline (``flow``) or the
            # change-request layout (``action``) from a stated kind rather
            # than inferred ambient session state.
            "approval_kind": approval_kind,
        }
        # SPEC-051 R-6: card-level flow headline rendered above the per-call
        # tool detail; absent when no flow is bound (tool-level fallback).
        # SPEC-054 R-1: emitted from the same branch as approval_kind, so it
        # is present iff approval_kind == "flow".
        if flow_summary is not None:
            frame["flow_summary"] = flow_summary
        return frame

    @staticmethod
    def _extract_browser_element_map(
        evidence_frames: list[dict[str, object]],
    ) -> dict[int, str]:
        """Extract element map from the last web.snapshot result (SPEC-050).

        Confirmation cards for browser interaction tools (web.click, web.type,
        etc.) show the element description from the snapshot, not just the
        raw ref number. Returns an empty dict if no snapshot is found.
        """
        from agent_service.services.hitl_confirmations import (
            parse_snapshot_elements,
        )

        # Walk backwards to find the last web.snapshot result.
        for frame in reversed(evidence_frames):
            if (
                frame.get("type") == "tool_result"
                and frame.get("tool_name") == "web.snapshot"
                and frame.get("status") == "success"
            ):
                # The snapshot text is in data.snapshot.
                data = frame.get("data")
                if isinstance(data, dict):
                    snapshot_text = data.get("snapshot")
                    if isinstance(snapshot_text, str):
                        return parse_snapshot_elements(snapshot_text)
        return {}

    @staticmethod
    def _record_resolution(
        session_id: str,
        confirm_id: str,
        status: str,
        decider_user_id: str | None,
        decision: str | None,
    ) -> None:
        """Best-effort durable outcome write (SPEC-031 R-1).

        The live stream already carried the result; a store failure only
        degrades the persisted card/inbox history, never the decision.
        """
        try:
            CONFIRMATION_RECORD_STORE.mark_resolved(
                session_id, confirm_id, status, decider_user_id, decision
            )
        except Exception as exc:
            LOGGER.warning(
                "confirmation record resolution failed for session %s: %s",
                session_id,
                exc,
            )

    # --- Signed execution requests and receipts (SPEC-037 R-2/R-4/R-5) ---

    def _prepare_executions(
        self,
        pending: PendingConfirmation,
        decider_user_id: str,
        confirmed: bool,
        request_id: str,
        session_id: str,
    ) -> tuple[dict[str, dict], str | None]:
        """Build, persist, and audit the signed requests (SPEC-037 R-2).

        Returns ``(requests_by_call_id, rejection_reason)``. Approved
        batches with a provisioned key produce one signed request per
        parked call; a missing key rejects the whole batch fail-closed
        (the resumed stream reports the rejection through the tool
        boundary) and audits ``execution_rejected``
        (``signing_unavailable``). Denials construct nothing.
        """
        if not confirmed:
            return {}, None
        key = self.settings.execution_signing_key
        if not key:
            LOGGER.warning(
                "mutating resume rejected: no execution signing key "
                "provisioned (confirm_id=%s)",
                pending.confirm_id,
            )
            for call in pending.pending_calls_payload():
                self._emit_execution_event(
                    "execution_rejected",
                    "deny",
                    {
                        "confirm_id": pending.confirm_id,
                        "call_id": call.get("call_id"),
                        "tool_name": call.get("tool_name"),
                        "reason": REASON_SIGNING_UNAVAILABLE,
                    },
                    request_id,
                    session_id,
                    decider_user_id,
                )
            return {}, REASON_SIGNING_UNAVAILABLE
        requests_by_call: dict[str, dict] = {}
        # The signed envelope carries an ``args_digest``, never the raw
        # arguments, so the authoring-trace capture below has to be handed
        # them separately (SPEC-055 R-2). One read of the parked payload
        # yields both the arguments and the risk tier the toolkit
        # snapshotted at park time; it is raw at resume because
        # ``redact_parameters`` is a display/at-rest projection applied to
        # copies, never to a signing input.
        calls_by_id: dict[str, dict] = {
            str(call.get("call_id")): call
            for call in pending.pending_calls_payload()
        }
        # SPEC-063 R-4: an approved resume under durable admission signs a v3
        # envelope bound to the parked batch's originating run. The identity is
        # inherited from ``pending.run_id`` and never re-minted here; a resume
        # missing it (e.g. a card parked before the cutover) fails closed rather
        # than degrading to a v2 envelope that the bound v3 guard would reject
        # mid-dispatch. Inert when admission is disabled (recovery is None).
        sign_run_id: str | None = None
        sign_epoch: str | None = None
        if self._execution_recovery() is not None:
            if not pending.run_id:
                LOGGER.warning(
                    "mutating resume rejected: no durable run identity on the "
                    "parked batch (confirm_id=%s)",
                    pending.confirm_id,
                )
                for call in pending.pending_calls_payload():
                    self._emit_execution_event(
                        "execution_rejected",
                        "deny",
                        {
                            "confirm_id": pending.confirm_id,
                            "call_id": call.get("call_id"),
                            "tool_name": call.get("tool_name"),
                            "reason": REASON_REQUEST_MISSING,
                        },
                        request_id,
                        session_id,
                        decider_user_id,
                    )
                return {}, REASON_REQUEST_MISSING
            sign_run_id = pending.run_id
            sign_epoch = self.settings.execution_admission_epoch
        for request in build_requests(
            pending,
            decider_user_id,
            key,
            run_id=sign_run_id,
            admission_epoch=sign_epoch,
        ):
            requests_by_call[request["call_id"]] = request
            self._persist_execution_request(request)
            call = calls_by_id.get(str(request["call_id"])) or {}
            # Being *signed* is not the same as being a mutation, so the
            # trace gate is the tier rather than the signature. A read-tier
            # call reaches this seam whenever it is off the middleware's
            # curated auto-allow list — an unvetted read tool parks and is
            # signed like any other ASK-gated call — and it is not a replay
            # step: a graduated flow declares ``risk_class: write``, so a
            # read in its step list is refused by R-4's blast-radius
            # re-validation, which derives read-tier from the same
            # ``BROWSER_WRITE_TOOLS`` set rather than keeping a second list.
            # The platform's single risk→action mapping decides, so this seam
            # and the policy bridge cannot disagree about what a mutation
            # is; a call with no known tier is not captured either, which
            # degrades to "no graduation candidate" — the outcome R-2
            # already accepts for a store failure — rather than polluting a
            # store that outlives every receipt. The flow-unlock site needs
            # no such gate: it is reachable only through
            # ``BROWSER_WRITE_TOOLS``.
            if RISK_LEVEL_ACTIONS.get(call.get("risk_level")) == "tools:mutate":
                self._capture_authoring_step(
                    request, dict(call.get("parameters") or {})
                )
            self._emit_execution_event(
                "execution_requested",
                "success",
                {
                    "confirm_id": request["confirm_id"],
                    "execution_id": request["execution_id"],
                    "call_id": request["call_id"],
                    "tool_name": request["tool_name"],
                    "args_digest": request["args_digest"],
                    "decider_user_id": request["decider_user_id"],
                    "owner_user_id": request["owner_user_id"],
                },
                request_id,
                session_id,
                decider_user_id,
            )
        return requests_by_call, None

    def _persist_execution_request(self, request: dict) -> None:
        """Best-effort durable request write (SPEC-037 R-4).

        Same posture as the SPEC-031 claim-time writes: a store failure
        degrades audit completeness, never the resumed stream.
        """
        try:
            EXECUTION_RECORD_STORE.save_request(make_execution_record(request))
        except Exception as exc:
            LOGGER.warning(
                "execution record request write failed for %s: %s",
                request["execution_id"],
                exc,
            )

    def _capture_authoring_step(self, envelope: dict, parameters: dict) -> None:
        """Best-effort authoring-trace append (SPEC-055 R-2).

        Runs at the same seam as ``_persist_execution_request`` and on the
        same already-signed envelope, so a trace step exists only for a
        *mutating* call a human authorized (per-action, SPEC-054) or
        admitted under a flow authority (SPEC-051) **and** a key signed —
        never for a parked, denied or read-tier call, and never for an
        unsigned one (a missing signing key rejects the batch before this
        seam is reached). The tier gate lives at the two call sites, not
        here: the per-action site reads the parked call's snapshotted
        ``risk_level``, and the flow-unlock site is reachable only through
        ``BROWSER_WRITE_TOOLS``. Both approval kinds append, so a mixed
        session yields one coherent ordered trace; the store assigns the
        position, because only the store sees the whole sequence.

        Same posture as the write beside it: a trace failure degrades
        graduation candidacy — the session simply produces no candidate —
        and never blocks the mutation's execution, its signed request, or
        its receipt. Called *after* ``_persist_execution_request`` so the
        tamper evidence is durable before the derived trace is attempted.

        The arguments are parameterized here, before the write: the store
        persists exactly what it is given, and a trace outlives the receipts
        that would otherwise be the only copy of those arguments, so a
        literal credential must never reach it. Only ``execution_id`` /
        ``confirm_id`` *references* are stored — the signed request, receipt
        and outcome stay in ``execution_records``, so the trace never
        duplicates tamper evidence (ADR-0009).
        """
        session_id = str(envelope.get("session_id") or "")
        if not session_id:
            return
        tool_name = str(envelope.get("tool_name") or "")
        execution_id = str(envelope.get("execution_id") or "")
        try:
            AUTHORING_TRACE_STORE.append_step(
                make_trace_step(
                    session_id=session_id,
                    tool_name=tool_name,
                    # The signed envelope carries an ``args_digest``, never
                    # the raw arguments, so the caller hands them in from the
                    # same in-memory copy the signer digested.
                    args=parameterize_for_trace(tool_name, parameters),
                    # Date the step from the signature, not from the append:
                    # ``requested_at`` is the moment the mutation was
                    # authorized, and it is already in the trace store's
                    # canonical ``%Y-%m-%dT%H:%M:%SZ`` form.
                    captured_at=str(envelope.get("requested_at") or ""),
                    execution_id=execution_id or None,
                    confirm_id=str(envelope.get("confirm_id") or "") or None,
                )
            )
        except Exception as exc:
            LOGGER.warning(
                "authoring trace capture failed for %s: %s",
                execution_id or session_id,
                exc,
            )

    def _sign_flow_execution(
        self, tool_call: object, gateway_tool_name: str
    ) -> dict | None:
        """Auto-sign one unlocked browser write under a flow authority (SPEC-051 R-1/R-3).

        Armed as ``GatewayPermissionMiddleware``'s ``flow_signer``. Returns a
        signed execution envelope — injecting it into the shared
        ``EXECUTION_REQUESTS`` map so the tool closure verifies and hands off
        exactly like a card-approved call — or ``None`` to fail safe and let the
        write park. ``None`` (→ ASK) whenever: the tool is not a browser write;
        the session id is absent; no live flow authority exists (TTL lapse or
        ``ttl <= 0`` disable); the bound ``FlowContext`` identity no longer
        matches the approval (a rebind — the guard that eliminates the ADR-0007
        cross-flow window); the execution state is not armed
        (``EXECUTION_REQUESTS`` is not a dict); or no signing key is
        provisioned. Each unlocked write is still individually signed,
        persisted, audited (``execution_requested``), and appended to the
        session's authoring trace, and the tool-gateway deviation guard still
        bounds it on invocation.
        """
        from agent_service.tools.gateway_tools import (
            CHAT_SESSION_ID,
            EXECUTION_AUDIT_CONTEXT,
            EXECUTION_REQUESTS,
        )

        if gateway_tool_name not in BROWSER_WRITE_TOOLS:
            # SPEC-055 R-5: enforce this function's own stated scope — "one
            # unlocked *browser* write" — rather than inheriting it from the
            # middleware that happens to be its only caller today. A browser
            # flow authority is scoped to a web target the operator approved;
            # auto-signing an infra mutation under it would execute a write no
            # decision of theirs covers, which is the one thing the OQ-2
            # per-action fallback must never do. Ahead of every side effect
            # below — the ``EXECUTION_REQUESTS`` injection, the durable
            # execution record, the authoring-trace step and the
            # ``execution_requested`` audit — so a refused name leaves no
            # trace of a request that was never made. (The lookups it also
            # precedes are pure reads every other ``None`` path takes too;
            # the side effects are what the position buys.) Fail-safe:
            # ``None`` parks the call, exactly as an absent authority would.
            return None

        # SPEC-063 R-4 (T-21): gate at the flow-signing seam itself, not only at
        # the permission middleware that precedes it. A stopped run must never
        # auto-sign a flow-unlocked browser write — signing persists an intent
        # registration, an authoring-trace step, and an ``execution_requested``
        # audit, so the check belongs ahead of every one of those side effects.
        # Fail safe: ``None`` parks the write exactly as an absent authority
        # would, and the durable worker claim/final-send gates stay the backstop.
        # Inert when no guard is bound (admission disabled), so the legacy
        # flow-unlock path is byte-identical.
        from agent_service.services.execution_run_guard import current_guard

        flow_guard = current_guard()
        if flow_guard is not None and flow_guard.stopped():
            return None

        session_id = CHAT_SESSION_ID.get()
        if not session_id:
            return None
        approval = FLOW_APPROVALS.get(session_id)
        if approval is None:
            return None
        context = FLOW_CONTEXTS.get(session_id)
        if context is None or context.identity() != approval.identity():
            # No bound flow, or the flow was rebound to a different skill/origin
            # since approval — fail safe and re-park (SPEC-051 R-1 identity
            # guard). This is what eliminates the cross-flow auto-sign window.
            return None
        requests = EXECUTION_REQUESTS.get()
        if not isinstance(requests, dict):
            # Execution state not armed for this turn — nothing to inject into,
            # so the write cannot be verified/handed off; park it instead.
            return None
        key = self.settings.execution_signing_key
        if not key:
            return None
        call_id = str(getattr(tool_call, "id", "") or "")
        if not call_id:
            return None
        # Parse the parked arguments exactly as the card path does, so the
        # args_digest matches what the tool closure recomputes from the invoked
        # kwargs (SPEC-037 R-3). Display enrichment never touches parameters.
        raw = getattr(tool_call, "input", "") or ""
        try:
            parsed = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            parsed = {}
        parameters = parsed if isinstance(parsed, dict) else {}
        # SPEC-063 R-4: a flow-unlocked write under durable admission signs a v3
        # envelope bound to the flow authority's run. The authority recorded at
        # the approving card carries ``run_id``; if it predates the cutover the
        # identity is absent, so fail safe and park (return None) rather than
        # sign a v2 envelope the bound v3 guard would reject mid-dispatch.
        sign_run_id: str | None = None
        sign_epoch: str | None = None
        if self._execution_recovery() is not None:
            if not approval.run_id:
                return None
            sign_run_id = approval.run_id
            sign_epoch = self.settings.execution_admission_epoch
        envelope = build_flow_request(
            call_id=call_id,
            tool_name=gateway_tool_name,
            parameters=parameters,
            flow_approval=approval,
            key=key,
            run_id=sign_run_id,
            admission_epoch=sign_epoch,
        )
        # Inject BEFORE the tool closure runs (the permission check precedes
        # acting), so _verify_execution_request finds it by call_id and
        # _handoff_execution presents it to the worker.
        requests[call_id] = envelope
        self._persist_execution_request(envelope)
        # Same seam as the card path, so a session mixing per-action writes
        # and flow-unlocked writes yields one ordered trace (SPEC-055 R-2).
        # ``parameters`` here is the very object just digested into
        # ``envelope["args_digest"]``.
        self._capture_authoring_step(envelope, parameters)
        audit_context = EXECUTION_AUDIT_CONTEXT.get() or {}
        self._emit_execution_event(
            "execution_requested",
            "success",
            {
                "confirm_id": envelope["confirm_id"],
                "execution_id": envelope["execution_id"],
                "call_id": envelope["call_id"],
                "tool_name": envelope["tool_name"],
                "args_digest": envelope["args_digest"],
                "decider_user_id": envelope["decider_user_id"],
                "owner_user_id": envelope["owner_user_id"],
            },
            str(audit_context.get("request_id") or ""),
            session_id,
            envelope["decider_user_id"],
        )
        return envelope

    @staticmethod
    def _observe_flow_binding(frame: dict[str, object], session_id: str) -> None:
        """Record the session's FlowContext from a web.navigate result (SPEC-051 R-1/R-6).

        The tool-gateway binds a flow on ``web.navigate`` and rides it back on
        ``data["flow"]``; this is the single population point for the kernel's
        reflection of that binding (both the live and resumed streams drain
        through ``_drain_trace_queue``). A successful navigate binding a
        different skill/origin overwrites the context — exactly how a rebind is
        detected and the next write re-parks. Non-navigate frames, failures, and
        results without a flow dict are ignored.
        """
        if frame.get("type") != "tool_result":
            return
        if frame.get("tool_name") != "web.navigate":
            return
        if frame.get("status") != "success":
            return
        data = frame.get("data")
        if not isinstance(data, dict):
            return
        flow = data.get("flow")
        if not isinstance(flow, dict):
            return
        FLOW_CONTEXTS.record(session_id, flow)

    @staticmethod
    def _observe_flow_invalidation(
        frame: dict[str, object],
        session_id: str,
        evidence_frames: list[dict[str, object]],
    ) -> None:
        """Drop the session's flow reflection and authority when the binding dies.

        SPEC-054 R-2: ``FLOW_APPROVALS`` auto-signs later browser writes under
        an authority scoped to the gateway's flow binding, so it must never
        outlive that binding. Two shapes end it:

        - a refusal in ``FLOW_KILLING_ERROR_CODES`` — the origin deviated, the
          flow was denied, a redirect was halted, or an envelope claimed a flow
          authority the gateway no longer holds;
        - a failed ``web.navigate`` that **was binding** a flow (it carried a
          ``skill_id``). The gateway nulls ``entry.flow`` on that path only —
          "A pre-existing flow is left intact — the page did not move" — so a
          plain in-flow navigation failure keeps the binding, the kernel's
          reflection stays truthful, and clearing would cost a legitimately
          one-gated flow an extra approval card (ADR-0007).

        Both stores drop together: a context without an authority re-renders the
        next card tool-level, and an authority without a context is what the R-1
        identity guard already refuses to auto-sign, so dropping either alone
        would only leave the two disagreeing.

        This is the kernel-side half of ADR-0010's two-part backstop and is not
        sufficient alone — it depends on the kernel draining the refusal before
        the next write is auto-signed, which is a race. The gateway's own
        ``approval_kind`` refusal is the enforcement boundary; this keeps the
        card honest and avoids spending a denied call to find out.
        """
        if frame.get("type") != "tool_result":
            return
        error = frame.get("error")
        error = error if isinstance(error, dict) else {}
        code = str(error.get("code") or "")
        killed = code in FLOW_KILLING_ERROR_CODES or (
            frame.get("tool_name") == "web.navigate"
            and code == "BROWSER_NAVIGATION_ERROR"
            and AgentKernel._navigate_bound_a_flow(frame, evidence_frames)
        )
        if not killed:
            return
        FLOW_CONTEXTS.clear(session_id)
        FLOW_APPROVALS.clear(session_id)
        LOGGER.info(
            "browser flow authority cleared",
            extra={
                "session_id": session_id,
                "tool_name": str(frame.get("tool_name") or ""),
                "error_code": code,
            },
        )

    @staticmethod
    def _navigate_bound_a_flow(
        frame: dict[str, object],
        evidence_frames: list[dict[str, object]],
    ) -> bool:
        """True when the failed navigate carried a ``skill_id`` (a bind attempt).

        Pairs the result with its ``tool_call`` frame by ``call_id`` — the same
        backward walk ``_extract_browser_element_map`` uses over the turn's
        evidence frames, which the drain loop appends to in emission order. An
        unpaired result (no call frame in this turn) answers ``False``: the
        kernel declines to guess and leaves the refusal to the gateway, which is
        the fail-closed boundary either way.
        """
        call_id = frame.get("call_id")
        if not call_id:
            return False
        for candidate in reversed(evidence_frames):
            if (
                candidate.get("type") == "tool_call"
                and candidate.get("call_id") == call_id
            ):
                parameters = candidate.get("parameters")
                return (
                    isinstance(parameters, dict)
                    and bool(parameters.get("skill_id"))
                )
        return False

    def _drain_trace_queue(
        self,
        trace_queue: asyncio.Queue,
        request_id: str,
        session_id: str,
        evidence_frames: list[dict[str, object]],
        execution_requests: dict[str, dict],
    ) -> list[dict[str, object]]:
        """Decorate queued trace frames and close any landed executions."""
        frames: list[dict[str, object]] = []
        while not trace_queue.empty():
            trace = trace_queue.get_nowait()
            decorated = {
                **trace,
                "request_id": request_id,
                "session_id": session_id,
            }
            if decorated.get("type") in EVIDENCE_FRAME_TYPES:
                evidence_frames.append(decorated)
            # SPEC-051 R-1/R-6: keep the session FlowContext current before any
            # later write in this turn parks (card headline) or auto-signs
            # (identity guard). Single population point for both streams.
            self._observe_flow_binding(decorated, session_id)
            # SPEC-054 R-2: and the single invalidation point, so a flow-killing
            # refusal drops the reflection and the auto-signing authority
            # together before any later write in this turn can ride them.
            self._observe_flow_invalidation(
                decorated, session_id, evidence_frames
            )
            self._observe_tool_result(decorated, execution_requests)
            frames.append(decorated)
        return frames

    def _observe_tool_result(
        self,
        frame: dict[str, object],
        execution_requests: dict[str, dict],
    ) -> None:
        """Close the signed execution when its tool result lands (SPEC-037 R-4/R-5).

        A receipt closes a request that actually ran; an invocation-boundary
        rejection (R-3) marks the row rejected without a receipt — the call
        never reached the gateway. Requests are looked up by the parked
        call id riding the evidence frame.
        """
        if frame.get("type") != "tool_result":
            return
        request = execution_requests.get(frame.get("call_id"))
        key = self.settings.execution_signing_key
        if request is None or not key:
            return
        error = frame.get("error")
        error = error if isinstance(error, dict) else {}
        if error.get("code") == "EXECUTION_REJECTED":
            reason = error.get("reason") or "unknown"
            digest_match = (
                False if reason == REASON_ARGS_DIGEST_MISMATCH else None
            )
            try:
                EXECUTION_RECORD_STORE.mark_rejected(
                    request["confirm_id"],
                    request["call_id"],
                    reason,
                    digest_match,
                )
            except Exception as exc:
                LOGGER.warning(
                    "execution record rejection write failed for %s: %s",
                    request["execution_id"],
                    exc,
                )
            # The rejection audit already went out at the invocation
            # boundary (gateway_tools); nothing more to emit here.
            return
        if error.get("code") == "OUTCOME_UNKNOWN":
            # SPEC-063 R-3b (T-17): a v3 caller timeout / transport uncertainty
            # is typed uncertainty, never a definitive outcome. The invocation
            # coordinator already stopped the run and appended the attributed
            # ``wait_expired`` / ``transport_uncertain`` observation to the
            # durable ledger, where a late worker result stays appendable
            # without deleting that observation. Writing the legacy synthetic
            # receipt here would falsely close the v2 row as ``timeout`` /
            # ``failed`` and contradict the unknown outcome, so the row is
            # deliberately left unclosed (``requested``) and no completion event
            # is emitted. The admission-disabled ``TIMEOUT`` receipt path below
            # is unchanged, and read-tier calls never reach the coordinator, so
            # legacy and read-tier handling stay separate.
            return
        if frame.get("status") == "success":
            status = "succeeded"
        elif error.get("code") == "TIMEOUT":
            status = "timeout"
        else:
            status = "failed"
        receipt = build_receipt(
            request,
            status,
            frame,
            str(frame.get("request_id") or ""),
            key,
        )
        try:
            EXECUTION_RECORD_STORE.save_receipt(
                request["confirm_id"],
                request["call_id"],
                receipt,
                True,
            )
        except Exception as exc:
            LOGGER.warning(
                "execution record receipt write failed for %s: %s",
                request["execution_id"],
                exc,
            )
        # After the receipt, so the tamper evidence is durable before the
        # derived trace amendment is attempted (same ordering R-2 uses
        # between _persist_execution_request and _capture_authoring_step).
        self._observe_step_origin(request, frame, status)
        self._emit_execution_event(
            "execution_completed",
            "success" if status == "succeeded" else "error",
            {
                "confirm_id": request["confirm_id"],
                "execution_id": request["execution_id"],
                "call_id": request["call_id"],
                "tool_name": request["tool_name"],
                "status": status,
                "duration_ms": self._execution_duration_ms(request),
                "request_id": receipt["request_id"],
            },
            str(frame.get("request_id") or ""),
            str(frame.get("session_id") or ""),
            request["decider_user_id"],
        )

    def _observe_original_step_origin(self, request, original, current_request_id):
        """Consume accepted original evidence synchronously, outside tool frames."""
        self._observe_step_origin(
            request, {}, "succeeded", original=original,
            signing_key=self.settings.execution_signing_key,
            current_request_id=current_request_id,
        )

    @staticmethod
    def _observe_step_origin(
        request: dict, frame: dict[str, object], status: str, *,
        original=None, signing_key=None, current_request_id=None,
    ) -> None:
        """Amend the captured step with the origin it landed on (SPEC-055 R-4).

        R-2 appends a trace step at the *signing* seam, before the call runs,
        so the step cannot carry the origin the interaction landed on. This is
        the only place the kernel can read it: the tool-gateway reports
        ``data["url"]`` on every browser result, and by the time the frame
        reaches the receipt the value is already gone elsewhere —
        ``build_receipt`` digests the outcome into ``outcome_digest`` and never
        stores it, and the execution records are swept at 30 days while a trace
        must outlive them (ADR-0009). The URL is legible for exactly one
        moment; recording it here is what makes it durable.

        Only a ``succeeded`` result is recorded, and ``status`` is the value
        just written into the receipt rather than a second reading of the
        frame, so the trace and the receipt cannot disagree about which
        mutations landed. A failed or timed-out write may still report the URL
        it was attempting — corroborating that as "landed on target" would let
        a mutation that never happened count toward graduation.

        Scoped to ``BROWSER_WRITE_TOOLS`` rather than to "any frame with a
        url". ``flow_origin`` is evidence about the web target a *mutation*
        landed on, and a read-tier result carrying an unrelated link would
        otherwise attach an origin to a step graduation has no reason to
        compare — or, worse, to a step that is not in the trace at all. The
        same set already gates the flow-unlock capture site, so the two ends
        of the amendment cannot disagree about which steps carry origins.

        A step whose origin is never observed stays ``NULL``, which R-4 reads
        as *unverified* rather than as a drift. Three shapes produce that, and
        all fail toward refusing the draft: a result that did not succeed, a
        payload over the evidence frame's size guard (``_make_full_data`` omits
        ``data`` entirely rather than truncating it), and a gateway that
        reported no URL.

        Best-effort on the same terms as the capture beside it: a store
        failure degrades graduation candidacy and never touches the receipt
        already written, the audit event about to be emitted, or the resumed
        stream.
        """
        if request.get("protocol_version") == 3:
            from agent_service.services.execution_protocol import ProtocolError, VerifiedOriginal

            if not isinstance(original, VerifiedOriginal) or not current_request_id:
                return
            try:
                original.revalidate(request, signing_key)
            except ProtocolError:
                return
            if original.observation["request_id"] != current_request_id:
                return
            frame = original.result
            status = "succeeded" if frame.get("status") == "success" else "failed"
        if status != "succeeded":
            return
        if request.get("tool_name") not in BROWSER_WRITE_TOOLS:
            return
        session_id = str(request.get("session_id") or "")
        execution_id = str(request.get("execution_id") or "")
        if not session_id or not execution_id:
            return
        data = frame.get("data")
        if not isinstance(data, dict):
            return
        origin = origin_of_url(data.get("url"))
        if origin is None:
            return
        try:
            AUTHORING_TRACE_STORE.record_step_origin(
                session_id, execution_id, origin
            )
        except Exception:
            LOGGER.warning("authoring trace origin write failed")

    @staticmethod
    def _execution_duration_ms(request: dict) -> int:
        """Whole-milliseconds between request signing and receipt close."""
        try:
            started = datetime.strptime(
                request["requested_at"], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            return 0
        elapsed = datetime.now(timezone.utc) - started
        return max(int(elapsed.total_seconds() * 1000), 0)

    def _emit_execution_event(
        self,
        event_type: str,
        outcome: str,
        details: dict,
        request_id: str,
        session_id: str,
        decider_user_id: str,
    ) -> None:
        """Emit one execution audit event through the canonical emitter.

        Fire-and-forget with ``confirm_id`` in details and the resume's
        ``x-request-id`` forwarded, so the trail correlates
        ``confirmation_decided`` → ``execution_requested`` →
        ``tool_invoked`` → ``execution_completed`` (SPEC-037 R-5).
        """
        event = build_audit_event(
            event_type,
            request_id,
            outcome,
            details=details,
            subject=decider_user_id,
            username=decider_user_id,
            session_id=session_id,
        )
        emit_audit_event(self.settings, event)

    @staticmethod
    def _toolkit_risk_map(toolkit: object | None) -> dict[str, str]:
        """Map sanitized tool names to gateway risk tiers (SPEC-021 R-3).

        Only gateway-backed tools carry ``gateway_risk_level``; task tools
        and builtins stay absent, so their parked entries (which cannot
        happen today — they are auto-allowed) would omit ``risk_level``.
        """
        risks: dict[str, str] = {}
        for group in getattr(toolkit, "tool_groups", None) or []:
            for tool in getattr(group, "tools", None) or []:
                name = getattr(tool, "name", None)
                risk = getattr(tool, "gateway_risk_level", None)
                if name and risk:
                    risks[name] = risk
        return risks

    @staticmethod
    def _toolkit_gateway_name_map(toolkit: object | None) -> dict[str, str]:
        """Map sanitized tool names to dotted gateway canonical names.

        Parked tool calls carry the model-visible sanitized name, but the
        signed execution envelope (and the worker's gateway invocation)
        needs the canonical name the registry resolves; the envelope would
        otherwise fail closed with TOOL_NOT_FOUND after approval.
        """
        names: dict[str, str] = {}
        for group in getattr(toolkit, "tool_groups", None) or []:
            for tool in getattr(group, "tools", None) or []:
                name = getattr(tool, "name", None)
                gateway_name = getattr(tool, "gateway_tool_name", None)
                if name and gateway_name:
                    names[name] = gateway_name
        return names

    @staticmethod
    def _confirmation_message(pending_calls: list[dict[str, object]]) -> str:
        """The card's informative top-line message (SPEC-054 R-3/R-4).

        Sources from the curated change-request effect sentence where the
        parked batch has one, so the card explains *what changes*; otherwise
        falls back to the deterministic generic constant. The gateway
        middleware's ASK reason is deliberately **not** wired through verbatim:
        it interpolates the *sanitized* tool name (``web_click``), breaking the
        dotted-canonical convention, and explains an implementation detail
        ("outside the auto-approve allow-list") rather than the change (R-3).
        Computed once at park time and fed to both the live frame and the
        durable record from that single value, so the two cannot diverge (R-4).
        """
        for call in pending_calls:
            if call.get("tool_name") == "secrets.deliver" and call.get("change_request"):
                return call["change_request"]["summary"]
            sentence = curated_effect_sentence(
                str(call.get("tool_name", "")),
                call.get("parameters") or {},
                call.get("display_hint"),
            )
            if sentence:
                return sentence
        return "Tool execution requires your confirmation."

    @staticmethod
    def _tool_names_have_browser_write(
        tool_names: list[str], gateway_names: dict[str, str]
    ) -> bool:
        """True when any sanitized tool name maps to a write-tier browser tool.

        Single source of truth for the R-1 browser-write predicate, shared by
        the card-headline gate (``_build_confirmation_frame``) and flow-unlock
        authority arming (``_record_flow_approval``) so framing and authority
        can never disagree about whether a batch is a browser-write batch.
        Uses the canonical dotted gateway names captured at park time (the
        model-visible names are sanitized) matched against
        ``BROWSER_WRITE_TOOLS``.
        """
        for sanitized in tool_names:
            gateway_name = gateway_names.get(sanitized, sanitized)
            if gateway_name in BROWSER_WRITE_TOOLS:
                return True
        return False

    @staticmethod
    def _batch_has_browser_write(pending: PendingConfirmation) -> bool:
        """True when the parked batch contains a write-tier browser tool (R-1).

        A batch of only non-browser writes (``k8s.*``, etc.) or only read-tier
        browser probes does not arm flow-unlock.
        """
        return AgentKernel._tool_names_have_browser_write(
            pending.tool_names(), pending.gateway_names
        )

    def _record_flow_approval(
        self,
        pending: PendingConfirmation,
        decider_user_id: str,
        session_id: str,
    ) -> None:
        """Record the flow authority when an approved batch holds a browser write.

        SPEC-051 R-1: the authority is scoped to the session AND the approved
        flow's identity (``skill_id`` + ``origin``) captured on the parked
        card's ``browser_flow`` (R-6), so only that flow's subsequent browser
        writes unlock. With no bound flow identity there is nothing to scope to,
        and a batch without a browser write must not arm browser flow-unlock —
        either way nothing is recorded and every write keeps parking. TTL comes
        from settings; ``0`` records an immediately-expired authority
        (flow-unlock disabled — the pre-fix posture).

        SPEC-054 R-2 adds a third condition: the bound flow must be
        ``risk_class == "write"``. A read-class binding can never execute an
        unlocked write — the gateway refuses it ``BROWSER_FLOW_READ_ONLY`` on
        every attempt — so arming an authority there produced an approval that
        silently bought nothing while the card claimed a flow gate. The card
        still renders the read-class binding's headline; only the auto-signing
        authority is withheld, and each write keeps parking.
        """
        if not self._batch_has_browser_write(pending):
            return
        browser_flow = pending.browser_flow or {}
        skill_id = str(browser_flow.get("skill_id") or "")
        origin = str(browser_flow.get("origin") or "")
        if not skill_id and not origin:
            return
        if str(browser_flow.get("risk_class") or "") != "write":
            return
        FLOW_APPROVALS.record(
            session_id=session_id,
            confirm_id=pending.confirm_id,
            owner_user_id=pending.user_id,
            decider_user_id=decider_user_id,
            skill_id=skill_id,
            origin=origin,
            ttl=self.settings.browser_flow_approval_ttl,
            # SPEC-063 R-4: the flow authority retains the parked batch's
            # originating run, so a later auto-signed write in this flow
            # inherits the same ``run_id`` instead of minting a replacement.
            run_id=pending.run_id,
        )

    async def resume_confirmation(
        self,
        session_id: str,
        pending: PendingConfirmation,
        decision: str,
        user_name: str,
        request_id: str,
        bearer_token: str | None = None,
        model_id: str | None = None,
        owner_user_name: str | None = None,
    ) -> AsyncIterator[dict[str, object]]:
        """Resume a parked reply with the operator's decision (SPEC-020 R-2).

        The caller must pass the entry as returned by
        ``ConfirmationRegistry.claim`` — the claim runs before response
        headers go out, so one parked batch can never be resumed twice.
        Who may decide is enforced upstream by the platform-gateway
        approval-tier bridge (SPEC-030 R-3): a tier_2 confirmation can
        legitimately be resumed by a confirmer other than the session
        owner, so the kernel no longer asserts registry ownership.
        The resumed stream follows the v2 frame contract and begins with
        the matching ``confirmation_result`` frame. The confirmer's
        bearer token rides ``DELEGATED_TOKEN`` so the tool-gateway sees
        the approving identity on any resulting invocation.

        ``user_name`` is the DECIDER (the approver who answered this
        card) and attributes the resolution, the signed executions, and
        the flow authority. ``owner_user_name`` is the SESSION OWNER
        (the original requester); SPEC-054 R-2 lets an unbound resumed
        turn park ANOTHER per-action card, and that new card must be
        owned by the requester — not the approver who happened to resume
        the turn — or the tier_2 self-approval rule would block the same
        approver from deciding the next card. It defaults to ``user_name``
        when the caller cannot supply the owner (e.g. an ownerless
        session), preserving the prior attribution.
        """
        from agentscope.event import ConfirmResult, UserConfirmResultEvent

        from agent_service.services.kernel_middleware import (
            PENDING_RELEASE_DELIVERIES,
            RELEASE_PERMITS,
            STREAM_PENDING_DELIVERIES,
            TOOL_EVIDENCE_SINK,
        )
        from agent_service.services.execution_run_guard import CURRENT_RUN_GUARD
        from agent_service.tools.gateway_tools import (
            CHAT_SESSION_ID,
            DELEGATED_TOKEN,
            EXECUTION_AUDIT_CONTEXT,
            EXECUTION_REJECTION,
            EXECUTION_REQUESTS,
            GENERATION_OWNER_TOKEN,
        )

        # Pass the session's pinned model (SPEC-024 R-3) so the resumed
        # stream rebuilds against the same model that parked it.
        agent, _user_msg_cls, _bound_model_id = await self.ensure_agent(
            session_id, bearer_token, model_id
        )
        # SPEC-025 R-1: resumed frames belong to the same assistant turn as
        # the pre-park frames — no user message was added by the park, so
        # the count reproduces the original turn ordinal.  The original
        # stream captured its turn_index BEFORE the user message entered
        # the context (stream_events line ~892); the confirmation stream
        # runs AFTER the user message is already in context, so subtract 1
        # to align with the pre-park ordinal.
        turn_index = max(0, self._count_user_turns(agent) - 1)
        evidence_frames: list[dict[str, object]] = []
        # SPEC-049 R-5 applied to chat prose, resumed: the operator's message
        # is already in the context here, so the harvest needs no extra text.
        # A resumed turn is a continuation of the same assistant reply, and
        # the model restating the password after an approval is exactly as
        # much a leak as restating it before one.
        prose = self._prose_redactor(agent, "", session_id)
        confirmed = decision == "approve"
        confirm_event = UserConfirmResultEvent(
            reply_id=pending.reply_id,
            confirm_results=[
                ConfirmResult(confirmed=confirmed, tool_call=tool_call)
                for tool_call in pending.tool_calls
            ],
        )

        # SPEC-037 R-2: the signing envelope is built where the decision
        # and the parked arguments are both in hand — one signed request
        # per approved parked call, persisted and audited before any
        # invocation. Denials construct nothing; a missing key rejects
        # the whole batch fail-closed.
        execution_requests, execution_rejection = self._prepare_executions(
            pending, user_name, confirmed, request_id, session_id
        )

        # SPEC-051 R-1: approving a card whose batch contains a browser write
        # records a session+identity-scoped flow authority BEFORE the resumed
        # stream, so same-turn subsequent writes in that flow unlock (auto-sign)
        # instead of re-parking. Denials and non-browser batches record nothing;
        # a batch rejected fail-closed (e.g. ``signing_unavailable``) records
        # nothing either, so the authority is never broader than the batch that
        # actually executed.
        if confirmed and execution_rejection is None:
            self._record_flow_approval(pending, user_name, session_id)

        trace_queue: asyncio.Queue = asyncio.Queue()
        sink_var = TOOL_EVIDENCE_SINK.set(trace_queue)
        # SPEC-062 R-3 reveal-on-commit: carry the parked card's held deliveries
        # into PENDING_RELEASE so the middleware emits them the instant an
        # approved gated mutation commits — and only on an approval. A deny (or a
        # batch that never executes) leaves the buffer empty, so nothing is
        # revealed and the delivery burns. STREAM_PENDING collects any NEW
        # delivery generated during this resumed stream (flushed at its normal
        # end, or re-attached to a new card on a re-park).
        release_deliveries_var = PENDING_RELEASE_DELIVERIES.set(
            list(pending.pending_deliveries) if confirmed else []
        )
        pending_deliveries_var = STREAM_PENDING_DELIVERIES.set([])
        # SPEC-063 R-4: arm the secret-release permit map for the resumed stream
        # exactly as stream_events does, so an approved gated mutation that
        # durably commits here can reveal its held portal_copy delivery.
        permits_var = RELEASE_PERMITS.set({})
        prose_var = CURRENT_PROSE_REDACTOR.set(prose)
        token_var = DELEGATED_TOKEN.set(bearer_token)
        session_var = CHAT_SESSION_ID.set(session_id)
        owner_token_var = GENERATION_OWNER_TOKEN.set((pending.requester_delegated_token,))
        requests_var = EXECUTION_REQUESTS.set(execution_requests or None)
        rejection_var = EXECUTION_REJECTION.set(execution_rejection)
        audit_var = EXECUTION_AUDIT_CONTEXT.set(
            {
                "settings": self.settings,
                "confirm_id": pending.confirm_id,
                "session_id": session_id,
                "request_id": request_id,
                "decider_user_id": user_name,
                "observe_original": self._observe_original_step_origin,
            }
            if confirmed
            else None
        )
        # SPEC-063 R-4: rebind the guard to the parked batch's originating run.
        # A resume NEVER mints a replacement identity — it inherits
        # ``pending.run_id``; when admission is enabled but the identity is
        # missing, no guard is bound here and the mutation lane fails closed at
        # registration rather than proceeding under a fresh run. Inert when
        # admission is disabled (recovery is None).
        resume_recovery = self._execution_recovery()
        guard_var = (
            CURRENT_RUN_GUARD.set(
                self._bind_guard(
                    resume_recovery, pending.run_id, session_id, pending.user_id
                )
            )
            if resume_recovery is not None and pending.run_id is not None
            else None
        )
        try:
            yield {
                "type": "confirmation_result",
                "confirm_id": pending.confirm_id,
                "status": "approved" if confirmed else "denied",
                # Echo the parked batch so downstream consumers (gateway
                # audit, portal card) can name the decided tools.
                # SPEC-055 R-7: redact the echoed batch too, so the result
                # frame never streams a plaintext secret either (the gateway
                # audit reads only tool_name; signing uses build_requests).
                "pending_calls": redact_structure(redact_pending_calls(
                    pending, pending.pending_calls_payload()
                ), prose.literals),
                "request_id": request_id,
                "session_id": session_id,
            }
            async for event in agent.reply_stream(confirm_event):
                self.clear_error()
                drained = list(
                    self._drain_trace_queue(
                        trace_queue,
                        request_id,
                        session_id,
                        evidence_frames,
                        execution_requests,
                    )
                )
                if drained:
                    # SPEC-035 R-2, as in stream_events: release the held tail
                    # before the tool frames so the portal's paragraph break
                    # falls on the segment boundary and not one hold-length
                    # early inside the preceding word.
                    for flushed in flush_prose_frames(
                        prose, request_id, session_id
                    ):
                        yield flushed
                for decorated in drained:
                    yield decorated
                # A resumed turn can park again on another ASK-gated tool.
                # SPEC-054 R-2: attribute the re-parked card to the SESSION
                # OWNER (the original requester), not the approver whose
                # confirm resumed this turn — otherwise the tier_2
                # self-approval rule blocks that same approver from deciding
                # the next unbound per-action card. ``user_name`` (the
                # decider) still attributes this card's own resolution above.
                frame = self._build_confirmation_frame(
                    event,
                    session_id,
                    owner_user_name or user_name,
                    agent.toolkit,
                    turn_index=turn_index,
                    evidence_frames=evidence_frames,
                    run_id=pending.run_id,
                )
                if frame is not None:
                    # A re-park ends this stream without a terminal frame, so
                    # this is its only chance to release the held-back tail.
                    for flushed in flush_prose_frames(
                        prose, request_id, session_id
                    ):
                        yield flushed
                    yield {
                        **frame,
                        "request_id": request_id,
                        "session_id": session_id,
                    }
                    return
                frame = self.normalize_event(
                    event, request_id, session_id, redactor=prose
                )
                if frame.get("event") in TERMINAL_STREAM_EVENTS:
                    for flushed in flush_prose_frames(
                        prose, request_id, session_id
                    ):
                        yield flushed
                yield frame
            # Safety net for a resumed stream that ends without a terminal
            # frame, released before the closing trace frames for the same
            # paragraph reason as in the loop. flush is idempotent, so the
            # paths above add nothing here.
            for flushed in flush_prose_frames(prose, request_id, session_id):
                yield flushed
            # SPEC-062 R-3 reveal-on-commit: flush only deliveries GENERATED
            # during this resumed stream (a standalone generate with no further
            # gate). Held deliveries from the prior park live in PENDING_RELEASE
            # and are NOT flushed here — if the gated mutation never committed
            # they burn silently, which is the deny/failure posture.
            self._flush_pending_deliveries(trace_queue)
            for decorated in self._drain_trace_queue(
                trace_queue,
                request_id,
                session_id,
                evidence_frames,
                execution_requests,
            ):
                yield decorated
            # SPEC-062 R-3 deny-path hardening: actively discard the deliveries
            # that burned — never released because the gate was denied, or because
            # an approved gate's mutation failed/never committed — so the handle is
            # not redeemable even by a direct owner-scoped fetch during the hold
            # TTL. On a deny these are the parked card's deliveries (never carried
            # into PENDING_RELEASE); on an approve, the unreleased remainder. A
            # re-park returned early above (its deliveries ride the new card), so a
            # still-pending handle is never discarded. Best-effort: a failure here
            # degrades to the hold-TTL expiry burn.
            burned = (
                list(pending.pending_deliveries)
                if not confirmed
                else list(PENDING_RELEASE_DELIVERIES.get() or [])
            )
            if burned:
                await self._discard_burned_deliveries(
                    burned, pending.requester_delegated_token
                )
        except Exception as exc:
            self.remember_error(exc, prose.literals if prose is not None else ())
            LOGGER.error("AgentScope confirmation resume failed: %s", self._last_error)
            yield {"type": "error", "message": "The resumed turn failed. Start a new turn.",
                   "request_id": request_id, "session_id": session_id}
        finally:
            # Covers both completion and re-park (the early return above):
            # either way the frames drained so far belong to this turn.
            self._persist_evidence(
                session_id, request_id, turn_index, evidence_frames
            )
            CURRENT_PROSE_REDACTOR.reset(prose_var)
            DELEGATED_TOKEN.reset(token_var)
            CHAT_SESSION_ID.reset(session_var)
            EXECUTION_REQUESTS.reset(requests_var)
            EXECUTION_REJECTION.reset(rejection_var)
            GENERATION_OWNER_TOKEN.reset(owner_token_var)
            pending.requester_delegated_token = None
            # SPEC-062 R-3: drop the held deliveries after resume — released on a
            # gated commit, burned on a deny/failure, or re-attached to a re-parked
            # card by _drain_held_deliveries — so a resolved entry never retains a
            # live secret handle.
            pending.pending_deliveries = ()
            STREAM_PENDING_DELIVERIES.reset(pending_deliveries_var)
            PENDING_RELEASE_DELIVERIES.reset(release_deliveries_var)
            RELEASE_PERMITS.reset(permits_var)
            EXECUTION_AUDIT_CONTEXT.reset(audit_var)
            if guard_var is not None:
                CURRENT_RUN_GUARD.reset(guard_var)
            TOOL_EVIDENCE_SINK.reset(sink_var)
            CONFIRMATION_REGISTRY.resolve(session_id, pending.confirm_id)
            # SPEC-031 R-1: idempotent safety net — the confirm route
            # already wrote the outcome at claim time (R-4), so this only
            # covers paths that resolved without a claim-time write.
            self._record_resolution(
                session_id,
                pending.confirm_id,
                "approved" if confirmed else "denied",
                user_name,
                decision,
            )
            self._snapshot_state(session_id, agent, prose.literals)

    async def expire_confirmation(
        self,
        session_id: str,
        confirm_id: str,
        model_id: str | None = None,
    ) -> None:
        """Close a TTL-expired parked reply without resuming it (SPEC-020 R-2).

        Feeds ``UserInterruptEvent`` so the kernel closes the parked calls
        with an interrupted result, then drops the registry entry. Never
        streams to a client; a failed interrupt still resolves the entry so
        the session cannot wedge. Claimed entries are unreachable here:
        an in-flight resume owns the entry and resolves it in its own
        ``finally``, so a racing expiry can never interrupt an approved
        batch mid-stream (``take_for_expiry`` raises instead).

        ``model_id`` must be the session's resolved pin, exactly as
        ``resume_confirmation`` receives it. Left ``None`` it normalizes to
        ``settings.provider`` — a bare provider name — which never equals a
        session pinned to a concrete model, so ``ensure_agent`` evicts and
        rebuilds the agent before the interrupt is fed. The rebuilt agent
        restores persisted *memory* but not the in-flight parked reply, so
        the ``UserInterruptEvent`` lands on nothing: the parked call never
        receives its interrupted result and the turn is left with no
        closure. Expiry must not change the model a session runs on.
        """
        from agentscope.event import UserInterruptEvent

        # Take-for-expiry ignores TTL (this path exists precisely to close
        # an expired entry) but claims the entry first, keeping the
        # interrupt single-flight against confirms and concurrent expiries.
        pending = CONFIRMATION_REGISTRY.take_for_expiry(session_id, confirm_id)
        try:
            agent, _user_msg_cls, _bound_model_id = await self.ensure_agent(
                session_id, None, model_id
            )
            prose = self._prose_redactor(agent, "", session_id)
            interrupt = UserInterruptEvent(reply_id=pending.reply_id)
            async for _event in agent.reply_stream(interrupt):
                pass
            self._snapshot_state(session_id, agent, prose.literals)
        except Exception as exc:  # pragma: no cover - defensive cleanup
            LOGGER.warning(
                "expiring confirmation %s failed to interrupt parked reply: %s",
                confirm_id,
                type(exc).__name__,
            )
        finally:
            # SPEC-062 R-3 deny-path hardening: an expired park burns its held
            # deliveries too, so actively discard them rather than leaving the
            # handle redeemable for the remainder of the hold TTL. Best-effort —
            # the requester token may itself have expired by now, which degrades
            # to the gateway hold-TTL burn.
            if pending.pending_deliveries:
                await self._discard_burned_deliveries(
                    list(pending.pending_deliveries),
                    pending.requester_delegated_token,
                )
            CONFIRMATION_REGISTRY.resolve(session_id, confirm_id)
            # SPEC-031 R-1: surface expiry as an outcome, not a
            # disappearance — the record stays visible as expired.
            self._record_resolution(
                session_id, confirm_id, "expired", None, None
            )
        LOGGER.info(
            "kernel confirmation expired",
            extra={"session_id": session_id, "confirm_id": confirm_id},
        )
