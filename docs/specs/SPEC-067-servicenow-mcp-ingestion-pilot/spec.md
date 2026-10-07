# SPEC-067: ServiceNow ITSM MCP-Ingestion Pilot (Read Tier)

## Status

- status: `draft`
- owner: luban-platform-team
- created: 2026-10-06
- release slice: **R6 — External System Integration via MCP Ingestion** (first slice;
  see the [delivery roadmap](../../agentic-aiops-platform/delivery-roadmap.md#r6-external-system-integration-via-mcp-ingestion))
- target version: unversioned while `draft` — R6 has no approved slice yet, so the
  version is pinned only at approval (the platform is at v0.46.0; R5 closed at
  v0.45.0 and SPEC-066 shipped standalone at v0.46.0).
- related ADRs: **none at draft.** Adopting the official MCP SDK as the ingestion
  transport (OQ-3, resolved 2026-10-07) is recorded here; whether it also merits its
  own ADR is an approval-time call. The outbound-credential acquisition-locus ADR
  trigger (Option A connector-local vs B/C centralized) now lives in
  [SPEC-068](../SPEC-068-outbound-execution-credential-schemes/spec.md), where this
  spec's original R-1 was extracted; this pilot consumes that substrate and introduces
  no signing authority of its own.
- lineage: promoted from the
  [MCP ingestion spike](../../workspace/mcp-ingestion-spike.md) §2 (the
  gateway-as-client seam, ServiceNow-first staging), §5 (the credential/audience
  boundary), and §6 (the sequencing that makes the credential model the first
  slice), and from the
  [machine-consumer credential memo](../../workspace/machine-consumer-credential-model-spike.md)
  §3–§4 (the `credential_set` Basic-only gap and the outbound plane) and §6 (the
  recommendation this spec enacts). **The outbound execution-credential extension
  originally drafted as this spec's R-1 was extracted to
  [SPEC-068](../SPEC-068-outbound-execution-credential-schemes/spec.md) on 2026-10-08
  (OQ-2 resolved); SPEC-068 extends SPEC-049 R-5** (the `credential_set` mechanism)
  additively, and this pilot now **depends on** that substrate rather than defining it.
  Builds on
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
> scope questions to "the first pilot spec" — i.e. to this document. Three Open
> Questions therefore block `approved` — OQ-1, OQ-4, and OQ-5, all PDI-gated
> live-target facts. OQ-2 (substrate-vs-pilot coupling) was resolved 2026-10-08 by
> extracting the credential extension to SPEC-068; OQ-3 (transport) was resolved
> 2026-10-07; OQ-6 (provisioning) moved to and was resolved in SPEC-068.
> `plan.md`/`tasks.md` stay banner-marked provisional until the remaining three are
> resolved and ratified. None of the three blocks SPEC-068 — which is exactly why the
> substrate was extracted: OQ-1 now only *selects* among schemes SPEC-068 already
> ships, and OQ-4/OQ-5 scope and validate this pilot's live target.

## Summary

Give operators real read-only ServiceNow ITSM actions through the platform's
existing governed tool path — consuming ServiceNow's **own** MCP server via the
official `mcp` Python SDK behind a gateway-owned adapter. This pilot **depends on**
[SPEC-068](../SPEC-068-outbound-execution-credential-schemes/spec.md) — the
target-agnostic outbound execution-credential substrate (bearer / OAuth2
`client_credentials`) extracted from this spec's original R-1 — which lands first and
is reused by every future ingestion pilot. This is R6's first *target* slice; SPEC-068
is the enabling substrate it consumes.

## Motivation

- **The trigger is met.** The MCP-ingestion backlog row's promotion trigger
  ("operations names a concrete external target system to expose as MCP tools")
  fired on 2026-09-30 when operations named three targets — ServiceNow ITSM,
  Ansible runbooks, and Windows UI automation. ServiceNow is the first
  risk-ordered pilot (structured REST/OAuth API, read tier first, real operations
  value, no arbitrary host-code-execution risk).
- **The outbound credential gap is the real prerequisite — and is delivered by
  SPEC-068.** Today `products/tool-gateway/src/tool_gateway/tools/credential_sets.py`
  enforces `REQUIRED_FIELDS = ("username", "password")` and `http_connector._resolve_auth`
  returns only `httpx.BasicAuth`; there is no bearer or OAuth2 token acquisition
  anywhere in `products/`. A real ServiceNow (or any modern SaaS) surface will not
  authenticate with Basic, so the pilot cannot proceed without extending the credential
  vocabulary. That extension was extracted to
  [SPEC-068](../SPEC-068-outbound-execution-credential-schemes/spec.md) (the *External
  Execution Identity* plane of the
  [identity model](../../agentic-aiops-platform/identity-and-authorization-design.md)
  §Service Identity Model — **not** the parked inbound machine-consumer grant), so this
  pilot consumes it as a dependency.
- **Why this release slice is the right time.** R5 closed at v0.45.0; SPEC-066
  shipped standalone at v0.46.0. R6 is the next theme the trigger-gated backlog
  promotes. The credential substrate (SPEC-068) was split out precisely because it is
  unblocked, well-understood, and prerequisite to all three named pilots — it can be
  approved and shipped while this ServiceNow pilot waits on its PDI-gated Stage-0.

## Requirements

Each requirement is stable once the spec is `approved` and carries testable
acceptance criteria. R-1 is a dependency pointer to SPEC-068 (decision-ready there);
R-2–R-6 are provisional on the Open Questions and are written to be finalized at
approval.

### R-1: Outbound execution credential (delivered by SPEC-068)

The credential-scheme extension this pilot needs — an optional per-set `scheme`
(`basic` | `bearer` | `oauth2_client_credentials`) plus a connector-local OAuth2 token
client behind a reusable auth-resolution seam — was **extracted to
[SPEC-068](../SPEC-068-outbound-execution-credential-schemes/spec.md)** on 2026-10-08
(OQ-2 resolved) so the target-agnostic substrate can be approved and shipped
independent of this pilot's PDI-gated Stage-0. SPEC-067 no longer defines that
capability; it **consumes** it.

Acceptance criteria:

- SPEC-068 is delivered (or at least approved and built) before this pilot's connector
  authenticates a live target: the ServiceNow MCP/REST session resolves its credential
  through SPEC-068's resolver seam, never a pilot-local re-implementation.
- OQ-1 (ServiceNow's actual scheme) selects **among** the schemes SPEC-068 already
  ships (`bearer` or `oauth2_client_credentials`). If Stage-0 finds ServiceNow requires
  a scheme SPEC-068 does not yet build (e.g. mTLS-only), that reopens SPEC-068's scope
  in a follow-up rather than being special-cased here.
- SPEC-068's secret-handling invariants (redaction, fail-closed, no secret in
  audit/logs) apply to this pilot's calls by inheritance; R-4 asserts them for the
  ServiceNow path specifically.

### R-2: ServiceNow read-tier ingestion connector beneath the gateway

Add a ServiceNow ingestion client owned by tool-gateway that registers read-tier
tools into the same registry as native tools, reusing the SPEC-007
`BaseTool`/`ToolDefinition`/`ToolRegistry` seam. The transport consumes
**ServiceNow's own MCP server** through the **official `mcp` Python SDK**, wrapped
in a gateway-owned ingestion adapter that keeps every governance decision
(classification, policy, redaction, audit) tool-gateway-side. The `mcp` dependency
is added to **tool-gateway only**; the agent-platform kernel never becomes an MCP
client. *(Transport direction resolved 2026-10-07 — OQ-3; scope still provisional
on OQ-4.)*

Acceptance criteria:

- ServiceNow read tools register in the gateway registry and are callable by the
  kernel through the existing signed-tool path (SPEC-037) with no new kernel seam.
- Each call carries the requester identity and the acting service identity to the
  target, per the identity model's three-plane logging.
- No write/mutating ServiceNow operation is exposed in this slice (read tier only).
- The connector talks to ServiceNow's own MCP server via the official `mcp` SDK;
  `mcp` is a direct dependency of tool-gateway only, and the MCP protocol is never
  hand-rolled. A hand-rolled REST/Table-API connector is the documented **fallback**
  if Stage-0 (OQ-1/OQ-4) finds the target instance's MCP server unavailable,
  preview-only, or short of the needed read coverage.
- The MCP session authenticates using the R-1 credential scheme (bearer/OAuth2); no
  credential or token crosses the adapter into a tool result or log.

### R-3: Deny-by-default policy coverage for ServiceNow tools

ServiceNow tools are deny-by-default until the policy bundle names them, and each
named read tool resolves to the correct tier.

Acceptance criteria:

- An unlisted ServiceNow tool is denied (deny-by-default preserved).
- **Tool metadata advertised by the MCP server is untrusted input.** The adapter
  admits only tools explicitly named in the policy bundle and never auto-registers
  whatever the server advertises; a server-declared annotation, `readOnlyHint`, or
  description never sets a tool's tier or grants approval (the MCP-exposure spike's
  "remote annotations never auto-approve" invariant, applied to ingestion).
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
- **Outbound credential acquisition locus.** Centralizing token acquisition
  (identity-broker or K8s workload identity) is out of scope for the substrate this
  pilot consumes — see
  [SPEC-068](../SPEC-068-outbound-execution-credential-schemes/spec.md)'s Non-Goals
  (Option A connector-local is the default; B/C would require their own ADR).
- **Hand-rolling the MCP protocol, or adopting a third-party ServiceNow MCP
  *server*.** The official `mcp` Python SDK is the transport (OQ-3, resolved
  2026-10-07); the protocol is never re-implemented here. We consume ServiceNow's
  **own** MCP server — not a community/marketplace one (supply-chain + license
  risk, an extra stateful deployment, and it would re-expose our credential to a
  component we do not control).

## Impact

- products touched: `products/tool-gateway` (a new MCP ingestion adapter + ServiceNow
  connector, tool registration, and a new **direct `mcp` dependency** in
  tool-gateway's `pyproject.toml`/`uv.lock` — the kernel's separate lockfile is
  untouched); `shared/shared-contracts/policies` (ServiceNow tool names/tiers);
  `shared/platform-ops/gitops/dev-k8s` (overlay + the ServiceNow credential-set entry).
  The outbound-credential code (`credential_sets.py`, `http_connector.py`,
  `oauth_client.py`) is delivered by **SPEC-068**, on which this pilot depends.
- contracts touched: the policy bundle (new read-tier ServiceNow tool names). The
  credential-file shape and any secret-vocabulary work belong to SPEC-068.
- identity / policy / audit / execution safety impact: **consumes** SPEC-068's outbound
  execution credential (the External Execution Identity's first concrete form); audit
  gains external-target attribution; read-tier only, so no new HITL surface;
  fail-closed and no-fabrication preserved.
- living state docs to update on delivery: `products/tool-gateway/README.md` (tool
  surface + the credential scheme), `docs/agentic-aiops-platform/architecture.md`
  (tool-gateway section), the delivery-roadmap R6 status, and
  `identity-and-authorization-design.md` §Service Identity Model (record the
  outbound credential landing as the External Execution Identity's first concrete
  credential form).

## Open Questions

These block `approved` and must all be resolved before approval. **OQ-2 and OQ-3 are
resolved and OQ-6 moved to SPEC-068; the remaining three — OQ-1, OQ-4, OQ-5 — are open,
and all three are PDI-gated live-target facts** (Stage-0 verification, not design
preferences). None of the three blocks SPEC-068.

- **OQ-1 (fact, PDI-gated):** What is ServiceNow's actual auth scheme for the target
  surface (its MCP server and/or REST) — static bearer, OAuth2 `client_credentials`,
  mTLS, or Basic? This now **selects among the schemes SPEC-068 already ships** (and
  confirms whether the pilot needs the token client at all); it no longer defines the
  substrate's shape, which is why SPEC-068 is approvable without it.
- **OQ-2 (architectural fork) — RESOLVED 2026-10-08 (operator decision).** Extract
  the credential-scheme extension into a standalone target-agnostic substrate spec —
  **[SPEC-068](../SPEC-068-outbound-execution-credential-schemes/spec.md)** — so the
  reusable capability is not bound to this pilot's PDI-gated fate (the SPEC-007
  tool-framework precedent: land the reusable seam first). R-1 above is now a
  dependency pointer, and SPEC-068 can be approved and shipped during the ServiceNow
  waitlist.
- **OQ-3 (dependency) — RESOLVED 2026-10-07 (operator decision).** Adopt the
  official `mcp` Python SDK as the ingestion transport against **ServiceNow's own**
  MCP server, behind a gateway-owned governance adapter; add `mcp` as a direct
  dependency of tool-gateway only; keep a hand-rolled REST/Table-API connector as
  the fallback. Never hand-roll the protocol and never adopt a third-party
  ServiceNow MCP server. Governance stays tool-gateway-side regardless of transport.
  Stage-0 (OQ-1/OQ-4/OQ-5) still gates feasibility: if the target instance's MCP
  server is not GA/enabled or lacks the needed read coverage, the REST fallback is
  taken. This reverses the drafting-time lean in the exposure spike's "don't take
  the dependency until it earns its keep" posture — overridden because ServiceNow now
  ships an official MCP server and an official maintained SDK exists.
- **OQ-4 (scope):** Which ServiceNow read-tier operations are in scope (incident
  query, CMDB read, user/assignment lookup, attachment read?) and what are their
  policy tier and argument-validation shape?
- **OQ-5 (fact, go/no-go):** Can the pilot be validated against the local dev-k8s
  cluster, or does it require a real ServiceNow tenant / Personal Developer
  Instance? The MCP-ingestion spike §2 named dev-cluster feasibility a go/no-go
  gate for the theme.
- **OQ-6 (provisioning) — MOVED to SPEC-068 (resolved there 2026-10-08).** The
  credential-field provisioning question travels with the extracted substrate: SPEC-068
  R-5 confirms the new fields ride the existing file-mounted `credential-sets.json` +
  `sync-browser-credentials.sh` model, and R-4 confirms `make validate-secret-vocabulary`
  needs **no** new canonical field set (the validator pins redaction vocabularies, not
  credential field names).

## Changelog

- 2026-10-08: **OQ-2 resolved by operator decision — extract the credential
  substrate.** The outbound execution-credential extension originally drafted as R-1
  was extracted to a standalone target-agnostic spec,
  [SPEC-068](../SPEC-068-outbound-execution-credential-schemes/spec.md), so it can be
  approved and shipped independent of this pilot's PDI-gated Stage-0. R-1 became a
  dependency pointer; OQ-6 (provisioning) moved to and was resolved in SPEC-068; the
  title, Status (ADRs + lineage), approval note, Summary, Motivation, Non-Goals,
  Impact, and the Open Questions were updated accordingly. Three Open Questions remain
  (OQ-1, OQ-4, OQ-5), all PDI-gated. Spec remains `draft`. No implementation.
- 2026-10-07: **OQ-3 resolved by operator decision** — adopt the official `mcp`
  Python SDK as the ingestion transport against ServiceNow's own MCP server, behind
  a gateway-owned governance adapter (dependency added to tool-gateway only), with a
  hand-rolled REST/Table-API fallback; never hand-roll the protocol, never adopt a
  third-party ServiceNow MCP server. Amended R-2 (transport + fallback + credential
  wiring), R-3 (untrusted server metadata never auto-registers or sets tier), the
  Non-Goals, Impact, Summary, the approval note, and the Open Questions preamble
  accordingly. Spec remains `draft` — five Open Questions still block `approved`. No
  implementation.
- 2026-10-06: created as `draft`; full scaffold (`spec.md` + `plan.md` +
  `tasks.md`) authored together per the SPEC-064/065/066 precedent, with
  `plan.md`/`tasks.md` banner-marked provisional because six Open Questions block
  `approved` and the source memos authorize no implementation.
