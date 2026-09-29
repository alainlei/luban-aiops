---
kind: error_handling
name: Error Handling — Domain Exceptions, HTTPException Mapping, and Fail-Closed Contracts
category: error_handling
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/services/execution_protocol.py
    - products/agent-platform/src/agent_service/services/execution_worker_client.py
    - products/agent-platform/src/agent_service/api/v2/routes.py
    - products/platform-gateway/src/platform_gateway/services/token_verifier.py
    - products/platform-gateway/src/platform_gateway/services/policy_engine.py
    - products/tool-gateway/src/tool_gateway/services/policy_engine.py
    - products/agent-platform/src/agent_service/runtime_kernel.py
    - products/agent-platform/src/agent_service/app.py
    - products/platform-gateway/src/platform_gateway/app.py
---

## Approach

The Luban platform uses a layered error model across its nine Python FastAPI services:

1. **Domain exceptions** — per-service `*Error` classes (subclassing `Exception` or `ValueError`) represent business-level failures such as configuration errors, store failures, auth failures, policy load failures, and protocol violations.
2. **HTTP boundary** — route handlers raise FastAPI's `HTTPException` with explicit `status_code` + `detail`, letting FastAPI serialize it to JSON responses without custom exception handlers in most services.
3. **Inter-service contracts** — the agent-platform's execution handoff layer wraps transport/protocol failures in typed exceptions (`WorkerHandoffError`, `WorkerHandoffTimeout`, `ProtocolError`) carrying a machine-readable `reason` string so callers can distinguish "worker unavailable" from "timeout" vs. a structured verification rejection.
4. **Middleware logging** — each service registers an `http` middleware that logs every request/response pair (method, path, status_code, duration_ms, x-request-id) via the shared `log_event` observability helper; this is the closest thing to a centralized error log sink.
5. **No global exception handler** — no service defines `@app.exception_handler(...)` for domain errors; only the sample `acme-admin` app registers one for its own `AdminAuthRequired`. The production services rely on FastAPI's default `HTTPException` serialization and let domain exceptions bubble up (typically surfaced by tests).

## Key files and packages

- `products/agent-platform/src/agent_service/services/execution_protocol.py` — `ProtocolError(ValueError)` with a `reason` attribute; used throughout the signed execution envelope validation pipeline.
- `products/agent-platform/src/agent_service/services/execution_worker_client.py` — `WorkerHandoffError(Exception)` with `reason: str` and `WorkerHandoffTimeout`; documents the fail-closed posture and never returns error dicts over the wire.
- `products/platform-gateway/src/platform_gateway/services/token_verifier.py` — `TokenVerificationError(Exception)` with `detail: str`; raised for JWKS resolution, expired tokens, invalid issuer/audience, and generic token errors.
- `products/platform-gateway/src/platform_gateway/services/policy_engine.py` — `PolicyLoadError(Exception)`.
- `products/tool-gateway/src/tool_gateway/services/policy_engine.py` — `PolicyLoadError(Exception)`.
- Per-service config/store/auth errors: `SettingsError`, `StoreError`, `QueryAuthError`, `ConnectorConfigError`, `NormalizationError`, `TriageError`, `ExchangeError`, `IncidentClientError`, `SkillsClientError`, `ProviderConfigurationError`, `UnknownModelError`, `DigestInputError`, `UnknownSessionError`, `IngestAuthError`.
- Route layer: `products/agent-platform/src/agent_service/api/v2/routes.py` — primary site of `HTTPException` usage (401, 409, 410, 422, 404, 502, 503).
- App bootstrap: `products/agent-platform/src/agent_service/app.py`, `products/platform-gateway/src/platform_gateway/app.py` — register the `http` logging middleware but no custom exception handlers.

## Architecture and conventions

### Domain exceptions carry a reason code
Most domain exceptions expose a single machine-readable field:
- `ProtocolError(reason)` — reasons include `bad_request`, `protocol_unsupported`, `signing_unavailable`, `signature_invalid`, `lifetime_invalid`, `identity_conflict`, `response_invalid`, `metadata_replay`, `wait_expired`, `transport_error`, `gateway_not_configured`, `credential_missing`, `args_digest_mismatch`, `response_invalid`.
- `WorkerHandoffError(reason, message)` — `reason` defaults to `REASON_WORKER_UNAVAILABLE = "worker_unavailable"`; the docstring states the fail-closed posture explicitly.
- `TokenVerificationError(detail)` — detail strings like `"token expired"`, `"invalid token issuer"`, `"invalid token audience"`, `"unable to resolve signing key"`.
- Other services follow the same shape: `StoreError`, `QueryAuthError`, `SettingsError`, `PolicyLoadError`, `ConnectorConfigError`, `NormalizationError`, `TriageError`, `ExchangeError`, `IncidentClientError`, `SkillsClientError`, `ProviderConfigurationError`, `UnknownModelError`, `DigestInputError`, `UnknownSessionError`, `IngestAuthError`.

### HTTP boundary mapping lives in routes
Route handlers translate domain exceptions into `HTTPException` with explicit status codes:
- Missing identity header → 401.
- Unknown model id / malformed skill target → 422.
- Confirmation pending / conflict → 409.
- Expired confirmation → 410.
- Session/incident not found → 404.
- Downstream worker failure → 502/503 with the underlying exception's message/status.
- Invalid recovery query → 400.

The pattern in `routes.py` is consistent: catch a lower-level exception, log or map it, then `raise HTTPException(status_code=..., detail=...) from None` to drop the traceback from the response payload.

### Inter-service errors are typed, not dict payloads
The execution handoff client (`execution_worker_client.py`) enforces that the wire never carries raw error objects. Transport failures become `WorkerHandoffError("worker_unavailable", ...)`; timeouts become `WorkerHandoffTimeout`; structured 4xx rejections from the worker are parsed for an `error.reason` field and re-raised with that reason. The v3 exchange path (`handoff_original`) goes further: all parsing/validation failures collapse to `ProtocolError("response_invalid")` or `ProtocolError("transport_error")`, and cancellation/timeout collapses to `ProtocolError("wait_expired")`.

### No centralized exception-to-JSON mapper
Services do not define `@app.exception_handler(YourError)`. Instead, they either:
- Raise `HTTPException` directly at the API boundary, or
- Let domain exceptions propagate (caught by tests), or
- Catch them inside route handlers and convert to `HTTPException`.

The only `exception_handler` registration in the repo is in `samples/acme-admin/app/src/acme_admin/main.py` for `AdminAuthRequired`, which is a sample, not a production service.

### Logging is uniform, error presentation is not
Every service's `create_app()` installs an `http` middleware that emits a `http_request` event with `service`, `request_id`, `method`, `path`, `status_code`, and `duration_ms`. This is the cross-cutting error observability mechanism. There is no shared structured error formatter applied globally.

### Settings validation raises plain `ValueError`
`RuntimeSettings` (and equivalent settings classes in other services) validate environment variables by raising `ValueError` with human-readable messages (e.g. `"AGENTSCOPE_MAX_ITERS must be >= 1."`). These are startup-time failures, not runtime domain errors.

## Conventions and constraints

- Domain exceptions subclass `Exception` (or `ValueError` for protocol/config errors) and expose a single machine-readable attribute (`reason` or `detail`) rather than embedding structured payloads in the message.
- Inter-service boundaries (execution handoff) wrap transport errors in typed exceptions with a stable `reason` code instead of returning error dicts; the docstring in `execution_worker_client.py` states the fail-closed posture as an invariant.
- Route handlers map domain failures to explicit HTTP status codes (401, 409, 410, 422, 404, 502, 503) using `HTTPException`; there is no global exception handler registering these mappings.
- Sensitive data (URLs, payloads, credentials) is deliberately excluded from error logs — see the transport-error branch in `execution_worker_client.py` which logs only `exc.__class__.__name__` and never the exception text.
- Settings validation uses bare `ValueError` with descriptive messages; these are treated as configuration errors, not runtime domain errors.
- The only documented enforcement source is the module docstring in `execution_worker_client.py`: "Fail-closed posture: a missing worker URL or handoff token raises before any network call... timeouts raise WorkerHandoffTimeout... any transport error raises WorkerHandoffError with worker_unavailable — there is no in-process fallback."