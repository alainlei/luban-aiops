# SPEC-067 Tasks: ServiceNow ITSM MCP-Ingestion Pilot (Read Tier)

Task states: `[ ]` pending, `[x]` done. Keep tasks small and tied to requirement IDs.

> **Provisional — do not implement.** SPEC-067 is `draft` with three unresolved Open
> Questions (OQ-1, OQ-4, OQ-5 — all PDI-gated live-target facts; OQ-2 was resolved
> 2026-10-08 by extracting the credential substrate to SPEC-068, OQ-3 on 2026-10-07,
> and OQ-6 moved to SPEC-068), so this list is provisional and may change when they are
> resolved at approval. R-1 is no longer built here — it is a dependency on
> [SPEC-068](../SPEC-068-outbound-execution-credential-schemes/spec.md). Nothing here is
> authorized: approval, implementation, commit/push, deployment, and any version bump
> are each separate authorization boundaries. **Stage 0 is read-only and is the first
> thing to execute once the spec is approved** — the ServiceNow connector (Stage 2)
> depends on the auth-scheme fact Stage 0 pins, so no target-specific implementation
> should start before Stage 0 closes.

## Stage 0 — Verify (read-only; resolves OQ-1, OQ-4, OQ-5; validates the OQ-3 transport decision; confirms the SPEC-068 dependency)

- [ ] Pin ServiceNow's actual auth scheme for the target surface (its MCP server
      and/or REST) (OQ-1) — record it against R-1's `scheme` vocabulary
      (`docs/specs/SPEC-067-*/spec.md`).
- [ ] Fix the read-tier ServiceNow operation set + each tool's argument-validation
      shape (OQ-4) — record against R-2/R-3.
- [ ] Establish dev-cluster validation feasibility vs a real tenant/PDI (OQ-5) —
      record the mock-target fallback decision against the plan's Test Strategy.
- [ ] Confirm SPEC-068 (the extracted credential substrate, OQ-2 resolved 2026-10-08)
      is approved/delivered before this pilot authenticates a live target, and that
      OQ-1's scheme is one SPEC-068 already ships.
- [ ] Validate the OQ-3 transport decision on the target (resolved 2026-10-07):
      ServiceNow's own MCP server is GA/enabled on the instance release, exposes the
      needed ITSM read tools, and accepts a bearer/OAuth2 credential we can issue —
      else take the REST/Table-API fallback.
- [ ] Pin the official `mcp` Python SDK version and run the supply-chain/license
      review before adding it as a direct tool-gateway dependency.

## R-1: Outbound execution credential (dependency on SPEC-068 — not built here)

The credential-scheme extension was extracted to
[SPEC-068](../SPEC-068-outbound-execution-credential-schemes/spec.md) (OQ-2, resolved
2026-10-08); its parsing, token client, resolver seam, redaction, fail-closed, and
provisioning tasks (and OQ-6) live in SPEC-068's `tasks.md`.

- [ ] Gate: SPEC-068 is approved/delivered before this pilot authenticates a live
      target; the ServiceNow connector resolves its credential through SPEC-068's
      resolver seam (no pilot-local re-implementation).

## R-2: ServiceNow read-tier ingestion connector beneath the gateway

- [ ] Add the official `mcp` SDK as a direct tool-gateway dependency
      (`products/tool-gateway/pyproject.toml` + `uv.lock`; kernel lockfile untouched).
- [ ] Add the MCP ingestion adapter that consumes ServiceNow's own MCP server and
      maps discovered tools into the SPEC-007 `BaseTool`/`ToolDefinition`/`ToolRegistry`
      seam, admitting only policy-named tools and treating server metadata as untrusted
      (`products/tool-gateway/src/tool_gateway/`).
- [ ] Authenticate the MCP session via the R-1 credential scheme; implement the
      REST/Table-API fallback connector for the Stage-0 fallback path.
- [ ] Wire calls through the existing signed-tool path (SPEC-037); confirm no new
      kernel seam and the kernel is never an MCP client.
- [ ] Tests: tools register and are callable; read-tier-only (no mutating operation
      exposed); server-advertised metadata never sets tier/auto-approves; requester +
      acting-service identity carried to the target (`products/tool-gateway/tests/`).

## R-3: Deny-by-default policy coverage for ServiceNow tools

- [ ] Name each ServiceNow read tool at read tier in the canonical bundle
      (`shared/shared-contracts/policies/`); sync via `make sync-policy`.
- [ ] Add policy scenario coverage; keep `make validate-policy-scenarios`,
      `make validate-policy`, and `make policy-diff` green.

## R-4: Audit fidelity for external ingestion

- [ ] Emit requester + acting-service identity + target system + tool name + outcome
      per ServiceNow call (`products/tool-gateway/`).
- [ ] Tests: audit record carries all five fields; no secret/token/`client_secret`
      appears in audit or logs (`products/tool-gateway/tests/`).

## R-5: Fail-closed and no-fabrication guardrail

- [ ] Map transport/timeout/HTTP-error to a failed outcome with a reason + a
      target-unavailable audit attribution; never an empty "success"
      (`products/tool-gateway/`).
- [ ] Tests: simulated outage/timeout yields a failed outcome, not a fabricated result
      (`products/tool-gateway/tests/`).

## R-6: Secret provisioning and overlay wiring

- [ ] Deliver the new credential fields (`scheme`, `token_url`, `client_id`,
      `client_secret`) through the `sync-*.sh` model — never hand-edited in a consumer
      copy (`shared/platform-ops/`).
- [ ] Wire the ServiceNow credential set into the dev-k8s overlay; keep
      `make overlays` and `make validate-secret-vocabulary` green
      (`shared/platform-ops/gitops/dev-k8s/`).

## Delivery Gate

- [ ] Stage 0 facts recorded and all remaining Open Questions resolved in `spec.md`
      (OQ-2 resolved 2026-10-08, OQ-3 on 2026-10-07, OQ-6 moved to SPEC-068; OQ-1,
      OQ-4, OQ-5 still to pin).
- [ ] SPEC-068 (the outbound credential substrate) delivered — this pilot's connector
      depends on its resolver seam.
- [ ] All acceptance criteria in `spec.md` verified; `make verify` green (incl.
      `portal-test`, `validate-policy-scenarios`, `validate-secret-vocabulary`,
      `overlays`).
- [ ] `products/tool-gateway/uv.lock` regenerated with the direct `mcp` dependency
      (kernel lockfile untouched); dependency review recorded.
- [ ] Living state docs updated (see spec `Impact`): `products/tool-gateway/README.md`,
      `docs/agentic-aiops-platform/architecture.md`, delivery-roadmap R6 status,
      `identity-and-authorization-design.md` §Service Identity Model.
- [ ] `CHANGELOG.md` entry added referencing SPEC-067; `VERSION` bumped in lockstep
      (separate authorization).
- [ ] Spec index in `docs/specs/README.md` updated; spec status set to `delivered`.
