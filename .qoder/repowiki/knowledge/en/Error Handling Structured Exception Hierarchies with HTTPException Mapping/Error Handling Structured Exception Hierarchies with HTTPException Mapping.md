---
kind: error_handling
name: 'Error Handling: Structured Exception Hierarchies with HTTPException Mapping'
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
    - products/platform-gateway/src/platform_gateway/services/policy_engine.py
    - products/platform-gateway/src/platform_gateway/services/token_verifier.py
    - products/tool-gateway/src/tool_gateway/services/policy_engine.py
    - products/tool-gateway/src/tool_gateway/services/token_verifier.py
    - products/audit-service/src/audit_service/services/audit_store.py
    - products/incident-service/src/incident_service/core/config.py
    - products/skills-hub/src/skills_hub/core/config.py
    - products/agent-platform/src/agent_service/core/telemetry.py
---

## Approach

The Luban platform uses a **per-service structured exception hierarchy** layered on top of FastAPI's `HTTPException`. There is no shared base error class, no global `@app.exception_handler` registration, and no centralized error-code registry. Each product service defines its own small domain-specific exception classes (typically a base `*Error(Exception)` plus a handful of subclasses), and route handlers translate those into `fastapi.HTTPException(status_code=..., detail=...)` responses.

This is a Python/Pydantic/FastAPI stack — no third-party error library is used. The only `@app.exception_handler` in the repo lives in `samples/acme-admin/app/src/acme_admin/main.py`, which is sample code, not part of the platform services.

## Key Files and Packages

Domain exception hierarchies are defined inside each product under `src/<service>/services/` or `src/<service>/core/`:

- `products/agent-platform/src/agent_service/services/skills_client.py` — `SkillsClientError` / `SkillsDependencyNotConfigured` / `SkillsServiceUnavailable` / `SkillsClientRejected`
- `products/agent-platform/src/agent_service/services/incident_client.py` — `IncidentClientError` / `IncidentDependencyNotConfigured` / `IncidentServiceUnavailable` / `IncidentNotFound` / `IncidentClientRejected`
- `products/agent-platform/src/agent_service/services/execution_worker_client.py` — `WorkerHandoffError`
- `products/agent-platform/src/agent_service/runtime_kernel.py` — `UnknownModelError(ValueError)`
- `products/agent-platform/src/agent_service/providers/base.py` — `ProviderConfigurationError(ValueError)`
- `products/agent-platform/src/agent_service/services/execution_protocol.py` — `ProtocolError(ValueError)`
- `products/platform-gateway/src/platform_gateway/services/policy_engine.py` — `PolicyLoadError`
- `products/platform-gateway/src/platform_gateway/services/token_verifier.py` — `TokenVerificationError`
- `products/tool-gateway/src/tool_gateway/services/policy_engine.py` — `PolicyLoadError`
- `products/tool-gateway/src/tool_gateway/services/token_verifier.py` — `TokenVerificationError`
- `products/audit-service/src/audit_service/services/audit_store.py` — `StoreError`
- `products/audit-service/src/audit_service/services/ingest_auth.py` — `IngestAuthError`
- `products/incident-service/src/incident_service/core/config.py` — `SettingsError`
- `products/incident-service/src/incident_service/services/connectors.py` — `ConnectorConfigError`
- `products/incident-service/src/incident_service/services/incident_store.py` — `StoreError`
- `products/incident-service/src/incident_service/services/normalization.py` — `NormalizationError`
- `products/incident-service/src/incident_service/services/query_auth.py` — `QueryAuthError`
- `products/incident-service/src/incident_service/services/triage.py` — `TriageError`
- `products/skills-hub/src/skills_hub/core/config.py` — `SettingsError`
- `products/skills-hub/src/skills_hub/services/query_auth.py` — `QueryAuthError`
- `products/skills-hub/src/skills_hub/services/skill_store.py` — `StoreError`

The principal mapping layer is `products/agent-platform/src/agent_service/api/v2/routes.py`, which catches client errors and raises `HTTPException` with explicit status codes.

## Architecture and Conventions

### 1. Client-layer error taxonomy

Every outbound HTTP client (`skills_client.py`, `incident_client.py`) exposes a four-class hierarchy that mirrors the three HTTP postures the caller needs to distinguish:

| Class | Meaning | Route-level status code |
|---|---|---|
| `*DependencyNotConfigured` | Service URL/secret missing | `503` |
| `*ServiceUnavailable` | Transport failure or upstream `>= 500` | `502` |
| `*NotFound` | Domain-not-found (e.g. unknown incident id) | `404` |
| `*ClientRejected` | Upstream `4xx` with a message/status | passthrough `exc.status_code` |

The docstrings in both clients state this contract explicitly: "Errors surface as a small structured hierarchy so the [route] maps them to the house posture — 503 when the dependency is not configured, 502 on transport failure or upstream 5xx — and an unvalidated draft is never returned."

### 2. Route-level translation

`agent_service/api/v2/routes.py` contains all the `try/except` blocks that convert domain exceptions into `HTTPException`s. A representative pattern (from `_validate_skill_markdown`):

```python
except SkillsDependencyNotConfigured as exc:
    raise HTTPException(status_code=503, detail=str(exc)) from None
except SkillsServiceUnavailable as exc:
    raise HTTPException(status_code=502, detail=str(exc)) from None
except SkillsClientRejected as exc:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
```

The same shape is repeated for incident-client calls and other cross-service boundaries. Validation failures in skill-draft generation degrade to a facts-only skeleton rather than returning an invalid document — the comment says "consistency outranks availability on a knowledge-production path".

### 3. Error chaining discipline

When wrapping one exception into another, the code consistently uses either `from None` (to hide internal tracebacks from the client) or `from exc` (to preserve the chain for diagnostics):

- `from None` is used when converting domain errors to `HTTPException` so the operator sees a clean response body.
- `from exc` is used when re-raising the original cause (e.g. `IncidentNotFound` preserving the underlying lookup).

### 4. Non-HTTP errors

For non-HTTP paths, services raise their own domain exceptions directly:

- Configuration validation uses `ValueError` (e.g. `runtime_settings.py`, `schemas/v2.py`).
- Provider configuration uses `ProviderConfigurationError(ValueError)`.
- Protocol-level issues use `ProtocolError(ValueError)`.
- Storage/auth failures use per-service `*Error(Exception)` subclasses.

There is no `panic/recover` equivalent; Python exceptions propagate up to FastAPI, which converts unhandled ones to `500 Internal Server Error` responses.

### 5. No global exception handler

A search for `@app.exception_handler` across `products/*/src/**/*.py` returns zero matches. Error-to-HTTP conversion is done inline in route handlers rather than via a central middleware. This means each route is responsible for catching and translating the domain exceptions it can handle.

### 6. Telemetry swallows errors silently

`agent_service/core/telemetry.py` wraps telemetry emission in broad `except Exception:` blocks (lines ~123, 137, 204, 228, 238, 248). Failures in metrics/observability emission do not propagate — they are logged and ignored, ensuring observability does not break request processing.

## Conventions and Constraints

Observed conventions (descriptive, not enforced by lint/build):

1. **Per-service exception modules**: Domain errors live next to the code that raises them, typically under `services/` or `core/` within each product package. There is no shared `errors` package.
2. **Base + subclasses pattern**: Most hierarchies follow `<Domain>Error(Exception)` with specialized subclasses for config-missing, unavailable, not-found, and rejected cases.
3. **Status-code mapping at the route boundary**: Only route handlers raise `HTTPException`; business logic raises domain exceptions. The mapping table (dependency-not-configured → 503, transport/upstream-5xx → 502, 4xx passthrough) is documented in client module docstrings.
4. **`from None` for user-facing wrappers**: When converting a domain exception into an `HTTPException`, the original traceback is suppressed with `from None` so operators see only the `detail` string.
5. **Upstream messages are normalized**: Helper functions like `_upstream_message()` extract `error.message` from JSON payloads with a `try/except ValueError` fallback to a generic string, preventing malformed upstream responses from crashing the caller.
6. **Validation failures use `ValueError`**: Pydantic-style input validation errors are raised as plain `ValueError` with descriptive messages (see `runtime_settings.py`, `schemas/v2.py`).
7. **Telemetry is fail-open**: Broad `except Exception:` around telemetry calls ensures observability cannot take down requests.

No repository-wide rule enforces these patterns (no linter rule, no shared base class, no global exception handler). Enforcement is therefore limited to the explicit contracts stated in the docstrings of the client modules and the consistent repetition of the same try/except shape across routes.