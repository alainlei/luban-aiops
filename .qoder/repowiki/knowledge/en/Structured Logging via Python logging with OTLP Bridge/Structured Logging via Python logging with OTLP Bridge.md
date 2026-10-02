---
kind: logging_system
name: Structured Logging via Python logging with OTLP Bridge
category: logging_system
scope:
    - '**'
source_files:
    - shared/shared-contracts/observability-conventions.md
    - products/agent-platform/src/agent_service/core/observability.py
    - products/agent-platform/src/agent_service/core/telemetry.py
    - products/audit-service/src/audit_service/core/observability.py
    - products/platform-gateway/src/platform_gateway/core/observability.py
    - products/execution-runtime/src/execution_runtime/core/observability.py
    - products/identity-broker/src/identity_service/core/observability.py
    - products/incident-service/src/incident_service/core/observability.py
    - products/skills-hub/src/skills_hub/core/observability.py
---

## What system/approach is used

Luban services use the **Python standard library `logging`** module — no third-party logger framework (no loguru, structlog, or similar). Business and request events are emitted as single-line JSON records through a thin per-service `core/observability.py` helper that wraps `logger.info(json.dumps(...))`. An optional OpenTelemetry bridge (`opentelemetry.exporter.otlp.proto.http._log_exporter`) mirrors every structured record to the OTLP log pipeline when `OTEL_ENABLED=true`, but stdout JSON remains the source of truth for audit tooling.

The observability surface is split into two decoupled channels per `shared/shared-contracts/observability-conventions.md`:
- `/metrics` (Prometheus pull, always on)
- OpenTelemetry push (opt-in, gated by `OTEL_ENABLED`, fails open)

## Key files and packages

- `shared/shared-contracts/observability-conventions.md` — cross-service contract defining structured logging levels, OTLP bridge semantics, correlation headers, and cardinality rules.
- Per-service `core/observability.py` (agent-platform, audit-service, execution-runtime, identity-broker, incident-service, platform-gateway, skills-hub, tool-gateway) — identical `configure_logging()` + `log_event(logger, event, **fields)` helpers.
- `products/*/src/<service>/core/telemetry.py` — OTel initialization; attaches an OTLP `LoggingHandler` to the root logger when enabled.
- Each service's `app.py` calls `configure_logging()` at startup and uses `log_event(...)` for business events.

## Architecture and conventions

1. **Per-service duplication of the logging helper.** Every product ships its own `core/observability.py` with the same two functions: `configure_logging()` reads `LOG_LEVEL` (default `INFO`), calls `logging.basicConfig(level=..., force=True)`, and `log_event()` serializes `{"event": ..., **fields}` via `json.dumps(..., default=str, sort_keys=True)` at INFO level.
2. **Audit trail lives at INFO.** Uvicorn starts with root logger at WARNING; `configure_logging()` explicitly raises it to INFO so structured audit events (http_request, tool_invoked, policy decisions) are not silently dropped.
3. **Structured fields via `extra=` or `log_event` kwargs.** Call sites pass domain fields as keyword arguments; `log_event` flattens them into the JSON payload under the top-level key `event` plus the supplied field names. Some call sites also use `logger.info(..., extra={...})` directly for additional context.
4. **OTLP log bridge.** `core/telemetry.py::setup_telemetry()` installs an OTLP `LoggingHandler` on the root logger when `OTEL_ENABLED=true`. The `opentelemetry.*` loggers are detached from the root logger (`propagate = False`) to prevent recursion. Trace/span association is automatic — records emitted inside an active span carry `trace_id`/`span_id`, joining logs to traces on the W3C id that backs `x-request-id`.
5. **Request correlation.** `x-request-id` is the log- and portal-facing correlation key; when tracing is active it equals the active span's W3C `trace_id`, otherwise falls back to `req-<uuid4>`. It is forwarded on every outbound service-to-service call.
6. **Fail-open.** All OTel setup paths wrap initialization in try/except and log errors rather than raising; missing/misconfigured OTLP backend never breaks a request.
7. **Cardinality discipline.** `observability-conventions.md` forbids high-cardinality labels on metrics and, by extension, discourages unbounded values in structured logs (raw URLs, user ids, session ids, request ids).

## Conventions and constraints

- **Convention:** Structured audit events are emitted via `log_event(logger, "<event_name>", **fields)` at INFO level, producing one JSON line per record. Observed across agent-platform, audit-service, execution-runtime, identity-broker, incident-service, platform-gateway, skills-hub, and tool-gateway.
- **Convention:** Each service defines its own `core/observability.py` exposing `configure_logging()` and `log_event`; there is no shared SDK package yet (the doc says "so that signal ... is stable enough for a future shared SDK").
- **Rule (enforced by code):** Root logger level defaults to INFO and is overridable via the `LOG_LEVEL` environment variable; tests in each service assert this behavior (e.g. `test_observability.py` patches `LOG_LEVEL` to `WARNING`).
- **Rule (enforced by code):** OTLP log export is strictly opt-in via `OTEL_ENABLED`; when disabled, `setup_telemetry()` returns without initializing any provider, and `MetricsMirror` is a no-op.
- **Rule (documented in observability-conventions.md):** JSON stdout stays the source of truth; OTLP mirror must never replace container logs, and audit tooling must keep reading stdout.
- **Rule (documented in observability-conventions.md):** `x-request-id` is the log- and portal-facing correlation key; no service may silently drop an inbound correlation id.
- **Rule (documented in observability-conventions.md):** OTLP credentials come from `OTEL_EXPORTER_OTLP_HEADERS` (Basic auth for OpenObserve) provisioned via runtime secrets, never committed or placed in ConfigMaps.