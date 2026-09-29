---
kind: build_system
name: Coordinated Makefile + Kustomize Build & Release Pipeline
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
    - shared/platform-ops/gitops/dev-k8s/kustomization.yaml
    - shared/platform-ops/gitops/dev-k8s/deploy.sh
    - shared/shared-contracts/policies/policy-default.yaml
    - shared/shared-contracts/policies/password-policy.yaml
---

## What system/approach is used

The repository uses a **GNU make-driven, forge-agnostic build orchestration** layered on top of per-product `uv` (Python) and `npm`/Vite (SPA) toolchains, with container images built via Docker and Kubernetes manifests managed through **Kustomize overlays**. There are no CI workflow files checked into the repo; the root `Makefile` explicitly states it is "forge-agnostic" and that `make verify` is intended to run identically locally and under any CI. The coordinated release flow is driven by a single source-of-truth version file (`VERSION`) that pins every product image tag.

## Key files and packages

- **Root orchestrator**: `Makefile` — defines cross-cutting targets (`sync`, `test`, `build`, `push`, `verify`, `deploy`, `e2e`, policy/secret/version validation), enumerates all Python and image products, computes a coordinated `IMAGE_TAG`, writes `.images.env` for deployment, and delegates per-product work.
- **Shared fragments**:
  - `mk/defaults.mk` — single source of overridable defaults (`IMAGE_PLATFORM`, `REGISTRY`, `BASE_UV_*`, `AUTO_LOAD_KIND`, `IMAGE_TAG_PREFIX`).
  - `mk/image.mk` — shared `build` / `push` / `lint` Docker targets used by every product Makefile; resolves `IMAGE_REF` from `IMAGE_NAME` + `IMAGE_TAG`.
  - `mk/python.mk` — shared `sync` (`uv sync --frozen`) and `test` (`uv run pytest` with OTel exporters disabled).
- **Per-product Makefiles** — tiny wrappers that set `IMAGE_NAME` and include the shared fragments (e.g. `products/agent-platform/Makefile`, `products/operator-portal/Makefile`).
- **Base image**: `shared/base-images/base-uv/Dockerfile` — pinned `al2023` + `uv` + `python:3.12` base image built by `make base-images`.
- **Kubernetes/GitOps**: `shared/platform-ops/gitops/dev-k8s/` (base overlay), `runtime-profiles/{default,mutating-dev,browser-dev}/` (profile overlays), rendered via `kustomize build --load-restrictor LoadRestrictionsNone` in `make overlays` and deployed through `shared/platform-ops/gitops/dev-k8s/deploy.sh`.
- **Version pinning**: `VERSION` (semver, e.g. `0.44.0`) — consumed by root `PLATFORM_VERSION`, injected into the operator portal SPA at build time, and enforced against product versions by `make validate-version`.
- **Policy contracts**: canonical bundles in `shared/shared-contracts/policies/` synced to consumers via `make sync-policy`; validated by scripts under `shared/shared-contracts/scripts/`.

## Architecture and conventions

### Product enumeration model
Products are declared as lists in the root `Makefile`:
- `PYTHON_PRODUCTS` — eight Python services that get `uv sync` / `pytest`.
- `IMAGE_PRODUCTS` — nine services plus `operator-portal` that produce Docker images.
Each product's own `Makefile` only sets `IMAGE_NAME` and includes `../../mk/image.mk` and/or `../../mk/python.mk`; there is no per-product build logic duplicated.

### Coordinated image tagging
The root `make build` computes one `IMAGE_TAG` once using this formula:
`<PLATFORM_VERSION>-<IMAGE_TAG_PREFIX><-IMAGE_TAG_PROFILE>-<git-sha>[-dirty-<timestamp>]`
It then builds every product image with that tag and writes `shared/platform-ops/gitops/dev-k8s/.images.env` containing `IMAGE_TAG` plus the full `luban-aiops/<service>:<tag>` reference for each service. The deploy step reads this file so the GitOps overlay always references the exact images just built.

### Base image strategy
A shared `base-uv` image is built first (`make base-images`) using pinned `BASE_UV_UV_VERSION=0.12.1` and `BASE_UV_PYTHON_VERSION=3.12` on `al2023`. All product Dockerfiles inherit from this base, ensuring reproducible Python environments across the platform.

### Multi-stage portal build
The operator portal is an npm/Vite SPA (not a uv product). Its Makefile overrides `IMAGE_CONTEXT := ../..` and `IMAGE_DOCKERFILE := Dockerfile` so the multi-stage Dockerfile can access both the root `VERSION` file and `web-ui/app/`. Unit tests run via `npm test` (Vitest) and production build via `npm run build` (tsc + vite); `make verify` runs both and intentionally has no zero-test green path.

### Policy and contract synchronization
Canonical policy YAMLs live in `shared/shared-contracts/policies/` and are copied into consumer locations (`tool-gateway`, `platform-gateway`, dev-k8s base) via `make sync-policy`. Password-strength policy is similarly authored once and synced to `tool-gateway` (SPEC-062 R-2). Validation scripts enforce JSON-schema conformance and scenario expectations against both engines.

### Secret vocabulary lockstep
`make validate-secret-vocabulary` enforces that secret-literal declarations stay synchronized between `agent-platform`, `tool-gateway`, and `skills-hub` via a shared script.

### Deployment model
`make deploy` invokes `shared/platform-ops/gitops/dev-k8s/deploy.sh`, which applies the `dev-k8s` Kustomize overlay. Samples (acme-admin app, skill demos) are installed out-of-band via `make deploy-samples` so they never appear in the base overlay (per SPEC-050 R-11). Runtime profiles (`default`, `mutating-dev`, `browser-dev`) are selectable overlays applied alongside the base.

### Verification gate
`make verify` is the pre-commit/pre-push gate and composes:
- Per-product `test` suites
- `overlays` (kustomize build check)
- `validate-policy`, `validate-policy-scenarios`
- `validate-version`, `validate-secret-vocabulary`, `validate-password-policy`
- `secret-delivery-demo` (local handoff proof)
- `portal-test` (Vitest + production build)
- `execution-failure-test` (crash-safety proof with disposable Postgres)

## Conventions and constraints

- **Forge-agnostic CI**: The root `Makefile` declares itself forge-agnostic and expects CI to invoke `make verify`; no GitHub Actions or other CI YAML exists in the repo.
- **Single version source**: `VERSION` is the authoritative semver; `make validate-version` enforces lockstep between `VERSION`, product versions, and the portal build.
- **Frozen dependencies**: Python products use `uv sync --frozen`, pinning installs to `uv.lock`.
- **Pinned base images**: Base image tags and tool versions (`BASE_UV_UV_VERSION`, `BASE_UV_PYTHON_VERSION`) are pinned constants — never `latest`.
- **Image naming convention**: All images follow `luban-aiops/<service>:<coordinated-tag>`; optional `REGISTRY` re-tags them before push.
- **Cross-platform builds**: `IMAGE_PLATFORM` defaults to `linux/amd64` but can be overridden (e.g. `linux/arm64` for native kind builds).
- **Kind auto-loading**: `AUTO_LOAD_KIND=true` plus `KIND_CLUSTER_NAME` causes `make build` to load all images into the named cluster after building.
- **Samples isolation**: Tutorial samples and the acme-admin sample app are deployed separately from the base overlay; `make deploy` never names a sample (enforced by spec).
- **No skip gates**: Portal Vitest suite fails on zero tests, and the verification gate accepts no integration skip toggle — a release pass requires all checks to succeed.