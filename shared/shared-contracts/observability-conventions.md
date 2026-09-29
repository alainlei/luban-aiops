# Observability Conventions

## Purpose

Define the metrics, tracing, logging, and request-correlation conventions that all platform services follow, so that signal from every service is consistent, joinable, and stable enough for a future shared SDK or backend migration.

These conventions back `SPEC-005` (observability baseline) and `SPEC-065` (R5 observability — LLM token emission, the domain-metric OTel push mirror, and the config-as-code dashboards).

## Two Surfaces

Each service exposes two deliberately decoupled observability surfaces:

1. **`/metrics` (pull, always on)** — a collector-independent Prometheus endpoint for debugging and health. Works with no external infrastructure. Implemented directly with `prometheus_client` (a minimal RED middleware plus the endpoint; `prometheus-fastapi-instrumentator` proved incompatible with the pinned starlette — see the SPEC-005 changelog).
2. **OpenTelemetry push (opt-in)** — traces, metrics, and mirrored logs pushed via OTLP **HTTP/protobuf** to the configured backend (OpenObserve in this organization). Gated by `OTEL_ENABLED`; off by default; fails open.

The two never depend on each other: disabling OTel push leaves `/metrics` fully functional.

**Domain-metric push mirror (SPEC-065 R-2, ADR-0014).** Every domain family in the `prometheus_client` registry is additionally mirrored to an OpenTelemetry instrument of the *same name and same bounded label set* when `OTEL_ENABLED=true`, so it pushes over the existing OTLP pipeline and becomes visible in OpenObserve (and on the dashboards). The mirror is strictly **additive**: `/metrics` stays the always-on source of truth, and push-only dashboard visibility requires `OTEL_ENABLED`. The mechanism lives once in the parity-guarded `core/telemetry.py` and fails open.

## Metric Naming

- format: `<service>_<noun>_<unit>`, snake_case
- counters carry the `_total` suffix (Prometheus convention)
- the `<service>` prefix is the short service name: `gateway`, `identity`, `agent`

Examples:

- `gateway_policy_decisions_total{action,decision}`
- `gateway_token_verification_total{result}`
- `identity_tokens_issued_total`
- `agent_sessions_created_total`, `agent_chat_requests_total`
- `agent_llm_tokens_total{provider,model,direction}` — the LLM token counter (SPEC-065 R-1), recording provider-reported usage per model call; no cost metric is emitted (deferred — the platform maintains no price table)

## Standard Labels

- HTTP RED metrics (from the RED middleware): `method`, `handler` (the templated route, e.g. `/api/v1/sessions/{session_id}`), `status`
- domain counters use **bounded enum labels only** (e.g. `decision` ∈ {allow, deny}; `result` ∈ {valid, invalid, expired, missing})
- the LLM token counter's `direction` is the bounded enum `{input, output, cache_input, cache_creation}` (the counts agentscope's `ChatUsage` reports); its `model` is a bounded value drawn from the SPEC-026/027 model catalog, coerced to the sentinel `unknown` when uncatalogued so cardinality stays bounded

## Cardinality Rules

Never use an unbounded value as a label. In particular, do **not** label on:

- raw request URL (use the templated `handler`)
- user id / subject
- session id
- request id

High-cardinality labels explode storage and query cost and are rejected at review.

## OpenTelemetry Switch Semantics

OTel push is controlled by standard-aligned environment variables:

- `OTEL_ENABLED` — master gate, default `false`. When false, no OTel providers or instrumentation are initialized (zero overhead) and `/metrics` is unaffected. One switch gates the full signal (traces + metrics + log mirror); there are no per-signal toggles.
- `OTEL_EXPORTER_OTLP_ENDPOINT` — the backend OTLP HTTP base URL. Exporters speak OTLP over HTTP/protobuf and append the per-signal path (`/v1/traces`, `/v1/metrics`, `/v1/logs`), so the value stops at the org prefix, e.g. `http://openobserve-router:5080/api/default` for the OpenObserve ingest contract `/api/{org}/v1/{signal}`.
- `OTEL_EXPORTER_OTLP_HEADERS` — ingest authentication, `Authorization=Basic <base64(email:password)>` for OpenObserve. Secret material: provisioned into each service's runtime-secrets Secret by `sync-otel-secrets.sh`, never committed, never placed in the ConfigMap.
- `OTEL_SERVICE_NAME` — the resource service name; defaults to the service's metadata name.

Fail-open guarantee: an unreachable or misconfigured backend must never break a request. Missing/invalid credentials produce 401s at export time; OTel batch processors drop telemetry on export failure and service setup additionally guards initialization and logs rather than raising.

## Structured Logging Levels

All business and request events are emitted as single-line JSON via `log_event(...)` at **INFO** level. Because these records are the audit trail (http_request, tool_invoked, policy decisions), every service calls `configure_logging()` at app startup to raise the root logger from uvicorn's WARNING default to INFO. The level is overridable per-deployment via `LOG_LEVEL`; the default must stay INFO so audit records are never silently discarded.

## OTLP Log Bridge

When OTel push is enabled, each service attaches an OTel `LoggingHandler` to the root logger so every structured record is also exported as an OTLP log record. Semantics:

- **JSON stdout stays the source of truth.** The OTLP mirror exists so the backend can correlate logs with traces; it never replaces container logs and audit tooling must keep reading stdout.
- Trace/span association is automatic: records emitted inside an active span carry its `trace_id`/`span_id`, joining the log mirror to the trace view on the same W3C id that backs `x-request-id`.
- Recursion guard: the `opentelemetry` loggers are detached from the root logger, so exporter failures cannot loop back through the bridge.
- The bridge is gated by the same `OTEL_ENABLED` switch and fails open with the rest of the pipeline.

## Request Correlation And Trace Bridging

- `x-request-id` is the **log- and portal-facing** correlation key. It is generated if absent (preserving the existing portal contract) and forwarded on every outbound service-to-service call.
- `traceparent` (W3C Trace Context) is the **machine-facing** propagation header, managed automatically by OpenTelemetry instrumentation across service hops.
- Bridging rule: when tracing is active, `x-request-id` is set to the active span's W3C `trace_id` (32 hex chars), so a single value joins structured logs and APM traces. When tracing is inactive, `x-request-id` falls back to a generated `req-<uuid4>`.
- No service may silently drop an inbound correlation id.

## Relationship To Backends

Services only *expose* `/metrics` and *push* OTLP. Scraping infrastructure, metrics/traces/logs storage, dashboards, and alerting are platform-ops concerns outside the service contract. OpenObserve is the organization's observability backend; OTLP HTTP is its first-class ingestion path (org-scoped at `/api/{org}/v1/{signal}`, Basic-authenticated). The dashboards that consume these signals are **config-as-code** under `shared/platform-ops/dashboards/` (SPEC-065 R-3), validated by `make validate-dashboards` in the verification path and applied by `apply-dashboards.sh`; see the [observability dashboards operator guide](../../docs/guides/observability-dashboards.md).
