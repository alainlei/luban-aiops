---
kind: dependency_management
name: uv + npm Dependency Management with Frozen Lockfiles
category: dependency_management
scope:
    - '**'
source_files:
    - mk/python.mk
    - mk/image.mk
    - mk/defaults.mk
    - Makefile
    - products/agent-platform/pyproject.toml
    - products/agent-platform/uv.lock
    - products/agent-platform/.python-version
    - products/agent-platform/Dockerfile
    - products/operator-portal/web-ui/app/package.json
    - products/operator-portal/web-ui/app/package-lock.json
    - docs/agentic-aiops-platform/release-notes/2026-08-28-dependency-hygiene.md
---

## Approach

The Luban workspace is a monorepo of eight Python services plus one TypeScript/React operator portal. Dependency management is split by language:

- **Python**: `uv` (PEP 621 via `pyproject.toml`, lockfile `uv.lock`) — used for every product under `products/<name>/`.
- **Frontend**: `npm` (`package.json` + `package-lock.json`) — used only by `products/operator-portal/web-ui/app/`.

There is no root-level manifest; each product owns its own dependency graph. The root `Makefile` orchestrates them uniformly through shared fragments in `mk/`.

## Key Files

- `mk/python.mk` — shared `sync` / `test` targets that invoke `uv sync --frozen` and `uv run pytest`.
- `mk/image.mk` — shared Docker build/push/lint targets; images copy `.python-version`, `pyproject.toml`, `uv.lock` and run `uv sync --frozen --no-dev` at build time.
- `mk/defaults.mk` — pins `BASE_UV_UV_VERSION=0.12.1` and `BASE_UV_PYTHON_VERSION=3.12`; the shared base image `shared/base-images/base-uv/Dockerfile` builds from these values.
- Root `Makefile` — defines `PYTHON_PRODUCTS := agent-platform audit-service execution-runtime identity-broker incident-service platform-gateway skills-hub tool-gateway` and dispatches `make sync` / `make test` across all of them.
- Per-product `pyproject.toml` — declares `[project] dependencies` with upper-bound major-version caps (e.g. `agentscope>=2.0.4,<3.0`, `fastapi>=0.115,<1.0`, `pydantic>=2.8,<3.0`).
- Per-product `uv.lock` — frozen resolution committed alongside the source.
- Per-product `.python-version` — pins the interpreter (e.g. `3.12`); copied into images so `uv` resolves against the exact runtime.
- `products/operator-portal/web-ui/app/package.json` + `package-lock.json` — frontend deps, including antd 6.x, React 19, Vite 8, Vitest 4, TypeScript 5.9.
- `docs/agentic-aiops-platform/release-notes/2026-08-28-dependency-hygiene.md` — documents the adopted posture: "latest stable only — no alpha, beta, RC, or dev builds", with one recorded exception for OTel instrumentation packages on the permanent `0.xb` channel.

## Architecture and Conventions

### Python products

Each Python product follows an identical layout: `src/<package>/`, `tests/`, `Dockerfile`, `Makefile`, `pyproject.toml`, `uv.lock`, `.python-version`. The root `Makefile` iterates over `PYTHON_PRODUCTS` and runs `make -C products/$p sync` / `test` / `build` / `push`.

Dependency ranges use a two-tier strategy: lower bounds pin minimum versions, upper bounds cap the major version (e.g. `<3.0` for pydantic, `<7.0` for redis). This allows minor/patch upgrades while preventing breaking-major bumps. The release notes document explicit decisions to keep `redis(<7.0)` and `elasticsearch(<9.0)` due to deployed server compatibility, and to widen `cryptography(<45.0)` → `(<51.0)` after call-site review.

Build-time reproducibility is enforced by:
- `uv sync --frozen` in both development (`mk/python.mk`) and container builds (`Dockerfile`), which refuses to resolve outside `uv.lock`.
- A shared base image `luban-aiops/base-uv:al2023` built from pinned `BASE_UV_UV_VERSION` and `BASE_UV_PYTHON_VERSION` in `mk/defaults.mk`.
- `.python-version` files per product, ensuring the same interpreter as the image.

### Frontend (operator portal)

The portal uses standard npm: `package.json` declares dependencies, `package-lock.json` is committed. The release notes describe a managed refresh adopting React 19, Vite 8, Vitest 4, TypeScript 5.9, and antd 6.6.2, with a vitest teardown guard that fails the suite on any `[antd: …] deprecated` warning — effectively enforcing zero-deprecation posture.

### Cross-cutting orchestration

The root `Makefile.verify` target aggregates product tests, GitOps overlay validation, policy validation, dashboard validation, secret-vocabulary checks, portal unit+build, and execution-failure tests. Dependency hygiene is exercised indirectly through `make verify` running every product's frozen `uv sync` + test suite.

## Conventions and Constraints

Observed conventions:
- Every Python product declares dependencies in `pyproject.toml` using PEP 621 `[project.dependencies]` with semver ranges capped at the next major version.
- Every Python product ships a committed `uv.lock`; development and CI use `uv sync --frozen` (never `--reinstall` or unconstrained resolution).
- Container images are built from the shared `luban-aiops/base-uv` image and install deps with `uv sync --frozen --no-dev`.
- The Python interpreter version is pinned per product via `.python-version` and mirrored in `mk/defaults.mk` (`BASE_UV_PYTHON_VERSION=3.12`).
- The `uv` toolchain version itself is pinned in `mk/defaults.mk` (`BASE_UV_UV_VERSION=0.12.1`) and baked into the base image.
- The frontend uses npm with a committed `package-lock.json`.
- Dependency updates follow the documented "latest stable only" posture, with exceptions recorded explicitly (OTel instrumentation `0.xb` channel).

Enforced rules (source cited):
- `mk/python.mk`: `uv sync --frozen` is the only supported way to install dependencies in this repo; any unconstrained resolution will fail.
- `mk/image.mk` + per-product `Dockerfile`s: production images always run `uv sync --frozen --no-dev`, so the locked `uv.lock` is the single source of truth for installed packages.
- `mk/defaults.mk`: `BASE_UV_UV_VERSION` and `BASE_UV_PYTHON_VERSION` are pinned defaults (comment: "Pinned values below are defaults for reproducible builds — never `latest`").
- Root `Makefile`: `verify` aggregates all product test suites, overlays, policies, dashboards, portal tests, and failure proofs — a dependency change must pass the full gate.
- Release notes (`2026-08-28-dependency-hygiene.md`): the adopted policy is "latest stable only — no alpha, beta, RC, or dev builds", with the OTel instrumentation packages being the sole recorded exception.