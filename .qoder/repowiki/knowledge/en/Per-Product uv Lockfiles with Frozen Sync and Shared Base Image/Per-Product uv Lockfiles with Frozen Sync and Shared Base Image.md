---
kind: dependency_management
name: Per-Product uv Lockfiles with Frozen Sync and Shared Base Image
category: dependency_management
scope:
    - '**'
source_files:
    - mk/python.mk
    - mk/image.mk
    - mk/defaults.mk
    - shared/base-images/base-uv/Dockerfile
    - products/agent-platform/pyproject.toml
    - products/platform-gateway/pyproject.toml
    - products/tool-gateway/pyproject.toml
    - products/agent-platform/Dockerfile
    - products/operator-portal/web-ui/app/package.json
    - products/operator-portal/web-ui/app/package-lock.json
    - .python-version
    - docs/agentic-aiops-platform/release-notes/2026-08-28-dependency-hygiene.md
---

# Dependency Management in the Luban Agentic AIOps Platform

## Approach

The workspace uses a **per-product dependency model** built around Python's `uv` (with `pyproject.toml` + `uv.lock`) for all eight backend services, and a standard Node.js toolchain (`package.json` + `package-lock.json`) for the operator portal SPA. There is no monorepo-level lockfile; each product owns its own manifest and lockfile, and the root Makefile orchestrates them uniformly.

### Python products

Every backend service under `products/` declares its dependencies as PEP 621 `[project].dependencies` ranges in `pyproject.toml` and pins exact transitive resolutions in a committed `uv.lock`. The shared fragment `mk/python.mk` exposes two targets used by every product:

- `make sync` → runs `uv sync --frozen`, which refuses to resolve anything beyond the committed lockfile.
- `make test` → re-runs `uv sync --frozen` then executes `uv run pytest` with OTel exporters disabled so tracing tests stay deterministic.

Dockerfiles follow an identical pattern: copy `.python-version`, `pyproject.toml`, `uv.lock`, and `src/`, then run `RUN uv sync --frozen --no-dev`. This guarantees that production images are built from the exact same resolution that was verified locally.

A shared base image at `shared/base-images/base-uv/Dockerfile` installs a pinned `uv` version (default `0.12.1`, overridable via `BASE_UV_UV_VERSION` in `mk/defaults.mk`) onto Amazon Linux 2023 minimal, sets `UV_PYTHON=3.12` and `UV_PYTHON_INSTALL_DIR=/app/.python`, and runs as a non-root `app` user. Each product's `.python-version` file (e.g. `products/*/ .python-version`) selects the interpreter that `uv sync` resolves against.

### Node.js portal

The operator portal lives in `products/operator-portal/web-ui/app/` and uses a conventional Vite + React + TypeScript stack declared in `package.json` with a committed `package-lock.json`. Its build script (`"build": "tsc --noEmit && vite build"`) is invoked by the root `make verify` target through `make -C products/operator-portal web-build`, and the root Makefile treats it as a separate concern from the Python `sync`/`test` loop because it is not a `uv` product.

## Key files

| File | Role |
|---|---|
| `mk/python.mk` | Shared `sync` / `test` targets enforcing `uv sync --frozen` |
| `mk/image.mk` | Shared Docker build/push/lint targets used by every product |
| `mk/defaults.mk` | Centralised defaults for `IMAGE_PLATFORM`, `REGISTRY`, `BASE_UV_*` versions |
| `shared/base-images/base-uv/Dockerfile` | Pinned `uv` + Python base image consumed by all backend Dockerfiles |
| `products/*/pyproject.toml` | Per-product dependency ranges, dev groups, entrypoints, build-backend |
| `products/*/uv.lock` | Exact transitive resolution locked per product |
| `products/*/Dockerfile` | Copies `uv.lock` and builds with `uv sync --frozen --no-dev` |
| `products/operator-portal/web-ui/app/package.json` | Portal frontend dependencies and scripts |
| `products/operator-portal/web-ui/app/package-lock.json` | Locked frontend resolution |
| `.python-version` | Workspace-wide Python version hint (3.12) |

## Architecture and conventions

1. **Ranges in manifests, pins in lockfiles.** Dependencies are declared with caret or compatible-release ranges (e.g. `fastapi>=0.115,<1.0`, `cryptography>=43.0,<51.0`). Exact versions live only in `uv.lock`; the release notes for v0.24.0 document how refreshes bump the lockfile while keeping ranges intact.

2. **Frozen sync everywhere.** Both local development (`make sync`) and container builds use `--frozen`, so any drift between `pyproject.toml` and `uv.lock` fails fast. No runtime `pip install` or editable installs occur in images.

3. **Shared base image isolates toolchain versions.** `BASE_UV_UV_VERSION` and `BASE_UV_PYTHON_VERSION` in `mk/defaults.mk` are the single source of truth for the `uv` and Python versions baked into `shared/base-images/base-uv`. Product builds inherit these unless overridden on the command line.

4. **Per-product isolation, root orchestration.** The root `Makefile` enumerates `PYTHON_PRODUCTS` and `IMAGE_PRODUCTS` and dispatches `make -C products/<name> <target>` for each. There is no workspace-level `uv sync`; developers must run the root `make sync` or invoke a specific product.

5. **Frontend handled separately.** The portal is excluded from the Python product loop and has its own `make portal-test` / `web-build` path. It uses `engines.node = ">=22.22.2"` to pin the minimum Node version required by jsdom 30.

6. **Dependency hygiene policy documented in release notes.** The v0.24.0 release note (SPEC-042) codifies the adoption posture: *latest stable only* — no alpha, beta, RC, or dev builds — with one recorded exception for OpenTelemetry instrumentation packages that ship on a permanent `0.xb` channel and are kept paired with their SDK version.

7. **Version lockstep enforced by scripts.** The root `make validate-version` invokes `shared/shared-contracts/scripts/validate_version.py` against the repo tree, ensuring the root `VERSION` file stays in lockstep with product versions and the portal.

## Conventions and constraints

- Every backend product must declare dependencies in `pyproject.toml` under `[project].dependencies` and commit a matching `uv.lock`; adding a dependency without updating the lockfile will fail `make sync` and `make test`.
- Production images must be built with `uv sync --frozen --no-dev`; any image that performs a runtime `pip install` breaks the frozen-resolution contract.
- New Python dependencies should use range caps (e.g. `<major+1`) rather than exact pins, letting `uv.lock` carry the concrete version.
- The `uv` binary version and Python interpreter are not chosen per-product; they come from the shared base image and `mk/defaults.mk`, so changes require updating those defaults and rebuilding `base-uv`.
- Frontend dependencies follow the standard npm convention: `package.json` holds ranges, `package-lock.json` holds the resolved tree, and `node >=22.22.2` is enforced via `engines`.
- The verification gate (`make verify`) includes `test overlays validate-policy validate-policy-scenarios validate-version validate-secret-vocabulary validate-password-policy secret-delivery-demo portal-test execution-failure-test`; any dependency change that breaks one of these steps blocks a release.