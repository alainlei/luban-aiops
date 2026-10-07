# SPEC-067 Plan: ServiceNow ITSM MCP-Ingestion Pilot (Read Tier) And The Outbound Execution-Credential Scheme Extension It Requires

> **Provisional — do not implement.** This plan was authored alongside `spec.md`
> at drafting time per the SPEC-064/065/066 same-session precedent. SPEC-067 is
> `draft` with **five unresolved Open Questions** (OQ-3, the transport decision,
> was resolved 2026-10-07), so everything below is a
> provisional recommendation, not an authorized contract. The credential-shape
> work in R-1 in particular cannot be finalized until **OQ-1** (ServiceNow's real
> auth scheme) is pinned as a Stage-0 fact. Nothing here is implemented: approval,
> implementation, commit/push, deployment, and any version bump are each separate
> authorization boundaries not granted by this document. **Stage 0 (verification)
> is the first thing to execute once the spec is approved.**

## Approach

The pilot is two moves stacked, not one. The first (R-1) is a target-agnostic
extension to the gateway's outbound credential vocabulary — the piece every future
ingestion pilot reuses. The second (R-2–R-6) is the ServiceNow-specific read-tier
connector that consumes it. R-1 is decision-ready from the shipped code; R-2–R-6
are provisional until Stage 0 pins ServiceNow's auth scheme, operation set, and
dev-cluster feasibility. The stages are ordered so the reusable substrate lands and
is tested before any target-specific code depends on it.

0. **Verify** (Stage 0) — read-only. Pin the three facts the memos could not
   settle from the repository because they are properties of an external system, not
   decisions: ServiceNow's auth scheme (OQ-1), the read-tier operation set (OQ-4),
   and whether the pilot can be validated against the dev cluster or needs a real
   tenant/PDI (OQ-5). Each has a named fallback in *Sequencing* so a hard-to-obtain
   fact degrades the pilot's scope rather than blocking R-1.
1. **Extend** (Stage 1, R-1) — additive `scheme` field + connector-local token
   client in tool-gateway, with redaction and fail-closed tests. `basic` unchanged.
2. **Connect** (Stage 2, R-2 + R-3) — the MCP-SDK ingestion adapter against
   ServiceNow's own MCP server (REST/Table-API fallback), reusing the SPEC-007
   registry seam, plus deny-by-default policy-bundle coverage.
3. **Attribute** (Stage 3, R-4 + R-5) — audit fidelity (requester + acting service +
   target + tool + outcome) and the fail-closed/no-fabrication guardrail.
4. **Provision** (Stage 4, R-6) — secret sync + dev-k8s overlay wiring.
5. **Deliver** (Stage 5) — living-state docs, CHANGELOG, version; separate
   authorization.

## Design Per Requirement

### R-1: Outbound execution-credential scheme extension (additive)

- affected files / modules:
  - `products/tool-gateway/src/tool_gateway/tools/credential_sets.py` — add an
    optional `scheme` key (default `basic`); make `_reload`'s required-field check
    per-scheme instead of the fixed `REQUIRED_FIELDS = ("username", "password")`.
  - `products/tool-gateway/src/tool_gateway/tools/http_connector.py` — extend
    `_resolve_auth` (today returns only `httpx.BasicAuth`) with a bearer branch.
  - a new connector-local token client module (e.g. `tools/oauth_client.py`) for the
    `oauth2_client_credentials` fetch + in-memory cache + redaction.
- chosen approach: **Option A — connector-local token client** (credential memo §4).
  The scheme vocabulary is `basic` (unchanged default) | `bearer` (static token in
  the set) | `oauth2_client_credentials` (`token_url` + `client_id` + `client_secret`
  [+ `scope`], token fetched on miss/near-expiry and cached in memory only). All
  secret handling reuses the existing never-logged, fail-closed, mtime-refreshed
  `CredentialSetStore` behavior; the token client adds the same redaction guarantees
  to the acquired `access_token`.
- alternatives considered and why rejected (at draft):
  - **Option B — centralize acquisition in identity-broker.** Rejected for the first
    pilot: it adds a new signing authority and an ADR (the memo §4 records the ADR
    trigger), which is over-scope when a connector-local client suffices. Revisit
    only if a second consumer of the same target credential appears.
  - **Option C — Kubernetes workload identity.** Rejected: the identity doc names it
    the documented *upgrade path* for the External Execution Identity, appropriate
    when cluster-to-cluster trust exists, not for a first SaaS pilot.
- **OQ-1 gate:** the exact vocabulary (does ServiceNow need `bearer`, full OAuth2, or
  something else?) is finalized against ServiceNow's real scheme in Stage 0. The
  field is additive either way, so R-1's `basic` regression is unaffected.

### R-2: ServiceNow read-tier ingestion connector beneath the gateway

- affected files / modules: a new `products/tool-gateway/src/tool_gateway/` ingestion
  subpackage (an MCP client adapter over the official `mcp` SDK + a ServiceNow
  connector); registration into the existing `ToolRegistry`; a new **direct `mcp`
  dependency** in tool-gateway's `pyproject.toml`/`uv.lock`.
- chosen approach (**OQ-3 resolved 2026-10-07**): consume **ServiceNow's own MCP
  server** through the **official `mcp` Python SDK** behind a gateway-owned adapter
  that maps each discovered server tool into a `BaseTool`/`ToolDefinition` (SPEC-007
  seam), authenticating the MCP session via the R-1 credential set (bearer/OAuth2).
  Governance stays tool-gateway-side: the adapter admits only tools explicitly named
  in the policy bundle and treats server-advertised metadata as untrusted. The kernel
  calls them through the existing signed-tool path (SPEC-037); no new kernel seam, and
  the kernel never becomes an MCP client. `mcp` is added to tool-gateway only — its
  lockfile is separate from the kernel's transitive AgentScope pin.
- alternatives: (a) a **hand-rolled REST/Table-API client** — retained as the
  documented **fallback** if Stage-0 finds the target instance's MCP server
  unavailable, preview-only, or short of read coverage; (b) a third-party ServiceNow
  MCP *server* — rejected (supply-chain/license risk, an extra stateful deployment,
  and it would re-expose our credential to a component we do not control); (c)
  hand-rolling the MCP protocol — rejected (an official maintained SDK exists).
- **OQ-4 gate:** the concrete tool set and each tool's argument-validation shape are
  fixed in Stage 0 (whether the needed reads come via the MCP server or the REST
  fallback).

### R-3: Deny-by-default policy coverage for ServiceNow tools

- affected files / modules: `shared/shared-contracts/policies/` (canonical bundle),
  synced to consumers via `make sync-policy`; the policy scenario suite.
- chosen approach: name each ServiceNow read tool in the bundle at read tier;
  unlisted tools stay denied. Add scenario coverage so `make validate-policy-scenarios`
  asserts the new names resolve as intended.

### R-4: Audit fidelity for external ingestion

- affected files / modules: the tool-gateway audit emission path, keeping the
  requester and acting-service identities separate per ADR-0004's `sub`/`act`
  delegation and the identity model's separate-identity logging.
- chosen approach: emit requester identity + acting service identity + target system +
  tool name + outcome per call; assert no secret/token/`client_secret` reaches audit.

### R-5: Fail-closed and no-fabrication guardrail

- affected files / modules: the ServiceNow connector's error handling.
- chosen approach: map transport/timeout/HTTP-error to a failed tool outcome with a
  reason and a target-unavailable audit attribution; never return an empty "success."
  Mirrors SPEC-058's `http.get` "an upstream 4xx/5xx is a fact, not a tool error" rule.

### R-6: Secret provisioning and overlay wiring

- affected files / modules: the `sync-*.sh` secret-delivery scripts;
  `shared/platform-ops/gitops/dev-k8s/` (credential-set secret + overlay);
  `shared/shared-contracts/scripts/` (secret vocabulary, if OQ-6 requires).
- chosen approach: deliver the new fields through the existing sync model (never
  hand-edited in a consumer copy); wire the ServiceNow set into dev-k8s; keep
  `make validate-secret-vocabulary` and `make overlays` green.

## Sequencing And Dependencies

1. **Stage 0 — Verify** — depends on nothing; read-only; first to execute at
   approval. Fallbacks: if OQ-1 cannot be pinned, R-1 still ships `bearer` +
   `oauth2_client_credentials` (both are standard) and the ServiceNow connector waits;
   if OQ-5 shows no dev-cluster path, the connector is validated against a local mock
   target and live ServiceNow validation becomes an operator step.
2. **Stage 1 — R-1 credential extension** — depends on Stage 0 (scheme vocabulary).
3. **Stage 2 — R-2 connector + R-3 policy** — depends on Stage 1.
4. **Stage 3 — R-4 audit + R-5 fail-closed** — depends on Stage 2.
5. **Stage 4 — R-6 provisioning + overlay** — depends on Stage 1 (fields) and Stage 2.
6. **Stage 5 — delivery boundary** — separate authorization (docs, CHANGELOG, version).

## Test Strategy

- unit tests: `credential_sets` per-scheme parsing + fail-closed on missing/malformed
  sets; `_resolve_auth` bearer branch; the token client's cache/near-expiry/redaction;
  the MCP-tool→`ToolDefinition` mapping (server metadata treated as untrusted, never
  setting tier); connector registration and read-tier-only exposure; the
  no-fabrication mapping. Redaction tests mirror SPEC-009 R-1's deterministic
  tool-output redaction.
- contract tests: policy-bundle scenarios (`make validate-policy-scenarios`),
  `make validate-policy` + `make policy-diff`, and `make validate-secret-vocabulary`.
- integration / overlay validation: `make overlays` renders the dev-k8s wiring; the
  adapter is exercised against a **local mock MCP server / mock ServiceNow target** so
  CI makes no live external call (live-tenant validation is an operator step per
  OQ-5's fallback), and the REST fallback path is covered by the same mock-target tests.

## Rollout And Migration

- deployment or configuration changes required: new credential-set fields delivered by
  a sync script + the dev-k8s overlay; a synced policy-bundle update naming the
  ServiceNow read tools.
- backward compatibility: `basic` sets are unchanged (`scheme` defaults to `basic`);
  the extension is inert until a non-`basic` set exists, so no current behavior moves.
- rollback approach: remove the ServiceNow credential set and its policy entries; the
  additive scheme code path is dead without a non-`basic` set, and the MCP adapter is
  inert without the credential set + policy entries, so rollback needs no code revert
  (the `mcp` dependency can stay pinned-but-unused or be dropped).
