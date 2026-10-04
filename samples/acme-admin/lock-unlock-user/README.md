# ACME Admin Lock / Unlock User (`http.post`, one `action` card)

Rung 3 of the five-rung `acme-admin` ladder (SPEC-059 R-7). One write-tier
`http.post`, one confirmation card, of kind **`action`**.

This is the rung that makes the card count non-zero, and it is paired with
rung 4 on purpose: the two perform the same class of change — mutate one
account in one store — over the two surfaces, and park one card each of a
*different* `approval_kind`. Read back to back, SPEC-054's discriminator stops
being a field in a schema and becomes something you have seen twice.

## What this sample contains

| Path | Purpose |
|---|---|
| `skill/LockUnlockUser.md` | The skill document — one `http.post`, annotated with why the card is `action`, why a body the endpoint ignores is sent anyway, and why the credential can only be a reference |
| `demo/demo.sh` | Standalone demo: tier registration → the app's 200/409/404/401 → the `mutation_confirmed` projection → the structural refusals → skill ingestion → optional chat leg |
| `WALKTHROUGH.md` | The same story driven by hand through the operator portal's **Chat**, approved by a second identity |

Skill id: **`samples/lock-unlock-user-lockunlockuser`**.

## Prerequisites

| Requirement | Why this rung needs it |
|---|---|
| `make deploy` with the `browser-dev` runtime profile | `GATEWAY_HTTP_ENABLED=true` and the origin on `GATEWAY_HTTP_ALLOW_ORIGINS` |
| `make deploy` with the `mutating-dev` runtime profile | `GATEWAY_MUTATING_TOOLS_ENABLED=true`, or `http.post` is not registered at all and the call fails `TOOL_NOT_FOUND` |
| `AGENT_HITL_CONFIRM_TIMEOUT` greater than `0` on agent-platform | otherwise write-tier tools are excluded from the agent's toolkit entirely and the chat leg cannot reach a card |
| `tools:mutate` grant for the caller's role | the policy bundle decides who may ask |
| A **designated approver** distinct from the operator | SPEC-030 R-4: the requester cannot decide their own mutating call. `luban-approver` holds the decider role; `luban-operator` does not |
| `make deploy-sample-app`, `make deploy-samples`, `sync-browser-credentials.sh` | the app, the skill, and the `acme-admin` credential set |
| identity-service port-forward on `18081`; platform-gateway on `18083` for the chat leg | the demo issues its own tokens for both identities |

## How it works

One call, in one of two directions:

- lock: `http.post` to `http://acme-admin:8080/api/users/<identifier>/lock`
  with `body: {"locked": true}`
- unlock: `http.post` to `http://acme-admin:8080/api/users/<identifier>/unlock`
  with `body: {"locked": false}`
- both with `credential_set: "acme-admin"`

The identifier is a username (`carol`) or an email (`carol@example.com`); the
app resolves either, case-insensitively. The call **parks** the card: the
kernel's HITL bridge holds it, a designated approver decides in the portal,
and on approval the same call executes and the stream resumes. The response
then carries `action`, `username`, `locked`, `last_modified` (microsecond
UTC), `revision` and `password_changed_at`.

Verification is a separate skill — [`../user-status/`](../user-status/) reads
the new Status cell off the rendered console. That separation is deliberate: a
skill that mutates *and* verifies hides which half produced the evidence.

## Key design decisions

### Why the card is `action` and not `flow`

`approval_kind: "flow"` is reserved for a *bound browser flow*, where one
approval unlocks the rest of the flow's write-tier interactions (ADR-0007).
This skill opens no browser and binds no flow, so its single gated call is an
`action` card: one approval for exactly one call. The demo asserts the
discriminator on the parked frame itself (`require_card_shape … action
http.post`), not on a field it read out of a spec.

### Why the card is legible

`change_request.summary` reads
`POST to http://acme-admin:8080/api/users/carol/lock — 1 field: locked`, so an
approver decides on the origin, the path and the field rather than on
`url: *** body: ***`. The demo asserts the summary names both the origin and
the path. That projection is SPEC-058 R-5's kernel-side formatter; this rung
is where a reader sees it earning its keep.

### Why a body the endpoint ignores is sent anyway

`/api/users/{identifier}/lock` and `/unlock` take **no** request body — the
action is in the path. `{"locked": true}` is sent regardless, and the app
ignores it, because the body is what the card projects: with it the approver
reads `1 field: locked`, and without it the card names only a URL. The skill
document says out loud that this is a choice and not a requirement, because a
tutorial that hides its own conventions teaches the reader to guess.

### Why the credential is a set name and not a header

Neither `http.get` nor `http.post` publishes a `headers` parameter — the demo
asserts this against the gateway's *published discovery document*, not against
the implementation. So a model cannot put a literal secret into an `http.post`
argument, and the graduation pipeline has no credential hole to fill
(SPEC-055 R-4). This is a structural control, and asserting the schema is what
keeps it structural.

### Why the deterministic legs do not claim an approval

A direct `POST /api/v2/tools/invoke` of a write-tier tool carries **no** card:
the gate lives in the kernel's HITL bridge, not in the gateway, and `operator`
holds the `tools:mutate` grant. So the deterministic legs prove the
*projection* (`mutation_confirmed` true on a 200, false on a 409) and only the
opt-in chat leg proves the *gate*. Conflating the two is how a demo ends up
claiming an approval it never exercised.

## Running the demo

```sh
make deploy-samples SAMPLE=acme-admin/lock-unlock-user

# Deterministic legs only (no model, no approval):
sh samples/acme-admin/lock-unlock-user/demo/demo.sh

# Including the chat leg: one action card, a tier-2 approval by a second
# identity, and the store checked afterwards:
RUN_CHAT_LEG=true sh samples/acme-admin/lock-unlock-user/demo/demo.sh
```

Overrides: `TARGET_USER` (default `carol`), `DENIED_ORIGIN` (default
`http://acme-denied.invalid:8080`). Pick a target that starts **active** —
`dave` is pre-locked in the seed, so locking him is a `409 NO_OP_MUTATION`
that proves nothing.

## Where this rung sits

| rung | sample | surface | tier | cards |
|---|---|---|---|---|
| 1 | [`../health-check/`](../health-check/) | `http.get` | read | 0 |
| 2 | [`../user-status/`](../user-status/) | bound browser flow | read | 0 |
| **3** | **`lock-unlock-user/` (this one)** | **`http.post`** | **write** | **1 (`action`)** |
| 4 | [`../password-reset/`](../password-reset/) | bound browser flow | write | 1 (`flow`) |
| 5 | [`../composition/`](../composition/) | runbook (4 then 3) | write (derived) | 2 (`flow` + `action`) |

Rungs 1 and 3 talk to the same JSON API and differ only in effect, which is
the pair that breaks "API means safe". [`../demo-suite.sh`](../demo-suite.sh)
runs the ladder and then locks a user over HTTP and reads the change back from
the rendered console, asserting the two revisions agree.

## Adapting for your own target

1. Copy this directory to `samples/<your-category>/<your-sample>/`.
2. Point the `http.post` URL at your mutating endpoint and add its origin to
   `GATEWAY_HTTP_ALLOW_ORIGINS` in your runtime profile.
3. Declare `risk_class: write` and **no** `web_target` — the two have been
   decoupled since SPEC-055 R-3, and a mutating skill that never opens a
   browser declares the first only.
4. Make your endpoint distinguish a real mutation from a no-op from a missing
   row (200 / 409 / 404). `mutation_confirmed` is a projection of the upstream
   status, so a target that answers 200 for everything turns it into a
   tautology and the card into a formality.
5. Return a monotonic revision or an equivalent marker on every mutation, so a
   skill can prove *which* action changed the row rather than only that
   something did.
6. Send a body your card can project, even if the route reads it from the path.
7. Write the verification as a separate read-only skill and let a composition
   put the two in either order.
