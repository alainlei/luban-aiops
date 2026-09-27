---
kind: build_system
name: Coordinated Makefile + Docker Build System with GitOps Overlays
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
    - products/agent-platform/pyproject.toml
    - products/operator-portal/Dockerfile
    - shared/platform-ops/gitops/dev-k8s/kustomization.yaml
    - shared/platform-ops/gitops/dev-k8s/deploy.sh
    - shared/platform-ops/gitops/runtime-profiles/default/kustomization.yaml
    - shared/platform-ops/gitops/runtime-profiles/browser-dev/kustomization.yaml
    - shared/platform-ops/gitops/runtime-profiles/mutating-dev/kustomization.yaml
    - shared/shared-contracts/scripts/validate_version.py
    - shared/shared-contracts/scripts/validate_policy.py
    - shared/shared-contracts/scripts/validate_policy_scenarios.py
    - shared/shared-contracts/scripts/validate_secret_vocabulary.py
    - shared/shared-contracts/scripts/validate_password_policy.py
---

## What system/approach is used

The repository uses a **Makefile-driven, multi-product build orchestration** layered on top of per-product `Dockerfile` builds and `uv`-managed Python dependencies. A root `Makefile` delegates to shared fragments under `mk/` (`defaults.mk`, `image.mk`, `python.mk`) so that every product in `products/<name>/` exposes the same surface: `sync`, `test`, `build`, `push`, `lint`. Container images are built with `docker build --platform $(IMAGE_PLATFORM)` against a pinned `luban-aiops/base-uv:al2023` base image (Python 3.12 + uv 0.12.1). The operator portal (`operator-portal`) is an exception — it is a Node/Vite SPA built via a two-stage Dockerfile using `node:22-alpine` and served by `nginxinc/nginx-unprivileged:1.27-alpine`.

Deployment is GitOps-based: `shared/platform-ops/gitops/dev-k8s/` holds Kustomize overlays (`base/`, plus `runtime-profiles/default|mutating-dev|browser-dev`), rendered through `kustomize build --load-restrictor LoadRestrictionsNone`. A coordinated deploy script at `shared/platform-ops/gitops/dev-k8s/deploy.sh` consumes an `.images.env` state file written by `make build`.

## Key files and packages

- Root orchestrator: `Makefile` — defines `PYTHON_PRODUCTS`, `IMAGE_PRODUCTS`, `OVERLAYS`, coordinated `build`/`push`/`deploy`/`verify` targets, policy sync, version validation, e2e demo runner.
- Shared build fragments:
  - `mk/defaults.mk` — single source of overridable defaults (`IMAGE_PLATFORM`, `REGISTRY`, `BASE_UV_*`, `AUTO_LOAD_KIND`).
  - `mk/image.mk` — generic `build`/`push`/`lint` Docker targets; computes `IMAGE_REF` from `IMAGE_NAME` and `IMAGE_TAG`.
  - `mk/python.mk` — `sync`/`test` targets running `uv sync --frozen` and `pytest` with OTLP exporters disabled.
- Per-product entry points: each `products/<name>/Makefile` sets `IMAGE_NAME` and includes both `../../mk/image.mk` and `../../mk/python.mk`; each `products/<name>/Dockerfile` copies `pyproject.toml` + `uv.lock` and runs `uv sync --frozen --no-dev`.
- Versioning: root `VERSION` file is the single source of truth for platform release semver; `make validate-version` enforces lockstep across products and the portal.
- Policy contracts: canonical bundles live in `shared/shared-contracts/policies/`; `make sync-policy` copies them into `tool-gateway`, `platform-gateway`, and the dev overlay.
- GitOps overlays: `shared/platform-ops/gitops/dev-k8s/` (base manifests) plus `runtime-profiles/*` overlays; `make overlays` validates all via `kustomize build`.
- E2E / acceptance: `shared/platform-ops/e2e/` scripts and `samples/acme-admin/` demo suite invoked via `make e2e`.

## Architecture and conventions

1. **Single-image-tag coordination.** `make build` computes one `IMAGE_TAG` (semver + optional prefix/profile + git sha + `-dirty-<timestamp>` if uncommitted changes exist) and passes it to every product's `make build IMAGE_TAG=...`. After building, it writes `shared/platform-ops/gitops/dev-k8s/.images.env` mapping each service name to its `luban-aiops/<service>:<tag>`, which `deploy.sh` consumes.
2. **Per-product isolation with shared tooling.** Each product has its own `pyproject.toml` + `uv.lock`, `tests/`, and `Dockerfile`, but shares dependency installation, testing, linting, and image-building logic via `include ../../mk/*.mk`. Command-line overrides always win (all defaults use `?=`).
3. **Base image pinning.** All Python services derive from `luban-aiops/base-uv:al2023`, built once by `make base-images` with pinned `UV_VERSION=0.12.1` and `PYTHON_VERSION=3.12`. No `latest` tags are used anywhere in the build.
4. **Multi-stage portal build.** The operator portal is the only non-Python product: a Node build stage compiles the Vite/React SPA (injecting `PLATFORM_VERSION` from the root `VERSION` file) and an nginx runtime stage serves the hashed bundle with `/api/` proxied to the gateway.
5. **Verification gate.** `make verify` aggregates `test`, `overlays`, `validate-policy`, `validate-policy-scenarios`, `validate-version`, `validate-secret-vocabulary`, `validate-password-policy`, `secret-delivery-demo`, `portal-test`, and `execution-failure-test`. It is documented as the pre-commit/pre-push gate and runs identically locally and in CI.
6. **Policy-as-code distribution.** Policy bundles are authored once in `shared/shared-contracts/policies/` and copied to consumers via `make sync-policy`; schema validation and scenario evaluation run via scripts under `shared/shared-contracts/scripts/`.
7. **Kind integration.** When `AUTO_LOAD_KIND=true` and `KIND_CLUSTER_NAME` is set, `make build` automatically loads all nine images into the named kind cluster after building.

## Conventions and constraints

- **Every Python product must expose `sync` and `test`** via inclusion of `mk/python.mk`; tests run with `uv sync --frozen` and pytest, with OpenTelemetry exporters disabled to avoid OTLP noise during test runs.
- **Every containerized product must expose `build` and `push`** via inclusion of `mk/image.mk`; images are tagged `luban-aiops/<IMAGE_NAME>:<IMAGE_TAG>` and optionally re-tagged to `$(REGISTRY)/luban-aiops/<IMAGE_NAME>:<IMAGE_TAG>` when `REGISTRY` is set.
- **Image platforms are pinned per-invocation** via `IMAGE_PLATFORM` (default `linux/amd64`); cross-compilation to `linux/arm64` is supported for local ARM hosts.
- **Version lockstep is enforced**: `make validate-version` checks that the root `VERSION` semver matches every product's declared version and the portal's injected version; this is part of the `verify` gate.
- **Secret vocabulary and password-policy contracts are validated centrally** via `make validate-secret-vocabulary` and `make validate-password-policy`, ensuring agent-platform/tool-gateway/skills-hub share the same secret literal list and that tool-gateway pins its connector floor to the canonical password policy.
- **GitOps overlays must render cleanly**: `make overlays` runs `kustomize build` against every overlay in `OVERLAYS` and fails the gate on any render error.
- **Samples are kept out-of-band from the base overlay** (per SPEC-050 R-11): `make deploy` never names sample resources; samples are installed separately via `make deploy-samples` and the acme-admin app via `make deploy-sample-app`.
- **Portal unit tests and production build are mandatory** in the verification gate (`make portal-test` runs Vitest and the Vite production build); zero tests would fail the gate, so no skip path exists.