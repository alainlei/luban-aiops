# Incident Service

## Purpose

`incident-service` turns alert noise and operator reports into tracked incidents, runs agent-driven triage on them, and dispatches the outcomes through collaboration connectors.

It is responsible for:

- dual intake: an Alertmanager-compatible webhook and manual operator reports, both normalized into one canonical incident model (`shared/shared-contracts/schemas/incident.schema.json`)
- fingerprint-based dedupe and resolution of Alertmanager alert groups
- operator-initiated triage: one agent turn in a dedicated session that produces a schema-validated triage report (`triage-report.schema.json`) with a severity assessment, evidence, hypotheses, and ranked advisory next steps
- a pluggable connector framework dispatching triage reports to collaboration surfaces (built-in `audit` sink; Slack/Jira adapters are future work)
- the incident query API behind the portal Incidents panel and the read-only `incidents.*` agent tools

## Ownership

Recommended owner:

- platform operations / on-call enablement team

## Current Scope

Current implementation status (SPEC-015):

- frozen-dataclass `INCIDENT_*` settings with fail-fast connector registry validation at startup
- Alertmanager v4 normalization: `groupKey` (or stable label hash) fingerprint, severity label mapping with `warning` default, annotations → title/summary, `resolved` handling
- webhook intake guarded by a shared bearer token (`INCIDENT_WEBHOOK_TOKEN`), fail-closed (503) when unconfigured; firing payloads dedupe onto the open incident with the same fingerprint, resolutions close it (unknown fingerprint → idempotent no-op)
- manual intake (`POST /api/v1/incidents`) authenticated by the platform-caller registry; `reported_by` records the operator name relayed via `X-Reported-By`
- triage: `triaging` → one agent-platform `/api/v2/chat` turn under the operator's delegated bearer in session `incident-<id>` → fenced `triage-report` JSON block extracted and validated → `triaged` (report stored, connectors dispatched) or `triage_failed` (raw agent text preserved); re-triage is latest-wins, and because agent sessions are single-owner, re-triage by a second operator falls back to `incident-<id>--<operator>` with the incident tracking the session actually used; report attribution (`session_id`/`generated_at`/`generated_by`) is server-minted, never taken from agent output
- `IncidentStore` protocol with two backends: `InMemoryIncidentStore` (dev/tests) and `PostgresIncidentStore` (psycopg v3; `incidents`, `triage_reports`, `connector_dispatches` tables), selected via `INCIDENT_STORE_BACKEND`
- query auth via the static Basic registry `INCIDENT_QUERY_CLIENTS` (SPEC-014 R-3 vocabulary) plus projected workload tokens (`INCIDENT_WORKLOAD_*`, SPEC-009 vocabulary)

API surface:

- `POST /api/v1/webhooks/alertmanager` — Alertmanager v4 webhook (bearer webhook token)
- `POST /api/v1/incidents` — manual report (platform-caller auth)
- `POST /api/v1/incidents/{incident_id}/triage` — operator-initiated triage (platform-caller auth + `X-User-ID` + `X-Delegated-Token` relayed by platform-gateway)
- `GET /api/v1/incidents` — list with `status`/`severity`/`source` filters and capped offset pagination, newest first
- `GET /api/v1/incidents/{incident_id}` — full record with the latest report and connector dispatch outcomes
- `GET /api/v1/incidents/{incident_id}/report` — the triage report (structured 404 when absent)
- `/health/live`, `/health/ready`, `/metrics`

Current runtime environment knobs:

- `INCIDENT_WEBHOOK_TOKEN`
  - shared bearer token for the Alertmanager webhook; empty disables intake (503)
- `INCIDENT_QUERY_CLIENTS`
  - static platform-caller registry (`client_id=secret,...`); lives in `incident-service-runtime-secrets`
- `INCIDENT_WORKLOAD_ISSUER_URL`, `INCIDENT_WORKLOAD_AUDIENCE`, `INCIDENT_WORKLOAD_CLIENTS`
  - projected workload-token auth (production upgrade path, SPEC-009 vocabulary)
- `INCIDENT_STORE_BACKEND`
  - `memory` or `postgres`; defaults to `memory`
- `INCIDENT_DB_URL`
  - PostgreSQL connection URL (required for the postgres backend; database `incidents`)
- `INCIDENT_CONNECTORS`
  - comma list of registered connector names; defaults to `audit`
- `INCIDENT_AGENT_SERVICE_URL`, `INCIDENT_TRIAGE_TIMEOUT_SECONDS`
  - agent-platform chat endpoint and triage turn timeout (default `120`)
- `INCIDENT_AUDIT_SERVICE_URL`, `INCIDENT_AUDIT_CLIENT_ID`, `INCIDENT_AUDIT_CLIENT_SECRET`
  - audit-service ingest endpoint and credential for the built-in `audit` connector

## Connector extension point

A connector pushes a validated triage report onto a collaboration surface. To add one:

1. Implement the `Connector` protocol in `services/` — a `name` attribute and `async def dispatch(incident, report) -> ConnectorOutcome(status, reference, error)`.
2. Register a factory (receiving `IncidentSettings`) in `CONNECTOR_REGISTRY` in `services/connectors.py`.
3. Add the name to `INCIDENT_CONNECTORS`.

Dispatch failures are recorded per incident and counted (`incident_connector_dispatches_total{connector,result}`) but never fail the triage path. Unknown names in `INCIDENT_CONNECTORS` fail startup fast. R3 ships only the `audit` connector; Slack/Jira adapters implement the same contract later.

## Expected Integration Points

- `platform-gateway` is the portal-facing proxy: it resolves operator identity, enforces the `incident:*` policy actions, and forwards queries/reports/triage with its service credential (triage additionally relays `X-User-ID` and the operator's delegated bearer)
- `tool-gateway` registers the read-only `incidents.list` / `incidents.get` tools against `INCIDENT_QUERY_CLIENTS`; no mutating incident tool exists (SPEC-007 invariant)
- `agent-platform` runs the triage turn in session `incident-<id>` and carries the triage-report output discipline in its system prompt
- `audit-service` receives the `incident_triaged` structured events from the built-in connector

## Boundary

This service does not execute operational actions: ranked next steps are advisory. Acting on them is R4 (approval-gated bounded actions). It also does not authenticate end users — operator identity arrives relayed from platform-gateway.
