---
kind: configuration_system
name: Environment-Based Configuration System Across Services
category: configuration_system
scope:
    - '**'
source_files:
    - docs/guides/configuration-reference.md
    - products/agent-platform/src/agent_service/core/env.py
    - products/agent-platform/src/agent_service/runtime_settings.py
    - products/platform-gateway/src/platform_gateway/core/config.py
    - products/tool-gateway/src/tool_gateway/core/config.py
    - products/execution-runtime/src/execution_runtime/core/config.py
    - products/audit-service/src/audit_service/core/config.py
    - products/identity-broker/src/identity_service/core/config.py
    - products/skills-hub/src/skills_hub/core/config.py
    - products/incident-service/src/incident_service/core/config.py
    - shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env
    - shared/shared-contracts/policies/policy-default.yaml
---

## Approach

The Luban platform has no centralized configuration framework. Each of the nine Python services defines its own frozen `dataclass` settings object, loaded from environment variables at import time via a module-level `@lru_cache(maxsize=1)`-wrapped `get_settings()` accessor. There is no `.env` file loader, no YAML/JSON config parser for runtime values, and no feature-flag library — configuration is purely `os.environ` + typed validation.

Configuration sources are layered by Kubernetes:

1. **Service-specific `runtime-config.env`** files under `shared/platform-ops/gitops/dev-k8s/base/<service>/runtime-config.env` (ConfigMap-mounted).
2. **Profile overlays** (`mutating-dev`, `browser-dev`) that merge additional env into `platform-runtime-config`.
3. **Runtime secrets** as K8s `Secret` objects mounted as env vars or files (e.g. `execution-signing-secret`, `execution-handoff-secret`, `tool-gateway-browser-credentials`).
4. **Shared runtime env** at `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env` for cross-service constants like `OTEL_*` and `IDENTITY_SERVICE_URL`.
5. **Packaged defaults** embedded in each service's image (policy bundles, password policy contract) used when the corresponding path env var is empty.
6. **Policy bundle** (`shared/shared-contracts/policies/policy-default.yaml`) is the single canonical source; `make sync-policy` replicates it byte-identically to both gateway images and the dev overlay, with `make verify` enforcing copy parity.

## Key Files

- `docs/guides/configuration-reference.md` — authoritative cross-service variable map, secret contracts, dependency chains, and per-service tables.
- `products/agent-platform/src/agent_service/core/env.py` — shared helpers `get_env_value` / `get_env_int` (fallback-name lookup).
- `products/agent-platform/src/agent_service/runtime_settings.py` — `RuntimeSettings` dataclass with provider options, kernel tuning, HITL, evidence caps, execution worker/admission, skills/incident clients, authoring-trace bounds, and extensive `__post_init__` validation.
- `products/platform-gateway/src/platform_gateway/core/config.py` — `PlatformGatewaySettings` (JWT audience, delegation, audit, incident, skills, workspace proxies).
- `products/tool-gateway/src/tool_gateway/core/config.py` — `GatewaySettings` (K8s connector, browser/HTTP connectors, secrets delivery, email, redaction, elastic).
- `products/execution-runtime/src/execution_runtime/core/config.py` — `ExecutionSettings` (signing key, handoff token, admission epoch).
- `products/audit-service/src/audit_service/core/config.py`, `products/identity-broker/src/identity_service/core/config.py`, `products/skills-hub/src/skills_hub/core/config.py`, `products/incident-service/src/incident_service/core/config.py` — analogous per-service settings modules.
- `shared/platform-ops/gitops/dev-k8s/base/*/runtime-config.env` — per-service default env values.
- `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env` — shared constants.
- `shared/shared-contracts/policies/policy-default.yaml` — canonical policy bundle.

## Architecture and Conventions

### Settings dataclasses
Every service exposes a frozen `dataclass` named `<Service>Settings` with a `from_env()` classmethod and an `@lru_cache(maxsize=1)` `get_settings()` function. The cache ensures one parse per process lifetime. Fields carry sensible defaults matching the packaged image behavior; unset env vars fall back to those defaults rather than raising.

### Validation strategy
Validation lives in `__post_init__` (or `RuntimeSettings.__post_init__`), not during parsing. This separates "parse env → construct" from "validate semantics." Common checks include:
- Enum allowlists (store backends: `memory` | `postgres`; providers: `dashscope` | `deepseek` | `openai` | `luban`).
- Numeric ranges (timeouts > 0, bounded by spec constraints).
- Cross-field invariants (admission enabled requires DSN + epoch; compression tool requires `context_trigger_ratio > 0.2`).
- IANA timezone validation via `zoneinfo.ZoneInfo`.
Invalid values raise `ValueError` at startup — there is no silent fallback for core knobs.

### Boolean parsing
Boolean env vars accept case-insensitive `{"1", "true", "yes", "on"}`; agent-service additionally supports `{"0", "false", "no", "off"}` and raises on unknown strings.

### Secret vs non-secret distinction
Secrets are never committed to Git. They are provisioned as K8s Secrets and injected as env vars or mounted files. The documentation distinguishes `**runtime-secrets**` entries (e.g. API keys, client secrets, OTLP headers) from plain `runtime-config` entries. Some secrets are read through optional `secretKeyRef` so an absent secret fails closed rather than degrading (e.g. `AGENT_EXECUTION_SIGNING_KEY`, `AGENT_EXECUTION_HANDOFF_TOKEN`).

### Feature gating
Capabilities are opt-in via boolean env flags with deny-by-default posture: `GATEWAY_MUTATING_TOOLS_ENABLED=false`, `GATEWAY_BROWSER_ENABLED=false`, `GATEWAY_HTTP_ENABLED=false`, `GATEWAY_SECRETS_ENABLED=false`, `EXECUTION_ADMISSION_ENABLED=false`. An unset URL typically disables the corresponding connector or route (fail-closed 503) rather than enabling it.

### Policy bundle workflow
The canonical policy file is `shared/shared-contracts/policies/policy-default.yaml`. Editing it requires bumping its `version` field, updating `policy-scenarios.yaml` if grants change, running `make sync-policy`, then `make verify` (schema check + scenario guard + copy-parity). Consumers load the path from `PLATFORM_GATEWAY_POLICY_PATH` / `GATEWAY_POLICY_PATH` (default `/etc/luban/policy/policy.yaml`); a missing or invalid bundle fails startup with `PolicyLoadError` — no silent fallback to the packaged default.

### Runtime profiles
Agent-service supports pluggable LLM backends via Kustomize profile overlays selected with `shared/platform-ops/gitops/select-runtime-profile.sh <profile-name>`. Only one profile is active at a time; since SPEC-026 the profile label is decoupled from the provider, which is selected via `AGENTSCOPE_PROVIDER`. Two permanent postures (`mutating-dev`, `browser-dev`) merge extra env but are not switchable.

### Cross-service secret contracts
Inter-service authentication uses paired client_id/client_secret pairs registered in a central registry on the server side (e.g. `AUDIT_INGEST_CLIENTS`, `SKILLS_QUERY_CLIENTS`, `INCIDENT_QUERY_CLIENTS`, `IDENTITY_SERVICE_CLIENTS`). Provisioning scripts (`sync-audit-secrets.sh`, `sync-delegation-secrets.sh`, `sync-skills-secrets.sh`, `sync-incident-secrets.sh`, `sync-execution-signing-secret.sh`, `sync-execution-handoff-secret.sh`, `sync-email-secrets.sh`, `sync-otel-secrets.sh`, `sync-browser-credentials.sh`) generate random secrets and write the corresponding K8s Secrets. Many support a `SKIP_*_SECRETS=true` opt-out.

## Conventions and Constraints

- Every service loads configuration exclusively from environment variables via `os.getenv`; no `.env` file parsing, no Pydantic settings, no YAML/JSON runtime config files for service knobs.
- Settings objects are `frozen=True` dataclasses with defaults mirroring packaged-image behavior; `from_env()` is the sole constructor.
- A module-level `@lru_cache(maxsize=1)` `get_settings()` provides process-wide singleton access.
- Startup-time `__post_init__` validation rejects invalid enums, out-of-range numbers, and inconsistent cross-field combinations with `ValueError`.
- Feature flags are boolean env vars parsed against `{1,true,yes,on}` (with stricter variants in agent-service); defaults are deny-by-default for security-sensitive features.
- Secrets live only in K8s Secrets, never in Git; provisioning is done via `sync-*` scripts invoked by `make deploy`.
- The policy bundle has exactly one canonical copy (`shared/shared-contracts/policies/policy-default.yaml`); `make sync-policy` and `make verify` enforce byte-identical replicas across consumers.
- Missing critical secrets (execution signing key, handoff token) fail closed at startup or invocation — they do not degrade to unauthenticated operation.
- Unset service URLs for optional dependencies (audit, skills, incidents) disable the connector or route (fail-closed 503) rather than enabling them with defaults.
- The `configuration-reference.md` document is the definitive cross-service variable map and secret contract reference; new variables should be added there alongside their service's settings module.