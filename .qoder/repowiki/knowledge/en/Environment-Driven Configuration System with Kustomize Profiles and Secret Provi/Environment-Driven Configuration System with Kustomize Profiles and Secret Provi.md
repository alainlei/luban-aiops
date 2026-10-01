---
kind: configuration_system
name: Environment-Driven Configuration System with Kustomize Profiles and Secret Provisioning
category: configuration_system
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/runtime_settings.py
    - products/platform-gateway/src/platform_gateway/core/config.py
    - products/execution-runtime/src/execution_runtime/core/config.py
    - products/identity-broker/src/identity_service/core/config.py
    - products/audit-service/src/audit_service/core/config.py
    - products/skills-hub/src/skills_hub/core/config.py
    - products/incident-service/src/incident_service/core/config.py
    - products/tool-gateway/src/tool_gateway/core/config.py
    - shared/platform-ops/gitops/dev-k8s/base/agent-platform/runtime-config.env
    - shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env
    - shared/platform-ops/gitops/select-runtime-profile.sh
    - shared/platform-ops/gitops/sync-audit-secrets.sh
    - shared/platform-ops/gitops/sync-delegation-secrets.sh
    - shared/platform-ops/gitops/sync-skills-secrets.sh
    - shared/platform-ops/gitops/sync-execution-signing-secret.sh
    - shared/platform-ops/gitops/sync-execution-handoff-secret.sh
    - shared/platform-ops/gitops/sync-incident-secrets.sh
    - shared/platform-ops/gitops/sync-otel-secrets.sh
    - shared/platform-ops/gitops/sync-browser-credentials.sh
    - shared/platform-ops/gitops/sync-email-secrets.sh
    - shared/platform-ops/gitops/sync-runtime-secret.sh
    - shared/shared-contracts/policies/policy-default.yaml
    - docs/guides/configuration-reference.md
---

# Configuration System

Luban's configuration system is **purely environment-variable driven** at runtime, layered on top of Kubernetes ConfigMaps/Secrets and Kustomize profiles for deployment-time composition. There is no YAML-based application configuration loader; each service parses `os.getenv` into frozen dataclasses.

## Approach and Frameworks

- **Runtime loading**: Python `dataclass(frozen=True)` settings objects with a `from_env()` classmethod per service. No third-party config library (Pydantic, dynaconf, etc.) — only stdlib `os.getenv`, `zoneinfo`, and `functools.lru_cache`.
- **Validation**: Per-field validation lives in `__post_init__` raising `ValueError` with human-readable messages tied to SPEC numbers. Unknown backend names fail startup via explicit allowlists.
- **Caching**: Services expose a module-level `get_settings()` accessor decorated with `@lru_cache(maxsize=1)` so settings are parsed once per process.
- **Deployment composition**: Kustomize overlays under `shared/platform-ops/gitops/runtime-profiles/<profile>/` merge env files into a single `platform-runtime-config` ConfigMap. The active LLM profile is selected by `select-runtime-profile.sh`, which rewrites `dev-k8s/kustomization.yaml`.
- **Secret provisioning**: Dedicated shell scripts (`sync-audit-secrets.sh`, `sync-delegation-secrets.sh`, `sync-skills-secrets.sh`, `sync-execution-signing-secret.sh`, `sync-execution-handoff-secret.sh`, `sync-incident-secrets.sh`, `sync-otel-secrets.sh`, `sync-browser-credentials.sh`, `sync-email-secrets.sh`, `sync-runtime-secret.sh`) generate or rotate secrets and write them as K8s `Secret` objects. Secrets are never committed to Git.
- **Policy bundle**: A single canonical file `shared/shared-contracts/policies/policy-default.yaml` is replicated byte-identically to both gateways' packaged defaults and the dev overlay via `make sync-policy`; contract tests enforce copy parity.

## Key Files and Packages

| Area | Files |
|---|---|
| Agent-service settings (largest surface) | `products/agent-platform/src/agent_service/runtime_settings.py` |
| Platform-gateway settings | `products/platform-gateway/src/platform_gateway/core/config.py` |
| Execution-runtime settings | `products/execution-runtime/src/execution_runtime/core/config.py` |
| Identity-broker settings | `products/identity-broker/src/identity_service/core/config.py` |
| Audit-service settings | `products/audit-service/src/audit_service/core/config.py` |
| Skills-hub settings | `products/skills-hub/src/skills_hub/core/config.py` |
| Incident-service settings | `products/incident-service/src/incident_service/core/config.py` |
| Tool-gateway settings | `products/tool-gateway/src/tool_gateway/core/config.py` |
| Dev runtime env (agent-service) | `shared/platform-ops/gitops/dev-k8s/base/agent-platform/runtime-config.env` |
| Shared runtime env | `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env` |
| Profile selector | `shared/platform-ops/gitops/select-runtime-profile.sh` |
| Cross-service dependency map | `docs/guides/configuration-reference.md` |
| Canonical policy bundle | `shared/shared-contracts/policies/policy-default.yaml` |

## Architecture and Conventions

### Settings object pattern
Every service follows the same shape:

```python
@dataclass(frozen=True)
class ServiceSettings:
    field: Type = default
    @classmethod
    def from_env(cls) -> "ServiceSettings":
        return cls(field=os.getenv("SERVICE_FIELD", default))
    def __post_init__(self):
        if self.field < 0:
            raise ValueError("FIELD must be >= 0")

@lru_cache(maxsize=1)
def get_settings() -> ServiceSettings:
    return ServiceSettings.from_env()
```

The agent-service's `RuntimeSettings` is the most complex instance (~600 lines), modeling provider-specific options (`DashScopeOptions`, `DeepSeekOptions`, `OpenAIOptions`) through a union type `RuntimeProviderOptions` dispatched by `provider_options_type(provider)`.

### Environment variable naming conventions
- Service-scoped variables use an uppercase prefix matching the service: `AGENTSCOPE_*` (agent-service), `PLATFORM_GATEWAY_*` (platform-gateway), `GATEWAY_*` (tool-gateway), `IDENTITY_*` / `OIDC_*` (identity-broker), `AUDIT_*` (audit-service), `SKILLS_*` (skills-hub), `INCIDENT_*` (incident-service), `EXECUTION_*` (execution-runtime).
- Cross-service URLs follow `<SERVICE>_URL` (e.g. `TOOL_GATEWAY_URL`, `AGENT_SERVICE_URL`, `IDENTITY_SERVICE_URL`).
- Boolean flags accept `"1" | "true" | "yes" | "on"` (lowercased); unknown values raise `ValueError`.
- Comma-separated lists are split and stripped (e.g. `AGENT_EMAIL_RECIPIENT_ALLOWLIST`, `GATEWAY_BROWSER_ALLOW_ORIGINS`).

### Defaults and opt-in posture
Defaults are chosen to be **deny-by-default** and **fail-closed**:
- Mutating tools are disabled unless `GATEWAY_MUTATING_TOOLS_ENABLED=true`.
- Browser/HTTP connectors are disabled unless explicitly enabled.
- Durable execution admission is `false` by default and requires coordinated enablement at agent, worker, and catalog.
- Optional dependencies (audit-service, skills-hub, incident-service) degrade gracefully when unset rather than crashing, except where safety demands it (e.g. missing `AGENT_EXECUTION_SIGNING_KEY` refuses mutating resumes with `signing_unavailable`).

### Validation strategy
Validation is centralized in `RuntimeSettings.__post_init__` and covers:
- Range checks (`max_iters >= 1`, `context_trigger_ratio ∈ (0, 0.9)`, `model_discovery_refresh_seconds >= 1`, `execution_worker_timeout_seconds ∈ (0, 120]`).
- Cross-field invariants (enabling `execution_admission_enabled` requires both `execution_state_db_url` and `execution_admission_epoch`; enabling compression requires `context_trigger_ratio > 0.2`).
- Type/allowlist checks (`AGENTSCOPE_PROVIDER ∈ {dashscope, deepseek, openai, luban}`, `SESSION_STORE_BACKEND ∈ {memory, redis, postgres}`).
- IANA timezone validation via `zoneinfo.ZoneInfo`.

### Secret contracts
Cross-service secrets are paired client_id/client_secret registries:
- `IDENTITY_SERVICE_CLIENTS` — token delegation between platform-gateway ↔ identity-service.
- `AUDIT_INGEST_CLIENTS` — fire-and-forget audit ingestion from all services.
- `SKILLS_QUERY_CLIENTS` — skills-hub query authentication.
- `INCIDENT_QUERY_CLIENTS` — incident-service query authentication.
- Format is consistently `client_id=client_secret,...` (or `client_id:client_secret:audience1|audience2` for delegation).

### Runtime profiles
Three categories coexist:
1. **Switchable LLM provider profiles** under `runtime-profiles/<name>/` (e.g. `default` pointing to `deepseek`).
2. **Always-wired dev postures** (`mutating-dev`, `browser-dev`, `secrets-dev`) that cannot be deselected — they are merged alongside the active LLM profile.
3. The selector script rejects non-switchable names and unknown directories.

### Documentation contract
`docs/guides/configuration-reference.md` is the authoritative cross-service dependency map. Each service section cites its source file and dev-k8s config fragment, and every feature activation row documents required variables, owning services, and dev-k8s defaults. The document also diagrams cross-service chains (token delegation, tool relay, HITL approval, audit ingestion, skills retrieval, incident intake).

## Conventions and Constraints

- **Rule**: All runtime configuration comes from environment variables read via `os.getenv`; there is no `.env` file parser, YAML config loader, or hot-reload mechanism. Changes take effect only on pod restart.
- **Rule**: Unknown backend names (`SESSION_STORE_BACKEND`, `AGENT_STATE_STORE_BACKEND`, `AUDIT_STORE_BACKEND`, `SKILLS_STORE_BACKEND`, `INCIDENT_STORE_BACKEND`) fail startup rather than falling back silently.
- **Rule**: Policy bundles loaded from `PLATFORM_GATEWAY_POLICY_PATH` / `GATEWAY_POLICY_PATH` fail startup (`PolicyLoadError`) if missing or invalid — there is no silent fallback to the packaged default.
- **Rule**: Missing `AGENT_EXECUTION_SIGNING_KEY` fails mutating resume handling closed (`signing_unavailable`); missing `AGENT_EXECUTION_WORKER_URL` + `AGENT_EXECUTION_HANDOFF_TOKEN` fails closed (`worker_unavailable`). There is no in-process fallback path.
- **Rule**: Enabling `AGENT_EXECUTION_ADMISSION_ENABLED` requires both `AGENT_EXECUTION_STATE_DB_URL` and `AGENT_EXECUTION_ADMISSION_EPOCH`; partial configuration fails startup rather than degrading to legacy handoff.
- **Rule**: The canonical policy bundle at `shared/shared-contracts/policies/policy-default.yaml` must stay byte-identical to both gateway replicas and the dev overlay; `make verify` enforces this via contract tests.
- **Rule**: Secrets are provisioned exclusively through the `sync-*-secrets.sh` scripts and stored as Kubernetes `Secret` objects; none are committed to Git.
- **Rule**: The `select-runtime-profile.sh` script rejects `mutating-dev`, `browser-dev`, and `secrets-dev` as switchable profiles — these are always wired in regardless of the selected LLM profile.
- **Rule**: Feature activation is defined as "all required variables set to non-empty values" per the Feature Activation Matrix in the configuration reference; a partially configured optional dependency degrades according to the documented behavior (log-only audit, 503 for unconfigured downstream, or connector off).
- **Rule**: OpenTelemetry push is enabled by default (`OTEL_ENABLED=true`) and requires `OTEL_EXPORTER_OTLP_HEADERS` from runtime-secrets; without the header exporters push anonymously and OpenObserve returns 401, but the pipeline fails open rather than blocking requests.