---
kind: logging_system
name: Structured Logging and OTLP Log Bridge Across All Services
category: logging_system
scope:
    - '**'
source_files:
    - shared/shared-contracts/observability-conventions.md
    - products/agent-platform/src/agent_service/core/observability.py
    - products/audit-service/src/audit_service/core/observability.py
    - products/execution-runtime/src/execution_runtime/core/observability.py
    - products/identity-broker/src/identity_service/core/observability.py
    - products/incident-service/src/incident_service/core/observability.py
    - products/platform-gateway/src/platform_gateway/core/observability.py
    - products/skills-hub/src/skills_hub/core/observability.py
    - products/tool-gateway/src/tool_gateway/core/observability.py
    - products/agent-platform/src/agent_service/core/telemetry.py
---

## What is used

Luban's logging system is built on Python's stdlib `logging` module — no third-party logger framework (no loguru, structlog, or logzero). Each product service ships its own tiny `core/observability.py` that exposes two functions:

- `configure_logging()` — raises the root logger from uvicorn's default WARNING to INFO so structured audit records are not silently dropped; reads `LOG_LEVEL` from the environment.
- `log_event(logger, event, **fields)` — serializes a dict with an `event` key plus arbitrary fields as a single-line JSON string via `json.dumps(..., sort_keys=True, default=str)`, emitted at INFO level.

The same two-function shape is duplicated in every FastAPI product under `src/<service>/core/observability.py` (agent-platform, audit-service, execution-runtime, identity-broker, incident-service, platform-gateway, skills-hub, tool-gateway).

Opt-in OpenTelemetry push is wired through `opentelemetry.exporter.otlp.proto.http.*`. When `OTEL_ENABLED=true`, `core/telemetry.setup_telemetry()` attaches an OTel `LoggingHandler` to the root logger so every structured record is mirrored over OTLP HTTP/protobuf to the configured backend (OpenObserve). The bridge is idempotent (`_attach_log_bridge` guards against double attachment), detaches `opentelemetry`'s own loggers from propagation, and fails open — exporter errors are logged and swallowed.

## Key files

- `shared/shared-contracts/observability-conventions.md` — repository-wide spec for observability: surfaces, metric naming, cardinality rules, OTel switch semantics, structured logging levels, OTLP log bridge, request correlation.
- `products/*/src/<service>/core/observability.py` — per-service `configure_logging` + `log_event` (8 copies, one per product).
- `products/agent-platform/src/agent_service/core/telemetry.py` — shared OTel setup, log bridge, `MetricsMirror`, `current_trace_id`; reused by other services.
- `products/*/src/<service>/app.py` — calls `configure_logging()` at startup and emits `log_event(LOGGER, "<lifecycle>", ...)` for app start/shutdown.
- `products/*/tests/test_observability.py` — per-service tests asserting `LOG_LEVEL` env override works.

## Architecture and conventions

1. **Two decoupled surfaces** (from `observability-conventions.md`):
   - `/metrics` (Prometheus, always-on, `prometheus_client`).
   - OTLP push (opt-in, gated by `OTEL_ENABLED`, default false).
2. **Structured log format**: every business/request event is a single-line JSON object with a required `event` field plus domain-specific keys. Business events use `log_event`; internal diagnostics use `LOGGER.info("message", extra={...})`.
3. **Level policy**: root logger defaults to INFO; `LOG_LEVEL` overrides it. The convention document states the default must stay INFO so audit records are never silently discarded.
4. **OTLP log bridge**: when enabled, the root logger gets an OTel `LoggingHandler` at INFO level. JSON stdout remains the source of truth; OTLP is a mirror for trace/log correlation. Trace/span ids attach automatically inside active spans.
5. **Request correlation**: `x-request-id` is the log- and portal-facing key; when tracing is active it is set to the active span's W3C `trace_id` (32 hex chars), otherwise falls back to `req-<uuid4>`. No service may silently drop an inbound correlation id.
6. **Fail-open**: missing/misconfigured OTel backend must never break a request; initialization and export failures are logged rather than raised.
7. **Cardinality rule**: never label on raw URL, user id, session id, or request id — these explode storage/query cost and are rejected at review.

## Conventions and constraints

- Every service initializes logging via its local `configure_logging()` at application startup; this is enforced by the presence of the function in each product's `core/observability.py` and by per-service `test_observability.py` cases that assert `LOG_LEVEL` overrides the default.
- Structured audit events go through `log_event(...)`, which guarantees a single-line JSON payload with `event` as the first key and sorted field names.
- `OTEL_ENABLED` is the single master gate for traces + metrics + logs push; there are no per-signal toggles.
- `OTEL_EXPORTER_OTLP_ENDPOINT` points to the org prefix (e.g. `http://openobserve-router:5080/api/default`); exporters append `/v1/traces`, `/v1/metrics`, `/v1/logs`.
- `OTEL_EXPORTER_OTLP_HEADERS` carries Basic-auth credentials provisioned via runtime-secrets; they are never committed or placed in ConfigMaps.
- `OTEL_SERVICE_NAME` defaults to the service's metadata name.
- The OTLP log bridge is attached exactly once per process (`_log_bridge_attached` guard) and detaches `opentelemetry` loggers from propagation to prevent recursion.
- Domain-metric mirroring (`MetricsMirror`) re-emits prometheus families as OTel instruments with the same name and bounded label set, but only when `OTEL_ENABLED=true`; `/metrics` stays the authoritative surface regardless.