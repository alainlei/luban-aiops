---
kind: configuration_system
name: Environment-Driven Runtime Configuration with Frozen Dataclass Settings and Kustomize Profiles
category: configuration_system
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/runtime_settings.py
    - products/tool-gateway/src/tool_gateway/core/config.py
    - products/platform-gateway/src/platform_gateway/core/config.py
    - docs/guides/configuration-reference.md
    - shared/platform-ops/gitops/dev-k8s/base/agent-platform/runtime-config.env
    - shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env
    - shared/platform-ops/gitops/runtime-profiles/default/configmap.yaml
    - shared/platform-ops/gitops/select-runtime-profile.sh
    - shared/platform-ops/gitops/sync-delegation-secrets.sh
    - shared/platform-ops/gitops/sync-audit-secrets.sh
    - shared/platform-ops/gitops/sync-skills-secrets.sh
    - shared/platform-ops/gitops/sync-execution-signing-secret.sh
    - shared/platform-ops/gitops/sync-execution-handoff-secret.sh
    - shared/platform-ops/gitops/sync-otel-secrets.sh
---

## Approach

The Luban platform uses a uniform, code-first configuration system across all six Python services. Each service defines its own frozen `dataclass` settings object (e.g. `RuntimeSettings`, `PlatformGatewaySettings`, `GatewaySettings`) that reads exclusively from environment variables via `os.getenv`. There is no `.env` file loader, no YAML/JSON config parser for runtime values, and no feature-flag framework — configuration is purely environment-driven, validated at startup, and cached process-wide.

Configuration sources are layered in this order:
1. **Code defaults** — hard-coded default values on the dataclass fields.
2. **Kustomize profile overlays** — `shared/platform-ops/gitops/runtime-profiles/{default,mutating-dev,browser-dev}/` merge additional env into the active profile's ConfigMap; profiles are selected with `select-runtime-profile.sh`.
3. **Service-specific `runtime-config.env` files** under `shared/platform-ops/gitops/dev-k8s/base/<service>/runtime-config.env` — one per service, mounted as a Kubernetes ConfigMap.
4. **Shared `runtime.env`** under `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env` — shared knobs like `OTEL_ENABLED`, `IDENTITY_SERVICE_URL`.
5. **Kubernetes Secrets** — mounted as environment variables or file mounts (e.g. `GATEWAY_BROWSER_CREDENTIAL_SETS`, `OTEL_EXPORTER_OTLP_HEADERS`).

There is no hot reload: changing a ConfigMap requires a pod restart. The policy bundle is the only exception — it is loaded from a file path (`GATEWAY_POLICY_PATH`, `PLATFORM_GATEWAY_POLICY_PATH`) and can be replaced without redeploying the image, but the documentation explicitly states there is "deliberately no hot reload" and operators must rolling-restart gateways.

## Key Files

- `products/agent-platform/src/agent_service/runtime_settings.py` — largest settings class; parses ~60 env vars including LLM provider options, kernel tuning, execution handoff, audit/incident/skills client credentials, browser flow TTL, authoring-trace bounds, and skill graduation limits.
- `products/tool-gateway/src/tool_gateway/core/config.py` — gateway settings covering K8s connector, browser/HTTP connectors, secrets delivery, email, Elastic, redaction, and audit/skills/incidents clients.
- `products/platform-gateway/src/platform_gateway/core/config.py` — smaller settings for token audience/delegation, identity broker, policy path, and portal proxy URLs.
- `products/execution-runtime/src/execution_runtime/core/config.py`, `products/audit-service/src/audit_service/core/config.py`, `products/identity-broker/src/identity_service/core/config.py`, `products/incident-service/src/incident_service/core/config.py`, `products/skills-hub/src/skills_hub/core/config.py` — analogous per-service settings modules.
- `docs/guides/configuration-reference.md` — authoritative cross-service environment variable dependency map, secret contracts, feature activation matrix, and per-service tables.
- `shared/platform-ops/gitops/dev-k8s/base/*/runtime-config.env` — per-service deployment env.
- `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env` — shared env.
- `shared/platform-ops/gitops/runtime-profiles/` — Kustomize profile overlays (`default`, `mutating-dev`, `browser-dev`, `secrets-dev`).
- `shared/platform-ops/gitops/sync-*.sh` scripts — provisioners for delegation, audit, skills, incident, OTLP, browser credentials, execution signing/handoff, and runtime secrets.

## Architecture and Conventions

### Frozen dataclass settings
Every service exposes a single frozen `@dataclass` settings object with a `from_env()` classmethod and an `lru_cache(maxsize=1)`-wrapped `get_settings()` accessor. This makes settings immutable after construction and cached once per process.

### Validation in `__post_init__`
Validation lives in `__post_init__` rather than `from_env`, so invalid values fail startup with explicit `ValueError` messages referencing the relevant SPEC number. Examples include range checks (`AGENTSCOPE_MAX_ITERS >= 1`, `context_trigger_ratio ∈ (0, 0.9)`, `execution_worker_timeout_seconds ≤ 120`), IANA timezone validation via `zoneinfo.ZoneInfo`, and cross-field constraints (e.g. enabling `execution_admission_enabled` requires both `execution_state_db_url` and `execution_admission_epoch`).

### Boolean parsing convention
Booleans accept `1`, `true`, `yes`, `on` (case-insensitive). Some modules use a shared `_TRUTHY` set; agent-service uses a local `_optional_bool` helper that raises `ValueError` for unrecognized values.

### Optional vs required semantics
Optional fields return `None` when unset and are used to disable features (e.g. unset `*_AUDIT_SERVICE_URL` degrades to log-only auditing; unset `GATEWAY_SKILLS_SERVICE_URL` leaves the connector unregistered). Required dependencies either have sensible defaults or raise at startup — missing `AGENT_EXECUTION_SIGNING_KEY` fails mutating resumes closed (`signing_unavailable`), missing `AGENT_EXECUTION_WORKER_URL` + `AGENT_EXECUTION_HANDOFF_TOKEN` refuses execution (`worker_unavailable`), and missing `AGENT_INCIDENT_CLIENT_SECRET` returns 503.

### Cross-service secret contracts
Secrets are never committed to Git. They are provisioned by `sync-*.sh` scripts into named Kubernetes Secrets (`platform-gateway-runtime-secrets`, `tool-gateway-runtime-secrets`, `identity-service-runtime-secrets`, `audit-service-runtime-secrets`, `skills-hub-runtime-secrets`, `incident-service-runtime-secrets`, `execution-signing-secret`, `execution-handoff-secret`, `tool-gateway-browser-credentials`, `agent-platform-runtime-secrets`). Each consumer registers a `client_id` and `client_secret` pair against a registry owned by the target service (e.g. `AUDIT_INGEST_CLIENTS`, `SKILLS_QUERY_CLIENTS`, `INCIDENT_QUERY_CLIENTS`, `IDENTITY_SERVICE_CLIENTS`).

### Policy bundle as configuration-as-code
The action-authorization bundle has exactly one canonical copy: `shared/shared-contracts/policies/policy-default.yaml`. It is replicated byte-identically to both gateways' packaged defaults and the dev-k8s overlay via `make sync-policy`; contract tests fail `make verify` on drift. Consumers load it from a file path and expose a SHA-256 fingerprint of the exact loaded text on `/health/ready`.

### Feature flags
Feature toggles are plain environment variables (e.g. `GATEWAY_BROWSER_ENABLED`, `GATEWAY_HTTP_ENABLED`, `GATEWAY_SECRETS_ENABLED`, `AGENT_MODEL_DISCOVERY_ENABLED`, `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED`, `EXECUTION_ADMISSION_ENABLED`). Most are off-by-default (deny-by-default posture); dev overlays opt in selectively.

### Documentation as enforcement surface
`docs/guides/configuration-reference.md` is the definitive reference: every env var is documented with its purpose, default, source (code default / runtime-config / runtime-secrets), and cross-service dependency chain. The "Feature Activation Matrix" maps capabilities to required variables and their service(s).

## Conventions and Constraints

- **All runtime configuration comes from environment variables.** No `.env` file loader is used at runtime; `runtime-config.env` files are Kustomize inputs rendered into Kubernetes ConfigMaps.
- **Settings objects are frozen dataclasses** with `from_env()` and a cached `get_settings()` accessor — observed consistently in `platform_gateway.core.config`, `tool_gateway.core.config`, and mirrored by other services.
- **Validation belongs in `__post_init__`**, not in `from_env`, so misconfiguration fails startup with a descriptive `ValueError` referencing the governing SPEC.
- **Boolean parsing accepts `1|true|yes|on`** (case-insensitive); unknown boolean strings raise `ValueError` in agent-service's `_optional_bool`.
- **Features are opt-in by default.** Browser tools, HTTP tools, secrets delivery, mutating tools, live model discovery, context compression, and durable admission are all disabled unless explicitly enabled via env.
- **Missing optional dependencies degrade gracefully** (log-only audit, unregistered connector, 503 route), while critical security dependencies (execution signing key, worker handoff token, incident/skills client secrets) fail closed rather than silently downgrading.
- **Cross-service secrets are provisioned through `sync-*.sh` scripts** and mounted as Kubernetes Secrets; they are never embedded in images or committed to Git.
- **Policy bundles are synchronized from a single canonical file** (`shared/shared-contracts/policies/policy-default.yaml`) via `make sync-policy`; `make verify` enforces byte-identical copies across consumers.
- **No hot reload for policy bundles** — changes take effect only on pod restart, as stated in the configuration reference.
- **Profile selection is done via Kustomize overlays** under `shared/platform-ops/gitops/runtime-profiles/`, switched with `select-runtime-profile.sh`; `mutating-dev` and `browser-dev` are permanently merged alongside the active LLM profile.
- **OpenTelemetry headers** (`OTEL_EXPORTER_OTLP_HEADERS`) are treated as secret material and injected per-service via `sync-otel-secrets.sh`, not via the shared `runtime.env`.