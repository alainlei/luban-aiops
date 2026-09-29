---
kind: error_handling
name: Python Service Error Handling — Domain Exceptions, HTTPException, and Per-Service Exception Handlers
category: error_handling
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/providers/base.py
    - products/agent-platform/src/agent_service/runtime_kernel.py
    - products/agent-platform/src/agent_service/services/execution_protocol.py
    - products/agent-platform/src/agent_service/api/v2/routes.py
    - products/platform-gateway/src/platform_gateway/services/policy_engine.py
    - products/tool-gateway/src/tool_gateway/services/policy_engine.py
    - products/execution-runtime/src/execution_runtime/services/execution_protocol.py
    - products/identity-broker/src/identity_service/services/exchange_service.py
    - products/incident-service/src/incident_service/services/triage.py
    - products/audit-service/src/audit_service/services/audit_store.py
    - products/skills-hub/src/skills_hub/services/skill_store.py
    - samples/acme-admin/app/src/acme_admin/main.py
---

## Approach

Luban is a multi-service Python platform (FastAPI + uv) with no cross-cutting exception framework. Each product service defines its own small set of domain `Exception` subclasses and lets FastAPI's default JSON error responses handle them, except where a service needs a custom shape.

The only repository-wide `@app.exception_handler(...)` registration lives in the sample console (`samples/acme-admin/app/src/acme_admin/main.py`), which maps a custom `AdminAuthRequired` exception to a shared `unauthorized()` JSON response. The production services do not register global exception handlers; they raise `fastapi.HTTPException` directly from route handlers for client-facing errors and domain exceptions for internal control flow.

## Key files and packages

Domain exception classes are defined per service under `src/<service>/services/...` or `core/`:

- `products/agent-platform/src/agent_service/providers/base.py` — `ProviderConfigurationError(ValueError)`
- `products/agent-platform/src/agent_service/runtime_kernel.py` — `UnknownModelError(ValueError)`
- `products/agent-platform/src/agent_service/services/execution_protocol.py` — `ProtocolError(ValueError)`
- `products/agent-platform/src/agent_service/services/execution_worker_client.py` — `WorkerHandoffError(Exception)`
- `products/agent-platform/src/agent_service/services/incident_client.py` — `IncidentClientError(Exception)`
- `products/agent-platform/src/agent_service/services/shift_summary.py` — `DigestInputError`, `UnknownSessionError`
- `products/agent-platform/src/agent_service/services/skills_client.py` — `SkillsClientError`
- `products/audit-service/src/audit_service/services/audit_store.py` — `StoreError`
- `products/audit-service/src/audit_service/services/ingest_auth.py` — `IngestAuthError`
- `products/execution-runtime/src/execution_runtime/services/execution_protocol.py` — `ProtocolError`
- `products/identity-broker/src/identity_service/services/exchange_service.py` — `ExchangeError`
- `products/incident-service/src/incident_service/core/config.py` — `SettingsError`
- `products/incident-service/src/incident_service/services/connectors.py` — `ConnectorConfigError`
- `products/incident-service/src/incident-service/services/incident_store.py` — `StoreError`
- `products/incident-service/src/incident-service/services/normalization.py` — `NormalizationError`
- `products/incident-service/src/incident-service/services/query_auth.py` — `QueryAuthError`
- `products/incident-service/src/incident-service/services/triage.py` — `TriageError`
- `products/platform-gateway/src/platform_gateway/services/policy_engine.py` — `PolicyLoadError`
- `products/platform-gateway/src/platform_gateway/services/token_verifier.py` — `TokenVerificationError`
- `products/skills-hub/src/skills_hub/core/config.py` — `SettingsError`
- `products/skills-hub/src/skills_hub/services/query_auth.py` — `QueryAuthError`
- `products/skills-hub/src/skills_hub/services/skill_store.py` — `StoreError`
- `products/tool-gateway/src/tool_gateway/services/policy_engine.py` — `PolicyLoadError`
- `products/tool-gateway/src/tool_gateway/services/token_verifier.py` — `TokenVerificationError`

HTTP-level errors are raised as `fastapi.HTTPException` from route handlers (e.g. `products/agent-platform/src/agent_service/api/v2/routes.py` raises it for missing headers, invalid recovery queries, unknown sessions, and upstream failures).

## Architecture and conventions

1. **Domain exceptions are thin subclasses.** Most are `class XxxError(Exception)` or `class XxxError(ValueError)` with no extra fields. They carry their message in the standard `Exception.args`; there is no shared base class or common payload schema across services.

2. **Exceptions propagate up to FastAPI.** Route handlers and service methods raise domain exceptions; callers catch them where business logic requires branching (e.g. execution protocol validation). There is no middleware that converts domain exceptions into a uniform JSON envelope.

3. **Client-facing errors use `HTTPException`.** Validation failures, missing auth headers, 404s, and upstream connectivity problems are surfaced via `raise HTTPException(status_code=..., detail=...)` from route handlers rather than through domain exceptions.

4. **Startup failures fail closed.** The sample console (`samples/acme-admin/app/src/acme_admin/main.py`) raises `RuntimeError` from the lifespan when required credentials are absent, with a comment explicitly stating "failing closed at startup beats failing open". This pattern documents an intentional design choice rather than a repo-wide rule enforced by a base class.

5. **No panic/recover.** Python has no panic/recover; the codebase does not use `try/except BaseException` blocks for top-level crash recovery. Errors are propagated as exceptions.

6. **No centralized error codes.** Unlike the policy engine (which uses named constants like `OUTCOME_REQUIRE_APPROVAL`), there is no shared error-code registry. Status codes are literal integers passed to `HTTPException`.

7. **Per-service exception handler registration is the exception, not the norm.** Only the sample console registers `@app.exception_handler(AdminAuthRequired)`. Production services rely on FastAPI's default behavior.

## Conventions and constraints

- Domain exceptions are defined next to the code that raises them, typically under `src/<service>/services/` or `core/`, and named `<Context>Error` (e.g. `PolicyLoadError`, `TokenVerificationError`, `StoreError`).
- Configuration/validation failures subclass `ValueError` (`ProviderConfigurationError`, `UnknownModelError`, `ProtocolError`); transport/client failures subclass plain `Exception` (`WorkerHandoffError`, `IncidentClientError`, `ExchangeError`).
- Policy bundle parsing (`platform-gateway/services/policy_engine.py`, `tool-gateway/services/policy_engine.py`) consistently wraps YAML/schema parse failures in `PolicyLoadError`, preserving the original exception via `from exc`.
- Tests import and assert against these domain exceptions directly (e.g. `test_runtime_providers.py` imports `ProviderConfigurationError`, failure probes import `ProtocolError`), so the exception types form part of the inter-service contract surface used by tests.
- The author guidelines do not exclude error handling; this card therefore covers the observed patterns.