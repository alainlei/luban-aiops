---
kind: dependency_management
name: uv-based Per-Product Dependency Management with Frozen Lockfiles
category: dependency_management
scope:
    - '**'
source_files:
    - mk/python.mk
    - mk/image.mk
    - mk/defaults.mk
    - Makefile
    - shared/base-images/base-uv/Dockerfile
    - products/agent-platform/pyproject.toml
    - products/platform-gateway/pyproject.toml
    - products/audit-service/pyproject.toml
    - products/tool-gateway/pyproject.toml
    - products/agent-platform/Dockerfile
    - docs/specs/SPEC-042-dependency-hygiene/spec.md
---

## Approach

Luban uses **uv** as the sole Python package manager and **npm** for the operator portal. Each product under `products/<name>/` is an independent uv project with its own `pyproject.toml` and committed `uv.lock`. There is no workspace-level lockfile, no vendored third-party code, and no private PyPI registry configured — dependencies resolve from the public index.

The shared base image `shared/base-images/base-uv/Dockerfile` (built via `make base-images`) installs a pinned `uv` (`BASE_UV_UV_VERSION=0.12.1`, overridable via `--build-arg BASE_UV_UV_VERSION`) on Amazon Linux 2023 minimal; it does not install a system Python. Product Dockerfiles then copy only `.python-version`, `pyproject.toml`, `uv.lock`, `README.md`, and `src/`, and run `uv sync --frozen --no-dev` to install runtime-only dependencies deterministically.

## Key Files

- `mk/python.mk` — shared `sync` / `test` targets that invoke `uv sync --frozen` and `uv run pytest`; this is the single entry point every Python product Makefile includes.
- `mk/image.mk` — shared container-image targets (`build`, `push`, `lint`) used by all product Dockerfiles.
- `mk/defaults.mk` — pinned defaults for `BASE_UV_UV_VERSION=0.12.1`, `BASE_UV_PYTHON_VERSION=3.12`, `IMAGE_PLATFORM=linux/amd64`, `REGISTRY`.
- Root `Makefile` — orchestrates cross-product `sync`, `test`, `build`, `push`; declares `PYTHON_PRODUCTS := agent-platform audit-service execution-runtime identity-broker incident-service platform-gateway skills-hub tool-gateway` and iterates them.
- Per-product `pyproject.toml` + `uv.lock` — dependency declarations and frozen resolutions for each of the eight Python services.
- `shared/base-images/base-uv/Dockerfile` — pinned uv + non-root `app` user (uid 1000), env vars `UV_LINK_MODE=copy`, `UV_NO_SYNC=1`, `UV_PYTHON=${PYTHON_VERSION}`, `UV_PYTHON_INSTALL_DIR=/app/.python`.
- `docs/specs/SPEC-042-dependency-hygiene/spec.md` — the authoritative policy document governing how dependencies are refreshed.

## Architecture and Conventions

### Python products

Every backend service follows the same layout: `pyproject.toml` declares `[project]` metadata, `dependencies`, optional `[dependency-groups].dev`, and `[build-system]` using `uv_build>=0.8.14,<0.9.0`. Dependencies use **upper-bound major caps** (e.g. `fastapi>=0.115,<1.0`, `pydantic>=2.8,<3.0`, `opentelemetry-sdk>=1.25,<2.0`, `cryptography>=43.0,<51.0`, `redis>=6.2,<7.0` or `<7.0` in tool-gateway) so minor/patch updates flow automatically while majors are gated by review.

The `uv.lock` file is committed alongside `pyproject.toml`. Build and test paths always use `uv sync --frozen` (see `mk/python.mk` line 12 and every product Dockerfile's `RUN uv sync --frozen --no-dev`), which rejects any lockfile drift — there is no `--frozen` bypass in normal flows.

Development dependencies live under `[dependency-groups].dev` (typically `pytest>=8.3,<9.0` plus `jsonschema>=4.23,<5.0`; `agent-platform` adds `fakeredis>=2.26,<3.0`). The `--no-dev` flag in production images excludes them.

### Operator portal

The operator portal (`products/operator-portal/web-ui/`) is a Node.js SPA managed by npm (`package.json` + `package-lock.json`). It is excluded from the Python `PYTHON_PRODUCTS` list and has its own `make test` / `web-build` targets driven by Vitest and Vite.

### Version lockstep

All Python products pin their own `version = "0.45.0"` in `pyproject.toml`, matching the root `VERSION` file. A `make validate-version` target runs `shared/shared-contracts/scripts/validate_version.py` against the repo root to enforce this lockstep at verify time.

### Refresh policy

`SPEC-042-dependency-hygiene` codifies the refresh rules:

- Adopted versions must be **latest stable** — no alpha, beta, RC, or dev builds anywhere.
- Backend lockfiles are re-locked inside declared ranges (`uv lock` per product); range caps are adjudicated explicitly when a new major is considered (e.g. cryptography raised from `<45.0` to `<51.0`, redis and elasticsearch caps parked with reasons).
- OpenTelemetry instrumentation packages (`opentelemetry-instrumentation-fastapi/httpx/logging`) are a recorded exception: they publish on a permanent `0.xb` channel and stay paired with the SDK version already locked.
- TypeScript 7.x is parked; React 19 was adopted because peer surfaces were ready.
- No deprecation snapshot allow-list: antd deprecations fail the suite via a guard added in R-2.

### CI / verification gate

`make verify` aggregates product tests, GitOps overlay rendering, dashboard validation, policy validation/scenarios, version lockstep, secret-vocabulary validation, password-policy validation, secret-delivery demo, and portal unit/build checks. It is documented as the pre-commit/pre-push gate in the root `Makefile` comment.

## Conventions and Constraints

- **One uv lockfile per product, committed.** Every Python product ships a `uv.lock` next to its `pyproject.toml`; `uv sync --frozen` is the only supported install path in both development (`mk/python.mk`) and production Dockerfiles.
- **No vendoring.** Third-party code is never checked into the tree; resolution goes through uv's default public index.
- **Major-version caps in `pyproject.toml` dependencies.** Observed across fastapi, pydantic, opentelemetry-* (sdk/api/exporter), cryptography, redis, elasticsearch, kubernetes, agentscope, agentscope-runtime, uvicorn, jsonschema, pytest, fakeredis, playwright, etc. New majors require explicit range edits and review.
- **Pinned toolchain in the base image.** `BASE_UV_UV_VERSION=0.12.1` and `BASE_UV_PYTHON_VERSION=3.12` in `mk/defaults.mk`; overridden via `--build-arg` for `make base-images`, but never left floating.
- **Non-root container user.** `shared/base-images/base-uv/Dockerfile` creates user `app` (uid 1000) and sets `USER app`; product Dockerfiles inherit it.
- **Version lockstep enforced by `make validate-version`.** The root `VERSION` file is the single source of truth; `shared/shared-contracts/scripts/validate_version.py` is invoked by the root Makefile and fails if any product's `pyproject.toml` version diverges.
- **Latest-stable-only adoption policy.** Stated in `SPEC-042-dependency-hygiene/spec.md` (R-3, R-5, Design Decisions): no prerelease/beta/RC/dev versions adopted; the OTel instrumentation `0.xb` channel is the single recorded exception.
- **Deprecation failures are hard gates.** SPEC-042 R-2 requires the portal's vitest setup to fail when any antd deprecation warning appears — zero-tolerance, no allow-list.
- **Frozen sync in production images.** Every product Dockerfile copies `uv.lock` and runs `uv sync --frozen --no-dev`; there is no network fetch at build time beyond what uv resolves from the committed lock.