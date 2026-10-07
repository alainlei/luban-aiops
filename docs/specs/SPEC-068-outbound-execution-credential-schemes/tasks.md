# SPEC-068 Tasks: Outbound Execution-Credential Schemes (Tool-Gateway Substrate)

Task states: `[ ]` pending, `[x]` done. Keep tasks small and tied to requirement IDs.

> **Draft — decision-complete, but not yet authorized.** SPEC-068 is `draft` with **no
> Open Questions blocking `approved`**, so this list is stable rather than provisional.
> It is still **not** an authorization to build: approval, implementation, commit/push,
> deployment, and any version bump are each separate authorization boundaries. There is
> no external Stage-0 fact to pin first — every task is verifiable against the shipped
> code and mocks, so work can begin as soon as the spec is approved.

## R-1: Per-set `scheme` field and generalized parsing (additive)

- [ ] Replace the fixed `REQUIRED_FIELDS` projection in `_reload` with a per-scheme
      required-field map, and retain each scheme's fields instead of dropping keys
      outside `username`/`password`
      (`products/tool-gateway/src/tool_gateway/tools/credential_sets.py`).
- [ ] Add the optional per-set `scheme` (default `basic`); ignore an unknown scheme or a
      set missing its scheme's required fields with a `LOGGER.warning` (fail-closed,
      never a crash) — generalizing today's "non-empty username and password" warning.
- [ ] Retain optional keys (`scope`, `audience`, `resource`, `client_auth`) when
      present; leave the mtime-refresh + keep-last-good-on-unreadable logic unchanged.
- [ ] Tests: a `basic` set (and a set with no `scheme`) parses byte-identically to
      pre-SPEC-068 (regression on the `acme-admin` sample set through
      `web.fill_credential` / `http.get` / `http.post`); `bearer` requires `token`;
      `oauth2_client_credentials` requires `token_url`/`client_id`/`client_secret`;
      unknown scheme + missing fields are ignored with a warning; a browser flow naming
      a non-`basic` set fails closed (`products/tool-gateway/tests/`).

## R-2: Connector-local OAuth2 `client_credentials` token client (Option A)

- [ ] Add `tools/oauth_client.py`: an async `client_credentials` grant as a single
      form-encoded POST to the set's `token_url` via the existing `httpx` (**no new
      dependency**); read `{access_token, token_type, expires_in}`
      (`products/tool-gateway/src/tool_gateway/tools/oauth_client.py`).
- [ ] Cache the token in memory keyed by set name; refresh when within a safety margin of
      `expires_in`; make concurrent callers share one in-flight fetch (per-set lock or
      in-flight-future map).
- [ ] Support both client-auth variants (`client_secret_basic` header vs
      `client_secret_post` body), explicit per set; send optional `scope`/`audience`/
      `resource` when configured.
- [ ] Never log/persist/serialize `client_secret` or `access_token` (log the failure
      *class* only); fail closed with a structured error on unreachable/timeout/non-2xx/
      missing-`access_token`.
- [ ] Tests: cache miss → fetch → cache hit; near-expiry refresh; single-flight under
      concurrency; both client-auth variants; a token-endpoint failure fails closed; no
      secret in logs/results/evidence (`products/tool-gateway/tests/`).

## R-3: Reusable outbound auth-resolution seam

- [ ] Generalize `http_connector._resolve_auth` (today sync, `httpx.BasicAuth | None`)
      into one reusable `async` resolver — inline or in a new `tools/auth_resolution.py`
      — covering `basic` → `httpx.BasicAuth`, `bearer` → `Authorization: Bearer <token>`
      (a small `httpx.Auth` subclass), `oauth2_client_credentials` → the R-2 token as a
      bearer (`products/tool-gateway/src/tool_gateway/tools/http_connector.py`).
- [ ] Return both an `httpx.Auth` and the resolved bearer token/header so a non-httpx
      transport (SPEC-067's MCP streamable-HTTP client) can reuse one acquisition path;
      add the single `await` at the `_request` call site.
- [ ] Map a credential/config failure to `CREDENTIAL_SET_NOT_FOUND` or a new
      `CREDENTIAL_ACQUISITION_FAILED` structured **gateway error** — never an upstream
      "fact" (the deliberate inverse of SPEC-058's rule) and never an unauthenticated
      fallback; keep only the set **name** surfaceable.
- [ ] Tests: each scheme's resolution; the `httpx.Auth` + raw-token outputs; the
      gateway-error contract; no credential/token in a result, evidence field, or log
      (`products/tool-gateway/tests/`).

## R-4: Secret-handling invariants — redaction and fail-closed

- [ ] Assert the existing vocabulary covers the new values: drive a token through a URL
      query, a tool result, an evidence field, and audit, and confirm it is masked
      (relies on `url_redaction.SECRET_QUERY_PARAMS` + `redaction._VALUE_PATTERNS`,
      which already list `client_secret`/`authorization`).
- [ ] Confirm `_PROJECTED_HEADERS` still omits `authorization`/`set-cookie` (a bearer
      token echoed in a response header is never projected).
- [ ] Confirm `make validate-secret-vocabulary` stays green **without** a new canonical
      field set (it pins redaction vocabularies, not credential field names) — resolve
      SPEC-067's OQ-6 by evidence, not assumption.
- [ ] Tests: every scheme's missing/malformed/expired/unresolvable path fails closed with
      a structured error and no unauthenticated fallback, preserving the
      `CredentialSetStore` keep-last-good + `CredentialSetError` contract
      (`products/tool-gateway/tests/`).

## R-5: Provisioning and config wiring reuse the existing model

- [ ] Document the extended `credential-sets.json` shape and confirm an operator can
      supply it through the existing `sync-browser-credentials.sh`
      `BROWSER_CREDENTIAL_SETS_FILE` override — no new secret mechanism, never inline
      env, never committed (`shared/platform-ops/gitops/sync-browser-credentials.sh`).
- [ ] Keep the http connector reading `GATEWAY_HTTP_CREDENTIAL_SETS` with the existing
      `GATEWAY_BROWSER_CREDENTIAL_SETS` fallback; introduce no new mandatory env var;
      leave the sync script's `acme-admin` dev default byte-identical.
- [ ] Render the dev-k8s overlay green (`make overlays`); note the dedicated
      real-target sync/secret as optional and owned by the consuming pilot (SPEC-067),
      not this substrate (`shared/platform-ops/gitops/dev-k8s/`).

## Delivery Gate

- [ ] All acceptance criteria in `spec.md` verified; `make verify` green (incl.
      `validate-secret-vocabulary` asserted unchanged, `overlays`, `portal-test`).
- [ ] A `basic`-set regression proves the `acme-admin` sample path is byte-identical and
      **no new dependency** was added (both lockfiles unchanged).
- [ ] Living state docs updated (see spec `Impact`): `products/tool-gateway/README.md`,
      `docs/agentic-aiops-platform/architecture.md`, `identity-and-authorization-design.md`
      §Service Identity Model, and the delivery-roadmap (substrate delivered; SPEC-067
      R-1 now depends on it).
- [ ] `CHANGELOG.md` entry added referencing SPEC-068; `VERSION` bumped in lockstep
      (separate authorization).
- [ ] Spec index in `docs/specs/README.md` updated; spec status set to `delivered`.
