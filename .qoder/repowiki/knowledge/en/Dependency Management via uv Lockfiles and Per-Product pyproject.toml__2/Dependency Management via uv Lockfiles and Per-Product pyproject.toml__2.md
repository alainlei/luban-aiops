---
kind: dependency_management
name: Dependency Management via uv Lockfiles and Per-Product pyproject.toml
category: dependency_management
scope:
    - '**'
source_files:
    - mk/python.mk
    - Makefile
    - products/agent-platform/pyproject.toml
    - products/agent-platform/uv.lock
    - products/platform-gateway/pyproject.toml
    - products/tool-gateway/pyproject.toml
    - products/operator-portal/web-ui/app/package.json
    - shared/base-images/base-uv/Dockerfile
    - .python-version
---

## Approach

The Luban workspace is a Python monorepo whose dependency management is built on **uv** (the fast Python package manager) with one `pyproject.toml` + `uv.lock` pair per product under `products/<name>/`. There is no shared `requirements.txt`, no `setup.py`, no Poetry, no pipenv, and no vendored third-party source trees. The only non-Python dependency surface is the operator portal SPA (`products/operator-portal/web-ui/app/package.json`) managed by npm/Vite.

## Key files

- Per-product manifests: `products/*/pyproject.toml` — declare runtime dependencies, `[dependency-groups].dev`, entry points, and build backend.
- Per-product lockfiles: `products/*/uv.lock` — pinned versions, hashes, and wheel/sdist URLs from PyPI.
- Shared Makefile targets: `mk/python.mk` (`sync`, `test`) and root `Makefile` (`make sync`, `make test`) orchestrate resolution across all nine Python products.
- Root `.python-version` pins the interpreter for the workspace.
- Portal frontend manifest: `products/operator-portal/web-ui/app/package.json` (npm).
- Base image definition: `shared/base-images/base-uv/Dockerfile` plus `mk/defaults.mk` variables `BASE_UV_*` pin the uv binary version baked into images.

## Architecture and conventions

1. **Per-product isolation.** Each of the eight Python services (`agent-platform`, `audit-service`, `execution-runtime`, `identity-broker`, `incident-service`, `platform-gateway`, `skills-hub`, `tool-gateway`) declares its own `dependencies` list in its `pyproject.toml`. There are no cross-package references between them; they communicate over HTTP/gRPC contracts defined in `shared/shared-contracts/`.

2. **Semver-ranged constraints.** Dependencies use upper-bounded ranges (e.g. `fastapi>=0.115,<1.0`, `pydantic>=2.8,<3.0`, `agentscope>=2.0.4,<3.0`). This allows patch/minor updates while blocking breaking major releases. Dev-only tooling lives under `[dependency-groups].dev` (pytest, fakeredis, jsonschema) and is not installed at runtime.

3. **Frozen installs in CI and dev.** `mk/python.mk` runs `uv sync --frozen`, which refuses to resolve or update anything — the lockfile is authoritative. The root `Makefile` exposes `make sync` and `make test` that iterate over `PYTHON_PRODUCTS := agent-platform audit-service execution-runtime identity-broker incident-service platform-gateway skills-hub tool-gateway` and invoke each product's Makefile.

4. **Build backend pinned.** Every `pyproject.toml` sets:
   ```
   [build-system]
   requires = ["uv_build>=0.8.14,<0.9.0"]
   build-backend = "uv_build"
   ```
   The base Docker image (`shared/base-images/base-uv`) is built with `--build-arg UV_VERSION=$(BASE_UV_UV_VERSION)` so the same uv binary used locally resolves the same lockfile in production containers.

5. **No private registry or vendoring.** All packages resolve from `https://pypi.org/simple` as recorded in every `uv.lock` entry (`source = { registry = "https://pypi.org/simple" }`). No `uv.toml`, `pyproject.toml` `[tool.uv.sources]`, `PIP_INDEX_URL`, `UV_INDEX_URL`, `GOPRIVATE`, or custom registries appear anywhere in the repo. There is no `vendor/` directory and no vendored third-party code.

6. **Frontend dependencies separate.** The operator portal SPA uses npm (`package.json`), Vite, Vitest, TypeScript, React/Ant Design. It is excluded from the Python `sync`/`test` loop and has its own `make -C products/operator-portal web-build` / `portal-test` gate in the root Makefile.

7. **Version lockstep enforced externally.** The root `VERSION` file is the single source of truth for the platform release; `make validate-version` (via `shared/shared-contracts/scripts/validate_version.py`) asserts that every product's `pyproject.toml` `version` field matches it. This is a product-version invariant, not a dependency-version constraint, but it keeps the nine service packages coordinated.

## Conventions and constraints

- **Observed convention:** Runtime dependencies use `<major>` upper bounds (e.g. `<3.0`, `<1.0`, `<9.0`) to allow safe upgrades without manual review of breaking changes.
- **Observed convention:** Common observability stack (`opentelemetry-*`, `prometheus-client`, `pydantic`, `fastapi`, `uvicorn[standard]`) is declared identically across gateway-like services.
- **Enforced rule:** Dependency resolution must be frozen — `mk/python.mk` calls `uv sync --frozen`; any drift between `pyproject.toml` and `uv.lock` fails the build.
- **Enforced rule:** The Python interpreter version is pinned at the workspace root (`.python-version`) and propagated to the base image via `BASE_UV_PYTHON_VERSION`.
- **Enforced rule:** The uv binary version used to build images is pinned via `BASE_UV_UV_VERSION` in `mk/defaults.mk` and passed as a Docker build arg to `shared/base-images/base-uv/Dockerfile`.
- **Enforced rule:** Product versions must match the root `VERSION` file — enforced by `make validate-version`.
- **Constraint:** No private PyPI index, no `uv.toml` configuration, no `pip.conf`, no `requirements.txt`, no vendored packages — the repository relies exclusively on public PyPI.