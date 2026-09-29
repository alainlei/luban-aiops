---
kind: configuration_system
name: Environment-Driven Frozen Dataclass Settings with Kustomize Runtime Profiles
category: configuration_system
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/core/config.py
    - products/agent-platform/src/agent_service/runtime_settings.py
    - products/incident-service/src/incident_service/core/config.py
    - products/skills-hub/src/skills_hub/core/config.py
    - products/audit-service/src/audit_service/core/config.py
    - products/identity-broker/src/identity_service/core/config.py
    - shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env
    - shared/platform-ops/gitops/dev-k8s/base/agent-platform/runtime-config.env
    - shared/platform-ops/gitops/runtime-profiles/default/configmap.yaml
---

## Approach

Luban's services use a uniform, framework-free configuration pattern: each product service defines frozen `dataclass` settings objects in `src/<service>/core/config.py`, reads values exclusively from environment variables via `os.getenv`, exposes a module-level `get_settings()` cached through `functools.lru_cache(maxsize=1)`, and validates fields in `__post_init__`. There is no Pydantic, no `.env` file loader, no YAML config parser — configuration is pure env → dataclass.

The agent-platform deviates slightly by keeping its large runtime surface in `runtime_settings.RuntimeSettings` (a ~600-line frozen dataclass with nested provider-specific options) and exposing it through `core.config.get_settings()`, while other services keep everything in one `config.py`.

## Key Files

- `products/agent-platform/src/agent_service/core/config.py` — thin `@lru_cache` wrapper around `RuntimeSettings.from_env()`
- `products/agent-platform/src/agent_service/runtime_settings.py` — the canonical `RuntimeSettings` dataclass, all AGENT* / AGENTSCOPE* env parsing, validation, and defaults
- `products/incident-service/src/incident_service/core/config.py` — `IncidentSettings` + `parse_query_clients` / `parse_workload_clients` / `parse_connectors`
- `products/skills-hub/src/skills_hub/core/config.py` — `SkillsSettings` + JSON-based `parse_sources` / `parse_git_tokens` / `parse_composition_max_sub_skills`
- `products/audit-service/src/audit_service/core/config.py` — `AuditSettings`
- `products/identity-broker/src/identity_service/core/config.py` — `IdentitySettings`
- `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env` — shared ConfigMap keys (`OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `IDENTITY_SERVICE_URL`) mounted into every pod
- `shared/platform-ops/gitops/dev-k8s/base/*/runtime-config.env` — per-service deployment env files (e.g. `agent-platform/runtime-config.env`)
- `shared/platform-ops/gitops/runtime-profiles/default/configmap.yaml` — profile ConfigMap that sets `AGENTSCOPE_PROFILE`, `AGENTSCOPE_PROVIDER`, `AGENTSCOPE_MODEL_NAME`, `AGENTSCOPE_BASE_URL`
- `shared/platform-ops/gitops/runtime-profiles/README.md` — runtime-profile selection mechanism

## Architecture & Conventions

1. **Frozen dataclasses as immutable settings.** Every settings class is declared `@dataclass(frozen=True)` so callers cannot mutate runtime state after startup.
2. **Env-only source of truth.** Values come from `os.getenv(name, default)`; there is no file fallback, no precedence chain between files/env vars, and no secret manager SDK inside the Python code.
3. **Typed helpers for env coercion.** The agent-platform defines `_optional_str`, `_optional_int`, `_optional_float`, `_optional_bool`, `_optional_choice` — booleans accept `{1,true,yes,on}` and `{0,false,no,off}`, raising `ValueError` on unknown strings. Other services implement their own parsers (e.g. `parse_query_clients`, `parse_sources`).
4. **Module-level cached accessor.** Each service exports `get_settings()` decorated with `@lru_cache(maxsize=1)` so the parsed settings object is constructed once at first import.
5. **Validation in `__post_init__`.** Range checks, cross-field dependencies, and type assertions live in `__post_init__`; invalid configuration raises `ValueError` at import time, causing the service to fail fast during startup rather than later at request time.
6. **Per-feature opt-in knobs.** Many settings are boolean flags defaulting to `False` (e.g. `kernel_tracing`, `task_tools_enabled`, `compress_context_enabled`, `model_discovery_enabled`, `execution_admission_enabled`) so new features ship disabled unless explicitly enabled by an operator.
7. **Fail-closed dependency wiring.** Optional inter-service URLs (`audit_service_url`, `incident_service_url`, `skills_service_url`, `tool_gateway_url`) default to `None`; when required for a feature, missing values cause startup failure or a closed error path (e.g. `execution_rejected`, reason `worker_unavailable`), never a silent degradation.
8. **Provider-conditional options.** `RuntimeSettings._provider_options_from_env` dispatches on `AGENTSCOPE_PROVIDER` (`dashscope`, `deepseek`, `openai`, `luban`) to build typed provider option dataclasses (`DashScopeOptions`, `DeepSeekOptions`, `OpenAIOptions`), validated against `SUPPORTED_RUNTIME_PROVIDERS`.
9. **Kustomize overlay delivery.** Environment variables are delivered to pods via Kustomize:
   - Per-service `base/<service>/runtime-config.env` files are mounted as env sources in the Deployment.
   - Shared keys go through `base/shared/runtime.env`.
   - Profile-specific overrides (provider, model, base URL) are applied via the `runtime-profiles/<name>/configmap.yaml` ConfigMap selected by `select-runtime-profile.sh`.
   - Secrets ride separate `runtime-secrets.example.env` files and are provisioned by `sync-*-secrets.sh` scripts into Kubernetes Secrets (never committed).
10. **Consistent naming prefixes.** Service-scoped env vars use uppercase prefixes matching the service name: `AGENTSCOPE_*` / `AGENT_*` for agent-platform, `INCIDENT_*` for incident-service, `SKILLS_*` for skills-hub, `AUDIT_*` for audit-service, `IDENTITY_*` for identity-broker. Cross-service endpoints use unscoped names like `TOOL_GATEWAY_URL`, `IDENTITY_SERVICE_URL`, `OTEL_EXPORTER_OTLP_ENDPOINT`.
11. **`SettingsError` exception type.** Services that parse complex multi-value env vars (skills-hub, incident-service) define a local `SettingsError` subclass raised on malformed input, distinguishing configuration errors from generic `ValueError`s.

## Conventions & Constraints

- Settings classes are frozen dataclasses loaded from environment variables only — no `.env` file support, no YAML/TOML config files read at runtime.
- `get_settings()` is cached with `lru_cache(maxsize=1)`; callers must not call `from_env()` directly outside tests.
- Boolean env values accept case-insensitive `{1,true,yes,on}` and `{0,false,no,off}`; any other string raises `ValueError`.
- Provider selection is constrained to the set `("dashscope", "deepseek", "openai", "luban")` defined in `SUPPORTED_RUNTIME_PROVIDERS`; unsupported values raise `ValueError` during `RuntimeSettings.from_env()`.
- Kernel tuning bounds are enforced in `__post_init__`: `max_iters >= 1`, `context_trigger_ratio ∈ (0, 0.9)`, `tool_result_limit >= 1`, `model_max_retries >= 0`, `reply_token_budget > 0` when set, `reply_input/output_token_weight >= 0`, `execution_worker_timeout_seconds ∈ (0, 120]`, `authoring_trace_max_steps >= 1`, `skill_graduation_max_steps >= 1`.
- Enabling `execution_admission_enabled` requires both `AGENT_EXECUTION_STATE_DB_URL` and `AGENT_EXECUTION_ADMISSION_EPOCH` to be set; otherwise startup fails.
- Enabling compression (`AGENTSCOPE_COMPRESS_CONTEXT_ENABLED`) requires `AGENTSCOPE_CONTEXT_TRIGGER_RATIO > 0.2` (agentscope's internal `context_buffer_ratio`).
- Timezone values are validated against Python's `zoneinfo.ZoneInfo`; invalid IANA timezone names raise `ValueError`.
- Skills sources are validated at parse time: `source_id` must match `[a-z0-9][a-z0-9-]*`, duplicates are rejected, `local` sources require `path`, `git` sources require `url`, and git `path` must be relative (no leading `/` or `..`).
- Composition sub-skill count (`SKILLS_COMPOSITION_MAX_SUB_SKILLS`) must be ≥ 1; zero or negative values raise `SettingsError`.
- Inter-service client credentials follow a consistent triple: `<SERVICE>_URL`, `<SERVICE>_CLIENT_ID`, `<SERVICE>_CLIENT_SECRET` (e.g. `AGENT_AUDIT_SERVICE_URL` / `AGENT_AUDIT_CLIENT_ID` / `AGENT_AUDIT_CLIENT_SECRET`).
- Secrets are never embedded in `runtime-config.env`; they are provisioned separately by `sync-*-secrets.sh` scripts into Kubernetes Secrets referenced by the deployments.