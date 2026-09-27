---
kind: design
name: SPEC-063 crash-safe execution built on durable single-use claims with Postgres-backed admission
source: session
category: adr
---

# SPEC-063 crash-safe execution built on durable single-use claims with Postgres-backed admission

_Source: coding plans from commit period 00186fb → 3f94385 — records intent at planning time; the implementation may lag or differ._

**Status:** accepted

## Context
Execution paths needed to survive process crashes while preserving single-use guarantees for both execution IDs and approved-call identities. The existing plan references ADR-0013 as the approved architectural trade-off.

## Decision drivers
- crash safety without claiming exactly-once business effects
- fail-closed admission backed by real Postgres readiness checks
- bounded uncertainty rather than perfect ordering
- no automatic retries or queue-based scaling in scope

## Considered options
- **In-memory claim tracking with optimistic retry** _(rejected)_ — pros: simple; cons: lost on crash; cannot prove single-use across restarts
- **Durable signed v3 requests + immutable intents/claims in Postgres with mandatory durable receipt before authoritative response** — pros: survives process death; unique constraints protect execution ID and approved-call identity; late/conflicting results preserved with bounded uncertainty; cons: requires Postgres, epoch tracking, migration/cutover, and explicit operational proof
- **Queue-based exactly-once semantics** _(rejected)_ — pros: cleaner ordering; cons: out of scope; adds queue infrastructure and stronger-than-supported guarantees

## Decision
Implement SPEC-063 using signed v3 requests carrying expiry/run/epoch identity, immutable intents and unique claims protecting execution ID and approved-call identity, and a mandatory durable receipt before returning an authoritative response. Worker outcomes preserve late/conflicting results under bounded uncertainty; no mutation retry or takeover is allowed. Secret release requires verified original durable success.

## Consequences
Requires disposable Postgres 16 harness, independent worker processes, B0–B5 barriers, fault proxies, and negative controls. Verification demands running race scenarios ≥20 times and demonstrating that unsafe negative controls fail. Cutover/rollback/restore must be mutation-disabled and externally epoch-checked. MCP, queues/scaling, and automatic retries remain explicitly out of scope.