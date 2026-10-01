---
kind: error_handling
name: Error Handling — Domain Exceptions, HTTPException Mapping, and Client Error Hierarchies
category: error_handling
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/api/v2/routes.py
    - products/agent-platform/src/agent_service/services/incident_client.py
    - products/agent-platform/src/agent_service/services/skills_client.py
    - products/agent-platform/src/agent_service/providers/base.py
    - products/agent-platform/src/agent_service/runtime_kernel.py
    - products/agent-platform/src/agent_service/runtime_settings.py
    - products/platform-gateway/src/platform_gateway/services/policy_engine.py
    - products/platform-gateway/src/platform_gateway/services/token_verifier.py
    - products/tool-gateway/src/tool_gateway/services/token_verifier.py
    - products/incident-service/src/incident_service/core/config.py
    - products/incident-service/src/incident-service/services/connectors.py
    - products/incident-service/src/incident-service/services/incident_store.py
    - products/incident-service/src/incident-service/services/normalization.py
    - products/incident-service/src/incident-service/services/query_auth.py
    - products/incident-service/src/incident-service/services/triage.py
    - products/skills-hub/src/skills_hub/core/config.py
    - products/skills-hub/src/skills_hub/services/query_auth.py
    - products/skills-hub/src/skills_hub/services/skill_store.py
    - products/audit-service/src/audit_service/services/audit_store.py
    - products/audit-service/src/audit_service/services/ingest_auth.py
    - products/identity-broker/src/identity_service/services/exchange_service.py
---

## Overview

The Luban platform uses a layered Python exception model: domain-level custom `Exception` subclasses propagate through service layers, while FastAPI route handlers translate them into `HTTPException`s with explicit status codes. There is no global `@app.exception_handler` registration in any product; each route layer catches and maps errors locally.

## Custom Exception Hierarchy

Each product defines its own small hierarchy of domain exceptions under `services/` (or `core/config.py` for configuration errors):

- **agent-platform**: `ProviderConfigurationError(ValueError)` for LLM provider misconfiguration (`providers/base.py`); `UnknownModelError(ValueError)` (`runtime_kernel.py`); `ProtocolError(ValueError)` (`services/execution_protocol.py`); `WorkerHandoffError`, `IncidentClientError`, `SkillsClientError`, `DigestInputError`, `UnknownSessionError`, `DevelopmentSessionRejected` (`services/*`).
- **incident-service**: `SettingsError`, `ConnectorConfigError`, `StoreError`, `NormalizationError`, `QueryAuthError`, `TriageError`.
- **platform-gateway**: `PolicyLoadError(Exception)`, `TokenVerificationError(Exception)` (with a `detail` attribute).
- **skills-hub**: `SettingsError`, `QueryAuthError`, `StoreError`.
- **tool-gateway**: `TokenVerificationError(Exception)` mirroring the gateway's shape.
- **identity-broker**: `ExchangeError`.
- **audit-service**: `StoreError`, `IngestAuthError`.

Client-facing client modules follow a consistent three-tier pattern: a base `*ClientError(Exception)` plus `*DependencyNotConfigured`, `*ServiceUnavailable`, and `*ClientRejected` variants carrying `status_code` and `message` attributes so callers can re-raise as `HTTPException(status_code=exc.status_code, detail=exc.message)`.

## Configuration Validation Errors

Configuration loading raises plain `ValueError` with descriptive messages rather than custom types:

- `RuntimeSettings.from_env()` raises `ValueError` for invalid env vars such as `AGENTSCOPE_MAX_ITERS < 1`, `AGENT_HITL_CONFIRM_TIMEOUT < 0`, empty `AGENTSCOPE_TIMEZONE`, etc. (`products/agent-platform/src/agent_service/runtime_settings.py`).
- Per-product `SettingsError` subclasses exist in `incident-service/core/config.py` and `skills-hub/core/config.py` but are not used by the shared runtime settings path.

## HTTP Layer Translation

FastAPI routes raise `fastapi.HTTPException` directly with explicit `status_code` and `detail`. The canonical mapping pattern appears in `products/agent-platform/src/agent_service/api/v2/routes.py`:

```python
except SkillsDependencyNotConfigured as exc:
    raise HTTPException(status_code=503, detail=str(exc)) from None
except SkillsServiceUnavailable as exc:
    raise HTTPException(status_code=502, detail=str(exc)) from None
except SkillsClientRejected as exc:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
```

This pattern is repeated for incident-client calls and document operations, consistently mapping:
- dependency-not-configured → 503
- upstream unavailable → 502
- upstream rejected (4xx) → passthrough via `exc.status_code`
- not-found → 404
- validation failure → 400 or 422
- missing auth header → 401

The `from None` chain suppresses the internal traceback from the HTTP response payload, keeping client-visible details minimal.

## No Global Exception Handler

A grep across the repo finds only one `@app.exception_handler` usage, in the sample app `samples/acme-admin/app/src/acme_admin/main.py`; none of the nine production products register a global handler. Error translation is therefore done inline at the route boundary.

## Middleware / Kernel Error Path

The agent-platform's `runtime_kernel.py` exposes an `UnknownModelError` that callers catch when selecting an LLM provider. The kernel itself does not swallow errors — it propagates them upward to the route layer, which then converts them to HTTP responses.

## Observability Integration

Errors are logged via the structured logger before conversion. For example, audit ingestion failures log `ingest rejected with {response.status_code}` (`services/audit_emitter.py`) before raising `RuntimeError`. The `TokenVerificationError` class carries a human-readable `detail` string that flows through to the HTTP response.

## Conventions Observed

1. **Domain exceptions are plain `Exception` subclasses** (or `ValueError` for configuration/validation), never wrapped in a single root type.
2. **Client-layer exceptions form a three-class hierarchy**: base `*ClientError` plus `*DependencyNotConfigured`, `*ServiceUnavailable`, `*ClientRejected` — enabling uniform 503/502/4xx routing at the API layer.
3. **Route handlers do all status-code mapping**; services return domain exceptions.
4. **Upstream 4xx is preserved** via `exc.status_code` on `*ClientRejected` rather than collapsed to a generic 400.
5. **Traceback suppression** uses `from None` on HTTP exceptions to avoid leaking internal stack traces to clients.
6. **No global exception handler** — every product handles its own error-to-HTTP mapping at the route layer.
7. **Configuration errors use `ValueError`** with machine-readable messages, not custom exception types.