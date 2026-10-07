# SPEC-067 Tasks: ServiceNow ITSM MCP-Ingestion Pilot (Read Tier) And The Outbound Execution-Credential Scheme Extension It Requires

Task states: `[ ]` pending, `[x]` done. Keep tasks small and tied to requirement IDs.

> **Provisional — do not implement.** SPEC-067 is `draft` with five unresolved Open
> Questions (OQ-3, the transport decision, was resolved 2026-10-07), so this list is
> provisional and may change when they are resolved at
> approval. Nothing here is authorized: approval, implementation, commit/push,
> deployment, and any version bump are each separate authorization boundaries.
> **Stage 0 is read-only and is the first thing to execute once the spec is
> approved** — R-1's credential shape (Stage 1) depends on the auth-scheme fact
> Stage 0 pins, so no implementation should start before Stage 0 closes.

## Stage 0 — Verify (read-only; resolves OQ-1, OQ-4, OQ-5; settles OQ-2, OQ-6; validates the OQ-3 transport decision)

- [ ] Pin ServiceNow's actual auth scheme for the target surface (its MCP server
      and/or REST) (OQ-1) — record it against R-1's `scheme` vocabulary
      (`docs/specs/SPEC-067-*/spec.md`).
- [ ] Fix the read-tier ServiceNow operation set + each tool's argument-validation
      shape (OQ-4) — record against R-2/R-3.
- [ ] Establish dev-cluster validation feasibility vs a real tenant/PDI (OQ-5) —
      record the mock-target fallback decision against the plan's Test Strategy.
- [ ] Confirm the substrate-vs-pilot coupling decision (OQ-2): R-1 stays in this spec
      or is extracted into a standalone target-agnostic spec first.
- [ ] Validate the OQ-3 transport decision on the target (resolved 2026-10-07):
      ServiceNow's own MCP server is GA/enabled on the instance release, exposes the
      needed ITSM read tools, and accepts a bearer/OAuth2 credential we can issue —
      else take the REST/Table-API fallback.
- [ ] Pin the official `mcp` Python SDK version and run the supply-chain/license
      review before adding it as a direct tool-gateway dependency.
- [ ] Confirm the secret-provisioning field set and whether
      `make validate-secret-vocabulary` needs a new canonical vocabulary (OQ-6).

## R-1: Outbound execution-credential scheme extension (additive)

- [ ] Add optional per-set `scheme` (default `basic`) + per-scheme required-field
      validation in `credential_sets.py` (`products/tool-gateway/src/tool_gateway/tools/credential_sets.py`).
- [ ] Extend `_resolve_auth` with a bearer branch
      (`products/tool-gateway/src/tool_gateway/tools/http_connector.py`).
- [ ] Add the connector-local `oauth2_client_credentials` token client (fetch +
      in-memory cache + near-expiry refresh + redaction)
      (`products/tool-gateway/src/tool_gateway/tools/oauth_client.py`).
- [ ] Tests: `basic` regression is byte-identical; bearer attaches + redacts; OAuth2
      caches and never logs/persists `client_secret`/`access_token`; missing/malformed
      set fails closed (`products/tool-gateway/tests/`).

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
      (OQ-3 already resolved 2026-10-07).
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
