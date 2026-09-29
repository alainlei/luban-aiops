Four top-level document collections form a tiered documentation system defined by `docs/specs/README.md`:

- `adr/` — Architecture Decision Records (14 numbered records plus template), capturing cross-product architectural choices that constrain trust models, identity flows, or deployment topology; immutable once accepted.
- `specs/` — Feature specifications under `SPEC-NNN-<slug>/`, each with a fixed three-file structure (`spec.md` requirements, `plan.md` technical approach, `tasks.md` execution checklist) sourced from `templates/`; currently 65 specs covering the full platform lifecycle.
- `agentic-aiops-platform/` — Long-lived Tier 1 architecture records (decision matrix, reference architecture, authorization matrix, policy specification, delivery roadmap) plus `release-notes/` dated per-release changelogs.
- `guides/` — Operator-facing living documentation (getting started, portal/studio user guides, configuration, troubleshooting, tool authoring).
- `workspace/` — Workspace-level design documents defining product boundaries, backend layout conventions, container strategy, and repository governance, including spike memos for exploratory work.

Dependency direction is one-way: specs and ADRs drive implementation; guides and release notes reflect delivered state. The root `make verify` gate enforces spec-to-test traceability and renders GitOps overlays as part of verification.