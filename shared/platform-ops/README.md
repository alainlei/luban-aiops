# Platform Ops

## Purpose

`platform-ops` contains the shared operational assets for running the workspace in Kubernetes and exposing it through enterprise infrastructure.

Typical contents include:

- Kubernetes manifests or Helm charts
- gateway configuration
- environment overlays
- shared deployment assets

## Ownership

Recommended owner:

- platform operations or platform engineering team

## Current Scope

This module covers:

- Kubernetes deployment assets
- gateway and ingress configuration
- environment overlays and release wiring
- shared operational conventions across workspace products

Current implementation artifacts:

- `gitops/dev-k8s/README.md`
- `gitops/dev-k8s/kustomization.yaml`
- `gitops/dev-k8s/base/`
- `gitops/runtime-profiles/`

The current implementation provides a single development Kubernetes overlay under a durable `gitops/` root. The `dev-k8s` overlay deploys the full platform — nine application workloads (operator-portal, platform-gateway, agent-platform, tool-gateway, execution-runtime, identity-broker, audit-service, skills-hub, incident-service) plus Redis and PostgreSQL — into the `dev-luban-aiops` namespace. Provider choice is modeled as a separate shared runtime profile layer so the active profile remains reviewable and Git-diffable. The source manifests are grouped by shared infrastructure and product ownership so the overlay stays maintainable as the workspace grows.

## Execution reliability operations (SPEC-063)

- `e2e/execution-failure-test.sh` runs the required disposable Postgres/process
  campaign; missing prerequisites and incomplete coverage fail, never skip to green.
- `gitops/execution-cutover.sh` guards deliberate downgrade/unknown-version changes
  with operator-confirmed disabled mutations and verified empty sender inventory.
- `gitops/rotate-execution-epoch.sh` updates only the DSN-selected disabled catalog;
  it neither configures consumer epochs nor enables admission.
- The [cutover/restore runbook](../../docs/guides/execution-cutover-restore.md)
  defines the mandatory first protocol upgrade, old-sender accounting, restore wait,
  and limits. Stock deploy does not automate that procedure. No wrapper proves
  exactly-once remote effects or cancellation of already dispatched work.

## Expected Integration Points

- all deployable `products/` services
- `shared/shared-contracts` and `shared/shared-sdk` where runtime configuration depends on shared platform conventions
- cluster, ingress, and secret-management infrastructure

## Boundary

This module supports deployment and operations, but should not own application business logic.
