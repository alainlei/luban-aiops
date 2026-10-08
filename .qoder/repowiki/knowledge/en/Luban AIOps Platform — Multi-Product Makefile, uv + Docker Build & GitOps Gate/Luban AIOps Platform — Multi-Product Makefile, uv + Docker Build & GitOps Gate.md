---
kind: build_system
name: Luban AIOps Platform — Multi-Product Makefile, uv + Docker Build & GitOps Gate
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
    - products/agent-platform/Dockerfile
    - products/operator-portal/Makefile
    - shared/base-images/base-uv/Dockerfile
---

## Approach

The Luban platform is a multi-product Python workspace (nine services under `products/`, one SPA under `products/operator-portal/`) built with a **single root GNU make** that delegates per-product work to shared fragments in `mk/`. Each product has its own `pyproject.toml` + `uv.lock` (frozen dependency resolution), its own `Dockerfile`, and a tiny `Makefile` that only sets `IMAGE_NAME` and includes the shared fragments. There are no CI workflow files checked into `.github/workflows`; the repository's verification gate (`make verify`) is intended to be run locally and by an external CI system.

## Key Files

- `Makefile` — root orchestrator: lists `PYTHON_PRODUCTS` and `IMAGE_PRODUCTS`, computes a coordinated `IMAGE_TAG` from `VERSION` + git SHA (+ `-dirty` timestamp for uncommitted changes), builds all images, writes `shared/platform-ops/gitops/dev-k8s/.images.env`, optionally loads images into kind, runs policy/dashboard/version/secret-vocabulary validation, and exposes `deploy`, `e2e`, `verify`.
- `mk/defaults.mk` — single source of overridable build settings via `?=`: `IMAGE_PLATFORM=linux/amd64`, `IMAGE_TAG_PREFIX=dev-k8s`, `REGISTRY`, `AUTO_LOAD_KIND`, `BASE_UV_IMAGE=luban-aiops/base-uv`, `BASE_UV_TAG=al2023`, `BASE_UV_UV_VERSION=0.12.1`, `BASE_UV_PYTHON_VERSION=3.12`.
- `mk/image.mk` — shared container-image targets (`build`, `push`, `lint`). `build` runs `docker build --platform $(IMAGE_PLATFORM) -f $(IMAGE_DOCKERFILE) -t luban-aiops/$(IMAGE_NAME):$(IMAGE_TAG)`; `push` re-tags through `REGISTRY` if set; `lint` uses `hadolint` with a docker-run fallback.
- `mk/python.mk` — shared `sync` / `test` targets using `uv sync --frozen` and `uv run pytest` with OTel exporters disabled so tracing tests stay quiet.
- `products/<name>/Makefile` — each product's thin wrapper (e.g. `products/agent-platform/Makefile` sets `IMAGE_NAME := agent-service` then includes `../../mk/image.mk` and `../../mk/python.mk`).
- `shared/base-images/base-uv/Dockerfile` — shared base image built once by `make base-images`.
- `VERSION` — single source of truth for the platform release version (currently `0.47.0`); read as `PLATFORM_VERSION` and used to prefix every coordinated image tag.
- `products/operator-portal/Makefile` — non-Python product: defines `test` (npm Vitest) and `web-build` (Vite production build) plus `IMAGE_CONTEXT := ../..` because the multi-stage Dockerfile needs the repo-root `VERSION` file.
- `shared/platform-ops/gitops/` — Kustomize overlays rendered by `make overlays` (`kustomize build --load-restrictor LoadRestrictionsNone`).
- `shared/platform-ops/dashboards/validate_dashboards.py` — offline dashboard validator invoked by `make validate-dashboards`.
- `shared/shared-contracts/scripts/validate_version.py`, `validate_secret_vocabulary.py`, `validate_password_policy.py`, `validate_policy.py`, `validate_policy_scenarios.py`, `policy_diff.py` — cross-cutting contract validators called from root targets.

## Architecture and Conventions

1. **Two-level Makefile hierarchy.** The root `Makefile` owns cross-cutting concerns (image tagging, policy sync, overlay rendering, e2e orchestration). Product Makefiles own nothing but `IMAGE_NAME` and include `mk/image.mk` / `mk/python.mk`. This lets `make -C products/<name>` work standalone while `make test` / `make build` at the root iterate over all products.

2. **Coordinated image tagging.** `IMAGE_TAG` is computed once at the root: `<semver>-<prefix>[-<profile>]-<gitsha>` for clean trees, or `<semver>-<prefix>-<gitsha>-dirty-<YYYYMMDDHHMMSS>` for dirty trees. All nine service images plus `web-ui` are tagged with this same value and written to `.images.env` so the deploy step references exactly what was built.

3. **Frozen Python dependencies.** Every Python product uses `uv sync --frozen` against its own `uv.lock`. No network access during build/test; reproducible across machines.

4. **Base image strategy.** All Python services inherit from `luban-aiops/base-uv:<tag>` (AlmaLinux 2023 + pinned uv + python 3.12). The base image is built first via `make base-images` before any product image.

5. **Multi-stage operator portal build.** The SPA is not a uv product. Its Dockerfile lives at `products/operator-portal/Dockerfile`, uses `IMAGE_CONTEXT := ../..` to reach the root `VERSION` file, and the Makefile adds `test` (Vitest) and `web-build` (Vite + tsc) targets. `make verify` explicitly calls both (`portal-test` target).

6. **GitOps-first deployment.** `make deploy` delegates to `shared/platform-ops/gitops/dev-k8s/deploy.sh`. Overlays are validated by `make overlays` (kustomize build check). Samples (`acme-admin`, skills) are installed out-of-band via `make deploy-samples` so the base overlay never names them (per SPEC-050 R-11).

7. **Verification gate.** `make verify` aggregates: product pytest suites, kustomize overlay render, dashboard validation, policy bundle validation + scenario evaluation, version lockstep check, secret vocabulary check, password-policy check, secret-delivery demo, portal Vitest + production build, and execution failure test. It is documented as the pre-commit/pre-push gate.

8. **Policy contracts are canonicalized once.** `shared/shared-contracts/policies/policy-default.yaml` and `password-policy.yaml` are copied into consumers via `make sync-policy`; `make validate-policy` and `make validate-password-policy` enforce schema compliance.

9. **Version lockstep.** `make validate-version` runs `shared/shared-contracts/scripts/validate_version.py` to ensure the root `VERSION` file matches every product's declared version.

## Conventions and Constraints

- **GNU make required.** The root Makefile header states it requires GNU make (default on macOS/Linux).
- **Image platform defaults to `linux/amd64`; override via `IMAGE_PLATFORM=linux/arm64`** (documented in `mk/defaults.mk` for native local/kind builds on arm64 hosts).
- **All image tags are pinned semver + git SHA; `latest` is never used.** Enforced by the tag computation in the root `Makefile` and the comment in `mk/defaults.mk`: "Pinned values below are defaults for reproducible builds — never `latest`."
- **Python deps must be frozen.** `mk/python.mk` always runs `uv sync --frozen`; there is no `--upgrade` path in the standard targets.
- **OTel exporters are disabled during tests.** `mk/python.mk` sets `OTEL_TRACES_EXPORTER=none OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none` so tracing tests do not emit noise; the comment explains `OTEL_SDK_DISABLED` would break them.
- **Operator portal tests cannot be skipped.** Per `SPEC-063 R-8c` (enforced by the `portal-test` target in the root `Makefile`), the full Vitest suite and typechecked Vite production build run as part of `make verify`; there is no integration skip toggle accepted as a release pass.
- **Samples are excluded from the base overlay.** Per `SPEC-050 R-11` (root `Makefile` comments), samples are deployed out-of-band via `make deploy-samples` so `make deploy` never names one.
- **Dashboards are validated offline before deploy.** Per `SPEC-065 R-3`, `make validate-dashboards` parses the OpenObserve dashboards, validates envelope/panel schemas, and verifies every metric reference resolves to an emitted `OTEL_MIRROR_FAMILIES` stream.
- **Registry push is opt-in.** `REGISTRY ?=` is empty by default; `make push` only re-tags and pushes when `REGISTRY` is set.
- **Kind auto-load is opt-in.** `AUTO_LOAD_KIND ?= false`; when enabled, `KIND_CLUSTER_NAME` is required (enforced by the root `Makefile`'s `build` target).
- **No CI workflows checked in.** `.github/workflows/` does not exist; the root `Makefile` documents `make verify` as the forge-agnostic gate to be run locally and under any CI.