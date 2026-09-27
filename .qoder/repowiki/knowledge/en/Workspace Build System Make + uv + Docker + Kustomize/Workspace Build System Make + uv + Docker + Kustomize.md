---
kind: build_system
name: 'Workspace Build System: Make + uv + Docker + Kustomize'
category: build_system
scope:
    - '**'
source_files:
    - Makefile
    - mk/defaults.mk
    - mk/image.mk
    - mk/python.mk
    - products/agent-platform/Makefile
    - products/agent-platform/Dockerfile
    - products/operator-portal/Makefile
    - products/operator-portal/Dockerfile
    - shared/base-images/base-uv/Dockerfile
    - shared/platform-ops/gitops/dev-k8s/kustomization.yaml
    - shared/platform-ops/gitops/dev-k8s/deploy.sh
    - shared/shared-contracts/scripts/validate_version.py
    - shared/shared-contracts/scripts/validate_secret_vocabulary.py
    - shared/shared-contracts/scripts/validate_password_policy.py
    - shared/shared-contracts/scripts/validate_policy_scenarios.py
    - shared/shared-contracts/scripts/policy_diff.py
    - VERSION
---

# Build & Artifact Management

## Approach

The Luban platform is a Python monorepo built with a layered toolchain:

- **GNU make** at the workspace root orchestrates cross-cutting concerns (image build, policy sync, overlay validation, e2e demos).
- **uv** is the per-product dependency manager and test runner (`pyproject.toml` + `uv.lock`, frozen installs).
- **Docker** builds container images for every service; a shared base image `luban-aiops/base-uv` (AlmaLinux 2023 + pinned uv/python) is built first.
- **kustomize** renders GitOps overlays under `shared/platform-ops/gitops/` as part of verification.
- The operator portal is a Vite/React SPA built via npm in a multi-stage Dockerfile served by nginx.

There is no CI configuration file in this repository snapshot — the root `Makefile` is explicitly forge-agnostic and intended to be the pre-commit/pre-push gate that runs identically locally and in CI.

## Key Files

- `Makefile` — workspace master entry point. Declares `PYTHON_PRODUCTS`, `IMAGE_PRODUCTS`, coordinated `IMAGE_TAG`, and targets `sync`, `test`, `lint`, `build`, `push`, `overlays`, `verify`, `deploy`, `e2e`, plus policy/secret/version validators.
- `mk/defaults.mk` — single source of overridable defaults (`IMAGE_PLATFORM`, `IMAGE_TAG_PREFIX`, `IMAGE_TAG_PROFILE`, `REGISTRY`, `AUTO_LOAD_KIND`, `BASE_UV_*`). All values use `?=`, so command-line overrides always win.
- `mk/image.mk` — shared container-image fragment defining `help`, `build`, `push`, `lint` (hadolint with docker-run fallback). Includes `defaults.mk` relative to itself so standalone product invocations resolve the same config.
- `mk/python.mk` — shared `sync` / `test` targets using `uv sync --frozen` and `uv run pytest` with OTLP exporters disabled during tests.
- `products/<service>/Makefile` — thin wrapper setting `IMAGE_NAME` and including both `../../mk/image.mk` and `../../mk/python.mk`. Eight Python services follow this pattern.
- `products/operator-portal/Dockerfile` — multi-stage build (node:22-alpine → nginxinc/nginx-unprivileged:1.27-alpine), reads root `VERSION` to inject `PLATFORM_VERSION` at build time.
- `products/operator-portal/Makefile` — defines `test` (vitest) and `web-build` (tsc + vite build); excluded from `PYTHON_PRODUCTS` because it has no uv suite.
- `shared/base-images/base-uv/Dockerfile` — shared base image built by `make base-images`.
- `shared/platform-ops/gitops/dev-k8s/` — kustomize base overlay with per-service deployment/service/env manifests.
- `shared/platform-ops/gitops/runtime-profiles/{default,mutating-dev,browser-dev}/` — runtime profile overlays.
- `shared/shared-contracts/scripts/validate_version.py`, `validate_secret_vocabulary.py`, `validate_password_policy.py`, `validate_policy_scenarios.py`, `policy_diff.py` — contract validation scripts invoked from the root Makefile.
- `VERSION` — single source of truth for the platform semver; propagated into image tags and the portal build.

## Architecture and Conventions

### Product layout
Every Python product under `products/<name>/` follows the same shape: `src/<package>/`, `tests/`, `.python-version`, `Dockerfile`, `Makefile`, `pyproject.toml`, `uv.lock`. The root `Makefile` enumerates them in `PYTHON_PRODUCTS` and `IMAGE_PRODUCTS`; adding a new service requires updating those lists.

### Image tagging
Coordinated tag computation lives in the root `Makefile`:
```
<semver>-<prefix>[-<profile>]-<gitsha>[-dirty-<timestamp>]
```
The semver comes from `VERSION`; prefix/profile come from `IMAGE_TAG_PREFIX` / `IMAGE_TAG_PROFILE`. A clean tree gets `<version>-<sha>`; a dirty tree appends `-dirty-<timestamp>`. The computed tag is written to `shared/platform-ops/gitops/dev-k8s/.images.env` alongside per-service image name variables consumed by `deploy.sh`.

### Base image strategy
All Python services derive from `luban-aiops/base-uv:al2023`, which is built once by `make base-images` with pinned `BASE_UV_UV_VERSION=0.12.1` and `BASE_UV_PYTHON_VERSION=3.12`. Each service's Dockerfile then does `uv sync --frozen --no-dev` against its own lockfile.

### Policy contracts
Canonical policy bundles live in `shared/shared-contracts/policies/` and are copied to consumers via `make sync-policy` (tool-gateway, platform-gateway, dev-k8s base). `make validate-policy` and `make validate-policy-scenarios` enforce schema and scenario expectations across both engines.

### Version lockstep
`make validate-version` calls `shared/shared-contracts/scripts/validate_version.py` to assert that the root `VERSION` file matches every product version — enforced as part of `make verify`.

### Secret vocabulary lockstep
`make validate-secret-vocabulary` asserts that secret literal declarations stay in sync between agent-platform, tool-gateway, and skills-hub.

### Portal build exclusion
The operator portal is not a uv product. Its unit tests and production build are gated through `make portal-test`, which is included in `make verify`. The comment documents SPEC-063 R-8c: Vitest fails on zero tests, so there is no skip path.

### Deployment flow
`make deploy` delegates to `shared/platform-ops/gitops/dev-k8s/deploy.sh`, which consumes the `.images.env` state produced by `make build`. Samples are installed out-of-band via `make deploy-samples` (SPEC-050 R-11 keeps samples out of the base overlay).

### E2E and failure proofs
`make e2e` runs demo scripts against a deployed cluster after port-forwarding gateway and identity-service. `make execution-failure-test` proves crash safety with disposable Postgres and independent processes.

## Conventions and Constraints

- **Per-product Makefiles must include both `mk/image.mk` and `mk/python.mk`** and set `IMAGE_NAME`. Observed in all eight Python products.
- **Dependencies are locked**: `uv sync --frozen` is used everywhere; no transitive drift is allowed.
- **Image builds target `linux/amd64` by default** (`IMAGE_PLATFORM ?= linux/amd64` in `mk/defaults.mk`); override via `make build IMAGE_PLATFORM=linux/arm64`.
- **Images are tagged `luban-aiops/<name>:<tag>` locally**; when `REGISTRY` is set, they are re-tagged to `$(REGISTRY)/luban-aiops/<name>:<tag>` and pushed.
- **Dockerfile lint uses hadolint if available**, falling back to `docker run --rm -i hadolint/hadolint`; otherwise it skips with a message.
- **`make verify` is the canonical gate**: it runs `test`, `overlays`, `validate-policy`, `validate-policy-scenarios`, `validate-version`, `validate-secret-vocabulary`, `validate-password-policy`, `secret-delivery-demo`, `portal-test`, and `execution-failure-test`. It is described as the pre-commit/pre-push gate.
- **Policy bundles are single-source-of-truth**: `sync-policy` copies the canonical bundle to every consumer; consumers do not author their own copy.
- **Samples are never named by the base overlay** (SPEC-050 R-11): they are deployed separately via `make deploy-samples` and `make deploy-sample-app`.
- **Portal tests cannot be skipped**: the Makefile comment states Vitest fails on zero tests and no integration skip toggle is accepted as a release pass (SPEC-063 R-8c).
- **Base image versions are pinned, never `latest`**: documented in `mk/defaults.mk` comments and reflected in `BASE_UV_IMAGE=luban-aiops/base-uv` with tag `al2023`.
- **Cross-compilation**: supported via `IMAGE_PLATFORM`; the root `base-images` target passes `--platform $(IMAGE_PLATFORM)` to `docker build`.