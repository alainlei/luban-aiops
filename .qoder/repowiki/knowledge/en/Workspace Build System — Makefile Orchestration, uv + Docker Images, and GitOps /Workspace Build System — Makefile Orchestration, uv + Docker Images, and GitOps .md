---
kind: build_system
name: Workspace Build System — Makefile Orchestration, uv + Docker Images, and GitOps Overlays
category: build_system
scope:
    - '**'
source_files:
    - Makefile
    - mk/defaults.mk
    - mk/python.mk
    - mk/image.mk
    - VERSION
    - products/agent-platform/Makefile
    - products/operator-portal/Makefile
    - shared/platform-ops/gitops/dev-k8s/.images.env
    - shared/shared-contracts/scripts/validate_version.py
    - shared/shared-contracts/scripts/validate_secret_vocabulary.py
    - shared/shared-contracts/scripts/validate_policy.py
    - shared/shared-contracts/scripts/validate_policy_scenarios.py
    - shared/shared-contracts/scripts/policy_diff.py
    - shared/shared-contracts/scripts/validate_password_policy.py
    - shared/platform-ops/dashboards/validate_dashboards.py
---

# Luban Agentic AIOps Platform — Build & Artifact Management

## Approach

The repository uses a **Makefile-driven workspace** that delegates per-product work to shared fragments under `mk/`. There is no CI pipeline file in this snapshot (no `.github/workflows` directory); the root `make verify` target is documented as the forge-agnostic pre-commit/pre-push gate intended to run identically locally and under any CI.

Each product under `products/<name>/` is an independent Python FastAPI service (or the operator-portal SPA) with its own `pyproject.toml`, `uv.lock`, `Dockerfile`, and thin `Makefile` that only sets `IMAGE_NAME` and includes the shared fragments. The root `Makefile` aggregates them into coordinated image builds, policy sync/validation, GitOps overlay rendering, dashboard validation, e2e demos, and deployment.

## Key Files

- `Makefile` — master orchestrator; defines `PYTHON_PRODUCTS`, `IMAGE_PRODUCTS`, `OVERLAYS`, `verify`, `build`, `push`, `deploy`, `sync-policy`, `validate-version`, `validate-secret-vocabulary`, `validate-password-policy`, `overlays`, `validate-dashboards`, `observability-livecheck`, `execution-failure-test`, `portal-test`, `e2e`, `deploy-samples`.
- `mk/defaults.mk` — single source of overridable build settings (`IMAGE_PLATFORM`, `IMAGE_TAG_PREFIX`, `IMAGE_TAG_PROFILE`, `REGISTRY`, `AUTO_LOAD_KIND`, `KIND_CLUSTER_NAME`, `BASE_UV_IMAGE`, `BASE_UV_TAG`, `BASE_UV_UV_VERSION`, `BASE_UV_PYTHON_VERSION`). All values use `?=`, so command-line overrides always win.
- `mk/python.mk` — shared `sync` / `test` targets for Python products: `uv sync --frozen` then `uv run pytest` with OTLP exporters disabled (`OTEL_TRACES_EXPORTER=none OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none`) so tests stay free of retry noise while the SDK stays active.
- `mk/image.mk` — shared `build` / `push` / `lint` targets for container images; resolves `IMAGE_CONTEXT`, `IMAGE_DOCKERFILE`, `IMAGE_REF` (`luban-aiops/<name>:<tag>` or `<REGISTRY>/luban-aiops/<name>:<tag>`), and falls back to `hadolint` via `docker run hadolint/hadolint` when the binary is not installed.
- `VERSION` — single source of truth for the platform release version (semver, currently `0.46.0`); consumed by the root Makefile to compute `PLATFORM_VERSION` and enforced against every product's declared version via `shared/shared-contracts/scripts/validate_version.py`.
- Per-product `Makefile`s — minimal files that set `IMAGE_NAME` and include `../../mk/image.mk` and `../../mk/python.mk`; the operator-portal additionally defines `WEB_UI_APP := web-ui/app`, `test` (npm Vitest), and `web-build` (npm Vite production build).
- `shared/platform-ops/gitops/` — Kustomize overlays rendered by `make overlays` (`dev-k8s`, `runtime-profiles/default`, `runtime-profiles/mutating-dev`, `runtime-profiles/browser-dev`).
- `shared/platform-ops/dashboards/` — OpenObserve dashboards validated offline by `make validate-dashboards` (SPEC-065 R-3).
- `shared/shared-contracts/scripts/` — canonical validators invoked from the root Makefile: `validate_policy.py`, `validate_policy_scenarios.py`, `policy_diff.py`, `validate_version.py`, `validate_secret_vocabulary.py`, `validate_password_policy.py`.

## Architecture and Conventions

### Coordinated image tagging

The root `make build` computes one `IMAGE_TAG` once:

```
<semver>-<prefix>[-<profile>]-<gitsha>
```

A dirty tree appends `-dirty-<timestamp>`. The tag is derived from `VERSION` (the semver prefix), `IMAGE_TAG_PREFIX` (default `dev-k8s`), `IMAGE_TAG_PROFILE`, and `git rev-parse --short HEAD`. This same tag is applied to every product image and written to `shared/platform-ops/gitops/dev-k8s/.images.env`, which the deploy script consumes so all services are deployed at a consistent point-in-time.

### Product classification

Products are explicitly enumerated in two lists at the top of the root `Makefile`:

- `PYTHON_PRODUCTS` — agent-platform, audit-service, execution-runtime, identity-broker, incident-service, platform-gateway, skills-hub, tool-gateway (each has `uv sync --frozen` + pytest).
- `IMAGE_PRODUCTS` — the above plus `operator-portal` (SPA served by nginx; no Python test suite).

Adding a new product requires adding it to both lists and providing a `products/<name>/Makefile` that sets `IMAGE_NAME` and includes the shared fragments.

### Policy distribution model

The canonical policy bundle lives at `shared/shared-contracts/policies/policy-default.yaml` and is copied to three consumers by `make sync-policy`: `products/tool-gateway/src/tool_gateway/policies/policy-default.yaml`, `products/platform-gateway/src/platform_gateway/policies/policy-default.yaml`, and `shared/platform-ops/gitops/dev-k8s/base/shared/policy.yaml`. A separate `password-policy.yaml` is similarly synced to `products/tool-gateway/src/tool_gateway/policies/password-policy.yaml` (SPEC-062 R-2). Consumers never edit these copies directly; they are regenerated from the canonical location.

### Version lockstep

`make validate-version` runs `shared/shared-contracts/scripts/validate_version.py` against the repo root, enforcing that the root `VERSION` file and every product's declared version stay in lockstep. This is part of the `verify` gate.

### Secret vocabulary lockstep

`make validate-secret-vocabulary` runs `shared/shared-contracts/scripts/validate_secret_vocabulary.py` across agent-platform, tool-gateway, and skills-hub to keep secret-literal declarations synchronized.

### Dashboard validation

OpenObserve dashboards under `shared/platform-ops/dashboards/` are validated offline by `python3 $(DASHBOARDS_DIR)/validate_dashboards.py` (SPEC-065 R-3): parse + envelope/panel schema + every metric reference must resolve to an emitted `OTEL_MIRROR_FAMILIES` stream. The live import itself is reserved for the operator step `apply-dashboards.sh` (SPEC-065 R-4).

### Operator portal build

The operator-portal is the only non-Python product. Its `Makefile` defines `test` (runs `npm --prefix web-ui/app test`, i.e. Vitest) and `web-build` (runs `npm --prefix web-ui/app run build`, which performs `tsc --noEmit && vite build`). The root `make portal-test` runs both, and `make verify` delegates to it because the SPA is not covered by `make test` (SPEC-063 R-8c).

### Kind integration

Setting `AUTO_LOAD_KIND=true` after `make build` automatically loads all nine built images into a kind cluster named by `KIND_CLUSTER_NAME` (required when enabled). The default `IMAGE_PLATFORM` is `linux/amd64`; `linux/arm64` is supported for native local/kind builds on arm64 hosts.

### Base image strategy

All Python services build on a shared base image `shared/base-images/base-uv/Dockerfile` built by `make base-images`, pinned to `BASE_UV_UV_VERSION=0.12.1` and `BASE_UV_PYTHON_VERSION=3.12` on Amazon Linux 2023 (`BASE_UV_TAG=al2023`). No `latest` tags are used anywhere in the defaults.

## Conventions and Constraints

- **GNU make required.** The root Makefile header states: "Requires GNU make (default on macOS and Linux)".
- **Single source of truth for versions:** `VERSION` is the platform release version; `make validate-version` enforces lockstep with every product's declared version.
- **No `latest` tags:** `mk/defaults.mk` comments state pinned values are defaults for reproducible builds — never `latest`.
- **Command-line overrides always win:** `mk/defaults.mk` documents that all values use `?=` so invocations like `make build IMAGE_PLATFORM=linux/arm64` override defaults.
- **`make verify` is the canonical gate:** It runs `test overlays validate-dashboards validate-policy validate-policy-scenarios validate-version validate-secret-vocabulary validate-password-policy secret-delivery-demo portal-test execution-failure-test` — product tests, contract validation, policy validation, GitOps overlay render check, dashboard validation, portal unit tests + production build, secret delivery demo, and crash-safety failure proof.
- **Policy bundles are never edited at consumer sites:** They are copied from `shared/shared-contracts/policies/` by `make sync-policy`; consumers validate via `make validate-policy` and `make validate-policy-scenarios`.
- **Password policy is a canonical contract:** SPEC-062 R-2 pins the connector floor to the password-policy contract authored beside the policy bundle.
- **Operator portal tests cannot be skipped:** The comment in `products/operator-portal/Makefile` notes that Vitest fails on zero tests, so there is no skip/zero-tests green path; `make verify` demands both the full Vitest suite and the typechecked production build.
- **GitOps overlays are checked at build time:** `make overlays` runs `kustomize build --load-restrictor LoadRestrictionsNone` on every overlay listed in `OVERLAYS`.
- **Secret vocabulary must stay synchronized:** Enforced by `make validate-secret-vocabulary` across agent-platform, tool-gateway, and skills-hub.
- **Images are tagged with a deterministic coordinated tag:** The root `make build` writes `shared/platform-ops/gitops/dev-k8s/.images.env` with the exact `IMAGE_TAG` and every service image name, consumed by the deploy script so all components ship together.