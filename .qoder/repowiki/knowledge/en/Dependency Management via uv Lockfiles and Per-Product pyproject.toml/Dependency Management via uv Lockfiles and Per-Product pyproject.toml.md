---
kind: dependency_management
name: Dependency Management via uv Lockfiles and Per-Product pyproject.toml
category: dependency_management
scope:
    - '**'
source_files:
    - Makefile
    - mk/python.mk
    - mk/defaults.mk
    - .python-version
    - products/agent-platform/pyproject.toml
    - products/agent-platform/uv.lock
    - products/tool-gateway/pyproject.toml
    - products/operator-portal/web-ui/app/package.json
    - shared/base-images/base-uv/Dockerfile
---

## Approach

Luban is a multi-product Python workspace (nine services under `products/`) that uses **uv** as its package manager, with one `pyproject.toml` + `uv.lock` per product. The frontend (`operator-portal/web-ui/app/package.json`) uses npm/Vite for Node dependencies. There is no vendoring of third-party code — all packages are resolved from PyPI at build time.

## Key Files

- Root orchestrator: `Makefile` (aggregates per-product `sync`, `test`, `build`, `verify`), `mk/python.mk` (shared `uv sync --frozen` / `uv run pytest` targets), `mk/defaults.mk` (pins `BASE_UV_UV_VERSION=0.12.1`, `BASE_UV_PYTHON_VERSION=3.12`).
- Per-product manifests: `products/*/pyproject.toml` declare runtime deps; each has a matching `products/*/uv.lock` pinning exact transitive versions and hashes.
- Python version pins: root `.python-version` and per-product `.python-version` both set `3.12`; `pyproject.toml` `requires-python = ">=3.11"`.
- Frontend manifest: `products/operator-portal/web-ui/app/package.json` (npm, pinned via `node_modules/` in-tree).
- Shared base image: `shared/base-images/base-uv/Dockerfile` builds a reproducible base image with the pinned uv/python versions referenced by `mk/defaults.mk`.

## Architecture and Conventions

1. **Per-product isolation.** Each service owns its own `pyproject.toml` and `uv.lock`. The root `Makefile` iterates over `PYTHON_PRODUCTS := agent-platform audit-service execution-runtime identity-broker incident-service platform-gateway skills-hub tool-gateway` and delegates `sync`/`test`/`build` into each product directory so `uv` resolves the local `pyproject.toml`.

2. **Frozen installs.** `mk/python.mk` runs `uv sync --frozen` — lockfiles are mandatory; dependency resolution cannot drift between developer machines and CI.

3. **Version specifiers use bounded ranges.** Dependencies are declared with lower and upper bounds (e.g. `agentscope>=2.0.4,<3.0`, `fastapi>=0.115,<1.0`, `pydantic>=2.8,<3.0`, `redis>=6.2,<7.0`). This constrains major upgrades while allowing minor/patch bumps.

4. **Dev vs runtime separation.** Runtime dependencies live under `[project].dependencies`; test-only packages (`pytest`, `fakeredis`, `jsonschema`) go under `[dependency-groups] dev` and are excluded from the built artifact.

5. **Build backend pinned.** Every Python product declares `[build-system] requires = ["uv_build>=0.8.14,<0.9.0"]` with `build-backend = "uv_build"`, pinning the packaging tool itself.

6. **Base image reproducibility.** `mk/defaults.mk` pins `BASE_UV_UV_VERSION=0.12.1` and `BASE_UV_PYTHON_VERSION=3.12`; the root `make base-images` target passes these as `--build-arg UV_VERSION` / `--build-arg PYTHON_VERSION` to `shared/base-images/base-uv/Dockerfile`, ensuring container images are built against a known uv/python combination.

7. **No private registry configured.** A grep across the repo finds no `UV_INDEX_URL`, `index-url`, `extra-index-url`, or `UV_PIP_INDEX_URL` configuration — all packages resolve from `https://pypi.org/simple` (visible in every `[[package]] source = { registry = "https://pypi.org/simple" }` entry in the lockfiles).

8. **Frontend dependencies managed separately.** The operator portal SPA lives under `products/operator-portal/web-ui/app/` and uses standard npm (`package.json` + `node_modules/`); it is not part of the uv ecosystem and is exercised through `make portal-test` which runs `vitest` and `vite build`.

## Conventions and Constraints

- **Lockfiles are committed and enforced.** `uv sync --frozen` in `mk/python.mk` refuses to install anything not present in `uv.lock`; this is the hard enforcement mechanism for reproducible builds.
- **Python version is pinned at two levels.** `.python-version` files (root and per-product) state `3.12`; `pyproject.toml` sets `requires-python = ">=3.11"`.
- **All products share the same dependency categories.** Runtime deps under `[project].dependencies`, dev/test deps under `[dependency-groups] dev`, and `uv_build` under `[build-system]` — observed consistently across all eight Python products.
- **Major-version caps on third-party libraries.** Every dependency uses an upper bound `<X.0` (e.g. `<3.0`, `<1.0`, `<4.0`, `<7.0`), preventing accidental major upgrades.
- **The root `make verify` gate includes `test overlays validate-dashboards validate-policy validate-policy-scenarios validate-version validate-secret-vocabulary validate-password-policy secret-delivery-demo portal-test execution-failure-test`**, making dependency-related checks (version lockstep, policy contracts, dashboard schemas) part of the pre-commit/pre-push verification surface defined in the root Makefile.
- **No vendored third-party code.** All third-party packages are pulled from PyPI at build/install time; there is no `vendor/`, `third_party/`, or similar directory.