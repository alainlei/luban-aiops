---
kind: configuration_system
name: Environment-Driven Settings with Frozen Dataclasses and Kustomize Profiles
category: configuration_system
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/runtime_settings.py
    - products/tool-gateway/src/tool_gateway/core/config.py
    - products/platform-gateway/src/platform_gateway/core/config.py
    - products/execution-runtime/src/execution_runtime/core/config.py
    - products/identity-broker/src/identity_service/core/config.py
    - products/audit-service/src/audit_service/core/config.py
    - products/skills-hub/src/skills_hub/core/config.py
    - products/incident-service/src/incident_service/core/config.py
    - docs/guides/configuration-reference.md
    - shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env
    - shared/platform-ops/gitops/dev-k8s/base/agent-platform/runtime-config.env
    - shared/platform-ops/gitops/dev-k8s/base/tool-gateway/runtime-config.env
    - shared/platform-ops/gitops/dev-k8s/base/platform-gateway/runtime-config.env
    - shared/shared-contracts/policies/policy-default.yaml
---

## Approach

Luban has no third-party configuration framework. Every service loads its runtime settings exclusively from environment variables via `os.getenv`, wrapped in Python `dataclass(frozen=True)` models with a `from_env()` classmethod and an `@lru_cache(maxsize=1)`-decorated `get_settings()` accessor. There is no Pydantic, no `.env` file loader, no YAML/JSON config parser for runtime values — the only non-env configuration files are static policy bundles (`policy-default.yaml`) mounted at a path.

The canonical cross-service variable map lives in `docs/guides/configuration-reference.md`; each service's `core/config.py` (or `runtime_settings.py` for agent-platform) is the authoritative implementation source cited by that document.

## Key Files

- `products/agent-platform/src/agent_service/runtime_settings.py` — largest settings model; frozen dataclass with extensive `__post_init__` validation, per-provider option classes (`DashScopeOptions`, `DeepSeekOptions`, `OpenAIOptions`), and ~60 env vars under the `AGENTSCOPE_*`, `AGENT_*`, `TOOL_GATEWAY_URL` namespaces.
- `products/tool-gateway/src/tool_gateway/core/config.py` — `GatewaySettings` with connector switches (`browser_enabled`, `http_enabled`, `secrets_enabled`, `k8s_enabled`, `mutating_tools_enabled`) and password-policy tightening validation in `__post_init__`.
- `products/platform-gateway/src/platform_gateway/core/config.py` — `PlatformGatewaySettings`, smallest model, cached via `get_settings()`.
- `products/execution-runtime/src/execution_runtime/core/config.py`, `products/identity-broker/src/identity_service/core/config.py`, `products/audit-service/src/audit_service/core/config.py`, `products/skills-hub/src/skills_hub/core/config.py`, `products/incident-service/src/incident_service/core/config.py` — analogous patterns.
- `shared/platform-ops/gitops/dev-k8s/base/<service>/runtime-config.env` — per-service default env values applied by Kustomize overlays.
- `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env` — shared variables (`OTEL_ENABLED`, `IDENTITY_SERVICE_URL`).
- `shared/platform-ops/gitops/dev-k8s/base/*/runtime-secrets.example.env` — secret key inventory (not actual secrets).
- `docs/guides/configuration-reference.md` — definitive cross-service dependency map, feature activation matrix, secret contracts, and per-service tables.

## Architecture and Conventions

### Per-service frozen dataclass settings
Each service defines one frozen dataclass (e.g. `RuntimeSettings`, `GatewaySettings`, `PlatformGatewaySettings`) whose fields are all optional or have safe defaults. `from_env()` maps every `os.getenv(...)` call to a field; `get_settings()` wraps it in `@lru_cache(maxsize=1)` so the process-level singleton is built once on first access.

### Validation in `__post_init__`
Validation is centralized in `__post_init__` rather than per-field validators. It raises `ValueError` with human-readable messages referencing the SPEC number when applicable (e.g. `SPEC-027 R-5`, `SPEC-038 R-4`, `SPEC-063 R-2a`). This enforces startup-time failure for invalid ranges: e.g. `AGENT_EXECUTION_WORKER_TIMEOUT_SECONDS` must be > 0 and <= 120; `AGENTSCOPE_CONTEXT_TRIGGER_RATIO` must be in (0, 0.9); `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` requires `context_trigger_ratio > 0.2`.

### Boolean parsing convention
Booleans accept the set `{"1", "true", "yes", "on"}` (lowercased, stripped). The agent-platform module centralizes this in `_optional_bool`; other services inline the same pattern.

### Optional vs required semantics
Optional fields return `None` when unset and use typed defaults otherwise. Required dependencies (e.g. `AGENT_EXECUTION_SIGNING_KEY`, `AGENT_EXECUTION_HANDOFF_TOKEN`, `AGENT_EXECUTION_STATE_DB_URL` + `AGENT_EXECUTION_ADMISSION_EPOCH`) fail closed at startup or at invocation time rather than degrading silently — documented extensively in comments and the configuration reference.

### Secrets separation
Secrets are never embedded in `runtime-config.env`. They live in Kubernetes `Secret` objects provisioned by scripts like `sync-delegation-secrets.sh`, `sync-audit-secrets.sh`, `sync-skills-secrets.sh`, `sync-execution-signing-secret.sh`, `sync-execution-handoff-secret.sh`, `sync-incident-secrets.sh`, `sync-browser-credentials.sh`, `sync-email-secrets.sh`, `sync-otel-secrets.sh`. Each service's `runtime-secrets.example.env` documents which keys it consumes.

### Kustomize profile overlays
Agent LLM backends are selected via Kustomize profiles (`default` → `deepseek-v4-flash`). Profile switching is done through `shared/platform-ops/gitops/select-runtime-profile.sh <profile-name>`. Two permanent postures (`mutating-dev`, `browser-dev`) merge additional env into `platform-runtime-config` and are not switchable.

### Policy bundle as code
The action-authorization bundle has exactly one canonical copy: `shared/shared-contracts/policies/policy-default.yaml`. It is replicated byte-identically to both gateways' packaged defaults and the dev-k8s overlay via `make sync-policy`. Drift fails `make verify`. Consumers load it from a path (`GATEWAY_POLICY_PATH`, `PLATFORM_GATEWAY_POLICY_PATH`); a missing or invalid bundle fails startup (`PolicyLoadError`, no silent fallback).

### Cross-service contract documentation
`configuration-reference.md` is the single source of truth for operators: it lists every variable, default, owning service, and provisioning script, plus diagrams of token delegation, identity verification, tool relay, mutating-action approval, audit ingestion, skills retrieval, and incident intake chains.

## Conventions and Constraints

- **No external config library**: All runtime configuration is loaded from `os.getenv`; there is no Pydantic `BaseSettings`, python-dotenv, or YAML/JSON config parser for runtime values.
- **Frozen dataclasses**: Settings models are `@dataclass(frozen=True)`, making them immutable after construction and forcing any derived state into methods or properties.
- **Process-level caching**: `get_settings()` uses `@lru_cache(maxsize=1)` so settings are parsed once per process.
- **Boolean normalization**: All boolean env vars accept only `1|true|yes|on` (case-insensitive, stripped); anything else is rejected or treated as false depending on the helper used.
- **Fail-fast validation**: Invalid ranges, unsupported choices, and inconsistent combinations raise `ValueError` during `__post_init__`, causing pod startup to fail rather than running misconfigured.
- **Deny-by-default feature flags**: Browser tools (`GATEWAY_BROWSER_ENABLED=false`), HTTP tools (`GATEWAY_HTTP_ENABLED=false`), secrets delivery (`GATEWAY_SECRETS_ENABLED=false`), mutating tools (`GATEWAY_MUTATING_TOOLS_ENABLED=false`), and workload identity are all disabled unless explicitly enabled.
- **Secrets via K8s Secrets only**: No secret value appears in Git; provisioning is done through `sync-*` scripts referenced in the configuration reference.
- **Policy bundle immutability**: Editing replicas directly is forbidden; changes go through `shared/shared-contracts/policies/policy-default.yaml` followed by `make sync-policy` and `make verify`.
- **Cross-service secret contracts**: Shared secrets (delegation, audit, skills, incidents) require matching client_id/client_secret pairs across producer and consumer services, documented as explicit contracts in `configuration-reference.md`.
- **Configuration reference as spec**: The `docs/guides/configuration-reference.md` table of contents cites each service's `core/config.py` as the source of truth for its variable section, tying documentation to implementation.