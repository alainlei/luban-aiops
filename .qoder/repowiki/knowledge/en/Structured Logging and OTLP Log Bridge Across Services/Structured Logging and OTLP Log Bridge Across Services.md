---
kind: logging_system
name: Structured Logging and OTLP Log Bridge Across Services
category: logging_system
scope:
    - '**'
source_files:
    - shared/shared-contracts/observability-conventions.md
    - products/agent-platform/src/agent_service/core/observability.py
    - products/agent-platform/src/agent_service/core/telemetry.py
    - products/agent-platform/src/agent_service/services/audit_emitter.py
    - products/audit-service/src/audit_service/core/observability.py
    - products/audit-service/src/audit_service/core/telemetry.py
    - products/execution-runtime/src/execution_runtime/core/observability.py
    - products/execution-runtime/src/execution_runtime/core/telemetry.py
    - products/identity-broker/src/identity_service/core/observability.py
    - products/identity-broker/src/identity_service/core/telemetry.py
    - products/incident-service/src/incident_service/core/observability.py
    - products/incident-service/src/incident_service/core/telemetry.py
    - products/platform-gateway/src/platform_gateway/core/telemetry.py
---

## Approach

The platform uses Python's stdlib `logging` module for all application logging, with a uniform structured-JSON convention documented in `shared/shared-contracts/observability-conventions.md`. There is no third-party logger framework (no structlog, loguru, or similar). An opt-in OpenTelemetry push pipeline mirrors every INFO-level JSON record to an OTLP backend (OpenObserve) via `opentelemetry.exporter.otlp.proto.http._log_exporter`, but stdout remains the source of truth.

## Key Files

- `shared/shared-contracts/observability-conventions.md` — authoritative cross-service contract describing the two observability surfaces (`/metrics` pull + OTLP push), the `LOG_LEVEL` / `OTEL_ENABLED` switches, request-correlation rules, and the structured-logging level policy.
- Per-service `core/observability.py` — defines `configure_logging()` and `log_event(logger, event, **fields)`:
  - `products/agent-platform/src/agent_service/core/observability.py`
  - `products/audit-service/src/audit_service/core/observability.py`
  - `products/execution-runtime/src/execution_runtime/core/observability.py`
  - `products/identity-broker/src/identity_service/core/observability.py`
  - `products/incident-service/src/incident_service/core/observability.py`
  - `products/platform-gateway/src/platform_gateway/core/telemetry.py` (gateway has no separate `observability.py`; its `setup_telemetry` also attaches the OTLP bridge).
- Per-service `core/telemetry.py` — initializes traces/metrics/logs OTLP exporters gated by `OTEL_ENABLED`.
- `products/agent-platform/src/agent_service/services/audit_emitter.py` — fire-and-forget HTTP emitter that ships structured audit events to the dedicated audit service; failures are swallowed and logged at WARNING.

## Architecture and Conventions

1. **Root logger configuration.** Each service calls `configure_logging()` at startup. It reads `LOG_LEVEL` (default `INFO`, upper-cased, falling back to `logging.INFO` if unknown) and applies it via `logging.basicConfig(level=level, force=True)`. This overrides uvicorn's default WARNING root level so INFO audit records are not silently discarded.
2. **Structured event emission.** Business/request events go through `log_event(LOGGER, "event_name", key=value, ...)`, which serializes `{"event": name, ...}` as a single-line JSON string at INFO level using `json.dumps(..., default=str, sort_keys=True)`. Call sites across services use this helper rather than calling `logger.info(json.dumps(...))` directly.
3. **Logger instance pattern.** Modules define `LOGGER = logging.getLogger(__name__)` at module top level and pass it to `log_event`.
4. **OTLP log bridge.** When `OTEL_ENABLED` is truthy (`1|true|yes|on`), each service installs an OTel `LoggingHandler` on the root logger. The bridge:
   - Is attached once per process (`_log_bridge_attached` guard).
   - Detaches `logging.getLogger("opentelemetry")` from propagation so exporter errors cannot recurse into the bridge.
   - Emits at INFO level only.
   - Is wrapped in try/except around the whole provider setup; exceptions are logged and the service continues without push.
5. **Two decoupled surfaces.** `/metrics` (Prometheus, always on) and OTLP push (opt-in, fails open). Disabling OTel leaves `/metrics` fully functional.
6. **Request correlation.** `x-request-id` is the portal-facing correlation key; when tracing is active it is set to the W3C `trace_id` (32 hex chars), otherwise generated as `req-<uuid4>`. Outbound calls forward both `x-request-id` and `traceparent`.
7. **Audit trail separation.** Structured logs are the human/CLI audit trail; a separate fire-and-forget HTTP emitter (`audit_emitter.emit_audit_event`) ships normalized audit events to the audit service over `/api/v1/audit/events` on a daemon thread with a 2s timeout. Audit emit failures are counted via metrics and logged at WARNING but never raised.

## Conventions and Constraints

- **Level policy:** All business and request events are emitted at INFO level via `log_event`. The root logger is explicitly raised from uvicorn's WARNING default to INFO at startup; `LOG_LEVEL` may override per deployment. (Enforced by `configure_logging` in every service's `core/observability.py`.)
- **Structured format:** Events are single-line JSON with a required `event` field plus arbitrary additional fields serialized with `sort_keys=True` and `default=str`. (Defined in `log_event` and observed across all call sites.)
- **OTel switch semantics:** `OTEL_ENABLED` is the master gate; when false, no OTel providers or instrumentation are initialized (zero overhead) and `/metrics` is unaffected. One switch gates traces + metrics + log mirror; there are no per-signal toggles. (Documented in `observability-conventions.md` and enforced by `is_enabled()` / early-return in `setup_telemetry`.)
- **Fail-open guarantee:** Missing/invalid OTel credentials produce 401s at export time; batch processors drop telemetry on failure; service setup additionally guards initialization and logs rather than raising. (Documented in `observability-conventions.md`; implemented in each service's `setup_telemetry` try/except.)
- **No unbounded label cardinality:** Metrics labels must be bounded enums; raw URLs, user ids, session ids, and request ids are never used as labels. (Constraint stated in `observability-conventions.md`.)
- **Audit emit non-blocking:** `emit_audit_event` runs on a daemon thread with a 2-second timeout; failures are swallowed and recorded via metrics, never propagated to the caller. (Enforced by the implementation in `audit_emitter.py`.)
- **Correlation header rule:** No service may silently drop an inbound correlation id; `x-request-id` is preserved or regenerated, and `traceparent` is forwarded on outbound calls. (Stated in `observability-conventions.md`.)
- **Source-of-truth rule:** JSON stdout is the source of truth for the audit trail; the OTLP mirror exists only for backend correlation and never replaces container logs. (Stated in `observability-conventions.md` and enforced by attaching the bridge to the root logger rather than replacing handlers.)