# SPEC-064 Plan: Agent-Driven Context Compression and Goal-Oriented Pipeline Adoption

> **Provisional.** Per the workspace SDD workflow, `plan.md` firms up only after
> `spec.md` is approved. This is a scaffold capturing the intended technical direction
> of an **adoption-gate spike**; it authorizes no implementation. The spike is
> documentation-first: Stage 0/1 produce a memo and a verdict, and only a returned
> `adopt` verdict unlocks the conditional Stage 2/3 wiring.

## Approach

Spike-first, verdict-gated. Read the two surfaces in the locked agentscope 2.0.8
install, score each against the SPEC-018 four-point adoption gate, and land a memo with
a per-surface `adopt` / `keep out` verdict. Implementation happens only for a surface
that returns `adopt`; the expected shape is `CompressContext` adopted behind an opt-in
knob and `GoalPipeline` kept out. Stages group the requirements:

- **Stage 0 — Source study (R-1):** read `CompressContext` and `GoalPipeline` in the
  locked venv; capture symbols, gating flags, state/middleware hooks, and event surface.
- **Stage 1 — Gate scoring + memo (R-1):** score both surfaces against the four gate
  points; write the memo; record verdicts.
- **Stage 2 — Compression wiring (R-2, conditional):** only if `CompressContext` adopts.
- **Stage 3 — Pipeline reconciliation (R-3, conditional):** only if `GoalPipeline`
  adopts (expected: keep out, memo-only).
- **Stage 4 — Documentation reconciliation (R-4):** always; resolves the audit rows,
  roadmap backlog, spec index, and — if adopted — CHANGELOG/config/ADR.

## Design Per Requirement

### R-1: Four-point adoption-gate evaluation

- **Affected files / modules:** none (read-only study of
  `products/agent-platform/.venv/lib/python3.12/site-packages/agentscope/agent/_agent.py`
  and `.../agentscope/pipeline/_goal_pipeline.py`); output is a new memo under
  `docs/workspace/`.
- **Chosen approach:** for each surface, fill a four-row gate table (policy+audit /
  delegated-token identity / read-only posture / v2-contract leakage) with concrete 2.0.8
  evidence, then record `adopt` or `keep out`.
- **Grounding already established (drafting):** `CompressContext` is a `FunctionTool`
  (`_COMPRESSION_TOOL_NAME`) over `Agent.compress_context`, gated by
  `ContextConfig.compression_tool_enabled`, with an `on_compress_context` middleware hook
  and an optional context offloader — a SPEC-018-style supported surface. `GoalPipeline`
  is `GoalPipeline(executor, verifier, verifier_reset_context, max_iters, max_retries)`,
  an executor-until-verifier loop surfacing `RequireUserConfirmEvent` /
  `RequireExternalExecutionEvent` / `UserInterruptEvent`.
- **Alternatives considered:** adopting either surface without a memo (rejected — the
  roadmap promotion rule and ADR-0006 require the gate to be evidenced); leaving both
  permanently "deferred" (rejected — the lockfile pins 2.0.8 and an unexamined surface
  is a drift risk).

### R-2: `CompressContext` conditional adoption

- **Affected files / modules (if adopted):** `products/agent-platform/src/agent_service/`
  kernel config/agent-build path (the `ContextConfig` construction and the opt-in env
  plumbing that today carries `AGENTSCOPE_TASK_TOOLS_ENABLED` /
  `AGENTSCOPE_KERNEL_TRACING`), plus `products/agent-platform/tests/`.
- **Chosen approach:** add `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` (default off) →
  `ContextConfig.compression_tool_enabled`; keep compression state in kernel-owned agent
  state so the SPEC-017 snapshot/restore persists it unchanged; verify the tool performs
  no execution; define coexistence with the threshold (`trigger_ratio`) hard compression.
- **Alternatives considered:** enabling by default (rejected — violates the opt-in,
  inert-when-off posture of every other adopted 2.0.x surface); wiring the optional
  context offloader to a new store (rejected unless the memo shows it is safe and
  durable — otherwise keep compression in existing kernel state, no second storage path).

### R-3: `GoalPipeline` conditional reconciliation

- **Affected files / modules (if adopted):** would touch the governed execution seam —
  which is precisely why the expected verdict is `keep out`.
- **Chosen approach:** the memo reconciles the executor/verifier loop against ADR-0011
  (composition carries no authority) and the SPEC-037/038/063 governed dispatch path. If
  it cannot run entirely under the existing policy/HITL/dispatch-claim gates, or if no
  concrete platform caller exists, it is kept out.
- **Alternatives considered:** adopting it as an internal orchestration helper (rejected
  unless every loop iteration is subject to the same gates as a direct turn — otherwise
  it is a second execution edge).

### R-4: Documentation reconciliation

- **Affected files / modules:** `docs/workspace/agentscope-utilization-audit.md` (§2 both
  rows + scope line), `docs/agentic-aiops-platform/delivery-roadmap.md` (Exploration
  Backlog), `docs/specs/README.md` (spec index), this spec's status/changelog; and only
  if a surface ships, `CHANGELOG.md`, `docs/guides/configuration-reference.md`, and a
  new/updated ADR.
- **Chosen approach:** flip "Deferred to SPEC-064" to the resolved verdict with a memo
  link; keep the audit as the single source of truth for surface disposition.

## Sequencing And Dependencies

1. **Stage 0 — source study** — depends on nothing (2.0.8 already pinned by v0.43.2).
2. **Stage 1 — gate scoring + memo (R-1)** — depends on Stage 0. **Gate:** the verdicts
   here decide whether Stages 2/3 run at all, and must land before this spec advances to
   `approved`.
3. **Stage 2 — compression wiring (R-2)** — depends on Stage 1 returning `adopt` for
   `CompressContext`; separately authorized implementation.
4. **Stage 3 — pipeline reconciliation (R-3)** — depends on Stage 1 returning `adopt`
   for `GoalPipeline` (expected: skipped as `keep out`).
5. **Stage 4 — documentation reconciliation (R-4)** — depends on the final verdicts from
   Stages 1–3; always runs.

## Test Strategy

- **unit tests (only if R-2 adopts, in `products/agent-platform/tests/`):** opt-in gating
  (knob off ⇒ `CompressContext` absent from the toolkit and behavior identical to
  v0.43.2; knob on ⇒ present); compression-state persistence across the SPEC-017
  snapshot/restore; no agentscope type leak; coexistence with threshold compression
  (no double-compress / no corrupted tool-result truncation markers).
- **contract tests:** assert `agent-stream-event.schema.json` is byte-unchanged (or, if
  an additive frame is justified, that the version bump and vocabulary parity guards
  pass in every consumer).
- **integration / overlay validation:** none expected — no GitOps, policy-bundle, or
  deployment change. If a knob ships, the configuration-reference drift check and
  `make verify` (which renders overlays and runs the version/policy/secret gates) must
  stay green; the SPEC-063 execution-failure campaign is unaffected.
- **keep-out path:** if both surfaces are kept out, the "test" is the documentation
  reconciliation itself (audit rows resolved, roadmap backlog updated, spec index added)
  and a green `make verify` with no product diff.

## Rollout And Migration

- **Deployment / configuration:** if R-2 adopts, one new default-off env knob
  (`AGENTSCOPE_COMPRESS_CONTEXT_ENABLED`) documented in the configuration reference;
  no GitOps overlay change is required to keep the default posture.
- **Backward compatibility:** default-off means sessions behave exactly as at v0.43.2;
  enabling is per-deployment and reversible. No contract, schema, or storage migration.
- **Rollback:** disable the knob (inert immediately); if compression state was persisted,
  it is kernel-owned agent state that a disabled tool simply stops populating — no
  destructive migration. A `keep out` verdict for both surfaces has nothing to roll back.
