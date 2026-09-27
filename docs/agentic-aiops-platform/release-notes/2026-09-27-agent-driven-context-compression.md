# v0.44.0 — Agent-Driven Context Compression (SPEC-064 R-2)

Date: 2026-09-27
Release type: minor (one new opt-in, default-off kernel capability — no new
routes, actions, event types, contracts, schemas, audit changes, or execution
paths)

## Summary

This release adopts the first of the two agentscope 2.0.8 surfaces that the
v0.43.2 dependency refresh pinned into the lockfile but deliberately left
unwired. [SPEC-064](../../specs/SPEC-064-agentscope-compression-and-goal-pipeline/spec.md)
scored both against SPEC-018's four-point adoption gate in the
[R-1 spike memo](../../workspace/agentscope-compression-goal-pipeline-spike.md):
`CompressContext` **clears** the gate and is adopted here as an opt-in,
default-off kernel knob; `GoalPipeline` is **kept out** (no code). Because the
new capability is off by default, an unset deployment is byte-identical to
v0.43.2 — threshold compression still runs off `ContextConfig.trigger_ratio`.

## What shipped

- **`AGENTSCOPE_COMPRESS_CONTEXT_ENABLED`** (`RuntimeSettings.compress_context_enabled`,
  default `false`) maps onto `ContextConfig.compression_tool_enabled` in the
  kernel's `_build_kernel_configs`. When enabled, agentscope registers its
  `CompressContext` tool, letting the agent summarize its own working context
  on demand. It runs the *same* `_compress_context_impl` the threshold trigger
  already runs, so the change is *who* triggers compression, not the mechanism.
- **Kernel-local always-allow.** `"CompressContext"` joins `TASK_TOOL_NAMES` and
  `GenerateStructuredOutput` in `KERNEL_LOCAL_TOOL_NAMES`, so the permission
  gate short-circuits it before the read-only allow-list and the run-stop DENY
  path. It only rewrites `state.summary`/`state.context` and never touches an
  external system, so parking it on the headless ASK gate would wedge
  compression for no governance benefit.
- **Startup ordering guard.** `__post_init__` rejects the opt-in unless
  `AGENTSCOPE_CONTEXT_TRIGGER_RATIO > 0.2` (agentscope's
  `context_buffer_ratio`), mirroring agentscope's `Agent._validate_configs`
  requirement that `context_buffer_ratio < trigger_ratio`. This keeps the
  agent-driven tool firing *ahead of* the hard-threshold backstop and fails
  startup early rather than wedging at agent-build time.

## Why the offloader stays unwired

agentscope's `CompressContext` can optionally take a workspace `offloader` that
writes the compressed messages to a `Workspace` filesystem path and injects a
`<system-reminder>` referencing it. SPEC-064 R-2 deliberately passes
`offloader=None`:

- **Gate point 3 (read-only posture).** The offloader writes to the pod
  filesystem and bundles a full exec backend — an ungoverned, unmasked
  plaintext copy of context outside the tool-gateway.
- **Durability fork.** Compression state instead stays in
  `state.summary`/`state.context`, which the SPEC-017 agent-state snapshot
  already persists to the shared Postgres store and secret-redacts at rest — so
  it is durable for free, with no second storage path.
- **Deployment topology.** The agent runtime runs in-cluster with `replicas: 1`
  and the workspace mounted as `emptyDir`. A pod-local offloader file would be
  invisible to any future replica (split-brain on scale-out) and wiped on
  reschedule (`emptyDir` is ephemeral while the Postgres snapshot survives).

## Not adopted

- **`pipeline.GoalPipeline`** — *kept out.* It has no platform caller, and its
  executor-until-verifier loop-with-retries shape cannot be reconciled with
  ADR-0011 (composition carries no authority) or the SPEC-037/038/063 governed
  dispatch path. Reopen only on a concrete need that runs entirely under the
  existing policy/HITL/signed-dispatch gates as a single governed agent.

## Verification

- agent-platform suite green under frozen sync (**1514 passed**), including the
  new SPEC-064 R-2 tests: opt-in gating at the config and env layers, the
  permission-gate always-allow / kernel-local membership, and the
  `trigger_ratio`-above-`context_buffer_ratio` startup guard.
- No agentscope type leak and no stream-contract change: `on_acting` emits
  evidence frames only for tools carrying a `gateway_tool_name`, which
  `CompressContext` lacks, so `agent-stream-event.schema.json` and the audit
  vocabulary are untouched (the existing `test_contract_adapter.py`
  schema-stability guard still passes).
- `make validate-version` green at 0.44.0 (all eight products + portal wiring).

## Posture

Additive and default-off. No route, action, event type, contract, schema,
policy, or audit change; identity, policy, audit, and execution safety
semantics are unchanged. Deployments that do not set
`AGENTSCOPE_COMPRESS_CONTEXT_ENABLED=true` behave exactly as they did at
v0.43.2.
