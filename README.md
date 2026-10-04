# Agentic AIOps Workspace

This repository is the workspace for the proposed enterprise-grade agentic AIOps platform.

The workspace is organized as a modular platform made up of multiple product-oriented projects with clear boundaries, explicit integration points, and shared platform contracts.

## Workspace Goals

- keep the platform modular and maintainable
- support independent evolution of major platform capabilities
- preserve clear ownership boundaries
- make integration points explicit
- allow self-contained release slices across the platform

## Top-Level Structure

- `products/`
  - product-oriented projects that deliver core platform capabilities
- `shared/`
  - shared contracts, SDKs, and platform operations assets
- `docs/`
  - architecture, design, delivery, and workspace documents

## Product Projects

- `products/operator-portal`
  - web portal for operators, approvers, and auditors
- `products/agent-platform`
  - agent runtime, orchestration, session handling, and streaming
- `products/policy-center`
  - policy evaluation, approval orchestration, and authorization controls (design-stage stub: not yet built or deployed — the action-authorization slice is currently enforced inside `tool-gateway`; see its README)
- `products/identity-broker`
  - `SSO`, identity federation, group normalization, and identity propagation
- `products/platform-gateway`
  - portal-facing API edge: token verification, action policy, chat/session proxying, and token delegation
- `products/skills-hub`
  - Git-based Markdown skill ingestion, validation, indexing, and retrieval support
- `products/tool-gateway`
  - normalized tool and connector access, including `MCP` and external system integration
- `products/audit-service`
  - durable audit trail: authenticated event ingest, retention-bounded store, and permission-scoped query API
- `products/incident-service`
  - incident intake (Alertmanager webhook and manual reports), fingerprint dedupe, agent-driven triage with validated reports, and collaboration connector dispatch
- `products/execution-runtime`
  - isolated execution workers for bounded operational actions

## Shared Modules

- `shared/shared-contracts`
  - API, event, policy, approval, and domain contracts
- `shared/shared-sdk`
  - shared client libraries, auth helpers, and tracing helpers
- `shared/platform-ops`
  - Kubernetes, gateway, deployment, and environment assets

## Key Documents

- Repository changelog: [CHANGELOG.md](CHANGELOG.md)
- Spec-driven development workflow and spec index: [README.md](docs/specs/README.md)
- Architecture decision records: [README.md](docs/adr/README.md)
- Platform study index: [README.md](docs/agentic-aiops-platform/README.md)
- Release notes index: [README.md](docs/agentic-aiops-platform/release-notes/README.md)
- Workspace docs index: [README.md](docs/workspace/README.md)
- Python container strategy: [python-container-strategy.md](docs/workspace/python-container-strategy.md)
- GitHub governance baseline: [github-repository-governance.md](docs/workspace/github-repository-governance.md)
- Agent platform runtime options: [agent-platform-runtime-options.md](docs/agentic-aiops-platform/agent-platform-runtime-options.md)

## Design Rules

- keep platform boundaries product-oriented, not only technology-oriented
- keep identity, policy, and execution concerns separated
- keep shared modules small and dependency-light
- prefer API and event contracts over direct internal coupling
- expand capabilities release by release with clear validation points

## Python Toolchain

- Python services standardize on `uv` for environment and package management
- the workspace pins the preferred interpreter version with `.python-version`
- Python product directories also carry `.python-version` so product-local container builds can honor the same interpreter target
- the current backend images build on the shared `luban-aiops/base-uv` image — an environment-specific Amazon Linux 2023 base (non-root uid 1000) with `uv` layered on to manage both the interpreter and packages

## Current State

The platform is currently at **v0.46.0**; see [CHANGELOG.md](CHANGELOG.md) and the [spec index](docs/specs/README.md) for the full delivered sequence through SPEC-066. All nine build products — `operator-portal`, `agent-platform`, `platform-gateway`, `tool-gateway`, `identity-broker`, `skills-hub`, `audit-service`, `incident-service`, and `execution-runtime` — are implemented, tested, and deployable to the `dev-k8s` overlay (eleven workloads in total, including Redis and PostgreSQL). The narrative below is the release-by-release history through Release 3. Release 0 (platform foundation) and Release 1 (SPEC-001 through SPEC-009) established the first deployable slice: `agent-platform`, `identity-broker`, `platform-gateway`, `tool-gateway`, and `operator-portal`. Release 1 closes with the read-only tool execution framework (SPEC-007), broker-mediated service-to-service identity (SPEC-008, implementing ADR-0004), and pre-production hardening (SPEC-009: tool-output redaction and workload-identity service tokens) before the first non-dev deployment. SPEC-010 (implementing ADR-0005) then split the former combined gateway into `platform-gateway` (portal-facing edge) and `tool-gateway` (tool and connector service). SPEC-011 added the Elastic observability connector and portal evidence panels, SPEC-012 delivered the operator guide suite, and SPEC-013 replaced the ephemeral pod-log audit trail with a durable one: the new `audit-service` product ingests audit events from `tool-gateway`, `platform-gateway`, and `identity-broker`, retains them under a bounded retention window (in-memory or PostgreSQL), and serves an `audit:read`-gated query API to the portal's audit view. Release 2 opens with SPEC-014 (Skills and Grounded Guidance): the new `skills-hub` product federates team-owned Markdown skill sources (local directories and git repositories), validates them against the shared skill contract, and serves deterministic ranked search; `tool-gateway` exposes read-only `skills.search` / `skills.get` tools, and the agent is prompted to consult, cite, and honestly report when no team guidance matches. Release 3 delivers SPEC-015 (Incident Triage and Collaboration): the new `incident-service` product ingests Alertmanager webhooks and manual operator reports into one canonical incident model, runs operator-initiated agent triage that produces schema-validated triage reports with ranked advisory next steps, and dispatches outcomes through a pluggable connector framework whose built-in `audit` sink puts `incident_triaged` events on the durable trail; `tool-gateway` exposes read-only `incidents.list` / `incidents.get` tools, and the operator portal gains the Incidents panel with report, triage, and continue-in-chat workflows.

See [CHANGELOG.md](CHANGELOG.md) for delivered work and the [spec index](docs/specs/README.md) for the status of each spec.

## Routines

Day-to-day routines are driven by the root [Makefile](Makefile): `make verify` (the pre-commit/pre-push gate — all product test suites plus GitOps overlay rendering), `make test`, `make build`, `make lint`, and `make deploy`. Run `make help` for the full list, or `make -C products/<name> help` for per-product targets.
