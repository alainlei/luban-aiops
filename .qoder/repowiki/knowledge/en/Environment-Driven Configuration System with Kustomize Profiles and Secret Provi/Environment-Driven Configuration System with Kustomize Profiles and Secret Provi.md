---
kind: configuration_system
name: Environment-Driven Configuration System with Kustomize Profiles and Secret Provisioning
category: configuration_system
scope:
    - '**'
source_files:
    - docs/guides/configuration-reference.md
    - products/agent-platform/src/agent_service/runtime_settings.py
    - products/platform-gateway/src/platform_gateway/core/config.py
    - products/tool-gateway/src/tool_gateway/core/config.py
    - products/execution-runtime/src/execution_runtime/core/config.py
    - products/identity-broker/src/identity_service/core/config.py
    - products/audit-service/src/audit_service/core/config.py
    - products/incident-service/src/incident_service/core/config.py
    - products/skills-hub/src/skills_hub/core/config.py
    - shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env
    - shared/platform-ops/gitops/runtime-profiles/default/configmap.yaml
    - shared/platform-ops/gitops/runtime-profiles/browser-dev/browser.env
    - shared/platform-ops/gitops/runtime-profiles/mutating-dev/mutating.env
    - shared/platform-ops/gitops/select-runtime-profile.sh
    - shared/platform-ops/gitops/sync-delegation-secrets.sh
    - shared/platform-ops/gitops/sync-audit-secrets.sh
    - shared/platform-ops/gitops/sync-skills-secrets.sh
    - shared/platform-ops/gitops/sync-incident-secrets.sh
    - shared/platform-ops/gitops/sync-execution-signing-secret.sh
    - shared/platform-ops/gitops/sync-execution-handoff-secret.sh
---

# Configuration System

## Approach

The Luban platform has no configuration framework library (no Pydantic-settings, python-dotenv, or typed-config package). Each service reads its own configuration directly from `os.environ` via small, frozen `dataclass` settings modules that expose a `from_env()` constructor plus an `@lru_cache(maxsize=1) get_settings()` singleton. The system is therefore **pure environment-variable driven**, layered over Kubernetes ConfigMaps/Secrets and Kustomize profile overlays.

## Key Files

**Per-service settings loaders:**
- `products/agent-platform/src/agent_service/runtime_settings.py` — `RuntimeSettings.from_env()` parses ~50 `AGENT*` / `AGENTSCOPE_*` env vars; validates ranges in `__post_init__` (e.g. `context_trigger_ratio ∈ (0, 0.9)`, worker timeout ≤ 120s, IANA timezone).
- `products/platform-gateway/src/platform_gateway/core/config.py` — `PlatformGatewaySettings.from_env()` for `PLATFORM_GATEWAY_*` / `IDENTITY_*` / `*_AUDIT_*` / `*_INCIDENT_*` / `*_SKILLS_*` variables.
- `products/tool-gateway/src/tool_gateway/core/config.py` — `GatewaySettings.from_env()` for `GATEWAY_*` variables (browser, HTTP, secrets, elastic, audit, skills, incidents connectors); `__post_init__` enforces password-policy overrides can only tighten the contract.
- `products/execution-runtime/src/execution_runtime/core/config.py`
- `products/identity-broker/src/identity_service/core/config.py`
- `products/audit-service/src/audit_service/core/config.py`
- `products/incident-service/src/incident_service/core/config.py`
- `products/skills-hub/src/skills_hub/core/config.py`

**Kubernetes deployment manifests (per service):**
- `shared/platform-ops/gitops/dev-k8s/base/<service>/runtime-config.env` — non-secret env mounted as ConfigMap.
- `shared/platform-ops/gitops/dev-k8s/base/<service>/runtime-secrets.example.env` — template for per-service Secrets.
- `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env` — shared OTel + identity broker endpoint for every pod.

**Profile overlays (Kustomize):**
- `shared/platform-ops/gitops/runtime-profiles/default/` — default LLM provider ConfigMap.
- `shared/platform-ops/gitops/runtime-profiles/browser-dev/` — enables `GATEWAY_BROWSER_ENABLED=true` + chromium sidecar.
- `shared/platform-ops/gitops/runtime-profiles/mutating-dev/` — enables `GATEWAY_MUTATING_TOOLS_ENABLED=true` + pod-delete RBAC.
- `shared/platform-ops/gitops/select-runtime-profile.sh` — switches active profile.

**Secret provisioning scripts (top-level under `shared/platform-ops/gitops/`):**
`sync-delegation-secrets.sh`, `sync-audit-secrets.sh`, `sync-skills-secrets.sh`, `sync-incident-secrets.sh`, `sync-execution-signing-secret.sh`, `sync-execution-handoff-secret.sh`, `sync-browser-credentials.sh`, `sync-email-secrets.sh`, `sync-otel-secrets.sh`, `sync-runtime-secret.sh`.

**Authoritative documentation:**
- `docs/guides/configuration-reference.md` — cross-service environment variable dependency map, secret contracts, policy bundle rollout procedure, per-service tables with source (`runtime-config` vs `runtime-secrets`).

## Architecture and Conventions

### One dataclass per service
Each product owns a single frozen `dataclass` holding all runtime knobs. Defaults are declared as class attributes; `from_env()` maps `os.getenv(<VAR>, <default>)` into the constructor. A module-level `get_settings()` cached function provides process-wide access.

### Boolean parsing is uniform
Booleans accept `"1" | "true" | "yes" | "on"` (case-insensitive, stripped); unset values fall through to defaults. The agent-service uses a shared `_optional_bool` helper; tool-gateway uses a local `_env_bool` helper.

### Feature flags are opt-in by default
Connector toggles (`GATEWAY_BROWSER_ENABLED`, `GATEWAY_HTTP_ENABLED`, `GATEWAY_SECRETS_ENABLED`, `GATEWAY_K8S_ENABLED`, `GATEWAY_ELASTIC_ENABLED`) default to `false`. Unset URLs for downstream services (skills, incidents, tool-gateway proxies) leave routes fail-closed (503) rather than falling back.

### Validation fails startup, not at request time
Invalid values raise `ValueError` from `__post_init__` (e.g. unknown `SESSION_STORE_BACKEND`, invalid IANA timezone, negative TTLs, port outside 1–65535, `GATEWAY_SECRET_DELIVERY_BACKEND` not `memory|redis`). This prevents misconfigured pods from starting.

### Secrets never live in ConfigMaps
Sensitive values (`*_CLIENT_SECRET`, `*_API_KEY`, `OIDC_CLIENT_SECRET`, `OTEL_EXPORTER_OTLP_HEADERS`, signing keys, handoff tokens) are provisioned as Kubernetes `Secret` objects by dedicated `sync-*-secrets.sh` scripts and referenced via `secretKeyRef` in deployments. Non-secret runtime knobs go into `runtime-config.env` → ConfigMap.

### Cross-service credentials use client_id/client_secret registries
Every outbound caller registers a `client_id` and `client_secret`; the callee maintains a registry (`AUDIT_INGEST_CLIENTS`, `SKILLS_QUERY_CLIENTS`, `INCIDENT_QUERY_CLIENTS`, `IDENTITY_SERVICE_CLIENTS`). Scripts generate matching pairs and write them into each service's runtime-secrets. The `configuration-reference.md` documents every chain (token delegation, audit ingestion, skills retrieval, incident intake).

### Policy bundles are single-source-of-truth
`shared/shared-contracts/policies/policy-default.yaml` is the canonical file. `make sync-policy` copies it byte-identically into both gateways' packaged defaults and the dev-k8s overlay; `make verify` asserts copy parity and scenario expectations. Consumers load from `PLATFORM_GATEWAY_POLICY_PATH` / `GATEWAY_POLICY_PATH` (default `/etc/luban/policy/policy.yaml`); missing or invalid bundles fail startup with `PolicyLoadError` — no silent fallback.

### Runtime profiles decouple LLM providers from deployment posture
A generic profile label (`default`) selects the active LLM provider via `AGENTSCOPE_PROVIDER` / `AGENTSCOPE_PROFILE` ConfigMap; separate overlays (`mutating-dev`, `browser-dev`) add feature flags without touching the LLM profile. Only one profile is active at a time.

### Documentation is the spec
`docs/guides/configuration-reference.md` is the authoritative cross-service dependency map: every variable, default, owning service, and secret contract is enumerated there alongside diagrams of inter-service chains. It references the exact source file and `runtime-config.env` path for each service.

## Conventions and Constraints

- **All runtime configuration is read from `os.environ` at process start.** No `.env` files, no YAML config files consumed at runtime (policy bundles are the only exception, loaded once from a configured path), no hot reload.
- **Feature flags are deny-by-default.** New connectors/tools are gated behind explicit `*_ENABLED` env vars; leaving them unset disables discovery and registration.
- **Unknown backend names fail startup.** E.g. `SESSION_STORE_BACKEND`, `AGENT_STATE_STORE_BACKEND`, `AUDIT_STORE_BACKEND`, `SKILLS_STORE_BACKEND`, `INCIDENT_STORE_BACKEND`, `EXECUTION_STATE_STORE_BACKEND` reject unknown values.
- **Cross-service secrets are generated and synchronized by scripts, never committed.** Each `sync-*-secrets.sh` creates or reuses a random secret and writes the corresponding K8s Secret(s); `SKIP_*_SECRETS=true` opts out.
- **Policy bundle drift is enforced by CI.** `make verify` runs schema validation, scenario-expectation guards against both engines, and copy-parity assertions between the canonical file and consumer replicas.
- **Missing required secrets fail closed.** Absent execution signing key → mutating resumes rejected (`signing_unavailable`); absent handoff token → worker rejects handoff (`worker_unavailable`); absent incident/skills client secret → 503 dependency-not-configured.
- **Password-policy overrides may only tighten the contract.** Tool-gateway's `__post_init__` imports the canonical policy and raises if `GATEWAY_PASSWORD_MIN_LENGTH` weakens it, adds unknown classes, or drops a required class.
- **Shared OTel configuration lives in a single ConfigMap** (`shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env`); per-service auth headers ride in each service's runtime-secrets Secret.
- **Configuration reference is maintained alongside code.** Every new variable documented in `configuration-reference.md` must also be parsed in the corresponding service's settings module.