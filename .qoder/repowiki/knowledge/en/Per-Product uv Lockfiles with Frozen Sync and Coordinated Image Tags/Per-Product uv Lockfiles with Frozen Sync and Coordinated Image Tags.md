---
kind: dependency_management
name: Per-Product uv Lockfiles with Frozen Sync and Coordinated Image Tags
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
    - docs/agentic-aiops-platform/release-notes/2026-08-28-dependency-hygiene.md
    - CONTRIBUTING.md
---

## System Overview

The Luban AIOps Platform uses **uv** as the Python package manager across all nine backend services under `products/`. Each product is an independent PEP 621 project declared in its own `pyproject.toml`, with a per-product `uv.lock` that pins every transitive dependency to exact versions and hashes. There is no monorepo-level lockfile; instead, each product resolves and locks independently against PyPI.

The workspace root orchestrates dependency operations via shared Makefile fragments in `mk/`: `mk/python.mk` defines the canonical `sync` target (`uv sync --frozen`) and test target, and `mk/image.mk` plus `mk/defaults.mk` pin the base image toolchain (UV version 0.12.1, Python 3.12) used by every Docker build. The root `Makefile` exposes `make sync` which iterates over `PYTHON_PRODUCTS` and invokes each product's `make sync`, ensuring every service re-syncs from its frozen lockfile.

## Key Files

- `products/<service>/pyproject.toml` — declares runtime dependencies with upper-bound major-version caps (e.g. `agentscope>=2.0.4,<3.0`, `fastapi>=0.115,<1.0`, `pydantic>=2.8,<3.0`) and a `[dependency-groups] dev = [...]` section for test-only packages like `pytest` and `fakeredis`.
- `products/<service>/uv.lock` — generated lockfile with `version = 1`, `revision = 3`, `requires-python = ">=3.11"`, and per-package entries sourced from `https://pypi.org/simple` with full sdist/wheel URLs and sha256 hashes.
- `mk/python.mk` — shared targets: `sync` runs `uv sync --frozen`; `test` runs `uv sync --frozen` then `uv run pytest` with OTLP exporters disabled so tracing tests stay noise-free.
- `mk/defaults.mk` — pins `BASE_UV_UV_VERSION = 0.12.1` and `BASE_UV_PYTHON_VERSION = 3.12`, consumed by `shared/base-images/base-uv/Dockerfile` and the root `base-images` target.
- `mk/image.mk` — container build wrapper that tags images as `luban-aiops/<name>:<tag>` and optionally re-tags/pushes to a configured `REGISTRY`.
- Root `Makefile` — aggregates per-product `sync`, `test`, `build`, `push`; computes a coordinated `IMAGE_TAG` from `VERSION` + git SHA; writes `.images.env` listing all built images with the same tag.
- `docs/agentic-aiops-platform/release-notes/2026-08-28-dependency-hygiene.md` — documents the adopted policy of "latest stable only" (no alpha/beta/RC/dev), with OpenTelemetry instrumentation packages staying on their permanent `0.xb` channel paired to the locked SDK.

## Architecture and Conventions

- **Per-product isolation**: each service owns its own `pyproject.toml` and `uv.lock`; there is no workspace-level dependency aggregation. Cross-cutting concerns are expressed through shared contracts in `shared/shared-contracts/` (schemas, policies) rather than shared Python packages.
- **Major-version caps**: runtime dependencies use caret-style lower bounds with strict `<next_major` upper bounds (e.g. `<3.0`, `<1.0`, `<4.0`, `<7.0`). This allows patch/minor refreshes while preventing breaking upgrades.
- **Frozen installs**: both development and CI always use `uv sync --frozen`, meaning the lockfile is authoritative — no resolution at install time. Any dependency change requires editing `pyproject.toml` and regenerating the lockfile.
- **Coordinated release tagging**: the root `VERSION` file is the single source of truth. The root `Makefile` computes a coordinated image tag `<semver>-<prefix>-<gitsha>[-dirty-<timestamp>]` and applies it uniformly to all eight Python services plus the operator portal web UI. Product `pyproject.toml` versions must match `VERSION` (enforced by `make validate-version`, part of `make verify`).
- **Base image pinning**: `shared/base-images/base-uv/Dockerfile` builds a reproducible base image using the pinned UV and Python versions from `mk/defaults.mk`; every product Dockerfile inherits this base.
- **Private registry / vendoring**: none observed. All packages resolve from `https://pypi.org/simple`. No `vendor/` directories, no `pip.conf`/`uv.toml` registry overrides, no `GOPRIVATE` equivalents.
- **Frontend dependency management** (operator portal): the SPA under `products/operator-portal/web-ui/` uses Node.js tooling (Vitest, TypeScript, Vite, React 19, antd 6). It is not a uv product; its dependencies are managed separately and verified via `make portal-test` (unit suite + production build).

## Conventions and Constraints

- **Dependency updates follow SPEC-042 posture**: adopt "latest stable only" — no pre-release channels except the documented OpenTelemetry instrumentation exception on the `0.xb` channel paired to the locked SDK.
- **Lockstep versioning**: every `products/*/pyproject.toml` `version`, every `metadata.py` `SERVICE_VERSION`, and the portal's `PLATFORM_VERSION` must equal the root `VERSION`. Enforced by `make validate-version` which is part of the `make verify` gate.
- **Policy-driven verification**: `make verify` is the pre-commit/pre-push gate and includes `validate-policy`, `validate-policy-scenarios`, `validate-secret-vocabulary`, `validate-password-policy`, overlay rendering, and portal build — any dependency change that breaks these gates fails the PR.
- **No behavior changes without tests**: per CONTRIBUTING.md, dependency-only releases still exercise live checks (chat, HITL confirmation, approved-mutating paths) when they touch the runtime kernel (`agentscope`).
- **Cryptography cap management**: products declaring cryptography move the upper bound together (e.g. `>=43.0,<45.0` → `>=43.0,<51.0`) and review call sites before upgrading, as recorded in the dependency hygiene release notes.
- **Redis/Elasticsearch client majors are intentionally parked** below server majors to avoid API-removal releases, as explicitly justified in the release notes.