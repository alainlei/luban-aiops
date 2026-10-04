# `acme-admin` — the sample application and its skill suite

A small FastAPI user-administration console, and the samples written against it.
It is the **first sample in this repository to own a container image**, and since
SPEC-060 the sole target of the browser samples too: the three that once lived
under `samples/web-checks/` and drove `browser-check-target` — a static page
bundle in platform GitOps that can render a form but cannot answer "did that
actually change anything?" — were rebased onto this app (and the static
`password-reset` one retired outright), so every browser sample here now mutates
a real store.

> **Naming:** `acme` is the conventional fictional-company placeholder (Acme
> Corp), **not** the ACME certificate protocol (RFC 8555).

The app holds state, validates a login, refuses mutations that would
change nothing, and answers its own confirmation page *from that state* rather
than from the query string it was handed. That last property is what makes the
fourth rung below honest, and the reason this directory exists.

Working on the application code itself (build, test, run locally, deliberate
boundaries) is [`app/README.md`](app/README.md). This file is the
operator-facing document.

## The samples: a five-rung ladder plus two approval models

Five samples form a progressive ladder on the card count:

| # | Sample | Surface | Effect | Cards | `approval_kind` |
|---|---|---|---|---|---|
| 1 | [health-check](health-check/) | `http.get` | read | **0** | — |
| 2 | [user-status](user-status/) | bound browser flow | read | **0** | — |
| 3 | [lock-unlock-user](lock-unlock-user/) | `http.post` | write | **1** | `action` |
| 4 | [password-reset](password-reset/) | bound browser flow | write | **1** | `flow` |
| 5 | [composition](composition/) | runbook (4 then 3) | write (derived) | **2** | `flow` + `action` |

Read together they make a claim none of them makes alone: **the card count
tracks the effect of a skill, not the surface it uses.** Rungs 1 and 3 both talk
to the JSON API and differ; rungs 2 and 4 both drive a browser and differ. A
reader who has seen all five stops inferring "browser means dangerous" and "API
means safe" — and sees at rung 5 that composing two mutating skills parks two
cards, not one.

Two more samples share the same console to contrast the *approval models* — where
rung 4's bound flow comes from, and what the work costs before one exists:

| Sample | Skill | Approval shape |
|---|---|---|
| [adhoc-password-reset](adhoc-password-reset/) | hand-written runbook, **no `web_target`** | N `action` cards for N writes (SPEC-054) |
| [skill-graduation](skill-graduation/) | **none** — the skill is the artifact the demo produces | N `action` cards to author, then 1 `flow` card to replay (SPEC-055) |

Each sample directory carries a `README.md` (what the pattern is and why it is
shaped that way), a `WALKTHROUGH.md` (a live, click-by-click run against a
cluster), a `skill/` document (installed by `make deploy-samples`) and a
`demo/demo.sh` (the same run, unattended and asserted) — except
`skill-graduation`, which ships no `skill/` because its skill is what the demo
produces.

## Deploying it

The platform base overlay names nothing in this directory — the dependency
arrow is always tutorial → platform. Deploy out-of-band, after `make deploy`:

```sh
make deploy                # platform, with the browser-dev + mutating-dev profiles
make deploy-sample-app     # build the image, apply deploy/, then ASSERT it works
make deploy-samples        # install all six skill documents (five rungs + adhoc-password-reset)
```

`make deploy-sample-app` runs [`deploy.sh`](deploy.sh), which is a deploy *and*
an assertion. It does not exit 0 unless:

1. the `acme-admin-credentials` secret exists,
2. `GATEWAY_HTTP_ALLOW_ORIGINS` lists `http://acme-admin:8080`,
3. the rollout completed,
4. the running pod is the image just built (a stale tag cannot pass),
5. `GET /healthz` answers 200 with all eight keys,
6. `GET /api/hello?name=luban` echoes the name back,
7. `GET /api/users` without credentials answers **401**,
8. `GET /api/users` with the synced credential answers 200 and the four seeded
   users,
9. both allowlists carry the origin and `GATEWAY_HTTP_ENABLED=true` in the live
   config.

Two additional checks are deliberately *warnings* rather than failures, because both
depend on something the manifests do not control: whether the gateway's mounted
credential-sets file carries an `acme-admin` entry (fixed by re-running
`sync-browser-credentials.sh`), and whether the cluster's CNI enforces
NetworkPolicy at all. A local cluster whose CNI ignores NetworkPolicy would
otherwise fail an otherwise perfect deploy.

In-cluster probes run by `kubectl exec` into the real `tool-gateway` container
rather than by launching a labelled probe pod: that container already ships
`curl`, needs no image pull, and *is* the pod the ingress rule admits. A passing
probe proves that path is reachable; only the separate denied-source probe can
check whether the CNI enforces the restriction.

Remove it with `make undeploy-sample-app`.

### Exposing the human surface

The walkthroughs all ask you to look at the console yourself first:

```sh
kubectl -n dev-luban-aiops port-forward svc/acme-admin 8080:8080 &
open http://localhost:8080/admin/
```

This works even though the ingress NetworkPolicy admits only `app: tool-gateway`
pods: `kubectl port-forward` is tunnelled by the kubelet straight into the pod's
network namespace and never traverses pod ingress. The agent's browser does
**not** use it — the sidecar reaches `http://acme-admin:8080` in-cluster, from
the tool-gateway pod, which the policy is configured to admit.

## Endpoints

Two surfaces over one store. `/healthz` and `/api/hello` are unauthenticated on
purpose: a health check that needs a credential is not a health check, and rung
1 is the repository's first genuinely card-free skill.

### JSON (`api.py`) — HTTP Basic, `admin`

| Method | Path | Answers |
|---|---|---|
| `GET` | `/healthz` | eight keys: `status`, `service`, `version`, `hostname`, `uptime_seconds`, `started_at`, `users_seeded`, `store_revision`. No auth |
| `GET` | `/api/hello?name=` | `{"message": "hello, <name>!"}`. No auth. `name` is bounded to `^[A-Za-z0-9 _.-]{1,64}$` and anything outside it arrives as a **422** |
| `GET` | `/api/users` | every row plus `store_revision` |
| `GET` | `/api/users/{identifier}` | one row by **username or email**, case-insensitively |
| `POST` | `/api/users/{identifier}/lock` | `{"action": "lock", …}` |
| `POST` | `/api/users/{identifier}/unlock` | `{"action": "unlock", …}` |
| `POST` | `/api/users/{identifier}/password` | `{"action": "password_reset", …}`, body `{"password": "…"}` |
| `POST` | `/internal/reset-demo` | restores the seed. **Header-gated**, no auth |

Error bodies are one envelope, `{"error": "<CODE>", "message": "<human>"}`, so a
caller branches on a code rather than parsing prose:

| Status | Code | Means |
|---|---|---|
| 401 | `UNAUTHORIZED` / `INVALID_CREDENTIALS` | carries `WWW-Authenticate: Basic realm="acme-admin"` |
| 404 | `UNKNOWN_USER` | no such username or email. Report the identifier used and stop |
| 409 | `NO_OP_MUTATION` | the target is already in that state. **Nothing changed, the revision did not move** |
| 400 | `INVALID_PASSWORD` / `PASSWORD_MISMATCH` | empty password, or the two reset fields disagree |
| 403 | `DEMO_RESET_HEADER_REQUIRED` | `/internal/reset-demo` without `X-Luban-Demo-Reset` |

404 and 409 are the two that matter most. An upstream that answers 200 for
everything makes SPEC-058 R-3's `mutation_confirmed` marker a tautology and the
confirmation card a formality.

### HTML (`pages.py`) — session cookie

| Path | What it is |
|---|---|
| `/` | a login form (`#login-form`, `#login-status`) |
| `/status` | a rendered service-status page (`#api-status`, `#db-status`, `#queue-status`, `#checked-at`, `#store-revision`, `#users-seeded`) |
| `/admin/` | the operator login (`#admin-login-form`, `#admin-username`, `#admin-password`, `#admin-sign-in`, `#admin-login-status`) |
| `POST /admin/login` | issues the session token; the form **auto-submits ~100 ms** after both fields are filled, so a read-class flow never has to click |
| `/admin/users/` | the console: `#user-table`, one `#user-row-<username>` per user with `data-username` / `data-locked`, a "Recent Password Resets" panel (`#last-reset-user`, `#last-reset-time`, `#no-resets`), and `#store-revision` in the footer |
| `/admin/users/reset/?user=&newpw=` | the reset form (`#target-user`, `#new-password`, `#confirm-password`, `#confirm-reset`, `#reset-status`). Pre-fills from the query string and deliberately does **not** submit |
| `POST /admin/users/reset/` | performs the reset |
| `/admin/users/reset/done/` | the confirmation page (`#confirmation-message`, `#reset-timestamp`, `#back-to-users`) — answered **from the store**, not from the query string |

Element ids are asserted from outside the application by
`app/tests/test_pages.py`, so a skill that names `#confirm-reset` is not naming
something a template refactor can silently move.

## Seed data

Four users, seeded deterministically at `SEED_REVISION = 0`:

| Username | Name | Email | Role | Status | Last modified |
|---|---|---|---|---|---|
| `alice` | Alice Johnson | alice@example.com | viewer | active | 9 days before start |
| `bob` | Bob Smith | bob@example.com | editor | active | **2 hours** before start |
| `carol` | Carol Williams | carol@example.com | admin | active | 30 days before start |
| `dave` | Dave Brown | dave@example.com | viewer | **locked** | 60 days before start |

Three things about this table are deliberate:

- **`dave` starts locked**, so a read-only skill has a non-uniform table to
  describe on its very first run. It also makes him a poor target for rung 3:
  locking an already-locked user is a `409 NO_OP_MUTATION`.
- **`bob` was modified two hours ago**, so a skill answering "what changed
  lately?" has something to find without waiting on a mutation of its own.
- **The offsets are relative to process start**, so `reseed()` restores
  byte-identical timestamps and a demo can prove it started from a known state.

The seeded users are **records, not accounts** — they cannot sign in. The
console has exactly one operator account, `admin`.

Restore the seed at any time:

```sh
curl -s -X POST -H 'X-Luban-Demo-Reset: 1' localhost:8080/internal/reset-demo
```

**Neither HTTP tool can make that call.** The endpoint requires a request
header, and neither `http.get` nor `http.post` publishes a `headers` parameter
(SPEC-058 R-4). This prevents reseeding through those tools; it is not a
platform-wide authorization boundary. Other capabilities, such as approved
browser JavaScript, may issue requests with headers. No skill document names
this endpoint. OpenAPI and `/docs` are disabled to avoid advertising the demo
control endpoint; hiding it is not access control.

## The credential arrangement

One generated password, two sinks, written by one script:

```sh
shared/platform-ops/gitops/sync-browser-credentials.sh dev-luban-aiops
```

| Sink | What lands there | Who reads it |
|---|---|---|
| `tool-gateway-browser-credentials` secret | an `acme-admin` entry (`username: admin`) | the gateway: `web.fill_credential(credential_set="acme-admin")` and `http.post(credential_set="acme-admin")` resolve it server-side |
| `acme-admin-credentials` secret | `ACME_ADMIN_PASSWORD` | the app, at startup |

Both come from the same random value, so the browser surface, the HTTP surface
and the application cannot disagree. The script restarts both deployments
afterwards, because the app reads the variable only at startup.

**Rotate one without the other and the sign-in is rejected** — the console
redirects back to `/admin/`, and the downstream symptom is a `web.extract`
returning no rows, which looks like "no users" but is really "not signed in".
Re-run the sync script.

Nothing is defaulted. With `ACME_ADMIN_PASSWORD` absent or empty the app
**refuses to start** and names the secret and the script that produce it.
`SKIP_BROWSER_CREDENTIALS=true` skips provisioning; it does not remove existing
secrets. A fresh, unprovisioned deployment therefore fails closed, while an
already provisioned deployment retains its credentials. The generated admin
password travels through tool calls as a *reference name* the gateway resolves,
not as a literal tool argument.

## State model, and the `replicas: 1` consequence

State is **in memory** — users, a monotonic `revision`, and one `last_reset`
record. There is no database, no PVC and no external dependency, because a
tutorial target that needs provisioning stops being a tutorial target.

Three consequences worth knowing before you demo it:

- **The Deployment pins `replicas: 1`.** Two replicas would be two independent
  consoles that disagree, and the whole claim this suite makes — a mutation made
  over HTTP is visible over HTML — would be false on every other request.
- **A pod restart reverts to the seed.** Uptime keeps counting from the original
  process start across a `reseed()`, so `uptime_seconds` is honest about the pod
  and `store_revision` is honest about the data.
- **Every mutation bumps the global revision** and stamps the row with it, so
  `revision` is the answer to "did anything happen at all?" and to "*which*
  action changed this row". No password value is ever stored: a reset records
  *when* it happened and which revision it produced, then discards the value.

## Running the demos

Each sample's `demo/demo.sh` runs the same story unattended and asserts it. The
deterministic legs always run and involve no model; the chat legs are opt-in
behind `RUN_CHAT_LEG=true`, because an assertion that depends on a model
choosing the right tools is not an assertion.

```sh
samples/acme-admin/health-check/demo/demo.sh          # rung 1 alone
RUN_CHAT_LEG=true samples/acme-admin/demo-suite.sh    # all five, plus the cross-skill leg
```

[`demo-suite.sh`](demo-suite.sh) runs the five in ladder order and then asserts
the claim the whole slice makes: it locks a user over **HTTP** with the same
`http.post` call rung 3 makes, and reads `locked` back off the rendered console
over a real browser session — one store, two surfaces. It also asserts that
every skill id the mounted set produces is pairwise distinct, so
`ResetAcmePassword.md` cannot silently re-id a shipped sample.
`make e2e` lists it.

Shared plumbing lives in [`demo-lib.sh`](demo-lib.sh), sourced rather than
executed. Prerequisites and the environment overrides (`NAMESPACE`,
`IDENTITY_URL`, `GATEWAY_URL`, `TEST_USER`, `APPROVER_USER`, `CROSS_TARGET`,
`RUN_CHAT_LEG`) are documented in its header. In short:

```sh
kubectl -n dev-luban-aiops port-forward svc/identity-service 18081:8000 &
kubectl -n dev-luban-aiops port-forward svc/platform-gateway 18083:8000 &   # chat legs
```

## Writing a new walkthrough against this app

The existing walkthroughs are the template. The shape they share:

1. **Say which portal surface it uses, and which it does not.** The operational
   samples — the five rungs plus `adhoc-password-reset` — live in **Chat**;
   **Studio** is the skill-development workspace (SPEC-056), used only by
   `skill-graduation`, and each Chat walkthrough names it explicitly as unused,
   pointing at `samples/acme-admin/skill-graduation/WALKTHROUGH.md`.
2. **Prerequisites as a table**: component, what must be true, and the command
   that checks it. Name the ConfigMap keys the reader has to confirm —
   `GATEWAY_HTTP_ENABLED`, `GATEWAY_BROWSER_ENABLED`, both allowlists,
   `GATEWAY_MUTATING_TOOLS_ENABLED` — and keep `AGENT_HITL_CONFIRM_TIMEOUT`
   separate from them: it is an **agent-platform** setting, dev-k8s sets no
   value for it, and the default `600` is what makes the card appear.
3. **Have the reader look at the console first.** Every walkthrough opens
   `http://localhost:8080/admin/` before touching the portal, so the reader has
   a starting state to compare against and knows what "changed" looks like.
4. **Give the exact message to paste**, identical to the one the demo's chat leg
   sends. Naming the skill id and the credential set closes the two ambiguities
   that make a model stall: which runbook to follow, and where the password
   comes from. **Then say out loud that the explicit form is a determinism
   choice, not a requirement.** In regular use the reader can ask conversationally
   and the agent finds the runbook through `skills.search`, so every Step-4 prompt
   carries a short "or just ask conversationally" note linking to
   [`skills-guide.md`](../../docs/guides/skills-guide.md#asking-for-a-runbook-without-naming-it).
   The strict block is what `demo.sh` asserts against; the conversational note is
   what a person would actually type.
5. **List what the turn should contain, tool by tool**, and what should *not*
   appear. "No confirmation card. Nothing parked." is an observation, not an
   omission — say so out loud on a read rung.
6. **Add honest caveats.** Where the walkthrough underclaims is fine; where it
   overclaims is not. Name the things that vary (`uptime_seconds`), the things
   that only hold after a reseed (`store_revision: 0`), and the results that
   look like failures but are answers (a 422, a 409).
7. **Draw the sequence.** An ASCII diagram of who called whom makes the gate
   visible in a way prose does not.
8. **Tabulate step ↔ demo leg.** R-8's criterion is that a walkthrough does not
   instruct the reader to click anything the demo does not also exercise; the
   table is how a reviewer checks it, and a row honestly marked "not driven by
   the demo" is better than a row that quietly is.
9. **End with a troubleshooting table**, symptom → cause → fix.

Then add the sample to [`demo-suite.sh`](demo-suite.sh)'s ladder and to the
`e2e` target's script list in the root `Makefile` — both are hardcoded, so a new
script does not join them by existing.

## Related

- [`app/README.md`](app/README.md) — the application: build, test, boundaries
- [`../README.md`](../README.md) — samples in general, and how
  `make deploy-samples` derives skill ids
- [`../deploy-samples.sh`](../deploy-samples.sh) — the installer
- [`../../docs/specs/SPEC-059-acme-admin-sample-app-and-skill-suite/`](../../docs/specs/SPEC-059-acme-admin-sample-app-and-skill-suite/)
  — the requirements this directory implements
- [`../../docs/specs/SPEC-058-http-service-check-tools/`](../../docs/specs/SPEC-058-http-service-check-tools/)
  — `http.get` and `http.post`, which rungs 1 and 3 use
- [`../../docs/guides/tool-configuration.md`](../../docs/guides/tool-configuration.md)
  — the allowlists and feature switches named above
- [`../../docs/guides/skills-guide.md`](../../docs/guides/skills-guide.md#asking-for-a-runbook-without-naming-it)
  — asking for a runbook conversationally, without naming a skill id
