# SPEC-065: R5 Observability — Token/Cost Emission, Domain-Metric Push, Dashboards, And A Gated Live-Check

## Status

- status: `approved`
- owner: luban-platform-team
- created: 2026-09-27
- approved: 2026-09-27
- release slice: R5 — hardening and external consumption ("all core services ↔
  dashboards and metrics"; "stronger reliability and observability" — the one R5
  theme deliverable with no spec yet)
- target version: v0.45.0
- related ADRs: [ADR-0014](../../adr/0014-domain-metrics-via-otel-push.md)
  (domain metrics reach dashboards via OTel-instrument push, not a Prometheus
  scraper — `accepted` on this spec's approval, 2026-09-27);
  [ADR-0008](../../adr/0008-spec-delivery-traceability-gate.md) (every `R-x`
  criterion maps to an asserting test; a shipped demo is exercised by its own
  script in the verification path — the discipline R-4's live-check follows)
- lineage: promoted from the
  [observability metrics & dashboards spike](../../workspace/observability-metrics-dashboards-spike.md)
  (2026-09-27), whose §7 records the five operator decisions this spec implements;
  builds on SPEC-005 (observability baseline — the two-surface `/metrics` + OTLP
  contract), SPEC-018 (kernel middleware alignment — the supported-hook discipline
  R-1 follows), SPEC-026/027 (the bounded model catalog R-1's `model` label draws
  from), and SPEC-013 (durable audit — where per-turn/per-session attribution
  belongs instead of metrics)

> Approval note (SDD discipline): the full scaffold (`spec.md` + `plan.md` +
> `tasks.md`) was authored together at drafting time per the SPEC-064 same-session
> precedent. The scope decisions were already resolved by the operator in the spike
> memo §7 (2026-09-27), so this spec was decision-complete at drafting; the operator
> reviewed and advanced it to `approved` on 2026-09-27, which also flips
> [ADR-0014](../../adr/0014-domain-metrics-via-otel-push.md) from `proposed` to
> `accepted`. `plan.md` and `tasks.md` are now the binding implementation plan and
> derived task list. Approval authorizes implementation; it is a separate
> authorization boundary from commit/push, deployment, and the R-4 live paid model
> call. This approval step is documentation-only: no runtime change, no deployment,
> no live model call, and no version bump are part of it.

## Summary

Close the last untouched R5 deliverable — "all core services ↔ dashboards and
metrics." The spike proved OpenObserve is already integrated and live and that
token-by-model usage already reaches it as per-span GenAI trace attributes, but
that **no aggregated token metric exists, no scraper runs, and nothing is on
any dashboard**. This spec (1) emits a first-class, always-on LLM **token**
metric captured from provider-reported usage via a supported
`on_model_call` middleware, (2) makes the platform's domain metrics
**dashboard-visible** by additionally pushing them as OTel instruments over the
existing OTLP pipeline (no new infrastructure), (3) ships an **OpenObserve
dashboard suite** as config-as-code, and (4) gates the whole path with a
**repeatable live-check script** so observability is verified like every other
shipped demo.

## Motivation

- **What exists today.** SPEC-005 gives every service two decoupled surfaces: an
  always-on `prometheus_client` `/metrics` pull endpoint and an opt-in OTLP push.
  The 2026-09-27 spike live-verified that the push pipeline is up
  (`OTEL_ENABLED=true`, `AGENTSCOPE_KERNEL_TRACING=true` in the running
  `agent-service` pod; the full OpenObserve HA stack in the `openobserve`
  namespace) and that logs, traces, and OTel auto-instrumentation HTTP metrics
  from all seven Python services are landing right now.
- **The gap.** Three concrete holes the spike measured:
  1. **No token metric.** `/metrics` carries RED plus rich domain counters
     (sessions, chat, session-store, agent-state, evidence, audit emits, model
     discovery) but `grep -iE 'token|llm|usage'` returns nothing. Token-by-model
     reaches OpenObserve only as per-span `gen_ai.usage.*` attributes — queryable
     by raw-span SQL, but **not aggregated and on no dashboard**, so "how many
     tokens did model X consume this week" is not operator-answerable.
  2. **No consumer for any domain metric.** The dev cluster runs no
     Prometheus/Grafana and no prometheus-operator (no `ServiceMonitor`/
     `PodMonitor` CRDs), so the `prometheus_client` domain counters are curl-only.
     OpenObserve receives only what OTLP push sends; the pull and push metric
     worlds never overlap.
  3. **No dashboard, no gated live-check.** R5's "dashboards and metrics" promise
     is genuinely un-started because the conventions doc (correctly) names
     scraping/storage/dashboards a platform-ops concern outside the service
     contract — so it needs an explicit slice to realize it without breaching
     that boundary.
- **Evidence that makes it concrete.** The spike's one authorized live
  `deepseek-v4-flash` turn showed a trivial one-word reply still consumed **5,352
  input tokens** (system prompt + the ~30-tool schema, 5,120 cache-served) for
  **1 output token**. That is precisely the per-model token insight an aggregated
  metric + dashboard surfaces and that raw per-span querying hides.
  - **Cost correction (Stage-0, 2026-09-27).** The spike §6.5 aside that the same
    span "carries `gen_ai.usage.cost` (dollars)" is **not supported** by the locked
    agentscope 2.0.8 source: `ChatUsage` exposes tokens + latency only, the tracing
    span attributes define **no** `gen_ai.usage.cost*`, and the extractor writes
    tokens only (the sole agentscope "cost" is `_budget.py`'s synthetic
    weighted-token budget, not dollars). Any dollar value seen on a live span could
    only have arrived via the provider-specific free-form `metadata` dict —
    undocumented and not guaranteed across providers, so not a reliable first-class
    source. The platform also maintains no price table. R-1 therefore ships
    **tokens-only**; dollar cost is **deferred** to a follow-up (see the R-1 scope
    note and `plan.md` "Cost provenance"). No dollar figure is fabricated here.
- **Why now.** It is the sole R5 theme deliverable with no spec; the ingestion
  pipe it builds on is proven live; and the capture point is the identical
  supported-hook pattern SPEC-018 established and the tracing middleware already
  uses. The four-point adoption gate is cleared trivially (metrics observe a call
  the kernel already makes; no tool, no identity edge, no contract change).

## Requirements

Each requirement is stable once this spec is `approved` and carries testable
acceptance criteria. Requirement IDs use `R-x` and are referenced by `tasks.md`.

### R-1: First-class LLM token emission (cost deferred)

Add an always-on `TokenUsageMiddleware(MiddlewareBase)` on the supported
`on_model_call` hook that records the provider-reported usage of every model call
as a bounded Prometheus counter in `agent-platform`'s `core/metrics.py`:
`agent_llm_tokens_total{provider,model,direction}`. Usage is read from the
kernel's `ChatResponse.usage` only — never estimated — and the middleware is
streaming-aware so the platform's streaming chat path records real counts rather
than zero.

> **Scope note — cost deferred (Stage-0 finding, 2026-09-27).** The Stage-0
> investigation proved agentscope 2.0.8 exposes **no** provider-derived dollar
> cost (`ChatUsage` is tokens + `time`; no `gen_ai.usage.cost*` span attribute;
> `_budget.py`'s "cost" is a synthetic token weight) and the platform has no price
> table. Emitting `agent_llm_cost_usd_total` would therefore require inventing a
> per-model price table — exactly what this spec forbids. Per operator decision
> (2026-09-27) R-1 ships **tokens-only**; a dollar-cost metric is deferred to a
> separate follow-up that would add an explicit, reviewed price table labelled as
> an estimate. Recorded in `plan.md` "Cost provenance".

Acceptance criteria:

- A non-streaming `ChatResponse` with a populated `usage` increments
  `agent_llm_tokens_total` by the provider-reported `input_tokens` /
  `output_tokens` (and `cache_input` / `cache_creation` when non-zero) under the
  correct `{provider,model,direction}` labels.
- A **streaming** response (`AsyncGenerator[ChatResponse, None]`) records the
  same counts from the terminal chunk's `usage` — asserted by a test that drives
  a multi-chunk generator whose usage lands only on the final chunk (the naive
  non-generator read would record zero and must fail).
- `direction` is a bounded enum `{input, output, cache_input, cache_creation}`;
  no other value is ever emitted.
- `model` is a **bounded** value drawn from the SPEC-026/027 model catalog (not
  free text); `provider` matches the bounded label already used by
  `agent_model_discovery_*`. An unknown/uncatalogued model is coerced to a
  bounded sentinel (e.g. `model="unknown"`) rather than emitted as raw text, so
  cardinality stays bounded.
- **No** `session_id`, `user_id`, or `request_id` label appears on either counter
  (asserted by a test inspecting the emitted label set).
- When a provider returns **no** `usage`, the middleware records **nothing** — it
  never synthesizes a zero-fill estimate. Asserted by a test with a usage-less
  response.
- The middleware is registered unconditionally in
  `runtime_kernel._build_middlewares()` (always-on; no opt-in knob), beside
  `GatewayPermissionMiddleware` and `ToolEvidenceMiddleware`, and executes no
  tool and carries no identity.
- The counter family appears on `GET /metrics` with `_total` suffixes and
  `<service>_<noun>_<unit>` naming per `observability-conventions.md`.
- **No cost metric is emitted in this slice.** `agent_llm_cost_usd_total` is
  deferred (see the scope note above); a test asserts the middleware emits **no**
  cost counter, so no fabricated dollar value can appear on `/metrics`.

### R-2: Domain metrics pushed as OTel instruments

Make the platform's domain metrics dashboard-visible without deploying a
scraper: additionally emit them as OpenTelemetry instruments on the `MeterProvider`
`setup_telemetry` already builds, so they push over the existing OTLP metric
pipeline into OpenObserve (ADR-0014). The always-on `/metrics` pull surface is
unchanged and stays functional with `OTEL_ENABLED=false`; the OTel mirror is
additive, gated by the same switch, and fails open.

Acceptance criteria:

- With `OTEL_ENABLED=true`, each mirrored domain metric is emitted both to the
  `prometheus_client` registry and to an OTel instrument of the **same name and
  same bounded label set**; a test asserts name/label parity between the two
  surfaces (no second definition, no added high-cardinality dimension).
- With `OTEL_ENABLED=false`, no OTel instrument is created and no push occurs,
  while `/metrics` still serves the identical domain families (the SPEC-005
  decoupling and always-on guarantee hold) — asserted by a test.
- The mirror helper is defined **once** in the canonical `core/telemetry.py`,
  which the existing `TelemetryParityTest` drift guard
  (`products/tool-gateway/tests/test_module_parity.py`) already pins
  byte-identical across all eight services — so the mechanism is replicated under
  guard, not re-invented per service. There is **no shared importable Python
  package** (`shared/shared-sdk` is a placeholder; extraction is deferred by a
  parked backlog decision), so parity — not an import graph — is the single-
  definition enforcement. Each service's own `core/metrics.py` (service-specific,
  **not** parity-guarded) registers its families onto the meter via that helper.
  A test asserts the helper is invoked from the parity-guarded `telemetry.py` and
  that the guard still passes after the change.
- The R-1 `agent_llm_tokens_total` counter is among the mirrored families, so it
  pushes into OpenObserve.
- The push fails open: an unreachable/misconfigured backend never raises into the
  request path (mirrors the existing `setup_telemetry` guard) — asserted by a test
  that forces an exporter error.
- The set of mirrored families is enumerated explicitly in `plan.md` (the
  operator-facing subset at minimum: the R-1 token family, chat/session
  counters, evidence and audit-emit counters, model-discovery gauges); mirroring
  is additive so the enumeration can grow without a contract change.

### R-3: OpenObserve dashboard suite (config-as-code)

Ship at least one OpenObserve dashboard that surfaces token consumption by
model/provider over time, plus the RED and decision-chain views the audit work
already produces, as **version-controlled config-as-code** (not click-built state
that lives only in the cluster) so it is reproducible and reviewable. (A cost
panel is deferred together with the R-1 cost metric.)

Acceptance criteria:

- A dashboard definition is committed under the platform-ops GitOps tree
  (e.g. `shared/platform-ops/`) in a format OpenObserve can import, and a
  documented, repeatable apply step loads it.
- The token dashboard queries the OpenObserve **metrics** stream for
  `agent_llm_tokens_total` broken down by `{provider,model,direction}`, over a
  selectable time range.
- The dashboard suite includes the RED view (`http_requests_total` /
  `http_request_duration_seconds`) and at least one governance/decision-chain
  view sourced from already-emitted domain metrics or audit signals.
- A render/import validation runs in the verification path (the dashboard JSON is
  well-formed and importable), analogous to `kustomize build` for overlays — so
  the artifact cannot silently rot.
- The dashboards are documented in the operator guide with how to reach them and
  what each panel means.

### R-4: Gated observability live-check

Add a repeatable live-check script that exercises the end-to-end observability
path — the §6 spike procedure — and wire it into the verification path so
observability is gated like the other shipped demos (ADR-0008 spirit).

Acceptance criteria:

- A committed script reproduces the spike procedure: assert cluster + config
  (`OTEL_ENABLED=true`, `AGENTSCOPE_KERNEL_TRACING=true`), inspect `/metrics` for
  `agent_llm_tokens_total` after a turn, port-forward OpenObserve, and query the
  `metrics`/`traces` streams for the emitted token signal correlated by
  `trace_id`.
- The script drives **one** read-only chat turn to produce a real LLM span and
  metric sample. Per operator decision §7.3 the live leg runs against the
  **external `deepseek` provider** (`deepseek-v4-flash`, an authorized billable
  call), not the local Ollama; the script makes the paid-call nature explicit and
  cleans up the test session afterward (no mutation, no tool call, no HITL card).
- The script is idempotent and safe to re-run, fails loudly on a missing signal,
  and is invoked from the same entrypoint the other demos use (e.g. the `make`
  demo/e2e list) so it cannot be skipped silently.
- A mocked-I/O execution of the script (no live paid call) runs in the ordinary
  test suite to validate its logic; the live paid leg is an explicitly gated,
  operator-authorized step, matching how other live demos separate mocked from
  live execution.

### R-5: Contract and living-doc updates

Record the new metric family, the consumer path, and the dashboard/live-check in
the living state docs so documentation cannot drift from the shipped behavior.

Acceptance criteria:

- `shared/shared-contracts/observability-conventions.md` gains: the
  `agent_llm_tokens_total` family and its bounded labels in the naming/labels
  sections; a short "domain-metric OTel push" note
  under the two-surfaces section stating the mirror is additive and push-only
  visibility requires `OTEL_ENABLED` (ADR-0014); and a pointer that dashboards
  live as config-as-code under platform-ops.
- The operator guide documents the dashboards (R-3) and the live-check (R-4).
- The config reference records any new knob (none expected — R-1 is always-on)
  and the Feature Activation Matrix reflects the OTel-push dependency for
  dashboard visibility.
- `CHANGELOG.md` gains an entry referencing SPEC-065; `VERSION` and the lockstep
  version files bump to v0.45.0 at delivery.
- `docs/specs/README.md` and the delivery-roadmap Exploration Backlog row are
  updated through the draft → approved → delivered lifecycle.

## Non-Goals

- **No Prometheus scraper, prometheus-operator, Grafana, or Thanos/Victoria.**
  ADR-0014 rejects the pull-consumer path; nothing in this spec deploys one.
- **No per-turn or per-session cost attribution in metrics.** High-cardinality
  attribution (which session/user cost what) belongs in the durable audit record
  (SPEC-013), not in a metric label; this spec explicitly forbids those labels.
- **No local tokenizer estimation.** The platform never computes token counts
  itself; it mirrors provider-reported usage or records nothing.
- **No platform-owned price table, and no dollar-cost metric in this slice.**
  Stage-0 proved agentscope 2.0.8 exposes no provider-derived cost and the
  platform has no price table, so R-1 ships tokens-only; a cost metric is deferred
  to a follow-up that would introduce an explicit, reviewed price table labelled as
  an estimate. This slice fabricates no dollars.
- **No change to the agent-stream-event contract, policy actions, audit event
  types, or the trust model.** R-1 observes a call the kernel already makes; R-2
  is additive emission; R-3/R-4 are platform-ops artifacts.
- **Re-plumbing the OTLP pipeline is out of scope** — it is proven live and is
  built on, not rebuilt.
- **Alerting** on the new metrics is out of scope for this slice (a follow-on
  platform-ops concern); this spec delivers emission, push, dashboards, and a
  live-check.

## Impact

- products touched:
  - `products/agent-platform/` — `core/metrics.py` (R-1 counters, R-2 mirror
    wiring), `core/telemetry.py` (R-2 shared OTel-instrument bridge),
    `services/kernel_middleware.py` + `runtime_kernel.py` (R-1
    `TokenUsageMiddleware` and its registration), tests.
  - The other seven services' `core/metrics.py` / `core/telemetry.py` — R-2 mirror
    for their domain families via the shared bridge (additive; no behavior change).
- shared / platform-ops touched:
  - `shared/shared-contracts/observability-conventions.md` (R-5).
  - `shared/platform-ops/` — OpenObserve dashboard config-as-code + apply step
    (R-3); the gated live-check script (R-4).
- contracts touched: none. `agent-stream-event.schema.json` and all
  `shared-contracts` JSON schemas are unchanged; the observability-conventions
  markdown is updated but is a conventions doc, not a validated schema.
- identity / policy / audit / execution safety impact: **none.** No new identity
  edge, no new policy action, no new audit event type, no execution surface. R-1
  clears the SPEC-018 four-point adoption gate (spike §4). The only external side
  effect anywhere in the spec is R-4's single authorized, billable, read-only
  model call, which mutates nothing and is cleaned up.
- living state docs to update on delivery: `observability-conventions.md`, the
  operator guide, the config reference / Feature Activation Matrix, root
  `README.md` if it enumerates observability surfaces, `CHANGELOG.md`, `VERSION`
  + lockstep version files, `docs/specs/README.md`, and the delivery-roadmap
  Exploration Backlog row.

## Open Questions

None blocking. The five scope questions the spike raised are resolved by operator
decision (memo §7, 2026-09-27):

- OQ-1 (consumer path) → **OTel-instrument push, no scraper** (§7.1; ADR-0014).
- OQ-2 (first-spec scope) → **the full R5 observability theme**, planned as
  carefully separated, separately verifiable tasks (§7.2) — hence R-1..R-5.
- OQ-3 (live chat-turn leg) → **external `deepseek` provider**, authorized paid
  call (§7.3) — hence R-4.
- OQ-4 (cost) → originally "emit both tokens and dollars" (§7.4), **superseded by
  the Stage-0 finding** (2026-09-27): agentscope 2.0.8 exposes no provider-derived
  cost and the platform has no price table, so R-1 ships **tokens-only** and the
  dollar-cost metric is **deferred** to a follow-up. No `agent_llm_cost_usd_total`
  in this slice.
- OQ-5 (middleware knob) → **always-on**, pure observation, no opt-in (§7.5) —
  hence R-1's unconditional registration.

Of the two plan-time investigations, the cost-provenance one is **complete**
(recorded in `plan.md`): agentscope 2.0.8 sources no pricing, which is exactly what
drove the cost-deferral above. The mirrored-family enumeration for R-2 is fixed in
`plan.md` at implementation time.

## Changelog

- 2026-09-27: created as `draft` from the observability metrics & dashboards spike
  (memo §7 operator decisions); full scaffold (`spec.md` + `plan.md` + `tasks.md`)
  authored together per the SPEC-064 same-session precedent, plan/tasks provisional
  pending scope approval; ADR-0014 recorded as `proposed`.
- 2026-09-27: reviewed and advanced to `approved` (all five Open Questions already
  resolved by memo §7; no scope change required). ADR-0014 flipped `proposed` →
  `accepted`. `plan.md` / `tasks.md` provisional banners lifted; they are now the
  binding implementation plan and task list. Implementation, commit/push,
  deployment, and the R-4 live paid leg remain separate authorization boundaries.
- 2026-09-27: **scope refined during Stage-0 implementation** — the cost-provenance
  investigation proved agentscope 2.0.8 exposes **no** provider-derived dollar cost
  (`ChatUsage` = tokens + `time`; no `gen_ai.usage.cost*` span attribute;
  `_budget.py`'s "cost" is a synthetic token weight) and the platform has no price
  table, contradicting spike §6.5. Per operator decision, R-1 ships **tokens-only**
  and `agent_llm_cost_usd_total` is **deferred** to a follow-up (an explicit,
  reviewed price table labelled as an estimate). Cost references updated across
  `spec.md`, `plan.md`, `tasks.md`, ADR-0014, and the spike memo; the token path,
  R-2 push, R-3 token/RED/decision-chain dashboards, and R-4 live-check are
  unchanged. Spec stays `approved` (a scope refinement within the approved theme,
  not a re-open).
