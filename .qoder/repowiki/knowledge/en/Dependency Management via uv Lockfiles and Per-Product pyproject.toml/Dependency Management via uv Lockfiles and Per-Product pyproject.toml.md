---
kind: dependency_management
name: Dependency Management via uv Lockfiles and Per-Product pyproject.toml
category: dependency_management
scope:
    - '**'
source_files:
    - mk/python.mk
    - mk/defaults.mk
    - Makefile
    - products/agent-platform/pyproject.toml
    - products/agent-platform/uv.lock
    - products/audit-service/pyproject.toml
    - products/execution-runtime/pyproject.toml
    - products/identity-broker/pyproject.toml
    - products/incident-service/pyproject.toml
    - products/platform-gateway/pyproject.toml
    - products/skills-hub/pyproject.toml
    - products/tool-gateway/pyproject.toml
    - products/operator-portal/web-ui/app/package.json
    - shared/base-images/base-uv/Dockerfile
    - docs/agentic-aiops-platform/release-notes/2026-08-28-dependency-hygiene.md
---

## Approach

The Luban AIOps Platform is a Python monorepo (plus one operator-portal SPA) that manages third-party dependencies with **uv** as the package manager, using per-product `pyproject.toml` + `uv.lock` pairs. The root Makefile orchestrates dependency operations across all products; there is no workspace-level lockfile.

## Key Files

- `mk/python.mk` — shared `sync` / `test` targets that invoke `uv sync --frozen` and `uv run pytest`, enforcing deterministic installs.
- `mk/defaults.mk` — pins `BASE_UV_UV_VERSION = 0.12.1` and `BASE_UV_PYTHON_VERSION = 3.12`; these are consumed by the shared base image `shared/base-images/base-uv/Dockerfile` so runtime images use the same uv binary.
- Root `Makefile` — `make sync` iterates over `PYTHON_PRODUCTS` (`agent-platform audit-service execution-runtime identity-broker incident-service platform-gateway skills-hub tool-gateway`) and delegates to each product's `make sync`.
- Per-product `products/<name>/pyproject.toml` — declares runtime `dependencies` and `[dependency-groups] dev` for test-only packages.
- Per-product `products/<name>/uv.lock` — frozen resolution snapshot committed alongside the manifest.
- `products/operator-portal/web-ui/app/package.json` — the only non-Python dependency manifest (React 19, antd 6, Vite 8, Vitest 4).
- `docs/agentic-aiops-platform/release-notes/2026-08-28-dependency-hygiene.md` — documents the adopted policy: "latest stable only" with a single recorded exception for OpenTelemetry instrumentation on its permanent `0.xb` channel.

## Architecture and Conventions

1. **Per-product isolation.** Each of the eight Python services owns its own `pyproject.toml` and `uv.lock`. There is no shared `requirements.txt` or workspace-level resolver. Cross-cutting orchestration lives in the root `Makefile` and `mk/*.mk` fragments.

2. **Frozen installs in CI and local runs.** `mk/python.mk` uses `uv sync --frozen` for both `sync` and `test`, meaning the lockfile is authoritative — the resolver cannot drift versions at install time. The root `verify` gate chains `make test` across all products, so any lockfile drift fails verification.

3. **Reproducible base image.** `mk/defaults.mk` pins `BASE_UV_UV_VERSION` and `BASE_UV_PYTHON_VERSION`; `make base-images` builds `shared/base-images/base-uv` with those exact versions, ensuring every product Docker image gets the same uv binary.

4. **Version ranges in manifests, pinning in lockfiles.** Runtime dependencies in `pyproject.toml` use broad upper bounds (e.g. `agentscope>=2.0.4,<3.0`, `fastapi>=0.115,<1.0`, `pydantic>=2.8,<3.0`, `redis>=6.2,<7.0`). Exact resolved versions live only in `uv.lock`. The release notes document deliberate cap decisions (e.g. keeping `redis <7.0` because the deployed server is 7.2 and client majors 7/8 were API-removal releases; parking Elasticsearch `<9.0` since no ES server is deployed).

5. **Dev vs runtime separation.** Test-only packages go under `[dependency-groups] dev` (e.g. `fakeredis`, `pytest`), not the runtime `dependencies` list.

6. **Operator portal uses npm/Vitest instead of uv.** Its dependencies are declared in `package.json` with caret ranges; the root `Makefile` calls `make -C products/operator-portal test` and `web-build` separately (see `portal-test` target). Node version is pinned via `engines.node = ">=22.22.2"`.

7. **No vendoring, no private registry configuration visible in the repo.** Dependencies are fetched from PyPI/npm registries; no `--index-url`, `PIP_INDEX_URL`, `UV_INDEX_URL`, `GOPRIVATE`, or `.npmrc` files are present in the tree shown.

## Conventions and Constraints

- **Adopted policy:** "latest stable only" — no alpha, beta, RC, or dev builds. The sole documented exception is the OpenTelemetry instrumentation packages, which stay on their permanent `0.xb` pre-release channel paired with the locked SDK version (source: `docs/agentic-aiops-platform/release-notes/2026-08-28-dependency-hygiene.md`).
- **Lockfiles are frozen:** `uv sync --frozen` is used everywhere in `mk/python.mk`, so installing outside the lockfile is rejected by design.
- **Base uv binary is pinned centrally:** `BASE_UV_UV_VERSION` in `mk/defaults.mk` is the single source of truth for the uv version baked into `shared/base-images/base-uv`.
- **Python floor:** `requires-python = ">=3.11"` in each `pyproject.toml`; the base image uses Python 3.12.
- **Node floor:** `engines.node = ">=22.22.2"` in `products/operator-portal/web-ui/app/package.json`, matching jsdom 30's engine requirement.
- **Verification gate enforces consistency:** `make verify` runs `make test` (which does frozen `uv sync`), overlay rendering, dashboard validation, policy validation, version validation, secret-vocabulary validation, password-policy validation, portal tests, and execution failure tests — any dependency-related breakage surfaces here.