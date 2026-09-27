# v0.43.2 — Dependency Refresh (agentscope 2.0.8)

Date: 2026-09-27
Release type: patch (dependency-only — no new routes, actions, event types,
contracts, schemas, audit changes, or execution paths)

## Summary

A routine re-lock of the eight backend products inside their declared ranges
at latest stable, prompted by the AgentScope 2.0.8 release. The adoption
posture is unchanged from SPEC-042: **latest stable only** — no alpha, beta,
RC, or dev builds — with the OpenTelemetry instrumentation packages staying on
their permanent `0.xb` channel paired with the locked SDK. No manifest range
changed in this patch; every bump lands inside an existing caret-capped range,
so this is a lockfile refresh rather than a contract change.

## Backend re-lock

| Package | Products | From | To |
|---|---|---|---|
| agentscope | agent-platform | 2.0.7.post1 | **2.0.8** |
| pydantic | all eight | 2.13.4 | **2.13.5** |
| pydantic-core | all eight (transitive) | 2.46.4 | 2.46.5 |
| playwright | tool-gateway | 1.62.0 | **1.63.0** |

- **agentscope 2.0.8** is the runtime kernel per ADR-0002, so the bump carries
  the kernel-verification leg (full gate below). `agentscope-runtime` stays at
  **1.1.6.post2** — still the latest published runtime — and co-resolves
  cleanly with agentscope 2.0.8 (no version conflict). 2.0.8 additionally pulls
  `json-repair[schema]`, whose `jsonschema` and `pydantic` requirements reuse
  packages already in the tree, so no new third-party package is introduced.
- **Everything else was already current**: fastapi 0.141.1, cryptography
  50.0.1, httpx 0.28.1, psycopg 3.3.4, uvicorn 0.52.4, pyjwt 2.13.0,
  pyyaml 6.0.3, prometheus-client 0.26.0, jsonschema 4.26.0, and the OTel
  SDK 1.44.0 all sit at their latest stable within range.
- **Caps left parked (deliberate)**: Redis client `<7.0` (deployed server 7.2;
  client majors 7/8 were API-removal releases) and Elasticsearch client `<9.0`
  (client major follows the deployed server major). tool-gateway's Kubernetes
  client stays `<33.0` (locked 32.0.1); agent-platform transitively resolves
  kubernetes 36.0.3 through agentscope-runtime, which is unaffected by the
  tool-gateway cap.

## AgentScope 2.0.8 — what the platform does and does not adopt

AgentScope 2.0.8 (released 2026-09-08) adds several new agent-facing surfaces.
Consistent with the "prefer out-of-box features, but pass the four-point
adoption gate" discipline recorded in
`docs/workspace/agentscope-utilization-audit.md`, this patch adopts **none** of
the new capabilities — it only moves the pinned kernel version:

- **Agent-driven context compression (`CompressContext` tool)** — *not
  adopted*. The kernel keeps its existing threshold-based compression via
  `ContextConfig(trigger_ratio, tool_result_limit)`. Agent-*driven* compression
  (the agent choosing to compress between tasks) is a new opt-in tool surface
  and a genuine adoption candidate; it is deferred to **SPEC-064**.
- **`pipeline` module (`GoalPipeline`)** — *not adopted*. A new
  executor-until-verifier orchestration surface with no current platform
  caller; deferred to **SPEC-064** for an adoption-gate spike.
- **`A2AAgent`, realtime voice agent, RAG LLM reranking** — *not adopted*; out
  of scope for the read-only operational posture (see the utilization audit's
  decision matrix for channels/hub, sandboxes, and RAG).

The `Toolkit.tool_groups` internal surface (task-tool append, gateway-tool
counting) that the utilization audit flags for re-verification on every
agentscope upgrade is re-pinned by the agent-platform suite under 2.0.8
(`test_task_tools_appended_and_excluded_from_gateway_count` and companions) and
passes.

## Verification

- Full root `make verify` gate at 0.43.2: all eight product suites green under
  frozen sync after the re-lock, Kustomize overlays render, policy +
  policy-scenario + version-lockstep + secret-vocabulary + password-policy
  validations pass, the local secret-delivery demo runs, the operator-portal
  vitest suite (494 tests) and production build are green, and the SPEC-063
  execution-failure campaign passes (**791 passed, 2 deselected, exit 0**).
- The SPEC-063 real-Postgres campaign needed one clean re-run to reach exit 0:
  the first attempt (and the paired v0.43.1 attempt) wedged partway through
  under sustained multiprocess load on the local Docker daemon — a cascade of
  `psycopg.errors.ConnectionTimeout` plus dependent `store_unavailable`
  assertions, the environmental flake recorded during the v0.43.0 delivery
  (attempts V1/V5/V6). Every failure was a connection timeout or its direct
  cascade; there were no assertion failures attributable to the re-lock. The
  re-run on a responsive daemon passed all 791 with clean teardown.
- agentscope 2.0.8 kernel leg: the agent-platform suite (including the
  `tool_groups` internals pinning tests and the kernel-middleware tests) passes
  against the upgraded kernel.

## Posture

No behavior, contract, policy, audit, schema, or execution change. Routes,
actions, event types, and execution paths are untouched; identity, policy,
audit, and execution safety semantics are unchanged. The only functional delta
is the upgraded dependency set itself.
