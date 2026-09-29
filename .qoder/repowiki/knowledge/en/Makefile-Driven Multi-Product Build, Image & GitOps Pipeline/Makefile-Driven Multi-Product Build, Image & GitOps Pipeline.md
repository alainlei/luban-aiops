---
kind: build_system
name: Makefile-Driven Multi-Product Build, Image & GitOps Pipeline
category: build_system
scope:
    - '**'
source_files:
    - Makefile
    - mk/defaults.mk
    - mk/image.mk
    - mk/python.mk
    - VERSION
    - products/agent-platform/Makefile
    - shared/platform-ops/gitops/dev-k8s/kustomization.yaml
    - shared/platform-ops/gitops/dev-k8s/deploy.sh
    - shared/base-images/base-uv/Dockerfile
---

## What system/approach is used

The repository uses a **single GNU Make workspace** as the build orchestrator. There is no CI configuration file in `.github/workflows`; the root `Makefile` is explicitly documented as "forge-agnostic" and intended to be the pre-commit/pre-push gate run identically locally and under any CI. Product-level build logic is delegated to per-product `Makefile`s that include two shared fragments from `mk/`: `mk/image.mk` (container image targets) and `mk/python.mk` (uv-based dependency sync + pytest). All overridable defaults live in `mk/defaults.mk`. Deployment is via **Kustomize overlays** under `shared/platform-ops/gitops`, with a coordinated tag written into `shared/platform-ops/gitops/dev-k8s/.images.env` by `make build` and consumed by `make deploy`.

## Key files and packages

- `Makefile` — root orchestrator: product lists, coordinated image tagging, policy/dashboard/version validation, overlay rendering, e2e demo runner, verification gate (`verify`).
- `mk/defaults.mk` — single source of truth for `IMAGE_PLATFORM`, `IMAGE_TAG_PREFIX`, `IMAGE_TAG_PROFILE`, `REGISTRY`, `AUTO_LOAD_KIND`, `BASE_UV_*` versions; all values use `?=`, so command-line overrides always win.
- `mk/image.mk` — shared `build` / `push` / `lint` Docker targets; computes `IMAGE_REF` from `REGISTRY`/`IMAGE_NAME`/`IMAGE_TAG`; falls back to `hadolint` docker-run if the binary is missing.
- `mk/python.mk` — shared `sync` (`uv sync --frozen`) and `test` targets; disables OTLP exporters during tests while keeping the SDK active.
- `products/*/Makefile` — thin wrappers that set `IMAGE_NAME` and include the two shared fragments (e.g. `agent-platform` sets `IMAGE_NAME := agent-service`).
- `VERSION` — single source of truth for the platform semver (currently `0.44.0`); read by the root Makefile as `PLATFORM_VERSION`.
- `shared/platform-ops/gitops/dev-k8s/` — Kustomize base overlay plus runtime-profile overlays (`default`, `mutating-dev`, `browser-dev`), each with per-service deployment/service/env manifests.
- `shared/platform-ops/gitops/dev-k8s/deploy.sh` — wrapper invoked by `make deploy`.
- `shared/shared-contracts/scripts/validate_version.py`, `validate_policy.py`, `validate_policy_scenarios.py`, `policy_diff.py`, `validate_secret_vocabulary.py`, `validate_password_policy.py` — scripts invoked by root Makefile targets to enforce cross-cutting contracts.
- `shared/base-images/base-uv/Dockerfile` — shared Python+uv base image built by `make base-images`.

## Architecture and conventions

1. **Two-layer Makefile design.** The root `Makefile` owns cross-cutting concerns (product iteration, coordinated tagging, policy/dashboard/version validation, overlay render checks, e2e demos). Each product's `Makefile` only declares `IMAGE_NAME` and includes `../../mk/image.mk` and `../../mk/python.mk`. This keeps product-specific logic minimal and reusable across all eight Python products plus the operator-portal.

2. **Coordinated image tagging.** The root computes one `IMAGE_TAG` once: `<semver>-<prefix>[-<profile>]-<gitsha>` for clean trees, or `<...>-dirty-<timestamp>` for dirty trees. `make build` invokes `$(MAKE) -C products/<p> build IMAGE_TAG=...` for every `IMAGE_PRODUCT`, then writes `IMAGE_TAG` plus nine service image refs into `shared/platform-ops/gitops/dev-k8s/.images.env`. `make push` re-invokes each product's `push` target.

3. **Image naming convention.** Images are tagged `luban-aiops/<service>:<tag>` locally; when `REGISTRY` is set they are additionally re-tagged to `$(REGISTRY)/luban-aiops/<service>:<tag>` before push. Service names map one-to-one between product directory and image name (e.g. `products/agent-platform` → `agent-service`).

4. **Python dependency management via uv.** Every Python product has its own `pyproject.toml` + `uv.lock` + `.python-version`. `make sync` and `make test` both call `uv sync --frozen` first, ensuring reproducible environments. Tests run under `pytest` with OTLP exporters disabled (`OTEL_TRACES_EXPORTER=none OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none`) so tracing tests pass without an external collector.

5. **Policy bundle canonicalization.** Policy bundles are authored once at `shared/shared-contracts/policies/policy-default.yaml` (and `password-policy.yaml`) and copied into consumers via `make sync-policy` into `products/tool-gateway/src/tool_gateway/policies/`, `products/platform-gateway/src/platform_gateway/policies/`, and `shared/platform-ops/gitops/dev-k8s/base/shared/policy.yaml`. Consumers validate them via `make validate-policy` and scenario evaluation via `make validate-policy-scenarios`.

6. **Version lockstep enforcement.** `make validate-version` runs `shared/shared-contracts/scripts/validate_version.py` against the repo root, enforcing that the root `VERSION` file stays in lockstep with every product version and the portal.

7. **Secret vocabulary lockstep.** `make validate-secret-vocabulary` runs a script that validates secret-literal declarations across `agent-platform`, `tool-gateway`, and `skills-hub`.

8. **GitOps overlay validation.** `make overlays` runs `kustomize build` on every overlay listed in `OVERLAYS` (`dev-k8s`, `runtime-profiles/default`, `runtime-profiles/mutating-dev`, `runtime-profiles/browser-dev`) with `--load-restrictor LoadRestrictionsNone`.

9. **Dashboard validation.** `make validate-dashboards` runs `shared/platform-ops/dashboards/validate_dashboards.py`, which parses OpenObserve dashboard JSON, validates envelope/panel schemas, and verifies every metric reference resolves to an emitted `OTEL_MIRROR_FAMILIES` stream.

10. **Portal build/test separation.** The operator-portal SPA is not a uv product. Its unit suite and production build are gated by `make portal-test`, which runs `make -C products/operator-portal test` (Vitest) and `make -C products/operator-portal web-build` (tsc/vite).

11. **Kind integration.** When `AUTO_LOAD_KIND=true` and `KIND_CLUSTER_NAME` is set, `make build` automatically loads the nine images into the named kind cluster after building them.

## Conventions and constraints

- **GNU make required.** The root `Makefile` header states it requires GNU make (default on macOS and Linux) and sets `SHELL := /bin/sh` consistently across all fragments.
- **Single source of truth for versions.** The root `VERSION` file is the authoritative platform release version; `make validate-version` enforces lockstep with product and portal versions.
- **Frozen Python dependencies.** `mk/python.mk` always runs `uv sync --frozen`, pinning installs to `uv.lock`.
- **Dockerfile linting fallback.** `mk/image.mk`'s `lint` target prefers the `hadolint` binary but falls back to running `hadolint/hadolint` via `docker run` if the binary is unavailable; if neither is present it prints a skip message rather than failing.
- **No CI pipeline in this repo.** There are no GitHub Actions workflows or other CI configs under `.github/`; the author guidelines state the root `Makefile` is "forge-agnostic" and intended to be the pre-commit/pre-push gate.
- **Verification gate composition.** `make verify` chains together `test`, `overlays`, `validate-dashboards`, `validate-policy`, `validate-policy-scenarios`, `validate-version`, `validate-secret-vocabulary`, `validate-password-policy`, `secret-delivery-demo`, `portal-test`, and `execution-failure-test` — it is the comprehensive pre-release gate.
- **Samples kept out of the base overlay.** The root Makefile comments cite SPEC-050 R-11: samples are installed out-of-band via `make deploy-samples` so the base overlay never names a sample.
- **Operator-portal coverage invariant.** A comment in the root Makefile (citing SPEC-063 R-8c) states the portal SPA is not covered by `make test`; `make verify` therefore runs its full Vitest suite and typechecked production build, with no integration skip toggle accepted as a release pass.
- **Base image pinning.** `mk/defaults.mk` pins `BASE_UV_UV_VERSION ?= 0.12.1` and `BASE_UV_PYTHON_VERSION ?= 3.12` with a comment stating pinned values are defaults for reproducible builds — never `latest`.