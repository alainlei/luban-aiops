---
kind: logging_system
name: Standard Library Logging with Structured Event Emission
category: logging_system
scope:
    - '**'
source_files:
    - products/agent-platform/src/agent_service/core/observability.py
    - products/agent-platform/src/agent_service/app.py
    - products/platform-gateway/src/platform_gateway/core/observability.py
    - products/platform-gateway/src/platform_gateway/app.py
    - products/audit-service/src/audit_service/core/observability.py
    - products/audit-service/src/audit_service/app.py
    - products/execution-runtime/src/execution_runtime/core/observability.py
    - products/execution-runtime/src/execution_runtime/app.py
    - products/identity-broker/src/identity_service/core/observability.py
    - products/identity-broker/src/identity_service/app.py
    - products/incident-service/src/incident_service/core/observability.py
    - products/incident-service/src/incident_service/app.py
---

## Approach

The platform does not use a third-party logging framework (no structlog, loguru, or gunicorn-logging). Every product service configures Python's built-in `logging` module and emits **structured JSON events** by serializing a dict through `json.dumps(..., sort_keys=True)`. The pattern is duplicated identically in each product under `<product>/src/<package>/core/observability.py`.

## Per-service initialization

Each FastAPI service follows the same bootstrap shape in its `app.py`:

1. `LOGGER = logging.getLogger(__name__)` — per-module logger instance.
2. `configure_logging()` is called first thing inside `create_app()`, before the `FastAPI` constructor.
3. An HTTP middleware named `log_requests` wraps every request and emits an `http_request` event via `log_event(LOGGER, "http_request", ...)`.
4. `setup_metrics(app)` and `setup_telemetry(app, SERVICE_NAME)` are invoked after routing is attached.

This pattern appears verbatim across `agent-platform`, `platform-gateway`, `audit-service`, `execution-runtime`, `identity-broker`, and `incident-service`.

## Level configuration

`configure_logging()` reads `LOG_LEVEL` from the environment (defaulting to `"INFO"`), maps it via `getattr(logging, level_name, logging.INFO)`, and calls `logging.basicConfig(level=level, force=True)`. The docstring explicitly documents why: Uvicorn starts the root logger at `WARNING`, which would silently drop every `log_event` record (the audit trail). `force=True` reconfigures the root logger even if handlers were already installed.

Tests in `test_observability.py` for several services assert this behavior by patching `os.environ["LOG_LEVEL"]` to `"WARNING"` and verifying that INFO-level records are discarded.

## Structured event format

`log_event(logger, event, **fields)` builds `payload = {"event": event, **fields}` and logs it at `INFO` as a single JSON string. All values are coerced via `default=str`; keys are sorted. Consumers therefore see one line per event — a JSON object with a stable `event` discriminator field plus arbitrary key/value pairs.

Common fields emitted by the HTTP middleware include:
- `service` — the canonical service name (`"agent-service"`, `"platform-gateway"`, `"audit-service"`, `"execution-runtime"`, etc.).
- `request_id` — resolved from the `x-request-id` header (or generated).
- `method`, `path`, `status_code`, `duration_ms`.

Domain-specific events follow the same shape, e.g. `auth_login_url_requested`, `auth_login_started`, `auth_logout_requested`, `identity_normalized`, `http_request`.

## Sinks / output

There is no custom handler, formatter, or sink layer. `basicConfig` attaches the default `StreamHandler` writing to `sys.stderr`. Log output is therefore consumed by the container runtime (stdout/stderr) and forwarded to whatever external collector the deployment targets (e.g. OpenTelemetry via the separate `telemetry` subsystem, or a log aggregator). No file sinks, rotation, or enrichment pipeline exists in code.

## Conventions observed

- One `core/observability.py` per product, containing both `configure_logging()` and `log_event()`.
- Services import them as `from <product>.core.observability import configure_logging, log_event`.
- `LOG_LEVEL` is the sole knob for verbosity; there is no per-module level override.
- Business events go through `log_event` (JSON); startup/shutdown diagnostics sometimes call `LOGGER.info("message", extra={...})` directly (see `audit_service.app.lifespan` and `execution_runtime.app.lifespan`).
- Request correlation uses the `x-request-id` header, resolved by `core/request_context.resolve_request_id` and injected into every `http_request` event.
- The `event` field is the primary discriminator used by consumers to parse structured logs.

## Rules enforced by the codebase

- Root logger level must be set via `configure_logging()` at process start; relying on Uvicorn's default `WARNING` level is treated as a bug because it drops audit events (documented in the docstrings of every `configure_logging`).
- New structured events should be emitted through `log_event` rather than raw `logger.info(json.dumps(...))`, since all callers in the codebase consistently use the helper.
- The `LOG_LEVEL` environment variable is the only supported mechanism for changing log verbosity at runtime.