# Configuration Reference

A definitive cross-service environment variable dependency map for the Luban AIOps platform.
This document shows which variables interact across service boundaries, what each feature
requires, and where each value originates.

## Feature Activation Matrix

The table below maps platform capabilities to the environment variables and secrets that
activate them. A feature is **active** when all required variables are set to non-empty values.

| Capability | Required Variables | Service(s) | Default (dev-k8s) |
|---|---|---|---|
| **Chat and sessions** | `AGENT_SERVICE_URL`, `SESSION_STORE_BACKEND`, `SESSION_DB_URL`, `AGENT_STATE_STORE_BACKEND`, `AGENT_STATE_DB_URL` | platform-gateway, agent-service | enabled |
| **Portal authentication** | `PLATFORM_GATEWAY_REQUIRE_AUTH=true`, `IDENTITY_TOKEN_AUDIENCE` | platform-gateway, identity-service | enabled |
| **Token delegation** | `PLATFORM_GATEWAY_SERVICE_CLIENT_SECRET` ↔ `IDENTITY_SERVICE_CLIENTS` | platform-gateway ↔ identity-service | **must be provisioned** |
| **Kubernetes tools** | `GATEWAY_K8S_ENABLED=true`, `GATEWAY_K8S_NAMESPACE` | tool-gateway | enabled (`dev-luban-aiops`) |
| **Mutating tools (`k8s.delete_pod`)** | `GATEWAY_MUTATING_TOOLS_ENABLED=true`, `GATEWAY_K8S_ENABLED=true`, `AGENT_HITL_CONFIRM_TIMEOUT>0`, `tools:mutate` policy grant, opt-in pod-delete RBAC | tool-gateway, agent-service, policy bundle | disabled (`false`) |
| **Browser web-checks (`web.*`, SPEC-049)** | `GATEWAY_BROWSER_ENABLED=true`, `GATEWAY_BROWSER_ALLOW_ORIGINS` (deny-by-default), reachable `GATEWAY_BROWSER_CDP_ENDPOINT`; write-class flows additionally need `GATEWAY_MUTATING_TOOLS_ENABLED=true` + `AGENT_HITL_CONFIRM_TIMEOUT>0`; credentials via `GATEWAY_BROWSER_CREDENTIAL_SETS` | tool-gateway, agent-service | disabled in base (`false`); dev-k8s opts in via the `browser-dev` profile |
| **HTTP service-checks (`http.*`, SPEC-058)** | `GATEWAY_HTTP_ENABLED=true`, `GATEWAY_HTTP_ALLOW_ORIGINS` (deny-by-default); `http.post` (write) additionally needs `GATEWAY_MUTATING_TOOLS_ENABLED=true` + `AGENT_HITL_CONFIRM_TIMEOUT>0` + a `tools:mutate` grant; credentials via `GATEWAY_HTTP_CREDENTIAL_SETS` (defaults to the browser path) | tool-gateway, agent-service | disabled in base (`false`); dev-k8s opts in via the `browser-dev` profile |
| **Signed execution (SPEC-037)** | `AGENT_EXECUTION_SIGNING_KEY` ↔ `execution-signing-secret` | agent-service | **must be provisioned** (`sync-execution-signing-secret.sh`); absent key fails mutating resumes closed |
| **Isolated execution worker (SPEC-038/063)** | `AGENT_EXECUTION_WORKER_URL` + `AGENT_EXECUTION_HANDOFF_TOKEN` ↔ `execution-handoff-secret`; durable admission below | agent-service, execution-runtime | **must be provisioned**; missing configuration refuses execution; transport loss after a possible send is uncertain, never proof of no effect |
| **Durable mutation admission (SPEC-063)** | `AGENT_EXECUTION_STATE_DB_URL`, `AGENT_EXECUTION_ADMISSION_ENABLED=true`, `AGENT_EXECUTION_ADMISSION_EPOCH`; `EXECUTION_STATE_STORE_BACKEND=postgres`, `EXECUTION_STATE_DB_URL`, `EXECUTION_ADMISSION_ENABLED=true`, `EXECUTION_ADMISSION_EPOCH`; verified, enabled Postgres catalog with matching epoch | agent-service, execution-runtime | **disabled**; requires coordinated mutation-disabled migration/cutover and separate explicit enablement |
| **Elastic observability** | `GATEWAY_ELASTIC_ENABLED=true`, `GATEWAY_ELASTIC_URL`, auth (`_API_KEY` or `_USERNAME`+`_PASSWORD`) | tool-gateway | disabled |
| **Secure password generation / Copy password (SPEC-062)** | `GATEWAY_SECRETS_ENABLED=true`, readable `GATEWAY_PASSWORD_POLICY_PATH`, delegation + `tools:invoke` | tool-gateway, agent-service, platform-gateway, portal | disabled (`false`); no SMTP required |
| **Email secret delivery (SPEC-062)** | Secrets + mutating/HITL/signed execution enabled; `GATEWAY_EMAIL_HOST`, sender, TLS, optional SMTP Secret; paired gateway/agent recipient allowlists; `secrets:deliver` + `tools:mutate` | tool-gateway, agent-service, platform-gateway, policy bundle | SMTP unconfigured; inert |
| **Output redaction** | `GATEWAY_REDACTION_ENABLED` | tool-gateway | enabled (`true`) |
| **Policy enforcement** | `GATEWAY_POLICY_PATH`, `PLATFORM_GATEWAY_POLICY_PATH` | tool-gateway, platform-gateway | `/etc/luban/policy/policy.yaml` |
| **OpenTelemetry push** | `OTEL_ENABLED=true`, `OTEL_EXPORTER_OTLP_ENDPOINT`, auth `OTEL_EXPORTER_OTLP_HEADERS` | all services | enabled (OpenObserve; header via `sync-otel-secrets.sh`) |
| **LLM runtime** | `AGENTSCOPE_PROVIDER`, `AGENTSCOPE_MODEL_NAME`, `AGENTSCOPE_API_KEY` | agent-service | via runtime profile |
| **Workload identity** | `PLATFORM_GATEWAY_WORKLOAD_TOKEN_PATH`, `IDENTITY_WORKLOAD_ISSUER_URL`, `IDENTITY_WORKLOAD_CLIENTS` | platform-gateway, identity-service | disabled (dev) |
| **Durable audit trail** | `*_AUDIT_SERVICE_URL`, `*_AUDIT_CLIENT_SECRET` ↔ `AUDIT_INGEST_CLIENTS` | audit-service, tool-gateway, platform-gateway, identity-service, incident-service, skills-hub, agent-service | **must be provisioned** (`sync-audit-secrets.sh`) |
| **Skills and grounded guidance** | `SKILLS_SOURCES`, `GATEWAY_SKILLS_SERVICE_URL`, `GATEWAY_SKILLS_CLIENT_SECRET`, `PLATFORM_GATEWAY_SKILLS_HUB_URL`, `PLATFORM_GATEWAY_SKILLS_CLIENT_SECRET` ↔ `SKILLS_QUERY_CLIENTS` | skills-hub, tool-gateway, platform-gateway | **must be provisioned** (`sync-skills-secrets.sh`) |
| **Skill compositions (`kind: composition`, SPEC-057)** | *(no activation switch — additive on the skills path above)*; `SKILLS_COMPOSITION_MAX_SUB_SKILLS` bounds a composition's `sub_skills` count. A composition carries no authority (ADR-0011): no new policy action, no new audit event type, no new gate — each sub-skill keeps its own HITL gate | skills-hub | enabled (`8`); `make policy-diff` reports zero transitions |
| **Incident intake and triage** | `INCIDENT_WEBHOOK_TOKEN`, `PLATFORM_GATEWAY_INCIDENT_SERVICE_URL`, `PLATFORM_GATEWAY_INCIDENT_CLIENT_SECRET`, `AGENT_INCIDENT_SERVICE_URL`, `AGENT_INCIDENT_CLIENT_SECRET` (SPEC-043 incident-report documents) ↔ `INCIDENT_QUERY_CLIENTS` | incident-service, platform-gateway, tool-gateway, agent-service | **must be provisioned** (`sync-incident-secrets.sh`) |
| **Portal voice input** | *(none — browser Web Speech API; `input_modality` passes through gateway/agent and is audited only)* | operator-portal, platform-gateway, agent-service | enabled (browser-capability gated) |
| **Agent-driven context compression (`CompressContext`, SPEC-064)** | `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED=true` + `AGENTSCOPE_CONTEXT_TRIGGER_RATIO>0.2`; *(no execution/audit surface — kernel-local, state-only, no `offloader`)* | agent-service | disabled (`false`) |

## Secure Password Generation and Delivery (SPEC-062)

| Variable | Default | Owning service / behavior |
|---|---|---|
| `GATEWAY_SECRETS_ENABLED` | `false` | tool-gateway discovery switch for `secrets.*` |
| `GATEWAY_PASSWORD_POLICY_PATH` | packaged contract; dev-k8s `/etc/luban/policy/password-policy.yaml` | tool-gateway reads the canonical password policy; unreadable/invalid policy refuses generation |
| `GATEWAY_PASSWORD_MIN_LENGTH` | unset (contract) | Tightening only; weakening or exceeding the generator bound fails startup |
| `GATEWAY_PASSWORD_REQUIRED_CLASSES` | unset (contract) | Comma-separated classes; must retain all required classes without duplicates/unknowns |
| `GATEWAY_PASSWORD_EXCLUDE_AMBIGUOUS` | `false` | May add exclusion, never relax a policy's exclusion |
| `GATEWAY_SECRET_DELIVERY_BACKEND` | `memory` | `memory` or `redis`; other names fail startup |
| `GATEWAY_SECRET_DELIVERY_TTL_SECONDS` | `300` | Positive standalone redemption window — how long a generated value waits for the operator to click Copy |
| `GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS` | `900` | Positive portal-copy hold TTL spanning a full HITL approval wait (600s timeout + 300s redemption margin) so a password generated before a gated reset is still redeemable when the reveal-on-commit Copy button appears (SPEC-062 R-3) |
| `GATEWAY_SECRET_DELIVERY_MAX_ENTRIES` | `256` | Positive in-memory capacity; oldest-expiring entry evicted |
| `GATEWAY_SECRET_DELIVERY_REDIS_HOST` | `127.0.0.1` | Redis host; use `redis` for the dev-k8s Service |
| `GATEWAY_SECRET_DELIVERY_REDIS_PORT` | `6379` | Redis port, 1–65535 |
| `GATEWAY_SECRET_DELIVERY_REDIS_DB` | `2` | Nonnegative DB index, separate from the kernel message bus |
| `GATEWAY_EMAIL_HOST` | empty | SMTP host; empty keeps email inert |
| `GATEWAY_EMAIL_PORT` | `587` | SMTP STARTTLS port, 1–65535 |
| `GATEWAY_EMAIL_USER` | empty | Optional SMTP login username |
| `GATEWAY_EMAIL_PASSWORD` | empty | SMTP login secret; Secret only, never ConfigMap |
| `GATEWAY_EMAIL_FROM` | empty (falls back to user) | Must resolve to one valid ASCII mailbox |
| `GATEWAY_EMAIL_USE_TLS` | `true` | STARTTLS with certificate validation; `false` refuses email |
| `GATEWAY_EMAIL_RECIPIENT_ALLOWLIST` | empty | Comma-separated exact domains or addresses; no wildcard/subdomain expansion |
| `GATEWAY_EMAIL_STRICT_ALLOWLIST` | `false` | If true, send-time refusal outside the list; otherwise warning + approval |
| `AGENT_EMAIL_RECIPIENT_ALLOWLIST` | empty | agent-service's matching card-warning list, captured at park time |

Chain: portal click → authenticated platform-gateway proxy
`GET /api/v1/secrets/delivery/{id}` → delegated token → tool-gateway
`GET /api/v2/secrets/delivery/{id}` → owner-scoped atomic redemption → clipboard.
Only delivery metadata enters the stream and durable record. No email setup is
needed for generation or portal copy. After an approver resumes a turn, generation
uses the original requester's ephemeral delegated credential, not the approver's;
missing/expired requester credentials fail closed and require a new requester turn.
On the deny / gated-failure / expiry burn paths, agent-service issues an **internal**
owner-scoped `DELETE /api/v2/secrets/delivery/{id}` (no portal proxy) to discard the
held handle at once rather than leave it redeemable until the hold TTL lapses; the
discard is value-less, oracle-free, best-effort, and degrades to the expiry burn
(SPEC-062 R-3 deny-path hardening).

Email adds the existing mutating-tool switch, HITL and signed-execution setup,
plus `tools:mutate` and `secrets:deliver` grants. Keep both recipient allowlists
identical; the gateway's strict send-time check is authoritative. Provision SMTP
credentials explicitly with `sh shared/platform-ops/gitops/sync-email-secrets.sh`
after securely exporting `GATEWAY_EMAIL_PASSWORD`. It updates only the optional
`tool-gateway-email-secrets` Secret, does not restart workloads, and is not part
of automatic deployment. Base overlays leave secrets disabled and SMTP unset.

Memory buffers require one replica and lose handles on restart. Redis uses TTL
and atomic `GETDEL` (Redis 6.2+). Startup connectivity failure logs a fallback to
memory: **do not scale out while fallback is active**. Use a private, access-controlled,
non-persistent Redis instance for ephemeral values; do not enable RDB/AOF backups
for this buffer. TTL expiry is logical deletion, not secure erasure of snapshots.
The current client targets private-network Redis without an authentication/TLS
configuration surface; do not expose it beyond that trusted network.

`secret_delivered` is emitted on redemption or SMTP acceptance, not when a handle
is created. SMTP acceptance does not prove inbox delivery. A spent, expired or
wrong-owner handle is unavailable; a wrong-owner attempt also consumes the handle.
Clipboard failure cannot restore it. Never log redemption bodies or SMTP bodies.

## Cross-Service Dependency Chains

### Token Delegation Chain

The most critical cross-service dependency. Without it, the agent cannot invoke tools.

```
platform-gateway                          identity-service
┌──────────────────────┐                  ┌──────────────────────┐
│ PLATFORM_GATEWAY_    │                  │ IDENTITY_SERVICE_    │
│ SERVICE_CLIENT_ID    │─── must match ──►│ CLIENTS entry:       │
│ PLATFORM_GATEWAY_    │   client_id      │ platform-gateway:    │
│ SERVICE_CLIENT_      │                  │   <secret>:          │
│ SECRET               │─── must match ──►│   tool-gateway       │
│ PLATFORM_GATEWAY_    │                  │                      │
│ DELEGATION_AUDIENCE  │─── becomes aud ──►│ (delegated token)    │
│   = tool-gateway     │                  │                      │
└──────────────────────┘                  └──────────────────────┘
```

**Secret contract:**
- `PLATFORM_GATEWAY_SERVICE_CLIENT_SECRET` (in `platform-gateway-runtime-secrets`)
- Must match the secret in `IDENTITY_SERVICE_CLIENTS` (in `identity-service-runtime-secrets`)
- Format of `IDENTITY_SERVICE_CLIENTS`: `client_id:client_secret:audience1|audience2`
- Example: `platform-gateway:my-shared-secret:tool-gateway`

**Provisioning:** `make deploy` calls `sync-delegation-secrets.sh` which generates a random
shared secret (or uses `DELEGATION_CLIENT_SECRET` if exported) and creates both K8s secrets.

### Identity Verification Chain

```
identity-service                          platform-gateway & tool-gateway
┌──────────────────────┐                  ┌──────────────────────┐
│ IDENTITY_TOKEN_      │                  │ IDENTITY_TOKEN_      │
│ ISSUER               │◄── must match ──│ ISSUER (or default)  │
│ IDENTITY_TOKEN_      │                  │ PLATFORM_GATEWAY_    │
│ AUDIENCE             │◄── must match ──│ TOKEN_AUDIENCE       │
│                      │                  │ GATEWAY_TOKEN_       │
│ /.well-known/jwks.json│◄── fetched via ─│ AUDIENCE             │
│ (public keys)        │   JWKS URL       │ IDENTITY_JWKS_URL    │
└──────────────────────┘                  └──────────────────────┘
```

### Tool Relay Chain

```
platform-gateway          agent-service               tool-gateway
┌──────────────┐          ┌──────────────┐            ┌──────────────┐
│ AGENT_       │          │ TOOL_GATEWAY_ │            │ listens on   │
│ SERVICE_URL  │──relay──►│ URL           │──invoke───►│ :8000        │
│ = agent-     │          │ = http://tool-│            │              │
│   service:   │          │   gateway:8000│            │              │
│   8000       │          │              │            │              │
└──────────────┘          └──────────────┘            └──────────────┘
```

### Mutating Action Approval Chain (SPEC-021)

A mutating tool (`risk_level: write/admin`) only reaches execution when every
link in this chain holds; each link fails closed independently:

```
tool-gateway                     agent-service                    policy bundle
┌──────────────────────┐         ┌──────────────────────┐         ┌──────────────────────┐
│ GATEWAY_MUTATING_    │         │ auto-allow list is   │         │ tools:mutate granted │
│ TOOLS_ENABLED=true   │◄─gate──►│ read-only by         │◄─HITL──►│ to platform-admin +  │
│ (registers write/    │         │ construction;        │         │ operator only        │
│ admin tools)         │         │ AGENT_HITL_CONFIRM_  │         │ (deny-by-default)    │
│ tools:mutate checked │         │ TIMEOUT>0 (else      │         │ chat:confirm granted │
│ on every invoke      │         │ mutating tools are   │         │ to confirmation      │
│                      │         │ excluded)            │         │ roles                │
└──────────────────────┘         └──────────────────────┘         └──────────────────────┘
```

**Dependency chain:** tool-gateway risk-tier gate (`GATEWAY_MUTATING_TOOLS_ENABLED`
+ `tools:mutate`) → agent-platform invariant (mutating tools never auto-approved;
`AGENT_HITL_CONFIRM_TIMEOUT=0` drops them from the toolkit) → HITL confirmation
(`chat:confirm`) with the SPEC-030 approval-tier bridge (the default bundle's
`tier_2` rule on `tools:mutate` requires a designated approver distinct from the
requester; blocked attempts 403 and are audited, no new variables) →
`tools:mutate` grant in the policy bundle. Turning on only the
gateway flag is deliberately insufficient: without HITL bridging the agent cannot
even offer the tool, and without the policy grant the invocation 403s at the
gateway. Approved resumes additionally sign an execution request over the
parked arguments' digest and verify it at invocation (SPEC-037); without
`AGENT_EXECUTION_SIGNING_KEY` the mutating resume fails closed with an
audited `signing_unavailable` rejection. Since SPEC-038 the verified call
is handed off to the isolated `execution-runtime` worker, which re-verifies
the envelope and executes under the forwarded confirmer token; without
`AGENT_EXECUTION_WORKER_URL` + `AGENT_EXECUTION_HANDOFF_TOKEN` the resume
refuses execution — there is no in-process fallback. SPEC-063 additionally
requires enabled durable admission at agent, worker, and verified Postgres
catalog, with matching epochs. An ambiguous handoff transport failure after a
possible send records uncertainty and stops automatic mutation continuation;
it is not a pre-send rejection or proof of no target effect. See the
[Approval and HITL Governance Guide](approval-and-hitl.md) and the mandatory
[initial protocol cutover](execution-cutover-restore.md#initial-spec-063-protocol-cutover).

### Audit Ingestion Chain

Fire-and-forget audit delivery (SPEC-013). Unreachable audit-service degrades
to log-only auditing; user-facing requests are never blocked.

```
tool-gateway / platform-gateway / identity-service /
incident-service / skills-hub / agent-service               audit-service
┌─────────────────────────────────────────┐                 ┌──────────────────────┐
│ *_AUDIT_SERVICE_URL                     │── POST events ──►│ listens on :8000     │
│ = http://audit-service:8000             │                 │ AUDIT_INGEST_CLIENTS │
│ *_AUDIT_CLIENT_ID                       │── must match ──►│ entry:               │
│ *_AUDIT_CLIENT_SECRET                   │── must match ──►│ <client_id>=<secret> │
└─────────────────────────────────────────┘                 └──────────────────────┘
```

**Secret contract:**
- Each emitter's `*_AUDIT_CLIENT_SECRET` (in its `*-runtime-secrets`)
- Must match the secret registered for its client id in `AUDIT_INGEST_CLIENTS`
  (in `audit-service-runtime-secrets`), format `client_id=client_secret,...`

**Provisioning:** `make deploy` calls `sync-audit-secrets.sh` which generates
one random shared secret (or uses `AUDIT_INGEST_SECRET` if exported) and writes
all K8s secrets, registering every emitter in `AUDIT_INGEST_CLIENTS`.
agent-service (the SPEC-037 execution events) is the one exception to the
per-service secret files: its `AGENT_AUDIT_CLIENT_SECRET` is upserted in
place into the active runtime profile's `runtime-secrets.env`
(`agent-platform-runtime-secrets`) so the LLM provider keys already
provisioned there survive. `SKIP_AUDIT_SECRETS=true` opts out; unsetting an
emitter's `*_AUDIT_SERVICE_URL` falls back to log-only auditing.

**Known limitation (shared query credential):** the audit-service query API
(`GET /api/v1/audit/events`) authenticates against the same
`AUDIT_INGEST_CLIENTS` registry as ingest, so any caller holding an ingest
credential can also query the trail directly. End-user authorization is
enforced upstream — platform-gateway gates the proxied route behind the
deny-by-default `audit:read` policy (granted to `auditor` and
`platform-admin` only) — so this is acceptable for the dev overlay. For the
first non-dev deployment, split the registries: a separate query-credential
registry (e.g. `AUDIT_QUERY_CLIENTS`) so ingest clients cannot read the
trail, keeping ingest-only services from gaining query capability.

### Skills Retrieval Chain

Grounded guidance delivery (SPEC-014). The agent consults team-owned skills
through the tool-gateway's read-only skills tools; with no
`GATEWAY_SKILLS_SERVICE_URL` configured the connector stays unregistered and
the agent answers without guidance.

```
agent-service          tool-gateway                          skills-hub
┌──────────────┐       ┌──────────────────────┐              ┌──────────────────────┐
│ skills.search│       │ GATEWAY_SKILLS_      │── GET search ─►│ listens on :8000     │
│ skills.get   │invoke►│ SERVICE_URL          │   / get / list │ SKILLS_QUERY_CLIENTS │
│ skills.list  │       │ = http://skills-hub: │              │ entry:               │
│ (auto-allow) │       │   8000               │              │ <client_id>=<secret> │
│              │       │ GATEWAY_SKILLS_      │── must match ─►│                      │
│              │       │ CLIENT_ID / _SECRET  │              │                      │
└──────────────┘       └──────────────────────┘              └──────────────────────┘
```

**Secret contract:**
- `GATEWAY_SKILLS_CLIENT_SECRET` (in `tool-gateway-runtime-secrets`)
- Must match the secret registered for client `tool-gateway` in
  `SKILLS_QUERY_CLIENTS` (in `skills-hub-runtime-secrets`), format
  `client_id=client_secret,...`

**Portal inventory proxy (SPEC-019):** platform-gateway speaks to the same
skills-hub registry under its own client id for the portal's Skills view:
`PLATFORM_GATEWAY_SKILLS_HUB_URL` + `PLATFORM_GATEWAY_SKILLS_CLIENT_ID` /
`PLATFORM_GATEWAY_SKILLS_CLIENT_SECRET` (in
`platform-gateway-runtime-secrets`) must match the `platform-gateway` entry
in `SKILLS_QUERY_CLIENTS`. The portal's Tools view takes a separate path:
`PLATFORM_GATEWAY_TOOL_GATEWAY_URL` proxies tool-gateway `GET /api/v2/tools`
under a delegated operator token, so no extra secret is needed. Unset URLs
leave the respective portal routes fail-closed (503).

**Provisioning:** `make deploy` calls `sync-skills-secrets.sh` which creates
the `skills` database idempotently, generates one random shared secret, and
writes the skills-hub, tool-gateway, and platform-gateway K8s secrets. Export `SKILLS_GIT_TOKEN=<pat>` before running it to
also provision `SKILLS_GIT_TOKENS` for git-federated sources (the token is
never echoed or committed). `SKIP_SKILLS_SECRETS=true` opts out; unsetting
`GATEWAY_SKILLS_SERVICE_URL` leaves the skills tools unregistered. Unlike the
audit-service query path, skills-hub uses a dedicated query-credential
registry from day one (no shared ingest/query credential).

### Incident Intake and Triage Chain

Incident triage delivery (SPEC-015). Alertmanager posts to the webhook with
the shared bearer token; operators drive queries, manual reports, and triage
through platform-gateway, which enforces the `incident:*` policy actions and
relays identity. Triage reuses the chat delegation chain (SPEC-008): the
operator's delegated bearer is forwarded to incident-service, which uses it
for the single agent-platform turn in session `incident-<id>`. Agent
sessions are single-owner, so re-triage by a second operator falls back to
`incident-<id>--<operator>`; the incident record tracks the session
actually used, and the portal's Continue in chat follows it. Operator-facing
workflow detail lives in the
[Incident Triage and Collaboration Guide](incident-guide.md).

```
Alertmanager                    incident-service
┌──────────────────────┐        ┌──────────────────────────┐
│ POST /api/v1/webhooks│──token─►│ INCIDENT_WEBHOOK_TOKEN   │
│ /alertmanager        │        │ (fail-closed when unset) │
└──────────────────────┘        └──────────────────────────┘

platform-gateway / tool-gateway            incident-service
┌──────────────────────────────┐           ┌──────────────────────────┐
│ PLATFORM_GATEWAY_INCIDENT_   │── GET /   │ listens on :8000         │
│ SERVICE_URL                  │   POST ──►│ INCIDENT_QUERY_CLIENTS   │
│ GATEWAY_INCIDENTS_SERVICE_URL│           │ entry:                   │
│ = http://incident-service:   │           │ <client_id>=<secret>     │
│   8000                       │           │                          │
│ PLATFORM_GATEWAY_INCIDENT_   │── must    │                          │
│ CLIENT_SECRET /              │   match ─►│                          │
│ GATEWAY_INCIDENTS_CLIENT_    │           │                          │
│ SECRET                       │           │                          │
└──────────────────────────────┘           └──────────────────────────┘
```

**Secret contract:**
- `INCIDENT_WEBHOOK_TOKEN` (in `incident-service-runtime-secrets`) — shared
  bearer for the Alertmanager webhook; empty disables intake with a 503
- `PLATFORM_GATEWAY_INCIDENT_CLIENT_SECRET` /
  `GATEWAY_INCIDENTS_CLIENT_SECRET` / `AGENT_INCIDENT_CLIENT_SECRET`
  (in each caller's runtime-secrets) —
  must match the secrets registered for clients `platform-gateway`,
  `tool-gateway`, and `agent-service` in `INCIDENT_QUERY_CLIENTS` (in
  `incident-service-runtime-secrets`), format `client_id=client_secret,...`
- `INCIDENT_AUDIT_CLIENT_SECRET` (in `incident-service-runtime-secrets`) —
  the built-in audit connector's ingest credential; must match the
  `incident-service` entry in `AUDIT_INGEST_CLIENTS`

**Provisioning:** `make deploy` calls `sync-incident-secrets.sh` which
creates the `incidents` database idempotently, generates the webhook token
and one shared query secret (or uses exported `INCIDENT_WEBHOOK_TOKEN` /
`INCIDENT_QUERY_SECRET`), and writes the K8s secrets for every caller
(including `agent-platform-runtime-secrets` since SPEC-043).
`SKIP_INCIDENT_SECRETS=true` opts out; unsetting
`PLATFORM_GATEWAY_INCIDENT_SERVICE_URL` leaves the portal incidents routes
fail-closed (503), and unsetting `GATEWAY_INCIDENTS_SERVICE_URL` leaves the
incident tools unregistered. Like skills-hub, incident-service uses a
dedicated query-credential registry from day one.

**Incident-report document assembly (SPEC-043):** agent-service queries
the same registry when assembling `incident_report` documents:
`AGENT_INCIDENT_SERVICE_URL` + `AGENT_INCIDENT_CLIENT_ID` ride
runtime-config, and `AGENT_INCIDENT_CLIENT_SECRET` rides
`agent-platform-runtime-secrets`. An unset URL or secret fails
incident-report creation closed (503, "incident service not
configured"); the portal incidents routes and the document surface
degrade independently.

## Policy Bundle Rollout (SPEC-048)

The action-authorization bundle has exactly one canonical copy:
`shared/shared-contracts/policies/policy-default.yaml`. It is replicated
byte-identically to both gateways' packaged defaults and the dev-k8s
GitOps overlay by `make sync-policy`, and contract tests fail
`make verify` on any drift. Never edit a replica — edit the canonical
file and follow the rollout sequence:

1. **Edit** `shared/shared-contracts/policies/policy-default.yaml` and
   bump its `version` field. Version discipline is review discipline —
   Git history is the authority; there is no monotonicity machinery.
2. **Record intent** in
   `shared/shared-contracts/policies/policy-scenarios.yaml` if the edit
   adds a grant or flips an operator-visible outcome — the scenario
   guard fails `make verify` on any granted (role, action) pair with no
   expectation, which is the prompt, not a nuisance.
3. **Sync**: `make sync-policy`.
4. **Verify**: `make verify` runs the schema check, the
   scenario-expectation guard against both engines (the platform-gateway
   21-action vocabulary and the tool-gateway tools:* vocabulary), and
   the copy-parity assertions.
5. **Review impact**: `make policy-diff CANDIDATE=<candidate.yaml>`
   reports every per-(role, action) outcome transition between the
   canonical bundle and the candidate for both engines (new grants,
   removed grants, allow↔deny, approval-tier changes), with unchanged
   pairs summarized by count. For an in-place edit, diff against the
   pre-edit copy (`git show HEAD:shared/shared-contracts/policies/policy-default.yaml > /tmp/prev.yaml`).
6. **Commit** the bundle, the scenario table update, and the synced
   replicas in one commit — the reviewer reads the policy-diff report
   in the PR description.
7. **Deploy**: `make deploy`. Bundles are cached keyed on the configured
   path, and there is deliberately no hot reload: a changed ConfigMap
   takes effect on pod restart (rolling restart the gateway
   deployments), and the packaged default changes ride the image build.
8. **Confirm provenance**: both gateways expose a SHA-256 fingerprint
   of the exact loaded bundle text — platform-gateway on the policy
   matrix response (`policy:read`-gated) and `/health/ready`,
   tool-gateway on `/health/ready`. Compare against
   `shasum -a 256 shared/shared-contracts/policies/policy-default.yaml`
   to confirm the enforced bundle matches the intended commit without
   shelling into the pod.

A missing or invalid bundle at a configured path fails startup
(`PolicyLoadError`, no silent fallback to the packaged default), and
readiness reports the degraded policy state.

## Per-Service Environment Variables

### agent-service

Source: `products/agent-platform/src/agent_service/runtime_settings.py`
Config fragment: `shared/platform-ops/gitops/dev-k8s/base/agent-platform/runtime-config.env`

| Variable | Purpose | Default | Source |
|---|---|---|---|
| `AGENTSCOPE_PROVIDER` | LLM backend: `dashscope`, `deepseek`, `openai`, or `luban` | *(from profile)* | profile ConfigMap |
| `AGENTSCOPE_PROFILE` | Active profile name (must match provider) | *(from profile)* | profile ConfigMap |
| `AGENTSCOPE_MODEL_NAME` | Model identifier | *(from profile)* | profile ConfigMap |
| `AGENTSCOPE_BASE_URL` | Provider API endpoint | *(from profile)* | profile ConfigMap |
| `AGENTSCOPE_API_KEY` | Provider API key | *(none)* | **runtime-secrets** |
| `<PROVIDER>_API_KEY` / `<PROVIDER>_MODEL_NAME` / `<PROVIDER>_BASE_URL` | Additional model-catalog entries (SPEC-024); `PROVIDER` ∈ `DASHSCOPE`, `DEEPSEEK`, `OPENAI`, `LUBAN`. Each provider with a resolvable key contributes one selectable model (id = provider name); the active profile's provider falls back to the `AGENTSCOPE_*` knobs, so single-provider deployments need no new config | *(none)* | **runtime-secrets** |
| `LUBAN_API_KEY` / `LUBAN_BASE_URL` / `LUBAN_MODEL_NAME` / `LUBAN_MODELS` | Team-hosted (local/on-prem) OpenAI-compatible server as the `luban` provider (SPEC-028). Both the API key and the base URL are mandatory — a key without `LUBAN_BASE_URL` gates the provider out (self-hosted endpoints have no default endpoint). `LUBAN_MODELS` pinning is recommended for fixed-point audit attribution; see the [Luban-Hosted Small Model Guide](luban-llm-guide.md) | *(none)* | **runtime-secrets** |
| `LUBAN_THINKING_ENABLE` | Opt a thinking-capable luban model into thinking mode (OpenAI-shaped options; small-model-safe default is off) | `false` | **runtime-secrets** |
| `AGENTSCOPE_AGENT_NAME` | Agent identifier | `LubanOpsRuntime` | runtime-config |
| `AGENTSCOPE_REDIS_HOST` | Redis host for AgentScope coordination | `redis` | runtime-config |
| `AGENTSCOPE_REDIS_PORT` | Redis port | `6379` | runtime-config |
| `AGENTSCOPE_REDIS_DB` | Redis database number | `0` | runtime-config |
| `AGENTSCOPE_WORKSPACE_DIR` | Working directory for session files | `/var/lib/luban-aiops/workspaces/agent-platform` | runtime-config |
| `AGENTSCOPE_WORKSPACE_TTL_SECONDS` | Workspace cleanup TTL | `3600` | runtime-config |
| `SESSION_STORE_BACKEND` | Session persistence backend (`memory` \| `redis` \| `postgres`; unknown values fail startup) | `postgres` | runtime-config |
| `SESSION_DB_URL` | Postgres DSN for sessions (required for `postgres`) | `postgresql://audit:audit-dev-local@postgres:5432/sessions` | runtime-config |
| `AGENT_STATE_STORE_BACKEND` | Agent state persistence backend (`memory` \| `postgres`; unknown values fail startup, unreachable Postgres fails open to memory) | `postgres` | runtime-config |
| `AGENT_STATE_DB_URL` | Postgres DSN for agent state (required for `postgres`; shares the `sessions` database) | `postgresql://audit:audit-dev-local@postgres:5432/sessions` | runtime-config |
| `AGENT_STATE_TTL_SECONDS` | Sweep TTL for stale agent state rows | `3600` | code default |
| `AGENT_EVIDENCE_ENTRY_MAX_CHARS` | Serialized-size cap for one persisted evidence frame payload (SPEC-025); oversized `tool_result.data` is truncated with an `entry_cap` marker | `131072` | code default |
| `AGENT_EVIDENCE_SESSION_MAX_BYTES` | Per-session budget for persisted evidence (SPEC-025); when exceeded, oldest `tool_result` data payloads are evicted with a `session_budget` marker (metadata kept) | `4194304` | code default |
| `AGENT_MODEL_DISCOVERY_ENABLED` | Live model discovery (SPEC-027): periodic `GET /models` per configured provider feeds the catalog behind a fail-soft ladder (live → memory → Postgres → curated); `false` restores the pure curated-series behavior | `true` | code default |
| `AGENT_MODEL_DISCOVERY_REFRESH_SECONDS` | Discovery refresh cadence in seconds (must be >= 1) | `1800` | code default |
| `AGENT_MODEL_DISCOVERY_TIMEOUT_SECONDS` | Per-provider `/models` fetch timeout in seconds (must be > 0) | `5` | code default |
| `AGENTSCOPE_MAX_ITERS` | ReAct loop iteration cap (`ReActConfig.max_iters`; must be >= 1) | `20` | code default |
| `AGENTSCOPE_CONTEXT_TRIGGER_RATIO` | Long-term memory trigger ratio (`ContextConfig.trigger_ratio`; must be in open interval (0, 0.9)) | `0.8` | code default |
| `AGENTSCOPE_TOOL_RESULT_LIMIT` | Tool result character limit (`ContextConfig.tool_result_limit`; must be >= 1) | `50000` | code default |
| `AGENTSCOPE_TIMEZONE` | Runtime-state injection timezone (`InjectionConfig.timezone`; IANA name, validated at startup) | `UTC` | code default |
| `AGENTSCOPE_MODEL_MAX_RETRIES` | Model call retry count (`ModelConfig.max_retries`; must be >= 0) | `0` | code default |
| `AGENTSCOPE_KERNEL_TRACING` | Register agentscope's out-of-box `TracingMiddleware` for OTel kernel spans (inert without an SDK `TracerProvider`) | `false` | code default |
| `AGENTSCOPE_REPLY_TOKEN_BUDGET` | Reply token budget (`ReplyBudgetControlMiddleware.token_budget`; must be > 0 when set; unset disables the budget) | unset | code default |
| `AGENTSCOPE_REPLY_INPUT_TOKEN_WEIGHT` | Input token weight for the reply budget (must be >= 0; `0` is valid) | `1.0` | code default |
| `AGENTSCOPE_REPLY_OUTPUT_TOKEN_WEIGHT` | Output token weight for the reply budget (must be >= 0; `0` is valid) | `1.0` | code default |
| `AGENTSCOPE_TASK_TOOLS_ENABLED` | Opt-in agentscope task tools (`TaskCreate`/`TaskGet`/`TaskList`/`TaskUpdate`; state-local, persisted via the agent state store) | `false` | code default |
| `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` | Opt-in agent-driven context compression (`CompressContext`, SPEC-064 R-2): registers the kernel-local tool that reuses the threshold `_compress_context_impl` to summarize `state.summary`/`state.context`. State-only, no `offloader` wired, no new audit/evidence event. Requires `AGENTSCOPE_CONTEXT_TRIGGER_RATIO > 0.2` (agentscope `context_buffer_ratio`); rejected at startup otherwise | `false` | code default |
| `AGENT_AUDIT_SERVICE_URL` | Audit-service ingest URL for agent-service emissions (SPEC-037 execution events); unset degrades to log-only auditing | `http://audit-service:8000` | runtime-config |
| `AGENT_AUDIT_CLIENT_ID` | Audit ingest client id for agent-service; must match an `AUDIT_INGEST_CLIENTS` entry | `agent-service` | runtime-config |
| `AGENT_INCIDENT_SERVICE_URL` | incident-service base URL for incident-report document assembly (SPEC-043); unset fails incident-report creation closed (503) | `http://incident-service:8000` (dev-k8s) | runtime-config |
| `AGENT_INCIDENT_CLIENT_ID` | Incident query client id for agent-service; must match an `INCIDENT_QUERY_CLIENTS` entry | `agent-service` | runtime-config |
| `AGENT_INCIDENT_CLIENT_SECRET` | Incident query credential for agent-service (SPEC-043); rides `agent-platform-runtime-secrets` — absent secret fails incident-report creation closed (503) | **must be provisioned** | agent-platform-runtime-secrets |
| `AGENT_INCIDENT_CLIENT_TIMEOUT_SECONDS` | Incident bundle fetch timeout for document assembly; must be > 0 | `10` | code default |
| `AGENT_SKILLS_SERVICE_URL` | skills-hub base URL for skill-draft validation (SPEC-044); unset fails skill-draft export closed (503) | `http://skills-hub:8000` (dev-k8s) | runtime-config |
| `AGENT_SKILLS_CLIENT_ID` | Skills query client id for agent-service; must match a `SKILLS_QUERY_CLIENTS` entry | `agent-service` | runtime-config |
| `AGENT_SKILLS_CLIENT_SECRET` | Skills query credential for agent-service (SPEC-044); rides `agent-platform-runtime-secrets` — absent secret fails skill-draft export closed (503) | **must be provisioned** | agent-platform-runtime-secrets |
| `AGENT_SKILLS_CLIENT_TIMEOUT_SECONDS` | Skills-hub validation round-trip timeout for skill drafts; must be > 0 | `10` | code default |
| `AGENT_EXECUTION_SIGNING_KEY` | HMAC key for signed execution requests and receipts (SPEC-037); rides the `execution-signing-secret` via an optional `secretKeyRef` — an absent secret leaves it unset and mutating resumes fail closed (`signing_unavailable`) | **must be provisioned** | execution-signing-secret |
| `AGENT_EXECUTION_WORKER_URL` | Internal `execution-runtime` worker endpoint for the authenticated handoff of approved mutating calls (SPEC-038); unset rejects mutating resumes with an audited `worker_unavailable` rejection — no in-process fallback | `http://execution-runtime:8000` (dev-k8s) | runtime-config |
| `AGENT_EXECUTION_HANDOFF_TOKEN` | Static bearer token presented to the worker handoff (SPEC-038); rides the `execution-handoff-secret` via an optional `secretKeyRef` — absent secret fails mutating resumes closed (`worker_unavailable`) | **must be provisioned** | execution-handoff-secret |
| `AGENT_EXECUTION_WORKER_TIMEOUT_SECONDS` | Handoff wait budget; must be > 0 and <= 120. Durable-path expiry records wait uncertainty, not a terminal worker receipt or cancellation | `60` | code default |
| `AGENT_EXECUTION_STATE_DB_URL` | Postgres DSN for the SPEC-063 execution ledger, shared with the worker; no memory-backed mutation fallback | *(none)* | explicitly provisioned Secret/environment |
| `AGENT_EXECUTION_ADMISSION_ENABLED` | Opt-in admission flag; enabling requires ledger DSN and epoch; effective admission also requires verified enabled catalog | `false` | code default; explicit cutover configuration |
| `AGENT_EXECUTION_ADMISSION_EPOCH` | Externally managed UUID matching worker/catalog; not inferred from a restored snapshot | *(none)* | explicit cutover configuration |
| `AGENT_GATEWAY_TOOL_AUTO_ALLOW` | Comma-separated dotted gateway tool names auto-approved by the permission middleware when read-only (overrides the built-in vetted list); the allow-list is the only auto-approval surface — every other tool is answered with an explicit ASK and parks for operator confirmation (SPEC-020). Mutating tools are never auto-approved regardless of this setting (SPEC-021) | built-in vetted list | code default |
| `AGENT_HITL_CONFIRM_TIMEOUT` | HITL confirmation timeout in seconds; an expired parked batch is closed via `UserInterruptEvent` on the next confirm attempt (410) or next chat turn. `0` disables HITL confirmation bridging entirely (SPEC-020) and excludes mutating tools from the agent toolkit (SPEC-021) | `600` | code default |
| `AGENT_BROWSER_FLOW_APPROVAL_TTL` | Seconds an operator's approval of a `write`-class browser flow unlocks subsequent `web.*` writes in that same flow (SPEC-051 R-2): the authority is scoped to the chat session **and** the approved flow's identity (`skill_id` + `origin`) and each unlocked write is auto-signed under the approving card (ADR-0007). An expired approval no longer unlocks — the next write parks again. `0` disables flow-unlock entirely, restoring the pre-SPEC-051 posture where every browser write parks its own card. Must be `>= 0`. The tool-gateway deviation guard (origin allowlist, `risk_class`, `GATEWAY_BROWSER_FLOW_MAX_STEPS`) still bounds every unlocked write regardless of this knob | `900` | code default |
| `AGENT_TOOL_DATA_SUMMARY_MAX_CHARS` | Serialized-size cap for the `data_summary` field on `tool_result` evidence frames; oversized payloads are truncated with a marker | `2000` | code default |
| `AGENT_TOOL_DATA_MAX_CHARS` | Serialized-size cap for the full `data` field on `tool_result` evidence frames (stream schema v6); oversized payloads are omitted from the frame and stay in the audit trail only | `32000` | code default |
| `AGENT_AUTHORING_TRACE_MAX_STEPS` | Per-session authoring-trace step cap (SPEC-055 R-1); capture beyond the cap is dropped best-effort rather than letting one long session grow an unbounded trace. Must be `>= 1` | `100` | code default |
| `AGENT_AUTHORING_TRACE_IDLE_DAYS` | Idle window after which a still-`draft` authoring trace is reclaimed (SPEC-055 R-1 / OQ-1), at startup and opportunistically on write. Lifecycle-bound — deliberately **not** the 30-day `execution_records` sweep, so a session authored now stays graduable after its signed receipts are gone, and a terminal (`graduated`/`discarded`) trace is never swept. `0` disables the idle-GC. Must be `>= 0` | `180` | code default |
| `AGENT_SKILL_GRADUATION_MAX_STEPS` | Blast-radius step bound re-checked at graduation (SPEC-055 R-4): a trace longer than this is refused as not-graduable (409) rather than exported as a flow that would die part-way through mutating. A deliberate twin of the tool-gateway's `GATEWAY_BROWSER_FLOW_MAX_STEPS` replay budget, and tunable because that one is — raise the two together or graduation refuses flows that would have replayed. Not skills-hub's `MAX_STEPS` ingestion ceiling (`200`), which is a resource limit rather than a policy bound. Must be `>= 1` | `20` | code default |
| `TOOL_GATEWAY_URL` | Upstream tool-gateway URL | `http://tool-gateway:8000` | runtime-config |

### execution-runtime

Source: `products/execution-runtime/src/execution_runtime/core/config.py`
Config fragment: `shared/platform-ops/gitops/dev-k8s/base/execution-runtime/runtime-config.env`

| Variable | Purpose | Default | Source |
|---|---|---|---|
| `EXECUTION_SIGNING_KEY` | HMAC key verifying SPEC-037 envelopes and signing receipts (shared with agent-service); unset rejects every handoff | **must be provisioned** | execution-signing-secret |
| `EXECUTION_HANDOFF_TOKEN` | Static credential authenticating the agent-service handoff (constant-time comparison); unset rejects every handoff | **must be provisioned** | execution-handoff-secret |
| `TOOL_GATEWAY_URL` | tool-gateway endpoint for approved executions | `http://tool-gateway:8000` | runtime-config (merged ConfigMap) |
| `EXECUTION_GATEWAY_TIMEOUT_SECONDS` | Tool-gateway invocation budget; must be > 0 and <= 30; expiry does not cancel remote work | `30` | code default |
| `EXECUTION_STATE_STORE_BACKEND` | Legacy presentation-store selection; actual `postgres` ledger is mandatory for SPEC-063 admission (`memory` cannot execute mutations) | `memory` | code default (`postgres` in dev-k8s) |
| `EXECUTION_STATE_DB_URL` | Postgres DSN shared with agent execution recovery; ledger catalog/claims/observations are distinct from historical `execution_records` | *(none)* | runtime-config in dev; protected Secret elsewhere |
| `EXECUTION_ADMISSION_ENABLED` | Worker admission opt-in, in addition to the verified catalog flag; disabled readiness returns 503 | `false` | code default; explicit cutover configuration |
| `EXECUTION_ADMISSION_EPOCH` | External UUID matching agent/catalog; mismatch refuses dispatch | *(none)* | explicit cutover configuration |
| `EXECUTION_AUDIT_SERVICE_URL` | audit-service ingest URL; unset degrades to log-only auditing | *(none)* | runtime-config |
| `EXECUTION_AUDIT_CLIENT_ID` | Audit ingest client id; must match an `AUDIT_INGEST_CLIENTS` entry | `execution-runtime` | runtime-config |
| `EXECUTION_AUDIT_CLIENT_SECRET` | Audit ingest client secret | *(none)* | **runtime-secrets** |
| `EXECUTION_FLIGHT_RETENTION_SECONDS` | Legacy single-flight cache knob; not the durable claim retention or dispatch authority | `900` | code default |

The migration CLI explicitly creates/verifies the ledger with admission disabled;
normal startup verifies only. Postgres durability settings `fsync`,
`full_page_writes`, and `synchronous_commit` must remain on. Session/presentation
TTL does not release claims: the ledger protects requests through their signed
expiry plus at least 30 days, and retains dependent run identities/stops.
`/health/live` remains process-local; `/health/ready` distinguishes disabled,
misconfigured, or unavailable admission. Never repair readiness by bypassing the
[cutover and restore procedure](execution-cutover-restore.md).

### platform-gateway

Source: `products/platform-gateway/src/platform_gateway/core/config.py`
Config fragment: `shared/platform-ops/gitops/dev-k8s/base/platform-gateway/runtime-config.env`

| Variable | Purpose | Default | Source |
|---|---|---|---|
| `AGENT_SERVICE_URL` | Upstream agent-service URL | `http://agent-service:8000` | runtime-config |
| `PLATFORM_GATEWAY_REQUIRE_AUTH` | Require bearer token on requests | `true` | runtime-config |
| `PLATFORM_GATEWAY_DEV_USER` | Synthetic identity when auth is off | `dev.operator` | runtime-config |
| `PLATFORM_GATEWAY_POLICY_PATH` | Path to policy bundle YAML | `/etc/luban/policy/policy.yaml` | runtime-config |
| `PLATFORM_GATEWAY_TOKEN_AUDIENCE` | Expected JWT audience claim | `platform-gateway` | runtime-config |
| `PLATFORM_GATEWAY_DELEGATION_AUDIENCE` | Audience for delegated tokens | `tool-gateway` | runtime-config |
| `PLATFORM_GATEWAY_SERVICE_CLIENT_ID` | Client ID for token exchange | `platform-gateway` | runtime-config |
| `PLATFORM_GATEWAY_SERVICE_CLIENT_SECRET` | Client secret for token exchange | *(none)* | **runtime-secrets** |
| `PLATFORM_GATEWAY_WORKLOAD_TOKEN_PATH` | Projected SA token file (prod) | *(none)* | runtime-secrets |
| `IDENTITY_SERVICE_URL` | Identity broker URL | `http://identity-service:8000` | shared/runtime.env |
| `IDENTITY_JWKS_URL` | JWKS public key endpoint | `http://identity-service:8000/.well-known/jwks.json` | derived |
| `IDENTITY_TOKEN_ISSUER` | Expected JWT issuer | `http://identity-service:8000` | derived |
| `IDENTITY_JWKS_CACHE_SECONDS` | JWKS key cache TTL | `300` | code default |
| `CHAT_RESPONSE_TIMEOUT_SECONDS` | Upstream chat timeout | `30` | code default |
| `PLATFORM_GATEWAY_AUDIT_SERVICE_URL` | Audit-service ingest URL (unset = log-only) | `http://audit-service:8000` | runtime-config |
| `PLATFORM_GATEWAY_AUDIT_CLIENT_ID` | Audit ingest client id | `platform-gateway` | runtime-config |
| `PLATFORM_GATEWAY_AUDIT_CLIENT_SECRET` | Audit ingest credential | *(none)* | **runtime-secrets** |
| `PLATFORM_GATEWAY_INCIDENT_SERVICE_URL` | incident-service base URL (unset = incidents routes fail closed 503) | *(none)* | runtime-config |
| `PLATFORM_GATEWAY_INCIDENT_CLIENT_ID` | Incident query client id | `platform-gateway` | code default |
| `PLATFORM_GATEWAY_INCIDENT_CLIENT_SECRET` | Incident query credential | *(none)* | **runtime-secrets** |
| `PLATFORM_GATEWAY_INCIDENT_TRIAGE_TIMEOUT_SECONDS` | Triage proxy timeout | `120` | code default |
| `PLATFORM_GATEWAY_TOOL_GATEWAY_URL` | tool-gateway base URL for the portal Tools proxy (unset = route fails closed 503) | *(none)* | runtime-config |
| `PLATFORM_GATEWAY_SKILLS_HUB_URL` | skills-hub base URL for the portal Skills proxy (unset = route fails closed 503) | *(none)* | runtime-config |
| `PLATFORM_GATEWAY_SKILLS_CLIENT_ID` | Skills query client id | `platform-gateway` | runtime-config |
| `PLATFORM_GATEWAY_SKILLS_CLIENT_SECRET` | Skills query credential | *(none)* | **runtime-secrets** |

Request field (SPEC-022 R-2): `POST /api/v1/chat` accepts an optional
`input_modality` (`text` | `voice`, default `text`). It is metadata only —
forwarded to agent-platform, recorded in the chat log event and audit
details, and never influences authorization, tool policy, or HITL gating.

### tool-gateway

Source: `products/tool-gateway/src/tool_gateway/core/config.py`
Config fragment: `shared/platform-ops/gitops/dev-k8s/base/tool-gateway/runtime-config.env`

| Variable | Purpose | Default | Source |
|---|---|---|---|
| `GATEWAY_REQUIRE_AUTH` | Require bearer token on requests | `true` | runtime-config |
| `GATEWAY_DEV_USER` | Synthetic identity when auth is off | `dev.operator` | runtime-config |
| `GATEWAY_POLICY_PATH` | Path to policy bundle YAML | `/etc/luban/policy/policy.yaml` | runtime-config |
| `GATEWAY_TOKEN_AUDIENCE` | Expected JWT audience claim | `tool-gateway` | runtime-config |
| `GATEWAY_K8S_ENABLED` | Enable Kubernetes connector | `true` | runtime-config |
| `GATEWAY_K8S_NAMESPACE` | Default namespace for K8s tools | `dev-luban-aiops` | runtime-config |
| `GATEWAY_MUTATING_TOOLS_ENABLED` | Register write/admin risk tools (SPEC-021); while `false` they are absent from discovery and invoke | `false` | runtime-config |
| `GATEWAY_REDACTION_ENABLED` | Enable output redaction | `true` | code default |
| `GATEWAY_REDACTION_OVERFLOW_FRACTION` | Fail-closed redaction threshold | `0.2` | code default |
| `GATEWAY_ELASTIC_ENABLED` | Enable Elastic connector | `false` | runtime-config |
| `GATEWAY_ELASTIC_URL` | Elasticsearch cluster URL | *(none)* | runtime-config |
| `GATEWAY_ELASTIC_API_KEY` | Elastic API key (base64) | *(none)* | runtime-config |
| `GATEWAY_ELASTIC_USERNAME` | Elastic basic-auth username | *(none)* | runtime-config |
| `GATEWAY_ELASTIC_PASSWORD` | Elastic basic-auth password | *(none)* | runtime-config |
| `GATEWAY_ELASTIC_VERIFY_TLS` | Verify Elastic TLS certificates | `true` | code default |
| `GATEWAY_ELASTIC_ALERTS_INDEX` | Elastic alerts index pattern | `.alerts-*` | code default |
| `GATEWAY_WORKLOAD_TOKEN_PATH` | Projected SA token file (prod) | *(none)* | runtime-secrets |
| `GATEWAY_AUDIT_SERVICE_URL` | Audit-service ingest URL (unset = log-only) | `http://audit-service:8000` | runtime-config |
| `GATEWAY_AUDIT_CLIENT_ID` | Audit ingest client id | `tool-gateway` | runtime-config |
| `GATEWAY_AUDIT_CLIENT_SECRET` | Audit ingest credential | *(none)* | **runtime-secrets** |
| `GATEWAY_SKILLS_SERVICE_URL` | skills-hub base URL (unset = connector off) | `http://skills-hub:8000` | runtime-config |
| `GATEWAY_SKILLS_CLIENT_ID` | Skills query client id | `tool-gateway` | runtime-config |
| `GATEWAY_SKILLS_CLIENT_SECRET` | Skills query credential | *(none)* | **runtime-secrets** |
| `GATEWAY_INCIDENTS_SERVICE_URL` | incident-service base URL (unset = connector off) | *(none)* | runtime-config |
| `GATEWAY_INCIDENTS_CLIENT_ID` | Incidents query client id | `tool-gateway` | code default |
| `GATEWAY_INCIDENTS_CLIENT_SECRET` | Incidents query credential | *(none)* | **runtime-secrets** |
| `GATEWAY_BROWSER_ENABLED` | Enable the browser connector (`web.*`, SPEC-049); while `false` no web tool registers | `false` | runtime-config (dev-k8s merges `true` via `browser-dev`) |
| `GATEWAY_BROWSER_CDP_ENDPOINT` | CDP websocket endpoint of the browser sidecar; a bare `ws://`/`wss://` endpoint (no path) is dialed as its `http(s)://` DevTools discovery base, a full `/devtools/browser/<id>` URL passes through verbatim | `ws://localhost:9222` | runtime-config |
| `GATEWAY_BROWSER_ALLOW_ORIGINS` | Comma-separated origin allowlist; empty denies all navigation; redirect landings re-checked | *(empty)* | runtime-config |
| `GATEWAY_BROWSER_SESSION_TTL` | Idle seconds before a chat session's browser context is swept | `600` | code default |
| `GATEWAY_BROWSER_MAX_SESSIONS` | Session-pool cap (oldest-idle eviction) | `4` | code default |
| `GATEWAY_BROWSER_FLOW_MAX_STEPS` | Interaction step budget per bound flow | `20` | code default |
| `GATEWAY_BROWSER_CREDENTIAL_SETS` | Secret-mounted credential-sets JSON path; empty = `web.fill_credential` fails closed | *(none)* | **runtime-secrets** (mounted file) |
| `GATEWAY_BROWSER_SCREENSHOT_MAX_BYTES` | Byte cap for base64 JPEG screenshots (compressed to fit) | `65536` | code default |
| `GATEWAY_HTTP_ENABLED` | Enable the HTTP service-check connector (`http.get`/`http.post`, SPEC-058); while `false` no `http.*` tool registers | `false` | runtime-config (dev-k8s merges `true` via `browser-dev`) |
| `GATEWAY_HTTP_ALLOW_ORIGINS` | Comma-separated origin allowlist; empty denies every URL; redirect landings re-checked; loopback/link-local/multicast literals refused regardless of the list | *(empty)* | runtime-config |
| `GATEWAY_HTTP_TIMEOUT_MS` | Per-request timeout in milliseconds (capped at 30000) | `10000` | code default |
| `GATEWAY_HTTP_MAX_RESPONSE_BYTES` | Response-body projection cap; a larger body is cut and reported with `truncated: true` | `65536` | code default |
| `GATEWAY_HTTP_MAX_REQUEST_BYTES` | Serialized `http.post` body cap (alongside depth ≤ 2 and ≤ 32 keys) | `4096` | code default |
| `GATEWAY_HTTP_CREDENTIAL_SETS` | Secret-mounted credential-sets JSON path for `http.*` Basic auth; **defaults to `GATEWAY_BROWSER_CREDENTIAL_SETS`** when unset so one mounted file serves both surfaces; empty = a `credential_set` reference fails closed (`CREDENTIAL_SET_NOT_FOUND`) | *(browser path)* | **runtime-secrets** (mounted file) |
| `IDENTITY_SERVICE_URL` | Identity broker URL | `http://identity-service:8000` | shared/runtime.env |

### identity-service

Source: `products/identity-broker/src/identity_service/core/config.py`
Config fragment: `shared/platform-ops/gitops/dev-k8s/base/identity-broker/runtime-config.env`

| Variable | Purpose | Default | Source |
|---|---|---|---|
| `KEYCLOAK_BASE_URL` | Keycloak server URL | `https://idp.apps.metasync.cc` | runtime-config |
| `KEYCLOAK_REALM` | Keycloak realm name | `luban-aiops` | runtime-config |
| `OIDC_CLIENT_ID` | OIDC browser client ID | `luban-aiops-portal` | runtime-config |
| `OIDC_CLIENT_SECRET` | OIDC client secret (confidential clients) | *(none)* | **runtime-secrets** |
| `OIDC_SCOPES` | Requested OIDC scopes | `openid groups` | runtime-config |
| `OIDC_REDIRECT_URI` | Primary browser callback URI | `https://aiops.luban.metasync.cc/callback` | runtime-config |
| `OIDC_POST_LOGOUT_REDIRECT_URI` | Primary post-logout redirect | `https://aiops.luban.metasync.cc/` | runtime-config |
| `OIDC_EXTRA_REDIRECT_URIS` | Comma-separated extra callback URIs, registered with Keycloak for reachability only — the broker always uses `OIDC_REDIRECT_URI` as the flow's callback | gateway `.orb.local` + `localhost:18080` | runtime-config |
| `OIDC_EXTRA_POST_LOGOUT_REDIRECT_URIS` | Comma-separated extra post-logout redirects registered with Keycloak; the portal passes its own origin on logout, so these let logout return to any reachable portal origin | gateway `.orb.local` + `localhost:18080` | runtime-config |
| `IDENTITY_TOKEN_AUDIENCE` | JWT audience for portal tokens | `platform-gateway` | runtime-config |
| `IDENTITY_TOKEN_TTL_SECONDS` | Portal JWT TTL | `3600` | code default |
| `IDENTITY_DELEGATED_TOKEN_TTL_SECONDS` | Delegated token TTL | `300` | runtime-config |
| `IDENTITY_JWT_ISSUER` | JWT issuer claim | `http://identity-service:8000` | code default |
| `IDENTITY_JWT_PRIVATE_KEY_PATH` | RSA private key file (prod) | *(auto-generate)* | code default |
| `IDENTITY_SERVICE_CLIENTS` | Registered service callers | *(none)* | **runtime-secrets** |
| `IDENTITY_WORKLOAD_ISSUER_URL` | Cluster OIDC issuer (prod) | *(none, disabled)* | runtime-secrets |
| `IDENTITY_WORKLOAD_AUDIENCE` | Projected token audience | `identity-broker` | code default |
| `IDENTITY_WORKLOAD_CLIENTS` | SA subject→client mapping | *(none)* | runtime-secrets |
| `IDENTITY_AUDIT_SERVICE_URL` | Audit-service ingest URL (unset = log-only) | `http://audit-service:8000` | runtime-config |
| `IDENTITY_AUDIT_CLIENT_ID` | Audit ingest client id | `identity-broker` | runtime-config |
| `IDENTITY_AUDIT_CLIENT_SECRET` | Audit ingest credential | *(none)* | **runtime-secrets** |

### audit-service

Source: `products/audit-service/src/audit_service/core/config.py`
Config fragment: `shared/platform-ops/gitops/dev-k8s/base/audit-service/runtime-config.env`

| Variable | Purpose | Default | Source |
|---|---|---|---|
| `AUDIT_STORE_BACKEND` | Store backend: `memory` or `postgres` | `postgres` (dev-k8s) | runtime-config |
| `AUDIT_DB_URL` | PostgreSQL connection URL (postgres backend) | in-cluster `postgres` service | runtime-config |
| `AUDIT_INGEST_CLIENTS` | Registered ingest callers (`client_id=secret,...`) | *(none)* | **runtime-secrets** |
| `AUDIT_WORKLOAD_ISSUER_URL` | Cluster OIDC issuer for workload tokens (prod) | *(none, disabled)* | runtime-secrets |
| `AUDIT_WORKLOAD_AUDIENCE` | Projected token audience | `audit-service` | code default |
| `AUDIT_WORKLOAD_CLIENTS` | SA subject→client mapping | *(none)* | runtime-secrets |
| `AUDIT_RETENTION_DAYS` | Retention window for eviction | `30` | runtime-config |
| `AUDIT_MAX_EVENTS` | Hard store-size cap | `100000` | runtime-config |
| `AUDIT_EVICTION_INTERVAL_SECONDS` | Eviction task period | `3600` | runtime-config |
| `AUDIT_EVICTION_BATCH_SIZE` | Batched delete size (postgres) | `1000` | code default |
| `AUDIT_MAX_BATCH` | Max events per ingest request | `50` | code default |
| `AUDIT_EXPORT_MAX_ROWS` | Row cap for the bounded CSV export (SPEC-046); must be positive, truncated exports set `X-Audit-Export-Truncated: true` | `10000` | code default |

### skills-hub

Source: `products/skills-hub/src/skills_hub/core/config.py`
Config fragment: `shared/platform-ops/gitops/dev-k8s/base/skills-hub/runtime-config.env`

| Variable | Purpose | Default | Source |
|---|---|---|---|
| `SKILLS_SOURCES` | Federated source list (JSON: `source_id`, `type` `local`/`git`; local requires `path`; git requires `url`, optional `ref` (default `HEAD`) and `path` — the subdirectory within the checkout to ingest) | two local sample sources + one git source | runtime-config |
| `SKILLS_GIT_TOKENS` | Per-source git tokens (JSON map `source_id`→token, injected into https clone URLs as `x-access-token`) | *(none)* | **runtime-secrets** |
| `SKILLS_SYNC_INTERVAL_SECONDS` | Per-source sync loop period | `300` | runtime-config |
| `SKILLS_COMPOSITION_MAX_SUB_SKILLS` | Composite-wide cap on a `kind: composition` skill's `sub_skills` count; ingestion rejects a composition over it (SPEC-057 R-2). Worst case `cap × GATEWAY_BROWSER_FLOW_MAX_STEPS` = 8 × 20 = 160 unlocked browser writes/run, each still individually signed, audited, receipted and gated once per sub-skill. Must be `>= 1` (`SettingsError` at startup otherwise) | `8` | runtime-config |
| `SKILLS_DATA_PATH` | Working dir for git checkouts | `/var/lib/skills-hub` | runtime-config |
| `SKILLS_STORE_BACKEND` | Store backend: `memory` or `postgres` | `postgres` (dev-k8s) | runtime-config |
| `SKILLS_DB_URL` | PostgreSQL connection URL (database `skills`) | in-cluster `postgres` service | runtime-config |
| `SKILLS_QUERY_CLIENTS` | Registered query callers (`client_id=secret,...`) | *(none)* | **runtime-secrets** |
| `SKILLS_WORKLOAD_ISSUER_URL` | Cluster OIDC issuer for workload tokens (prod) | *(none, disabled)* | runtime-secrets |
| `SKILLS_WORKLOAD_AUDIENCE` | Projected token audience | `skills-hub` | code default |
| `SKILLS_WORKLOAD_CLIENTS` | SA subject→client mapping | *(none)* | runtime-secrets |
| `SKILLS_AUDIT_SERVICE_URL` | Audit-service ingest URL for usage events (empty = emission disabled) | `http://audit-service:8000` | runtime-config |
| `SKILLS_AUDIT_CLIENT_ID` | Audit ingest client id | `skills-hub` | runtime-config |
| `SKILLS_AUDIT_CLIENT_SECRET` | Audit ingest credential | *(none)* | **runtime-secrets** |

### incident-service

Source: `products/incident-service/src/incident_service/core/config.py`
Config fragment: `shared/platform-ops/gitops/dev-k8s/base/incident-service/runtime-config.env`

| Variable | Purpose | Default | Source |
|---|---|---|---|
| `INCIDENT_STORE_BACKEND` | Store backend: `memory` or `postgres` | `postgres` (dev-k8s) | runtime-config |
| `INCIDENT_DB_URL` | PostgreSQL connection URL (database `incidents`) | in-cluster `postgres` service | runtime-config |
| `INCIDENT_WEBHOOK_TOKEN` | Shared bearer for the Alertmanager webhook (empty = intake disabled, 503) | *(none)* | **runtime-secrets** |
| `INCIDENT_QUERY_CLIENTS` | Registered query callers (`client_id=secret,...`) | *(none)* | **runtime-secrets** |
| `INCIDENT_WORKLOAD_ISSUER_URL` | Cluster OIDC issuer for workload tokens (prod) | *(none, disabled)* | runtime-secrets |
| `INCIDENT_WORKLOAD_AUDIENCE` | Projected token audience | `incident-service` | code default |
| `INCIDENT_WORKLOAD_CLIENTS` | SA subject→client mapping | *(none)* | runtime-secrets |
| `INCIDENT_AGENT_SERVICE_URL` | agent-platform chat endpoint for triage turns | `http://agent-service:8000` | runtime-config |
| `INCIDENT_TRIAGE_TIMEOUT_SECONDS` | Triage turn timeout | `120` | code default |
| `INCIDENT_CONNECTORS` | Active connector names (registered: `audit`) | `audit` | runtime-config |
| `INCIDENT_AUDIT_SERVICE_URL` | audit-service ingest URL for the `audit` connector (unset = dispatch skipped) | `http://audit-service:8000` | runtime-config |
| `INCIDENT_AUDIT_CLIENT_ID` | Audit ingest client id | `incident-service` | runtime-config |
| `INCIDENT_AUDIT_CLIENT_SECRET` | Audit ingest credential | *(none)* | **runtime-secrets** |

### Shared (all pods)

Source: `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env`

| Variable | Purpose | Default | Source |
|---|---|---|---|
| `OTEL_ENABLED` | Enable OpenTelemetry push pipeline (traces + metrics + log mirror) | `true` | shared/runtime.env |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP HTTP base URL; exporters append `/v1/{traces,metrics,logs}` | `http://openobserve-router.openobserve.svc.cluster.local:5080/api/default` | shared/runtime.env |
| `IDENTITY_SERVICE_URL` | Identity broker URL (shared) | `http://identity-service:8000` | shared/runtime.env |

The OTLP ingest credential (`OTEL_EXPORTER_OTLP_HEADERS`) is secret material and lives in each service's runtime-secrets Secret, not in this ConfigMap. Provision it with `sync-otel-secrets.sh`, sourcing the OpenObserve root credentials from the luban-bootstrapper repo (`openobserve/secrets/openobserve.env`) at provision time only. Without the header the exporters push anonymously, OpenObserve answers 401, and the pipeline fails open.

## Secret Contracts

Secrets are provisioned as Kubernetes `Secret` objects, never committed to Git.

### `agent-platform-runtime-secrets`

| Key | Purpose | How to Provision |
|---|---|---|
| `AGENTSCOPE_API_KEY` | LLM provider API key | `sync-runtime-secret.sh <profile>` |
| `AGENT_AUDIT_CLIENT_SECRET` | Audit ingest credential for the SPEC-037 execution events | `sync-audit-secrets.sh` |
| `AGENT_SKILLS_CLIENT_SECRET` | Skills query credential for the SPEC-044 skill-draft validation leg | `sync-skills-secrets.sh` |
| `OTEL_EXPORTER_OTLP_HEADERS` | OTLP ingest auth (Basic) for the OTel push pipeline | `sync-otel-secrets.sh` |

### `execution-signing-secret`

| Key | Purpose | How to Provision |
|---|---|---|
| `AGENT_EXECUTION_SIGNING_KEY` | HMAC key signing execution requests and receipts (SPEC-037); the agent-service deployment reads it through an optional `secretKeyRef`, so an absent secret fails mutating resumes closed instead of degrading to unsigned execution | `sync-execution-signing-secret.sh` (generate → reuse ladder; `SKIP_EXECUTION_SIGNING_SECRET=true` opts out) |

### `execution-handoff-secret`

| Key | Purpose | How to Provision |
|---|---|---|
| `EXECUTION_HANDOFF_TOKEN` | Static credential for the internal agent-service → execution-runtime handoff (SPEC-038). Both sides read the same secret: the worker requires it on every handoff (constant-time comparison), and agent-service maps it to `AGENT_EXECUTION_HANDOFF_TOKEN` via an optional `secretKeyRef` — an absent secret fails mutating resumes closed (`worker_unavailable`) instead of degrading to unauthenticated handoff | `sync-execution-handoff-secret.sh` (generate → reuse ladder; `SKIP_EXECUTION_HANDOFF_SECRET=true` opts out); wired into `dev-k8s/deploy.sh` |

### `platform-gateway-runtime-secrets`

| Key | Purpose | How to Provision |
|---|---|---|
| `PLATFORM_GATEWAY_SERVICE_CLIENT_SECRET` | Token exchange credential | `sync-delegation-secrets.sh` |
| `PLATFORM_GATEWAY_AUDIT_CLIENT_SECRET` | Audit ingest credential | `sync-audit-secrets.sh` |
| `PLATFORM_GATEWAY_INCIDENT_CLIENT_SECRET` | Incident query credential | `sync-incident-secrets.sh` |
| `PLATFORM_GATEWAY_SKILLS_CLIENT_SECRET` | Skills query credential (portal Skills proxy) | `sync-skills-secrets.sh` |
| `OTEL_EXPORTER_OTLP_HEADERS` | OTLP ingest auth (Basic) for the OTel push pipeline | `sync-otel-secrets.sh` |

### `identity-service-runtime-secrets`

| Key | Purpose | How to Provision |
|---|---|---|
| `OIDC_CLIENT_SECRET` | Keycloak confidential client secret | Manual or CI |
| `IDENTITY_SERVICE_CLIENTS` | Service client registry | `sync-delegation-secrets.sh` |
| `IDENTITY_AUDIT_CLIENT_SECRET` | Audit ingest credential | `sync-audit-secrets.sh` |
| `OTEL_EXPORTER_OTLP_HEADERS` | OTLP ingest auth (Basic) for the OTel push pipeline | `sync-otel-secrets.sh` |

### `tool-gateway-runtime-secrets`

| Key | Purpose | How to Provision |
|---|---|---|
| `GATEWAY_AUDIT_CLIENT_SECRET` | Audit ingest credential | `sync-audit-secrets.sh` |
| `GATEWAY_SKILLS_CLIENT_SECRET` | Skills query credential | `sync-skills-secrets.sh` |
| `GATEWAY_INCIDENTS_CLIENT_SECRET` | Incidents query credential | `sync-incident-secrets.sh` |
| `OTEL_EXPORTER_OTLP_HEADERS` | OTLP ingest auth (Basic) for the OTel push pipeline | `sync-otel-secrets.sh` |

### `tool-gateway-browser-credentials`

| Key | Purpose | How to Provision |
|---|---|---|
| `credential-sets.json` | Named credential sets for `web.fill_credential` (JSON map `set`→`{"username", "password"}`); mounted at `GATEWAY_BROWSER_CREDENTIAL_SETS`; values never travel through skills, prompts, or tool results (SPEC-049 R-5) | `sync-browser-credentials.sh` (or `BROWSER_CREDENTIAL_SETS_FILE=<path>`) |

### `audit-service-runtime-secrets`

| Key | Purpose | How to Provision |
|---|---|---|
| `AUDIT_INGEST_CLIENTS` | Ingest client registry (`client_id=secret,...`) | `sync-audit-secrets.sh` |
| `OTEL_EXPORTER_OTLP_HEADERS` | OTLP ingest auth (Basic) for the OTel push pipeline | `sync-otel-secrets.sh` |

### `skills-hub-runtime-secrets`

| Key | Purpose | How to Provision |
|---|---|---|
| `SKILLS_QUERY_CLIENTS` | Query client registry (`client_id=secret,...`) | `sync-skills-secrets.sh` |
| `SKILLS_GIT_TOKENS` | Git-source PATs (JSON map `source_id`→token); without it a git source fails auth while others keep serving | `SKILLS_GIT_TOKEN=<pat> sync-skills-secrets.sh` (never committed) |
| `SKILLS_AUDIT_CLIENT_SECRET` | Audit ingest credential for usage events (SPEC-029) | `sync-audit-secrets.sh` |
| `OTEL_EXPORTER_OTLP_HEADERS` | OTLP ingest auth (Basic) for the OTel push pipeline | `sync-otel-secrets.sh` |

### `incident-service-runtime-secrets`

| Key | Purpose | How to Provision |
|---|---|---|
| `INCIDENT_WEBHOOK_TOKEN` | Alertmanager webhook bearer token | `sync-incident-secrets.sh` |
| `INCIDENT_QUERY_CLIENTS` | Query client registry (`client_id=secret,...`) | `sync-incident-secrets.sh` |
| `INCIDENT_AUDIT_CLIENT_SECRET` | Audit ingest credential for the built-in `audit` connector | `sync-audit-secrets.sh` |
| `OTEL_EXPORTER_OTLP_HEADERS` | OTLP ingest auth (Basic) for the OTel push pipeline | `sync-otel-secrets.sh` |

## Runtime Profiles

The agent-service supports pluggable LLM backends through Kustomize profile overlays.
Only one LLM profile is active at a time. Since SPEC-026 the profile label is generic
(`default`) and decoupled from the provider — provider selection is a ConfigMap knob:

| Profile | Provider | Default Model | ConfigMap |
|---|---|---|---|
| `default` | `deepseek` (via `AGENTSCOPE_PROVIDER`) | `deepseek-v4-flash` | `runtime-profiles/default/configmap.yaml` |

Switch profiles with:

```bash
shared/platform-ops/gitops/select-runtime-profile.sh <profile-name>
```

Two non-LLM postures ride alongside the active profile permanently:
`mutating-dev` (SPEC-022 R-3, pod-delete RBAC + `GATEWAY_MUTATING_TOOLS_ENABLED=true`)
and `browser-dev` (SPEC-049 R-7, `GATEWAY_BROWSER_ENABLED=true` + the
chromium-headless-shell sidecar on tool-gateway; SPEC-061 retired the static
sample target it once shipped, so its one allowlisted origin is now the
out-of-band `acme-admin` sample app). Neither is switchable; both merge their env
into `platform-runtime-config`, and the base stays deny-by-default.

The profile's `runtime-secrets.example.env` documents the active provider key plus the
multi-model catalog knobs: every supported provider (`deepseek`, `dashscope`, `openai`,
`luban`) with an `<PROVIDER>_API_KEY` joins the catalog with its curated model series,
and an optional `<PROVIDER>_MODELS=a,b,c` overrides/restricts that series. The `luban`
provider (SPEC-028) covers team-hosted OpenAI-compatible servers (Ollama, vLLM,
llama.cpp): it additionally requires `LUBAN_BASE_URL` (no default endpoint exists) and
ships with an empty curated series, so pinning via `LUBAN_MODELS` or live discovery
supplies the lineup — see the [Luban-Hosted Small Model Guide](luban-llm-guide.md).

Live model discovery (SPEC-027) refreshes each configured provider's series from its
OpenAI-compatible `/models` endpoint: once at startup, then every
`AGENT_MODEL_DISCOVERY_REFRESH_SECONDS` (default 1800). Successful fetches pass the
per-provider filter (dated snapshots and non-chat modalities are dropped, the
provider's default model is always kept), update the last-good caches, and atomically
swap the catalog. On fetch failure the ladder degrades: in-memory last-good →
Postgres-persisted last-good (`model_discovery_cache` table in the sessions database;
Redis gains no new consumers) → curated series. A set `<PROVIDER>_MODELS` stays
authoritative and skips discovery for that provider; `AGENT_MODEL_DISCOVERY_ENABLED=false`
disables discovery entirely. Discovery never blocks chat or startup — every failure is
logged and swallowed.

## Policy Management

The policy bundle controls which roles can perform which actions.

**Canonical source:** `shared/shared-contracts/policies/policy-default.yaml`

**Workflow:**

1. Edit the canonical file
2. Validate against the JSON schema: `make validate-policy`
3. Sync to all consumer locations: `make sync-policy`
4. Rebuild images and redeploy (or re-apply the Kustomize overlay)

**Consumer locations** (must stay byte-identical):

- `products/tool-gateway/src/tool_gateway/policies/policy-default.yaml`
- `products/platform-gateway/src/platform_gateway/policies/policy-default.yaml`
- `shared/platform-ops/gitops/dev-k8s/base/shared/policy.yaml`

See the [Architecture Overview](architecture-overview.md) for the RBAC model and default
policy rules.
