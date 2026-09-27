# v0.43.1 — Clock-Sensitive Document Fixture Fix

Date: 2026-09-27
Release type: patch (test-only — no product code, routes, actions, event
types, contracts, schemas, audit changes, or execution paths)

## Summary

Two agent-platform operation-document tests carried hardcoded `created_at`
fixtures dated `2026-08-27`. The operation-document store sweeps rows older
than `RETENTION_DAYS` (30) on every write, so those fixtures were only valid
inside a 30-day window that closed on 2026-09-26 — the day v0.43.0 shipped.
From 2026-09-27 onward the records aged out of retention on insert, the
listing returned empty, and both assertions failed. This patch makes the two
fixtures clock-relative so they are stable regardless of run date. It is a
test-hygiene fix only; no shipped behaviour changes.

## The defect

- `tests/test_documents.py::TestDocumentSummary::test_legacy_record_degrades_without_summary`
  seeded a legacy record with `"created_at": "2026-08-27T08:00:00Z"` directly
  through `OPERATION_DOCUMENT_STORE.create(...)`. The write-time retention
  sweep dropped it, so `[row] = response.json()["documents"]` unpacked zero
  items.
- `tests/test_operation_documents.py::TestInMemoryStore::test_list_for_owner_is_owner_scoped_and_newest_first`
  seeded `doc-1`/`doc-2` with `2026-08-27T08:00:00Z`/`…T09:00:00Z`; both were
  swept, so the newest-first ordering assert compared `[]` against
  `["doc-2", "doc-1"]`.

These were **pre-existing, clock-sensitive** failures — not introduced by any
dependency change. They reproduce identically on the v0.43.0 lockfile and are
purely a function of the wall clock crossing the fixtures' 30-day retention
horizon.

## The fix

Both tests now derive their timestamps from `datetime.now(timezone.utc)` minus
a small offset, preserving the intended ordering (`doc-2` newer than `doc-1`)
while staying well inside the retention window. This mirrors the pattern
already used and commented in `test_cap_evicts_oldest_per_owner`, which had
been written clock-relative for exactly this reason.

Deliberately **left unchanged** (inert — they never pass through the retention
sweep):

- The `INCIDENT_BUNDLE` provenance dates (`incident.created_at`,
  `report.generated_at`, `dispatch.created_at`) in `test_documents.py` — these
  are incident content fields, not the operation document's own swept
  timestamp.
- `test_load_maps_row`'s `2026-08-27` datetimes in `test_operation_documents.py`
  — a Postgres fake-driver row whose assertion checks deterministic string
  formatting, with no store write and no sweep.

## Verification

- The two previously-failing tests pass; the full agent-platform suite is green
  under frozen sync.
- Full root `make verify` gate at 0.43.1 is green (all eight product suites,
  Kustomize overlays, policy + policy-scenario + version-lockstep +
  secret-vocabulary + password-policy validations, the local secret-delivery
  demo, the operator-portal vitest suite and production build, and the
  SPEC-063 execution-failure campaign).

## Posture

No behavior, contract, policy, audit, schema, or execution change. The seven
products not under test move on version lockstep only. Identity, policy,
audit, and execution safety semantics are unchanged.
