---
kind: logging_system
name: Structured Logging and OTLP Log Bridge Across Platform Services
category: logging_system
scope:
    - '**'
source_files:
    - shared/shared-contracts/observability-conventions.md
    - products/agent-platform/src/agent_service/core/observability.py
    - products/agent-platform/src/agent_service/core/telemetry.py
    - products/platform-gateway/src/platform_gateway/core/observability.py
    - products/tool-gateway/src/tool_gateway/core/observability.py
    - products/audit-service/src/audit_service/core/observability.py
    - products/identity-broker/src/identity_service/core/observability.py
    - products/incident-service/src/incident_service/core/observability.py
    - products/skills-hub/src/skills_hub/core/observability.py
    - products/execution-runtime/src/execution_runtime/core/observability.py
---

## What system/approach is used

The platform uses Python's stdlib `logging` module as the sole logging framework, with a uniform per-service `core/observability.py` that provides two helpers: `configure_logging()` (raises the root logger from uvicorn's default WARNING to INFO so audit records are never silently dropped) and `log_event(logger, event, **fields)` which emits a single-line JSON record via `json.dumps(payload, default=str, sort_keys=True)`. Business and request events form the audit trail and are always emitted at INFO level.

OpenTelemetry push is opt-in (`OTEL_ENABLED`) and implemented in each service's `core/telemetry.py` (currently present in `agent-platform`). When enabled, an OTel `LoggingHandler` is attached to the root logger so every structured log line is mirrored into the OTLP logs pipeline alongside traces and metrics. The bridge is guarded against recursion by detaching `opentelemetry` loggers from the root logger.

## Key files and packages

- Per-service logging configuration: `products/*/src/<service>/core/observability.py` — identical implementations across all nine services (agent-platform, audit-service, execution-runtime, identity-broker, incident-service, platform-gateway, skills-hub, tool-gateway).
- OpenTelemetry log bridge: `products/agent-platform/src/agent_service/core/telemetry.py` — initializes TracerProvider, MeterProvider, FastAPI/HTTPX instrumentation, and attaches the OTLP log bridge; also exposes `current_trace_id()` for correlation.
- Cross-cutting conventions: `shared/shared-contracts/observability-conventions.md` — documents the two-surface model (`/metrics` pull + OTLP push), environment variables, structured logging levels, OTLP log bridge semantics, and request-correlation rules.
- Usage sites: every service's `app.py` calls `configure_logging()` at startup; API route modules import `log_event` from their local `core.observability` and emit structured events (e.g. `http_request`, `tool_invoked`, policy decisions).

## Architecture and conventions

1. **Per-service isolation** — Each product ships its own `core/observability.py`; there is no shared library for logging. This keeps dependencies minimal and lets each service configure its own root logger without cross-process side effects.
2. **Structured audit trail** — All business/request events go through `log_event(...)`, producing a flat JSON object with a required `event` field plus arbitrary domain fields. Records are sorted keys and stringified defaults so they stay parseable even when non-serializable objects leak in.
3. **Log-level policy** — Root logger is raised to INFO at startup because uvicorn starts it at WARNING. The effective level is controlled by the `LOG_LEVEL` environment variable (default `INFO`); tests verify that overriding it works.
4. **OTLP mirror, not replacement** — When `OTEL_ENABLED=true`, the same stdout JSON records are also exported over OTLP HTTP/protobuf to `OTEL_EXPORTER_OTLP_ENDPOINT`. The convention explicitly states JSON stdout remains the source of truth; OTLP is only for correlation with traces/metrics.
5. **Request correlation** — `x-request-id` is the log- and portal-facing correlation key. When tracing is active, it is set to the active span's W3C `trace_id`; otherwise it falls back to `req-<uuid4>`. `traceparent` (W3C Trace Context) is propagated automatically by OTel instrumentation.
6. **Fail-open telemetry** — OTel setup errors are logged and swallowed; missing/invalid credentials produce export-time 401s that batch processors drop. No exception propagates into the request path.
7. **Metric naming / cardinality rules** — Metrics follow `<service>_<noun>_<unit>` snake_case with `_total` suffixes on counters, bounded enum labels only, and explicit prohibitions on high-cardinality labels (raw URL, user id, session id, request id). These rules live in the shared conventions doc and apply to all services.

## Conventions and constraints

- Every service must call `configure_logging()` during app startup so INFO audit records survive uvicorn's default WARNING threshold. (Enforced by per-service tests that patch `LOG_LEVEL`.)
- All business/request events must be emitted via `log_event(...)` at INFO level; ad-hoc `logger.info(json.dumps(...))` bypassing the helper is not observed in production code.
- OTLP push is gated exclusively by `OTEL_ENABLED`; there are no per-signal toggles. When disabled, zero OTel providers or instrumentation are initialized.
- Authentication for OTLP ingestion uses `OTEL_EXPORTER_OTLP_HEADERS` (Basic auth for OpenObserve) provisioned via runtime secrets — never committed to source.
- Structured log records must include an `event` field identifying the semantic action; additional fields are free-form but should remain low-cardinality.
- Correlation: inbound `x-request-id` must never be silently dropped; outbound calls forward it, and when tracing is active `x-request-id` equals the span's W3C `trace_id`.
- Metric labels must be bounded enums; raw identifiers (user/session/request ids) are prohibited as labels.