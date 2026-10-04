# Agent Platform

## Purpose

`agent-platform` is the runtime and orchestration kernel for the platform.

It is responsible for:

- AgentScope-based orchestration
- session and conversation state
- event streaming
- agent coordination
- interaction with policy, knowledge, and tool services

## Ownership

Recommended owner:

- agent platform or orchestration team

## Current Scope

This project covers:

- AgentScope-based runtime services
- session and conversation state handling
- streaming response and event fan-out paths
- orchestration across identity, policy, knowledge, and tool services

Current implementation artifacts:

- `pyproject.toml`
- `Dockerfile`
- `src/agent_service/app.py`
- `src/agent_service/main.py`
- `src/agent_service/api/v2/` (platform-owned contract adapter)
- `src/agent_service/core/`
- `src/agent_service/entrypoints/` (native AgentScope entrypoints)
- `src/agent_service/schemas/`
- `src/agent_service/services/`
- `src/agent_service/runtime_settings.py`
- `src/agent_service/runtime_kernel.py`
- `src/agent_service/providers/`
- `src/agent_service/agent_app.py`
- `src/agent_service/native_service.py`
- `src/agent_service/metadata.py`
- `tests/`

Current implementation status:

- uses `uv` packaging with `uv_build`
- includes a container build path for the current service contract
- exposes a single platform-owned HTTP+SSE contract at `/api/v2/` (see `ADR-0003`)
- the AgentScope kernel sits behind an adapter; no framework types leak through the contract boundary
- identity is conveyed via headers (`X-User-ID`, `x-request-id`), never in request bodies
- centralizes AgentScope runtime construction in reusable kernel modules
- isolates provider-specific AgentScope construction behind a registry and adapter modules
- adds a native `AgentScope` runtime service entrypoint via `agent-service-runtime`
- adds a native `AgentScope 2.0` service-factory entrypoint via `agent-service-native`
- routes chat and streaming calls through a provider-configurable AgentScope runtime adapter when credentials are configured
- distinguishes between unconfigured runtime state and provider-call failures in runtime metadata
- enables real runtime replies when `AGENTSCOPE_API_KEY` is supplied to the service environment
- emits per-request tool trace events (`tool_call` and `tool_result`) into the SSE stream when `TOOL_GATEWAY_URL` is configured; traces are merged with text deltas so the operator portal can render an evidence panel (SPEC-011)
- carries the triage-report output discipline in the default system prompt so incident triage turns end with a schema-conformant fenced `triage-report` JSON block; `incidents.list` / `incidents.get` join the default auto-allowed tool set alongside the `skills.*` tools, so the agent can ground answers in live incidents without configuration changes (SPEC-015)
- implements all cross-cutting kernel behavior on agentscope's supported `MiddlewareBase` hooks: a permission middleware that owns the gate for a headless runtime — vetted read-only gateway tools and state-local task tools are ALLOWed, every other tool is answered with an explicit ASK rather than delegated to agentscope's `PermissionEngine` (whose read-only fast path auto-allows read-only invocations in every mode, bypassing the platform allow-list) — an evidence middleware emits the `tool_call`/`tool_result` frames, and the out-of-box `TracingMiddleware` and `ReplyBudgetControlMiddleware` are opt-in via settings; toolkits are cached per delegated token (tokens are read from a contextvar at call time, so portal token refresh never requires an agent rebuild) (SPEC-018)
- bridges kernel ASKs to the portal: a permission-middleware ASK parks the active reply on `RequireUserConfirmEvent`, emits a `confirmation_request` SSE frame (stream schema v6, carrying the optional per-call `risk_level`), and holds the batch in an in-memory confirmation registry; `POST /api/v2/chat/confirm` resumes the parked reply with the operator's decision; expired entries abort the reply via `UserInterruptEvent`; `AGENT_HITL_CONFIRM_TIMEOUT=0` disables bridging (SPEC-020)
- switches the serving LLM per chat turn from a credential-gated model catalog derived at startup from per-provider env knobs (`<PROVIDER>_API_KEY` / `_MODEL_NAME` / `_BASE_URL` / `_MODELS`, with `AGENTSCOPE_*` fallback for the active profile's provider): every provider with a resolvable key contributes its curated model series — one entry per model, id = model name — and legacy bare-provider-name ids alias to that provider's default model; selection resolves request > session pin > deploy-time default and fails closed on unknown ids (422 / `unknown_model` stream frame), pins onto the session store, rebuilds the cached kernel agent with state restore, and is exposed for discovery via `GET /api/v2/models` (id/label/provider/default only — no credentials leave the runtime); `message_end` frames carry the serving model (SPEC-024, SPEC-026)
- keeps the catalog current via live model discovery: a lifespan-owned background task queries each configured provider's OpenAI-compatible `/models` endpoint at startup and every `AGENT_MODEL_DISCOVERY_REFRESH_SECONDS` (default 1800), applies per-provider filters (dated snapshots and non-chat modalities dropped; the provider's default model always force-included), and atomically swaps the catalog in place. The fail-soft ladder is live → in-memory last-good → Postgres-persisted last-good (`model_discovery_cache` in the sessions database — Redis gains no new consumers) → curated series; a set `<PROVIDER>_MODELS` skips discovery for that provider, `AGENT_MODEL_DISCOVERY_ENABLED=false` restores the pure curated behavior, and every failure is logged and swallowed — discovery never blocks chat or startup (SPEC-027)

Service layout:

- `src/agent_service/app.py`
  - builds the `FastAPI` app and mounts the `/api/v2/` contract router
- `src/agent_service/api/v2/routes.py`
  - the adapter layer: validates requests, delegates to the kernel, shapes responses into contract-conformant models
- `src/agent_service/entrypoints/`
  - holds the native `AgentApp` and native `AgentScope 2.0` entrypoint implementations (for AgentScope-native consumers)
- `src/agent_service/core/`
  - holds shared configuration and request-context helpers
- `src/agent_service/schemas/`
  - `v2.py`: pydantic models bound to the platform-owned contract; `api.py`: internal session models
- `src/agent_service/services/`
  - session store, session service, runtime dependencies, kernel middleware stack (permission + evidence; SPEC-018), HITL confirmation registry (SPEC-020), credential-gated model catalog (`model_catalog.py`; SPEC-024), live model discovery with cached fallback (`model_discovery.py`; SPEC-027)
- `src/agent_service/runtime_*.py`, `providers/`, `agent_app.py`, `native_service.py`
  - runtime-focused modules that configure and expose AgentScope-backed execution paths

Entrypoint distinction:

- `src/agent_service/main.py`
  - default entrypoint: runs the platform-owned contract service (`/api/v2/`)
- `src/agent_service/agent_app.py`
  - native `AgentScope` `AgentApp` runtime entrypoint (for AgentScope Studio / runtime consumers)
- `src/agent_service/native_service.py`
  - native `AgentScope 2.0` service built with `create_app` (for AgentScope-native tooling)

Configuration and singleton access:

- `src/agent_service/core/config.py`
  - exposes cached runtime settings through `get_settings()`
- `src/agent_service/services/runtime_dependencies.py`
  - exposes the cached `AgentKernel` singleton through `get_runtime_kernel()`
- `src/agent_service/services/session_store.py`
  - isolates session persistence (memory / Redis / Postgres backends, SPEC-016) from higher-level session and chat orchestration

Local run options:

- `uv run --directory products/agent-platform agent-service`
  - runs the platform-owned contract service on port `8000`
  - accepts `AGENT_SERVICE_HOST` and `AGENT_SERVICE_PORT`
- `uv run --directory products/agent-platform agent-service-runtime`
  - runs the `AgentApp`-based entrypoint (for AgentScope-native consumers)
- `uv run --directory products/agent-platform agent-service-native`
  - runs the native `AgentScope 2.0` service built with `create_app`
  - accepts `AGENT_NATIVE_HOST`, `AGENT_NATIVE_PORT`, `AGENT_NATIVE_TITLE`, and `AGENT_NATIVE_VERSION`
  - expects a reachable `Redis` instance using `AGENTSCOPE_REDIS_HOST`, `AGENTSCOPE_REDIS_PORT`, and related env vars if you override defaults
- `docker build -t luban-aiops/agent-service:dev-local products/agent-platform`
  - builds the container image used by the development Kubernetes overlays
  - defaults to the `agent-service` entrypoint (platform-owned contract)

Current runtime environment knobs:

- `AGENTSCOPE_PROVIDER`
  - selects the provider-specific AgentScope chat model
  - current supported values: `dashscope`, `deepseek`, `openai`, `luban` (team-hosted OpenAI-compatible server; SPEC-028)
- `AGENTSCOPE_PROFILE`
  - optional deployment-level selector for the active runtime profile
  - when set, it must match `AGENTSCOPE_PROVIDER`
- `AGENTSCOPE_API_KEY`
  - required to move provider-backed chat/runtime paths out of unconfigured placeholder behavior
- `AGENTSCOPE_MODEL_NAME`
  - optional provider-specific model override; when omitted, the selected provider supplies its default model
- `AGENTSCOPE_BASE_URL`
  - optional override for provider endpoints
- `<PROVIDER>_API_KEY`, `<PROVIDER>_MODEL_NAME`, `<PROVIDER>_BASE_URL`, `<PROVIDER>_MODELS` (SPEC-024, SPEC-026)
  - per-provider model-catalog knobs (`PROVIDER` is one of `DASHSCOPE`, `DEEPSEEK`, `OPENAI`, `LUBAN`): each supported provider with a resolvable API key contributes its curated model series — one selectable catalog entry per model, id and label are the model name — with `_MODEL_NAME` picking the provider's default model and `_MODELS=a,b,c` overriding/restricting the series (the provider's default model is always force-included); the active profile's provider additionally falls back to the `AGENTSCOPE_*` knobs above, so a single-provider deployment needs zero new configuration. Bare provider names (pre-SPEC-026 ids) alias to that provider's default model. Providers without a resolvable key are dropped; a zero-entry catalog degrades to the existing unconfigured-runtime behavior.
  - `LUBAN_API_KEY`, `LUBAN_BASE_URL`, `LUBAN_MODEL_NAME`, `LUBAN_MODELS`, `LUBAN_THINKING_ENABLE` (SPEC-028)
  - team-hosted (local/on-prem) OpenAI-compatible servers (Ollama, vLLM, llama.cpp) as the `luban` provider with bearer-token auth: both `LUBAN_API_KEY` and `LUBAN_BASE_URL` are mandatory (a key without a base URL gates the provider out — self-hosted endpoints have no default endpoint). The curated series is empty, so `LUBAN_MODELS` pinning (recommended, fixed-point ids) or live discovery supplies the lineup; thinking defaults off (small-model-safe). See `docs/guides/luban-llm-guide.md` and the reference Ollama manifests under `shared/platform-ops/gitops/llm-hosting/`.
- `AGENT_MODEL_DISCOVERY_ENABLED`, `AGENT_MODEL_DISCOVERY_REFRESH_SECONDS`, `AGENT_MODEL_DISCOVERY_TIMEOUT_SECONDS` (SPEC-027)
  - live model discovery tuning: periodic `GET /models` per configured provider feeds the catalog behind a fail-soft ladder (live → in-memory last-good → Postgres last-good in the sessions database → curated series). Enabled by default; `false` restores the pure curated-series behavior. A set `<PROVIDER>_MODELS` stays authoritative and skips discovery for that provider.
- `AGENTSCOPE_ORGANIZATION`
  - optional organization identifier for `openai`
- `AGENTSCOPE_MAX_TOKENS`, `AGENTSCOPE_TEMPERATURE`, `AGENTSCOPE_TOP_P`
  - common provider-agnostic inference controls
- `AGENTSCOPE_AGENT_NAME`
  - defaults to `LubanOpsRuntime`
- `AGENTSCOPE_SYSTEM_PROMPT`
  - defaults to the current runtime grounding prompt
- `AGENTSCOPE_MAX_ITERS`
  - ReAct loop iteration cap passed to the kernel's `ReActConfig`; defaults to `20`; must be >= 1 (SPEC-017)
- `AGENTSCOPE_CONTEXT_TRIGGER_RATIO`
  - long-term memory trigger ratio passed to the kernel's `ContextConfig`; defaults to `0.8`; must be in the open interval (0, 0.9) (SPEC-017)
- `AGENTSCOPE_TOOL_RESULT_LIMIT`
  - tool result character limit passed to the kernel's `ContextConfig`; defaults to `50000`; must be >= 1 (SPEC-017)
- `AGENTSCOPE_TIMEZONE`
  - IANA timezone for runtime-state injection (`InjectionConfig`); defaults to `UTC`; validated at startup (SPEC-017)
- `AGENTSCOPE_MODEL_MAX_RETRIES`
  - model call retry count passed to the kernel's `ModelConfig`; defaults to `0`; must be >= 0 (SPEC-017)
- `DASHSCOPE_THINKING_ENABLE`, `DASHSCOPE_THINKING_BUDGET`, `DASHSCOPE_TOP_K`, `DASHSCOPE_PARALLEL_TOOL_CALLS`
  - DashScope-specific runtime options
- `DEEPSEEK_THINKING_ENABLE`, `DEEPSEEK_REASONING_EFFORT`
  - DeepSeek-specific runtime options
- `OPENAI_THINKING_ENABLE`, `OPENAI_REASONING_EFFORT`, `OPENAI_PARALLEL_TOOL_CALLS`
  - OpenAI-compatible runtime options
- `SESSION_TTL_SECONDS`
  - idle lifetime for sessions; defaults to `3600`; used by all backends
- `SESSION_MAX_ENTRIES`
  - maximum concurrent in-memory sessions before oldest-first eviction; defaults to `1000`; only applies to the `memory` backend
- `SESSION_STORE_BACKEND`
  - selects the session store backend: `memory`, `redis`, or `postgres`; defaults to `memory`; unknown values fail startup (deployed overlays set `postgres`, SPEC-016)
- `SESSION_DB_URL`
  - Postgres DSN for the session store; required when the backend is `postgres`; the table DDL is applied idempotently on startup; unreachable databases fail open to the in-memory backend (`session_store_fallbacks_total`)
- `SESSION_REDIS_HOST`
  - Redis host for the session store; defaults to `127.0.0.1`; only applies to the `redis` backend
- `SESSION_REDIS_PORT`
  - Redis port for the session store; defaults to `6379`; only applies to the `redis` backend
- `SESSION_REDIS_DB`
  - Redis DB number for session keys; defaults to `1` (separate from AgentScope's DB `0`); only applies to the `redis` backend
- `AGENT_STATE_STORE_BACKEND`
  - selects the agent state store backend: `memory` or `postgres`; defaults to `memory`; unknown values fail startup (deployed overlays set `postgres`, SPEC-017)
- `AGENT_STATE_DB_URL`
  - Postgres DSN for agent state; required when the backend is `postgres` (shares the `sessions` database); the table DDL is applied idempotently on startup; unreachable databases fail open to the in-memory backend (`agent_state_fallbacks_total`)
- `AGENT_STATE_TTL_SECONDS`
  - sweep TTL for stale agent state rows; defaults to `3600`
- `AGENT_EVIDENCE_ENTRY_MAX_CHARS`
  - serialized-size cap for one persisted evidence frame payload; oversized `tool_result.data` is replaced by a prefix plus a `{"truncated": {"reason": "entry_cap", "original_chars": n}}` marker; defaults to `131072` (SPEC-025)
- `AGENT_EVIDENCE_SESSION_MAX_BYTES`
  - per-session budget for persisted evidence; when exceeded, the oldest `tool_result` data payloads are evicted (data dropped, metadata kept, `{"truncated": {"reason": "session_budget"}}` marker); defaults to `4194304` (SPEC-025)
- `TOOL_GATEWAY_URL`
  - base URL of the tool-gateway for tool discovery and invocation (SPEC-007); when set, the AgentScope kernel registers gateway tools into a per-token cached Toolkit; when unset, the agent builds with an empty Toolkit
  - tool calls relay the gateway-forwarded delegated token (SPEC-008) as `Authorization: Bearer`; the token is exposed per-turn through a request-scoped contextvar and read by the tool closures at call time (toolkits stay per-token and are never shared across users), so portal token refresh works without rebuilding the agent; identity is never carried in the request body; without a token, discovery degrades to an empty Toolkit and invocation returns a structured error
  - evidence frames (`tool_call`/`tool_result`) are emitted by the kernel's evidence middleware into a request-scoped sink and drained into the SSE stream alongside text deltas; besides the bounded `data_summary`, a `tool_result` frame carries the full `data` payload when it stays within `AGENT_TOOL_DATA_MAX_CHARS` (stream schema v6) so the portal can show the complete output of a run regardless of how the model phrases its reply (SPEC-011, SPEC-018)
- `AGENT_GATEWAY_TOOL_AUTO_ALLOW`
  - comma-separated dotted gateway tool names auto-approved by the permission middleware when the tool is read-only; overrides the built-in vetted list; the allow-list is the only auto-approval surface — every other tool is answered with an explicit ASK (which parks the batch for operator confirmation under SPEC-020) instead of being delegated to agentscope's read-only auto-allow fast path (SPEC-018); the surface is read-only by construction: mutating (`write`/`admin`) tools carry `is_read_only=False`, so naming one here can never grant auto-execution — it is logged and still parks for confirmation (SPEC-021)
- `AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA`
  - comma-separated dotted gateway tool names *added* to the resolved allow-list (built-in default, or `AGENT_GATEWAY_TOOL_AUTO_ALLOW` when set) instead of replacing it; lets an environment opt a single read-tier tool back into auto-approval without restating the whole list — e.g. the dev-k8s overlay sets `AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA=http.get` to preserve the SPEC-058 R-1 "a read-tier `http.get` parks no card" behaviour after v0.39.1 removed `http.get` from the built-in default (outbound-egress HITL bypass is now opt-in); subject to the same read-only-by-construction invariant, so naming a mutating tool here is a logged no-op
- `AGENT_HITL_CONFIRM_TIMEOUT`
  - seconds a parked tool batch may wait for an operator decision before expiring; defaults to `600`; `0` disables HITL confirmation bridging so ASKs fall through to the built-in resolution (SPEC-020); with bridging disabled, mutating tools are excluded from the toolkit entirely and each turn carries an explicit system notice instead of a silent omission (SPEC-021)
- `AGENTSCOPE_KERNEL_TRACING`
  - registers agentscope's out-of-box `TracingMiddleware` for OTel kernel spans; defaults to `false`; inert without an SDK `TracerProvider` (SPEC-018)
- `AGENTSCOPE_REPLY_TOKEN_BUDGET`
  - reply token budget for the out-of-box `ReplyBudgetControlMiddleware`; must be > 0 when set; unset leaves replies unbudgeted (SPEC-018)
- `AGENTSCOPE_REPLY_INPUT_TOKEN_WEIGHT` / `AGENTSCOPE_REPLY_OUTPUT_TOKEN_WEIGHT`
  - token weights for the reply budget; each must be >= 0 (`0` is valid); default to `1.0` (SPEC-018)
- `AGENTSCOPE_TASK_TOOLS_ENABLED`
  - opts into agentscope's built-in task tools (`TaskCreate`/`TaskGet`/`TaskList`/`TaskUpdate`); defaults to `false`; task state is session-local agent state and persists through the agent state store; task tools never count toward the no-tools guard (SPEC-018)
- `AGENT_TOOL_DATA_SUMMARY_MAX_CHARS`
  - maximum character length for `data_summary` fields in tool trace events; defaults to `2000`; payloads exceeding the limit are truncated with a structured marker (SPEC-011)
- `AGENT_TOOL_DATA_MAX_CHARS`
  - serialized-size cap for the full `data` field on `tool_result` evidence frames (stream schema v6); defaults to `32000`; oversized payloads are omitted from the frame and remain in audit logs only (SPEC-020 live-check enhancement)
- `OTEL_ENABLED`
  - master switch for the OTLP push pipeline (traces + metrics); defaults to `false`; when disabled, the `/metrics` surface is unaffected
- `OTEL_EXPORTER_OTLP_ENDPOINT`
  - OTLP collector URL used when `OTEL_ENABLED=true`
- `OTEL_SERVICE_NAME`
  - logical service name reported to the collector; defaults to the agent-platform's metadata name

Session store (SPEC-006):

- sessions are persisted to Redis when `SESSION_STORE_BACKEND=redis`; sessions survive pod restarts and are shared across replicas
- when Redis is unreachable at startup, the store falls back to in-memory with a warning and a Prometheus counter (`session_store_fallbacks_total`)
- the in-memory backend (`SESSION_STORE_BACKEND=memory`) keeps sessions in process memory only, with TTL and max-entry eviction
- sessions are scoped to the creating user (via `X-User-ID` header); unknown or foreign `session_id` values return `404`
- `POST /api/v2/sessions` accepts an optional body `{"session_id": ...}` to create a caller-named dedicated session (SPEC-015 triage sessions); it is get-or-create and idempotent for the owning user, and a foreign owner still answers `404`
- session workspace (SPEC-022 R-1): `GET /api/v2/sessions` lists the caller's own sessions (most-recently-active first, capped at 50, `pending_confirmation` flags), `GET /api/v2/sessions/{id}` additionally carries a server-minted title (first user turn, 80 chars, set once) and a best-effort transcript reconstructed from the kernel state snapshot (`transcript_available` marks the explicit fallback), and `DELETE /api/v2/sessions/{id}` removes the session plus its state snapshot — `404` for unknown/foreign ids (anti-enumeration) and `409` while a parked HITL confirmation is unresolved. Known limitation: the parked check is check-then-act, so deleting a session while its last turn is still streaming can let that turn re-snapshot state afterwards; avoid deleting mid-turn (a conditional-delete design is tracked as follow-up hardening)
- `POST /api/v2/chat` accepts an optional `input_modality` (`text` | `voice`, default `text`, SPEC-022 R-2): metadata only — it never influences authorization, tool policy, or HITL gating, which stay click-gated
- the native runtime path delegates session state to the AgentScope runtime services instead

Agent state durability (SPEC-017):

- the kernel-serializable agent state (conversation context, summaries, reply context) is snapshotted after every completed turn and restored when an agent is constructed for a session, so conversations survive agent-platform restarts
- `AGENT_STATE_STORE_BACKEND=postgres` persists snapshots as JSONB in the SPEC-016 `sessions` database; `memory` keeps them in process memory (dev/CI default)
- snapshot and restore never fail a turn: store errors log, increment `agent_state_errors_total`, and degrade gracefully; unreachable Postgres at startup fails open to memory (`agent_state_fallbacks_total`)
- a corrupt persisted snapshot is discarded (fresh agent) instead of wedging the session
- session deletion also removes the session's persisted state (best-effort)
- `POST /api/v2/chat` accepts an optional `response_schema` (JSON-schema dict) and returns the kernel-validated `structured_output` alongside the text reply (null when no schema was requested or the turn produced none)

Evidence persistence (SPEC-025):

- the kernel persists `tool_call`/`tool_result` frames per assistant turn into a dedicated `session_evidence` store (`evidence_store.py`) behind the same `AGENT_STATE_STORE_BACKEND` / `AGENT_STATE_DB_URL` knobs as agent state; persistence is best-effort next to the state snapshot and never fails a turn
- caps are enforced identically in both backends: an entry cap (`AGENT_EVIDENCE_ENTRY_MAX_CHARS`) truncates oversized payloads with an `entry_cap` marker, and a per-session budget (`AGENT_EVIDENCE_SESSION_MAX_BYTES`) evicts oldest `tool_result` data payloads with a `session_budget` marker while keeping metadata
- `GET /api/v2/sessions/{id}` assembles `evidence_turns` (turn-grouped frames with `turn_index`/`request_id`): empty list when the session stored none, `null` when the evidence store is unreadable — never a 500; session delete cascades evidence cleanup (fail-open)
- redaction is inherited by construction: frames arrive already redacted at the tool-gateway `invoke_tool` choke point (SPEC-009) and the store round-trips them byte-identical
- counters: `evidence_store_writes_total{result}`, `evidence_frames_persisted_total`, `evidence_frames_truncated_total{reason}`

HITL confirmation bridging (SPEC-020):

- when the permission middleware resolves an unvetted tool batch as ASK, the kernel parks the active reply on `RequireUserConfirmEvent` and emits a `confirmation_request` frame carrying `confirm_id` and the pending calls; the stream ends without `message_end`
- parked entries live in an in-memory registry scoped to session and owner (`X-User-ID`); a new chat against a parked session answers `409`
- `POST /api/v2/chat/confirm` resumes the parked reply with `UserConfirmResultEvent` (approve runs the batch under the confirmer's delegated token, deny feeds the refusal back to the model), emits a `confirmation_result` frame first (echoing the decided calls), continues the paused reply on the same SSE stream, and snapshots agent state after completion
- unknown, foreign, or already-answered confirmations answer `404`; expired entries answer `410`; a TTL-expired park is closed via `UserInterruptEvent` on the confirm attempt or the next chat turn — expiry never silently evicts a parked reply
- the confirm route claims the entry before any headers go out, so a duplicate confirm (retry, second tab) fails closed with `404` instead of double-resuming the parked batch
- confirmed calls are not re-asked: agentscope re-traverses the permission middleware for ALLOWED calls, but SPEC-063 checks the durable run stop before that shortcut; approval never overrides an unresolved or stopped run
- `AGENT_HITL_CONFIRM_TIMEOUT=0` disables bridging entirely and ASKs keep the built-in permission-middleware resolution
- mutating tools can never bypass the bridge (SPEC-021): gateway tools carry their risk tier onto the FunctionTool, parked `confirmation_request`/`confirmation_result` frames include the per-call `risk_level` (stream schema v6), and with bridging disabled non-read tools are dropped from toolkit construction with a per-turn system notice

Current runtime status surface:

- `/api/v2/runtime`
  - returns provider, resolved model, runtime state, and the last provider error if one exists
- `/api/v2/health`
  - returns runtime mode, runtime state, provider, configured status, session store backend and readiness, and agent state store backend and readiness
- `/metrics`
  - always-on Prometheus exposition endpoint (auth-exempt), reporting standard HTTP RED metrics plus `agent_sessions_created_total` and `agent_chat_requests_total`; opt-in OTLP push via `opentelemetry-instrumentation-fastapi` + `opentelemetry-exporter-otlp` when `OTEL_ENABLED=true` (fail-open); see `SPEC-005` and `shared/shared-contracts/observability-conventions.md`
- `x-request-id` remains the log/portal correlation key; when OTel tracing is active it equals the W3C `trace_id`

Testing note:

- keep adding focused tests as the runtime surface grows
- the current package includes a lightweight `pytest`-based starting point for runtime configuration and placeholder behavior

## Durable execution and recovery (SPEC-063)

Approved action and flow writes register immutable intents in Postgres before
handoff to execution-runtime. `AGENT_EXECUTION_ADMISSION_ENABLED` defaults to
`false`; enabling requires `AGENT_EXECUTION_STATE_DB_URL` and a matching canonical
UUID `AGENT_EXECUTION_ADMISSION_EPOCH`. This ledger has no memory fallback and is
independent of best-effort session, agent-state, and presentation stores.

The persistent run identity survives park/resume. A stopped run, unresolved
predecessor, or unavailable ledger blocks further automatic mutations before the
middleware's `ALLOWED` shortcut, flow signing, handoff, and final send. Read-only
investigation keeps its existing policy gates. A worker timeout (default 60s,
maximum 120s) records uncertainty, not a terminal no-effect receipt.

Only a verified original result, durably accepted by the agent, can mint the
single-use, process-bound permit that releases a held secret. Metadata replay,
late results, and reload never recreate original output or release authority.
Owner session recovery exposes bounded facts even if presentation writes failed;
foreign owners get no additional access and the approver inbox stays decision-only.
New document digests and authoring decisions preserve unknown/unavailable/conflict
states; published snapshots are not rewritten.

See [recovery guidance](../../docs/guides/portal-user-guide.md#recovering-an-uncertain-execution)
and the mandatory [cutover/restore runbook](../../docs/guides/execution-cutover-restore.md).
The gateway/worker/agent migration is coordinated and mutation-disabled; deploying
new binaries alone does not enable admission.

## Expected Integration Points

- `identity-broker` for normalized identity context
- `policy-center` for action and approval decisions
- `skills-hub` for knowledge retrieval inputs
- `tool-gateway` for grounded tool access
- `shared/shared-contracts` and `shared/shared-sdk` for shared interfaces

## Boundary

This project may propose actions and request policy decisions, but it does not directly authorize or execute privileged operations.
