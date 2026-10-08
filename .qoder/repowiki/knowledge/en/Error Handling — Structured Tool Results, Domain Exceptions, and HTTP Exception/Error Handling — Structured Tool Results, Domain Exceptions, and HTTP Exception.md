---
kind: error_handling
name: Error Handling — Structured Tool Results, Domain Exceptions, and HTTP Exception Mapping
category: error_handling
scope:
    - '**'
source_files:
    - shared/shared-contracts/schemas/tool-result.schema.json
    - shared/shared-contracts/schemas/execution-receipt.schema.json
    - products/tool-gateway/src/tool_gateway/tools/base.py
    - products/tool-gateway/src/tool_gateway/tools/secrets_connector.py
    - products/platform-gateway/src/platform_gateway/services/policy_engine.py
    - products/agent-platform/src/agent_service/runtime_kernel.py
    - products/agent-platform/src/agent_service/api/v2/routes.py
    - products/agent-platform/src/agent_service/providers/base.py
    - products/agent-platform/src/agent_service/runtime_kernel.py
    - products/agent-platform/src/agent_service/services/execution_worker_client.py
    - products/agent-platform/src/agent_service/services/incident_client.py
    - products/agent-platform/src/agent_service/services/skills_client.py
    - products/agent-platform/src/agent_service/services/shift_summary.py
    - products/audit-service/src/audit_service/services/audit_store.py
    - products/identity-broker/src/identity_service/services/exchange_service.py
    - products/incident-service/src/incident_service/services/connectors.py
    - products/incident-service/src/incident_service/services/incident_store.py
    - products/incident-service/src/incident_service/services/triage.py
    - products/skills-hub/src/skills_hub/services/query_auth.py
    - products/skills-hub/src/skills_hub/services/skill_store.py
---

## System Overview

The Luban platform uses a layered error model that separates **tool execution errors** (structured `ToolResult` envelopes), **domain/service exceptions** (per-product Python exception classes), and **HTTP boundary errors** (`fastapi.HTTPException`). There is no centralized error-code registry; instead, machine-readable codes are embedded in tool results and propagated as string constants through the runtime kernel.

## Tool-Execution Error Envelope

The canonical contract for any tool invocation is defined by `shared/shared-contracts/schemas/tool-result.schema.json`. Every tool returns a `ToolResult` dataclass with:
- `status`: one of `"success"`, `"error"`, `"denied"`
- `data`: present on success
- `evidence`: required provenance object (`executed_at`, `duration_ms`, `risk_level`, `source_system`)
- `error`: optional `{code: str, message: str}` present on `error`/`denied`

In `products/tool-gateway/src/tool_gateway/tools/base.py`, two factory helpers enforce this shape:
- `make_error_result(tool_name, code, message, ...)` → `status="error"` with an `error` dict
- `make_denied_result(tool_name, reason, ...)` → `status="denied"` with `error.code = "POLICY_DENIED"`

Tools return these structured results rather than raising exceptions, so failures flow through the agent-stream pipeline without crashing the process. The agent-platform's runtime kernel then inspects `frame["error"]["code"]` to drive control-flow decisions — notably `FLOW_KILLING_ERROR_CODES` and special cases like `BROWSER_NAVIGATION_ERROR` and `EXECUTION_REJECTED` (see `runtime_kernel.py` lines ~1780–1912). A `TIMEOUT` code maps to receipt status `timeout`; other non-success statuses map to `failed`.

## Domain Exceptions per Product

Each product defines its own small set of domain exceptions, typically under `services/` or `core/`:

| Product | Exception(s) | Purpose |
|---|---|---|
| `agent-platform` | `ProviderConfigurationError(ValueError)`, `UnknownModelError(ValueError)`, `WorkerHandoffError`, `IncidentClientError`, `SkillsClientError`, `DigestInputError`, `UnknownSessionError` | Provider config validation, unknown model IDs, cross-service client failures, session/digest validation |
| `platform-gateway` | `PolicyLoadError(Exception)`, `TokenVerificationError(Exception)` | Policy bundle parse/load failures, token verification failures |
| `tool-gateway` | `PolicyLoadError(Exception)`, `TokenVerificationError(Exception)`, `PasswordPolicyError(Exception)` | Same policy/token concerns plus password-policy violations |
| `audit-service` | `StoreError`, `IngestAuthError` | Store I/O and ingestion auth failures |
| `identity-broker` | `ExchangeError` | Token exchange failures |
| `incident-service` | `SettingsError`, `ConnectorConfigError`, `StoreError`, `NormalizationError`, `QueryAuthError`, `TriageError` | Config, connector, store, normalization, query auth, triage failures |
| `skills-hub` | `SettingsError`, `QueryAuthError`, `StoreError` | Config, query auth, skill-store failures |

These exceptions bubble up to route handlers, which translate them into HTTP responses.

## HTTP Boundary Mapping

FastAPI routes raise `fastapi.HTTPException` directly. In `products/agent-platform/src/agent_service/api/v2/routes.py`, the pattern is consistent: catch a domain exception and re-raise as an `HTTPException` with an explicit status code and `detail` string, using `from None` to suppress the chained traceback for upstream callers:

```python
except SkillsDependencyNotConfigured as exc:
    raise HTTPException(status_code=503, detail=str(exc)) from None
except SkillsServiceUnavailable as exc:
    raise HTTPException(status_code=502, detail=str(exc)) from None
except SkillsClientRejected as exc:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
```

Upstream service errors are mapped to 502/503 based on capability state (configured vs unreachable), while 4xx client errors are passed through verbatim. This keeps the API surface stable regardless of downstream failure mode.

## Policy Denial as a First-Class Error Path

Policy enforcement produces a third outcome distinct from tool errors: `status="denied"` with `error.code = "POLICY_DENIED"`. The `platform-gateway` policy engine (`policy_engine.py`) evaluates rules against a YAML bundle and returns a `PolicyDecision` with decision `"deny"`, `"allow"`, or `"require_approval"`. When a rule requires approval, the decision carries an `ApprovalSpec` (tier, decider roles, self-approval flag). The tool-gateway enforces this at the invocation boundary before the tool runs, returning `make_denied_result(...)` with the policy reason.

## Flow-Killing and Execution Receipt Semantics

The runtime kernel treats certain tool-error codes as terminal for browser flows. `FLOW_KILLING_ERROR_CODES` (imported from `flow_approvals.py`) causes the kernel to clear `FlowContext` and `FlowApprovals` for the session, revoking auto-signing authority. Special-cased handling exists for `BROWSER_NAVIGATION_ERROR` when it occurs during a bind attempt. `EXECUTION_REJECTED` marks a signed execution request as rejected without producing a receipt; `TIMEOUT` sets receipt status to `timeout`; all other failures produce a `failed` receipt. Receipts are signed HMAC-SHA256 envelopes per `execution-receipt.schema.json`, ensuring tamper evidence even on failure paths.

## Conventions Observed

- Tools never raise exceptions for recoverable failures; they return `ToolResult` with `status="error"` via `make_error_result`.
- Configuration/validation failures raise typed `ValueError` subclasses (e.g. `ProviderConfigurationError`, `SettingsError`) so callers can distinguish config issues from runtime errors.
- Cross-service client failures use dedicated exception classes per product (`*ClientError`, `*ConnectorConfigError`) carrying either a status code + message or a plain string.
- Route handlers are the single translation point between domain exceptions and HTTP status codes; business logic stays free of HTTP concerns.
- Policy denials are not exceptions — they are structured results flowing through the same tool pipeline, enabling uniform audit/evidence capture.
- Error codes in tool results are string literals (e.g. `"INVALID_PARAMETERS"`, `"UPSTREAM_ERROR"`, `"EMAIL_NOT_CONFIGURED"`, `"POLICY_DENIED"`, `"EXECUTION_REJECTED"`, `"TIMEOUT"`) consumed centrally by the kernel and UI layers.
