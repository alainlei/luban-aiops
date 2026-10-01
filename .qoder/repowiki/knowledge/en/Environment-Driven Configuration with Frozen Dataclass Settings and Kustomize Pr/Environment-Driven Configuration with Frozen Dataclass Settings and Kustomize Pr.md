---
kind: configuration_system
name: Environment-Driven Configuration with Frozen Dataclass Settings and Kustomize Profiles
category: configuration_system
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/runtime_settings.py
    - products/tool-gateway/src/tool_gateway/core/config.py
    - products/platform-gateway/src/platform_gateway/core/config.py
    - products/execution-runtime/src/execution_runtime/core/config.py
    - products/audit-service/src/audit_service/core/config.py
    - products/identity-broker/src/identity_service/core/config.py
    - products/incident-service/src/incident_service/core/config.py
    - products/skills-hub/src/skills_hub/core/config.py
    - shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env
    - shared/platform-ops/gitops/dev-k8s/base/agent-platform/runtime-config.env
    - shared/platform-ops/gitops/dev-k8s/base/tool-gateway/runtime-config.env
    - shared/platform-ops/gitops/dev-k8s/base/platform-gateway/runtime-config.env
    - shared/platform-ops/gitops/runtime-profiles/default/configmap.yaml
    - shared/platform-ops/gitops/sync-delegation-secrets.sh
    - shared/platform-ops/gitops/sync-audit-secrets.sh
    - shared/platform-ops/gitops/sync-skills-secrets.sh
    - shared/platform-ops/gitops/sync-incident-secrets.sh
    - shared/platform-ops/gitops/sync-execution-signing-secret.sh
    - shared/platform-ops/gitops/sync-execution-handoff-secret.sh
    - docs/guides/configuration-reference.md
---

## What system/approach is used

The Luban platform uses a **pure environment-variable configuration model** — no YAML/JSON config files are read at runtime by the Python services. Each service defines a frozen `dataclass` of settings in a `core/config.py` (or `runtime_settings.py`) module, exposes a `from_env()` classmethod that reads `os.getenv`, and caches the instance via `functools.lru_cache(maxsize=1)` behind a `get_settings()` accessor. There is no third-party configuration library (no pydantic-settings, python-dotenv, dynaconf, etc.).

Kubernetes deployment is driven by **Kustomize overlays** under `shared/platform-ops/gitops/dev-k8s/base/<service>/runtime-config.env`, which are mounted as ConfigMaps and referenced from each Deployment's envFrom. Secrets live in per-service Kubernetes `Secret` objects (`*-runtime-secrets`, `execution-signing-secret`, `execution-handoff-secret`, `tool-gateway-browser-credentials`) provisioned by shell scripts under `shared/platform-ops/gitops/sync-*.sh`. LLM provider profiles are selected through Kustomize profile overlays under `shared/platform-ops/gitops/runtime-profiles/`.

## Key files and packages

- `products/agent-platform/src/agent_service/runtime_settings.py` — agent-service settings; the largest and most feature-rich, covering LLM providers, kernel tuning, HITL, evidence caps, execution signing/handoff/admission, browser flow TTL, audit/incident/skills clients, authoring-trace bounds.
- `products/tool-gateway/src/tool_gateway/core/config.py` — gateway settings for auth, policy, k8s/browser/http/secrets connectors, Elastic, audit, skills, incidents.
- `products/platform-gateway/src/platform_gateway/core/config.py` — platform-gateway settings for identity, delegation, policy, audit, incident, workspace proxies.
- `products/execution-runtime/src/execution_runtime/core/config.py`, `products/audit-service/src/audit_service/core/config.py`, `products/identity-broker/src/identity_service/core/config.py`, `products/incident-service/src/incident_service/core/config.py`, `products/skills-hub/src/skills_hub/core/config.py` — analogous per-service settings modules.
- `shared/platform-ops/gitops/dev-k8s/base/<service>/runtime-config.env` — per-service default env values.
- `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env` — shared OTel + identity broker endpoint.
- `shared/platform-ops/gitops/runtime-profiles/default/configmap.yaml` — active LLM profile ConfigMap.
- `docs/guides/configuration-reference.md` — authoritative cross-service environment variable dependency map, secret contracts, provisioning procedures, and policy rollout workflow.

## Architecture and conventions

### Per-service frozen dataclass settings
Every service follows the same pattern:

```python
@dataclass(frozen=True)
class ServiceSettings:
    field: type = DEFAULT_VALUE

    @classmethod
    def from_env(cls) -> "ServiceSettings":
        return cls(field=os.getenv("SERVICE_FIELD", DEFAULT_VALUE))

@lru_cache(maxsize=1)
def get_settings() -> ServiceSettings:
    return ServiceSettings.from_env()
```

The `frozen=True` makes the settings immutable after construction; validation lives in `__post_init__` where invalid combinations raise `ValueError` at startup rather than failing later. The `lru_cache` ensures a single process-wide singleton.

### Boolean parsing convention
Boolean env vars accept the truthy set `{"1", "true", "yes", "on"}` (lowercased). The agent-service helper `_optional_bool` additionally raises `ValueError` for non-empty strings outside this set, while tool-gateway's `_env_bool` silently defaults to `False` for unknown values.

### Optional vs required semantics
- **Optional knobs**: unset → `None` (via `_optional_str`/`_optional_int` helpers), allowing graceful degradation (e.g., unset `*_AUDIT_SERVICE_URL` degrades audit to log-only).
- **Required secrets**: marked `**must be provisioned**` in the reference doc; absent values fail closed (503 or startup error) rather than falling back to insecure defaults. Examples include `AGENT_EXECUTION_SIGNING_KEY`, `IDENTITY_SERVICE_CLIENTS`, `INCIDENT_WEBHOOK_TOKEN`, `OIDC_CLIENT_SECRET`.
- **Feature gates**: boolean flags like `GATEWAY_BROWSER_ENABLED`, `GATEWAY_HTTP_ENABLED`, `GATEWAY_SECRETS_ENABLED`, `AGENT_EXECUTION_ADMISSION_ENABLED` are off-by-default; enabling them requires coordinated multi-service configuration.

### Deny-by-default posture
Many features ship disabled and require explicit opt-in:
- Browser connector (`GATEWAY_BROWSER_ENABLED=false`)
- HTTP connector (`GATEWAY_HTTP_ENABLED=false`)
- Mutating tools (`GATEWAY_MUTATING_TOOLS_ENABLED=false`)
- Secrets delivery (`GATEWAY_SECRETS_ENABLED=false`)
- Durable execution admission (`AGENT_EXECUTION_ADMISSION_ENABLED=false`, `EXECUTION_ADMISSION_ENABLED=false`)
- Workload identity (disabled in dev)
- Origin allowlists for browser/HTTP connectors default to empty (deny-all).

### Cross-service secret contracts
Inter-service authentication uses a shared-secret registry pattern:
- Token delegation: `PLATFORM_GATEWAY_SERVICE_CLIENT_SECRET` ↔ `IDENTITY_SERVICE_CLIENTS` entry.
- Audit ingestion: each emitter's `*_AUDIT_CLIENT_SECRET` ↔ `AUDIT_INGEST_CLIENTS` in audit-service.
- Skills query: `SKILLS_QUERY_CLIENTS` registry.
- Incident query: `INCIDENT_QUERY_CLIENTS` registry.
All are documented as `client_id=secret,...` or `client_id:client_secret:audience1|audience2` formats in `configuration-reference.md`.

### Policy bundle as configuration-as-code
The authorization policy has exactly one canonical copy: `shared/shared-contracts/policies/policy-default.yaml`. It is replicated byte-identically to both gateways' packaged defaults and the dev-k8s overlay via `make sync-policy`; contract tests enforce parity via `make verify`. Runtime consumers load it from `PLATFORM_GATEWAY_POLICY_PATH` / `GATEWAY_POLICY_PATH` (default `/etc/luban/policy/policy.yaml`). A missing or invalid bundle fails startup (`PolicyLoadError`) — there is no silent fallback to the packaged default.

### Secret provisioning
Secrets are never committed to Git. They are created by idempotent shell scripts under `shared/platform-ops/gitops/`:
- `sync-delegation-secrets.sh` — token delegation
- `sync-audit-secrets.sh` — audit ingest credentials
- `sync-skills-secrets.sh` — skills query credentials
- `sync-incident-secrets.sh` — incident webhook/query credentials
- `sync-execution-signing-secret.sh` / `sync-execution-handoff-secret.sh` — execution security
- `sync-otel-secrets.sh` — OTLP headers
- `sync-browser-credentials.sh` — browser credential sets
- `sync-email-secrets.sh` — SMTP credentials
- `sync-runtime-secret.sh` — LLM provider keys
Each script generates random values unless an exported override is provided (e.g., `DELEGATION_CLIENT_SECRET`, `SKIP_AUDIT_SECRETS=true`).

### LLM runtime profiles
Agent-service supports pluggable LLM backends through Kustomize profile overlays under `shared/platform-ops/gitops/runtime-profiles/`. Only one profile is active at a time, selected via `shared/platform-ops/gitops/select-runtime-profile.sh <profile-name>`. Two permanent non-LLM postures (`mutating-dev`, `browser-dev`) merge additional env into `platform-runtime-config` alongside the active profile.

### Documentation-driven configuration
`docs/guides/configuration-reference.md` is the definitive source of truth: it maps every environment variable to its service, default, source (ConfigMap vs Secret), and behavior. It also documents cross-service dependency chains (token delegation, identity verification, tool relay, mutating action approval, audit ingestion, skills retrieval, incident intake) and the policy management workflow.

## Conventions and constraints

- **Convention**: Each service's configuration lives in `<service>/src/<service_package>/core/config.py` (or `runtime_settings.py` for agent-service) as a frozen dataclass with `from_env()` and a cached `get_settings()` accessor.
- **Convention**: Feature toggles are off-by-default boolean env vars; enabling a feature requires coordinated changes across all services in the dependency chain.
- **Convention**: Secrets are provisioned exclusively via Kubernetes Secrets managed by `sync-*.sh` scripts; no inline secrets appear in Git.
- **Convention**: Shared runtime variables (OTel, identity broker URL) go in `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env`.
- **Convention**: Per-service defaults go in `shared/platform-ops/gitops/dev-k8s/base/<service>/runtime-config.env`.
- **Rule (enforced)**: Unknown boolean values in agent-service raise `ValueError` during settings construction (`_optional_bool`); see `runtime_settings.py` lines 94–103.
- **Rule (enforced)**: Unsupported `AGENTSCOPE_PROVIDER` values raise `ValueError` at startup (`runtime_settings.py` line 483).
- **Rule (enforced)**: Enabling `AGENT_EXECUTION_ADMISSION_ENABLED` without both `AGENT_EXECUTION_STATE_DB_URL` and `AGENT_EXECUTION_ADMISSION_EPOCH` raises `ValueError` at startup (`runtime_settings.py` lines 371–377).
- **Rule (enforced)**: Password policy overrides may only tighten the contract floor; weakening overrides raise `ValueError` in tool-gateway's `__post_init__` (`config.py` lines 161–205).
- **Rule (enforced)**: Policy bundles are loaded from disk path configured via `PLATFORM_GATEWAY_POLICY_PATH` / `GATEWAY_POLICY_PATH`; a missing or invalid bundle fails startup with `PolicyLoadError` (documented in `configuration-reference.md` section "Policy Bundle Rollout").
- **Rule (enforced)**: Cross-service client registries must match: e.g., `PLATFORM_GATEWAY_SERVICE_CLIENT_SECRET` must match the corresponding entry in `IDENTITY_SERVICE_CLIENTS`; mismatch causes token exchange failure (documented in `configuration-reference.md` "Secret contract" blocks).
- **Rule (enforced)**: The policy bundle at `shared/shared-contracts/policies/policy-default.yaml` must stay byte-identical to both gateway replicas and the dev-k8s overlay; `make verify` enforces this parity.