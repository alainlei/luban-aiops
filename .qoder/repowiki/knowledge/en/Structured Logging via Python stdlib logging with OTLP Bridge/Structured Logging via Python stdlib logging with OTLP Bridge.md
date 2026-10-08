---
kind: logging_system
name: Structured Logging via Python stdlib logging with OTLP Bridge
category: logging_system
scope:
    - '**'
source_files:
    - shared/shared-contracts/observability-conventions.md
    - products/agent-platform/src/agent_service/core/observability.py
    - products/agent-platform/src/agent_service/core/telemetry.py
    - products/agent-platform/src/agent_service/app.py
    - products/audit-service/src/audit_service/core/observability.py
    - products/audit-service/src/audit_service/app.py
    - products/execution-runtime/src/execution_runtime/app.py
    - products/identity-broker/src/identity_service/app.py
    - products/incident-service/src/incident_service/app.py
    - products/platform-gateway/src/platform_gateway/app.py
    - products/skills-hub/src/skills_hub/app.py
    - products/tool-gateway/src/tool_gateway/app.py
---

## What is used

The platform uses **Python's built-in `logging` module** (no third-party logger framework such as structlog or loguru). Structured, single-line JSON audit records are emitted through a thin per-service wrapper `core/observability.log_event`, and an opt-in OpenTelemetry bridge mirrors those records over OTLP HTTP/protobuf to the organization's OpenObserve backend.

## Key files

- `shared/shared-contracts/observability-conventions.md` — repository-wide observability contract that defines the logging conventions for every service.
- Per-product `src/<product>/core/observability.py` — identical `configure_logging()` / `log_event()` pair duplicated across all eight services.
- Per-product `src/<product>/app.py` — calls `configure_logging()` at startup and installs the HTTP request middleware that emits `http_request` events.
- `products/agent-platform/src/agent_service/core/telemetry.py` — implements the OTel push pipeline (`setup_telemetry`, `MetricsMirror`) and attaches the OTLP `LoggingHandler` to the root logger when `OTEL_ENABLED=true`.

## Architecture and conventions

### Initialization

Every FastAPI service follows the same startup pattern:

1. `create_app()` calls `configure_logging()` before any route handler runs.
2. `configure_logging()` reads `LOG_LEVEL` from the environment (default `INFO`), resolves it via `getattr(logging, level_name, logging.INFO)`, and calls `logging.basicConfig(level=level, force=True)` to override uvicorn's default WARNING level so INFO-level structured records are not silently dropped.
3. An HTTP middleware wraps each request, resolves `x-request-id` (generated if absent, bridged to the active W3C `trace_id` when tracing is enabled), and emits a single `http_request` event via `log_event`.

### Structured record format

`log_event(logger, event, **fields)` builds `{"event": event, ...fields}`, serializes it with `json.dumps(..., default=str, sort_keys=True)`, and logs it at INFO level. The resulting stdout line is a single JSON object; consumers parse it rather than relying on positional fields. Business events include `service`, `request_id`, `method`, `path`, `status_code`, `duration_ms`, etc., depending on the call site.

### Log levels

- INFO = business/request/audit events (http_request, tool_invoked, policy decisions).
- WARNING and above = library/framework noise.
- The default root level is INFO; operators can raise it via `LOG_LEVEL` (e.g. `WARNING`).

### OTLP log bridge

When `OTEL_ENABLED=true`, `setup_telemetry` in `core/telemetry.py` attaches an OpenTelemetry `LoggingHandler` to the root logger. This causes every INFO+ record emitted by `logger.info(json.dumps(...))` to be exported as an OTLP log record alongside the JSON stdout stream. The bridge:

- Is gated by the same `OTEL_ENABLED` switch as traces and metrics.
- Automatically associates records with the active span's `trace_id`/`span_id`.
- Detaches `opentelemetry`'s own loggers from the root logger to prevent recursion.
- Fails open: setup exceptions are logged and swallowed; exporter failures do not break requests.

### Request correlation

- `x-request-id` is the log- and portal-facing correlation key.
- `traceparent` (W3C Trace Context) is the machine-facing propagation header managed by OTel instrumentation.
- When tracing is active, `x-request-id` is set to the active span's W3C `trace_id`; otherwise it falls back to `req-<uuid4>`.
- No service may silently drop an inbound correlation id.

### Replication across products

All eight services follow the same shape: `src/<product>/core/observability.py` contains the identical `configure_logging` + `log_event` implementation, and `src/<product>/app.py` imports and invokes them. The convention is documented centrally in `shared/shared-contracts/observability-conventions.md` rather than enforced by a shared SDK package.

## Conventions and constraints

- **Convention (descriptive):** Every service defines its own `core/observability.py` with `configure_logging()` and `log_event()`, and calls both from its `app.create_app()` entry point. This pattern is observed in agent-platform, audit-service, execution-runtime, identity-broker, incident-service, platform-gateway, skills-hub, and tool-gateway.
- **Convention (descriptive):** Structured events are emitted via `log_event(LOGGER, "<event_name>", **fields)` at INFO level, producing a single-line JSON object with an `event` field plus arbitrary key/value pairs.
- **Convention (descriptive):** A FastAPI HTTP middleware emits an `http_request` event carrying `service`, `request_id`, `method`, `path`, `status_code`, and `duration_ms`.
- **Rule (documented in `shared/shared-contracts/observability-conventions.md`):** All business and request events are emitted as single-line JSON via `log_event(...)` at INFO level, and every service calls `configure_logging()` at app startup to raise the root logger from uvicorn's WARNING default to INFO. The level is overridable via `LOG_LEVEL`; the default must stay INFO so audit records are never silently discarded.
- **Rule (documented in `observability-conventions.md`):** `OTEL_ENABLED` is the master gate for OTel push (traces + metrics + log mirror); when false, no OTel providers or instrumentation are initialized and `/metrics` is unaffected. Missing/invalid credentials produce 401s at export time; OTel batch processors drop telemetry on export failure and service setup additionally guards initialization and logs rather than raising.
- **Rule (documented in `observability-conventions.md`):** JSON stdout stays the source of truth; the OTLP mirror exists only so the backend can correlate logs with traces. Audit tooling must keep reading stdout.
- **Rule (documented in `observability-conventions.md`):** No service may silently drop an inbound correlation id (`x-request-id`).
- **Constraint (enforced by code):** `configure_logging()` uses `logging.basicConfig(level=..., force=True)`, which overrides any prior configuration — including uvicorn's default WARNING level — ensuring INFO records reach the root logger unless explicitly raised via `LOG_LEVEL`.