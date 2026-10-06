# Monitoring and Observability

<cite>
**Referenced Files in This Document**
- [observability.py](file://products/tool-gateway/src/tool_gateway/core/observability.py)
- [metrics.py](file://products/tool-gateway/src/tool_gateway/core/metrics.py)
- [telemetry.py](file://products/tool-gateway/src/tool_gateway/core/telemetry.py)
- [audit_emitter.py](file://products/tool-gateway/src/tool_gateway/services/audit_emitter.py)
- [request_context.py](file://products/tool-gateway/src/tool_gateway/core/request_context.py)
- [base.py](file://products/tool-gateway/src/tool_gateway/tools/base.py)
- [registry.py](file://products/tool-gateway/src/tool_gateway/tools/registry.py)
- [observability-conventions.md](file://shared/shared-contracts/observability-conventions.md)
- [sync-otel-secrets.sh](file://shared/platform-ops/gitops/sync-otel-secrets.sh)
- [telemetry.py](file://products/execution-runtime/src/execution_runtime/core/telemetry.py)
</cite>

## Update Summary
**Changes Made**
- Updated OTLP telemetry provisioning section to document the critical execution-runtime service inclusion fix
- Added troubleshooting guidance for 401 authentication errors in telemetry collection
- Enhanced deployment configuration section with proper service coverage requirements
- Updated architecture diagrams to reflect complete service mesh observability

## Table of Contents
1. Introduction
2. Project Structure
3. Core Components
4. Architecture Overview
5. Detailed Component Analysis
6. Dependency Analysis
7. Performance Considerations
8. Troubleshooting Guide
9. Conclusion
10. Appendices

## Introduction
This document explains the monitoring and observability features implemented in the Tool Gateway. It covers metrics collection for tool invocations, error rates, and performance indicators; distributed tracing integration across service boundaries; audit event emission for compliance and debugging; and guidance for dashboards, alerting, log aggregation, structured logging, and troubleshooting. It also provides examples of how specialized tools can emit custom metrics and traces.

**Updated** Added comprehensive coverage of OTLP telemetry provisioning and authentication mechanisms that ensure all platform services can successfully export telemetry data.

## Project Structure
The Tool Gateway implements a two-surface observability model aligned with platform conventions:
- A pull-based Prometheus /metrics endpoint that is always on and collector-independent.
- An opt-in OpenTelemetry push pipeline that exports traces, metrics, and mirrored logs via OTLP HTTP/protobuf to a configured backend.

Key modules:
- Logging configuration and structured event emission
- Prometheus metrics surface and RED middleware
- OpenTelemetry setup, FastAPI and HTTP client instrumentation, and log bridge
- Audit event emitter (fire-and-forget delivery to the audit service)
- Request correlation helpers that bridge x-request-id and trace context
- Tool base abstractions and registry used by tool implementations

```mermaid
graph TB
subgraph "Tool Gateway"
A["HTTP Requests"]
B["FastAPI App"]
C["RED Middleware<br/>Prometheus /metrics"]
D["OpenTelemetry Setup<br/>Traces + Metrics + Logs"]
E["Audit Emitter<br/>Fire-and-forget"]
F["Structured Logger<br/>log_event()"]
end
A --> B
B --> C
B --> D
B --> E
B --> F
```

**Diagram sources**
- [metrics.py:68-89](file://products/tool-gateway/src/tool_gateway/core/metrics.py#L68-L89)
- [telemetry.py:69-117](file://products/tool-gateway/src/tool_gateway/core/telemetry.py#L69-L117)
- [audit_emitter.py:67-98](file://products/tool-gateway/src/tool_gateway/services/audit_emitter.py#L67-L98)
- [observability.py:9-24](file://products/tool-gateway/src/tool_gateway/core/observability.py#L9-L24)

**Section sources**
- [observability-conventions.md:9-16](file://shared/shared-contracts/observability-conventions.md#L9-L16)
- [metrics.py:1-11](file://products/tool-gateway/src/tool_gateway/core/metrics.py#L1-L11)
- [telemetry.py:1-13](file://products/tool-gateway/src/tool_gateway/core/telemetry.py#L1-L13)

## Core Components
- Structured logging: configure_logging raises the root logger level so JSON audit events are emitted at INFO; log_event emits single-line JSON records suitable for log aggregation.
- Prometheus metrics: RED middleware records request counts and durations per handler; domain counters track policy decisions, token verification outcomes, redacted spans, and audit emit results; GET /metrics exposes raw Prometheus text.
- Distributed tracing: optional OTel push pipeline initializes TracerProvider, MeterProvider, FastAPI and HTTPX instrumentation, and bridges structured logs to OTLP logs when enabled.
- Audit events: fire-and-forget delivery to the audit service with non-blocking threads, timeouts, and outcome metrics; no degradation to the tool path on failures.
- Request correlation: resolves x-request-id from inbound header, active trace_id, or generated UUID; used consistently across services.

**Section sources**
- [observability.py:9-24](file://products/tool-gateway/src/tool_gateway/core/observability.py#L9-L24)
- [metrics.py:25-108](file://products/tool-gateway/src/tool_gateway/core/metrics.py#L25-L108)
- [telemetry.py:28-133](file://products/tool-gateway/src/tool_gateway/core/telemetry.py#L28-L133)
- [audit_emitter.py:29-98](file://products/tool-gateway/src/tool_gateway/services/audit_emitter.py#L29-L98)
- [request_context.py:8-19](file://products/tool-gateway/src/tool_gateway/core/request_context.py#L8-L19)

## Architecture Overview
The Tool Gateway processes requests through FastAPI, applies RED metrics, optionally instruments with OpenTelemetry, executes tools via the registry, emits audit events asynchronously, and writes structured logs. Outbound calls propagate trace context automatically.

```mermaid
sequenceDiagram
participant Client as "Client"
participant GW as "FastAPI App"
participant MET as "Prometheus /metrics"
participant OTEL as "OTel Pipeline"
participant REG as "Tool Registry"
participant AUD as "Audit Service"
Client->>GW : HTTP Request
GW->>MET : Record method/handler/status/duration
alt OTEL Enabled
GW->>OTEL : Start span (FastAPI instrumented)
end
GW->>REG : invoke(tool, params, identity)
REG-->>GW : ToolResult
GW->>AUD : emit_audit_event(event) [fire-and-forget]
GW-->>Client : Response
Note over GW,OTEL : If tracing active, logs include trace/span ids
```

**Diagram sources**
- [metrics.py:68-89](file://products/tool-gateway/src/tool_gateway/core/metrics.py#L68-L89)
- [telemetry.py:69-117](file://products/tool-gateway/src/tool_gateway/core/telemetry.py#L69-L117)
- [registry.py:65-88](file://products/tool-gateway/src/tool_gateway/tools/registry.py#L65-L88)
- [audit_emitter.py:67-98](file://products/tool-gateway/src/tool_gateway/services/audit_emitter.py#L67-L98)

## Detailed Component Analysis

### Structured Logging and Audit Trail
- configure_logging sets the root logger to INFO so JSON audit events survive Uvicorn's default WARNING level.
- log_event emits a single-line JSON record with an event name and fields; these records form the audit trail and are forwarded to OTLP logs when tracing is enabled.
- The OTLP log bridge attaches a LoggingHandler to the root logger, mirroring structured logs into the OTLP log pipeline while keeping stdout as source of truth.

```mermaid
flowchart TD
Start(["App startup"]) --> Level["configure_logging()<br/>set root level to INFO"]
Level --> Emit["log_event(logger, event, **fields)<br/>JSON line at INFO"]
Emit --> Bridge{"OTEL_ENABLED?"}
Bridge -- "Yes" --> OTLP["Attach LoggingHandler<br/>mirror to OTLP logs"]
Bridge -- "No" --> End(["Continue without OTLP mirror"])
OTLP --> End
```

**Diagram sources**
- [observability.py:9-24](file://products/tool-gateway/src/tool_gateway/core/observability.py#L9-L24)
- [telemetry.py:37-66](file://products/tool-gateway/src/tool_gateway/core/telemetry.py#L37-L66)

**Section sources**
- [observability.py:9-24](file://products/tool-gateway/src/tool_gateway/core/observability.py#L9-L24)
- [telemetry.py:37-66](file://products/tool-gateway/src/tool_gateway/core/telemetry.py#L37-L66)
- [observability-conventions.md:58-69](file://shared/shared-contracts/observability-conventions.md#L58-L69)

### Prometheus Metrics Surface
- RED middleware records http_requests_total and http_request_duration_seconds per method and templated handler, excluding the /metrics endpoint itself.
- Domain counters:
  - gateway_policy_decisions_total{action, decision}
  - gateway_token_verification_total{result}
  - gateway_tool_redacted_spans_total{tool}
  - audit_emits_total{result}
- GET /metrics returns the latest Prometheus format.

```mermaid
flowchart TD
Req["Incoming HTTP Request"] --> MW["record_http_metrics middleware"]
MW --> CallNext["call_next(request)"]
CallNext --> Update["Increment counters<br/>Observe histogram"]
Update --> Resp["Return response"]
Resp --> |GET /metrics| Export["generate_latest()"]
```

**Diagram sources**
- [metrics.py:62-89](file://products/tool-gateway/src/tool_gateway/core/metrics.py#L62-L89)

**Section sources**
- [metrics.py:25-108](file://products/tool-gateway/src/tool_gateway/core/metrics.py#L25-L108)
- [observability-conventions.md:18-45](file://shared/shared-contracts/observability-conventions.md#L18-L45)

### Distributed Tracing Integration
- Gated by OTEL_ENABLED; when disabled, no providers are initialized and there is zero overhead.
- Initializes TracerProvider and MeterProvider once, configures BatchSpanProcessor and PeriodicExportingMetricReader with OTLP HTTP exporters, and instruments FastAPI and HTTPX clients.
- Bridges structured logs to OTLP logs so they join traces via W3C trace context.
- current_trace_id returns the active span's trace_id when available, enabling correlation with x-request-id.

```mermaid
sequenceDiagram
participant App as "FastAPI App"
participant OTel as "OTel Providers"
participant Exp as "OTLP Exporters"
App->>OTel : setup_telemetry(app, service_name)
OTel->>Exp : Initialize TracerProvider/MeterProvider
App->>OTel : Instrument FastAPI + HTTPX
App->>OTel : Attach LoggingHandler (if enabled)
Note over App,Exp : Fail-open : setup errors logged, not raised
```

**Diagram sources**
- [telemetry.py:69-117](file://products/tool-gateway/src/tool_gateway/core/telemetry.py#L69-L117)

**Section sources**
- [telemetry.py:28-133](file://products/tool-gateway/src/tool_gateway/core/telemetry.py#L28-L133)
- [observability-conventions.md:47-57](file://shared/shared-contracts/observability-conventions.md#L47-L57)

### OTLP Telemetry Provisioning and Authentication
**Updated** Critical fix applied to ensure all platform services can authenticate with the OTLP backend.

The OTLP telemetry system requires proper authentication headers provisioned to each service's runtime secrets. The `sync-otel-secrets.sh` script now properly includes the execution-runtime service in all synchronization loops, resolving previous 401 authentication errors that prevented telemetry collection.

**Provisioning Process:**
- Computes Basic auth header from OpenObserve root credentials
- Merges OTLP headers cluster-side using `kubectl patch` (preserving other keys)
- Mirrors headers to local env files for consistency
- Restarts all eight workloads including agent-service, audit-service, execution-runtime, identity-service, incident-service, platform-gateway, skills-hub, and tool-gateway

**Service Coverage:**
All seven runtime-secrets Secrets now carry the authentication header:
- audit-service-runtime-secrets
- execution-runtime-runtime-secrets  
- identity-service-runtime-secrets
- incident-service-runtime-secrets
- platform-gateway-runtime-secrets
- skills-hub-runtime-secrets
- tool-gateway-runtime-secrets

```mermaid
flowchart TD
Start(["Run sync-otel-secrets.sh"]) --> Compute["Compute Authorization header<br/>from OpenObserve credentials"]
Compute --> MergeSecrets["Merge headers into all runtime-secrets<br/>using kubectl patch"]
MergeSecrets --> MirrorEnv["Mirror headers to local env files"]
MirrorEnv --> Restart["Restart all 8 deployments"]
Restart --> Verify["Verify rollout status"]
Verify --> Success["Authenticated telemetry push"]
```

**Diagram sources**
- [sync-otel-secrets.sh:54-90](file://shared/platform-ops/gitops/sync-otel-secrets.sh#L54-L90)
- [sync-otel-secrets.sh:116-163](file://shared/platform-ops/gitops/sync-otel-secrets.sh#L116-L163)

**Section sources**
- [sync-otel-secrets.sh:1-164](file://shared/platform-ops/gitops/sync-otel-secrets.sh#L1-L164)
- [telemetry.py:7-12](file://products/execution-runtime/src/execution_runtime/core/telemetry.py#L7-L12)

### Audit Event Emission
- build_audit_event constructs an envelope matching the shared audit-event schema, including event_id, occurred_at, event_type, service, request_id, outcome, details, and optional identity/session fields.
- emit_audit_event sends events to the audit service over HTTP using a daemon thread with a short timeout; failures are recorded via metrics and warnings but never block the caller.
- When audit service URL is unset, emission is a no-op, preserving historical log-only behavior.

```mermaid
sequenceDiagram
participant Caller as "Gateway Code"
participant AE as "emit_audit_event"
participant Thread as "Daemon Thread"
participant AS as "Audit Service"
Caller->>AE : emit_audit_event(settings, event)
AE->>Thread : start(_deliver(settings, event))
Thread->>AS : POST /api/v1/audit/events {events : [event]}
AS-->>Thread : Status code
Thread-->>Caller : Return immediately (non-blocking)
Note over Thread,AS : On failure, record_audit_emit("error") and log warning
```

**Diagram sources**
- [audit_emitter.py:29-98](file://products/tool-gateway/src/tool_gateway/services/audit_emitter.py#L29-L98)

**Section sources**
- [audit_emitter.py:29-98](file://products/tool-gateway/src/tool_gateway/services/audit_emitter.py#L29-L98)
- [metrics.py:105-108](file://products/tool-gateway/src/tool_gateway/core/metrics.py#L105-L108)

### Request Correlation and Trace Bridging
- resolve_request_id prefers an inbound x-request-id, then bridges to the active OTel trace_id when tracing is enabled, otherwise generates a UUID-prefixed id.
- This ensures a single correlation key joins logs and traces when tracing is active.

```mermaid
flowchart TD
In["Inbound request"] --> CheckHeader{"x-request-id present?"}
CheckHeader -- "Yes" --> UseHeader["Use provided id"]
CheckHeader -- "No" --> TraceId{"Tracing active?"}
TraceId -- "Yes" --> UseTrace["Use active trace_id"]
TraceId -- "No" --> Gen["Generate req-<uuid4>"]
UseHeader --> Out["Set correlation id"]
UseTrace --> Out
Gen --> Out
```

**Diagram sources**
- [request_context.py:8-19](file://products/tool-gateway/src/tool_gateway/core/request_context.py#L8-L19)
- [telemetry.py:120-133](file://products/tool-gateway/src/tool_gateway/core/telemetry.py#L120-L133)

**Section sources**
- [request_context.py:8-19](file://products/tool-gateway/src/tool_gateway/core/request_context.py#L8-L19)
- [observability-conventions.md:71-76](file://shared/shared-contracts/observability-conventions.md#L71-L76)

### Tool Execution and Evidence
- Tools implement BaseTool.execute and return ToolResult with status, data/evidence/error.
- Evidence includes executed_at, duration_ms, risk_level, and source_system, enabling post-execution analysis.
- Registry.invoke wraps execution and converts exceptions into structured error results with consistent codes.

```mermaid
classDiagram
class BaseTool {
+definition : ToolDefinition
+execute(parameters, identity) ToolResult
}
class ToolRegistry {
+register(tool) void
+invoke(name, parameters, identity) ToolResult
+list_definitions() ToolDefinition[]
}
class ToolResult {
+string tool_name
+string status
+dict data
+dict evidence
+dict error
}
BaseTool <|-- ToolRegistry : "dispatches"
ToolRegistry --> ToolResult : "returns"
```

**Diagram sources**
- [base.py:15-123](file://products/tool-gateway/src/tool_gateway/tools/base.py#L15-L123)
- [registry.py:18-89](file://products/tool-gateway/src/tool_gateway/tools/registry.py#L18-L89)

**Section sources**
- [base.py:15-123](file://products/tool-gateway/src/tool_gateway/tools/base.py#L15-L123)
- [registry.py:18-89](file://products/tool-gateway/src/tool_gateway/tools/registry.py#L18-L89)

## Dependency Analysis
- metrics.py depends on prometheus_client and FastAPI; it is independent of OTel.
- telemetry.py conditionally imports OTel SDKs only when enabled; it instruments FastAPI and HTTPX and bridges logs.
- audit_emitter.py depends on httpx and settings; it uses metrics to record outcomes.
- request_context.py depends on telemetry to read the active trace_id.
- registry.py and base.py provide the tool execution contract used by all tools.

```mermaid
graph LR
M["metrics.py"] --> P["prometheus_client"]
T["telemetry.py"] --> O["opentelemetry.*"]
T --> F["fastapi"]
T --> H["httpx"]
AE["audit_emitter.py"] --> M
AE --> X["httpx"]
RC["request_context.py"] --> T
REG["registry.py"] --> BASE["tools/base.py"]
```

**Diagram sources**
- [metrics.py:13-23](file://products/tool-gateway/src/tool_gateway/core/metrics.py#L13-L23)
- [telemetry.py:74-106](file://products/tool-gateway/src/tool_gateway/core/telemetry.py#L74-L106)
- [audit_emitter.py:10-21](file://products/tool-gateway/src/tool_gateway/services/audit_emitter.py#L10-L21)
- [request_context.py:1-5](file://products/tool-gateway/src/tool_gateway/core/request_context.py#L1-L5)
- [registry.py:1-13](file://products/tool-gateway/src/tool_gateway/tools/registry.py#L1-L13)
- [base.py:1-12](file://products/tool-gateway/src/tool_gateway/tools/base.py#L1-L12)

**Section sources**
- [metrics.py:13-23](file://products/tool-gateway/src/tool_gateway/core/metrics.py#L13-L23)
- [telemetry.py:74-106](file://products/tool-gateway/src/tool_gateway/core/telemetry.py#L74-L106)
- [audit_emitter.py:10-21](file://products/tool-gateway/src/tool_gateway/services/audit_emitter.py#L10-L21)
- [request_context.py:1-5](file://products/tool-gateway/src/tool_gateway/core/request_context.py#L1-L5)
- [registry.py:1-13](file://products/tool-gateway/src/tool_gateway/tools/registry.py#L1-L13)
- [base.py:1-12](file://products/tool-gateway/src/tool_gateway/tools/base.py#L1-L12)

## Performance Considerations
- Prometheus /metrics is always on and lightweight; avoid high-cardinality labels per conventions.
- OTel push is off by default; when enabled, batch processors minimize overhead and fail open.
- Audit emission is fire-and-forget with a short timeout; it never blocks tool execution paths.
- Tool implementations should measure their own duration and populate evidence.duration_ms for accurate per-tool performance analysis.

## Troubleshooting Guide
- No logs visible: ensure configure_logging() is called at startup and LOG_LEVEL allows INFO.
- Missing OTel signals: verify OTEL_ENABLED and OTEL_EXPORTER_OTLP_ENDPOINT; check that authentication headers are provisioned and reachable.
- **401 Unauthorized errors**: Run `shared/platform-ops/gitops/sync-otel-secrets.sh` to provision OTLP headers for all services including execution-runtime. Ensure OO_ROOT_USER_EMAIL and OO_ROOT_USER_PASSWORD are exported.
- High cardinality alerts: review label usage against conventions; use templated handlers instead of raw URLs.
- Audit gaps: confirm GATEWAY_AUDIT_SERVICE_URL is set; inspect audit_emits_total{result} and warnings for delivery failures.
- Slow endpoints: analyze http_request_duration_seconds per handler; correlate with tool execution evidence.duration_ms.

**Updated** Added specific troubleshooting steps for 401 authentication errors that were caused by missing execution-runtime service in the OTLP header synchronization process.

**Section sources**
- [observability.py:9-19](file://products/tool-gateway/src/tool_gateway/core/observability.py#L9-L19)
- [telemetry.py:28-35](file://products/tool-gateway/src/tool_gateway/core/telemetry.py#L28-L35)
- [metrics.py:62-89](file://products/tool-gateway/src/tool_gateway/core/metrics.py#L62-L89)
- [audit_emitter.py:67-98](file://products/tool-gateway/src/tool_gateway/services/audit_emitter.py#L67-L98)
- [observability-conventions.md:18-45](file://shared/shared-contracts/observability-conventions.md#L18-L45)
- [sync-otel-secrets.sh:47-52](file://shared/platform-ops/gitops/sync-otel-secrets.sh#L47-L52)

## Conclusion
The Tool Gateway provides a robust, standards-aligned observability foundation: always-on Prometheus metrics, opt-in OpenTelemetry tracing and log bridging, structured audit trails, and fire-and-forget audit delivery. These components enable reliable dashboards, alerting, and cross-service tracing while preserving performance and fail-open guarantees.

**Updated** The recent fix to the OTLP telemetry provisioning ensures all platform services, including execution-runtime, can successfully authenticate and export telemetry data, eliminating previous 401 authentication errors that prevented comprehensive observability across the service mesh.

## Appendices

### Setting Up Dashboards and Alerting
- Pull metrics from GET /metrics and scrape with your preferred Prometheus-compatible system.
- Build dashboards around:
  - http_requests_total{method, handler, status}
  - http_request_duration_seconds{method, handler}
  - gateway_policy_decisions_total{action, decision}
  - gateway_token_verification_total{result}
  - gateway_tool_redacted_spans_total{tool}
  - audit_emits_total{result}
- Configure alert rules for:
  - Elevated error rates (status >= 5xx) per handler
  - Latency SLO breaches per handler
  - Policy denials spikes
  - Audit emit errors increasing beyond thresholds
  - OTLP export failures indicating authentication issues

### Log Aggregation Strategy
- Aggregate single-line JSON logs from stdout at INFO level.
- When OTel is enabled, correlate logs with traces using the same W3C trace_id bound to x-request-id.
- Ensure log levels are not downgraded below INFO to preserve the audit trail.

**Section sources**
- [observability.py:9-24](file://products/tool-gateway/src/tool_gateway/core/observability.py#L9-L24)
- [observability-conventions.md:58-69](file://shared/shared-contracts/observability-conventions.md#L58-L69)

### Custom Metrics and Traces for Specialized Tools
- Add custom counters/histograms in a module-level scope to avoid double registration and follow naming conventions.
- Record tool-specific success/failure and latency in tool.execute and populate evidence.duration_ms.
- When tracing is enabled, spans created by FastAPI and HTTPX instrumentation will automatically capture outbound calls; add additional spans inside tool.execute if needed to capture internal steps.

**Section sources**
- [metrics.py:1-11](file://products/tool-gateway/src/tool_gateway/core/metrics.py#L1-L11)
- [base.py:108-123](file://products/tool-gateway/src/tool_gateway/tools/base.py#L108-L123)
- [telemetry.py:69-117](file://products/tool-gateway/src/tool_gateway/core/telemetry.py#L69-L117)
- [observability-conventions.md:18-45](file://shared/shared-contracts/observability-conventions.md#L18-L45)

### Deployment Configuration Requirements
**Updated** Complete service coverage is required for effective observability across the platform.

**Required Services for OTLP Telemetry:**
All eight platform services must be included in OTLP header synchronization:
- agent-service
- audit-service
- execution-runtime (critical fix applied)
- identity-service
- incident-service
- platform-gateway
- skills-hub
- tool-gateway

**Verification Steps:**
1. Run `shared/platform-ops/gitops/sync-otel-secrets.sh` with proper credentials
2. Verify all runtime-secrets contain OTEL_EXPORTER_OTLP_HEADERS
3. Check pod logs for successful OTLP authentication
4. Monitor for absence of 401 Unauthorized errors
5. Confirm traces, metrics, and logs flow to the configured backend

**Section sources**
- [sync-otel-secrets.sh:116-163](file://shared/platform-ops/gitops/sync-otel-secrets.sh#L116-L163)