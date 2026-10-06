# Tool Gateway

<cite>
**Referenced Files in This Document**
- [app.py](file://products/tool-gateway/src/tool_gateway/app.py)
- [main.py](file://products/tool-gateway/src/tool_gateway/main.py)
- [registry.py](file://products/tool-gateway/src/tool_gateway/tools/registry.py)
- [base.py](file://products/tool-gateway/src/tool_gateway/tools/base.py)
- [gateway_service.py](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py)
- [config.py](file://products/tool-gateway/src/tool_gateway/core/config.py)
- [k8s_connector.py](file://products/tool-gateway/src/tool_gateway/tools/k8s_connector.py)
- [elastic_connector.py](file://products/tool-gateway/src/tool_gateway/tools/elastic_connector.py)
- [browser_connector.py](file://products/tool-gateway/src/tool_gateway/tools/browser_connector.py)
- [incidents_connector.py](file://products/tool-gateway/src/tool_gateway/tools/incidents_connector.py)
- [skills_connector.py](file://products/tool-gateway/src/tool_gateway/tools/skills_connector.py)
- [http_connector.py](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py)
- [secrets_connector.py](file://products/tool-gateway/src/tool_gateway/tools/secrets_connector.py)
- [url_redaction.py](file://products/tool-gateway/src/tool_gateway/tools/url_redaction.py)
- [redaction.py](file://products/tool-gateway/src/tool_gateway/tools/redaction.py)
- [audit_emitter.py](file://products/tool-gateway/src/tool_gateway/services/audit_emitter.py)
- [policy_engine.py](file://products/tool-gateway/src/tool_gateway/services/policy_engine.py)
- [secret_delivery.py](file://products/tool-gateway/src/tool_gateway/tools/secret_delivery.py)
- [router.py](file://products/tool-gateway/src/tool_gateway/api/router.py)
- [test_tool_registry.py](file://products/tool-gateway/tests/test_tool_registry.py)
- [test_tool_invoke.py](file://products/tool-gateway/tests/test_tool_invoke.py)
- [test_http_connector.py](file://products/tool-gateway/tests/test_http_connector.py)
- [README.md](file://products/tool-gateway/README.md)
</cite>

## Update Summary
**Changes Made**
- Updated connector inventory to include HTTP, secrets, and browser web-checks alongside existing Kubernetes, Elastic, skills-hub, and incidents connectors
- Added comprehensive documentation for the new HTTP connector with bounded service check capabilities
- Enhanced SecretsConnector documentation covering secure password generation and delivery mechanisms
- Updated architecture diagrams to reflect the complete connector ecosystem
- Expanded credential management section to cover shared credential set infrastructure across connectors

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

## Introduction
The Tool Gateway is a normalized access layer that exposes external systems through pluggable tool connectors. It centralizes authentication, policy enforcement, parameter validation, output redaction, audit emission, and structured error handling. The platform now provides comprehensive connectivity through seven built-in connectors: Kubernetes, Elasticsearch, browser automation (web-check flows), HTTP services, incidents, skills repositories, and secure secret delivery mechanisms. Each connector implements standardized security controls including origin allowlisting, credential set management, parameter validation, and structured error responses. The gateway enforces risk-tier admission for mutating actions and integrates with the platform's audit and policy systems to ensure consistent governance across all tool invocations.

## Project Structure
The Tool Gateway service is organized into:
- Application entrypoint and lifecycle management
- API routing and request orchestration
- Tool registry and base abstractions
- Seven connector implementations per system
- Policy engine and token verification
- Audit emission and observability
- Configuration and runtime settings

```mermaid
graph TB
A["FastAPI app<br/>lifespan"] --> B["ToolRegistry"]
A --> C["GatewayService<br/>invoke_tool()"]
C --> D["PolicyEngine<br/>evaluate()"]
C --> E["AuditEmitter<br/>emit_audit_event()"]
C --> F["Redaction<br/>redact_result()"]
B --> G["KubernetesConnector"]
B --> H["ElasticConnector"]
B --> I["BrowserConnector"]
B --> J["IncidentsConnector"]
B --> K["SkillsConnector"]
B --> L["HttpConnector"]
B --> M["SecretsConnector"]
L --> N["URL Redaction<br/>secret masking"]
M --> O["SecretDeliveryBuffer<br/>stash/redeem/discard"]
O --> P["InMemory/Redis Backend"]
```

**Diagram sources**
- [app.py:19-237](file://products/tool-gateway/src/tool_gateway/app.py#L19-L237)
- [gateway_service.py:158-376](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L158-L376)
- [policy_engine.py:299-355](file://products/tool-gateway/src/tool_gateway/services/policy_engine.py#L299-L355)
- [audit_emitter.py:67-98](file://products/tool-gateway/src/tool_gateway/services/audit_emitter.py#L67-L98)
- [redaction.py:126-151](file://products/tool-gateway/src/tool_gateway/tools/redaction.py#L126-L151)
- [http_connector.py:350-359](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L350-L359)
- [secrets_connector.py:379-387](file://products/tool-gateway/src/tool_gateway/tools/secrets_connector.py#L379-L387)
- [secret_delivery.py:50-91](file://products/tool-gateway/src/tool_gateway/tools/secret_delivery.py#L50-L91)

**Section sources**
- [app.py:19-237](file://products/tool-gateway/src/tool_gateway/app.py#L19-L237)
- [main.py:1-9](file://products/tool-gateway/src/tool_gateway/main.py#L1-L9)

## Core Components
- ToolRegistry: In-process lookup and dispatch; enforces risk-tier admission at registration time and wraps execution errors into structured results.
- BaseTool and ToolDefinition: Abstract interface and metadata schema for tools, including risk_level and parameters_schema.
- GatewayService: Orchestrates identity resolution, policy checks, tool dispatch, redaction, audit emission, and response mapping.
- PolicyEngine: Loads and evaluates policy bundles; deny-by-default semantics with explicit allow/deny and require_approval outcomes.
- Redaction: Deterministic output sanitization using value patterns and sensitive key lists; fail-closed on overflow.
- URL Redaction: Specialized URL secret masking for query parameters and userinfo components.
- AuditEmitter: Fire-and-forget durable audit events to the audit service; non-blocking and failure-tolerant.
- Config: Centralized environment-driven configuration for connectors, policy, auth, and feature flags.

**Section sources**
- [registry.py:18-89](file://products/tool-gateway/src/tool_gateway/tools/registry.py#L18-L89)
- [base.py:15-123](file://products/tool-gateway/src/tool_gateway/tools/base.py#L15-L123)
- [gateway_service.py:61-156](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L61-L156)
- [policy_engine.py:254-355](file://products/tool-gateway/src/tool_gateway/services/policy_engine.py#L254-L355)
- [redaction.py:1-151](file://products/tool-gateway/src/tool_gateway/tools/redaction.py#L1-L151)
- [url_redaction.py:1-91](file://products/tool-gateway/src/tool_gateway/tools/url_redaction.py#L1-L91)
- [audit_emitter.py:1-98](file://products/tool-gateway/src/tool_gateway/services/audit_emitter.py#L1-L98)
- [config.py:32-190](file://products/tool-gateway/src/tool_gateway/core/config.py#L32-L190)

## Architecture Overview
The invocation path enforces security and safety at every stage:
- Identity verification via local JWT verification or synthetic dev identity when configured.
- Policy evaluation for tools:invoke and tools:mutate based on roles and loaded bundle.
- Risk-tier gating prevents mutating tools from executing unless explicitly admitted.
- Tool dispatch through the registry with structured error envelopes.
- Output redaction before response and audit emission.
- Durable audit trail via fire-and-forget emission.

```mermaid
sequenceDiagram
participant Client as "Caller"
participant Gateway as "FastAPI App"
participant Service as "GatewayService.invoke_tool"
participant Policy as "PolicyEngine.evaluate"
participant Registry as "ToolRegistry.invoke"
participant HttpConn as "HttpConnector"
participant UrlRedact as "URL Redaction"
participant Redact as "Redaction"
participant Audit as "AuditEmitter"
Client->>Gateway : POST /api/v2/tools/invoke
Gateway->>Service : resolve_request_identity + enforce_policy
Service->>Policy : evaluate("tools : invoke")
Policy-->>Service : decision
alt denied
Service-->>Client : 403 {status : "denied"}
else allowed
Service->>Registry : invoke(tool_name, parameters, identity)
alt http.get/http.post
Registry->>HttpConn : execute(parameters, identity)
HttpConn->>UrlRedact : redact_secret_query(url)
UrlRedact-->>HttpConn : masked URL
HttpConn-->>Registry : ToolResult
else secrets.generate_password/secrets.deliver
Registry->>SecretsConn : execute(parameters, identity)
SecretsConn-->>Registry : ToolResult
end
Registry-->>Service : ToolResult
Service->>Redact : redact_result(result)
Redact-->>Service : redacted result + stats
Service->>Audit : emit_audit_event(...)
Service-->>Client : JSONResponse(status_code)
end
```

**Diagram sources**
- [gateway_service.py:158-376](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L158-L376)
- [policy_engine.py:299-355](file://products/tool-gateway/src/tool_gateway/services/policy_engine.py#L299-L355)
- [registry.py:65-89](file://products/tool-gateway/src/tool_gateway/tools/registry.py#L65-L89)
- [http_connector.py:389-491](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L389-L491)
- [url_redaction.py:49-91](file://products/tool-gateway/src/tool_gateway/tools/url_redaction.py#L49-L91)
- [redaction.py:126-151](file://products/tool-gateway/src/tool_gateway/tools/redaction.py#L126-L151)
- [audit_emitter.py:67-98](file://products/tool-gateway/src/tool_gateway/services/audit_emitter.py#L67-L98)

## Detailed Component Analysis

### Tool Registry and Base Abstraction
- ToolRegistry validates risk_level against a fixed vocabulary and refuses mutating tools unless allow_mutating is enabled.
- Registry.invoke returns structured ToolResult for both unknown tools and exceptions, ensuring callers always receive a consistent envelope.
- BaseTool defines the contract: definition and async execute(parameters, identity).

```mermaid
classDiagram
class BaseTool {
+definition : ToolDefinition
+execute(parameters, identity) ToolResult
}
class ToolDefinition {
+name : string
+description : string
+risk_level : string
+category : string
+parameters_schema : dict
+to_dict() dict
}
class ToolResult {
+tool_name : string
+status : string
+data : dict|None
+evidence : dict
+error : dict|None
+to_dict() dict
}
class ToolRegistry {
-_tools : dict
-_allow_mutating : bool
+register(tool) void
+get(name) BaseTool|None
+list_definitions() list
+invoke(name, parameters, identity) ToolResult
}
BaseTool <|-- KubernetesConnector
BaseTool <|-- ElasticConnector
BaseTool <|-- BrowserConnector
BaseTool <|-- IncidentsConnector
BaseTool <|-- SkillsConnector
BaseTool <|-- HttpGetTool
BaseTool <|-- HttpPostTool
BaseTool <|-- GeneratePasswordTool
BaseTool <|-- DeliverSecretTool
ToolRegistry --> BaseTool : "dispatches"
```

**Diagram sources**
- [base.py:15-123](file://products/tool-gateway/src/tool_gateway/tools/base.py#L15-L123)
- [registry.py:18-89](file://products/tool-gateway/src/tool_gateway/tools/registry.py#L18-L89)
- [http_connector.py:497-699](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L497-L699)
- [secrets_connector.py:403-620](file://products/tool-gateway/src/tool_gateway/tools/secrets_connector.py#L403-L620)

**Section sources**
- [registry.py:18-89](file://products/tool-gateway/src/tool_gateway/tools/registry.py#L18-L89)
- [base.py:15-123](file://products/tool-gateway/src/tool_gateway/tools/base.py#L15-L123)
- [test_tool_registry.py:56-172](file://products/tool-gateway/tests/test_tool_registry.py#L56-L172)

### HTTP Connector
The HTTP connector provides bounded HTTP service check capabilities with two tools: `http.get` (read tier) and `http.post` (write tier). It implements strict security controls including origin allowlisting, redirect following with allowlist validation, body size limits, and credential set-based authentication.

Key features:
- **Origin Allowlist**: Deny-by-default with configurable allowed origins
- **Redirect Handling**: Follows up to 3 redirects with allowlist validation at each hop
- **Body Validation**: Limits JSON POST bodies to depth ≤ 2, ≤ 32 keys, and configurable byte limits
- **Credential Management**: Uses named credential sets resolved server-side into HTTP Basic auth
- **URL Secret Masking**: Automatically masks secret-bearing query parameters in reported URLs
- **Response Projection**: Filters response headers to a safe allowlist, excluding credentials

```mermaid
flowchart TD
Start(["http.get/http.post"]) --> ValidateDest{"Validate destination URL"}
ValidateDest --> |Invalid| ErrorParam["Return INVALID_PARAMETERS"]
ValidateDest --> |Valid| CheckAllowlist{"Origin in allowlist?"}
CheckAllowlist --> |No| OriginDenied["HTTP_ORIGIN_NOT_ALLOWED"]
CheckAllowlist --> |Yes| ResolveAuth{"Resolve credential_set"}
ResolveAuth --> |Error| CredError["CREDENTIAL_SET_NOT_FOUND"]
ResolveAuth --> |Success| MakeRequest["Make HTTP request"]
MakeRequest --> Redirect{"3xx redirect?"}
Redirect --> |Yes| ValidateHop{"Validate redirect target"}
ValidateHop --> |Invalid| RedirectDenied["HTTP_REDIRECT_NOT_ALLOWED"]
ValidateHop --> |Valid| FollowHop["Follow redirect"]
Redirect --> |No| ProcessResponse["Process response"]
ProcessResponse --> ProjectHeaders["Project safe headers only"]
ProjectHeaders --> MaskSecrets["Mask secret query params"]
MaskSecrets --> ReturnResult["Return ToolResult"]
```

**Diagram sources**
- [http_connector.py:100-180](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L100-L180)
- [http_connector.py:389-491](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L389-L491)
- [http_connector.py:255-302](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L255-302)

**Section sources**
- [http_connector.py:1-699](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L1-L699)
- [test_http_connector.py:1-789](file://products/tool-gateway/tests/test_http_connector.py#L1-L789)

### Secrets Connector and Secure Delivery System
The SecretsConnector provides secure password generation and delivery capabilities as specified in SPEC-062. This connector introduces two tool primitives with comprehensive security controls and active destruction capabilities.

**Key Features:**
- **`secrets.generate_password`**: A read-tier CSPRNG tool that generates cryptographically strong passwords using Python's `secrets` module, bound to a centralized password policy
- **`secrets.deliver`**: A write-tier tool that securely delivers generated passwords through multiple channels (portal Copy button, email) without ever exposing plaintext in transcripts or evidence
- **Active Destruction**: New DELETE endpoint for immediate destruction of held deliveries without revealing values
- **Password Policy Enforcement**: Centralized password strength rules with configurable tightening
- **One-Time Delivery**: Ephemeral, single-use, TTL-bounded delivery mechanism with owner-scoped access
- **Extensible Channel Interface**: Support for portal Copy button (primary) and email (optional, gated) with extensibility for Teams/Slack

```mermaid
flowchart TD
Start(["secrets.generate_password"]) --> ValidatePolicy{"Validate password policy"}
ValidatePolicy --> |Invalid| ErrorPolicy["Return INVALID_PARAMETERS"]
ValidatePolicy --> |Valid| Generate["Generate CSPRNG password"]
Generate --> StashValue["Stash in delivery buffer"]
StashValue --> ReturnGen["Return masked ToolResult with delivery_id"]
Start2(["secrets.deliver"]) --> ValidateChannel{"Validate channel"}
ValidateChannel --> |Portal| CreateHandle["Create ephemeral handle"]
CreateHandle --> ReturnDeliver["Return delivery_id"]
ValidateChannel --> |Email| GateDelivery{"Gated by secrets:deliver"}
GateDelivery --> |Allowed| SendEmail["Send via SMTP"]
GateDelivery --> |Denied| AccessDenied["Return ACCESS_DENIED"]
SendEmail --> EmitAudit["Emit secret_delivered event"]
EmitAudit --> ReturnDeliver
Start3(["DELETE /delivery/{id}"]) --> ValidateOwner{"Validate owner scope"}
ValidateOwner --> |Valid| DestroyHandle["Destroy delivery handle"]
DestroyHandle --> Return204["Return 204 No Content"]
ValidateOwner --> |Invalid| Return204
```

**Diagram sources**
- [secrets_connector.py:403-620](file://products/tool-gateway/src/tool_gateway/tools/secrets_connector.py#L403-L620)
- [secret_delivery.py:50-91](file://products/tool-gateway/src/tool_gateway/tools/secret_delivery.py#L50-L91)

**Section sources**
- [secrets_connector.py:1-664](file://products/tool-gateway/src/tool_gateway/tools/secrets_connector.py#L1-L664)
- [secret_delivery.py:1-369](file://products/tool-gateway/src/tool_gateway/tools/secret_delivery.py#L1-L369)

### Secret Delivery Buffer
The SecretDeliveryBuffer provides single-use, owner-scoped, TTL-bounded secret storage with both redemption and active destruction capabilities. It supports both in-memory and Redis backends for different deployment scenarios.

**Key Capabilities:**
- **Single-Use Redemption**: Values can be redeemed exactly once by the authorized owner
- **Active Destruction**: New discard capability allows immediate destruction without revealing values
- **Owner Scoping**: Both redemption and destruction are scoped to the original owner
- **TTL Management**: Automatic expiration with configurable TTL periods
- **Backend Flexibility**: Supports both in-memory (development) and Redis (production) backends
- **Oracle-Free Responses**: All operations return indistinguishable responses regardless of outcome

```mermaid
flowchart TD
Input["delivery_id + owner_sub"] --> Validate{"Valid UUID format?"}
Validate --> |No| ReturnFalse["Return False"]
Validate --> |Yes| Lookup{"Lookup entry"}
Lookup --> |Not Found| ReturnFalse
Lookup --> |Found| CheckExpiry{"Entry expired?"}
CheckExpiry --> |Yes| ReturnFalse
CheckExpiry --> |No| CheckOwner{"Owner matches?"}
CheckOwner --> |No| ReturnFalse
CheckOwner --> |Yes| Operation{"Operation type?"}
Operation --> |Redeem| PopAndReturn["Pop entry and return value"]
Operation --> |Discard| DeleteOnly["Delete entry only"]
PopAndReturn --> SuccessTrue["Return True"]
DeleteOnly --> SuccessTrue
```

**Diagram sources**
- [secret_delivery.py:158-186](file://products/tool-gateway/src/tool_gateway/tools/secret_delivery.py#L158-L186)
- [secret_delivery.py:232-263](file://products/tool-gateway/src/tool_gateway/tools/secret_delivery.py#L232-L263)

**Section sources**
- [secret_delivery.py:50-369](file://products/tool-gateway/src/tool_gateway/tools/secret_delivery.py#L50-L369)

### URL Redaction Module
The URL redaction module provides coordinated secret masking for URLs across HTTP and browser connectors. It masks secret-bearing query parameters and userinfo components while preserving URL structure and non-secret values.

Features:
- **Secret Parameter Detection**: Case-insensitive matching of known secret parameter names
- **Userinfo Masking**: Masks passwords in `scheme://user:password@host` format
- **Query Parameter Masking**: Replaces secret parameter values with `***` markers
- **Preservation**: Maintains exact URL encoding and non-secret parameter values

```mermaid
flowchart TD
Input["URL Input"] --> Parse["Parse URL components"]
Parse --> CheckUserinfo{"Has password in userinfo?"}
CheckUserinfo --> |Yes| MaskUserinfo["Replace password with ***"]
CheckUserinfo --> |No| SkipUserinfo["Skip userinfo processing"]
MaskUserinfo --> ProcessQuery["Process query parameters"]
SkipUserinfo --> ProcessQuery
ProcessQuery --> SplitQuery["Split by & delimiter"]
SplitQuery --> ForEachParam{"For each parameter"}
ForEachParam --> CheckSecret{"Is parameter name secret?"}
CheckSecret --> |Yes| MaskValue["Replace value with ***"]
CheckSecret --> |No| KeepValue["Keep original value"]
MaskValue --> Reconstruct["Reconstruct URL"]
KeepValue --> Reconstruct
Reconstruct --> Output["Masked URL Output"]
```

**Diagram sources**
- [url_redaction.py:49-91](file://products/tool-gateway/src/tool_gateway/tools/url_redaction.py#L49-L91)

**Section sources**
- [url_redaction.py:1-91](file://products/tool-gateway/src/tool_gateway/tools/url_redaction.py#L1-L91)

### Kubernetes Connector
- Provides read-only tools: k8s.list_pods, k8s.get_pod, k8s.get_events, k8s.get_pod_logs.
- Offers one bounded mutating tool: k8s.delete_pod (write risk), only registered when mutating tools are admitted.
- Uses in-cluster config or kubeconfig; returns structured K8S_NOT_CONFIGURED when unavailable.
- Parameter validation includes clamping tail_lines and enforcing required fields.

```mermaid
flowchart TD
Start(["k8s.get_pod_logs"]) --> CheckConfig{"K8s client configured?"}
CheckConfig --> |No| ErrorCfg["Return K8S_NOT_CONFIGURED"]
CheckConfig --> |Yes| ValidateParams["Validate name, container, tail_lines"]
ValidateParams --> Invalid{"Valid?"}
Invalid --> |No| ErrorParam["Return INVALID_PARAMETERS"]
Invalid --> |Yes| Exec["Run sync call in executor"]
Exec --> Success["Return success with logs"]
Exec --> ApiError["Map ApiException -> POD_NOT_FOUND/K8S_PERMISSION_DENIED/K8S_API_ERROR"]
```

**Diagram sources**
- [k8s_connector.py:41-92](file://products/tool-gateway/src/tool_gateway/tools/k8s_connector.py#L41-L92)
- [k8s_connector.py:376-518](file://products/tool-gateway/src/tool_gateway/tools/k8s_connector.py#L376-L518)

**Section sources**
- [k8s_connector.py:41-518](file://products/tool-gateway/src/tool_gateway/tools/k8s_connector.py#L41-L518)

### Elasticsearch Connector
- Read-only tools: elastic.search_logs, elastic.get_service_health, elastic.get_active_alerts.
- Supports API-key or basic auth; verifies connectivity at initialization.
- Parameter coercion clamps time ranges and result limits to safe bounds.

```mermaid
flowchart TD
Start(["elastic.search_logs"]) --> EnsureClient{"Client ready?"}
EnsureClient --> |No| ErrNotCfg["Return ELASTIC_NOT_CONFIGURED"]
EnsureClient --> |Yes| CoerceParams["Coerce time_range_minutes, max_results"]
CoerceParams --> Valid{"Valid?"}
Valid --> |No| ErrParam["Return INVALID_PARAMETERS"]
Valid --> |Yes| Query["Execute search query"]
Query --> Ok["Return hits, total, query metadata"]
Query --> ConnErr["Return ELASTIC_CONNECTION_ERROR"]
```

**Diagram sources**
- [elastic_connector.py:40-103](file://products/tool-gateway/src/tool_gateway/tools/elastic_connector.py#L40-L103)
- [elastic_connector.py:287-379](file://products/tool-gateway/src/tool_gateway/tools/elastic_connector.py#L287-L379)

**Section sources**
- [elastic_connector.py:40-535](file://products/tool-gateway/src/tool_gateway/tools/elastic_connector.py#L40-L535)

### Browser Connector
- Bounded web-check surface over Chromium sidecar via CDP with session pooling.
- Origin allowlist enforcement; flow binding validates skill declarations and risk_class.
- Interaction guards prevent off-origin navigation and enforce step budgets; read captures re-check live origin.
- Credential sets resolved from secret-mounted files; screenshots mask password-tier values.
- Write-tier tools include web.click, web.type, web.select, web.press_key, web.upload_file, web.evaluate; read-tier includes web.navigate, web.snapshot, web.screenshot, web.fill_credential, web.extract, web.wait_for, web.hover, web.scroll, web.switch_frame.

```mermaid
sequenceDiagram
participant Caller as "Caller"
participant Browser as "BrowserConnector"
participant Pool as "BrowserSessionPool"
participant Page as "Page/Frame"
participant UrlRedact as "URL Redaction"
Caller->>Browser : web.navigate(url, skill_id?)
Browser->>Pool : get_or_create(session_key)
Pool-->>Browser : BrowserSessionEntry
Browser->>Browser : is_origin_allowed(url)
alt skill_id provided
Browser->>Browser : fetch_skill(skill_id)
Browser->>Browser : bind_flow(entry, skill_id, url, skill)
end
Browser->>UrlRedact : redact_secret_query(url)
UrlRedact-->>Browser : masked URL
Browser->>Page : goto(url)
Page-->>Browser : active_target.url
Browser->>Browser : gate_capture() for snapshots/screenshots
Browser-->>Caller : ToolResult(evidence URL masked)
```

**Diagram sources**
- [browser_connector.py:315-399](file://products/tool-gateway/src/tool_gateway/tools/browser_connector.py#L315-L399)
- [browser_connector.py:425-531](file://products/tool-gateway/src/tool_gateway/tools/browser_connector.py#L425-L531)
- [browser_connector.py:655-698](file://products/tool-gateway/src/tool_gateway/tools/browser_connector.py#L655-L698)
- [browser_connector.py:730-800](file://products/tool-gateway/src/tool_gateway/tools/browser_connector.py#L730-L800)
- [url_redaction.py:49-91](file://products/tool-gateway/src/tool_gateway/tools/url_redaction.py#L49-L91)

**Section sources**
- [browser_connector.py:1-800](file://products/tool-gateway/src/tool_gateway/tools/browser_connector.py#L1-L800)

### Incidents Connector
- Read-only access to incident-service: incidents.list, incidents.get.
- Validates incident_id pattern and filters by status/severity/source with bounded limits.
- Maps upstream HTTP errors to structured codes like INCIDENT_NOT_FOUND.

**Section sources**
- [incidents_connector.py:68-339](file://products/tool-gateway/src/tool_gateway/tools/incidents_connector.py#L68-L339)

### Skills Connector
- Read-only access to skills-hub: skills.search, skills.get, skills.list.
- Enforces namespaced skill_id pattern and projects stable match/list keys.
- Forwards request_id for downstream usage audit correlation.

**Section sources**
- [skills_connector.py:71-419](file://products/tool-gateway/src/tool_gateway/tools/skills_connector.py#L71-L419)

### Invocation Lifecycle and Error Handling
- Identity resolution supports bearer tokens and synthetic dev identity when configured.
- Policy enforcement denies without identity or matching allow rules; mutating tools additionally require tools:mutate.
- Registry.invoke catches exceptions and returns TOOL_EXECUTION_ERROR with evidence.
- Redaction applies deterministic masking and fails closed on overflow; audit events emitted for all outcomes.

```mermaid
flowchart TD
Req["Incoming request"] --> Auth["Resolve identity"]
Auth --> PolicyCheck{"tools:invoke allowed?"}
PolicyCheck --> |No| Deny["403 denied"]
PolicyCheck --> |Yes| MutateCheck{"Risk level != read?"}
MutateCheck --> |Yes| MutatePolicy{"tools:mutate allowed?"}
MutatePolicy --> |No| MutDeny["403 denied"]
MutatePolicy --> |Yes| Dispatch["Registry.invoke"]
MutateCheck --> |No| Dispatch
Dispatch --> Result["ToolResult"]
Result --> Redact["Redaction check"]
Redact --> Overflow{"Overflow?"}
Overflow --> |Yes| Withhold["REDACTION_OVERFLOW"]
Overflow --> |No| Emit["Emit audit event"]
Emit --> Resp["JSONResponse"]
```

**Diagram sources**
- [gateway_service.py:61-156](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L61-L156)
- [gateway_service.py:158-376](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L158-L376)
- [registry.py:65-89](file://products/tool-gateway/src/tool_gateway/tools/registry.py#L65-L89)
- [redaction.py:126-151](file://products/tool-gateway/src/tool_gateway/tools/redaction.py#L126-L151)

**Section sources**
- [gateway_service.py:61-376](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L61-L376)
- [registry.py:65-89](file://products/tool-gateway/src/tool_gateway/tools/registry.py#L65-L89)
- [test_tool_invoke.py:184-549](file://products/tool-gateway/tests/test_tool_invoke.py#L184-L549)

### Credential Management and Security
- Browser credential sets loaded from a secret-mounted file path; never inline.
- Sensitive query parameters masked in reported URLs for evidence.
- Screenshots mask password-tier values to avoid leaking secrets.
- All connector credentials are passed via configuration and never exposed in results or audit payloads.
- HTTP connector uses the same credential set mechanism as browser connector, supporting rotation without restart.

**Section sources**
- [browser_connector.py:123-148](file://products/tool-gateway/src/tool_gateway/tools/browser_connector.py#L123-L148)
- [browser_connector.py:174-257](file://products/tool-gateway/src/tool_gateway/tools/browser_connector.py#L174-L257)
- [http_connector.py:361-387](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L361-L387)
- [url_redaction.py:27-41](file://products/tool-gateway/src/tool_gateway/tools/url_redaction.py#L27-L41)
- [config.py:63-73](file://products/tool-gateway/src/tool_gateway/core/config.py#L63-L73)

### Integration with Audit and Policy Systems
- PolicyEngine loads bundled rules, computes content fingerprint, and evaluates actions with deny-by-default semantics.
- AuditEmitter emits durable events asynchronously; failures do not degrade the tool path.
- GatewayService records metrics for policy decisions, redaction spans, and token verification outcomes.
- The SecretsConnector integrates with the existing audit and policy systems, introducing a new `secret_delivered` audit event type and `secrets:deliver` policy action for email delivery operations.

**Section sources**
- [policy_engine.py:254-355](file://products/tool-gateway/src/tool_gateway/services/policy_engine.py#L254-L355)
- [audit_emitter.py:29-98](file://products/tool-gateway/src/tool_gateway/services/audit_emitter.py#L29-L98)
- [gateway_service.py:32-59](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L32-L59)

## Dependency Analysis
- Application wiring: app creates registry and optional browser connector; lifespan starts/stops browser pool.
- Connectors depend on external clients (kubernetes, elasticsearch, httpx) and register tools conditionally based on configuration.
- GatewayService depends on policy engine, token verifier, redaction, and audit emitter.
- HTTP connector integrates with URL redaction module and shares credential set infrastructure with browser connector.
- SecretsConnector depends on password policy validation and secure delivery buffer backends.

```mermaid
graph LR
App["app.create_app"] --> Reg["ToolRegistry"]
App --> Browser["BrowserConnector (optional)"]
Reg --> K8s["KubernetesConnector"]
Reg --> ES["ElasticConnector"]
Reg --> Br["BrowserConnector"]
Reg --> Inc["IncidentsConnector"]
Reg --> Sk["SkillsConnector"]
Reg --> Http["HttpConnector"]
Reg --> Secrets["SecretsConnector"]
Http --> UrlRedact["URL Redaction"]
Secrets --> Buffer["SecretDeliveryBuffer"]
Buffer --> Memory["InMemory Backend"]
Buffer --> Redis["Redis Backend"]
GS["GatewayService"] --> PE["PolicyEngine"]
GS --> AE["AuditEmitter"]
GS --> RD["Redaction"]
```

**Diagram sources**
- [app.py:19-237](file://products/tool-gateway/src/tool_gateway/app.py#L19-L237)
- [gateway_service.py:158-376](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L158-L376)
- [http_connector.py:350-359](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L350-L359)
- [secret_delivery.py:277-327](file://products/tool-gateway/src/tool_gateway/tools/secret_delivery.py#L277-L327)

**Section sources**
- [app.py:19-237](file://products/tool-gateway/src/tool_gateway/app.py#L19-L237)

## Performance Considerations
- Async execution: Connectors run blocking calls in executors to avoid blocking the event loop.
- Connection pooling: Browser sessions pooled with TTL and max sessions; Elasticsearch client initialized once per connector instance.
- Parameter bounds: Time ranges, result limits, and log tail sizes are clamped to prevent resource exhaustion.
- Redaction overhead: Redaction runs once per result; overflow detection prevents excessive processing.
- Observability: Metrics recorded for policy decisions, redaction spans, token verification, and audit emissions.
- HTTP connector uses connection-per-request pattern with timeout limits and response size caps to prevent resource exhaustion.
- SecretsConnector uses efficient CSPRNG generation and minimal memory footprint for ephemeral delivery handles.

## Troubleshooting Guide
Common issues and diagnostics:
- Authentication failures: Verify bearer token audience and issuer; check token expiration and JWKS availability.
- Policy denials: Inspect matched rule IDs and reasons; confirm roles and actions align with policy bundle.
- Unknown tools: Ensure tool registration and risk-tier admission; verify tool name matches definition.
- Upstream connectivity: Connectors return structured errors (e.g., K8S_NOT_CONFIGURED, ELASTIC_NOT_CONFIGURED, UPSTREAM_ERROR); check configuration and network reachability.
- Browser flow deviations: Off-origin navigation or stale flow provenance triggers specific denial codes; navigate back to bound target or re-bind flow.
- Redaction overflow: If too much of the result appears sensitive, outputs are withheld; tighten parameters or reduce payload size.
- HTTP connector issues: Origin allowlist denials, redirect loops, credential set resolution failures, and URL secret masking problems.
- SecretsConnector issues: Password policy violations, delivery handle expiration, email delivery configuration problems, and active destruction failures.

**Section sources**
- [gateway_service.py:61-156](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L61-L156)
- [k8s_connector.py:41-92](file://products/tool-gateway/src/tool_gateway/tools/k8s_connector.py#L41-L92)
- [elastic_connector.py:40-103](file://products/tool-gateway/src/tool_gateway/tools/elastic_connector.py#L40-L103)
- [browser_connector.py:533-698](file://products/tool-gateway/src/tool_gateway/tools/browser_connector.py#L533-L698)
- [http_connector.py:100-180](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L100-L180)
- [redaction.py:126-151](file://products/tool-gateway/src/tool_gateway/tools/redaction.py#L126-L151)
- [test_tool_invoke.py:184-549](file://products/tool-gateway/tests/test_tool_invoke.py#L184-L549)

## Conclusion
The Tool Gateway provides a secure, extensible, and observable framework for invoking external tools through standardized connectors. It enforces risk-tier admission, policy-based authorization, robust parameter validation, deterministic output redaction, and durable auditing. The platform now includes seven comprehensive built-in connectors covering Kubernetes, Elasticsearch, browser automation, HTTP services, incidents, skills repositories, and secure secret delivery, while the registry and base abstractions make it straightforward to add custom connectors with consistent behavior and governance.

The addition of HTTP connector capabilities extends the platform's ability to perform bounded HTTP service checks with the same security guarantees as other connectors, including origin allowlisting, credential set management, and URL secret masking. The complete implementation of SPEC-062 secure password generation and delivery system provides cryptographically strong password generation, secure one-time delivery mechanisms, and active destruction capabilities through the new DELETE endpoint. 

This comprehensive connector ecosystem ensures that the Tool Gateway serves as a unified, secure boundary between the platform and external systems, maintaining consistent security policies, audit trails, and operational visibility across all tool invocations while providing flexible integration patterns for diverse operational requirements.