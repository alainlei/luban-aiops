---
kind: logging_system
name: Logging System — Structured JSON Audit Trail with OTLP Log Bridge
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

## Approach

The Luban platform uses Python's stdlib `logging` module as the sole logging framework. There is no third-party logger (no structlog, loguru, or similar). Each FastAPI product service owns its own `core/observability.py` and `core/telemetry.py`, but all eight services follow an identical pattern defined by `SPEC-005` / `SPEC-065` and documented in `shared/shared-contracts/observability-conventions.md`.

## Key Files

- `shared/shared-contracts/observability-conventions.md` — authoritative cross-service contract for metrics, tracing, logging, request correlation, and OTel switch semantics.
- Per-service `app.py` — calls `configure_logging()` at startup and installs an HTTP middleware that emits a structured `http_request` event via `log_event`.
- Per-service `core/observability.py` — defines `configure_logging()` and `log_event(logger, event, **fields)`.
- Per-service `core/telemetry.py` — opt-in OpenTelemetry push pipeline (traces + metrics + mirrored logs) gated by `OTEL_ENABLED`; attaches an OTel `LoggingHandler` to the root logger when enabled.

Every product service (`agent-platform`, `audit-service`, `execution-runtime`, `identity-broker`, `incident-service`, `platform-gateway`, `skills-hub`, `tool-gateway`) follows this layout; each also has a `test_telemetry.py` asserting parity across services.

## Architecture and Conventions

### Two surfaces
1. **stdout JSON** — the audit trail source of truth. Every business and request event is emitted as a single-line JSON object via `log_event`, which serializes `{"event": <name>, ...fields}` through `json.dumps(..., default=str, sort_keys=True)` at INFO level.
2. **OpenTelemetry push (opt-in)** — traces, metrics, and a mirror of the same structured logs pushed over OTLP HTTP/protobuf to `OTEL_EXPORTER_OTLP_ENDPOINT`. Gated by `OTEL_ENABLED` (default false); fails open — setup errors are logged, never raised into the request path.

### Root logger configuration
`configure_logging()` reads `LOG_LEVEL` from the environment (default `INFO`), converts it via `getattr(logging, level_name, logging.INFO)`, and calls `logging.basicConfig(level=level, force=True)`. This overrides Uvicorn's WARNING default so INFO-level structured audit records survive.

### Structured fields
Business events use `log_event(LOGGER, "<event_name>", service="<service-name>", request_id=..., method=..., path=..., status_code=..., duration_ms=...)`. The `service` field identifies the producer; `request_id` is the correlation key (see below). Fields are passed as keyword arguments and merged into the payload dict before JSON serialization.

### Request correlation
- `x-request-id` is the log- and portal-facing correlation key, generated if absent and forwarded on every outbound call.
- When OTel tracing is active, `x-request-id` is bridged to the active span's W3C `trace_id` (32 hex chars) so a single value joins structured logs and APM traces.
- When tracing is inactive, `x-request-id` falls back to `req-<uuid4>`.
- No service may silently drop an inbound correlation id.

### OTLP log bridge
When `OTEL_ENABLED=true`, `setup_telemetry` attaches an OTel `LoggingHandler` (level INFO) to the root logger. Records emitted inside an active span automatically carry `trace_id`/`span_id`, joining the log mirror to the trace view. The `opentelemetry` loggers are detached from the root logger (`propagate = False`) so exporter failures cannot recurse back into the bridge. JSON stdout remains the source of truth; the OTLP mirror exists only for backend correlation.

### Level strategy
All business and request events are INFO. The default `LOG_LEVEL` must stay INFO so audit records are never silently discarded; operators can raise it per deployment (e.g. to WARNING) via the environment variable. Tests in `products/agent-platform/tests/test_observability.py` assert that `LOG_LEVEL=WARNING` suppresses INFO records and that the default restores INFO.

### Fail-open guarantees
Both `configure_logging` and `setup_telemetry` swallow exceptions: telemetry initialization failure is logged and the service continues without push. Missing/misconfigured OTel backends produce export-time 401s dropped by batch processors; they do not break requests.

### Domain-metric mirroring (related)
The `MetricsMirror` class in `core/telemetry.py` re-emits prometheus domain families as OTel instruments (same name, same bounded label set) when OTel is enabled, so domain metrics reach dashboards over the OTLP push path instead of via scraping. This is additive and does not affect the always-on `/metrics` surface.

## Conventions and Constraints

- **Convention:** Every service initializes logging via `from <service>.core.observability import configure_logging, log_event` and calls `configure_logging()` before creating the FastAPI app.
- **Convention:** Business events are emitted through `log_event(LOGGER, "<event>", **fields)` rather than direct `logger.info(...)`, ensuring uniform JSON shape.
- **Convention:** HTTP request lifecycle is instrumented via a FastAPI `@app.middleware("http")` that emits an `http_request` event with `method`, `path`, `status_code`, `duration_ms`, and `request_id`.
- **Rule (enforced by convention doc):** All business and request events are single-line JSON at INFO level; `LOG_LEVEL` defaults to INFO so audit records are never silently discarded.
- **Rule (enforced by convention doc):** OTel push is controlled exclusively by `OTEL_ENABLED` (master gate, default false); there are no per-signal toggles.
- **Rule (enforced by convention doc):** `OTEL_EXPORTER_OTLP_HEADERS` carries ingest authentication (Basic auth for OpenObserve) provisioned via runtime secrets, never committed.
- **Rule (enforced by convention doc):** `x-request-id` is the log- and portal-facing correlation key; when tracing is active it is set to the active span's W3C `trace_id`, and no service may silently drop an inbound correlation id.
- **Rule (enforced by convention doc):** Never use unbounded values as metric labels (raw URL, user id, session id, request id); high-cardinality labels are rejected at review.