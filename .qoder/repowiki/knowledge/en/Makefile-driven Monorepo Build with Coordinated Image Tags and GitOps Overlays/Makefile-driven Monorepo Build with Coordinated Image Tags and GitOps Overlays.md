---
kind: build_system
name: Makefile-driven Monorepo Build with Coordinated Image Tags and GitOps Overlays
category: build_system
scope:
    - '**'
source_files:
    - Makefile
    - mk/defaults.mk
    - mk/image.mk
    - mk/python.mk
    - VERSION
    - products/agent-platform/Makefile
    - products/operator-portal/Makefile
    - products/tool-gateway/Makefile
    - products/agent-platform/Dockerfile
    - products/operator-portal/Dockerfile
    - shared/base-images/base-uv/Dockerfile
---

# Build System Overview

Luban is built as a **GNU make-driven monorepo** with no CI pipeline files checked into `.github/` (only issue templates and a PR template). The root `Makefile` aggregates per-product routines, owns cross-cutting concerns (GitOps overlay validation, policy sync, version lockstep), and delegates language-specific work to shared fragments under `mk/`.

## Architecture

### Directory layout

- `Makefile` — master entry point; defines product lists (`PYTHON_PRODUCTS`, `IMAGE_PRODUCTS`), computes coordinated `IMAGE_TAG`, and wires verification targets.
- `mk/defaults.mk` — single source of overridable build settings (`IMAGE_PLATFORM`, `REGISTRY`, `BASE_UV_*`, `AUTO_LOAD_KIND`). All values use `?=`, so command-line overrides always win.
- `mk/image.mk` — shared container-image targets (`build`, `push`, `lint`) used by every product Makefile.
- `mk/python.mk` — shared Python targets (`sync`, `test`) using `uv sync --frozen` + pytest with OTel exporters disabled for test output cleanliness.
- Each product under `products/<name>/` has a thin `Makefile` that sets `IMAGE_NAME` and includes both `mk/image.mk` and `mk/python.mk` (except `operator-portal`, which only includes `image.mk` and adds npm-based `test` / `web-build` targets).
- `shared/base-images/base-uv/Dockerfile` — shared base image built via `make base-images`.
- `shared/platform-ops/gitops/` — Kustomize overlays validated by `make overlays`.
- `shared/platform-ops/dashboards/` — OpenObserve dashboards validated offline by `make validate-dashboards`.

### Product model

| Category | Products | Notes |
|---|---|---|
| Python (uv) | agent-platform, audit-service, execution-runtime, identity-broker, incident-service, platform-gateway, skills-hub, tool-gateway | `uv sync --frozen` + pytest |
| Container images | Same eight plus operator-portal | Dockerfiles all `FROM luban-aiops/base-uv:al2023` except operator-portal |
| Frontend SPA | operator-portal | Vite + Vitest + tsc; served by nginxinc/nginx-unprivileged |

### Image tagging strategy

The root `make build` computes one coordinated tag:

```
<semver>-<prefix>[-<profile>]-<gitsha>[-dirty-<timestamp>]
```

- Semver comes from the root `VERSION` file (currently `0.46.0`).
- Prefix defaults to `dev-k8s`; profile is empty unless set.
- Clean tree → `<version>-dev-k8s-<short-sha>`.
- Dirty tree → appends `-dirty-<YYYYMMDDHHmmss>`.
- The computed tag is written to `shared/platform-ops/gitops/dev-k8s/.images.env` alongside per-service variables (`AGENT_SERVICE_IMAGE`, `PLATFORM_GATEWAY_IMAGE`, …) consumed by the deploy step.

### Verification gate

`make verify` is the pre-commit/pre-push gate (documented in the root Makefile header) and runs everything locally and in CI:

1. `test` — iterates `PYTHON_PRODUCTS`, running each product's `make test`.
2. `overlays` — `kustomize build` on every overlay under `shared/platform-ops/gitops/`.
3. `validate-dashboards` — validates OpenObserve dashboard JSON against schema and resolves every metric reference to an emitted OTEL stream.
4. `validate-policy` — validates canonical policy bundle against JSON schema.
5. `validate-policy-scenarios` — evaluates scenario expectations against both engines (`api` and `tools`).
6. `validate-version` — enforces lockstep between root `VERSION`, every product's declared version, and the portal.
7. `validate-secret-vocabulary` — validates secret-literal lockstep across agent-platform, tool-gateway, skills-hub.
8. `validate-password-policy` — validates password-policy contract (SPEC-062 R-2).
9. `secret-delivery-demo` — local sample handoff proof.
10. `portal-test` — runs operator-portal unit suite + production build (no integration skip accepted).
11. `execution-failure-test` — crash-safety proof with disposable Postgres.

### Policy synchronization

Canonical policies live in `shared/shared-contracts/policies/` and are copied to consumers via `make sync-policy`: `policy-default.yaml` goes to `tool-gateway`, `platform-gateway`, and `shared/platform-ops/gitops/dev-k8s/base/shared/policy.yaml`; `password-policy.yaml` goes to `tool-gateway`. Consumers never author their own copy.

### Deployment

- `make deploy` — wraps `shared/platform-ops/gitops/dev-k8s/deploy.sh`.
- `make deploy-samples` / `undeploy-samples` — installs tutorial sample skills out-of-band (SPEC-050 R-11 keeps samples out of the base overlay).
- `make deploy-sample-app` / `undeploy-sample-app` — deploys the acme-admin sample application (SPEC-059 R-6); uses the coordinated `IMAGE_TAG` and asserts reachability before exiting 0.
- `make e2e` — runs demo scripts against a deployed cluster after port-forwards for `platform-gateway` and `identity-service`.

### Base image and reproducibility

- Shared base image `luban-aiops/base-uv:<tag>` is pinned to `BASE_UV_PYTHON_VERSION=3.12` and `BASE_UV_UV_VERSION=0.12.1` (defaults.mk) and built via `make base-images`.
- All Python products run `uv sync --frozen` — dependency resolution is locked to `uv.lock`.
- Operator-portal uses `npm ci --no-audit --no-fund` with a `package-lock.json`.
- Multi-stage Dockerfiles pin runtime images (`node:22-alpine`, `nginxinc/nginx-unprivileged:1.27-alpine`).

### Conventions observed

- Every product Makefile is a two-line shim: set `IMAGE_NAME`, include `../../mk/image.mk` and `../../mk/python.mk`.
- Dockerfiles for Python services follow the same shape: `FROM luban-aiops/base-uv:al2023`, `COPY --chown=app:app .python-version pyproject.toml uv.lock README.md ./`, `COPY src ./src`, `RUN uv sync --frozen --no-dev`, `EXPOSE 8000`, `CMD ["uv", "run", "<entrypoint>"]`.
- `IMAGE_PLATFORM ?= linux/amd64` is the default deployment target; `linux/arm64` is supported for native kind builds.
- `REGISTRY` is optional; when unset images stay local under `luban-aiops/<name>:<tag>`, when set they are re-tagged to `$(REGISTRY)/luban-aiops/<name>:<tag>`.
- `AUTO_LOAD_KIND=true` requires `KIND_CLUSTER_NAME` and loads all nine coordinated images into the named cluster after `make build`.
- Dockerfile linting falls back from `hadolint` to `docker run hadolint/hadolint` if the binary is not installed.
- The operator-portal SPA is excluded from `PYTHON_PRODUCTS` and `make test`; it is covered separately by `make portal-test` (SPEC-063 R-8c).

### Not present

No GitHub Actions workflow, CircleCI config, or other CI YAML was found under `.github/` — only `ISSUE_TEMPLATE/` and `pull_request_template.md`. There are no `build*.sh` scripts at the repo root; orchestration lives entirely in the Makefile.