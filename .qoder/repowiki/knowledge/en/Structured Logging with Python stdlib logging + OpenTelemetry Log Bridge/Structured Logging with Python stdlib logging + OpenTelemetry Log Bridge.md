---
kind: logging_system
name: Structured Logging with Python stdlib logging + OpenTelemetry Log Bridge
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
---

## What system/approach is used

The platform uses **Python's standard-library `logging` module** as the sole logging framework — no third-party logger (structlog, loguru, etc.). Structured events are emitted as single-line JSON via a thin `log_event()` helper that serializes `{event, ...fields}` with `json.dumps(..., sort_keys=True)`. An opt-in **OpenTelemetry push pipeline** (gated by `OTEL_ENABLED`) attaches an OTLP `LoggingHandler` to the root logger so every structured record is mirrored to the backend (OpenObserve) alongside stdout.

Two observability surfaces are deliberately decoupled per `shared/shared-contracts/observability-conventions.md`:
1. `/metrics` pull surface (prometheus_client, always on).
2. OTLP HTTP/protobuf push for traces, metrics, and logs (opt-in, fail-open).

## Key files and packages

- `products/*/src/<service>/core/observability.py` — per-service copy of `configure_logging()` and `log_event()`, raising the root logger from uvicorn's WARNING default to INFO and emitting JSON records.
- `products/agent-platform/src/agent_service/core/telemetry.py` — shared-style OTel setup: `setup_telemetry(app, service_name)`, `current_trace_id()`, `MetricsMirror`, and `_attach_log_bridge()` which installs the OTLP `LoggingHandler` and detaches `opentelemetry` loggers from the root logger to prevent recursion.
- `shared/shared-contracts/observability-conventions.md` — the authoritative spec for structured logging levels, OTLP bridge semantics, request correlation (`x-request-id` / `traceparent`), and cardinality rules.

Every product service (`agent-platform`, `audit-service`, `execution-runtime`, `identity-broker`, `incident-service`, `platform-gateway`, `skills-hub`, `tool-gateway`) ships its own `core/observability.py` implementing the same two functions, and calls `configure_logging()` at app startup in its `app.py`.

## Architecture and conventions

- **Logger instantiation**: modules create a module-level `LOGGER = logging.getLogger(__name__)` and call `LOGGER.info(...)`, `LOGGER.exception(...)`, or `LOGGER.debug(...)` directly; business events go through `log_event(LOGGER, "event_name", **fields)`.
- **Structured payload shape**: `{"event": <string>, ...arbitrary_fields}` serialized to one JSON line. Fields are passed as keyword arguments and merged into the dict before serialization.
- **Log level strategy**: all audit/business/request events use `INFO`. The root logger is raised from uvicorn's default `WARNING` to `INFO` at startup so these records are not silently dropped. Level can be overridden per deployment via `LOG_LEVEL` (e.g. `DEBUG`, `ERROR`).
- **OTLP log bridge**: when `OTEL_ENABLED=true`, `_attach_log_bridge()` installs an OTLP `LoggingHandler` on the root logger. Records emitted inside an active span automatically carry `trace_id`/`span_id`, joining logs to traces. The `opentelemetry` internal loggers have `propagate=False` to avoid recursive export loops.
- **Fail-open**: OTel initialization errors are caught and logged (`LOGGER.exception(...)`); they never propagate into the request path. When disabled, zero OTel providers are initialized.
- **Request correlation**: `x-request-id` is the portal-facing key; `traceparent` (W3C Trace Context) is machine-facing. When tracing is active, `x-request-id` is set to the active span's W3C `trace_id`; otherwise it falls back to `req-<uuid4>`.
- **Cardinality rule**: labels must be bounded enums — raw URLs, user ids, session ids, request ids are forbidden as label values.

## Conventions and constraints

- Every service calls `configure_logging()` at application startup in its `app.py` entrypoint (verified in `agent-platform/app.py`, `audit-service/app.py`, and identical patterns across other products). This raises the root logger to INFO so audit records survive.
- Business and request events are emitted as single-line JSON via `log_event(...)` at INFO level — this is documented as the audit trail contract in `observability-conventions.md` (line 64).
- `LOG_LEVEL` overrides the default INFO level; the default must stay INFO so audit records are never silently discarded (enforced by the docstring in `core/observability.py`).
- OTLP log bridge is gated by `OTEL_ENABLED` (default false) and fails open — setup errors are logged, never raised (documented in `telemetry.py` module docstring and enforced by try/except blocks around provider initialization).
- The `opentelemetry` logger namespace is detached from the root logger (`logging.getLogger("opentelemetry").propagate = False`) to prevent exporter failures from recursing back into the bridge (enforced in `_attach_log_bridge`).
- Structured log fields must respect cardinality rules: no unbounded values as labels (raw URL, user id, session id, request id) — codified in `observability-conventions.md` section "Cardinality Rules".