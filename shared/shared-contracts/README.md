# Shared Contracts

## Purpose

`shared-contracts` contains the cross-project contracts that keep the workspace integrated without tight coupling.

Typical contents include:

- API schemas
- event schemas
- policy request and response models
- approval payloads
- audit record schemas

## Ownership

Recommended owner:

- platform architecture or core platform team

## Current Scope

This module covers:

- shared API schemas
- event and streaming payloads
- policy, approval, execution, and audit models
- versioned contracts consumed across workspace products

Current implementation artifacts (`schemas/` holds 33 versioned JSON Schemas — the directory itself is the authoritative inventory; grouped by domain below):

- **Portal/gateway chat (v1):** `chat-request`, `chat-response`, `chat-confirm`, `session`, `stream-event`, `health-response`, `identity-context`
- **Agent-service (v2, platform-owned):** `agent-chat-request`, `agent-chat-response`, `agent-stream-event`, `agent-session`, `agent-session-list`, `agent-runtime-metadata`, `agent-health`
- **Identity:** `identity-token` (JWT claim set issued by identity-broker)
- **Policy (v1):** `policy-rule` (action-authorization rule), `policy-decision` (decision object), `policy-matrix` (effective permission matrix)
- **Tool execution (v1):** `tool-invocation` (request envelope), `tool-result` (result evidence envelope)
- **Execution-runtime (SPEC-038/063):** `execution-request`, `execution-receipt`, `execution-observation`, `execution-recovery`, `execution-handoff-response`
- **Audit:** `audit-event`, `audit-summary`
- **Incidents (SPEC-015):** `incident`, `triage-report`
- **Skills (SPEC-014):** `skill`
- **Model catalog (SPEC-026/027):** `model-catalog`
- **Operations documents (SPEC-039):** `operation-document`
- **Session evidence:** `session-evidence`
- `policies/policy-default.yaml` (default action-authorization bundle, v1)
- `observability-conventions.md` (metrics naming, OTel switch semantics, correlation bridging)

## Agent-Service Contract Conventions (v2)

The `agent-*` schemas define the platform-owned boundary between `tool-gateway` and `agent-platform` (see `ADR-0003`).

Header conventions (required on all v2 requests):

- `X-User-ID`: the authenticated or resolved user identifier; the agent-service uses this for session ownership
- `x-request-id`: correlation identifier shared across portal, gateway, and runtime for tracing

Design rules:

- identity travels in headers, never in request bodies
- response envelopes do not expose framework-specific types (no AgentScope `Msg`, `payload`, or event internals)
- the `content` field (v2) replaces the v1 `response` field for naming consistency with streaming `delta` terminology
- stream events use `type` (v2) instead of `event` (v1) to avoid collision with the SSE `event:` field name

## Identity Token Conventions

The `identity-token.schema.json` documents the JWT claim set issued by `identity-broker` and verified locally by `tool-gateway` via JWKS (RFC 7517). This schema is for documentation and contract alignment — the token is transported as a compact JWT string, not a JSON body.

Verification model:

- identity-broker signs with RSA-256 and publishes the public key at `/.well-known/jwks.json`
- the gateway fetches and caches the JWKS (no per-request network call)
- the `iss` claim is always validated against `IDENTITY_TOKEN_ISSUER`
- the `username` claim becomes the `X-User-ID` header forwarded to downstream services

## Policy Contract Conventions (v1)

The `policy-*` schemas and `policies/policy-default.yaml` define the first enforceable slice of the Tier-1 policy design (`docs/agentic-aiops-platform/policy-specification.md`), scoped to the `action_authz` domain with `allow`, `deny`, and `require_approval` outcomes.

Action naming convention:

- `<resource>:<verb>` for resource operations (e.g. `session:create`, `session:read`)
- a bare noun for the primary conversational surface (`chat`)

Evaluation semantics (implemented by both gateways, each over its own action vocabulary):

- deny by default: no matching rule yields `deny`
- precedence: `deny` > `require_approval` > `allow`; higher `priority` wins within an outcome; disabled rules are ignored
- the decision object carries `decision`, `matched_rule_ids`, and `reason`

Rollout controls (SPEC-048): `policy-default.yaml` is the single canonical bundle — edits happen there only, with a `version` bump, and ride `make sync-policy` to the gateway packaged copies and the dev-k8s ConfigMap source. `policies/policy-scenarios.yaml` records the expected outcome for every granted (role, action) pair and is enforced by `make verify`; `make policy-diff CANDIDATE=<bundle>` reports per-(role, action) outcome transitions at review time. Each gateway fingerprints the loaded bundle (SHA-256) on its readiness and matrix surfaces so a deployment can be confirmed against the canonical file. The full procedure is the Policy Bundle Rollout runbook in `docs/guides/configuration-reference.md`.

`policy-center` is currently a stub; when it becomes a service it will serve this same contract, so consumers swap a local evaluation call for a network call without contract changes.

## Tool Execution Contract Conventions (v1)

The `tool-invocation.schema.json` and `tool-result.schema.json` define the wire format between `agent-platform` (caller) and `tool-gateway` (executor) for tool invocations (SPEC-007).

Tool naming convention:

- `<system>.<verb>_<noun>` (e.g. `k8s.list_pods`, `k8s.get_events`)
- the system prefix identifies the external system; the verb/noun describe the operation

Result semantics:

- `status: success` — `data` contains the tool-specific payload
- `status: error` — `error` contains a machine-readable code and message
- `status: denied` — policy rejected the invocation; `error.code` is `POLICY_DENIED`
- `evidence` is always present and carries execution provenance (timestamp, duration, risk level, source system)

## Observability Conventions

Metrics naming, label/cardinality rules, the `OTEL_*` switch semantics, and the `x-request-id` ↔ `trace_id` bridging rule are defined in [observability-conventions.md](observability-conventions.md). All eight Python services implement these conventions (`SPEC-005`): an always-on `/metrics` Prometheus surface plus an opt-in OTLP push pipeline gated by `OTEL_ENABLED`.

## Expected Integration Points

- all `products/` modules that publish or consume shared interfaces
- `shared/shared-sdk` for generated or hand-written client helpers
- `docs/` for documented canonical contract definitions

## Boundary

This module should remain dependency-light and should not accumulate business logic.
