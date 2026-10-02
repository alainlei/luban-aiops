---
kind: build_system
name: Luban Workspace Build System — Makefile + uv + Docker Orchestration
category: build_system
scope:
    - '**'
source_files:
    - Makefile
    - mk/defaults.mk
    - mk/image.mk
    - mk/python.mk
    - VERSION
    - products/platform-gateway/Makefile
    - products/platform-gateway/Dockerfile
    - shared/base-images/base-uv/Dockerfile
    - shared/platform-ops/gitops
    - shared/platform-ops/dashboards
    - shared/platform-ops/e2e
    - shared/shared-contracts/scripts
---

## What system/approach is used

The Luban workspace is a monorepo built with **GNU make** as the top-level orchestrator, **uv** for Python dependency resolution and test execution (frozen lockfiles), and **Docker** for container images. There are no CI workflow files under `.github/workflows`; the root `Makefile` declares itself "Forge-agnostic" and is intended to be the pre-commit/pre-push gate run identically locally and in any CI.

Each product under `products/<name>/` is self-contained: it has its own `pyproject.toml`, `uv.lock`, `.python-version`, `Dockerfile`, and a thin `Makefile` that only sets `IMAGE_NAME` and includes two shared fragments from `mk/`. The root `Makefile` aggregates per-product routines and owns cross-cutting concerns: GitOps overlay checks, verification gates, coordinated image tagging, policy sync/validation, dashboard validation, portal SPA build, and e2e demo orchestration.

## Key files and packages

- `Makefile` — master orchestrator; defines `PYTHON_PRODUCTS`, `IMAGE_PRODUCTS`, `OVERLAYS`, `GITOPS_DIR`, `E2E_DIR`, `SAMPLES_DIR`, coordinated `IMAGE_TAG` computation, and targets `sync`, `test`, `lint`, `build`, `push`, `verify`, `deploy`, `e2e`, `validate-dashboards`, `portal-test`, `execution-failure-test`, `policy-*`, `validate-version`, `validate-secret-vocabulary`, `validate-password-policy`.
- `mk/defaults.mk` — single source of overridable build settings (`IMAGE_PLATFORM`, `IMAGE_TAG_PREFIX`, `IMAGE_TAG_PROFILE`, `REGISTRY`, `AUTO_LOAD_KIND`, `KIND_CLUSTER_NAME`, `BASE_UV_IMAGE`, `BASE_UV_TAG`, `BASE_UV_UV_VERSION`, `BASE_UV_PYTHON_VERSION`). All values use `?=`, so command-line overrides always win.
- `mk/image.mk` — shared container-image targets (`help`, `build`, `push`, `lint`) included by every product Makefile; requires `IMAGE_NAME` and optionally `IMAGE_CONTEXT` / `IMAGE_DOCKERFILE`.
- `mk/python.mk` — shared `sync` / `test` targets using `uv sync --frozen` and `uv run pytest` with OTLP exporters disabled.
- `shared/platform-ops/gitops` — Kustomize overlays rendered by `make overlays` (`dev-k8s`, `runtime-profiles/default|mutating-dev|browser-dev`).
- `shared/platform-ops/dashboards` — OpenObserve dashboards validated offline by `make validate-dashboards`.
- `shared/platform-ops/e2e` — end-to-end demo scripts invoked via `make e2e`.
- `shared/shared-contracts/scripts/*` — policy and version validators invoked from the root Makefile.
- `VERSION` — single source of truth for the platform release semver; read into `PLATFORM_VERSION` at the top of the root Makefile.
- Per-product `Dockerfile`s — all inherit `luban-aiops/base-uv:<tag>` and install deps with `uv sync --frozen --no-dev`.
- Per-product `Makefile`s — minimal wrappers setting `IMAGE_NAME` and including `../../mk/image.mk` and `../../mk/python.mk`.

## Architecture and conventions

1. **Two-layer Makefile design.** Root `Makefile` holds processing logic (tag computation, product iteration, cross-cutting targets); `mk/*.mk` hold reusable fragments. Products include fragments rather than duplicating logic.
2. **Coordinated image tagging.** `make build` computes one `IMAGE_TAG` once per invocation using the pattern `<semver>-<prefix>[-<profile>]-<gitsha>` (or `-dirty-<timestamp>` when `git status --porcelain` is non-empty) and writes an `.images.env` state file consumed by `make deploy`. All images share this tag.
3. **Product registry lists.** `PYTHON_PRODUCTS` and `IMAGE_PRODUCTS` enumerate products centrally; new services must be added to both lists to participate in `make test` / `make build`.
4. **Frozen dependency management.** Every Python product uses `uv sync --frozen` against its local `uv.lock`; there is no runtime dependency resolution or editable installs in the build path.
5. **Base image strategy.** A shared `shared/base-images/base-uv/Dockerfile` builds `luban-aiops/base-uv:<tag>` (default `al2023`) with pinned `UV_VERSION=0.12.1` and `PYTHON_VERSION=3.12`; all product images derive from it.
6. **Policy-as-code synchronization.** Canonical policies live in `shared/shared-contracts/policies/`; `make sync-policy` copies them into `tool-gateway`, `platform-gateway`, and the GitOps base overlay. Consumers never author their own copy.
7. **Version lockstep enforcement.** `make validate-version` runs `shared/shared-contracts/scripts/validate_version.py` to assert the root `VERSION` file matches every product's declared version.
8. **Secret vocabulary lockstep.** `make validate-secret-vocabulary` asserts consistency of secret literals across `agent-platform`, `tool-gateway`, and `skills-hub`.
9. **Password policy contract.** `make validate-password-policy` validates the password-strength contract and pins the connector floor to it (SPEC-062 R-2).
10. **GitOps overlay validation.** `make overlays` runs `kustomize build --load-restrictor LoadRestrictionsNone` on every overlay; failures block the verify gate.
11. **Dashboard validation.** `make validate-dashboards` runs `shared/platform-ops/dashboards/validate_dashboards.py` to parse envelopes, panels, and metric references offline (SPEC-065 R-3).
12. **Portal SPA build separate from Python suite.** `make portal-test` runs `make -C products/operator-portal test` (Vitest) and `make -C products/operator-portal web-build` (typechecked production build); it is not part of `make test` because the portal is not a uv product.
13. **Verification gate.** `make verify` chains `test`, `overlays`, `validate-dashboards`, `validate-policy`, `validate-policy-scenarios`, `validate-version`, `validate-secret-vocabulary`, `validate-password-policy`, `secret-delivery-demo`, `portal-test`, and `execution-failure-test` — the documented pre-commit/pre-push gate.
14. **Deploy pipeline.** `make deploy` delegates to `shared/platform-ops/gitops/dev-k8s/deploy.sh`; `make deploy-samples` / `undeploy-samples` manage tutorial skills out-of-band from the base overlay (SPEC-050 R-11). `make e2e` runs the full demo suite against a deployed cluster.

## Conventions and constraints

- **GNU make required.** The root Makefile header states `Requires GNU make (default on macOS and Linux)`.
- **No `latest` tags.** `mk/defaults.mk` comments explicitly say pinned values are defaults for reproducible builds — never `latest`.
- **Command-line overrides always win.** `mk/defaults.mk` documents that all values use `?=` so `make build IMAGE_PLATFORM=linux/arm64` etc. override defaults.
- **New Python services must register themselves.** Adding a service requires adding it to `PYTHON_PRODUCTS` and `IMAGE_PRODUCTS` in the root `Makefile` plus creating a product directory with `pyproject.toml`, `uv.lock`, `.python-version`, `Dockerfile`, and a thin `Makefile` that includes `../../mk/image.mk` and `../../mk/python.mk`.
- **Images are tagged with the coordinated `IMAGE_TAG`.** The root `make build` passes `IMAGE_TAG=$(IMAGE_TAG)` to each product; standalone product builds fall back to `$(shell git rev-parse --short HEAD 2>/dev/null || echo dev)`.
- **Policy bundles are authored once and copied.** `make sync-policy` is the only supported way to propagate canonical policies; consumers do not maintain independent copies.
- **Platform release version is centralized.** `VERSION` is the single source of truth; `make validate-version` enforces lockstep between `VERSION`, every product, and the portal.
- **Samples are excluded from the base overlay.** `make deploy` never names a sample; samples are installed separately via `make deploy-samples` and `make deploy-sample-app` (SPEC-050 R-11, SPEC-059 R-6).
- **CI is expected to run `make verify`.** The root Makefile declares `make verify` is the pre-commit/pre-push gate and runs the same checks locally and under any CI.