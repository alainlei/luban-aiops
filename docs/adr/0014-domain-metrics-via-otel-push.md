# ADR-0014: Domain Metrics Reach Dashboards Via OTel-Instrument Push, Not A Prometheus Scraper

## Status

`accepted`

- date: 2026-09-27
- accepted: 2026-09-27
- deciders: workspace operator, through explicit SPEC-065 scope approval
- related specs: [SPEC-065](../specs/SPEC-065-r5-observability-token-cost-dashboards/spec.md)
  (R5 observability — token emission [cost deferred], domain-metric push,
  dashboards, gated live-check); [SPEC-005](../specs/SPEC-005-observability-baseline/spec.md)
  (observability baseline — the two-surface contract this builds on)
- evidence: `docs/workspace/observability-metrics-dashboards-spike.md`
  (2026-09-27), operator decision §7.1
- scope: records the approved architectural trade-off (OTel-instrument push, no
  Prometheus scraper); implementation details remain in the SPEC-065
  [plan](../specs/SPEC-065-r5-observability-token-cost-dashboards/plan.md).
  Acceptance is not a claim of shipped behavior or authorization for
  deployment or the R-4 live paid model call.

## Context

SPEC-005 established two deliberately decoupled observability surfaces per
service: an always-on `prometheus_client` `/metrics` pull endpoint (RED plus a
rich set of domain counters) and an opt-in OTLP **push** pipeline (traces,
metrics, mirrored logs) gated by `OTEL_ENABLED`. The conventions doc closes with
a hard boundary: *"Services only expose `/metrics` and push OTLP. Scraping
infrastructure, metrics/traces/logs storage, dashboards, and alerting are
platform-ops concerns outside the service contract."*

The 2026-09-27 spike live-inspected the running `dev-luban-aiops` cluster and
found the consequence of that boundary: OpenObserve is deployed and the OTLP
push is live, but the cluster runs **no Prometheus, no Grafana, and no
prometheus-operator** (no `ServiceMonitor`/`PodMonitor` CRDs). So the
`prometheus_client` domain counters — including the new
`agent_llm_tokens_total` family SPEC-065 R-1 adds —
have **no scraper and no dashboard**: they are a curl-only debug surface.
OpenObserve receives only what the OTLP push sends (the OTel auto-instrumentation
HTTP metrics, traces, mirrored logs); the two metric worlds never overlap.

R5 promises "all core services ↔ dashboards and metrics." Realizing it forces one
architectural choice: how does a domain metric get from a service to a dashboard?

## Decision

**Domain metrics reach the dashboard by being additionally emitted as
OpenTelemetry instruments that push over the existing OTLP metric pipeline into
OpenObserve. No Prometheus scraper is deployed.**

1. Each service's `MeterProvider` (already constructed by `setup_telemetry` when
   `OTEL_ENABLED`) also carries OTel counters/gauges mirroring the
   `prometheus_client` domain metrics, so the domain signal pushes over the pipe
   proven live in the spike (§2.1) with **zero new cluster infrastructure**.
2. The two SPEC-005 surfaces stay decoupled and independently correct: the
   `/metrics` pull endpoint remains the always-on, collector-independent debug
   surface and is unchanged; the OTel mirror is additive and gated by the same
   `OTEL_ENABLED` switch, failing open with the rest of the pipeline.
3. The mirror is a **push of the same bounded-label metric**, not a second
   definition: identical name, identical bounded enum labels, no new
   high-cardinality dimension. Where a metric exists on both surfaces it must
   agree.
4. Dashboards and the gated live-check consume the OpenObserve **metrics**
   stream (`agent_llm_tokens_total` and the mirrored
   domain families), queried the same way the spike queried logs/traces.

## Alternatives Considered

- **Deploy a Prometheus scraper (+ prometheus-operator) and have OpenObserve or
  Grafana remote-read `/metrics`** — rejected: adds cluster infrastructure the
  platform has deliberately never carried; the conventions doc names scraping a
  platform-ops concern *outside* the service contract, so wiring it would either
  breach that boundary from the product side or require a separate ops component
  with its own lifecycle; and it duplicates a pipe (OTLP push) that is already
  live and proven. It also forks the metric world into pull-only domain counters
  plus push-only auto-instrumentation, which is the exact split this ADR closes.
- **Abandon `prometheus_client` and emit domain metrics only as OTel
  instruments** — rejected: breaks the SPEC-005 always-on, works-with-no-backend
  guarantee. `/metrics` must stay functional with `OTEL_ENABLED=false` and no
  collector reachable; the pull surface is the debug floor and the contract tests
  bind to it. The mirror is additive by design.
- **Query token usage from raw trace spans instead of a metric** — rejected as
  the operator-facing answer: the spike confirmed token usage already lands on LLM
  spans as GenAI attributes, but per-span SQL is not aggregation and hides
  exactly the "tokens by model this week" signal a dashboard surfaces. The span
  data stays (it is the provenance), but a metric is the queryable, aggregatable
  operator surface.

## Consequences

- **No new infrastructure.** Realizing R5 dashboards needs no scraper, no
  prometheus-operator, no Grafana; it reuses the OTLP metric pipeline and the
  in-cluster OpenObserve already running.
- **Consistency with the contract.** The "services only push OTLP; scraping is
  platform-ops" boundary is preserved and, for the first time, actually exercised
  on the metrics signal — the domain counters become dashboard-visible without a
  pull consumer.
- **Accepted trade-off — double emission.** Every mirrored domain metric is
  written twice (once to the `prometheus_client` registry, once to an OTel
  instrument). This is a small, bounded CPU/alloc cost on an observation path and
  is accepted in exchange for keeping the always-on pull surface intact. The two
  must be kept in agreement; drift is a review defect.
- **Accepted trade-off — push-only visibility.** With no scraper, a domain metric
  is dashboard-visible **only** when `OTEL_ENABLED` is true and the backend is
  reachable. That is the same posture the OTLP trace/log pipeline already has and
  fails open identically; `/metrics` remains the fallback for a cluster with OTel
  off.
- **Follow-up work triggered:** SPEC-065 R-2 implements the mirror as a helper in
  the canonical `core/telemetry.py` — the module the existing `TelemetryParityTest`
  drift guard already pins byte-identical across all eight services, so the
  mechanism is defined once and replicated under guard rather than re-invented per
  service (there is no shared importable Python package; extraction stays a parked
  backlog decision); R-3 ships the OpenObserve dashboards as config-as-code; R-4
  adds the gated live-check. The broader "should *every* existing domain counter be
  mirrored, or only the operator-facing subset" question is scoped inside SPEC-065
  R-2 rather than deferred, since the mirror is cheap and additive.
