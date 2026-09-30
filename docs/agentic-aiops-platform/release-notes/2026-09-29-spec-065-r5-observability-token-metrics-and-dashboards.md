# v0.45.0 — R5 Observability: LLM Token Metrics, OTel Domain-Metric Push & Dashboards (SPEC-065)

Date: 2026-09-29
Release type: minor (the R5 observability slice — no new route, action, event
type, contract, schema, policy, or audit change; the only external side effect is
R-4's single authorized, billable, read-only model call, which mutates nothing and
is cleaned up)

## Summary

This release ships
[SPEC-065](../../specs/SPEC-065-r5-observability-token-cost-dashboards/spec.md)
(implementing [ADR-0014](../../adr/0014-domain-metrics-via-otel-push.md)), the
reliability/observability deliverable and the last R5 slice. It makes the
platform's own operation measurable end to end: a first-class **LLM token metric**,
every existing **domain metric pushed as an OpenTelemetry instrument** so it is
dashboard-visible without a Prometheus scraper, an **OpenObserve dashboard suite as
config-as-code**, and a **gated end-to-end live-check** reproducing the
observability spike §6 procedure. The slice is additive throughout — the always-on
`/metrics` pull surface stays the source of truth, and a deployment that does not
set `OTEL_ENABLED=true` is unchanged.

**Dollar cost is deliberately deferred.** Stage-0 found agentscope 2.0.8 exposes no
provider-derived dollar cost and the platform maintains no price table, so no
`agent_llm_cost_usd_total` is emitted. Token counts are the shipped currency; a
cost metric awaits a price-table decision.

R5 was formally closed at this version: four of the five named theme deliverables
shipped, and the fifth — stable API productization / external consumption — is
parked on the exploration backlog for want of a named second consumer (see the
[delivery roadmap](../delivery-roadmap.md)).

## What shipped

- **R-1 — Always-on LLM token metric.** `agent-platform` gains a
  `TokenUsageMiddleware` on the supported `on_model_call` hook, recording
  provider-reported usage as `agent_llm_tokens_total{provider,model,direction}`
  (`direction` ∈ {input, output, cache_input, cache_creation}; `model` bounded by
  the SPEC-026/027 catalog with an `unknown` sentinel). It is streaming-aware
  (reads usage off the terminal chunk), never estimated, records nothing when a
  provider returns no usage, and carries no session/user/request id. It is
  registered unconditionally beside the permission and evidence middleware.
- **R-2 — Domain metrics pushed as OTel instruments (ADR-0014).** Every
  `prometheus_client` domain family across all eight services is additionally
  mirrored to an OpenTelemetry instrument of the same name and bounded label set
  when `OTEL_ENABLED=true`, pushing over the existing OTLP pipeline into
  OpenObserve with no scraper. Strictly additive: the `/metrics` pull surface is
  unchanged and stays authoritative with push disabled. The mirror lives once in
  the parity-guarded `core/telemetry.py` and fails open.
- **R-3 — OpenObserve dashboards as config-as-code.** Three `version: 5` dashboard
  JSON files under `shared/platform-ops/dashboards/` — Service Health/RED, LLM
  Token Consumption, and Governance & Decision Chain (36 panels) — query the
  per-metric OpenObserve streams via PromQL. `validate_dashboards.py` is wired into
  `make verify` as `validate-dashboards` (the `kustomize build` analog) and
  cross-references every metric against the eight services' `OTEL_MIRROR_FAMILIES`
  (AST-parsed), so a renamed metric fails the gate; `apply-dashboards.sh` imports
  idempotently by `dashboardId`.
- **R-4 — Gated observability live-check.**
  `shared/platform-ops/e2e/observability-livecheck.sh` reproduces the spike §6
  procedure in three escalating legs: a mocked-I/O proof (default), a read-only
  cluster pre-flight, and a gated **billable** one-turn `deepseek` correlation by
  `trace_id`. The mocked leg runs in the ordinary test suite
  (`test_observability_livecheck.py`, 8 scenarios) and in the `make e2e` list; the
  paid leg is an explicitly gated, operator-authorized step.

## Changed

- **R-5 — Observability contract and living docs.**
  `shared/shared-contracts/observability-conventions.md` records the
  `agent_llm_tokens_total` family and its bounded labels, a "domain-metric OTel
  push" note under Two Surfaces, and a config-as-code dashboards pointer. The
  operator guide
  ([observability-dashboards.md](../../guides/observability-dashboards.md)) and the
  configuration reference Feature Activation Matrix document the dashboards and the
  R-4 live-check.

## Verification

- `make verify` green, including the new `validate-dashboards` gate (3 dashboards /
  36 panels cross-referenced against the eight services' mirrored families) and the
  mocked live-check leg (`test_observability_livecheck.py`, 8 scenarios).
- The R-4 gated **paid** leg was run and evidenced at delivery (2026-09-29): one
  read-only turn correlated in OpenObserve by `trace_id` to its LLM span and the
  `agent_llm_tokens_total` stream, then the throwaway session deleted — no
  mutation, no tool call, no HITL. This closed the slice.
- No route, action, contract, schema, audit-event-type, or execution-path change;
  `make validate-version` green at 0.45.0 across the eight products and the portal.

## Posture

Additive and default-safe. The `/metrics` pull surface remains the source of truth;
the OTel push mirror and the dashboards are opt-in (`OTEL_ENABLED=true`) and fail
open. Identity, policy, audit, and execution-safety semantics are unchanged. The
only external side effect anywhere in the slice is R-4's single authorized,
billable, read-only model call, which mutates nothing and is cleaned up.
