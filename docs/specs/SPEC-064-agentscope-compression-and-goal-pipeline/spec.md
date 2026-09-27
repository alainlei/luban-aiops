# SPEC-064: Agent-Driven Context Compression and Goal-Oriented Pipeline Adoption

## Status

- status: `draft`
- owner: luban-platform-team
- created: 2026-09-27
- release slice: R5 — hardening / Exploration Backlog (agentscope adoption family)
- related ADRs: [ADR-0006](../../adr/0006-contract-purpose-invariant-enforcement.md)
  (kernel exploitation follows SPEC-018's four-point adoption gate),
  [ADR-0011](../../adr/0011-composition-carries-no-authority.md) (composition carries
  no authority — the control-flow boundary `GoalPipeline` must be reconciled against);
  a new ADR is required only if a surface is adopted and the decision is architectural
- lineage: promoted from the agentscope-utilization-audit §2 rows deferred to SPEC-064
  during the v0.43.2 dependency refresh (agentscope 2.0.7.post1 → 2.0.8); extends the
  SPEC-017 (kernel state durability) and SPEC-018 (kernel middleware alignment /
  adoption gate) discipline

> Drafting note (SDD discipline): this is a **draft adoption-gate spike**. Per the
> workspace workflow, `spec.md` is agreed first; the accompanying `plan.md` and
> `tasks.md` are provisional scaffolds that firm up only after scope approval. Nothing
> in this spec authorizes product-code, contract, policy, GitOps, deployment, or live
> changes. A "keep out" verdict is a complete, deliverable outcome.

## Summary

Evaluate — and adopt **only if they clear the four-point adoption gate** — the two
agentscope 2.0.8 surfaces that the v0.43.2 dependency refresh pinned into the lockfile
but deliberately did **not** wire: `CompressContext` (agent-driven context compression)
and the `pipeline` module's `GoalPipeline` (an executor-until-verifier orchestration
loop). This spec resolves the "Deferred to SPEC-064" placeholders in the utilization
audit. Because the platform's posture is deny-by-default, read-only, and
gateway-governed, the expected default for `GoalPipeline` is **keep out**; the expected
default for `CompressContext` is **adopt behind an opt-in knob** if, and only if, the
spike shows it is context-only, state-durable, and grounding-preserving.

## Motivation

- **The surfaces are already pinned and unexamined.** v0.43.2 moved agentscope to
  2.0.8, which added `CompressContext` and `pipeline.GoalPipeline`. Consistent with the
  four-point adoption-gate discipline, that patch adopted none of 2.0.8's new agent
  surfaces and deferred both to this spec
  (`docs/workspace/agentscope-utilization-audit.md` §2, and the v0.43.2 release note).
  Deciding their disposition while the version is fresh prevents a silent
  "available-but-unexamined" drift in the lockfile.
- **`CompressContext` fills a real gap the kernel does not cover today.** The kernel
  already compresses automatically **by threshold** via
  `ContextConfig(trigger_ratio, tool_result_limit)` — a reactive, kernel-owned squeeze
  at a token ratio. agentscope 2.0.8 additionally exposes an **agent-directed**
  compression tool (`_COMPRESSION_TOOL_NAME = "CompressContext"`, a `FunctionTool`
  wrapped over `Agent.compress_context`) gated by `ContextConfig.compression_tool_enabled`,
  with a first-class `on_compress_context` middleware hook and an optional context
  offloader. Letting the agent choose to compress **between tasks** is a genuine
  capability candidate — but it is a new opt-in tool surface with kernel-owned
  compression-state, audit, and durability (SPEC-017 snapshot/restore) interactions
  that must be scored before wiring.
- **`GoalPipeline` overlaps the governed execution path and SPEC-057's control-flow
  boundary.** `GoalPipeline(executor, verifier, max_iters, max_retries)` runs an
  executor agent and a verifier agent **in a loop until the goal is verified**, and it
  surfaces `RequireUserConfirmEvent`, `RequireExternalExecutionEvent`, and
  `UserInterruptEvent`. That is autonomous multi-step orchestration with no current
  platform caller. It collides with (a) SPEC-057's deliberate "no control flow, no
  interpreter, composition carries no authority" decision (ADR-0011) and (b) the
  SPEC-037/038/063 governed, approval-gated, at-most-one-dispatch execution path.
  Adopting it naively would create a **second, ungoverned orchestration edge** — the
  same failure mode that keeps channels/hub, sandboxes, and MCP "out" in the audit.
- **Why this slice.** Both rows are already tracked as deferred-to-SPEC-064 in a
  delivered living doc; the roadmap promotion rule ("a spike lands its findings as a
  short memo; only then does the item get a SPEC number") is satisfied by assigning this
  spec number and requiring the memo as R-1's deliverable.

## Requirements

Each requirement is stable once this spec is `approved` and carries testable acceptance
criteria. R-2 and R-3 are **conditional**: they bind only if R-1's gate evaluation
returns an `adopt` verdict for the corresponding surface. A `keep out` verdict closes
the requirement with a documentation change only.

### R-1: Four-point adoption-gate evaluation for both surfaces

Score `CompressContext` and `GoalPipeline` independently against the SPEC-018 four-point
adoption gate, and record a per-surface `adopt` / `keep out` verdict backed by evidence
from the locked 2.0.8 install.

The four gate points (from SPEC-018):

1. preserves deny-by-default policy enforcement and the audit trail (tool-gateway
   remains the only tool **execution** surface);
2. keeps identity carried exclusively by the gateway-forwarded delegated token;
3. keeps the read-only operational posture;
4. leaks no agentscope types through the platform-owned v2 contract (routes,
   request/response schemas, SSE event contract unchanged).

Acceptance criteria:

- A spike memo lands under `docs/workspace/` (e.g.
  `agentscope-compression-goal-pipeline-spike.md`) recording, **for each surface**, the
  four gate points, the concrete 2.0.8 evidence (symbol, gating flag, state/middleware
  hooks, event surface), and an explicit `adopt` or `keep out` verdict with rationale.
- `docs/workspace/agentscope-utilization-audit.md` §2 rows for `CompressContext` and
  `GoalPipeline` are updated from "Deferred to SPEC-064" to the resolved decision, each
  linking the memo.
- A `keep out` verdict for either surface is a complete, deliverable outcome requiring
  no product-code change; the spec closes as an evaluation record for that surface.
- No verdict may be recorded without the gate evidence; "available in 2.0.8" is not by
  itself an adoption reason.

### R-2: Agent-driven context compression (`CompressContext`) — conditional adoption

**Binds only if R-1 returns `adopt` for `CompressContext`.** Wire it as an opt-in,
default-off kernel surface that coexists with the existing threshold compression and
preserves durability, grounding, and the contract boundary.

Acceptance criteria:

- **Opt-in, default off, inert when disabled.** Enabled by a new environment knob
  (working name `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED`, default off) that maps onto
  `ContextConfig.compression_tool_enabled`, mirroring the existing
  `AGENTSCOPE_TASK_TOOLS_ENABLED` / `AGENTSCOPE_KERNEL_TRACING` pattern. When disabled,
  the `CompressContext` tool is absent from the toolkit and behavior is byte-identical
  to v0.43.2.
- **Kernel-owned state, durability-preserving.** Any compression state (including the
  optional context offloader output) lives in kernel-owned agent state covered by the
  SPEC-017 snapshot/restore, so it survives session persistence and re-hydration;
  asserted by a persistence test. No second storage path is introduced (the
  kernel-side `AsyncSQLAlchemyStorage` stays "kept out" per the audit).
- **Context-only; no execution surface.** Compression performs no infrastructure or
  tool access and cannot reach the network, filesystem, or any connector — the
  tool-gateway stays the only execution surface (gate point 1) and the read-only posture
  is intact (gate point 3).
- **Grounding-preserving (anti-fabrication).** The spike must show that agent-directed
  compression does not drop grounding/citation content in a way analogous to the ReME
  LLM write-back rejection recorded in the audit; if it cannot be shown safe, the
  verdict flips to `keep out`.
- **Defined interaction with existing compression.** The relationship between
  agent-directed `CompressContext` and the reactive `ContextConfig(trigger_ratio,
  tool_result_limit)` hard compression is specified (coexist without double-compressing
  or corrupting tool-result truncation markers) and matches agentscope's own
  ordering guard (`compression_tool_enabled` vs. hard-compression threshold).
- **Identity unchanged.** The compression path carries identity only via the existing
  delegated-token contextvar; it introduces no new identity edge (gate point 2).
- **Contract boundary unchanged.** No agentscope types leak through the v2 contract;
  `agent-stream-event.schema.json` stays byte-unchanged unless the spike demonstrates a
  concrete operator-visible need, in which case any change is additive and versioned.
- **Audit disposition decided and minimal.** The spike records whether compression
  warrants an audit event; the default is **no new audit event type** unless an
  operator-visible need is evidenced.
- **Tests.** opt-in gating (off ⇒ tool absent, on ⇒ present); state persistence across
  snapshot/restore; no-toolkit/no-type leak; contract byte-stability; coexistence with
  threshold compression.

### R-3: Goal-oriented pipeline (`GoalPipeline`) — conditional adoption (expected keep-out)

**Binds only if R-1 returns `adopt` for `GoalPipeline`.** The expected default verdict
is `keep out`, given no current platform caller and the direct overlap with the
governed execution path; this requirement exists to make that reconciliation explicit
and evidenced rather than assumed.

Acceptance criteria:

- **Reconciled against ADR-0011 / SPEC-057 and the governed path.** The spike states
  explicitly how an executor-until-verifier loop (`max_iters`, `max_retries`) would sit
  under SPEC-057's "no control flow / no interpreter / composition carries no authority"
  decision and the SPEC-037/038/063 at-most-one-dispatch governed execution path. If
  `GoalPipeline` would introduce autonomous multi-step execution outside the
  tool-gateway / policy / HITL / approval gates, it is **kept out**.
- **No gate bypass if adopted.** Any adopted orchestration remains subject to the same
  deny-by-default policy, HITL approval for mutating steps, delegated-token identity,
  durable single-use dispatch claims, and audit as the existing path — its
  `RequireUserConfirmEvent` / `RequireExternalExecutionEvent` / `UserInterruptEvent`
  must bridge onto the platform's existing confirmation and execution frames, not
  around them.
- **No caller ⇒ keep out.** If the spike identifies no concrete platform product need
  (the TTS/channels situation), the verdict is `keep out` and no code is written.
- **A `keep out` verdict is fully deliverable** with a documentation change only.

### R-4: Documentation, audit, and backlog reconciliation

Whichever verdicts are reached, reconcile the living documentation so no surface is
left in a "deferred" limbo.

Acceptance criteria:

- `docs/workspace/agentscope-utilization-audit.md` §2 resolves **both** rows (adopt or
  keep out) with links to the memo; the scope line's "deferred to SPEC-064" note is
  updated to the outcome.
- `docs/agentic-aiops-platform/delivery-roadmap.md` Exploration Backlog promotes or
  closes the agentscope-compression and pipeline entries to reflect the verdicts.
- This spec's status/changelog records the outcome; `docs/specs/README.md` spec index
  gains the SPEC-064 row.
- **If a surface is adopted:** a `CHANGELOG.md` entry references SPEC-064,
  `docs/guides/configuration-reference.md` documents the new knob(s), and a new/updated
  ADR captures the decision if it is architectural (per ADR-0006).
- **If neither is adopted:** no product `CHANGELOG` entry; the spec closes as an
  evaluation record and both audit rows read "Kept out (SPEC-064)".

## Non-Goals

- The other agentscope 2.0.8 surfaces also deferred by v0.43.2 — `A2AAgent`, realtime
  voice, and RAG LLM reranking — stay in the audit/backlog and are **out of scope** here.
- MCP exposure/consumption, kernel-side `AsyncSQLAlchemyStorage`, sandboxes/workspaces,
  built-in file/shell tools, channels/hub, and TTS remain "kept out" or "spike needed"
  per the audit; this spec does not revisit them.
- No change to the governed execution path (SPEC-037/038/063), the approval/HITL model
  (SPEC-020/021/030/054), or skill-composition authority (SPEC-057 / ADR-0011).
- Not replacing or retuning the existing threshold-based `ContextConfig` compression;
  R-2 only defines how an agent-directed tool **coexists** with it.
- No dependency version change — agentscope is already pinned at 2.0.8 by v0.43.2; this
  spec changes disposition, not the lockfile version.

## Impact

- **products touched:** `products/agent-platform` (kernel) only, and only if R-2 or R-3
  returns `adopt`; otherwise documentation-only. No other product is affected.
- **contracts touched:** none expected. `agent-stream-event.schema.json` stays
  byte-unchanged unless R-2's spike evidences a concrete operator-visible frame need,
  in which case any change is additive and version-bumped.
- **identity / policy / audit / execution safety impact:** must be **none by design**
  (gate points 1–3). Compression is context-only; any adopted orchestration stays under
  the existing policy/HITL/approval/dispatch-claim gates. R-2's default is no new audit
  event type.
- **living state docs to update on delivery:** `docs/workspace/agentscope-utilization-audit.md`,
  `docs/agentic-aiops-platform/delivery-roadmap.md`, `docs/specs/README.md`, and — only
  if a surface ships — `docs/guides/configuration-reference.md`, `CHANGELOG.md`, and a
  new/updated ADR.

## Open Questions

Resolved by the R-1 spike
([agentscope-compression-goal-pipeline-spike.md](../../workspace/agentscope-compression-goal-pipeline-spike.md),
2026-09-27); none remain open, so this spec is decision-complete and ready for the
operator to approve or reject.

1. **State the snapshot does not capture / offloader safety — resolved.** `CompressContext`
   mutates only `state.summary` + `state.context`, both captured by `_snapshot_state`'s
   `agent.state.model_dump_json()` and secret-redacted at rest. The optional `offloader`
   writes compressed messages to a `Workspace` filesystem path; it is **not** wired (the
   workspace surface stays "kept out"), so there is no new store and no filesystem write.
2. **Anti-fabrication (ReME analogy) — resolved.** Not analogous: the identical
   `_compress_context_impl` already runs by threshold today (`trigger_ratio=0.8`), the
   `compression_prompt` mandates self-contained absolute references (paths, IDs, URLs,
   exact commands verbatim), and the durable evidence (SPEC-025) and transcript (SPEC-039)
   records are separate from kernel context — so compression reshapes only the model's
   working context, never the auditable record.
3. **Interaction with `ReplyBudgetControlMiddleware` / the trigger path — resolved.** No
   conflict: the budget middleware's state lives in `agent.state.middle_context` (SPEC-018)
   while compression touches `state.context`/`state.summary`; `on_compress_context` is a
   distinct hook (none registered today). The agent tool fires at
   `trigger_ratio - context_buffer_ratio`, ahead of the hard-threshold backstop, and
   `_validate_configs` already enforces that ordering because `inject_runtime_state=True`.
4. **Any concrete `GoalPipeline` caller — resolved.** None. The platform is human-led,
   approval-gated operations, not autonomous goal-seeking (the TTS/channels situation), so
   R-3 resolves to an immediate **keep out**.
5. **`GoalPipeline` event bridging — resolved (N/A).** Moot under keep-out; recorded as the
   reopen condition — a future need must run entirely under the existing
   policy/HITL/signed-dispatch gates as a single governed agent, which the two-agent
   loop-with-retries shape does not satisfy.

## R-1 Verdicts (2026-09-27)

- **`CompressContext`: clears the four-point adoption gate.** Recommended for opt-in,
  default-off adoption under R-2 (`AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` →
  `ContextConfig.compression_tool_enabled`; add `"CompressContext"` to
  `KERNEL_LOCAL_TOOL_NAMES`; do not wire the `offloader`). R-2 wiring is **not** authorized
  by the spike and requires this spec to reach `approved` plus separate implementation
  authorization.
- **`GoalPipeline`: kept out.** No code; the audit row is resolved to "Kept out (SPEC-064)".


## Changelog

- 2026-09-27: **R-1 spike landed.** Static inspection of the locked agentscope 2.0.8
  install and the agent-platform kernel integration at 0.43.2 resolved all five Open
  Questions and produced per-surface verdicts in
  [agentscope-compression-goal-pipeline-spike.md](../../workspace/agentscope-compression-goal-pipeline-spike.md):
  `CompressContext` **clears** the four-point gate (recommended opt-in adoption under R-2);
  `GoalPipeline` is **kept out**. Updated the utilization-audit §2 rows accordingly. Status
  stays `draft` — the spike authorizes no wiring, and advancing to `approved` (which would
  permit R-2 under separate authorization) is the operator's decision.
- 2026-09-27: created as `draft` — an adoption-gate spike resolving the two
  agentscope 2.0.8 surfaces (`CompressContext`, `GoalPipeline`) deferred to SPEC-064 by
  the v0.43.2 dependency refresh. Grounded in the locked 2.0.8 install and the SPEC-018
  four-point adoption gate. No product code, contract, policy, GitOps, deployment, or
  live change is authorized by this draft.
