---
kind: error_handling
name: Error Handling Across Luban Services
category: error_handling
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/api/v2/routes.py
    - products/agent-platform/src/agent_service/services/skills_client.py
    - products/agent-platform/src/agent_service/services/incident_client.py
    - products/agent-platform/src/agent_service/services/execution_worker_client.py
    - products/agent-platform/src/agent_service/runtime_kernel.py
    - products/agent-platform/src/agent_service/providers/base.py
    - products/audit-service/src/audit_service/services/audit_store.py
    - products/audit-service/src/audit_service/services/ingest_auth.py
    - products/incident-service/src/incident_service/services/connectors.py
    - products/incident-service/src/incident_service/services/incident_store.py
    - products/incident-service/src/incident_service/services/normalization.py
    - products/incident-service/src/incident_service/services/query_auth.py
    - products/incident-service/src/incident_service/services/triage.py
    - products/platform-gateway/src/platform_gateway/services/policy_engine.py
    - products/platform-gateway/src/platform_gateway/services/token_verifier.py
    - products/skills-hub/src/skills_hub/services/query_auth.py
    - products/skills-hub/src/skills_hub/services/skill_store.py
    - products/tool-gateway/src/tool_gateway/services/policy_engine.py
    - products/tool-gateway/src/tool_gateway/services/token_verifier.py
---

## Approach

Luban services are FastAPI applications that combine two complementary error strategies:

1. **Domain exceptions** — per-service `*Error` classes raised inside business logic and client wrappers.
2. **HTTP translation** — route handlers catch domain exceptions and raise `fastapi.HTTPException` with explicit status codes, so the API surface is expressed in HTTP semantics rather than Python types.

There is no shared base exception class, no centralized `exception_handlers` registration, and no global middleware that converts errors into responses. Each product owns its own exception hierarchy and its own route-level translation.

## Key files and packages

- `products/agent-platform/src/agent_service/api/v2/routes.py` — the largest consumer of the pattern; translates domain errors from skills-hub, incident-service, execution-runtime, and internal kernel calls into HTTP responses.
- `products/agent-platform/src/agent_service/services/skills_client.py` — defines `SkillsClientError`, `SkillsDependencyNotConfigured`, `SkillsServiceUnavailable`, `SkillsClientRejected` (with `status_code` / `message`).
- `products/agent-platform/src/agent_service/services/incident_client.py` — defines `IncidentClientError`, `IncidentDependencyNotConfigured`, `IncidentServiceUnavailable`, `IncidentNotFound`, `IncidentClientRejected`, `NoValidatedTriageReport`.
- `products/agent-platform/src/agent_service/services/execution_worker_client.py` — defines `WorkerHandoffError`.
- `products/agent-platform/src/agent_service/runtime_kernel.py` — defines `UnknownModelError(ValueError)`.
- `products/agent-platform/src/agent_service/providers/base.py` — defines `ProviderConfigurationError(ValueError)` used by every provider implementation (`dashscope`, `deepseek`, `luban`, `openai`).
- Per-product service modules define analogous client/domain errors: `audit_store.StoreError`, `ingest_auth.IngestAuthError`; `exchange_service.ExchangeError`; `incident_store.StoreError`, `connectors.ConnectorConfigError`, `normalization.NormalizationError`, `query_auth.QueryAuthError`, `triage.TriageError`; `platform_gateway.services.policy_engine.PolicyLoadError`, `token_verifier.TokenVerificationError`; `skills_hub.query_auth.QueryAuthError`, `skill_store.StoreError`; `tool_gateway` mirrors the platform-gateway exceptions.
- `shared/shared-contracts/schemas/*.schema.json` — JSON Schema definitions for request/response payloads; validation failures are surfaced as HTTP 422 via Pydantic/FastAPI defaults rather than custom exceptions.

## Architecture and conventions

### Domain exceptions carry HTTP intent

Client-layer exceptions expose both a semantic type and an HTTP mapping. For example, `SkillsClientRejected` carries `status_code` and `message` attributes so the caller can re-raise them verbatim:

```python
except SkillsClientRejected as exc:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
```

This lets upstream services (agent-platform) forward downstream policy or validation decisions without inventing new status codes.

### Route-level try/except maps domains to HTTP

In `routes.py`, each endpoint wraps cross-service calls in a small `try/except` block that selects the right status code:

- `503` → dependency not configured (`SkillsDependencyNotConfigured`, `IncidentDependencyNotConfigured`).
- `502` → upstream unavailable (`SkillsServiceUnavailable`, `IncidentServiceUnavailable`).
- `404` → resource not found (`IncidentNotFound`, session-not-found).
- `409` → conflict / state mismatch (`ConfirmationNotFound`, `NoValidatedTriageReport`).
- `422` → input validation failure (unknown model id, malformed skill target).
- `401` → missing auth header (`X-User-ID`).
- `410` → expired confirmation.
- `500` is never returned directly; internal `RuntimeError` / `ValueError` bubbles up to FastAPI's default handler only when unhandled.

The `_validate_skill_markdown` helper centralizes the skills-hub error-to-HTTP mapping so both draft endpoints share identical behavior.

### Configuration and runtime settings use `ValueError`

Startup-time configuration validation raises plain `ValueError` with human-readable messages (e.g. `AGENTSCOPE_MAX_ITERS must be >= 1`, `AGENTSCOPE_MODEL_MAX_RETRIES must be >= 0`). These are caught at process startup, not during request handling.

### No global exception handler

None of the four main services (`app.py`) register `@app.exception_handler`. Error presentation is therefore delegated to FastAPI's default JSON error response. The only place a custom handler appears is in the sample app `samples/acme-admin/app/src/acme_admin/main.py`, which registers one for `AdminAuthRequired` — this is sample code, not a platform convention.

### Middleware is logging-only

Every service installs an `http` middleware that records `log_event("http_request", ...)` with `method`, `path`, `status_code`, `duration_ms`, and `request_id`. It does not transform errors; it observes whatever response FastAPI produces.

### Cross-service contracts are typed, not exception-based

Shared schemas live under `shared/shared-contracts/schemas/` and describe wire formats. There is no shared exception schema. Cross-service error propagation relies on the client wrapper layer translating those schemas' rejection cases into HTTP status codes.

## Conventions and constraints

- **Domain exceptions are raised in services and clients; HTTP responses are produced in routes.** This separation keeps business logic free of HTTP concerns while keeping the API surface deterministic.
- **Downstream client errors preserve their original status code** via `status_code` / `message` attributes on `*ClientRejected` exceptions, enabling faithful passthrough of policy decisions from skills-hub, incident-service, etc.
- **Unconfigured dependencies map to 503; unreachable/upstream 5xx map to 502; client-rejected requests reuse the downstream status code.** This is enforced by the explicit `try/except` blocks in `routes.py`.
- **Input validation uses FastAPI/Pydantic defaults (422)** rather than custom exceptions — malformed bodies, unknown model ids, and invalid headers are rejected through the framework's built-in machinery.
- **Configuration errors use `ValueError`** at module load time, not during request processing.
- **There is no repository-wide base error class or centralized error mapper**; each product defines its own `*Error` hierarchy locally.
- **No `panic` / `recover` equivalent exists** — Python has no such construct, and the codebase does not use `try/finally` around user code for fault containment beyond standard lifespan/resource cleanup.
- **Tests exercise failure paths explicitly** (e.g. `products/execution-runtime/tests/failure/`, `test_execution_recovery.py`, `test_execution_run_guard.py`), but they assert on raised exceptions or HTTP status codes rather than on a shared assertion library.