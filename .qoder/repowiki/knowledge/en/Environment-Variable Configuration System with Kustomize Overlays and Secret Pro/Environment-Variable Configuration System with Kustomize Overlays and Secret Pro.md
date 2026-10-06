---
kind: configuration_system
name: Environment-Variable Configuration System with Kustomize Overlays and Secret Provisioning Scripts
category: configuration_system
scope:
    - '**'
source_files:
    - docs/guides/configuration-reference.md
    - products/agent-platform/src/agent_service/runtime_settings.py
    - products/tool-gateway/src/tool_gateway/core/config.py
    - products/platform-gateway/src/platform_gateway/core/config.py
    - products/execution-runtime/src/execution_runtime/core/config.py
    - products/identity-broker/src/identity_service/core/config.py
    - products/audit-service/src/audit_service/core/config.py
    - products/skills-hub/src/skills_hub/core/config.py
    - products/incident-service/src/incident_service/core/config.py
    - shared/platform-ops/gitops/dev-k8s/base/tool-gateway/runtime-config.env
    - shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env
    - shared/platform-ops/gitops/sync-delegation-secrets.sh
    - shared/platform-ops/gitops/sync-audit-secrets.sh
    - shared/platform-ops/gitops/sync-skills-secrets.sh
    - shared/platform-ops/gitops/sync-incident-secrets.sh
    - shared/platform-ops/gitops/sync-execution-signing-secret.sh
    - shared/platform-ops/gitops/sync-execution-handoff-secret.sh
    - shared/platform-ops/gitops/sync-browser-credentials.sh
    - shared/platform-ops/gitops/sync-email-secrets.sh
    - shared/platform-ops/gitops/sync-otel-secrets.sh
    - shared/platform-ops/gitops/select-runtime-profile.sh
    - shared/shared-contracts/policies/policy-default.yaml
---

## Approach

Luban's configuration system is **purely environment-variable driven** — there is no YAML/JSON config loader inside services. Each Python service owns a `core/config.py` (or `runtime_settings.py`) that reads `os.environ` into a frozen `dataclass`, validates it in `__post_init__`, and exposes a process-wide singleton via an `lru_cache`-decorated `get_settings()` function. There is no framework abstraction (no pydantic-settings, python-dotenv, dynaconf); the parsing helpers (`_optional_str/int/float/bool/_choice`, `_env_bool`, `_env_optional_tuple`) are hand-written per module.

Configuration is layered through **Kustomize overlays** under `shared/platform-ops/gitops/dev-k8s/base/<service>/runtime-config.env` plus per-service `runtime-secrets.example.env`. A separate set of shell scripts under `shared/platform-ops/gitops/sync-*.sh` generates shared secrets and applies them as Kubernetes `Secret` objects; these scripts are the authoritative provisioning surface for cross-service credentials.

## Key Files and Packages

- Per-service configuration loaders:
  - `products/agent-platform/src/agent_service/runtime_settings.py` — `RuntimeSettings` dataclass, `from_env()`, validation in `__post_init__`
  - `products/tool-gateway/src/tool_gateway/core/config.py` — `GatewaySettings`, `get_settings()`
  - `products/platform-gateway/src/platform_gateway/core/config.py`
  - `products/execution-runtime/src/execution_runtime/core/config.py`
  - `products/identity-broker/src/identity_service/core/config.py`
  - `products/audit-service/src/audit_service/core/config.py`
  - `products/skills-hub/src/skills_hub/core/config.py`
  - `products/incident-service/src/incident_service/core/config.py`
- Canonical operator documentation: `docs/guides/configuration-reference.md` (841 lines, the definitive cross-service env-var dependency map)
- Dev-Kubernetes base configs: `shared/platform-ops/gitops/dev-k8s/base/<service>/runtime-config.env` and `runtime-secrets.example.env`
- Shared runtime: `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env` (OTLP endpoint, identity URL)
- Secret provisioning scripts: `shared/platform-ops/gitops/sync-delegation-secrets.sh`, `sync-audit-secrets.sh`, `sync-skills-secrets.sh`, `sync-incident-secrets.sh`, `sync-execution-signing-secret.sh`, `sync-execution-handoff-secret.sh`, `sync-browser-credentials.sh`, `sync-email-secrets.sh`, `sync-otel-secrets.sh`, `sync-runtime-secret.sh`
- Runtime profile overlays: `shared/platform-ops/gitops/runtime-profiles/{default,mutating-dev,browser-dev,secrets-dev}/`
- Policy bundle canonical source: `shared/shared-contracts/policies/policy-default.yaml` (synced to both gateways and dev overlay by `make sync-policy`)

## Architecture and Conventions

### Layering model

1. **Code defaults** live as default arguments on the frozen dataclass fields (e.g. `GATEWAY_K8S_ENABLED = False`, `AGENT_HITL_CONFIRM_TIMEOUT = 600`). These define the deny-by-default posture.
2. **Service-level env overrides** come from `runtime-config.env` files mounted as ConfigMaps. They override code defaults but never contain secrets.
3. **Secrets** are injected via Kubernetes Secrets mounted as env vars (or secretKeyRef) and documented in `runtime-secrets.example.env` templates.
4. **Cross-service contracts** (client_id/client_secret pairs, JWT audiences, JWKS URLs) are coordinated by `sync-*.sh` scripts that write matching values into two or more `*-runtime-secrets` files and then `kubectl apply` + `rollout restart` the affected deployments.
5. **Feature activation** is opt-in via boolean env vars (`GATEWAY_MUTATING_TOOLS_ENABLED`, `GATEWAY_BROWSER_ENABLED`, `GATEWAY_HTTP_ENABLED`, `GATEWAY_SECRETS_ENABLED`, `AGENT_EXECUTION_ADMISSION_ENABLED`). Disabled features register no tools/connectors and return `TOOL_NOT_FOUND` / fail-closed routes.
6. **Runtime profiles** (`select-runtime-profile.sh`) layer additional env files on top of the base: `mutating-dev` enables pod-delete RBAC + mutating tools; `browser-dev` enables browser/HTTP connectors + chromium sidecar. Neither is switchable at runtime.
7. **Policy bundles** have exactly one canonical copy (`shared/shared-contracts/policies/policy-default.yaml`), replicated byte-identically to both gateway engines and the dev overlay by `make sync-policy`; contract tests enforce parity.

### Validation strategy

Validation is performed eagerly at import/startup time in `__post_init__` or `from_env`, raising `ValueError` with a human-readable message. Examples:
- `AGENTSCOPE_CONTEXT_TRIGGER_RATIO` must be in `(0, 0.9)`
- `AGENT_EXECUTION_WORKER_TIMEOUT_SECONDS` must be > 0 and ≤ 120
- `GATEWAY_SECRET_DELIVERY_BACKEND` must be `memory` or `redis`
- Password policy overrides may only *tighten* the contract floor (weakening raises)
- Unknown `SESSION_STORE_BACKEND` / `AGENT_STATE_STORE_BACKEND` values fail startup
- IANA timezone names are validated via `zoneinfo.ZoneInfo`

### Cross-service credential contracts

All inter-service authentication follows the same shape: a client registers a `<SERVICE>_CLIENT_ID` / `<SERVICE>_CLIENT_SECRET` pair, and the server maintains a registry string like `AUDIT_INGEST_CLIENTS=client_id=secret,...` or `SKILLS_QUERY_CLIENTS=...`. The `configuration-reference.md` documents every chain (token delegation, audit ingestion, skills retrieval, incident intake, identity verification).

### Secrets handling

Secrets are **never committed to Git**. They are generated by `sync-*.sh` scripts (e.g. `openssl rand -hex 24` for delegation secrets) and applied via `kubectl create secret generic ... --from-env-file=...`. Some scripts preserve existing keys (e.g. `OTEL_EXPORTER_OTLP_HEADERS`) when rewriting the `.env` file. `SKIP_*_SECRETS=true` env vars let CI skip provisioning when secrets are injected externally.

### Documentation-driven configuration

The single source of truth for operators is `docs/guides/configuration-reference.md`, which enumerates every variable per service, its default, source (runtime-config vs runtime-secrets vs code default), and cross-service dependency chains. It also documents the seven secret contracts (`agent-platform-runtime-secrets`, `execution-signing-secret`, `execution-handoff-secret`, `platform-gateway-runtime-secrets`, `identity-service-runtime-secrets`, `tool-gateway-runtime-secrets`, `tool-gateway-browser-credentials`, `audit-service-runtime-secrets`, `skills-hub-runtime-secrets`, `incident-service-runtime-secrets`).

## Conventions and Constraints

- Every service defines its settings as a **frozen `dataclass`** with a `from_env()` classmethod and a `get_settings()` `@lru_cache(maxsize=1)` singleton — observed in `tool_gateway.core.config.GatewaySettings` and mirrored across other services.
- Boolean env vars accept `{"1", "true", "yes", "on"}` (case-insensitive, stripped) — implemented in per-module `_env_bool` / `_optional_bool` helpers.
- Feature switches are **deny-by-default**: `GATEWAY_MUTATING_TOOLS_ENABLED=false`, `GATEWAY_BROWSER_ENABLED=false`, `GATEWAY_HTTP_ENABLED=false`, `GATEWAY_SECRETS_ENABLED=false` in the base `runtime-config.env`; enabling requires explicit opt-in plus matching policy grants and, for mutating/browser/HTTP tools, `AGENT_HITL_CONFIRM_TIMEOUT>0` on agent-service.
- Origin allowlists (`GATEWAY_BROWSER_ALLOW_ORIGINS`, `GATEWAY_HTTP_ALLOW_ORIGINS`) are empty by default, which denies all requests — enforced at the connector level, not just the env parser.
- Missing required secrets (e.g. `AGENT_EXECUTION_SIGNING_KEY`, `AGENT_EXECUTION_HANDOFF_TOKEN`, `INCIDENT_WEBHOOK_TOKEN`) cause **fail-closed behavior** (rejected execution, 503 routes, webhook disabled) rather than silent degradation — enforced by the setting constructors and route handlers.
- Audit delivery degrades to log-only when `*_AUDIT_SERVICE_URL` is unset — fire-and-forget, never blocking user requests.
- Policy bundle loading fails startup (`PolicyLoadError`) if the configured path is missing or invalid — no silent fallback to the packaged default.
- Runtime profiles are selected via `shared/platform-ops/gitops/select-runtime-profile.sh <profile-name>`; the active profile label is decoupled from the LLM provider since SPEC-026.
- The policy bundle workflow is enforced by `make verify`: editing the canonical `policy-default.yaml` requires bumping its `version` field, updating `policy-scenarios.yaml` for new grants, running `make sync-policy`, and committing all replicas together — `make verify` fails on any drift between the canonical file and the two gateway copies plus the dev overlay.