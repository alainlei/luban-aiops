# Spec-Driven Development Workflow

## Objective

Define how this workspace manages specifications so that implementation work is always driven by a reviewable, decision-complete spec, and so that documentation cannot silently drift from the code.

This workflow formalizes the discipline already practiced during the platform study and `Release 0`, and makes it repeatable for every future change wave.

## Documentation Tiers

All workspace documentation belongs to exactly one of three tiers, each with a different lifecycle:

### Tier 1: Architecture Record

- long-lived, rarely edited
- examples: `docs/agentic-aiops-platform/part-1-decision-matrix.md`, `part-2-reference-architecture.md`, `identity-and-authorization-design.md`, `docs/workspace/workspace-model.md`
- new architectural decisions are captured as ADRs in `docs/adr/` instead of growing these documents
- edits are limited to corrections and explicit supersession notes

### Tier 2: Feature Specs

- short-lived, written before implementation, frozen after delivery
- live under `docs/specs/SPEC-NNN-<slug>/`
- each spec owns its requirements, technical plan, and task list
- once delivered, a spec is a historical record; follow-up changes require a new spec

### Tier 3: Living State Docs

- must always reflect the current state of the workspace
- examples: root `README.md`, `CHANGELOG.md`, product `README.md` files, GitOps overlay `README.md` files
- kept intentionally minimal so there is less surface that can go stale
- every delivered spec includes a task to update affected living state docs

## When A Spec Is Required

Write a spec before implementation when a change:

- adds or modifies a product capability or service endpoint
- changes a shared contract in `shared/shared-contracts`
- crosses product boundaries or affects the trust model
- changes identity, policy, approval, audit, or execution behavior
- spans more than one focused pull request

A spec is not required for:

- typo and formatting fixes
- dependency bumps without behavior change
- single-file bug fixes with an existing test demonstrating the regression
- documentation-only corrections inside one tier

When in doubt, write the spec. A small spec is cheap; an untracked cross-boundary change is not.

## Spec Structure

Each spec is a directory:

```text
docs/specs/
  SPEC-NNN-<slug>/
    spec.md     # what and why: requirements with acceptance criteria
    plan.md     # how: technical approach, decisions, sequencing
    tasks.md    # execution: tracked task checklist
```

Templates live in `docs/specs/templates/`.

- `spec.md` is written and agreed first
- `plan.md` is written after the spec is approved and before implementation starts
- `tasks.md` is derived from the plan and updated as work proceeds

## Spec Lifecycle

Every `spec.md` carries a status header. Allowed statuses:

- `draft` — under discussion, not yet agreed
- `approved` — agreed scope, implementation may start
- `in-progress` — implementation underway, tasks tracked in `tasks.md`
- `delivered` — all acceptance criteria met and validated; spec is frozen
- `superseded` — replaced by a later spec, which must be linked

Rules:

- requirements in an `approved` spec change only by agreement, recorded in the spec changelog section
- a `delivered` spec is never rewritten; corrections go into the spec changelog section or a new spec
- every implementation pull request links the spec ID it serves

## Numbering And Naming

- specs are numbered sequentially: `SPEC-001`, `SPEC-002`, ...
- slugs are short and kebab-case, for example `SPEC-001-release-1-platform-hardening`
- requirement IDs inside a spec use `R-1`, `R-2`, ... and are stable once the spec is approved
- tasks reference requirement IDs so delivery is traceable from requirement to code

## Relationship To Existing Workflow

- branch naming and commit prefixes follow `CONTRIBUTING.md`; spec work typically uses branches like `feat/spec-001-gateway-auth`
- the design review checklist in `CONTRIBUTING.md` is applied when reviewing `spec.md`, not only the code
- release slices in `delivery-roadmap.md` group specs; a release closes when its specs are `delivered`
- `CHANGELOG.md` entries reference spec IDs for traceability

## Enforcement

Current enforcement is by review discipline:

- pull requests that qualify under `When A Spec Is Required` must link a spec
- reviewers check acceptance criteria before marking a spec `delivered`
- per ADR-0008, a spec advances to `delivered` only when every `R-x` acceptance criterion maps to at least one asserting test (recorded in its `tasks.md`) and any shipped `samples/` demo is exercised by its own script in the verification path

Mechanical enforcement:

- `make verify` is the verification gate: it runs every product test suite and renders every GitOps overlay (`kustomize build`). It is forge-agnostic — the same command runs locally before commit/push and under any CI, so the project does not couple to a specific provider's workflow format. (`SPEC-001` first delivered this gate as GitHub Actions workflows; they were replaced by the portable root `Makefile`.)
- contract tests bind gateway models to `shared/shared-contracts` schemas

## Spec Index

| ID | Title | Status |
| --- | --- | --- |
| `SPEC-001` | Release 1 platform hardening | `delivered` |
| `SPEC-002` | Platform-owned agent-service contract | `delivered` |
| `SPEC-003` | Identity trust hardening | `delivered` |
| `SPEC-004` | Deny-by-default policy enforcement | `delivered` |
| `SPEC-005` | Observability baseline — metrics, tracing, and request correlation | `delivered` |
| `SPEC-006` | Session durability — Redis-backed session store | `delivered` |
| `SPEC-007` | Read-only tool execution framework | `delivered` |
| `SPEC-008` | Service-to-service identity — broker-mediated token delegation | `delivered` |
| `SPEC-009` | Pre-production hardening — tool output redaction and workload-identity service tokens | `delivered` |
| `SPEC-010` | Platform gateway extraction — splitting `tool-gateway` into `platform-gateway` and `tool-gateway` | `delivered` |
| `SPEC-011` | Observability connector and evidence panels — Elastic connector, tool trace events, portal evidence panel | `delivered` |
| `SPEC-012` | Operator guide and deployment documentation — getting started, configuration, troubleshooting, tools, architecture | `delivered` |
| `SPEC-013` | Durable audit trail — audit event contract, audit service store, permission-scoped query API | `delivered` |
| `SPEC-014` | Skills and grounded guidance — skills-hub ingestion/retrieval, skills.search tool, cited answers | `delivered` |
| `SPEC-015` | Incident triage and collaboration — incident-service intake/triage, connector framework, portal Incidents experience | `delivered` |
| `SPEC-016` | Session store separation — Postgres session backend for agent-platform, kernel Redis untouched | `delivered` |
| `SPEC-017` | Agent kernel utilization and conversation durability — kernel configs, structured triage output, AgentState persistence to Postgres | `delivered` |
| `SPEC-018` | Kernel middleware alignment — middleware-based tracing/permission hooks, built-in task tools (sequenced after SPEC-017) | `delivered` |
| `SPEC-019` | Portal transparency — permission matrix, workspace resource views, sectioned navigation | `delivered` |
| `SPEC-020` | HITL confirmation bridging — kernel ASK to portal approve/deny, `chat:confirm` action, `confirmation_decided` audit | `delivered` |
| `SPEC-021` | Bounded mutating actions — first approval-gated write tool (`k8s.delete_pod`), `tools:mutate` action, Approval and HITL Governance Guide | `delivered` |
| `SPEC-022` | Multi-session foundations — session lifecycle API with transcripts and parked-confirmation flags, voice-readiness contract, `mutating-dev` deployment profile (portal UI deferred to the rebuild spec) | `delivered` |
| `SPEC-023` | Portal framework rebuild — multi-session workspace UI on Ant Design X behind a platform-owned SSE contract adapter (consumes SPEC-022 Appendix A) | `delivered` |
| `SPEC-024` | Runtime LLM model switching — credential-gated model catalog, per-session selection with affinity, audited choice, portal composer selector | `delivered` |
| `SPEC-025` | Evidence persistence in session transcripts — durable tool-evidence frames with traceability and metrics, replayed evidence cards on reopened sessions | `delivered` |
| `SPEC-026` | Multi-model runtime catalog — curated model series per provider with model-name entry ids, series override, generic profile consolidation (extends SPEC-024) | `delivered` |
| `SPEC-027` | Live model discovery — provider `/models` endpoints feed the catalog with a fail-soft fallback ladder (live -> memory -> Postgres -> curated) and periodic refresh (extends SPEC-026) | `delivered` |
| `SPEC-028` | Luban-hosted small model provider — `luban` adapter for team-hosted OpenAI-compatible servers (Ollama/vLLM/llama.cpp) with token auth, operator hosting guide, and reference K8s manifests (extends SPEC-026/027) | `delivered` |
| `SPEC-029` | Skills usage audit trail — skills-hub emits `skill_searched`/`skill_retrieved`/`skills_synced` audit events with request-id correlation to caller `tool_invoked` events (extends SPEC-013/014) | `delivered` |
| `SPEC-030` | Require-approval policy semantics — `require_approval` as a first-class policy outcome in both engines, approver-gated confirmation bridge with self-approval blocking, matrix/audit transparency, Settings view restored as a read-only Session & Identity panel (extends SPEC-004/019/020/021) | `delivered` |
| `SPEC-031` | Approval inbox and persistent confirmation cards — durable confirmation records, owner-side cards surviving re-login, decider-scoped approvals inbox with history, race-resilient `already_resolved` semantics (extends SPEC-020/022/030) | `delivered` |
| `SPEC-032` | Owner-side live decision sync — poll-while-pending chat view surfaces external decisions and the resumed turn without refresh (extends SPEC-031) | `delivered` |
| `SPEC-033` | Confirmation card turn anchoring — parked records persist their turn ordinal and seeded cards anchor under the exchange that parked them (extends SPEC-031) | `delivered` |
| `SPEC-034` | Approval & owner chat UX polish — arrival highlight for post-decision content, instant session-list refresh, Pending/History tabs, separated inbox entries, expiry banner note (extends SPEC-031/SPEC-032) | `delivered` |
| `SPEC-035` | Decision sync robustness and arrival polish — transcript segment boundaries, time-based settle window with visibility kick, progressive arrival reveal, session-tag park timing and stale-guard, approvals banner line and history pagination (extends SPEC-032/SPEC-034) | `delivered` |
| `SPEC-036` | Server inbox pagination and seeded transcript reveal — split inbox store queries, paginated inbox API with totals, gateway pass-through, and server-driven History tab (extends SPEC-031/SPEC-035); the seeded-transcript typewriter (R-1) was reverted in the 0.18.1 patch after live-check feedback | `delivered` |
| `SPEC-037` | Signed execution requests and receipts — HMAC-signed execution envelopes bound to parked arguments, invocation-time digest verification, durable request/receipt records, execution audit events, and receipt badges on decided cards (execution-runtime spike Phase 1; extends SPEC-020/021/030/031) | `delivered` |
| `SPEC-038` | Isolated execution worker — `execution-runtime` product consuming the SPEC-037 signed envelope contract, authenticated internal handoff with fail-closed verification, blocking bounded-timeout resume await, `execution_id`-keyed single-flight idempotency, and infrastructure-enforced isolation with no portal or LLM exposure (execution-runtime spike Phase 2; extends SPEC-037) | `delivered` |
| `SPEC-039` | Operations document repository — typed-document substrate with a role-based access matrix (no per-document ACLs), draft→publish lifecycle, provenance anchoring, document audit, and a portal Documents view; Phase 1 ships the shift-summary type (deterministic digest over sessions/confirmations/executions/evidence with two-tier own/metadata-only foreign coverage and an optional digest-only prose layer); session rename and session-id copy ship as add-ons (session-handover spike Option B, extended per the 2026-08-27 operator review; first R5 slice; extends SPEC-022/025/031/037) | `delivered` |
| `SPEC-040` | Shift-summary handover narrative and export — deterministic `handover` digest section (decisions, execution outcomes, open items), prose as the default digest-anchored narrative, Documents moved from Control to Workspace, and client-side Markdown export for offline use (second R5 slice; extends SPEC-039) | `delivered` |
| `SPEC-041` | Documents readability and digest reference — operator-facing digest/vocabulary reference guide, tabbed structured digest rendering in the drawer (handover default, raw JSON preserved), bounded scrollable digest and prose panes, and a deterministic counts-only document summary shown in the Mine/Published lists (third R5 slice; extends SPEC-039/040) | `delivered` |
| `SPEC-042` | Dependency hygiene — portal and backend. Migration off every deprecated antd v6 API (Drawer `width` → `size`, Alert `message` → `title`), a zero-tolerance vitest deprecation guard, a managed portal component refresh per the 2026-08-28 upgrade check (vite 8 + plugin-react 6, vitest 4, TypeScript 5.9, jsdom 30), the React 19 migration, and a backend stable-channel re-lock (agentscope 2.0.7.post1, fastapi/uvicorn floats, cryptography cap adjudication) — latest stable versions only, no beta/RC (fourth R5 slice; extends SPEC-023) | `delivered` |
| `SPEC-043` | Incident report document type — the second type on the SPEC-039 operations document repository: a durable, attributed `incident_report` assembled verbatim from incident-service facts (incident envelope, validated triage report, connector dispatches) plus the linked triage session's digest under the existing two-tier own/foreign posture, with the inherited digest-only prose layer, draft→publish lifecycle, and role-based access matrix; gated by the combination of the existing `documents:create` and `incident:read` actions — no new policy actions, no new audit event types, read-only with respect to incident state (fifth R5 slice) | `delivered` |
| `SPEC-044` | Skill authoring export from sessions — the platform drafts, humans merge: a skill Markdown draft generated from the caller's own session digest (plus the validated triage report when incident-linked) in the digest-anchored posture, validated against Skill Format v1 through skills-hub's own ingestion code path before it reaches the operator, and exported as a client-side `.md` download for contribution to the team's Git skills repo; ephemeral by construction (no durable draft record), gated by one new `session:skill_draft` action with one new `skill_draft_generated` audit event (sixth R5 slice; skill-authoring spike Option A; extends SPEC-014/015/040/043) | `delivered` |
| `SPEC-045` | Incident-anchored skill drafts and draft preview — the two-use-case split adjudicated post-v0.26.0: the incident detail gains **Draft as skill** (generated from the incident envelope minus `triage_raw` plus the validated triage report, dual-gated on one new `incident:skill_draft` action and `incident:read`, deterministic 409 without a validated triage report, one new `incident_skill_draft_generated` audit event) so any incident reader can convert a triage without touching session ownership, while the session surface stays owner-only; and both entry points open a read-only preview (rendered + raw toggle, mode badge, Download .md / Discard) before the client-side download — ephemeral by construction, nothing persisted (seventh R5 slice; extends SPEC-015/043/044) | `delivered` |
| `SPEC-046` | Audit reporting and export — deterministic envelope-column summary aggregates (`total_events`, by type/outcome/service, top actors, and a decision-chain projection over the SPEC-037 events) plus a bounded server-side CSV export (`AUDIT_EXPORT_MAX_ROWS`, streaming pages, truncation headers), proxied by platform-gateway under the existing `audit:read` action, and a portal Audit view upgrade (Events/Summary tabs, export button, full filter vocabulary pinned to the shared audit-event schema by a drift guard) — no new policy actions, no new audit event types, auditor stays read-only (eighth R5 slice; extends SPEC-013/029/037) | `delivered` |
| `SPEC-047` | Audit summary drill-down and readability — every SPEC-046 aggregate value clickable into the Events tab under merged filters (enabled by one additive `outcome` filter dimension on the existing audit routes), percentage + bar proportion on every bucket row (the bar was retired in the 0.29.1 patch after live-review feedback; the share cell is now a single right-aligned percentage), antd statistic row for the headline numbers, collapsible bucket sections; multi-tab-per-report rejected (ninth R5 slice; extends SPEC-013/046) | `delivered` |
| `SPEC-048` | Policy testing and rollout controls — bundle content-hash provenance on the matrix/readiness surfaces, a scenario-expectation harness pinned into `make verify` (the policy analog of the portal drift guard), a `make policy-diff` per-(role, action) impact report, the documented rollout runbook, and copy-parity coverage extended to the overlay copy; no new policy actions, no new audit event types, bundle schema and evaluation semantics unchanged (tenth R5 slice; policy-rollout-controls spike Option B; extends SPEC-004/019/030) | `delivered` |
| `SPEC-049` | Browser-based web application check tools — stateful headless-Chromium browser connector in tool-gateway (Playwright) with a bounded `web.*` tool surface, server-side origin allowlist, skill-declared flows via two additive optional frontmatter keys, one HITL gate per mutating flow with a deviation guard, named credential sets, and screenshots in the existing evidence chain; no new policy actions, no new audit event types (eleventh R5 slice; drafted memo-free from the 2026-09-01/02 operator design discussion; extends SPEC-007/014/018/020/021/030) | `delivered` |
| `SPEC-050` | Browser tools expansion and samples reorganization — nine new `web.*` tools (`web.select`, `web.press_key`, `web.upload_file`, `web.evaluate` write tier; `web.extract`, `web.wait_for`, `web.hover`, `web.scroll`, `web.switch_frame` read tier), iframe traversal with cross-origin denial, HITL-gated JavaScript evaluation with result bounding and a defense-in-depth mutation guard, file upload with path allowlisting, `GATEWAY_BROWSER_UPLOAD_DIR` config, and a `samples/` top-level directory for self-contained tutorial content (twelfth R5 slice; extends SPEC-049) | `delivered` |
| `SPEC-051` | Browser flow HITL gate enforcement and password-reset sample reconciliation — completes SPEC-049 R-4 platform-side (one HITL gate per mutating browser flow: a session-scoped flow authority recorded on approval, each subsequent unlocked `web.*` write auto-signed under the approving card and still bounded by the gateway origin/risk_class/step-budget deviation guard, browser writes never auto-allowed, TTL-bounded via `AGENT_BROWSER_FLOW_APPROVAL_TTL`) and reconciles the password-reset sample to a single gate on the destructive "Confirm reset" click; makes that card flow-semantic (R-6 — the headline names the bound skill's title/description/target origin/risk class rather than a bare tool action, carried from the gateway flow binding through the kernel confirmation frame to the portal card, with the tool action kept as secondary detail); no new policy actions, no new audit event types, contracts unchanged (thirteenth R5 slice; tracked with ADR-0007/ADR-0008; extends SPEC-049/050) | `delivered` |
| `SPEC-052` | Skill content viewer — a read-only rendered/raw view of an ingested skill's `body` in the portal Skills table, via a new platform-gateway single-skill detail proxy (`GET /api/v1/skills/{skill_id:path}`) that reuses the existing `skills:read` action, skills-hub's existing `get_skill` endpoint (which already returns `body` and emits `skill_retrieved`), and the SPEC-045 rendered/raw preview pattern; the list payload omits `body` by contract, so the detail hop is required; no new policy actions, no new audit event types, no shared-contract change, skills-hub unchanged (fourteenth R5 slice; extends SPEC-014/019/045) | `delivered` |
| `SPEC-053` | Skill-declared step intent on the browser confirmation card — one additive optional `flow_intent` frontmatter key (≤ 200 chars, requires `web_target`) authoring what the flow's gated mutating step achieves, carried card-level on the existing SPEC-051 R-6 `flow_summary` path (skill record → gateway `bind_flow`/`FlowState` → `web.navigate` `data["flow"]` → kernel `FlowContext.summary()` → confirmation frame + durable record → portal card) and rendered as a plain-text decision line above the demoted DOM/technical detail; because SPEC-051 R-1 collapses a mutating flow to one gate, a single card-level intent maps 1:1 to the card (no brittle per-click matching); display-only and never a security input (deviation guard + SPEC-037 signed execution unchanged), skills that omit it render as today; no new policy actions, no new audit event types, additive contract change (`skill.schema.json` + the two `flow_summary` schemas, stream v9 → v10) touching the skills-hub ingestion/store path (fifteenth R5 slice; realizes the follow-up SPEC-051 R-6 deferred; extends SPEC-014/049/051) | `delivered` |
| `SPEC-054` | Action-level HITL approval and the change-request confirmation card — makes action approval first-class alongside flow approval: an explicit `approval_kind: flow \| action` discriminator on the confirmation frame + durable record (a card's kind is declared, not inferred from ambient session state — the structural fix behind the SPEC-051 R-6 headline-leak patch), ad-hoc browser writes on allowlisted origins park as per-action signed gates instead of being hard-denied `BROWSER_FLOW_NOT_BOUND` (extending ADR-0007 without reversing it), and every action card becomes a secret-masked change request promoting decision-relevant parameters into the approval intention (display-only, never in the signed `args_digest`); reuses the SPEC-020/021/030/037 mechanism, additive contract change only (sixteenth R5 slice; extends SPEC-020/021/030/037/049/050/051/053) | `delivered` |
| `SPEC-055` | Develop-as-you-go skill graduation — the graduation destination of the A→B→C program (implements ADR-0009): a durable authoring-trace store (dual-backend, separate from the 30-day execution sweep, secret-safe parameterized steps referencing `execution_id`/`confirm_id`) captured at the approval seam, an executable-flow skill class declaring `risk_class: write` decoupled from `web_target` with a machine-readable replay step list, deterministic human-merge graduation with blast-radius re-validation (one new `session:skill_graduate` action + `skill_graduated` audit event, never auto-publish), and one-gate secret-safe replay under SPEC-051's authority with credentials resolved from credential-set references; phases ADR-0007 rather than reversing it; plus **R-7** (folded post-approval from the SPEC-054 delivery review) hardening the change-request card's secret masking at the approval seam — fail-closed projection, no plaintext secret on the stream/render surface, signed `args_digest` preserved — the source-side complement of R-2's secret-safe capture (seventeenth R5 slice; depends on and extends SPEC-054 incl. R-3; extends SPEC-014/037/038/044/045/049/050/051) | `delivered` |
| `SPEC-056` | Studio — a dedicated skill-development workspace: split the operator-portal Chat entry into **Chat** (operation) and **Studio** (development) over one shared chat core parameterized by `mode`, backed by an additive `session_type` discriminator fixed at birth and **immutable** (no promotion or in-place conversion), so the shift-summary picker filters to operation sessions (closing a live unfiltered-picker defect), the authoring controls move to their right homes (**Design B** — draft stays in Chat, declare-target + graduate move to Studio, no in-place conversion — the Chat→Studio spawn bridge + composition are deferred to SPEC-057), and the role mapping is explicit (**Option A** — Studio is an authoring power held by operator/approver/platform-admin, developer/observer/auditor denied); shared security-critical core asserted identical across modes (blast-radius control), no new policy action, no new audit event type (eighteenth R5 slice; memo-free from the 2026-09-08→12 design discussion; extends SPEC-022/023/039/040/044/045/055) | `delivered` |
| `SPEC-057` | Skill composition — validated runbooks of single-target skills: a third additive skill `kind: composition` carrying an ordered `sub_skills[]` list of published single-target skills (no nesting, no duplicates, no own `web_target` or `steps`, capped by a new `SKILLS_COMPOSITION_MAX_SUB_SKILLS`) that realizes **ADR-0011** — a composition carries **no authority**, each sub-skill keeps its own gate through the existing `FlowContext` `(skill_id, origin)` identity guard, so multi-binding re-park needs **no new enforcement machinery** and adds no kernel trust state; **no control flow** (no interpreter, no branch/loop/conditional), delivery to the agent as grounded guidance rather than platform sequencing, and **not a transaction** (no rollback — report-and-stop, re-entry from a named step derived from existing `execution_records` signed receipts); no new policy action, no new audit event type, tool-gateway and the deviation guard untouched (nineteenth R5 slice; drafted from the composition-trust-model spike; roadmap row 346's **(b)** only — the (a) Chat→Studio spawn bridge and (c) assisted trace-extraction stay deferred to Phase 2; extends SPEC-014/049/050/051/054/055/056) | `delivered` |
| `SPEC-058` | HTTP service-check tools — the platform's first HTTP surface, and the most common operations task it cannot currently do: `http.get` (read tier) and `http.post` (write tier) in a new tool-gateway connector, both confined to a server-side origin allowlist that is deny-by-default with redirects halting when they leave it, because a model-supplied URL is `web.navigate`'s shape and **not** `adding-a-tool.md`'s config-base-URL `cmdb.lookup` shape (the inversion that makes this a spec rather than a connector); a fixed response projection whose header allowlist can never carry `set-cookie`, an upstream 4xx/5xx reported as a fact rather than a tool error, credentials by `credential_set` reference only with **no `headers` parameter**, and a curated `_cr_http_post` change-request card naming the target and fields — with one recorded divergence from SPEC-055 R-7's fail-closed masking for scalar body values, sound only because the no-headers/reference-only rule makes a credential-in-argument structurally impossible; `_redact_secret_query` extracted into a shared gateway helper with the `validate-secret-vocabulary` path constant moved in the same commit; no new policy action (policy is tier-based, so a read tool needs no bundle edit), no new audit event type, no contract change (twentieth R5 slice; motivated by `InventoryHealth`'s unfillable claim to complement "the API-level checks"; extends SPEC-007/009/021/049/050/054/055) | `delivered` |
| `SPEC-059` | `acme-admin` sample application and its single-target skill suite — the first sample to own a container image, replacing a tutorial target whose reset page "reports success for any user" with one that really mutates: a stand-alone FastAPI user-administration console (in-memory state, `replicas: 1` + `Recreate`, real credential validation, lock/unlock/reset mutations carrying `last_modified` and a monotonic `revision`, and a header-gated `/internal/reset-demo` the agent structurally cannot call because `http.post` ships no `headers` parameter) deployed by a new `make deploy-sample-app` that reuses the coordinated `IMAGE_TAG` and `mk/` fragments without joining `IMAGE_PRODUCTS`, keeping SPEC-050 R-11's tutorial→platform dependency direction; four skills demonstrating the approval model as a **0/0/1/1** card ladder across both surfaces (`http.get` health check — the repository's first card-free read-only skill; browser user-status; `http.post` lock/unlock parking one `action` card; bound browser password reset parking one `flow` card), where the read-only status skill exists to verify what the mutating one did; preserves the current target's six URL shapes and 28 element ids so the three shipped samples rebase as a retarget in a later slice, and names around `deploy-samples.sh`'s leaf-dir slug rule to avoid colliding with the existing `samples/password-reset-resetuserpassword` id; **no product code changes at all** (twenty-first R5 slice; depends on SPEC-058; supplies the single-target repertoire SPEC-057 composes; extends SPEC-049/050/051/053/054/055/056) | `delivered` |
| `SPEC-060` | Rebase the `web-checks` samples onto `acme-admin` — executes the retarget SPEC-059 R-2 engineered for and named as its follow-up slice: retire the static-mock `web-checks/password-reset` (superseded by the delivered `acme-admin/password-reset`, which already verifies via the JSON API), migrate `adhoc-password-reset` and `skill-graduation` under `samples/acme-admin/` retargeted from `browser-check-target` to the stateful `acme-admin`, and **upgrade** `skill-graduation` to verify both resets against real store state (`/api/users/{u}` `revision` + `password_changed_at`) rather than a static page — so one target that really mutates backs every browser tutorial and the approval-model triad (flow ↔ action ↔ author/graduate) is taught and verified end to end. Retires the `samples/web-checks/` category while **keeping `browser-check-target` shipped and untouched** for its platform consumers (the `InventoryHealth` runbook, `browser-check-demo.sh`, the `browser-dev` allowlist, and the `admin-portal`/`browser-check-target` credential sets); leaf directory names preserved so surviving skill ids stay stable and only `samples/password-reset-resetuserpassword` is intentionally removed. **No product code, contract, policy, or GitOps change** — a samples-and-docs slice (twenty-second R5 slice; executes the rebase SPEC-059 deferred; extends SPEC-050/051/054/055/059) | `delivered` |
| `SPEC-061` | Retire `browser-check-target`, `InventoryHealth`, and the orphaned credential sets — the cleanup SPEC-060 deferred: now that every browser tutorial runs against the stateful `acme-admin` console and the HTTP surface is shipped, the static `browser-check-target` mock, its one platform runbook (`InventoryHealth`, a `risk_class: write` browser health check whose "complements the API-level checks" promise is fulfilled elsewhere by `CheckServiceHealth`), and its dedicated `browser-check-demo.sh` e2e (not even in the `make e2e` list) are redundant with the `acme-admin` suite that *is* gated. Deletes the runbook + its skills-hub ConfigMap wiring, the three `browser-check-target-*` GitOps resources (leaving `browser-dev` as the browser *posture* profile permitting one origin, `acme-admin`), and the e2e script; drops the two now-orphaned dev credential sets (`browser-check-target`, and `admin-portal` which SPEC-060 already emptied of consumers); repoints five `products/agent-platform/tests/` fixtures (and one incidental `src/` comment example) off the retired origin string; and corrects the living docs. **No product behavior, contract, policy, or audit change** — test fixtures, one comment, and GitOps/config reduction only (twenty-third R5 slice; reverses SPEC-060's *keep* decision; extends SPEC-049/050/058/059/060) | `delivered` |
| `SPEC-062` | Secure password generation and delivery tools — a read-tier CSPRNG `secrets.generate_password` (never model-invented) bound to a single-source strength policy, plus a one-time, owner-scoped, server-mediated delivery handoff whose primary channel renders a portal **Copy password** button (value to clipboard, never a plaintext projection) and whose optional second channel emails it through a HITL-gated outbound tool; delivery is an extensible channel interface (Teams/Slack additive), the generated value rides no transcript/title/card/evidence frame, and one new `secret_delivered` audit event type plus a `secrets:deliver` action are introduced; the retrieval-vs-masking crux is resolved by redemption-on-click (ADR-0012) and the email-exfiltration risk by a recipient allowlist plus mandatory card confirmation (twenty-fourth R5 slice; target v0.41.0; extends SPEC-007/009/014/021/049/054/055/058) | `delivered` |
| `SPEC-063` | [Crash-safe execution and outcome reconciliation](SPEC-063-crash-safe-execution/spec.md) — approved durable pre-dispatch claims, explicit unknown outcomes, retained late results, and owner-scoped recovery; [failure-first implementation plan](SPEC-063-crash-safe-execution/plan.md) and [tasks](SPEC-063-crash-safe-execution/tasks.md) map 26 criteria and the 36-scenario [failure matrix](SPEC-063-crash-safe-execution/failure-test-matrix.md). Delivered 2026-09-26 as 0.43.0: the full root `make verify` is green (real-Postgres campaign 791 passed, exit 0; all product/portal/policy/version/secret gates and clean disposable teardown). [Delivery evidence](SPEC-063-crash-safe-execution/tasks.md#delivery-closure-evidence) retains every run, including the daemon-wedge attempts (V1/V5/V6) and the V4 test-only fixture fix. ADR-0013 and the approved plan remain frozen; no commit, tag, registry push, or shared deployment is claimed | `delivered` |
| `SPEC-064` | [Agent-driven context compression and goal-oriented pipeline adoption](SPEC-064-agentscope-compression-and-goal-pipeline/spec.md) — an adoption-gate spike resolving the two agentscope 2.0.8 surfaces (`CompressContext`, `pipeline.GoalPipeline`) that the v0.43.2 dependency refresh pinned but deliberately did not wire, deferred to SPEC-064 in the utilization audit. Scores each against SPEC-018's four-point adoption gate and lands a per-surface `adopt` / `keep out` verdict in a spike memo; conditional wiring (`CompressContext` behind an opt-in default-off knob; `GoalPipeline` expected keep-out against ADR-0011 / the governed execution path) binds only on an `adopt` verdict. [Provisional plan](SPEC-064-agentscope-compression-and-goal-pipeline/plan.md) and [tasks](SPEC-064-agentscope-compression-and-goal-pipeline/tasks.md) firm up after scope approval; no product code, contract, policy, or deployment change is authorized by the draft | `draft` |
