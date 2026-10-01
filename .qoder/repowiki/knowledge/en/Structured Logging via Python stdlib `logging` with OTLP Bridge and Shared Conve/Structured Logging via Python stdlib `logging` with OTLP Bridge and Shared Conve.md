---
kind: logging_system
name: Structured Logging via Python stdlib `logging` with OTLP Bridge and Shared Conventions
category: logging_system
scope:
    - '**'
source_files:
    - shared/shared-contracts/observability-conventions.md
    - products/agent-platform/src/agent_service/core/observability.py
    - products/agent-platform/src/agent_service/core/telemetry.py
    - products/audit-service/src/audit_service/core/observability.py
    - products/execution-runtime/src/execution_runtime/core/observability.py
    - products/identity-broker/src/identity_service/core/observability.py
    - products/incident-service/src/incident_service/core/observability.py
    - products/platform-gateway/src/platform_gateway/core/observability.py
    - products/skills-hub/src/skills_hub/core/observability.py
    - products/tool-gateway/src/tool_gateway/core/observability.py
---

## What system/approach is used

The platform uses **Python's built-in `logging` module** for all application log output — no third-party logger framework (no structlog, loguru, or custom formatter). Every product service defines its own thin `core/observability.py` that exposes two functions:

- `configure_logging()` — raises the root logger from uvicorn's default WARNING to INFO so structured audit records survive.
- `log_event(logger, event, **fields)` — serializes a dict `{"event": ..., ...fields}` to JSON via `json.dumps(..., default=str, sort_keys=True)` and emits it at INFO level.

All business and request events (http_request, tool_invoked, policy decisions) are emitted through this helper at INFO level. The format is one-line JSON on stdout; there is no per-field structured schema beyond the `event` key plus arbitrary keyword fields.

For distributed tracing and metrics the platform layers **OpenTelemetry** on top of the stdlib logger. When `OTEL_ENABLED=true`, `core/telemetry.py` attaches an OTel `LoggingHandler` to the root logger so every INFO record is also exported over OTLP HTTP/protobuf to the configured backend (OpenObserve). Trace/span association is automatic: records emitted inside an active span carry `trace_id`/`span_id`. The bridge detaches `opentelemetry`'s own loggers from the root logger to prevent recursion when exporters fail.

## Key files and packages

- `shared/shared-contracts/observability-conventions.md` — the authoritative cross-product contract describing the two observability surfaces (`/metrics` pull + OTLP push), naming rules, cardinality constraints, environment variables, and structured logging levels.
- Per-product `src/<service>/core/observability.py` — local copy of `configure_logging` / `log_event` (agent-platform, audit-service, execution-runtime, identity-broker, incident-service, platform-gateway, skills-hub, tool-gateway).
- Per-product `src/<service>/app.py` — calls `configure_logging()` at startup and uses `log_event(LOGGER, "http_request", ...)` in middleware.
- Per-product `src/<service>/core/telemetry.py` — OTel setup, `MetricsMirror`, `current_trace_id()`, and the OTLP log bridge.

## Architecture and conventions

1. **Per-product duplication by design.** Each service ships its own `core/observability.py` rather than sharing a package. This keeps the dependency graph flat and avoids cross-product imports between services.
2. **Two decoupled surfaces:**
   - `/metrics` (Prometheus, always-on, `prometheus_client`).
   - OpenTelemetry push (opt-in via `OTEL_ENABLED`; off by default, zero overhead when disabled).
3. **Fail-open OTel pipeline:** All OTel initialization is wrapped in try/except; exporter failures are logged and swallowed, never raised into the request path. Missing/invalid credentials produce 401s at export time; batch processors drop failed telemetry.
4. **Request correlation:** `x-request-id` is the portal-facing correlation key; `traceparent` (W3C) is the machine-facing propagation header. When tracing is active, `x-request-id` is set to the active span's W3C `trace_id`; otherwise it falls back to `req-<uuid4>`.
5. **Domain-metric mirror (SPEC-065 R-2):** `MetricsMirror` re-emits each service's prometheus families as OTel instruments (same name, same bounded label set) so domain metrics reach dashboards over OTLP. It is lazy, generic, and no-op when disabled.
6. **Cardinality rules:** Labels must be bounded enums — raw URLs, user ids, session ids, request ids are forbidden as labels.
7. **Environment-driven configuration:**
   - `LOG_LEVEL` — overrides the root logger level (default INFO).
   - `OTEL_ENABLED` — master gate for traces + metrics + logs mirror.
   - `OTEL_EXPORTER_OTLP_ENDPOINT` — OTLP HTTP base URL.
   - `OTEL_EXPORTER_OTLP_HEADERS` — Basic auth for OpenObserve ingest.
   - `OTEL_SERVICE_NAME` — resource service name.

## Conventions and constraints

- **Convention (descriptive):** Every service's `app.py` imports `configure_logging` and `log_event` from its own `core.observability`, calls `configure_logging()` during app startup, and emits structured events via `log_event(LOGGER, "<event_name>", **fields)`.
- **Convention (descriptive):** Business/request events are single-line JSON strings emitted at INFO level; the `event` field names the semantic event (e.g. `http_request`, `tool_invoked`, `policy_decision`).
- **Convention (descriptive):** Structured fields are passed as keyword arguments to `log_event` and become top-level keys in the JSON payload.
- **Rule (enforced by convention doc):** `OTEL_ENABLED` is the single switch gating the full signal (traces + metrics + log mirror); there are no per-signal toggles. Source: `shared/shared-contracts/observability-conventions.md` line 55.
- **Rule (enforced by convention doc):** The default log level must stay INFO so audit records are never silently discarded; uvicorn's WARNING default is explicitly overridden. Source: `shared/shared-contracts/observability-conventions.md` line 64 and `core/observability.py` lines 9–19.
- **Rule (enforced by convention doc):** No service may silently drop an inbound correlation id (`x-request-id` / `traceparent`). Source: `shared/shared-contracts/observability-conventions.md` line 80.
- **Rule (enforced by convention doc):** Never use an unbounded value as a metric label (raw URL, user id, session id, request id); high-cardinality labels are rejected at review. Source: `shared/shared-contracts/observability-conventions.md` lines 42–49.
- **Rule (enforced by convention doc):** JSON stdout remains the source of truth for the audit trail; the OTLP log bridge is additive and never replaces container logs. Source: `shared/shared-contracts/observability-conventions.md` line 70.