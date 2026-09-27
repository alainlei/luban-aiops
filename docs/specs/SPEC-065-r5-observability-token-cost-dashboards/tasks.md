# SPEC-065 Tasks: R5 Observability — Token/Cost Emission, Domain-Metric Push, Dashboards, Gated Live-Check

Task states: `[ ]` pending, `[x]` done. Keep tasks small and tied to requirement IDs.

> **Approved — tasks are now derived from the binding plan** (SPEC-065 `approved`
> 2026-09-27). Approval authorizes implementation as a **separate** step; it does
> not by itself authorize commit/push, deployment, or the R-4 live paid model call,
> each of which is its own authorization boundary. The approval step itself was
> documentation-only (no runtime change, no deployment, no live call, no version
> bump). Begin execution at Stage 0 (read-only plan-time investigations) before any
> code change.

## Stage 0: Plan-time investigations (read-only; recorded in `plan.md`)

- [ ] Confirm where the locked agentscope 2.0.8 sources its **cost** so R-1's
      dollar figure is a documented mirror of a provider-derived value, not an
      invented platform price table; record the finding in `plan.md`
      (`products/agent-platform/.venv/.../agentscope/` — the `gen_ai.usage.cost*`
      path the tracing extractor writes)
- [ ] Fix the exact **mirrored-family enumeration** for R-2 in `plan.md` (the
      operator-facing subset at minimum), confirming each family's kind
      (counter/gauge/histogram) and bounded label set

## R-1: First-class LLM token and cost emission

- [ ] Add `agent_llm_tokens_total{provider,model,direction}` and
      `agent_llm_cost_usd_total{provider,model}` counters + `record_*` helpers to
      `products/agent-platform/src/agent_service/core/metrics.py` (module-level
      objects; `direction ∈ {input,output,cache_input,cache_creation}`)
- [ ] Add `TokenUsageMiddleware(MiddlewareBase)` implementing `on_model_call` in
      `products/agent-platform/src/agent_service/services/kernel_middleware.py`:
      resolve `{provider,model}` from `current_model` (bounded to the catalog;
      unknown → `model="unknown"` sentinel), `await next_handler(...)`, read
      `result.usage` (+ cost) for a `ChatResponse`
- [ ] Make the middleware **streaming-aware**: wrap the `AsyncGenerator` and
      increment from the terminal chunk's `usage` (mirror the tracing middleware's
      generator wrapper)
- [ ] Record **nothing** when a provider returns no `usage` / no cost (never
      synthesize a zero-fill or a fabricated cost)
- [ ] Register the middleware unconditionally in
      `runtime_kernel._build_middlewares()` (`runtime_kernel.py:531-565`), beside
      `GatewayPermissionMiddleware` / `ToolEvidenceMiddleware` — always-on, no knob
- [ ] Test: non-streaming usage → correct `{provider,model,direction}` increments +
      cost when reported (`products/agent-platform/tests/`)
- [ ] Test: streaming multi-chunk generator records terminal-chunk usage (a naive
      non-generator read records zero and must fail)
- [ ] Test: usage-less response records nothing; cost-less response → tokens-only
- [ ] Test: `direction` enum bounded; unknown model → sentinel; emitted label set
      contains **no** `session_id`/`user_id`/`request_id`
- [ ] Test: middleware is present in `_build_middlewares()` output with no opt-in
      set; the family appears on `GET /metrics` with `_total` + naming conventions

## R-2: Domain metrics pushed as OTel instruments (ADR-0014)

- [ ] Add a mirror helper to the **canonical**
      `products/agent-platform/src/agent_service/core/telemetry.py` that, when
      `OTEL_ENABLED`, obtains a meter from the already-set `MeterProvider` and
      creates OTel instruments of the **same name + bounded labels** for a family
      list passed in by the caller (no service-specific name inside the guarded
      module)
- [ ] Replicate the edited `telemetry.py` to all **eight** services in the same
      commit; `TelemetryParityTest`
      (`products/tool-gateway/tests/test_module_parity.py`) must pass byte-identical
- [ ] Call the helper from each service's own `core/metrics.py` for its enumerated
      families (incl. the R-1 token/cost family in agent-platform); record into
      both surfaces from the existing `record_*` call sites
- [ ] Test: name + label parity between the prometheus family and the OTel instrument
- [ ] Test: `OTEL_ENABLED=false` → no instrument created, `/metrics` unchanged
      (SPEC-005 decoupling + always-on hold)
- [ ] Test: exporter error fails open (never raises into the request path)
- [ ] Test: `TelemetryParityTest` still green after the eight-copy edit

## R-3: OpenObserve dashboard suite (config-as-code)

- [ ] Add OpenObserve-importable dashboard JSON under
      `shared/platform-ops/dashboards/` (token by `{provider,model,direction}`;
      cost by `{provider,model}`; RED; one governance/decision-chain view), querying
      the OpenObserve **metrics** stream
- [ ] Add a documented, repeatable apply/import script under `shared/platform-ops/`
- [ ] Wire a dashboard import/render validation into `make verify` (analogous to
      `kustomize build` for overlays) so the artifact cannot silently rot
- [ ] Document the dashboards + how to reach them in the operator guide

## R-4: Gated observability live-check

- [ ] Add a live-check script under `shared/platform-ops/` reproducing spike §6
      (assert `OTEL_ENABLED`/`AGENTSCOPE_KERNEL_TRACING`; inspect `/metrics` for
      `agent_llm_tokens_total`; port-forward OpenObserve; query metrics/traces
      correlated by `trace_id`)
- [ ] Drive **one** read-only chat turn against external `deepseek`
      (`deepseek-v4-flash`, authorized billable per memo §7.3); delete the test
      session; no mutation/tool/HITL
- [ ] Make the script idempotent, loud on a missing signal, and invoked from the
      demo/e2e entrypoint (`make` list) so it cannot be skipped silently
- [ ] Add a mocked-I/O execution of the script (no live paid call) to the ordinary
      test suite; keep the paid live leg an explicitly gated, authorized step

## R-5: Contract and living-doc updates

- [ ] Update `shared/shared-contracts/observability-conventions.md`: the token/cost
      family + bounded labels; an additive "domain-metric OTel push" note under Two
      Surfaces (push-only visibility requires `OTEL_ENABLED`, ADR-0014); a
      dashboards-as-config-as-code pointer
- [ ] Update the operator guide (dashboards R-3, live-check R-4) and the config
      reference / Feature Activation Matrix (dashboard visibility depends on
      `OTEL_ENABLED`; no new knob expected)
- [ ] `CHANGELOG.md` entry referencing SPEC-065; `VERSION` + lockstep version files
      → v0.45.0 at delivery
- [x] Flip ADR-0014 `proposed` → `accepted`; update `docs/adr/README.md` index
      (done at approval, 2026-09-27)

## Delivery Gate

> Per ADR-0008, the spec advances to `delivered` only when every `R-x` acceptance
> criterion maps to at least one asserting test and the shipped live-check is
> exercised. Mapping (criterion → asserting test):

- [ ] **R-1** non-streaming increment → token/cost label test
- [ ] **R-1** streaming terminal-chunk → multi-chunk generator test
- [ ] **R-1** bounded `direction` enum + model sentinel → label-bound test
- [ ] **R-1** no forbidden labels → emitted-label-set assertion
- [ ] **R-1** absent usage/cost → records-nothing / tokens-only tests
- [ ] **R-1** always-on registration → `_build_middlewares` presence test
- [ ] **R-1** cost provenance is a mirror → Stage-0 finding + assertion the value
      comes from provider-reported usage, not a platform price table
- [ ] **R-2** name/label parity → parity test
- [ ] **R-2** `OTEL_ENABLED=false` no-op + `/metrics` unchanged → decoupling test
- [ ] **R-2** fail-open → exporter-error test
- [ ] **R-2** single definition under guard → `TelemetryParityTest` green
- [ ] **R-3** dashboards importable → `make verify` render/import validation
- [ ] **R-4** live path end to end → mocked-I/O script test in CI + the authorized
      live paid leg run and evidenced
- [ ] **R-5** docs/version updated; all bookkeeping surfaces consistent
- [ ] Full root `make verify` green (every product suite incl. the parity guard,
      every overlay render, policy rules, version lockstep, secret vocabulary)
- [ ] Living state docs updated (see `spec.md` Impact)
- [ ] Spec index (`docs/specs/README.md`) + delivery-roadmap backlog row updated
- [ ] `spec.md` status set to `delivered` (+ delivered date/version + changelog)
