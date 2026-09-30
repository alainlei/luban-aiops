# AgentScope Utilization Re-Audit (post SPEC-018)

Status: delivered with SPEC-018 (2026-08-20)
Supersedes: the post-SPEC-017 utilization audit findings that motivated SPEC-018.
Scope: every agentscope surface the agent-platform kernel touches or deliberately does not, re-audited after the middleware alignment landed. Verified against the locked agentscope 2.0.6 install; re-verified under agentscope 2.0.8 in v0.43.2 (2026-09-27), which added the `CompressContext` tool and `pipeline` module (`GoalPipeline`) surfaces tracked in §2. The [SPEC-064 R-1 spike](agentscope-compression-goal-pipeline-spike.md) (2026-09-27) resolved both: `CompressContext` **clears** the four-point gate (opt-in adoption recommended, wiring pending SPEC-064 R-2 approval); `GoalPipeline` is **kept out**. The [long-term operator memory spike](long-term-operator-memory-spike.md) (2026-10-01) resolved the §2 long-term-memory row the same way: all three surfaces (`AgenticMemoryMiddleware`, `Mem0Middleware`, `ReMeMiddleware`) are **kept out**, closing the 2026-08-20 "spike needed" posture.

## 1. What SPEC-018 changed

The kernel moved off three private surfaces onto supported ones:

| Before (private surface) | After (supported surface) |
|---|---|
| `GatewayFunctionTool.check_permissions` (FunctionTool subclass) | `GatewayPermissionMiddleware.on_check_permission` |
| Per-request trace queue bound into every tool closure | `ToolEvidenceMiddleware.on_acting` + request-scoped sink contextvar |
| Per-request `_build_request_toolkit` + `agent.toolkit = ...` mutation | Per-token cached toolkit; `DELEGATED_TOKEN` contextvar read at call time; agent rebuild only on gateway-tool recovery (0 → >0) |

Adopted out-of-box features (each passed the four-point adoption gate in SPEC-018):

- `TracingMiddleware` — OTel agent/LLM/tool spans through the existing OTLP pipeline; opt-in via `AGENTSCOPE_KERNEL_TRACING`; inert without an SDK TracerProvider.
- `ReplyBudgetControlMiddleware` — weighted per-reply token budget; opt-in via `AGENTSCOPE_REPLY_TOKEN_BUDGET` (+ weights); budget state lives in `agent.state.middle_context`, covered by the SPEC-017 snapshot/restore.
- Task tools (`TaskCreate`/`TaskGet`/`TaskList`/`TaskUpdate`) — opt-in via `AGENTSCOPE_TASK_TOOLS_ENABLED`; state-local (`AgentState.tasks_context`), persisted through the SPEC-017 store, always-ALLOWed by the permission middleware, excluded from the no-tools guard.

## 2. Decision matrix — remaining agentscope surfaces

| Surface | Decision | Reason |
|---|---|---|
| `Toolkit.tool_groups` internals (task-tool append, gateway-tool counting/introspection) | **Kept best-effort, pinned by tests** | The one remaining internal-facing surface after SPEC-018: tool registration lands in `tool_groups[0]` and availability is read dynamically. Works in 2.0.6, re-verified under 2.0.8 (v0.43.2), and is pinned by `test_task_tools_appended_and_excluded_from_gateway_count`; re-verify on every agentscope upgrade. |
| Agent-driven context compression (`CompressContext` tool, new in 2.0.8) | **Clears the gate — adopt (opt-in), pending SPEC-064 R-2** | [SPEC-064 R-1 spike](agentscope-compression-goal-pipeline-spike.md) scored it against all four gate points: it is context-only (calls the kernel's own model, mutates only `AgentState.summary`/`.context`), emits no evidence/SSE frame (no `gateway_tool_name`, so `ToolEvidenceMiddleware.on_acting` passes it through), needs no identity edge, and persists for free via the SPEC-017 snapshot. The *same* `_compress_context_impl` already runs by threshold today (`ContextConfig(trigger_ratio=0.8)`), so agent-driven compression changes only the trigger timing, not the fabrication surface. Adopt behind a default-off `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` knob → `compression_tool_enabled`, add `"CompressContext"` to `KERNEL_LOCAL_TOOL_NAMES`, and do **not** wire the `offloader` (workspaces stay kept out). Wiring is R-2, not authorized by the spike. |
| `pipeline` module (`GoalPipeline`, new in 2.0.8) | **Kept out (SPEC-064 R-1)** | An executor-until-verifier loop over two full `Agent` instances (`max_iters=10`, `max_retries=3`) is platform-side autonomous control flow, contradicting ADR-0011 / SPEC-057 ("no control flow, composition carries no authority, grounded guidance not platform sequencing") and the SPEC-037/038/063 governed at-most-one-dispatch path. It fails gate points 1–4 (second orchestration edge, two-agent identity/toolkit surface, bounded-autonomy posture, interleaved two-agent event stream vs. the single-turn v2 contract) and has no platform caller. Kept out like the other orchestration edges; reopen only on a concrete autonomous-remediation need that runs entirely under the existing gates as a single governed agent. See the [R-1 spike](agentscope-compression-goal-pipeline-spike.md). |
| `MiddlewareBase` hooks (`on_check_permission`, `on_acting`, plus the out-of-box tracing/budget middlewares) | **Adopted** (SPEC-018) | Supported interception points replacing all hand-rolled paths; adoption gate passed per requirement. |
| Built-in task tools | **Adopted** (SPEC-018, opt-in) | State-local only; durability for free via SPEC-017; no infrastructure access. |
| MCP (MCPClient / MCP exposure of tool-gateway connectors) | **Spike needed** | Could let the kernel reach external MCP servers directly — must be gated so the tool-gateway stays the only execution surface (adoption gate point 1). Roadmap Exploration Backlog. |
| RAG middleware / embedding models | **Spike needed** | Semantic skill retrieval could improve recall over skills-hub's ranked lexical retrieval; must not bypass skills-hub governance/audit. Roadmap Exploration Backlog. |
| Long-term memory middlewares (Mem0 / ReME / Agentic) | **Kept out — spike done 2026-10-01** | All three 2.0.8 surfaces scored against the four-point gate in [the operator-memory spike](long-term-operator-memory-spike.md): each **fails gate points 1, 2, and 3 as shipped**, and no configuration of any of them passes. *Gate 1* — `AgenticMemoryMiddleware` overrides no `list_tools()` and instead instructs the model to use agentscope's builtin `Write`/`Read`, which this platform does not register; all three add non-gateway tools, so deny-by-default `GatewayPermissionMiddleware` would park a confirmation card on every memory read and write, and the only escape (`KERNEL_LOCAL_TOOL_NAMES`) is reserved for state-local tools. *Gate 2* — `_build_agent` receives no user identity: mem0's `user_id` is a constructor argument, i.e. a new identity edge, and ReME scopes writes on an `AgentState.session_id` the platform never assigns. *Gate 3* — all three write after every reply; `AgenticMemory` and ReME write into the pod's `emptyDir` workspace (the same objection that keeps the SPEC-064 R-2 `offloader` unwired), and mem0 writes to an external store before the `redact_structure` boundary. The 2026-08-20 ReME findings hold and two are worse than recorded: its write-back is not configurable away in any mode, and its retrieval races the reply, so injection may not land on the 107 of 124 observed sessions that are single-turn. Neither `mem0` nor `reme` is installed; mem0's default store is Qdrant and its embedder must be 1536-dim. Separately, an injected memory note is model-visible and snapshot-persisted but absent from the transcript, the evidence panel, and the closed 22-value audit `event_type` enum. Reopen only on the memo's §9 conditions, not on a library upgrade. Recorded on the memo's recommendation; the roadmap backlog row closes on the operator's acceptance of it. |
| Kernel-side `AsyncSQLAlchemyStorage` (kernel-owned session/message storage) | **Kept platform-owned** | Sessions and agent state already persist through the platform's Postgres stores (SPEC-006/SPEC-017) under platform audit; a second storage path would fork durability and audit ownership. |
| Sandboxes / workspaces | **Kept out** | Execution surfaces contradict the read-only operational posture (adoption gate point 3). |
| Built-in file/shell tools (`Bash`/`Read`/`Write`/...) | **Kept out** | Same as sandboxes: unbounded local execution contradicts the read-only posture and tool-gateway-only execution. |
| Channels / hub (chat channels, skill hub, MCP hub) | **Kept out** | The platform owns its delivery surfaces (operator portal SSE, skills-hub, tool-gateway); adopting channels would create a second, ungoverned interaction edge. |
| TTS | **Kept out** | No operator-portal voice surface; no need identified. |
| `agentscope.app` application layer (`create_app` FastAPI factory: routers, access policy, sessions, storage, message bus, hubs, RAG, channels) | **Kept platform-owned** | Deploying it would create a second API edge with a second access model, duplicate governed capabilities (skills-hub, session durability, credential delegation), and re-instate the native-wire-protocol option rejected in ADR-0003. The `native.py` entrypoint remains a capability probe only. Its HITL projectors (`_service/_projectors`) and the AGUI protocol middleware are reference-only candidates for the HITL bridging spec. |

## 3. Entrypoint surface clarification

Only one kernel entrypoint is deployed: the `agent-service` FastAPI
application serving the platform-owned `/api/v2/` contract (ADR-0003).

- `agent-service-native` (AgentScope 2.0 service factory) — available as a
  kernel-capability probe; **not** part of the deployed topology; no
  ingress, no identity edge.
- `agent-service-runtime` (runtime adapter entrypoint) — same status:
  capability probe only.

Neither probe may gain a deployed route without its own spec passing the
adoption gate.

## 4. Future Scope carry-forward (from SPEC-018)

| Item | Status | Sequencing |
|---|---|---|
| HITL confirmation bridging (map kernel `ASK` / `RequireUserConfirmEvent` onto new v2 SSE frames; portal approve/deny; session suspend/resume) | Tracked; needs its own spec | **Must precede any write/mutating tool.** Until then the headless posture (pre-answered permission decisions, read-only tools only) is what keeps the platform safe. |
| ASK → DENY tightening (non-allow-listed gateway tools currently fall through to the interactive ASK default, which headlessly means "silently never runs") | Tracked; candidate follow-up | Behaviorally equivalent in the deployed topology; can land any time after HITL bridging design clarifies the confirmation model. |
| `agentscope.app` HITL projectors / AGUI protocol middleware as reference designs | Reference-only | Only inside the HITL bridging spec; no runtime dependency without its own adoption-gate pass. |
| Discovery negative-cache / backoff | Tracked; candidate follow-up | Empty discovery is intentionally uncached (recovery UX), but while the tool-gateway is down every turn on the `ensure_agent` fast path pays a discovery attempt (up to its timeout). A short negative-cache TTL would bound outage latency without re-poisoning recovery. |

## 5. Invariants re-confirmed

- Tool execution remains exclusive to the tool-gateway (policy, redaction, evidence, audit).
- Identity is carried only by the gateway-forwarded delegated token (now read from a contextvar at call time — token rotation safe without agent rebuilds).
- No agentscope types leak through the v2 contract; `agent-stream-event.schema.json` is byte-unchanged.
- Read-only operational posture intact; task tools perform no infrastructure access.
