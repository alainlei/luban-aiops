---
kind: build_system
name: Build System — Makefile-driven Multi-Product Workspace with uv, Docker, and Kustomize
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
    - products/operator-portal/Makefile
    - shared/platform-ops/gitops
    - shared/platform-ops/dashboards/validate_dashboards.py
    - shared/shared-contracts/scripts/validate_version.py
---

# Build System

## Approach

The Luban workspace is built entirely through **GNU make** orchestration layered on top of three per-product toolchains:

- **Python products** (agent-platform, audit-service, execution-runtime, identity-broker, incident-service, platform-gateway, skills-hub, tool-gateway) use `uv` for dependency resolution (`uv sync --frozen`) and `pytest` for tests.
- **operator-portal** is a Vite + Vitest SPA served by nginx; its build runs via `npm` under `web-ui/app`.
- **Container images** are built with `docker build`, using a shared multi-stage base image `luban-aiops/base-uv` (Al2023 + pinned Python/uv versions).
- **Kubernetes deployment** uses `kustomize` over overlays under `shared/platform-ops/gitops`, invoked through `make overlays` and `make deploy`.

There is no CI workflow file checked into this repo (`.github/workflows` does not exist); the root `Makefile` declares itself forge-agnostic and intended to run identically locally and under any CI (`Forge-agnostic: make verify is the pre-commit/pre-push gate`).

## Key Files

| File | Role |
|---|---|
| `Makefile` | Root orchestrator: product dispatch, coordinated image tagging, policy/dashboard/version validation, e2e demo runner |
| `mk/defaults.mk` | Single source of truth for overridable build settings (`IMAGE_PLATFORM`, `REGISTRY`, `BASE_UV_*`, `AUTO_LOAD_KIND`) |
| `mk/image.mk` | Shared `build` / `push` / `lint` targets for every product's Dockerfile |
| `mk/python.mk` | Shared `sync` / `test` targets wrapping `uv sync --frozen` + `uv run pytest` |
| `VERSION` | Single source of truth for the platform semver; consumed by root `IMAGE_TAG` computation and validated against each product |
| `products/<product>/Makefile` | Minimal product shim setting `IMAGE_NAME` and including the two shared fragments |
| `products/operator-portal/Makefile` | Extends `mk/image.mk` with `test` (vitest) and `web-build` (tsc/vite) |
| `shared/platform-ops/gitops/` | Kustomize overlays rendered by `make overlays` |
| `shared/platform-ops/dashboards/validate_dashboards.py` | Offline dashboard schema/metric-reference validator (SPEC-065 R-3) |
| `shared/shared-contracts/scripts/*` | Policy, version, secret-vocabulary, password-policy validators invoked from root targets |

## Architecture and Conventions

### Product layout
Every product under `products/` follows the same skeleton: `src/<name>/`, `tests/`, `.python-version`, `Dockerfile`, `Makefile`, `pyproject.toml`, `uv.lock`. The root `PYTHON_PRODUCTS` and `IMAGE_PRODUCTS` lists enumerate them explicitly; adding a new product requires registering it in both lists.

### Image naming and tagging
Images are always tagged `luban-aiops/<image-name>:<tag>` locally; when `REGISTRY` is set they are re-tagged as `<registry>/luban-aiops/<image-name>:<tag>` before push. The coordinated tag computed by the root Makefile has the form `<semver>-<prefix>[-<profile>]-<gitsha>` for clean trees and `<semver>-<prefix>[-<profile>]-<gitsha>-dirty-<timestamp>` for dirty trees. The `base-images/base-uv` image is built first and reused by all product Dockerfiles.

### Coordinated state
After `make build`, the root writes `shared/platform-ops/gitops/dev-k8s/.images.env` containing `IMAGE_TAG` plus one `*_IMAGE=luban-aiops/<service>:<tag>` variable per service. `make deploy` reads this file so the overlay and the images stay in lockstep.

### Version lockstep
`make validate-version` runs `shared/shared-contracts/scripts/validate_version.py` against the root `VERSION` file and every product's metadata, enforcing that the platform release version stays synchronized across the monorepo.

### Policy distribution
Canonical policy bundles live under `shared/shared-contracts/policies/`; `make sync-policy` copies them into `products/tool-gateway`, `products/platform-gateway`, and the GitOps base overlay. `make validate-policy` and `make validate-policy-scenarios` exercise JSON-schema validation and scenario evaluation against both engines.

### Verification gate
`make verify` aggregates the full pre-commit/pre-push check: product tests, kustomize overlay renders, dashboard validation, policy validation/scenarios, version lockstep, secret-vocabulary lockstep, password-policy validation, secret-delivery demo, operator-portal unit tests + production build, and the crash-safety execution failure test.

### E2E and samples
`make e2e` runs the scripts under `shared/platform-ops/e2e/` plus `samples/acme-admin/demo-suite.sh` against a deployed cluster. `make deploy-samples` installs tutorial skills out-of-band (per SPEC-050 R-11, samples must never appear in the base overlay). `make deploy-sample-app` builds and deploys the acme-admin sample application separately.

### Defaults vs. overrides
All tunables in `mk/defaults.mk` use `?=` so command-line flags win unconditionally (documented examples include `IMAGE_PLATFORM=linux/arm64`, `BASE_UV_UV_VERSION=0.13.0`). The defaults pin `IMAGE_PLATFORM=linux/amd64`, `BASE_UV_IMAGE=luban-aiops/base-uv`, `BASE_UV_TAG=al2023`, `BASE_UV_UV_VERSION=0.12.1`, `BASE_UV_PYTHON_VERSION=3.12`, and `IMAGE_TAG_PREFIX=dev-k8s`.

## Conventions and Constraints

- **Each product Makefile is a thin shim**: it only sets `IMAGE_NAME` (and optionally `IMAGE_CONTEXT` / `IMAGE_DOCKERFILE`) and includes `../../mk/image.mk` and `../../mk/python.mk`. No product contains duplicated build logic.
- **Dependency resolution is frozen**: `uv sync --frozen` is used everywhere; `uv.lock` is the authoritative manifest.
- **Image builds are reproducible**: base image tags and Python/uv versions are pinned in `mk/defaults.mk`; `latest` is explicitly disallowed by comment.
- **The root `verify` target is the single gate**: it combines product tests, overlay rendering, dashboard validation, policy checks, version lockstep, secret vocabulary, password policy, portal tests/build, secret-delivery demo, and execution failure proof — intended to be the pre-commit/pre-push hook in any forge.
- **Operator-portal is excluded from `make test`**: the root Makefile documents that the SPA is not a uv product and delegates to `make -C products/operator-portal test` + `web-build` instead (SPEC-063 R-8c).
- **Samples are kept out of the base overlay**: `make deploy` never names a sample; samples are installed via `make deploy-samples` or `make deploy-sample-app` (SPEC-050 R-11).
- **GitOps overlays are validated at build time**: `make overlays` runs `kustomize build --load-restrictor LoadRestrictionsNone` on every overlay listed in `OVERLAYS`.
- **Dashboard artifacts are validated offline**: `make validate-dashboards` parses the OpenObserve dashboards, validates envelope/panel schemas, and verifies every metric reference resolves to an emitted `OTEL_MIRROR_FAMILIES` stream (SPEC-065 R-3).
- **Version lockstep is enforced**: `make validate-version` fails if `VERSION` diverges from product metadata.
- **Policy bundles are single-source-of-truth**: canonical policies under `shared/shared-contracts/policies/` are copied to consumers via `make sync-policy`; consumers do not maintain independent copies.