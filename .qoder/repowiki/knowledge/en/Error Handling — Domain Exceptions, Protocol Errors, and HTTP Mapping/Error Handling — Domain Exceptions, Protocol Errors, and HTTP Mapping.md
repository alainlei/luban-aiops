---
kind: error_handling
name: Error Handling — Domain Exceptions, Protocol Errors, and HTTP Mapping
category: error_handling
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/services/execution_protocol.py
    - products/agent-platform/src/agent_service/services/execution_catalog.py
    - products/agent-platform/src/agent_service/providers/base.py
    - products/agent-platform/src/agent_service/runtime_kernel.py
    - products/agent-platform/src/agent_service/api/v2/routes.py
    - products/agent-platform/src/agent_service/app.py
    - products/platform-gateway/src/platform_gateway/app.py
---

## Overview

The Luban platform is a multi-service Python/FastAPI codebase. Error handling follows three layered conventions:

1. **Domain / protocol exceptions** raised inside service logic (e.g. `ProtocolError`, `ProviderConfigurationError`, `UnknownModelError`).
2. **HTTP-level mapping** in route handlers that translate domain exceptions into `fastapi.HTTPException` with explicit status codes.
3. **Middleware logging** around every request for observability; no global exception handler is registered — FastAPI's default JSON error responses are used.

There is no repository-wide shared error package. Each product defines its own small set of sentinel exceptions and maps them at the API boundary.

## Key files and packages

- `products/agent-platform/src/agent_service/services/execution_protocol.py` — defines `ProtocolError(ValueError)` with a `.reason` attribute and a fixed vocabulary of reason strings (`bad_request`, `protocol_unsupported`, `signing_unavailable`, `signature_invalid`, `lifetime_invalid`, `identity_conflict`, `response_invalid`, `metadata_replay`). This is the canonical error type for the execution wire protocol between agent-service and execution-runtime.
- `products/agent-platform/src/agent_service/providers/base.py` — defines `ProviderConfigurationError(ValueError)`, raised by every LLM provider implementation when configuration is missing or invalid.
- `products/agent-platform/src/agent_service/runtime_kernel.py` — defines `UnknownModelError(ValueError)`.
- `products/agent-platform/src/agent_service/api/v2/routes.py` — the single place where domain exceptions from downstream services are caught and mapped to `HTTPException(status_code=..., detail=...)`. It also contains the helper `_validate_skill_markdown` which centralizes the mapping of skills-hub dependency errors (`SkillsDependencyNotConfigured` → 503, `SkillsServiceUnavailable` → 502, `SkillsClientRejected` → passthrough `exc.status_code`/`exc.message`).
- `products/platform-gateway/src/platform_gateway/app.py` — registers an `http` middleware that logs every request/response pair but does not catch exceptions; it simply forwards the response (including FastAPI's default error responses).
- `products/agent-platform/src/agent_service/app.py` — same pattern: logging middleware only, no custom exception handler.

## Architecture and conventions

### Sentinel exceptions carry a machine-readable code

`ProtocolError` stores both the human-readable message and a stable string `.reason`. Call sites raise it with one of the documented reason constants rather than ad-hoc messages. The same pattern is used for domain-specific failures like `ProviderConfigurationError` and the various `*NotFound` / `*Unavailable` / `*Rejected` exceptions raised by client helpers (e.g. `IncidentNotFound`, `SkillsClientRejected`) — these expose `status_code` and `message` attributes so routes can forward them verbatim.

### Route handlers perform the exception-to-HTTP mapping

In `routes.py`, downstream calls are wrapped in `try/except` blocks that map each known exception class to an HTTP status:

| Downstream exception | Mapped status | Notes |
|---|---:|---|
| `SkillsDependencyNotConfigured` | 503 | "not configured" posture |
| `SkillsServiceUnavailable` | 502 | unreachable upstream |
| `SkillsClientRejected` | passthrough | uses `exc.status_code` / `exc.message` |
| `IncidentDependencyNotConfigured` | 503 | |
| `IncidentServiceUnavailable` | 502 | |
| `IncidentNotFound` | 404 | |
| `NoValidatedTriageReport` | 409 | business precondition |
| Other `IncidentClientRejected` | passthrough | |

This is the de facto contract: service-layer code raises typed exceptions; route handlers decide the HTTP semantics.

### Validation functions swallow non-fatal parsing errors

`execution_protocol.validate()` and `validate_original()` wrap schema validation and canonicalization in `try/except (ValueError, TypeError, RecursionError)` and re-raise as `ProtocolError("bad_request")` / `ProtocolError("response_invalid")` with `from None` to suppress the original traceback. This keeps malformed input out of audit trails and logs.

### No global exception handler

Neither `platform_gateway.app.create_app()` nor `agent_service.app.create_app()` registers an `@app.exception_handler`. Requests flow through the logging middleware unchanged, and FastAPI's built-in 4xx/5xx JSON error responses are returned directly. There is no centralized error formatter, no panic/recover, and no `sys.excepthook` customization observed.

### Logging is uniform via `log_event`

Both services configure logging through `core.observability.configure_logging()` and emit structured events via `log_event(LOGGER, event_name, ...)`. The HTTP middleware records `method`, `path`, `status_code`, `duration_ms`, and `request_id` on every response, including error responses. Internal failures use `LOGGER.exception(...)` (e.g. telemetry setup failures in `telemetry.py`) to preserve tracebacks while allowing the process to continue.

## Conventions and constraints

- **Domain exceptions are subclasses of `ValueError`**, not generic `Exception`. This is visible in `ProtocolError(ValueError)`, `ProviderConfigurationError(ValueError)`, and `UnknownModelError(ValueError)`.
- **Wire protocol failures use `ProtocolError` with a reason string** from a fixed set defined in `execution_protocol.py`; callers of the execution protocol must catch `ProtocolError` (see `execution_invocation.py` lines 124, 158) rather than arbitrary `ValueError`s.
- **Route handlers explicitly map each downstream exception class** to an HTTP status code; there is no blanket `except Exception` catching all errors at the API layer. The comment in `_validate_skill_markdown` documents the policy: "validation not configured 503, unreachable or upstream 5xx 502, any other 4xx passed through — an unvalidated draft is never returned."
- **Structured errors from clients expose `status_code` and `message`** (e.g. `SkillsClientRejected`, `IncidentClientRejected`) so routes can forward them without losing the upstream status.
- **Validation helpers strip tracebacks** using `raise ... from None` after converting low-level parse/validation failures into domain protocol errors.
- **No global FastAPI exception handler exists** in either `platform_gateway` or `agent-service`; error presentation is delegated to FastAPI's defaults.
- **Logging middleware is present in every service** (`app.py`), but it only observes — it does not transform or suppress exceptions.