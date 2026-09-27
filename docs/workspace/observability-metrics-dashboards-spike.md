# Spike: Observability Metrics and Dashboards — Token-by-Model Emission and the Consumer Gap

Status: assessment complete (pre-spec spike). No runtime change, no implementation, and
no spec-status flip are part of this assessment. This memo is the promotion artifact the
[delivery-roadmap](../agentic-aiops-platform/delivery-roadmap.md#exploration-backlog)
promotion rule requires before an observability slice gets a SPEC number.
Date: 2026-09-27
Roadmap home: R5 "stronger reliability and observability" / "all core services ↔ dashboards
and metrics" (the one R5 theme deliverable with no spec yet)
Contract home: [observability-conventions.md](../../shared/shared-contracts/observability-conventions.md) (SPEC-005 baseline)
Evidence baseline: repository at v0.44.0 (`413c596`); the locked agentscope 2.0.8 install
(`products/agent-platform/.venv/lib/python3.12/site-packages/agentscope/`); and a **live**
inspection of the running `dev-luban-aiops` OrbStack cluster and its in-cluster OpenObserve
on 2026-09-27. Read-only cluster inspection plus **one authorized live chat turn** against the
external `deepseek` provider (a real, billable single-word model call) to capture an LLM span;
the test session was deleted afterward and no cluster state was mutated. Port-forwards to the
identity-service, platform-gateway, and OpenObserve router were opened for the run and torn down.

## 1. Question and recommendation

> R5 promises "all core services ↔ dashboards and metrics" and "stronger reliability and
> observability," but no spec has addressed them. What is the actual gap, does observability
> include token consumption by model, and do we need to integrate OpenObserve?

Findings, in one line each:

- **OpenObserve is already integrated and live.** It is not a to-do. `OTEL_ENABLED=true` and
  `AGENTSCOPE_KERNEL_TRACING=true` are set in the running `agent-service` pod; logs, traces,
  and OTel metrics from all seven Python services are landing in the in-cluster OpenObserve
  right now (§2.1). Any new slice must **build on** this, not re-plumb it.
- **Token consumption by model already reaches OpenObserve — as trace-span attributes only.**
  The agentscope tracing middleware writes `gen_ai.usage.input_tokens` / `.output_tokens`
  (plus `agentscope.usage.cache_input_tokens` / `.cache_creation_input_tokens`) and the model
  onto every LLM span (§2.3, §3). It is **not** aggregated into any metric and appears on **no
  dashboard**, so "how many tokens did model X consume this week" is not answerable today
  without hand-querying raw spans.
- **There is no token metric, and the domain metrics that do exist have no consumer.** The
  `/metrics` surface has RED + a rich set of domain counters (sessions, chat, session-store,
  agent-state, evidence, audit emits, model discovery) but **no LLM/token family** (§2.2).
  Critically, the dev cluster runs **no Prometheus/Grafana and no prometheus-operator** (no
  ServiceMonitor/PodMonitor CRDs), so those domain counters are **curl-only** — nothing scrapes
  or dashboards them (§2.4). OpenObserve receives only the OTel *auto-instrumentation* HTTP
  metrics, not the `prometheus_client` domain counters.

Recommendation — two coherent, separable slices, A first:

- **Slice A (emit): first-class LLM token/cost metric.** Add a bounded Prometheus counter
  `agent_llm_tokens_total{provider,model,direction}` captured from the provider-reported
  `ChatResponse.usage` via a small `MiddlewareBase.on_model_call` middleware — the identical
  supported-hook pattern SPEC-018 established and the very hook the tracing middleware already
  uses (§3, §4). Narrow, high operator value, clears the four-point adoption gate trivially.
- **Slice B (consume): close the dashboard gap.** Decide how domain metrics (including the new
  token counter) reach a dashboard, given no scraper exists — either emit them as OTel
  instruments so they push over the existing OTLP metric pipeline (no new infra, consistent with
  the "services only push OTLP" contract), or deploy a scraper + OpenObserve remote-write. Then
  ship the actual OpenObserve dashboards + a repeatable live-check script (§5, §6).

My lean: scope the first spec to **Slice A plus the minimal Slice B needed to see it** (push the
new counter as an OTel instrument so it is queryable in OpenObserve, and one dashboard), and
leave the broader domain-metrics-scraping decision as a recorded follow-on. Slice A is the
compelling, concrete hook; the rest of the observability theme hangs off it.

## 2. What already exists (live-verified on the running cluster, 2026-09-27)

### 2.1 OTel → OpenObserve push pipeline: live and working

Confirmed **inside the running `agent-service` pod**:

```
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://openobserve-router.openobserve.svc.cluster.local:5080/api/default
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <provisioned>
AGENTSCOPE_KERNEL_TRACING=true
```

The full OpenObserve HA stack is up in the `openobserve` namespace (router, ingester, querier,
compactor, scheduler, NATS ×3). Querying it read-only over a port-forward
(`kubectl port-forward -n openobserve svc/openobserve-router 5080:5080`) shows real platform
telemetry. Note the OTLP streams are all named `default`, disambiguated by `stream_type`
(`logs` / `traces` / `metrics`), so queries target `/api/default/_search?type=<stream_type>`
with `FROM "default"`.

**Logs** (mirrored structured JSON via the OTLP log bridge), last 30 days, by service:

| service_name | log records |
|---|---|
| audit-service | 8703 |
| skills-hub | 8697 |
| incident-service | 7355 |
| agent-service | 124 |
| platform-gateway | 13 |
| tool-gateway | 12 |
| identity-service | 4 |

**Traces**, last 30 days: dominated by health probes (`GET /health/ready`, `/health/live`) across
audit/incident/skills-hub, plus real work — `POST /api/v1/audit/events` (~668), `skills.sync`
(670), `skills.git.checkout` (168), and platform-gateway session fetches. **agent-service shows
only `GET /api/v2/{runtime,health}` and `GET /metrics` — no chat/LLM spans**, because no real
chat turn has been driven in the retention window (§6 records the one remaining live leg).

**Metrics** streams present in OpenObserve: `http_server_duration`, `http_client_duration`,
`http_server_active_requests`, `http_server_request_size`, `http_server_response_size` (each with
`_bucket`/`_count`/`_sum`/`_min`/`_max`). These come from the OTel FastAPI + HTTPX
auto-instrumentation in `setup_telemetry` — **not** from the platform's `prometheus_client`
domain counters (see §2.4).

Conclusion: the ingestion pipe is a solved, governed, live surface (SPEC-005; the 2026-08-21
durable-header fix). No integration work is needed.

### 2.2 Prometheus `/metrics` domain surface: rich, but no token family

Live `curl localhost:8000/metrics` inside `agent-service` returns exactly the families defined in
[`core/metrics.py`](../../products/agent-platform/src/agent_service/core/metrics.py):

- RED: `http_requests_total{method,handler,status}`, `http_request_duration_seconds{method,handler}`
- Domain: `agent_sessions_created_total`, `agent_chat_requests_total`,
  `session_store_backend{backend}` / `_errors_total{operation}` / `_fallbacks_total`,
  `agent_state_backend{backend}` / `_errors_total` / `_fallbacks_total`,
  `evidence_store_writes_total{result}`, `evidence_frames_persisted_total`,
  `evidence_frames_truncated_total{reason}`, `audit_emits_total{result}`,
  `agent_model_discovery_refreshes_total{provider,result}`, `agent_model_discovery_models{provider}`

`grep -iE 'token|llm|usage'` over the served metrics returns **nothing** — there is no LLM or
token metric anywhere. (The pod was idle, so the labeled domain counters had no samples yet;
the family list from the `# HELP` lines is authoritative for what exists.) Note
`agent_model_discovery_*` already uses `provider` as a bounded label — precedent for a
`{provider,model}` label set on a token metric.

### 2.3 Token usage today: present in traces, absent from metrics

From the locked agentscope 2.0.8 install, the tracing middleware extractor
([`_tracing/_extractor.py:356-385`](../../products/agent-platform/.venv/lib/python3.12/site-packages/agentscope/middleware/_tracing/_extractor.py))
sets, on every LLM span, OTel **GenAI semantic-convention** attributes:

- `gen_ai.usage.input_tokens`  ← `ChatResponse.usage.input_tokens`
- `gen_ai.usage.output_tokens` ← `ChatResponse.usage.output_tokens`
- `agentscope.usage.cache_input_tokens` (when non-zero)
- `agentscope.usage.cache_creation_input_tokens` (when non-zero)
- plus `gen_ai.response.id`, finish reasons, output messages, and the request-side model
  attribute (`gen_ai.request.model`).

So token-by-model **is already flowing into OpenObserve** whenever a chat turn runs — as
per-span attributes on the `traces` stream. It is queryable (SQL over the flattened span
attributes) but it is **not aggregated, not a metric, and on no dashboard**. That is precisely
the gap: the raw data exists, the operator-facing signal does not. **Live-confirmed** in §6.5 on a
real `deepseek-v4-flash` turn, which also showed the span carries `gen_ai.usage.cost` (dollars)
and the model/provider dimensions — so token **and** cost by model are both already present at the
span level.

### 2.4 The consumer gap: no scraper, no dashboard

`kubectl get ns | grep -iE 'prometheus|monitor|grafana|thanos|victoria'` → only `openobserve`.
`kubectl get servicemonitor,podmonitor --all-namespaces` → `the server doesn't have a resource
type "servicemonitor"` (prometheus-operator not installed).

Consequences:

- The `prometheus_client` domain counters (§2.2) have **no scraper and no dashboard** — they are
  a curl-only debug surface today, exactly as SPEC-005 framed them ("collector-independent …
  for debugging and health").
- OpenObserve gets **only** what the OTLP push sends: traces, mirrored logs, and the OTel
  auto-instrumentation HTTP metrics. The two metric worlds (Prometheus pull vs OTLP push) do not
  overlap.
- The conventions doc already declares scraping/storage/dashboards/alerting a **platform-ops
  concern outside the service contract** — which is why this is genuinely un-started R5 work
  rather than an oversight.

This is the architectural crux for Slice B: to make *any* domain metric (existing or a new token
counter) visible on a dashboard, we must choose a consumer path — (a) additionally emit domain
metrics as **OTel instruments** so they push over the existing OTLP metric pipeline into
OpenObserve (no new infra; consistent with "services only push OTLP"), or (b) deploy a
**Prometheus scraper** and have OpenObserve (or Grafana) consume `/metrics` (new infra, but keeps
the domain metrics pull-only and Prometheus-native). Option (a) needs no cluster additions and
reuses the pipe already proven live in §2.1.

## 3. Capture point for a token-by-model metric

The platform does **not** call the model directly — the agentscope kernel does. The clean,
supported interception point is `MiddlewareBase.on_model_call`
([`_base.py:213-239`](../../products/agent-platform/.venv/lib/python3.12/site-packages/agentscope/middleware/_base.py)):

```
async def on_model_call(self, agent, input_kwargs, next_handler):
    # input_kwargs: messages, tools, tool_choice, current_model (a ChatModelBase → model name)
    # next_handler(...) → ChatResponse | AsyncGenerator[ChatResponse, None]
```

This is the **same hook the tracing middleware uses**
([`_trace.py:259-307`](../../products/agent-platform/.venv/lib/python3.12/site-packages/agentscope/middleware/_tracing/_trace.py)):
read `input_kwargs["current_model"]` for the model/provider, `await next_handler(**input_kwargs)`,
then read `result.usage` for tokens. A platform `TokenUsageMiddleware(MiddlewareBase)` would:

1. resolve `provider`/`model` from `current_model` (bounded by the SPEC-026/027 catalog);
2. `await next_handler(...)`;
3. for a **non-streaming** `ChatResponse`: increment the counter from `result.usage`;
4. for a **streaming** `AsyncGenerator`: wrap it and read `usage` off the terminal chunk —
   exactly what the tracing middleware's `_trace_async_generator_wrapper` already does. **This
   streaming nuance matters**: the platform's chat path streams, so a naive non-generator read
   would record zero tokens.

This lands beside the two middleware the platform already registers
(`GatewayPermissionMiddleware.on_check_permission`, `ToolEvidenceMiddleware.on_acting` in
[`services/kernel_middleware.py`](../../products/agent-platform/src/agent_service/services/kernel_middleware.py))
— no private surface, matching the SPEC-018 "move onto supported hooks" discipline and the
SPEC-064 `on_compress_context` precedent.

Metric shape (bounded labels only, per the cardinality rules):

- `agent_llm_tokens_total{provider,model,direction}` where `direction ∈ {input, output,
  cache_input, cache_creation}` — a counter, `_total` suffix, `<service>_<noun>_<unit>` naming.
- `model` is a **bounded enum** drawn from the model catalog (not free text), so it satisfies the
  cardinality rule; `provider` is already used as a label by `agent_model_discovery_*`.
- **No** `session_id` / `user_id` / `request_id` labels — those are explicitly forbidden. Per-turn
  or per-session cost attribution, if ever needed, belongs in the durable audit record (SPEC-013),
  not in metrics.
- **Accuracy / anti-fabrication:** record the **provider-reported** `usage` only; never a local
  tokenizer estimate. If a provider returns no `usage`, record nothing (do not synthesize).
- **Cost-in-dollars is already computed by agentscope** — the live span (§6.5) carries
  `gen_ai.usage.cost`, `gen_ai.usage.cost_input`, and `gen_ai.usage.cost_output` beside the token
  counts. So the dollar metric is a **mirror of an existing provider-derived value**, not a price
  table the platform must own. Per decision §7.4 the spec emits both
  (`agent_llm_tokens_total{…}` and a cost figure, e.g. `agent_llm_cost_usd_total{provider,model}`);
  where a provider reports no cost, degrade to tokens-only rather than fabricate. The spike should
  still confirm where agentscope sources its pricing so the dollar figure's provenance is
  documented, not assumed.

## 4. Four-point adoption-gate check (SPEC-018)

Slice A (the token middleware + counter) is metrics-only and clears the gate trivially:

1. **Deny-by-default / audit / gateway-only execution:** unaffected — `on_model_call` observes a
   model call the kernel already makes; it executes no tool and adds no execution surface.
2. **Identity via delegated token only:** no new identity edge; the middleware reads usage, it
   does not carry or mint identity.
3. **Read-only operational posture:** intact — recording a counter is not an infrastructure
   mutation.
4. **No agentscope types through the v2 contract:** `ChatResponse.usage` is consumed inside the
   kernel and reduced to integers on a Prometheus/OTel counter; no agentscope type crosses the
   platform contract, and `agent-stream-event.schema.json` is untouched.

No new policy action, no new audit event type, no contract change. Slice B (dashboards) is
platform-ops/GitOps and touches no product contract either.

## 5. Proposed slicing

**Slice A — emit (recommended first spec):**
- `TokenUsageMiddleware(MiddlewareBase).on_model_call` incrementing
  `agent_llm_tokens_total{provider,model,direction}` from provider-reported usage, streaming-aware.
- Register it beside the existing kernel middleware; no opt-in knob required (pure observation),
  though one can be added for symmetry with the other kernel toggles if the operator prefers.
- Tests: usage recorded for non-streaming and streaming responses; zero/absent usage records
  nothing; label cardinality bounded to catalog models; no session/user label.

**Slice B — consume (fast-follow, or folded minimally into A):**
- Decision: push the new counter (and optionally the existing domain counters) as **OTel
  instruments** over the existing OTLP metric pipeline (option §2.4a, no new infra), vs. deploy a
  Prometheus scraper (option §2.4b).
- Ship at least one OpenObserve dashboard (token consumption by model/provider over time; the RED
  and decision-chain views the audit work already surfaces).
- Add a repeatable live-check script (the §6 procedure) so the observability path is gated like
  the other demos (ADR-0008 spirit).

## 6. Live-test procedure (how to prove it end to end)

Most of this was already executed for this memo; the one leg not yet run is the chat turn, which
makes a real model call and is therefore left as an explicit operator choice.

1. **Cluster + config** (done): pods `1/1`; `OTEL_ENABLED=true` and `AGENTSCOPE_KERNEL_TRACING=true`
   in the `agent-service` pod.
2. **Pull side** (done): `kubectl exec <agent-pod> -- curl -s localhost:8000/metrics` and inspect
   the families; after Slice A, `grep agent_llm_tokens_total`.
3. **OpenObserve access** (done): `kubectl port-forward -n openobserve svc/openobserve-router
   5080:5080`, then query `/api/default/_search?type={logs,traces,metrics}` with `FROM "default"`
   over a microsecond time window.
4. **Drive one chat turn — DONE (2026-09-27, external `deepseek`, authorized paid call).** With
   port-forwards for identity-service (`18081`) and platform-gateway (`18083`), a dev operator
   platform token was minted (`POST /api/v1/auth/token`), a session created
   (`POST /api/v1/sessions` → `session_type=operation`, `model=null` → the default
   `deepseek-v4-flash`), and one **read-only** turn streamed
   (`GET /api/v1/chat/stream?message="Reply with exactly one word: healthy. Do not call any
   tools."`). The SSE returned `"healthy"` with `request_id=63d9bd754cd3ebcc3cda4527991f37f9`
   (32 hex = the W3C `trace_id`, confirming the correlation bridge). The test session was deleted
   afterward; no mutation, no tool call, no HITL card.
5. **Push side confirmation — DONE.** Querying the OpenObserve `traces` stream by that `trace_id`
   returned the full distributed trace: `platform-gateway GET /api/v1/chat/stream` →
   `agent-service GET /api/v2/chat/stream` → `invoke_agent LubanOpsRuntime` →
   **`chat deepseek-v4-flash`** (the LLM span, `_get_llm_span_name` = `chat {model}`) →
   `tool-gateway GET /api/v2/tools`. The LLM span carries the complete GenAI attribute set:

   | attribute | live value |
   |---|---|
   | `gen_ai_provider_name` | `deepseek` |
   | `gen_ai_request_model` / `gen_ai_response_model` | `deepseek-v4-flash` |
   | `gen_ai_operation_name` | `chat` |
   | `gen_ai_usage_input_tokens` | `5352` |
   | `gen_ai_usage_output_tokens` | `1` |
   | `gen_ai_usage_total_tokens` | `5353` |
   | `agentscope_usage_cache_input_tokens` | `5120` |
   | `gen_ai_usage_cost` | `0.0011781` |
   | `gen_ai_usage_cost_input` / `_output` | `0.00117744` / `6.6e-07` |

   Two conclusions the static reading could not reach: **(a)** agentscope already computes
   **dollar cost** (`gen_ai.usage.cost{,_input,_output}`), so decision §7.4 is a *mirror* of an
   existing value, not a price table to build; **(b)** a trivial one-word turn still consumed
   **5,352 input tokens** (system prompt + the full ~30-tool schema, 5,120 of it cache-served) for
   **1 output token** — precisely the per-model cost insight an aggregated metric + dashboard
   would surface and that raw per-span querying hides. After Slice A, the same numbers would appear
   as `agent_llm_tokens_total{provider="deepseek",model="deepseek-v4-flash",direction=…}` on
   `/metrics` and, under decision §7.1, as an OpenObserve metric stream.

## 7. Decisions (resolved by the operator, 2026-09-27)

1. **Slice B consumer path → push domain metrics as OTel instruments.** No new scraping infra;
   the existing OTLP metric pipeline (proven live in §2.1) carries the domain metrics — including
   the new token counter — into OpenObserve. Consistent with the "services only push OTLP;
   scraping is platform-ops" contract. A Prometheus scraper is not deployed.
2. **First-spec scope → the full R5 observability theme**, provided it is planned and broken into
   careful, detailed tasks (not one blob). Expect a multi-requirement spec: token/cost emission
   (Slice A), OTel-instrument push of the domain metrics, the OpenObserve dashboard suite, and a
   gated live-check — sequenced as separately verifiable tasks.
3. **Live chat-turn leg → run against the external `deepseek` provider** (`deepseek-v4-flash`,
   paid), not the local Ollama, which is too slow for an interactive evidence run. Authorized as a
   real (billable) model call.
4. **Cost → emit both tokens and dollars.** A per-model price table becomes an in-scope input; the
   token counter is the durable provider-agnostic unit and the dollar figure is derived from it, so
   a missing/unknown price degrades to tokens-only rather than failing or fabricating a cost.
5. **Token middleware → always-on** (pure observation; no opt-in knob), matching its
   read-only/no-execution character.

## 8. Verdict

- **OpenObserve integration:** already done and live — do not re-plumb; build on it.
- **Token consumption by model:** the raw data already reaches OpenObserve as GenAI trace-span
  attributes; what is missing is an **aggregated, dashboard-visible metric**. Adding
  `agent_llm_tokens_total{provider,model,direction}` via a supported `on_model_call` middleware is
  a small, gate-clearing, high-value Slice A.
- **The larger untouched R5 deliverable** is the **consumer side** — no scraper, no dashboards,
  domain metrics curl-only. Slice B closes it and is where "all core services ↔ dashboards and
  metrics" is actually realized.
- Recommendation: promote to a spec scoped to the **full R5 observability theme** (operator
  decision §7.2), planned as carefully separated tasks — token+cost emission via an always-on
  `on_model_call` middleware, OTel-instrument push of the domain metrics, the OpenObserve
  dashboard suite, and a gated live-check. The consumer path is OTel push (§7.1); cost is emitted
  in both tokens and dollars (§7.4); the live chat-turn leg runs against the external `deepseek`
  provider (§7.3).
