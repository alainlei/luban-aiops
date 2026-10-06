# SPEC-067: ServiceNow ITSM MCP-Ingestion Pilot (Read Tier) And The Outbound Execution-Credential Scheme Extension It Requires

## Status

- status: `draft`
- owner: luban-platform-team
- created: 2026-10-06
- release slice: **R6 — External System Integration via MCP Ingestion** (first slice;
  see the [delivery roadmap](../../agentic-aiops-platform/delivery-roadmap.md#r6-external-system-integration-via-mcp-ingestion))
- target version: unversioned while `draft` — R6 has no approved slice yet, so the
  version is pinned only at approval (the platform is at v0.46.0; R5 closed at
  v0.45.0 and SPEC-066 shipped standalone at v0.46.0).
- related ADRs: **none at draft.** An ADR becomes required **only if** token
  acquisition is centralized (Option B/C in
  [the credential memo](../../workspace/machine-consumer-credential-model-spike.md)
  §4) rather than connector-local (Option A); the connector-local direction reuses
  ADR-0004's delegation vocabulary without a new signing authority and needs no ADR.
- lineage: promoted from the
  [MCP ingestion spike](../../workspace/mcp-ingestion-spike.md) §2 (the
  gateway-as-client seam, ServiceNow-first staging), §5 (the credential/audience
  boundary), and §6 (the sequencing that makes the credential model the first
  slice), and from the
  [machine-consumer credential memo](../../workspace/machine-consumer-credential-model-spike.md)
  §3–§4 (the `credential_set` Basic-only gap and the outbound plane) and §6 (the
  recommendation this spec enacts). **R-1 extends SPEC-049 R-5** (the
  `credential_set` mechanism) additively. Builds on
  [SPEC-007](../SPEC-007-tool-execution-framework/spec.md) (the
  `BaseTool`/`ToolRegistry` seam the ingestion connector reuses) and is the
  **opposite direction** from the parked
  [MCP-exposure spike](../../workspace/mcp-exposure-spike.md) (gateway-as-MCP-*server*,
  never promoted to a spec): ingestion reuses the platform's tool contract, never an
  exposure path.

> **Approval note (SDD discipline).** The full scaffold (`spec.md` + `plan.md` +
> `tasks.md`) was authored together per the SPEC-064/SPEC-065/SPEC-066
> same-session precedent. At drafting this spec is deliberately **not**
> decision-complete: the source memos authorize **no implementation** and hand the
> scope questions to "the first pilot spec" — i.e. to this document. Six Open
> Questions therefore block `approved`, and `plan.md`/`tasks.md` are banner-marked
> provisional until they are resolved and the operator ratifies the resolutions.
> The largest is OQ-1: the credential shape R-1 builds depends on ServiceNow's
> **actual** auth scheme, which is a Stage-0 fact to pin, not a design preference.

## Summary

Give operators real read-only ServiceNow ITSM actions through the platform's
existing governed tool path — and, as the prerequisite every MCP-ingestion pilot
shares, extend the gateway's outbound credential model beyond HTTP Basic so a
connector can authenticate to a modern API (bearer / OAuth2 `client_credentials`).
This is R6's first slice: the credential extension (R-1) is the natural opening
move because every pilot depends on it and nothing else in the platform does.

## Motivation

- **The trigger is met.** The MCP-ingestion backlog row's promotion trigger
  ("operations names a concrete external target system to expose as MCP tools")
  fired on 2026-09-30 when operations named three targets — ServiceNow ITSM,
  Ansible runbooks, and Windows UI automation. ServiceNow is the first
  risk-ordered pilot (structured REST/OAuth API, read tier first, real operations
  value, no arbitrary host-code-execution risk).
- **The outbound credential gap is the real prerequisite.** Today
  `products/tool-gateway/src/tool_gateway/tools/credential_sets.py` enforces
  `REQUIRED_FIELDS = ("username", "password")` and `http_connector._resolve_auth`
  returns only `httpx.BasicAuth`. There is no bearer or OAuth2 token acquisition
  anywhere in `products/`. A real ServiceNow (or any modern SaaS) REST surface will
  not authenticate with Basic, so the pilot cannot proceed without extending the
  credential vocabulary. This is the *External Execution Identity* plane of the
  [identity model](../../agentic-aiops-platform/identity-and-authorization-design.md)
  §Service Identity Model — **not** the parked inbound machine-consumer grant.
- **Why this release slice is the right time.** R5 closed at v0.45.0; SPEC-066
  shipped standalone at v0.46.0. R6 is the next theme the trigger-gated backlog
  promotes, and the credential extension is unblocked, well-understood, and
  prerequisite to all three named pilots.

## Requirements

Each requirement is stable once the spec is `approved` and carries testable
acceptance criteria. R-1 is decision-ready; R-2–R-6 are provisional on the Open
Questions and are written to be finalized at approval.

### R-1: Outbound execution-credential scheme extension (additive)

Extend the tool-gateway credential model with an optional per-set `scheme` so a
connector can authenticate to a target beyond HTTP Basic, plus a connector-local
token acquisition path. Existing `basic` sets are byte-for-byte unchanged.

Acceptance criteria:

- A `basic` credential set behaves identically to pre-SPEC-067 (regression test on
  the existing `admin-portal` set and `web.fill_credential` path).
- A `bearer` set attaches `Authorization: Bearer <token>` on the outbound call, and
  the token never appears in logs, tool results, snapshots, or audit (redaction
  test mirroring SPEC-009 R-1's deterministic tool-output redaction and the
  `make validate-secret-vocabulary` gate).
- An `oauth2_client_credentials` set acquires a token from a configured token URL,
  caches it in memory until near expiry, and never persists or logs the
  `client_secret` or the acquired `access_token`.
- A missing, malformed, or expired credential set **fails closed** — no
  unauthenticated fallback — preserving the existing `CredentialSetError` contract.
- The exact `scheme` vocabulary (`basic` | `bearer` | `oauth2_client_credentials` |
  …) is finalized against OQ-1 (ServiceNow's real scheme); the field is additive
  and defaults to `basic`, so no existing set changes meaning.

### R-2: ServiceNow read-tier ingestion connector beneath the gateway

Add a ServiceNow ingestion client owned by tool-gateway that registers read-tier
tools into the same registry as native tools, reusing the SPEC-007
`BaseTool`/`ToolDefinition`/`ToolRegistry` seam. The agent-platform kernel never
becomes an MCP client. *(Provisional on OQ-3, OQ-4.)*

Acceptance criteria:

- ServiceNow read tools register in the gateway registry and are callable by the
  kernel through the existing signed-tool path (SPEC-037) with no new kernel seam.
- Each call carries the requester identity and the acting service identity to the
  target, per the identity model's three-plane logging.
- No write/mutating ServiceNow operation is exposed in this slice (read tier only).
- The connector is hand-rolled over ServiceNow's REST/OAuth surface; no generic
  `mcp` client dependency is added (OQ-3).

### R-3: Deny-by-default policy coverage for ServiceNow tools

ServiceNow tools are deny-by-default until the policy bundle names them, and each
named read tool resolves to the correct tier.

Acceptance criteria:

- An unlisted ServiceNow tool is denied (deny-by-default preserved).
- Each named read tool resolves to read tier; the policy-bundle scenario suite
  (`make validate-policy-scenarios`) gains coverage for the new tool names.
- `make validate-policy` and `make policy-diff` stay green after the bundle change
  is synced (authored canonically in `shared/shared-contracts/policies/`, never
  edited in place).

### R-4: Audit fidelity for external ingestion

Every ServiceNow tool call records the requester identity, the acting service
identity, the target system, the tool name, and the result outcome; secrets never
appear in audit.

Acceptance criteria:

- An audit event for a ServiceNow read carries requester + acting-service identity
  + target + tool + outcome, keeping the requester and acting-service identities
  separate per ADR-0004's `sub`-user / `act`-service delegation and the identity
  model's separate-identity logging.
- No credential secret, token, or `client_secret` appears in any audit record or
  log line (asserted alongside R-1's redaction tests).

### R-5: Fail-closed and no-fabrication guardrail

A target that is unreachable, times out, or returns an error is surfaced as a
failed outcome and never presented as a successful result.

Acceptance criteria:

- A simulated ServiceNow outage/timeout yields a failed tool outcome with a
  reason, not a fabricated or empty "success" (mirrors SPEC-058's `http.get` rule
  that "an upstream 4xx/5xx is a fact, not a tool error", and the MCP-exposure
  spike §5's fail-closed-no-fabrication posture).
- The failure is attributed in audit as a target-unavailable outcome, distinct from
  a policy denial.

### R-6: Secret provisioning and overlay wiring

The new credential fields are provisioned through the established `sync-*.sh`
model and wired into the dev-k8s overlay; nothing is edited in place.

Acceptance criteria:

- New fields (`token_url`, `client_id`, `client_secret`, `scheme`) are delivered by
  a sync script and never hand-edited in a consumer copy.
- The dev-k8s overlay wires the ServiceNow credential set; `make overlays` renders
  green.
- `make validate-secret-vocabulary` stays green (a new canonical field set is added
  if OQ-6 requires it).

## Non-Goals

- **Write-tier ServiceNow operations** (mutations). These stay behind the existing
  HITL one-gate-per-flow (ADR-0007) and signed-execution (SPEC-037) path and belong
  to a later slice, not this read-tier pilot.
- **Ansible and Windows pilots.** Risk-ordered staging puts them after ServiceNow;
  each is a separate spec (the backlog row names "one connector spec per pilot").
- **The inbound machine-consumer `client_credentials` grant / stable-API
  productization.** That is the parked, trust-model-blocked row (no human
  owner/approver); it needs a machine-*subject* token identity-broker cannot mint.
  This spec is the outbound plane and does not touch it. See the credential memo §5.
- **Gateway-as-MCP-server exposure.** That is the parked
  [MCP-exposure spike](../../workspace/mcp-exposure-spike.md) (never promoted to a
  spec), the opposite direction; this spec reuses the platform's tool contract,
  never an exposure path.
- **Centralizing token acquisition in identity-broker, or K8s workload-identity
  minting.** Only if OQ resolves to Option B/C in the credential memo §4 — which
  would require its own ADR — not the connector-local default this spec assumes.
- **A generic `mcp` client dependency.** Deferred until it earns its keep; the
  ServiceNow connector is hand-rolled over REST/OAuth.

## Impact

- products touched: `products/tool-gateway` (`tools/credential_sets.py`,
  `tools/http_connector.py`, a new ServiceNow ingestion connector, tool
  registration); `shared/shared-contracts/policies` (ServiceNow tool names/tiers);
  `shared/platform-ops/gitops/dev-k8s` (overlay + credential-set secret);
  `shared/shared-contracts/scripts` (secret vocabulary, if OQ-6 requires).
- contracts touched: the policy bundle (new read-tier ServiceNow tool names);
  the secret-literal vocabulary (new credential fields).
- identity / policy / audit / execution safety impact: introduces the platform's
  **first non-Basic outbound execution credential** (the External Execution
  Identity); audit gains external-target attribution; read-tier only, so no new
  HITL surface; fail-closed and no-fabrication preserved.
- living state docs to update on delivery: `products/tool-gateway/README.md` (tool
  surface + the credential scheme), `docs/agentic-aiops-platform/architecture.md`
  (tool-gateway section), the delivery-roadmap R6 status, and
  `identity-and-authorization-design.md` §Service Identity Model (record the
  outbound credential landing as the External Execution Identity's first concrete
  credential form).

## Open Questions

These block `approved` and must be empty before approval. OQ-1 and OQ-5 are
checkable facts (Stage-0 verification), not preferences; the rest are decisions.

- **OQ-1 (fact, blocks R-1's shape):** What is ServiceNow's actual auth scheme for
  the target REST surface — static bearer, OAuth2 `client_credentials`, mTLS, or
  Basic? This pins the R-1 `scheme` vocabulary and whether a token client is needed
  at all for the first pilot.
- **OQ-2 (architectural fork):** Keep the credential-scheme extension as R-1 of
  this pilot, or extract it into a standalone target-agnostic substrate spec first
  (the SPEC-007 tool-framework precedent) so the reusable capability is not bound
  to one target's fate? The credential memo §6 framed it as "R6's first slice,"
  which is compatible with either.
- **OQ-3 (dependency):** Confirm the ServiceNow ingestion stays hand-rolled over
  its REST/OAuth surface with no generic `mcp` client dependency, consistent with
  the exposure spike's "don't take the dependency until it earns its keep" posture.
- **OQ-4 (scope):** Which ServiceNow read-tier operations are in scope (incident
  query, CMDB read, user/assignment lookup, attachment read?) and what are their
  policy tier and argument-validation shape?
- **OQ-5 (fact, go/no-go):** Can the pilot be validated against the local dev-k8s
  cluster, or does it require a real ServiceNow tenant / Personal Developer
  Instance? The MCP-ingestion spike §2 named dev-cluster feasibility a go/no-go
  gate for the theme.
- **OQ-6 (provisioning):** Do the new credential fields extend the existing
  `sync-*.sh` vocabulary cleanly, and does `make validate-secret-vocabulary` need a
  new canonical field set?

## Changelog

- 2026-10-06: created as `draft`; full scaffold (`spec.md` + `plan.md` +
  `tasks.md`) authored together per the SPEC-064/065/066 precedent, with
  `plan.md`/`tasks.md` banner-marked provisional because six Open Questions block
  `approved` and the source memos authorize no implementation.
