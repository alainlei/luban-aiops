---
kind: error_handling
name: Error Handling — Domain Exception Hierarchies Mapped to HTTP Status Codes
category: error_handling
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/services/skills_client.py
    - products/agent-platform/src/agent_service/services/incident_client.py
    - products/agent-platform/src/agent_service/api/v2/routes.py
    - products/agent-platform/src/agent_service/providers/base.py
    - products/agent-platform/src/agent_service/runtime_settings.py
    - products/execution-runtime/src/execution_runtime/services/execution_protocol.py
    - products/audit-service/src/audit_service/services/audit_store.py
    - products/audit-service/src/audit_service/services/ingest_auth.py
    - products/identity-broker/src/identity_service/services/exchange_service.py
    - products/incident-service/src/incident_service/core/config.py
    - products/incident-service/src/incident_service/services/connectors.py
    - products/incident-service/src/incident_service/services/incident_store.py
    - products/incident-service/src/incident_service/services/normalization.py
    - products/incident-service/src/incident_service/services/query_auth.py
    - products/incident-service/src/incident_service/services/triage.py
    - products/platform-gateway/src/platform_gateway/services/policy_engine.py
    - products/platform-gateway/src/platform_gateway/services/token_verifier.py
    - products/skills-hub/src/skills_hub/core/config.py
    - products/skills-hub/src/skills_hub/services/query_auth.py
    - products/skills-hub/src/skills_hub/services/skill_store.py
    - products/execution-runtime/tests/failure/support/infrastructure.py
---

## Approach

Luban uses a per-service Python exception-hierarchy pattern combined with FastAPI `HTTPException` translation at route boundaries. There is no repository-wide exception base class, no global `@app.exception_handler`, and no panic/recover strategy (Python has neither). Errors are propagated as typed exceptions up through services and converted to HTTP responses only at the API layer.

## Key Files and Packages

- `products/agent-platform/src/agent_service/services/skills_client.py` — canonical example of the client-error hierarchy: `SkillsClientError` → `SkillsDependencyNotConfigured`, `SkillsServiceUnavailable`, `SkillsClientRejected`.
- `products/agent-platform/src/agent_service/services/incident_client.py` — parallel hierarchy: `IncidentClientError` → `IncidentDependencyNotConfigured`, `IncidentServiceUnavailable`, `IncidentNotFound`.
- `products/agent-platform/src/agent_service/api/v2/routes.py` — central mapping site where client exceptions are caught and translated to `HTTPException(status_code=...)`.
- `products/agent-platform/src/agent_service/providers/base.py` — `ProviderConfigurationError(ValueError)` for provider setup failures.
- Per-service domain errors: `audit_store.StoreError`, `ingest_auth.IngestAuthError`, `execution_runtime.services.execution_protocol.ProtocolError`, `identity_service.exchange_service.ExchangeError`, `incident_service.core.config.SettingsError`, `incident_service.services.{ConnectorConfigError,StoreError,NormalizationError,QueryAuthError,TriageError}`, `platform_gateway.services.{PolicyLoadError,TokenVerificationError}`, `skills_hub.{SettingsError,QueryAuthError,StoreError}`.
- Shared JSON Schema contracts under `shared/shared-contracts/schemas/` define the wire-level error shape consumed by clients (e.g. `error.message` extraction in `_upstream_message`).

## Architecture and Conventions

1. **Domain exceptions live next to the code that raises them.** Each product package defines small exception hierarchies close to the failing subsystem (clients, stores, config, protocol layers). Base classes are typically named `<Subsystem>Error` or `<Subsystem>Exception`.

2. **Client-layer exceptions encode the failure mode, not just the message.** The skills-client hierarchy separates "not configured" (503) from "transport/upstream 5xx" (502) from "upstream 4xx" (passthrough), so callers can make deterministic posture decisions without string-matching messages.

3. **Route handlers perform explicit try/except translation.** In `agent_service/api/v2/routes.py`, `_validate_skill_markdown` and the incident-draft endpoint catch the client exceptions and raise `HTTPException` with a fixed status code:
   - `*DependencyNotConfigured` → 503
   - `*ServiceUnavailable` → 502
   - `*Rejected` → passthrough `exc.status_code`
   - `*NotFound` → 404
   - `NoValidatedTriageReport` → 409

4. **Structured rejection payloads carry `status_code` and `message`.** `SkillsClientRejected.__init__` stores both attributes so the route can forward the upstream response verbatim (`raise HTTPException(status_code=exc.status_code, detail=exc.message)`).

5. **Validation failures use built-in exceptions.** Configuration validation in `runtime_settings.py` raises `ValueError` directly with descriptive messages (e.g. `AGENTSCOPE_MAX_ITERS must be >= 1`); this is distinct from domain/business exceptions.

6. **No global exception middleware.** A grep across the repo finds only one `@app.exception_handler` usage, and it lives in `samples/acme-admin/app/src/acme_admin/main.py` (a sample app, not a platform service). Platform services rely on FastAPI's default `HTTPException` rendering plus explicit translations in route handlers.

7. **Failure-test coverage exists for the execution-runtime.** Under `products/execution-runtime/tests/failure/` there is a dedicated failure test suite (including `failure/support/infrastructure.py` defining `PrerequisiteError(RuntimeError)`), indicating that crash paths and recovery are tested separately from happy-path assertions.

8. **Cross-service contracts document error shapes.** The shared schemas under `shared/shared-contracts/schemas/` include `chat-response.schema.json`, `agent-chat-response.schema.json`, and others that describe the wire payload structure consumers expect, including error fields.

## Conventions and Constraints

- **Observed convention:** Client libraries wrap `httpx.HTTPError` and upstream non-2xx responses into a small, named exception hierarchy rather than propagating raw transport exceptions to route handlers.
- **Observed convention:** Route handlers convert those domain exceptions to `fastapi.HTTPException` with an explicit `status_code`; the `detail` field carries the human-readable message.
- **Observed convention:** Dependency-not-configured vs. service-unavailable are modeled as separate exception subclasses so the caller can return 503 vs. 502 deterministically.
- **Observed constraint (enforced by code):** Generated skill drafts are never returned unvalidated — if validation fails twice, the route falls back to a facts-only skeleton and raises 502 only when even the skeleton fails format validation (`_validated_draft_sequence` in `routes.py`).
- **Observed constraint (enforced by code):** Upstream 4xx rejections from skills-hub are passed through with their original status code via `SkillsClientRejected.status_code`; they are not collapsed into a generic 400.
- **Observed constraint (enforced by code):** Provider adapters validate settings eagerly in `AgentScopeProvider.validate()` and raise `ProviderConfigurationError` before model resolution, preventing misconfigured providers from reaching downstream code.