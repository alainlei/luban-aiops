# SPEC-068: Outbound Execution-Credential Schemes (Tool-Gateway Substrate)

## Status

- status: `draft`
- owner: luban-platform-team
- created: 2026-10-08
- release slice: **R6-enabling substrate** — the target-agnostic outbound
  execution-credential extension every MCP-ingestion pilot depends on. Extracted
  from [SPEC-067](../SPEC-067-servicenow-mcp-ingestion-pilot/spec.md) R-1 so it can
  be approved and shipped **independently of any single pilot's live-system gate**
  (see the [delivery roadmap](../../agentic-aiops-platform/delivery-roadmap.md#r6-external-system-integration-via-mcp-ingestion)).
- target version: unversioned while `draft` — the version is pinned only at approval.
  The platform is at v0.46.0; like SPEC-066, this substrate is small and
  self-contained enough to ship standalone at its own bump once approved.
- related ADRs: **none.** SPEC-068 adds no new platform signing authority and mints
  no platform delegation token — it acquires a **target-issued** token via the
  standard OAuth2 `client_credentials` grant and attaches it outbound. ADR-0004's
  `sub`-user / `act`-service delegation model is unaffected (the outbound target
  credential is the *External Execution Identity*, a separate plane). An ADR becomes
  required **only if** acquisition is centralized (Option B in identity-broker, or
  Option C Kubernetes workload identity, per
  [the credential memo](../../workspace/machine-consumer-credential-model-spike.md)
  §4), each of which introduces a new minting/signing authority. This spec is the
  connector-local Option A default and needs no ADR.
- lineage: extracted from
  [SPEC-067](../SPEC-067-servicenow-mcp-ingestion-pilot/spec.md) R-1 per its OQ-2
  (operator decision 2026-10-08 to decouple the target-agnostic credential substrate
  from the ServiceNow pilot's PDI-gated live verification). Promoted from the
  [machine-consumer credential memo](../../workspace/machine-consumer-credential-model-spike.md)
  §3–§4 (the `credential_set` Basic-only gap, the outbound plane, and the
  Option A/B/C acquisition-locus fork) and §6 (the recommendation). **Extends
  [SPEC-049 R-5](../SPEC-049-browser-web-check-tools/spec.md)** (the named
  `credential_set` mechanism) additively; the first consumer is
  [SPEC-058](../SPEC-058-http-service-check-tools/spec.md)'s `http_connector`
  (`http.get`/`http.post`), and SPEC-067's ServiceNow ingestion adapter is the second.

> **Approval note (SDD discipline).** The full scaffold (`spec.md` + `plan.md` +
> `tasks.md`) was authored together per the SPEC-064/065/066/067 same-session
> precedent. Unlike SPEC-067, **no Open Question blocks `approved`**: SPEC-068 is
> target-agnostic and decision-complete, so it is ready for an approval decision
> without any live-system verification. It was extracted from SPEC-067 R-1 precisely
> so the reusable substrate can be approved and shipped during the ServiceNow PDI
> waitlist, independent of that pilot's Stage-0 facts. Approval, implementation,
> commit/push, deployment, and any version bump are each separate authorization
> boundaries **not** granted by this `draft`.

## Summary

Extend the tool-gateway's outbound credential model beyond HTTP Basic so a connector
can authenticate to a modern API — adding an optional per-set `scheme`
(`basic` | `bearer` | `oauth2_client_credentials`) and a connector-local OAuth2
`client_credentials` token client, behind one reusable auth-resolution seam. The
change is **additive and target-agnostic**: every existing `basic` set is
byte-for-byte unchanged, the extension is inert until a non-`basic` set is
provisioned, and no new dependency is introduced. This is the *External Execution
Identity*'s first concrete credential form and the prerequisite every MCP-ingestion
pilot shares.

## Motivation

- **The outbound credential gap is the real prerequisite for external integration.**
  Today `products/tool-gateway/src/tool_gateway/tools/credential_sets.py` enforces a
  fixed `REQUIRED_FIELDS = ("username", "password")` and drops every other key on
  reload, and `http_connector._resolve_auth` returns only `httpx.BasicAuth`. There is
  no bearer or OAuth2 token acquisition anywhere in `products/`. A real ServiceNow (or
  any modern SaaS) surface will not authenticate with Basic, so **no** ingestion pilot
  can proceed without extending the credential vocabulary.
- **Why a standalone substrate rather than a pilot requirement.** SPEC-067 framed this
  as its R-1 but left the coupling an open question (its OQ-2). Binding a reusable,
  target-agnostic capability to one pilot's fate would stall it behind that pilot's
  live-system gate — concretely, the ServiceNow PDI waitlist. Extracting it (the
  SPEC-007 tool-framework precedent: land the reusable seam first) lets the substrate
  be approved, built, and tested against mocks **now**, so SPEC-067 later *selects* an
  already-shipped scheme instead of waiting to define one.
- **Why this is decision-complete without the PDI.** Desk research confirms ServiceNow
  authenticates within the OAuth2 family on both paths (REST/Table API via the
  `client_credentials` grant; its own MCP server via an OAuth inbound integration) with
  no exotic-only scheme. SPEC-068 therefore ships the standard vocabulary
  target-agnostically; SPEC-067's OQ-1 (ServiceNow's *actual* scheme) only picks among
  schemes this spec already builds — it never gates the substrate.

## Requirements

Each requirement is stable once the spec is `approved` and carries testable acceptance
criteria. All five are decision-ready from the shipped code; none depends on an
external system's live facts.

### R-1: Per-set `scheme` field and generalized parsing (additive)

Generalize `credential_sets.py` from the fixed `REQUIRED_FIELDS` to a per-scheme field
model that **retains** the scheme-specific fields, and add an optional per-set `scheme`
that defaults to `basic`. Existing `basic` sets are byte-for-byte unchanged and the
extension is inert until a non-`basic` set exists.

Acceptance criteria:

- A `basic` set — or a set with no `scheme` key — parses exactly as pre-SPEC-068: a
  regression test on the `acme-admin` sample set asserts identical resolution through
  the `web.fill_credential`, `http.get`, and `http.post` paths.
- The scheme vocabulary is `basic` | `bearer` | `oauth2_client_credentials`. A `bearer`
  set requires a non-empty `token`; an `oauth2_client_credentials` set requires
  non-empty `token_url`, `client_id`, and `client_secret`, and may carry optional
  `scope`, `audience`, `resource`, and a `client_auth` variant. Missing required fields
  for the declared scheme cause the set to be ignored with a warning (never a crash),
  extending today's "each set needs non-empty username and password strings" behavior.
- An **unknown** `scheme` value is ignored with a warning (fail-closed) — never silently
  treated as `basic`.
- `_reload` retains the scheme-specific fields (it no longer projects each set down to
  `username`/`password` only); the mtime-refresh and keep-last-good-on-unreadable
  behavior is unchanged.
- A browser login flow (`web.fill_credential`) that references a non-`basic` set fails
  closed with a structured error rather than attempting a fill with absent
  `username`/`password`.

### R-2: Connector-local OAuth2 `client_credentials` token client (Option A)

Add a connector-local token client (e.g. `tools/oauth_client.py`) that performs the
OAuth2 `client_credentials` grant against a set's `token_url`, caches the acquired
token in memory only, and refreshes it on near-expiry. This is Option A of the
credential memo §4 — no new signing authority, no centralized broker, and **no new
dependency** (the grant is a single form-encoded POST that `httpx` already performs).

Acceptance criteria:

- A token is fetched from `token_url` on cache miss and cached in memory keyed by
  credential-set name; it is never written to disk, a tool result, an evidence field,
  audit, or a log line.
- The cached token is refreshed when within a safety margin of `expires_in`
  (near-expiry), so a call never rides an expired token; the response's `token_type`
  and `expires_in` are honored.
- Both common client-authentication variants are supported and selectable per set —
  `client_secret_basic` (client id/secret in the token request's `Authorization`
  header) and `client_secret_post` (in the form body) — because OAuth 2.1 servers
  differ; optional `scope` / `audience` / `resource` are sent when configured.
- A token-endpoint failure (unreachable, timeout, non-2xx, or a response carrying no
  `access_token`) fails closed with a structured gateway error — never an
  unauthenticated call and never a fabricated token.
- Concurrent callers for one set share a single in-flight fetch (no thundering herd of
  token requests), and `client_secret` / `access_token` are redacted on every path
  (asserted by R-4's tests).

### R-3: Reusable outbound auth-resolution seam

Generalize `http_connector._resolve_auth` (today sync, returning only
`httpx.BasicAuth | None`) into a single reusable resolver that produces the correct
outbound auth for any scheme. The resolver is the one acquisition path every connector
reuses: SPEC-058's `http_connector` first, SPEC-067's ServiceNow/MCP adapter second,
with no re-implementation.

Acceptance criteria:

- `basic` resolves to `httpx.BasicAuth` exactly as today (no behavior change); `bearer`
  attaches `Authorization: Bearer <token>`; `oauth2_client_credentials` attaches the
  R-2 client's fetched token as a bearer.
- The resolver is `async` (OAuth2 acquisition is a network call); the single `_request`
  call site in `http_connector.py` gains one `await`, and `basic`/`bearer` resolution is
  unchanged behind that coroutine.
- The resolver exposes both an `httpx.Auth` (for httpx-based connectors) and the
  resolved bearer token/header (for a non-httpx transport such as the MCP SDK's
  streamable-HTTP client, which takes a header or client factory), so SPEC-067 reuses
  one acquisition path. *This is the only forward-looking generality; SPEC-068 itself
  ships no MCP or ServiceNow code.*
- A credential/config failure (store unconfigured, unknown set, missing field, token
  fetch failure) returns a structured `CREDENTIAL_SET_NOT_FOUND` or a new
  `CREDENTIAL_ACQUISITION_FAILED` code — a gateway error, **not** an upstream "fact."
  This is the deliberate inverse of SPEC-058's rule that "an upstream 4xx/5xx is a fact,
  not a tool error": a missing credential is our failure to authenticate, not the
  target's answer.
- Neither the credential value nor an acquired token ever surfaces in a result,
  evidence field, or log line — only the set **name** is safe to surface, per the
  existing `_resolve_auth` contract.

### R-4: Secret-handling invariants — redaction and fail-closed

Every secret-bearing value SPEC-068 introduces (`client_secret`, `access_token`, a
static bearer `token`) is provably covered by the platform's existing redaction, and
every failure mode fails closed.

Acceptance criteria:

- The existing vocabulary already covers the new names: `url_redaction.SECRET_QUERY_PARAMS`
  includes `secret`, `token`, `credential`, `access_key`, `private_key`, `session_id`,
  and `signature` (substring-matched, so `client_secret` and `access_token` match), and
  `redaction._VALUE_PATTERNS` covers the password/secret/token family plus `client_secret`
  and `authorization`. A test asserts a token value never survives into a URL projection,
  a tool result, an evidence field, or audit.
- `make validate-secret-vocabulary` stays green **without a new canonical field set** —
  the validator pins the cross-product *redaction vocabularies* (secret-param substrings
  + value shapes), not credential-set field names, so additive credential fields do not
  touch it. *(This resolves SPEC-067's OQ-6.)*
- `_PROJECTED_HEADERS` continues to exclude `authorization` and `set-cookie`, so a bearer
  token echoed in a response header is never projected into a result.
- Missing, malformed, expired, or unresolvable credential state fails closed on every
  scheme — no unauthenticated fallback — preserving the `CredentialSetStore`
  keep-last-good behavior and the `CredentialSetError` contract.

### R-5: Provisioning and config wiring reuse the existing model

The new fields ride the established file-mounted credential-set secret; no new secret
mechanism, no inline env, nothing hand-edited in a consumer copy.

Acceptance criteria:

- An operator supplies an extended set (e.g.
  `{"scheme": "oauth2_client_credentials", "token_url": "...", "client_id": "...",
  "client_secret": "..."}`) through the existing `credential-sets.json` file mounted
  from the `tool-gateway-browser-credentials` secret and delivered by
  `sync-browser-credentials.sh` (via its `BROWSER_CREDENTIAL_SETS_FILE` override); the
  file is never inline env and never committed.
- The http connector keeps reading `GATEWAY_HTTP_CREDENTIAL_SETS`, falling back to
  `GATEWAY_BROWSER_CREDENTIAL_SETS` exactly as today; no new required env var is
  introduced for the substrate itself.
- The sync script's dev default (the `acme-admin` basic set) is unchanged, so existing
  `make deploy` behavior is byte-identical; a dedicated sync/secret for a real
  non-sample target is documented as **optional**, not required by this spec.
- `make overlays` renders the dev-k8s wiring green, and the extension is inert until a
  non-`basic` set is provisioned.

## Non-Goals

- **Centralizing token acquisition** in identity-broker (Option B) or Kubernetes
  workload identity (Option C). Each introduces a new minting/signing authority and
  requires its own ADR; SPEC-068 is the connector-local Option A default. Revisit only
  if a second consumer of the same target credential appears.
- **The inbound machine-consumer `client_credentials` grant / stable-API
  productization.** That is the parked, trust-model-blocked plane (no human
  owner/approver; it needs a machine-*subject* token identity-broker cannot mint).
  SPEC-068 is strictly the **outbound** External Execution Identity plane. See the
  credential memo §5.
- **Any ServiceNow-specific connector, MCP client/SDK integration, ingestion adapter, or
  `mcp` dependency.** That is [SPEC-067](../SPEC-067-servicenow-mcp-ingestion-pilot/spec.md).
  SPEC-068 is target-agnostic: it ships no target connector and no new dependency.
- **Write-tier tools or any new HITL surface.** SPEC-068 changes only auth resolution
  beneath the tier system; risk tiers, one-gate-per-flow (ADR-0007), and signed
  execution (SPEC-037) are untouched.
- **Credential schemes beyond `basic` / `bearer` / `oauth2_client_credentials`.** mTLS,
  OAuth2 authorization-code, JWT-bearer assertion, and the `refresh_token` grant are
  deferred until a named target requires one. If SPEC-067's Stage-0 finds ServiceNow
  requires mTLS-only, that reopens scope in a follow-up; SPEC-068 does not build schemes
  speculatively.

## Impact

- products touched: `products/tool-gateway` only — `tools/credential_sets.py`
  (generalized per-scheme parsing + field retention), `tools/http_connector.py`
  (`_resolve_auth` → the reusable async resolver; one new `await` at the single
  `_request` call site), a new `tools/oauth_client.py`, and optionally a small
  `tools/auth_resolution.py` seam module. **No kernel change and no new dependency**
  (`httpx` is already present; the `client_credentials` grant is a plain form-encoded
  POST).
- contracts touched: the credential-set secret **file shape** (additive optional
  `scheme` + scheme-specific keys). No policy-bundle change (no new tools). No
  secret-vocabulary change (existing redaction already covers the new names).
- identity / policy / audit / execution-safety impact: introduces the platform's
  **first non-Basic outbound execution credential** — the External Execution Identity's
  first concrete credential form
  ([identity model](../../agentic-aiops-platform/identity-and-authorization-design.md)
  §Service Identity Model). No new HITL surface; audit gains no new tool events (auth
  resolution sits beneath the tool tier); fail-closed and no-fabrication preserved; the
  platform's own ADR-0004 `sub`/`act` delegation is unaffected (the outbound target
  token is a separate plane).
- living state docs to update on delivery: `products/tool-gateway/README.md` (the
  credential-scheme surface), `docs/agentic-aiops-platform/architecture.md`
  (tool-gateway credential section), `identity-and-authorization-design.md` §Service
  Identity Model (record the outbound credential landing), and the delivery-roadmap
  (mark the substrate delivered; note SPEC-067 R-1 now depends on it).

## Open Questions

**None block `approved`.** SPEC-068 is decision-complete by design: it ships a
target-agnostic scheme vocabulary (`basic` / `bearer` / `oauth2_client_credentials`)
that depends on **no** single target's live-system facts — which is exactly why
extracting it from SPEC-067 (its OQ-2) unblocks approval during the ServiceNow PDI
wait. SPEC-067's OQ-1 (ServiceNow's real scheme) only *selects* among schemes SPEC-068
already builds; it never gates this spec. Approval, implementation, commit/push,
deployment, and any version bump remain separate authorization boundaries not granted
by a `draft`.

Decisions pinned at drafting (recorded so a reviewer sees they were settled, not
skipped):

- **OQ-6 (carried from SPEC-067) — resolved here.** The new fields ride the existing
  file-mounted `credential-sets.json` + `sync-browser-credentials.sh` model, and
  `make validate-secret-vocabulary` needs **no** new canonical field set: the validator
  pins the cross-product *redaction vocabularies* (secret-param substrings + value
  shapes), not credential-set field names, and the existing vocabulary already covers
  `token` / `secret` / `client_secret` / `authorization`.
- **Acquisition locus — Option A (connector-local).** Chosen over Option B/C
  (centralized) because a first SaaS pilot needs no new signing authority or ADR;
  revisit only on a second consumer of the same target credential.
- **`token_url` per set (in the secret file), not a global env.** Different targets have
  different token endpoints, and co-locating the endpoint with the client credential
  matches the file-mounted secret model.
- **Client-auth variant is explicit config, not auto-detected.** `client_secret_basic`
  vs `client_secret_post` is declared per set because OAuth 2.1 servers differ, and
  silent auto-negotiation could send a secret to the wrong place on a misconfig.

## Changelog

- 2026-10-08: created as `draft`; full scaffold (`spec.md` + `plan.md` + `tasks.md`)
  authored together per the SPEC-064/065/066/067 precedent. Extracted from
  [SPEC-067](../SPEC-067-servicenow-mcp-ingestion-pilot/spec.md) R-1 per its OQ-2
  (operator decision to decouple the target-agnostic outbound credential substrate from
  the ServiceNow pilot's PDI-gated live verification, so it can be approved and shipped
  during the waitlist). Absorbs and resolves SPEC-067's OQ-6. No Open Questions block
  `approved`. No implementation.
