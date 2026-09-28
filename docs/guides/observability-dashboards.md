# Observability Dashboards

Operator guide to the platform's OpenObserve dashboards: what ships, how to
reach them, how to read them, and how to (re)apply them. The dashboards are the
**consumer side** of the platform's two-surface observability model
([`observability-conventions.md`](../../shared/shared-contracts/observability-conventions.md)):
every service always exposes a Prometheus `/metrics` pull endpoint, and — when
`OTEL_ENABLED=true` — also **pushes** the same domain metrics as OpenTelemetry
instruments into the in-cluster OpenObserve, where these dashboards render them.

They are **config-as-code**: the dashboard definitions live in git under
[`shared/platform-ops/dashboards/`](../../shared/platform-ops/dashboards/), not
click-built in the cluster, so they are reviewable, reproducible, and validated
on every `make verify` (SPEC-065 R-3, ADR-0014).

## What ships

| Dashboard | Purpose | Key signals |
|---|---|---|
| **Service Health (RED)** | Cross-service Rate / Errors / Duration | Request rate and 5xx error rate per service; p50/p95 request latency; top handlers; requests by status. |
| **LLM Token Consumption** | Token spend visibility by model | `agent_llm_tokens_total` by `{provider, model, direction}` over time; top models; input vs output vs cache tokens. Tokens only — **no cost panel** (the dollar metric is deferred; agentscope reports no provider-derived cost and the platform has no price table). |
| **Governance & Decision Chain** | The decision path as metrics | Policy decisions by `decision`/`action`, token verification, execution handoffs/completions/rejections, evidence writes/truncations, audit emits by `result`, incident triage, delegation exchanges. |

## Prerequisites

1. **`OTEL_ENABLED=true`** on the services (default in `dev-k8s`, set in
   `shared/runtime.env`). With push disabled, nothing reaches OpenObserve and the
   panels are empty — the `/metrics` pull surface is unaffected either way. See
   the [Configuration Reference](configuration-reference.md#feature-activation-matrix).
2. **OpenObserve reachable** and its OTLP ingest credentials provisioned
   (`sync-otel-secrets.sh`). Without the ingest header the exporters push
   anonymously and OpenObserve answers 401.
3. **Dashboards applied** at least once (below). They are not auto-created on
   deploy; import is an explicit operator step.

## Reaching the dashboards

Open the OpenObserve UI (port-forward the router, then browse to it):

```sh
kubectl port-forward -n openobserve svc/openobserve-router 5080:5080
# open http://localhost:5080 → Dashboards → folder "default"
```

The three dashboards appear by their titles: *Luban AIOps - Service Health
(RED)*, *Luban AIOps - LLM Token Consumption*, and *Luban AIOps - Governance &
Decision Chain*.

## Applying / re-applying (idempotent)

`apply-dashboards.sh` imports every dashboard JSON, matching by `dashboardId`
(update if present, else create), so re-running is safe and never duplicates.
Full details live in the
[dashboards README](../../shared/platform-ops/dashboards/README.md).

```sh
kubectl port-forward -n openobserve svc/openobserve-router 5080:5080

OO_ROOT_USER_EMAIL=... OO_ROOT_USER_PASSWORD=... \
  sh shared/platform-ops/dashboards/apply-dashboards.sh
```

The credentials are the same OpenObserve root pair used for OTLP ingest; they
are read from the environment and never echoed. This is a live, state-mutating
call, so it is intentionally **not** part of `make verify`.

## Reading the panels

- **Empty panel?** The most common causes, in order:
  1. `OTEL_ENABLED` is not `true` on the service that emits the metric.
  2. **No traffic yet** — a freshly started, idle service exposes no counter
     samples until it serves a request, so the series is genuinely absent (not
     zero). Drive one request (or one chat turn for the token dashboard) and
     re-check.
  3. The time range predates the data, or the metric has aged out of the
     retention window.
- **`service_name` breakdown** (RED dashboard) comes from the OTel resource
  label; each of the eight services appears as its own series.
- **Latency percentiles** use `histogram_quantile` over the
  `http_request_duration_seconds_bucket` stream (p50 and p95).
- **Token `direction`** is bounded to `input`, `output`, `cache_input`, and
  `cache_creation` (the counts agentscope's `ChatUsage` reports).

## Editing and adding dashboards

Dashboards are plain OpenObserve JSON (dashboard schema `version: 5`). To change
one, edit the file (or build it in the UI and export it into the folder), then
validate before applying:

```sh
make validate-dashboards
```

This offline gate (the analog of `kustomize build` for the GitOps overlays)
checks that each file parses, carries the OpenObserve dashboard envelope, has
well-formed panels, and — importantly — that **every metric it references is one
the services actually emit** (cross-checked against each service's
`OTEL_MIRROR_FAMILIES`). Renaming a metric in `core/metrics.py` therefore fails
`make verify` until the dashboards are updated, so they cannot silently rot.

## Verifying the pipeline end to end

`observability-livecheck.sh` (SPEC-065 R-4) reproduces the observability spike
as a repeatable, idempotent check that is loud on any missing signal. It has
three escalating legs:

```sh
# 1. Mocked-I/O proof of the pipeline logic — no cluster, no network, no paid
#    call. This leg is collected by the agent-platform suite (so it runs on every
#    `make verify`) and is also in the `make e2e` list, so it cannot be skipped.
make observability-livecheck

# 2. Read-only cluster pre-flight: asserts OTEL_ENABLED=true and
#    AGENTSCOPE_KERNEL_TRACING=true on the agent pod, agent_llm_tokens_total on
#    /metrics (R-1), and that OpenObserve is reachable. Fires no model call.
#    Needs the OpenObserve port-forward plus OO_ROOT_USER_EMAIL/OO_ROOT_USER_PASSWORD.
make observability-livecheck LIVE=1

# 3. The gated, BILLABLE leg: additionally drives ONE read-only deepseek chat
#    turn, correlates it in OpenObserve by trace_id (the LLM span carrying
#    gen_ai token usage + the agent_llm_tokens_total metric stream), then deletes
#    the throwaway session. No mutation, no tool call, no HITL.
make observability-livecheck LIVE=1 DRIVE_TURN=1
```

The paid turn never fires by default — it requires the explicit `DRIVE_TURN=1`
gate (equivalently `LUBAN_OBS_DRIVE_PAID_TURN=1` with `--live`), matching the
operator authorization for a real, billable model call (spike memo §7.3). The
turn sends no `X-Request-ID`, so the gateway bridges the SSE `request_id` to the
active OTel `trace_id` — the correlation key the check queries OpenObserve by.
See the
[observability spike memo](../workspace/observability-metrics-dashboards-spike.md)
for the underlying manual procedure.

## Related

- [Dashboards README (config-as-code)](../../shared/platform-ops/dashboards/README.md) — files, validation, apply script
- [Configuration Reference](configuration-reference.md) — `OTEL_ENABLED` and the OTLP endpoint/credentials
- [Observability Conventions](../../shared/shared-contracts/observability-conventions.md) — the two-surface contract and metric-naming rules
- [ADR-0014: Domain metrics via OTel push](../adr/0014-domain-metrics-via-otel-push.md) — why push, not a scraper
- [SPEC-065](../specs/SPEC-065-r5-observability-token-cost-dashboards/spec.md) — token emission, OTel push, dashboards, live-check
- [Troubleshooting](troubleshooting.md) — symptom-based diagnostics
