---
kind: build_system
name: Luban Platform Build System — Multi-Product Makefile + Docker + Kustomize
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
    - products/platform-gateway/Makefile
    - products/platform-gateway/Dockerfile
    - products/operator-portal/Makefile
    - shared/platform-ops/gitops/dev-k8s/kustomization.yaml
    - shared/shared-contracts/scripts/validate_version.py
    - shared/shared-contracts/scripts/validate_policy.py
    - shared/shared-contracts/scripts/validate_secret_vocabulary.py
    - shared/shared-contracts/scripts/validate_password_policy.py
---

# Build System

## Approach

The Luban platform is a monorepo of nine Python services plus an operator-portal SPA, built through a layered system:

1. GNU Make at the repository root (`Makefile`) orchestrates cross-cutting concerns (sync, test, lint, image build, policy sync, overlay validation, e2e).
2. Shared Makefile fragments under `mk/` provide reusable targets for Python products and container images.
3. Per-product `Dockerfile`s (one per service) are built with `docker build`, using a shared base image.
4. Kustomize overlays under `shared/platform-ops/gitops/` render Kubernetes manifests; they are validated by `make overlays` but not applied directly from the repo.
5. uv is the Python dependency manager and runner — every product has its own `pyproject.toml` + `uv.lock`, installed via `uv sync --frozen`.
6. npm/Vitest builds the operator-portal SPA (`products/operator-portal/web-ui/app`).

There is no CI configuration in this snapshot (`.github/` contains only issue templates and a PR template); the root `Makefile` is explicitly forge-agnostic: "`make verify` is the pre-commit/pre-push gate and runs the same checks locally and under any CI".

## Key Files

- `Makefile` — root orchestrator; defines `PYTHON_PRODUCTS`, `IMAGE_PRODUCTS`, `OVERLAYS`, coordinated `IMAGE_TAG` computation, and the `verify` gate.
- `mk/defaults.mk` — single source of truth for overridable defaults (`IMAGE_PLATFORM`, `REGISTRY`, `BASE_UV_*`, `AUTO_LOAD_KIND`, `KIND_CLUSTER_NAME`).
- `mk/image.mk` — shared `build` / `push` / `lint` targets for container images; requires the including Makefile to set `IMAGE_NAME`.
- `mk/python.mk` — shared `sync` / `test` targets running `uv sync --frozen` then `pytest` with OTLP exporters disabled.
- `VERSION` — single source of truth for the platform release version (semver), consumed as `PLATFORM_VERSION`.
- `shared/base-images/base-uv/Dockerfile` — shared base image built by `make base-images`.
- `shared/platform-ops/gitops/dev-k8s/` — Kustomize base overlay containing all service deployments/services/configmaps.
- Per-product `Makefile` (minimal): sets `IMAGE_NAME` and includes `../../mk/image.mk` and `../../mk/python.mk`.
- Per-product `Dockerfile`: multi-stage or single-stage, always `FROM luban-aiops/base-uv:al2023`, copies `.python-version pyproject.toml uv.lock src`, runs `uv sync --frozen --no-dev`, exposes `8000`, CMD via `uv run <entrypoint>`.
- `shared/shared-contracts/scripts/` — scripts invoked by root Makefile targets (`validate_policy.py`, `validate_version.py`, `validate_secret_vocabulary.py`, `validate_password_policy.py`, `policy_diff.py`, `validate_policy_scenarios.py`).

## Architecture and Conventions

### Product taxonomy
Products are classified into two lists at the top of the root `Makefile`:
- `PYTHON_PRODUCTS := agent-platform audit-service execution-runtime identity-broker incident-service platform-gateway skills-hub tool-gateway`
- `IMAGE_PRODUCTS := agent-platform audit-service execution-runtime identity-broker incident-service platform-gateway skills-hub tool-gateway operator-portal`

The root `sync`, `test`, `lint`, `build`, `push` targets iterate these lists and delegate to `make -C products/<name> <target>`.

### Image tagging
Coordinated tags are computed once by the root Makefile: `<semver>-<prefix>[-<profile>]-<gitsha>` for clean trees, `<semver>-<prefix>[-<profile>]-<gitsha>-dirty-<timestamp>` for dirty trees. The tag is written to `shared/platform-ops/gitops/dev-k8s/.images.env` so `make deploy` consumes the exact images that were built. Individual product `Dockerfile`s do not compute tags themselves — they receive `IMAGE_TAG` from the root.

### Base image strategy
All Python services derive from `luban-aiops/base-uv:al2023`, built from `shared/base-images/base-uv/Dockerfile` with pinned `BASE_UV_UV_VERSION=0.12.1` and `BASE_UV_PYTHON_VERSION=3.12` (from `mk/defaults.mk`). The base image is built first (`make base-images`), then all product images depend on it.

### Dependency management
Each Python product pins dependencies via `uv.lock`; `make sync` and `make test` both invoke `uv sync --frozen`. Tests run with `OTEL_TRACES_EXPORTER=none OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none` so OpenTelemetry SDK stays active for tracing tests without emitting noise.

### Policy contracts
Canonical policy bundles live in `shared/shared-contracts/policies/` and are copied into consumers by `make sync-policy` into `products/tool-gateway/src/tool_gateway/policies/`, `products/platform-gateway/src/platform_gateway/policies/`, and `shared/platform-ops/gitops/dev-k8s/base/shared/policy.yaml`. Validation uses scripts under `shared/shared-contracts/scripts/`.

### GitOps overlays
Overlays under `shared/platform-ops/gitops/runtime-profiles/{default,mutating-dev,browser-dev}` are validated by `make overlays` via `kustomize build --load-restrictor LoadRestrictionsNone`. The dev deployment target is `dev-k8s`; samples are deployed out-of-band via `make deploy-samples` so the base overlay never names a sample (per SPEC-050 R-11).

### Operator portal (non-Python)
The operator-portal is a Vite + Vitest SPA. Its `Makefile` overrides `IMAGE_CONTEXT := ../..` and `IMAGE_DOCKERFILE := Dockerfile` because the multi-stage Dockerfile needs the root `VERSION` file plus the `web-ui/app` project. `make verify` delegates to `products/operator-portal/test` (vitest) and `products/operator-portal/web-build` (tsc + vite build) — SPEC-063 R-8c requires the full suite and production build with no skip toggle.

### Verification gate
`make verify` aggregates: product tests, kustomize overlay renders, dashboard validation, policy bundle validation, policy scenario evaluation, version lockstep validation, secret vocabulary validation, password policy validation, secret-delivery demo, portal unit/build, and execution failure test. It is intended as the pre-commit/pre-push gate.

## Conventions and Constraints

- Single source of truth for versions: `VERSION` at the repo root is the platform semver; `make validate-version` enforces lockstep between `VERSION`, each product's declared version, and the portal (via `shared/shared-contracts/scripts/validate_version.py`).
- Pinned base image versions: `mk/defaults.mk` pins `BASE_UV_UV_VERSION=0.12.1`, `BASE_UV_PYTHON_VERSION=3.12`, `BASE_UV_TAG=al2023`; comments state "never `latest`".
- Frozen Python installs: All `uv sync` invocations use `--frozen`, enforcing that `uv.lock` is authoritative.
- Image platform default: `IMAGE_PLATFORM ?= linux/amd64`; `linux/arm64` is documented for native local/kind builds on arm64 hosts.
- Registry re-tag pattern: When `REGISTRY` is set, images are tagged as `$(REGISTRY)/luban-aiops/$(IMAGE_NAME):$(IMAGE_TAG)` before push; when unset, images stay local as `luban-aiops/<name>:<tag>`.
- Auto-load kind integration: `AUTO_LOAD_KIND=true` after `make build` loads all eight service images plus `web-ui` into the named kind cluster (`KIND_CLUSTER_NAME` required).
- Policy synchronization rule: Canonical policies in `shared/shared-contracts/policies/` must be copied to all consumer locations via `make sync-policy`; there is no runtime discovery of policy files.
- Dashboard validation rule: Dashboards under `shared/platform-ops/dashboards/` are validated offline by `make validate-dashboards` (SPEC-065 R-3) — parse, envelope/panel schema, and every metric reference must resolve to an emitted `OTEL_MIRROR_FAMILIES` stream.
- Portal build rule: The operator-portal SPA unit suite and typechecked production build are mandatory parts of `make verify` (SPEC-063 R-8c); zero-test green paths are rejected.
- Sample isolation rule: Samples are kept out of the base overlay and deployed separately via `make deploy-samples` (SPEC-050 R-11); `make deploy` never names a sample.
- Cross-cutting scripts location: Validation and diffing logic lives in `shared/shared-contracts/scripts/` and is invoked from the root Makefile rather than duplicated per product.