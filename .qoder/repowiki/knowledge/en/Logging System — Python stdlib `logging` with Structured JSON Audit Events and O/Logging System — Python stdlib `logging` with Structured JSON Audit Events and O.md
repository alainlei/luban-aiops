---
kind: logging_system
name: Logging System — Python stdlib `logging` with Structured JSON Audit Events and OTLP Log Bridge
category: logging_system
scope:
    - '**'
source_files:
    - shared/shared-contracts/observability-conventions.md
    - products/agent-platform/src/agent_service/core/observability.py
    - products/agent-platform/src/agent_service/core/telemetry.py
    - products/audit-service/src/audit_service/core/observability.py
    - products/audit-service/src/audit_service/core/telemetry.py
    - products/execution-runtime/src/execution_runtime/core/observability.py
    - products/execution-runtime/src/execution_runtime/core/telemetry.py
    - products/identity-broker/src/identity_service/core/observability.py
    - products/identity-broker/src/identity_service/core/telemetry.py
    - products/incident-service/src/incident_service/core/observability.py
    - products/incident-service/src/incident_service/core/telemetry.py
---

## What system/approach is used

The platform uses **Python's standard-library `logging` module** as its sole logging framework. There is no third-party logger (no structlog, loguru, or logbook). Business and request events are emitted as **single-line JSON strings** via a shared `log_event(logger, event, **fields)` helper that serializes `{"event": ..., ...fields}` with `json.dumps(..., default=str, sort_keys=True)`. This JSON stdout stream is the **audit trail source of truth**; an optional OpenTelemetry `LoggingHandler` bridges the same records to the OTLP push pipeline for correlation with traces.

Structured fields are plain keyword arguments passed through `**fields`; they are not attached via `extra=` on every call but are merged into the JSON payload by `log_event`. Trace/span context (`trace_id`, `span_id`) is joined automatically by the OTel bridge when a span is active.

## Key files and packages

- `shared/shared-contracts/observability-conventions.md` — authoritative cross-service convention document defining the two-surface model, structured logging levels, OTLP log bridge semantics, and request-correlation rules.
- Per-service `core/observability.py` — defines `configure_logging()` and `log_event()`; one copy per product service.
- Per-service `core/telemetry.py` — opt-in OTel push pipeline; attaches the OTLP `LoggingHandler` to the root logger when `OTEL_ENABLED=true`.
- Per-service `app.py` / `main.py` entrypoints — call `configure_logging()` at startup and emit audit events via `log_event`.

Observed per-service copies:
- `products/agent-platform/src/agent_service/core/observability.py`
- `products/audit-service/src/audit_service/core/observability.py`
- `products/execution-runtime/src/execution_runtime/core/observability.py`
- `products/identity-broker/src/identity_service/core/observability.py`
- `products/incident-service/src/incident_service/core/observability.py`
- `products/platform-gateway/src/platform_gateway/core/observability.py`
- `products/skills-hub/src/skills_hub/core/observability.py`
- `products/tool-gateway/src/tool_gateway/core/observability.py`

## Architecture and conventions

### Two-surface observability model

All services expose two deliberately decoupled surfaces (per `observability-conventions.md`):

1. **`/metrics` (pull, always-on)** — Prometheus endpoint implemented directly with `prometheus_client`.
2. **OpenTelemetry push (opt-in)** — traces, metrics, and mirrored logs pushed via OTLP HTTP/protobuf to `OTEL_EXPORTER_OTLP_ENDPOINT`; gated by `OTEL_ENABLED` (default `false`); fails open.

Disabling OTel push leaves `/metrics` fully functional; the two never depend on each other.

### Root logger configuration

Each service calls `configure_logging()` at application startup. It reads `LOG_LEVEL` from the environment (defaulting to `INFO`), converts it via `getattr(logging, level_name, logging.INFO)`, and applies it with `logging.basicConfig(level=level, force=True)`. The comment explains this raises the root logger above Uvicorn's WARNING default so INFO-level structured audit events survive.

### Structured event emission

Business and request events go through `log_event(logger, event, **fields)`, which builds a dict `{"event": event, **fields}`, serializes it to JSON with sorted keys, and emits it at INFO level. Call sites throughout services use this helper rather than calling `logger.info(json.dumps(...))` directly.

### OTLP log bridge

When `OTEL_ENABLED=true`, `setup_telemetry()` in each service's `core/telemetry.py` installs an OTel `LoggingHandler` on the root logger. Semantics documented in both the code and `observability-conventions.md`:

- JSON stdout remains the source of truth; the OTLP mirror exists only for backend correlation with traces.
- Trace/span association is automatic: records emitted inside an active span carry W3C `trace_id`/`span_id`.
- Recursion guard: `logging.getLogger("opentelemetry").propagate = False` prevents exporter failures from looping back through the bridge.
- The bridge is gated by the same `OTEL_ENABLED` switch and fails open.

### Request correlation

- `x-request-id` is the log- and portal-facing correlation key; generated if absent and forwarded on outbound calls.
- `traceparent` (W3C Trace Context) is the machine-facing propagation header managed by OTel instrumentation.
- Bridging rule: when tracing is active, `x-request-id` is set to the active span's W3C `trace_id` (32 hex chars); otherwise it falls back to `req-<uuid4>`.

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `LOG_LEVEL` | Root logger level for structured audit events | `INFO` |
| `OTEL_ENABLED` | Master gate for OTel push (traces + metrics + log mirror) | `false` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP HTTP base URL (exporters append `/v1/{traces,metrics,logs}`) | required when enabled |
| `OTEL_EXPORTER_OTLP_HEADERS` | Ingest auth headers (e.g. Basic auth for OpenObserve) | provisioned via runtime secrets |
| `OTEL_SERVICE_NAME` | Resource service name | metadata-derived |

## Conventions and constraints

- **Convention:** All business and request events are emitted as single-line JSON via `log_event(...)` at INFO level. Observed across all eight Python services under `products/*/src/*/core/observability.py`.
- **Rule (convention doc):** "Every service calls `configure_logging()` at app startup to raise the root logger from uvicorn's WARNING default to INFO. The level is overridable per-deployment via `LOG_LEVEL`; the default must stay INFO so audit records are never silently discarded." — stated in `shared/shared-contracts/observability-conventions.md`.
- **Rule (convention doc):** "No service may silently drop an inbound correlation id." — stated in `observability-conventions.md`.
- **Rule (convention doc):** OTel push is controlled exclusively by `OTEL_ENABLED`; there are no per-signal toggles. Fail-open guarantee: setup/export errors are logged, never raised into the request path.
- **Constraint (code enforcement):** `configure_logging()` uses `logging.basicConfig(..., force=True)`, overriding any prior handler configuration so the configured level takes effect regardless of earlier initialization.
- **Constraint (code enforcement):** The OTel log bridge is guarded by a module-level `_log_bridge_attached` flag and detaches `opentelemetry` loggers from the root logger (`propagate = False`) to prevent recursion.
- **Constraint (code enforcement):** `MetricsMirror` is lazy — instruments are built on first record, never at import time, because `setup_metrics` runs before `setup_telemetry` sets the global `MeterProvider`.
- **Convention:** Each service ships its own copy of `core/observability.py` and `core/telemetry.py` rather than sharing a package; the copies are kept byte-identical across services (enforced by `TelemetryParityTest`).