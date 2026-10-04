# Audit Service

## Purpose

`audit-service` is the durable home for the platform audit trail (SPEC-013).
It ingests structured audit events from seven emitters (`tool-gateway`,
`platform-gateway`, `identity-service`, `agent-service`, `skills-hub`,
`incident-service`, and `execution-runtime`), retains them in a retention-bounded store
(`AUDIT_STORE_BACKEND`: `memory` for tests/dev, `postgres` for deployed
environments), and exposes a permission-scoped query API proxied to the
portal through `platform-gateway` behind the `audit:read` policy action.

## Boundary

- Ingests and serves audit events only; it never authorizes business actions.
- Stores what emitters send (post-redaction payloads); it performs no
  redaction of its own.
- User-level authorization for the query path is enforced by
  `platform-gateway`; the service itself authenticates registered platform
  callers via the SPEC-008/009 service-identity credential vocabulary.

## Key Surface

- `POST /api/v1/audit/events` — authenticated batch ingest (capped by
  `AUDIT_MAX_BATCH`); malformed events rejected with 400 and counted
- `GET /api/v1/audit/events` — filtered, newest-first cursor-paginated
  query (proxied by `platform-gateway` under `/api/v1/audit/*`)
- `/health`, `/health/ready`, `/metrics` — store backend/readiness,
  ingest and query counters, retention window, and store size
- Retention background task: `AUDIT_RETENTION_DAYS` window eviction plus
  `AUDIT_MAX_EVENTS` hard cap; eviction never blocks ingest
