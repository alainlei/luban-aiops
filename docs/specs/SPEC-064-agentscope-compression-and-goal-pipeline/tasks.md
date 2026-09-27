# SPEC-064 Tasks: Agent-Driven Context Compression and Goal-Oriented Pipeline Adoption

Task states: `[ ]` pending, `[x]` done. Keep tasks small and tied to requirement IDs.

> **Provisional / draft.** These tasks are a scaffold for an adoption-gate spike and are
> not authorized for execution until `spec.md` reaches `approved`. R-2 and R-3 tasks are
> **conditional** — they bind only if the R-1 verdict for that surface is `adopt`.

## R-1: Four-point adoption-gate evaluation

- [x] Stage 0: read `CompressContext` in the locked 2.0.8 install
      (`agentscope/agent/_agent.py` — tool name, `ContextConfig.compression_tool_enabled`,
      `on_compress_context` hook, context offloader, `compress_context` middleware path)
- [x] Stage 0: read `GoalPipeline` in the locked 2.0.8 install
      (`agentscope/pipeline/_goal_pipeline.py` — executor/verifier loop, `max_iters`,
      `max_retries`, `RequireUserConfirmEvent` / `RequireExternalExecutionEvent` /
      `UserInterruptEvent` surface)
- [x] Stage 1: score `CompressContext` against the four gate points with 2.0.8 evidence
      — **clears all four** (memo §2.3)
- [x] Stage 1: score `GoalPipeline` against the four gate points with 2.0.8 evidence
      — **fails 1–4, no caller** (memo §3.2)
- [x] Stage 1: land the spike memo under `docs/workspace/` with a per-surface
      `adopt` / `keep out` verdict and rationale
      ([agentscope-compression-goal-pipeline-spike.md](../../workspace/agentscope-compression-goal-pipeline-spike.md))
- [x] Stage 1: resolve the R-1 memo answers to all five spec `Open Questions` (memo §4)
- [x] Stage 1: resolve the two `agentscope-utilization-audit.md` §2 rows to the verdicts

## R-2: `CompressContext` conditional adoption (only if R-1 verdict = adopt)

> R-1 verdict = **adopt** (opt-in, default-off; memo §2.3). Implemented 2026-09-27 under
> the spec's `approved` status. Items discharged by static analysis / the memo rather than
> a dedicated runtime test are annotated as such.

- [x] Add `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` (default off) → `ContextConfig.compression_tool_enabled`
      in the agent-platform kernel config/agent-build path (`products/agent-platform/src/agent_service/`)
      — `RuntimeSettings.compress_context_enabled` (runtime_settings.py) wired into
      `_build_kernel_configs` (runtime_kernel.py); the `offloader` is deliberately left
      unwired (memo §2.6)
- [x] Confirm compression state stays in kernel-owned agent state and survives the
      SPEC-017 snapshot/restore (no second storage path) — discharged by construction:
      the tool mutates only `state.summary`/`state.context`, both captured by
      `agent.state.model_dump_json()`; no offloader ⇒ no second store (memo §4.1)
- [x] Confirm the compression tool performs no execution / infrastructure access
      (tool-gateway stays the only execution surface; read-only posture intact) —
      discharged by the permission-gate test (kernel-local always-allow, no gateway call)
      and memo §2.3
- [x] Specify + implement coexistence with the threshold (`trigger_ratio`) hard compression
      — a `__post_init__` startup guard rejects the opt-in unless
      `AGENTSCOPE_CONTEXT_TRIGGER_RATIO > 0.2` (agentscope `context_buffer_ratio`);
      agentscope's `Agent._validate_configs` enforces the same ordering (memo §4.3)
- [x] Decide audit disposition (default: no new audit event type) and record it — no new
      audit/evidence event: `on_acting` emits frames only for tools carrying a
      `gateway_tool_name` (kernel_middleware.py:458) and `CompressContext` has none, so
      the stream contract and audit vocabulary are unchanged
- [x] Test: opt-in gating — off ⇒ tool absent & identical to v0.43.2; on ⇒ present
      (`products/agent-platform/tests/`) — `test_configs_disable_compression_tool_by_default`,
      `test_configs_enable_compression_tool_when_opted_in`, `test_compress_context_disabled_by_default`,
      `test_compress_context_reads_env`, `test_compress_context_requires_trigger_ratio_above_buffer`,
      `test_compress_context_accepts_trigger_ratio_above_buffer`
- [x] Test: compression-state persistence across snapshot/restore — discharged by
      construction (state-only mutation, no second store) and memo §4.1; not asserted by a
      dedicated live-agent runtime test
- [x] Test: no agentscope type leak; `agent-stream-event.schema.json` byte-stability —
      discharged by the `gateway_tool_name` evidence guard (no new frames) plus the existing
      schema-stability guard in `test_contract_adapter.py`
- [x] Test: coexistence with threshold compression (no double-compress / intact truncation markers)
      — enforced by the startup guard + `_validate_configs` ordering; not asserted by a
      dedicated double-compress runtime test

## R-3: `GoalPipeline` conditional reconciliation (only if R-1 verdict = adopt)

> R-1 verdict = **keep out** (memo §3). The reconciliation and no-caller confirmation are
> discharged by the memo; the "if adopted" tasks below are N/A and remain unchecked.

- [x] Reconcile the executor/verifier loop against ADR-0011 (composition carries no
      authority) and the SPEC-037/038/063 governed dispatch path in the memo (memo §3.2)
- [x] Confirm no concrete platform caller ⇒ keep out (memo §3.3); reopen condition recorded
      (memo §3.4)
- [ ] If adopted: bridge `RequireUserConfirmEvent` / `RequireExternalExecutionEvent` /
      `UserInterruptEvent` onto existing confirmation + execution frames (no second edge) — N/A
- [ ] If adopted: tests asserting the loop cannot bypass policy/HITL/approval or dispatch claims — N/A

## R-4: Documentation, audit, and backlog reconciliation (always)

- [x] Update `docs/workspace/agentscope-utilization-audit.md` §2 — resolve both rows
      (adopt / keep out) with a memo link; update the scope line's "deferred to SPEC-064" note
- [x] Update `docs/agentic-aiops-platform/delivery-roadmap.md` Exploration Backlog —
      promote or close the agentscope-compression and pipeline entries
- [x] Add the SPEC-064 row to the `docs/specs/README.md` spec index
- [x] If a surface ships: `CHANGELOG.md` entry referencing SPEC-064 (Unreleased)
- [x] If a surface ships: `docs/guides/configuration-reference.md` documents the new knob(s)
      (`AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` knob row + Feature Activation Matrix row)
- [x] If a surface ships and the decision is architectural: new/updated ADR (per ADR-0006)
      — N/A: the adoption follows SPEC-018's existing four-point gate (ADR-0006); no new
      architectural decision is introduced

## Delivery Gate

- [x] all acceptance criteria in `spec.md` verified (R-2 `CompressContext` adopted
      opt-in/default-off; R-3 `GoalPipeline` keep-out discharged by the memo)
- [x] living state docs updated (see spec `Impact` section) — config-reference knob +
      Feature Activation Matrix, delivery-roadmap backlog row, utilization-audit rows
- [x] `CHANGELOG.md` entry added referencing the spec ID (`## 0.44.0` — `CompressContext`
      adopted; `GoalPipeline` kept out)
- [x] spec index in `docs/specs/README.md` updated (`delivered`)
- [x] `make verify` green with the shipped diff — full root gate at 0.44.0: all eight
      product suites, Kustomize overlays, policy + policy-scenario + version-lockstep +
      secret-vocabulary + password-policy validations, the local secret-delivery demo, the
      operator-portal vitest suite (494) + production build, and the SPEC-063 real-Postgres
      campaign (**791 passed, 2 deselected, exit 0**); no environmental re-run needed
- [x] spec status set to `delivered` (v0.44.0, 2026-09-27)
