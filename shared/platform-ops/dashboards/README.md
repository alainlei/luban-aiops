# OpenObserve Dashboards (config-as-code)

SPEC-065 R-3. The platform's observability dashboards live here as
OpenObserve-importable JSON, reviewed and versioned in git rather than
click-built in the cluster (which is not reproducible and rots silently). They
are the **consumer side** of the SPEC-005 two-surface observability model.

## What ships

| File | Dashboard | Shows |
|---|---|---|
| `luban-aiops-service-health.dashboard.json` | Service Health (RED) | Cross-service Rate / Errors / Duration from `http_requests_total` and `http_request_duration_seconds`, broken down by the OTel `service_name` resource label. p50/p95 via `histogram_quantile` over the `_bucket` stream. |
| `luban-aiops-llm-tokens.dashboard.json` | LLM Token Consumption | `agent_llm_tokens_total{provider,model,direction}` (SPEC-065 R-1) over time and by model/provider. Tokens only — no cost panel (deferred with the R-1 cost metric). |
| `luban-aiops-governance.dashboard.json` | Governance & Decision Chain | The decision path already emitted as domain metrics: policy decisions, token verification, execution handoffs/completions/rejections, evidence writes/truncations, audit emits, incident triage, delegation exchanges. |

## Data source and prerequisites

- The panels query the **OTel push mirror** of the `prometheus_client` domain
  families, added by SPEC-065 R-2 (ADR-0014). Each service's `core/metrics.py`
  declares `OTEL_MIRROR_FAMILIES` and mirrors every family to an OTel instrument
  of the same name and bounded labels.
- **Requires `OTEL_ENABLED=true`.** When OTel push is off, no metrics reach
  OpenObserve and the panels are empty. The always-on Prometheus `/metrics` pull
  surface is unaffected and remains the source of truth (SPEC-005 decoupling).
- Counters keep their `_total` suffix, so an OTel instrument name equals the
  Prometheus exposed sample name; OpenObserve stores each metric as a stream of
  that name, and histograms split into `_bucket` / `_sum` / `_count` / `_min` /
  `_max`. Queries use PromQL over these streams.

## Validate (offline — the `make verify` gate)

```sh
make validate-dashboards          # or: python3 shared/platform-ops/dashboards/validate_dashboards.py
```

`validate_dashboards.py` is the config-as-code analog of `kustomize build` for
the GitOps overlays: it never touches a cluster. It fails when any
`*.dashboard.json` does not parse, is missing the OpenObserve dashboard envelope,
has a malformed panel (unknown type, empty query, duplicate id, bad layout), or
**references a metric stream that no service emits**. That last check parses each
`products/*/src/*/core/metrics.py` `OTEL_MIRROR_FAMILIES` (via AST, no import) —
so renaming a metric fails `make verify` until the dashboards are updated. It is
wired into `make verify`.

## Apply (live — operator / R-4 step)

`apply-dashboards.sh` idempotently imports every `*.dashboard.json` into
OpenObserve, matching by `dashboardId` (update if present, else create). It is a
live, state-mutating call, so it is **not** part of `make verify`; run it as an
operator step or from the SPEC-065 R-4 gated live-check.

```sh
# 1. Reach the OpenObserve router.
kubectl port-forward -n openobserve svc/openobserve-router 5080:5080

# 2. Import with the root credentials (the same pair sync-otel-secrets.sh uses
#    for the OTLP ingest Basic-auth header). Credentials are never echoed.
OO_ROOT_USER_EMAIL=... OO_ROOT_USER_PASSWORD=... \
  sh shared/platform-ops/dashboards/apply-dashboards.sh
```

Configuration (env, with defaults): `OO_ENDPOINT` (`http://localhost:5080`),
`OO_ORG` (`default`), `OO_FOLDER` (`default`). In-cluster, set
`OO_ENDPOINT=http://openobserve-router.openobserve.svc.cluster.local:5080`.
Then open the OpenObserve UI → **Dashboards** → folder `default`.

## Schema and editing

- The JSON uses the OpenObserve dashboard **version 5** envelope
  (`version` / `dashboardId` / `title` / `description` / `role` / `owner` /
  `created` / `tabs[].panels[]` / `variables` / `defaultDatetimeDuration`), the
  stable, importable shape shared by current OpenObserve community dashboards.
  The envelope is forward-compatible with newer instances (they migrate on
  import); the exact live import against the deployed backend is confirmed by
  the R-4 live-check.
- To add or edit a dashboard: change the JSON (or build it in the UI and export
  it here), give it a unique `dashboardId` and `title`, then run
  `make validate-dashboards` before applying. Keep every metric reference within
  the emitted `OTEL_MIRROR_FAMILIES`; add the family in the relevant service's
  `core/metrics.py` first if a new signal is needed.

See the operator-facing guide at
[`docs/guides/observability-dashboards.md`](../../../docs/guides/observability-dashboards.md).
