# Delivery Roadmap

## Objective

Define a delivery roadmap for the enterprise-grade agentic AIOps platform where each release:

- is self-contained
- adds one major capability on top of the previous release
- has explicit integration points
- is straightforward for operations teams to verify

This roadmap provides a release-by-release delivery view. Implementation details are tracked in feature specs under `docs/specs/`.

## Roadmap Principles

### 1. One release, one major value theme

Every release should have a clear purpose that operations teams can understand without reading the full platform design.

### 2. Releases should stack, not sprawl

Each release should extend the previous one rather than opening many parallel fronts of partially completed work.

### 3. Validation must happen inside each release

Each release must be verifiable by real user workflows, not only by engineering-level unit or integration tests.

### 4. Integration points should be visible

Each release should name the key service and API boundaries that must work together before the release is considered complete.

### 5. Trust should increase alongside capability

As the platform gains more power, it must also gain stronger identity, policy, approval, and audit behavior.

## Recommended Release Sequence

The roadmap is designed as six stacked releases:

| Release | Theme | Primary User Value | Risk Level |
|---|---|---|---|
| `R0` | Platform Foundation | Usable portal and runtime baseline | low |
| `R1` | Read-Only Operations Copilot | Grounded operational answers | low |
| `R2` | Skills and Grounded Guidance | Team-owned procedural guidance in answers | low |
| `R3` | Incident Triage and Collaboration | Faster and better triage | medium |
| `R4` | Approval-Gated Bounded Actions | Safe operational action through approval | medium-high |
| `R5` | Hardening and External Consumption | Broader adoption and stable reuse | medium |

## Release Details

## R0: Platform Foundation

### Theme

Make the platform real, runnable, and accessible.

### What It Delivers

- Kubernetes-deployed control-plane baseline
- enterprise portal login through `Keycloak`
- API gateway entry
- basic AgentScope runtime
- session handling
- event streaming to the UI

### Why It Comes First

All later releases depend on stable access, session, and serving foundations.

### Integration Points

- `web-ui` <-> `Keycloak`
- `web-ui` <-> `api-gateway`
- `api-gateway` <-> `agent-service`
- `agent-service` <-> session store
- `agent-service` <-> event streaming channel

### How Operations Teams Validate It

- log in through `SSO`
- open the portal successfully
- start a session
- receive a streamed response

### Release Completion Signal

Operations users can reliably access and use the portal in the target environment.

## R1: Read-Only Operations Copilot

### Theme

Give operators grounded answers before giving the platform write capabilities.

### What It Delivers

- service health query flow
- read-only Kubernetes access
- read-only observability access
- evidence-backed responses
- audit for read-only tool access

### Why It Comes Next

This is the first low-risk way to prove platform usefulness.

### Integration Points

- `agent-service` <-> `tool-gateway`
- `tool-gateway` <-> Kubernetes
- `tool-gateway` <-> observability source
- `agent-service` <-> UI evidence panels

### How Operations Teams Validate It

- ask about a service or deployment
- review returned status and supporting evidence
- confirm the system used the correct data sources

### Release Completion Signal

Operators say the platform is useful for real status and diagnostic questions.

## R2: Skills and Grounded Guidance

### Theme

Blend live evidence with team-owned operational knowledge.

### What It Delivers

- Git-based skill ingestion
- Markdown validation
- searchable knowledge retrieval
- runbook-aware answers
- cited skills and sources in the UI

### Why It Comes Next

After live evidence is working, team-owned guidance is the next layer of trust and utility.

### Integration Points

- skill repo <-> `skill-ingestion-service`
- `skill-ingestion-service` <-> `knowledge-service`
- `knowledge-service` <-> `agent-service`
- `agent-service` <-> UI source display

### How Operations Teams Validate It

- add or update a skill in Git
- verify the platform ingests it
- ask a relevant operational question
- confirm the platform cites and uses the expected skill

### Release Completion Signal

Operations teams trust that their own runbooks and skills are entering the answer flow correctly.

## R3: Incident Triage and Collaboration

### Theme

Help operators respond faster and with better context during incidents.

### What It Delivers

- incident or alert intake
- enrichment and correlation
- ranked next-step recommendations
- update flow to ticketing or collaboration systems
- richer incident context in the UI

### Why It Comes Next

This release turns the platform from a query assistant into an incident-support tool.

### Integration Points

- incident source <-> `agent-service`
- `agent-service` <-> `knowledge-service`
- `agent-service` <-> `tool-gateway`
- `agent-service` <-> collaboration or ticket connector
- `web-ui` <-> incident context view

### How Operations Teams Validate It

- feed a real or simulated alert into the platform
- verify the summary, evidence, and next steps
- confirm ticket or collaboration updates are usable

### Release Completion Signal

Operations users report that the platform improves triage quality and speed on sample incidents.

## R4: Approval-Gated Bounded Actions

### Theme

Allow the platform to act safely within explicit approval and policy boundaries.

### What It Delivers

- policy engine
- approval workflow
- approval queue and action cards
- isolated execution worker
- signed execution requests
- first bounded operational actions

### Why It Comes Next

Only after identity, evidence, grounding, and triage are stable should the platform be allowed to take actions.

### Integration Points

- `agent-service` <-> `policy-service`
- `policy-service` <-> `approval-service`
- `approval-service` <-> `web-ui`
- `approval-service` <-> `execution-worker`
- `execution-worker` <-> `tool-gateway`
- `execution-worker` <-> `audit-service`

### How Operations Teams Validate It

- request a bounded action such as `restart-service`
- verify the system returns `require_approval`
- approve the action as an authorized approver
- verify the worker executes and returns results
- confirm the full audit chain is present

### Release Completion Signal

Operations and governance teams agree that bounded actions are sufficiently trustworthy for controlled use.

### Status

Closed 2026-08-27 with the v0.20.0 delivery. All six deliverables are
shipped — policy engine (SPEC-030), approval workflow (SPEC-031–036),
approval queue and action cards (SPEC-031/033/034), first bounded
operational actions (SPEC-021), signed execution requests (SPEC-037),
and the isolated execution worker (SPEC-038). The completion signal
was exercised end to end across the v0.13.1–v0.20.0 live approval-test
campaign: every run drove the full request → `require_approval` →
approver decision → isolated-worker execution → signed receipt →
audit-chain path on the `mutating-dev` profile, and the final delivery
gate verified the worker pod's handoff → invoke → audit chain directly.
R4-adjacent candidates that remain deliberately parked are recorded on
the exploration backlog with explicit promotion triggers.

## R5: Hardening and External Consumption

### Theme

Make the platform easier to operate, govern, and consume beyond the initial user group.

### What It Delivers

- better policy testing and rollout controls
- stronger reliability and observability
- stable API productization
- richer audit reporting
- better internal platform operations visibility

### Why It Comes Last

This release builds on proven operator value and focuses on broader rollout readiness.

### Integration Points

- policy repo <-> CI/CD
- `api-gateway` <-> external consumers
- `audit-service` <-> reporting interface
- all core services <-> dashboards and metrics

### How Operations Teams Validate It

- use stable platform APIs from another internal application
- inspect audit trails for real workflows
- verify policy changes move through promotion safely
- confirm platform stability under realistic usage

### Release Completion Signal

The platform is ready for wider enterprise adoption beyond the initial user group.

### Status

Closed 2026-09-30 with the v0.45.0 delivery. R5 ran as a long slice
train (SPEC-039 → SPEC-065, v0.21.0 → v0.45.0) rather than a single
release, and carried substantial operator-capability work beyond its
five named themes (the SPEC-039 operations-document repository, the
SPEC-044/045/052/053/055/056/057 skill authoring, graduation, viewer,
Studio and composition suite, the SPEC-049→061 browser/HTTP tool and
`acme-admin` sample suite, and SPEC-062 secure password generation and
delivery).

Of the five named theme deliverables, four are shipped: better policy
testing and rollout controls (SPEC-048); stronger reliability and
observability (crash-safe execution SPEC-063, agent-driven context
compression SPEC-064, and the token/domain-metric/dashboard slice
SPEC-065); richer audit reporting (SPEC-046/047); and better internal
platform-operations visibility (the SPEC-065 dashboards and the
SPEC-047 audit summary drill-down).

The fifth — **stable API productization / external consumption**
(`api-gateway` <-> external consumers; "use stable platform APIs from
another internal application") — is **deliberately deferred, not
dropped**: the operator confirmed no second consumer exists, matching
the [MCP toolset memo](../workspace/mcp-exposure-spike.md)'s
independent finding that external access to Luban workflows is "a
separate, unestablished product use case." It is parked on the
exploration backlog with an explicit promotion trigger (a named second
internal application committing to a concrete workflow + operation
set, read-only-first given the attribution/HITL constraint).

Accordingly the Release Completion Signal is **re-scoped**: R5 closes
on its internal hardening and operator-value deliverables, and the
platform is production-ready for its *initial* user group; "wider
enterprise adoption beyond the initial user group" via external API
consumption is deferred behind that trigger rather than claimed now.

## Release Stacking Logic

### Why This Sequence Works

- `R0` creates access and runtime
- `R1` proves read-only value
- `R2` adds team-owned knowledge
- `R3` adds incident workflow value
- `R4` adds safe action capability
- `R5` makes the platform ready for broader production use

This avoids introducing powerful execution features before the platform has earned user trust.

## Exploration Backlog

Candidates identified during the AgentScope utilization audit (post-R3) that
are not yet decision-complete enough for a spec. Each needs a spike before
promotion; until then they stay here.

| Candidate | Question to answer in a spike | Likely home |
|---|---|---|
| Independent MCP toolsets consumed by tool-gateway | Assessed 2026-09-23 in [the MCP toolset memo](../workspace/mcp-exposure-spike.md): retain native connectors; no implementation promotion; reopen on a concrete credential-local deployment need, recurring connector-release friction, named second consumer, or missing operational capability. **Reopen trigger met 2026-09-30** — operations named three concrete external targets with workflows (Ansible runbooks for task automation, ServiceNow ITSM ticket handling end to end, Windows UI automation for desktop-application / Windows-service health checks), satisfying the "missing operational capability" trigger. Re-assessed in [the MCP-ingestion memo](../workspace/mcp-ingestion-spike.md): build one generic ingestion connector *beneath* tool-gateway (the gateway is the MCP client; the kernel never is), reusing the `BaseTool` / `ToolRegistry` seam and preserving Luban policy, approval, redaction, evidence, and audit; onboard one separately-approved pilot at a time in risk order (ServiceNow → Ansible → Windows), admitting only each use case's required operations (a large catalog is not itself a use case). Still compares native extension vs existing-server adoption vs selective extraction. External access to Luban workflows remains a separate, unestablished product use case (the SPEC-066 row below); the memo authorizes no implementation, pilot, ADR, or spec. | candidate new release theme (R6, "external system integration via MCP ingestion"); first pilot likely its own spec once the machine-consumer credential gap (`client_credentials`) is scoped — trigger met and direction recorded, no spec assigned yet |
| Stable API productization / external consumption | The one R5 theme deliverable ("stable API productization"; integration point `api-gateway` <-> external consumers; validation "use stable platform APIs from another internal application") never spiked or specified. **Parked 2026-09-30** on the operator's confirmation that **no second consumer exists** — the same finding the [MCP toolset memo](../workspace/mcp-exposure-spike.md) reached independently ("no second consumer and required operation set have been named"; external access to Luban workflows is "a separate, unestablished product use case"). This row is the home for that separate use case and is distinct from the MCP row: MCP = expose Luban's *tools* for reuse by other systems; this = expose Luban's *workflows/APIs* for a second application to consume. A speculative build is also the risky path — the platform's attribution/HITL model requires a human owner and a distinct human approver ([identity design](identity-and-authorization-design.md) principles 2 and 5), so external consumption of anything that drives an agent turn or mutates state collides with the trust model; only read-only consumption is tractable without first solving machine-consumer attribution. Unbuilt anchors a future spec would pick up: the empty `shared/shared-sdk` placeholder (service clients / auth helpers / typed event consumers); the identity design doc's named-but-unbuilt "approved machine consumers" client registration and `client_credentials` gap (only `authorization_code` + `refresh_token` are wired today); a published stability/deprecation contract for the `/api/v1/*` surface (versioned by convention only — the `/api/v2/*` namespace is the internal tool-gateway <-> agent-platform boundary, guarded from leaking into the public gateway); and external API reference docs. | own spec (likely `SPEC-066`); trigger-gated — promote when a named second internal application commits to a concrete workflow + operation set, read-only-first given the attribution/HITL constraint |
| Crash-safe execution and outcome reconciliation | [SPEC-063](../specs/SPEC-063-crash-safe-execution/spec.md) scope approved 2026-09-23; [failure-first implementation plan](../specs/SPEC-063-crash-safe-execution/plan.md), [tasks](../specs/SPEC-063-crash-safe-execution/tasks.md), and accepted [ADR-0013](../adr/0013-durable-single-use-execution-claims.md) recorded. Durable single-use dispatch claims, explicit unknown outcomes, late-result preservation, and owner-scoped recovery without automatic mutation retries. All 26 criteria and 36 [failure scenarios](../specs/SPEC-063-crash-safe-execution/failure-test-matrix.md) are mapped; real-Postgres multiprocess crash tests and independent target counters are mandatory. Implementation, the historical 791-test campaign, and the separately authorized corrected five-path S6 acceptance/cleanup preceded delivery; the final full root `make verify` is green (real-Postgres campaign 791 passed, exit 0), with the daemon-wedge attempts (V1/V5/V6) and the V4 test-only fixture fix retained in the [closure evidence](../specs/SPEC-063-crash-safe-execution/tasks.md#delivery-closure-evidence). Delivered locally 2026-09-26 as 0.43.0; no shared rollout, registry push, or release tag is claimed. Queue/pool scaling and MCP remain deferred. | `SPEC-063` — delivered 2026-09-26 as 0.43.0 |
| Semantic (vector) skill retrieval | Does a vector store measurably beat skills-hub's lexical `rank()` scoring (title/tag/body substring weighting) on our corpus? **Spiked 2026-09-30** in [the semantic skill retrieval memo](../workspace/semantic-skill-retrieval-spike.md) against the live corpus and audit trail; the recommendation is **measure before building**, and two premises of this row are corrected. (1) No Elasticsearch server is deployed in dev — SPEC-011 ships a feature-gated Elastic observability *connector* (`GATEWAY_ELASTIC_ENABLED=false`), not a running store. (2) `pgvector` is **not installed and is not a zero-infrastructure change**: `postgres-0` runs stock `postgres:16-alpine` offering **0 of 61** available extensions matching `%vector%`, so `CREATE EXTENSION vector` fails today, and that StatefulSet's 1 Gi PVC also holds the `audit`, `incidents`, and `sessions` databases — an image swap touches all durable state. (3) The assumed *recall* defect is **not observed**: all 96 `skill_searched` audit events (63 distinct queries, 2026-09-02 → 09-22) returned ≥1 hit — zero-hit rate **0/96**, mean **4.72** of `limit=5`. **Ranking defects, however, are now measured** — see the [evaluation-set artifact](../workspace/semantic-skill-retrieval-eval-set.md) (2026-10-01), which re-ran the real scorer over a full corpus export. The corpus is **18 distinct documents carried in 30 rows** (`md5(body)`: 12 byte-identical pairs) because the `platform-skills` git source and two ConfigMap-generated local sources ingest the *same files* under different `source_id`s, and `rank()` does no content de-duplication — so **32 of 63 queries (50.8%) return fewer distinct documents than result slots**. CamelCase titles tokenize to a single opaque token (`KubePodCrashLooping`), so for `pod keeps restarting CrashLoopBackOff` the exactly-right alert ranks **3rd** and loses its slot to an alphabetical `skill_id` tie-break against a scheduling-failures guide. And zero-hit is not a recall proxy: `argocd health check` — the trail's second most frequent query, 7 occurrences — scores **20.0** on an unrelated ACME health-check document, with no ArgoCD runbook in the corpus at all. The traffic is demo/e2e rather than sustained operator triage, and 14 of the 63 queries already carry a target identifier, so the evidence is weak but real. Recommended order is **cost-first, and a cheaper step that closes the measured gap cancels everything below it**: the evaluation set is built and awaits operations' relevance labels; then de-duplicate content in `rank()` and fix tokenization/tie-break (no model, no new dependency, no image change); then the heavier lexical options (`ts_rank_cd` cover density, curated alias map — deterministic, explainable, no model); only then a sidecar `skill_embedding` table over `real[]` with `ON DELETE CASCADE` and `model_id`/`dim`/`content_hash` provenance (promotable to `vector(n)` by ALTER, no data migration), with pgvector deferred to a **recorded scale trigger** (proposed >2,000 skills or search p95 >300 ms). Vectors must not enter the `Skill` contract or the search payload. agentscope 2.0.8's `embedding` module (`OllamaEmbeddingModel`, `DashScopeEmbeddingModel`) is the adopt-worthy surface; its `rag` stores are rejected — no pgvector store, and `MilvusLiteStore` is pod-local (the SPEC-064 offloader objection, `FileEmbeddingCache` likewise). An in-cluster Ollama already runs (`llm-hosting`, already `LUBAN_BASE_URL`) but answers `/api/embed` with **501** (embeddings not enabled) and holds only a chat model; skills-hub holds **no model credential** today, so an external embedder would add a secret, egress, spend, and a data-egress decision on skill body text. Gating posture: `SKILLS_SEMANTIC_ENABLED=false`, fail open to lexical, readiness must not gain a model dependency, new metric families must join `OTEL_MIRROR_FAMILIES`, and embedders stay out of the chat catalog (`_NON_CHAT_MARKERS`). The memo authorizes no implementation, embedding run, extension install, image swap, ADR, or spec. | own spec only after the memo §7 measurements; trigger-gated — promote on a labeled-set precision@5 / MRR win outside the noise band with no regression on queries lexical already answers, or on catalog growth past the recorded pgvector scale trigger; reported metrics must include **zero-relevant rate** and distinct-document variants, not zero-hit rate alone; a null result closes the row — and so does a cheaper de-duplication or tokenizer fix closing the measured gap |
| Long-term operator memory | Do agentscope long-term-memory middlewares (mem0/reme) add real triage continuity across sessions, and where would that state live? ReME was evaluated 2026-08-20 and does not fit as-is (file-based vault vs Postgres durability, unaudited LLM write-back, no per-user isolation); a spike needs a governed storage backend, per-tenant scoping, and audit hooks first (see `docs/workspace/agentscope-utilization-audit.md`). | follow-up to SPEC-017 durability |
| Kernel-side SQL storage | When would adopting `AsyncSQLAlchemyStorage` for the kernel app beat platform-owned state snapshots (SPEC-017 R-3)? | revisit if the native entrypoint is ever deployed |
| Agent-driven context compression + goal-oriented pipeline (agentscope 2.0.8) | [SPEC-064](../specs/SPEC-064-agentscope-compression-and-goal-pipeline/spec.md) approved 2026-09-27 on the R-1 [spike memo](../workspace/agentscope-compression-goal-pipeline-spike.md): the two surfaces the v0.43.2 refresh pinned but left unwired, scored against SPEC-018's four-point gate. `CompressContext` **clears** the gate → adopted under R-2 as an opt-in, default-off kernel knob (`AGENTSCOPE_COMPRESS_CONTEXT_ENABLED`, kernel-local always-allow, state-only, `offloader` deliberately unwired to avoid pod-local split-brain vs the shared SPEC-017 Postgres snapshot); R-2 wiring is implemented, tested (agent-platform suite 1514 passed), and delivered 2026-09-27 as 0.44.0 ([release note](release-notes/2026-09-27-agent-driven-context-compression.md)). `GoalPipeline` **kept out** — no caller and the executor/verifier loop fails the gate against ADR-0011 / the governed dispatch path; reopen only on a concrete need that runs entirely under the existing policy/HITL/signed-dispatch gates as a single governed agent. | `SPEC-064` — delivered 2026-09-27 as 0.44.0 |
| Observability metrics and dashboards (token by model; cost deferred) | The one R5 theme deliverable ("all core services ↔ dashboards and metrics"; "stronger reliability and observability") with no spec. Assessed 2026-09-27 in the [observability metrics & dashboards spike](../workspace/observability-metrics-dashboards-spike.md) against the **live** `dev-luban-aiops` cluster and its in-cluster OpenObserve: OpenObserve is **already integrated and live** (`OTEL_ENABLED=true`, `AGENTSCOPE_KERNEL_TRACING=true`; logs/traces/OTel-HTTP metrics from all Python services landing now) and token-by-model usage **already reaches it as per-span GenAI trace attributes** (`gen_ai.usage.*` token attributes; the memo's `gen_ai.usage.cost` claim was later disproved by SPEC-065 Stage-0) — but there is **no aggregated token metric, no Prometheus/Grafana/prometheus-operator (no scraper), and nothing on any dashboard**, so the domain counters are curl-only. One authorized billable read-only `deepseek-v4-flash` turn evidenced the gap (a one-word reply still consumed 5,352 input / 1 output tokens; the memo's $0.0011781 cost figure was later disproved — see SPEC-065 Stage-0). Operator decisions (memo §7) resolved all five scope questions: consumer path = **push domain metrics as OTel instruments over the existing OTLP pipeline, no scraper** (recorded as [ADR-0014](../adr/0014-domain-metrics-via-otel-push.md), `accepted`); first-spec scope = the **full R5 observability theme** planned as separated verifiable tasks; live leg = external `deepseek` (paid); cost = originally "emit both tokens and dollars" but **superseded by SPEC-065 Stage-0** (agentscope 2.0.8 exposes no provider-derived cost and the platform has no price table, so R-1 ships tokens-only and cost is deferred); token middleware = **always-on**. Drafted 2026-09-27 and **approved 2026-09-27** as [SPEC-065](../specs/SPEC-065-r5-observability-token-cost-dashboards/spec.md) (full scaffold authored together per the SPEC-064 precedent; ADR-0014 flipped `proposed` → `accepted` on approval; implementation is a separate authorization boundary): R-1 always-on `TokenUsageMiddleware` on the supported `on_model_call` hook emitting `agent_llm_tokens_total{provider,model,direction}` (streaming-aware, bounded catalog labels, no session/user/request id, never estimated; **cost deferred** per Stage-0 — no `agent_llm_cost_usd_total` in this slice); R-2 the OTel-instrument mirror via a helper in the parity-guarded `core/telemetry.py` (keeps the SPEC-005 `/metrics` pull surface intact); R-3 OpenObserve dashboards as config-as-code with a `make verify` import check; R-4 a gated live-check reproducing the spike §6 procedure; R-5 doc/version updates. No contract, policy, audit, or trust-model change; the only external side effect is R-4's single authorized paid read-only call. Delivered 2026-09-29 as v0.45.0 (R-4 authorized paid live-check leg run and evidenced; full `make verify` green). | `SPEC-065` — delivered 2026-09-29 as v0.45.0 (`delivered`), the R5 observability slice (R-1 tokens-only; cost deferred) |
| HITL confirmation bridging | Delivered 2026-08-21 as `SPEC-020-hitl-confirmation-bridging` (kernel ASK → portal approve/deny, `chat:confirm` action, `confirmation_decided` audit). MUST still precede any write/mutating tool. | `docs/specs/SPEC-020-hitl-confirmation-bridging/` |
| Bounded mutating actions | Delivered 2026-08-21 (0.7.0) as `SPEC-021-bounded-mutating-actions`: first write tool `k8s.delete_pod`, triple-gated (gateway `GATEWAY_MUTATING_TOOLS_ENABLED` risk-tier admission → read-only-by-construction auto-allow invariant → SPEC-020 HITL confirmation) behind the deny-by-default `tools:mutate` action (platform-admin + operator). Disabled by default in dev-k8s; opt-in RBAC and `mutating-demo.sh` ship out-of-band. Policy-center `require_approval` semantics delivered 2026-08-25 (0.12.0) as `SPEC-030-require-approval-policy-semantics` (spike memo: `docs/workspace/policy-require-approval-spike.md`). | `docs/specs/SPEC-021-bounded-mutating-actions/` |
| ASK → DENY tightening | Resolved 2026-08-21 during SPEC-020 live-check hardening: `GatewayPermissionMiddleware` now answers every non-allow-listed tool with an explicit ASK (parked as a confirmation card) instead of delegating to the built-in engine, whose read-only fast path silently auto-allowed read-only tools; "silently never runs" no longer describes any path. | superseded by SPEC-020 hardening |
| Multi-session operator workspace | Delivered 2026-08-22 (0.8.0) as `SPEC-022-multi-session-operator-workspace`, backend-first: session lifecycle API (list/transcript/delete, `pending_confirmation` flags, `session:list`/`session:delete` actions), voice-readiness contract (`input_modality` + HITL-stays-click-gated invariants), and the SPEC-021 dev opt-in promoted to a committed `mutating-dev` kustomize profile. The portal session-panel UI is deferred to the portal rebuild spec (Appendix A handoff). | `docs/specs/SPEC-022-multi-session-operator-workspace/` |
| Portal framework rebuild | Delivered 2026-08-22 (0.9.0) as `SPEC-023-portal-framework-rebuild`: operator portal rebuilt on Vite + React 18 + TypeScript with antd / Ant Design X — platform-owned SSE contract adapter (schema v6), SPEC-022 Appendix A session workspace UI (panel, switch/resume, anchored confirmations, incident deep links), browser voice composition with a language selector (`input_modality=voice` metadata only), full view-migration parity, and the vanilla trio removed at delivery. | `docs/specs/SPEC-023-portal-framework-rebuild/` |
| Runtime LLM model switching | Delivered 2026-08-24 as `SPEC-024-runtime-llm-model-switching`: credential-gated model catalog (one entry per configured provider), per-session selection with affinity and switch-on-demand agent rebuild, audited choice via `chat_started`/`chat_completed` enrichment, portal composer selection bar. | `docs/specs/SPEC-024-runtime-llm-model-switching/` |
| Evidence persistence in session transcripts | Delivered 2026-08-24 as `SPEC-025-evidence-persistence`: `tool_call`/`tool_result` frames persisted per assistant turn into a `session_evidence` store behind the existing `AGENT_STATE_STORE_BACKEND`/`AGENT_STATE_DB_URL` knobs, per-entry truncation cap and per-session byte budget with eviction markers, additive `evidence_turns` on session detail, and prop-identical replayed evidence cards in the portal. | `docs/specs/SPEC-025-evidence-persistence-in-transcripts/` |
| Multi-model runtime catalog | Delivered 2026-08-24 as `SPEC-026-multi-model-runtime-catalog`: extends SPEC-024 — each configured provider exposes its curated model series (model name as entry id), `<PROVIDER>_MODELS` override, legacy provider-name ids aliased to the provider default, and gitops runtime-profiles consolidated from per-provider dirs into one generic `default` profile. | `docs/specs/SPEC-026-multi-model-runtime-catalog/` |
| Live model discovery | Delivered 2026-08-24 as `SPEC-027-live-model-discovery`: extends SPEC-026 — agent-service queries each configured provider's OpenAI-compatible `/models` endpoint and serves the live list with snapshot/modality filtering, a fail-soft fallback ladder (live fetch -> in-memory last-good -> Postgres-persisted last-good -> curated series), periodic refresh with atomic catalog swap, and Redis kept exclusively as the AgentScope kernel message bus. | `docs/specs/SPEC-027-live-model-discovery/` |
| Luban-hosted small model provider | Delivered 2026-08-24 as `SPEC-028-luban-llm-provider`: `luban` adapter for team-hosted OpenAI-compatible servers (Ollama/vLLM/llama.cpp) with token-based auth and a mandatory base URL, an operator hosting guide (`docs/guides/luban-llm-guide.md`), and free-standing reference Ollama K8s manifests (`shared/platform-ops/gitops/llm-hosting/`) — the foundation for the big-small LLM collaboration pattern (small edge model for pre-triage/redaction, cloud flagship for tool-heavy agent turns). | `docs/specs/SPEC-028-luban-llm-provider/` |
| Skills usage audit trail | Delivered 2026-08-25 (0.11.0) as `SPEC-029-skills-usage-audit-trail`: skills-hub emits `skill_searched`/`skill_retrieved` per authenticated query and one `skills_synced` per source per sync cycle via the canonical fire-and-forget emitter (fourth parity-guard member), correlated with caller `tool_invoked` events through forwarded `x-request-id` (no user identity forwarded); shipped alongside the pre-milestone review remediation (operator guides, drift-guard parity suite, audit-service 95% / incident-service 92% coverage). | `docs/specs/SPEC-029-skills-usage-audit-trail/` |
| Require-approval policy semantics | Delivered 2026-08-25 (0.12.0) as `SPEC-030-require-approval-policy-semantics`: `require_approval` becomes a first-class, enforced policy outcome with approval tiers — `tier_1` session-operator self-confirmation and `tier_2` designated-approver with self-approval blocked — evaluated in both gateway engines (deny > require_approval > allow) and bridged onto `chat:confirm` with structured 403s, blocked-attempt audit, and fail-closed parked-info fetch. The default bundle ships a `tier_2` rule on `tools:mutate` (decided by `approver` / `platform-admin`), the live matrix gains an additive `approval_requirements` third cell state, confirmation cards gain tier badges with read-only rendering for non-deciders, and the portal Settings view is restored as an extensible read-only Session & Identity panel (add-on R-6). | `docs/specs/SPEC-030-require-approval-policy-semantics/` |
| In-portal help & onboarding | Spiked 2026-08-25 from the 2026-08-25 code/doc review (finding D6): tiered scope and a measurement plan are recorded in `docs/workspace/portal-help-onboarding-spike.md` — guide links (option A) are the cheap floor and prerequisite, the antd first-run tour (option B) follows on real onboarding friction, contextual hints and an in-app guide renderer stay deferred/rejected. The Settings view restoration (read-only Session & identity panel) was moved forward into SPEC-030 as add-on R-6 (memo addendum). Promote on the first onboarding friction signal, not before. | portal enhancement spec |
| Shared-package extraction of duplicated service modules | Spiked 2026-08-25 from the 2026-08-25 code/doc review (finding M1): copy-with-parity retained — the memo (`docs/workspace/shared-sdk-extraction-spike.md`) measures the five parity families (~400 unique lines) against packaging, seven-lockfile ripple, and image-build coupling, rejects a `make sync` generator, and records three revisit triggers (sixth family / five copies of one family, 3+ behavioral changes to one family per quarter, shared-sdk needed for another reason). | own spec; revisit on the recorded triggers |
| Cross-owner session review | Raised in the v0.16.0 live approval test (SPEC-035 open question) and re-stated by SPEC-036: incident review and 7x24 roster handover need a read-only view of another operator's sessions. Agreed direction: role-gated, read-only, audit-logged; session inheritance is discouraged (never-expiring sessions, ambiguous HITL ownership). Spiked 2026-08-27 in the paired memo (`docs/workspace/session-handover-spike.md`): parked behind a recorded trigger — promote on the first concrete need to read raw sessions the shift-summary artifact cannot satisfy; the artifact's provenance index doubles as its natural entry point. | portal + session-API spec |
| Shift-summary artifacts | Delivered 2026-08-27 (0.21.0) as `SPEC-039-operations-document-repository`, the first R5 slice: spiked 2026-08-27 in the paired memo (`docs/workspace/session-handover-spike.md`) as the paired candidate with cross-owner session review (SPEC-035 open question), promoted on same-day operator sign-off, then retargeted by the same-day operator review to the **operations document repository** — a typed-document substrate with a role-based access matrix (draft→publish replaces per-document grants), provenance anchoring, and document audit, shipping the shift-summary digest (deterministic two-tier own/foreign coverage plus an optional digest-only prose layer) as the first type and the session-rename and session-id-copy add-ons; incident reports were
promoted as the next type on 2026-08-28 (`SPEC-043-incident-report-document-type`,
delivered 2026-08-29 as v0.25.0), and skill authoring is tracked separately below. | `docs/specs/SPEC-039-operations-document-repository/` |
| Shift-summary handover narrative and export | Delivered 2026-08-28 (0.22.0) as `SPEC-040-shift-summary-handover-narrative` (second R5 slice) from same-day operator feedback on the v0.21.0/0.21.1 document repository: the shipped digest is a pile of receipts without the story, so the spec adds a deterministic `handover` digest section (decisions, execution outcomes, open items — facts only), repositions prose as the default digest-anchored narrative, moves the portal Documents entry from Control to Workspace, and adds a client-side Markdown export for offline use; no new policy actions or audit event types. | `docs/specs/SPEC-040-shift-summary-handover-narrative/` |
| Documents readability and digest reference | Delivered 2026-08-28 (0.23.0) as `SPEC-041-documents-readability-and-digest-reference` (third R5 slice) from operator live-test feedback on v0.22.0: the digest's vocabulary (digest, frame, coverage tiers, handover) is nowhere documented for operators, the drawer renders the digest as hard-to-scan nested lists, Digest/Prose blocks grow unbounded, and the document lists give no glimpse of each document's substance. The slice adds an operator-facing digest reference guide, tabbed structured digest rendering (handover default, raw JSON preserved), bounded scrollable digest and prose panes, and a deterministic counts-only creation-time summary shown in the Mine/Published lists (kept counts-only so the envelope-only listing posture holds); no new policy actions or audit event types. | `docs/specs/SPEC-041-documents-readability-and-digest-reference/` |
| Incident report document type | Delivered 2026-08-29 (0.25.0) as `SPEC-043-incident-report-document-type` (fifth R5 slice) from the SPEC-039 recorded next-type commitment, promoted by the v0.24.0 post-release review: a durable `incident_report` assembled verbatim from incident-service facts (incident envelope, validated triage report, connector dispatches) plus the linked triage session's digest under the existing two-tier own/foreign posture, with the inherited digest-only prose layer and draft→publish lifecycle; gated by the combination of the existing `documents:create` and `incident:read` actions — no new policy actions, no new audit event types, read-only with respect to incident state; retention adjudicated to inherit the substrate defaults with the bump parked behind an operator-ask trigger. | `docs/specs/SPEC-043-incident-report-document-type/` |
| Skill authoring export from sessions | Delivered 2026-08-30 (0.26.0) as `SPEC-044-skill-authoring-export` (sixth R5 slice), raised in the 2026-08-27 operator review beside the document repository and spiked 2026-08-29 in `docs/workspace/skill-authoring-spike.md` (Option A promoted by operator sign-off the same day): the platform drafts a Skill Format v1 Markdown from the caller's own session digest bundle (plus the validated triage report when incident-linked), validates it on skills-hub's own ingestion code path before it reaches the operator, and hands it over as a client-side `.md` download — ephemeral by construction, the artifact of record stays in the team's Git skills repo (the platform drafts, humans merge); gated by one new `session:skill_draft` action (platform-admin/approver/operator) with one new `skill_draft_generated` audit event, and generation never 500s (facts-only skeleton degradation). | `docs/specs/SPEC-044-skill-authoring-export/` |
| Incident-anchored skill drafts and draft preview | Delivered 2026-08-30 (0.27.0) as `SPEC-045-incident-skill-draft-and-preview` (seventh R5 slice), raised in the 2026-08-30 post-v0.26.0 design exchange (memo-free, drafted directly from the discussion per the SPEC-042 precedent): the operator's mental model for skill authoring starts at the incident — re-read the triage report, then convert it — so the incident detail gained **Draft as skill** anchored to the incident envelope plus the validated triage report (never anyone's session: the two-use-case split keeps session drafting owner-only and incident drafting incident-visible, dual-gated on one new `incident:skill_draft` action plus `incident:read`, deterministic 409 without a validated triage report, one new `incident_skill_draft_generated` audit event); both entry points open a read-only preview (rendered + raw toggle, mode badge, Download .md / Discard) before the client-side download; editing in the preview and dispatch-outcome bundle input parked as promotion triggers. The exchange's Q-1…Q-7 resolved in the draft's Design Decisions; live check 5/5 on the canonical deployment. | `docs/specs/SPEC-045-incident-skill-draft-and-preview/` |
| Audit reporting and export | Delivered 2026-08-31 (0.28.0) as `SPEC-046-audit-reporting-and-export` (eighth R5 slice), drafted 2026-08-31 and promoting the R5 "richer audit reporting" deliverable (`audit-service` <-> reporting interface) memo-free per the SPEC-042/045 precedent from the 2026-08-31 roadmap review: deterministic envelope-column summary aggregates (total, by event type/outcome/service, top actors, and a decision-chain projection over the SPEC-037 `confirmation_decided` / `execution_*` events) plus a bounded server-side CSV export (`AUDIT_EXPORT_MAX_ROWS` default 10 000, streaming 200-row pages, always-present truncation headers), proxied by platform-gateway under the existing `audit:read` action — no new policy actions, no new audit event types, `auditor` stays read-only — and a portal Audit view upgrade (Events/Summary tabs, export button, full filter vocabulary pinned to the shared audit-event schema by a vitest drift guard, remediating the stale 7-of-20 event-type / 4-of-7 service selects). Reports are ephemeral facts-only surfaces, not a SPEC-039 document type (the auditor holds no document actions); JSON export, scheduled reports, and per-detail breakdowns parked as promotion triggers. Approved 2026-08-31 with no requirement changes; the browser live check on the canonical deployment found and fixed one Postgres array-adaptation defect in the summary path (`event_type IN $1` rejects a list parameter; `= ANY(...)` with a pinned-shape test) before release, then all scenarios ran green — filtered summary with the decision-chain zeros, bounded export with the truncation notice, operator/observer denial (nav gate + audited policy 403 on both routes), and the stale-vocabulary regression (all 20 event types / 7 emitter services filterable). | `docs/specs/SPEC-046-audit-reporting-and-export/` |
| Audit summary drill-down and readability | Delivered 2026-08-31 (0.29.0) as `SPEC-047-audit-summary-drilldown` (ninth R5 slice), drafted memo-free from the operator UX review of the v0.28.0 Summary tab live check and approved the same day with no requirement changes: one additive `outcome` filter dimension on the existing audit events/summary/export routes (four contract enum values, 422 otherwise, applied in the shared WHERE-builder so both store backends inherit it) forwarded by platform-gateway under the unchanged `audit:read` gate, `OUTCOMES` joining the portal's pinned vocabulary behind the existing drift guard plus the toolbar select, and the Summary tab rebuilt into a single page — headline statistic row (total + decision chain, zeros as 0), drill-down from every aggregate value into the Events tab under merged filters (merge never reset, time range survives, zero-count buckets still navigate), a one-decimal percentage + neutral bar share column per bucket row via one shared formatter (the bar was retired in the 0.29.1 patch hardening after live-review feedback — the share cell is now a single right-aligned percentage), and default-expanded collapsible sections; no new routes, no new policy actions, no new event types, both contract schemas unchanged. The browser live check passed all twelve scenarios on the canonical deployment. | `docs/specs/SPEC-047-audit-summary-drilldown/` |
| Policy testing and rollout controls | Delivered 2026-09-02 (0.30.0) as `SPEC-048-policy-testing-rollout-controls` (tenth R5 slice), spiked 2026-09-01 from the next-step review after the v0.29.3 train (`docs/workspace/policy-rollout-controls-spike.md`) promoting the R5 "better policy testing and rollout controls" deliverable (`policy repo <-> CI/CD` integration point) under Option B: a SHA-256 content-hash provenance field computed at load in both engines and surfaced on the policy matrix (unchanged `policy:read` gate) and both gateways' readiness surfaces, a scenario-expectation harness pinned into `make verify` (131 api / 19 tools expectations over the exact engine evaluation path, with mechanical full-grant coverage so any new grant without a recorded intent fails the gate), a `make policy-diff CANDIDATE=...` per-(role, action) outcome-transition report sharing the harness evaluator, the rollout runbook in the configuration reference (edit → sync → verify → diff → commit → deploy → confirm hash, explicit ConfigMap+restart posture), and copy-parity coverage extended to the GitOps overlay copy; no new policy actions, no new audit event types, bundle schema and evaluation semantics unchanged. Staged promotion, hot reload, policy-center, change windows, and bundle-lifecycle audit stay parked as the policy-center-shaped remainder, with the 2026-09-01 environment-promotion adjudication (dev/qa/prd promotion rides a follow-on deployment-promotion slice) recorded in the spec's Parked section; the live check confirmed readiness hashes matching the canonical file byte-for-byte on both gateways. | `docs/specs/SPEC-048-policy-testing-rollout-controls/` |
| Browser-based web application check tools | Delivered 2026-09-02 (0.31.0) as `SPEC-049-browser-web-check-tools` (eleventh R5 slice), drafted 2026-09-02 memo-free from the 2026-09-01/02 operator design discussion (the SPEC-045/046 memo-free precedent): the agent's capability to check web applications — including legacy web apps — through skill-declared flows. A stateful browser connector in tool-gateway drives a chromium-headless-shell sidecar over CDP (D-6, engine swappable at deployment level after the 2026-09-02 agent-browser survey recorded vercel agent-browser, ego-lite, Steel, Browserless, and hosted SaaS as rejected and Obscura/Lightpanda parked with promotion triggers), exposing a bounded `web.*` surface (read-tier navigate/snapshot/screenshot, write-tier click/type) behind a server-side origin allowlist; skills gain two additive optional frontmatter keys (`web_target`, `risk_class`) validated on the existing ingestion path; `write`-class flows park exactly one confirmation card through the existing SPEC-020 bridge inheriting the `tools:mutate` tier_2 rule, with a deviation guard escalating out-of-plan actions; named credential sets resolve from a secret-mounted file with leak-asserted redaction; screenshots ride bounded base64 JPEG inside existing evidence caps — no new policy actions, no new audit event types, contracts unchanged. Approved 2026-09-02 with no requirement changes (Q-1/Q-2/Q-3 resolved in Design Decisions); shipped with the full `make verify` gate green at 0.31.0 and the committed `browser-dev` dev posture (`chromedp/headless-shell` sidecar, `browser-check-target` sample app, credential-set secret sync, `browser-check-demo.sh`). | `docs/specs/SPEC-049-browser-web-check-tools/` |
| Browser tools expansion and samples reorganization | Delivered 2026-09-04 (0.32.0) as `SPEC-050-browser-tools-expansion-and-samples` (twelfth R5 slice), extending SPEC-049's six-tool browser surface by nine tools to cover what real admin panels and dashboards need — `web.select`, `web.press_key`, `web.upload_file`, and `web.evaluate` (write tier, inheriting the `_WebInteractionTool` deviation guard + HITL gate) plus `web.extract`, `web.wait_for`, `web.hover`, `web.scroll`, and `web.switch_frame` (read tier via `gate_capture` origin re-check). `web.evaluate` is HITL-gated write tier with result bounding and a defense-in-depth mutation guard (never the security boundary); `web.upload_file` allowlists paths under the new `GATEWAY_BROWSER_UPLOAD_DIR`; `web.switch_frame` denies cross-origin frames and `web.navigate` resets to the main frame. Tutorial demo content reorganizes into a self-contained top-level `samples/` tree under a strict tutorial → platform arrow — sample skills install out-of-band via `make deploy-samples` / `make undeploy-samples` into a generic `skills-samples` ConfigMap mounted at `/skills/samples` (skill id `samples/password-reset-resetuserpassword`), the base overlay names no specific sample, and the former `platform-runbooks/web-checks/ResetUserPassword.md` copy plus its base wiring are removed; no new policy actions, no new audit event types, contracts unchanged. Shipped with the full `make verify` gate green at 0.32.0 and a live `dev-k8s` check (deploy-samples ingestion, five-leg demo, undeploy/redeploy lifecycle). | `docs/specs/SPEC-050-browser-tools-expansion-and-samples/` |
| Browser flow HITL gate enforcement and password-reset sample reconciliation | Delivered 2026-09-04 (0.33.0) as `SPEC-051-browser-flow-hitl-gate-enforcement` (thirteenth R5 slice) from a live password-reset test on v0.32.0 that parked an approval card for **every** write-tier browser interaction: SPEC-049 R-4's "approval unlocks the bound flow's interactions for that session" was specified but never implemented in the agent-platform kernel, so the one-gate behavior only ever existed as fragile skill authoring. SPEC-051 completes R-4 platform-side (a session-scoped flow authority recorded on approval; each subsequent unlocked browser write auto-signed under the approving card and still bounded by the gateway origin/risk_class/step-budget deviation guard) and reconciles the password-reset sample to a single gate on the destructive "Confirm reset" click; makes that single card flow-semantic (R-6 — the headline names the bound skill's title, description, target origin, and risk class rather than a bare tool action, carried from the gateway flow binding through the kernel confirmation frame to the portal card, with the tool action kept as secondary detail); tracked with ADR-0007 (the flow-gate trust-model decision) and ADR-0008 (a spec-delivery requirement-to-test traceability gate). No new policy actions, no new audit event types, contracts unchanged. Shipped with the full `make verify` gate green at 0.33.0 and a live `dev-k8s` check (redeploy + `RUN_CHAT_LEG=true demo.sh` proved one card with every write-tier execution auto-signed under it, a live-Postgres smoke confirmed the durable `flow_summary` persists as real JSONB, and the portal re-check showed a single gate headlined "Reset User Password in Admin Portal"). | `docs/specs/SPEC-051-browser-flow-hitl-gate-enforcement/` |
| Skill content viewer | Delivered 2026-09-05 (0.34.0) as `SPEC-052-skill-content-viewer` (fourteenth R5 slice) from the 2026-09-05 post-live-test feedback that operators could not read a skill's authored content on the Skills page — the list payload omits `body` by contract, so only the envelope metadata (id, title, source, risk class) showed and an operator could not validate where a web-check skill's single HITL gate lands (the transparency goal motivating SPEC-049/051). A read-only rendered/raw viewer reusing the SPEC-045 R-5 preview pattern opens from each Skills-table row and lazily fetches the full record through a new platform-gateway single-skill detail proxy (`GET /api/v1/skills/{skill_id:path}`) that reuses the existing `skills:read` action and skills-hub's existing `get_skill` endpoint (which already returns `body` and emits `skill_retrieved`); nothing is persisted, no download/discard. No new policy actions, no new audit event types, no shared-contract change, skills-hub unchanged. Shipped with the full `make verify` gate green at 0.34.0 (gateway detail proxy 37 passed, portal suite green, `npm run build` clean). | `docs/specs/SPEC-052-skill-content-viewer/` |
| Skill-declared step intent on the browser confirmation card | Delivered 2026-09-05 (0.34.0) as `SPEC-053-skill-declared-step-intent` (fifteenth R5 slice), realizing the per-step-intent follow-up SPEC-051 R-6 explicitly deferred ("structured per-step plan rendering … needs a skill-format change touching the skills contract and ingestion path") from the 2026-09-05 post-live-test feedback that the browser approval card led with parsed DOM/technical detail instead of an authored "what this achieves" line. One additive optional `flow_intent` frontmatter key (≤ 200 chars, requires `web_target`) authors the flow's gated-step intent in plain language; because SPEC-051 R-1 collapses a mutating flow to exactly one gate, a single card-level intent maps 1:1 to the card (no brittle per-click matching). It rides the existing SPEC-051 R-6 `flow_summary` path verbatim and under the same name (skill record → gateway `bind_flow`/`FlowState` → `web.navigate` `data["flow"]` → kernel `FlowContext.summary()` → `confirmation_request` frame + durable `ConfirmationRecordModel` → portal `ConfirmationCardView` decision line above the demoted DOM/technical detail). Display-only and never a security input — the deviation guard and SPEC-037 signed execution are unchanged, and skills that omit it render as today. Additive contract change (`skill.schema.json` + the two `flow_summary` schemas; stream v9 → v10) touching the skills-hub ingestion/store path; no new policy actions, no new audit event types. Shipped with the full `make verify` gate green at 0.34.0 (skills-hub 57, tool-gateway browser connector 96, agent-platform 798, portal 283). | `docs/specs/SPEC-053-skill-declared-step-intent/` |
| Action-level HITL approval and the change-request confirmation card | Delivered 2026-09-07 (0.35.0) as `SPEC-054-action-approval-and-change-request-card` (sixteenth R5 slice), drafted 2026-09-06 memo-free from the A→B→C HITL redesign discussion and revised on the 2026-09-07 pre-approval code review: makes **action** approval first-class beside **flow** approval through an explicit `approval_kind: flow \| action` discriminator on the confirmation frame and durable record (a card's kind is declared, not inferred from ambient session state — the structural fix behind the v0.34.1 SPEC-051 R-6 headline-leak patch); relaxes the gateway's `BROWSER_FLOW_NOT_BOUND` hard-deny so an ad-hoc browser interaction on an allowlisted origin parks as a per-action signed gate, **shipped together with** the two replacements that keep it fail-closed (the kernel clears `FLOW_CONTEXTS`/`FLOW_APPROVALS` wherever the gateway clears its own binding, and every signed envelope declares its authority provenance under **ADR-0010** with a new `BROWSER_FLOW_AUTHORITY_STALE` refusal); read-tier `web.fill_credential` joins the relaxation so credentials stay reference-only instead of landing in `web.type` args; and every action card becomes a secret-masked **change request** (curated per-tool plus generic projection, structured `{summary, fields[]}`, display-only and never in the signed `args_digest`) with the card `message` persisted on the durable record for replay parity. Tracked with ADR-0007 (extended, not reversed), ADR-0008, and ADR-0010 (accepted 2026-09-07). No new policy actions, no new audit event types; additive contract change (`execution-request.schema.json` plus the confirmation frame/record). Shipped with the full `make verify` gate green at 0.35.0 (all product pytest, kustomize overlays, policy rules and scenarios, version lockstep, and the new `validate-secret-vocabulary` leg), the portal suite green (303) with `npm run build` clean, and an unbound per-action browser-write sample (`samples/web-checks/adhoc-password-reset/`, a no-`web_target` runbook so the session stays platform-enforced unbound) exercised by its own `demo.sh` per ADR-0008; the clean 0.35.0 image also carries the deferred v0.34.1 headline-leak gate. | `docs/specs/SPEC-054-action-approval-and-change-request-card/` |
| Develop-as-you-go skill graduation | Delivered 2026-09-09 (0.36.0) as `SPEC-055-develop-as-you-go-skill-graduation` (seventeenth R5 slice), the graduation destination of the A→B→C program and the implementation of **ADR-0009** (accepted 2026-09-07, stays `accepted`): a durable dual-backend authoring-trace store separate from the 30-day `execution_records` receipt sweep, capturing secret-safe parameterized steps as a by-product of each already-approved already-signed mutation at **both** signing sites (per-action and flow-unlock) and gated on the platform's single risk→action mapping so it fails closed on an unclassified tier; an executable-flow skill class (**Skill v1 → v2**, additive `kind` + `steps`) declaring `risk_class: write` **decoupled from `web_target`**, so a non-browser mutating skill can declare that it mutates; deterministic no-model graduation whose `revalidate_blast_radius` runs before the draft exists and checks the recorded **declared target** (an authorization scope named before mutating) against every step's **observed origin** (what the gateway reported the mutation landed on, captured at the receipt seam and only for a `succeeded` result), producing a previewable draft for human merge that is never auto-published and persisted nowhere server-side, behind one new `session:skill_graduate` action and one new `skill_graduated` audit event; and one-gate replay with **no new executor** — a graduated browser flow binds through the existing SPEC-051 path, its `steps` list never an input to its own gate (budget from the gateway knob, `FlowState` declaring no `kind`/`steps`), credentials resolved from credential-set references at replay. **R-7** (folded post-approval from the SPEC-054 delivery review) closes the two change-request secret-masking gaps SPEC-054 recorded and deferred: `should_mask` flipped to fail closed against a curated `KNOWN_SAFE_FIELDS` allow-list, and an `action` card's raw `parameters` redacted in place so nothing plaintext persists, streams, or renders in the expander — with no contract change and a byte-identical signed `args_digest`, plus `web.evaluate.expression` joining `OPAQUE_VALUE_FIELDS`. Three new knobs (`AGENT_AUTHORING_TRACE_MAX_STEPS`, `AGENT_AUTHORING_TRACE_IDLE_DAYS`, `AGENT_SKILL_GRADUATION_MAX_STEPS`). **OQ-2 did not ship in this train**: it was scoped at approval to target 0.36.0, and it is re-anchored to its own backlog row below rather than silently carried — infra executable-flow steps park per-action under SPEC-054 R-2, which fails safe and is asserted by R-5's tests. Shipped with the full `make verify` gate green at 0.36.0 (all product pytest, kustomize overlays, policy rules and scenarios including the new `session:skill_graduate` grants and denials, api and tools scenarios, version lockstep, secret vocabulary), the portal suite green (342 tests / 29 files) with `npm run build` clean, and a new `samples/web-checks/skill-graduation/` demo exercised by its own `demo.sh` per ADR-0008 (six deterministic legs plus four opt-in chat acts: author → graduate → human-merge → replay under one gate). | `docs/specs/SPEC-055-develop-as-you-go-skill-graduation/` |
| Studio — a dedicated skill-development workspace | Delivered 2026-09-13 (0.37.0) as `SPEC-056-studio-skill-development-workspace` (eighteenth R5 slice), drafted 2026-09-12 memo-free from the 2026-09-08→12 operator design discussion (the SPEC-045/046/049 precedent): split the single operator-portal **Chat** entry into **Chat** (operation sessions) and a new **Studio** (development sessions) over **one shared `ChatView` core** parameterized by a `mode`, backed by an additive two-value `session_type` discriminator (operation/development) fixed at birth and **immutable** (no promotion or in-place conversion). Delivers the operator's four goals — two distinct entries; a clean role mapping (**Option A**: Studio is an authoring power held by operator/approver/platform-admin, developer/read-only-observer/auditor keep Chat only); correct document generation (the shift-summary picker filters to operation sessions, closing a live unfiltered-picker defect in `DocumentsView.tsx`); and blast-radius control (the SSE stream, secret masking, and HITL core are shared and asserted identical across modes, never forked). **Design B** control placement: "Draft as skill" stays in Chat (a read-only knowledge export that may span many targets), "Declare a target" + "Graduate as skill" move to Studio (a graduate is a replayable **single-target** flow), and there is **no in-place conversion** — SPEC-055 R-4 re-validates every observed origin against the one target declared *before* mutating, so a multi-target operation session's trace would make graduation deterministically refuse. The Chat→Studio *spawn* bridge ("Continue in Studio"), a composition/runbook-of-skills construct, and assisted trace-extraction are deferred to **SPEC-057** (below). No new policy action (development-session creation dual-gates on the existing `session:skill_graduate`), no new audit event type, no change to the graduation/replay trust model. **Status `delivered`** (2026-09-13) — OQ-1..OQ-3 (entry-gating mechanism, legacy backfill, list scoping) resolved on the draft's recommendations: the route-level dual-gate on `session:skill_graduate`, infer the backfill from a declared target, and scope each entry's list to its own `session_type`. The companion role-vocabulary reconciliation (retire the design-only `senior-operator`, document `developer`) landed separately as a docs-only patch on 0.36.3. Shipped with the full `make verify` gate green at 0.37.0 (**2616** product tests, kustomize overlays, policy rules and scenarios **unchanged**, api and tools scenarios, version lockstep, secret vocabulary), the portal suite green (**400** tests / 32 files) with `npm run build` clean, `make policy-diff` reporting **zero** outcome transitions across all 138 (role, action) pairs on both engines against an identical bundle hash, and the OQ-2 backfill exercised against a **real Postgres 16.14** — which found and fixed a defect in this slice's own migration: the `to_regclass` guard was *decorative*, because PostgreSQL resolves the relation inside the inference's `IN (SELECT … FROM authoring_trace_target)` subquery at **parse-analysis time** before any predicate is evaluated, so a cluster without the SPEC-055 authoring-trace DDL would have aborted the whole schema bootstrap instead of skipping the inference; it now runs inside a PL/pgSQL `DO` block with dynamic `EXECUTE`, pinned structurally and re-verified on the real server and through the production psycopg path. **No `samples/` demo ships** (operator decision at plan review — the split leaves nothing otherwise-unexercised, so ADR-0008 rule 2 does not bind); the operator documentation is a new `## Studio` section in `docs/guides/portal-user-guide.md` beside `## Chat` plus the nav and Documents-picker updates, and no new ADR (`docs/adr/` untouched, ADR-0009 stays `accepted`). Rolled onto dev-k8s with all nine products `1/1 READY` at `0` restarts, `agent-service` bootstrapping the shipped DDL against the **real** legacy `sessions` database six times over and classifying both legacy rows exactly as OQ-2 prescribes with none left NULL; the browser live check then confirmed the per-role nav split, the verbatim control split in each entry, one-click Chat create vs Studio's target-optional dialog, a `403` naming the *existing* `session:skill_graduate` for a hand-crafted development create as `luban-developer`, the operation-only picker with its `400` create-path rejection (`201` for an operation session carrying a declared target), live immutability under declare-target, and R-5's shared core by **identical SSE frame vocabulary** across both modes. | `docs/specs/SPEC-056-studio-skill-development-workspace/` |
| Multi-target skill development — Studio spawn bridge + composition | Deferred from the 2026-09-12 SPEC-056 design discussion. With skills confirmed **single-target** (SPEC-055 R-4 re-validates every observed origin against the one target declared *before* mutating, so a multi-target operation trace cannot graduate), multi-target *workflows* need what SPEC-056 deliberately omits: (a) a **"Continue in Studio" spawn bridge** opening a fresh development session that carries context from an operation session without mutating its now-immutable `session_type`; (b) a **stored composition / runbook-of-skills** construct sequencing single-target skills into a multi-target workflow; and (c) **assisted trace-extraction** (offer the captured steps that landed on a chosen target so the operator curates rather than re-performs). **Spiked and answered 2026-09-16**: the memo (`docs/workspace/composition-trust-model-spike.md`) found the question already resolved by shipped code — `FlowContext.identity()` is `(skill_id, origin)`, `FLOW_CONTEXTS` is keyed by `session_id`, and ADR-0007 re-parks on rebind, so a composite navigating into its next sub-skill re-parks with **no composition-aware code**. **ADR-0011** (accepted 2026-09-16) records the decision: a composition carries no authority and each sub-skill keeps its own gate; it is a declarative ordered sub-skill list validated at ingestion with **no control flow**; it is not a transaction, re-entering from a named step off existing `execution_records` receipts; and mixed browser+infra composites are allowed. One accepted trade-off was carried into the spec and is bounded there — the step budget is per bound flow, so N sub-skills bring N budgets, and **SPEC-057 R-2** caps a composite at 8 sub-skills (a new `SKILLS_COMPOSITION_MAX_SUB_SKILLS` knob) rather than adding a kernel counter, making 8 × `GATEWAY_BROWSER_FLOW_MAX_STEPS` (20) = 160 the worst-case unlocked browser writes per run, each still individually signed, audited and receipted and each sub-skill still gated once. Both promotion gates are satisfied (SPEC-056 delivered 0.37.0; ADR-0011 accepted) and **SPEC-057 was approved 2026-09-16**, OQ-1..OQ-5 resolved on the draft's own recommendations. Phase 1 is **(b)** only; **(a)** and **(c)** stay deferred behind it as authoring ergonomics that change no gate semantics. **Status `delivered`** (2026-09-20, v0.40.0) — the composition construct, its two-layer fail-closed ingestion validation (the structural `_validate_composition` shared by the validate route + CLI, and the store-consulting `_resolve_compositions` in `sync_once`), the derived **persisted** `risk_class`, the `get_skill` resolved-sub-skill projection, the portal risk badge + read-only Runbook list, and the mixed browser+infra `samples/acme-admin/composition/` demo (**2** cards on one session, wired into `demo-suite.sh` so the mounted id set grows five → six) all shipped; **ADR-0011** realized with **no new enforcement machinery** (each sub-skill keeps its own gate through the shipped `FlowContext` `(skill_id, origin)` identity guard + ADR-0007 re-park-on-rebind), **no new policy action**, **no new audit event type**, and no kernel trust state. Shipped with the full `make verify` gate green at 0.40.0 (**2,738** product tests, four kustomize overlays, policy rules and scenarios **unchanged**, api and tools scenarios, version lockstep, secret vocabulary), the portal suite green (**408** tests / 32 files) with `npm run build` clean, and `make policy-diff` reporting **zero** outcome transitions across all **138** (role, action) pairs on both engines against an identical bundle hash. | own spec (`SPEC-057`), nineteenth R5 slice, Phase 1 — **delivered** 2026-09-20 (v0.40.0; retargeted v0.38.0 → v0.40.0 on 2026-09-17 so SPEC-058/059 supplied its repertoire first) |
| HTTP service-check tools (`http.get` / `http.post`) | Raised 2026-09-17 by the walkthrough-enrichment discussion that produced SPEC-059, and answered the same day: the platform has **no HTTP surface at all** — fifteen `web.*` tools and five `k8s.*` tools — so "is this service healthy" has to drive a headless browser to `/healthz` and scrape JSON out of a rendered page. The shipped skill library already claims the surface exists: `InventoryHealth` states its purpose as "Complements the API-level checks by exercising the rendered UI", and there is not one API-level check skill in `shared/platform-ops/skills/`. It is a spec rather than a contributed connector because of a **shape inversion** — `docs/guides/adding-a-tool.md`'s worked example (`cmdb.lookup`) takes the upstream from configuration and the model supplies only a validated id, whereas `http.get(url)` has the *model supply the URL*, which is `web.navigate`'s shape and therefore inherits its discipline: a server-side origin allowlist that is deny-by-default, redirects that halt when they leave it (max three hops, relative redirects resolved and re-checked), scheme and userinfo refusals, and loopback/link-local/multicast refused even when listed. Fixed response projection whose header allowlist can never carry `set-cookie`; an upstream 4xx/5xx returned as a **fact** rather than a tool error, because "the service answered 503" is the signal a health check exists to report; credentials by `credential_set` reference only with **no `headers` parameter** on either tool, so a credential cannot be a model-supplied literal by construction. `http.post` (write tier, one URL per invocation, JSON body bounded to depth 2 / 32 keys / 4096 bytes, secret-bearing POST URLs refused) parks exactly one `approval_kind: action` card through machinery `runtime_kernel.py:1251` already derives for every non-browser write, so it arrives with SPEC-054/055/037 approval, masking, signing and audit posture built rather than invented — the one new design work is a curated `_cr_http_post` change-request formatter, since the generic fallback would render `url: ***` / `body: ***` and turn the gate into approval theatre. That formatter carries the slice's single recorded divergence from SPEC-055 R-7's fail-closed masking (non-secret-named scalar body values render), sound only because the no-headers/reference-only rule makes a credential-in-argument impossible; `KNOWN_SAFE_FIELDS` gains `http.post.url` only, `OPAQUE_VALUE_FIELDS` gains nothing, so an HTTP-mutating skill stays graduable. `_redact_secret_query` and `_SECRET_QUERY_PARAMS` extract into a shared `tools/url_redaction.py` with `validate_secret_vocabulary.py`'s textually pinned `TOOL_GATEWAY_REL` moved in the **same** commit. No new policy action (policy is tier-based, so a read tool needs no bundle edit — `make validate-policy` passing with an unmodified bundle is itself an assertion), no new audit event type, no contract change. **Approved 2026-09-17**, OQ-1..OQ-4 resolved on the draft's recommendations; it takes the v0.38.0 slot and SPEC-057 moves to v0.40.0, because SPEC-057's compositions need the single-target repertoire SPEC-058 and SPEC-059 supply. | own spec (`SPEC-058`), twentieth R5 slice — **delivered** 2026-09-17 (v0.38.0) |
| `acme-admin` sample application and its single-target skill suite | Raised 2026-09-17 by the operator's request to enrich the SPEC-056 single-target walkthroughs before moving to SPEC-057. The current tutorial target cannot teach verification: stock `nginxinc/nginx-unprivileged` serving six static pages from a ConfigMap, whose login accepts any credentials and whose reset page "reports success for any user" (`samples/web-checks/password-reset/WALKTHROUGH.md:203`) — the walkthrough says so out loud and then has to explain why the URL it just showed is a lie. Nothing persists, so no skill can check whether a previous skill's mutation landed, and four demos stay four disconnected demos. `acme-admin` is a small FastAPI user-administration console with **real state** (in-memory, `replicas: 1` + `Recreate`, a monotonic `revision` on every mutation, real 404/409, real credential validation) over two parallel surfaces — a JSON API and the same six server-rendered page shapes and 28 element ids the current target serves — which is what makes the later rebase of the three shipped samples a *retarget* rather than a rewrite (that rebase is deliberately a separate slice). Its `/internal/reset-demo` reseed is gated on a header **`http.post` structurally cannot send** (SPEC-058 R-4 ships no `headers` parameter), so the agent cannot reset demo state mid-run: a structural control rather than an instruction. One generated admin password written into two secret sinks (`tool-gateway-browser-credentials` credential set + `acme-admin-credentials`) by an extended `sync-browser-credentials.sh`, failing **closed** at startup when `SKIP_BROWSER_CREDENTIALS=true`. The first sample to own a container image, and it honours both existing constraints rather than working around them: SPEC-050 R-11 (manifests under `samples/`, allowlist entries in the `browser-dev` runtime profile, `dev-k8s/base` names nothing) and `make build` as the single coordinated image path (a new `make deploy-sample-app` reuses `IMAGE_TAG` and the `mk/` fragments **without** joining `IMAGE_PRODUCTS`, whose loops are hardcoded to `products/$$p`). Four skills demonstrate the approval model as a clean **0 / 0 / 1 / 1** card ladder across both surfaces: `http.get` health check (the repository's first genuinely card-free read-only skill — every shipped `web-checks` skill is `risk_class: write` because signing in needs `web.click`), a browser user-status read that exists to *verify what the mutating skill did*, an `http.post` lock/unlock parking one `action` card, and a bound browser password reset parking one `flow` card — so a reader sees SPEC-054's discriminator from both sides. Both SPEC-051 asymmetries are preserved (login auto-submits so authentication costs only read-tier `web.fill_credential`; reset pre-fills from `?newpw=` but does not, so the sole `web.click` is the mutation the operator approves). Names around `deploy-samples.sh`'s leaf-dir slug rule, which would otherwise collide byte-identically with the shipped `samples/password-reset-resetuserpassword` id. **No product code changes at all** — which is the point of keeping it separate from SPEC-058. **Approved 2026-09-17**, OQ-1..OQ-5 resolved on the draft's recommendations. | own spec (`SPEC-059`), twenty-first R5 slice — **delivered** 2026-09-17 (v0.38.0, pulled in with its SPEC-058 dependency) |
| Rebase the `web-checks` samples onto `acme-admin` | The retarget SPEC-059 R-2 deliberately engineered for and named as its follow-up slice ("the next slice (SPEC-060)"), promoted 2026-09-18 from a password-reset walkthrough question that exposed the static target's core teaching defect live: a tester following `skill-graduation` sees no "Last reset" change because `browser-check-target` has no server state. Retire the static-mock `web-checks/password-reset` (superseded by the delivered `acme-admin/password-reset`, which already verifies via `http.get /api/users/{u}`), migrate `adhoc-password-reset` and `skill-graduation` under `samples/acme-admin/` retargeted to the stateful `acme-admin` (origin + credential-set swap plus prose, valid because SPEC-059 R-2 kept the six URL shapes and 28 element ids), and **upgrade** `skill-graduation` to reseed and verify both resets against real store state (`revision` + `password_changed_at`) — so one target that really mutates backs every browser tutorial and the approval-model triad (flow ↔ action ↔ author/graduate) is taught and verified end to end. Retires the `samples/web-checks/` category but **keeps `browser-check-target` shipped and untouched** for its platform consumers (`InventoryHealth`, `browser-check-demo.sh`, the `browser-dev` allowlist, the `admin-portal`/`browser-check-target` credential sets); leaf dir names preserved so surviving skill ids stay stable and only `samples/password-reset-resetuserpassword` is intentionally removed. Also records that `acme` is the fictional-company placeholder (Acme Corp), not the ACME certificate protocol. **No product code, contract, policy, or GitOps change.** | own spec (`SPEC-060`), twenty-second R5 slice — **delivered** 2026-09-19, ships in v0.39.0 |
| Retire `browser-check-target`, `InventoryHealth`, and the orphaned credential sets | The cleanup SPEC-060 deliberately deferred: SPEC-060 kept the static `browser-check-target` mock shipped for its platform consumers and named their retirement as a follow-up decision; this slice makes it. Now that every browser tutorial runs against the stateful `acme-admin` console and the HTTP surface is shipped, three assets are redundant — `InventoryHealth` (the last `platform-runbooks/web-checks/` runbook, a `risk_class: write` browser health check whose Purpose claims it "complements the API-level checks" that only arrived with SPEC-058/059 and are now supplied by the `acme-admin/health-check` *sample* `CheckServiceHealth`), the `browser-check-target` static app (six hard-coded pages, a `/status` that always reads `operational`, a reset page that "reports success for any user" — the exact teaching defect SPEC-059 replaced), and `browser-check-demo.sh` (its only driver, and *not* in the `make e2e` script list — the browser flow + single-HITL-gate path it exercised is covered against a target that really mutates by `demo-suite.sh` rung 4, which *is* gated and was live-validated for SPEC-060). Retires all three, drops the two now-orphaned dev credential sets (`browser-check-target`, and `admin-portal` which SPEC-060 already emptied of consumers), repoints five `products/agent-platform/tests/` fixtures (and one incidental `src/` comment example) off the retired origin string, and corrects the living docs — leaving `browser-dev` as the browser *posture* profile (sidecar + CDP-deny NetworkPolicy + env) permitting exactly one origin, `acme-admin`. **No product behavior, contract, policy, or audit change** — test fixtures, one comment, plus a GitOps/config *reduction* only. | own spec (`SPEC-061`), twenty-third R5 slice — **delivered** 2026-09-19, ships in v0.39.0 (rides the same unreleased train as SPEC-060) |
| Secure password generation and delivery tools | Raised 2026-09-21 by the conversational-reset walkthrough reframe (the doc-only change that made the `acme-admin` reset prompts conversational): an operator who can conversationally ask to reset dave's password should also be able to ask the platform to generate a strong one, which it can neither do nor hand back securely today. Two tool-gateway primitives — a read-tier CSPRNG `secrets.generate_password` (randomness from Python's `secrets`, never model-invented) bound to a single-source `password-policy` contract, and a one-time, owner-scoped, server-mediated **delivery** handoff whose primary channel renders a portal **Copy password** button (redemption-on-click, so the value rides no transcript/title/card/evidence/stream frame and the SPEC-049 R-5 / SPEC-055 R-7 no-plaintext-projection posture is preserved, not excepted) and whose optional second channel emails it through a `secrets:deliver`-gated outbound tool bounded by a recipient allowlist plus mandatory card confirmation. Delivery is one `secrets.deliver(channel=…)` dispatcher over per-channel senders (Teams/Slack additive), the buffer is replica-ready behind an in-memory/Redis `Protocol`, and one new `secret_delivered` audit event type plus one new `secrets:deliver` action are introduced. The retrieval-vs-masking crux — a tool-generated value is not caught by `prose_redaction`'s user-text-only harvesting — is why this is a spec, not a connector. **Approved 2026-09-21**, D-1..D-8 resolved; tracked with **ADR-0012** (one-time secret-delivery handoff). **Status `delivered`** (2026-09-22, v0.41.0) — the read-tier CSPRNG `secrets.generate_password` with a fail-closed single-source policy contract, the intrinsic one-time owner-scoped portal-copy handoff (redemption-on-click through an authenticated `no-store` gateway route + platform proxy, value straight to clipboard and riding no projection), the write-tier `secrets.deliver(channel="email")` dispatcher behind `secrets:deliver` + `tools:mutate` with mandatory certificate-validated STARTTLS and exact-recipient allowlisting, the kernel generated-literal harvest/masking across every projection, the `secret_delivery` stream frame (v12) + `secret_delivered` audit event, the portal Copy-password control and email-warning acknowledgment, and the `GeneratePassword` knowledge skill + `acme-admin` runbook branches all shipped; **no model-side generation**, generation disabled by default and SMTP inert in the base overlay. Shipped with the full `make verify` gate green at 0.41.0 (all product pytest, four kustomize overlays, policy rules and scenarios, version lockstep, secret vocabulary, the new `validate-password-policy` leg, and the local handoff demo), the portal suite green with `npm run build` clean, a cross-product generation→projection→redemption integration test, mocked-I/O execution of the live demo, and three in-memory security mutation checks (projection bypass, dropped harvest, weakened owner scope) each tripping an assertion; no live email, deployment, browser or OS-clipboard use. | own spec (`SPEC-062`), twenty-fourth R5 slice — **delivered** 2026-09-22 (v0.41.0) |
| Infra mutating-tool granularity | SPEC-055's **OQ-2**, deferred at approval and re-anchored here at that delivery rather than shipped; **reframed 2026-09-16** by the composition-trust-model spike (`docs/workspace/composition-trust-model-spike.md`) and **ADR-0011**, which rejected this row's original premise. The premise was that today's flow binding (`FlowContext`/`web.navigate(skill_id=…)`) is browser-specific, so an infra (`k8s.*`) executable-flow skill — authorable and ingestable since SPEC-055 R-3 decoupled `risk_class: write` from `web_target` — has no binding analog, and its steps park **per-action** under SPEC-054 R-2 instead of collapsing to one gate. That fallback fails safe (each write still approved, signed, audited, receipted, and joining no auto-allow list) and is asserted by SPEC-055 R-5's tests, so the gap was always usability rather than safety — but generalizing browser flow binding to infra is the **wrong fix**. Infra arguments are self-describing (`k8s.delete_pod` names its pod and namespace, so a card's arguments *are* the action), whereas browser refs are opaque pointers needing `display_hint` resolution; binding would replace N assessable cards with one carrying strictly less information. The real gap is **tool granularity** — no `k8s.restart_deployment`-shaped tool matches the operator's decision unit, so one decision costs N `delete_pod` cards. Card count should track assessable decisions, not tool risk labels: three pods deleted as three decisions correctly costs three cards. Promote on the first infra executable flow an operator actually graduates and replays, since the missing tool's shape should be driven by a real `k8s.*` step list rather than a speculative generalization of the browser one. | tool-gateway infra connector (new mutating tools matching operator decision units), not flow authority |
| Browser tier residuals — `web.evaluate` card opacity and read-tier tools with side effects | Two findings from the 2026-09-16 write-tier review (which changed no tier — all six `BROWSER_WRITE_TOOLS` stayed write, shipped as `30b84ff` giving the five blanket descriptions their real rationale) that the review deliberately did **not** act on. **(c)** `web.evaluate` is write tier (`flow_approvals.py:47-54`) because arbitrary JS can mutate the DOM, but its ad-hoc card can only ever read "Evaluate a JavaScript expression on the page": `web.evaluate.expression` is in `OPAQUE_VALUE_FIELDS` (`secret_params.py:110-122`) and `_cr_web_evaluate` refuses to project it — necessarily so, because the expression can *be* the mutation and can embed a literal credential (`document.querySelector('#pw').value = '<literal>'`). The card is therefore unassessable **by construction, not by oversight**, which means `web.evaluate` is only meaningfully gateable *inside a bound flow* where intent was declared at authoring time (`flow_intent` + declared `web_target`). Options: accept and document evaluate as flow-only in practice; deny unbound evaluate outright; or add a structural projection safe to show (a DOM-read vs DOM-write classification rather than the expression). **(d)** `web.hover` is read tier (`browser_connector.py:1975`) though a hover can open menus and change visible page state. `web.navigate` is also read tier (`browser_connector.py:744`) but must stay so — it is the flow-binding call, and gating it would break the mechanism ADR-0011 relies on — so the residual is hover alone. Promote (c) on the first operator report that an evaluate card was unactionable, or the first ad-hoc evaluate used to mutate; promote (d) on the first hover-triggered state change that should have gated. | tool-gateway browser connector + agent-platform change-request formatters |
| Approval-workflow extensions | SPEC-031 non-goals parked as future candidates: multi-approver quorum / N-of-M semantics (extending the SPEC-030 approval tiers), push notifications (webhook, email, browser push), cross-session bulk approve, and richer approver review context (owner-transcript exposure has its own decision). Promote on the first concrete governance or operational ask, not before. | approval-flow spec |
| Numbered-list continuation across separated blocks | v0.18.1 live-check observation: when the model emits numbered steps as separate blocks (blank line or paragraph between items), the escape-first renderer produces separate `<ol>` elements and each restarts at 1. Cosmetic; decide renderer merge strategy vs prompt guidance if operators complain. | operator-portal markdown renderer / prompt guidance |
| Dependency hygiene (portal and backend) | Raised in the v0.23.2 delivery train: the vitest suite prints 53 antd deprecation warnings (48× Drawer `width`, 5× Alert `message`) and the same-day upgrade check found the portal majors several majors behind upstream (vite 6 vs 8, vitest 3 vs 4, TypeScript 5.6 vs 5.9, React 18 vs 19, jsdom 25 vs 30). A matching backend check found the lockfiles close to current: agentscope 2.0.6 → 2.0.7.post1 and fastapi/uvicorn in-range floats, plus three adjudicated range decisions (cryptography caps `<45` vs upstream 50.x; redis `<7` and elasticsearch `<9` parked with reasons). Revised 2026-08-28 per operator feedback: latest-stable-only adoption policy (no beta/RC/dev; single recorded exception — the OTel instrumentation packages' permanent 0.xb upstream channel, kept at its locked pairing). Drafted as `SPEC-042-dependency-hygiene` (renamed from `SPEC-042-portal-dependency-hygiene`) directly from the checks (memo-free, SPEC-031/032 departure): deprecation migration plus a zero-tolerance vitest guard, the recorded adopt set, the React 19 migration with a behavioral gate, and the backend re-lock with a kernel-verification leg for agentscope; TypeScript 7.x parked as too new. Approved 2026-08-28; delivered 2026-08-28 (0.24.0) as the fourth R5 slice — antd deprecation migration with a zero-tolerance vitest guard, the recorded adopt set (TypeScript 5.9.3, vite 8.2.2 + plugin-react 6.1.1, vitest 4.1.11, jsdom 30.0.1, `engines.node >=22.22.2`), React 19.2.8 behind the behavioral gate, and the backend stable-channel re-lock (agentscope 2.0.7.post1, fastapi 0.141.1, uvicorn 0.52.4; cryptography caps raised to `<51.0` after the signing call-site review; redis/elasticsearch caps parked). | `docs/specs/SPEC-042-dependency-hygiene/` |
| Isolated execution worker and signed execution requests | Spiked 2026-08-26 after the v0.18.1 consolidated live check declared the approval cluster stable: the memo (`docs/workspace/execution-runtime-spike.md`) verifies the approved mutating path still executes in-process under the confirmer's delegated token, weighs sign-and-record vs isolated-worker vs full-async-queue, and recommends a phased shape. Phase 1 (HMAC-signed execution requests/receipts bound to the parked args digest) was promoted to `SPEC-037-signed-execution-requests` on 2026-08-27 after operator sign-off and delivered the same day (0.19.0). The memo's promotion gate was then satisfied — Phase 1 live-verified on the `mutating-dev` profile — and Phase 2 (the isolated `execution-runtime` worker) was promoted to `SPEC-038-isolated-execution-worker` on 2026-08-27 with the memo's Q-1 (handoff service identity) and Q-2 (resume await timeout) resolved in the draft; the spec was approved the same day with one recorded condition — an R5 re-evaluation trigger: when more team members work simultaneously, concurrent approved actions contending on the single worker pod promote the queue/pool spec at that signal. Together they close the two remaining R4 deliverables. | SPEC-037 delivered; SPEC-038 delivered (0.20.0) |
| Approval inbox and persistent confirmation cards | Delivered 2026-08-25 (0.13.0) as `SPEC-031-approval-inbox-persistent-confirmation`, drafted directly from the SPEC-030 live-cluster validation (no spike memo — the validation itself was the evidence base): durable confirmation lifecycle records on the shared Postgres posture (cap 50 per session, TTL-scoped startup expiry), an additive owner-transcript `confirmations` surface so cards survive re-login and pod restarts, a decider-scoped `GET /api/v1/approvals/inbox` behind a new `approvals:list` policy action (metadata-only, pending + 30-day history incl. expired), structured `409 already_resolved` race responses, and a portal Approvals view with pending-count badge plus persistent owner-side cards. | `docs/specs/SPEC-031-approval-inbox-persistent-confirmation/` |
| Owner-side live decision sync | Delivered 2026-08-25 (0.14.0) as `SPEC-032-owner-side-live-decision-sync`, drafted directly from the v0.13.1 live validation finding that the owner's open chat window never learned about a decision made from the approver inbox: a bounded, change-gated poll-while-pending on the existing session-detail surface (5s, torn down when no card is pending or any stream is active, settle window for the trailing resumed-turn content) re-seeds the turn timeline so the decided card with attribution and the resumed turn appear without a refresh. Portal-only — no backend, contract, or policy changes. | `docs/specs/SPEC-032-owner-side-live-decision-sync/` |
| Confirmation card turn anchoring | Delivered 2026-08-26 (0.15.0) as `SPEC-033-confirmation-card-turn-anchoring` from the v0.14.1 live validation finding that a multi-park session stacks every confirmation card under the newest turn: parked records persist their parking turn ordinal (the same `_count_user_turns` convention SPEC-025 evidence uses, additive column with in-place migration), the session-detail surface carries it additively, and transcript seeding anchors each card under the exchange that parked it. Legacy rows fall back to today's anchoring. | `docs/specs/SPEC-033-confirmation-card-turn-anchoring/` |
| Approval & owner chat UX polish | Delivered 2026-08-26 (0.16.0) as `SPEC-034-approval-owner-ux-polish` from the v0.15.0 live approval-test feedback: portal-only — owner-window arrival highlight for post-decision content, instant session-list refresh on applied decisions, Pending/History tabs in the Approvals view, separated inbox entries with structured provenance headers, and a banner note on pending-request expiry. | `docs/specs/SPEC-034-approval-owner-ux-polish/` |
| Decision sync robustness and arrival polish | Delivered 2026-08-26 (0.17.0) as `SPEC-035-decision-sync-arrival-polish` from the v0.16.0 live approval-test feedback: transcript segment boundaries (agent-service block join + live-stream paragraph break), a time-based settle window with a visibility kick, progressive arrival reveal, session-tag park timing with a stale-response guard, approvals banner line, and History-tab pagination. | `docs/specs/SPEC-035-decision-sync-arrival-polish/` |
| Server inbox pagination and seeded transcript reveal | Delivered 2026-08-26 (0.18.0) as `SPEC-036-inbox-pagination-and-seeded-reveal` from the v0.17.0 post-release review: the approvals History tab moved to server-side pagination (split store queries with a windowed total, paginated inbox API, gateway pass-through, server-driven portal tab) because the combined payload's 100-row cap silently dropped older decisions as volume grew. R-1 (the cold-seeded transcript typewriter cascade) shipped with 0.18.0 but was reverted in the 0.18.1 patch after the live check — the typewriter now applies to live arrivals only — alongside two more live-check fixes: a markdown list-rendering fix (nested/indented bullets and ordered-list wrapping) and pod-log excerpts in agent replies moving to fenced code blocks rendered in a fixed-height scrollable box. | `docs/specs/SPEC-036-inbox-pagination-and-seeded-reveal/` |
| Signed execution requests and receipts | Delivered 2026-08-27 (0.19.0) as `SPEC-037-signed-execution-requests`, Phase 1 of the execution-runtime spike (`docs/workspace/execution-runtime-spike.md`): approved mutating calls gain a tamper-evident execution chain — HMAC-signed execution requests bound to the parked arguments' digest at approval resume (missing signing key fails closed with an audited `signing_unavailable` rejection), argument-digest verification at the invocation boundary (`args_digest_mismatch` blocks and audits), durable execution records and signed receipts beside the SPEC-031 confirmation records with an additive owner-scoped `executions` session-detail surface, `execution_requested` / `execution_completed` / `execution_rejected` audit events correlating the full decision-to-execution chain, a read-only receipt badge on decided confirmation cards, and the `execution-signing-secret` deploy wiring. Execution stays in-process; the isolated worker remains Phase 2. | `docs/specs/SPEC-037-signed-execution-requests/` |
| Isolated execution worker | Delivered 2026-08-27 (0.20.0) as `SPEC-038-isolated-execution-worker`, Phase 2 of the execution-runtime spike (`docs/workspace/execution-runtime-spike.md`) and the close of R4: approved mutating calls leave agent-service via an authenticated internal handoff to the new `execution-runtime` worker, which independently re-verifies the SPEC-037 envelope signature and parked-arguments digest, executes through the tool-gateway under the forwarded confirmer delegated token, authors the signed receipt on the shared `execution_records` table (first-write-wins), and emits the correlated `execution_completed` / `execution_rejected` events. The resumed stream blocks on the worker under a bounded timeout (default 60s); single-flight idempotency keyed by `execution_id` suppresses repeats while the entry remains in that worker process, with one desired replica (restart/overlap durability is proposed in SPEC-063, not shipped); every missing credential fails closed (`worker_unavailable`, no in-process fallback); isolation is infrastructure-enforced (own Deployment/ClusterIP Service, `execution-handoff-secret`, no HTTPRoute). The approval-condition R5 re-evaluation trigger (concurrent-operator queueing) stays recorded on the backlog. | `docs/specs/SPEC-038-isolated-execution-worker/` |

Promotion rule: a spike lands its findings as a short memo (workspace docs);
only then does the item get a SPEC number. SPEC-018 (kernel middleware
alignment) was delivered after SPEC-017 and re-confirmed this backlog in its
utilization memo (`docs/workspace/agentscope-utilization-audit.md`).
SPEC-020 (HITL confirmation bridging) was promoted from this backlog on
2026-08-21 after its spike memo landed. SPEC-030 (require-approval policy
semantics) was drafted on 2026-08-25 from its spike memo, promoted from the
"next R4 slice" marker on the bounded-mutating-actions row, and delivered
the same day in the 0.12.0 train. SPEC-031 (approval inbox and persistent
confirmation cards) was drafted on 2026-08-25 directly from the SPEC-030
live-cluster validation findings — a deliberate departure from the
memo-first rule, since the validation itself supplied the evidence base —
and delivered the same day in the 0.13.0 train. SPEC-032 (owner-side live
decision sync) was drafted the same day from the v0.13.1 live validation
finding (owner window deaf to external decisions) — the same memo-free
evidence-base departure — and delivered the same day in the 0.14.0 train.
SPEC-033 (confirmation card turn anchoring) was drafted on 2026-08-26 from
the v0.14.1 live validation finding (multi-park sessions stack every card
under the newest turn) — the same memo-free evidence-base departure — and
delivered the same day in the 0.15.0 train. SPEC-034 (approval & owner
chat UX polish) was drafted the same day from the v0.15.0 live
approval-test feedback (five portal usability enhancements) — the same
memo-free evidence-base departure — and delivered the same day in the
0.16.0 train. SPEC-035 (decision sync robustness and arrival polish) was
drafted the same day from the v0.16.0 live approval-test feedback (a
refresh-needed sync gap, broken resumed-heading markdown, an unnoticed
arrival highlight, session-tag timing, and two approvals-view layout
asks) — the same memo-free evidence-base departure — and delivered
the same day in the 0.17.0 train. SPEC-036 (server inbox pagination and
seeded transcript reveal) was drafted the same day from the v0.17.0
post-release review (a growing-history truncation concern and a
presentation-consistency ask) — the same memo-free evidence-base
departure — and delivered the same day in the 0.18.0 train, with R-1
refined mid-flight at operator sign-off so the cold-seed reveal
cascades every seeded reply instead of only the most recent one. The
v0.18.0 live check then produced the 0.18.1 patch the same day: R-1
was reverted at operator decision (the seeded typewriter read as delay
rather than polish — the reveal stays reserved for live arrivals), and
the chat markdown renderer gained nesting-aware list handling after
indented sub-bullets were observed rendering as literal "- text"; the
same patch moved pod-log excerpts in agent replies into fenced code
blocks (prompt guidance plus a fixed-height scrollable box in the
portal) after the live check surfaced a JSON-serialized log string.
SPEC-037 (signed execution requests and receipts) then returned the
promotion flow to the memo-first rule: spiked 2026-08-26 from the
verified current execution path after the consolidated v0.18.1 live
check declared the approval cluster stable
(`docs/workspace/execution-runtime-spike.md`), operator sign-off on
the phased shape given 2026-08-27, and the Phase-1 scope promoted to
a spec draft the same day. Its Phase 2 (the isolated
`execution-runtime` worker) will take its own spec number after Phase
1 is live-verified. Phase 1 was delivered the same day in the 0.19.0
train with no requirement changes: the live check ran the
`mutating-demo.sh` HITL leg on the `mutating-dev` profile and observed
the signed receipt on the approved card plus the correlated
`execution_requested` / `execution_completed` audit chain. That live
verification satisfied the memo's promotion gate, and the Phase-2 scope
(the isolated `execution-runtime` worker) was promoted on 2026-08-27 to
`SPEC-038-isolated-execution-worker` under the same memo-first lineage —
the memo's Q-1 (worker service identity for the internal handoff) and
Q-2 (resume-stream await timeout) resolved during drafting; Q-3 was
already resolved by SPEC-037 R-6. SPEC-038 was approved the same day
with one recorded condition — the R5 re-evaluation trigger for
concurrent-operator queueing on the single worker pod — and delivered
the same day in the 0.20.0 train, closing the last two R4
deliverables. R4 was formally closed the same day: all six R4
deliverables shipped and the Release Completion Signal exercised
across the v0.13.1–v0.20.0 live approval-test campaign. Opening R5,
the paired cross-owner session review / shift-summary candidates
(raised in the SPEC-035 open question, re-stated by SPEC-036) were
spiked together on 2026-08-27 under the memo-first rule
(`docs/workspace/session-handover-spike.md`), verified against the
0.20.0 session workspace and approval surfaces; the memo recommends
promoting the shift-summary artifact first — a deterministic digest
with an optional clearly-labeled prose layer and provenance anchoring
— and parks raw cross-owner session review behind a recorded trigger,
awaiting operator sign-off before spec promotion. Sign-off was granted
the same day, and the shift-summary artifact was promoted to SPEC-039
(draft) under the memo-first lineage with the memo's Q-1 (artifact
ownership/audience), Q-2 (audit posture), Q-3 (prose guardrails —
digest-only prompt contract, labeled rendering, fail-soft), and Q-4
(retention — immutable snapshot, cap 20, 30-day TTL aligned with the
inbox history window) resolved in the draft. The same-day operator
review then generalized the scope — operators also need incident
reports and reusable guidance, and per-document permission grants are
the wrong operating model — so SPEC-039 was retargeted to
`SPEC-039-operations-document-repository`: a typed-document substrate
with a role-based access matrix (draft→publish lifecycle replaces
per-document ACLs; creation/publishing behind `documents:create`,
role-scoped reads behind `documents:read`, cross-owner reads
audited), the shift summary as the first document type, and session
rename plus session-id copy as add-ons supporting the sharing
workflow. Incident reports become the next type candidate (their
assembly reaches incident-service data), skill authoring export is
recorded as a separate backlog candidate — explicitly not a document
type, keeping Git-managed team knowledge (SPEC-014) the artifact of
record — and cross-owner raw session review stays parked behind its
recorded trigger. SPEC-039 remains the first R5 slice.

## Validation Model Per Release

Every release should have four validation layers:

- `service validation`
- `workflow validation`
- `control validation`
- `user acceptance validation`

### Service Validation

Checks:

- service health
- API contract behavior
- event streaming
- connector integration

### Workflow Validation

Checks:

- end-to-end operator scenarios
- evidence visibility
- UI usability for the intended release goal

### Control Validation

Checks:

- `SSO`
- identity propagation
- policy decision behavior
- approval and audit integrity

### User Acceptance Validation

Checks:

- operations team can use the release without engineering guidance
- release saves time or improves confidence
- operators trust the outputs enough to adopt the workflow

## Suggested Iteration Rhythm

Use short internal iterations within each release, but treat the release itself as the validation boundary.

Recommended rhythm:

- `design and integration preparation`
- `core implementation`
- `end-to-end workflow completion`
- `operations validation`
- `hardening and release decision`

This keeps releases self-contained while still allowing normal engineering iteration inside them.

## Recommended Release Readiness Checklist

Every release should answer `yes` to these questions before moving on:

- does the release deliver one clear operator-visible capability?
- are the integration points working end to end?
- can operations teams validate the release with a small set of concrete scenarios?
- are logs, traces, and audit records sufficient to investigate problems?
- does the release keep faith with the platform design principles?

## Design Principles Carried Through Delivery

These principles should remain visible in every release:

- `bounded autonomy`
- `diagnose before act`
- `identity before privilege`
- `read before write`
- `explicit approvals for risk`
- `Git-managed team knowledge`
- `API-first and gateway-friendly integration`

## Final Recommendation

Deliver the platform as a sequence of self-contained, vertically integrated releases where each release gives operations teams something specific to try, verify, and trust.

The recommended release progression is:

- `R0` foundation
- `R1` read-only operational value
- `R2` grounded guidance
- `R3` incident triage
- `R4` approval-gated bounded action
- `R5` hardening and external consumption

This roadmap provides the clearest path to building enterprise trust while steadily increasing platform capability.
