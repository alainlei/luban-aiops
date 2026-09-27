---
kind: design
name: Defer secret_delivery frame emission until gated mutation commits
source: session
category: adr
---

# Defer secret_delivery frame emission until gated mutation commits

_Source: coding plans from commit period 0a22faf → 00186fb — records intent at planning time; the implementation may lag or differ._

**Status:** accepted

## Context
The previous SPEC-062 behavior emitted the `secret_delivery` frame immediately when `secrets.generate_password(handoff="portal_copy")` returned, making the Copy-password button live before the approval card was filed. This allowed an operator to redeem a password that might later be denied or fail during the gated write.

## Decision drivers
- prevent premature reveal of secrets before approval
- preserve standalone generate-and-copy flow when no gate follows
- no schema change to avoid portal/tool-gateway protocol churn

## Considered options
- **Emit at generation (current behavior)** _(rejected)_ — pros: simplest path; immediate button availability; cons: password can be redeemed before approval; risk of leaking secrets on deny/fail
- **Hold delivery in memory and release on successful commit** — pros: guarantees redemption only after approved gated call succeeds; silent burn on deny/failure/expiry; keeps frame shape unchanged; cons: requires per-stream buffering across park/resume; needs hold TTL spanning approval window; restarts lose ephemeral buffer (fail-safe expiry)

## Decision
Buffer portal_copy deliveries in a per-stream contextvar (`STREAM_PENDING_DELIVERIES`) from generation through park/resume, then emit `secret_delivery` frames only when the resumed stream yields a successful tool_result for the gated write; on deny, failure, or expiry the deliveries are silently discarded. Standalone flows without a gate still emit at stream end. A new config knob `GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS` extends the tool-gateway stash TTL to cover the full approval window.

## Consequences
No `secret_delivery` schema or portal changes; replay attaches the frame under the original `turn_index`. Production must use Redis backend so tool-gateway restarts do not drop in-flight handoffs. Ephemeral `pending_deliveries` survive agent-service restarts via re-park attachment; if lost, deliveries expire unreleased — a safe default with no leak. Version bumped 0.41.1 → 0.42.0 as an observable behavior refinement.