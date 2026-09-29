# Changelog

All notable changes to this repository are documented in this file.

Platform releases follow semantic versioning (MAJOR.MINOR.PATCH): the root
`VERSION` file is the single source of truth, release trains map to MINOR
bumps, and entries accumulate under `Unreleased` until a release closes
them into a versioned section. Version lockstep across products and the
portal is enforced by `make validate-version`.

Versions prior to 0.1.0 were not numbered; Release 0 foundation work and
Release 1 entries are grouped retrospectively under 0.1.0.

## Unreleased

## 0.45.0 — 2026-09-29

Feature release: the R5 observability slice — a first-class LLM
token metric, the platform's domain metrics pushed as OpenTelemetry instruments
so they are dashboard-visible without a scraper, an OpenObserve dashboard suite
as config-as-code, and a gated end-to-end live-check. Delivered under
[SPEC-065](docs/specs/SPEC-065-r5-observability-token-cost-dashboards/spec.md)
(implementing [ADR-0014](docs/adr/0014-domain-metrics-via-otel-push.md)). No new
route, action, contract, schema, audit event type, or execution path; the only
external side effect is R-4's single authorized, billable, read-only model call,
which mutates nothing and is cleaned up. **Cost is deferred** — Stage-0 found
agentscope 2.0.8 exposes no provider-derived dollar cost and the platform has no
price table, so no `agent_llm_cost_usd_total` is emitted. Delivered as v0.45.0
(2026-09-29): the gated live-check's authorized paid leg was run and evidenced at
delivery, closing the slice.

### Added

- **Always-on LLM token metric (SPEC-065 R-1).** `agent-platform` gains a
  `TokenUsageMiddleware` on the supported `on_model_call` hook, recording
  provider-reported usage as `agent_llm_tokens_total{provider,model,direction}`
  (`direction` ∈ {input, output, cache_input, cache_creation}; `model` bounded by
  the SPEC-026/027 catalog with an `unknown` sentinel). Streaming-aware (reads
  usage off the terminal chunk), never estimated, records nothing when a provider
  returns no usage, and carries no session/user/request id. Registered
  unconditionally beside the permission and evidence middleware.
- **Domain metrics pushed as OTel instruments (SPEC-065 R-2, ADR-0014).** Every
  `prometheus_client` domain family across all eight services is additionally
  mirrored to an OpenTelemetry instrument of the same name and bounded label set
  when `OTEL_ENABLED=true`, so it pushes over the existing OTLP pipeline into
  OpenObserve — no Prometheus scraper. Strictly additive: the always-on
  `/metrics` pull surface is unchanged and stays the source of truth with push
  disabled. The mirror lives once in the parity-guarded `core/telemetry.py` and
  fails open.
- **OpenObserve dashboards as config-as-code (SPEC-065 R-3).** Three
  `version: 5` dashboard JSON files under `shared/platform-ops/dashboards/`
  (Service Health/RED, LLM Token Consumption, Governance & Decision Chain; 36
  panels) query the per-metric OpenObserve streams via PromQL.
  `validate_dashboards.py` is wired into `make verify` as `validate-dashboards`
  (the `kustomize build` analog) and cross-references every metric against the
  eight services' `OTEL_MIRROR_FAMILIES` (AST-parsed) so a renamed metric fails
  the gate; `apply-dashboards.sh` imports idempotently by `dashboardId`.
- **Gated observability live-check (SPEC-065 R-4).**
  `shared/platform-ops/e2e/observability-livecheck.sh` reproduces the spike §6
  procedure with three escalating legs: a mocked-I/O proof (default), a read-only
  cluster pre-flight, and a gated **billable** one-turn `deepseek` correlation by
  `trace_id`. The mocked leg runs in the ordinary test suite
  (`test_observability_livecheck.py`, 8 scenarios) and in the `make e2e` list; the
  paid leg is an explicitly gated, operator-authorized step.

### Changed

- **Observability contract and living docs (SPEC-065 R-5).**
  `shared/shared-contracts/observability-conventions.md` records the
  `agent_llm_tokens_total` family and its bounded labels, a "domain-metric OTel
  push" note under Two Surfaces, and a config-as-code dashboards pointer; the
  operator guide (`docs/guides/observability-dashboards.md`) and the
  configuration reference Feature Activation Matrix document the dashboards and
  the R-4 live-check.

## 0.44.0 — 2026-09-27

Feature release: opt-in agent-driven context compression in the agent-platform
kernel, adopting the first of the two agentscope 2.0.8 surfaces that the v0.43.2
dependency refresh pinned but deliberately left unwired. Delivered under
[SPEC-064](docs/specs/SPEC-064-agentscope-compression-and-goal-pipeline/spec.md);
see the
[release note](docs/agentic-aiops-platform/release-notes/2026-09-27-agent-driven-context-compression.md).
No new route, action, contract, schema, audit event type, or execution path; the
capability is default-off, so unset deployments are byte-identical to 0.43.2.

### Added

- **Opt-in agent-driven context compression (`CompressContext`, SPEC-064 R-2).**
  The agent-platform kernel can now register agentscope 2.0.8's `CompressContext`
  tool behind a new `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED` flag (`RuntimeSettings.compress_context_enabled`,
  default `false` → `ContextConfig.compression_tool_enabled`). When enabled, the agent may
  summarize its own working context on demand, reusing the same `_compress_context_impl`
  the threshold trigger already runs; it mutates only `state.summary`/`state.context`,
  which the SPEC-017 agent-state snapshot already persists and secret-redacts. The tool is
  a kernel-local always-allow (`KERNEL_LOCAL_TOOL_NAMES`) because it touches no external
  system, and a startup guard rejects the opt-in unless `AGENTSCOPE_CONTEXT_TRIGGER_RATIO > 0.2`
  (agentscope's `context_buffer_ratio`), preserving the agent-fires-before-threshold ordering.
  The `offloader` is deliberately **not** wired: it would write divergent pod-local context
  copies to the `emptyDir` workspace that the shared Postgres snapshot never sees (split-brain
  on scale-out, loss on reschedule). No new route, action, contract, schema, audit event type,
  or evidence frame — `on_acting` emits only for gateway tools, and `CompressContext` has no
  `gateway_tool_name`. Default-off, so unset deployments are byte-identical to 0.43.2. See
  [SPEC-064](docs/specs/SPEC-064-agentscope-compression-and-goal-pipeline/spec.md) and the
  [spike memo](docs/workspace/agentscope-compression-goal-pipeline-spike.md).

  `GoalPipeline`, the second deferred 2.0.8 surface, is **kept out** (no code): it has no
  platform caller and its executor/verifier loop fails the four-point adoption gate against
  ADR-0011 and the governed dispatch path.

## 0.43.2 — 2026-09-27

Dependency-refresh patch: a routine re-lock of the eight backend products
inside their declared ranges at latest stable, prompted by the AgentScope 2.0.8
release. No manifest range changed — every bump lands inside an existing
caret-capped range — so this is a lockfile refresh, not a contract change. No
new routes, actions, event types, contracts, schemas, audit changes, or
execution paths. See the
[release note](docs/agentic-aiops-platform/release-notes/2026-09-27-dependency-refresh-agentscope-2-0-8.md).

### Changed

- **agentscope 2.0.7.post1 → 2.0.8** (agent-platform; the runtime kernel per
  ADR-0002, so the bump carries the full kernel-verification leg). Adopts
  **none** of 2.0.8's new agent surfaces — `CompressContext` (agent-driven
  context compression), the `pipeline` module (`GoalPipeline`), `A2AAgent`,
  realtime voice, and RAG LLM reranking are all deferred; the first two are
  tracked in `docs/workspace/agentscope-utilization-audit.md` and scoped to
  **SPEC-064** under the four-point adoption gate. 2.0.8 additionally pulls
  `json-repair[schema]`, whose `jsonschema`/`pydantic` requirements reuse
  packages already in the tree (no new third-party package).
  `agentscope-runtime` stays at **1.1.6.post2** (still the latest published
  runtime) and co-resolves cleanly with agentscope 2.0.8.
- **pydantic 2.13.4 → 2.13.5** (pydantic-core 2.46.4 → 2.46.5) across all eight
  products.
- **playwright 1.62.0 → 1.63.0** (tool-gateway).
- Redis client `<7.0` and Elasticsearch client `<9.0` caps stay parked
  (deployed server majors); tool-gateway's Kubernetes client stays `<33.0`.

## 0.43.1 — 2026-09-27

Test-only patch fixing two clock-sensitive operation-document fixtures that
began failing on 2026-09-27, one day after v0.43.0 shipped. No product code,
contract, policy, schema, audit, or execution-path change; the seven products
not under test move on version lockstep only.

### Fixed

- Two agent-platform document tests hardcoded a `created_at` of
  `2026-08-27T…Z`. The operation-document store sweeps rows older than
  `RETENTION_DAYS` (30) on every write, so once the wall clock passed
  2026-09-26 those fixtures aged out of the retention window and the
  listing/ordering assertions saw an empty result
  (`test_legacy_record_degrades_without_summary`,
  `test_list_for_owner_is_owner_scoped_and_newest_first`). Both now derive
  their timestamps relative to `datetime.now(timezone.utc)`, matching the
  existing `test_cap_evicts_oldest_per_owner` pattern, so they are stable
  regardless of run date. The incident-bundle provenance dates and the
  Postgres fake-driver mapping asserts are inert (they never pass through the
  retention sweep) and are unchanged.

## 0.43.0 — 2026-09-26

Crash-safe execution and outcome reconciliation (SPEC-063), per ADR-0013. The
full root `make verify` is green: the real-Postgres failure campaign passed 791
(exit 0) with every product/portal/policy/version/secret gate and clean disposable
teardown; see [delivery evidence](docs/specs/SPEC-063-crash-safe-execution/tasks.md#delivery-closure-evidence),
which also retains the daemon-wedge attempts (V1/V5/V6) and the V4 test-only
fixture fix as honest history. No release tag, registry push, or shared deployment
is implied by this local delivery.

### Added

- Postgres single-use dispatch claims, immutable intent/observation metadata,
  dual execution/approved-call identity protection, and v3 signed run/epoch/expiry
  contracts. Ambiguous commit acknowledgment grants no send permission.
- Owner-scoped, bounded execution recovery in agent, platform-gateway, and portal;
  explicit unknown, late, conflict, and unavailable states. New document digests
  preserve uncertainty while published snapshots remain immutable.
- Real-Postgres multiprocess failure campaign, deterministic crash barriers,
  independent gateway/target counters, and coverage/negative-control gates.
  Root verification now includes portal tests/build and the required campaign.
- Disabled migration/cutover/epoch-rotation tools, bounded worker drain,
  admission/readiness/uncertainty metrics, and operator recovery guidance.

### Changed

- Durable claims replace process-local duplicate authority. Mutations require
  enabled agent/worker/catalog admission and matching epochs; legacy executable
  requests are refused, historical receipts stay readable. The first protocol
  upgrade requires a coordinated mutation-disabled cutover.
- Unknown or unaccepted outcomes stop automatic mutating continuation. Metadata
  replay cannot execute again, reopen a run, reconstruct original output, or
  release a held password. Secret release requires the original validated result
  plus durable agent acceptance and a single-use process-bound permit.
- Request lifetime is bounded to 900 seconds by database time; claim/evidence
  protection lasts at least 30 days after expiry independently of session cleanup.
  At-most-one worker dispatch does not promise exactly-once target effects or
  remote cancellation.

### Fixed

- Cutover wrapper refuses failed scale/wait/inventory and remaining worker/agent
  pods instead of announcing safe replacement; nine local regression cases cover
  the shipped shell and real decision CLI without cluster writes.
- Isolated acceptance's held-secret test uses separate handles for destructive
  wrong-owner probing and legitimate redemption; the original failed run remains
  retained. Corrected S6 passed all five paths with target reconciliation and
  cleanup. Historical 0.42.0 acceptance image provenance is unchanged.

## 0.42.0 — 2026-09-23

Minor release refining **SPEC-062 R-3** delivery timing after a live-test
finding: the portal **Copy password** button appeared the instant
`secrets.generate_password(handoff="portal_copy")` returned — before the bound
reset's HITL approval card was even filed. The reveal now fires on **commit**:
for a gated flow the `secret_delivery` frame is withheld at generation and
released only once the gate is approved **and** its gated mutation executes
successfully, so the button lands on the operator's committed turn. A standalone
generation (no gate follows) still reveals at that turn's end, preserving the
original generate-and-copy flow. On deny, gated-call failure, or expiry the held
delivery is silently burned — no frame is emitted and the handle is **actively
discarded** at the gateway (best-effort, falling back to TTL expiry), so it is
not redeemable even by a direct owner-scoped fetch during the hold window. The
frame shape, portal rendering, redemption path, and
`secret_delivered` audit are unchanged; only emission timing moves (**ADR-0012**,
amended). No wire-format or schema change (agent-stream-event stays title v12).

### Added

- **Reveal-on-commit hold TTL** (`products/tool-gateway`): a new
  `GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS` (default `900` = the 600s HITL
  approval timeout plus the 300s redemption margin) bounds how long a portal-copy
  delivery is stashed, so a password generated before a gated reset survives the
  full approval wait and is still redeemable when the Copy button is revealed.
  The standalone `GATEWAY_SECRET_DELIVERY_TTL_SECONDS` (300) remains the
  redemption window and the buffer's baseline TTL; single-use, owner-scope, and
  expiry-burn are unchanged. Documented in the configuration reference and the
  dev-k8s tool-gateway `runtime-config.env`.

- **Deny-path discard hardening** (`products/tool-gateway`,
  `products/agent-platform`): defense-in-depth over the reveal-on-commit hold.
  `SecretDeliveryBuffer` gains a value-less, owner-scoped, idempotent
  `discard(delivery_id, owner_sub)` — the burn counterpart to `redeem` — exposed
  internally as `DELETE /api/v2/secrets/delivery/{delivery_id}`. On the three
  burn paths (deny, approve-but-gated-failure, park expiry) `runtime_kernel`
  calls `discard_deliveries` with the requester's delegated token, so a held
  handle is destroyed at once rather than left redeemable until the 900s hold TTL
  lapses. A re-park drains onto the new card and returns early, so it never
  discards. The route is oracle-free (204 for found / already-spent / expired /
  wrong-owner / malformed alike, mirroring the redeem route's single-404
  posture), adds no audit vocabulary (the deny is already `confirmation_decided`;
  discard logs a structured INFO line, never the value), and is fail-safe: a
  missing gateway/token or transport error degrades to the expiry burn, since the
  value is inert once the gated reset never commits.

### Changed

- **Deferred emission** (`products/agent-platform`): `ToolEvidenceMiddleware` no
  longer emits the `secret_delivery` frame inline at generation; it buffers the
  delivery handle in a per-stream contextvar (`STREAM_PENDING_DELIVERIES`).
  `runtime_kernel` drains that buffer onto the parked confirmation card
  (`PendingConfirmation.pending_deliveries`, ephemeral like
  `requester_delegated_token` and never persisted to the durable record), flushes
  it as a frame at normal stream end for the standalone case, and — on an
  approved resume — releases it into the resumed sink only when the gated call
  returns success (`PENDING_RELEASE_DELIVERIES`, gated on `EXECUTION_REQUESTS`).
  The deferred frame is persisted under the **original** `turn_index`, so it
  replays to an operator who reloads after the commit without watching the
  resumed stream. A mid-approval restart drops the ephemeral hold and the value
  expires unreleased (fail-safe — no leaked secret, no orphaned button).

## 0.41.1 — 2026-09-22

Patch release hardening the agent-platform default system prompt after a
**SPEC-062** live-test finding. On an imperative operational request ("reset
alice's acme-admin password") the model refused on anti-fabrication grounds —
it had "no record of an acme-admin system, an alice account, or a credential
set" — and never called `skills.search`, so the conversational (no-`skill_id`)
password-reset flow the acme-admin samples document went undemonstrated. The
platform was wired correctly: `skills.search` returned the `ResetAcmePassword`
runbook as the top hit and the operator held every required capability, so the
gap was purely that the model did not search.

The prompt's skill-search trigger, previously scoped to "procedure,
interpretation, or remediation questions", now also fires for **any request to
act on a named system, account, or target** (resetting a password, locking or
recovering an account, restarting or scaling a workload), and an absence of
offhand grounding is reframed as a reason to search rather than to refuse. No
tool, policy, contract, or wire format changes; agent-platform only. Mirrors
the `0.18.1` log-quoting and `SPEC-054 R-2` browser-discipline prompt fixes,
each shipped after a live-run finding and pinned by a prompt assertion in
`test_runtime_settings.py`.

## 0.41.0 — 2026-09-22

Minor release delivering **SPEC-062** (Secure Password Generation and Delivery
Tools), the twenty-fourth R5 slice. It gives the agent two new tool-gateway
primitives: a **read-tier** CSPRNG `secrets.generate_password` (randomness from
Python's `secrets`, never model-invented) bound to a single-source strength
policy, and a **write-tier** `secrets.deliver(channel="email")` outbound sender.
The generated value rides **no** human-readable projection — the retrieval-vs-
masking crux is resolved by redemption-on-click (**ADR-0012**), a narrow
server-mediated secret-*retrieval* path that sits *beside* the SPEC-049 R-5 /
SPEC-055 R-7 no-plaintext posture without excepting it. Generation is disabled
by default (`GATEWAY_SECRETS_ENABLED=false`) and SMTP ships unconfigured/inert in
the base overlay. One new `secrets:deliver` policy action and one new
`secret_delivered` audit event type are introduced; the `secret_delivery` stream
frame is additive (agent-stream-event schema title v11 → v12, stable `$id`).

### Added

- **Secrets connector** (`products/tool-gateway/src/tool_gateway/tools/`):
  `secrets.generate_password(policy="default", handoff="portal_copy"|"none",
  length?, exclude_ambiguous?)` — read tier, `tools:invoke`, no approval;
  `secrets.choice` generation with a Fisher-Yates shuffle and conservative
  entropy accounting, raising short requests to the policy minimum and refusing
  impossible/oversized requests with `INVALID_PARAMETERS`. The raw
  `generated_password` survives the gateway's exact-key `redact_result` gate for
  model use while every copy is masked.
- **Password-policy contract** — canonical
  `shared/shared-contracts/policies/password-policy.yaml` (min length 16, hard
  floor 12, entropy floor 64 bits, four required classes) synced to the packaged
  tool-gateway copy by `make sync-policy`; overrides tighten only. A fail-closed
  loader refuses generation on a missing/unreadable/invalid policy with **no**
  stale or built-in fallback. `validate_password_policy.py` +
  `make validate-password-policy` (added to `make verify`) reject floor/class
  drift, a missing consumer, malformed input, and packaged-copy drift.
- **One-time delivery handoff** (`tools/secret_delivery.py`): a `SecretDeliveryBuffer`
  `Protocol` with in-memory (monotonic TTL + capacity) and Redis (`SET EX` +
  atomic `GETDEL`) backends; wrong-owner/foreign attempts burn the handle and
  share the single unavailable posture with expired/unknown. Portal-copy is
  folded into generation as the default intrinsic handoff.
- **Redemption routes**: authenticated `GET /api/v2/secrets/delivery/{delivery_id}`
  on tool-gateway and a delegated `GET /api/v1/secrets/delivery/{delivery_id}`
  proxy on platform-gateway — canonical-UUID validated, authentication mandatory
  even in the dev posture, no redirects, `no-store`/`no-cache`, destructive
  single-use redemption, sanitized upstream failures, and metadata-only
  `secret_delivered` audit at redemption.
- **External email delivery**: `secrets.deliver(channel="email", password,
  recipient)` — write tier requiring `secrets:deliver` in addition to
  `tools:mutate`, enforced at the gateway before connector execution and
  independently at platform-gateway confirmation admission. Mandatory
  certificate-validated STARTTLS (missing SMTP/TLS config refuses with
  `EMAIL_NOT_CONFIGURED`), exact-address/domain recipient allowlisting (no
  automatic subdomain match), and an out-of-allowlist warning requiring a strict
  boolean `recipient_warning_acknowledged=true` checked before the confirmation
  is claimed. `secret_delivered` fires at SMTP acceptance (not proof of inbox
  delivery), metadata only.
- **Kernel generated-literal masking** (`products/agent-platform`): raw,
  percent-encoded and quote-plus generated literals are harvested per session and
  masked across blocking/streaming/resumed prose, structured output, evidence
  frames, snapshots, error paths and legacy transcripts, while raw model and
  signing arguments stay intact. Knowledge is retained while an agent is cached
  (including compacted contexts); owner deletion clears session caches and
  turn-local literals still protect an in-flight snapshot. The requester's
  delegated token is preserved ephemerally across approval resume/re-park for
  generation only; approved writes retain approver authority.
- **`secret_delivery` stream frame** (metadata-only: `delivery_id`, `channel`,
  `expires_at`, optional recipient) emitted alongside tool results and
  persisted/replayed independently of result-data truncation.
- **`secrets:deliver` action** registered in all three policy bundles
  (platform-admin, approver, operator) with both engines' scenario suites
  updated; **`secret_delivered`** added to the audit vocabulary, service mirror
  and the portal audit filter (drift-guarded).
- **Operator portal**: a one-time **Copy password** control driven by the
  `secret_delivery` frame — explicit click fetches directly to the clipboard with
  no plaintext React state, DOM, or browser storage (only tab-local spent
  markers); expired/unavailable controls stay disabled, and missing auth or
  clipboard support prevents redemption. The email out-of-allowlist warning
  acknowledgment renders in both chat and the approvals inbox.
- **`GeneratePassword` knowledge skill**
  (`shared/platform-ops/skills/platform-runbooks/guides/GeneratePassword.md`)
  citing the policy contract by reference and forbidding restating a generated
  value; the `acme-admin` reset/recovery runbooks gained the generate-and-hand-off
  branch.
- **Configuration** (`GATEWAY_*` on `GatewaySettings.from_env()`): generation
  enablement, policy path/tightening, buffer backend/TTL/capacity/Redis, SMTP/TLS,
  and paired gateway/agent recipient allowlists + strict mode — documented in
  `configuration-reference.md` (Feature Activation Matrix), `tool-configuration.md`
  (tool table, activation checklist, error codes) and `skills-guide.md`; SMTP
  password provisioned by `sync-email-secrets.sh` (never in the ConfigMap).
- **e2e**: `shared/platform-ops/e2e/secret-delivery-demo.sh` (local by default;
  `--live` is an explicit opt-in) registered in `make e2e` and run in local mode
  by `make verify`; a cross-product generation→projection→redemption integration
  test, mocked-I/O execution of the live demo, and three in-memory security
  mutation checks (projection bypass, dropped harvest, weakened owner scope).

### Security

- The generated value is real only in bounded, intentional places (the gateway
  process, the kernel working context, the single-use delivery buffer, and the
  approved TLS SMTP transport) and masked or absent everywhere else. No
  model-side generation, no plaintext in any transcript/title/card/evidence/stream
  frame/audit event/log, and no live email, deployment, browser or OS-clipboard
  use in verification.

## 0.40.0 — 2026-09-20

Minor release delivering **SPEC-057** (Skill Composition — Validated Runbooks of
Single-Target Skills), the nineteenth R5 slice and roadmap row 346's item **(b)**.
It adds a third, additive skill `kind: composition`: an ordered `sub_skills[]`
list of existing published single-target skills that reaches the agent as
grounded guidance for a multi-target runbook. A composition carries **no
authority** (ADR-0011) — it never mints tokens, unlocks flows, or auto-approves a
gate — and each named sub-skill keeps its own human-in-the-loop gate through the
shipped `FlowContext.identity() == (skill_id, origin)` guard plus ADR-0007
re-park-on-rebind, so multi-binding re-park needed **no new enforcement
machinery** and adds no kernel trust state. Skill Format goes **v2 → v3**
additively: a v2 consumer ignores `sub_skills` and is unaffected. There is **no
control flow** (no interpreter, no branch/loop/conditional/retry) and a
composition is **not a transaction** (report-and-stop, re-entry from a named step
derived off existing `execution_records` signed receipts, swept at 30 days). No
new policy action, no new audit event type, no stream-contract change; the
tool-gateway deviation guard and both gateways' skill passthrough are untouched.

### Added

- **`kind: composition`** on the shared skill contract
  (`shared/shared-contracts/schemas/skill.schema.json`, retitled `"Skill (v2)"` →
  `"Skill (v3)"`), carrying an optional top-level `sub_skills[]` array whose
  items are `{ skill_id (required), note (optional ≤ 200 chars) }` with
  `additionalProperties: false`. A composition declares **no** `web_target`,
  **no** `steps`, and **no** `risk_class` of its own, and `sub_skills` items carry
  no sequencing vocabulary — a `note` is a string, never interpreted.
- **`SKILLS_COMPOSITION_MAX_SUB_SKILLS`** (default `8`) — the composite-wide
  sub-skill cap that bounds the per-bound-flow step budget a composition inherits
  (8 × `GATEWAY_BROWSER_FLOW_MAX_STEPS` = 160 worst-case unlocked browser writes
  per run, each still individually gated, signed, audited and receipted). Read in
  `SkillsSettings.from_env` with a fail-fast `SettingsError` below 1, wired
  through the dev-k8s `runtime-config.env` and documented in the configuration
  reference.
- **Two-layer fail-closed validation** in skills-hub: a pure structural
  `_validate_composition` in ingestion (shared by the `/skills/validate` route and
  the `python -m skills_hub.validate` CLI) and a store-consulting
  `_resolve_compositions` pass in `SyncManager.sync_once` that drops a record on
  an unresolved sub-skill or a **nested** composition reference (single-target
  needs no active check — a sub-skill's `web_target` is a scalar, so a resolved
  skill is single-target by construction), appending a `Rejection` to the existing
  `skills_synced` rejected count (no new event type). Cross-source compositions are
  eventually consistent —
  rejected on the cycle before a sub-skill's own source syncs, accepted after.
- **Derived display `risk_class`** for a composition — `write` when any resolved
  sub-skill is `write`, else `read` — computed in the resolution pass and
  **persisted** (reusing the existing top-level field, no new column), so
  `summary()` carries it to the list badge without a per-read computation.
- **Resolved-sub-skill read path**: skills-hub's `get_skill` projects each stored
  `{ skill_id, note }` to a display view adding `resolved_title` and
  `resolved_web_target` looked up from the store (the `search_skills`
  `score`/`excerpt` projection precedent); read-path only, nothing resolved is
  persisted, and both gateways forward the record verbatim.
- **Portal read/viewer surface**: a derived **risk** badge column on the Skills
  catalog (`SkillsView`) and an ordered, read-only **Runbook** sub-skill list
  (title · declared target · note) above the body in `SkillContentViewer`. Phase 1
  ships **no** bespoke composition editor — a composition is authored by hand and
  merged to a skill source through Git like any other skill.
- **`samples/acme-admin/composition/`** — a `kind: composition` runbook
  (`RecoverAcmeAccount`) composing the published `password-reset` (browser write,
  one `flow` card) and `lock-unlock-user` (infra `http.post` write, one `action`
  card) into a mixed browser+infra workflow that parks **2** cards on one session
  (> any single sub-skill's 1), with the house README, WALKTHROUGH, and a
  `demo/demo.sh` (deterministic legs plus an opt-in `RUN_CHAT_LEG=true` live leg),
  wired into `acme-admin/demo-suite.sh` (the mounted sample id set grows five → six).

### Changed

- **Skill Format documented at v3** (`shared/shared-contracts/skill-format.md`):
  a `sub_skills` frontmatter row, a `kind: composition` value, and a "Composition
  skills (v3)" section recording the ordered-reference model, the no-authority and
  no-control-flow invariants, the derived display-only `risk_class`, the
  report-and-stop / named-step re-entry convention, and additivity on a v2
  consumer. The skills-hub schema, ingestion, and store mirrors move in lockstep so
  the `test_contracts.py` property-set and `kind`-enum parity guards stay green.

## 0.39.1 — 2026-09-20

Patch hardening the agent kernel's tool auto-allow posture after the v0.39.0
release. An L3 deep security review of the v0.39.0 train flagged the SPEC-058
R-1 entry that placed the outbound-egress read `http.get` in the kernel's
built-in `DEFAULT_AUTO_ALLOWED_TOOLS`, letting an agent-initiated HTTP GET
bypass the human-in-the-loop card. The finding is defence-in-depth, not a live
vulnerability — the tool-gateway's `http_connector` already enforces a
deny-by-default origin allowlist, refuses loopback/link-local/multicast
destinations even when allowlisted (blocking the `169.254.169.254` metadata
path), validates the scheme, rejects userinfo-bearing URLs, and re-validates
the allowlist against the final post-redirect origin on every call regardless
of the kernel allow-list. This patch nonetheless tightens the default so that
network egress — a different risk class from in-cluster reads — must be opted
into explicitly for HITL bypass. No contract, policy, schema, or audit change.

### Added

- **`AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA`** — a new additive companion to the
  existing replacement-style `AGENT_GATEWAY_TOOL_AUTO_ALLOW`. Where the original
  variable *replaces* the vetted default (the posture the HITL demo relies on to
  drop `k8s.get_pod_logs` and force a card), the `_EXTRA` variable *unions* its
  entries with the resolved set, so an environment can opt a single read-tier
  tool back into auto-approval without restating the whole list and without a
  manual-sync footgun. Naming a mutating tool in either variable remains a
  logged no-op (read-only-by-construction invariant, SPEC-021 R-3). The dev-k8s
  overlay sets `AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA=http.get`, preserving the
  SPEC-058 R-1 "a read-tier `http.get` parks no card" behaviour on the local
  demo cluster while the shipped default stays hardened.

### Changed

- **`http.get` is no longer in the kernel's built-in `DEFAULT_AUTO_ALLOWED_TOOLS`**
  (`products/agent-platform/src/agent_service/services/kernel_middleware.py`). A
  read-tier `http.get` now parks an `action` card for operator confirmation by
  default, matching how every other network-egress surface is treated. `http.post`
  is unchanged: it is write-tier, so the `is_read_only` half of the gate already
  refused it and its single per-action card is the point of the tool. The
  gateway-side SSRF controls are untouched and remain the primary egress boundary.

## 0.39.0 — 2026-09-19

Release train delivering **SPEC-060 — rebasing the `web-checks` browser samples
onto `acme-admin`** and **SPEC-061 — retiring `browser-check-target`,
`InventoryHealth`, and the orphaned credential sets** (the twenty-second and
twenty-third R5 slices), shipped together as one `web-checks` consolidation:
SPEC-060 migrates the surviving samples onto the stateful console, and SPEC-061
removes the now-redundant static target and every one of its consumers. Neither
slice changes product behavior, contracts, policy, or audit, so the train carries
no schema or migration work.

### Changed

- **SPEC-060 — rebased the `web-checks` browser samples onto `acme-admin`**
  (samples + docs only; **no** product code, contract, policy-bundle, or GitOps
  change, so no `VERSION` bump). Executes the retarget SPEC-059 R-2 deliberately
  engineered for: because `acme-admin` serves the same six URL shapes and 28
  element ids the static target did, migrating the surviving samples is an origin
  + credential-set swap plus prose rather than a rewrite. `adhoc-password-reset`
  and `skill-graduation` move under `samples/acme-admin/` (leaf directory names
  preserved, so their skill ids are unchanged) and now drive the stateful
  console. `skill-graduation` is **upgraded** to reseed the store before act 1
  and to prove both resets landed against real store state
  (`/api/users/{alice,bob}` `revision` + `password_changed_at`), with act 4's
  revision asserted higher than act 1's so a genuine replay is told apart from
  leftover authoring state. The approval-model triad (flow ↔ action ↔
  author/graduate) now shares one target that really mutates. The catalog
  (`samples/README.md`, `samples/acme-admin/README.md`), `demo-suite.sh` (six →
  five distinct ids), `demo-lib.sh`, `deploy-samples.sh`, `test_packaging.py` and
  the Studio guide are reframed to match, and the walkthrough cross-links between
  the six samples are repointed. Records that `acme` is the fictional-company
  placeholder (Acme Corp), not the ACME certificate protocol (RFC 8555).
- **SPEC-061 — retired `browser-check-target`, `InventoryHealth`, and the
  orphaned credential sets** (GitOps/config reduction + test fixtures; **no**
  product behavior, contract, policy, or audit change, so no `VERSION` bump).
  Makes the follow-up decision SPEC-060 deferred: now that every browser
  tutorial runs against the stateful `acme-admin` console and the HTTP surface
  is shipped, the static `browser-check-target` mock, its one platform runbook
  (`InventoryHealth`, a `risk_class: write` browser health check whose
  "complements the API-level checks" promise is fulfilled elsewhere by the
  `acme-admin/health-check` sample `CheckServiceHealth`), and its dedicated
  `browser-check-demo.sh` e2e (never in the `make e2e` list) are redundant with
  the `acme-admin` suite that *is* gated. The `browser-dev` profile survives as
  the browser *posture* profile (sidecar patch + CDP-deny NetworkPolicy + env),
  now permitting exactly one origin, `acme-admin`. Five
  `products/agent-platform/tests/` fixtures and one incidental `src/` comment
  example are repointed off the retired origin string (behavior unchanged).
  Reverses SPEC-060's *keep* decision; rides the same v0.39.0 train.

### Removed

- **`samples/web-checks/password-reset/`** — the static-mock reset sample whose
  confirmation page "reports success for any user" is retired, superseded by the
  delivered `acme-admin/password-reset` (which already verifies via
  `http.get /api/users/{u}`). Removes skill id
  `samples/password-reset-resetuserpassword`; the surviving `ResetAcmePassword.md`
  keeps its name (renaming would re-id a shipped skill), its collision rationale
  now historical. The whole `samples/web-checks/` category is gone.
  **`browser-check-target` stays shipped and untouched** for its platform
  consumers — the `platform-runbooks/web-checks/InventoryHealth.md` runbook,
  `shared/platform-ops/e2e/browser-check-demo.sh`, the `browser-dev` allowlist and
  the `admin-portal`/`browser-check-target` credential fixtures — none of which is
  a tutorial sample. *(SPEC-061, in this same unreleased train, subsequently
  retires the target and every one of these consumers — see below.)*
- **`platform-runbooks/web-checks/InventoryHealth.md`** (SPEC-061) — and the
  now-empty `web-checks/` directory — plus its skills-hub ConfigMap generator
  entry and volume mount; removes platform skill id
  `platform-runbooks/web-checks/inventoryhealth`. The `platform-runbooks` README
  keeps its web-check authoring guidance, repointed at the `samples/acme-admin/`
  worked examples.
- **`browser-check-target` static app** (SPEC-061) — the three
  `runtime-profiles/browser-dev/browser-check-target-*.yaml` resources
  (Deployment, Service, pages ConfigMap) and the `http://browser-check-target:8080`
  entry in `GATEWAY_BROWSER_ALLOW_ORIGINS`. `browser-sidecar-network-policy.yaml`
  and the sidecar patch are untouched.
- **`shared/platform-ops/e2e/browser-check-demo.sh`** (SPEC-061) — the manual
  smoke test (not in the `make e2e` list); its browser flow-gate coverage is
  provided by `samples/acme-admin/demo-suite.sh` rung 4, which *is* gated.
- **Two orphaned dev credential sets** (SPEC-061) — `sync-browser-credentials.sh`
  now generates only the `acme-admin` set, dropping `browser-check-target`
  (`svc-check`) and `admin-portal` (`admin`, already emptied of consumers by
  SPEC-060).

## 0.38.0 — 2026-09-17

Release train delivering **SPEC-058 — HTTP service-check tools** and
**SPEC-059 — the `acme-admin` sample application and its single-target skill
suite** (the twentieth and twenty-first R5 slices), shipped together because
two of SPEC-059's four skills cannot exist without SPEC-058's tools; SPEC-059
was slated for v0.39.0 and is pulled in with its dependency. SPEC-058 gives the
platform its **first HTTP surface** — `http.get` (read tier) and `http.post`
(write tier) in a new tool-gateway connector confined to a server-side origin
allowlist that is deny-by-default with redirects halting when they leave it —
closing the gap where "is this service healthy" had to drive a headless browser
to `/healthz` and scrape JSON out of a rendered page, and where the shipped
`InventoryHealth` skill claimed to complement "the API-level checks" that did
not exist. SPEC-059 adds a small FastAPI console that really mutates alongside
the retained static tutorial target whose reset page "reports success for any user",
plus four skills that demonstrate the approval model as a clean **0 / 0 / 1 / 1**
card ladder across both surfaces. There is **no** new policy action (policy is
tier-based, so a read tool needs no bundle edit — `make validate-policy` passing
on an unmodified bundle is itself the assertion), **no** new audit event type,
and **no** stream-contract or Skill-schema change; the other products move on
version lockstep only.

### Added

- **`http.get` and `http.post` (SPEC-058 R-1..R-4)** — a new
  `tools/http_connector.py` registering both tools behind
  `GATEWAY_HTTP_ENABLED`, confined to `GATEWAY_HTTP_ALLOW_ORIGINS` with the same
  discipline `web.navigate` carries for a model-supplied URL: deny-by-default,
  GET redirects resolved and re-checked and halting outside the allowlist
  (max three hops), POST redirects never followed, scheme/userinfo refused,
  and loopback / link-local /
  multicast refused even when listed. A fixed response projection whose header
  allowlist can never carry `set-cookie` or `authorization`; an upstream 4xx/5xx
  returned as a **fact** in the result rather than a tool error, because "the
  service answered 503" is the signal a health check exists to report;
  credentials by `credential_set` reference only with **no `headers` parameter**
  on either tool, so the model cannot supply a literal authentication header.
  `http.post` is write tier, one URL per invocation, a JSON body
  bounded to depth 2 / 32 keys / 4096 bytes, and secret-bearing POST URLs refused
  outright.
- **The `_cr_http_post` change-request formatter (SPEC-058 R-5)** — `http.post`
  parks exactly one `approval_kind: action` card through machinery the runtime
  kernel already derives for every non-browser write, so it arrives with the
  SPEC-054/055/037 approval, masking, signing and audit posture built rather than
  invented; the one new design work is a curated formatter, because the generic
  fallback would render `url: ***` / `body: ***` and turn the gate into approval
  theatre. It names the target and the mutated fields and carries the slice's
  single recorded divergence from SPEC-055 R-7's fail-closed masking (non-secret-
  named scalar body values render). Authentication headers remain reference-only;
  body values still require secret-name and secret-shape masking.
  `KNOWN_SAFE_FIELDS` gains `http.post.url` only, so an HTTP-mutating skill stays
  graduable.
- **`tools/url_redaction.py` shared helper (SPEC-058 R-6)** — `_redact_secret_query`
  and `_SECRET_QUERY_PARAMS` extract out of the browser connector into a shared
  gateway module, with `validate_secret_vocabulary.py`'s textually pinned
  `TOOL_GATEWAY_REL` path constant moved in the **same** commit so the lockstep
  guard never points at a file mid-move.
- **The `acme-admin` sample application (SPEC-059 R-1..R-3)** — the first sample
  to own a container image: a stand-alone FastAPI user-administration console with
  **real state** (in-memory, `replicas: 1` + `Recreate`, a monotonic `revision` on
  every mutation, real 401/404/409, real credential validation) over two parallel
  surfaces — a JSON API and the same six server-rendered page shapes and element
  ids the current static target serves, which is what makes the later rebase of
  the three shipped samples a *retarget* rather than a rewrite. Its
  `/internal/reset-demo` reseed is gated on a header `http.post` structurally
  cannot send, so these HTTP tools cannot reset demo state mid-run. This is a
  tool-surface restriction, not a platform-wide authorization boundary. One
  generated admin password is written into two secret sinks by an extended
  `sync-browser-credentials.sh`. A fresh deployment fails closed if credential
  provisioning is skipped; skipping does not remove an existing secret.
- **`make deploy-sample-app` (SPEC-059 R-4..R-6)** — an out-of-band deploy path
  that reuses the coordinated `IMAGE_TAG` and the `mk/` fragments **without**
  joining `IMAGE_PRODUCTS` (whose loops are hardcoded to `products/$$p`), keeping
  SPEC-050 R-11's tutorial→platform dependency direction: manifests live under
  `samples/`, allowlist entries in the `browser-dev` runtime profile, and
  `dev-k8s/base` names nothing. The companion `deploy.sh` asserts the allowlists,
  the credential set and `GATEWAY_HTTP_ENABLED` in the live config before it exits
  0, so a failed run names the checkbox you missed.
- **The four-skill 0 / 0 / 1 / 1 ladder (SPEC-059 R-7)** — `health-check`
  (`http.get`, read, **zero** cards, the repository's first genuinely card-free
  read-only skill), `user-status` (bound browser read, zero cards, `web_target`
  only), `lock-unlock-user` (`http.post`, write, one `action` card) and
  `password-reset` (bound browser write, one `flow` card), where the read-only
  status skill exists to *verify what the mutating one did* — so a reader sees
  SPEC-054's `action`-vs-`flow` discriminator from both sides and sees that the
  card count tracks *effect*, not surface. Skill ids are named around
  `deploy-samples.sh`'s leaf-dir slug rule to avoid colliding byte-identically
  with the shipped `samples/password-reset-resetuserpassword`.
- **Walkthroughs, demos and guides (SPEC-059 R-8, R-9)** — a `WALKTHROUGH.md`,
  `README.md`, `skill/` document and `demo/demo.sh` per sample plus a
  `demo-suite.sh` that runs all four rungs in order and a cross-skill
  verification (lock over HTTP, then observe `locked` on the rendered console);
  `make e2e` gains the new script. Guides grow a read-only-skills section, a
  four-skill-ladder Studio section and a dev-target note, and a stale
  `skills-guide` bullet claiming `risk_class` requires `web_target` is corrected
  (SPEC-055 R-3 decoupled them; `flow_intent` still requires it).

### Fixed during validation and review

- Added `http.get` to the kernel's default read-tool auto-allow list; the live
  health-check rung exposed that read-tier registration alone did not prevent
  a confirmation card. `http.post` remains non-auto-allowable.
- Masked secret-bearing query values in projected `location` headers, and
  stopped every POST redirect before a second request could execute against
  a URL absent from the approval card. Regression tests pin both boundaries.
- Corrected sample permission names, skill counts, requirement references,
  redirect/body assertions and documentation of the demo reset restriction.

## 0.37.1 — 2026-09-13

Patch closing the in-depth **code and documentation review** that followed the
0.37.0 delivery. The review re-derived all six of SPEC-056's load-bearing
invariants from shipped source rather than from the delivery's own claims and
found every one holding — `session_type` is still written exactly once at birth
with no setter on any store protocol, the list scope is still enforced in the
SQL `WHERE` clause, the gateway still dual-gates on the pre-existing
`session:skill_graduate` with no policy or bundle drift, `mode` still never
reaches the stream, masking or HITL paths, and the OQ-2 backfill still defers
its `authoring_trace_target` reference inside the PL/pgSQL `EXECUTE`. It
surfaced one behavioural regression the split introduced in the portal, plus
three documentation defects of the same class that 0.37.0's own docs pass had
only partially retired. No credential leak, and no contract, policy, schema or
audit change: the stream contract stays at v11 and Skill at v2.

### Fixed

- **An approvals-inbox decision now refreshes the Studio session panel as well
  as Chat's** — SPEC-034 R-2 wired the inbox's decision callback so a decision
  refreshes the session panel immediately instead of at the next 30s poll tick.
  It was written when App owned **one** workspace covering every session;
  SPEC-056 split that into two mode-scoped instances and left the callback
  refreshing only the operation one, so a decision on a *development* session no
  longer cleared the Studio panel's amber **awaiting approval** tag until the
  next poll. The path is reachable, not theoretical: the tag derives from the
  session list's `pending_confirmation` flag, `APPROVAL_DECIDER_ROLES`
  (`approver`, `platform-admin`) is a subset of `STUDIO_ROLES` so every decider
  can own a development session, and `policy_engine.effective_self_approval`
  defaults to *permitting* self-approval at **tier_1** while forbidding it at
  tier_2 — so a decider resolving a tier_1 card on a development session of
  their own fires `onDecisionApplied` in their own browser. Browser mutations
  are tier_2 and were never affected, so the blast radius was one amber tag
  living up to 30s too long: cosmetic and self-healing, with no effect on the
  trust path. Both instances now refresh; `developmentWorkspace.refresh()` is
  inert outside the Studio roles and while signed out, because `refresh()`
  clears its list and returns before fetching when the instance was never
  enabled. A regression test captures the callback App hands
  `useApprovalsInbox` and asserts both stubs' `refresh` fire exactly once per
  decider role, and fails against the previous form.

### Documented

- **The removed in-place promotion no longer survives in code docstrings** —
  0.37.0 corrected the wording in the graduation walkthrough but left two
  copies standing in the agent-platform. `declare_skill_target`'s route
  docstring called itself "the path for a session that *becomes* a development
  session after it was opened", which is exactly the capability R-1 removed; it
  now agrees with the sibling `create_session` docstring that 0.37.0 had
  already corrected — the endpoint serves a *development* session opened
  unscoped, and "declare a target" is not "become a development session".
  `tests/test_skill_graduation.py`'s module docstring repeated the claim. Both
  are docstring-only, and the route has never written `session_type`, which is
  why the wording was harmless enough to survive a delivery review and why it
  was worth removing before someone reads it as a guarantee the code does not
  make. A repo-wide sweep for the phrasing now returns only negated uses.
- **Three `studio-guide.md` claims corrected against the shipped portal** — the
  guide landed in 0.37.0 and three of its statements had drifted from what it
  documents. It claimed the two entries "differ in exactly three things: the
  type of session they create, the session list they show, and the authoring
  controls they offer", taking its "exactly three" from `useSessionWorkspace.ts`
  while naming the wrong third item: the mode fixes the birth `session_type`,
  the list scope and the *active-session key namespace*, whereas the
  authoring-control split is a separate conditional in `ChatView` and the
  namespace was missing entirely — and "exactly" contradicted the guide's own
  seven-row comparison table. It described Chat, Studio, Incidents, Documents
  and Settings as each keeping "their own view of the world", implying five
  workspaces where App creates two and the operation instance is *reused* by
  the other three. And it attributed a missing **Studio** entry solely to a
  missing `session:skill_graduate` grant, missing that `studioVisible` is
  `signedIn && hasAnyRole(...)`, so being signed out hides it too — corrected in
  the prose and in the matching troubleshooting row.

## 0.37.0 — 2026-09-13

Release train delivering **SPEC-056 — Studio, a dedicated skill-development
workspace** (the eighteenth R5 slice). The portal's one **Chat** entry splits
into **Chat** for *operation* sessions and a new **Studio** for *development*
sessions over **one shared chat core** parameterized by a `mode`, backed by an
additive `session_type` discriminator on the session contract that is **fixed at
birth and immutable**. The split closes a live defect — the shift-summary picker
listed every session the caller owned, so skill-authoring work could be
mis-filed into an operational handover — and re-homes SPEC-055's authoring
controls: **Draft as skill** stays in Chat, while **Declare target** and
**Graduate as skill** move to Studio. There is **no** new policy action, **no**
policy-bundle or content-hash change, **no** new audit event type, and **no** new
configuration knob; the stream contract stays at v11 and Skill at v2. Shared
contracts, agent-platform, platform-gateway and the portal are touched — the
other six products (audit-service, execution-runtime, identity-broker,
incident-service, skills-hub, tool-gateway) move on version lockstep only.
**No `samples/` demo ships**: the split adds no new backend capability and no new
trust path, so every criterion is already pinned by the vitest
nav/control/shared-core suite, the agent and gateway pytest, and the
real-Postgres OQ-2 check, and ADR-0008 rule 2 does not bind (R-7). Operator
documentation lands in the portal user guide instead.

### Added

- **The `session_type` birth discriminator (SPEC-056 R-1)** — an additive
  `session_type` enum (`operation | development`, default `operation`) on **both**
  authoritative session contracts, `agent-session.schema.json` and
  `agent-session-list.schema.json`, and on every mirror atomically: the
  agent-platform `SessionRecord` and its three store backends (InMemory, Redis,
  Postgres — including the Postgres DDL), the agent v2 API request/response
  models, the platform-gateway `SessionRecord` / `CreateSessionRequest`, and the
  portal's `SessionSummary` / `SessionDetail` TypeScript interfaces. Both Python
  sides declare the vocabulary once as a named `SessionType` alias rather than as
  three inline `Literal`s (the audit-service `EventType` precedent), so a drift
  guard has one symbol to read per side. The legacy `session.schema.json` is
  deliberately **untouched** — it is the unbound v1 surface and widening it would
  have implied a v1 behaviour change. Omitting the field behaves exactly as
  before, so no existing caller breaks.
- **An enum-value parity drift guard (R-1)** — the property-set-equality
  assertions both contract suites already carried catch a *missing* field but not
  a *diverged vocabulary*: one side could add a third value and every existing
  test would stay green. Each suite now also reads the enum out of the schema and
  compares it to the values its models accept, and a companion test proves the
  guard **fires** by re-validating a doctored schema against a narrowed model —
  the same gap that once let a new audit `event_type` reach ingest unaccepted.
- **The OQ-2 legacy-row backfill (R-1)** — a Postgres-only, nullable
  `ALTER TABLE sessions ADD COLUMN IF NOT EXISTS session_type TEXT` followed by an
  idempotent inference that classifies every pre-existing row exactly once: a
  session that already holds a declared `authoring_trace_target` row becomes
  `development` (defaulting it to `operation` would mis-file it into the very
  picker R-4 exists to protect), and everything else becomes `operation`. The
  inference is **NULL-keyed**, so a re-run finds no row to touch, and it runs
  inside a PL/pgSQL `DO` block with dynamic `EXECUTE` so its
  `to_regclass('authoring_trace_target')` guard is **real** rather than
  decorative: PostgreSQL resolves the relation inside the inference's
  `IN (SELECT … FROM authoring_trace_target)` subquery at parse-analysis time,
  before any predicate is evaluated, so the same guard written as a plain `WHERE`
  clause would have aborted the whole schema bootstrap with `relation … does not
  exist` on a cluster whose SPEC-055 authoring-trace DDL had not run — a hard
  pod-startup failure in exactly the situation the guard exists for. Deferring the
  text into `EXECUTE` moves that resolution inside the `IF`. The real-Postgres-16
  gate check is what caught it: a fake driver never parses SQL, and a text
  assertion on the DDL cannot tell a guard that runs from one that only appears in
  the string, so the unit test is now structural (with `--` commentary stripped,
  the relation name appears only inside the deferred `EXECUTE` text). The
  `operation` fallback stays a plain statement — it references no conditional
  relation and must still leave no row NULL when the inference is skipped. The
  default lives on the Pydantic model, not on the column, which is what leaves
  legacy rows NULL long enough to be inferred; Memory and Redis are ephemeral and
  need no migration. Both row mappers read `session_type or "operation"`
  defensively, so a NULL that somehow survived degrades to operational rather than
  erroring.
- **Studio: a role-gated nav entry over two mode-scoped workspaces (R-2)** —
  `ViewId` gains `studio`, rendered beside **Chat** for
  `platform-admin`/`approver`/`operator` and hidden from
  `developer`/`read-only-observer`/`auditor`, with **Chat** itself unchanged for
  every signed-in role. `STUDIO_ROLES` is defined *equal to* the existing
  `SKILL_GRADUATE_ROLES` rather than as a re-typed literal, so the client nav gate
  and the gateway's dual-gate set cannot drift. App owns **two**
  `useSessionWorkspace` instances — `operation` and `development` — and the
  development instance's polling is gated on `STUDIO_ROLES`, so a non-authoring
  role never issues a development list request at all. The active-session pointer
  is **namespaced per mode** (`…activeSessionId.operation` / `.development`), so
  each entry restores its own last-open session across reloads and a detour from
  Studio into Chat and back loses neither place. Incidents, Documents and
  Settings all stay on the operation workspace, and the synthetic pinned incident
  triage entry is typed `operation`.
- **Server-side `session_type` list scoping (R-2 / R-4)** — an optional
  `session_type` query parameter on the agent v2 list route, forwarded verbatim by
  the gateway and applied **in the SQL `WHERE` clause** as a NULL-tolerant
  predicate (`%(session_type)s::text IS NULL OR COALESCE(session_type,
  'operation') = …`), so an omitted filter is byte-for-byte the legacy query and a
  supplied one narrows server-side. That placement is the point: Chat lists only
  `operation` sessions, Studio only `development` ones, and the shift-summary
  picker — which reads the operation workspace — can never be coerced by a client
  into surfacing authoring work. Ownership scoping is unchanged, so the
  anti-enumeration posture holds.
- **The shift-summary create-path guard (R-4, in scope by plan §9)** — a list
  filter alone leaves the create path open to a hand-crafted request, so
  `shift_summary.build_digest` now raises a new structural
  `DevelopmentSessionRejected` when a coverage list names a `development` session,
  which `create_document` maps to a **400** naming the offending ids — the same
  posture as the existing `UnknownSessionError` / `ForeignSessionDenied`
  rejections. It is checked **after** the foreign gate (so a session the caller
  cannot view is denied as foreign first and its type never leaks) and **before**
  any fact is read (so a request about to be rejected reads nothing). Rejected
  whole rather than silently dropped, which would hide a caller mistake. Shift
  summary only: the incident-report path anchors to an `incident_id`, never takes
  `session_ids`, and is untouched. The comparison is an explicit
  `== "development"`, so a legacy NULL row reading back `operation` is never
  falsely rejected.
- **A route-level dual-gate on opening a development session (R-6 / OQ-1)** — the
  gateway's `create_session_route` still enforces `session:create` on every
  request and **additionally** enforces the existing `session:skill_graduate` when
  the body's `session_type` is `development`, following the SPEC-043/045
  route-level dual-gate precedent. The gate lives at the gateway because that is
  the only place holding roles — the agent v2 API sees an `X-User-ID` and nothing
  else. A non-authoring role holds `session:create` but not
  `session:skill_graduate`, so it can no longer open a dead-end Studio session it
  could never graduate. This adds **no** new policy vocabulary, **no**
  `policy-default.yaml` / `policy-scenarios.yaml` change, **no** bundle
  content-hash bump and **no** new audit event type — `make policy-diff` reports
  **zero** new grants, pinned by a test that fails if the action set or the
  role→action mapping moves. The birth type rides the existing `session_created`
  log line as a discriminator, never a secret.

### Changed

- **One ChatView, parameterized by `mode` (R-5)** — Studio is **not** a second
  chat surface. `ChatView` gains a `mode` prop that selects exactly three things:
  which authoring controls are visible, the birth `session_type`, and the list
  scope — and the last two are properties of the workspace instance App hands in,
  not of anything the component computes. `mode` is deliberately **not** threaded
  into the SSE stream adapter, the secret-masking renderer, the change-request
  projection, or the HITL confirmation path, so there is no code path on which the
  two entries could disagree about what an operator is approving. A regression
  test renders a fixed transcript — a markdown reply, a `tool_call`/`tool_result`
  pair, and a pending change-request card carrying a masked secret — in **both**
  modes and asserts the transcript surface's `innerHTML` is **byte-identical**,
  with a companion test asserting the session header *does* differ so the
  comparison cannot pass vacuously. A divergence fails the suite.
- **The authoring controls move to their right homes (R-3, Design B)** — an
  `operation` session shows **Draft as skill** and neither Declare-target nor
  Graduate; a `development` session shows **Declare target** + **Graduate as
  skill** and not Draft. There is **no** "Move to Studio" and no conversion in
  either direction, in the UI or in the store: `session_type` is written exactly
  once, at creation, and the `SessionStore` protocol deliberately exposes **no
  setter** for it — the Postgres upsert's `session_type = EXCLUDED.session_type`
  sits in the *expired-reclaim* branch only, where reclaiming a dead row is a
  fresh creation, and the live-row `WHERE` guard makes the whole `DO UPDATE` a
  no-op, which is the immutability boundary. The SPEC-055 declare-target route —
  the one place an operator re-scopes a live session — writes the authoring-trace
  target row and never this field, so declaring a target on an operation session
  cannot make it a development one. `session_type` is likewise **decoupled** from
  `skill_target` and never inferred from it: a development session may carry no
  target at all, and inferring the type from a declaration would re-couple a birth
  property to an inert field.
- **Chat's create affordance is now one-click; Studio's is the target dialog
  (R-3)** — the develop-as-you-go opener leaves Chat's session panel entirely and
  becomes Studio's, and its dialog's target is now **optional** (per R-2's "may
  name a `skill_target` at birth"): open the session unscoped and use **Declare
  target** later, and graduation reports that declaration as *fitted to the trace*
  rather than as the scope the session acted under. The dialog's OK button is no
  longer disabled on an empty target.
- **The Documents shift-summary picker reads the operation-scoped workspace
  (R-4)** — `CreateDialogProps.workspace` is now always the operation instance, so
  the picker's options are the server-scoped list rather than a client filter of an
  unscoped one, and its help copy says plainly that Studio sessions are never shift
  material and a hand-crafted request naming one is rejected. A test asserts the
  picker never calls `listSessions` itself — the scoping is the workspace's, not
  the dialog's.
- **antd v6 `Spin tip` → `description` (drive-by)** — the new `ChatView` suite is
  the first test to render the whole component, and the portal's zero-tolerance
  antd deprecation guard (SPEC-042 R-2) failed the file on `Warning: [antd: Spin]
  tip is deprecated`. Two pre-existing call sites — the app's startup spinner and
  the transcript loader — now use `description`, which antd 6.6.2 documents as the
  replacement. Rendering is unchanged; the guard had simply never been reached.

### Documented

- **A Studio section in the portal user guide (R-7)** —
  `docs/guides/portal-user-guide.md` gains a `## Studio` section beside `## Chat`
  carrying the Chat-vs-Studio mental model as a table (session type, session list,
  create affordance, session-header actions, whether it feeds a shift summary),
  plus the birth-fixed / no-conversion rule, the optional target-at-birth dialog
  and its declare-later path, the refusal-as-modal graduation outcome, per-entry
  last-open session memory, and the dual-gate. `## Finding Your Way Around` now
  names the role-gated Studio item (and Documents, which the Workspace bullet had
  been omitting), `## Sessions` records that the panel lists only its own entry's
  type *enforced server-side rather than filtered in your browser*, the
  Draft-as-skill bullet is scoped to Chat, `## Documents (Workspace)` gains a
  "Studio sessions are never shift material" bullet, and the "What your roles
  unlock" table gains a **Studio** column.
- **The authorization matrix records the Studio gate (R-6)** —
  `docs/agentic-aiops-platform/authorization-matrix.md` names the split, the
  additive immutable discriminator, and the development-session dual-gate on the
  existing `session:skill_graduate` action, stating explicitly that it adds no new
  policy action, no bundle change and no new audit event type.
- **No new ADR, no configuration change** — `docs/adr/README.md` is unchanged:
  ADR-0009 stays `accepted` (Studio re-homes its declare-target and graduate
  controls with the behaviour and trust model unchanged) and the ADR-0008
  requirement-to-test gate is satisfied by this delivery's task mapping.
  `docs/guides/configuration-reference.md` is likewise verified **unchanged**
  rather than edited: the split introduces no new knob.

## 0.36.3 — 2026-09-11

Patch closing the in-depth *documentation* review that followed the 0.36.2
code review, plus two low-severity code-quality items re-derived from the
credential-masking module while re-reading it. No credential leak, no
behaviour change, and no contract, policy, schema, or audit change: the
stream contract stays at v11 and Skill at v2. The review found the shipped
tutorial docs — three walkthroughs, three demo scripts, two skill files, the
samples README — accurate on every load-bearing claim (the fifteen `web.*`
tools and their 9-read/6-write split, the 20-step budgets and both env-var
names, the `skill_graduate` grant, the OIDC redirect mechanism) and surfaced
only the small drifts recorded below. This release also carries the cluster
build/deploy batched out of 0.36.2, so the masking fixes from both patches go
live together.

### Changed

- **`prose_redaction._secret_shape_patterns` caches its deferred import** —
  the resolver reads the pinned secret-shape vocabulary
  (`skill_draft.REDACTION_VALUE_PATTERNS`) through an import deferred to call
  time to keep a real circular dependency inert. It sits on the streaming hot
  path — `StreamingProseRedactor.feed` reaches it three times per delta via
  `_shape_hold`, `_match_spans`, and `redact_assistant_text` — so it now
  resolves once into a module global and returns the cached tuple thereafter.
  The tuple is immutable for the process lifetime and the deferral is
  unchanged (the first call still lands at runtime), so behaviour is
  identical; a regression test poisons the source after the first call and
  asserts the cache is returned rather than re-read, which fails against the
  uncached form.

### Documented

- **`prose_redaction`'s module-docstring hold limit now names the anchor
  hold** — the "Known accepted limits" entry for `StreamingProseRedactor`
  listed only harvested literals, shapes already present in the buffer, and a
  URL still arriving. The 0.36.2 fix added a fourth guarantee — a pinned
  shape *still arriving* is held by its `SHAPE_ANCHORS` prefix up to
  `SHAPE_HOLD_MAX_CHARS` back — which the class docstring already described
  but the module docstring did not. The two now agree, including the residual
  cap: past 512 chars a large multi-line PEM key is best-effort in the stream
  and falls back to the durable transcript.
- **Sample evidence wording corrected from `web.snapshot` to `web.extract`**
  — the password-reset walkthrough's Step 6 summary and both demo scripts'
  evidence banners called the `#reset-status` success read a "snapshot",
  contradicting the same files' detailed evidence sections: a `web.snapshot`
  enumerates interactive elements only, and the status line is a plain
  `<p role="status">`, so the success sentence is legitimately absent from
  every snapshot and is read with `web.extract`. Three sites reworded.
- **The 0.36.2 release note's deploy state reflects the batched deploy** —
  it described a standalone `0.36.2-dev-k8s-<sha>` rebuild that the decision
  to batch the deploy into this release superseded; it now says so, and the
  release-notes index entry agrees.
- **Known limitation: the generated repowiki overstates the Identity Broker
  surface** — three IDE-generated articles under the repowiki's Identity
  Broker API reference fabricate a user-management CRUD surface
  (`/identity/register`, `/identity/profile`, `register_user`,
  `update_user_profile`, a `UserProfile` class, a `user.updated` event) that
  the broker does not implement: its real surface is twelve routes (auth,
  token, JWKS, exchange/refresh, health, and `identity/normalize` +
  `identity/me`), with user management delegated to Keycloak. The repowiki is
  a regenerable cache, so hand-edits revert on the next regeneration; this is
  recorded rather than patched, and the routes and `token_service.py` remain
  the source of truth.

## 0.36.2 — 2026-09-11

Patch hardening batch closing an in-depth code review of the credential-masking
surface 0.36.1 introduced — `services/prose_redaction.py` and the two
`redact_secret_query` twins. Where every 0.36.1 entry closed a defect *observed
in a live run*, these seven were *found by reading the new code*, then
reproduced against it before being fixed: six are edges where a credential
still reaches a human-readable or persisted surface, and the seventh is the
opposite failure — an over-mask that destroys a non-secret word. Each is pinned
by a regression test confirmed to fail against the unpatched code (36 pre-fix
failures across the two products). No contract, policy, schema, or audit
change: the stream contract stays at v11 and Skill at v2.

### Fixed

- **A credential in a URL's userinfo is masked, in both query-redactor twins
  (SPEC-049 R-5)** — `redact_secret_query` (kernel `secret_params`) and its
  gateway twin `_redact_secret_query` opened with `if not parsed.query: return
  url`, so a secret carried in the *userinfo* — `scheme://user:password@host`,
  the shape of a database DSN, which frequently has no query string at all —
  was returned untouched and re-serialized into results, evidence, and the
  audit trail. Both now mask `parsed.password` in the netloc by a single
  first-occurrence replace that preserves every non-secret byte exactly (no
  re-encoding, matching the segment-wise query rewrite), and the empty-query
  early return is gone so the userinfo is masked whether or not a query is also
  present. The two copies stay lockstep, as `validate_secret_vocabulary.py`
  requires of the vocabulary they share.
- **A non-HTTP DSN is recognised as a URL in prose, and its userinfo
  harvested** — the prose-layer twin of the gap above. `URL_TOKEN` matched only
  `https?://` or `www.`, so a `postgres://admin:pw@db/app` DSN the model echoed
  sailed straight through the URL layer and `_secret_query_values` harvested
  nothing from it. The scheme is now any RFC-3986 scheme
  (`[a-z][a-z0-9+.\-]*://`, case-insensitive), and `_secret_query_values`
  harvests the userinfo password — quoted and unquoted — on the same footing as
  a query value, so an assistant restating a DSN credential bare still meets
  the exact-literal layer.
- **A pinned secret shape split across stream deltas is held, not emitted in
  pieces** — `StreamingProseRedactor` held a URL split across deltas (0.36.1)
  but a *pinned shape* split the same way — a PEM `-----BEGIN…` header, a JWT
  `eyJ…`, a `Bearer`/`Basic` token, an AWS `AKIA…` id — was published in pieces
  no later buffer re-forms into a match, so `redact_assistant_text` never saw a
  complete shape and the credential leaked to the live stream; the durable
  transcript, which masks complete text, still caught it. The class docstring
  had *listed this as a known limit* ("a shape that has not finished arriving
  is not recognised … would need unbounded lookahead"). The redactor now holds
  a tail that is, or opens with, one of the five shape anchors until its
  pattern completes or `flush` releases it, capped at `SHAPE_HOLD_MAX_CHARS =
  512` so a false anchor (`Bearer token expired`, where `token` is too short to
  match) stalls the stream only briefly and a shape longer than the cap falls
  back to the transcript's unbounded guarantee. The anchors are the leading
  literals of the pinned `skill_draft.REDACTION_VALUE_PATTERNS`, not a third
  vocabulary, and a test streams one canonical example of each shape so an
  anchor cannot go stale against its pattern silently.
- **An uppercase URL scheme split across deltas is held** — `URL_TOKEN` is
  `re.IGNORECASE`, so the match layer redacts `HTTPS://…`, but `_scheme_hold`
  compared the raw buffer tail against the lowercase `URL_SCHEME_STARTS`, so an
  uppercase scheme split across deltas (`… to HTTPS` | `://…`) published
  `HTTPS` before the `://` arrived and the URL was never recognised. The held
  tail is lowercased before the comparison, so the case the match layer already
  accepts is the case the hold layer protects.
- **A navigation error masks the secret Playwright interpolates into its
  message (SPEC-049 R-5)** — `web.navigate`'s exception path passed `str(exc)`
  straight to `make_error_result`, and a Playwright navigation error
  interpolates the target URL, which for the password-reset demo carries
  `?newpw=<value>` and for a DSN-style target could carry it in the userinfo.
  That message rides into the tool result, the evidence frame, and the audit
  trail, so the secret left in plaintext on the *error* path even though the
  success path masks it. The message now goes through `_redact_secret_query`
  first; the fix is kept at the navigate call site rather than in the shared
  `make_error_result`, which has no URL context to redact.
- **A credential whose length is met only by its trailing sentence punctuation
  is still masked** — `is_credential_literal` stripped sentence punctuation
  *before* applying the `CREDENTIAL_MIN_CHARS` length gate, so a valid
  eight-character credential the operator ended with a sentence `!` or `.`
  (`Secret1!`) was cut to seven and rejected, leaving it unmasked in the
  assistant's restatement. The gate now runs on the token as written; the
  character-class test still runs on the stripped core, so surrounding
  punctuation never counts toward either budget.
- **A `key=value` token is not harvested whole, so the secret's *name*
  survives** — the one over-mask in the batch, and the opposite of a leak.
  `credential_literals`'s secret-name heuristic harvested whole whitespace
  tokens, so `newpw=TempPass123!` went onto the literal list *including its
  key*; the `KEY_VALUE_SECRET` pass had already harvested the value on its own,
  so the effect was purely to destroy a non-secret word — an assistant writing
  "the `newpw=***` field" collapsed to "the `***` field", losing the one token
  that said what the field was. The heuristic branch now skips a token
  `KEY_VALUE_SECRET` matches; the value side stays covered by that pass.

## 0.36.1 — 2026-09-11

Patch hardening batch. Every entry closes a defect observed in a live run
against the dev-k8s cluster — most while browser-testing the two password-reset
samples end to end — and each is pinned by a regression test confirmed to fail
against the unpatched code. No contract, policy, schema, or audit change: the
stream contract stays at v11 and Skill at v2.

One theme dominates. A credential an operator types into the chat reaches six
human-readable surfaces, and at 0.36.0 only two masked it: `web.navigate`'s
result (SPEC-049 R-5) and a change-request card's arguments (SPEC-055 R-7).
Four entries below close the rest, following that path — the gateway's other
tool results, then the kernel's evidence frame and minted session title, then
the model's own prose — and are followed by a HITL expiry defect and two
browser-tool correctness fixes.

### Fixed

- **A secret-bearing query value is masked in every browser tool result, not
  only in `web.navigate`'s (SPEC-049 R-5)** — `_redact_secret_query` was called
  from exactly one place, so every other browser tool reported
  `entry.active_target.url` raw. Navigating is only the *first* result carrying
  the URL: the browser then sits on it while the runbook snapshots, clicks
  through, and screenshots it, and each result re-serialized it. Live evidence
  from a bound password-reset flow — the `web.navigate` frame reported
  `...&newpw=***` while the following `web.click` frame reported
  `...&newpw=TempPass-2026%21` in both `data.url` and the derived
  `data_summary.url`, persisting the plaintext into the evidence store. All
  nine emission sites now mask: `_step_result` (shared by `web.click`,
  `web.type`, `web.select`, `web.upload_file`, `web.fill_credential`), plus
  `web.snapshot`, `web.screenshot`, `web.hover`, `web.evaluate`, `web.scroll`,
  `web.switch_frame`, and the two paths that build their own data dict rather
  than calling `_step_result` (`web.press_key`, and the `URL:` header line
  inside the snapshot text), the entry-based ones through a new `_evidence_url`
  helper that carries the rationale once. The page still holds the real value —
  only the reported copy is masked — so nothing about what reaches the target
  application changes, and the runbook's existing claim that the gateway
  redacts `newpw` from every result became true for the steps after navigation,
  which it previously was not. `PostNavigateRedactionTests` pins the plaintext
  really is in the live page URL first, so the absence assertions cannot pass
  vacuously.
- **A typed secret is masked in the `tool_call` evidence frame and in the
  minted session title** — two persisted *and* rendered surfaces that neither
  SPEC-049 R-5 nor SPEC-055 R-7 reaches. The kernel emits the arguments the
  model chose *before* the gateway is ever called, so gateway redaction cannot
  see them, and R-7's `_redact_pending_parameters` is gated on `approval_kind
  == "action"` and reads the parked payload rather than this frame — which
  streams to the portal's evidence panel and persists into the evidence store.
  The session title is minted by `mark_session_turn` from the first user
  message, the one credential carrier no tool-side redactor sees at all,
  because the operator typed the password into the chat rather than into a tool
  argument; it renders in the workspace sidebar and the session header and — an
  approver's inbox listing a pending card by its session title — in front of a
  second identity. Live evidence from both walkthroughs: the flow run's
  evidence panel showed `newpw=TempPass123%21` in the `web.navigate` parameters
  and the ad-hoc run's `newpw=TempPass-2026!`; the flow sidebar title carried
  the whole password, while the ad-hoc one carried its first four characters
  because the 80-char cap bit the secret in half rather than removing it. The
  evidence frame gets a third masking posture,
  `secret_params.redact_evidence_parameters`, whose divergence from the other
  two is forced by what the frame is for.
- **Credentials are masked in chat prose, for both roles** — the fourth path a
  typed credential travels, and the one 0.36.0 left open: the model reads the
  value in its own prompt and writes it back out. A live run of the ad-hoc
  reset sample ended turn 1 with "worth flagging: the temporary password
  `TempPass123!` is now in this chat transcript", rendered verbatim underneath
  a sidebar title reading `... to ***`. The defect is that incoherence — two
  projections of one conversation disagreeing about whether the value is
  secret. A new `services/prose_redaction.py` is the fifth application of the
  SPEC-049 R-5 posture and absorbs the title-masking machinery verbatim
  (`session_service` loses 98 lines and now calls `redact_user_text`), so the
  heuristic is declared once and the six existing title tests pass unchanged —
  what proves the move was behaviour-preserving. The vocabulary stays where
  `validate_secret_vocabulary.py` pins it, read through a deferred accessor
  rather than a module-level import. Heuristic detection runs on user-authored
  text only: `SECRET_PARAM_SUBSTRINGS` includes `token`, `session_id`, and
  `signature`, ordinary words in an operations reply, so running it over model
  output would mask the session id in "the delegated token for ses-c8171f20
  refreshed" — precisely the evidence-destroying false positive
  `secret_params.is_secret_value` documents rejecting. `redact_assistant_text`
  is therefore narrower: the pinned shapes, the URL query layer, and an exact
  match against literals the operator typed, where a false positive is
  impossible by construction because the string matched is one the operator
  wrote. Masking lives in the projection rather than in its callers, so neither
  can forget it, and `extract_transcript` harvests every user turn first so a
  cross-turn echo is caught — the model restating in turn five a password typed
  in turn one. Verified byte-identical to whole-text redaction across 6
  scenarios × 11 chunk sizes, after tests found three real bugs in the first
  implementation: `urlsplit` called on a whole *sentence* both ate prose and
  missed the bare credential, a URL split across deltas leaked because
  `[^\s<>"']+` cannot match a buffer ending at `https://`, and a split *scheme*
  (`o htt` | `ps://`) needed its own hold, since once `htt` is emitted no later
  buffer can ever match a URL.
- **The held prose tail is released before the tool frames that follow it
  (SPEC-035 R-2)** — a regression the entry above introduced, caught only by a
  browser. Holding back `max(len(literal)) - 1` characters of each streamed
  chunk keeps a secret split across deltas from being published in pieces, but
  the hold outlived the text segment it belongs to: the kernel drains the
  tool-evidence queue at the *top* of each loop iteration, before
  `normalize_event`, so when a tool call follows narration the previous
  segment's tail is still inside the redactor and rides out in the same delta
  as the next segment's opening text. The portal opens a new paragraph on the
  first delta after a tool frame and applies it to the whole frame, so the
  break landed one hold-length early and mid-word — `procedu` | `re precisely`
  — while the real segment boundary lost its break and sentences ran together
  (`procedure.Navigation`). A live run showed six such breaks and five lost
  separators. No text was lost, and that is why every text-equality test passed
  while the rendered reply was corrupt: concatenating the deltas reproduces the
  durable transcript character for character, so a misplaced *frame boundary*
  is invisible to a concatenated assertion. In both `stream_events` and
  `resume_confirmation` the drain now lands in a list and, when non-empty,
  flushes the prose tail before the tool frames are yielded; the flush stays
  conditional because flushing on every event would defeat the hold entirely,
  and the post-loop safety-net flush moves ahead of the final drain. The tests
  reproduce the portal's accumulator rather than concatenating deltas —
  `_portal_render` mirrors `useChatStream`'s `segmentBreak` handling — which is
  the only way the misordering is observable. Reverting only the kernel fails
  all three at position 43 of a 56-character segment (43 = 56 − 13, the hold
  length) with the mask still intact: the leak never returned, only the
  paragraphing broke.
- **An expired confirmation settles the turn, and interrupts the agent that
  parked it** — an expired approval card left the operator staring at a spinner
  that never resolved, which read exactly like a hung agent. Two independent
  defects, found in a live run (card parked 16:22:53, decided after the TTL
  elapsed, 410 Gone at 16:33:31, then ~6.4 minutes of polling with no further
  chat turn). In the portal, the 410 branch of `decide()` cleared
  `turn.confirmationPending` without setting `turn.completed`; `ChatView`
  derives `loading = !completed && !confirmationPending && !error`, so that
  combination is true forever, and the reply text is only produced once
  `completed` — a permanent spinner with no reply and no error. The 409 branch
  shared the omission, and worse: the unstructured-409 case is *retryable* with
  the card still pending, so clearing there also dropped the session panel's
  awaiting-approval tag from a card the operator could still answer.
  `confirmationPending` is now cleared only in the terminal branches (410 and
  the SPEC-031 R-4 already-resolved race), which also set `completed`, and the
  retryable branch leaves the turn parked. In the kernel,
  `expire_confirmation()` called `ensure_agent(session_id, None)`, leaving
  `model_id` at its default; `_normalize_model_id(None)` returns
  `settings.provider` — a bare provider name — which never equals a session
  pinned to a concrete model, so `ensure_agent` evicted and rebuilt the agent
  on *every* expiry, deterministically. The rebuilt agent restores persisted
  memory but not the in-flight parked reply, so the `UserInterruptEvent` landed
  on nothing: of 42 `session_evidence` rows for that session, none contain
  `interrupted` and none reference the expired call id, so the docstring's
  promise to close the parked calls did not hold and the transcript ended
  mid-procedure with no closure.
- **Browser calls are serialized per session so parallel fills cannot race
  (SPEC-049 R-1)** — one chat session has exactly one browser context and one
  active page, but nothing serialized the calls driving it. The kernel runs
  every tool call a model emits in a turn concurrently, so two `web.*` calls
  for one session interleaved on one page and on the shared entry state that
  goes with it (`refs`, `frame_stack`, `filled_values`, `flow.steps_used`).
  Playwright's `fill()` focuses its element and then inserts text into whatever
  holds focus at that moment, so two concurrent fills can both land in the same
  field and the loser reports `success` with its value silently absent. Live
  evidence from the flow demo's chat leg: the two `web.fill_credential` calls
  for the admin login completed 1.4 ms apart, both `status: success`, and the
  snapshot taken afterwards showed the username field carrying no value at all
  — the credential set was correct, so the value was lost in flight rather than
  mis-sourced. The target's legacy-SSO auto-submit waits for both fields, so it
  never fired, the flow stalled before its single gated write, and no card was
  parked. A per-session-key `asyncio.Lock` now covers the whole of each call,
  applied at the registration boundary so `register_tools` wraps all fifteen
  tools and a tool added later inherits the guarantee instead of having to
  remember to opt in. The lock lives on the pool rather than on the session
  entry: taking it from the entry would mean resolving the session first, which
  creates a browser context — that changed the behaviour of a call refused
  before it ever reached the pool, and would let refused calls consume the
  `GATEWAY_BROWSER_MAX_SESSIONS` budget and evict live sessions — and the first
  pair of calls for a key needs the same guarantee the later ones do.
  `sweep_expired` prunes locks neither held nor backed by a session, so the map
  stays bounded by the live sessions. The tradeoff is honest: a queued call now
  waits behind a slow one, up to the 30 s cap against the caller's own 30 s
  budget, so a pathological pairing can surface as a `TIMEOUT` — retryable,
  where the race produced a false success.
- **Six model-facing `web.*` descriptions no longer assert the pre-SPEC-054
  contract (SPEC-054 R-2)** — they still told the model a write is permitted
  only "inside a bound, approved write-class web-check flow". R-2 relaxed that:
  an unbound interaction is no longer a hard deny, it re-checks the live origin
  and the signed envelope's authority provenance, so an ad-hoc write executes
  once its per-action card is approved. The module docstring and the in-code
  gate comments already documented the relaxation; only the description strings
  the model actually reads were stale, which made the ad-hoc reset sample
  unreachable through chat — the agent refused before issuing a single `web.*`
  call, quoting the description text back. `web.click`, `web.type`,
  `web.select`, `web.press_key`, and `web.upload_file` now name both permitted
  paths and state that the live origin must stay on the allowlist;
  `web.evaluate` already carried correct wording and is untouched.
  `web.fill_credential` is corrected in the opposite direction: it is read tier
  by design, because filling a field submits nothing and needs no operator
  confirmation — the write gate lands on the submitting interaction.
- **The kernel and the ad-hoc sample now treat an unbound write as a gated
  path, not an attack** — live testing showed the platform wiring was correct
  and the models would not use it. On the ad-hoc sample the agent read the
  runbook, then refused: a skill's steps are only authoritative when the flow
  is bound, `newpw` is "a credential-handling anti-pattern", and an instruction
  to stay unbound is "exactly what a prompt-injection or privilege-escalation
  attempt looks like". On the flow sample it stalled asking whether it may
  proceed. Either way no card was parked, so SPEC-054's R-2/R-3 per-action seam
  and its R-7 masking went undemonstrated and the automated ad-hoc chat leg
  failed with "no per-action card parked". This was not model-specific: a
  stronger model produced zero tool calls across both turns and demanded the
  URL and `skill_id` outright. The model was substituting its own refusal for
  the operator's decision — the control that actually protects the system,
  since refusing pre-emptively parks no card, shows no approver a change
  request, and records no signed receipt. `DEFAULT_SYSTEM_PROMPT` now names
  both platform-enforced authorization paths and states that neither is a
  bypass, so the model attempts the step and lets the platform gate it. The
  refusal boundary is kept explicit and narrowed to what is genuinely the
  model's call: an instruction that contradicts the runbook, an origin off the
  allowlist, or a request to invent evidence. Consent to a mutation is not.

### Documented

- **The reset walkthroughs send the tier-2 approval to a second identity** —
  both told the reader to click Approve on the parked card in the same chat
  that requested the reset. Mutating execution carries a tier-2 approval
  requirement (`decided_by_roles`: approver, platform-admin), so that click
  answers 403 and the card stays parked; for an operator the reason is
  `not_a_designated_approver`, because the decider-role check runs before the
  self-approval one and the operator role holds no decider role. The
  walkthroughs described a step that cannot succeed. Step 5 now names the
  identity to sign in as and asks for a second window signed in as the approver
  up front, mirroring the framing the skill-graduation walkthrough already
  carried against the same policy bundle.
- **The reset samples point at the tools that can actually produce the
  evidence** — two claims the platform cannot satisfy, both grounded in source
  rather than in the runs alone. Both runbooks' step 8 told the agent to take a
  `web.snapshot` to confirm the "Password for <user> has been reset
  successfully." message, but `_build_snapshot` enumerates interactive
  selectors only and the status line is a plain `<p role="status">`, which that
  list does not include — a snapshot cannot show it. Step 8 names
  `web.extract`, which can. Separately, both walkthroughs told operators to
  verify the result by opening `/admin/users/?reset=...` in their own browser;
  the target is a static mock with no server-side state, so those pages render
  their own query parameters back and report success for any value, including a
  user absent from the fixed three-row roster. Relabelled as not evidence, and
  pointed at what is: the post-click `web.extract` of `#reset-status`, emitted
  by the target's own submit handler, the accompanying screenshot, and the
  signed receipt.
- **The ad-hoc walkthrough pins the expected card count at exactly one** — it
  described a per-action card in the singular but never stated the number, so a
  run that parked two looked like a pass and a run that parked one looked like
  a failure. It is the reverse. The target's login page auto-submits on a timer
  once both credential fields are filled, and step 4 of the runbook says not to
  click Sign in — authentication is read tier and needs no write. The reset
  form pre-fills from the URL but deliberately does not auto-submit, so Confirm
  reset is the procedure's single write-tier interaction. Two cards mean the
  agent clicked Sign in anyway: a redundant gated write, not a stronger gate.
- **Both walkthroughs state the prose and transcript masking guarantee, and its
  boundaries** — they documented only the sidebar title as masked, which was
  true when written and has been incomplete since the prose fix above: the live
  stream and the durable transcript now mask too, for both roles, so a reader
  following Step 4 sees their own turn come back as `... to ***` on reload with
  the doc silent on why. Each also records the two boundaries rather than
  letting the guarantee read as absolute. The operator's own bubble is
  plaintext while the turn is live, because it is rendered from the composer in
  their own browser and never from a stream frame — the only kernel frames that
  echo the message are the unconfigured and provider-error fallbacks, which
  mask it first. And the value stays real in the agent's context at rest,
  because the model needs it to perform the reset: masking is a property of
  every human-readable projection — title, transcript, live stream, cards,
  evidence — not of the machine input the reset runs from.

## 0.36.0 — 2026-09-09

### Added

- **Develop-as-you-go skill graduation (SPEC-055)** — the **C** phase of the
  operator-approved A→B→C HITL redesign and the implementation of **ADR-0009**
  (the seventeenth R5 slice). An operator who troubleshoots a live problem
  through chat, approving each mutation as it parks (SPEC-054), can now
  **graduate that session** into a replayable executable-flow skill: the
  platform captures the ordered, secret-safe parameterized step sequence as a
  by-product of each already-approved *and* already-signed mutation,
  re-validates the captured blast radius, and emits a **draft for a human to
  review and merge** into their own skills repo — never an auto-published
  skill, preserving SPEC-044's "the platform drafts, humans merge". Once
  merged and ingested, the flow replays under SPEC-051's **one** HITL gate
  with every write still individually signed, persisted, audited, receipted,
  and gateway-guarded. Shared contracts, agent-platform, skills-hub,
  platform-gateway, tool-gateway and the portal are touched;
  execution-runtime is **verify-only** (a browser replay envelope is
  byte-identical to a hand-authored flow envelope, `approval_kind: "flow"`).
- **Durable authoring-trace store and its capture seam (SPEC-055 R-1/R-2)** —
  a new `AuthoringTraceStore` with `InMemory` and `Postgres` backends records,
  per session, the ordered position, the canonical tool name, the
  **secret-safe parameterized** arguments, and *references* to the originating
  `execution_id`/`confirm_id` — it never duplicates the signed receipt or the
  outcome, which stay in `execution_records`. Every schema field exists on
  **both** backends (the skills-hub `web_target`/`risk_class` lesson: a field
  on one backend only is silently dropped in production). Its lifecycle is
  `draft → graduated | discarded` with a retention policy **independent of**
  the 30-day execution sweep, so a session authored now is still graduable
  after its receipts are gone. Capture happens at the same resume/receipt seam
  that writes `execution_records`, at **both** signing sites (the per-action
  one and the flow-unlock one), so a mixed troubleshooting session yields one
  coherent ordered trace; read-tier calls are never captured, and because
  *being signed is not being a mutation* the per-action site is gated on the
  platform's single risk→action mapping (`tools:mutate`) and so fails
  **closed** on an unclassified tier. Capture is best-effort: a trace-store
  failure degrades to "no graduation candidate" and never blocks the
  mutation's execution or its receipt path. Deleting a session cascades its
  trace, terminal or not. Two new knobs — `AGENT_AUTHORING_TRACE_MAX_STEPS`
  (per-session step cap, default `100`) and `AGENT_AUTHORING_TRACE_IDLE_DAYS`
  (idle-GC of still-`draft` traces, default `180`, `0` disables; a terminal
  trace is never swept).
- **Executable-flow skill class (SPEC-055 R-3)** — the skill contract advances
  **Skill v1 → v2** additively: an optional `kind`
  (`knowledge | executable_flow`, absent = `knowledge`) and an optional ordered
  `steps` list of `{tool, args, expect?}` whose `args` carry credential-set
  **references**, never literals. `risk_class: read|write` is now accepted
  **without** a `web_target`, so a non-browser mutating skill (one that runs
  `k8s.*`) can declare that it mutates — the explicit mechanism the operator
  asked for, mirroring a tool's risk attribute rather than inferring
  mutating-ness from a browser declaration. skills-hub ingestion validates the
  class on the existing `validate_document` path SPEC-044 drafts against
  (`risk_class: write` required unconditionally for an executable flow; a
  `web.*` step still requires a `web_target`; credential references must
  resolve to named credential sets) and rejects a malformed one, and
  `skill_store` carries `kind TEXT` + `steps JSONB` on **both** backends. A
  knowledge skill with no `kind`/`steps` validates exactly as today, so no
  existing skill breaks. `shared/shared-contracts/skill-format.md` advances
  v1 → v2 alongside the schema, since it is the human-readable half of the same
  contract and still documented the rule R-3 removes.
- **Graduation with blast-radius re-validation (SPEC-055 R-4)** —
  `POST /api/v1/sessions/{session_id}/skill-graduate` assembles the
  executable-flow draft **deterministically** from the trace, with no model
  call and no facts-only skeleton fallback: it renders what the session
  actually did, or it refuses. `revalidate_blast_radius` runs *before* the
  draft exists and re-applies at graduation the guards the tool-gateway applies
  at replay — the step budget (`AGENT_SKILL_GRADUATION_MAX_STEPS`, default
  `20`), every **observed origin** inside the declared target's origin, a
  write-class declaration with no read-tier step in it, and no unresolved
  credential placeholder — plus a graduation-only **fifth** guard that refuses
  an argument *shaped* like a secret literal. That one is the only guard
  reading a shape rather than a fact the trace records, and it over-catches
  deliberately (a `web.select` option reading `Basic Authentication` is refused
  too, and cannot be told apart from a real `Authorization` value at this
  layer): a false refusal costs an operator a re-author, a false accept
  publishes a credential into the one artifact a human merges into a
  repository. A trace that fails answers `409` naming **every** guard that
  refused and the steps responsible, rather than only the first — reporting one
  would send the operator back for a second round-trip.
  "Target/origin" is two *recorded* things rather than one inferred one: the
  **declared target** (`authoring_trace_target`, one row per session) is the
  web target the operator names when opening a develop-as-you-go session,
  declared *before* mutating so it is an authorization scope rather than a
  claim fitted to the trace afterwards, and the **observed origin**
  (`authoring_trace.flow_origin`) is what the gateway reported each captured
  mutation actually landed on, recorded at the receipt seam and only for a
  `succeeded` result — corroborating a failed write's intended URL would let a
  mutation that never happened count toward graduation. A step with no
  observed origin is *unverified*, not drifted, and refuses. The declaration is
  stored as origin **and path** (a path narrowing is part of the scope
  `bind_flow` enforces, so collapsing it would silently widen the graduated
  skill to every path on the host) with query, fragment and `user:password@`
  userinfo stripped by `skill_target_scope` — a target pasted from an address
  bar is exactly where a session token rides, into a table that outlives every
  receipt.
- **One new policy action and one new audit event type (SPEC-055 R-4 / OQ-3)** —
  `session:skill_graduate` gates graduation and is deliberately **not** folded
  into `session:skill_draft`: the artifact declares `risk_class: write` and a
  machine-readable replay step list rather than knowledge prose, so it is a
  higher trust level and is separately authorized. It follows the
  operational-role grant pattern of its authoring siblings —
  `platform-admin`, `approver` and `operator` hold it; `developer`,
  `read-only-observer` and `auditor` receive the standard audited policy 403 —
  and one grant covers both graduated-session entry points (the chat header's
  **Graduate as skill** and the mid-session **Declare target** route).
  Declaring a target at session *birth* rides `session:create` alone, because
  it is inert: it grants nothing and only narrows what a later graduation may
  emit, so dual-gating it would refuse session creation over an inert field.
  Each export is recorded once as a `skill_graduated` event whose `details`
  carry the session, the mode, the step count, the `web_target` scope in force
  and the declaration-ordering verdict; the declare-target route is
  deliberately unaudited at the gateway (a declaration is a scope, not an
  operational act) and `session_created` records only a boolean
  `skill_target_declared` flag rather than the URL, so `skill_graduated` is
  where a reviewer learns which origin a graduated flow is bound to.
- **Skill-graduation sample (SPEC-055 R-6)** — a new
  `samples/web-checks/skill-graduation/` tutorial (`README.md` +
  `WALKTHROUGH.md` + `demo/demo.sh`) drives the whole loop against the same
  admin portal as its two siblings: author a session of individually-approved
  mutations, graduate it, merge the draft by hand, then replay the merged flow
  under **one** gate and compare the two sessions' card counts side by side —
  collapsing N per-action cards into one flow gate is the whole point of
  graduation. It is the only web-check sample that ships **no `skill/`
  directory**, deliberately, since the skill is the artifact the demo
  *produces* and a hand-written one would beg the question; consequently
  `deploy-samples.sh` cannot discover it, so act 3 patches the
  `skills-samples` ConfigMap directly under the same `<sample-leaf>-<file>.md`
  key convention and the `cleanup()` trap removes that key on exit (a
  write-class executable flow left behind would be indistinguishable from a
  properly merged one). Its `demo.sh` runs six deterministic legs plus four
  opt-in chat acts per ADR-0008, and the two sibling demos' chat legs stay
  byte-identical and green.

### Changed

- **A graduated flow replays under one gate, and its step list is never an
  input to that gate (SPEC-055 R-5)** — replay needed **no new executor**: once
  ingested, a graduated executable flow is an ordinary `web_target` +
  `risk_class: write` skill and binds through the existing SPEC-051 path
  (`_observe_flow_binding` → `_record_flow_approval` → `_sign_flow_execution` →
  `build_flow_request`), parking one `flow`-kind card whose subsequent writes
  are each individually signed and receipted. Its `steps` list is the replay
  contract the *agent* follows under the single gate, never an input *to* the
  gate — were it one, a skill author could widen their own blast radius by
  writing a longer step list. That indistinguishability is now guaranteed
  structurally twice over: `bind_flow` reads only
  `web_target`/`risk_class`/`title`/`description`/`flow_intent` and takes its
  budget from the gateway's `GATEWAY_BROWSER_FLOW_MAX_STEPS` knob rather than
  from `len(steps)`, and `FlowState` declares no `kind`/`steps` field at all,
  so `to_dict()` emits a fixed envelope and `FlowContextStore.record` drops
  anything else. Credentials resolve **at replay time** from the named
  credential sets a step references, so a graduated skill is shareable
  precisely because it carries no literal secret. Executable-flow writes join
  **no** auto-allow list, and the gateway deviation guard (origin allowlist,
  declared `risk_class`, step budget) bounds a replayed write identically to a
  hand-authored one — a replay past budget or off-allowlist fails closed.
- **Operator-portal graduation entry points (SPEC-055 R-4)** — the chat header
  gains a role-gated **Graduate as skill** action beside the SPEC-044 draft
  button, plus a mid-session **Declare target** route for a session opened
  without one, and a session created with a target surfaces it. The graduated
  draft opens in the SPEC-045 preview pattern (rendered Markdown ⇄ raw source,
  a mode badge, download), because the draft *is* the ephemeral response — the
  platform persists nothing server-side for a human to merge later.
- **The deferred OQ-2 infra binding stays deferred** — because today's flow
  binding is browser-specific, a non-browser (`k8s.*`) executable flow's steps
  park **per-action** under SPEC-054 R-2 rather than collapsing to one gate.
  That is the asserted safe fallback, not a gap: it fails safe, joins no
  auto-allow list, and the generalized binding is anchored to its own
  follow-up train in `delivery-roadmap.md`.

### Fixed

- **Change-request masking now fails closed (SPEC-055 R-7)** — the projection
  SPEC-054 R-3 shipped masked by name and fell back to a generic path that
  failed **open**, so a secret under an off-vocabulary key projected as
  plaintext. `secret_params.should_mask` is flipped to *mask unless positively
  known safe*, with a new curated per-tool `KNOWN_SAFE_FIELDS` allow-list for
  the fields that may render verbatim (`k8s.delete_pod` name/namespace,
  `web.select` value, `web.fill_credential` credential_set/field,
  `web.press_key` key, `web.upload_file` filename), and `_generic_fields`
  inherits the same posture. This closes a gap SPEC-054 recorded and deferred,
  not a regression it introduced.
- **No plaintext secret on the durable record, the stream frame, or the portal
  expander (SPEC-055 R-7)** — for an `action`-kind card the raw `parameters`
  values are now redacted **in place** (keys preserved, secret-bearing values →
  `***`) beside the `change_request` projection, so nothing plaintext persists
  in `confirmation_records.pending_calls`, rides the `confirmation_request`
  frame, or renders in the "Technical details" expander, which now presents the
  masked projection. `flow` and legacy cards are unchanged. This is the other
  half of the same recorded SPEC-054 deferral (its Non-Goal "No masking of the
  raw parameters already persisted on the durable record" + OQ-5), and it ships
  with **no contract change** and a byte-identical signed `args_digest`: the
  digest is computed at resume from the in-memory `PendingConfirmation`
  (`build_requests` re-parses `tool_calls`), never from the persisted JSONB or
  the frame, and a parked confirmation never survives a restart — so masking is
  a pure display + persistence projection.
- **`web.evaluate.expression` joins the opaque-value vocabulary (SPEC-055 R-2)** —
  arbitrary JS can read a masked secret off the page and can *be* the mutation
  (`document.querySelector('#pw').value = '<literal>'`); it is write-tier, in
  `BROWSER_WRITE_TOOLS`, and `_cr_web_evaluate` already refused to project it
  on a card, so without this entry the trace projection was the one place a
  JS-embedded literal survived — into a store that outlives every receipt. The
  nesting walker now takes the tool name so per-tool opaque fields hold below
  the top level too.
- **The flow auto-signer now enforces its own browser-write scope (SPEC-055
  R-5)** — `_sign_flow_execution`'s contract is "auto-sign one unlocked
  *browser* write", but what made that true was its single gated call site:
  calling the signer directly with `k8s.scale_deployment` under a live browser
  flow authority returned a full signed envelope, a durable execution record
  and an `execution_requested` audit event for a mutation no operator decision
  covered. Not reachable in production as it stood, which is precisely the
  problem — the invariant rested on a call site staying disciplined. The
  `BROWSER_WRITE_TOOLS` guard is now inside the signer, so the scope is
  enforced by the function that declares it.
- **The skill-graduation sample now matches the platform it exercises
  (SPEC-055 R-6)** — the `dev-k8s` browser live check that closes this release
  found three defects in the sample and none in the platform, so the shipped
  images are unaffected. Its act-1 prompt asked the model to click "Sign in" on
  a page whose legacy-SSO auto-login hides the form and navigates away within
  100 ms of both credential fields being filled, so that click could only ever
  fail on a detached element; the model recovered and finished both resets, but
  the failed write left a trace step with no observed origin, and graduation
  refuses an unverified step — R-4 behaving as specified against a prompt that
  guaranteed it would fire. Act 3 read the merged skill back with a single
  un-retried `GET` against the service it had just restarted, and `rollout
  status` returning does not mean the Service endpoints have finished
  propagating: the gateway answered `502` "skills hub unavailable", its honest
  mapping of a transport error, reproducibly on the first request and never on
  the second. That call is now bounded-retried on `502`/`503` alone, so a `404`
  — a real answer about the skill — still fails at once. And the walkthrough's
  step 1 sent readers to sign in on a localhost port-forward, where sign-in
  cannot round-trip: the identity-broker starts every login at
  `OIDC_REDIRECT_URI`, which makes the canonical portal origin the only one
  that works. The two sibling web-check walkthroughs carry that same stale
  instruction and predate this spec, so they are flagged rather than changed
  here.

## 0.35.0 — 2026-09-07

### Added

- **Action-level HITL approval and the change-request confirmation card
  (SPEC-054)** — makes **action** approval first-class beside **flow**
  approval. An explicit `approval_kind: flow | action` discriminator on the
  `confirmation_request` frame and the durable record declares a card's kind
  rather than inferring it from ambient session state — the structural fix
  behind the v0.34.1 SPEC-051 R-6 headline-leak patch, with `flow_summary`
  present iff the kind is `flow` on the same kernel branch so a card's kind
  and its headline can never disagree. Every action card becomes a
  secret-masked **change request**: a display-only `{summary, fields[]}`
  projection assembled as a *sibling* of `parameters` (never inside), so
  `canonical_digest(parameters)` and the signed `args_digest` stay
  byte-identical while the approver reads a plain-language intention with
  decision-relevant fields (secrets masked to `***`) promoted out of the
  collapsed "Technical details" expander. The card `message` is now computed
  once at park time and persisted on the durable record, so the approver inbox
  and a re-loaded owner transcript render exactly the card the live stream
  showed. Stream contract v9 → v11 (retro-fitting the v10 clause SPEC-053
  shipped but never recorded and declaring the latent `display_hint` on
  `pending_calls.items`); additive `execution-request.schema.json` change. No
  new policy actions, no new audit event types.
- **Unbound per-action browser-write sample (SPEC-054)** — a new
  `samples/web-checks/adhoc-password-reset/` tutorial drives the same admin
  password reset as `web-checks/password-reset` but **ad-hoc, with no bound
  flow**, so each mutating browser action parks its own per-action
  change-request card. The runbook deliberately declares no `web_target`, so a
  flow cannot bind (`SKILL_NOT_WEB_FLOW`) and the unbound path is
  platform-enforced regardless of model behavior — the unbound counterpart to
  the bound-flow one-gate sample. Its `demo.sh` exercises the path per
  ADR-0008.

### Changed

- **Unbound browser writes park per-action instead of hard-denying
  (SPEC-054 R-2)** — the tool-gateway's `BROWSER_FLOW_NOT_BOUND` hard-deny is
  relaxed so an ad-hoc browser interaction on an allowlisted origin parks as a
  per-action signed gate (N unbound writes → N cards; there is no flow-unlock
  on the unbound path), extending ADR-0007 without reversing it. The
  relaxation ships **together with** the replacements that keep it fail-closed:
  the kernel clears `FLOW_CONTEXTS`/`FLOW_APPROVALS` wherever the gateway
  clears its own binding, and every signed envelope declares its authority
  provenance under **ADR-0010** — a discriminator stamped inside the HMAC by
  whichever builder signs, forwarded by the execution-runtime worker as
  untrusted-as-identity correlation data, and enforced one-directionally by
  the gateway with a new `BROWSER_FLOW_AUTHORITY_STALE` refusal (a declared
  kind can only ever add a refusal, never remove one). Read-tier
  `web.fill_credential` joins the relaxation so unbound credential entry stays
  reference-only instead of being pushed toward `web.type` with a literal
  secret in the arguments, the card, the durable record, and the audit trail.
- **Secret-parameter vocabulary lockstep gate (SPEC-054)** — a new
  `validate_secret_vocabulary.py` leg joins `make verify`, textually comparing
  the agent-platform and tool-gateway secret-parameter tuples (the
  `validate_version.py` pattern, never import-based, fail-closed) and failing
  on drift in either direction, so the two masking vocabularies the
  change-request projection relies on cannot silently diverge.

### Fixed

- **Re-parked confirmation cards are owned by the session requester, not the
  approver (SPEC-054 R-2)** — the live dev-k8s exercise of the unbound
  per-action sample surfaced a defect in the N-card path R-2 introduces. When
  an approver's decision resumes a turn that then parks *another* per-action
  card, the confirm-resume passed the approver's identity as the resumed
  turn's `user_name`, so the new card was attributed `owner_user_id =
  <approver>`. The platform-gateway's SPEC-030 R-3 tier check then saw
  `owner == approver` and blocked that same approver from deciding the next
  card with a `self_approval` 403 (tier_2 forbids self-approval) — so a second
  unbound write could never be approved by the approver who cleared the first,
  contradicting R-2's "N unbound writes → N approvable cards". It is newly
  reachable only because R-2 relaxed unbound writes from a hard
  `BROWSER_FLOW_NOT_BOUND` deny into a per-action park, so a resumed turn could
  park again at all. `resume_confirmation` now takes the session owner
  separately (`owner_user_name`, threaded from `session.user_id` by the confirm
  route) and attributes any re-parked card to the requester, while the approver
  stays the decider of the card they answered (resolution, signed executions,
  flow authority). Kernel + route only — no contract, policy, audit, or portal
  change; pinned by three regression tests (kernel re-park owner attribution,
  the ownerless-session default, and the confirm-route wiring).

## 0.34.1 — 2026-09-06

### Fixed

- **Browser-flow headline no longer leaks onto non-browser approval cards
  (SPEC-051 R-6)** — a live test of v0.34.0 showed a session that first
  bound a browser flow (`web.navigate(skill_id=…)`) and later parked an
  unrelated non-browser mutation (`k8s.delete_pod`) rendering that action
  card with the lingering flow's headline (e.g. "Reset User Password"). The
  card's `flow_summary` was attached whenever a flow context was bound in
  the session (`FLOW_CONTEXTS`), with no check that the *parked batch*
  carried a browser write, so it rode ambient session state rather than the
  batch. It is now gated on `_tool_names_have_browser_write` — the same
  write-tier predicate (`BROWSER_WRITE_TOOLS`) that arms flow-unlock
  authority in `_record_flow_approval`, extracted into one shared helper so
  card framing and unlock authority can never disagree. A non-browser or
  read-tier-only batch falls back to action-level rendering; a browser-write
  batch still carries the headline. Because the durable record is built from
  the same gated summary, the approver inbox and a re-loaded owner
  transcript are corrected too. Kernel-only — no contract, policy, audit, or
  portal change; pinned by `TestConfirmationFrameFlowHeadline` (non-browser,
  read-tier-only, and browser-write batches).

## 0.34.0 — 2026-09-05

### Added

- **Skill content viewer (SPEC-052)** — the portal Skills view (SPEC-019
  R-4) listed ingested skills but showed only their envelope metadata
  (id, title, source, risk class), never the authored `body`, so an
  operator could not read a skill to validate where its single
  browser-flow HITL gate lands (the transparency goal motivating
  SPEC-049/051). A new read-only rendered/raw viewer opens from each
  Skills-table row, reusing the SPEC-045 R-5 preview pattern (rendered
  Markdown ⇄ raw source toggle, mode badge). Because the skills list
  payload omits `body` by contract, the viewer fetches it through a new
  platform-gateway single-skill detail proxy
  (`GET /api/v1/skills/{skill_id:path}`) that reuses the existing
  `skills:read` action and skills-hub's existing `get_skill` endpoint
  (which already returns `body` and emits `skill_retrieved`). No new
  policy actions, no new audit event types, no shared-contract change;
  skills-hub is unchanged.
- **Skill-declared step intent on the browser confirmation card
  (SPEC-053)** — realizes the follow-up SPEC-051 R-6 explicitly deferred
  ("structured per-step plan rendering … needs a skill-format change
  touching the skills contract and ingestion path"). One additive optional
  frontmatter key, `flow_intent` (≤ 200 chars, requires `web_target`),
  authors in plain language what the flow's single gated mutating step
  achieves. Because SPEC-051 R-1 collapses a mutating browser flow to
  exactly one HITL gate, a single card-level intent maps 1:1 to the card
  (no brittle per-click matching). It rides the existing SPEC-051 R-6
  `flow_summary` path verbatim and under the same name — skill record →
  gateway `bind_flow`/`FlowState` → `web.navigate` `data["flow"]` →
  kernel `FlowContext.summary()` → `confirmation_request` frame + durable
  `ConfirmationRecordModel` → portal card — where `ConfirmationCardView`
  renders it as a plain-text decision line above the demoted
  DOM/technical detail. `flow_intent` is display-only and never a
  security input: the deviation guard and SPEC-037 signed execution are
  unchanged, and skills that omit it render exactly as today. Additive
  contract change (`skill.schema.json` plus the two `flow_summary`
  schemas; stream contract v9 → v10) touching the skills-hub
  ingestion/store path; no new policy actions, no new audit event types.
  The password-reset sample skill declares a `flow_intent` so the demo
  card leads with the plain decision line.

### Changed

- **Humanized browser approval card (post-live-test quick win)** — the
  per-call block on the browser-flow confirmation card keeps the tool name
  and risk tier but now renders the parsed DOM element label as prose
  (`.confirm-call-hint`) instead of a raw code block, and folds the raw
  argument JSON behind a native "Technical details" expander mirroring the
  evidence card's "Parameters" expander. Nothing is dropped — the full
  parameters stay one click away and still travel to the audit trail
  unchanged. Portal-only, no stream-contract change.
- **Clarified post-approval progress (post-live-test quick win)** — the
  post-approval activity indicator moves from a bare animated-dots bubble
  below the evidence to a labelled spinner row ("Agent is working…")
  rendered under the reply and above the tool-evidence panel, so the
  operator reads "work is continuing" ahead of the still-growing
  evidence. Portal-only, no stream-contract change.

### Fixed

- **DocumentsView parallel-suite flake** — the test `flush()` helper
  awaited a bare `setTimeout(0)` (a single macrotask tick not wrapped in
  `act()`); under full-parallel CPU contention React 19 deferred the
  resolved mock promise's re-render to a later macrotask, so post-flush
  assertions intermittently read the pre-update DOM. Awaiting the timer
  inside `act()` drains the pending promise, the scheduler hop, and the
  commit, so every call site reads the settled tree regardless of worker
  load. Test-only; no runtime change.

## 0.33.1 — 2026-09-05

### Fixed

- **Live HITL confirmation card omitted the browser-flow headline
  (SPEC-051 R-6)** — a live password-reset test on v0.33.0 showed the
  operator's confirmation card render without its flow *description*
  initially, while the approver inbox card showed it, and the operator's
  own card only gained the description after the decision. Both views
  share the portal's `ConfirmationCardView` and read
  `flowSummary.description`, so the divergence was in the data each
  received, not the rendering. The approver inbox and the
  post-decision/reload card read the **durable** `ConfirmationRecordModel`
  (whose `flow_summary` JSONB column carries the headline), whereas the
  operator's **live** card reads the `confirmation_request` SSE frame —
  which is serialized through `AgentStreamEvent` in
  `_normalize_stream_event`, and that model had no `flow_summary` field.
  The kernel's headline (`frame["flow_summary"]`, from
  `FlowContext.summary()`) was therefore dropped at the serialization
  boundary and never reached the live card. `AgentStreamEvent` gains the
  optional `flow_summary` (stream contract v8 → v9),
  `_normalize_stream_event` passes it through a defensive
  `_coerce_flow_summary` (keeps only the contract's five string fields; a
  non-dict summary degrades to absent so a malformed headline can never
  fail `additionalProperties:false`), and `agent-session.schema.json`
  declares the same field on the durable confirmation-card items (a latent
  gap — the model already served it). Pinned by three contract tests: the
  live frame preserves `description` and every field, malformed/unknown
  fields are dropped while the frame stays valid, and a durable card
  carrying a headline conforms to the session contract. The portal was
  already correct and is unchanged; no API route, policy action, or audit
  event type changed.

## 0.33.0 — 2026-09-04

### Fixed

- **One HITL gate per mutating browser flow, enforced platform-side
  (SPEC-051)** — completes SPEC-049 R-4, which specified that "approval
  unlocks the bound flow's interactions for that session" but was only
  ever half-implemented (the tool-gateway flow binding, origin allowlist,
  `risk_class`, and step-budget deviation guard shipped; the
  agent-platform kernel never collapsed the per-write ASKs). A live
  password-reset test on v0.32.0 parked an approval card for *every*
  write-tier browser interaction. The kernel now enforces the invariant:
  - The first write-tier browser interaction in a `write`-class flow
    parks exactly one confirmation card through the existing SPEC-020
    bridge. On approval the kernel records a session-scoped flow
    authority (`services/flow_approvals.py`) keyed on the chat session
    **and** the approved flow's identity (`skill_id` + `origin`), and
    every subsequent write-tier `web.*` interaction in that same flow is
    admitted without a further card.
  - Each unlocked write is auto-signed under the approving card's
    authority (`build_flow_request`: fresh `execution_id`, the call's own
    `args_digest`, reusing the card's `confirm_id`/`decider_user_id` and
    the platform signing key) and stays persisted (`execution_requested`),
    audited, receipted, and gateway-guarded — identical to an
    approved-card execution (SPEC-037/038).
  - The kernel maintains the flow identity as a session-scoped
    `FlowContext` updated from each `web.navigate` result, so the
    authority is scoped to a real flow: if the session rebinds to a
    *different* `write`-class flow, `_sign_flow_execution`'s identity
    guard re-parks a fresh card rather than auto-signing — the ADR-0007
    cross-flow-rebind trade-off is eliminated, not merely bounded.
  - Fail-safe by construction: browser write tools never join any
    auto-allow list (the `test_browser_write_tools_never_auto_allowed_even_if_forced`
    invariant stays green); a missing precondition, an expired authority,
    or a rebind makes the signer return `None` and the write parks (ASK).
    Non-browser mutating tools (`k8s.*`) are unaffected and continue to
    gate per SPEC-021/030/037.
- **Password-reset sample reconciled to a single gate (SPEC-051 R-4)** —
  the sample was internally inconsistent (skill/README/WALKTHROUGH named
  the admin sign-in click as the single write while the target pages
  auto-submitted both the login and the reset). The reset form now
  pre-fills from the URL and does **not** auto-submit, so the sole
  write-tier interaction — and the single HITL gate — lands on the
  destructive "Confirm reset" click; login stays read-tier auto-submit.
  The skill (`ResetUserPassword.md`, v1.1 → v1.2), README, WALKTHROUGH,
  and `demo.sh` all agree, and the demo's second-card tolerance is
  removed in favor of a one-card assertion.

### Added

- **Flow-semantic confirmation card (SPEC-051 R-6)** — realizes the
  second half of SPEC-049 R-4 ("the card names the skill, target origin,
  and declared steps"). The single card a `write`-class browser flow
  parks now headlines the **workflow** the operator is approving — the
  bound skill's declared `title`, `description`, target `origin`, and
  `risk_class` (e.g. "Reset User Password in Admin Portal") — instead of
  a bare tool action like `web.click` on "Sign in". The triggering tool
  action is retained as secondary detail. The headline is assembled from
  frontmatter that already rides `web.navigate`'s `data["flow"]`:
  tool-gateway `FlowState` gains `title`/`description` (populated at
  `bind_flow`, exposed in `to_dict()`), the kernel renders the card from
  the same maintained `FlowContext` R-1 keys on and carries a
  `flow_summary` on the confirmation-request frame, and the portal decodes
  it onto the card. Durable and replayed cards (approvals inbox, session
  detail) render the same headline via a new nullable `flow_summary`
  JSONB column on `confirmation_records`. When no flow is bound the card
  falls back to today's tool-level rendering — no regression. No new
  contract, policy action, audit event type, or shared schema; no
  skill-format change.
- **`AGENT_BROWSER_FLOW_APPROVAL_TTL`** (agent-service, default `900`
  seconds, `>= 0`) bounds how long a recorded flow approval unlocks
  writes; an expired approval no longer unlocks (the next write parks
  again) and `0` disables flow-unlock entirely, restoring the
  pre-SPEC-051 posture. The tool-gateway deviation guard still bounds
  every unlocked write regardless of this knob.

### Governance

- Delivered under **ADR-0008** (spec delivery requires requirement-to-test
  traceability and exercised samples), the gate that would have caught
  R-4 shipping unimplemented: every SPEC-051 acceptance criterion maps to
  at least one asserting test in `tasks.md`, and the password-reset
  `demo.sh` chat leg is exercised in the verification path. **ADR-0007**
  records the flow-gate trust-model decision (one operator decision per
  mutating flow, each unlocked write still signed and gateway-guarded).
  Both ADRs are `accepted`; SPEC-051 is `delivered`.

## 0.32.0 — 2026-09-04

### Added

- **Browser tools expansion and samples reorganization (SPEC-050)** —
  the browser tool surface grows from six to fifteen tools, and
  tutorial content moves into a top-level `samples/` directory:
  - Nine new `web.*` tools: `web.select`, `web.press_key`,
    `web.upload_file`, and `web.evaluate` (write tier — HITL gated)
    plus `web.extract`, `web.wait_for`, `web.hover`, `web.scroll`,
    and `web.switch_frame` (read tier). Each follows the existing
    enforcement patterns: write-tier tools inherit the deviation
    guard and HITL confirmation; read-tier tools use the origin
    re-check capture gate.
  - `web.select` selects a dropdown option by snapshot ref.
  - `web.press_key` presses a keyboard key with optional element
    focus. `web.upload_file` uploads a file from an allowlisted
    directory to a file input element.
  - `web.extract` pulls structured data from tables or lists by
    CSS selector (bounded to 500 rows, 50 columns).
  - `web.wait_for` waits for an element to reach a state (attached,
    detached, visible, hidden) with a server-capped 30s timeout.
  - `web.hover` hovers over an element to reveal tooltips or menus.
  - `web.evaluate` runs a JavaScript expression in the page context
    with result bounding (16K chars). It is write tier — arbitrary JS
    can mutate the DOM and read back masked secrets, so each call parks
    for HITL confirmation; a pre-execution mutation guard
    (`BROWSER_EVAL_MUTATION_BLOCKED`) is defense-in-depth only, never
    the security boundary.
  - `web.scroll` scrolls the page by pixel offsets, centering the
    cursor over the active frame first when an iframe is in scope.
  - `web.switch_frame` switches into an iframe with cross-origin
    denial; `web.navigate` resets to the main frame.
  - New config knob `GATEWAY_BROWSER_UPLOAD_DIR` (default
    `/tmp/browser-uploads`) for the file upload allowlist.
  - `samples/web-checks/password-reset/` bundles the password-reset
    tutorial as a self-contained leaf: skill document, demo script,
    README, and WALKTHROUGH, *referencing* — never duplicating — the
    shared browser target pages, credential secret, and NetworkPolicy
    that stay in `shared/platform-ops/gitops/`. The dependency arrow is
    always tutorial → platform.
  - Sample skills install out-of-band via `make deploy-samples`
    (and remove via `make undeploy-samples`): the base overlay declares
    one *generic* `samples` local source — an optional `skills-samples`
    ConfigMap mounted read-only at `/skills/samples` — that ingests
    nothing until the target packs the selected samples' `skill/*.md`
    into it, so the skill lands as `samples/password-reset-resetuserpassword`
    with zero system → tutorial coupling. The former
    `platform-runbooks/web-checks/ResetUserPassword.md` copy and its
    base-overlay wiring are removed; the base overlay deploys cleanly
    with zero samples installed.

## 0.31.0 — 2026-09-02

### Added

- **Browser-based web application check tools (SPEC-049)** — the
  agent can now verify internal web applications the way an operator
  would: navigate, read the page, and (behind the existing HITL
  gate) sign in and click. Every layer fails closed and stays off
  unless explicitly enabled:
  - tool-gateway gains a stateful `BrowserConnector` (Playwright,
    connecting over CDP to an out-of-process browser — no browser
    binary ships in the image). Sessions are pooled per chat session
    id (the id rides the invoke payload as a trusted correlation
    handle — never model-supplied, carrying no authority, with an
    identity-subject fallback), so a flow the owner binds survives
    the approver's HITL resume; the connector is registered only
    when `GATEWAY_BROWSER_ENABLED=true` and a CDP endpoint is
    configured.
  - Six bounded `web.*` tools: `web.navigate`, `web.snapshot`,
    `web.screenshot`, `web.fill_credential` (read tier) and
    `web.click`, `web.type` (write tier — they ride the existing
    `GATEWAY_MUTATING_TOOLS_ENABLED` + signed-execution + HITL
    posture, never auto-allowed). Element refs are minted only by
    `web.snapshot`; interactions resolve against the last snapshot.
  - Server-side origin allowlist (`GATEWAY_BROWSER_ALLOW_ORIGINS`,
    empty = deny all): every navigation is re-checked gateway-side
    and off-allowlist origins are denied with
    `BROWSER_ORIGIN_NOT_ALLOWED`, regardless of what a skill or the
    model asks for.
  - Flow binding with a deviation guard: a write-class check binds
    to the target origin for the whole flow, one HITL approval
    covers the bound mutating flow, and any off-flow navigation or
    interaction is denied.
  - Named credential sets (`GATEWAY_BROWSER_CREDENTIAL_SETS`, a
    secret-synced JSON file): `web.fill_credential` takes a set
    *name* only — secrets never enter the prompt, tool arguments, or
    snapshots, and filled values are masked (`value=***`) in every
    subsequent snapshot. Leak-asserted tests pin the redaction.
  - Screenshots are bounded base64 JPEGs with an explicit size cap.
  - skills-hub skill frontmatter gains optional `web_target` and
    `risk_class` fields (validated, carried through ingestion and
    search) so web-check runbooks declare their target and risk
    class; the sample `platform-runbooks/web-checks/InventoryHealth.md`
    ships with the overlay.
  - New committed `browser-dev` runtime profile (like `mutating-dev`,
    wired into `dev-k8s` permanently): `chromium-headless-shell`
    sidecar for tool-gateway, the `browser-check-target` sample web
    app (static login + status pages), the dev env fragment, and
    `sync-browser-credentials.sh` for the credential-set secret
    (hooked into `make deploy`). `shared/platform-ops/e2e/browser-check-demo.sh`
    exercises the full chain: deny-by-default controls, discovery,
    origin denials, snapshot/screenshot, and an opt-in HITL chat leg.
  - agent-platform auto-allow list gains the four read-class web
    tools; invariant tests pin that `web_click`/`web_type` can never
    satisfy the read-only auto-allow contract even if force-listed.
  The base deployment stays byte-identical: browser off, no
  allowlist, no sidecar.

## 0.30.0 — 2026-09-02

### Added

- **Policy testing and rollout controls (SPEC-048)** — the bundle
  change workflow gains rehearsal, regression, and verification
  controls around the existing engines, none of which touches
  evaluation semantics:
  - Bundle provenance: both policy engines compute a SHA-256
    fingerprint of the exact loaded bundle text at load time (never
    authored in the bundle). platform-gateway surfaces it on the
    policy matrix response (unchanged `policy:read` gate) and
    `/health/ready`; tool-gateway on `/health/ready`. A deploy can
    now be confirmed against the canonical file without shelling
    into the pod.
  - Scenario-expectation harness: `policy-scenarios.yaml` pins
    per-(role, action) outcome expectations for both engines (131
    api / 19 tools), honoring the deliberate non-parity, and
    `make validate-policy-scenarios` (part of `make verify`)
    evaluates them through the exact engine evaluation path while
    mechanically enforcing full grant coverage — a new grant with
    no recorded intent fails the gate.
  - `make policy-diff CANDIDATE=<bundle>`: a review-time impact
    report enumerating every per-(role, action) outcome transition
    (new/removed grants, allow↔deny, approval-tier changes) between
    the canonical bundle and a candidate, unchanged pairs
    count-summarized, sharing the harness evaluator.
  - Rollout runbook in the configuration reference: edit →
    `make sync-policy` → `make verify` → `make policy-diff` →
    commit → deploy → confirm the provenance hash, plus the
    explicit ConfigMap + pod-restart posture (no hot reload).
  - Copy-parity contract tests now cover the GitOps overlay copy
    under the same byte-identical posture as the packaged copies.
  - Canonical bundle header documents the version-bump discipline
    (bump `version` on every rule change; Git history as the
    authority — no monotonicity machinery).
  No new policy actions, no new audit event types, no bundle schema
  or evaluation-semantics changes, no new env knobs.

## 0.29.3 — 2026-09-01

### Fixed

- **Audit Events tab stuck empty until a manual Refresh** — raised by
  the post-v0.29.2 live-check observation (empty Events tab next to a
  populated Summary; server logs proved every query served rows).
  The portal can boot under a stale expired stored session — the
  cached identity restores the signed-in shell until the silent
  refresh fails and clears it — and the Audit view's first auto-load
  fired in that window failed 401. The initial-load effect then
  latched: its `!error` guard plus `[allowed]`-only deps meant the
  effect never re-ran after the fresh sign-in (the role gate stayed
  continuously true), so the view sat in its failure posture until a
  manual Refresh, which bypasses the guard. The effect is now keyed
  on the session object as well: when the identity lifecycle moves
  it clears any latched error and retries once if not yet loaded.
  Pinned by a stale-session 401 → fresh sign-in → auto-recovery test
  (fails on the old code; 261 portal tests).

## 0.29.2 — 2026-09-01

### Fixed

- **Audit view Rules-of-Hooks regression from SPEC-047** — the
  Summary drill-down callback landed after the role-gate early
  return in `AuditView`, so both render branches no longer ran an
  identical hook sequence; when the gate flipped while the view
  stayed mounted (sign-out clears the session before the redirect
  round-trip, and scheduled token refresh can swap roles), React
  threw "Rendered fewer hooks than during the previous render" and,
  with no error boundary in the portal, unmounted the whole shell.
  The callback now sits with the other hooks above the early return
  (behavior unchanged — it already guarded `!allowed` internally),
  is typed to the panel's exported `DrilldownPatch` contract so the
  one-dimension-at-a-time invariant is compile-time, and a role-flip
  re-render regression test pins the hook order (fails on the old
  code, green on the fix; 260 portal tests).

### Changed

- **Doc alignment for the v0.29.1 share-bar retirement** — the
  SPEC-047 index line, spec changelog, and delivery roadmap now
  annotate that the progress bar was retired in the 0.29.1 patch
  after live-review feedback (same annotation posture as the
  SPEC-036 R-1 revert in 0.18.1).

## 0.29.1 — 2026-09-01

### Changed

- **Audit summary bucket-table readability hardening** — post-v0.29.0
  operator review of the live Summary tab: the SPEC-047 share cell
  (percentage + thin progress bar in one inline span) wrapped onto
  multiple lines at live table widths, and the name column absorbed
  the table width unevenly.
  - The progress bar is retired (R-4 keeps the one-decimal percentage
    via the same shared formatter); the share cell is now a single
    right-aligned, non-wrapping percentage.
  - The bucket tables switch to a fixed layout with narrow fixed
    tracks for the count and share columns, so the name column — the
    only variable-content column — absorbs the width evenly.
  - No API, contract, route, or test-posture changes; the drill-down,
    statistic row, collapse behavior, and zero-total posture are
    untouched (259 portal tests green).

## 0.29.0 — 2026-08-31

### Added

- **Audit summary drill-down and readability (SPEC-047)** — one UX
  iteration on the SPEC-046 Summary tab plus the one additive API
  dimension that makes it complete; no new routes, no new gates, no
  new policy actions, no new event types, and both contract schemas
  keep their shapes.
  - audit-service gains an `outcome` filter dimension on its three
    read routes (`GET /api/v1/audit/events`, `/summary`, `/export`),
    validated against the four contract enum values (`allow`,
    `deny`, `success`, `error` — anything else is a 422) and applied
    in the shared WHERE-builder, so both store backends and all three
    read surfaces inherit it with no per-route special casing; the
    platform-gateway forwards the parameter on its existing
    pass-through routes under the unchanged `audit:read` gate.
  - The portal's pinned filter vocabulary gains `OUTCOMES` beside
    `EVENT_TYPES` / `EMITTER_SERVICES`, behind the same vitest drift
    guard that reads the contract schema enum.

### Changed

- **Audit Summary tab rebuilt** — the aggregates render as a single
  page instead of four static tables: a headline statistic row
  (total events plus the four decision-chain steps, zeros as 0),
  collapsible bucket sections (By event type / By outcome / By
  service / Top actors — all expanded by default, section total in
  the header), a share column per bucket row (one-decimal percentage
  plus a thin neutral progress bar), and drill-down from every
  aggregate value — each statistic card, bucket row, and chain step
  lands on the Events tab with that value merged into the current
  filters (merge, never reset; the time range survives).
- The shared audit toolbar gains the outcome select ("all
  outcomes" placeholder) in the pinned-vocabulary posture; it drives
  both tabs and the export like the existing dimensions.

## 0.28.0 — 2026-08-31

### Added

- **Audit reporting and export (SPEC-046)** — the audit trail gains
  two read-only reporting surfaces that ride the existing `audit:read`
  grant: no new policy action, no new event type, and the auditor
  read-only invariant unchanged — both surfaces aggregate envelope
  columns only and never touch event payloads.
  - audit-service gains `GET /api/v1/audit/summary`: deterministic
    aggregates over the same filters as the event query — total event
    count, the echo of the effective window, bucket tables by event
    type / outcome / service (count desc, name asc), top actors (cap
    10, null usernames excluded), and the decision-chain counters
    (`confirmation_decided → execution_requested →
    execution_completed → execution_rejected`, zeros included). Both
    store backends (in-memory and Postgres) compute identical results
    behind one shared filter clause; new counters
    `audit_summary_query_total` and `audit_exports_total`.
  - audit-service gains `GET /api/v1/audit/export`: a bounded
    RFC-4180 CSV of the filtered envelopes — ten fixed columns,
    RFC-3339 UTC `Z` timestamps, sorted-key compact `details` JSON as
    the final column. Rows are capped at `AUDIT_EXPORT_MAX_ROWS`
    (default `10000`, positive-int validated); `X-Audit-Export-Truncated`
    and `X-Audit-Export-Rows` are always set before the first byte
    streams, and the filename is deterministic
    (`audit-export-<timestamp>.csv`).
  - shared-contracts gains `audit-summary.schema.json`
    (`additionalProperties: false`), bound by the service's contract
    tests.
  - platform-gateway passes both routes through behind the existing
    `audit:read` gate with the standard 503/4xx-passthrough/502
    mapping; the export leg uses a dedicated 30 s timeout and forwards
    only the allowlisted content headers.
  - The portal Audit view becomes tabbed: **Events** (the existing
    table, moved intact) and **Summary** (aggregate panel that
    refetches when the filters move), driven by one shared filter
    toolbar alongside **Export CSV** (Blob download under the server
    filename, truncation notice when the cap bites, structured
    403/502/503 messages). The filter vocabulary now mirrors the
    shared audit-event schema — 20 event types and 7 emitter services
    instead of the stale 7 and 4 — pinned by a vitest drift guard.

## 0.27.6 — 2026-08-31

### Changed

- **Post-review hardening of the dotted tool-name rewrite** — the
  post-v0.27.5 code review returned approve-with-minor with two Low
  findings, both remediated here. (1) The match boundary now excludes a
  leading dot as well as word characters, so an already-dotted mention
  can never re-match a suffix key should the registry ever contain one
  (`k8s.get_pod_logs` vs a hypothetical `get_pod_logs` entry); the
  trailing boundary stays word-only so names ending a sentence
  ("called k8s_get_pods.") still rewrite. (2) Test coverage gains:
  leading-boundary adjacency, sentence-final names, the pathological
  suffix-key registry, and the third-colliding-entry skip branch.
  Portal-only, no backend changes.

## 0.27.5 — 2026-08-31

### Changed

- **Dotted canonical tool names everywhere, including code regions** —
  v0.27.4's render-time rewrite deliberately shielded inline code
  spans and fenced blocks so they kept the sanitized form, on the
  assumption that configuration surfaces expect it; a live test showed
  the model backticks every name in tool-list replies, so the lists
  stayed underscored. The assumption no longer holds: the sanitized
  form has no external consumer besides the model's function-calling
  schema, and `AGENT_GATEWAY_TOOL_AUTO_ALLOW` normalizes dots to
  underscores on input, so copy-paste of the dotted form works too.
  The rewrite now applies to every rendered surface — prose, inline
  code spans, and fenced blocks — dropping the shielding machinery
  entirely. Durable transcripts keep the model's original words;
  the rewrite remains presentation-only. Skill drafts still render
  as generated (preview must match the download). Portal-only, no
  backend changes.

## 0.27.4 — 2026-08-31

### Changed

- **Dotted canonical tool names in chat prose and triage summaries** —
  the model writes the sanitized tool names it sees in its
  function-calling schema (dots → underscores), so replies mentioned
  `k8s_get_pods` while evidence cards, confirmation cards, and
  execution receipts already show the registry's dotted canonical
  name. The portal now maps sanitized names back to the dotted form at
  render time (map built from the `/api/v1/tools` catalog, cached once
  per page session): chat reply bubbles and incident triage-report
  summaries show `k8s.get_pods` in prose, while code spans and fenced
  blocks keep the sanitized form that configuration surfaces like
  `AGENT_GATEWAY_TOOL_AUTO_ALLOW` expect. The durable transcript keeps
  the model's original words; the rewrite is presentation-only and
  re-applies to historical sessions on re-render. A failed catalog
  fetch degrades to no mapping (text renders as written); ambiguous
  sanitized collisions are skipped rather than guessed. Portal-only,
  no backend changes.

## 0.27.3 — 2026-08-31

### Fixed

- **Chat markdown rendering of tool identifiers (live-test finding)** —
  the agent writes the model-visible sanitized tool names
  (dots → underscores, e.g. `k8s_delete_pod`), and the renderer's
  underscore emphasis pass consumed the underscore pair, showing
  "k8sdeletepod"; backticks did not protect the name because code
  spans were converted before the emphasis passes and never shielded
  from them. Code fences and inline code spans are now stashed before
  any block/inline pass and restored at the end, and the underscore
  emphasis passes require non-word context at the edges (CommonMark
  flanking), so intra-word underscores stay literal while real
  `_emphasis_` still renders. The escape-first contract and the
  http(s)-only link allow-list are untouched.

## 0.27.2 — 2026-08-30

### Changed

- **Continue in chat availability gate (live-test follow-up to
  SPEC-045)** — the incident-detail **Continue in chat** button now
  renders disabled (with an explanatory tooltip) whenever the
  incident's triage session is not among the caller's own live
  sessions — expired by the idle TTL sweep, not yet visible, or owned
  by another operator — instead of failing with a confusing 404 on
  click. The gate reads the portal's existing caller-scoped session
  list; no extra API call. The chat header's **Draft as skill** keeps
  a 404 toast as a race-window safety net, and **Draft as skill** on
  the incident stays the ownership-free path to turn a triage into a
  skill.

### Added

- `GET /api/v1/runtime` now carries the platform `version` so probes
  and the portal's Settings inventory can read the deployed release
  without another endpoint.

### Fixed

- The identity-service sign-in legs (login-url, login, callback,
  logout-url, refresh) now ride the house proxy error model: the
  identity service's own 4xx postures pass through with their detail,
  while 5xx and transport failures answer a structured 502 — the
  sign-in surface never answers a raw 500 when a leg races a rollout.

## 0.27.1 — 2026-08-30

### Fixed

- **Post-release review remediation (SPEC-045 follow-up)** — the
  incident skill-draft bundle assembler stripped `triage_raw` from the
  incident envelope but not the triage `session_id`, which can name
  the triage operator; the field now rides neither the envelope nor
  the report into generation, restoring the "never anyone's session"
  invariant on the incident anchor. The purity-test fixture now
  carries a session id and the assertion pins the envelope strip. No
  routes, policy actions, audit events, or response shapes changed.

## 0.27.0 — 2026-08-30

### Added

- **Incident-anchored skill drafts and draft preview (SPEC-045, seventh
  R5 slice)** — a triaged incident becomes team-authored guidance: any
  caller holding the grant drafts a validated Skill Format v1 Markdown
  from the incident's validated triage — no matter who ran the triage
  session — and both skill-draft entry points now open a read-only
  preview before any download. Ephemeral by construction, as before:
  nothing about a draft is persisted anywhere on the platform.
  - agent-service gains `POST /api/v2/incidents/{incident_id}/skill-draft`:
    the bundle is the incident envelope (minus the raw failed-triage
    output) plus the validated triage report only — never anyone's
    session, never connector dispatches. Generation reuses the SPEC-044
    internals verbatim (digest-only prompt, fenced skill-frontmatter
    contract, deterministic redaction + Skill Format caps, provenance
    block carrying the incident id and no session line, facts-only
    skeleton degradation — generation never 500s) and the same bounded
    regeneration + fail-closed validation (503 not configured, 502
    unreachable). An incident without a validated triage report (new,
    triaging, `triage_failed`) answers a deterministic **409** — never
    a thin guess.
  - platform-gateway passes through
    `POST /api/v1/incidents/{incident_id}/skill-draft` behind the new
    deny-by-default **`incident:skill_draft`** action, dual-gated with
    `incident:read` at the same route (the SPEC-043 pattern; a denial
    reports the first failing action) and granted to `platform-admin`,
    `approver`, and `operator` via the new
    `allow-operators-incident-skill-draft` rule — synced byte-for-byte
    to both gateway copies and the dev-k8s ConfigMap.
  - `incident_skill_draft_generated` joins the audit-service event enum
    with the SPEC-029 parity-guard members (shared
    `audit-event.schema.json`); one event per generation carrying the
    incident id, mode, and validation outcome — emitted regardless of
    whether the operator downloads or discards.
  - The portal gains a shared read-only **skill-draft preview modal**:
    rendered view (escape-first renderer) with a **Raw** toggle that
    shows the full markdown including the provenance block, a
    **generated** / facts-only **skeleton** mode badge, validation
    status, and suggested filename; **Download .md** (SPEC-040 R-4 Blob
    download of the raw markdown) and **Discard** (drop the in-memory
    response). The incident detail toolbar gains **Draft as skill**
    beside Run/Re-run triage and Continue in chat, with structured
    403/404/409/502/503 toasts — the 409 names the precondition: run
    triage first, then draft the skill. The chat header's **Draft as
    skill** now opens the same preview instead of downloading blindly;
    its error toasts stay identical.
  - No new configuration knobs: the SPEC-043 incident client and the
    SPEC-044 skills-validation wiring are reused as-is.

## 0.26.0 — 2026-08-30

### Added

- **Skill authoring export from sessions (SPEC-044, sixth R5 slice)** —
  one route turns the durable record of a session into a validated
  Skill Format v1 Markdown draft and hands it over as a client-side
  download; the draft is ephemeral by construction (nothing is
  persisted anywhere on the platform).
  - agent-service generates the draft from the session's digest bundle
    only — the same session-fact assembly as the shift summary, plus
    the validated triage report when the session is incident-linked;
    raw transcripts, alert payloads, and evidence payloads never reach
    the builder. Content guardrails are deterministic: the gateway's
    redaction vocabulary and the Skill Format caps are enforced by
    post-processing regardless of model obedience, and every draft
    carries an HTML-comment provenance block (session, covered
    incident, date, platform version, mode).
  - Any generation or parse failure degrades to the facts-only
    skeleton, which is always format-valid — generation never raises a
    500. An unvalidated draft is never returned: the draft is validated
    on skills-hub's own ingestion code path before it reaches the
    operator, and validation legs fail closed (503 not configured,
    502 unreachable).
  - skills-hub exposes `POST /api/v1/skills/validate` — read-only, on
    the existing ingestion code path, behind the Basic query-credential
    registry; route and CLI answer identically (fixture-parity tests).
  - platform-gateway passes through
    `POST /api/v1/sessions/{session_id}/skill-draft` behind the new
    `session:skill_draft` action — granted to `platform-admin`,
    `approver`, and `operator` (documents-create grant pattern);
    ownership stays enforced by the anti-enumeration 404.
  - The portal chat header gains a **Draft as skill** session action:
    busy state during generation, `<suggested-slug>.md` Blob download,
    and a toast distinguishing the generated draft from the facts-only
    skeleton.
  - Audit: `skill_draft_generated` joins the audit event enum with the
    SPEC-029 parity-guard members, carrying session, mode, validation
    outcome, and the covered incident id when present.
  - Deployment: three new agent-platform knobs
    (`AGENT_SKILLS_SERVICE_URL`, `AGENT_SKILLS_CLIENT_ID`,
    `AGENT_SKILLS_CLIENT_SECRET`) wired in dev-k8s; the agent-service
    credential joins the skills-hub query-auth registry via the
    existing `sync-skills-secrets.sh` conventions.

## 0.25.2 — 2026-08-29

### Changed

- **Bounded-pane review follow-ups (v0.25.1 follow-up)** — operator
  portal rendering and tests only; no backend runtime behavior,
  routes, actions, event types, or dependency versions change.
  - The bounded-pane height is single-sourced: the view sets a
    `--bounded-pane-max-height` custom property on each bounded
    wrapper (from `BOUNDED_PANE_MAX_HEIGHT`) and the
    `.digest-bounded` / `.prose-bounded` CSS rules consume it, so the
    presentation bound and the overflow comparison can no longer
    drift apart.
  - The v0.25.1 post-motion re-measure race fix gains a fake-timer
    regression test: with the immediate measurement reading a
    pre-motion height, the *Expand to full height* affordance must
    appear only once the delayed re-measure runs.

## 0.25.1 — 2026-08-29

### Changed

- **Portal live-check polish (v0.25.0 follow-up)** — operator portal
  rendering and documentation polish only; no backend runtime
  behavior, routes, actions, event types, or dependency versions
  change.
  - Bounded panes now pin their structural chrome: the digest's tab
    bar and the narrative's collapse header stay visible while only
    the content region (active tab content / narrative body) scrolls
    inside the fixed-height bound; releasing the bound removes the
    constraint entirely. The *Expand to full height* affordance stays
    on both document types and appears only on overflow.
  - The **Raw JSON** tab is renamed **Digest data** (both document
    types): the tab has always rendered the stored digest through the
    typed renderers with a typed-but-open fallback, not a JSON dump;
    the name now says what the tab shows. Rendering is unchanged.
  - The digest reference codifies the house layout rule for tab
    content (tables for repeated records with shared scalar fields,
    description lists for single objects, bullets for heterogeneous
    or long-text items, chips for identifiers) and the incident
    report **Triage** tab is audited into it: evidence and next steps
    now ride tables, hypotheses stay bullets, cited skills ride
    chips.

## 0.25.0 — 2026-08-29

### Added

- **Incident report document type (SPEC-043)** — the operations
  document repository (SPEC-039) gains its second type,
  `incident_report`: pick one incident and the platform assembles a
  durable, attributed report — the incident envelope, the validated
  triage report (or a `not_triaged` marker), the connector dispatch
  outcomes, and the incident's linked triage session under the
  existing two-tier own/foreign coverage — with the same optional
  digest-anchored narrative, draft→publish lifecycle, role-based
  access matrix, and client-side Markdown export as shift summaries.
  - Assembly is mechanical and read-only: facts are copied verbatim
    from the incident-service bundle and the platform's durable
    stores; the raw alert payload (`triage_raw`) never enters the
    digest — a `has_triage_raw` presence marker replaces it — and no
    incident state is mutated anywhere in the path.
  - Authorization combines two existing actions — `documents:create`
    **and** `incident:read` — at creation (no new policy action); a
    denial reports the first failing action in the standard
    structured shape. The covered incident id rides `document_created`
    as provenance (no new audit event type).
  - Creation answers the dependency postures: 503 when incident
    reporting is not configured, 502 when incident-service is
    unreachable, 404 for an unknown incident id, other upstream 4xx
    passed through with their structured detail — never a 500. The
    gateway forwards these statuses and details verbatim.
  - New agent-platform incident client (Basic query credential
    against the incident-service `INCIDENT_QUERY_CLIENTS` registry,
    bounded timeout, `x-request-id` forwarding) behind
    `AGENT_INCIDENT_SERVICE_URL` / `AGENT_INCIDENT_CLIENT_ID` /
    `AGENT_INCIDENT_CLIENT_SECRET` / `AGENT_INCIDENT_CLIENT_TIMEOUT_SECONDS`;
    `sync-incident-secrets.sh` provisions the agent-service entry.
  - Portal Documents view: the create dialog becomes type-aware with
    a searchable incident picker; the drawer renders the incident
    digest as Incident / Triage / Dispatches / Session tabs with
    marker alerts (`not_triaged`, `missing`, `foreign_denied`,
    `unavailable`) and the foreign metadata banner.

## 0.24.1 — 2026-08-28

### Changed

- **Post-release review remediation (v0.24.0 follow-up)** — test and
  documentation polish only; no runtime behavior, routes, actions,
  event types, or dependency versions change.
  - The vitest antd deprecation guard now covers both antd emission
    modes: its pattern broadens from `[antd: …] … deprecated` to
    `[antd(: …)?] … deprecated`, so the aggregated batch emitted when
    a `ConfigProvider` sets `warning={{ strict: false }}` (`[antd]
    There exists deprecated usage in your code:`) can no longer slip
    past the zero-tolerance gate. Re-proven by deliberately
    re-introducing a deprecated prop (suite fails) and reverting
    (suite green, 18 files / 184 tests).
  - Release-note accuracy polish: the R-3 table marks the two
    range-only bumps (`@testing-library/dom`, `@types/node`) whose
    resolved versions were already current, and the `engines.node`
    note now states jsdom 30's full engine expression. SPEC-042
    tasks.md records the delivered R-1 reality (one App.tsx Drawer —
    the 230px draft-inventory figure was `Layout.Sider`; twenty
    Alert sites, not fifteen).

## 0.24.0 — 2026-08-28

### Changed

- **SPEC-042 dependency hygiene (fourth R5 slice)** — dependency-only
  release; no routes, actions, event types, or execution paths change.
  - **Portal antd deprecation migration (R-1)**: every deprecated antd
    v6 API the portal uses moves to its non-deprecated form — the two
    navigation/document `Drawer`s take `size` (260px / 560px) instead
    of `width`, and every `Alert` site takes `title` instead of
    `message` (`description` stays — it is not deprecated). The vitest
    suite now emits zero antd deprecation warnings with no visual,
    routing, or state behavior change.
  - **Zero-tolerance deprecation regression guard (R-2)**: the vitest
    setup intercepts console output and fails the suite at teardown
    when any `[antd: …] … deprecated` warning appears, pointing at the
    offending text — future deprecations surface at the pull that
    introduces them. Non-deprecation console output passes through
    untouched.
  - **Managed portal refresh (R-3)**: the adopt set from the
    2026-08-28 upgrade check lands on latest stable — antd 6.6.2,
    @testing-library/react 16.3.3 + dom 10.4.1, TypeScript 5.9.3 (the
    7.x native line stays parked), vite 8.2.2 paired with
    @vitejs/plugin-react 6.1.1, vitest 4.1.11, jsdom 30.0.1,
    @types/node 22.20.1 — and `engines.node` rises to `>=22.22.2`
    (jsdom 30's floor; the Dockerfile stays on the `node:22-alpine`
    line). No resolved version is a prerelease.
  - **React 19 (R-4)**: react / react-dom move to stable 19.2.8 with
    @types/react 19.2.18 and @types/react-dom 19.2.5 — every portal
    peer already declared React 19 support, so the gate was
    behavioral: full suite, `tsc --noEmit`, production build, and the
    live walkthrough. Two `useApprovalsInbox` hook tests gained
    React 19 state-flush timing fixes (waitFor around the asynchronous
    error/move flushes and a deferred resync mock); no production code
    changed for React 19.
  - **Backend stable-channel re-lock (R-5)**: all eight Python
    products re-lock inside their declared ranges at the latest stable
    — agentscope 2.0.6 → 2.0.7.post1 (PEP 440 post-release, verified
    like a kernel: full `make verify` plus a live chat/HITL/mutating
    check), fastapi → 0.141.1, uvicorn → 0.52.4. The cryptography caps
    in the six declaring products rise `>=43.0,<45.0` → `>=43.0,<51.0`
    after the JWT/signing call-site review found only the long-stable
    RSA/serialization surface (locking 50.0.1); redis (`<7.0`) and
    elasticsearch (`<9.0`) caps stay parked with their recorded
    reasons. The OTel instrumentation packages remain at their locked
    0.65b0 / SDK 1.44.0 pairing — the single recorded stable-channel
    exception.

## 0.23.4 — 2026-08-28

### Changed

- **Components table shows the tech stack underneath**: every component
  follows the platform version (already shown above the table), so the
  Settings Platform pane now lists each component's tech stack instead —
  Component / Technology / Version columns: React · Ant Design, FastAPI ·
  Python, AgentScope · FastAPI, the LLM provider API and model,
  PostgreSQL/Redis/In-memory store backends with their server versions,
  and the JSON policy rules. The agent service health gains optional
  Python/FastAPI/AgentScope and store-server versions and the gateway
  readiness status gains Python/FastAPI versions — all informational,
  readiness semantics unchanged. React/Ant Design versions are locked
  from the portal's package-lock at build time.
- **Unified component status vocabulary**: one word set across every
  table row — *ready / degraded / not ready*, with *unavailable* when a
  probe fails and *checking…* while loading — replaces the prior
  ok/loaded/ready mix. The status column stays because the portal is a
  static bundle: this page still renders with the gateway down or a
  store unhealthy, and the column surfaces exactly those degraded
  states before they appear as failed work.

## 0.23.3 — 2026-08-28

### Added

- **Key platform components table in Settings**: the Platform pane now
  renders a live component inventory below the platform-version block —
  operator portal, platform gateway, agent service, agent runtime (LLM
  provider and model), session store, agent-state store, and policy
  bundle — read from the gateway's unauthenticated health
  (`/health/ready`) and runtime-metadata (`/api/v1/runtime`) probes,
  with versions and readiness; rows degrade to *unavailable* when a
  probe fails. Locked by SettingsView tests with stubbed probes.
- **AI one-liner document summaries (blurb)**: narrative generation now
  also yields a single bounded sentence, stored as the document's
  `blurb` (additive nullable column and contract property) and rendered
  on Documents list rows, the detail card, and leading the Markdown
  export. The blurb inherits the digest's coverage scoping — the digest
  the model sees is already two-tier with foreign sessions counts-only —
  so it rides the envelope-only listing without weakening the audit
  posture; documents without one degrade to the counts-only summary.

### Changed

- **Human-oriented handover prose**: the narrative prompt is retuned to
  read like an experienced operator briefing the relieving peer — plain,
  direct language in at most three short paragraphs (~150 words total,
  down from six), counts woven in only where they carry meaning — while
  every SPEC-040 R-2 anchoring guardrail holds (digest-only input,
  section-tied facts, no invented ids/causes/recommendations, honest
  quiet flag). Locked by the document-prose prompt tests.

### Fixed

- **Health probes reach the gateway through the portal's nginx**: the
  web-ui image proxied only `/api/`, so the new Settings component
  probes to `/health/ready` hit the SPA fallback and degraded to
  *unavailable* in the browser; the portal nginx now routes `/health/`
  to the platform gateway alongside `/api/`.

## 0.23.2 — 2026-08-28

### Changed

- **Shift-summary narrative opens expanded**: the AI-generated narrative
  panel in the Documents drawer now opens expanded by default — the
  relieving operator reads the handover story without an extra click —
  while staying collapsible to the header alone. Presentation only:
  digest, export, and the stored document are untouched. Locked by a
  DocumentsView test asserting the narrative body renders immediately;
  the portal user guide was corrected to match.

## 0.23.1 — 2026-08-28

### Fixed

- **Approved mutating calls reach the gateway under the canonical tool
  name**: parked tool calls carried the model-visible sanitized name
  (`k8s_delete_pod`) into the SPEC-037 signed execution envelope, and the
  SPEC-038 worker invoked the gateway with it verbatim — the registry
  only knows the dotted canonical name (`k8s.delete_pod`) and answered
  `TOOL_NOT_FOUND`, so an approved restart never executed. The park now
  captures the sanitized→canonical map from the toolkit and emits the
  canonical name, so confirmation cards, durable records, inbox entries,
  `confirmation_decided` audit details, and signed envelopes all name the
  tool the registry resolves. Regression covered by new unit tests and
  the updated `mutating-demo.sh` HITL-leg assertion.

## 0.23.0 — 2026-08-28

### Added

- **Documents readability and digest reference (SPEC-041, third R5
  slice)**: a new operator-facing reference
  (`docs/guides/documents-digest-reference.md`) explains every concept
  in the Documents view — the digest as the deterministic artifact of
  record, each digest section, evidence frames, owner vs foreign
  coverage tiers, provenance anchoring, the quiet state, and the
  envelope-only listing posture — linked from the portal user guide
  and from a **Learn more** affordance beside the drawer's Digest
  title.
- **Deterministic counts-only document summaries (SPEC-041 R-4)**: the
  agent computes a one-line summary from the document's own `handover`
  skeleton at creation time (no model involvement), stores it on the
  record (additive nullable `summary` column; additive schema
  property), and both document lists surface it under the label —
  *2 sessions · 3 decisions · 1 execution · 1 open item* or the plain
  quiet phrasing. Counts only: never titles, record ids, decision
  outcomes, or narrative text, so the envelope-only listing posture is
  preserved. Pre-SPEC-041 documents stay summary-less (label-only
  rows).

### Changed

- The portal document drawer renders the digest as **tabs with
  table-shaped content** (SPEC-041 R-2): Handover (default when
  present), Sessions, Confirmations, Executions, Evidence &
  transcript, Open items, and Raw JSON (the stored digest verbatim).
  Rendering is tier-aware — foreign sessions are labeled *metadata
  only*, never empty owner-tier fields — and pre-SPEC-040 documents
  degrade gracefully. Rendering act only: stored documents, the
  audited single fetch, and the Markdown export are unchanged.
- The digest and prose regions in the drawer are now **bounded and
  scrollable** (SPEC-041 R-3) with an expand affordance, so long
  blocks no longer stretch the drawer body off screen.

## 0.22.0 — 2026-08-28

### Added

- **Shift-summary handover narrative and export (SPEC-040, second R5
  slice)**: every shift-summary digest now carries a deterministic
  `handover` section assembled from the durable stores — covered-session
  counts, own-coverage decisions and execution outcomes (stable-sorted,
  foreign sessions stay counts-only), still-open items, and an honest
  `quiet` flag for empty shifts — so the next operator reads what
  happened without a model in the loop.
- The generated narrative is now the **default** on document creation
  (`include_prose` defaults to true; the create dialog's switch is the
  opt-out) under a tightened anchoring prompt contract: the model sees
  the digest JSON only, every statement must trace to a digest section,
  and nothing absent from the digest may appear. Fail-soft degradation
  (`prose_status=failed` → digest-only document) is unchanged.
- **Client-side Markdown export**: the portal document drawer gains
  *Export .md*, serializing the already-fetched document (metadata,
  provenance, digest, narrative) for offline handover. Export is a
  rendering act — no new endpoint, no new policy action, and no new
  audit event type.

### Changed

- The portal **Documents** entry moved from the Control section to
  Workspace (SPEC-040 R-3): shift handover is an everyday workspace
  artifact, not oversight. Role gating is unchanged.
- The narrative panel is relabeled *AI-generated narrative — from this
  document's digest facts* to match the anchoring contract.
- Contract note: `operation-document.schema.json` documents the
  `handover` digest section (additive; no schema break).

## 0.21.1 — 2026-08-27

### Fixed

- **Document read audit integrity (SPEC-039)**: the document listing
  (`GET /documents`, both scopes) returned full rows — digest and prose
  included — so a `documents:read` holder could read a colleague's
  published document content without ever triggering the cross-owner
  `document_read` event, which only fires on the single fetch. Listings
  now return envelope rows (digest and prose omitted) and the portal
  drawer retrieves the full document through the single-fetch route,
  making the audited fetch the only path to document content. Also
  corrects the portal guide's deletion wording (owners may delete their
  own published documents; document content is never edited after
  creation) and adds the "Your first shift summary" get-started
  walkthrough.

## 0.21.0 — 2026-08-27

### Added

- **Operations document repository (SPEC-039)**: the platform's first
  document-producing capability — a typed-document substrate where team
  members generate durable documents from the platform's own records and
  colleagues access them by role, not per-document grants. Phase 1 ships
  the **shift summary** type: a deterministic digest over the cited
  sessions' kernel snapshots, confirmation decisions, execution receipts,
  and evidence counts with two-tier coverage (own sessions full,
  foreign sessions metadata-only gated on the caller's `approvals:list`
  grant), an optional clearly-labeled digest-only prose layer
  (`prose_status` included|failed|not_requested, fail-soft), and
  provenance anchors to every cited record id. Documents follow a
  one-way draft→publish lifecycle (cap 20 per owner with oldest-eviction,
  30-day TTL, immutable snapshots) behind new deny-by-default
  `documents:create` / `documents:read` actions granted to
  `platform-admin`, `approver`, and `operator`; the gateway forwards the
  caller's foreign coverage as a trusted internal header and agent-service
  fails closed on anything but `allowed`. Audit gains
  `document_created` / `document_published` (always) and `document_read`
  (cross-owner reads only — own reads stay unaudited), fire-and-forget
  with forwarded `x-request-id`. The portal gains a Documents control view
  (create dialog with own-session picker + foreign-id input + prose
  toggle, Mine / Published tabs, digest-first detail with owner
  attribution and collapsed labeled prose), inline session rename
  (`PATCH …/sessions/{id}/title`, 1–80 chars, owner-only, 404
  anti-enumeration, deliberately unaudited) under the new `session:update`
  action granted everywhere `session:list` is, and session-id
  reveal/copy on session-panel rows and the open-session header
  (portal-only, truncated with full value on hover).

## 0.20.0 — 2026-08-27

### Added

- **Isolated execution worker (SPEC-038)**: approved mutating calls no
  longer execute in-process in agent-service. A new
  `products/execution-runtime` worker product receives the SPEC-037
  signed envelope over an authenticated internal handoff
  (`POST /api/v1/executions/handoff`, static handoff token compared
  constant-time), independently re-verifies the envelope signature and
  the parked-arguments digest, performs the tool-gateway call under the
  forwarded confirmer delegated token, authors the signed receipt on the
  shared `execution_records` table (first-write-wins close), and emits
  `execution_completed` / `execution_rejected` with the same
  `confirm_id` + `x-request-id` correlation. The resumed stream blocks
  on the worker with a bounded
  `AGENT_EXECUTION_WORKER_TIMEOUT_SECONDS` budget (default 60s; expiry
  lands as the structured timeout result and a `timeout` receipt);
  single-flight idempotency keyed by `execution_id` makes re-execution
  structurally impossible (single replica pinned). Every missing
  credential fails closed: unset worker signing key or handoff token
  rejects all handoffs; unset `AGENT_EXECUTION_WORKER_URL` /
  `AGENT_EXECUTION_HANDOFF_TOKEN` on agent-service or any handoff
  transport error rejects the mutating resume with an audited
  `worker_unavailable` rejection — no in-process fallback. Isolation is
  enforced at the infrastructure layer: own Deployment/ClusterIP
  Service, its own `execution-handoff-secret`
  (`sync-execution-handoff-secret.sh`), and no HTTPRoute or gateway
  route.

## 0.19.0 — 2026-08-27

### Added

- **Signed execution requests and receipts (SPEC-037)**: approved
  mutating calls now carry a tamper-evident execution chain (Phase 1 of
  the execution-runtime spike; the isolated worker remains Phase 2).
  On approval resume the kernel canonicalizes each parked call's
  arguments, digests them, and signs an HMAC-SHA256 execution envelope
  (missing signing key fails closed with a `signing_unavailable`
  rejection audited at resume); at the invocation boundary the
  tool layer recomputes the digest and rejects any mismatch
  (`args_digest_mismatch`) without re-executing. Durable execution
  records keyed `(confirm_id, call_id)` track
  `requested|succeeded|failed|timeout|rejected`, and signed receipts —
  binding the resume request id, outcome status, latency, and a digest
  of the executed tool result — close only `requested` rows. The audit
  trail gains `execution_requested` / `execution_completed` /
  `execution_rejected` events correlated by `confirm_id` and
  `x-request-id`, session detail attaches executions to their decided
  confirmation cards, and the portal renders a receipt badge on decided
  cards (status, digest-match note; inbox stays decision-metadata-only).
  Deploys ship an `execution-signing-secret` (optional `secretKeyRef`,
  absent key fails closed) plus the agent-service audit-ingest
  credential wiring.

## 0.18.1 — 2026-08-26

### Fixed

- **Chat markdown list rendering**: indented sub-bullets previously
  fell through the renderer's column-0-only list passes and rendered
  as literal `- text` paragraphs at the left edge; ordered items were
  never wrapped in `<ol>`, dropping their numbering. A single
  nesting-aware block pass replaces both legacy passes: indented items
  nest inside the previous item, equally indented blocks stay flat,
  ordered and unordered markers may mix per level, and escaping is
  unchanged (new regression tests pin all of it).
- **Pod-log excerpts in chat replies**: the model used to quote the
  `k8s.get_pod_logs` JSON payload verbatim, landing one serialized
  string with escaped `\n` sequences in the reply. The default system
  prompt now steers log/command-output quoting into fenced code blocks
  with real line breaks (the evidence card keeps its audit-grade JSON),
  and the portal bounds fenced blocks in replies to a fixed-height
  scrollable box (280px, the evidence-expander bound) so long excerpts
  never push the transcript out of view.

### Reverted

- **Seeded-transcript typewriter reveal (SPEC-036 R-1)**: the v0.18.0
  live check found opening a session re-typed its history instead of
  showing it. Cold-seeded transcripts render at once again; the
  typewriter stays reserved for live arrivals (SPEC-035).

## 0.18.0 — 2026-08-26

### Added

- **Server inbox pagination and seeded transcript reveal (SPEC-036)**:
  two follow-ups from the v0.17.0 review. The approvals inbox History
  tab moves to server-side pagination: the store splits into an
  always-complete pending queue and an offset-paginated history page
  with its retention-window total, `GET /api/v2/confirmations` accepts
  `history_limit`/`history_offset` and returns
  `{ confirmations, history, history_total }`, the gateway forwards
  both params verbatim, and the portal History tab renders the server
  page (offset navigation, total-labeled tab, poll re-reads the current
  page, decided cards land on page one locally). The old combined
  payload's 100-row cap — which silently dropped older decisions as
  volume grew — is gone.
- The progressive typewriter reveal now cascades across every reply of
  a cold-seeded transcript (first fetch of a session in a tab):
  staggered top-to-bottom (≤ 150 ms, compressed under a ~3 s start
  budget on long transcripts), each turn bounded to ~6 s, no arrival
  flash, no scroll hijack, `prefers-reduced-motion` degrades to
  instant render, and session switches cancel an in-flight cascade.

## 0.17.0 — 2026-08-26

### Added

- **Decision-sync robustness and arrival polish (SPEC-035)**: four fixes
  from the v0.16.0 live test. The owner-side decision poll now keeps a
  time-based settle window (five minutes, reset by every applied change)
  with a visibility/focus kick, so a resumed turn whose tool run and
  summary outlast the old 60-second budget still lands without a manual
  refresh. Arrived reply text is revealed progressively (typewriter)
  from where the old reply ended, with a stronger flash, an accent edge,
  and scroll-into-view; `prefers-reduced-motion` degrades to instant
  reveal with the static tint.
- The session panel's "awaiting approval" tag now appears the moment a
  request parks (not only when it clears), and stale in-flight session
  list responses can no longer overwrite fresher ones (monotonic refresh
  sequence).
- The Approvals view's info banner sits on its own line under the title
  row, and the History tab paginates ten entries per page.

### Fixed

- Reconstructed transcripts join the kernel's per-segment text blocks
  with a blank line instead of gluing them, so block markdown at a
  segment start (e.g. `## Pod Restart Summary` after a tool run) renders
  as a heading; the live stream applies the same paragraph break after
  tool frames.
- Version lockstep refreshed for the 0.17.0 train.

## 0.16.0 — 2026-08-26

### Added

- **Approval & owner chat UX polish (SPEC-034)**: five portal usability
  enhancements from the v0.15.0 live approval test. The owner window now
  flashes a transient arrival highlight over every turn group that gained
  content when the decision-sync poll reseeds the transcript, so resumed
  agent messages are visible at a glance. The session panel refreshes the
  moment a decision applies (from the poll or the approvals inbox)
  instead of at the next 30-second tick, so the "awaiting approval" tag
  clears with the decision.

### Changed

- The Approvals view splits into **Pending** (default) and **History**
  tabs with per-tab record counts, keeping the actionable queue clean.
- Inbox entries render as separated cards with a structured provenance
  header: session title first, then owner and parked/decided relative
  times, with a status tag on history entries.
- The Approvals banner now also states that unanswered requests expire
  after the confirmation timeout (`AGENT_HITL_CONFIRM_TIMEOUT`, 10
  minutes by default).
- Version lockstep refreshed for the 0.16.0 train; a vitest jsdom setup
  stubs `ResizeObserver` for antd layout components.

## 0.15.0 — 2026-08-26

### Added

- **Confirmation card turn anchoring (SPEC-033)**: the v0.14.1 live
  validation found that a session with several parked requests stacked
  every confirmation card under the newest turn — the record store is
  session-scoped, but records carried no turn correlation, so the
  seeding path anchored them all to the last turn group. The park path
  now stores the parking turn ordinal on the durable record (the same
  `_count_user_turns` convention SPEC-025 evidence uses), via an
  additive `turn_index` column with an in-place migration for existing
  tables. The session-detail surface and the `agent-session.schema.json`
  contract carry the ordinal additively (null for pre-delivery records),
  and the portal's transcript seeding anchors each card under the
  exchange that parked it, falling back to the legacy newest-turn
  anchoring when the ordinal is absent or out of range.

### Changed

- Version lockstep and dependency lockfiles refreshed for the 0.15.0
  train; `docs/guides/approval-and-hitl.md` documents the per-exchange
  card placement.

## 0.14.1 — 2026-08-25

### Fixed

- **Owner-side live decision sync stayed deaf after an external decision
  (SPEC-032)**: the 0.14.0 poll applied its fresh timeline through
  `setSession`, but for the session already on screen `setSession`
  stashes the current turns into the per-tab cache and then restores
  that same entry — the cache hit wins over the passed history, so
  every successful poll re-seeded the exact same stale turns and the
  decided card never appeared until a manual refresh (which wipes the
  cache). Added `reseedTurns` to the stream hook as the authoritative
  same-session re-seed: it replaces both the live turns and the cache
  entry, never moves the session pointer, and never aborts a stream;
  the poll now applies through it. Regression tests pin both the
  cache-shadow pitfall and the re-seed semantics.

### Changed

- Version lockstep and dependency lockfiles refreshed for the 0.14.1
  patch; SPEC-032 plan and spec changelog synced to the reseed path.

## 0.14.0 — 2026-08-25

### Added

- **Owner-side live decision sync (SPEC-032)**: the owner's open chat
  window now learns about decisions made elsewhere (the approver inbox,
  a second browser session) without a manual refresh. While a
  confirmation card is pending, the chat view polls the session-detail
  surface on a short interval (5s) and re-seeds the turn timeline the
  moment the state moves — the card flips to its resolution with decider
  attribution and the resumed turn's content becomes visible. The poll
  is bounded and change-gated: it runs only while a card is pending
  (plus a short settle window for the trailing resumed-turn content),
  never while any chat stream is active, stops on its own once the last
  card resolves, and identical responses never rebuild the timeline.
  Portal-only — no backend, contract, or policy changes; the
  `confirmation_result` frame still rides the answering stream as
  before.

### Changed

- Version lockstep bumped to 0.14.0 and per-product `uv.lock` files
  refreshed; `approval-and-hitl.md` and `portal-user-guide.md` document
  the live owner-side sync.

## 0.13.1 — 2026-08-25

### Fixed

- **Confirm race window between claim and stream end (SPEC-031 review)**:
  the durable outcome was written only when the resumed turn finished, so
  a racing approver answering mid-stream got a bare 404 instead of the
  structured outcome. The confirm route now persists the outcome at claim
  time (the claim is single-flight and the decision irrevocable once
  claimed); the resume's safety-net write stays as an idempotent no-op,
  and `mark_resolved` is first-write-wins in both backends.
- **Startup sweep expired every pending row globally (SPEC-031 review)**:
  a sibling replica's restart killed another pod's live park. The sweep
  is now scoped to pending rows older than the HITL confirmation TTL
  (`AGENT_HITL_CONFIRM_TIMEOUT`, default 600s) — a park past its TTL
  answers no confirmation on any replica, so closing it is safe across
  replicas; younger rows stay untouched.

### Changed

- Version lockstep and dependency lockfiles refreshed for the 0.13.1
  patch; changelog, release notes, approval-and-hitl guide, and
  troubleshooting guide wording synced to the TTL-scoped sweep.

## 0.13.0 — 2026-08-25

### Added

- **Approval inbox and persistent confirmation cards (SPEC-031)**: every
  parked confirmation and its resolution are now persisted durably
  (Postgres on the shared `AGENT_STATE_DB_URL` posture; most recent 50
  records per session, cascade-deleted with the session, pending rows
  older than the HITL confirmation TTL flipped to expired on startup) —
  durability is the source of truth for history and restart recovery
  while the in-memory registry stays the hot path. Two surfaces build on
  the record store: the owner's session detail
  gains an additive `confirmations` array so cards survive re-login, page
  reloads, pod restarts, and replica boundaries (decided cards render
  read-only with decider attribution, pending cards stay actionable), and
  designated approvers get a cross-session inbox
  (`GET /api/v1/approvals/inbox`) gated by a new `approvals:list` policy
  action granted to `approver` and `platform-admin` (bundle rule
  `allow-approvers-approvals-list`). Inbox items are metadata only —
  session, owner, parked calls, outcome — never the owner's transcript
  text, listing pending items plus the last 30 days of history (expired
  items included) most recent first. The portal gains an Approvals view
  for decider roles — nav entry with a pending-count badge, 30s/focus
  polling, pending-first list + history — reusing the SPEC-030
  confirmation card component and the existing `chat/confirm` bridge, so
  tier enforcement, self-approval blocking, audit, and
  resume-under-confirmer-token semantics are unchanged.

### Changed

- Confirm races now resolve into a structured outcome instead of an
  opaque error: a decision against an already-resolved confirmation
  answers `409 already_resolved` carrying the winner's status, decider,
  decision, and decided-at timestamp (agent-platform and the gateway
  pass it through unchanged), and the portal flips the losing card to
  that outcome in both the chat transcript and the approvals inbox. The
  outcome is persisted at claim time — the durable write lands the
  moment the single-flight claim succeeds, so a racing approver sees the
  structured 409 even while the winner's resumed turn still streams,
  never an opaque 404.
- The mutating-demo e2e HITL leg asserts the SPEC-031 surfaces: the
  owner's session detail carries the decided card, the approver inbox
  lists the item with its outcome, and a second approve receives the
  `already_resolved` 409.

## 0.12.0 — 2026-08-25

### Added

- **Require-approval policy semantics (SPEC-030)**: `require_approval` is
  now a first-class, enforced policy outcome with approval tiers. The two
  shared policy schemas gain an additive v2 revision (`approval` block with
  `tier_1` / `tier_2`, `decided_by_roles`, tier-defaulted
  `allow_self_approval`; the reserved `approval_tier` decision field is
  activated), and both gateway engines evaluate three outcomes
  (deny > require_approval > allow). Platform-gateway bridges the outcome
  onto `chat:confirm`: parked batches under a `require_approval` rule check
  the confirmer's roles against `decided_by_roles` and block self-approval
  where the tier forbids it — structured 403s, the attempt audited as a
  blocked `confirmation_decided`, the parked call stays parked, and the
  parked-info fetch fails closed. The default bundle ships a `tier_2` rule
  on `tools:mutate` decided by `approver` / `platform-admin`, so mutating
  runs now need an approver distinct from the requester
  (`mutating-demo.sh` exercises the two-identity flow). The live policy
  matrix exposes requirements as an additive third cell state
  (`approval_requirements`), the portal permissions view renders it, and
  confirmation cards gain a tier badge ("operator confirmation" /
  "approver required") with read-only rendering for non-deciders.
- **Settings view restored (SPEC-030 R-6)**: the portal's Settings entry
  now renders a read-only, tabbed Session & Identity panel (Identity,
  Session, Platform panes — sign-in state and claims, the selected
  session, version / API origin / last request id) built as an extensible
  pane container; the SPEC-023 placeholder is removed and no mutable
  controls ship.

### Changed

- Agent-platform relaxes the confirmer-must-own-session restriction on
  `chat/confirm` (a tier_2 approver legitimately decides a foreign
  session) and exposes the parked batch's policy action via a new
  `GET /api/v2/chat/pending-confirmation` endpoint consumed by the
  gateway bridge; approval authorization lives at the platform edge.
- Tool-gateway validates approval blocks loudly at bundle load, then
  skips `require_approval` rules with a warning — the synced default
  bundle stays loadable there and SPEC-021 admission stays allow/deny.
- Default policy bundle grants `approver` the tool execution actions
  (`tools:list` / `tools:invoke` / `tools:mutate`) — a tier_2-approved
  call resumes under the confirmer's delegated token, so the approved
  execution must pass tool-gateway admission. Separation of duties stays
  enforced at the approval gate (tier_2 self-approval is blocked).

### Fixed

- Live cluster validation: incident triage turns now run in a per-turn
  read-only mode — mutating tools are excluded from the triage toolkit,
  so a single-shot triage can no longer park on a mutating call and lose
  the report.
- Live cluster validation: the kernel's structured-output delivery tool
  (`GenerateStructuredOutput`) joins the session-local allow set in the
  permission middleware — schema-shaped replies no longer park on the
  confirmation gate.
- Live cluster validation: `e2e/mutating-demo.sh` HITL leg targets a
  scratch deployment pod (the bounded restart semantic the model accepts)
  and matches the approved execution's `tool_invoked` audit event by
  tool + time window, since audit details are parameter-redacted.

## 0.11.1 — 2026-08-25

### Fixed

- `sync-skills-secrets.sh` no longer wipes `SKILLS_AUDIT_CLIENT_SECRET` from the shared skills-hub runtime secret file when re-provisioning the query credential — the missing key 401'd every skills-hub audit emission until audit sync ran again.

### Changed

- Version lockstep and dependency lockfiles refreshed for the 0.11.1 patch.

## 0.11.0 — 2026-08-25

### Added

- **Skills usage audit trail (SPEC-029)**: skills-hub now emits audit
  events so operators can see which skills are actually used. Every
  authenticated `search` produces a `skill_searched` event (query, limit,
  result count, matched skill ids, optional source/tag filters), every
  `get` produces a `skill_retrieved` event (hit → `success` with
  provenance, miss → `error` with `reason: not_found`), and each sync
  cycle produces one `skills_synced` event per source (accepted/rejected
  counts on success, token-scrubbed error on failure). Emission reuses
  the canonical fire-and-forget emitter (now drift-guarded across four
  services by the parity suite) behind new `SKILLS_AUDIT_SERVICE_URL` /
  `SKILLS_AUDIT_CLIENT_ID` / `SKILLS_AUDIT_CLIENT_SECRET` knobs — an
  empty URL disables it. Query events correlate with the caller's
  `tool_invoked` events: tool-gateway now forwards `x-request-id` to
  skills-hub, so one portal question can be traced end-to-end without
  forwarding user identity. The shared audit-event contract and
  audit-service vocabulary gained the three event types, and
  `sync-audit-secrets.sh` provisions the skills-hub ingest credential.

### Changed

- Documentation review remediation: new operator guides — portal day-2
  usage (`docs/guides/portal-user-guide.md`), add-a-tool contributor
  walkthrough (`docs/guides/adding-a-tool.md`), and user/role
  administration (`docs/guides/user-and-role-administration.md`); CONTRIBUTING
  testing section and stale study README fixed; pydantic pins aligned.
- Test-depth remediation: drift-guard parity suite for modules
  duplicated across services (telemetry, observability, token verifier,
  audit emitter, ingest/query auth); audit-service coverage 80% → 95%
  and incident-service 87% → 92% with new store/telemetry/runtime tests.

### Fixed

- `sync-audit-secrets.sh` now waits for the audit-service rollout to
  finish before restarting the emitter deployments, so an emitter's
  boot-time emission can no longer hit the old pod's registry and 401.

## 0.10.0 — 2026-08-24

### Added

- **Luban-hosted small model provider (SPEC-028)**: a fourth runtime
  provider `luban` wires team-hosted (local/on-prem) OpenAI-compatible
  servers — Ollama, vLLM, llama.cpp `llama-server` — into the existing
  SPEC-024/026/027 catalog machinery with bearer-token authentication.
  New knobs: `LUBAN_API_KEY` (credential gate), `LUBAN_BASE_URL`
  (mandatory — a key without a base URL gates the provider out, since
  self-hosted endpoints have no default endpoint), `LUBAN_MODEL_NAME`
  (provider default), `LUBAN_MODELS` (fixed-point pinning, authoritative
  over live discovery), and `LUBAN_THINKING_ENABLE` (opt-in; thinking
  defaults off for small-model-safe generation). The curated series is
  empty, so pinning or discovery supplies the lineup; the fail-soft
  ladder keeps an offline server degrading to the default model only.
  New operator guide `docs/guides/luban-llm-guide.md` (stack selection,
  token-auth setup, platform wiring, verification, troubleshooting) and
  free-standing reference Ollama manifests under
  `shared/platform-ops/gitops/llm-hosting/` (Deployment/Service/Secret/
  PVC; opt-in, not wired into `dev-k8s` or `make deploy`).

- **Live model discovery with cached fallback (SPEC-027)**: the model
  catalog now tracks each configured provider's real lineup — a
  lifespan-owned background task queries the provider's OpenAI-compatible
  `/models` endpoint at startup and every
  `AGENT_MODEL_DISCOVERY_REFRESH_SECONDS` (default 1800), applies
  per-provider filters (dated `-YYYY-MM-DD` snapshots and non-chat
  modalities dropped; the provider's default model always force-included),
  and atomically swaps the catalog in place. Failed fetches degrade down a
  fail-soft ladder: in-memory last-good → Postgres-persisted last-good
  (new `model_discovery_cache` table in the sessions database — Redis
  gains no new consumers) → curated series, so restarts stay served from
  cache before the first live fetch lands. A set `<PROVIDER>_MODELS` stays
  authoritative and skips discovery for that provider; new knobs
  `AGENT_MODEL_DISCOVERY_ENABLED` (default true; `false` restores the
  pure curated-series behavior) and `AGENT_MODEL_DISCOVERY_TIMEOUT_SECONDS`
  (default 5). Curated series refreshed to current lineups (DeepSeek V4
  family; DashScope qwen3.7/3.8 decimal generations). Discovery never
  blocks chat or startup — every failure is logged and swallowed. New
  metrics: `agent_model_discovery_refreshes_total{provider,result}`,
  `agent_model_discovery_models{provider}`.

- **Multi-model runtime catalog + profile consolidation (SPEC-026)**:
  every provider with a resolvable API key now joins the model catalog
  with its curated model series — one selectable entry per model
  (entry `id` = model name, sent as `model` on chat requests) instead
  of one entry per provider. An optional `<PROVIDER>_MODELS=a,b,c`
  overrides/restricts a provider's series, and the active provider's
  `AGENTSCOPE_MODEL_NAME` is always force-included as the deploy-time
  default. Legacy provider-name ids (existing session pins) alias to
  that provider's default model; unknown ids stay fail-closed, and
  duplicate model ids across providers fail startup as a
  misconfiguration guard. Runtime profiles are consolidated: the
  per-provider `runtime-profiles/{deepseek,dashscope,openai}` overlays
  are replaced by a single generic `runtime-profiles/default` whose
  `AGENTSCOPE_PROFILE` label is decoupled from `AGENTSCOPE_PROVIDER`
  (additional providers are configured via the active profile's secret,
  not by switching profile directories). The portal model selector now
  groups options by provider.

- **Evidence persistence in session transcripts (SPEC-025)**: agent-service
  now persists `tool_call`/`tool_result` frames per assistant turn into a
  dedicated `session_evidence` store behind the existing
  `AGENT_STATE_STORE_BACKEND` / `AGENT_STATE_DB_URL` knobs. An entry cap
  (`AGENT_EVIDENCE_ENTRY_MAX_CHARS`, default 131,072) truncates oversized
  payloads with an `entry_cap` marker, and a per-session budget
  (`AGENT_EVIDENCE_SESSION_MAX_BYTES`, default 4 MiB) evicts oldest
  `tool_result` data payloads with a `session_budget` marker while keeping
  metadata. `GET /api/v1/sessions/{id}` gains an additive `evidence_turns`
  field (empty list when none stored, `null` when the store is unreadable —
  never a 500); session delete cascades evidence cleanup. The portal
  re-attaches persisted evidence to the matching assistant turns on reload,
  so replayed evidence cards are prop-identical to the live ones and show
  truncation/eviction notes plus the persisted `request_id`. Redaction is
  inherited from the tool-gateway choke point by construction. New counters:
  `evidence_store_writes_total{result}`, `evidence_frames_persisted_total`,
  `evidence_frames_truncated_total{reason}`.
- **Runtime LLM model switching (SPEC-024)**: agent-service derives a
  credential-gated model catalog at startup from per-provider env knobs
  (`<PROVIDER>_API_KEY` / `<PROVIDER>_MODEL_NAME` / `<PROVIDER>_BASE_URL`;
  the active profile's provider additionally falls back to the existing
  `AGENTSCOPE_*` knobs), so a single-provider deployment needs zero new
  configuration and providers without an API key are dropped. Operators
  select a model per chat turn (`"model": "<provider>"` on POST chat,
  `?model=` on the stream); resolution is request > session pin >
  deploy-time default, and unknown ids fail closed (HTTP 422 / an
  `unknown_model` stream error frame — no silent fallback). Selection
  pins onto the session (additive `model` column across the
  memory/Redis/Postgres session stores, exposed additively on
  `GET /api/v1/sessions/{id}`), and switching rebuilds the cached kernel
  agent with full state restore. Discovery rides a new
  `GET /api/v1/models` route (gateway policy action `models:list`,
  mirroring the chat scope) that is discovery-safe by construction —
  no credentials or base URLs leave the runtime. The `message_end` stream
  frame carries the serving model; audit gains the requested model on
  `chat_started` and the serving model on `chat_completed` on both chat
  surfaces (a stream that closes without `message_end` falls back to the
  requested model; parked turns stay unattributed). The portal composer
  gains an extensible selection bar under the message input hosting the
  model selector (the designated mount point for future per-turn
  selections): pre-seeded with the catalog default, a fixed label when
  exactly one model is configured, and fail-open hiding when discovery
  is unavailable; switching sessions re-seeds the selector from the
  session's pinned model.

### Fixed

- **HITL confirm with an evicted model pin**: `/chat/confirm` forwarded
  the raw session pin into the resume path, so a pinned model evicted by
  a discovery refresh (or a key revocation) raised `UnknownModelError`
  mid-stream — tearing the SSE stream and permanently wedging the parked
  session (the pre-claim registry entry never resolved). The confirm
  route now resolves the pin through the same request > pinned > default
  ladder as other turns, degrading a stale pin to the catalog default.
- **Fallback response provider attribution**: the provider-error fallback
  text named the active profile's provider, so a dashscope model failure
  read "provider deepseek failed". The kernel now resolves the turn's
  serving model against the catalog and attributes that provider (model
  id included); without model context the previous wording is kept.
- **Discovery cache bootstrap connection leak**: when the
  `model_discovery_cache` bootstrap DDL failed against a reachable
  Postgres, `PostgresDiscoveryCache` leaked the opened connection on
  every refresh cycle; bootstrap failures now close the connection before
  the fail-soft swallow.

## 0.9.1 — 2026-08-23

### Fixed

- **Chat stream stale-session empty reply**: the gateway answered 200 with
  a zero-frame SSE stream when the agent service rejected an unknown
  session (a stale portal pointer at a deleted session), and the portal
  rendered "(no response received)". The gateway now opens the upstream
  stream eagerly and passes 4xx through (5xx/transport → 502); the portal
  retries once without the session id so the server auto-creates a fresh
  session (legacy first-message flow) and never primes the stream pointer
  with a 404'd session. Regression-tested on both sides.
- **Markdown table header/body disconnect**: the ported renderer split the
  header row and body rows into two stacked tables; a single-pass block
  parser now emits one table with `thead`/`tbody`.

### Changed

- **Folded sidebar is a navigable icon rail**: the portal sidebar folds to
  a 64px icon rail (antd icon-only menu with tooltips) instead of
  disappearing, keeping navigation reachable while folded. Because the
  rail owns its layout space, every view — chat included — aligns
  uniformly to its right and the per-view inset hacks are removed. Rail
  sections render as hairline dividers instead of clipped group titles;
  the expanded sidebar and drawer keep the full Control/Workspace labels
  (SPEC-019 R-1).
- **Sticky request banner**: restyled for prominence and readability —
  accent border and left bar, fully opaque gradient background (no
  transcript bleed-through), bold uppercase label.
- **Pre-login session creation disabled**: the New-session button is
  disabled before sign-in like the composer (the 401 fallback message is
  kept).
- **Evidence card parity**: cards match the chat message width and
  expanded tool results are bounded to a fixed height with a vertical
  scrollbar.
- **Version tag inline** beside the sidebar logo instead of a large chip.
- **Gateway eager-open cleanup hardening**: the chat/confirm stream
  proxies finally-guard the error-body read so a failed read cannot leak
  the httpx response or client.

### Documented

- **SPEC-025 draft**: evidence persistence in session transcripts —
  durable tool-evidence frames with traceability and metrics, and
  replayed evidence cards on reopened sessions. Numbering skips SPEC-024,
  reserved on the delivery roadmap for runtime LLM model switching.

## 0.9.0 — 2026-08-22

### Added — SPEC-023: Portal framework rebuild (multi-session workspace UI on Ant Design X)

- **Framework foundation and build toolchain** (SPEC-023 R-1): the operator
  portal is rebuilt as a Vite + React 18 + TypeScript SPA on antd 6 and Ant
  Design X under `products/operator-portal/web-ui/app/` (Vitest unit suite).
  The image build gains a Node stage that compiles the bundle with the root
  `VERSION` injected as `PLATFORM_VERSION` (asserted by
  `make validate-version`); nginx serves hashed `/assets/*` immutable and the
  SPA shell `no-store`. During the rebuild the SPA shipped at `/next/`
  alongside the vanilla trio; delivery flips the runtime root to the bundle
  and removes the legacy `app.js`/`styles.css`/`index.html` tree.
- **Platform-owned SSE contract adapter** (SPEC-023 R-2): `fetch` +
  `ReadableStream` transport with abort-controller session switching, a
  schema v6 decoder mapped 1:1 from the vanilla dispatch (deltas, tool
  frames, confirmation frames, error frames, truncation-locked cards), and a
  `useChatStream()` hook exposing typed models; fixture tests cover every
  schema v6 event type.
- **Multi-session workspace UI** (SPEC-023 R-3, consuming SPEC-022 Appendix
  A): session panel with titles, relative last-active, and amber *awaiting
  approval* badges (30s poll); switch/resume with transcript load and an
  explicit `transcript_available=false` state; in-UI session delete with 409
  parked refusal and neutral 404; confirmation cards stay anchored to the
  parking session across switches; incidents gain *Continue in chat*
  deep links that pin `incident-<id>` sessions into the panel.
- **Voice input** (SPEC-023 R-4): composer microphone performs browser
  speech-to-text (Web Speech API; no audio stored) and submits turns with
  `input_modality=voice`; a recognition-language selector (en-US / zh-CN,
  browser-locale default, `localStorage` persistence) drives the recognizer
  only and never reaches the backend; confirmation decisions never carry
  modality (Invariant II, test-pinned).
- **View migration parity** (SPEC-023 R-5): audit trail (filters, cursor
  pagination, expandable envelopes, auditor/platform-admin gate),
  permissions matrix, tools and skills inventories, and the incidents
  list/detail/triage/dispatch/report flows are rebuilt on antd primitives
  with the legacy role-scoped visibility and the 15s incident auto-refresh
  preserved.
- **Docs and living state** (SPEC-023 R-6): operator-portal README, operator
  guide, configuration reference, troubleshooting guide, and dev-k8s README
  updated for the rebuilt portal (build step, cache behavior, voice
  availability); 0.9.0 version lockstep across all products.
- **In-release walkthrough fix**: the stream hook completes a turn when the
  stream closes naturally (or is abort-closed by a session switch) without
  a `message_end` frame — live capture showed the kernel may close right
  after the last delta with empty `message_delta` frames; parked
  confirmation turns keep their pending marker (fixture test pins the
  behavior).
- **In-release review remediation** (pre-push code review): the markdown
  renderer escapes quotes and restricts links to `http(s)` targets
  (closes a `javascript:`-link XSS reachable from attacker-influenceable
  replies/summaries; regression-tested); the agent-platform stream route
  passes schema-conformant `risk_level` through on `pending_calls` so the
  portal's mutating-batch badge and per-call risk tags work; stream
  cleanup is ownership-checked (no superseded-stream state wipe on session
  switch); transcript fetch failures are only treated as "empty session"
  on a real 404; stored auth JSON parses defensively.

## 0.8.1 — 2026-08-22

Patch release closing the post-v0.8.0 code review. No API, contract, or
deployment-shape changes; the dev-k8s cluster was rebuilt and redeployed
with the hardened images.

### Fixed — post-v0.8.0 code-review hardening

- **Redis session title is now atomically set-once**: titles live in a
  dedicated `session:title:{id}` key minted with `SET ... NX`, so the
  `touch_session` blob rewrite can no longer clobber a minted title and
  concurrent first turns cannot both win (the Postgres backend was
  already atomic via its `title IS NULL` guard). Adds store-level tests
  for touch/title bookkeeping on both backends.
- **Gateway session-list proxy error posture aligned**: upstream `4xx`
  now passes through unchanged like the get/delete proxies instead of
  surfacing as `502`.
- `select-runtime-profile.sh` rejects `mutating-dev` as an LLM profile
  argument; `has_pending`/`is_parked` deduplicated; the
  delete-vs-in-flight-turn limitation is documented on the delete route
  and in the agent-platform README.

## 0.8.0 — 2026-08-22

### Added — SPEC-022: Multi-session foundations (backend-first)

- **Session workspace lifecycle API (R-1)**: agent-platform gains
  `GET /api/v2/sessions` (caller's own sessions, most-recently-active
  first, capped at 50, each with a `pending_confirmation` flag),
  `GET /api/v2/sessions/{id}` now returns a server-minted title (first
  user turn, 80 chars, set once) and a best-effort transcript
  reconstructed from the kernel state snapshot
  (`transcript_available` marks the explicit fallback), and
  `DELETE /api/v2/sessions/{id}` removes the session plus its state
  snapshot. Unknown or foreign ids answer `404` (anti-enumeration);
  a parked HITL confirmation blocks delete with `409`. Session records
  now carry `last_active_at` and titles in the store.
- **Gateway session proxies**: platform-gateway serves
  `GET /api/v1/sessions` (gated by the new deny-by-default
  `session:list` action) and `DELETE /api/v1/sessions/{session_id}`
  (gated by `session:delete`, emitting a durable `session_deleted`
  audit event); both actions mirror the existing `session:create`
  grants (all five chat-capable roles; `auditor` denied). Upstream
  `4xx` passes through unchanged; transport/5xx map to `502`.
- **Voice-readiness contract (R-2)**: `POST /api/v2/chat` and the
  gateway proxy accept an optional `input_modality` (`text` | `voice`,
  default `text`). It is metadata only — logged and audited, never
  decision-bearing: authorization, tool policy, and HITL gating are
  unchanged, and the confirm surface stays click-gated. Stream schema
  stays at v6; invalid modalities fail with `422` before any upstream
  call.
- **Mutating-dev runtime profile (R-3)**: new
  `shared/platform-ops/gitops/runtime-profiles/mutating-dev/` profile
  promotes the SPEC-021 opt-in into the committed dev posture —
  `GATEWAY_MUTATING_TOOLS_ENABLED=true` is merged into
  `platform-runtime-config` by the dev-k8s overlay and the pod-delete
  RBAC now rides the profile. The profile is wired into `dev-k8s` and
  the root `OVERLAYS` gate; `select-runtime-profile.sh` preserves it
  across LLM provider switches. Base and all LLM profiles stay
  `false`.
- **Docs and matrix (R-4)**: authorization matrix documents the live
  matrix transparency for the session lifecycle actions;
  architecture overview adds `session:list`/`session:delete` (plus the
  previously missing `chat:confirm`/`tools:mutate`) to the Protected
  Actions table and corrects the bundle rule count to twelve;
  troubleshooting gains transcript-fallback and delete-409 symptom
  sections; guides index notes the portal UI follows with the portal
  rebuild spec.

### Fixed — walkthrough findings closed in-release

- **Session detail proxy error posture**: the pre-existing
  `GET /api/v1/sessions/{id}` proxy leaked upstream errors as `500`;
  it now passes upstream `4xx` (unknown/foreign session,
  anti-enumeration 404) through unchanged and maps transport/5xx to
  `502`, matching the new list/delete posture.
- **Audit contract enum drift**: the audit-service `EventType`
  vocabulary was missing `session_deleted` (present in the shared JSON
  schema), so the ingest rejected the whole batch with `400`. The enum
  is synced, and the contract test now pins model/contract enum parity.

## 0.7.0 — 2026-08-21

### Added — SPEC-021: Bounded mutating actions (first approval-gated write tool)

- **First mutating capability, triple-gated**: `k8s.delete_pod` (risk tier
  `write`) deletes one named pod — the bounded "restart" primitive whose
  owning controller recreates it. It registers only when
  `GATEWAY_MUTATING_TOOLS_ENABLED=true` (committed `false`), invokes only
  under the new deny-by-default `tools:mutate` policy action, and never
  executes without a human confirmation through the SPEC-020 HITL bridge.
  Every gate fails closed independently.
- **Risk-tier admission at the tool-gateway (R-1)**: the registry validates
  the `risk_level` vocabulary (`read`/`write`/`admin`) at registration and
  skips non-read tools while the gate is off (absent from discovery,
  `TOOL_NOT_FOUND` on invoke); the invoke path selects the required action
  by risk tier (`tools:invoke` vs `tools:mutate`) with structured 403 +
  metric on deny.
- **Policy bundle (R-4)**: new deny-by-default `tools:mutate` action granted
  to `platform-admin` and `operator` only (`allow-operators-tools-mutate`),
  synced to all four bundle copies; the live permission matrix and both
  gateway policy vocabularies carry the action.
- **HITL invariant for mutating tools (R-3)**: the agent auto-allow surface
  is read-only by construction (naming a mutating tool in
  `AGENT_GATEWAY_TOOL_AUTO_ALLOW` logs a warning and can never grant
  auto-execution); with HITL bridging disabled
  (`AGENT_HITL_CONFIRM_TIMEOUT=0`) mutating tools are excluded from the
  toolkit and each turn carries an explicit system notice instead of a
  silent omission. Stream schema moved v5 → v6: confirmation frames carry
  the optional `risk_level` per pending call, and the portal renders a
  `mutating` badge plus per-call risk tiers (cache-busting bumped).
- **Operator documentation (R-5)**: new Approval and HITL Governance Guide
  (`docs/guides/approval-and-hitl.md`) covering the four-layer approval
  model, auto-allow management, the policy-bundle approval workflow, and the
  HITL knobs; tool guide gains the `k8s.delete_pod` inventory row and
  activation checklist; configuration reference gains the mutating action
  approval chain; troubleshooting gains four SPEC-021 symptoms.
- **Deployment and e2e (R-6)**: dev-k8s commits
  `GATEWAY_MUTATING_TOOLS_ENABLED=false` with a documented opt-in path and a
  separate, out-of-kustomization pod-delete RBAC manifest (pods `delete`
  only); new deterministic smoke test
  `shared/platform-ops/e2e/mutating-demo.sh` asserts the deny-by-default
  posture (or the opt-in chain incl. the observer 403) and an optional HITL
  chat leg (park → approve → audit chain).

## 0.6.1 — 2026-08-21

### Fixed — Durable OTLP ingest credential provisioning

- **OTLP push 401 regression repaired**: five of the seven services
  (audit-service, identity-service, incident-service, platform-gateway,
  skills-hub) were exporting traces/metrics/logs anonymously because
  sibling secret-sync scripts re-applied their runtime Secrets from
  regenerated env files, wiping `OTEL_EXPORTER_OTLP_HEADERS`. All seven
  Secrets now carry the OpenObserve ingest header and push is
  authenticated end to end.
- **`sync-otel-secrets.sh` merges the OTLP header cluster-side** via
  `kubectl patch` (OTEL key only, all other keys preserved) instead of
  rebuilding Secrets from local env files; a missing Secret is created
  with just the header. The agent-platform runtime profile file stays
  authoritative for its own Secret, with the cluster merge as fallback.
- **Sibling sync scripts preserve the header**: the env-file rewrites
  in `sync-delegation-secrets.sh`, `sync-audit-secrets.sh`, and
  `sync-skills-secrets.sh` capture and re-append any existing
  `OTEL_EXPORTER_OTLP_HEADERS` line, so a credential-less `make deploy`
  can no longer resurrect the anonymous-push state.

## 0.6.0 — 2026-08-21

### Added — SPEC-020: HITL confirmation bridging

- **Kernel ASK to portal approve/deny** (SPEC-020): non-allow-listed gateway
  tool batches no longer park silently. agent-platform translates the kernel's
  `RequireUserConfirmEvent` into a `confirmation_request` SSE frame (stream
  schema v3 → v4), parks the reply in an in-memory confirmation registry, and
  resumes it via `POST /api/v2/chat/confirm` (`UserConfirmResultEvent`; the
  confirmer's delegated token rides any resulting tool invocation). The entry
  is claimed pre-header, so a duplicate confirm fails closed with 404.
  Pending confirmations expire after `AGENT_HITL_CONFIRM_TIMEOUT` seconds
  (default 600; `0` disables bridging); an expired park is closed via
  `UserInterruptEvent` on the confirm attempt (410) or the next chat turn,
  never silently evicted; parked sessions reject new chat turns with 409.
- **The allow-list is the only auto-approval surface** (SPEC-018 R-1 hardening):
  the permission middleware now answers every non-allow-listed tool with an
  explicit ASK instead of delegating to AgentScope's `PermissionEngine`, whose
  read-only fast path auto-allows read-only invocations in every mode and was
  silently skipping `AGENT_GATEWAY_TOOL_AUTO_ALLOW` — under the locked
  agentscope 2.0.6 no read-only tool outside the allow-list ever parked.
  Unvetted read-only tools now park as confirmation cards like any other
  ASK-gated batch.
- **Confirmed calls are never re-asked** (SPEC-020 live-check fix): agentscope
  re-traverses the permission middleware chain for calls the operator already
  confirmed (state ALLOWED) and expects the built-in resolution to
  short-circuit them. The middleware now delegates ALLOWED-state calls so an
  approved batch actually executes on resume instead of re-parking the reply
  in an endless approve loop.
- **Portal card status reaches its final state** (SPEC-020 live-check fix):
  the confirmation card's status line now always switches from the
  in-progress "Approving…/Denying…" text to the final outcome once the
  decision is applied; previously only the badge updated and the line stayed
  on "Approving…" forever.
- **Full tool output on evidence cards** (SPEC-020 live-check enhancement):
  stream schema v5 adds an optional `data` field to `tool_result` frames —
  the full tool payload when its serialized size stays within
  `AGENT_TOOL_DATA_MAX_CHARS` (default `32000`; oversized payloads remain
  audit-trail-only). The portal renders it behind a "Show full output"
  expander on the evidence card, so operators can inspect the complete
  result (e.g. all requested log lines) regardless of how the model chooses
  to phrase its reply. Multi-line text fields (such as the `logs` blob from
  `k8s.get_pod_logs`) render as raw log-style blocks with wrapping lines
  instead of one escaped JSON string.
- **Expiry can no longer race an in-flight resume** (post-delivery review
  fix): the TTL cleanup path now claims the registry entry through
  `take_for_expiry` before interrupting, so an approved resume that
  outlives its TTL is never aborted mid-stream and two concurrent expiries
  cannot double-fire; a turn racing such a resume gets a retryable 409.
- **Confirm card always reaches a final state** (post-delivery review fix):
  the portal locks the confirmation card on mid-stream `error` frames and
  when the confirm stream ends without a `confirmation_result`, instead of
  leaving it on "Approving…/Denying…".
- platform-gateway gains `POST /api/v1/chat/confirm` under the new
  deny-by-default `chat:confirm` action (granted to `platform-admin`,
  `approver`, `operator`, `developer`; `read-only-observer` excluded) and
  emits a durable `confirmation_decided` audit event, tee'd off the
  kernel-applied `confirmation_result` frame so only actually-applied
  decisions reach the trail.
- Operator portal chat renders an inline Approve/Deny confirmation card
  (pending tools with collapsible parameters, decision locks the card, 410
  renders as expired) and resumes the stream in place; buttons hide for
  roles without `chat:confirm`.

## 0.5.0 — 2026-08-21

### Added — SPEC-019: Portal transparency and navigation

- **Portal transparency and navigation** (SPEC-019): sectioned sidebar (Chat / Control / Workspace) with auto-hiding sections, live permission matrix endpoint (`GET /api/v1/policy/matrix`) rendered from the enforced policy bundle with server-side role scoping, Permissions view, and read-only Tools and Skills inventory views behind new platform-gateway proxies (new `policy:read` / `skills:read` actions granted to all operational roles); version chip consolidated into the logo row. The Tools catalog table uses fixed column geometry so the short category/risk columns are not starved by the free-form description column.

## 0.4.0 — 2026-08-20

### Added — Platform versioning discipline

- New root `VERSION` file (semver) as the single source
  of truth for the platform version; all products and the portal track it in
  lockstep (`pyproject.toml`, `metadata.py` `SERVICE_VERSION`, portal
  `PLATFORM_VERSION` — all bumped from the stale `0.1.0`).
- New `make validate-version` gate (wired into `make verify`) fails on any
  drift between `VERSION` and the product/portal constants.
- Coordinated image tags now carry the semver prefix
  (`<semver>-<prefix>-<gitsha>`), and this changelog closes entries into
  versioned sections (`0.3.0`, `0.2.0`, `0.1.0`). Versioning policy is
  documented in `CONTRIBUTING.md`.

### Added — SPEC-016: Postgres session store backend

- agent-platform gains a third session store backend:
  `SESSION_STORE_BACKEND=memory|redis|postgres` (unknown values now fail
  startup instead of silently defaulting). The Postgres backend persists
  sessions in a dedicated `sessions` database with idle-TTL semantics
  matching the Redis store (refresh folded into reads, bounded
  opportunistic sweep) and applies its DDL idempotently on startup.
- `SESSION_DB_URL` supplies the DSN (required for `postgres`); unreachable
  databases fail open to the in-memory backend and increment
  `session_store_fallbacks_total`. `session_store_backend` gauge and
  `agent-health.schema.json` learn the `postgres` value.
- dev-k8s switches the deployed overlay from Redis-backed sessions to
  Postgres (`SESSION_REDIS_*` removed; Redis remains for kernel
  coordination only): new `infra/create-sessions-db.sql` initdb entry and
  `sync-sessions-db.sh` for existing clusters, wired into `make deploy`.

### Added — SPEC-017: kernel utilization and conversation durability

- agent-platform now drives the AgentScope kernel's own tuning surfaces
  (R-1): `AGENTSCOPE_MAX_ITERS` (ReAct loop cap),
  `AGENTSCOPE_CONTEXT_TRIGGER_RATIO` (long-term memory trigger),
  `AGENTSCOPE_TOOL_RESULT_LIMIT` (tool result truncation),
  `AGENTSCOPE_TIMEZONE` (runtime-state injection), and
  `AGENTSCOPE_MODEL_MAX_RETRIES` (model retries). Defaults mirror
  agentscope's own, every value is validated at startup, and each
  constructed agent logs its effective configuration once.
- `/api/v2/chat` accepts an optional `response_schema` and returns a
  kernel-validated `structured_output` (R-2): incident-service triage
  turns send the triage-report JSON schema and prefer the structured
  output, with the fenced-block parser retained as fallback; server-minted
  attribution forcing is unchanged. The default system prompt is now
  format-neutral about report delivery.
- Conversation durability (R-3): the kernel-serializable agent state is
  snapshotted after every completed turn and restored on agent
  construction via a new `AgentStateStore`
  (`AGENT_STATE_STORE_BACKEND=memory|postgres`, `AGENT_STATE_DB_URL`,
  `AGENT_STATE_TTL_SECONDS`), sharing the SPEC-016 `sessions` database.
  Snapshot/restore never fails a turn; corrupt rows are discarded with a
  counter. Session deletion also removes persisted state, and `/health`
  surfaces the `agent_state` backend.

### Added — SPEC-018: Kernel middleware alignment

- The agent-platform kernel moves all cross-cutting behavior onto
  AgentScope's supported `MiddlewareBase` hooks and drops the private
  surfaces: the `GatewayFunctionTool` subclass is gone (permission
  decisions now come from `GatewayPermissionMiddleware.on_check_permission`
  with the unchanged `AGENT_GATEWAY_TOOL_AUTO_ALLOW` allow-list), the
  per-request toolkit rebuild and `agent.toolkit` mutation are gone
  (evidence frames now come from `ToolEvidenceMiddleware.on_acting` with a
  request-scoped sink; toolkits are cached per delegated token), and tool
  closures read the delegated token from a contextvar at call time so
  portal token refresh no longer needs an agent rebuild. The
  `agent-stream-event.schema.json` frame contract is unchanged.
- Opt-in kernel capabilities via new settings, each validated at startup:
  `AGENTSCOPE_KERNEL_TRACING` (out-of-box `TracingMiddleware` for OTel
  agent/LLM/tool spans through the existing OTLP pipeline),
  `AGENTSCOPE_REPLY_TOKEN_BUDGET` (+ `_INPUT_TOKEN_WEIGHT` /
  `_OUTPUT_TOKEN_WEIGHT`, out-of-box `ReplyBudgetControlMiddleware`), and
  `AGENTSCOPE_TASK_TOOLS_ENABLED` (built-in `TaskCreate`/`TaskGet`/
  `TaskList`/`TaskUpdate`, persisted through the SPEC-017 agent state
  store). Unset deployments behave exactly as before.
- dev-k8s enables `AGENTSCOPE_KERNEL_TRACING=true` for the deployed
  agent-platform and documents recommended starting values for the
  budget/task-tools opt-ins.
- Delivery includes the utilization re-audit memo
  (`docs/workspace/agentscope-utilization-audit.md`) with the adopted /
  kept-platform-owned / spike-needed decision matrix, the entrypoint
  surface clarification, and the HITL bridging / ASK → DENY future-scope
  carry-forward.

### Changed

- agent-platform upgrades the AgentScope kernel from `2.0.4.post1` to
  `2.0.6`: O(n) stream accumulation and reused OpenAI clients on the
  streaming path, the OTel cross-task detach fix, preserved error state in
  tool responses, and the 2.0.5 agent-loop/permission fixes. The kernel now
  also ships a SQLAlchemy storage backend upstream (`AsyncSQLAlchemyStorage`).

## 0.3.0 — 2026-08-17

### Added — SPEC-015: Incident Triage and Collaboration (Release 3)

- New `shared/shared-contracts/schemas/incident.schema.json` and
  `triage-report.schema.json` (R-1): the canonical incident envelope and the
  structured triage output contract; incident-service models bind to both
  via contract tests.
- New `products/incident-service` product (R-2): FastAPI on the shared
  `base-uv` image mirroring the audit-service chassis. Alertmanager v4
  webhook intake (`INCIDENT_WEBHOOK_TOKEN` bearer, fail-closed 503 when
  unconfigured, `groupKey` fingerprint dedupe, resolution handling), manual
  intake for the portal report form, and an `IncidentStore` protocol with
  in-memory and Postgres backends (`incidents` database). Query auth uses
  the dedicated `INCIDENT_QUERY_CLIENTS` Basic registry plus projected
  workload tokens.
- Operator-initiated triage (R-3): `POST /api/v1/incidents/{id}/triage` runs
  one agent turn in the dedicated `incident-<id>` session, relaying the
  operator's delegated bearer, and captures the outcome as a validated
  fenced `triage-report` JSON block — `triaged` with report and connector
  dispatch, or `triage_failed` with the raw agent text preserved. The agent
  system prompt gains the triage-report output discipline. agent-platform
  gains named-session support (`POST /api/v2/sessions` accepts an optional
  caller-supplied `session_id`, idempotent for the owner); because sessions
  are single-owner, re-triage by a second operator falls back to
  `incident-<id>--<operator>`, and report attribution
  (`session_id`/`generated_at`/`generated_by`) is server-minted, never
  taken from agent output.
- Read-only incident tools (R-4): tool-gateway's `IncidentsConnector`
  registers `incidents.list` / `incidents.get` (Basic-auth httpx transport,
  structured error mapping), gated on `GATEWAY_INCIDENTS_SERVICE_URL`; both
  join `DEFAULT_AUTO_ALLOWED_TOOLS`. No mutating incident tool exists —
  the SPEC-007 read-only invariant holds.
- Connector framework (R-5): config-driven `Connector` registry
  (`INCIDENT_CONNECTORS`, unknown names fail startup) with the built-in
  `audit` sink emitting `incident_triaged` events to audit-service; dispatch
  outcomes persist per incident and never fail the triage path. Slack/Jira
  adapters are documented contract-only.
- Portal and gateway surfaces (R-6/R-7): platform-gateway proxies the
  incident list/get/report/create/triage routes under three new policy
  actions (`incident:read` / `incident:create` / `incident:triage`, bundle
  now eight rules) and relays identity; the operator portal gains the
  Incidents panel (filterable list with auto-refresh, report detail, Run
  triage, Report incident form, Continue in chat, connector dispatch
  outcomes) and the audit view gains the `incident_triaged` type.
- Deployment and demo: dev-k8s overlay for incident-service (deployment,
  service, postgres `incidents` database via initdb ConfigMap),
  `sync-incident-secrets.sh` wired into `make deploy`
  (`SKIP_INCIDENT_SECRETS` opt-out), `sync-audit-secrets.sh` registers
  incident-service as a fourth audit emitter, and
  `shared/platform-ops/e2e/incident-demo.sh` asserts intake auth, dedupe,
  resolution, query visibility, gateway triage, and the audit dispatch.
- Docs: release note
  `docs/agentic-aiops-platform/release-notes/2026-08-17-r3-incident-triage-and-collaboration.md`,
  new [Incident Triage and Collaboration Guide](docs/guides/incident-guide.md)
  (Alertmanager wiring, lifecycle and dedupe semantics, portal workflow,
  triage interpretation, re-triage collaboration), incident symptoms in
  troubleshooting, updated guides (getting-started Incident Triage tour,
  configuration reference, tool configuration, architecture overview),
  product and dev-k8s READMEs.

## 0.2.0 — 2026-08-15

### Added — OpenObserve Telemetry Enablement (SPEC-005 completion)

- The opt-in OTel push pipeline is now live for all six services against the
  in-cluster OpenObserve backend: `OTEL_ENABLED=true` and the org-scoped OTLP
  HTTP endpoint move into the shared ConfigMap, and the six `telemetry.py`
  pipelines switch from OTLP gRPC to OTLP **HTTP/protobuf** (the protocol
  OpenObserve ingests; dependency swapped to
  `opentelemetry-exporter-otlp-proto-http`).
- New **OTLP log bridge**: when enabled, each service attaches an OTel
  `LoggingHandler` to the root logger, mirroring every structured JSON record
  as an OTLP log with automatic trace/span association (via the non-deprecated
  `opentelemetry-instrumentation-logging` handler). JSON stdout remains the
  audit source of truth; OTel's own loggers are detached from the root to
  prevent export-failure recursion. Gating and fail-open semantics unchanged.
- skills-hub sync-loop depth: `skills.sync` spans (source id/type, result,
  accepted count) and `skills.git.checkout` spans (source id, requested ref)
  with checkout errors recorded **after** scrubbing the git token — the
  token-injected clone URL never reaches span attributes or events.
- New `sync-otel-secrets.sh` (wired into `make deploy`): computes the Basic
  auth header from `OO_ROOT_USER_EMAIL`/`OO_ROOT_USER_PASSWORD` and upserts
  `OTEL_EXPORTER_OTLP_HEADERS` into all six runtime-secrets Secrets, then
  restarts the workloads. Unset credentials skip with a clear message — push
  then 401s and fails open. `SKIP_OTEL_SECRETS=true` escape hatch for CI.
- Docs: observability conventions now define the OpenObserve backend, OTLP
  HTTP protocol, and log-bridge semantics; configuration reference documents
  the three `OTEL_*` variables and the header contract per Secret;
  troubleshooting gains a "no data in OpenObserve" section.

### Added — Git-Federated Skill Sources, End to End (R2 gap-closure)

- The skills-hub image now ships `git`: the sync engine shells out to it for
  `type=git` sources, but the base-uv-derived image lacked the binary, so git
  federation could never have worked in-cluster. Git stays out of the shared
  base image.
- `SKILLS_SOURCES` git entries accept an optional `path` — the subdirectory
  within the checkout to ingest (real team repos keep skills next to other
  code). Path-escaping values are rejected at config parse; a missing subpath
  fails the sync with a clear error while the previous snapshot keeps serving.
- dev-k8s wires a production-parity git source (`platform-skills`, tracking
  this repository's `shared/platform-ops/skills`): non-secret `url`/`ref`/
  `path` in the ConfigMap, the PAT only in `skills-hub-runtime-secrets`.
  `sync-skills-secrets.sh` provisions `SKILLS_GIT_TOKENS` when
  `SKILLS_GIT_TOKEN` is exported (never echoed, never committed).
- Operator portal: successful `skills.*` tool calls now render the matched
  skills as **Cited guidance** chips (title + namespaced id) under the
  tool-evidence card, making the guidance behind an answer glanceable.

### Refined — Skills and Grounded Guidance (post-delivery)

- Search prefilter semantics now match the deterministic scorer: query words
  are tokenized and OR-joined into `to_tsquery`, so multi-word queries keep
  partial matches (`plainto_tsquery` previously AND-ed the words and silently
  dropped them); a tokenless query short-circuits to an empty success without
  a database round-trip.
- New read-only `skills.list` tool in tool-gateway (catalog discovery:
  summaries without bodies, source/tag filters, capped offset pagination),
  mapped to the existing `GET /api/v1/skills` endpoint; auto-allowed for the
  agent alongside `skills.search` / `skills.get`, and the system prompt now
  teaches catalog discovery via `skills.list`.
- skills-hub prunes store records whose source is no longer configured at
  startup, so removing a `SKILLS_SOURCES` entry immediately retires its
  skills from search, list, and get.
- New [Skills and Guidance Operations Guide](docs/guides/skills-guide.md):
  day-2 content operations for operators — adding, revising, and removing
  skills and sources (local ConfigMap-backed and git), pre-flight
  validation, verification, metrics, and troubleshooting.

### Added — SPEC-014: Skills and Grounded Guidance

- New `shared/shared-contracts/schemas/skill.schema.json` (R-1): canonical
  skill envelope (`skill_id`, `title`, `description`, `tags`, `version`,
  `source_id`, `source_path`, optional `source_ref` / `source_url`
  attribution, `updated_at`, `body`) plus the `skill-format.md` frontmatter
  convention (size caps, slug rule, and an open-source skill discovery
  appendix). Contract tests bind skills-hub Pydantic models to the schema.
- New `products/skills-hub` product (R-2): FastAPI service mirroring the
  audit-service chassis — frozen-dataclass `SKILLS_*` settings, structured
  logging, `/health`, `/metrics` (incl. `skills_syncs_total{source,result}`),
  federated multi-source ingestion (`local` directories and `git`
  repositories, namespaced `<source_id>/<slug>` ids), per-source atomic sync
  with jitter (a failed sync keeps the prior slice), and a `SkillStore`
  protocol with in-memory and PostgreSQL backends selected via
  `SKILLS_STORE_BACKEND`. Includes a standalone validator CLI
  (`python -m skills_hub.validate <dir>`) for team pre-flight checks.
- Retrieval API (R-3): `GET /api/v1/skills` (source/tag filters, capped
  offset pagination), `GET /api/v1/skills/{skill_id:path}` (full record,
  structured 404), `GET /api/v1/skills/search` (deterministic ranking —
  title ×3 / tags ×2 / body ×1 with `skill_id` tie-break, excerpt ≤ 400
  chars, provenance), and an auth-exempt `/api/v1/skills/status`. Query auth
  uses a dedicated Basic registry `SKILLS_QUERY_CLIENTS` plus projected
  workload tokens — deliberately distinct from the SPEC-013 shared
  ingest/query credential.
- Skills connector in tool-gateway (R-4): read-only `skills.search` /
  `skills.get` tools with Basic-auth httpx transport (10s timeout) and
  structured error mapping (404 → `SKILL_NOT_FOUND`, unreachable →
  `TOOL_EXECUTION_ERROR`); registered only when `GATEWAY_SKILLS_SERVICE_URL`
  is set (unset preserves today's tool surface byte-for-byte). Settings:
  `GATEWAY_SKILLS_SERVICE_URL`, `GATEWAY_SKILLS_CLIENT_ID`,
  `GATEWAY_SKILLS_CLIENT_SECRET`.
- Runbook-aware answers (R-5): `DEFAULT_SYSTEM_PROMPT` gains the skills
  discipline (consult skills for procedure/remediation, cite by title, keep
  guidance separate from live cluster evidence, report no-match honestly);
  `skills.search` / `skills.get` join the default auto-allow list. Portal
  evidence panels render skills frames without changes.
- Deployment and sample content (R-6): dev-k8s deploys `skills-hub` with two
  sample sources — `sre-alerting` (six adapted Prometheus Operator alert
  runbooks, Apache-2.0) and `platform-runbooks` (five adapted Kubernetes
  troubleshooting guides, CC-BY-4.0), each with NOTICE attribution and a
  team contribution README. Postgres gains a `skills` database (initdb
  ConfigMap for fresh clusters; `sync-skills-secrets.sh` idempotently creates
  it and provisions the shared query secret on existing clusters,
  `SKIP_SKILLS_SECRETS=true` opt-out). Deterministic e2e smoke test
  `shared/platform-ops/e2e/skills-demo.sh` asserts source sync, alert-name
  search ranking, and the `skills.search` tool_call/tool_result frame pair in
  a scripted chat; getting-started gains a Skills demo tour (UAT checklist +
  operator training).

### Added — SPEC-013: Durable Audit Trail

- New `shared/shared-contracts/schemas/audit-event.schema.json` (R-1):
  canonical audit-event envelope (`event_id`, `occurred_at`, `event_type`,
  `service`, `request_id`, `subject`, `username`, optional `actor`
  delegation chain, `roles`, optional `session_id`, `outcome`, typed
  `details`); covers `tool_invoked`, `policy_decision`, `token_exchange`,
  `session_created`, `chat_started`, `chat_completed`. Contract tests bind
  emitter and audit-service Pydantic models to the schema.
- Canonical policy bundle: new `audit:read` action granted to `auditor`
  and `platform-admin` only (deny-by-default for all other roles);
  synced to all consumer copies via `make sync-policy`.
- New `products/audit-service` product (R-2): FastAPI service with
  frozen-dataclass `AUDIT_*` settings, structured logging, `/health`,
  `/metrics`, and an `AuditStore` protocol with two backends —
  `InMemoryAuditStore` (dev/tests) and `PostgresAuditStore` (psycopg v3
  async pool, keyset pagination), selected via `AUDIT_STORE_BACKEND`.
- Authenticated non-blocking ingest (R-3): `POST /api/v1/audit/events`
  accepts batches (capped by `AUDIT_MAX_BATCH`), rejects malformed events
  with 400 + counter. Auth via static Basic client registry
  (`AUDIT_INGEST_CLIENTS`) or projected workload tokens
  (`AUDIT_WORKLOAD_*`), mirroring SPEC-008/009 credential vocabulary.
- Fire-and-forget audit emitters (R-3) in tool-gateway, platform-gateway,
  and identity-broker: 2s bounded timeout, failure counted in
  `audit_emits_total`, never blocks or fails the originating request;
  feature-gated by `GATEWAY_AUDIT_SERVICE_URL`,
  `PLATFORM_GATEWAY_AUDIT_SERVICE_URL`, and `IDENTITY_AUDIT_SERVICE_URL`
  (unset preserves log-only behavior exactly). Structured-log emission
  retained alongside.
- Permission-scoped query API (R-4): `GET /api/v1/audit/events` with
  filters (`username`, `session_id`, `request_id`, `event_type`,
  `service`, `since`/`until`), newest-first cursor pagination, verbatim
  envelope round-trip. platform-gateway proxies the route under
  `/api/v1/audit/*` with portal-token verification and
  `enforce_policy("audit:read")` (structured 403 on deny).
- Operator portal audit view (R-5): read-only audit trail function view
  with filter bar, newest-first table, cursor pagination, and expandable
  event envelopes; navigation entry rendered only for `auditor` /
  `platform-admin` roles.
- Operator portal shell: two-column layout replacing the stacked panels —
  left sidebar carries the logo and the function list (Chat, Settings &
  Debug, Audit trail); the main column shows one function at a time with
  state preserved across switches. Narrow screens (≤800px) collapse the
  sidebar into a hamburger-triggered off-canvas drawer (the topbar stays
  above the open drawer so the hamburger always toggles).
- Operator portal sidebar footer: a user card (initials avatar, username,
  icon-only Sign in / Sign out with tooltips; clicking the user opens a
  popup menu showing granted roles, extensible with future user-related
  info) and a platform version card — separated from the function list.
- Operator portal polish: sticky audit-table column headers inside the
  scroll area, `:focus-visible` keyboard focus rings, and
  `prefers-reduced-motion` guards on blinking/spinning animations.
- Retention and bounded growth (R-6): `AUDIT_RETENTION_DAYS` (default 30)
  window eviction + `AUDIT_MAX_EVENTS` hard cap, batched deletes,
  eviction counted in metrics, never blocks ingest; window and store size
  exposed in `/health` / `/metrics`.
- dev-k8s overlay: PostgreSQL StatefulSet + PVC + Service, audit-service
  deployment/service/runtime-config (`AUDIT_STORE_BACKEND=postgres`),
  `sync-audit-secrets.sh` for shared ingest credentials (wired into
  `make deploy` with skip switch), emitter `*_AUDIT_SERVICE_URL` env in
  the three emitting services, policy ConfigMap updated.
- Root Makefile: `audit-service` added to `PYTHON_PRODUCTS`,
  `IMAGE_PRODUCTS`, `.images.env`, and the kind-load list.
- Operator guides updated: audit-service in the architecture topology and
  service inventory, `AUDIT_*` variables in the configuration reference,
  audit-service activation checklist, and troubleshooting entries for
  missing events, ingest 401, and query denial.

### Fixed — SPEC-013: Durable Audit Trail

- `PostgresAuditStore.add` now wraps `details` in `psycopg.types.json.Jsonb`
  before insert; a raw dict is not adaptable for the `JSONB` column and
  every ingest failed with `psycopg.ProgrammingError: cannot adapt type
  'dict'`. Caught during the dev-k8s live test (unit tests exercised the
  in-memory backend); regression test added against the fake psycopg
  driver (audit-service tests 67 → 68).

## 0.1.0 — 2026-08-11

### Added — SPEC-012: Operator Guide and Deployment Documentation

- New operator-facing documentation suite under `docs/guides/`:
  - `getting-started.md` (R-1): prerequisites, build→deploy→verify walkthrough,
    secrets provisioning, end-to-end verification checklist.
  - `configuration-reference.md` (R-2): feature activation matrix, cross-service
    dependency chains (token delegation, identity, tool relay), per-service
    environment variable tables, secret contracts, runtime profiles, policy
    management workflow.
  - `troubleshooting.md` (R-3): symptom-based diagnostics for nine common
    failure modes (access not granted, no tools, login fails, stream stalls,
    policy denied, Elastic not configured, ErrImagePull, policy load failure,
    token expiry).
  - `tool-configuration.md` (R-4): tool inventory (K8s + Elastic), connector
    activation checklists, RBAC configuration, redaction engine reference,
    new-connector extension guide.
  - `architecture-overview.md` (R-5): service topology, request flow, trust
    chain, token delegation, workload identity, RBAC model, with Mermaid
    diagrams.
  - `README.md`: guide index and navigation.
- Root Makefile: added `sync-policy` target (copy canonical `policy-default.yaml`
  to all consumer locations) and `validate-policy` target (validate bundle
  against `policy-rule.schema.json`); `validate-policy` wired into `make verify`.
- New `shared/shared-contracts/scripts/validate_policy.py` validation script.

### Changed — Evidence and audit groups follow their reply inline

- operator-portal: replaced the bottom evidence drawer with per-turn
  collapsible groups rendered inline directly after the agent reply they
  ground. Each question's evidence cards and audit card follow that
  answer; groups stay collapsed by default (the summary line shows the
  counts) and are created lazily on the first tool frame, so purely
  conversational turns leave no empty group.

### Changed — Evidence and audit cards are kept per turn

- operator-portal: evidence and audit cards are no longer wiped when the
  next question is sent. Each chat turn gets its own collapsible group in
  the evidence drawer ("Turn N · HH:MM · counts"), created lazily on the
  first tool frame and bounded to the last 20 turns; the drawer summary
  shows session totals. Logout resets the drawer.

### Changed — Evidence moved to a collapsed drawer; audit card; sticky scroll

- operator-portal: tool evidence no longer renders inline in the chat
  column (it crowded out the streamed answer and fought the auto-scroll).
  It now lives in a dedicated collapsed drawer above the input bar with a
  live summary line ("N calls · X ok · Y denied"), matching the existing
  Settings & Debug drawer idiom.
- Added an "Audit trail · this turn" card assembled from streamed evidence
  (tool, status, executed_at, duration, risk, source) plus request/session
  IDs — self-service inspection of the caller's own turn. The authoritative
  backend audit trail (cross-user, persistent) remains a future spec.
- Sticky smart-scroll: the chat view only follows the stream while the
  reader is near the bottom, so growing evidence no longer yanks the
  viewport away from text being read.

### Fixed — Rotated delegated tokens no longer strand sessions without tools

- agent-platform: delegated tokens rotate mid-session (portal token refresh,
  300s TTL), but tool discovery only ran at agent creation — keyed by
  session — so a rotated token never got tool definitions and every
  subsequent turn injected the no-tools notice until browser refresh.
  `_build_request_toolkit` now discovers with the current token on cache
  miss, and empty discovery results are never cached (both per-request and
  `_ensure_toolkit` paths) so a transient failure can no longer poison the
  cache. `_ensure_toolkit` additionally reuses the discovery result instead
  of discovering twice.

### Fixed — Evidence panel frames, audit log visibility, cluster-wide read access

- agent-platform: the stream event adapter (`AgentStreamEvent` /
  `_normalize_stream_event`) now passes v3 `tool_call`/`tool_result` frames
  through untouched. Previously the pre-v3 Pydantic model coerced every tool
  frame to `message_delta` and stripped all evidence fields, so the portal
  evidence panel never rendered despite kernel and portal support.
- All four Python services: `configure_logging()` now raises the root logger
  to INFO (overridable via `LOG_LEVEL`) at app startup. Uvicorn's WARNING
  default silently discarded every `log_event` record — including the
  `tool_invoked` audit trail and `http_request` middleware events.
  Convention codified in `shared-contracts/observability-conventions.md`.
- dev-k8s: tool-gateway RBAC upgraded from a namespaced Role to a
  cluster-wide read-only ClusterRole (get/list/watch on core, apps, batch,
  networking, and autoscaling resources) so the agent can health-check any
  namespace (e.g. `argocd`). No mutating verbs are granted; tool surface and
  deny-by-default policy remain the enforcement layers.

### Changed — Permission auto-approval narrowed to an explicit allow-list

- agent-platform: the `RequireUserConfirmEvent` bypass now applies only to
  read-only tools on a vetted allow-list (`DEFAULT_AUTO_ALLOWED_TOOLS`,
  overridable via `AGENT_GATEWAY_TOOL_AUTO_ALLOW`), instead of every
  read-only tool. Anything outside the allow-list keeps the interactive ASK
  default. Admission, policy enforcement, and per-invocation audit logging
  by the tool-gateway are unchanged. (L3 security review remediation,
  CWE-862.)

### Added — SPEC-011: Observability Connector and Evidence Panels

- Extended the agent stream event contract (`agent-stream-event.schema.json`,
  v3) with `tool_call` and `tool_result` event types carrying tool name,
  call ID, parameters, status, evidence metadata, and data summary.
- agent-platform: toolkit closures now post `tool_call`/`tool_result` events
  to a per-request `asyncio.Queue`; trace events are drained into the SSE
  stream alongside text deltas. `data_summary` is truncated to
  `AGENT_TOOL_DATA_SUMMARY_MAX_CHARS` (default 2000) with a structured
  marker; full payloads stay in audit logs only.
- tool-gateway: new Elastic observability connector
  (`elastic.search_logs`, `elastic.get_service_health`,
  `elastic.get_active_alerts`) following the Kubernetes connector pattern
  (lazy init, executor-based sync, feature-gated by `GATEWAY_ELASTIC_ENABLED`).
  Auth supports API key (preferred) and basic auth with TLS verification
  toggle. Added `elasticsearch>=8.0,<9.0` dependency.
- operator-portal: evidence panel renders tool call/result cards with status
  badges, collapsible parameters and data summaries, and evidence metadata.
  Panel appears on first `tool_call` event and clears on each new request.
- dev-k8s overlay: `GATEWAY_ELASTIC_ENABLED=false` with commented Elastic env
  var examples in tool-gateway `runtime-config.env`; gated off by default.

### Fixed — Token delegation secrets auto-provisioning

- New `sync-delegation-secrets.sh` script generates a shared client secret,
  creates both `platform-gateway-runtime-secrets` and
  `identity-service-runtime-secrets` K8s secrets, and restarts the affected
  deployments. Previously these optional secrets were not provisioned by
  `make deploy`, causing silent delegation failures — the agent ran without
  tools ("access not granted").
- `make deploy` now calls `sync-delegation-secrets.sh` automatically after
  the overlay apply; set `SKIP_DELEGATION_SECRETS=true` when secrets are
  injected externally (e.g. CI pipelines).
- dev-k8s README: new "Token Delegation Secrets" section with usage,
  verification commands, and skip switch.

### Changed — Observer read-only tool access + anti-fabrication guardrail

- Policy bundle now grants `read-only-observer` the `tools:list` and
  `tools:invoke` actions, aligning the implementation with the authorization
  matrix (observers may perform tier-0 reads, and every registered tool is
  read-only). Previously observers were denied tool discovery (403), which
  left the agent with an empty toolkit and caused it to emit fabricated
  "health check" reports. All four byte-identical copies updated
  (shared-contracts, tool-gateway, platform-gateway, dev-k8s overlay).
- agent-platform system prompt hardened against fabrication: the agent must
  ground every factual claim in real tool output and state explicitly when no
  tools are available or a call fails, instead of inventing metrics/statuses.

### Fixed — Agent toolkit registration (AgentScope 2.x) + deterministic no-tools guard

- agent-platform: gateway tools are now built with the AgentScope 2.x API —
  `FunctionTool` objects passed to `Toolkit(tools=[...])` instead of the
  removed `Toolkit.add()`, which raised `AttributeError` per tool and left
  every session with an empty toolkit (zero tool invocations, fabricated
  health reports). The gateway's `parameters_schema` is bound explicitly
  (closures expose only `**kwargs`) and normalized to the object-with-
  properties shape AgentScope validates.
- agent-platform: deterministic anti-hallucination guard — when a tool
  gateway is configured but zero tools are registered for the turn, the
  kernel injects an explicit "no operational tools" notice into that turn
  instead of relying solely on the standing system prompt.
- agent-platform: gateway tools now auto-approve read-only execution.
  AgentScope 2.x defaults custom function tools to an interactive
  user-confirmation prompt (`RequireUserConfirmEvent`), which a headless SSE
  stream can never answer — the agent stalled and the portal showed "No
  response received". `GatewayFunctionTool` returns ALLOW for read-only
  tools (admission and policy are enforced by the tool-gateway), mirroring
  AgentScope's MCP adapter; non-read-only tools still require confirmation.

### Fixed — Deployment env collisions and portal stream rendering

- All five dev-k8s app deployments set `enableServiceLinks: false`:
  Kubernetes' legacy service-link env vars (e.g.
  `AGENT_SERVICE_PORT=tcp://…`, injected for the same-named Service)
  collided with the services' own port settings and crash-looped
  `agent-service` on startup. Service discovery uses DNS names only.
- operator-portal chat stream rendering fixed: the UI read `payload.event`
  while the gateway/agent stream contract emits `payload.type`, so every
  `message_delta` was dropped and the response area showed
  "[stream completed with no visible text]". The portal now reads `type`
  (with `event` as a legacy alias) and treats stream EOF as completion
  when no `message_end` event arrives.

### Changed — SPEC-010 code-review follow-ups

- platform-gateway `/health/ready` now verifies the policy bundle loads
  (reports a `policy_rules` count when ok; `status: degraded` with
  `policy_error` on `PolicyLoadError` instead of silently reporting ok).
- tool-gateway protected-action vocabulary corrected to the actual routes
  (`tools:list` / `tools:invoke`); regression tests added for the readiness
  degradation path.

### Changed — Shared `base-uv` container base image and non-root enforcement

- New shared Python base image `luban-aiops/base-uv:al2023`
  (`shared/base-images/base-uv/Dockerfile`): Amazon Linux 2023 minimal with
  a pinned uv (`UV_VERSION` ARG, default 0.12.1 — never `latest`), no system
  Python (uv resolves the interpreter from each product's `.python-version`
  during `uv sync`; `UV_PYTHON`/`PYTHON_VERSION` ARG default 3.12 is the
  deterministic fallback), and a non-root `app` user (uid 1000). Built by
  the new `make base-images` target, wired as a prerequisite of `make build`
  (overridable: `make base-images BASE_UV_UV_VERSION=...`).
- All four Python product Dockerfiles (`agent-platform`, `identity-broker`,
  `platform-gateway`, `tool-gateway`) now build `FROM luban-aiops/base-uv:al2023`;
  the env contract, `WORKDIR`, and `USER` move into the base, replacing the
  divergent bookworm-slim and ad-hoc amazonlinux bootstrap.
- operator-portal switches to `nginxinc/nginx-unprivileged:1.27-alpine` and
  listens on 8080 (nginx.conf, deployment containerPort, web-ui Service
  port/targetPort, dev-k8s README port-forward).
- All five app deployments gain a non-root `securityContext`
  (`runAsNonRoot`, `runAsUser` 1000 — 101 for web-ui,
  `allowPrivilegeEscalation: false`, `seccompProfile: RuntimeDefault`).
- Docs: `python-container-strategy.md` records the Option B migration as
  executed; backend layout convention updated.

### Changed — Explicit target platform for image builds

- New `IMAGE_PLATFORM` build parameter (default `linux/amd64`, the deployment
  target) in the root `Makefile` and `mk/image.mk`: applied to
  `make base-images` and forwarded to every product build, so base and product
  images always share one platform. Override per build, e.g.
  `make build IMAGE_PLATFORM=linux/arm64` for native local/kind builds on
  arm64 hosts.

### Changed — Build configuration extracted to `mk/defaults.mk`

- New `mk/defaults.mk` is the single source of truth for overridable build
  settings (`IMAGE_PLATFORM`, `IMAGE_TAG_PREFIX`/`IMAGE_TAG_PROFILE`,
  `REGISTRY`, `AUTO_LOAD_KIND`/`KIND_CLUSTER_NAME`, `BASE_UV_*`), included by
  the root `Makefile` and by `mk/image.mk`, so root-driven and standalone
  product builds resolve identical defaults. All values use `?=`, so
  command-line overrides still win; `mk/` fragments keep processing logic
  only. `IMAGE_TAG` and `IMAGE_CONTEXT` intentionally stay in `mk/image.mk`
  (computed fallback / per-product hook).

### Changed — SPEC-010: Platform Gateway Extraction (ADR-0005)

- Split the former combined gateway into two products with the boundaries
  ADR-0005 assigns: new `products/platform-gateway` owns the portal-facing
  edge (token verification for portal sessions, action policy, chat/session
  proxying, broker delegation client, `/api/v1` portal routes); the existing
  product renames its package `api_gateway` → `tool_gateway` and keeps only
  the tool/connector home (`ToolRegistry`, connectors, `tools:list` /
  `tools:invoke`, redaction choke point, tool audit). HTTP contract shapes,
  deny-by-default policy, and audit fields are unchanged.
- env contract (Q-1): edge settings rename `GATEWAY_*` → `PLATFORM_GATEWAY_*`;
  `GATEWAY_*` stays tool-scoped only (k8s, policy path, redaction, token
  audience, auth knobs, host/port).
- k8s (Q-2): `api-gateway` deployment/service/image rename to
  `platform-gateway`; new `tool-gateway` deployment/service/SA/RBAC with
  image `luban-aiops/tool-gateway`; policy ConfigMap `gateway-policy` →
  `platform-policy` mounted on both services from one shared bundle;
  `deploy-overlay.sh` and root `Makefile` updated (`.images.env` gains
  `PLATFORM_GATEWAY_IMAGE` + `TOOL_GATEWAY_IMAGE`). Portal `nginx.conf`
  proxies to `platform-gateway:8000`.
- identity (Q-3/Q-4): portal platform JWTs change audience `tool-gateway` →
  `platform-gateway` (broker `IDENTITY_TOKEN_AUDIENCE` default, overlay,
  schema note, edge verifier); delegated tokens keep `aud = tool-gateway`.
  The edge registers as a new `platform-gateway` broker client
  (`act.sub = platform-gateway`); the old `tool-gateway` client entry is
  removed.
- guards: both gateways gain route-inventory tests pinning their surfaces
  (edge: `/api/v1/*` portal routes only; tool: health/metrics +
  `/api/v2/tools*` only). Metric names unchanged (`gateway_*` /
  `delegation_*` remain the scrape contract).
- docs: platform-gateway/tool-gateway READMEs, dev-k8s README (incl. the
  one-time `kubectl delete deployment/api-gateway service/api-gateway`
  cleanup), workspace model, product boundaries, layout convention, and
  governance label scheme updated; spec status `delivered`.

### Added — SPEC-009: Pre-Production Hardening (Tool Output Redaction and Workload-Identity Service Tokens)

- Closes the two deadline-bound Release 1 deferrals before the first non-dev
  deployment: SPEC-007 Q-3 (tool-output redaction) and the SPEC-008 R-3
  workload-identity upgrade path.
- tool-gateway: code-owned redaction engine applied at the single
  `invoke_tool` choke point before both the response and the audit log —
  value patterns (JWTs, `Bearer`/`Basic` values, PEM private keys, AWS-style
  key IDs) plus a bounded explicit key list; clean output passes through
  byte-identical. Fail-closed: results whose redacted fraction exceeds
  `GATEWAY_REDACTION_OVERFLOW_FRACTION` (default 0.2) are withheld with a
  `REDACTION_OVERFLOW` error. New `gateway_tool_redacted_spans_total{tool}`
  metric and `redacted_spans` audit field; `GATEWAY_REDACTION_ENABLED`
  (default `true`) is the dev-debugging opt-out.
- identity-broker: the exchange endpoint now also accepts Kubernetes
  projected service-account tokens as the service credential
  (`Authorization: Bearer`), validated against the cluster OIDC issuer JWKS
  (`IDENTITY_WORKLOAD_ISSUER_URL`, empty = feature off) with an audience
  check (`IDENTITY_WORKLOAD_AUDIENCE`) and a workload-subject registry
  (`IDENTITY_WORKLOAD_CLIENTS`); delegated-token claims are identical to the
  static path. Invalid/expired/wrong-audience/unregistered tokens yield 401.
- tool-gateway delegation: `GATEWAY_WORKLOAD_TOKEN_PATH` prefers the
  projected token file (re-read per exchange; kubelet rotates it in place)
  over the static secret; a missing file falls back to the static secret
  with a once-per-process warning. Unsetting the path is the rollback
  switch; the dev path is unchanged.
- docs: dev-k8s README documents the redaction opt-out and the workload-token
  contract (projected volume snippet, issuer/audience env names); the
  gateway `runtime-secrets.example.env` marks the static secret as the dev
  fallback.

### Added — Release 1 (SPEC-008: Service-to-Service Identity)

- Implemented ADR-0004 broker-mediated token delegation, closing SPEC-007 R-4/R-6
  and open questions Q-1/Q-2 and completing Release 1.
- identity-broker: platform JWTs are now audience-bound (`aud`, default
  `["tool-gateway"]`); added `POST /api/v1/auth/exchange` which authenticates a
  registered service credential, verifies the subject token, and mints a
  short-lived delegated token (`sub`/`username`/`roles` copied never elevated,
  `act` naming the caller, `aud` = requested audience, TTL
  `IDENTITY_DELEGATED_TOKEN_TTL_SECONDS` default 300s). New service-client
  registry `IDENTITY_SERVICE_CLIENTS` and `token_exchange_total` metric.
- tool-gateway: verifies token `aud` (`GATEWAY_TOKEN_AUDIENCE`); exchanges the
  verified user token for a delegated token via a per-user TTL cache
  (`delegation_exchange_total`, `delegation_cache_total` metrics) and forwards
  it downstream as `Authorization: Bearer`; exchange failure is non-fatal
  (chat proceeds tool-less). Tool routes derive identity solely from the
  verified token (`identity_context` removed from the invoke contract);
  `GET /api/v2/tools` is authenticated and gated by a new `tools:list` policy
  action; audit logs record both `sub` and `act`.
- agent-platform: relays the delegated token as a bearer token on tool
  discovery and invocation, bound per-user into the toolkit closures (no
  cross-user sharing); removed `identity_context` from the invoke payload;
  no-token path degrades to an empty Toolkit / structured error.
- contracts: `identity-token.schema.json` documents `aud` (required) and `act`
  (optional) with a delegated-token note; `policy-default.yaml` adds
  `tools:list`. Contract tests bind both gateway and identity-broker models to
  the updated schema.
- dev-k8s overlay: sets `GATEWAY_TOKEN_AUDIENCE`, `GATEWAY_SERVICE_CLIENT_ID`,
  `IDENTITY_TOKEN_AUDIENCE`, `IDENTITY_DELEGATED_TOKEN_TTL_SECONDS`; the gateway
  and broker service secrets are provisioned as optional K8s Secrets
  (`api-gateway-runtime-secrets`, `identity-service-runtime-secrets`) and are
  not committed.

### Changed — Single Image Build Path

- Folded `build-images.sh` into `make build`: the root target now builds all
  four product images (delegating to each product's Makefile) with a
  coordinated `IMAGE_TAG`, writes `.images.env` for `make deploy`, and keeps
  the `AUTO_LOAD_KIND` / `KIND_CLUSTER_NAME` kind-load support.
- Removed `shared/platform-ops/gitops/dev-k8s/build-images.sh` and the separate
  `build-images` Make target; `make build` is now the single build path.
- Per-product `build` always tags the local image and adds a registry tag when
  `REGISTRY` is set; `push` re-tags then pushes, so build and push stay
  consistent.
- Updated the dev-k8s README to use `make build` / `make deploy` and corrected
  stale `dev-k8s-transitional` paths to `dev-k8s`.

### Changed — Build & Verification Tooling

- Added a forge-agnostic root `Makefile` (with per-product Makefiles and shared
  `mk/` fragments) consolidating project routines: `verify` (the
  pre-commit/pre-push gate), `test`, `sync`, `lint`, `build`, `push`,
  `overlays`, `deploy`, and `clean`.
- Removed the GitHub Actions workflows (`.github/workflows/ci.yml`,
  `overlays.yml`). The verification gate now lives in `make verify`,
  decoupling the project from GitHub-specific CI; the same checks run
  locally and under any CI provider.
- Updated the SDD enforcement guidance (`docs/specs/README.md`) to name
  `make verify` as the mechanical gate in place of the CI workflows.

### Added — Release 1 (SPEC-007: Tool Execution Framework)

- Added tool execution framework to tool-gateway: `ToolRegistry`, `BaseTool`
  abstraction, and structured `ToolResult` evidence envelope.
- Added Kubernetes read-only connector with four tools: `k8s.list_pods`,
  `k8s.get_pod`, `k8s.get_events`, `k8s.get_pod_logs` (kubernetes-client/python).
- Added `GET /api/v2/tools` (discovery) and `POST /api/v2/tools/invoke`
  (execution) endpoints with policy enforcement and audit logging.
- Added `tools:invoke` policy action granted to platform-admin, operator, and
  developer roles; read-only-observer is excluded.
- Added agent-platform Toolkit integration: when `TOOL_GATEWAY_URL` is
  configured, the AgentScope kernel discovers and registers gateway tools so
  the LLM can autonomously invoke them.
- Added shared contract schemas: `tool-invocation.schema.json` and
  `tool-result.schema.json`.
- Added RBAC (ServiceAccount + Role + RoleBinding) to dev-k8s overlay granting
  tool-gateway read-only access to pods, events, and pods/log.

### Changed — Release 1 Close

- Changed `GATEWAY_REQUIRE_AUTH` default from `false` to `true` in code and
  the dev overlay, completing the outstanding SPEC-001 release-close step.
  Unauthenticated requests to business routes now return `401` by default.
- Added `POST /api/v1/auth/refresh` to identity-broker: exchanges a Keycloak
  refresh_token for a fresh platform JWT, re-fetching userinfo so role changes
  are picked up on refresh.
- Added gateway proxy route `POST /api/v1/auth/refresh` forwarding to
  identity-broker.
- Added silent token refresh in operator-portal: schedules a background refresh
  60 seconds before JWT expiry; on failure, clears the session and prompts
  re-authentication.
- Collapsed the dual GitOps overlay (`dev-k8s-transitional` + `dev-k8s-native`)
  into a single `shared/platform-ops/gitops/dev-k8s` overlay. The
  transitional/native distinction no longer exists at the code level after
  SPEC-002 retired the transitional surface; a single overlay removes
  configuration drift and maintenance overhead.

### Added — Release 1 (SPEC-001 .. SPEC-006)

- Added `SPEC-001` release-1 platform hardening (delivered): gateway authentication
  enforcement behind `GATEWAY_REQUIRE_AUTH`, role propagation in structured logs,
  transitional session integrity (ownership scoping, 404 on unknown session IDs,
  TTL/size-bounded store, per-session agent isolation), typed contract
  enforcement bound to shared-contracts schemas, cached backend resolution with
  bounded outbound timeouts, and the GitHub Actions CI baseline.
- Added `SPEC-002` agent-service contract (delivered): platform-owned
  agent-service contract (ADR-0003) with v2 envelope (`content` replacing
  `response`, simplified stream events, header-based identity), `/api/v2/`
  adapter in agent-platform over the AgentScope kernel, tool-gateway migrated to
  a single agent-service client, retired the transitional `/api/v1/` surface,
  and bidirectional contract tests.
- Added `SPEC-003` identity-trust hardening (delivered): identity-broker now
  issues RSA-signed platform JWTs (`POST /api/v1/auth/token`) and publishes a
  JWKS endpoint (`GET /.well-known/jwks.json`, RFC 7517); the gateway verifies
  tokens locally via PyJWKClient, validates the `iss` claim, and derives
  `X-User-ID` exclusively from verified claims; removed `DEFAULT_USER_ID`
  fallback in favour of explicit `GATEWAY_DEV_USER` with synthetic identity
  logging.
- Added `SPEC-004` deny-by-default policy enforcement (delivered): defined the
  policy contract in shared-contracts (`policy-rule.schema.json`,
  `policy-decision.schema.json`, `policies/policy-default.yaml`) as a strict
  `action_authz` subset of the Tier-1 policy specification; the gateway
  evaluates every business request (`chat`, `session:create`, `session:read`)
  against a versioned role→action bundle, denying by default with a structured
  403 and audit-logging every decision.
- Added `SPEC-005` observability baseline (delivered): metrics naming
  conventions, OTel switch semantics, and `x-request-id` ↔ `trace_id` bridging
  rule in `shared/shared-contracts/observability-conventions.md`; all three
  Python services expose an always-on `/metrics` Prometheus surface plus an
  opt-in OTLP push pipeline gated by `OTEL_ENABLED`; standard HTTP RED metrics,
  domain counters (`agent_sessions_created_total`, `identity_tokens_issued_total`,
  `gateway_policy_decisions_total`, `gateway_token_verification_total`), and
  Prometheus scrape annotations on every deployment manifest.
- Added `SPEC-006` session durability (delivered): Redis-backed session store
  with strategy-pattern interface (`InMemorySessionStore` for dev/CI,
  `RedisSessionStore` for deployed environments); backend selection via
  `SESSION_STORE_BACKEND` env; graceful fallback to in-memory when Redis is
  unreachable; session store backend and readiness reported in `/health`;
  `session_store_backend`, `session_store_errors_total`, and
  `session_store_fallbacks_total` Prometheus metrics.
- Added ADR-0001 (SDD adoption), ADR-0002 (AgentScope 2.0 kernel), and
  ADR-0003 (platform-owned agent-service contract) under `docs/adr/`.
- Added spec-driven development workflow under `docs/specs/` with plan/spec/tasks
  templates and delivered specs for SPEC-001 through SPEC-006.
- Added `docs/agentic-aiops-platform/part-1b-framework-revalidation.md`.

### Added — Release 0

- Added typed provider-specific runtime options for `products/agent-platform`,
  including provider-owned defaults for `dashscope`, `deepseek`, and `openai`.
- Added provider adapters and a provider registry that resolve runtime settings
  into concrete AgentScope chat model implementations.
- Added gateway backend adapters so `products/tool-gateway` can resolve
  `transitional` versus `native` agent-service backends through a shared
  interface.
- Added deterministic local image build and deploy scripts for the GitOps-based
  Kubernetes development overlays under `shared/platform-ops/gitops/`,
  including both `dev-k8s-transitional` and `dev-k8s-native`.
- Added shared runtime profile overlays and selector helpers so provider
  selection stays explicit, reviewable, and Git-diffable in the deployment
  layer.
- Added Dockerfiles for the Release 0 development overlay services and an
  `nginx` proxy baseline for `products/operator-portal`.
- Added a minimal `OIDC` authorization-code callback path across
  `products/operator-portal`, `products/identity-broker`, and
  `products/tool-gateway`.
- Added configurable `OIDC_SCOPES` support so the shared identity flow can work
  against realms that do not expose the default `profile` and `email` scopes.
- Added focused tests for runtime settings, runtime metadata, provider registry
  behavior, and gateway backend resolution.
- Added release notes under `docs/agentic-aiops-platform/release-notes/`.
- Added a Git-tracked Keycloak browser-client reconciliation script for
  `dev-k8s-transitional` so the portal client redirect URIs, PKCE/public-client
  settings, and `preferred_username` / `email` mappers stay durable across
  overlay deploys.

### Changed

- Changed runtime metadata to expose resolved provider, model, base URL, and
  provider option details instead of only raw environment overrides.
- Changed `api-gateway` development overlay configuration to prefer `auto`
  backend resolution rather than pinning `AGENT_BACKEND_MODE` to
  `transitional`.
- Changed the platform-ops layout to use the durable
  `shared/platform-ops/gitops/` root for active operational assets while
  keeping `Release 0` wording in milestone-planning documents.
- Changed the development overlay rollout workflow to use explicit,
  overlay-specific image tags and per-overlay `.images.env` state instead of
  reusing a single static placeholder tag.
- Changed the operator portal browser baseline to default API requests to the
  current origin and route them through the local `nginx` proxy.
- Changed backend package layout across `agent-platform`, `tool-gateway`, and
  `identity-broker` to follow a clearer FastAPI-by-responsibility structure.
- Changed the gateway and portal request path so authenticated bearer identity
  now overrides manually entered user IDs for session and chat operations.
- Changed the GitOps overlay roots to set the deployment namespace explicitly so
  shared runtime-profile config maps are created in the same namespace as the
  services that consume them.
- Changed the committed `dev-k8s-transitional` OIDC baseline to match the live
  shared sandbox `Keycloak` validation path used for `Release 0` closure.

### Fixed

- Fixed a runtime settings mismatch where direct `RuntimeSettings(...)`
  construction could pair a provider with the wrong provider-options type.
- Fixed development cluster rollout ambiguity caused by stale same-tag image reuse.
- Fixed native AgentScope streaming compatibility so incremental reply updates
  preserve all accumulated content blocks instead of dropping earlier blocks.
- Fixed the native overlay image-build wrapper so it is directly executable as
  documented and writes to the correct overlay-specific image-state file.
- Fixed local runtime artifact hygiene by ignoring generated `**/.workspaces/`
  directories.
- Fixed the remaining `Release 0` auth gap by adding identity-broker token
  exchange, portal callback handling, optional identity-service secret
  injection, and structured request/session logs across the core services.
- Fixed fresh-namespace startup for `api-gateway` and `identity-service` by
  ignoring Kubernetes service-link `*_PORT=tcp://...` values when parsing their
  listen ports.
- Fixed the live `Release 0` overlay wiring so `agent-platform-runtime-profile`
  is created in the target namespace instead of `default`.
- Fixed the portal SSO identity contract in the shared sandbox realm by making
  the browser client emit durable `preferred_username` and `email` claims, so
  authenticated identity no longer falls back to the UUID subject value.
- Fixed the remaining `Release 0` documentation drift so the checklist,
  release notes, and closure status now consistently describe `Release 0` as
  completed with only post-closure follow-up items remaining.
