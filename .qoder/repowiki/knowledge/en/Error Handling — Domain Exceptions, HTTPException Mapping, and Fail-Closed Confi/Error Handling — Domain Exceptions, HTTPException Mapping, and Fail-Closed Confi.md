---
kind: error_handling
name: Error Handling — Domain Exceptions, HTTPException Mapping, and Fail-Closed Configuration
category: error_handling
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/services/execution_worker_client.py
    - products/agent-platform/src/agent_service/api/v2/routes.py
    - products/skills-hub/src/skills_hub/core/config.py
    - products/incident-service/src/incident-service/src/incident_service/core/config.py
    - products/execution-runtime/src/execution_runtime/core/config.py
    - products/platform-gateway/src/platform_gateway/services/policy_engine.py
    - products/tool-gateway/src/tool_gateway/services/policy_engine.py
    - products/tool-gateway/src/tool_gateway/services/token_verifier.py
    - products/platform-gateway/src/platform_gateway/services/token_verifier.py
    - products/audit-service/src/audit_service/services/audit_store.py
    - products/incident-service/src/incident_service/services/connectors.py
    - products/incident-service/src/incident_service/services/incident_store.py
    - products/incident-service/src/incident_service/services/query_auth.py
    - products/incident-service/src/incident_service/services/triage.py
    - products/skills-hub/src/skills_hub/services/query_auth.py
    - products/skills-hub/src/skills_hub/services/skill_store.py
    - products/identity-broker/src/identity_service/services/exchange_service.py
    - products/agent-platform/src/agent_service/services/shift_summary.py
---

## Overview

The Luban platform uses a layered error model that is consistent across all nine Python services (`agent-platform`, `audit-service`, `execution-runtime`, `identity-broker`, `incident-service`, `platform-gateway`, `skills-hub`, `tool-gateway`, `operator-portal` backend). Errors are expressed as typed domain exceptions in `services/`, validated at startup via configuration dataclasses in `core/config.py`, and surfaced to callers through FastAPI's `HTTPException`. There is no global exception handler registered; routes catch service-layer exceptions and translate them into status codes. Panics (`raise Exception`) are reserved for programming errors; runtime failures raise domain-specific subclasses.

## Startup-time validation (fail-fast)

Each service defines frozen `@dataclass` settings loaded from environment variables with a `from_env()` classmethod and an `@lru_cache(maxsize=1)` `get_settings()` accessor. Validation happens in `__post_init__` or dedicated `parse_*` helpers:

- `execution_runtime.core.config.ExecutionSettings.__post_init__` raises `ValueError` for out-of-range `EXECUTION_GATEWAY_TIMEOUT_SECONDS`, unknown `EXECUTION_STATE_STORE_BACKEND`, and negative `EXECUTION_FLIGHT_RETENTION_SECONDS`.
- `skills_hub.core.config.SettingsError` wraps malformed JSON, duplicate `source_id`, invalid `source_id` regex, missing required fields, and non-positive `SKILLS_COMPOSITION_MAX_SUB_SKILLS`.
- `incident_service.core.config.SettingsError` is defined for the same purpose in the incident service.
- `policy_engine.PolicyLoadError` is raised when a policy YAML bundle is malformed, contains unknown outcomes, or has invalid approval blocks.

This pattern ensures misconfiguration kills the process at startup rather than failing later at request time.

## Domain exceptions per service

Services define small, focused exception classes in their `services/` modules, each carrying enough context to be mapped to an HTTP status code:

| Service | Exception(s) | Meaning |
|---|---|---|
| `agent-platform` | `WorkerHandoffError(reason, message)`, `WorkerHandoffTimeout`, `IncidentClientError`, `SkillsClientError`, `DigestInputError`, `UnknownSessionError` | Handoff transport failure, timeout, upstream client rejection, digest/session errors |
| `audit-service` | `StoreError`, `IngestAuthError` | Store I/O and ingestion auth failures |
| `identity-broker` | `ExchangeError` | Token exchange failures |
| `incident-service` | `ConnectorConfigError`, `StoreError`, `NormalizationError`, `QueryAuthError`, `TriageError` | Connector/store/auth/normalization/triage failures |
| `platform-gateway` | `PolicyLoadError`, `TokenVerificationError` | Policy bundle load and token verification failures |
| `skills-hub` | `StoreError`, `QueryAuthError` | Store and query auth failures |
| `tool-gateway` | `PolicyLoadError`, `TokenVerificationError` | Same shape as platform-gateway |

Exceptions carry structured attributes (e.g. `WorkerHandoffError.reason`, `SkillsClientRejected.status_code/message`, `PolicyLoadError` messages) so route handlers can map them precisely.

## Route-level mapping to HTTP responses

Routes do not use a central `@app.exception_handler`; instead they wrap service calls in `try/except` blocks and raise `fastapi.HTTPException` with explicit status codes. The canonical pattern appears in `agent_platform.api.v2.routes._validate_skill_markdown` and surrounding draft endpoints:

```python
except SkillsDependencyNotConfigured as exc:
    raise HTTPException(status_code=503, detail=str(exc)) from None
except SkillsServiceUnavailable as exc:
    raise HTTPException(status_code=502, detail=str(exc)) from None
except SkillsClientRejected as exc:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
```

Upstream dependency failures follow a fixed posture: "not configured" → 503, unreachable/upstream 5xx → 502, client-side rejections → pass-through status code, business logic violations → 400/409/404/422. This keeps the API contract stable even when downstream services are degraded.

## Cross-service handoff errors

The `agent-platform` → `execution-runtime` handoff in `services/execution_worker_client.py` is the most detailed example of error propagation across service boundaries. It enforces a fail-closed posture:

- Missing worker URL or handoff token raises `WorkerHandoffError(REASON_WORKER_UNAVAILABLE, ...)` before any network call.
- `httpx.TimeoutException` is caught and re-raised as `WorkerHandoffTimeout` (a distinct type so callers can distinguish timeout from rejection).
- Any other `httpx.HTTPError` is logged with only the exception class name (never the message, which could echo URLs/payloads) and re-raised as `WorkerHandoffError(REASON_WORKER_UNAVAILABLE, ...)`.
- Non-200 responses attempt to parse a structured `{error: {reason: ...}}` payload; if parsing fails the reason degrades to `worker_unavailable`.
- The v3 original-handoff path (`handoff_original`) validates every field against schemas and raises `ProtocolError` with enumerated reasons (`gateway_not_configured`, `credential_missing`, `args_digest_mismatch`, `bad_request`, `wait_expired`, `transport_error`, `response_invalid`, `metadata_replay`).

## Telemetry and metrics resilience

Every service's `core/telemetry.py` wraps metric emission in `except Exception:` blocks that log and continue. This guarantees that observability failures never break request handling. Similarly, `execution_runtime.core.metrics` catches exceptions during gauge refreshes so Prometheus scraping never fails.

## Configuration error handling conventions

- Settings are immutable (`frozen=True` dataclasses) — mutation after load is impossible.
- Secrets are optional and treated as absent rather than fatal unless explicitly required by a feature branch (e.g. execution-runtime comments state missing secrets keep health checks serving; verification fails closed at the handoff step).
- Numeric/string parsing falls back to defaults where safe (e.g. `tool_gateway.core.runtime._resolve_port` returns the default port when Kubernetes injects `tcp://IP:PORT` instead of a plain integer), but validation-sensitive values raise `ValueError` / `SettingsError`.
- Boolean flags are parsed via `.strip().lower() in {"1", "true", "yes", "on"}`.

## What is NOT used

- No `try/except` around entire request handlers — errors are handled at the boundary of each service call.
- No custom FastAPI exception handlers registered in `app.py` files; translation is inline in route handlers.
- No `logging.exception(...)` on user-facing paths; transport errors log at `warning` level with sanitized messages.
- No `sys.exit()` or `os.abort()` outside startup; failures propagate as exceptions.