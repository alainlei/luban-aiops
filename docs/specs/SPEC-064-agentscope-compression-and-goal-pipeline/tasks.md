# SPEC-064 Tasks: Agent-Driven Context Compression and Goal-Oriented Pipeline Adoption

Task states: `[ ]` pending, `[x]` done. Keep tasks small and tied to requirement IDs.

> **Provisional / draft.** These tasks are a scaffold for an adoption-gate spike and are
> not authorized for execution until `spec.md` reaches `approved`. R-2 and R-3 tasks are
> **conditional** — they bind only if the R-1 verdict for that surface is `adopt`.

## R-1: Four-point adoption-gate evaluation

- [ ] Stage 0: read `CompressContext` in the locked 2.0.8 install
      (`agentscope/agent/_agent.py` — tool name, `ContextConfig.compression_tool_enabled`,
      `on_compress_context` hook, context offloader, `compress_context` middleware path)
- [ ] Stage 0: read `GoalPipeline` in the locked 2.0.8 install
      (`agentscope/pipeline/_goal_pipeline.py` — executor/verifier loop, `max_iters`,
      `max_retries`, `RequireUserConfirmEvent` / `RequireExternalExecutionEvent` /
      `UserInterruptEvent` surface)
- [ ] Stage 1: score `CompressContext` against the four gate points with 2.0.8 evidence
- [ ] Stage 1: score `GoalPipeline` against the four gate points with 2.0.8 evidence
- [ ] Stage 1: land the spike memo under `docs/workspace/` with a per-surface
      `adopt` / `keep out` verdict and rationale
- [ ] Stage 1: resolve the R-1 memo answers to all five spec `Open Questions`

## R-2: `CompressContext` conditional adoption (only if R-1 verdict = adopt)

- [ ] Add `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` (default off) → `ContextConfig.compression_tool_enabled`
      in the agent-platform kernel config/agent-build path (`products/agent-platform/src/agent_service/`)
- [ ] Confirm compression state stays in kernel-owned agent state and survives the
      SPEC-017 snapshot/restore (no second storage path)
- [ ] Confirm the compression tool performs no execution / infrastructure access
      (tool-gateway stays the only execution surface; read-only posture intact)
- [ ] Specify + implement coexistence with the threshold (`trigger_ratio`) hard compression
- [ ] Decide audit disposition (default: no new audit event type) and record it
- [ ] Test: opt-in gating — off ⇒ tool absent & identical to v0.43.2; on ⇒ present
      (`products/agent-platform/tests/`)
- [ ] Test: compression-state persistence across snapshot/restore
- [ ] Test: no agentscope type leak; `agent-stream-event.schema.json` byte-stability
- [ ] Test: coexistence with threshold compression (no double-compress / intact truncation markers)

## R-3: `GoalPipeline` conditional reconciliation (only if R-1 verdict = adopt)

- [ ] Reconcile the executor/verifier loop against ADR-0011 (composition carries no
      authority) and the SPEC-037/038/063 governed dispatch path in the memo
- [ ] Confirm no concrete platform caller ⇒ keep out (expected default), or define how
      every loop iteration stays under existing policy/HITL/dispatch-claim gates
- [ ] If adopted: bridge `RequireUserConfirmEvent` / `RequireExternalExecutionEvent` /
      `UserInterruptEvent` onto existing confirmation + execution frames (no second edge)
- [ ] If adopted: tests asserting the loop cannot bypass policy/HITL/approval or dispatch claims

## R-4: Documentation, audit, and backlog reconciliation (always)

- [ ] Update `docs/workspace/agentscope-utilization-audit.md` §2 — resolve both rows
      (adopt / keep out) with a memo link; update the scope line's "deferred to SPEC-064" note
- [ ] Update `docs/agentic-aiops-platform/delivery-roadmap.md` Exploration Backlog —
      promote or close the agentscope-compression and pipeline entries
- [ ] Add the SPEC-064 row to the `docs/specs/README.md` spec index
- [ ] If a surface ships: `CHANGELOG.md` entry referencing SPEC-064
- [ ] If a surface ships: `docs/guides/configuration-reference.md` documents the new knob(s)
- [ ] If a surface ships and the decision is architectural: new/updated ADR (per ADR-0006)

## Delivery Gate

- [ ] all acceptance criteria in `spec.md` verified (a `keep out` verdict for both
      surfaces satisfies R-1/R-4 with no product diff)
- [ ] living state docs updated (see spec `Impact` section)
- [ ] `CHANGELOG.md` entry added referencing the spec ID (only if a surface is adopted)
- [ ] spec index in `docs/specs/README.md` updated
- [ ] `make verify` green with the shipped diff (no product diff on the keep-out path)
- [ ] spec status set to `delivered`
