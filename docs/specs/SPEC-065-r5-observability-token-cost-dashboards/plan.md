# SPEC-065 Plan: R5 Observability — Token/Cost Emission, Domain-Metric Push, Dashboards, Gated Live-Check

> **Binding implementation plan** (SPEC-065 `approved` 2026-09-27). Authored at
> drafting time alongside `spec.md` (SPEC-064 same-session precedent) and made
> binding on approval. Nothing here is implemented yet; this document is design
> only. Implementation, commit/push, deployment, and the R-4 live paid model call
> are separate authorization boundaries not granted by approval alone.

## Approach

The slice realizes R5's "all core services ↔ dashboards and metrics" by building
**on** the proven-live OTLP push pipeline (spike §2.1), never re-plumbing it, and
by keeping the SPEC-005 two-surface contract intact. It groups into four
implementation stages that map to R-1..R-4, plus a documentation stage (R-5):

1. **Emit** (R-1) — an always-on `TokenUsageMiddleware` on the supported
   `on_model_call` hook records provider-reported token/cost into two new bounded
   `agent-platform` counters.
2. **Push** (R-2) — a mirror helper in the parity-guarded `core/telemetry.py`
   registers domain metrics as OTel instruments on the existing `MeterProvider`,
   so they reach OpenObserve with no scraper (ADR-0014).
3. **Consume** (R-3) — OpenObserve dashboards as config-as-code under
   `shared/platform-ops/`, with an import validation in the verify path.
4. **Gate** (R-4) — a repeatable live-check script reproducing spike §6, wired
   into the demo/e2e entrypoint, with a mocked-I/O test for CI and an explicitly
   authorized live paid leg.
5. **Document** (R-5) — conventions, operator guide, config reference, changelog,
   version, and bookkeeping surfaces.

Stages 1 and 2 are independently shippable and testable; 3 and 4 depend on 1+2
being deployed to a cluster with `OTEL_ENABLED=true`.

## Resolved At Plan Time

- **Capture point (R-1).** `MiddlewareBase.on_model_call` — the same supported
  hook the agentscope `TracingMiddleware` uses (`_trace.py:259-307`), reading
  `input_kwargs["current_model"]` for provider/model and `result.usage` for
  tokens/cost. No private agentscope surface; matches the SPEC-018 "move onto
  supported hooks" discipline and the SPEC-064 `on_compress_context` precedent.
- **Registration point (R-1).** `runtime_kernel._build_middlewares()`
  (`runtime_kernel.py:531-565`). The new middleware is appended to the **base**
  list beside `GatewayPermissionMiddleware` / `ToolEvidenceMiddleware`
  unconditionally (always-on per memo §7.5), *not* behind a `settings.` knob like
  the tracing/budget middlewares.
- **Metric home (R-1).** `products/agent-platform/src/agent_service/core/metrics.py`,
  following the existing `agent_model_discovery_*` precedent for a bounded
  `{provider,...}` label set and the module-level-object pattern (so repeated
  `create_app()` in tests never double-registers).
- **Streaming (R-1).** The platform chat path streams, so the middleware must wrap
  the `AsyncGenerator` and read `usage` off the terminal chunk — exactly what the
  tracing middleware's `_trace_async_generator_wrapper` does. A non-generator read
  would record zero; a test drives a multi-chunk generator to prove the terminal
  read.
- **Mirror mechanism (R-2).** A helper in the canonical `core/telemetry.py`.
  That module is pinned **byte-identical across all eight services** by
  `TelemetryParityTest` in `products/tool-gateway/tests/test_module_parity.py`, so
  the helper is defined once and replicated under guard. There is **no shared
  importable package** (`shared/shared-sdk` is a README placeholder; extraction is
  a parked backlog decision), so parity — not an import graph — enforces the single
  definition. Each service's own `core/metrics.py` (service-specific, not
  parity-guarded) calls the helper to register its families onto the meter.
- **MeterProvider reuse (R-2).** `setup_telemetry` already builds a
  `MeterProvider` with a `PeriodicExportingMetricReader(OTLPMetricExporter())`
  (`telemetry.py:99-102`). The helper obtains a meter from
  `opentelemetry.metrics.get_meter(...)` after that provider is set, so the domain
  instruments ride the existing periodic push. No new exporter, reader, or
  endpoint.
- **Init-order gotcha (R-2).** `app.py` calls `setup_metrics()` **before**
  `setup_telemetry()`, so at metric-registration time no real `MeterProvider` is
  set yet. Two safe options, decided at implementation: (a) invoke the mirror from
  inside `setup_telemetry` (after `set_meter_provider`) passing the family list
  each service already declares, or (b) rely on OTel's proxy-meter late binding
  (`get_meter` before `set_meter_provider` returns a `_ProxyMeter` whose instruments
  bind once the real provider is installed). Option (a) is preferred for explicit
  ordering; a test asserts a mirrored instrument actually records after
  `setup_telemetry` completes (not a silently-dropped pre-provider no-op).
- **Consumer path (R-2/R-3).** OTel-instrument push per ADR-0014; **no**
  Prometheus scraper, prometheus-operator, or Grafana is deployed.
- **Cost provenance (R-1, investigation).** The spike observed
  `gen_ai.usage.cost{,_input,_output}` on the live LLM span, i.e. agentscope
  already computes dollars. **Plan-time task:** read the locked agentscope 2.0.8
  source to confirm where it sources pricing (its model-price table / provider
  response) and record the finding in this plan before implementation, so R-1's
  cost is documented as a mirror of a provider-derived value and not an invented
  platform price table. If agentscope's cost is unavailable for a provider, R-1
  degrades to tokens-only (memo §7.4).
- **Mirrored-family enumeration (R-2, investigation).** Minimum operator-facing
  subset: R-1 `agent_llm_tokens_total` + `agent_llm_cost_usd_total`;
  `agent_chat_requests_total`, `agent_sessions_created_total`;
  `evidence_store_writes_total`, `evidence_frames_persisted_total`,
  `evidence_frames_truncated_total`, `audit_emits_total`;
  `agent_model_discovery_models` / `_refreshes_total`; the RED pair
  (`http_requests_total`, `http_request_duration_seconds`). Each service mirrors
  its own domain families the same way. The exact final list is fixed in this plan
  at implementation time; mirroring is additive so it can grow without a contract
  change.

## Design Per Requirement

### R-1: Token/cost emission

- **Affected files:** `core/metrics.py` (two new `Counter`s + `record_*` helpers),
  `services/kernel_middleware.py` (new `TokenUsageMiddleware(MiddlewareBase)`),
  `runtime_kernel.py` (register it in `_build_middlewares`), tests.
- **Counters:**
  - `agent_llm_tokens_total{provider,model,direction}` —
    `direction ∈ {input, output, cache_input, cache_creation}`.
  - `agent_llm_cost_usd_total{provider,model}`.
  - Both `_total`, `<service>_<noun>_<unit>` (`agent_` prefix per the conventions).
- **Model/provider resolution:** from `current_model` (a `ChatModelBase`), coerced
  to the bounded SPEC-026/027 catalog enum; an uncatalogued model → `model="unknown"`
  sentinel so cardinality stays bounded. No `session_id`/`user_id`/`request_id`.
- **Middleware logic:** resolve labels → `await next_handler(**input_kwargs)` →
  if `ChatResponse`, read `result.usage` (+ cost) and increment; if
  `AsyncGenerator`, return a wrapper that yields chunks and increments from the
  terminal chunk's `usage`. Usage-less response → record nothing.
- **Alternatives rejected:** a local tokenizer estimate (forbidden — fabrication
  risk); reading usage only on the non-streaming path (records zero on the real
  streaming chat path); an opt-in knob (memo §7.5 chose always-on; observation is
  not a mutation and needs no gate).

### R-2: Domain-metric OTel push

- **Affected files:** canonical `core/telemetry.py` (new mirror helper; replicated
  to all eight copies in the same commit), each service's `core/metrics.py` (call
  the helper for its families), tests.
- **Helper shape:** given the `prometheus_client` registry families (or an
  explicit list of name+labels+kind), create matching OTel instruments
  (`create_counter` / `create_gauge` / histogram as appropriate) on the meter from
  the already-set provider, and record into both surfaces from the existing
  `record_*` call sites (the prometheus increment stays; the OTel increment is
  added beside it).
- **Decoupling:** the helper is a no-op when `OTEL_ENABLED=false` (no provider is
  set), so `/metrics` is unaffected and the SPEC-005 always-on guarantee holds.
- **Parity:** because `telemetry.py` must stay byte-identical, the helper cannot
  reference any service-specific metric name; it takes the family list as an
  argument supplied by each service's own `metrics.py`. The `TelemetryParityTest`
  must pass unchanged after the edit.
- **Alternatives rejected:** deploying a scraper (ADR-0014); emitting domain
  metrics *only* as OTel instruments (breaks the always-on pull surface); putting
  the helper in a shared package (none exists; extraction is parked).

### R-3: Dashboards

- **Affected files:** `shared/platform-ops/dashboards/` (new; OpenObserve-importable
  JSON) + an apply script + a render/import validation wired into `make verify`
  (analogous to `kustomize build` for overlays) + operator-guide section.
- **Panels:** (a) tokens over time by `{provider,model,direction}`; (b) cost over
  time by `{provider,model}`; (c) RED (`http_requests_total` rate,
  `http_request_duration_seconds` p50/p95); (d) a governance/decision-chain view
  from already-emitted domain/audit signals (e.g. `audit_emits_total{result}`,
  evidence counters).
- **Query target:** the OpenObserve **metrics** stream (`FROM "default"` with
  `stream_type=metrics`, per the spike's stream-naming note).
- **Alternatives rejected:** click-built dashboards living only in the cluster
  (not reproducible/reviewable, rots silently); Grafana (new infra, ADR-0014).

### R-4: Live-check

- **Affected files:** `shared/platform-ops/` live-check script (reproduces spike
  §6) + a mocked-I/O test in the ordinary suite + wiring into the demo/e2e
  entrypoint (`make` list) so it cannot be skipped silently.
- **Live leg:** one read-only chat turn against external `deepseek`
  (`deepseek-v4-flash`), authorized billable (memo §7.3); asserts
  `agent_llm_tokens_total` on `/metrics` and the correlated metric/trace in
  OpenObserve by `trace_id`; deletes the test session; no mutation/tool/HITL.
- **Separation:** mocked execution validates script logic in CI; the paid live leg
  is an explicit operator-authorized step, matching how other live demos separate
  mocked from live runs.

### R-5: Docs

- Update `observability-conventions.md` (metric family + labels; the additive
  domain-metric OTel-push note under Two Surfaces; dashboards-as-config pointer),
  operator guide (dashboards + live-check), config reference / Feature Activation
  Matrix (dashboard visibility depends on `OTEL_ENABLED`), `CHANGELOG.md`,
  `VERSION` + lockstep files at delivery, `docs/specs/README.md`, delivery-roadmap
  backlog row, and flip ADR-0014 to `accepted`.

## Sequencing And Dependencies

1. **Plan-time investigations** (agentscope cost provenance; mirrored-family
   enumeration) — depends on nothing; recorded in this plan before code.
2. **R-1 emit** — depends on (1). Independently testable; lands the counters on
   `/metrics`.
3. **R-2 push** — depends on (2) for the token family to mirror (and can mirror
   pre-existing families in parallel). Must keep `TelemetryParityTest` green.
4. **Deploy to dev cluster** with `OTEL_ENABLED=true` — depends on (2)+(3).
5. **R-3 dashboards** — depends on (4) (needs the metrics stream populated).
6. **R-4 live-check** — depends on (4)+(5); the authorized paid leg last.
7. **R-5 docs + version bump + delivery gate** — depends on all above.

## Test Strategy

- **Unit (R-1):** non-streaming usage recorded with correct labels; streaming
  terminal-chunk usage recorded (naive read fails); absent usage records nothing;
  absent cost → tokens-only; `direction` enum bounded; unknown model → sentinel;
  no forbidden labels; middleware registered unconditionally.
- **Unit (R-2):** parity of name+labels between the prometheus family and the OTel
  instrument; `OTEL_ENABLED=false` → no instrument, `/metrics` unchanged;
  exporter error fails open; `TelemetryParityTest` still passes byte-identical.
- **Contract:** no schema change; the existing observability/contract tests stay
  green (assert `agent-stream-event.schema.json` untouched).
- **Validation (R-3):** dashboard JSON import/render check in `make verify`.
- **Live/integration (R-4):** mocked-I/O script test in CI; the gated paid live leg
  reproduces spike §6 end to end on the dev cluster.
- **Gate:** full root `make verify` green (every product suite incl. the parity
  guard, every overlay render, policy rules, version lockstep, secret vocabulary).

## Rollout And Migration

- **Config/deploy:** R-1 is always-on code (no knob). R-2/R-3 visibility requires
  `OTEL_ENABLED=true` (already set in `dev-k8s`). Dashboards applied via the
  platform-ops script. No DB migration, no contract change.
- **Backward compatibility:** purely additive — new counters and a mirror; the
  `/metrics` pull surface and all existing families are unchanged. A cluster with
  OTel off behaves exactly as before (minus two idle counter families).
- **Rollback:** revert the middleware registration (R-1) and/or stop calling the
  mirror helper (R-2); dashboards/live-check are platform-ops artifacts removable
  without a product redeploy. No state to migrate back.
- **Cost/safety:** the only external side effect is R-4's single authorized,
  billable, read-only model call, cleaned up afterward.
