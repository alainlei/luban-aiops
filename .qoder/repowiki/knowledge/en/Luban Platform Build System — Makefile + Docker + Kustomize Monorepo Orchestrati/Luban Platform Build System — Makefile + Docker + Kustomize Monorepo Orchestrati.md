---
kind: build_system
name: Luban Platform Build System — Makefile + Docker + Kustomize Monorepo Orchestration
category: build_system
scope:
    - '**'
source_files:
    - Makefile
    - mk/defaults.mk
    - mk/image.mk
    - mk/python.mk
    - shared/base-images/base-uv/Dockerfile
    - products/platform-gateway/Makefile
    - products/operator-portal/Makefile
    - products/platform-gateway/Dockerfile
    - shared/platform-ops/gitops/dev-k8s/kustomization.yaml
    - shared/platform-ops/gitops/dev-k8s/deploy.sh
    - VERSION
---

## Overview

The Luban platform is a Python/Node monorepo built with **GNU make** as the single entry point, layered on top of **uv** (Python dependency manager), **Docker** (container builds), and **kustomize** (GitOps overlays). There are no CI workflow files in `.github/workflows`; the root `Makefile` declares itself "forge-agnostic" and is intended to run identically locally and under any CI.

## Architecture

### Directory layout

- `mk/` — shared build fragments:
  - `defaults.mk` — single source of overridable defaults (`IMAGE_PLATFORM`, `BASE_UV_*`, `REGISTRY`, `AUTO_LOAD_KIND`, etc.) via `?=` so command-line overrides always win.
  - `image.mk` — shared `build` / `push` / `lint` targets for container images; requires each including Makefile to set `IMAGE_NAME` (and optionally `IMAGE_CONTEXT` / `IMAGE_DOCKERFILE`).
  - `python.mk` — shared `sync` / `test` targets that run `uv sync --frozen` then `pytest` with OTLP exporters disabled.
- `shared/base-images/base-uv/Dockerfile` — pinned Amazon Linux 2023 minimal image with a pinned `uv` version and non-root `app` user (uid 1000); product images inherit it.
- `shared/platform-ops/gitops/` — kustomize overlays (`dev-k8s`, `runtime-profiles/default|mutating-dev|browser-dev`) rendered by `make overlays`.
- `products/<name>/` — per-product directories, each with its own `Makefile`, `Dockerfile`, `pyproject.toml` + `uv.lock`, `.python-version`, and `tests/`.
- `VERSION` at repo root — single source of truth for the coordinated platform release tag.

### Product registration

The root `Makefile` explicitly enumerates products:

```make
PYTHON_PRODUCTS := agent-platform audit-service execution-runtime identity-broker incident-service platform-gateway skills-hub tool-gateway
IMAGE_PRODUCTS := agent-platform audit-service execution-runtime identity-broker incident-service platform-gateway skills-hub tool-gateway operator-portal
```

Every new service must be added to both lists. The operator-portal is an exception: it has no uv test suite but still ships a container image.

### Image tagging strategy

Coordinated tags are computed once by the root Makefile:

```
<semver>-<prefix>[-<profile>]-<gitsha>    (clean tree)
<semver>-<prefix>[-<profile>]-dirty-<timestamp>   (dirty tree)
```

The semver comes from `VERSION`; prefix/profile come from `IMAGE_TAG_PREFIX` / `IMAGE_TAG_PROFILE`. All nine backend services plus the web UI share this tag, written into `shared/platform-ops/gitops/dev-k8s/.images.env` after `make build` and consumed by `make deploy`.

### Per-product Makefiles

Each Python product's `Makefile` is only three lines:

```make
IMAGE_NAME := <service-name>
include ../../mk/image.mk
include ../../mk/python.mk
```

The operator-portal overrides `IMAGE_CONTEXT := ../..` and `IMAGE_DOCKERFILE := Dockerfile` because its multi-stage Dockerfile needs the root `VERSION` file and the Vite project under `web-ui/app`.

### Dockerfiles

All backend Dockerfiles follow the same pattern:

1. `FROM luban-aiops/base-uv:al2023`
2. Copy `.python-version`, `pyproject.toml`, `uv.lock`, `README.md`, and `src/`
3. `RUN uv sync --frozen --no-dev`
4. `EXPOSE 8000`
5. `CMD ["uv", "run", "<entrypoint>"]`

The operator-portal Dockerfile is separate and produces the SPA artifact served by nginx.

### Verification gate

`make verify` is the pre-commit/pre-push gate and chains:

```
test overlays validate-dashboards validate-policy validate-policy-scenarios validate-version validate-secret-vocabulary validate-password-policy secret-delivery-demo portal-test execution-failure-test
```

This runs every product's pytest suite, renders all kustomize overlays, validates OpenObserve dashboards (SPEC-065 R-3), validates policy bundles against JSON schema, validates versions across products, validates secret vocabulary lockstep, runs the acme-admin secret-delivery demo, runs the operator-portal Vitest suite + production build, and proves crash safety with disposable Postgres.

### Policy synchronization

Canonical policies live in `shared/shared-contracts/policies/` and are copied into consumers via `make sync-policy`:

- `policy-default.yaml` → `products/tool-gateway/.../policies/policy-default.yaml`, `products/platform-gateway/.../policies/policy-default.yaml`, `shared/platform-ops/gitops/dev-k8s/base/shared/policy.yaml`
- `password-policy.yaml` → `products/tool-gateway/.../policies/password-policy.yaml`

Validation scripts live under `shared/shared-contracts/scripts/`.

### Deployment

- `make deploy` delegates to `shared/platform-ops/gitops/dev-k8s/deploy.sh`.
- `make e2e` runs the scripted demos under `shared/platform-ops/e2e/` against a deployed cluster (requires port-forwards).
- `make deploy-samples` / `undeploy-samples` install/remove tutorial skills out-of-band from the base overlay (per SPEC-050 R-11).
- `make deploy-sample-app` deploys the acme-admin sample app using the coordinated `IMAGE_TAG`.

## Conventions and Constraints

- **Single orchestrator**: All cross-cutting build/test/lint logic lives in the root `Makefile` and `mk/*.mk`; product Makefiles only declare `IMAGE_NAME` and include the shared fragments.
- **Pinned dependencies everywhere**: Python deps via `uv sync --frozen` (lockfile enforced); base image uses pinned `UV_VERSION=0.46.0` and `PYTHON_VERSION=3.12`; no `latest` tags.
- **Coordinated image tag**: All images produced by `make build` share one tag derived from `VERSION` + git SHA; `make push` pushes them all.
- **Non-root containers**: Base image creates uid 1000 `app` user; product images inherit it.
- **Kustomize-only GitOps**: Overlays are validated by `make overlays` (`kustomize build --load-restrictor LoadRestrictionsNone`); deployments go through `deploy.sh`.
- **Version lockstep**: `make validate-version` enforces that the root `VERSION` matches every product's declared version (via `shared/shared-contracts/scripts/validate_version.py`).
- **Secret vocabulary lockstep**: `make validate-secret-vocabulary` checks consistency between agent-platform, tool-gateway, and skills-hub.
- **Password policy contract**: `make validate-password-policy` pins the connector floor to the canonical password policy (SPEC-062 R-2).
- **Portal tests included in verify**: Although the operator-portal is not a uv product, `make verify` runs its full Vitest suite and typechecked production build (SPEC-063 R-8c); zero-test green paths are rejected.
- **Forge-agnostic CI**: No `.github/workflows` exist; the root Makefile comment states `make verify` is the pre-commit/pre-push gate and runs the same checks locally and under any CI.