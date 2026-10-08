# Credential Management and Security

<cite>
**Referenced Files in This Document**
- [credential_sets.py](file://products/tool-gateway/src/tool_gateway/tools/credential_sets.py)
- [auth_resolution.py](file://products/tool-gateway/src/tool_gateway/tools/auth_resolution.py)
- [oauth_client.py](file://products/tool-gateway/src/tool_gateway/tools/oauth_client.py)
- [redaction.py](file://products/tool-gateway/src/tool_gateway/tools/redaction.py)
- [url_redaction.py](file://products/tool-gateway/src/tool_gateway/tools/url_redaction.py)
- [http_connector.py](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py)
- [browser_connector.py](file://products/tool-gateway/src/tool_gateway/tools/browser_connector.py)
- [secrets_connector.py](file://products/tool-gateway/src/tool_gateway/tools/secrets_connector.py)
- [secret_delivery.py](file://products/tool-gateway/src/tool_gateway/tools/secret_delivery.py)
- [password_policy.py](file://products/tool-gateway/src/tool_gateway/tools/password_policy.py)
- [gateway_service.py](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py)
- [request_context.py](file://products/tool-gateway/src/tool_gateway/core/request_context.py)
- [config.py](file://products/tool-gateway/src/tool_gateway/core/config.py)
- [base.py](file://products/tool-gateway/src/tool_gateway/tools/base.py)
- [SPEC-062 spec.md](file://docs/specs/SPEC-062-secure-password-generation-and-delivery/spec.md)
- [SPEC-068 spec.md](file://docs/specs/SPEC-068-outbound-execution-credential-schemes/spec.md)
- [ADR-0012](file://docs/adr/0012-one-time-secret-delivery-handoff.md)
- [password-policy.yaml](file://shared/shared-contracts/policies/password-policy.yaml)
</cite>

## Update Summary
**Changes Made**
- Enhanced credential masking throughout the entire request/response lifecycle with ephemeral masking knowledge
- Added comprehensive redaction capabilities with improved pattern detection and overflow protection
- Integrated one-time secure delivery mechanisms with portal-based copy functionality and gated email delivery
- Expanded password generation with centralized policy enforcement and CSPRNG security
- Improved URL secret masking for query parameters and userinfo components across all connectors
- Enhanced audit logging with new secret delivery tracking events
- Updated troubleshooting guide with secrets connector-specific issues and policy enforcement scenarios
- **Updated** Enhanced credential model now supports scheme-aware parsing system with optional per-set scheme field, extending beyond fixed username/password requirements while maintaining backward compatibility
- **New** Complete OAuth2 client credentials implementation with token caching, refresh management, and fail-closed security semantics
- **New** Reusable outbound authentication resolution seam supporting basic, bearer, and oauth2_client_credentials schemes

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
This document explains how the Tool Gateway manages credentials and prevents sensitive data from leaking in tool outputs through enhanced credential masking throughout the entire request/response lifecycle. It covers:
- The credential set architecture for browser login flows and HTTP service authentication with reference-based credential resolution and scheme-aware parsing supporting multiple authentication schemes.
- The new secrets connector providing cryptographically secure password generation with centralized policy enforcement and one-time secure delivery mechanisms.
- One-time secure delivery mechanisms including portal-based copy functionality and gated email delivery.
- The enhanced redaction system that detects and masks secrets, tokens, and personal information in tool results with comprehensive pattern matching.
- Rotation strategies, access controls, audit logging, and best practices for secure credential management.
- HTTP connector capabilities including origin allowlisting, redirect protection, and URL secret masking.
- Ephemeral masking knowledge that tracks generated credentials throughout the execution pipeline to prevent any leakage in transcripts, evidence, or audit trails.

## Project Structure
The Tool Gateway implements comprehensive credential handling and output sanitization across a focused set of modules:
- Credential sets: lazy-loaded JSON secret file with named sets supporting scheme-aware parsing for both browser login flows and HTTP Basic authentication.
- Authentication resolution: reusable seam for resolving credential sets into appropriate outbound authentication mechanisms (basic, bearer, oauth2_client_credentials).
- OAuth2 token client: connector-local token acquisition with caching, refresh management, and fail-closed security semantics.
- Secrets connector: CSPRNG password generation with centralized policy enforcement and one-time secure delivery mechanisms.
- Redaction engine: deterministic, code-owned pattern matching and key-based masking applied to every tool result before it leaves the gateway.
- URL redaction: specialized URL masking for query parameters and userinfo components to prevent secret leakage.
- Secret delivery buffer: ephemeral storage for one-time secret handoff with TTL expiration and owner scoping.
- HTTP connector: bounded HTTP tools with strict origin validation, redirect protection, and credential set integration.
- Browser connector: bounded web tools that consume credential sets and mask sensitive query parameters and screenshots.
- Gateway orchestration: policy checks, tool dispatch, redaction, and audit emission at a single choke point.
- Configuration: environment-driven settings controlling redaction behavior, HTTP connectivity, secrets generation, and credential set injection.

```mermaid
graph TB
A["GatewaySettings<br/>config.py"] --> B["CredentialSetStore<br/>credential_sets.py"]
A --> C["Auth Resolution<br/>auth_resolution.py"]
A --> D["OAuth2 Token Client<br/>oauth_client.py"]
A --> E["Secrets Connector<br/>secrets_connector.py"]
A --> F["Redaction rules<br/>redaction.py"]
A --> G["URL Redaction<br/>url_redaction.py"]
A --> H["Secret Delivery Buffer<br/>secret_delivery.py"]
I["HTTP Connector<br/>http_connector.py"] --> B
I --> C
I --> D
I --> G
J["BrowserConnector<br/>browser_connector.py"] --> B
J --> G
K["Secrets Connector<br/>secrets_connector.py"] --> L["Password Policy<br/>policy contract"]
K --> M["Delivery Buffer<br/>one-time handles"]
N["GatewayService.invoke_tool<br/>gateway_service.py"] --> I
N --> J
N --> K
N --> O["Redact tool output<br/>redaction.py"]
N --> P["Audit events<br/>audit_emitter (external)"]
H --> Q["Portal Copy Channel<br/>ephemeral storage"]
H --> R["Email Channel<br/>gated delivery"]
```

**Diagram sources**
- [config.py:200-240](file://products/tool-gateway/src/tool_gateway/core/config.py#L200-L240)
- [credential_sets.py:30-103](file://products/tool-gateway/src/tool_gateway/tools/credential_sets.py#L30-L103)
- [auth_resolution.py:69-113](file://products/tool-gateway/src/tool_gateway/tools/auth_resolution.py#L69-L113)
- [oauth_client.py:81-232](file://products/tool-gateway/src/tool_gateway/tools/oauth_client.py#L81-L232)
- [redaction.py:24-57](file://products/tool-gateway/src/tool_gateway/tools/redaction.py#L24-L57)
- [url_redaction.py:27-41](file://products/tool-gateway/src/tool_gateway/tools/url_redaction.py#L27-L41)
- [secret_delivery.py:231-282](file://products/tool-gateway/src/tool_gateway/tools/secret_delivery.py#L231-L282)
- [http_connector.py:322-360](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L322-L360)
- [browser_connector.py:174-257](file://products/tool-gateway/src/tool_gateway/tools/browser_connector.py#L174-L257)
- [gateway_service.py:158-376](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L158-L376)

**Section sources**
- [config.py:200-240](file://products/tool-gateway/src/tool_gateway/core/config.py#L200-L240)
- [gateway_service.py:158-376](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L158-L376)

## Core Components
- **CredentialSetStore**: Loads a JSON file of named credential sets on demand, validates required fields based on scheme type, and reloads automatically when the file changes. Supports scheme-aware parsing with optional per-set scheme field.
- **Authentication Resolution**: Reusable seam that resolves credential sets into appropriate outbound authentication mechanisms, supporting basic, bearer, and oauth2_client_credentials schemes with fail-closed security semantics.
- **OAuth2 Token Client**: Connector-local token acquisition with memory-only caching, near-expiry refresh management, concurrent request deduplication, and structured error handling.
- **Enhanced Redaction Engine**: Applies value-pattern matches (e.g., PEM private keys, JWTs, Bearer/Basic headers, AWS access key IDs) and explicit sensitive key names to replace values with a marker. Includes comprehensive overflow protection and fail-closed behavior.
- **URL Redaction**: Specialized URL masking for query parameters and userinfo components using a shared vocabulary of secret-bearing parameter names.
- **Secret Delivery Buffer**: Ephemeral storage for one-time secret handoff with TTL expiration, owner scoping, and atomic redemption operations.
- **HTTP Connector**: Provides bounded `http.get` and `http.post` tools with strict origin validation, redirect protection, credential set integration, and response projection with header filtering.
- **Browser Connector**: Provides bounded web.* tools. It uses credential sets for filling credentials and masks secret-bearing URL query parameters and screenshot content to prevent leaks.
- **GatewayService.invoke_tool**: Orchestrates identity resolution, policy enforcement, tool dispatch, redaction, and audit logging. Redaction is applied once, at the gateway boundary, before both response and audit trail.
- **GatewaySettings**: Environment-driven configuration for redaction toggles, overflow thresholds, HTTP connectivity, secrets generation, and credential set paths.

**Section sources**
- [credential_sets.py:30-103](file://products/tool-gateway/src/tool_gateway/tools/credential_sets.py#L30-L103)
- [auth_resolution.py:69-113](file://products/tool-gateway/src/tool_gateway/tools/auth_resolution.py#L69-L113)
- [oauth_client.py:81-232](file://products/tool-gateway/src/tool_gateway/tools/oauth_client.py#L81-L232)
- [redaction.py:24-151](file://products/tool-gateway/src/tool_gateway/tools/redaction.py#L24-L151)
- [url_redaction.py:27-91](file://products/tool-gateway/src/tool_gateway/tools/url_redaction.py#L27-L91)
- [secret_delivery.py:231-282](file://products/tool-gateway/src/tool_gateway/tools/secret_delivery.py#L231-L282)
- [http_connector.py:322-699](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L322-L699)
- [browser_connector.py:174-257](file://products/tool-gateway/src/tool_gateway/tools/browser_connector.py#L174-L257)
- [config.py:200-240](file://products/tool-gateway/src/tool_gateway/core/config.py#L200-L240)

## Architecture Overview
The Tool Gateway enforces a strict execution pipeline with multiple security layers and enhanced credential masking throughout the request/response lifecycle:
- Identity and policy are resolved first.
- Tools are invoked through a registry; HTTP, browser, and secrets tools may use credential sets or policy enforcement.
- All tool results pass through comprehensive redaction before being returned or logged.
- Generated credentials are tracked with ephemeral masking knowledge to prevent leakage in any projection.
- Audit events record decisions and outcomes without leaking secrets.

```mermaid
sequenceDiagram
participant Client as "Caller"
participant GW as "GatewayService.invoke_tool"
participant POL as "PolicyEngine"
participant REG as "ToolRegistry"
participant HC as "HttpConnector"
participant CS as "CredentialSetStore"
participant AR as "Auth Resolution"
participant OC as "OAuth2 Token Client"
participant RED as "Redaction"
participant UR as "URL Redaction"
participant AUD as "AuditEmitter"
participant BUF as "Delivery Buffer"
Client->>GW : POST {tool_name, parameters}
GW->>POL : evaluate("tools : invoke")
POL-->>GW : allow/deny
alt deny
GW-->>Client : 403 denied
GW->>AUD : emit policy_decision(deny)
else allow
GW->>REG : invoke(tool_name, parameters, identity)
alt http.get/post
REG->>HC : execute(http.get/post)
HC->>CS : get(credential_set)
CS-->>HC : {scheme, fields...}
HC->>AR : resolve_outbound_auth()
alt basic/bearer
AR-->>HC : ResolvedAuth(auth, bearer_token)
else oauth2_client_credentials
AR->>OC : acquire(token_url, client_id, client_secret)
OC-->>AR : cached/fresh token
AR-->>HC : ResolvedAuth(auth, bearer_token)
end
HC->>UR : redact_secret_query(url)
HC->>RED : project_response()
HC-->>REG : ToolResult
else web.fill_credential
REG->>BC : execute(web.fill_credential)
BC->>UR : redact_secret_query(url)
BC-->>REG : ToolResult
else secrets.generate_password
REG->>SC : execute(secrets.generate_password)
SC->>BUF : stash value for one-time delivery
SC->>RED : mask_generated_value()
SC-->>REG : ToolResult (masked)
end
REG-->>GW : ToolResult
GW->>RED : redact_result()
RED-->>GW : redacted ToolResult + stats
alt overflow
GW-->>Client : error (REDACTION_OVERFLOW)
else ok
GW->>AUD : emit tool_invoked(success/error)
GW-->>Client : JSONResponse
end
end
```

**Diagram sources**
- [gateway_service.py:158-376](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L158-L376)
- [http_connector.py:368-402](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L368-L402)
- [auth_resolution.py:69-113](file://products/tool-gateway/src/tool_gateway/tools/auth_resolution.py#L69-L113)
- [oauth_client.py:123-140](file://products/tool-gateway/src/tool_gateway/tools/oauth_client.py#L123-L140)
- [url_redaction.py:49-91](file://products/tool-gateway/src/tool_gateway/tools/url_redaction.py#L49-L91)
- [redaction.py:126-151](file://products/tool-gateway/src/tool_gateway/tools/redaction.py#L126-L151)
- [secret_delivery.py:126-158](file://products/tool-gateway/src/tool_gateway/tools/secret_delivery.py#L126-L158)

## Detailed Component Analysis

### Enhanced Credential Set Architecture with Scheme-Aware Parsing

**Updated** Enhanced credential model now supports scheme-aware parsing system with optional per-set scheme field, extending beyond fixed username/password requirements while maintaining backward compatibility.

#### Scheme Vocabulary and Field Requirements
- **Supported schemes**: `basic`, `bearer`, and `oauth2_client_credentials` with distinct field requirements for each.
- **Backward compatibility**: Sets without a `scheme` field default to `basic` and parse exactly as before, ensuring existing configurations remain functional.
- **Field validation**: Each scheme has specific required fields - `basic` requires `username` and `password`, `bearer` requires `token`, and `oauth2_client_credentials` requires `token_url`, `client_id`, and `client_secret`.
- **Optional fields**: Additional fields like `scope`, `audience`, `resource`, and `client_auth` are retained when present for OAuth2 client credentials.
- **Fail-closed behavior**: Unknown schemes or missing required fields cause sets to be ignored with warnings rather than crashing the system.

#### Enhanced Loading and Validation Process
- **Lazy loading**: The store reads the file only when needed and caches until mtime changes.
- **Scheme-aware validation**: Instead of checking only `username` and `password`, the system now validates fields based on the declared scheme.
- **Field retention**: Unlike previous implementation that projected sets down to only `username`/`password`, the enhanced version retains all scheme-specific fields.
- **Error handling**: Malformed entries or unknown schemes are logged with warnings and skipped, maintaining system stability.

```mermaid
flowchart TD
Start(["Access CredentialSetStore"]) --> CheckPath{"Path configured?"}
CheckPath --> |No| ReturnNone["Return None/empty"]
CheckPath --> |Yes| Stat["stat(path)"]
Stat --> MtimeOK{"mtime == cached?"}
MtimeOK --> |Yes| UseCache["Use cached sets"]
MtimeOK --> |No| ReadFile["Read JSON file"]
ReadFile --> ValidateSchema{"Has valid schema?<br/>Required fields present?"}
ValidateSchema --> |No| Warn["Log warning, keep last good load"]
ValidateSchema --> |Yes| ParseScheme{"Parse scheme:<br/>basic/bearer/oauth2"}
ParseScheme --> ValidateFields{"Validate scheme-specific<br/>required fields"}
ValidateFields --> |Invalid| IgnoreSet["Ignore set with warning"]
ValidateFields --> |Valid| RetainFields["Retain all scheme fields"]
RetainFields --> UpdateCache["Update cache and mtime"]
UpdateCache --> ReturnSets["Return sets"]
IgnoreSet --> UpdateCache
```

**Diagram sources**
- [credential_sets.py:30-103](file://products/tool-gateway/src/tool_gateway/tools/credential_sets.py#L30-L103)
- [SPEC-068 spec.md:96-114](file://docs/specs/SPEC-068-outbound-execution-credential-schemes/spec.md#L96-L114)

**Section sources**
- [credential_sets.py:30-103](file://products/tool-gateway/src/tool_gateway/tools/credential_sets.py#L30-L103)
- [SPEC-068 spec.md:96-114](file://docs/specs/SPEC-068-outbound-execution-credential-schemes/spec.md#L96-L114)

### Reusable Outbound Authentication Resolution

**New** Complete authentication resolution seam supporting multiple schemes with fail-closed security semantics.

#### Multi-Scheme Support
- **Scheme dispatch**: Centralized resolver that routes credential sets to appropriate authentication mechanisms based on scheme type.
- **Basic authentication**: Returns `httpx.BasicAuth` instance with username/password credentials.
- **Bearer authentication**: Creates custom `BearerAuth` class that attaches `Authorization: Bearer <token>` headers.
- **OAuth2 client credentials**: Delegates to OAuth2TokenClient for token acquisition and returns bearer-authenticated requests.
- **Fail-closed errors**: All authentication failures return structured gateway errors with `CREDENTIAL_ACQUISITION_FAILED` code, never falling back to unauthenticated calls.

#### ResolvedAuth Data Structure
- **Scheme tracking**: Records which scheme was used for the current authentication.
- **HTTPX auth object**: Provides `httpx.Auth` instance for HTTP-based connectors.
- **Bearer token access**: Exposes raw token for non-HTTPX transports that need direct header manipulation.
- **Immutable design**: Frozen dataclass ensures authentication state cannot be modified after resolution.

```mermaid
flowchart TD
Input["resolve_outbound_auth(set_name, entry, token_client)"] --> GetScheme["Get scheme from entry"]
GetScheme --> BasicCheck{"scheme == 'basic'?"}
BasicCheck --> |Yes| BasicAuth["Create httpx.BasicAuth(username, password)"]
BasicCheck --> |No| BearerCheck{"scheme == 'bearer'?"}
BearerCheck --> |Yes| BearerAuth["Create BearerAuth(token)"]
BearerCheck --> |No| OAuth2Check{"scheme == 'oauth2_client_credentials'?"}
OAuth2Check --> |Yes| TokenAcquire["token_client.acquire()"]
OAuth2Check --> |No| Error["Return structured error"]
TokenAcquire --> CreateBearer["Create BearerAuth(fresh_token)"]
BasicAuth --> ReturnResolved["Return ResolvedAuth"]
BearerAuth --> ReturnResolved
CreateBearer --> ReturnResolved
Error --> ReturnError["Return (None, error_tuple)"]
```

**Diagram sources**
- [auth_resolution.py:69-113](file://products/tool-gateway/src/tool_gateway/tools/auth_resolution.py#L69-L113)

**Section sources**
- [auth_resolution.py:1-113](file://products/tool-gateway/src/tool_gateway/tools/auth_resolution.py#L1-L113)

### OAuth2 Client Credentials Implementation

**New** Complete OAuth2 client credentials token acquisition with caching, refresh management, and comprehensive error handling.

#### Token Acquisition Flow
- **Memory-only caching**: Acquired tokens live exclusively in memory, never persisted to disk or logs.
- **Near-expiry refresh**: Tokens are refreshed when within a safety margin (default 30 seconds) of expiry to prevent mid-flight expiration.
- **Concurrent request deduplication**: Per-set locks ensure only one token fetch occurs even with concurrent callers.
- **Double-check pattern**: Lock holders re-check cache after acquiring lock to avoid redundant network calls.

#### Client Authentication Variants
- **client_secret_basic**: Default variant where client ID and secret are sent via HTTP Basic authentication header.
- **client_secret_post**: Alternative variant where client credentials are included in the form body.
- **Explicit selection**: Operator must explicitly configure the variant per credential set to prevent accidental misconfiguration.

#### Optional Request Parameters
- **Scope**: Requested permissions/scopes for the access token.
- **Audience**: Target audience for the token (useful in multi-tenant environments).
- **Resource**: Resource identifier for the target service.
- **Forwarding**: Optional parameters are forwarded to the token endpoint when configured.

#### Fail-Closed Security Semantics
- **Structured errors**: All failures return `CREDENTIAL_ACQUISITION_FAILED` with descriptive messages.
- **No fallback**: Failed token acquisition never results in unauthenticated calls or fabricated tokens.
- **Safe logging**: Only failure classes and credential set names are logged, never actual secrets or tokens.
- **Timeout protection**: Configurable timeouts prevent hanging token requests.

```mermaid
sequenceDiagram
participant Caller as "Auth Resolver"
participant TC as "OAuth2TokenClient"
participant Cache as "Token Cache"
participant Endpoint as "OAuth2 Endpoint"
Caller->>TC : acquire(name, entry)
TC->>Cache : _fresh_token(name)
alt Cached & Fresh
Cache-->>TC : access_token
TC-->>Caller : (access_token, None)
else Expired or Missing
TC->>Cache : _lock_for(name)
Cache->>Cache : Double-check fresh token
alt Still Fresh
Cache-->>TC : access_token
TC-->>Caller : (access_token, None)
else Need Refresh
TC->>Endpoint : POST token_url with credentials
Endpoint-->>TC : {access_token, expires_in}
TC->>Cache : Store cached token
TC-->>Caller : (access_token, None)
end
end
```

**Diagram sources**
- [oauth_client.py:123-140](file://products/tool-gateway/src/tool_gateway/tools/oauth_client.py#L123-L140)
- [oauth_client.py:141-221](file://products/tool-gateway/src/tool_gateway/tools/oauth_client.py#L141-L221)

**Section sources**
- [oauth_client.py:1-232](file://products/tool-gateway/src/tool_gateway/tools/oauth_client.py#L1-L232)

### Reference-Based Credential Injection into Tool Invocations

**Updated** Enhanced support for scheme-aware credential sets with proper secret handling across all authentication types.

#### HTTP Connector Credential Resolution
- **Reference-only approach**: HTTP tools accept `credential_set` parameter (name only), never literal secrets.
- **Scheme-aware authentication**: Credential sets resolve to appropriate authentication mechanisms based on scheme type:
  - `basic`: HTTP Basic auth headers server-side
  - `bearer`: Authorization Bearer token headers
  - `oauth2_client_credentials`: OAuth2 client credentials flow with automatic token acquisition
- **Origin validation**: Requests must target allowlisted origins; loopback, link-local, and multicast addresses are always refused.
- **Redirect protection**: POST requests never follow redirects; GET requests validate each hop against the allowlist.
- **Secret query parameter handling**: POST URLs cannot carry secret-bearing query parameters; GET URLs mask them in responses.

#### Browser Connector Integration
- **Fill credentials**: Browser connector holds a CredentialSetStore instance and resolves named sets at fill time.
- **Scheme validation**: Browser flows require `basic` scheme sets; non-basic schemes fail closed with structured errors.
- **Parameter binding**: The web.fill_credential tool consumes a named set and injects username/password into the page via Playwright. Values are not serialized into results, snapshots, or evidence.
- **Screenshot protection**: When capturing screenshots, the connector masks filled password values in the DOM before capture to avoid leaking them in images.
- **Query parameter masking**: URLs reported in evidence have secret-bearing query parameters masked so they do not leak into results or audit trails.

```mermaid
sequenceDiagram
participant Caller as "Caller"
participant GW as "GatewayService"
participant HC as "HttpConnector"
participant CS as "CredentialSetStore"
participant AR as "Auth Resolution"
participant BA as "Basic Auth"
participant UR as "URL Redaction"
Caller->>GW : http.get {url, credential_set}
GW->>HC : execute(...)
HC->>CS : get(credential_set)
CS-->>HC : {scheme, fields...}
HC->>AR : resolve_outbound_auth()
alt basic scheme
AR->>BA : create BasicAuth(username, password)
else bearer scheme
AR->>AR : create BearerAuth(token)
else oauth2_client_credentials
AR->>AR : perform OAuth2 client credentials flow
end
HC->>UR : redact_secret_query(url)
Note over HC,BA : Credentials never leave process in plaintext
HC-->>GW : ToolResult (no secrets)
```

**Diagram sources**
- [http_connector.py:368-402](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L368-L402)
- [http_connector.py:404-506](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L404-L506)
- [url_redaction.py:49-91](file://products/tool-gateway/src/tool_gateway/tools/url_redaction.py#L49-L91)
- [credential_sets.py:47-103](file://products/tool-gateway/src/tool_gateway/tools/credential_sets.py#L47-L103)
- [auth_resolution.py:69-113](file://products/tool-gateway/src/tool_gateway/tools/auth_resolution.py#L69-L113)

**Section sources**
- [http_connector.py:322-699](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L322-L699)
- [browser_connector.py:174-257](file://products/tool-gateway/src/tool_gateway/tools/browser_connector.py#L174-L257)
- [credential_sets.py:30-103](file://products/tool-gateway/src/tool_gateway/tools/credential_sets.py#L30-L103)
- [auth_resolution.py:69-113](file://products/tool-gateway/src/tool_gateway/tools/auth_resolution.py#L69-L113)

### Generated Password Policy Enforcement

**New** Added comprehensive password generation with centralized policy enforcement.

#### CSPRNG Password Generation
- **Cryptographic randomness**: Uses Python's `secrets` module for cryptographically secure random generation, never model-invented randomness.
- **Policy-driven strength**: Enforced against a centralized `password-policy` contract that defines minimum length, required character classes, and entropy floors.
- **Hybrid policy model**: Versioned contract serves as source of truth while allowing per-deployment tightening via environment variables.
- **Validation safeguards**: Requests below policy floor are refused or raised to minimum; impossible requests fail closed with `INVALID_PARAMETERS`.

#### Password Policy Contract
- **Default policy**: Minimum 16 characters (floor 12), all four character classes required (uppercase, lowercase, digit, non-alphabetic), 64-bit entropy floor.
- **Configurable options**: Optional `exclude_ambiguous` flag for removing confusing characters like I/l/1/O/0.
- **Drift prevention**: `validate-password-policy` verify leg ensures tool implementation matches contract specifications.
- **Named policies**: Framework supports future named policies (default, strict) as additive extensions.

```mermaid
flowchart TD
Request["secrets.generate_password(length?, policy?)"] --> Validate["Validate request parameters"]
Validate --> PolicyCheck{"Check against password-policy contract"}
PolicyCheck --> |Valid| Generate["Generate using CSPRNG (secrets module)"]
PolicyCheck --> |Invalid| Error["Return INVALID_PARAMETERS"]
Generate --> Mask["Mask generated value for projections"]
Mask --> Deliver["Return masked result"]
Error --> Return["Return error response"]
```

**Diagram sources**
- [SPEC-062 spec.md:90-121](file://docs/specs/SPEC-062-secure-password-generation-and-delivery/spec.md#L90-L121)
- [SPEC-062 spec.md:122-170](file://docs/specs/SPEC-062-secure-password-generation-and-delivery/spec.md#L122-L170)

**Section sources**
- [SPEC-062 spec.md:90-170](file://docs/specs/SPEC-062-secure-password-generation-and-delivery/spec.md#L90-L170)

### One-Time Secure Delivery Mechanisms

**New** Added secure delivery mechanisms for generated passwords without plaintext exposure.

#### Portal Copy Handoff (Primary Channel)
- **Redemption-on-click**: Generated values are stored in ephemeral, single-use, TTL-bounded buffers and accessed via authenticated redemption endpoints.
- **No plaintext projection**: The actual password never enters transcripts, titles, cards, or evidence frames - only opaque delivery IDs are exposed.
- **Owner-scoped access**: Delivery handles are scoped to session owners and cannot be redeemed by other identities.
- **Single-use redemption**: Each delivery handle can only be used once, then becomes invalid.

#### Email Delivery Channel (Optional, Gated)
- **Write-tier action**: Requires `secrets:deliver` policy action plus `tools:mutate` permission.
- **Recipient allowlisting**: Configurable allowlist (`GATEWAY_EMAIL_RECIPIENT_ALLOWLIST`) with optional strict mode.
- **Mandatory approval**: Parks an action card requiring explicit approval, with prominent warnings for out-of-allowlist recipients.
- **TLS encryption**: Emails sent over TLS with no logging of secret content.

#### Delivery Buffer Architecture
- **Pluggable backends**: In-memory backend for single-replica deployments, Redis backend for multi-replica setups.
- **TTL management**: Handles expire automatically after configurable time-to-live.
- **Atomic operations**: Single-use redemption via atomic GETDEL operations in Redis backend.
- **Replica-safe design**: Mirrors existing session store patterns for consistency.

```mermaid
sequenceDiagram
participant Agent as "Agent"
participant GW as "GatewayService"
participant BUF as "Delivery Buffer"
participant PORTAL as "Portal"
participant USER as "User"
Agent->>GW : secrets.deliver(channel="portal", value)
GW->>BUF : Store value with delivery_id
BUF-->>GW : delivery_id
GW-->>Agent : ToolResult with delivery_id
Agent-->>USER : Chat shows "Copy password" button
USER->>PORTAL : Click "Copy password"
PORTAL->>GW : GET /secrets/delivery/{delivery_id}
GW->>BUF : Redeem delivery_id
BUF-->>GW : Value (single-use)
GW-->>PORTAL : Value for clipboard
PORTAL-->>USER : Value copied to clipboard
Note over BUF : Handle invalidated after redemption
```

**Diagram sources**
- [SPEC-062 spec.md:171-223](file://docs/specs/SPEC-062-secure-password-generation-and-delivery/spec.md#L171-L223)
- [ADR-0012:101-115](file://docs/adr/0012-one-time-secret-delivery-handoff.md#L101-L115)

**Section sources**
- [SPEC-062 spec.md:171-278](file://docs/specs/SPEC-062-secure-password-generation-and-delivery/spec.md#L171-L278)
- [ADR-0012:101-115](file://docs/adr/0012-one-time-secret-delivery-handoff.md#L101-L115)

### Enhanced Output Redaction System
- **Value patterns**: Detects and replaces high-confidence secret shapes such as PEM private keys, JWTs, Bearer/Basic authorization values, and AWS-style access key IDs.
- **Explicit key list**: Replaces string values under known sensitive field names (password, token, secret, api_key, etc.).
- **Overflow control**: If more than a configured fraction of the payload would be redacted, the gateway returns an error instead of leaking partial secrets.
- **Single choke point**: Redaction runs once after tool execution and before any response or audit log serialization.
- **Generated value masking**: Generated passwords are added to the secret vocabulary and masked in all projections including evidence, transcripts, titles, and cards.
- **Ephemeral masking knowledge**: Tracks generated credentials throughout the execution pipeline to ensure complete masking in all output surfaces.

```mermaid
flowchart TD
In["ToolResult"] --> ToDict["Serialize to dict"]
ToDict --> Walk["Walk nodes recursively"]
Walk --> DictNode{"dict?"}
DictNode --> |Yes| KeyCheck{"key in sensitive set<br/>and value is string?"}
KeyCheck --> |Yes| MaskKey["Replace value with marker"]
KeyCheck --> |No| RecurseChild["Recurse child"]
DictNode --> |No| ListNode{"list?"}
ListNode --> |Yes| RecurseList["Recurse items"]
ListNode --> |No| StrNode{"string?"}
StrNode --> |Yes| PatternScan["Apply value patterns"]
StrNode --> |No| Keep["Keep node"]
PatternScan --> Count["Accumulate spans/chars"]
MaskKey --> Count
RecurseChild --> Count
RecurseList --> Count
Count --> Overflow{"fraction > threshold?"}
Overflow --> |Yes| Error["Return error (REDACTION_OVERFLOW)"]
Overflow --> |No| Out["Return redacted result"]
```

**Diagram sources**
- [redaction.py:24-151](file://products/tool-gateway/src/tool_gateway/tools/redaction.py#L24-L151)
- [gateway_service.py:307-335](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L307-L335)

**Section sources**
- [redaction.py:24-151](file://products/tool-gateway/src/tool_gateway/tools/redaction.py#L24-L151)
- [gateway_service.py:307-335](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L307-L335)

### URL Secret Query Redaction
**New** Dedicated URL masking for query parameters and userinfo components.

- **Shared vocabulary**: Uses a centralized list of secret-bearing parameter names (password, token, api_key, etc.) matched case-insensitively.
- **Userinfo masking**: Masks passwords in `scheme://user:password@host` format.
- **Query parameter masking**: Replaces values of secret-bearing parameters with `***` while preserving parameter names.
- **Preservation**: Non-secret bytes are preserved exactly without re-encoding.
- **Cross-connector usage**: Both HTTP and browser connectors import this module for consistent URL masking.

```mermaid
flowchart TD
URL["Input URL"] --> Parse["Parse URL components"]
Parse --> CheckUserinfo{"Has userinfo?"}
CheckUserinfo --> |Yes| MaskUserinfo["Mask password in netloc"]
CheckUserinfo --> |No| CheckQuery["Check query params"]
MaskUserinfo --> CheckQuery
CheckQuery --> SplitQuery["Split query by &"]
SplitQuery --> ForEachParam{"For each param"}
ForEachParam --> CheckSecret{"Is param name secret?"}
CheckSecret --> |Yes| MaskValue["Replace value with ***"]
CheckSecret --> |No| KeepParam["Keep param unchanged"]
MaskValue --> Rebuild["Rebuild URL"]
KeepParam --> Rebuild
Rebuild --> Output["Masked URL"]
```

**Diagram sources**
- [url_redaction.py:49-91](file://products/tool-gateway/src/tool_gateway/tools/url_redaction.py#L49-L91)

**Section sources**
- [url_redaction.py:27-91](file://products/tool-gateway/src/tool_gateway/tools/url_redaction.py#L27-L91)
- [http_connector.py:255-303](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L255-L303)

### Access Controls and Risk Tiers
- Policy enforcement: Every invocation is evaluated against the policy bundle; mutating tools additionally require a mutate permission.
- Risk tiers: Tools declare read/write/admin risk levels; write/admin tools cannot be auto-approved and require explicit authorization.
- Browser-specific guards: Origin allowlists, flow binding, step budgets, and deviation guards ensure interactions stay within approved targets.
- HTTP-specific guards: Origin allowlists, redirect protection, and body size limits ensure safe HTTP operations.
- Secrets-specific controls: Password generation is read-tier with no confirmation; email delivery requires `secrets:deliver` action plus HITL approval.

```mermaid
classDiagram
class ToolDefinition {
+name
+description
+risk_level
+category
+parameters_schema
}
class BaseTool {
+definition
+execute(parameters, identity)
}
class HttpConnector {
+register_tools(registry)
+_validate_destination(url, allow_origins)
+_resolve_auth(credential_set)
}
class BrowserConnector {
+register_tools(registry)
+is_origin_allowed(url)
+gate_interaction(...)
}
class SecretsConnector {
+register_tools(registry)
+generate_password(length, policy)
+deliver(channel, value, recipient)
}
BaseTool <|-- HttpConnector
BaseTool <|-- BrowserConnector
BaseTool <|-- SecretsConnector
HttpConnector --> ToolDefinition : "uses"
BrowserConnector --> ToolDefinition : "uses"
SecretsConnector --> ToolDefinition : "uses"
```

**Diagram sources**
- [base.py:15-123](file://products/tool-gateway/src/tool_gateway/tools/base.py#L15-L123)
- [http_connector.py:322-360](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L322-L360)
- [browser_connector.py:315-399](file://products/tool-gateway/src/tool_gateway/tools/browser_connector.py#L315-L399)

**Section sources**
- [base.py:15-123](file://products/tool-gateway/src/tool_gateway/tools/base.py#L15-L123)
- [gateway_service.py:197-291](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L197-L291)
- [http_connector.py:100-181](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L100-L181)
- [browser_connector.py:533-698](file://products/tool-gateway/src/tool_gateway/tools/browser_connector.py#L533-L698)

### Audit Logging and Correlation
- Request correlation: A stable request ID is resolved from headers, tracing, or generated UUIDs to correlate events across services.
- Audit events: Both policy decisions and tool invocations are emitted with subject, roles, tool name, status, duration, risk level, and redaction span counts—without secrets.
- Evidence integrity: Tool results are redacted before audit emission to prevent leakage in durable logs.
- New audit types: `secret_delivered` event type tracks delivery channel and recipient without exposing secret values.

```mermaid
sequenceDiagram
participant GW as "GatewayService"
participant RC as "RequestContext"
participant AE as "AuditEmitter"
GW->>RC : resolve_request_id()
RC-->>GW : request_id
GW->>AE : emit policy_decision(deny/success)
GW->>AE : emit tool_invoked(success/error)
GW->>AE : emit secret_delivered(channel, recipient)
Note over GW,AE : No secrets in audit payloads
```

**Diagram sources**
- [request_context.py:8-35](file://products/tool-gateway/src/tool_gateway/core/request_context.py#L8-L35)
- [gateway_service.py:197-376](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L197-L376)

**Section sources**
- [request_context.py:8-35](file://products/tool-gateway/src/tool_gateway/core/request_context.py#L8-L35)
- [gateway_service.py:197-376](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L197-L376)

## Dependency Analysis
- Configuration drives behavior:
  - Redaction enabled/disabled and overflow threshold.
  - HTTP connector feature flags, origin allowlist, timeout, and credential set path.
  - Browser feature flags, origin allowlist, session limits, and credential set path.
  - Secrets connector enablement, password policy contract path, delivery buffer backend, and email configuration.
- CredentialSetStore depends on filesystem availability and JSON validity; it degrades gracefully when unreadable.
- HTTPConnector depends on origin validation, credential set resolution, and URL redaction.
- BrowserConnector depends on the skills service for flow validation, Playwright for browser automation, and URL redaction.
- SecretsConnector depends on password policy contract, delivery buffer backend, and email SMTP configuration.
- GatewayService depends on policy engine, token verifier, and audit emitter; it centralizes redaction and audit emission.

```mermaid
graph LR
CFG["GatewaySettings"] --> GW["GatewayService"]
CFG --> HC["HttpConnector"]
CFG --> BC["BrowserConnector"]
CFG --> SC["SecretsConnector"]
HC --> CS["CredentialSetStore"]
HC --> AR["Auth Resolution"]
HC --> UR["URL Redaction"]
BC --> CS
BC --> UR
SC --> PP["Password Policy"]
SC --> DB["Delivery Buffer"]
SC --> EM["Email SMTP"]
GW --> RED["Redaction"]
GW --> AUD["AuditEmitter"]
BC --> SKILLS["Skills Service"]
```

**Diagram sources**
- [config.py:200-240](file://products/tool-gateway/src/tool_gateway/core/config.py#L200-L240)
- [gateway_service.py:158-376](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L158-L376)
- [http_connector.py:322-360](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L322-L360)
- [browser_connector.py:174-257](file://products/tool-gateway/src/tool_gateway/tools/browser_connector.py#L174-L257)
- [credential_sets.py:30-103](file://products/tool-gateway/src/tool_gateway/tools/credential_sets.py#L30-L103)
- [url_redaction.py:27-91](file://products/tool-gateway/src/tool_gateway/tools/url_redaction.py#L27-L91)

**Section sources**
- [config.py:200-240](file://products/tool-gateway/src/tool_gateway/core/config.py#L200-L240)
- [gateway_service.py:158-376](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L158-L376)

## Performance Considerations
- Redaction cost: Pattern scanning and recursive traversal run once per tool result; keep payloads reasonable and tune overflow thresholds to avoid excessive masking.
- URL redaction cost: URL parsing and query parameter processing occur for every HTTP request and browser navigation; minimal overhead due to efficient string operations.
- Credential set reload: File stat and JSON parse occur only on mtime change; frequent rotations are supported without restarts.
- HTTP connection pooling: HTTP client instances are created per request but benefit from underlying connection reuse.
- Browser concurrency: Each chat session serializes interactions to avoid race conditions on shared page state.
- Password generation cost: CSPRNG generation is computationally lightweight; policy validation adds minimal overhead.
- Delivery buffer operations: Single-use redemption involves database lookups and atomic operations; designed for low-latency access.
- Ephemeral masking overhead: Tracking generated credentials adds minimal overhead during tool execution but provides comprehensive protection across all output surfaces.
- OAuth2 token caching: Memory-only token cache eliminates repeated network calls; near-expiry refresh prevents mid-flight expiration.
- Concurrent token acquisition: Per-set locks prevent thundering herd effects during token refresh cycles.

## Troubleshooting Guide
Common issues and diagnostics:
- **Credential sets file unreadable**:
  - Symptom: Warnings about unreadable files; last good load retained.
  - Action: Verify file path, permissions, and JSON structure; ensure each set has non-empty username and password.
- **Redaction overflow**:
  - Symptom: Tool invocation returns an error indicating too much of the result was redacted.
  - Action: Tighten parameters to reduce secret exposure; review tool logic to avoid returning large secret blobs.
- **HTTP origin not allowed**:
  - Symptom: HTTP requests denied due to off-allowlist origin.
  - Action: Add the target origin to `GATEWAY_HTTP_ALLOW_ORIGINS`; verify hostname normalization.
- **HTTP redirect not allowed**:
  - Symptom: POST requests refuse to follow redirects; GET requests halt on off-allowlist redirects.
  - Action: Ensure upstream services don't redirect unexpectedly; configure appropriate redirect handling.
- **Secret query parameters in HTTP URLs**:
  - Symptom: POST requests rejected with secret-bearing query parameters; GET requests mask them in responses.
  - Action: Move secrets to request bodies for POST; rely on automatic masking for GET responses.
- **Unknown credential set**:
  - Symptom: HTTP requests fail with `CREDENTIAL_SET_NOT_FOUND`.
  - Action: Verify credential set name exists in the configured file; check file path configuration.
- **Browser origin not allowed**:
  - Symptom: Navigation or interaction denied due to off-allowlist origin.
  - Action: Add the target origin to the allowlist; ensure flow binding matches the intended target.
- **Secret-bearing query parameters in browser evidence**:
  - Symptom: URLs in results/evidence contain sensitive query values.
  - Action: Ensure the connector's URL masking is active; verify that reported URLs go through the masking function.
- **Password generation policy violations**:
  - Symptom: Password generation fails with policy-related errors.
  - Action: Check password policy contract configuration; verify requested length meets minimum requirements; review character class constraints.
- **Delivery buffer exhaustion**:
  - Symptom: Delivery handles become invalid or expired.
  - Action: Check TTL configuration; verify buffer backend connectivity; ensure handles are redeemed promptly.
- **Email delivery failures**:
  - Symptom: Email delivery fails with SMTP or recipient errors.
  - Action: Verify SMTP configuration; check recipient allowlist settings; confirm `secrets:deliver` policy action is granted.
- **Secrets connector not available**:
  - Symptom: `secrets.generate_password` tool not found in discovery.
  - Action: Enable `GATEWAY_SECRETS_ENABLED=true`; verify password policy contract is accessible.
- **Password policy contract errors**:
  - Symptom: Password generation fails with policy loading errors.
  - Action: Check `GATEWAY_PASSWORD_POLICY_PATH`; verify YAML syntax and policy structure; ensure contract version is compatible.
- **Email recipient not allowed**:
  - Symptom: Email delivery blocked with `EMAIL_RECIPIENT_NOT_ALLOWED`.
  - Action: Add recipient domain to `GATEWAY_EMAIL_RECIPIENT_ALLOWLIST`; adjust strict allowlist settings.
- **Ephemeral masking issues**:
  - Symptom: Generated credentials appearing in unexpected output surfaces.
  - Action: Verify redaction is enabled and configured correctly; check that all output paths go through the redaction layer; review overflow thresholds.
- **Unknown credential scheme**:
  - Symptom: Credential sets with unknown scheme values are ignored with warnings.
  - Action: Verify scheme values are one of: `basic`, `bearer`, or `oauth2_client_credentials`; check for typos in scheme declarations.
- **Missing required fields for scheme**:
  - Symptom: Credential sets missing required fields for their declared scheme are ignored.
  - Action: Ensure `basic` sets have `username` and `password`, `bearer` sets have `token`, and `oauth2_client_credentials` sets have `token_url`, `client_id`, and `client_secret`.
- **Browser flow with non-basic scheme**:
  - Symptom: Browser credential filling fails when referencing non-basic schemes.
  - Action: Use `basic` scheme sets for browser credential filling; other schemes are not supported for web form filling.
- **OAuth2 token acquisition failures**:
  - Symptom: HTTP requests with OAuth2 credential sets fail with `CREDENTIAL_ACQUISITION_FAILED`.
  - Action: Verify token endpoint connectivity; check client credentials configuration; review token endpoint response format.
- **OAuth2 token endpoint unreachable**:
  - Symptom: Token acquisition fails with timeout or connection errors.
  - Action: Verify network connectivity to token endpoint; check firewall rules; verify DNS resolution.
- **OAuth2 token response malformed**:
  - Symptom: Token acquisition fails with JSON parsing or missing access_token errors.
  - Action: Check token endpoint response format; ensure `access_token` field is present; verify JSON structure.
- **OAuth2 client authentication variant mismatch**:
  - Symptom: Token acquisition fails with authentication errors.
  - Action: Configure correct `client_auth` variant (`client_secret_basic` or `client_secret_post`); verify server expectations.
- **OAuth2 token cache issues**:
  - Symptom: Frequent token refreshes or stale token errors.
  - Action: Check `expires_in` values in token responses; verify clock synchronization; review refresh margin configuration.

**Section sources**
- [credential_sets.py:52-103](file://products/tool-gateway/src/tool_gateway/tools/credential_sets.py#L52-L103)
- [auth_resolution.py:60-113](file://products/tool-gateway/src/tool_gateway/tools/auth_resolution.py#L60-L113)
- [oauth_client.py:141-232](file://products/tool-gateway/src/tool_gateway/tools/oauth_client.py#L141-L232)
- [redaction.py:60-73](file://products/tool-gateway/src/tool_gateway/tools/redaction.py#L60-L73)
- [gateway_service.py:307-335](file://products/tool-gateway/src/tool_gateway/services/gateway_service.py#L307-L335)
- [http_connector.py:100-181](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L100-L181)
- [browser_connector.py:174-257](file://products/tool-gateway/src/tool_gateway/tools/browser_connector.py#L174-L257)

## Conclusion
The Tool Gateway centralizes credential management and output sanitization to minimize risk through enhanced credential masking throughout the entire request/response lifecycle:
- Credentials are stored as named sets in a secret-mounted file with scheme-aware parsing and injected safely into both browser sessions and HTTP authentication mechanisms.
- Reference-based credential resolution ensures secrets never appear as literals in tool parameters or logs.
- Enhanced credential model supports multiple authentication schemes (`basic`, `bearer`, `oauth2_client_credentials`) while maintaining backward compatibility.
- Complete OAuth2 client credentials implementation provides automated token acquisition with caching, refresh management, and fail-closed security semantics.
- Reusable authentication resolution seam enables consistent credential handling across different connectors and transport types.
- Generated passwords provide cryptographically secure alternatives to manual password creation, enforced against centralized policy contracts.
- One-time secure delivery mechanisms prevent plaintext exposure through redemption-on-click and gated email channels.
- Enhanced redaction applies deterministic pattern and key-based masking to all tool outputs, with fail-closed overflow protection and comprehensive coverage.
- URL redaction provides specialized masking for query parameters and userinfo components across all connectors.
- Ephemeral masking knowledge tracks generated credentials throughout the execution pipeline to prevent any leakage in transcripts, evidence, or audit trails.
- HTTP connector adds robust origin validation, redirect protection, and response projection with header filtering.
- Policy enforcement, risk-tier gating, and audit logging provide strong access controls and traceability without leaking secrets.

## Appendices

### Example: Defining Custom Credential Sets with Schemes
- Create a JSON file with named sets supporting different authentication schemes.
- Mount the file into the gateway container and configure the credential sets path via environment.
- Reference the set name in `web.fill_credential` or HTTP tool parameters; values are injected into the respective systems but never logged or returned.
- HTTP connector supports both browser and HTTP credential sets through shared configuration.

**Example credential sets file:**
```json
{
  "inventory-app": {"username": "svc-check", "password": "..."},
  "legacy-crm": {"username": "checker", "password": "..."},
  "api-service": {"scheme": "bearer", "token": "..."},
  "oauth-service": {
    "scheme": "oauth2_client_credentials",
    "token_url": "https://auth.example.com/token",
    "client_id": "...",
    "client_secret": "...",
    "scope": "read write"
  }
}
```

**Section sources**
- [credential_sets.py:11-17](file://products/tool-gateway/src/tool_gateway/tools/credential_sets.py#L11-L17)
- [config.py:230-233](file://products/tool-gateway/src/tool_gateway/core/config.py#L230-L233)

### Example: Configuring HTTP Connector
- Enable HTTP connector via `GATEWAY_HTTP_ENABLED=true`.
- Configure allowed origins via `GATEWAY_HTTP_ALLOW_ORIGINS=http://service:8080,http://api:9090`.
- Set timeouts and size limits via `GATEWAY_HTTP_TIMEOUT_MS`, `GATEWAY_HTTP_MAX_RESPONSE_BYTES`, `GATEWAY_HTTP_MAX_REQUEST_BYTES`.
- Configure credential sets via `GATEWAY_HTTP_CREDENTIAL_SETS` or fall back to browser credential sets.

**Section sources**
- [config.py:200-240](file://products/tool-gateway/src/tool_gateway/core/config.py#L200-L240)
- [http_connector.py:322-360](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L322-L360)

### Example: Using Reference-Based Credentials in HTTP Tools
```python
# HTTP GET with basic credential set
result = await registry.invoke("http.get", {
    "url": "https://api.example.com/data",
    "credential_set": "inventory-app",
    "timeout_ms": 5000
}, identity)

# HTTP POST with bearer token credential set
result = await registry.invoke("http.post", {
    "url": "https://api.example.com/update",
    "body": {"action": "update", "value": 42},
    "credential_set": "api-service"
}, identity)

# HTTP POST with OAuth2 client credentials
result = await registry.invoke("http.post", {
    "url": "https://api.example.com/resource",
    "body": {"query": "data"},
    "credential_set": "oauth-service"
}, identity)
```

**Section sources**
- [http_connector.py:556-592](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L556-L592)
- [http_connector.py:654-698](file://products/tool-gateway/src/tool_gateway/tools/http_connector.py#L654-L698)

### Example: Generating Passwords with Policy Enforcement
```python
# Generate password with default policy
result = await registry.invoke("secrets.generate_password", {
    "length": 20,
    "exclude_ambiguous": True
}, identity)

# Generate password with custom policy override
result = await registry.invoke("secrets.generate_password", {
    "length": 24,
    "policy": "strict"
}, identity)
```

**Section sources**
- [SPEC-062 spec.md:90-121](file://docs/specs/SPEC-062-secure-password-generation-and-delivery/spec.md#L90-L121)
- [SPEC-062 spec.md:122-170](file://docs/specs/SPEC-062-secure-password-generation-and-delivery/spec.md#L122-L170)

### Example: Delivering Generated Passwords Securely
```python
# Deliver via portal copy (primary channel)
result = await registry.invoke("secrets.deliver", {
    "channel": "portal",
    "value": generated_password
}, identity)

# Deliver via email (requires policy action)
result = await registry.invoke("secrets.deliver", {
    "channel": "email",
    "value": generated_password,
    "recipient": "admin@example.com"
}, identity)
```

**Section sources**
- [SPEC-062 spec.md:171-278](file://docs/specs/SPEC-062-secure-password-generation-and-delivery/spec.md#L171-L278)

### Best Practices for Managing External System Credentials
- Store credentials in secret-mounted files; never inline values in configuration or code.
- Rotate credentials by updating the mounted file; no restart required.
- Limit HTTP origins to trusted targets and configure appropriate allowlists.
- Use reference-based credentials exclusively; never pass literal secrets in tool parameters.
- Rely on policy and risk tiers to restrict mutating actions.
- Monitor audit logs for policy decisions and tool invocations; investigate denials and redaction overflows promptly.
- Configure appropriate timeouts and size limits to prevent resource exhaustion.
- Test credential rotation procedures regularly to ensure seamless updates.
- Use generated passwords for temporary access scenarios; enforce centralized policy compliance.
- Implement proper delivery mechanisms to prevent plaintext exposure of generated secrets.
- Regularly review and update password policies to meet evolving security requirements.
- Configure email delivery channels with appropriate recipient allowlists and strict modes.
- Monitor delivery buffer capacity and TTL settings for optimal performance.
- Leverage ephemeral masking knowledge to ensure comprehensive credential protection across all output surfaces.
- Implement proper monitoring and alerting for credential-related security events.
- Use appropriate credential schemes for different authentication requirements.
- Validate credential set configurations regularly to ensure scheme compatibility.
- Test browser credential flows with basic scheme sets only.
- Monitor for unknown scheme warnings and missing required field errors.
- Configure OAuth2 token endpoints with appropriate timeouts and retry policies.
- Use explicit client authentication variants to prevent accidental misconfiguration.
- Monitor OAuth2 token cache health and refresh patterns.
- Implement proper error handling for token acquisition failures.
- Test OAuth2 flows end-to-end with mock token endpoints during development.
- Review token endpoint security configurations and access controls regularly.