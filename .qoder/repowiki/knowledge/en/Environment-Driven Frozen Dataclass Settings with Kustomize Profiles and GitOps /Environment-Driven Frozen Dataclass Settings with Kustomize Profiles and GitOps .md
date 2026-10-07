---
kind: configuration_system
name: Environment-Driven Frozen Dataclass Settings with Kustomize Profiles and GitOps Secret Provisioning
category: configuration_system
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/runtime_settings.py
    - products/tool-gateway/src/tool_gateway/core/config.py
    - products/platform-gateway/src/platform_gateway/core/config.py
    - products/audit-service/src/audit_service/core/config.py
    - products/execution-runtime/src/execution_runtime/core/config.py
    - products/identity-broker/src/identity_service/core/config.py
    - products/incident-service/src/incident_service/core/config.py
    - docs/guides/configuration-reference.md
    - shared/platform-ops/gitops/select-runtime-profile.sh
---

## Approach

Luban has no centralized configuration framework. Each FastAPI product owns its own settings module under `src/<service>/core/config.py` (or `runtime_settings.py` for agent-platform), which defines a **frozen `dataclass`** plus a `from_env()` classmethod that reads values from `os.environ`. A process-wide `@lru_cache(maxsize=1)` accessor (`get_settings()`) is the single entry point used by the service's `app.py`/`main.py` bootstrap.

There is no `.env` file loader, no Pydantic `BaseSettings`, no YAML/TOML config files consumed at runtime — environment variables are the sole source of truth. Configuration files in this repo are either Kubernetes manifests or documentation; runtime values come exclusively from K8s ConfigMaps and Secrets mounted as env vars.

## Key Files

- `products/agent-platform/src/agent_service/runtime_settings.py` — largest settings surface: `RuntimeSettings` + provider-specific `DashScopeOptions` / `DeepSeekOptions` / `OpenAIOptions` dataclasses, all parsed from `AGENTSCOPE_*`, `AGENT_*`, `DASHSCOPE_*`, `DEEPSEEK_*`, `OPENAI_*`, `LUBAN_*` env vars.
- `products/tool-gateway/src/tool_gateway/core/config.py` — `GatewaySettings` covering connectors (k8s, browser, http, secrets, elastic), policy path, redaction, audit, skills, incidents.
- `products/platform-gateway/src/platform_gateway/core/config.py` — `PlatformGatewaySettings` for upstream URLs, OIDC/JWKS, delegation, policy path, audit/incident/skills proxies.
- `products/audit-service/src/audit_service/core/config.py` — `AuditSettings` + `parse_ingest_clients` / `parse_workload_clients` helpers.
- `products/execution-runtime/src/execution_runtime/core/config.py` — `ExecutionSettings`.
- `products/identity-broker/src/identity_service/core/config.py` — `IdentitySettings`.
- `products/incident-service/src/incident_service/core/config.py` — `IncidentSettings`.
- `docs/guides/configuration-reference.md` — authoritative cross-service env-var matrix, secret contracts, feature activation table, and per-service variable tables.
- `shared/platform-ops/gitops/dev-k8s/base/<service>/runtime-config.env` — dev Kustomize overlays that set defaults for each service.
- `shared/platform-ops/gitops/select-runtime-profile.sh` — switches the active LLM profile ConfigMap for agent-platform.

## Architecture and Conventions

1. **Per-service frozen dataclass**: Every service defines one top-level `*Settings` frozen dataclass whose fields carry sensible defaults. The class is immutable once constructed.
2. **`from_env()` constructor**: All parsing lives in a single classmethod that maps env vars to typed fields. Boolean parsing uses the canonical truthy set `{"1", "true", "yes", "on"}` (defined locally as `_TRUTHY` or inline).
3. **Process-wide caching**: `get_settings()` wraps `from_env()` in `functools.lru_cache(maxsize=1)`, so the process reads env vars exactly once at import/bootstrap time.
4. **Validation in `__post_init__`**: Range checks, cross-field constraints, and IANA timezone validation live in `__post_init__`, raising `ValueError` on startup rather than failing later. Examples include `context_trigger_ratio < 0.9`, `execution_worker_timeout_seconds <= 120`, `browser_flow_approval_ttl >= 0`, and password-policy overrides being allowed only to *tighten* the contract floor.
5. **Typed helper parsers**: Small reusable helpers like `_optional_str`, `_optional_int`, `_optional_bool`, `_optional_choice`, `_env_optional_tuple`, `parse_ingest_clients`, `parse_positive_int` centralize common env-parsing patterns.
6. **Feature flags via env vars**: Optional capabilities (browser connector, HTTP connector, secrets connector, mutating tools, model discovery, compression tool, task tools, kernel tracing, workload identity, durable admission) are toggled through dedicated boolean env vars, defaulting to off/deny-by-default.
7. **Secrets vs config separation**: Non-secret knobs go into `runtime-config.env` (ConfigMap); secrets go into per-service `*-runtime-secrets` K8s Secrets. The `configuration-reference.md` marks each variable's source column as `runtime-config` or `runtime-secrets`.
8. **Cross-service client registries**: Consumers register a `client_id` and `client_secret`; the target service exposes an `*_CLIENTS` registry env var (e.g. `AUDIT_INGEST_CLIENTS`, `SKILLS_QUERY_CLIENTS`, `INCIDENT_QUERY_CLIENTS`, `IDENTITY_SERVICE_CLIENTS`) parsed as comma-separated `key=value` pairs.
9. **Kustomize profiles**: Agent-platform supports pluggable LLM backends via Kustomize profile overlays selected by `select-runtime-profile.sh`; the profile label is decoupled from the provider since SPEC-026.
10. **Policy bundle as code**: The action-authorization policy is a single canonical YAML (`shared/shared-contracts/policies/policy-default.yaml`) synced to both gateways' packaged defaults and the dev overlay via `make sync-policy`; drift fails `make verify`.
11. **Provisioning scripts**: Cross-service secrets are generated and applied by shell scripts under `shared/platform-ops/gitops/` (`sync-delegation-secrets.sh`, `sync-audit-secrets.sh`, `sync-skills-secrets.sh`, `sync-incident-secrets.sh`, `sync-execution-signing-secret.sh`, `sync-execution-handoff-secret.sh`, `sync-otel-secrets.sh`, `sync-email-secrets.sh`).

## Conventions and Constraints

- **No framework**: There is no dotenv, pydantic-settings, or config-file parser. All runtime configuration comes from `os.getenv`.
- **Boolean env vars** accept only `1`, `true`, `yes`, `on` (case-insensitive, stripped); any other non-empty value raises `ValueError`.
- **Unknown store backends fail startup**: `SESSION_STORE_BACKEND`, `AGENT_STATE_STORE_BACKEND`, `AUDIT_STORE_BACKEND`, `SKILLS_STORE_BACKEND`, `INCIDENT_STORE_BACKEND` reject unknown values at parse time.
- **Deny-by-default posture**: Browser, HTTP, secrets, and mutating-tool connectors are disabled unless explicitly enabled; origin allowlists default to empty (deny-all).
- **Missing required secrets fail closed**: Absent `AGENT_EXECUTION_SIGNING_KEY`, `AGENT_EXECUTION_HANDOFF_TOKEN`, `OIDC_CLIENT_SECRET`, or `PLATFORM_GATEWAY_SERVICE_CLIENT_SECRET` cause the relevant operation to refuse (not degrade to unauthenticated execution). Missing `AUDIT_*_SERVICE_URL` falls back to log-only auditing.
- **Cross-field invariants enforced in `__post_init__`**: e.g., enabling `execution_admission_enabled` requires both `execution_state_db_url` and `execution_admission_epoch`; enabling compression requires `context_trigger_ratio > 0.2` (agentscope's `context_buffer_ratio`); `provider_options` type must match `provider`.
- **Policy bundle cannot be edited in place**: Editing a replica instead of `shared/shared-contracts/policies/policy-default.yaml` causes `make verify` to fail; hot reload is intentionally not supported — changed bundles take effect on pod restart.
- **Secrets are never committed**: The reference document states "Secrets are provisioned as Kubernetes Secret objects, never committed to Git" and documents each secret's provisioning script.
- **Configuration reference is authoritative**: `docs/guides/configuration-reference.md` is the definitive cross-service dependency map and is kept in sync with the code via the per-service `Source:` comments pointing back to the owning `config.py`.