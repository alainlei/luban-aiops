---
kind: design
name: Defer secret_delivery frame emission until gated mutation commits
source: session
category: adr
---

# Defer secret_delivery frame emission until gated mutation commits

_Source: coding plans from commit period 00186fb → 3f94385 — records intent at planning time; the implementation may lag or differ._

**Status:** accepted

## Context
The portal_copy flow emitted a `secret_delivery` frame immediately after password generation, making the Copy-password button live before the human-in-the-loop approval card was even filed. This exposed secrets prematurely and did not match the reset runbook's intent.

## Decision drivers
- secrets must not be visible until the approved write actually executes
- no schema or portal rendering changes
- standalone generate-and-copy (no gate) must still reveal at turn end

## Considered options
- **Emit frame at generation time (current behavior)** _(rejected)_ — pros: simplest path; portal already handles it; cons: button appears before approval; secrets can leak if the gate denies or fails
- **Buffer deliveries in agent-platform contextvars and emit only on successful resume of the gated call** — pros: keeps protocol unchanged; ties reveal to actual commit; silent burn on deny/fail/expiry; cons: requires hold TTL across tool-gateway restarts; ephemeral buffer lost on kernel restart (fail-safe burn)

## Decision
Hold portal_copy deliveries in `tools/secrets_connector.py` for `GATEWAY_SECRET_DELIVERY_HOLD_TTL_SECONDS` (default 900 s), buffer them in `STREAM_PENDING_DELIVERIES` inside `kernel_middleware`, attach them to `PendingConfirmation.pending_deliveries`, and emit the `secret_delivery` frames only when the resumed stream yields a successful tool_result for the gated write. Deny, failure, or expiry silently burns the delivery without emitting any frame.

## Consequences
The `secret_delivery` schema and portal code are untouched; replay attaches the frame under the original `turn_index`. Production must use Redis-backed delivery (`GATEWAY_SECRET_DELIVERY_BACKEND=redis`) so a tool-gateway restart does not drop an in-flight handoff. A kernel restart during approval burns the delivery — fail-safe but means the operator must regenerate.