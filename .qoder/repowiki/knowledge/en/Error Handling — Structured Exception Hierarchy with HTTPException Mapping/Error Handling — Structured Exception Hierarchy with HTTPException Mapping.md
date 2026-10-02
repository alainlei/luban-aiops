---
kind: error_handling
name: Error Handling — Structured Exception Hierarchy with HTTPException Mapping
category: error_handling
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/services/skills_client.py
    - products/agent-platform/src/agent_service/api/v2/routes.py
    - products/platform-gateway/src/platform_gateway/services/policy_engine.py
    - products/platform-gateway/src/platform_gateway/services/token_verifier.py
    - products/platform-gateway/src/platform_gateway/app.py
    - products/agent-platform/src/agent_service/app.py
    - products/execution-runtime/src/execution_runtime/services/execution_protocol.py
    - products/incident-service/src/incident_service/services/triage.py
    - products/incident-service/src/incident_service/services/query_auth.py
    - products/audit-service/src/audit_service/services/ingest_auth.py
    - products/tool-gateway/src/tool_gateway/services/policy_engine.py
---

## Approach

Luban's Python services use a layered error model:

1. **Domain exceptions** — per-service, small hierarchies of `Exception` subclasses (sometimes `ValueError` for configuration/validation) that carry structured context (`status_code`, `message`).
2. **HTTP boundary mapping** — FastAPI route handlers translate domain exceptions into `fastapi.HTTPException(status_code=..., detail=...)` responses.
3. **No global exception handler** — there is no repository-wide `@app.exception_handler` or middleware that catches and normalizes all exceptions; each service's routes perform the mapping explicitly.
4. **Logging via structured events** — the FastAPI `http` middleware in every service logs `http_request` events through `core.observability.log_event`, which records method, path, status_code, duration_ms, and request_id regardless of whether the response came from a successful handler or an `HTTPException`.

There is no `panic`/`recover` equivalent; Python exceptions are the sole propagation mechanism.

## Key Files and Packages

- `products/agent-platform/src/agent_service/services/skills_client.py` — canonical example of a structured hierarchy: `SkillsClientError` base, `SkillsDependencyNotConfigured` (503), `SkillsServiceUnavailable` (502), `SkillsClientRejected` (passthrough 4xx with `status_code`/`message`).
- `products/agent-platform/src/agent_service/api/v2/routes.py` — central HTTP mapper: catches `ProtocolError`, `UnknownSessionError`, `DigestInputError`, `SkillsDependencyNotConfigured`, `SkillsServiceUnavailable`, `SkillsClientRejected` and converts them to 400/404/409/502/503 `HTTPException`s.
- `products/platform-gateway/src/platform_gateway/services/policy_engine.py` — `PolicyLoadError` raised during YAML bundle parsing/validation.
- `products/platform-gateway/src/platform_gateway/services/token_verifier.py` — `TokenVerificationError`.
- `products/incident-service/src/incident_service/services/triage.py` — `TriageError`.
- `products/incident-service/src/incident_service/services/query_auth.py` — `QueryAuthError`.
- `products/audit-service/src/audit_service/services/ingest_auth.py` — `IngestAuthError`.
- `products/tool-gateway/src/tool_gateway/services/policy_engine.py` — mirrors platform-gateway's `PolicyLoadError`.
- `products/tool-gateway/src/tool_gateway/services/token_verifier.py` — mirrors platform-gateway's `TokenVerificationError`.
- `products/execution-runtime/src/execution_runtime/services/execution_protocol.py` — `ProtocolError` (mirrors agent-platform's).
- `products/identity-broker/src/identity_service/services/exchange_service.py` — `ExchangeError`.
- `products/skills-hub/src/skills_hub/services/skill_store.py` — `StoreError`.

## Architecture and Conventions

### Domain exception hierarchy
Each product defines its own small tree rooted at a service-specific base class:

| Service | Base class | Subclasses |
|---|---|---|
| agent-platform | `SkillsClientError`, `WorkerHandoffError`, `IncidentClientError`, `DigestInputError`, `UnknownSessionError`, `ProviderConfigurationError(ValueError)` | `SkillsDependencyNotConfigured`, `SkillsServiceUnavailable`, `SkillsClientRejected` |
| platform-gateway | `PolicyLoadError`, `TokenVerificationError` | — |
| tool-gateway | `PolicyLoadError`, `TokenVerificationError` | — |
| incident-service | `SettingsError`, `ConnectorConfigError`, `NormalizationError`, `QueryAuthError`, `TriageError`, `StoreError` | — |
| audit-service | `StoreError`, `IngestAuthError` | — |
| identity-broker | `ExchangeError` | — |
| skills-hub | `SettingsError`, `QueryAuthError`, `StoreError` | — |

The `SkillsClientError` hierarchy is the most complete: it carries both a human-readable message and an HTTP status code on the rejection variant, enabling one-to-one mapping back to the caller.

### HTTP boundary mapping pattern
Route handlers follow a consistent try/except shape (see `_validate_skill_draft` in `routes.py`):

```python
try:
    return await validate_skill_draft(settings, request_id, markdown)
except SkillsDependencyNotConfigured as exc:
    raise HTTPException(status_code=503, detail=str(exc)) from None
except SkillsServiceUnavailable as exc:
    raise HTTPException(status_code=502, detail=str(exc)) from None
except SkillsClientRejected as exc:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
```

Key rules observed in this mapping:
- `from None` suppresses the original traceback in the HTTP response body (the docstring calls these "structured errors" that "never [show] a raw traceback").
- Dependency-not-configured → 503.
- Transport failure or upstream 5xx → 502.
- Upstream 4xx → passthrough with the upstream's status code and message.
- An unvalidated draft is never returned when validation fails — consistency outranks availability on the knowledge-production path.

### Configuration / runtime validation
Runtime settings validation raises plain `ValueError` (e.g. `AGENTSCOPE_MAX_ITERS must be >= 1`, `AGENTSCOPE_TIMEZONE must not be empty`) rather than a custom exception type. These surface as 500s unless caught by a route wrapper.

### No centralized error middleware
Neither `agent_service/app.py` nor `platform_gateway/app.py` registers a global `exception_handler`. The only shared middleware is the `http` logging middleware that wraps every request/response pair for observability. Custom exception handling lives in route-level try/except blocks.

### Cross-service protocol errors
`ProtocolError(ValueError)` is defined identically in both `agent_platform` and `execution_runtime` under `services/execution_protocol.py`, indicating a shared contract between those two services for execution-worker communication failures.

## Conventions and Constraints

- **Domain exceptions are explicit**: each service defines a small set of named exception classes rather than raising bare `Exception` or `ValueError` for business logic paths.
- **HTTP responses are produced via `HTTPException`**, not by returning tuples or using a response encoder.
- **Traceback suppression**: mapped exceptions use `from None` so the client sees only the `detail` string, not a Python traceback.
- **Structured client errors carry `status_code` and `message` attributes** (see `SkillsClientRejected.__init__`) so the route layer can re-emit the upstream posture verbatim.
- **Dependency-not-configured vs. service-unavailable** are distinguished: missing config yields 503, transport/upstream-5xx yields 502.
- **Validation errors** (bad env vars, bad policy YAML) raise `ValueError` or `PolicyLoadError`; they are not turned into user-facing HTTP codes at the boundary in every case — some propagate as 500s.
- **No `try/finally` recovery or `sys.excepthook` customization** was found; errors propagate up to FastAPI's default handler after being converted to `HTTPException`.
- **Cross-product duplication**: `PolicyLoadError`, `TokenVerificationError`, and `ProtocolError` appear in both `platform-gateway` and `tool-gateway` (and `ProtocolError` also in `execution-runtime`), suggesting these are duplicated rather than shared from `shared-contracts`.