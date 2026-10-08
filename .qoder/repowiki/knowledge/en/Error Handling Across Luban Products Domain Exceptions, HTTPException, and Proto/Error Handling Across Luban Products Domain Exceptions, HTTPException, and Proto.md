---
kind: error_handling
name: 'Error Handling Across Luban Products: Domain Exceptions, HTTPException, and Protocol Errors'
category: error_handling
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/services/execution_protocol.py
    - products/execution-runtime/src/execution_runtime/services/execution_protocol.py
    - products/agent-platform/src/agent_service/providers/base.py
    - products/agent-platform/src/agent_service/app.py
    - products/platform-gateway/src/platform_gateway/core/observability.py
    - products/agent-platform/src/agent_service/core/observability.py
    - products/platform-gateway/src/platform_gateway/api/routes/audit.py
    - products/platform-gateway/src/platform_gateway/api/routes/policy.py
    - products/execution-runtime/src/execution_runtime/api/routes/handoff.py
    - shared/shared-contracts/schemas
---

## Overview

The Luban platform is a multi-product Python monorepo (agent-platform, audit-service, execution-runtime, identity-broker, incident-service, platform-gateway, skills-hub, tool-gateway). Error handling is not centralized in a shared library; instead each product defines its own domain exceptions while FastAPI's `HTTPException` is used at API boundaries. Cross-process protocol validation errors are modeled as a small sentinel-error pattern using a `ProtocolError(ValueError)` with a string `reason` attribute.

There is no repository-wide exception base class, no global FastAPI `exception_handler`, and no `panic/recover` equivalent — Python exceptions propagate normally through the call stack and are converted to HTTP responses only at route handlers or explicit boundary code.

## Key Files and Packages

- `products/agent-platform/src/agent_service/services/execution_protocol.py` — defines `ProtocolError(ValueError)` with a `reason` attribute; all wire-format / envelope validation failures raise it with string codes (`bad_request`, `protocol_unsupported`, `signing_unavailable`, `signature_invalid`, `lifetime_invalid`, `identity_conflict`, `response_invalid`, `metadata_replay`).
- `products/execution-runtime/src/execution_runtime/services/execution_protocol.py` — duplicate `ProtocolError` definition for the worker side, keeping agent and runtime independent.
- `products/agent-platform/src/agent_service/providers/base.py` — `ProviderConfigurationError(ValueError)`, raised by every provider adapter when settings are missing/mismatched.
- Per-product domain exceptions:
  - `audit_store.StoreError`, `ingest_auth.IngestAuthError`
  - `exchange_service.ExchangeError`
  - `incident_store.StoreError`, `connectors.ConnectorConfigError`, `normalization.NormalizationError`, `query_auth.QueryAuthError`, `triage.TriageError`, `config.SettingsError`
  - `policy_engine.PolicyLoadError`, `token_verifier.TokenVerificationError`
  - `skills_hub.core.config.SettingsError`, `skills_hub.services.query_auth.QueryAuthError`, `skills_hub.services.skill_store.StoreError`
  - `agent_platform.runtime_kernel.UnknownModelError`, `services.WorkerHandoffError`, `IncidentClientError`, `SkillsClientError`, `shift_summary.DigestInputError`, `UnknownSessionError`
- `products/agent-platform/src/agent_service/app.py` — FastAPI app factory; registers an HTTP middleware that logs requests but does **not** install any custom exception handler. Unhandled exceptions fall through to FastAPI's default JSON error response.
- `products/platform-gateway/src/platform_gateway/api/routes/*.py` — routes raise `HTTPException(status_code=..., detail=...)` directly for client-facing errors (401, 409, 410, 422, 502, 503).
- `products/platform-gateway/src/platform_gateway/core/observability.py` and per-product equivalents — `configure_logging()` raises root logger level from Uvicorn's default WARNING to INFO so structured log events survive; `log_event()` emits JSON payloads via `logging.info`.

## Architecture and Conventions

### 1. Domain exceptions over sentinels
Each service layer defines a small set of named exception classes inheriting from `Exception` (or `ValueError` for configuration/validation cases). Examples include `StoreError`, `QueryAuthError`, `ConnectorConfigError`, `NormalizationError`, `TriageError`, `PolicyLoadError`, `TokenVerificationError`. These carry no payload convention beyond the standard exception message; callers inspect type, not fields.

### 2. Protocol-level sentinel errors
For cross-process contracts between the agent platform and execution runtime, `ProtocolError(reason: str)` is the canonical error type. The `reason` field is a machine-readable string code (e.g. `"store_unavailable"`, `"schema_invalid"`, `"signature_invalid"`, `"bad_request"`). Call sites catch `(ValueError, TypeError, RecursionError)` and re-raise as `ProtocolError("bad_request")` with `from None` to suppress chaining noise. This is the closest thing the repo has to a sentinel-error enum.

### 3. HTTP boundary conversion
At FastAPI route handlers, domain exceptions are either:
- Caught and translated into `HTTPException(status_code=..., detail=...)` (e.g. `platform-gateway` routes return 502/503 for downstream service failures), or
- Allowed to bubble up uncaught, which FastAPI converts to a 500 JSON response.

There is no central `@app.exception_handler` mapping across products. The only custom exception handler in the repo is in `samples/acme-admin/app/src/acme_admin/main.py`, which handles `AdminAuthRequired` locally.

### 4. Structured logging as the primary observability channel
Every product exposes `core/observability.configure_logging()` and `log_event(logger, event, **fields)`. The logging layer is intentionally simple: one `INFO`-level JSON line per event. Errors are primarily observed through this structured log stream rather than through a dedicated error-reporting framework.

### 5. No panic/recover
Python's `try/except` is used pervasively around I/O, database calls, and external service invocations. There is no `try/finally` cleanup pattern enforced globally, and no `sys.excepthook` override. Failures are logged and propagated upward.

### 6. Shared schemas, not shared exceptions
Cross-product contracts live in `shared/shared-contracts/schemas/*.schema.json` (JSON Schema Draft 2020-12). Validation uses `jsonschema.Draft202012Validator` with a `referencing.Registry`; schema mismatches become `ProtocolError("schema_invalid")`. There is no shared Python exception package analogous to the schema directory.

## Conventions and Constraints

- Domain-layer errors are expressed as custom exception subclasses of `Exception` or `ValueError`, defined next to the module that raises them. This is an observed convention, not enforced by linting.
- Wire-format / envelope validation failures raise `ProtocolError` with a lowercase snake_case reason string; the caller catches generic `ValueError`/`TypeError`/`RecursionError` and normalizes them to `ProtocolError("bad_request")` with `from None`. This pattern appears consistently in both `agent_platform` and `execution_runtime` copies of `execution_protocol.py`.
- Provider configuration errors use the single `ProviderConfigurationError(ValueError)` defined in `agent_service/providers/base.py`; all concrete providers (dashscope, deepseek, luban, openai, registry) raise it rather than defining their own.
- API routes raise `fastapi.HTTPException` directly with explicit `status_code` and human-readable `detail`; there is no shared HTTP error response model.
- Logging is configured per product via `core/observability.configure_logging()`, which reads `LOG_LEVEL` from the environment and sets the root logger to at least INFO. This is documented in the docstring as required because Uvicorn defaults to WARNING.
- No repository-wide rule forces a particular exception hierarchy or mandates catching specific exceptions; enforcement is limited to the explicit `except (ValueError, TypeError, RecursionError)` blocks that normalize protocol errors.