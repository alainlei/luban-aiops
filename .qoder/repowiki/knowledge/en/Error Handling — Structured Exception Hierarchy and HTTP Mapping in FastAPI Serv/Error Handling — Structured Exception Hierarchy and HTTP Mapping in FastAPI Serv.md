---
kind: error_handling
name: Error Handling — Structured Exception Hierarchy and HTTP Mapping in FastAPI Services
category: error_handling
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/services/skills_client.py
    - products/agent-platform/src/agent_service/services/incident_client.py
    - products/agent-platform/src/agent_service/api/v2/routes.py
    - products/platform-gateway/src/platform_gateway/services/token_verifier.py
    - products/platform-gateway/src/platform_gateway/services/policy_engine.py
    - products/audit-service/src/audit_service/services/audit_store.py
    - products/incident-service/src/incident_service/services/connectors.py
    - products/incident-service/src/incident_service/services/incident_store.py
    - products/incident-service/src/incident_service/services/triage.py
    - products/execution-runtime/src/execution_runtime/services/execution_protocol.py
    - products/agent-platform/src/agent_service/runtime_kernel.py
    - products/agent-platform/src/agent_service/providers/base.py
---

## Approach

The Luban platform uses a **structured Python exception hierarchy** layered on top of FastAPI's `HTTPException`. Each product service defines its own domain-specific base exceptions (e.g. `SkillsClientError`, `IncidentClientError`, `TokenVerificationError`, `PolicyLoadError`, `StoreError`), with subclasses encoding failure semantics (configured vs unavailable vs rejected). Route handlers catch these exceptions and translate them into `HTTPException(status_code, detail=...)` responses. There is no repository-wide global exception handler; each service's route module performs the mapping locally.

For configuration and schema validation, services rely on Pydantic's `ValidationError` and plain `ValueError`/`RuntimeError`; there is no custom wrapper for those cases. The only custom FastAPI exception handler found is in the sample app (`samples/acme-admin/app/src/acme_admin/main.py`), which registers an `AdminAuthRequired` handler — not part of the platform services.

## Key Files and Packages

- `products/agent-platform/src/agent_service/services/skills_client.py` — `SkillsClientError` / `SkillsDependencyNotConfigured` / `SkillsServiceUnavailable` / `SkillsClientRejected` hierarchy; the canonical example of the configured/unavailable/rejected triad.
- `products/agent-platform/src/agent_service/services/incident_client.py` — parallel `IncidentClientError` / `IncidentDependencyNotConfigured` / `IncidentServiceUnavailable` / `IncidentNotFound` hierarchy.
- `products/agent-platform/src/agent_service/api/v2/routes.py` — central HTTP mapper: catches client errors and raises `HTTPException(503|502|4xx)` with `from None` to suppress tracebacks.
- `products/platform-gateway/src/platform_gateway/services/token_verifier.py` — `TokenVerificationError` wrapping JWT library errors (`ExpiredSignatureError`, `InvalidIssuerError`, `InvalidAudienceError`, `InvalidTokenError`).
- `products/platform-gateway/src/platform_gateway/services/policy_engine.py` — `PolicyLoadError` raised during YAML policy bundle parsing/validation.
- `products/audit-service/src/audit_service/services/audit_store.py` — `StoreError`.
- `products/incident-service/src/incident_service/services/connectors.py` — `ConnectorConfigError`.
- `products/incident-service/src/incident_service/services/incident_store.py` — `StoreError`.
- `products/incident-service/src/incident_service/services/triage.py` — `TriageError`.
- `products/execution-runtime/src/execution_runtime/services/execution_protocol.py` — `ProtocolError(ValueError)` shared between agent-platform and execution-runtime.
- `products/agent-platform/src/agent_service/runtime_kernel.py` — `UnknownModelError(ValueError)`.
- `products/agent-platform/src/agent_service/providers/base.py` — `ProviderConfigurationError(ValueError)`.

## Architecture and Conventions

1. **Three-tier failure classification for outbound clients.** The skills-client pattern (documented in its module docstring) is replicated by the incident client: failures are classified as *not configured* → 503, *transport/upstream 5xx* → 502, *upstream 4xx* → pass-through status + message. This is enforced by the caller in `routes.py` via explicit `except` branches that map each subclass to a specific status code.

2. **Structured error classes carry both a message and, when needed, a status code.** `SkillsClientRejected.__init__` stores `status_code` and `message` as attributes so the route can forward the upstream response verbatim. `TokenVerificationError` stores `detail` instead.

3. **Route-level translation, not middleware.** Errors are caught at the edge of each route or helper function (e.g. `_validate_skill_markdown`, the incident-draft builder block in routes.py lines 1240–1258) and re-raised as `HTTPException`. There is no shared `exception_handler` decorator registered per service.

4. **Traceback suppression on mapped errors.** Mapped exceptions use `raise HTTPException(...) from None` (see routes.py lines 1076–1080, 1244–1251) so the user-facing response contains only the structured `detail`, not a Python traceback. Exceptions that should preserve context (e.g. `IncidentNotFound` on line 1249) use `from exc`.

5. **Domain exceptions are thin data carriers.** They extend `Exception` or `ValueError` and typically do not add behavior beyond storing a message/status. Validation logic lives in the same module that raises them (e.g. `_parse_approval` in `policy_engine.py` raises `PolicyLoadError` with human-readable rule-context messages).

6. **Request correlation is separate from error handling.** `core/request_context.py` resolves `x-request-id` from headers, OTel trace ID, or UUID — this is attached to log records but is not embedded in error payloads.

## Conventions and Constraints

- Outbound dependency failures follow the **configured → unavailable → rejected** classification documented in `skills_client.py`'s module docstring and implemented identically in `incident_client.py`.
- Generated skill drafts are never returned unvalidated: the `_validate_skill_draft` helper maps `SkillsDependencyNotConfigured`→503, `SkillsServiceUnavailable`→502, `SkillsClientRejected`→passthrough, and the generation flow degrades to a skeleton on first validation failure, then returns 502 if even the skeleton fails (routes.py lines 1154–1212).
- Policy bundle loading errors raise `PolicyLoadError` with rule-indexed, source-qualified messages produced by `_parse_rules` / `_parse_approval` in `policy_engine.py`; callers surface these as startup/configuration failures rather than request-time errors.
- Token verification wraps every `pyjwt` exception into `TokenVerificationError` with a stable, non-leaky message (token_verifier.py lines 73–80).
- No repository-wide `@app.exception_handler` is registered in any of the production services; error-to-HTTP mapping is performed inline in route modules.
- Tests import `pydantic.ValidationError` directly against contracts (e.g. `tests/test_contracts.py` in multiple products), confirming that Pydantic validation errors are expected to propagate as-is through FastAPI's default handler.