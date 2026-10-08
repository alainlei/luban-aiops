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

For the current release and the full delivered sequence, see [CHANGELOG.md](CHANGELOG.md) (the repository's release history) and the [spec index](docs/specs/README.md) (per-spec status: `draft` → `approved` → `delivered`). The root [VERSION](VERSION) file is the single source of truth for the platform semver.

All nine build products — `operator-portal`, `agent-platform`, `platform-gateway`, `tool-gateway`, `identity-broker`, `skills-hub`, `audit-service`, `incident-service`, and `execution-runtime` — are implemented, tested, and deployable to the `dev-k8s` overlay (eleven workloads in total, including Redis and PostgreSQL).

## Routines

Day-to-day routines are driven by the root [Makefile](Makefile): `make verify` (the pre-commit/pre-push gate — all product test suites plus GitOps overlay rendering), `make test`, `make build`, `make lint`, and `make deploy`. Run `make help` for the full list, or `make -C products/<name> help` for per-product targets.
