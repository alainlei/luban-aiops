# Spike: AgentScope 2.0.8 `CompressContext` and `GoalPipeline` — Adoption-Gate Evaluation

Status: assessment complete (SPEC-064 R-1) — `CompressContext` **clears** the four-point
adoption gate and is recommended for opt-in adoption under R-2 (wiring not authorized by
this memo); `GoalPipeline` is **kept out**. No runtime change, no implementation, and no
spec-status flip are part of this assessment.
Date: 2026-09-27
Spec home: [SPEC-064](../specs/SPEC-064-agentscope-compression-and-goal-pipeline/spec.md) (R-1)
Roadmap home: [Exploration Backlog](../agentic-aiops-platform/delivery-roadmap.md#exploration-backlog), agentscope adoption family
Audit home: [agentscope-utilization-audit.md §2](agentscope-utilization-audit.md) — resolves the two "Deferred to SPEC-064" rows
Evidence baseline: repository at 0.43.2 (`96a301e`); static inspection of the locked
agentscope 2.0.8 install
(`products/agent-platform/.venv/lib/python3.12/site-packages/agentscope/`) and the
agent-platform kernel integration, 2026-09-27. No agent was run, no compression or
pipeline was executed, and nothing was deployed.

## 1. Question and recommendation

> Do the two agentscope 2.0.8 surfaces pinned by the v0.43.2 dependency refresh —
> `CompressContext` (agent-driven context compression) and `pipeline.GoalPipeline`
> (executor-until-verifier orchestration) — clear SPEC-018's four-point adoption gate,
> and should the platform wire them?

Recommendation, per surface:

- **`CompressContext` — adopt (opt-in, default off), pending R-2 approval.** It clears all
  four gate points because it is a *context-only* kernel operation, not a tool-execution
  surface: it calls the kernel's own model to summarize and mutates only `AgentState`,
  emits no evidence/SSE frame, needs no identity edge, and persists for free through the
  SPEC-017 snapshot. Critically, the *same* summarization already runs in the platform
  today via the threshold trigger, so agent-driven compression changes **who** triggers
  compression, not the mechanism or the fabrication surface. Wire it behind a new
  default-off `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` knob under a separately approved R-2.
- **`GoalPipeline` — keep out.** It is platform-side autonomous sequencing of two full
  `Agent` instances in a retry/feedback loop, which contradicts ADR-0011 / SPEC-057's
  "no control flow, composition carries no authority, grounded guidance not platform
  sequencing" decision and the SPEC-037/038/063 governed at-most-one-dispatch execution
  path. It has no platform caller. Record it "kept out" alongside the other orchestration
  edges (channels/hub); reopen only on a concrete autonomous-remediation product need that
  can be shown to run entirely under the existing gates.

The four gate points (SPEC-018): (1) deny-by-default policy + audit preserved, tool-gateway
the only execution surface; (2) identity carried only by the gateway-forwarded delegated
token; (3) read-only operational posture; (4) no agentscope types leak through the
platform-owned v2 contract.

## 2. `CompressContext` — evidence and gate scoring

### 2.1 What the surface is (locked 2.0.8)

- `CompressContext` is a `FunctionTool` over `Agent._compress_context_tool`, registered as
  `_COMPRESSION_TOOL_NAME = "CompressContext"`, `is_concurrency_safe=False`, and carrying
  `permission=PermissionDecision(behavior=ALLOW)` — the same always-allowed shape as the
  built-in task tools ([`_agent.py:108-213`](../../products/agent-platform/.venv/lib/python3.12/site-packages/agentscope/agent/_agent.py)).
- It is added to the toolkit **only** when `ContextConfig.compression_tool_enabled` is true
  (`_agent.py:3256-3262`); that field defaults `False`
  ([`_config.py:168-177`](../../products/agent-platform/.venv/lib/python3.12/site-packages/agentscope/agent/_config.py)).
  When runtime-state injection is on, the agent is hinted to compress between tasks as the
  context nears the hard threshold (`_agent.py:1578-1584`).
- `_compress_context_tool` lowers the trigger to `trigger_ratio - context_buffer_ratio`
  (so it fires *ahead* of hard compression) and calls `compress_context`
  (`_agent.py:442-488`).
- `compress_context` runs an `on_compress_context` middleware chain if any middleware
  implements it, then `_compress_context_impl` (`_agent.py:386-440`) — a first-class
  supported hook of the same family SPEC-018 adopted (`on_check_permission`, `on_acting`).
- `_compress_context_impl` (`_agent.py:490-740`): counts tokens, returns early below the
  threshold, splits context into `msgs_to_compress` / `msgs_to_reserve`, calls
  `self.model.generate_structured_output(..., structured_model=cfg.summary_schema)`, then
  sets `self.state.summary = new_summary` and `self.state.context = msgs_to_reserve`.
  On a failed summary it falls back to truncation (`compression_fallback_to_truncation`
  defaults `True`, `_config.py:156-164`).
- Optional `offloader` (from `agentscope.workspace`): if provided, compressed messages are
  written to a `Workspace` path and a `<system-reminder>` referencing the path is appended
  to the summary (`_agent.py:709-733`).

### 2.2 How the platform already uses this mechanism

- `_build_kernel_configs` constructs `ContextConfig(trigger_ratio=settings.context_trigger_ratio,
  tool_result_limit=settings.tool_result_limit)` and **does not** set
  `compression_tool_enabled` — so it is `False` today
  ([`runtime_kernel.py:581-606`](../../products/agent-platform/src/agent_service/runtime_kernel.py)).
  `context_trigger_ratio` defaults `0.8` (`runtime_settings.py:159`), so the **hard
  threshold compression already runs** in the platform via the identical
  `_compress_context_impl` path. `CompressContext` reuses that exact impl.
- `inject_runtime_state=True` is already set (`runtime_kernel.py:602-605`), which already
  activates the `_validate_configs` constraint `context_buffer_ratio < trigger_ratio`
  (`_agent.py:266-282`). Defaults (`0.2 < 0.8`) satisfy it, so enabling the tool adds **no
  new validation burden**.
- State durability: `_snapshot_state` persists the whole agent state via
  `json.loads(agent.state.model_dump_json())`, applies `redact_structure(state, literals)`
  (masking generated credentials at rest), and saves through `AGENT_STATE_STORE`
  (`runtime_kernel.py:638-655`); `_restore_state` reloads it (`runtime_kernel.py:608-636`).
  `state.summary` and `state.context` are core `AgentState` fields, so compression state is
  durable **for free** — the same property the task-tools comment relies on
  (`runtime_kernel.py:521-529`). Ephemeral masking literals are held separately and
  "survive context compaction, never a snapshot" (`runtime_kernel.py:226-227`).

### 2.3 Gate scoring

| Gate point | Verdict | Evidence |
|---|---|---|
| 1. Policy + audit; tool-gateway the only **execution** surface | **Pass** | `CompressContext` executes no tool and reaches no infrastructure — it calls only the kernel's own model to summarize and mutates `AgentState`. It has no `gateway_tool_name`, so `ToolEvidenceMiddleware.on_acting` passes it through with no evidence frame (`kernel_middleware.py:446-451`) and `_count_gateway_tools` excludes it from the no-tools guard (`runtime_kernel.py:567-579`). No new audit event type (mirrors task tools). |
| 2. Identity via delegated token only | **Pass** | Compression never calls the gateway, so it introduces no identity edge; it uses the already-configured kernel model. The `DELEGATED_TOKEN` contextvar path is untouched. |
| 3. Read-only operational posture | **Pass, conditional** | Compression mutates only the agent's own context/summary in state. **Condition:** do **not** wire the optional `offloader` — it writes compressed context to a `Workspace` filesystem path (`_agent.py:709-733`), and workspaces/sandboxes are "kept out" per the audit. With no offloader there are no filesystem writes. |
| 4. No agentscope types through the v2 contract | **Pass** | As a non-gateway tool it emits no SSE/evidence frame, so `agent-stream-event.schema.json` stays byte-unchanged; the `ToolChunk`/`TextBlock` result is consumed internally, exactly like `GenerateStructuredOutput` and task tools today. |

### 2.4 Anti-fabrication assessment (the ReME concern)

The audit rejected ReME's long-term memory partly for "automatic LLM write-back [that]
bypasses audit and risks injecting ungrounded claims." `CompressContext` is **not**
analogous, for three evidenced reasons:

1. **No new mechanism.** The identical LLM summarization already runs by threshold today
   (§2.2); agent-driven compression changes the trigger timing, not the summarizer.
2. **Grounding-preserving prompt.** `ContextConfig.compression_prompt` explicitly requires
   self-contained, absolute references — "resolve anything that depends on the vanished
   context into an absolute, fully-qualified form … file paths, symbol names, PR/issue
   numbers, IDs, URLs, and exact commands/error strings verbatim" (`_config.py:82-114`).
3. **The durable record is untouched.** Compression reshapes only the model's *working
   context*. The evidence store (SPEC-025 `session_evidence`) and the transcript
   (SPEC-039) are separate platform-owned records; the snapshot applies credential
   redaction at rest. The auditable/groundable record therefore survives compression even
   though the live context is summarized.

Residual note: a summary is still model-authored text. This risk is already accepted for
threshold compression; adopting the agent-triggered path does not widen it.

### 2.5 Concrete R-2 wiring requirements (if approved)

- Add `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` (default off) to `RuntimeSettings`, parsed with
  `_optional_bool`, mapped to `ContextConfig.compression_tool_enabled` in
  `_build_kernel_configs` — mirroring `AGENTSCOPE_TASK_TOOLS_ENABLED`
  (`runtime_settings.py:169,495-496`).
- Add `"CompressContext"` to `KERNEL_LOCAL_TOOL_NAMES` (`kernel_middleware.py:105`) so
  `GatewayPermissionMiddleware.on_check_permission` auto-allows it instead of parking it on
  the headless ASK gate (`kernel_middleware.py:313-337`). agentscope also marks the tool
  `ALLOW`, but the platform middleware applies its own KERNEL-local/read-only logic, so the
  explicit membership is required — the task-tools/`GenerateStructuredOutput` precedent.
- Do **not** pass an `offloader` (gate point 3).
- Tests: opt-in gating (off ⇒ tool absent, on ⇒ present); state persistence across
  snapshot/restore; no evidence frame / no type leak; `agent-stream-event.schema.json`
  byte-stability; coexistence with threshold compression (no double-compress, truncation
  markers intact).

## 3. `GoalPipeline` — evidence and gate scoring

### 3.1 What the surface is (locked 2.0.8)

- `GoalPipeline(executor: Agent, verifier: Agent, verifier_reset_context=True, max_iters=10,
  max_retries=3)` runs the two agents in a `while True` loop until the goal is verified
  ([`_goal_pipeline.py:55-330`](../../products/agent-platform/.venv/lib/python3.12/site-packages/agentscope/pipeline/_goal_pipeline.py)).
- The executor produces an `_ExecutionReport`; the verifier produces a `_VerificationResult`
  (`pass` / `fail` / `impossible`). On `fail` it feeds a correction back to the executor and
  increments `_iters` up to `max_iters`; on `verifier_reset_context` it clears the verifier's
  `state.context`/`state.summary` between rounds (`_goal_pipeline.py:293-325`).
- HITL events (`RequireUserConfirmEvent`, `RequireExternalExecutionEvent`) do break the loop
  and propagate, and resumes route by `reply_id` to the executor or verifier
  (`_goal_pipeline.py:146-205, 259-273`).

### 3.2 Gate scoring

| Gate point | Verdict | Evidence / reason |
|---|---|---|
| 1. Policy + audit; single governed execution surface | **Fail** | A platform-owned autonomous loop with retry/feedback control flow directly contradicts ADR-0011 / SPEC-057 ("no control flow — no interpreter, no branch/loop/conditional"; "grounded guidance rather than platform sequencing"; "composition carries no authority"). It is a second orchestration edge beside the SPEC-037/038/063 governed at-most-one-dispatch path. |
| 2. Identity via delegated token only | **Fail (unmapped)** | The platform runs one kernel agent per session with a per-token cached gateway toolkit and `DELEGATED_TOKEN` identity read at call time. Two tool-capable agents (executor + verifier) expand the identity/toolkit surface with no mapped need. |
| 3. Read-only / bounded-autonomy posture | **Fail** | An executor that autonomously retries toward a goal (up to `max_iters`) is materially more autonomous than the platform's operator-driven, diagnose-before-act, one-turn-at-a-time HITL model — even though individual mutating steps still park via HITL events. |
| 4. No agentscope types through the v2 contract | **Fail** | The pipeline interleaves two agents' event streams; the v2 SSE contract and `agent-stream-event.schema.json` model one agent's turn. Surfacing executor + verifier would require a contract and portal decoder change. |

### 3.3 No caller

There is no platform product need for an executor-until-verifier loop: Luban is human-led,
approval-gated operations, not autonomous goal-seeking (the same "no need identified"
posture as TTS and channels/hub in the audit). Absent a caller, adoption fails on need
before the gate is even reached.

### 3.4 Reopen condition

Reopen only if a concrete autonomous-remediation product need is established **and** it can
be shown to run entirely under the existing policy/HITL/signed-dispatch gates as a single
governed agent. The two-agent loop-with-retries shape does not satisfy that today; a future
need would more likely be met by composing existing single-target skills (SPEC-057) than by
adopting `GoalPipeline`.

## 4. SPEC-064 Open Questions — resolutions

1. **State the snapshot does not capture / offloader safety.** None. `CompressContext`
   mutates only `state.summary` + `state.context`, both captured by
   `agent.state.model_dump_json()` and secret-redacted at rest. The optional `offloader`
   writes to a `Workspace` path — do not wire it (kept-out surface), so there is no new
   store and no filesystem write.
2. **Anti-fabrication (ReME analogy).** Not analogous — same mechanism already running by
   threshold, grounding-preserving prompt, and the durable evidence/transcript records are
   separate from kernel context (§2.4).
3. **Interaction with `ReplyBudgetControlMiddleware` / trigger path.** No conflict: the
   budget middleware's state lives in `agent.state.middle_context` (SPEC-018) while
   compression touches `state.context`/`state.summary`; `on_compress_context` is a distinct
   hook (none registered today). The agent tool fires at `trigger_ratio - context_buffer_ratio`,
   ahead of the hard-threshold backstop; `_validate_configs` already enforces the ordering
   because `inject_runtime_state=True`.
4. **Any concrete `GoalPipeline` caller?** None. Keep out (§3.3).
5. **`GoalPipeline` event bridging.** N/A under keep-out; recorded as the reopen condition
   (§3.4).

## 5. Go/no-go and next decision

- **`CompressContext`: go for R-2**, gated on operator approval of SPEC-064 scope. R-2 is a
  small, opt-in, default-off kernel change (one settings knob, one `KERNEL_LOCAL_TOOL_NAMES`
  membership, no offloader) plus the tests in §2.5. It is not authorized by this memo.
- **`GoalPipeline`: no-go / keep out.** No code. Resolve the audit row to "Kept out
  (SPEC-064)".
- This memo is documentation-only. It does not flip the SPEC-064 status, change product
  code, or authorize deployment. The operator decides whether to advance SPEC-064 to
  `approved` (which would then permit R-2 wiring under separate authorization).

## Changelog

- 2026-09-27: initial assessment (SPEC-064 R-1). Static inspection of the locked
  agentscope 2.0.8 install and the agent-platform kernel integration at 0.43.2
  (`96a301e`). Verdicts: `CompressContext` clears the four-point gate (adopt, opt-in,
  pending R-2 approval); `GoalPipeline` kept out. No runtime implementation, live test,
  deployment, or spec-status change.
