---
kind: logging_system
name: Structured JSON Logging with OpenTelemetry OTLP Push and Audit-Grade INFO Level
category: logging_system
scope:
    - '**'
source_files:
    - shared/shared-contracts/observability-conventions.md
    - products/agent-platform/src/agent_service/core/observability.py
    - products/agent-platform/src/agent_service/core/telemetry.py
    - products/agent-platform/src/agent_service/app.py
    - products/platform-gateway/src/platform_gateway/core/observability.py
    - products/platform-gateway/src/platform_gateway/core/telemetry.py
    - products/platform-gateway/src/platform_gateway/app.py
    - products/tool-gateway/src/tool_gateway/core/observability.py
    - products/tool-gateway/src/tool_gateway/core/telemetry.py
    - products/tool-gateway/src/tool_gateway/app.py
    - products/audit-service/src/audit_service/core/observability.py
    - products/audit-service/src/audit_service/core/telemetry.py
    - products/audit-service/src/audit_service/app.py
    - products/execution-runtime/src/execution_runtime/core/observability.py
    - products/execution-runtime/src/execution_runtime/core/telemetry.py
    - products/execution-runtime/src/execution_runtime/app.py
    - products/identity-broker/src/identity_service/core/observability.py
    - products/identity-broker/src/identity_service/core/telemetry.py
    - products/identity-broker/src/identity_service/app.py
    - products/incident-service/src/incident_service/core/observability.py
    - products/incident-service/src/incident_service/core/telemetry.py
    - products/incident-service/src/incident_service/app.py
---

## What system/approach is used

The platform uses Python's standard `logging` module as the sole logging framework, combined with an opt-in OpenTelemetry (OTel) push pipeline that mirrors structured logs to an OTLP HTTP/protobuf backend (OpenObserve). There is no third-party logger library (no structlog, loguru, or logzero). Every service ships its own thin `core/observability.py` and `core/telemetry.py` that mirror the same API surface defined in this card.

Two observability surfaces are deliberately decoupled (per `shared/shared-contracts/observability-conventions.md`, which backs SPEC-005):
1. **Prometheus `/metrics`** — always-on pull endpoint implemented directly with `prometheus_client` plus a RED middleware; never depends on OTel.
2. **OpenTelemetry push** — traces, metrics, and mirrored logs pushed via OTLP HTTP/protobuf, gated by `OTEL_ENABLED` (default false), failing open if the backend is unreachable.

## Key files and packages

- `shared/shared-contracts/observability-conventions.md` — authoritative cross-service contract for metric naming, cardinality rules, OTel switch semantics, structured log level policy, request correlation, and OTLP bridge behavior.
- Per-service `src/<service>/core/observability.py` — defines `configure_logging()` (raises root logger from uvicorn's WARNING default to INFO, overridable via `LOG_LEVEL`) and `log_event(logger, event, **fields)` which emits a single-line JSON record `{"event": ..., ...fields}` at INFO level.
- Per-service `src/<service>/core/telemetry.py` — defines `setup_telemetry(app, service_name)`, `is_enabled()`, and `current_trace_id()`. When enabled, initializes TracerProvider, MeterProvider, FastAPI + HTTPX instrumentation, and attaches an OTel `LoggingHandler` to the root logger so every structured record is also exported as an OTLP log record. The `opentelemetry` logger namespace is detached (`propagate = False`) to prevent recursion.
- Per-service `src/<service>/app.py` — calls `configure_logging()` before creating the FastAPI app, emits an `http_request` event via a middleware using `log_event`, then calls `setup_telemetry(app, SERVICE_NAME)`.

Observed across all nine products: `agent-platform`, `audit-service`, `execution-runtime`, `identity-broker`, `incident-service`, `platform-gateway`, `skills-hub`, `tool-gateway`, and `operator-portal` (the portal follows the same pattern through its shared SDK).

## Architecture and conventions

### Structured log format
Business and request events are emitted as single-line JSON via `log_event(...)`. The payload always contains an `event` field identifying the event type (e.g. `http_request`, `tool_invoked`, `policy_decision`, `secret_delivered`) plus domain-specific fields. Records are serialized with `json.dumps(..., default=str, sort_keys=True)` so output is deterministic and parseable without a schema.

### Log level strategy
- Root logger is raised to **INFO** at startup so audit-grade records are never silently discarded (uvicorn defaults to WARNING).
- The default level is INFO; it can be overridden per deployment via `LOG_LEVEL`.
- All business/request events use INFO. Debug-level logs may still be emitted via the module-level `LOGGER.debug(...)` but are not part of the audit trail.

### Request correlation and trace bridging
- `x-request-id` is the log- and portal-facing correlation key. It is generated if absent and forwarded on every outbound call.
- `traceparent` (W3C Trace Context) is the machine-facing propagation header, managed automatically by OTel instrumentation.
- When tracing is active, `x-request-id` is set to the active span's W3C `trace_id`; when inactive, it falls back to `req-<uuid4>`.
- No service may silently drop an inbound correlation id.

### OTLP log bridge
When `OTEL_ENABLED=true`, each service attaches an OTel `LoggingHandler` to the root logger. Semantics:
- JSON stdout remains the source of truth; OTLP is a mirror for backend correlation.
- Trace/span association is automatic — records emitted inside an active span carry `trace_id`/`span_id`, joining to the APM view via the same W3C id.
- Recursion guard: `opentelemetry` loggers are detached from the root logger.
- The bridge fails open; setup errors are logged and do not break requests.

### Metric naming and cardinality
- Format: `<service>_<noun>_<unit>` in snake_case; counters carry `_total`.
- Service prefix is the short name (`gateway`, `identity`, `agent`, etc.).
- Domain counters use bounded enum labels only (e.g. `decision ∈ {allow, deny}`).
- High-cardinality labels (raw URL, user id, session id, request id) are forbidden.

### Environment switches
- `OTEL_ENABLED` — master gate (accepts `1`, `true`, `yes`, `on`); default false.
- `OTEL_EXPORTER_OTLP_ENDPOINT` — OTLP HTTP base URL (org-scoped path appended by exporters).
- `OTEL_EXPORTER_OTLP_HEADERS` — Basic auth headers provisioned via runtime secrets.
- `OTEL_SERVICE_NAME` — resource service name, defaults to metadata.
- `LOG_LEVEL` — overrides the root logger level.

## Conventions and constraints

Enforced by the shared contract (`observability-conventions.md`) and reflected in every service's `app.py`:
1. Every service must call `configure_logging()` before any request handling starts.
2. All business and request events must go through `log_event(...)` at INFO level — never bare `print` or ad-hoc formatting.
3. The OTel push pipeline must be initialized via `setup_telemetry(app, SERVICE_NAME)` and must fail open.
4. `x-request-id` must be preserved and propagated; it cannot be silently dropped.
5. Metrics must follow the `<service>_<noun>_<unit>` naming convention and avoid high-cardinality labels.
6. OTLP credentials must come from environment/runtime secrets, never from code or ConfigMaps.
7. Disabling OTel must leave `/metrics` fully functional — the two surfaces are independent.