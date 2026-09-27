---
kind: error_handling
name: Error Handling — Domain Exceptions, FastAPI HTTPException Mapping, and Cross-Service Error Codes
category: error_handling
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/api/v2/routes.py
    - products/agent-platform/src/agent_service/services/execution_protocol.py
    - products/agent-platform/src/agent_service/providers/base.py
    - products/agent-platform/src/agent_service/services/execution_worker_client.py
    - products/agent-platform/src/agent_service/services/incident_client.py
    - products/agent-platform/src/agent_service/services/skills_client.py
    - products/platform-gateway/src/platform_gateway/services/policy_engine.py
    - products/platform-gateway/src/platform_gateway/services/token_verifier.py
    - products/audit-service/src/audit_service/services/audit_store.py
    - products/identity-broker/src/identity_service/services/exchange_service.py
    - products/incident-service/src/incident_service/core/config.py
    - products/incident-service/src/incident_service/services/connectors.py
    - products/incident-service/src/incident_service/services/incident_store.py
    - products/incident-service/src/incident_service/services/normalization.py
    - products/incident-service/src/incident_service/services/query_auth.py
    - products/incident-service/src/incident_service/services/triage.py
    - products/skills-hub/src/skills_hub/core/config.py
    - products/agent-platform/src/agent_service/app.py
    - products/platform-gateway/src/platform_gateway/app.py
---

## Approach

The Luban platform uses a layered Python error model across its nine services:

1. **Domain exceptions** — per-service `*Error` classes (subclassing `Exception` or `ValueError`) represent business-level failures.
2. **Protocol errors** — a shared `ProtocolError(reason: str)` sentinel used between agent-platform and execution-runtime for wire-format / signing / handoff validation.
3. **FastAPI `HTTPException`** — the sole HTTP boundary; routes translate domain/protocol errors into status codes with human-readable `detail` strings.
4. **No global exception handlers** — each service registers no `@app.exception_handler`; FastAPI's default JSON error response is used for unhandled exceptions, while route code explicitly raises `HTTPException` for expected cases.
5. **Middleware only logs** — the `http` middleware in every service (`agent_service/app.py`, `platform_gateway/app.py`, etc.) records `http_request` events with `status_code` but does not transform errors.

## Key Files and Packages

| Layer | Representative files |
|---|---|
| Agent-platform domain errors | `products/agent-platform/src/agent_service/providers/base.py` (`ProviderConfigurationError(ValueError)`), `services/execution_protocol.py` (`ProtocolError(ValueError)`), `services/execution_worker_client.py` (`WorkerHandoffError`), `services/incident_client.py` (`IncidentClientError`), `services/skills_client.py` (`SkillsClientError`), `services/shift_summary.py` (`DigestInputError`, `UnknownSessionError`) |
| Platform-gateway domain errors | `services/policy_engine.py` (`PolicyLoadError`), `services/token_verifier.py` (`TokenVerificationError`) |
| Other services | `audit-service/services/audit_store.py` (`StoreError`), `identity-broker/services/exchange_service.py` (`ExchangeError`), `incident-service/core/config.py` (`SettingsError`), `incident-service/services/connectors.py` (`ConnectorConfigError`), `incident-service/services/incident_store.py` (`StoreError`), `incident-service/services/normalization.py` (`NormalizationError`), `incident-service/services/query_auth.py` (`QueryAuthError`), `incident-service/services/triage.py` (`TriageError`), `skills-hub/core/config.py` (`SettingsError`) |
| HTTP boundary | `products/agent-platform/src/agent_service/api/v2/routes.py` (central `HTTPException` mapper) |
| App bootstrap (middleware) | `products/agent-platform/src/agent_service/app.py`, `products/platform-gateway/src/platform_gateway/app.py` |

## Architecture and Conventions

### Domain exceptions are narrow and typed
Each product defines small, purpose-specific exception classes rather than reusing generic `Exception`. Examples include `ProviderConfigurationError` (LLM provider config), `PolicyLoadError` (policy bundle parse/validation), `TokenVerificationError` (JWT decode/signing-key resolution), `ConnectorConfigError`, `NormalizationError`, `TriageError`, `StoreError`, `ExchangeError`, `SkillsClientError`, `WorkerHandoffError`, `IncidentClientError`, `DigestInputError`, `UnknownSessionError`, `UnknownModelError`.

### `ProtocolError` is the inter-process contract layer
Defined in both `agent_service/services/execution_protocol.py` and `execution_runtime/services/execution_protocol.py`, it carries a short string `reason` (`bad_request`, `protocol_unsupported`, `signing_unavailable`, `signature_invalid`, `lifetime_invalid`, `identity_conflict`, `response_invalid`, `metadata_replay`, `store_unavailable`, `schema_invalid`). It subclasses `ValueError` so callers can catch it as a value-error family. The `validate_*` helpers swallow low-level `ValueError`/`TypeError`/`KeyError`/`RecursionError` and re-raise as `ProtocolError("bad_request"|"response_invalid")` via `from None` to suppress the original traceback.

### Route-layer mapping is explicit and centralized
`products/agent-platform/src/agent_service/api/v2/routes.py` contains the canonical mapping from domain/protocol errors to HTTP status codes. The pattern appears repeatedly:

```python
except SkillsDependencyNotConfigured as exc:
    raise HTTPException(status_code=503, detail=str(exc)) from None
except SkillsServiceUnavailable as exc:
    raise HTTPException(status_code=502, detail=str(exc)) from None
except SkillsClientRejected as exc:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
```

The same shape is used for upstream calls to incidents, skills, and execution workers. Status-code mapping rules documented in the file comments include:
- Not configured → 503
- Unreachable / upstream 5xx → 502
- Any other 4xx passed through
- Unknown session id → 404 (anti-enumeration convention)
- Session with parked confirmation delete → 409
- Invalid recovery query → 400

### Token verification centralizes JWT failure modes
`platform_gateway/services/token_verifier.py.verify_token` catches `jwt.ExpiredSignatureError`, `InvalidIssuerError`, `InvalidAudienceError`, `InvalidTokenError`, and any other exception during JWKS resolution, wrapping them all in `TokenVerificationError` with a stable message. Callers then map this to an HTTP response at the gateway router layer.

### Policy loading fails fast
`PolicyLoadError` is raised by `_parse_approval` and `_parse_rules` when YAML is malformed, required fields are missing, `outcome` is unknown, or `require_approval` is applied to non-bridged actions. There is no retry or degradation path — invalid policy bundles are rejected at load time.

### No panic/recover strategy
Python has no `panic`/`recover`; the codebase does not use `try/finally` around user request processing beyond logging and background task cancellation. `except Exception` blocks appear only in telemetry emission paths (`core/telemetry.py`) where instrumentation must never break application logic.

### Test fixtures mirror production error behavior
Failure tests under `products/execution-runtime/tests/failure/` and `products/platform-gateway/tests/test_chat_stream_modality.py` assert that domain exceptions propagate through the HTTP boundary with the correct status code and detail, confirming the mapping is part of the acceptance surface.

## Conventions and Constraints

- **Domain exceptions are per-service**: each product defines its own `*Error` class(es); there is no shared base exception package. This is observed in `agent_platform`, `platform_gateway`, `audit_service`, `identity_broker`, `incident_service`, `skills_hub`, and `execution_runtime`.
- **Wire/format validation returns `ProtocolError` with a string reason**, not a rich object. Consumers match on the reason string (e.g. `"bad_request"`, `"signature_invalid"`).
- **HTTP responses are produced exclusively via `fastapi.HTTPException`** with explicit `status_code` and `detail`; no custom exception handler is registered in any product app.
- **Upstream dependency failures follow a fixed posture**: configuration-missing → 503, unreachable/upstream 5xx → 502, client rejection → pass-through `exc.status_code`/`exc.message`.
- **Anti-enumeration convention**: foreign or unknown IDs return 404 rather than 403/404 ambiguity (documented in route docstrings such as the session delete route).
- **Traceback suppression**: mapped exceptions use `from None` to avoid leaking internal stack traces in HTTP error bodies; original exceptions are preserved with `from exc` only when the caller needs the chain (e.g. `TokenVerificationError` wrapping `jwt.*` errors).
- **Middleware is read-only for errors**: the `http` middleware in every service logs `status_code` but never modifies or wraps exceptions.