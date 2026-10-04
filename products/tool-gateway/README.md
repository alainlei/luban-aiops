# Tool Gateway

## Purpose

`tool-gateway` is the standardized tool and connector access layer for the platform.

It is responsible for:

- connector normalization
- tool integration through native connectors
- Kubernetes and observability connectors
- collaboration and ticketing connectors
- stable tool contracts and execution metadata

Since SPEC-010 (per ADR-0005) this product is the tool service only: the
portal-facing edge (token verification for portal sessions, chat/session
proxying, token delegation) lives in [platform-gateway](../platform-gateway/README.md).
Callers of this service are other platform services — `agent-platform` with
delegated tokens (`aud = tool-gateway`) per ADR-0004 — never the portal directly.

The boundary definitions live in the workspace model: [workspace-model.md](../../docs/workspace/workspace-model.md).

## Approved execution boundary (SPEC-063)

Execution-runtime, not this gateway, owns the durable single-use dispatch claim.
The gateway preserves the original `x-request-id` and accepts an execution ID
header for correlation only; neither header grants permission. Existing delegated
identity, policy, risk tiers, origin checks, and target credentials remain enforced.
Direct gateway callers are outside the approved-worker duplicate guarantee.

Tool success is a tool report, not proof of the target's business outcome; an
upstream HTTP error or partial effect must still be investigated. Missing audit
events are inconclusive. Owner-only secret redemption remains destructive even
for a wrong-owner GET (unavailable/404); owner-scoped discard is different and
cannot be used by a wrong owner to delete a handle. Recovery metadata never
contains a password or delivery handle and never triggers delivery.

## Ownership

Recommended owner:

- integrations or platform connectors team

## Current Scope

This project covers:

- connector abstraction and normalization
- REST tool discovery and invocation for trusted platform callers
- read-only and bounded-action connector pathways
- connector execution metadata and health reporting

MCP-backed connectors and selective standalone toolset extraction remain under
assessment, not shipped or approved implementation scope. The 2026-09-23
[use-case assessment](../../docs/workspace/mcp-exposure-spike.md) recommended
retaining native connectors until a concrete need justified a pilot; that reopen
trigger is now **met** — operations has named three concrete external targets
(Ansible runbooks, ServiceNow ITSM ticket handling, Windows UI automation for
desktop-application / Windows-service health checks). The current direction is
captured in the [MCP-ingestion memo](../../docs/workspace/mcp-ingestion-spike.md):
tool-gateway becomes the MCP *client* of external servers (an ingestion connector
*beneath* the gateway, reusing the `BaseTool` / `ToolRegistry` seam) while Luban
retains policy, approval, redaction, evidence, and audit; the kernel never becomes
an independent MCP client. This is inbound consumption, **not** external exposure
of tool-gateway or Luban workflows (that separate concern stays parked and
de-numbered — the `SPEC-066` slot it was once earmarked for was taken by
skill-retrieval-ranking-fidelity). The memo authorizes no implementation,
pilot, ADR, or spec — each target pilot is separately approved.

Current implementation artifacts:

- `pyproject.toml`
- `Dockerfile`
- `src/tool_gateway/app.py`
- `src/tool_gateway/api/routes/` (`health`, `tools`)
- `src/tool_gateway/core/`
- `src/tool_gateway/services/`
- `src/tool_gateway/tools/`

Current implementation status:

- verifies bearer tokens locally via JWKS (no per-request network call to identity-broker)
- validates the `iss` claim against `IDENTITY_TOKEN_ISSUER` and the `aud` claim against `GATEWAY_TOKEN_AUDIENCE`; rejects expired/malformed/wrong-audience tokens with `401`
- when auth is optional and no token is present, injects a synthetic dev identity (logged as `synthetic: true`)
- enforces deny-by-default authorization on the tool actions (`tools:list`, `tools:invoke`, `tools:mutate`) against the shared versioned role→action policy bundle (the same bundle platform-gateway loads); denials return a structured `403` and are audit-logged
- loads the policy bundle from `GATEWAY_POLICY_PATH`, falling back to a packaged default kept in sync with `shared/shared-contracts`
- provides a tool execution framework (`src/tool_gateway/tools/`) with a `ToolRegistry`, `BaseTool` abstraction, and structured evidence envelope (SPEC-007)
- ships a Kubernetes connector (`k8s.list_pods`, `k8s.get_pod`, `k8s.get_events`, `k8s.get_pod_logs`, plus the bounded mutating `k8s.delete_pod`) using `kubernetes-client/python`; tools carry a risk tier (`read`/`write`/`admin`), and write/admin tools register only when `GATEWAY_MUTATING_TOOLS_ENABLED=true` and invoke under the deny-by-default `tools:mutate` action (SPEC-021)
- ships an Elastic observability connector (`elastic.search_logs`, `elastic.get_service_health`, `elastic.get_active_alerts`) using the `elasticsearch` Python client; lazy-initialized, feature-gated by `GATEWAY_ELASTIC_ENABLED` (SPEC-011)
- ships a skills connector (`skills.search`, `skills.get`, `skills.list`) against the `skills-hub` service with Basic-auth httpx transport, 10s timeout, and structured error mapping (404 → `SKILL_NOT_FOUND`, unreachable → `TOOL_EXECUTION_ERROR`); registered only when `GATEWAY_SKILLS_SERVICE_URL` is set (SPEC-014)
- ships an incidents connector (`incidents.list`, `incidents.get`) against the `incident-service` service with the same Basic-auth httpx transport and error-mapping pattern (404 → `INCIDENT_NOT_FOUND`, unreachable → `TOOL_EXECUTION_ERROR`); registered only when `GATEWAY_INCIDENTS_SERVICE_URL` is set; read-only by design — no mutating incident tool exists (SPEC-015)
- ships a browser connector (nine read-tier tools — `web.navigate`, `web.snapshot`, `web.screenshot`, `web.fill_credential`, `web.extract`, `web.wait_for`, `web.hover`, `web.scroll`, `web.switch_frame`; six write-tier tools — `web.click`, `web.type`, `web.select`, `web.press_key`, `web.upload_file`, `web.evaluate`) for bounded web-application checks against a sidecar browser over CDP (Playwright `connect_over_cdp`; the gateway image ships the Playwright library only — no browser binary); off-by-default via `GATEWAY_BROWSER_ENABLED`, navigation deny-by-default via `GATEWAY_BROWSER_ALLOW_ORIGINS`, per-chat-session browser contexts (keyed by a trusted chat-session correlation handle, subject fallback) with idle TTL and cap eviction, skill-bound flows (`web_target`/`risk_class`) with a deviation guard and one HITL gate per write-class flow, and platform-managed credential sets that never surface in results (SPEC-049/SPEC-050)
- exposes `GET /api/v2/tools` (tool discovery, gated by `tools:list`) and `POST /api/v2/tools/invoke` (tool execution gated by `tools:invoke` for read tools and additionally by `tools:mutate` for write/admin tools); both derive identity and authorization solely from the verified token — any identity in a request body is never trusted (the one body field the gateway reads is the optional `session_id` chat-session correlation handle, injected only by trusted internal callers and carrying no authority, SPEC-049)
- redacts credential-shaped spans (JWTs, `Bearer`/`Basic` values, PEM private keys, key-list fields such as `token`/`password`/`api_key`) from every tool result at the single invoke choke point before both the response and the audit log; when the redacted fraction exceeds `GATEWAY_REDACTION_OVERFLOW_FRACTION` the output is withheld with a `REDACTION_OVERFLOW` error (fail-closed, SPEC-009)
- forwards `tool_invoked` audit events (including policy-denied invocations, post-redaction) to `audit-service` via a fire-and-forget emitter when `GATEWAY_AUDIT_SERVICE_URL` is set; unreachability degrades to log-only auditing and never blocks the invoke path (SPEC-013)

Current runtime environment knobs (tool-scoped; the portal-facing `PLATFORM_GATEWAY_*` keys live in platform-gateway):

- `IDENTITY_SERVICE_URL`
  - identity-broker endpoint; defaults to the in-cluster service DNS name
- `IDENTITY_JWKS_URL`
  - JWKS endpoint for local token verification; defaults to `http://identity-service:8000/.well-known/jwks.json`
- `IDENTITY_JWKS_CACHE_SECONDS`
  - JWKS cache refresh interval; defaults to `300`
- `IDENTITY_TOKEN_ISSUER`
  - expected `iss` claim value; defaults to `luban-identity-broker`
- `GATEWAY_TOKEN_AUDIENCE`
  - expected `aud` claim value enforced on inbound (delegated) tokens; defaults to `tool-gateway`
- `GATEWAY_REQUIRE_AUTH`
  - when `true`, tool routes require a valid bearer token; defaults to `true` (set `false` explicitly for local development without SSO)
- `GATEWAY_DEV_USER`
  - synthetic identity username when auth is optional and no token is present; defaults to `dev.operator`
- `GATEWAY_POLICY_PATH`
  - path to the action-authorization policy bundle (YAML); when unset, the packaged default bundle is used; a configured-but-invalid path fails readiness rather than falling back
- `GATEWAY_K8S_ENABLED`
  - when `true`, registers the Kubernetes connector; defaults to `false`
- `GATEWAY_MUTATING_TOOLS_ENABLED`
  - risk-tier admission gate (SPEC-021): when `true`, write/admin risk tools (currently `k8s.delete_pod`, the six write-tier `web.*` interaction tools, `http.post`, and `secrets.deliver`) register; while `false` (default) they are absent from discovery and invoke fails closed with `TOOL_NOT_FOUND`
- `GATEWAY_K8S_NAMESPACE`
  - default namespace for K8s tool operations; when unset, tools use the `namespace` parameter or fall back to `default`
- `GATEWAY_REDACTION_ENABLED`
  - master switch for tool-output redaction; defaults to `true`; the `false` setting is a dev-debugging opt-out only
- `GATEWAY_REDACTION_OVERFLOW_FRACTION`
  - redacted-character fraction above which tool output is withheld with `REDACTION_OVERFLOW`; defaults to `0.2`
- `GATEWAY_HOST`, `GATEWAY_PORT`
  - HTTP bind host/port; the port parser ignores Kubernetes service-link values like `tcp://IP:PORT`
- `GATEWAY_ELASTIC_ENABLED`
  - when `true`, registers the Elastic observability connector; defaults to `false`
- `GATEWAY_ELASTIC_URL`
  - Elastic cluster URL (e.g. `https://elasticsearch:9200`); required when `GATEWAY_ELASTIC_ENABLED=true`
- `GATEWAY_ELASTIC_API_KEY`
  - API key for Elastic authentication; preferred over basic auth when set
- `GATEWAY_ELASTIC_USERNAME`, `GATEWAY_ELASTIC_PASSWORD`
  - basic auth credentials for Elastic; used when `GATEWAY_ELASTIC_API_KEY` is not set
- `GATEWAY_ELASTIC_VERIFY_TLS`
  - when `true`, verifies TLS certificates on the Elastic connection; defaults to `true`
- `GATEWAY_ELASTIC_ALERTS_INDEX`
  - index pattern for active alerts queries; defaults to `alerts-*`
- `GATEWAY_AUDIT_SERVICE_URL`
  - audit-service ingest URL; empty (default) keeps log-only auditing
- `GATEWAY_AUDIT_CLIENT_ID`
  - client id used to authenticate audit ingest; defaults to `tool-gateway`
- `GATEWAY_AUDIT_CLIENT_SECRET`
  - audit ingest credential; must match the entry in the audit-service's `AUDIT_INGEST_CLIENTS` registry
- `GATEWAY_SKILLS_SERVICE_URL`
  - skills-hub base URL (e.g. `http://skills-hub:8000`); empty (default) leaves the skills connector unregistered
- `GATEWAY_SKILLS_CLIENT_ID`
  - client id used to authenticate skills queries; defaults to `tool-gateway`
- `GATEWAY_SKILLS_CLIENT_SECRET`
  - skills query credential; must match the entry in the skills-hub's `SKILLS_QUERY_CLIENTS` registry
- `GATEWAY_INCIDENTS_SERVICE_URL`
  - incident-service base URL (e.g. `http://incident-service:8000`); empty (default) leaves the incidents connector unregistered
- `GATEWAY_INCIDENTS_CLIENT_ID`
  - client id used to authenticate incidents queries; defaults to `tool-gateway`
- `GATEWAY_INCIDENTS_CLIENT_SECRET`
  - incidents query credential; must match the entry in the incident-service's `INCIDENT_QUERY_CLIENTS` registry
- `GATEWAY_BROWSER_ENABLED`
  - when `true`, registers the browser connector and connects to the CDP endpoint at startup; defaults to `false` (SPEC-049)
- `GATEWAY_BROWSER_CDP_ENDPOINT`
  - Chrome DevTools Protocol websocket endpoint of the browser sidecar; defaults to `ws://localhost:9222`. A bare `ws://`/`wss://` endpoint (no path) is dialed as its `http(s)://` DevTools discovery base so Playwright resolves `/json/version` for the real browser websocket; a full `ws://.../devtools/browser/<id>` URL passes through verbatim
- `GATEWAY_BROWSER_ALLOW_ORIGINS`
  - comma-separated origin allowlist (`scheme://host[:port]`); deny-by-default — an empty list (default) refuses every navigation, and redirect landings are re-checked server-side
- `GATEWAY_BROWSER_SESSION_TTL`
  - idle seconds before a chat session's browser context is swept; defaults to `600`
- `GATEWAY_BROWSER_MAX_SESSIONS`
  - session-pool cap with oldest-idle eviction; defaults to `4`
- `GATEWAY_BROWSER_FLOW_MAX_STEPS`
  - interaction step budget per bound flow; exhaustion denies further interactions; defaults to `20`
- `GATEWAY_BROWSER_CREDENTIAL_SETS`
  - path to a secret-mounted JSON file mapping credential-set names to `{"username": ..., "password": ...}`; empty (default) leaves `web.fill_credential` failing closed; values flow only into Playwright fills and are masked in snapshots
- `GATEWAY_BROWSER_SCREENSHOT_MAX_BYTES`
  - byte cap for base64 JPEG screenshots; the connector compresses (quality loop, then clip shrink) to fit and errors when it cannot; defaults to `65536`
- `OTEL_ENABLED`
  - master switch for the OTLP push pipeline (traces + metrics); defaults to `false`; when disabled, the `/metrics` surface is unaffected
- `OTEL_EXPORTER_OTLP_ENDPOINT`
  - OTLP collector URL used when `OTEL_ENABLED=true` (e.g. Elastic APM endpoint); unused otherwise
- `OTEL_SERVICE_NAME`
  - logical service name reported to the collector; defaults to the gateway's metadata name

Observability surface (see `SPEC-005` and `shared/shared-contracts/observability-conventions.md`):

- `GET /metrics` — always-on Prometheus exposition endpoint (auth-exempt, policy-exempt), reporting standard HTTP RED metrics (`http_requests_total{method,handler,status}`, `http_request_duration_seconds{method,handler}`) plus `gateway_policy_decisions_total{action,decision}`, `gateway_token_verification_total{result}` (valid | invalid | expired | missing), `gateway_tool_redacted_spans_total{tool}` (credential spans redacted from tool results, SPEC-009), and `audit_emits_total{result}` (audit-event delivery attempts to audit-service, SPEC-013)
- opt-in OTLP push via `opentelemetry-instrumentation-fastapi` + `opentelemetry-exporter-otlp` when `OTEL_ENABLED=true`; fail-open — an unreachable collector drops telemetry without affecting requests
- `x-request-id` remains the log/portal correlation key; when OTel tracing is active it equals the W3C `trace_id`

## Expected Integration Points

- `agent-platform` for tool invocation requests (delegated bearer tokens)
- `identity-broker` JWKS for local token verification
- `execution-runtime` for approved bounded-action adapters
- external systems such as Kubernetes, observability, and ticketing platforms
- `shared/shared-contracts` for tool request and response schemas

## Boundary

This project does not own approval logic, session orchestration, portal-facing
routes, or operator-facing UI flows. Portal traffic terminates at
platform-gateway.
