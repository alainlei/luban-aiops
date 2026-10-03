---
kind: build_system
name: Luban Platform Build & Artifact Management
category: build_system
scope:
    - '**'
source_files:
    - Makefile
    - mk/defaults.mk
    - mk/image.mk
    - mk/python.mk
    - VERSION
    - shared/base-images/base-uv/Dockerfile
    - products/agent-platform/Makefile
    - products/operator-portal/Makefile
    - shared/platform-ops/gitops/dev-k8s/deploy.sh
    - samples/deploy-samples.sh
---

## System Overview

The Luban platform uses a layered GNU Make build system centered on a root `Makefile` that delegates per-product routines to individual product Makefiles, which in turn include shared fragments under `mk/`. There is no CI pipeline file in this repository snapshot (no `.github/workflows/`), so the documented gate is `make verify`, described as "Forge-agnostic" and intended to run identically locally and under any CI.

Build artifacts are container images produced by Docker; Python dependencies are managed per-product via `uv` with frozen lockfiles (`pyproject.toml` + `uv.lock`). Deployment is GitOps-driven through Kustomize overlays under `shared/platform-ops/gitops/`, orchestrated by shell scripts.

## Key Files

- Root orchestrator: `Makefile` — aggregates per-product targets, computes coordinated image tags, runs verification gates, policy sync/validation, overlay rendering, dashboard validation, e2e demos, and deploy.
- Shared defaults: `mk/defaults.mk` — single source of truth for overridable settings (`IMAGE_PLATFORM`, `REGISTRY`, `BASE_UV_*`, `AUTO_LOAD_KIND`, etc.) using `?=` so command-line overrides always win.
- Image fragment: `mk/image.mk` — provides `build` / `push` / `lint` targets for every product image; requires `IMAGE_NAME` from the including Makefile.
- Python fragment: `mk/python.mk` — provides `sync` / `test` targets running `uv sync --frozen` then `uv run pytest` with OTel exporters disabled.
- Per-product Makefiles (minimal): each under `products/<name>/Makefile` sets `IMAGE_NAME` and includes `../../mk/image.mk` and `../../mk/python.mk`.
- Operator portal frontend: `products/operator-portal/Makefile` — defines `test` (Vitest) and `web-build` (Vite + tsc) since it has no Python suite.
- Version pin: `VERSION` (semver, e.g. `0.46.0`) — single source of truth for the coordinated image tag prefix.
- Base image: `shared/base-images/base-uv/Dockerfile` — built by `make base-images` with pinned `BASE_UV_PYTHON_VERSION` and `BASE_UV_UV_VERSION`.
- Deploy orchestration: `shared/platform-ops/gitops/dev-k8s/deploy.sh` — applies the overlay then provisions secrets, sessions DB, OIDC realm/client, and OTel credentials via sibling `sync-*` scripts.
- Sample installer: `samples/deploy-samples.sh` — packs sample skill documents into a `skills-samples` ConfigMap and restarts skills-hub.

## Architecture and Conventions

### Coordinated tagging
The root `Makefile` computes one `IMAGE_TAG` once:
```
<semver>-<prefix>[-<profile>]-<gitsha>
```
for clean trees; dirty trees append `-dirty-<timestamp>`. The semver comes from `VERSION`; `IMAGE_TAG_PREFIX` defaults to `dev-k8s`; `IMAGE_TAG_PROFILE` is empty by default. All product images share this tag, and `make build` writes them all into `shared/platform-ops/gitops/dev-k8s/.images.env` so `make deploy` consumes a consistent set.

### Product decomposition
Products are split by stable architectural boundary (agent-platform, audit-service, execution-runtime, identity-broker, incident-service, platform-gateway, skills-hub, tool-gateway, operator-portal). Each product ships its own `Dockerfile`, `Makefile`, `pyproject.toml`, `uv.lock`, and `tests/`. The root `Makefile` enumerates them explicitly:
- `PYTHON_PRODUCTS` — eight Python services with a uv test suite.
- `IMAGE_PRODUCTS` — same eight plus `operator-portal`.

### Multi-stage image builds
Every product `Dockerfile` is a multi-stage build: a builder stage installs deps via `uv sync --frozen` against the product's `uv.lock`, and a runtime stage copies only the package. The shared base image `luban-aiops/base-uv:<tag>` (built from `shared/base-images/base-uv/Dockerfile`) pins both Python and uv versions.

### Policy contracts
Canonical policy bundles live under `shared/shared-contracts/policies/`. `make sync-policy` copies them into consumers (`tool-gateway`, `platform-gateway`, `dev-k8s/base/shared/policy.yaml`). `make validate-policy` validates against JSON schema; `make validate-policy-scenarios` evaluates scenario expectations against both engines; `make policy-diff CANDIDATE=<path>` reports per-(role, action) differences.

### Secret vocabulary lockstep
`make validate-secret-vocabulary` enforces that secret literal names stay synchronized across `agent-platform`, `tool-gateway`, and `skills-hub` via `shared/shared-contracts/scripts/validate_secret_vocabulary.py`.

### Dashboard validation
`make validate-dashboards` runs `shared/platform-ops/dashboards/validate_dashboards.py` to parse OpenObserve dashboards, validate envelope/panel schemas, and assert every metric reference resolves to an emitted `OTEL_MIRROR_FAMILIES` stream (SPEC-065 R-3).

### Portal testing
Per SPEC-063 R-8c, the operator-portal SPA is not a uv product. `make portal-test` runs Vitest unit tests and the Vite production build; zero tests is a failure path.

### Verification gate
`make verify` chains: product tests, kustomize overlay renders, dashboard validation, policy validation/scenarios/version check, secret vocabulary check, password policy check, secret-delivery demo, portal test, and execution failure test. It is the pre-commit/pre-push gate.

### Deployment flow
`make deploy` invokes `shared/platform-ops/gitops/dev-k8s/deploy.sh`, which:
1. Applies the overlay via `deploy-overlay.sh`.
2. Provisions secrets (delegation, audit trail, execution signing, handoff, skills, incidents, browser credentials, OTel) unless skipped via `SKIP_*` env vars.
3. Creates the sessions Postgres database.
4. Reconciles the Keycloak realm and portal OIDC client (unless `RECONCILE_OIDC_PORTAL_CLIENT=false`).

Samples are deployed out-of-band via `make deploy-samples` (or `samples/deploy-samples.sh`), never through the base overlay (SPEC-050 R-11).

### Cross-platform image builds
`IMAGE_PLATFORM` defaults to `linux/amd64` but can be overridden (e.g. `linux/arm64` for native kind on arm64 hosts). `AUTO_LOAD_KIND=true` after `make build` loads all nine images into a kind cluster named by `KIND_CLUSTER_NAME`.

## Conventions and Constraints

- **Single version source**: `VERSION` at the repo root is the authoritative platform version; `make validate-version` enforces lockstep between `VERSION`, every product's declared version, and the portal (enforced by `shared/shared-contracts/scripts/validate_version.py`).
- **Frozen Python deps**: `uv sync --frozen` is used everywhere; dependency changes require updating `uv.lock`.
- **No `latest` tags**: `mk/defaults.mk` comments state pinned values are defaults for reproducible builds — never `latest`.
- **GNU make required**: The root `Makefile` header states it requires GNU make (default on macOS and Linux).
- **Forge-agnostic gate**: `make verify` is the documented pre-commit/pre-push gate intended to run identically locally and under any CI.
- **Coordinated image tag invariant**: All images built by `make build` receive the same computed `IMAGE_TAG`; `make deploy` reads the `.images.env` state file rather than re-computing tags.
- **Policy bundle canonicalization**: The canonical policy files under `shared/shared-contracts/policies/` are the sole authors; consumers must be updated via `make sync-policy` (enforced by `make validate-policy` and `make validate-password-policy`).
- **Dashboard immutability check**: Dashboards must pass offline schema and metric-reference validation before deployment (SPEC-065 R-3 enforced by `make validate-dashboards`).
- **Portal coverage requirement**: The operator-portal SPA unit suite and production build are part of `make verify` and cannot be skipped (SPEC-063 R-8c).
- **Samples excluded from base overlay**: Tutorial samples are installed only via `make deploy-samples`, never through `make deploy` (SPEC-050 R-11).
- **Secret provisioning is opt-out in CI**: Each `sync-*-secrets.sh` script is gated by a `SKIP_*_SECRETS=true` environment variable for CI environments where secrets are injected externally.