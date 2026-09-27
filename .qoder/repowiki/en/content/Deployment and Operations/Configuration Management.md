# Configuration Management

<cite>
**Referenced Files in This Document**
- [kustomization.yaml](file://shared/platform-ops/gitops/dev-k8s/kustomization.yaml)
- [configmap.yaml](file://shared/platform-ops/gitops/runtime-profiles/default/configmap.yaml)
- [runtime-secrets.example.env](file://shared/platform-ops/gitops/runtime-profiles/default/runtime-secrets.example.env)
- [sync-runtime-secret.sh](file://shared/platform-ops/gitops/sync-runtime-secret.sh)
- [sync-delegation-secrets.sh](file://shared/platform-ops/gitops/sync-delegation-secrets.sh)
- [sync-execution-signing-secret.sh](file://shared/platform-ops/gitops/sync-execution-signing-secret.sh)
- [sync-sessions-db.sh](file://shared/platform-ops/gitops/sync-sessions-db.sh)
- [sync-incident-secrets.sh](file://shared/platform-ops/gitops/sync-incident-secrets.sh)
- [sync-skills-secrets.sh](file://shared/platform-ops/gitops/sync-skills-secrets.sh)
- [browser.env](file://shared/platform-ops/gitops/runtime-profiles/browser-dev/browser.env)
- [tool-gateway runtime-config.env](file://shared/platform-ops/gitops/dev-k8s/base/tool-gateway/runtime-config.env)
- [agent-platform runtime-config.env](file://shared/platform-ops/gitops/dev-k8s/base/agent-platform/runtime-config.env)
- [skills-hub runtime-config.env](file://shared/platform-ops/gitops/dev-k8s/base/skills-hub/runtime-config.env)
- [kernel_middleware.py](file://products/agent-platform/src/agent_service/services/kernel_middleware.py)
- [runtime_settings.py](file://products/agent-platform/src/agent_service/runtime_settings.py)
- [config.py](file://products/tool-gateway/src/tool_gateway/core/config.py)
- [skills_hub config.py](file://products/skills-hub/src/skills_hub/core/config.py)
- [skills_hub ingestion.py](file://products/skills-hub/src/skills_hub/services/ingestion.py)
- [secrets_connector.py](file://products/tool-gateway/src/tool_gateway/tools/secrets_connector.py)
- [secret_delivery.py](file://products/tool-gateway/src/tool_gateway/tools/secret_delivery.py)
</cite>

## Update Summary
**Changes Made**
- Added comprehensive documentation for the new `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` environment variable for enabling agent-driven context compression (SPEC-064 R-2)
- Updated configuration validation section to include trigger ratio constraints for compression functionality
- Enhanced agent platform configuration section with detailed explanation of context compression behavior and relationship to trigger ratio configuration
- Added troubleshooting guidance for compression-related startup failures
- Updated performance considerations to address context compression impact on memory usage
- Added reference to SPEC-064 agent-driven context compression feature

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
This document explains how the Luban AIOPS platform manages configuration and secrets across environments. It focuses on:
- The hierarchical configuration system that assembles a single ConfigMap named platform-runtime-config from product-scoped environment fragments under shared, agent-platform, execution-runtime, platform-gateway, tool-gateway, identity-broker, audit-service, skills-hub, and incident-service directories.
- The secret management strategy for runtime-sensitive values such as API keys, database credentials, OIDC client secrets, and delegation tokens.
- The sync scripts that provision secrets into the cluster and how they differ from non-secret ConfigMap values.
- How to change configuration without redeploying images.
- Environment-specific configuration, startup validation behavior, and troubleshooting techniques.
- Best practices for managing configuration across development, staging, and production.
- **New**: Skill composition configuration including the `SKILLS_COMPOSITION_MAX_SUB_SKILLS` operator-tunable limit for controlling the maximum number of sub-skills in compositions.
- **Updated**: Secret delivery configuration including the `GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS` environment variable for portal_copy channel TTL management in gated workflows.
- **New**: Agent-driven context compression configuration including the `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` environment variable for enabling proactive context summarization with trigger ratio validation.

## Project Structure
The configuration is assembled with Kustomize. The dev overlay defines a configMapGenerator that merges multiple env files into one ConfigMap named platform-runtime-config. Runtime profiles add additional environment fragments (for example, default, mutating-dev, browser-dev). Product deployments reference these ConfigMaps and Secrets through their deployment manifests.

```mermaid
graph TB
A["Kustomization<br/>dev-k8s/kustomization.yaml"] --> B["ConfigMap generator<br/>platform-runtime-config"]
A --> C["Runtime profile<br/>default/configmap.yaml"]
A --> D["Mutating profile env<br/>mutating-dev/mutating.env"]
A --> E["Browser profile env<br/>browser-dev/browser.env"]
B --> F["Platform services read ConfigMap at startup"]
F --> G["Skills Hub<br/>Composition Limits"]
F --> H["Tool Gateway<br/>Secret Delivery TTL"]
F --> I["Agent Platform<br/>Context Compression"]
```

**Diagram sources**
- [kustomization.yaml:9-15](file://shared/platform-ops/gitops/dev-k8s/kustomization.yaml#L9-L15)
- [configmap.yaml:1-11](file://shared/platform-ops/gitops/runtime-profiles/default/configmap.yaml#L1-L11)

**Section sources**
- [kustomization.yaml:1-22](file://shared/platform-ops/gitops/dev-k8s/kustomization.yaml#L1-L22)
- [configmap.yaml:1-11](file://shared/platform-ops/gitops/runtime-profiles/default/configmap.yaml#L1-L11)

## Core Components
- Platform runtime ConfigMap: Assembled by Kustomize from multiple env fragments. Non-secret configuration such as provider selection, model names, base URLs, feature toggles, and HTTP connector settings live here.
- Per-product runtime secrets: Stored in Kubernetes Secrets mounted as environment variables. Sensitive values such as API keys, database credentials, OIDC client secrets, and delegation tokens are managed via Secrets.
- Sync scripts: Shell utilities that generate or reuse secrets, write them into per-product runtime-secrets.env files, apply them to the cluster, and restart affected deployments.
- Environment overlays: Profiles under runtime-profiles allow environment-specific configuration without changing application code.
- **New**: Skills composition configuration: Operator-tunable limits for controlling the maximum number of sub-skills in skill compositions to prevent resource exhaustion and maintain security boundaries.
- **Updated**: Secret delivery configuration: Portal_copy channel TTL management with configurable hold periods spanning full HITL approval workflows.
- **New**: Agent-driven context compression: Opt-in feature that enables proactive context summarization before hard compression thresholds are reached, with strict trigger ratio validation.

Key responsibilities:
- Non-secret configuration: Managed via ConfigMap; changes can be applied without image rebuilds.
- Secret configuration: Managed via Secrets; provisioned by sync scripts; changes require Secret updates and workload restarts.
- **New**: Composition limits: Configurable bounds on skill composition complexity to balance functionality with resource constraints.
- **Updated**: Secret delivery TTL: Configurable hold periods for portal_copy channels to support gated workflow scenarios.
- **New**: Context compression: Opt-in agent-driven compression with trigger ratio validation to prevent premature context summarization.

**Section sources**
- [kustomization.yaml:9-15](file://shared/platform-ops/gitops/dev-k8s/kustomization.yaml#L9-L15)
- [runtime-secrets.example.env:1-57](file://shared/platform-ops/gitops/runtime-profiles/default/runtime-secrets.example.env#L1-L57)

## Architecture Overview
The platform uses a layered configuration approach:
- Base overlays define service deployments and per-service runtime-config.env files.
- Runtime profiles contribute additional environment fragments.
- Kustomize merges all env fragments into a single platform-runtime-config ConfigMap.
- Secrets are provisioned separately by sync scripts and mounted into pods.
- **New**: Skills composition limits are enforced at ingestion time through configurable bounds.
- **Updated**: Secret delivery hold TTL spans full HITL approval workflows for portal_copy channels.
- **New**: Agent-driven context compression is opt-in and validates trigger ratios against buffer constraints.

```mermaid
graph TB
subgraph "Configuration Sources"
P1["Default profile<br/>default/configmap.yaml"]
P2["Mutating profile env<br/>mutating-dev/mutating.env"]
P3["Browser profile env<br/>browser-dev/browser.env"]
P4["Skills Hub config<br/>SKILLS_COMPOSITION_MAX_SUB_SKILLS"]
P5["Tool Gateway config<br/>GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS"]
P6["Agent Platform config<br/>AGENTSCOPE_COMPRESS_CONTEXT_ENABLED"]
end
subgraph "Kustomize Assembly"
K["dev-k8s/kustomization.yaml<br/>configMapGenerator"]
end
subgraph "Cluster Objects"
CM["ConfigMap<br/>platform-runtime-config"]
S1["Secrets<br/>per-product runtime-secrets"]
end
subgraph "Services"
AG["Agent Service<br/>Context Compression"]
PG["Platform Gateway"]
TG["Tool Gateway<br/>Secret Delivery"]
IB["Identity Broker"]
AS["Audit Service"]
SH["Skills Hub<br/>Composition Validation"]
IS["Incident Service"]
end
P1 --> K
P2 --> K
P3 --> K
P4 --> K
P5 --> K
P6 --> K
K --> CM
S1 --> AG
S1 --> PG
S1 --> TG
S1 --> IB
S1 --> AS
S1 --> SH
S1 --> IS
CM --> AG
CM --> PG
CM --> TG
CM --> IB
CM --> AS
CM --> SH
CM --> IS
```

**Diagram sources**
- [kustomization.yaml:9-15](file://shared/platform-ops/gitops/dev-k8s/kustomization.yaml#L9-L15)
- [configmap.yaml:1-11](file://shared/platform-ops/gitops/runtime-profiles/default/configmap.yaml#L1-L11)

## Detailed Component Analysis

### Hierarchical ConfigMap assembly
- The Kustomization file declares a configMapGenerator that merges environment files from runtime profiles into a single ConfigMap named platform-runtime-config.
- The default profile provides a ConfigMap with generic deploy labels and provider settings.
- Additional profiles (mutating-dev, browser-dev) contribute environment fragments that are merged into the same ConfigMap.

Operational implications:
- Non-secret configuration is centralized in one ConfigMap and consumed by services at startup.
- Adding or updating environment fragments in profiles updates the ConfigMap without rebuilding images.

**Section sources**
- [kustomization.yaml:9-15](file://shared/platform-ops/gitops/dev-k8s/kustomization.yaml#L9-L15)
- [configmap.yaml:1-11](file://shared/platform-ops/gitops/runtime-profiles/default/configmap.yaml#L1-L11)

### Agent auto-allow list configuration
The agent-platform includes a sophisticated auto-allow list system that controls which tools can execute without operator confirmation. This system has two configuration surfaces:

**Primary Auto-Allow List (`AGENT_GATEWAY_TOOL_AUTO_ALLOW`):**
- **Replacement semantics**: When set, completely replaces the built-in vetted default list
- **Empty string**: Disables all auto-approval (every tool parks for confirmation)
- **Unset**: Uses the built-in vetted default list
- **Format**: Comma-separated dotted tool names (e.g., `k8s.list_pods,k8s.get_pod`)

**Additive Extra List (`AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA`):**
- **Additive semantics**: Adds tools to the resolved allow-list without restating the entire list
- **Union behavior**: Entries are unioned with either the built-in default or the replacement set
- **Opt-in pattern**: Enables adding specific tools back into auto-approval without maintaining full lists
- **Format**: Comma-separated dotted tool names (e.g., `http.get`)

**v0.39.1 Hardening Changes:**
- `http.get` was removed from the built-in default due to outbound egress security concerns
- Development clusters now use `AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA=http.get` to preserve demo behavior
- Production installations get hardened defaults where `http.get` requires explicit approval

**Security Invariants:**
- Mutating tools are never auto-approved regardless of configuration
- Read-only invariant enforced at middleware level
- Tool-gateway still enforces origin allowlists and structural refusals on every call

**Development Configuration Example:**
```bash
# Dev cluster preserves http.get auto-approval behavior
AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA=http.get

# Alternative: Replace entire default list (not recommended)
AGENT_GATEWAY_TOOL_AUTO_ALLOW=k8s.list_pods,k8s.get_pod,skills.search
```

**Production Hardened Default:**
```bash
# No auto-allow configuration - uses hardened built-in defaults
# http.get requires explicit operator approval
```

**Section sources**
- [kernel_middleware.py:71-138](file://products/agent-platform/src/agent_service/services/kernel_middleware.py#L71-L138)
- [agent-platform runtime-config.env:23-30](file://shared/platform-ops/gitops/dev-k8s/base/agent-platform/runtime-config.env#L23-L30)

### Agent-driven context compression configuration
**New Feature**: The agent-platform service now supports agent-driven context compression through SPEC-064 R-2, enabling proactive context summarization before hard compression thresholds are reached. The `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` environment variable provides operator control over this opt-in feature.

**Configuration Details:**
- **Variable**: `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED`
- **Default**: `false` (opt-in, disabled by default)
- **Source**: `runtime-config` (via Kustomize ConfigMap)
- **Validation**: Requires `AGENTSCOPE_CONTEXT_TRIGGER_RATIO > 0.2` (agentscope context_buffer_ratio); invalid combinations cause startup failure with `ValueError`
- **Purpose**: Enables the kernel agent to proactively compress its working context between tasks using the same mechanism as threshold-based compression

**Compression Behavior:**
- When enabled, the `CompressContext` tool is registered in the kernel toolkit and runs ahead of hard compression
- Fires at `trigger_ratio - context_buffer_ratio` (typically 0.6 when trigger_ratio=0.8), providing early compression before reaching hard threshold
- Reuses the existing `_compress_context_impl` mechanism, so it changes *who* triggers compression, not the mechanism itself
- State-only operation: no external network calls, no evidence events, no audit trail beyond normal session persistence
- Persists compression state via existing SPEC-017 snapshot/restore mechanism

**Security Implications:**
- Context-only operation: compression performs no infrastructure access, cannot reach network/filesystem/connectors
- Identity unchanged: compression path carries identity only via existing delegated-token contextvar
- Contract boundary unchanged: no agentscope types leak through v2 contract
- Kernel-local tool: always allowed, never parks on headless ASK gate
- No offloader wired: compression state stays in `state.summary`/`state.context`, rides SPEC-017 snapshot

**Trigger Ratio Validation:**
- Must satisfy `context_buffer_ratio < trigger_ratio` (agentscope requirement)
- With default `context_buffer_ratio = 0.2`, requires `AGENTSCOPE_CONTEXT_TRIGGER_RATIO > 0.2`
- Startup validation prevents wedge conditions at agent-build time
- Error message explicitly references `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` when validation fails

**Behavior Matrix:**
| Value | Behavior | Use Case |
|-------|----------|----------|
| `false` (default) | No agent-driven compression | Standard deployments, backward compatible |
| `true` + trigger_ratio > 0.2 | Proactive compression at 0.6 threshold | Memory-constrained environments, long sessions |
| `true` + trigger_ratio ≤ 0.2 | Startup failure with validation error | Misconfiguration prevention |

**Example Configuration:**
```bash
# Development environment - enable proactive compression
AGENTSCOPE_COMPRESS_CONTEXT_ENABLED=true
AGENTSCOPE_CONTEXT_TRIGGER_RATIO=0.8

# Production environment - conservative compression timing
AGENTSCOPE_COMPRESS_CONTEXT_ENABLED=true
AGENTSCOPE_CONTEXT_TRIGGER_RATIO=0.7

# High-memory environment - disable to avoid overhead
AGENTSCOPE_COMPRESS_CONTEXT_ENABLED=false
```

**Section sources**
- [runtime_settings.py:177-185](file://products/agent-platform/src/agent_service/runtime_settings.py#L177-L185)
- [runtime_settings.py:313-328](file://products/agent-platform/src/agent_service/runtime_settings.py#L313-L328)
- [runtime_settings.py:530-532](file://products/agent-platform/src/agent_service/runtime_settings.py#L530-L532)
- [kernel_middleware.py:105-117](file://products/agent-platform/src/agent_service/services/kernel_middleware.py#L105-L117)

### Secret management strategy
Secrets are provisioned using dedicated sync scripts. Each script handles a specific concern:
- Runtime secrets: sync-runtime-secret.sh provisions agent-platform runtime secrets from a profile-scoped runtime-secrets.env file.
- Delegation secrets: sync-delegation-secrets.sh generates or reuses a shared client secret, writes it into platform-gateway and identity-broker runtime-secrets.env files, applies the corresponding Secrets, and restarts affected deployments.
- Execution signing key: sync-execution-signing-secret.sh ensures an execution signing key exists in a Secret and restarts the agent-service to pick it up.
- Incident secrets: sync-incident-secrets.sh provisions webhook tokens and query client secrets, ensures the incidents database exists, updates per-product runtime-secrets.env files, applies Secrets, and restarts workloads.
- Skills secrets: sync-skills-secrets.sh provisions query secrets, ensures the skills database exists, updates per-product runtime-secrets.env files, applies Secrets, and restarts workloads.
- Sessions database: sync-sessions-db.sh ensures the sessions database exists and restarts agent-service.

Non-secret vs protected values:
- Non-secret values (e.g., provider selection, model names, base URLs) belong in ConfigMap fragments and are merged by Kustomize.
- Protected values (API keys, database credentials, OIDC client secrets, delegation tokens) belong in Secrets and are provisioned by sync scripts.

**Section sources**
- [sync-runtime-secret.sh:1-29](file://shared/platform-ops/gitops/sync-runtime-secret.sh#L1-L29)
- [sync-delegation-secrets.sh:1-97](file://shared/platform-ops/gitops/sync-delegation-secrets.sh#L1-L97)
- [sync-execution-signing-secret.sh:1-72](file://shared/platform-ops/gitops/sync-execution-signing-secret.sh#L1-L72)
- [sync-incident-secrets.sh:1-176](file://shared/platform-ops/gitops/sync-incident-secrets.sh#L1-L176)
- [sync-skills-secrets.sh:1-197](file://shared/platform-ops/gitops/sync-skills-secrets.sh#L1-L197)
- [sync-sessions-db.sh:1-46](file://shared/platform-ops/gitops/sync-sessions-db.sh#L1-L46)
- [runtime-secrets.example.env:1-57](file://shared/platform-ops/gitops/runtime-profiles/default/runtime-secrets.example.env#L1-L57)

### Tool-gateway HTTP connector configuration
The tool-gateway includes HTTP connector functionality that enables `http.get` and `http.post` tools for service health checks and HTTP operations. These connectors are controlled by environment variables:

**HTTP Connector Environment Variables:**
- `GATEWAY_HTTP_ENABLED`: Master switch to enable/disable HTTP connector tools (default: `false`)
- `GATEWAY_HTTP_ALLOW_ORIGINS`: Comma-separated list of allowed origins (deny-by-default when empty)
- `GATEWAY_HTTP_TIMEOUT_MS`: Per-request timeout in milliseconds (default: 10000, max: 30000)
- `GATEWAY_HTTP_MAX_RESPONSE_BYTES`: Response body size cap (default: 65536 bytes)
- `GATEWAY_HTTP_MAX_REQUEST_BYTES`: Request body size cap for POST operations (default: 4096 bytes)
- `GATEWAY_HTTP_CREDENTIAL_SETS`: Path to credential sets file (defaults to browser credential path if unset)

**Security Model:**
- HTTP connectors are disabled by default (`GATEWAY_HTTP_ENABLED=false`)
- Origin allowlist is deny-by-default (empty list blocks all requests)
- Redirects are validated against the allowlist
- Loopback, link-local, and multicast addresses are always blocked
- Credential sets must be mounted as files (no inline secrets)

**Development Configuration:**
In the browser-dev profile, HTTP connectors are enabled alongside browser tools:
```bash
GATEWAY_HTTP_ENABLED=true
GATEWAY_HTTP_ALLOW_ORIGINS=http://acme-admin:8080
# Inherits credential sets from browser configuration
```

**Updated** The browser-dev profile no longer ships the static browser-check-target app (retired by SPEC-061), so the only permitted origin is now `http://acme-admin:8080`.

**Section sources**
- [config.py:25-31](file://products/tool-gateway/src/tool_gateway/core/config.py#L25-L31)
- [config.py:201-234](file://products/tool-gateway/src/tool_gateway/core/config.py#L201-L234)
- [browser.env:16-26](file://shared/platform-ops/gitops/runtime-profiles/browser-dev/browser.env#L16-L26)
- [tool-gateway runtime-config.env:46-70](file://shared/platform-ops/gitops/dev-k8s/base/tool-gateway/runtime-config.env#L46-70)

### Browser profile configuration
The browser-dev profile serves as the browser posture profile for development environments. After SPEC-061, it no longer ships the static browser-check-target app and instead permits only the acme-admin sample application.

**Browser Profile Configuration:**
- `GATEWAY_BROWSER_ENABLED=true`: Enables browser web-check tools
- `GATEWAY_BROWSER_CDP_ENDPOINT=ws://localhost:9222`: Chromium DevTools Protocol endpoint
- `GATEWAY_BROWSER_ALLOW_ORIGINS=http://acme-admin:8080`: Single permitted origin (deny-by-default)
- `GATEWAY_BROWSER_CREDENTIAL_SETS=/etc/luban/browser-credentials/credential-sets.json`: Credential file path

**Updated** The browser-dev profile now functions purely as a posture profile, providing the sidecar NetworkPolicy and environment configuration without shipping any target applications. The static browser-check-target mock was retired in favor of the stateful acme-admin sample application.

**Section sources**
- [browser.env:1-26](file://shared/platform-ops/gitops/runtime-profiles/browser-dev/browser.env#L1-L26)
- [kustomization.yaml:1-29](file://shared/platform-ops/gitops/runtime-profiles/browser-dev/kustomization.yaml#L1-L29)

### Skills composition configuration
**New Feature**: The skills-hub service now supports skill compositions through SPEC-057, allowing operators to create runbooks that sequence multiple single-target skills. The `SKILLS_COMPOSITION_MAX_SUB_SKILLS` configuration option provides operator control over the maximum number of sub-skills allowed in a composition.

**Configuration Details:**
- **Variable**: `SKILLS_COMPOSITION_MAX_SUB_SKILLS`
- **Default**: `8`
- **Source**: `runtime-config` (via Kustomize ConfigMap)
- **Validation**: Must be an integer ≥ 1; invalid values cause startup failure with `SettingsError`
- **Purpose**: Controls the maximum number of sub-skills in a `kind: composition` skill

**Security Implications:**
- Worst-case calculation: `cap × GATEWAY_BROWSER_FLOW_MAX_STEPS` = 8 × 20 = 160 unlocked browser writes per run
- Each sub-skill remains individually signed, audited, receipted, and gated once per sub-skill
- Compositions carry no authority - each sub-skill maintains its own human-in-the-loop gate
- Prevents resource exhaustion while allowing complex multi-step workflows

**Behavior Matrix:**
| Value | Behavior | Use Case |
|-------|----------|----------|
| `8` (default) | Balanced composition complexity | Standard production deployments |
| `1-4` | Conservative limit | High-security environments |
| `5-12` | Moderate complexity | Development/staging environments |
| `13+` | Complex workflows | Specialized use cases requiring extensive sequencing |

**Example Configuration:**
```bash
# Development environment - higher limit for testing complex runbooks
SKILLS_COMPOSITION_MAX_SUB_SKILLS=12

# Production environment - conservative limit for security
SKILLS_COMPOSITION_MAX_SUB_SKILLS=8

# High-security environment - minimal composition complexity
SKILLS_COMPOSITION_MAX_SUB_SKILLS=4
```

**Section sources**
- [skills_hub config.py:161-178](file://products/skills-hub/src/skills_hub/core/config.py#L161-L178)
- [skills_hub config.py:188-191](file://products/skills_hub/src/skills_hub/core/config.py#L188-L191)
- [skills_hub config.py:211-213](file://products/skills_hub/src/skills_hub/core/config.py#L211-L213)
- [skills-hub runtime-config.env:4-8](file://shared/platform-ops/gitops/dev-k8s/base/skills-hub/runtime-config.env#L4-L8)

### Secret delivery configuration
**Updated Feature**: The tool-gateway service includes secret delivery functionality through SPEC-062, supporting one-time password generation and delivery with portal_copy channel support for gated workflows. The `GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS` configuration option provides operator control over the hold period for portal_copy deliveries.

**Configuration Details:**
- **Variable**: `GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS`
- **Default**: `900` seconds (600s HITL approval timeout + 300s redemption margin)
- **Source**: `runtime-config` (via Kustomize ConfigMap)
- **Validation**: Must be a positive integer; invalid values cause startup failure with `ValueError`
- **Purpose**: Controls the hold period for portal_copy channel deliveries to survive full HITL approval workflows

**Portal Copy Channel Behavior:**
- Portal_copy deliveries are stashed under the longer hold TTL rather than the standalone redemption window
- A password generated before a gated reset is filed remains redeemable when the reset commits and the reveal-on-commit Copy button appears
- The hold spans a full HITL approval wait (600s timeout) plus 300s redemption margin
- Standalone redemption window (`GATEWAY_SECRET_DELIVERY_TTL_SECONDS`) remains separate at 300s default

**Security Implications:**
- Hold TTL must be greater than or equal to the HITL approval timeout to ensure passwords remain available
- Multi-replica deployments should use Redis backend to persist held deliveries across restarts
- Memory backend is suitable for single-replica development but loses handles on restart
- Entry capacity (`GATEWAY_SECRET_DELIVERY_MAX_ENTRIES`) bounds memory usage

**Behavior Matrix:**
| Value | Behavior | Use Case |
|-------|----------|----------|
| `900` (default) | Full HITL approval span | Standard gated workflow support |
| `< 600` | Insufficient for full approval | May cause premature expiration during HITL |
| `> 900` | Extended hold period | Long-running approval workflows |
| `300` (standalone) | Direct redemption only | Simple copy-paste scenarios |

**Example Configuration:**
```bash
# Development environment - standard gated workflow support
GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS=900

# Production environment - extended hold for complex approvals
GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS=1200

# High-security environment - shorter hold to minimize exposure
GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS=600
```

**Backend Selection Guidance:**
- **Memory backend**: Suitable for single-replica development; holds expire on restart
- **Redis backend**: Required for multi-replica deployments; persists held deliveries across restarts
- **Startup validation**: Redis connection failure falls back to memory with recorded warning

**Section sources**
- [config.py:32-49](file://products/tool-gateway/src/tool_gateway/core/config.py#L32-L49)
- [config.py:171-179](file://products/tool-gateway/src/tool_gateway/core/config.py#L171-L179)
- [config.py:373-378](file://products/tool-gateway/src/tool_gateway/core/config.py#L373-L378)
- [secrets_connector.py:323-335](file://products/tool-gateway/src/tool_gateway/tools/secrets_connector.py#L323-L335)
- [tool-gateway runtime-config.env:84-97](file://shared/platform-ops/gitops/dev-k8s/base/tool-gateway/runtime-config.env#L84-L97)

### Environment-specific configurations
- Default profile: Provides baseline provider configuration and optional catalog entries.
- Mutating-dev profile: Adds environment-specific flags via mutating.env.
- Browser-dev profile: Adds browser-related configuration via browser.env and patches tool-gateway with a sidecar. Also enables HTTP connectors for service health checks.
- **New**: Skills composition limits can be tuned per environment based on security requirements and operational needs.
- **Updated**: Secret delivery hold TTL can be configured per environment based on HITL workflow requirements.
- **New**: Agent-driven context compression can be enabled per environment based on memory constraints and session length requirements.

To switch environments:
- Select or create a runtime profile under runtime-profiles.
- Update the profile's env files or ConfigMap.
- Apply the overlay so Kustomize regenerates platform-runtime-config.

**Section sources**
- [kustomization.yaml:1-22](file://shared/platform-ops/gitops/dev-k8s/kustomization.yaml#L1-L22)
- [configmap.yaml:1-11](file://shared/platform-ops/gitops/runtime-profiles/default/configmap.yaml#L1-L11)

### Configuration validation at service startup
- Services read configuration from the merged ConfigMap and Secrets at startup.
- Missing or invalid configuration typically causes startup failures or feature gating. For example, if required LLM provider credentials are absent, the provider is disabled and discovery may fall back to curated lists or cached data.
- Secret provisioning scripts ensure required keys exist before restarting workloads. If a required secret is missing, services will fail open or closed according to their design (for example, signing_unavailable rejection paths).
- HTTP connector validation: When `GATEWAY_HTTP_ENABLED=false`, no HTTP tools are registered. When enabled but origin allowlist is empty, all HTTP requests are denied.
- Browser connector validation: When `GATEWAY_BROWSER_ENABLED=false`, no browser tools are registered. When enabled but origin allowlist is empty, all browser navigation is denied.
- Agent auto-allow validation: Tools listed in auto-allow configuration must be read-only; mutating tools are logged as misconfiguration but remain available for HITL approval.
- **New**: Skills composition validation: Invalid `SKILLS_COMPOSITION_MAX_SUB_SKILLS` values (non-integer or < 1) cause immediate startup failure with descriptive error messages.
- **Updated**: Secret delivery validation: Both `GATEWAY_SECRET_DELIVERY_TTL_SECONDS` and `GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS` must be positive integers; invalid values cause startup failure with `ValueError("Secret delivery TTL and capacity must be positive integers")`.
- **New**: Context compression validation: When `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED=true`, requires `AGENTSCOPE_CONTEXT_TRIGGER_RATIO > 0.2`; invalid combinations cause startup failure with `ValueError` referencing the compression setting.

Operational guidance:
- Validate that all required keys are present in the relevant runtime-secrets.env files before applying.
- Use the SKIP_* environment variables in sync scripts to bypass provisioning when CI injects secrets externally.
- Verify auto-allow list composition matches expected behavior for your environment.
- **New**: Test context compression configuration with appropriate trigger ratios to ensure proper startup.
- **New**: Test composition limits during development to ensure they meet operational requirements before production deployment.
- **Updated**: Verify secret delivery TTL values are appropriate for your HITL workflow timing requirements.

[No sources needed since this section synthesizes behavior described by scripts and examples]

### Managing configuration changes without redeploying images
- Non-secret changes: Update environment fragments in runtime profiles and apply the overlay. Kustomize regenerates platform-runtime-config. Services must be restarted to pick up new ConfigMap values.
- Secret changes: Update the appropriate runtime-secrets.env file and run the corresponding sync script. The script applies the Secret and restarts affected deployments.
- HTTP connector changes: Toggle `GATEWAY_HTTP_ENABLED` and adjust timeout/size limits through ConfigMap updates without requiring image rebuilds.
- Browser configuration changes: Modify browser profile settings through ConfigMap updates without requiring image rebuilds.
- Agent auto-allow changes: Update `AGENT_GATEWAY_TOOL_AUTO_ALLOW` or `AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA` through ConfigMap updates; changes take effect on service restart.
- **New**: Skills composition limit changes: Update `SKILLS_COMPOSITION_MAX_SUB_SKILLS` through ConfigMap updates; changes take effect on skills-hub service restart.
- **Updated**: Secret delivery hold TTL changes: Update `GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS` through ConfigMap updates; changes take effect on tool-gateway service restart.
- **New**: Context compression changes: Update `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` and `AGENTSCOPE_CONTEXT_TRIGGER_RATIO` through ConfigMap updates; changes take effect on agent-service restart with proper trigger ratio validation.

Best practice:
- Keep non-secret configuration in profile env files and ConfigMaps.
- Keep sensitive configuration in Secrets and manage them exclusively via sync scripts.
- Test HTTP and browser connector configurations in development profiles before promoting to production.
- Use additive auto-allow patterns (`_EXTRA` variables) for environment-specific opt-ins rather than replacing entire default lists.
- **New**: Test context compression with appropriate trigger ratios in development to validate memory savings before production deployment.
- **New**: Ensure trigger ratio validation passes before enabling compression in production environments.
- **New**: Test composition limits thoroughly in development environments to validate workflow complexity requirements before production deployment.
- **Updated**: Test secret delivery hold TTL values to ensure they accommodate your HITL approval workflow timing before production deployment.

**Section sources**
- [kustomization.yaml:9-15](file://shared/platform-ops/gitops/dev-k8s/kustomization.yaml#L9-L15)
- [sync-runtime-secret.sh:1-29](file://shared/platform-ops/gitops/sync-runtime-secret.sh#L1-L29)
- [sync-delegation-secrets.sh:1-97](file://shared/platform-ops/gitops/sync-delegation-secrets.sh#L1-L97)
- [sync-incident-secrets.sh:1-176](file://shared/platform-ops/gitops/sync-incident-secrets.sh#L1-L176)
- [sync-skills-secrets.sh:1-197](file://shared/platform-ops/gitops/sync-skills-secrets.sh#L1-L197)

### Common configuration scenarios

#### Switching the active LLM provider
- Set provider selection and model metadata in the default profile ConfigMap fragment.
- Provide provider API keys in the runtime-secrets.example.env template and copy to the active profile's runtime-secrets.env.
- Apply the overlay and restart services to load the new provider configuration.

**Section sources**
- [configmap.yaml:1-11](file://shared/platform-ops/gitops/runtime-profiles/default/configmap.yaml#L1-L11)
- [runtime-secrets.example.env:1-57](file://shared/platform-ops/gitops/runtime-profiles/default/runtime-secrets.example.env#L1-L57)

#### Enabling token delegation between platform-gateway and identity-broker
- Run the delegation secret sync script to generate or reuse a shared client secret.
- The script updates both platform-gateway and identity-broker runtime-secrets.env files, applies Secrets, and restarts deployments.
- After rollout, the gateway can exchange user tokens for delegated tokens used by downstream services.

**Section sources**
- [sync-delegation-secrets.sh:1-97](file://shared/platform-ops/gitops/sync-delegation-secrets.sh#L1-L97)

#### Provisioning execution request signing
- Run the execution signing secret sync script. It reuses an existing key if present or generates a new one.
- The script applies the Secret and restarts agent-service so signed executions can proceed.

**Section sources**
- [sync-execution-signing-secret.sh:1-72](file://shared/platform-ops/gitops/sync-execution-signing-secret.sh#L1-L72)

#### Enabling incident intake and query
- Run the incident secrets sync script to provision webhook tokens and query client secrets.
- The script ensures the incidents database exists, updates per-product runtime-secrets.env files, applies Secrets, and restarts workloads.
- Point Alertmanager at the incident-service webhook endpoint with the provided bearer token.

**Section sources**
- [sync-incident-secrets.sh:1-176](file://shared/platform-ops/gitops/sync-incident-secrets.sh#L1-L176)

#### Enabling skills retrieval
- Run the skills secrets sync script to provision query secrets and optionally a Git PAT for remote skill sources.
- The script ensures the skills database exists, updates per-product runtime-secrets.env files, applies Secrets, and restarts workloads.

**Section sources**
- [sync-skills-secrets.sh:1-197](file://shared/platform-ops/gitops/sync-skills-secrets.sh#L1-L197)

#### Enabling HTTP service health checks
- Enable HTTP connectors by setting `GATEWAY_HTTP_ENABLED=true` in the browser-dev profile or create a custom profile.
- Configure `GATEWAY_HTTP_ALLOW_ORIGINS` with permitted service endpoints.
- Adjust timeout and size limits based on your service requirements.
- Optionally configure `GATEWAY_HTTP_CREDENTIAL_SETS` for authenticated endpoints.
- Apply the overlay and restart tool-gateway to register HTTP tools.

**Section sources**
- [browser.env:16-26](file://shared/platform-ops/gitops/runtime-profiles/browser-dev/browser.env#L16-L26)
- [tool-gateway runtime-config.env:46-70](file://shared/platform-ops/gitops/dev-k8s/base/tool-gateway/runtime-config.env#L46-70)

#### Configuring browser web-check tools
- Enable browser tools by setting `GATEWAY_BROWSER_ENABLED=true` in the browser-dev profile.
- Configure `GATEWAY_BROWSER_CDP_ENDPOINT` to point to a reachable Chromium instance.
- Set `GATEWAY_BROWSER_ALLOW_ORIGINS` to permit the acme-admin sample application.
- Mount credential sets file for authenticated browser interactions.
- Apply the overlay and restart tool-gateway to register browser tools.

**Updated** The browser-dev profile now only permits the acme-admin origin after retiring the static browser-check-target app.

**Section sources**
- [browser.env:1-26](file://shared/platform-ops/gitops/runtime-profiles/browser-dev/browser.env#L1-L26)
- [kustomization.yaml:1-29](file://shared/platform-ops/gitops/runtime-profiles/browser-dev/kustomization.yaml#L1-L29)

#### Opting in specific tools to auto-approval
- Use `AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA` for additive opt-in of specific tools without restating the entire default list.
- Use `AGENT_GATEWAY_TOOL_AUTO_ALLOW` for complete replacement of the default allow-list (advanced use cases).
- Both variables support comma-separated dotted tool names with automatic normalization.
- Mutating tools cannot be auto-approved regardless of configuration.

**Development Pattern (Dev Cluster):**
```bash
# Preserve http.get auto-approval behavior for demos
AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA=http.get
```

**Production Pattern (Hardened Default):**
```bash
# No auto-allow configuration - uses hardened built-in defaults
# All tools require explicit operator approval
```

**Section sources**
- [kernel_middleware.py:117-138](file://products/agent-platform/src/agent_service/services/kernel_middleware.py#L117-L138)
- [agent-platform runtime-config.env:23-30](file://shared/platform-ops/gitops/dev-k8s/base/agent-platform/runtime-config.env#L23-L30)

#### Tuning skill composition limits
**New Scenario**: Configure the maximum number of sub-skills allowed in skill compositions based on your environment's security requirements and operational needs.

**Development Environment (Higher Complexity):**
```bash
# Allow more complex runbooks for testing
SKILLS_COMPOSITION_MAX_SUB_SKILLS=12
```

**Production Environment (Balanced Security):**
```bash
# Standard production limit
SKILLS_COMPOSITION_MAX_SUB_SKILLS=8
```

**High-Security Environment (Conservative Limit):**
```bash
# Minimal composition complexity for high-security deployments
SKILLS_COMPOSITION_MAX_SUB_SKILLS=4
```

**Validation Testing:**
```bash
# Test composition validation with current limit
echo "Testing composition with $(cat /proc/self/environ | tr '\0' '\n' | grep SKILLS_COMPOSITION_MAX_SUB_SKILLS)"
```

**Section sources**
- [skills-hub runtime-config.env:4-8](file://shared/platform-ops/gitops/dev-k8s/base/skills-hub/runtime-config.env#L4-L8)
- [skills_hub config.py:161-178](file://products/skills_hub/src/skills_hub/core/config.py#L161-L178)

#### Configuring secret delivery hold TTL for gated workflows
**Updated Scenario**: Configure the portal_copy channel hold TTL to support gated workflow scenarios where passwords are generated before HITL approval completes.

**Development Environment (Standard Support):**
```bash
# Standard gated workflow support with full HITL approval span
GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS=900
```

**Production Environment (Extended Approval):**
```bash
# Extended hold for complex approval workflows
GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS=1200
```

**High-Security Environment (Minimal Exposure):**
```bash
# Shorter hold to minimize secret exposure window
GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS=600
```

**Multi-Replica Deployment:**
```bash
# Use Redis backend for persistence across restarts
GATEWAY_SECRET_DELIVERY_BACKEND=redis
GATEWAY_SECRET_DELIVERY_REDIS_HOST=redis
GATEWAY_SECRET_DELIVERY_REDIS_PORT=6379
GATEWAY_SECRET_DELIVERY_REDIS_DB=2
GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS=900
```

**Validation Testing:**
```bash
# Test secret delivery configuration with current hold TTL
echo "Testing secret delivery with $(cat /proc/self/environ | tr '\0' '\n' | grep GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS)"
```

**Section sources**
- [tool-gateway runtime-config.env:84-97](file://shared/platform-ops/gitops/dev-k8s/base/tool-gateway/runtime-config.env#L84-L97)
- [config.py:373-378](file://products/tool-gateway/src/tool_gateway/core/config.py#L373-L378)

#### Enabling agent-driven context compression
**New Scenario**: Enable proactive context compression to reduce memory usage in long-running agent sessions by summarizing context before reaching hard compression thresholds.

**Development Environment (Aggressive Compression):**
```bash
# Enable compression with standard trigger ratio
AGENTSCOPE_COMPRESS_CONTEXT_ENABLED=true
AGENTSCOPE_CONTEXT_TRIGGER_RATIO=0.8
```

**Production Environment (Conservative Compression):**
```bash
# Enable compression with earlier trigger for memory efficiency
AGENTSCOPE_COMPRESS_CONTEXT_ENABLED=true
AGENTSCOPE_CONTEXT_TRIGGER_RATIO=0.7
```

**High-Memory Environment (Disable Compression):**
```bash
# Disable compression to avoid overhead in memory-rich environments
AGENTSCOPE_COMPRESS_CONTEXT_ENABLED=false
```

**Validation Testing:**
```bash
# Test compression configuration with current trigger ratio
echo "Testing compression with $(cat /proc/self/environ | tr '\0' '\n' | grep AGENTSCOPE_COMPRESS_CONTEXT_ENABLED)"
echo "Trigger ratio: $(cat /proc/self/environ | tr '\0' '\n' | grep AGENTSCOPE_CONTEXT_TRIGGER_RATIO)"
```

**Section sources**
- [runtime_settings.py:177-185](file://products/agent-platform/src/agent_service/runtime_settings.py#L177-L185)
- [runtime_settings.py:313-328](file://products/agent-platform/src/agent_service/runtime_settings.py#L313-L328)

### Conceptual overview
```mermaid
flowchart TD
Start(["Operator updates configuration"]) --> Type{"Is value secret?"}
Type --> |No| UpdateCM["Update profile env or ConfigMap fragment"]
Type --> |Yes| UpdateSecret["Update runtime-secrets.env and run sync script"]
UpdateCM --> Apply["Apply Kustomize overlay"]
UpdateSecret --> Apply
Apply --> Restart["Restart affected deployments"]
Restart --> Verify["Verify services start and endpoints respond"]
Verify --> CompositionCheck{"Skills composition limit?"}
CompositionCheck --> |Yes| ValidateLimits["Validate SKILLS_COMPOSITION_MAX_SUB_SKILLS"]
CompositionCheck --> |No| SecretDeliveryCheck{"Secret delivery TTL?"}
SecretDeliveryCheck --> |Yes| ValidateTTL["Validate GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS"]
SecretDeliveryCheck --> |No| CompressionCheck{"Context compression?"}
CompressionCheck --> |Yes| ValidateCompression["Validate AGENTSCOPE_COMPRESS_CONTEXT_ENABLED + trigger ratio"]
CompressionCheck --> |No| Complete["Configuration complete"]
ValidateLimits --> Complete
ValidateTTL --> Complete
ValidateCompression --> Complete
```

[No sources needed since this diagram shows conceptual workflow, not actual code structure]

## Dependency Analysis
The sync scripts coordinate dependencies across services and databases:
- Delegation secrets link platform-gateway and identity-broker via a shared client secret.
- Incident secrets link incident-service with callers (platform-gateway, tool-gateway, agent-service) via a shared query secret and a webhook token.
- Skills secrets link skills-hub with callers (tool-gateway, platform-gateway, agent-service) via a shared query secret.
- Execution signing links agent-service to a signing key stored in a Secret.
- Session store migration depends on Postgres being available and the sessions database existing.
- HTTP connectors depend on configured origin allowlists and optional credential sets.
- Browser connectors depend on CDP endpoint availability and configured origin allowlists.
- Agent auto-allow list depends on tool definitions being available at toolkit construction time.
- **New**: Skills composition limits depend on proper validation of `SKILLS_COMPOSITION_MAX_SUB_SKILLS` during service startup.
- **Updated**: Secret delivery hold TTL depends on proper validation of `GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS` during service startup and appropriate backend selection for multi-replica deployments.
- **New**: Context compression depends on proper validation of trigger ratio constraints relative to buffer ratio during service startup.

```mermaid
graph LR
PGW["Platform Gateway"] --> IB["Identity Broker"]
PGW --> TG["Tool Gateway<br/>Secret Delivery"]
PGW --> IS["Incident Service"]
TG --> IS
TG --> SH["Skills Hub<br/>Composition Limits"]
TG --> HTTP["HTTP Connectors"]
TG --> BROWSER["Browser Connectors"]
TG --> SECRET["Secret Delivery<br/>Hold TTL"]
AG["Agent Service<br/>Context Compression"] --> IS
AG --> SH
AG --> EXEC["Execution Runtime"]
AG --> AUTOALLOW["Auto-Allow List"]
AG --> COMPRESS["Context Compression<br/>Trigger Ratio Validation"]
IS --> DBI["Postgres 'incidents'"]
SH --> DBS["Postgres 'skills'"]
SH --> LIMITS["Composition Limits<br/>SKILLS_COMPOSITION_MAX_SUB_SKILLS"]
AG --> DBA["Postgres 'sessions'"]
HTTP --> External["External Services"]
BROWSER --> ACME["Acme Admin Sample"]
AUTOALLOW --> TOOLS["Gateway Tools"]
LIMITS --> VALIDATION["Ingestion Validation"]
SECRET --> BUFFER["Delivery Buffer<br/>Memory/Redis"]
COMPRESS --> TRIGGER["Trigger Ratio<br/>Buffer Validation"]
```

**Diagram sources**
- [sync-delegation-secrets.sh:1-97](file://shared/platform-ops/gitops/sync-delegation-secrets.sh#L1-L97)
- [sync-incident-secrets.sh:1-176](file://shared/platform-ops/gitops/sync-incident-secrets.sh#L1-L176)
- [sync-skills-secrets.sh:1-197](file://shared/platform-ops/gitops/sync-skills-secrets.sh#L1-L197)
- [sync-execution-signing-secret.sh:1-72](file://shared/platform-ops/gitops/sync-execution-signing-secret.sh#L1-L72)
- [sync-sessions-db.sh:1-46](file://shared/platform-ops/gitops/sync-sessions-db.sh#L1-L46)
- [kernel_middleware.py:117-138](file://products/agent-platform/src/agent_service/services/kernel_middleware.py#L117-L138)
- [skills_hub config.py:161-178](file://products/skills_hub/src/skills_hub/core/config.py#L161-L178)
- [config.py:373-378](file://products/tool-gateway/src/tool_gateway/core/config.py#L373-L378)
- [runtime_settings.py:313-328](file://products/agent-platform/src/agent_service/runtime_settings.py#L313-L328)

**Section sources**
- [sync-delegation-secrets.sh:1-97](file://shared/platform-ops/gitops/sync-delegation-secrets.sh#L1-L97)
- [sync-incident-secrets.sh:1-176](file://shared/platform-ops/gitops/sync-incident-secrets.sh#L1-L176)
- [sync-skills-secrets.sh:1-197](file://shared/platform-ops/gitops/sync-skills-secrets.sh#L1-L197)
- [sync-execution-signing-secret.sh:1-72](file://shared/platform-ops/gitops/sync-execution-signing-secret.sh#L1-L72)
- [sync-sessions-db.sh:1-46](file://shared/platform-ops/gitops/sync-sessions-db.sh#L1-L46)

## Performance Considerations
- Prefer ConfigMap-based configuration for non-secret values to avoid frequent Secret rotations.
- Batch configuration changes per environment to minimize rollout cycles.
- Use deterministic model pinning where possible to reduce live discovery overhead.
- Ensure database prerequisites exist before restarting services to avoid repeated restart loops.
- Configure appropriate HTTP timeout and size limits to prevent resource exhaustion.
- Monitor HTTP connector usage to tune timeout and size parameters based on actual service response patterns.
- Browser connector performance depends on CDP endpoint responsiveness and session management settings.
- Auto-allow list resolution occurs at service startup; frequent changes require service restarts.
- **New**: Skills composition limits directly impact memory usage and processing time; higher limits increase resource consumption proportionally.
- **New**: Composition validation occurs during skill ingestion; excessive sub-skill counts can slow down sync operations.
- **New**: Consider the worst-case scenario: `SKILLS_COMPOSITION_MAX_SUB_SKILLS × GATEWAY_BROWSER_FLOW_MAX_STEPS` for resource planning.
- **Updated**: Secret delivery hold TTL impacts memory usage in the delivery buffer; longer hold periods retain secrets longer in memory.
- **Updated**: Multi-replica deployments require Redis backend for secret delivery to persist held values across restarts.
- **Updated**: Consider the relationship between `GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS` and `GATEWAY_SECRET_DELIVERY_MAX_ENTRIES` for capacity planning.
- **New**: Context compression reduces memory usage in long-running sessions by proactively summarizing context; enable in memory-constrained environments.
- **New**: Context compression adds CPU overhead for summarization operations; monitor agent performance when enabling compression.
- **New**: Trigger ratio affects compression frequency; lower ratios trigger compression earlier but may result in more aggressive summarization.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
Common issues and resolutions:
- Missing runtime profile secret file: The runtime secret sync script requires a profile-scoped runtime-secrets.env file. Copy the example file and fill in values before running the script.
- Skipped provisioning in CI: Some scripts honor SKIP_* flags to skip provisioning when secrets are injected externally. Adjust flags accordingly.
- Database not found: Scripts for sessions, incidents, and skills check for Postgres and create databases idempotently. If Postgres is not deployed yet, deploy the overlay first.
- Stale configuration after update: After applying ConfigMap or Secret changes, restart affected deployments to pick up new values.
- Delegation chain broken: Re-run the delegation secret sync script to regenerate or reuse the shared client secret and restart platform-gateway and identity-broker.
- Execution signing unavailable: Re-run the execution signing secret sync script to ensure the signing key exists and restart agent-service.
- HTTP connector not working: Verify `GATEWAY_HTTP_ENABLED=true`, check origin allowlist configuration, and ensure target services are reachable.
- HTTP requests timing out: Increase `GATEWAY_HTTP_TIMEOUT_MS` for slow services or investigate network connectivity issues.
- HTTP responses too large: Adjust `GATEWAY_HTTP_MAX_RESPONSE_BYTES` if legitimate responses exceed the default limit.
- Browser connector not working: Verify `GATEWAY_BROWSER_ENABLED=true`, check CDP endpoint connectivity, and ensure origin allowlist includes acme-admin.
- Browser navigation denied: Check that `GATEWAY_BROWSER_ALLOW_ORIGINS` includes `http://acme-admin:8080` and that the acme-admin sample is deployed.
- Tool auto-approval not working: Verify auto-allow list configuration and check that tools are read-only; mutating tools cannot be auto-approved.
- Unexpected tool parking: Check if tool is in the correct auto-allow list (built-in default vs. extra list) and verify environment-specific overrides.
- **New**: Skills composition validation failed: Check `SKILLS_COMPOSITION_MAX_SUB_SKILLS` value and ensure it's a valid integer ≥ 1. Review error messages for specific validation failures.
- **New**: Composition rejected during ingestion: Verify that the composition doesn't exceed the configured `SKILLS_COMPOSITION_MAX_SUB_SKILLS` limit. Check for duplicate sub-skill IDs or invalid references.
- **New**: Skills-hub startup failure: Inspect logs for `SettingsError` related to `SKILLS_COMPOSITION_MAX_SUB_SKILLS` parsing or validation.
- **Updated**: Secret delivery TTL validation failed: Check `GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS` and `GATEWAY_SECRET_DELIVERY_TTL_SECONDS` values and ensure they are positive integers. Review startup error messages for specific validation failures.
- **Updated**: Portal copy delivery expired prematurely: Verify that `GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS` is sufficient to span your HITL approval workflow duration. Consider increasing the hold TTL if approvals take longer than expected.
- **Updated**: Multi-replica secret delivery issues: Ensure Redis backend is configured for multi-replica deployments to persist held deliveries across restarts. Check Redis connectivity and authentication.
- **Updated**: Secret delivery buffer capacity exceeded: Monitor `GATEWAY_SECRET_DELIVERY_MAX_ENTRIES` and increase if you're experiencing eviction of held deliveries. Check for leaked delivery handles in long-running processes.
- **New**: Context compression startup failure: Check `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` and `AGENTSCOPE_CONTEXT_TRIGGER_RATIO` values. Ensure trigger ratio is greater than 0.2 (buffer ratio). Review startup error messages for specific validation failures.
- **New**: Context compression not triggering: Verify that compression is enabled and trigger ratio is properly configured. Check agent logs for compression activity and memory usage patterns.
- **New**: Excessive compression overhead: Consider adjusting trigger ratio or disabling compression if CPU overhead is too high. Monitor agent performance metrics.

**Updated** After SPEC-061, the browser-dev profile no longer includes the static browser-check-target app, so browser navigation is only permitted to the acme-admin sample application.

**Updated** v0.39.1 hardening removed `http.get` from built-in defaults; development clusters use `AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA=http.get` to preserve demo behavior while production gets hardened defaults.

Verification steps:
- Confirm the platform-runtime-config ConfigMap contains expected keys.
- Confirm per-product Secrets contain required keys.
- Check rollout status for affected deployments after applying changes.
- Test HTTP connector endpoints directly to verify reachability and response sizes.
- Verify browser connectivity to acme-admin sample through the CDP endpoint.
- Check agent-service logs for auto-allow list resolution and tool registration.
- Verify tool auto-approval behavior matches expected environment posture.
- **New**: Verify skills-hub logs for composition limit validation and successful ingestion of compositions.
- **New**: Test composition creation with various sub-skill counts to validate limit enforcement.
- **Updated**: Verify tool-gateway logs for secret delivery TTL validation and successful portal copy delivery handling.
- **Updated**: Test secret delivery flows with various hold TTL values to validate portal copy channel behavior.
- **New**: Verify agent-service logs for context compression activation and trigger ratio validation.
- **New**: Monitor agent memory usage patterns to validate compression effectiveness.

**Section sources**
- [sync-runtime-secret.sh:1-29](file://shared/platform-ops/gitops/sync-runtime-secret.sh#L1-L29)
- [sync-delegation-secrets.sh:1-97](file://shared/platform-ops/gitops/sync-delegation-secrets.sh#L1-L97)
- [sync-execution-signing-secret.sh:1-72](file://shared/platform-ops/gitops/sync-execution-signing-secret.sh#L1-L72)
- [sync-incident-secrets.sh:1-176](file://shared/platform-ops/gitops/sync-incident-secrets.sh#L1-L176)
- [sync-skills-secrets.sh:1-197](file://shared/platform-ops/gitops/sync-skills-secrets.sh#L1-L197)
- [sync-sessions-db.sh:1-46](file://shared/platform-ops/gitops/sync-sessions-db.sh#L1-L46)

## Conclusion
Luban's configuration system separates non-secret and secret concerns:
- Non-secret configuration is assembled into a single ConfigMap via Kustomize from environment fragments across runtime profiles.
- Secrets are provisioned by targeted sync scripts that update per-product runtime-secrets.env files, apply Kubernetes Secrets, and restart workloads.
- Environment-specific behavior is achieved through runtime profiles and overlays without rebuilding images.
- HTTP connector configuration provides flexible service health checking capabilities with security controls.
- Browser connector configuration enables web application testing through Chromium automation with strict origin controls.
- Agent auto-allow list configuration supports both hardened defaults and environment-specific opt-ins through additive patterns.
- **New**: Skills composition configuration provides operator control over composition complexity through the `SKILLS_COMPOSITION_MAX_SUB_SKILLS` knob, balancing functionality with security and resource constraints.
- **Updated**: Secret delivery configuration provides operator control over portal_copy channel hold periods through the `GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS` knob, supporting gated workflow scenarios with configurable TTL validation.
- **New**: Agent-driven context compression configuration provides operator control over proactive context summarization through the `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` knob, with strict trigger ratio validation to ensure proper compression timing.
- Following the documented procedures ensures consistent, auditable, and recoverable configuration management across development, staging, and production.

**Updated** The retirement of browser-check-target per SPEC-061 simplifies the browser configuration surface while maintaining full functionality through the stateful acme-admin sample application. The addition of `AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA` provides more granular control over tool auto-approval while maintaining security-hardened defaults. **New**: The introduction of `SKILLS_COMPOSITION_MAX_SUB_SKILLS` enables fine-grained control over skill composition complexity, supporting diverse operational requirements from high-security environments to development scenarios. **Updated**: The addition of `GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS` enables precise control over portal_copy channel TTL management, supporting gated workflow scenarios with robust validation and flexible backend options. **New**: The addition of `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` enables proactive context compression for memory optimization in long-running agent sessions, with comprehensive validation to prevent misconfiguration.

[No sources needed since this section summarizes without analyzing specific files]

## Appendices

### Quick reference: Sync scripts and responsibilities
- sync-runtime-secret.sh: Provisions agent-platform runtime secrets from a profile-scoped env file.
- sync-delegation-secrets.sh: Provisions shared delegation secret for platform-gateway and identity-broker.
- sync-execution-signing-secret.sh: Provisions execution signing key for agent-service.
- sync-incident-secrets.sh: Provisions incident webhook and query secrets and ensures incidents database.
- sync-skills-secrets.sh: Provisions skills query secrets and ensures skills database.
- sync-sessions-db.sh: Ensures sessions database exists and restarts agent-service.

**Section sources**
- [sync-runtime-secret.sh:1-29](file://shared/platform-ops/gitops/sync-runtime-secret.sh#L1-L29)
- [sync-delegation-secrets.sh:1-97](file://shared/platform-ops/gitops/sync-delegation-secrets.sh#L1-L97)
- [sync-execution-signing-secret.sh:1-72](file://shared/platform-ops/gitops/sync-execution-signing-secret.sh#L1-L72)
- [sync-incident-secrets.sh:1-176](file://shared/platform-ops/gitops/sync-incident-secrets.sh#L1-L176)
- [sync-skills-secrets.sh:1-197](file://shared/platform-ops/gitops/sync-skills-secrets.sh#L1-L197)
- [sync-sessions-db.sh:1-46](file://shared/platform-ops/gitops/sync-sessions-db.sh#L1-L46)

### HTTP Connector Configuration Reference
**Environment Variables:**
- `GATEWAY_HTTP_ENABLED`: Enable/disable HTTP connector (default: false)
- `GATEWAY_HTTP_ALLOW_ORIGINS`: Comma-separated origin allowlist (deny-by-default)
- `GATEWAY_HTTP_TIMEOUT_MS`: Request timeout in ms (default: 10000, max: 30000)
- `GATEWAY_HTTP_MAX_RESPONSE_BYTES`: Response size cap (default: 65536)
- `GATEWAY_HTTP_MAX_REQUEST_BYTES`: Request body size cap (default: 4096)
- `GATEWAY_HTTP_CREDENTIAL_SETS`: Credential file path (defaults to browser path)

**Security Features:**
- Deny-by-default origin policy
- Redirect validation against allowlist
- Blocked loopback/link-local/multicast addresses
- File-based credential management only

**Section sources**
- [config.py:25-31](file://products/tool-gateway/src/tool_gateway/core/config.py#L25-L31)
- [config.py:201-234](file://products/tool-gateway/src/tool_gateway/core/config.py#L201-L234)
- [browser.env:16-26](file://shared/platform-ops/gitops/runtime-profiles/browser-dev/browser.env#L16-L26)

### Browser Connector Configuration Reference
**Environment Variables:**
- `GATEWAY_BROWSER_ENABLED`: Enable/disable browser connector (default: false)
- `GATEWAY_BROWSER_CDP_ENDPOINT`: Chromium DevTools Protocol endpoint (default: ws://localhost:9222)
- `GATEWAY_BROWSER_ALLOW_ORIGINS`: Comma-separated origin allowlist (deny-by-default)
- `GATEWAY_BROWSER_SESSION_TTL_SECONDS`: Browser session TTL (default: 600)
- `GATEWAY_BROWSER_MAX_SESSIONS`: Maximum concurrent browser sessions (default: 4)
- `GATEWAY_BROWSER_FLOW_MAX_STEPS`: Maximum steps per browser flow (default: 20)
- `GATEWAY_BROWSER_SCREENSHOT_MAX_BYTES`: Screenshot size cap (default: 65536)
- `GATEWAY_BROWSER_UPLOAD_DIR`: Directory for browser uploads (default: /tmp/browser-uploads)
- `GATEWAY_BROWSER_CREDENTIAL_SETS`: Credential file path

**Security Features:**
- Deny-by-default origin policy
- CDP endpoint validation
- Session management with TTL and limits
- File-based credential management only

**Updated** The browser-dev profile now only permits the acme-admin origin after retiring the static browser-check-target app per SPEC-061.

**Section sources**
- [config.py:17-24](file://products/tool-gateway/src/tool_gateway/core/config.py#L17-L24)
- [config.py:72-80](file://products/tool-gateway/src/tool_gateway/core/config.py#L72-L80)
- [browser.env:1-15](file://shared/platform-ops/gitops/runtime-profiles/browser-dev/browser.env#L1-L15)

### Agent Auto-Allow List Configuration Reference
**Environment Variables:**
- `AGENT_GATEWAY_TOOL_AUTO_ALLOW`: Replacement allow-list (comma-separated dotted tool names)
- `AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA`: Additive allow-list (comma-separated dotted tool names)

**Behavior Matrix:**
| `AUTO_ALLOW` | `AUTO_ALLOW_EXTRA` | Resolved Behavior |
|---|---|---|
| unset | unset | Built-in hardened defaults (no `http.get`) |
| unset | `http.get` | Defaults ∪ `{http_get}` |
| `k8s.get_pod` | `http.get` | `{k8s_get_pod, http_get}` |
| "" (empty) | unset | Nothing auto-approved |
| "" (empty) | `http.get` | `{http_get}` |

**Security Invariants:**
- Mutating tools are never auto-approved regardless of configuration
- Read-only invariant enforced at middleware level
- Tool-gateway still enforces origin allowlists and structural refusals
- Names normalized to sanitized form (dots → underscores)

**Development Pattern:**
```bash
# Dev cluster preserves http.get auto-approval for demos
AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA=http.get
```

**Production Pattern:**
```bash
# Hardened defaults - all tools require explicit approval
# No auto-allow configuration
```

**Section sources**
- [kernel_middleware.py:117-138](file://products/agent-platform/src/agent_service/services/kernel_middleware.py#L117-L138)
- [agent-platform runtime-config.env:23-30](file://shared/platform-ops/gitops/dev-k8s/base/agent-platform/runtime-config.env#L23-L30)

### Skills Composition Configuration Reference
**New Feature**: Skill composition configuration for SPEC-057 runbooks.

**Environment Variables:**
- `SKILLS_COMPOSITION_MAX_SUB_SKILLS`: Maximum number of sub-skills in compositions (default: 8)

**Configuration Options:**
| Value Range | Environment | Security Level | Resource Impact |
|-------------|-------------|----------------|-----------------|
| 1-4 | High-security production | Maximum security | Minimal resource usage |
| 5-8 | Standard production | Balanced security | Moderate resource usage |
| 9-12 | Development/staging | Lower security | Higher resource usage |
| 13+ | Specialized use cases | Custom security | Significant resource usage |

**Security Implications:**
- Worst-case calculation: `cap × GATEWAY_BROWSER_FLOW_MAX_STEPS` = cap × 20 unlocked browser writes/run
- Each sub-skill remains individually signed, audited, receipted, and gated
- Compositions carry no authority - each sub-skill maintains its own gate
- Prevents resource exhaustion while allowing complex workflows

**Validation Rules:**
- Must be an integer ≥ 1
- Invalid values cause immediate startup failure with `SettingsError`
- During ingestion, compositions exceeding the limit are rejected with descriptive error messages

**Example Configuration:**
```bash
# Development environment - higher limit for testing
SKILLS_COMPOSITION_MAX_SUB_SKILLS=12

# Production environment - balanced security
SKILLS_COMPOSITION_MAX_SUB_SKILLS=8

# High-security environment - conservative limit  
SKILLS_COMPOSITION_MAX_SUB_SKILLS=4
```

**Section sources**
- [skills_hub config.py:161-178](file://products/skills_hub/src/skills_hub/core/config.py#L161-L178)
- [skills_hub config.py:188-191](file://products/skills_hub/src/skills_hub/core/config.py#L188-L191)
- [skills_hub config.py:211-213](file://products/skills_hub/src/skills_hub/core/config.py#L211-L213)
- [skills-hub runtime-config.env:4-8](file://shared/platform-ops/gitops/dev-k8s/base/skills-hub/runtime-config.env#L4-L8)

### Secret Delivery Configuration Reference
**Updated Feature**: Secret delivery configuration for SPEC-062 secure password generation and delivery.

**Environment Variables:**
- `GATEWAY_SECRETS_ENABLED`: Enable/disable secret delivery tools (default: false)
- `GATEWAY_SECRET_DELIVERY_BACKEND`: Backend type - `memory` or `redis` (default: memory)
- `GATEWAY_SECRET_DELIVERY_TTL_SECONDS`: Standalone redemption window (default: 300)
- `GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS`: Portal copy hold TTL (default: 900)
- `GATEWAY_SECRET_DELIVERY_MAX_ENTRIES`: In-memory capacity (default: 256)
- `GATEWAY_SECRET_DELIVERY_REDIS_HOST`: Redis host (default: 127.0.0.1)
- `GATEWAY_SECRET_DELIVERY_REDIS_PORT`: Redis port (default: 6379)
- `GATEWAY_SECRET_DELIVERY_REDIS_DB`: Redis database index (default: 2)

**Configuration Options:**
| Variable | Default | Purpose | Validation |
|----------|---------|---------|------------|
| `GATEWAY_SECRET_DELIVERY_TTL_SECONDS` | 300 | Standalone redemption window | Positive integer |
| `GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS` | 900 | Portal copy hold TTL | Positive integer |
| `GATEWAY_SECRET_DELIVERY_MAX_ENTRIES` | 256 | Buffer capacity | Positive integer |
| `GATEWAY_SECRET_DELIVERY_BACKEND` | memory | Storage backend | memory or redis |

**Portal Copy Channel Behavior:**
- Portal copy deliveries use the longer hold TTL rather than standalone TTL
- Hold TTL spans full HITL approval workflows (600s timeout + 300s margin)
- Passwords generated before gated resets remain redeemable after commit
- Single-use redemption with owner scope preservation

**Backend Selection Guidance:**
- **Memory backend**: Single-replica development; ephemeral storage
- **Redis backend**: Multi-replica production; persistent storage across restarts
- **Fallback behavior**: Redis connection failure falls back to memory with warning

**Validation Rules:**
- Both TTL values must be positive integers
- Invalid values cause immediate startup failure with `ValueError`
- Redis backend requires accessible Redis instance
- Entry capacity bounds memory usage with oldest-expiring eviction

**Example Configuration:**
```bash
# Development environment - standard gated workflow support
GATEWAY_SECRET_DELIVERY_BACKEND=memory
GATEWAY_SECRET_DELIVERY_TTL_SECONDS=300
GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS=900
GATEWAY_SECRET_DELIVERY_MAX_ENTRIES=256

# Production environment - multi-replica with Redis
GATEWAY_SECRET_DELIVERY_BACKEND=redis
GATEWAY_SECRET_DELIVERY_REDIS_HOST=redis
GATEWAY_SECRET_DELIVERY_REDIS_PORT=6379
GATEWAY_SECRET_DELIVERY_REDIS_DB=2
GATEWAY_SECRET_DELIVERY_TTL_SECONDS=300
GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS=1200
GATEWAY_SECRET_DELIVERY_MAX_ENTRIES=512
```

**Section sources**
- [config.py:32-49](file://products/tool-gateway/src/tool_gateway/core/config.py#L32-L49)
- [config.py:171-179](file://products/tool-gateway/src/tool_gateway/core/config.py#L171-L179)
- [config.py:373-378](file://products/tool-gateway/src/tool_gateway/core/config.py#L373-L378)
- [secrets_connector.py:323-335](file://products/tool-gateway/src/tool_gateway/tools/secrets_connector.py#L323-L335)
- [tool-gateway runtime-config.env:84-97](file://shared/platform-ops/gitops/dev-k8s/base/tool-gateway/runtime-config.env#L84-L97)

### Agent-Driven Context Compression Configuration Reference
**New Feature**: Agent-driven context compression configuration for SPEC-064 R-2 proactive context summarization.

**Environment Variables:**
- `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED`: Enable/disable agent-driven compression (default: false)
- `AGENTSCOPE_CONTEXT_TRIGGER_RATIO`: Context compression trigger ratio (default: 0.8)

**Configuration Options:**
| Variable | Default | Purpose | Validation |
|----------|---------|---------|------------|
| `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` | false | Enable agent-driven compression | Boolean |
| `AGENTSCOPE_CONTEXT_TRIGGER_RATIO` | 0.8 | Context compression trigger | Float in (0, 0.9) |

**Compression Behavior:**
- Opt-in feature that registers `CompressContext` tool in kernel toolkit
- Fires at `trigger_ratio - context_buffer_ratio` (typically 0.6 when trigger_ratio=0.8)
- Reuses existing `_compress_context_impl` mechanism for summarization
- State-only operation: no external network calls, no evidence events
- Persists via existing SPEC-017 snapshot/restore mechanism

**Validation Rules:**
- When enabled, requires `AGENTSCOPE_CONTEXT_TRIGGER_RATIO > 0.2` (buffer ratio)
- Invalid trigger ratios cause startup failure with `ValueError`
- Error message explicitly references `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED`
- Context-only operation: no execution surface, no identity changes

**Example Configuration:**
```bash
# Development environment - enable proactive compression
AGENTSCOPE_COMPRESS_CONTEXT_ENABLED=true
AGENTSCOPE_CONTEXT_TRIGGER_RATIO=0.8

# Production environment - conservative compression timing
AGENTSCOPE_COMPRESS_CONTEXT_ENABLED=true
AGENTSCOPE_CONTEXT_TRIGGER_RATIO=0.7

# High-memory environment - disable to avoid overhead
AGENTSCOPE_COMPRESS_CONTEXT_ENABLED=false
```

**Security Implications:**
- Context-only: compression performs no infrastructure access
- Identity unchanged: uses existing delegated-token contextvar
- Contract boundary unchanged: no agentscope types leak through v2 contract
- Kernel-local tool: always allowed, never parks on headless ASK gate
- No offloader wired: compression state stays in agent state

**Section sources**
- [runtime_settings.py:177-185](file://products/agent-platform/src/agent_service/runtime_settings.py#L177-L185)
- [runtime_settings.py:313-328](file://products/agent-platform/src/agent_service/runtime_settings.py#L313-L328)
- [runtime_settings.py:530-532](file://products/agent-platform/src/agent_service/runtime_settings.py#L530-L532)
- [kernel_middleware.py:105-117](file://products/agent-platform/src/agent_service/services/kernel_middleware.py#L105-L117)