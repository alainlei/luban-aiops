---
kind: configuration_system
name: Environment-Driven Frozen Dataclass Configuration System
category: configuration_system
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/runtime_settings.py
    - products/tool-gateway/src/tool_gateway/core/config.py
    - products/platform-gateway/src/platform_gateway/core/config.py
    - products/execution-runtime/src/execution_runtime/core/config.py
    - docs/guides/configuration-reference.md
    - shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env
---

## Approach

Luban uses a uniform, framework-free configuration system across all nine services: each service defines one frozen `dataclass` settings object with a `from_env()` classmethod that reads values from `os.getenv`, validates them in `__post_init__`, and exposes the instance through an `lru_cache(maxsize=1)`-memoized `get_settings()` accessor. There is no use of Pydantic `BaseSettings`, `pydantic-settings`, `dynaconf`, or any external config library — configuration is plain Python dataclasses backed by environment variables.

The only exception is `agent_service/runtime_settings.py`, which also contains a large embedded default system prompt (`DEFAULT_SYSTEM_PROMPT`) and per-provider option dataclasses (`DashScopeOptions`, `DeepSeekOptions`, `OpenAIOptions`), but it follows the same pattern: frozen dataclass + `from_env()` + validation in `__post_init__`.

## Key Files

- `products/agent-platform/src/agent_service/runtime_settings.py` — `RuntimeSettings` (609 lines); the largest settings object, covering LLM providers, kernel tuning, HITL, evidence caps, model discovery, execution handoff, audit/incident/skills clients, authoring traces, and graduation bounds.
- `products/tool-gateway/src/tool_gateway/core/config.py` — `GatewaySettings`; browser connector, HTTP connector, secrets/password-policy, email delivery, Elastic, K8s tool toggles.
- `products/platform-gateway/src/platform_gateway/core/config.py` — `PlatformGatewaySettings`; identity broker, token audiences, policy path, audit/incident/skills proxy URLs.
- `products/execution-runtime/src/execution_runtime/core/config.py` — `ExecutionSettings`; signing key, handoff token, admission epoch, gateway timeout.
- `products/identity-broker/src/identity_service/core/config.py`
- `products/audit-service/src/audit_service/core/config.py`
- `products/skills-hub/src/skills_hub/core/config.py`
- `products/incident-service/src/incident_service/core/config.py`
- `docs/guides/configuration-reference.md` — authoritative cross-service environment variable dependency map, secret contracts, feature activation matrix, and per-service tables.
- `shared/platform-ops/gitops/dev-k8s/base/<service>/runtime-config.env` — per-service runtime ConfigMap source files used by dev-k8s.
- `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env` — shared variables (`OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `IDENTITY_SERVICE_URL`).

## Architecture and Conventions

### One settings class per service
Each service has exactly one settings module under `src/<service_name>/core/config.py` (or `runtime_settings.py` for agent-service) defining a single frozen dataclass. The class name convention is `<ServiceName>Settings` (e.g. `PlatformGatewaySettings`, `GatewaySettings`, `ExecutionSettings`, `RuntimeSettings`).

### Environment-only loading
All values come from `os.getenv(name, default)`. There is no file-based config loader at application startup; YAML/TOML/env files are mounted as Kubernetes Secrets/ConfigMaps and surfaced to the process as environment variables. The `configuration-reference.md` documents every variable, its default, and whether it comes from `runtime-config` (ConfigMap) or `runtime-secrets` (Secret).

### Validation in `__post_init__`
Every settings class validates ranges, allowed values, and cross-field invariants in `__post_init__`, raising `ValueError` with a human-readable message. Examples:
- `RuntimeSettings`: `max_iters >= 1`, `context_trigger_ratio ∈ (0, 0.9)`, `AGENTSCOPE_TIMEZONE` must be a valid IANA timezone, `execution_admission_enabled` requires both `execution_state_db_url` and `execution_admission_epoch`, `browser_flow_approval_ttl >= 0`, `execution_worker_timeout_seconds ∈ (0, 120]`.
- `GatewaySettings`: `secret_delivery_backend ∈ {memory, redis}`, ports in 1–65535, password-policy overrides may only tighten the contract (validated against the canonical `tools/password_policy.py` store).
- `ExecutionSettings`: `gateway_timeout_seconds ∈ (0, 30]`, `state_store_backend ∈ {memory, postgres}`.

### Boolean parsing convention
Booleans accept the case-insensitive set `{"1", "true", "yes", "on"}`. Both `platform_gateway.core.config._env_bool` and `tool_gateway.core.config._env_bool` implement this explicitly; `agent_service.runtime_settings._optional_bool` adds the same set plus rejects unknown values with `ValueError(f"{name} must be a boolean value.")`.

### Optional helpers
Services define small private helpers for typed env access:
- `_optional_str` / `_optional_int` / `_optional_float` / `_optional_bool` / `_optional_choice` in agent-service.
- `_env_bool` / `_env_optional_int` / `_env_optional_tuple` in tool-gateway.
- A local `_secret` helper in execution-runtime that strips whitespace and returns `None` for empty strings.

### Memoized singleton accessor
Each settings module exposes `@lru_cache(maxsize=1)`-decorated `get_settings()` so callers import once and get a process-wide frozen snapshot. This is the standard accessor used throughout each service.

### Feature flags via env vars
Feature activation is entirely env-driven. The `configuration-reference.md` "Feature Activation Matrix" maps capabilities to required variables. Most features are opt-in with `false` defaults (e.g. `GATEWAY_BROWSER_ENABLED`, `GATEWAY_HTTP_ENABLED`, `GATEWAY_SECRETS_ENABLED`, `AGENT_EXECUTION_ADMISSION_ENABLED`, `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED`). Deny-by-default is the norm: empty origin allowlists deny all browser/HTTP requests; unset mutating tools are absent from discovery.

### Secret separation
Secrets live in Kubernetes `Secret` objects provisioned by scripts (`sync-delegation-secrets.sh`, `sync-audit-secrets.sh`, `sync-skills-secrets.sh`, `sync-incident-secrets.sh`, `sync-execution-signing-secret.sh`, `sync-execution-handoff-secret.sh`, `sync-otel-secrets.sh`, `sync-browser-credentials.sh`). They are never committed to Git. The `configuration-reference.md` documents every `*-runtime-secrets` Secret and its keys.

### Cross-service contracts
Many env vars form cross-service contracts documented in `configuration-reference.md`:
- Token delegation: `PLATFORM_GATEWAY_SERVICE_CLIENT_SECRET` ↔ `IDENTITY_SERVICE_CLIENTS` entry.
- Audit ingestion: `*_AUDIT_CLIENT_SECRET` ↔ `AUDIT_INGEST_CLIENTS` registry.
- Skills query: `GATEWAY_SKILLS_CLIENT_SECRET` ↔ `SKILLS_QUERY_CLIENTS`.
- Incident query: `*_INCIDENT_CLIENT_SECRET` ↔ `INCIDENT_QUERY_CLIENTS`.
- Execution signing: `AGENT_EXECUTION_SIGNING_KEY` ↔ `EXECUTION_SIGNING_KEY`.
- Handoff token: `AGENT_EXECUTION_HANDOFF_TOKEN` ↔ `EXECUTION_HANDOFF_TOKEN`.

### Policy bundle
Policy is not loaded from env; it is read from a file path (`GATEWAY_POLICY_PATH`, `PLATFORM_GATEWAY_POLICY_PATH`) pointing to `/etc/luban/policy/policy.yaml`. The canonical copy is `shared/shared-contracts/policies/policy-default.yaml`, replicated byte-identically to both gateways' packaged defaults and the dev-k8s overlay via `make sync-policy`. A missing or invalid bundle fails startup (`PolicyLoadError`, no silent fallback). Consumers expose a SHA-256 fingerprint on `/health/ready` for provenance verification.

### Runtime profiles
Agent-service supports pluggable LLM backends through Kustomize profile overlays selected by `shared/platform-ops/gitops/select-runtime-profile.sh <profile-name>`. Profiles are decoupled from providers since SPEC-026: the active profile label is generic (`default`) and provider selection is a ConfigMap knob (`AGENTSCOPE_PROVIDER`). Two non-LLM postures (`mutating-dev`, `browser-dev`) merge their env into `platform-runtime-config` permanently.

## Conventions and Constraints

- **Convention:** Each service's configuration lives in `src/<service>/core/config.py` (or `runtime_settings.py`) as a frozen `dataclass` with `from_env()` and `get_settings()`.
- **Convention:** All configuration is sourced from environment variables via `os.getenv`; no file-based config parser is used at runtime.
- **Convention:** Boolean env vars accept `1|true|yes|on` (case-insensitive); unknown boolean values raise `ValueError`.
- **Convention:** Optional string env vars return `None` when unset or blank after stripping.
- **Convention:** Feature flags default to `false` (deny-by-default); enabling a capability requires setting multiple related env vars.
- **Convention:** Secrets are provisioned as Kubernetes `Secret` objects via `sync-*-secrets.sh` scripts and mounted as env vars; they are never committed to Git.
- **Constraint:** Missing or invalid policy bundles fail startup — there is no silent fallback to a packaged default (enforced by the policy engine, documented in `configuration-reference.md`).
- **Constraint:** Enabling `AGENT_EXECUTION_ADMISSION_ENABLED` requires both `AGENT_EXECUTION_STATE_DB_URL` and `AGENT_EXECUTION_ADMISSION_EPOCH`; otherwise startup raises `ValueError` (enforced in `RuntimeSettings.__post_init__`).
- **Constraint:** `AGENT_EXECUTION_WORKER_TIMEOUT_SECONDS` must be > 0 and ≤ 120 (SPEC-038 R-4 cap); enforced in `RuntimeSettings.__post_init__`.
- **Constraint:** `GATEWAY_PASSWORD_MIN_LENGTH` and `GATEWAY_PASSWORD_REQUIRED_CLASSES` may only tighten the canonical policy floor; weakening overrides raise `ValueError` (SPEC-062 R-2/R-7, enforced in `GatewaySettings.__post_init__`).
- **Constraint:** Unknown `EXECUTION_STATE_STORE_BACKEND` values fail startup (enforced in `ExecutionSettings.__post_init__`).
- **Constraint:** `AGENTSCOPE_TIMEZONE` must be a valid IANA timezone (validated via `zoneinfo.ZoneInfo` in `RuntimeSettings.__post_init__`).
- **Constraint:** `AGENTSCOPE_CONTEXT_TRIGGER_RATIO` must be strictly greater than agentscope's internal `context_buffer_ratio` (0.2) when `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED=true` (SPEC-064 R-2, enforced in `RuntimeSettings.__post_init__`).
- **Constraint:** Cross-service secret contracts (delegation, audit, skills, incidents, execution signing/handoff) are enforced at the receiving service's auth layer — mismatched client IDs/secrets result in 401/403, not graceful degradation.