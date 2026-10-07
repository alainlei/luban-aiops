# Spike: Machine-Consumer Credential Model — Scoping the `client_credentials` Gap for R6

Status: assessment — scopes the "machine-consumer credential gap (`client_credentials`)" that both the [MCP-ingestion backlog row](../agentic-aiops-platform/delivery-roadmap.md#exploration-backlog) and the parked "stable API productization" row name as their prerequisite. **Central finding: that label conflates two different gaps in two different products; only the outbound one blocks R6.** Recommends a direction and the first-pilot prerequisite. **No implementation, pilot, ADR, or spec is authorized by this memo.**
Date: 2026-10-04
Roadmap home: [Exploration Backlog](../agentic-aiops-platform/delivery-roadmap.md#exploration-backlog), rows "Independent MCP toolsets consumed by tool-gateway" (R6 candidate) and "Stable API productization / external consumption" (parked).
Builds on: [mcp-ingestion-spike.md](mcp-ingestion-spike.md) (§5 credential/audience boundary, §8 open questions), [mcp-exposure-spike.md](mcp-exposure-spike.md) (§5 trust boundary, §6 adapter owns "server authentication"), [ADR-0004](../adr/0004-broker-mediated-token-delegation.md), and the [identity & authorization design](../agentic-aiops-platform/identity-and-authorization-design.md) Service Identity Model.
Evidence baseline: repository at v0.46.0 (`fdc0039`). Static code/manifest inspection only. **No MCP server installed, tested, or deployed; no credential flow exercised against any external system.**
Promoted to: [SPEC-067 ServiceNow ITSM MCP-ingestion pilot](../specs/SPEC-067-servicenow-mcp-ingestion-pilot/spec.md) — `draft` 2026-10-06, R6's first slice (§4 Option A became SPEC-067 R-1, **extracted to [SPEC-068](../specs/SPEC-068-outbound-execution-credential-schemes/spec.md) on 2026-10-08** as the target-agnostic outbound-credential substrate — OQ-2 resolved; §5's parked inbound plane stays a Non-Goal). Drafting authorizes no implementation; three Open Questions block SPEC-067's `approved` (OQ-1, OQ-4, OQ-5 — all PDI-gated; OQ-2 resolved 2026-10-08, OQ-3 on 2026-10-07, OQ-6 moved to SPEC-068), and SPEC-068 has none blocking its own approval.

## 1. Question and recommendation

> The R6 MCP-ingestion pilots (ServiceNow → Ansible → Windows) are recorded as
> "blocked on the machine-consumer credential gap — identity-broker wires only
> `authorization_code` + `refresh_token`, no `client_credentials`." Scope that
> gap: what exactly is missing, where does it live, and what must exist before
> the first pilot?

Recommendation: **the label is wrong, and correcting it de-risks R6.** There is no single "`client_credentials` gap." There are **two distinct credential planes**, in two different products, blocking two different backlog rows:

1. **Outbound — External Execution Identity** (Luban's tool-gateway authenticating *to* an external target). This is what MCP ingestion actually needs. It is a **tool-gateway connector concern**, it **does not require any identity-broker grant**, and it is a *bounded extension* of the already-shipped `credential_set` mechanism. **This — not `client_credentials` — is the R6 first-pilot prerequisite.**
2. **Inbound — approved machine consumer** (an external application authenticating *to* Luban's API as itself). This is what the **parked** stable-API-productization row needs. It is an **identity-broker + platform-gateway** concern, it collides with the attribution/HITL trust model, and it stays **parked** (no second consumer exists).

Consequence: **R6 does not depend on unblocking the parked inbound row.** The two should be scoped separately and never share a spec. The rest of this memo grounds that split in the shipped code, then scopes plane 1 (the R6 prerequisite) to a decision-complete outline and records plane 2's shape so it is not re-litigated.

## 2. The three identity planes and their real implementation state

The [design doc's Service Identity Model](../agentic-aiops-platform/identity-and-authorization-design.md) (L333-369) names three identities. Mapping each to shipped code:

| Plane | Design-doc name | Direction | State today |
|---|---|---|---|
| 1 | Human Identity | operator → Luban | **Shipped.** OIDC `authorization_code` + `refresh_token` via Keycloak ([identity_service.py](../../products/identity-broker/src/identity_service/services/identity_service.py) L142-192, L229-277). These are the *only* two grant types wired. |
| 2 | Platform Service Identity | Luban svc → Luban svc | **Shipped** (ADR-0004, SPEC-008/009). Broker-mediated delegation: the gateway exchanges the verified user token for a short-lived `aud`-bound token, `sub`=user, `act`=service ([exchange_service.py](../../products/identity-broker/src/identity_service/services/exchange_service.py) L148-194). The *calling service* authenticates by static client registry (`IDENTITY_SERVICE_CLIENTS`, L46-57) **or** a Kubernetes projected service-account token (`IDENTITY_WORKLOAD_CLIENTS`, L83-120). |
| 3 | External Execution Identity | Luban → external system | **Partial.** Per-target credential sets exist but express **HTTP Basic only** (see §3). No bearer/OAuth token acquisition, no refresh. **This is the R6 gap.** |

Two facts about plane 2 that constrain everything downstream:

- **The exchange is user-subject-bound by design.** `exchange_token` *requires* a `subject_token` and copies `sub`/`roles` verbatim from it; it mints `act` = the service but never makes the service the subject ([exchange_service.py](../../products/identity-broker/src/identity_service/services/exchange_service.py) L123-186). Roles are never elevated. So identity-broker **cannot mint a pure machine-subject token today** — there is no code path where a service gets a token representing *itself* as the principal.
- **ADR-0004 already spent the "one service credential" exception** on the gateway→broker exchange, described as "a deliberate, scoped exception to the platform's otherwise asymmetric model — it can only request tokens for the `tool-gateway` audience and confers no user authority on its own" ([ADR-0004](../adr/0004-broker-mediated-token-delegation.md) L44). Any *new* machine credential must be justified against that precedent, not assume it.

## 3. Plane 3 today: `credential_set` is Basic-auth only

The existing per-target outbound credential mechanism is `credential_sets.py` (SPEC-049 R-5), reused by the browser and HTTP connectors:

- File shape is fixed to `{"name": {"username": ..., "password": ...}}` — `REQUIRED_FIELDS = ("username", "password")` ([credential_sets.py](../../products/tool-gateway/src/tool_gateway/tools/credential_sets.py) L27, L82-100). A set with any other shape is dropped at load.
- The HTTP connector resolves a set into **`httpx.BasicAuth(entry["username"], entry["password"])` and nothing else** ([http_connector.py](../../products/tool-gateway/src/tool_gateway/tools/http_connector.py) L361-387). The browser connector likewise only ever `fill`s the two fields.
- Credentials are platform config, never model-supplied: the knob is a file path only (`GATEWAY_BROWSER_CREDENTIAL_SETS` / `GATEWAY_HTTP_CREDENTIAL_SETS`, [config.py](../../products/tool-gateway/src/tool_gateway/core/config.py) L112/L124/L303-347), neither `http.get`/`http.post` ships a `headers` parameter (L12-14), the file is mtime-refreshed so rotation needs no restart, and values are never logged or serialized into a result — only the set *name* surfaces.

This is a good, safe seam. But its expressible credential space is **exactly one point: HTTP Basic username/password.** The prior MCP analysis already established that MCP server authentication is a **bearer/OAuth** concern the gateway adapter owns ([mcp-exposure-spike.md](mcp-exposure-spike.md) L146-151 "HTTP OAuth... forwarding a bearer token"; L187 adapter responsibility = "server authentication"), and that token passthrough is unacceptable at the Luban boundary ([mcp-ingestion-spike.md](mcp-ingestion-spike.md) §5, invoking ADR-0004 and the MCP authorization spec). A `credential_set` that can only produce `BasicAuth` therefore **cannot express the credential an MCP target presents**, which is the concrete, code-level statement of the R6 gap.

Confirmed absence of any alternative: a repository-wide scan finds **no outbound OAuth/token-acquisition code anywhere in `products/`** — `oauthlib`/`requests-oauthlib` appear only as transitive lockfile entries, and the sole bearer-token handling is *inbound* (tool-gateway verifying user JWTs via JWKS) plus the delegation exchange. The only other machine-auth precedents are *inbound* static shared secrets (e.g. incident-service `INCIDENT_WEBHOOK_TOKEN`, and the per-service `*_INGEST_CLIENTS` / `*_QUERY_CLIENTS` registries).

## 4. Plane 3 scoped — the External Execution Identity for R6 (the real prerequisite)

What the first MCP pilot needs is a way for the tool-gateway MCP-ingestion connector to **present an authenticated credential to an external MCP server**, under Luban's existing discipline. Requirements, inherited from [mcp-ingestion-spike.md §5](mcp-ingestion-spike.md) and made concrete against the code:

- **Extend the credential-set vocabulary, do not replace it.** The natural shape is an additive per-set `scheme` (e.g. `basic` | `bearer` | `oauth2_client_credentials`) alongside the existing `username`/`password`, so a static bearer token is a config value and an OAuth target adds `token_url` / `client_id` / `client_secret` / `scope`. This keeps `credential_sets.py`'s file-mounted, mtime-refreshed, fail-closed, never-logged posture intact and changes only what a set may *contain* and how `_resolve_auth` projects it (`BasicAuth` → also `Authorization: Bearer …`).
- **Token acquisition + caching lives in the connector, bounded.** If a target needs an OAuth token, the connector acquires it, caches it in-process for its lifetime (mirroring the browser-session and secret-delivery buffer precedents), and re-acquires on expiry. Acquisition endpoints are **operator config, never model-selected arguments** — the same inversion SPEC-058 drew for `http.get(url)`.
- **The `aud=tool-gateway` delegated token is never forwarded upstream** (ADR-0004; MCP authorization spec prohibits passthrough). The outbound credential is independent of the inbound human token.
- **Attribution is unchanged and stays human.** The outbound credential is the design doc's *External Execution Identity*, which is logged **separately** from the requester ([design doc](../agentic-aiops-platform/identity-and-authorization-design.md) L365-369, L112-119). The human requester still rides the plane-2 delegation (`sub`=user, `act`=tool-gateway) for policy, HITL, signed execution, and audit. A dedicated target identity is **not** per-user target RBAC and must be documented as such ([mcp-ingestion-spike.md](mcp-ingestion-spike.md) §5 "Attribution").
- **Mutations still traverse the governed path.** An MCP-backed write parks a HITL card, is signed, and executes via `execution-runtime` — the credential model changes none of that (ADR-0007, SPEC-037/038). Reads are the first pilot.
- **Fail-closed and redacted.** A missing/unresolvable/expired credential is a structured error, never a silent anonymous call; credential material never reaches a result, evidence frame, transcript, or log line (the `credential_sets.py` contract, extended).

Design options for *where the OAuth client lives*, to settle in the pilot spec:

| Option | Shape | Trade-off |
|---|---|---|
| **A. Connector-local OAuth client** (recommended to evaluate first) | tool-gateway acquires/caches the target token itself, per credential set. | Smallest blast radius; entirely inside the existing `credential_set` seam; no identity-broker change; no new trust root. Cost: each connector re-implements a bounded token client (one shared helper avoids drift). |
| B. identity-broker as outbound token broker | broker gains an *outbound* exchange: "given target X, mint/fetch its credential." | Centralizes egress credentials, but expands the broker beyond its human-delegation charter, adds a hot-path dependency to every MCP call, and re-opens the ADR-0004 "one service credential" exception. Reject unless a measured need (shared token cache across connectors, centralized rotation) appears. |
| C. Sidecar/in-cluster credential broker (e.g. a vault-style agent) | external secret system issues short-lived target credentials. | Strongest rotation story; heaviest operational lift; disproportionate for a single-namespace dev deployment (the same objection ADR-0004 raised for mTLS/SPIFFE). Park as a scale trigger. |

**This plane needs no `client_credentials` grant in identity-broker.** The OAuth `client_credentials` *grant type* may appear here only as the mechanism the connector uses against the **external** target's IdP (Luban is the OAuth *client*; the external system is the OAuth *server*). That is unrelated to Luban minting machine-subject tokens for itself, which is plane 2.

## 5. Plane 2 — the inbound approved-machine-consumer model (stays parked)

For completeness, so the two are never re-conflated: an external application consuming *Luban's* API as itself needs a token whose **subject is the application**, which the platform cannot mint today (§2). Building it would require, at minimum:

- a `client_credentials` grant (or, following the platform's established inbound pattern, **local verification of a registered machine credential at platform-gateway** — the `*_INGEST_CLIENTS` / projected-workload-token vocabulary already used by audit-service and identity-broker, which avoids adding a broker endpoint);
- a **scoped service principal** in the authorization matrix, which today models human roles only (operator/approver/auditor/…), plus per-consumer rate limiting;
- a published `/api/v1` stability & deprecation contract (versioned by convention only today).

It is blocked by the trust model, not just by code: the attribution/HITL model requires a human owner and a distinct human approver ([design doc](../agentic-aiops-platform/identity-and-authorization-design.md) principles 2 and 5), so a machine subject can own no session, scope no recovery, and approve no card. Only **read-only** consumption is tractable without first solving machine attribution. This row therefore **stays parked** on its recorded trigger (a named second internal application committing to a concrete workflow + operation set, read-only-first) and **must not** be scoped together with R6.

## 6. Go/no-go gates and next decision

This memo authorizes **no** implementation. Recommended next decisions, in order:

1. **Accept the two-plane split** and correct the roadmap/backlog language: the R6 pilot prerequisite is the **outbound External Execution Identity credential model** (plane 3), *not* the inbound `client_credentials` grant (plane 2). Update the MCP-ingestion backlog row and [mcp-ingestion-spike.md §5](mcp-ingestion-spike.md) to name plane 3 explicitly.
2. **Frame R6** as a release theme ("External system integration via MCP ingestion") if the operator approves opening it — the plane-3 credential model is its natural first slice because every pilot depends on it and nothing else does.
3. **Promote one pilot spec** (ServiceNow first, per the ingestion memo's risk order) whose *first* requirement is the additive `credential_set` scheme extension + connector-local token client (Option A), read-tier only, writes deferred behind the existing HITL/signed path. Pin the target's actual auth scheme (static bearer vs OAuth `client_credentials` vs mTLS) as a Stage-0 fact before designing the credential shape.
4. **Record an ADR** for the External Execution Identity credential model *only if* the pilot chooses Option B or C (a new trust root / broker charter change). Option A extends an existing seam and may need only a spec, not an ADR — decide at pilot planning.
5. **Leave plane 2 parked.** Do not build inbound machine-consumer auth speculatively; it is gated on a named second consumer.

**Stop condition:** if a named target's only acceptable authentication is one Luban cannot express without widening authority (e.g. it demands the inbound human token be forwarded, or per-user target RBAC Luban cannot scope), retain native connectors for that target and do not build a replacement — the ingestion memo's adopt/stop rule.

## 7. Open questions for the first pilot spec

- Per-target auth scheme: for ServiceNow (then Ansible, Windows), is the MCP server's credential a static bearer token, an OAuth `client_credentials` flow against the target's IdP, mTLS, or a stdio-local credential? This is a **fact to pin**, and it determines whether plane 3 needs a token client at all or only a `bearer` scheme.
- Token cache placement and lifetime: in-connector in-process (per-pod, mirrors the browser-session/secret-delivery buffer precedent) vs a shared backend; and behavior on acquisition failure mid-flow (fail-closed, no blind retry after a possibly-dispatched mutation — [mcp-ingestion-spike.md §5](mcp-ingestion-spike.md) "Uncertain outcomes").
- Redaction/secret-vocabulary: the new credential fields must join the gateway's secret-key vocabulary and the `validate-secret-vocabulary` gate so a token can never surface in a result, evidence frame, or change-request card.
- Attribution correlation: how the outbound execution correlates to the human requester in audit when the target issues its own request ids (do not assume propagation — [mcp-ingestion-spike.md §5](mcp-ingestion-spike.md) "Attribution").
- Does the External Execution Identity warrant its own audit field distinct from `act`=tool-gateway, or is the existing separate-logging posture sufficient for the first pilot?

## Changelog

- 2026-10-04, initial draft: scopes the "machine-consumer credential (`client_credentials`) gap" named by the R6 MCP-ingestion row and the parked stable-API row. Grounds the finding in shipped code (identity-broker grants and the user-subject-bound exchange; `credential_sets.py` Basic-only projection; no outbound OAuth anywhere in `products/`) and the design doc's three-plane Service Identity Model. Central conclusion: the label conflates an **outbound External Execution Identity** gap (tool-gateway, the real R6 prerequisite, no broker grant needed) with an **inbound approved-machine-consumer** gap (identity-broker/platform-gateway, trust-model-blocked, stays parked); R6 does not depend on the parked row. Records three placement options (connector-local recommended), go/no-go gates, and first-pilot open questions. **Assessment only — no implementation, pilot, ADR, or spec promotion, and no approval of any of these, is part of this memo.**
