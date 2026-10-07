# SPEC-068 Plan: Outbound Execution-Credential Schemes (Tool-Gateway Substrate)

> **Draft — decision-complete, but not yet authorized.** SPEC-068 is `draft` with
> **no Open Questions blocking `approved`**: it is target-agnostic and ready for an
> approval decision without any live-system verification. That said, this plan is not
> an authorization to build — approval, implementation, commit/push, deployment, and any
> version bump are each separate authorization boundaries not granted by this document.
> Unlike SPEC-067, there is **no external Stage-0 fact to pin first**: the substrate is
> verified entirely against mocks and the shipped code, so implementation can begin as
> soon as the spec is approved.

## Approach

SPEC-068 is the reusable half of what SPEC-067 called R-1, lifted out so it is not held
hostage to the ServiceNow pilot's PDI gate. It is one capability — "authenticate an
outbound call with something other than Basic" — decomposed into a parser change, a
token client, and a resolver seam, then proven safe (redaction + fail-closed) and wired
through the existing provisioning model. The build order is bottom-up: parse the new
fields, then acquire a token, then resolve any scheme into an `httpx` auth behind one
seam, then prove the secret invariants, then provision.

1. **Parse** (R-1) — generalize `credential_sets.py` to a per-scheme field model that
   retains scheme-specific keys; add the optional `scheme` (default `basic`). `basic`
   is byte-for-byte unchanged.
2. **Acquire** (R-2) — add the connector-local `oauth2_client_credentials` token client
   (`tools/oauth_client.py`): fetch, in-memory cache, near-expiry refresh, client-auth
   variants, redaction, single-flight.
3. **Resolve** (R-3) — generalize `http_connector._resolve_auth` into one reusable
   `async` resolver covering `basic` / `bearer` / `oauth2_client_credentials`, exposing
   both an `httpx.Auth` and the raw bearer token/header for a non-httpx transport.
4. **Prove safe** (R-4) — redaction coverage + fail-closed tests across every scheme;
   confirm `make validate-secret-vocabulary` is unaffected.
5. **Provision** (R-5) — ride the existing file-mounted `credential-sets.json` +
   `sync-browser-credentials.sh`; render `make overlays` green.
6. **Deliver** — living-state docs, CHANGELOG, version; separate authorization.

## Design Per Requirement

### R-1: Per-set `scheme` field and generalized parsing (additive)

- affected files / modules:
  - `products/tool-gateway/src/tool_gateway/tools/credential_sets.py` — replace the
    fixed `REQUIRED_FIELDS = ("username", "password")` projection in `_reload` with a
    per-scheme required-field map, and **retain** the scheme's fields instead of
    dropping everything outside `username`/`password`. Add `scheme` (default `basic`).
- chosen approach: a `_SCHEME_FIELDS` map — `basic → ("username", "password")`,
  `bearer → ("token",)`, `oauth2_client_credentials → ("token_url", "client_id",
  "client_secret")` — plus a set of optional keys (`scope`, `audience`, `resource`,
  `client_auth`) retained when present. A set whose declared scheme is unknown, or whose
  required fields are missing/empty, is ignored with a `LOGGER.warning` (the existing
  "each set needs non-empty username and password strings" pattern generalized), so the
  store never crashes and never admits a half-formed set.
- backward compatibility: with no `scheme` key the set is `basic` and parses exactly as
  today; the `acme-admin` sample set and the browser `fill_credential` path are
  untouched. The mtime-refresh + keep-last-good-on-unreadable logic is unchanged.
- browser path: `web.fill_credential` consumes `username`/`password` from a `basic`
  set; a browser flow that names a non-`basic` set has no username/password to fill, so
  it fails closed with a structured error rather than filling blanks.

### R-2: Connector-local OAuth2 `client_credentials` token client (Option A)

- affected files / modules: a new
  `products/tool-gateway/src/tool_gateway/tools/oauth_client.py`.
- chosen approach: **Option A — connector-local** (credential memo §4). A small async
  client performs the `client_credentials` grant as a single `application/x-www-form-urlencoded`
  POST to the set's `token_url` via the already-present `httpx` (**no new dependency**),
  reads `{access_token, token_type, expires_in}`, and caches the result in memory keyed
  by set name. A per-set `asyncio.Lock` (or an in-flight-future map) makes concurrent
  callers share one fetch. Refresh triggers when `now >= expiry - margin`.
- client-auth variants: `client_secret_basic` sends the client id/secret as an
  `Authorization: Basic` header on the token request; `client_secret_post` puts them in
  the form body. The variant is explicit per set (no auto-negotiation). Optional
  `scope` / `audience` / `resource` are added to the form when configured.
- secret handling: the `client_secret` and the acquired `access_token` are never logged,
  persisted, serialized into a result, or emitted as evidence; only the failure *class*
  is logged (mirroring `_reload`'s "log the failure class only — never the file
  contents"). A token-endpoint failure fails closed with a structured error.
- alternatives considered and why rejected (at draft):
  - **Option B — centralize acquisition in identity-broker.** Rejected: adds a new
    signing authority and an ADR, over-scope for a first pilot; revisit on a second
    consumer of the same target credential.
  - **Option C — Kubernetes workload identity.** Rejected: the identity doc names it the
    documented *upgrade path* for the External Execution Identity, appropriate under
    cluster-to-cluster trust, not for a first SaaS pilot.
  - **A third-party OAuth library (`authlib`/`oauthlib`).** Rejected: the
    `client_credentials` grant is one POST; taking a dependency for it would add
    supply-chain surface the SDK-free path does not need.

### R-3: Reusable outbound auth-resolution seam

- affected files / modules:
  - `products/tool-gateway/src/tool_gateway/tools/http_connector.py` — `_resolve_auth`
    becomes the general resolver (or delegates to a new
    `tools/auth_resolution.py`), turns `async`, and returns `httpx.Auth | None` plus the
    resolved bearer token/header. The single `_request` call site gains one `await`.
- chosen approach: one resolver function/coroutine shared by every connector. `basic →
  httpx.BasicAuth`; `bearer →` a small `httpx.Auth` subclass that sets
  `Authorization: Bearer <token>`; `oauth2_client_credentials →` the R-2 token wrapped
  in the same bearer auth. The resolver also returns the raw token/header so a non-httpx
  transport (SPEC-067's MCP streamable-HTTP client) can inject it without re-acquiring.
- error contract: a credential/config failure returns the existing
  `CREDENTIAL_SET_NOT_FOUND` or a new `CREDENTIAL_ACQUISITION_FAILED` structured code —
  a **gateway error**, deliberately the inverse of SPEC-058's "an upstream 4xx/5xx is a
  fact, not a tool error." A missing credential is our failure to authenticate, not the
  target's answer, so it must never be projected as a successful result.
- why a seam (not just patching `http_connector`): the whole point of extraction is
  reuse. Keeping resolution in one place means SPEC-067's ServiceNow/MCP adapter
  inherits the allowlist-independent credential logic verbatim, and the redaction /
  fail-closed guarantees are proved once.

### R-4: Secret-handling invariants — redaction and fail-closed

- affected files / modules: tests under `products/tool-gateway/tests/`; no production
  vocabulary change is expected.
- chosen approach: assert, don't assume. The existing `url_redaction.SECRET_QUERY_PARAMS`
  (substring-matched: `secret`, `token`, `credential`, …) and `redaction._VALUE_PATTERNS`
  (which already list `client_secret` and `authorization`) cover the new values, so a
  test drives a token through a URL query, a tool result, an evidence field, and audit
  and asserts it is masked in each. `_PROJECTED_HEADERS` already omits `authorization` /
  `set-cookie`; a test keeps it that way. Every scheme's missing/malformed/expired path
  asserts a fail-closed structured error with no unauthenticated fallback.
- `make validate-secret-vocabulary`: expected to stay green with **no** edit — the
  validator pins the redaction vocabularies, not credential field names. A task confirms
  this rather than presuming it (if a genuinely new secret *param name* were introduced,
  both product copies would extend in lockstep, which is exactly what the validator
  enforces).

### R-5: Provisioning and config wiring reuse the existing model

- affected files / modules: `shared/platform-ops/gitops/sync-browser-credentials.sh`
  (documentation of the extended shape; its `BROWSER_CREDENTIAL_SETS_FILE` override
  already carries an arbitrary `credential-sets.json`),
  `shared/platform-ops/gitops/dev-k8s/` (overlay), and the tool-gateway README.
- chosen approach: no new secret mechanism. An extended set is just another entry in the
  file-mounted `credential-sets.json` delivered by the existing sync script; the http
  connector keeps reading `GATEWAY_HTTP_CREDENTIAL_SETS` (falling back to
  `GATEWAY_BROWSER_CREDENTIAL_SETS`). The sync script's dev default (the `acme-admin`
  basic set) is unchanged so existing `make deploy` is byte-identical. A dedicated
  sync/secret for a real target is documented as optional and belongs to the consuming
  pilot (SPEC-067), not this substrate.

## Sequencing And Dependencies

1. **R-1 parse** — depends on nothing; the foundation.
2. **R-2 token client** — depends on R-1 (reads the parsed `oauth2_client_credentials`
   fields).
3. **R-3 resolver seam** — depends on R-1 (basic/bearer) and R-2 (oauth2 token).
4. **R-4 invariants** — depends on R-1–R-3 (proves the paths they add).
5. **R-5 provisioning** — depends on R-1 (the field shape it delivers).
6. **Delivery boundary** — separate authorization (docs, CHANGELOG, version).

There is no external-fact gate: every stage is verifiable against the shipped code and
mocks. SPEC-067's ServiceNow adapter consumes this substrate but does not block it.

## Test Strategy

- unit tests: per-scheme parsing + field retention + unknown-scheme/missing-field
  fail-closed (R-1); the token client's cache hit/miss, near-expiry refresh,
  single-flight under concurrency, client-auth variants, and never-logged
  `client_secret`/`access_token` (R-2); the resolver's `basic`/`bearer`/`oauth2`
  branches, its `httpx.Auth` + raw-token outputs, and its structured gateway-error
  contract (R-3). Redaction tests mirror SPEC-009 R-1's deterministic tool-output
  redaction.
- contract tests: `make validate-secret-vocabulary` (asserted unchanged), plus a
  `basic`-set regression proving the `acme-admin` sample path is byte-identical.
- integration: exercise `http.get` / `http.post` against `httpx.MockTransport` (the
  seam `HttpConnector` already accepts) with a **mock token endpoint** — so CI makes no
  live external call — covering a bearer set, an oauth2 set (fetch → cache → attach),
  and every fail-closed path. `make overlays` renders the dev-k8s wiring.

## Rollout And Migration

- deployment or configuration changes required: none for the substrate itself. The new
  fields are inert until an operator provisions a non-`basic` set through the existing
  file-mounted secret; no new env var is mandatory.
- backward compatibility: `basic` sets are unchanged (`scheme` defaults to `basic`); the
  resolver's `basic` branch is behavior-identical; the browser `fill_credential` path is
  untouched. No dependency is added, so both lockfiles are unchanged.
- rollback approach: remove any non-`basic` set from the credential file — the added
  code paths are dead without one. Because nothing is a new dependency or a schema
  change, rollback needs no code revert and no re-render of the overlays.
