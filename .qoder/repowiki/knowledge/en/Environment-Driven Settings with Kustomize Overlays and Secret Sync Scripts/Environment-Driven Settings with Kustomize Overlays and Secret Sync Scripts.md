---
kind: configuration_system
name: Environment-Driven Settings with Kustomize Overlays and Secret Sync Scripts
category: configuration_system
scope:
    - '**'
source_files:
    - docs/guides/configuration-reference.md
    - products/platform-gateway/src/platform_gateway/core/config.py
    - products/tool-gateway/src/tool_gateway/core/config.py
    - products/agent-platform/src/agent_service/core/config.py
    - shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env
    - shared/shared-contracts/policies/policy-default.yaml
    - shared/platform-ops/gitops/sync-audit-secrets.sh
    - shared/platform-ops/gitops/sync-delegation-secrets.sh
    - shared/platform-ops/gitops/sync-skills-secrets.sh
    - shared/platform-ops/gitops/sync-execution-signing-secret.sh
    - shared/platform-ops/gitops/sync-email-secrets.sh
    - shared/platform-ops/gitops/sync-otel-secrets.sh
---

## What system/approach is used

The platform uses a **pure environment-variable configuration model** — no YAML/JSON config files are read at runtime by services. Each Python service defines a frozen `dataclass` (or Pydantic-style `RuntimeSettings`) in its `core/config.py` / `runtime_settings.py`, reads values via `os.getenv()` with typed defaults, and exposes them through an `@lru_cache(maxsize=1)`-wrapped `get_settings()` accessor that is imported once at process start. There is no hot reload; changing a ConfigMap or Secret requires a pod restart.

Configuration is layered through **Kustomize overlays** under `shared/platform-ops/gitops/dev-k8s/base/<service>/runtime-config.env` plus per-service `runtime-secrets.example.env` files. Shared variables live in `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env`. Feature flags (e.g. `GATEWAY_BROWSER_ENABLED`, `GATEWAY_MUTATING_TOOLS_ENABLED`, `AGENT_EXECUTION_ADMISSION_ENABLED`) are boolean env vars parsed as truthy strings (`"1"|"true"|"yes"|"on"`).

Secrets are provisioned imperatively by shell scripts under `shared/platform-ops/gitops/sync-*.sh` (e.g. `sync-audit-secrets.sh`, `sync-delegation-secrets.sh`, `sync-skills-secrets.sh`, `sync-execution-signing-secret.sh`, `sync-email-secrets.sh`, `sync-otel-secrets.sh`) which generate random values and create Kubernetes `Secret` objects consumed via `secretKeyRef` mounts or env injection. Secrets are never committed to Git; only `.example.env` templates exist in the repo.

Policy bundles are the one non-env configuration artifact: the canonical file `shared/shared-contracts/policies/policy-default.yaml` is synced byte-identically into both gateways' packaged defaults and the dev overlay via `make sync-policy`; consumers load it from the path given by `PLATFORM_GATEWAY_POLICY_PATH` / `GATEWAY_POLICY_PATH` (default `/etc/luban/policy/policy.yaml`). A missing or invalid bundle fails startup with `PolicyLoadError` — there is no silent fallback.

## Key files and packages

- Per-service settings modules:
  - `products/platform-gateway/src/platform_gateway/core/config.py` — `PlatformGatewaySettings` dataclass + `get_settings()`
  - `products/tool-gateway/src/tool_gateway/core/config.py` — `GatewaySettings` dataclass + `get_settings()`
  - `products/agent-platform/src/agent_service/core/config.py` — thin `get_settings()` wrapping `RuntimeSettings.from_env()`
  - `products/execution-runtime/src/execution_runtime/core/config.py`
  - `products/identity-broker/src/identity_service/core/config.py`
  - `products/audit-service/src/audit_service/core/config.py`
  - `products/skills-hub/src/skills_hub/core/config.py`
  - `products/incident-service/src/incident_service/core/config.py`
- Shared runtime env: `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env`
- Per-service runtime env fragments: `shared/platform-ops/gitops/dev-k8s/base/<service>/runtime-config.env`
- Policy bundle: `shared/shared-contracts/policies/policy-default.yaml` (canonical), replicated to `products/*/policies/policy-default.yaml` and `shared/platform-ops/gitops/dev-k8s/base/shared/policy.yaml`
- Secret provisioning scripts: `shared/platform-ops/gitops/sync-*.sh`
- Authoritative cross-service variable map: `docs/guides/configuration-reference.md`

## Architecture and conventions

1. **Single source of truth per setting**: each env var has exactly one owning service documented in `configuration-reference.md` with its default, type constraints, and whether it lives in `runtime-config` (ConfigMap) or `runtime-secrets` (Secret).
2. **Deny-by-default feature toggles**: optional connectors (browser, HTTP, secrets, mutating tools, Elastic) are `false`/empty by default and must be explicitly enabled via env vars before they register any tool or connector.
3. **Cross-service secret contracts**: inter-service auth uses paired client_id/client_secret pairs (token delegation, audit ingestion, skills query, incident query). Each consumer stores its own `_CLIENT_SECRET`; the server registers the matching entry in a registry env var (e.g. `AUDIT_INGEST_CLIENTS`, `SKILLS_QUERY_CLIENTS`, `IDENTITY_SERVICE_CLIENTS`, `INCIDENT_QUERY_CLIENTS`). The `sync-*.sh` scripts keep these pairs in sync.
4. **Typed validation at construction**: `__post_init__` on `GatewaySettings` enforces allowed backend names (`memory|redis`), positive TTLs, port ranges, and password-policy overrides that may only tighten (never weaken) the contract floor. Unknown store backends fail startup.
5. **Caching**: `get_settings()` is cached via `functools.lru_cache(maxsize=1)` so the process reads env once at import/startup time. Tests call `config.get_settings.cache_clear()` between runs.
6. **Profile-based LLM configuration**: agent-service selects an LLM provider via `AGENTSCOPE_PROVIDER` / `AGENTSCOPE_PROFILE` / `AGENTSCOPE_*` env vars mounted from a Kustomize profile ConfigMap; multi-model catalogs add `<PROVIDER>_API_KEY` / `<PROVIDER>_MODEL_NAME` / `<PROVIDER>_BASE_URL` / `<PROVIDER>_MODELS` knobs.
7. **Durable admission epochs**: execution admission uses an externally managed UUID epoch (`AGENT_EXECUTION_ADMISSION_EPOCH` / `EXECUTION_ADMISSION_EPOCH`) that must match across agent-service, execution-runtime, and the Postgres catalog; mismatch refuses dispatch.

## Conventions and constraints

- **No runtime config files for services**: services do not read application YAML/JSON at runtime; all behavior is driven by environment variables defined in the `configuration-reference.md` table.
- **Secrets are immutable per deployment**: provisioned via `sync-*.sh` scripts that generate random values; existing secrets are reused unless explicitly rotated. Scripts opt out via `SKIP_*_SECRETS=true`.
- **Policy drift is enforced**: `make verify` fails if the canonical policy bundle diverges from the replicas consumed by both gateways; edits must go through `make sync-policy`.
- **Feature activation requires all required variables set**: the "Feature Activation Matrix" in `configuration-reference.md` states that a capability is active only when every listed required variable is set to a non-empty value; unset URLs leave routes fail-closed (503) rather than degrading silently.
- **Audit delivery degrades gracefully**: unset `*_AUDIT_SERVICE_URL` falls back to log-only auditing; unreachable audit-service does not block user requests.
- **OpenTelemetry headers are secret-mounted**: `OTEL_EXPORTER_OTLP_HEADERS` lives in each service's runtime-secrets Secret and is provisioned by `sync-otel-secrets.sh`; without it exporters push anonymously and OpenObserve returns 401.
- **Browser/HTTP credential sets are file-mounted only**: `GATEWAY_BROWSER_CREDENTIAL_SETS` / `GATEWAY_HTTP_CREDENTIAL_SETS` point to a JSON file path; inline credential values are never accepted via env vars.