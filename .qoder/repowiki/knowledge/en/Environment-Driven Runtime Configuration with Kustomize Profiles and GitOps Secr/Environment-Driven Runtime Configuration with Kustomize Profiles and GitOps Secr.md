---
kind: configuration_system
name: Environment-Driven Runtime Configuration with Kustomize Profiles and GitOps Secrets
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
    - shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env
    - shared/platform-ops/gitops/runtime-profiles/default/configmap.yaml
    - shared/platform-ops/gitops/select-runtime-profile.sh
    - shared/platform-ops/gitops/sync-delegation-secrets.sh
    - shared/platform-ops/gitops/sync-audit-secrets.sh
    - shared/platform-ops/gitops/sync-skills-secrets.sh
    - shared/platform-ops/gitops/sync-incident-secrets.sh
    - shared/platform-ops/gitops/sync-execution-signing-secret.sh
    - shared/platform-ops/gitops/sync-execution-handoff-secret.sh
    - shared/platform-ops/gitops/sync-browser-credentials.sh
    - shared/platform-ops/gitops/sync-otel-secrets.sh
---

## Approach

Luban uses a **pure environment-variable configuration model** — no framework like Pydantic Settings, dotenv, or YAML config files are loaded at runtime. Each service defines its own frozen `dataclass` settings object with a `from_env()` classmethod that reads `os.getenv(...)`, applies defaults, coerces types, and validates in `__post_init__`. There is no centralized configuration library; each product owns its settings module.

Configuration values come from three layers, applied by Kubernetes via Kustomize overlays:
1. **Shared env** — `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env` (OTel endpoint, identity broker URL) mounted as a ConfigMap consumed by every pod.
2. **Per-service runtime-config** — one `runtime-config.env` per service under `dev-k8s/base/<service>/`, defining non-secret knobs.
3. **Secrets** — provisioned into per-service `*-runtime-secrets` Kubernetes Secrets via `sync-*-secrets.sh` scripts; never committed to Git.

Kustomize **runtime profiles** (`shared/platform-ops/gitops/runtime-profiles/`) layer feature toggles on top of the base: `default` (LLM provider), `mutating-dev` (pod-delete RBAC + mutating tools enabled), and `browser-dev` (headless Chromium sidecar). A profile is selected at deploy time via `select-runtime-profile.sh`; only one LLM profile is active at a time.

## Key Files

- `products/agent-platform/src/agent_service/runtime_settings.py` — `RuntimeSettings` dataclass, the largest settings surface (LLM providers, HITL, evidence caps, execution signing/worker/admission, skills/incident clients).
- `products/tool-gateway/src/tool_gateway/core/config.py` — `GatewaySettings` dataclass (browser, HTTP, secrets connectors, policy path, audit/skills/incidents clients).
- `products/platform-gateway/src/platform_gateway/core/config.py` — `PlatformGatewaySettings` dataclass (delegation, workload token, policy path, incident/skills proxies).
- `products/execution-runtime/src/execution_runtime/core/config.py` — execution worker admission and handoff settings.
- `products/identity-broker/src/identity_service/core/config.py` — OIDC/Keycloak client and delegated-token registry.
- `products/audit-service/src/audit_service/core/config.py` — ingest client registry and retention.
- `products/skills-hub/src/skills_hub/core/config.py` — federated source list and query client registry.
- `products/incident-service/src/incident_service/core/config.py` — webhook token and query client registry.
- `docs/guides/configuration-reference.md` — authoritative cross-service variable map, secret contracts, and provisioning procedures.
- `shared/platform-ops/gitops/dev-k8s/base/*/runtime-config.env` — per-service default env.
- `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env` — shared OTel + identity broker env.
- `shared/platform-ops/gitops/runtime-profiles/` — Kustomize profile overlays.
- `shared/platform-ops/gitops/sync-*.sh` — secret provisioning scripts (`sync-delegation-secrets.sh`, `sync-audit-secrets.sh`, `sync-skills-secrets.sh`, `sync-incident-secrets.sh`, `sync-execution-signing-secret.sh`, `sync-execution-handoff-secret.sh`, `sync-browser-credentials.sh`, `sync-otel-secrets.sh`, `sync-email-secrets.sh`).

## Architecture and Conventions

- **Settings objects are frozen dataclasses** with typed defaults and `__post_init__` validation. Invalid values fail startup rather than degrading silently (e.g. invalid timezone, out-of-range timeouts, unsupported provider).
- **Boolean parsing** is uniform across services: truthy values are `{"1", "true", "yes", "on"}` (case-insensitive); falsey is everything else.
- **Optional helpers** (`_optional_str`, `_optional_int`, `_optional_float`, `_optional_bool`, `_optional_choice`) centralize coercion in agent-service; tool-gateway has its own `_env_bool`, `_env_optional_int`, `_env_optional_tuple`.
- **Feature flags are deny-by-default**: browser tools (`GATEWAY_BROWSER_ENABLED=false`), HTTP tools (`GATEWAY_HTTP_ENABLED=false`), secrets connector (`GATEWAY_SECRETS_ENABLED=false`), mutating tools (`GATEWAY_MUTATING_TOOLS_ENABLED=false`), auth (`PLATFORM_GATEWAY_REQUIRE_AUTH=true`), etc. Enabling a flag alone is insufficient — cross-service chains require matching secrets.
- **Cross-service credentials** follow a client_id/client_secret contract: each caller registers its secret against the consumer's registry (e.g. `IDENTITY_SERVICE_CLIENTS`, `AUDIT_INGEST_CLIENTS`, `SKILLS_QUERY_CLIENTS`, `INCIDENT_QUERY_CLIENTS`). The canonical mapping lives in `docs/guides/configuration-reference.md` and is enforced by provisioning scripts.
- **Policy bundles** are single-source-of-truth: `shared/shared-contracts/policies/policy-default.yaml` is synced byte-identically to both gateways' packaged defaults and the dev-k8s overlay via `make sync-policy`; drift fails `make verify`.
- **Secrets are never in Git**: they are generated by `sync-*-secrets.sh` scripts and mounted as Kubernetes Secrets. Some keys ride `secretKeyRef` directly onto deployments (e.g. `AGENT_EXECUTION_SIGNING_KEY`, `EXECUTION_HANDOFF_TOKEN`); others are read from environment variables populated from Secrets.
- **Config loading is cached per-process**: gateway settings use `@lru_cache(maxsize=1)` on `get_settings()`; agent-service constructs `RuntimeSettings` once at startup.
- **No hot reload**: changing a ConfigMap takes effect only on pod restart; the documentation explicitly states this for policy bundles and applies to all env-based config.
- **Validation is strict at startup**: unknown backend names (session store, secret delivery, skills store, incident store) raise errors; missing required keys (execution signing key, worker URL/token) fail closed rather than falling back.

## Conventions and Constraints

- Every service exposes its settings source file path in `configuration-reference.md` under the Per-Service Environment Variables section, linking the doc to the implementation.
- Cross-service dependency chains (token delegation, audit ingestion, skills retrieval, incident intake) are documented as ASCII diagrams in `configuration-reference.md` with explicit secret contract formats (`client_id:client_secret:audience1|audience2`, `client_id=client_secret,...`).
- Provisioning is opt-out via `SKIP_*_SECRETS=true` environment variables passed to the `sync-*` scripts.
- The `*_AUDIT_CLIENT_SECRET` for agent-service is upserted into `agent-platform-runtime-secrets` (the same Secret holding LLM provider keys) so it survives profile switches; other services get dedicated `*-runtime-secrets` Secrets.
- Password policy overrides (`GATEWAY_PASSWORD_MIN_LENGTH`, `GATEWAY_PASSWORD_REQUIRED_CLASSES`, `GATEWAY_PASSWORD_EXCLUDE_AMBIGUOUS`) may only tighten the canonical contract — `__post_init__` raises if an override weakens it.
- Browser and HTTP credential sets are mounted as JSON files at paths referenced by `GATEWAY_BROWSER_CREDENTIAL_SETS` / `GATEWAY_HTTP_CREDENTIAL_SETS`; inline credential values are never accepted as env vars.
- OpenTelemetry push is configured centrally in `shared/runtime.env` but the auth header (`OTEL_EXPORTER_OTLP_HEADERS`) is injected per-service via `sync-otel-secrets.sh` into each service's runtime-secrets Secret.
- Runtime profiles decouple the LLM provider from the deployment label: `AGENTSCOPE_PROVIDER` selects the provider while the profile name is a free-form deploy label (SPEC-026 R-5).
- The canonical policy bundle version field is the review discipline mechanism — there is no monotonicity machinery; Git history is the authority.