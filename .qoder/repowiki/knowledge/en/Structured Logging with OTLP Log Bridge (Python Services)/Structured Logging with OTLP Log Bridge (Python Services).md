---
kind: logging_system
name: Structured Logging with OTLP Log Bridge (Python Services)
category: logging_system
scope:
    - '**'
source_files:
    - shared/shared-contracts/observability-conventions.md
    - products/agent-platform/src/agent_service/core/observability.py
    - products/agent-platform/src/agent_service/core/telemetry.py
    - products/audit-service/src/audit_service/core/observability.py
    - products/audit-service/src/audit_service/core/telemetry.py
    - products/execution-runtime/src/execution_runtime/core/telemetry.py
    - products/identity-broker/src/identity_service/core/telemetry.py
    - products/incident-service/src/incident_service/core/telemetry.py
    - products/platform-gateway/src/platform_gateway/core/telemetry.py
---

## What System Is Used

The platform uses Python's stdlib `logging` module as the primary logging framework. Structured audit events are emitted as single-line JSON via a thin `log_event()` helper, and when OpenTelemetry is enabled (`OTEL_ENABLED=true`), an OTLP log bridge (`opentelemetry.instrumentation.logging.handler.LoggingHandler`) mirrors every INFO-level record to the backend over HTTP/protobuf.

There is no third-party structured-logging library (no structlog, loguru, or Sentry SDK). The only external observability integration is OpenTelemetry for traces, metrics, and mirrored logs; Prometheus `/metrics` is separate and always-on.

## Key Files and Packages

- `shared/shared-contracts/observability-conventions.md` — authoritative cross-service convention document describing the two surfaces (`/metrics` pull + OTel push opt-in), level strategy, OTLP bridge semantics, and request-correlation rules.
- `products/*/src/<service>/core/observability.py` — per-service `configure_logging()` / `log_event()` helpers that raise the root logger from uvicorn's WARNING default to INFO (overridable via `LOG_LEVEL`) and emit `{"event": ..., **fields}` JSON.
- `products/*/src/<service>/core/telemetry.py` — opt-in OTel pipeline: `setup_telemetry(app, service_name)`, `is_enabled()`, `current_trace_id()`, and the shared `MetricsMirror` class. Each product ships an identical copy of this file (parity enforced by tests).
- Per-service `app.py` entrypoints call `configure_logging()` at startup and use `log_event(...)` for business/request events.

## Architecture and Conventions

**Two decoupled surfaces.** Every service exposes:
1. `/metrics` (Prometheus, always on, `prometheus_client`).
2. OpenTelemetry push (opt-in via `OTEL_ENABLED`; off by default, fails open).

These never depend on each other — disabling OTel leaves `/metrics` fully functional.

**Structured log format.** Business and request events go through `log_event(logger, event, **fields)`, which produces one line of JSON: `{"event": <name>, ...fields}`, sorted keys, values coerced via `default=str`. This is the audit trail (http_request, tool_invoked, policy decisions). All such records are emitted at INFO level.

**Level strategy.** `configure_logging()` reads `LOG_LEVEL` (default `INFO`) and calls `logging.basicConfig(level=..., force=True)` so uvicorn's WARNING default does not silently discard audit records. The default must stay INFO so audit records are never discarded.

**OTLP log bridge.** When `OTEL_ENABLED=true`, `_attach_log_bridge()` installs an OTel `LoggingHandler` on the root logger with `level=logging.INFO`. Semantics documented in the conventions doc:
- JSON stdout remains the source of truth; OTLP is a mirror for correlation.
- Trace/span association is automatic — records inside an active span carry `trace_id`/`span_id`, joining logs to traces on the same W3C id that backs `x-request-id`.
- Recursion guard: `logging.getLogger("opentelemetry").propagate = False` detaches OTel's own loggers from the root logger so exporter failures cannot loop back.
- The bridge is gated by the same `OTEL_ENABLED` switch and fails open.

**Request correlation.** `x-request-id` is the log- and portal-facing correlation key. When tracing is active it is set to the active span's W3C `trace_id` (32 hex chars); otherwise it falls back to `req-<uuid4>`. No service may silently drop an inbound correlation id.

**Environment variables.**
- `OTEL_ENABLED` — master gate (accepts `1`, `true`, `yes`, `on`); default false.
- `OTEL_EXPORTER_OTLP_ENDPOINT` — OTLP HTTP base URL (exporters append `/v1/{traces,metrics,logs}`).
- `OTEL_EXPORTER_OTLP_HEADERS` — Basic-auth headers for OpenObserve ingest.
- `OTEL_SERVICE_NAME` — resource service name, defaults to metadata.
- `LOG_LEVEL` — overrides the root logger level (default INFO).

**Fail-open guarantee.** Missing/misconfigured OTel backend never breaks a request. Exporter errors are logged and swallowed; setup exceptions are caught and logged rather than raised into the request path.

**Domain-metric mirror (SPEC-065 R-2).** `MetricsMirror` re-emits each service's prometheus domain families as OTel instruments (same exposed name, same bounded label set) so they reach dashboards over the OTLP push path. It is lazy, no-op when disabled, fail-open, and byte-identical across all eight services.

## Conventions and Constraints

- **Convention:** Every service initializes logging via its local `core/observability.configure_logging()` at app startup and emits business events via `log_event(logger, ...)`, not raw `LOGGER.info(...)`.
- **Convention:** Logger instances are created per module as `LOGGER = logging.getLogger(__name__)`.
- **Convention:** Audit/log events are single-line JSON with a top-level `event` field plus arbitrary extra fields.
- **Convention:** OTel push is controlled exclusively by `OTEL_ENABLED`; there are no per-signal toggles.
- **Rule (convention doc):** "All business and request events are emitted as single-line JSON via `log_event(...)` at INFO level." The default root level must stay INFO so audit records are never silently discarded.
- **Rule (convention doc):** "No service may silently drop an inbound correlation id."
- **Rule (convention doc):** Never use an unbounded value as a metric label (raw URL, user id, session id, request id are explicitly listed as forbidden).
- **Enforced pattern:** Each product ships an identical `core/telemetry.py` (with `MetricsMirror` parity guarded by tests), ensuring the OTel initialization and log-bridge behavior is uniform across services.