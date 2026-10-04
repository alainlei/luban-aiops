# Live Walkthrough: Lock or Unlock an ACME Admin User

Rung 3 of the five. You will ask the agent, in **Chat**, to lock an `acme-admin`
account. It will make **one** `http.post`, and that call will park **exactly
one** confirmation card — of kind **`action`** — which a **second identity**
must approve before anything changes.

This is the rung where the card count stops being zero, and it is paired with
rung 4 on purpose: the two make the same class of change over different
surfaces and park one card each of a *different* `approval_kind`. Do them back
to back and SPEC-054's discriminator stops being a field in a schema.

Everything below is also exercised unattended by
[`demo/demo.sh`](demo/demo.sh); the mapping is tabulated at the end.

**Portal surface: Chat** — for both identities. The operator asks in Chat; the
approver decides in **Approvals**, the decider-only inbox. Nothing here uses
**Studio** (SPEC-056), which is the skill-development workspace; see
[`samples/acme-admin/skill-graduation/WALKTHROUGH.md`](../skill-graduation/WALKTHROUGH.md)
for that.

## Prerequisites

| Component | What must be true | Check it with |
|---|---|---|
| Cluster | dev-k8s deployed | `kubectl -n dev-luban-aiops get pods` |
| HTTP surface | `GATEWAY_HTTP_ENABLED=true`, origin allowlisted | `platform-runtime-config`: `GATEWAY_HTTP_ENABLED`, `GATEWAY_HTTP_ALLOW_ORIGINS` |
| Mutating surface | `GATEWAY_MUTATING_TOOLS_ENABLED=true` | same ConfigMap. Without it `http.post` is **not registered at all** and the call fails `TOOL_NOT_FOUND` |
| HITL bridging | `AGENT_HITL_CONFIRM_TIMEOUT` not `0` **on agent-platform** — it is not a gateway ConfigMap key | `kubectl -n dev-luban-aiops exec deploy/agent-service -- printenv AGENT_HITL_CONFIRM_TIMEOUT`. Empty output (exit 1) means unset, so the default `600` applies. Only an explicit `0` excludes write-tier tools from the agent's toolkit entirely, and then no card can ever appear |
| Credential set | `acme-admin` present with a non-empty password | the demo's `require_credential_set` leg |
| `acme-admin` app | deployed and ready | `make deploy-sample-app` |
| Skill installed | `/skills/samples/lock-unlock-user-LockUnlockUser.md` | `make deploy-samples` |
| Two identities | `luban-operator` **and** `luban-approver` | see step 2 |
| Portal | reachable at the canonical origin | open `https://aiops.luban.metasync.cc` |

## Step 1: Note the starting state

```sh
kubectl -n dev-luban-aiops port-forward svc/acme-admin 8080:8080 &
```

Open **http://localhost:8080/admin/** and sign in (`admin`, plus the password
from `secret/acme-admin-credentials` — rung 2's Step 1 prints the command that
reads it). Find your target's row and note two cells:

- **Status** — `active` or `locked`
- **Revision** — `0` on a fresh or reseeded store

Pick a target that starts **active**: `alice`, `bob` or `carol`. **Do not pick
`dave`** — the seed pre-locks him, so locking him is a `409 NO_OP_MUTATION`
that changes nothing and proves nothing. (Rung 2's walkthrough explains why
the seed is non-uniform.)

Write the revision down. Step 6 is only meaningful if you can compare.

## Step 2: Sign in twice

Open **https://aiops.luban.metasync.cc** and sign in as **`luban-operator`**.
Then open a **private window or a second browser profile** and sign in there as
**`luban-approver`**.

You will need both at step 5. Mutating execution carries a tier-2 approval
requirement decided by `approver` or `platform-admin`, and **the requester
cannot decide their own call** (SPEC-030 R-4) — so this is not a formality you
can skip by using one identity twice.

Do not reach the portal through a `svc/web-ui` port-forward: the broker builds
every authorization URL from `OIDC_REDIRECT_URI` (the canonical origin), so a
localhost tab never receives the code and stays signed out. See `Runtime
Wiring` in `shared/platform-ops/gitops/dev-k8s/README.md`.

## Step 3: Open a Chat session as the operator

In the `luban-operator` window, click **Chat** and start a new session.

## Step 4: Ask for the lock

Paste this into the composer as one block — **Enter sends**, so typing it line
by line submits the first line on its own (Shift+Enter makes a newline):

```
Lock the acme-admin account for 'carol'. Use skill
samples/lock-unlock-user-lockunlockuser. The admin credentials are in the
acme-admin credential set — do not ask me for a password.
```

Naming the skill, the credential set and the direction is what `demo.sh`'s chat
leg sends. The direction matters: "lock" and "unlock" are not interchangeable,
they hit different endpoints, and the card an approver reads differs. If the
caller does not say which, the skill says to ask rather than guess.

> **Regular use is shorter.** You do not have to name the skill or the credential
> set — "lock carol's acme-admin account" is enough, and the agent finds the
> runbook through `skills.search`. Keep the direction ("lock", not "unlock"): it is
> the one thing the skill cannot infer and will ask for if you omit it. The
> explicit form above is what `demo.sh` sends so its assertions reproduce. See
> [Asking for a runbook without naming it](../../../docs/guides/skills-guide.md#asking-for-a-runbook-without-naming-it).

The agent should make **one** `http.post`:

```
url:             http://acme-admin:8080/api/users/carol/lock
body:            {"locked": true}
credential_set:  acme-admin
```

and then stop, waiting. It should **not** retry, split the call in two, or
reach for the browser surface as a workaround — the gate is the point.

> **Why a body the endpoint ignores?** `/api/users/{id}/lock` takes no request
> body; the action is in the path. `{"locked": true}` is sent anyway and the app
> ignores it, because the body is what the card projects: with it the approver
> reads `1 field: locked`, and without it the card names only a URL. This is a
> choice and not a requirement — the skill document says so out loud.

## Step 5: The card, and who decides it

A **confirmation card** appears in the operator's transcript. It shows:

- `approval_kind` = **`action`** — one approval for exactly one call. Rung 4's
  card reads `flow`, and the difference is the pair's whole content.
- The pending call: **`http.post`**, `risk_level` = **`write`**.
- A **legible `change_request.summary`**:

  ```
  POST to http://acme-admin:8080/api/users/carol/lock — 1 field: locked
  ```

  An approver decides on the **origin**, the **path** and the **field**. The
  generic fallback would have rendered `url: *** body: ***` — approval theatre
  that manufactures a record of a considered decision. This projection is
  SPEC-058 R-5's kernel-side formatter.
- A `credential_set` row naming the reference **`acme-admin`** — never a value.
  Neither verb publishes a `headers` parameter, so a secret cannot be a
  model-supplied literal at all. That is a structural control, not a
  convention.

**The operator cannot approve it.** On an `operator`'s screen the card renders
**no Approve or Deny button at all**, only the note "This request needs a
designated approver — your current role cannot approve or deny it."

That note is a display hint (SPEC-030 R-5) and the gateway stays authoritative.
Post the decision straight to `/api/v1/chat/confirm` as the operator and it
answers `403` with `reason: not_a_designated_approver` and
`approval_tier: tier_2` — the decider-role check runs before the self-approval
one, and `operator` holds no decider role at all. `self_approval` is the reason
a *designated decider* gets on a session they own, because tier 2 blocks
self-approval even for an approver. Either way the card stays parked.

Switch to the **`luban-approver`** window and open **Approvals** in the sidebar
— the decider-only inbox, badged with the pending count. The parked card
renders there identically to the one in the operator's transcript (same
component), under a provenance header naming the session and its owner. Approve
it. The operator's stream resumes and the call executes.

**Try denying it once**, in a fresh session, if you have the time. A denial
means nothing changed: the revision does not move, and step 6 will show that.
The skill's Interpretation section is explicit that a denial is an answer to
report, not an obstacle to route around.

## Step 6: Read the outcome

The resumed turn reports the response body:

| Field | What it tells you |
|---|---|
| `action` | `lock` (or `unlock`) — which direction actually ran |
| `username` | the resolved account |
| `locked` | the resulting state |
| `last_modified` | **microsecond precision, UTC** — two mutations in the same second stay distinguishable |
| `revision` | the post-mutation revision. This is the number to compare with step 1 |
| `password_changed_at` | unchanged by a lock; a lock is not a reset |

Then reload **http://localhost:8080/admin/users/** in your own browser. The
Status cell reads `locked`, the Revision cell matches, and the footer's store
revision moved by exactly one.

The strongest form of this check is to ask the agent for it in a **new Chat
session**, using rung 2's skill:

```
Read the current status of the acme-admin user 'carol' from the admin console
and tell me whether the account is active or locked, plus its revision.
Use skill samples/user-status-checkuserstatus. Admin credentials are in the
acme-admin credential set.
```

That is the suite's cross-skill verification: a mutation made over **HTTP**,
observed over **HTML**, against **one store**. `demo-suite.sh` asserts exactly
this agreement, including that the revision the console renders equals the
revision the API reported.

## Honest caveats

- **`409 NO_OP_MUTATION` is an answer, not a failure.** Locking an
  already-locked user returns `status: 409`, `error: NO_OP_MUTATION` and
  `mutation_confirmed` = **`false`**. Nothing broke, nothing changed, the
  revision did not move. Report "already locked". A target that answered 200
  for everything would make `mutation_confirmed` a tautology and the card a
  formality — which is why this app answers 200, 409, 404 and 401 separately.
- **`404 UNKNOWN_USER`** means no such username or email. Report the identifier
  you used and stop; do not try a similar name.
- **`401`** means the credential set did not authenticate. The response carries
  `WWW-Authenticate: Basic realm="acme-admin"`. Report that the
  platform-managed credential is wrong or missing — never ask the caller for a
  password.
- **An upstream 4xx is a successful tool result** carrying that status, not a
  tool error. The tool-layer HTTP status stays 200.
- **The deterministic demo legs prove the projection, not the gate.** A direct
  `POST /api/v2/tools/invoke` of a write-tier tool carries **no** card: the gate
  lives in the kernel's HITL bridge, not in the gateway. Only the chat leg —
  here, steps 4 to 6 — exercises an approval. Conflating the two is how a demo
  ends up claiming an approval it never ran.
- **The store is in memory.** A pod restart reverts it to the seed, and the
  Deployment pins `replicas: 1` because two replicas would be two consoles that
  disagree.

## What just happened

```
Operator          Agent           kernel HITL        Approver        acme-admin
   │                │                  │                │               │
   │ "lock carol"   │                  │                │               │
   │───────────────>│                  │                │               │
   │                │ http.post (write)│                │               │
   │                │─────────────────>│  PARK          │               │
   │  ┌───────────┐ │                  │                │               │
   │  │ action    │ │                  │   ┌──────────┐ │               │
   │  │ card      │ │                  │   │Approvals │ │               │
   │  │ (no btns) │ │                  │   │ inbox    │ │               │
   │  └───────────┘ │                  │   └──────────┘ │               │
   │                │                  │<───────────────│ approve       │
   │                │                  │────────────────────────────────>│
   │                │                  │   200 locked=true revision=N    │
   │                │<─────────────────│<────────────────────────────────│
   │ "carol locked" │                  │                │               │
   │<───────────────│                  │                │               │
```

## Step ↔ demo mapping

| Walkthrough step | Demo leg |
|---|---|
| Step 1 — Status and Revision before | the cross-skill leg of `../demo-suite.sh` asserts the baseline (`locked: false`, revision `0`) before mutating |
| Step 4 — `http.post` registered write | leg 1: `require_tools_registered "http.post:write" "http.get:read"` |
| Step 4 — the endpoint really distinguishes outcomes | leg 2: 200, `409 NO_OP_MUTATION`, `404 UNKNOWN_USER`, `401` with the Basic challenge |
| Step 4 — the body the endpoint ignores | leg 3: the same call twice, `mutation_confirmed` true then false |
| Step 5 — one card, kind `action`, naming `http.post` at write tier | chat leg: `require_card_shape … action http.post` |
| Step 5 — the summary names origin and path | chat leg: the two `case` assertions on `change_request.summary` |
| Step 5 — a second identity decides | chat leg: `chat_confirm` posts as `luban-approver`, then asserts `"status": "approved"` |
| Step 5 — exactly one card, not two | chat leg: `require_card_count "$SESSION" 1` on the **durable** session |
| Step 6 — the store moved | chat leg: `GET /api/users/<target>` asserts `locked: true` and `revision >= 1` |
| Step 6 — the console agrees | `../demo-suite.sh`'s cross-skill leg: the rendered row's `data-locked`, Status cell, Revision cell and the footer's store revision |
| Caveat — `409` leaves the revision unmoved | leg 2: the refused no-op is followed by a `GET` asserting revision is still `1` |
| Caveat — a lock is not a reset | `../demo-suite.sh`: the "Recent Password Resets" panel must still be empty |
| The credential can only be a reference | leg 4: the published discovery document is asserted to carry **no** `headers` parameter on either verb, and a `credential_set` on both |
| Refusals are structural | leg 4: a non-allowlisted origin answers `403 HTTP_ORIGIN_NOT_ALLOWED`; a secret-bearing query answers `400 HTTP_URL_SECRET_NOT_ALLOWED` |
| The skill declares `risk_class: write` and no `web_target` | leg 5: `require_skill` plus the explicit `web_target` absence check |

```sh
sh samples/acme-admin/lock-unlock-user/demo/demo.sh
RUN_CHAT_LEG=true sh samples/acme-admin/lock-unlock-user/demo/demo.sh  # + the card and the approval
TARGET_USER=bob sh samples/acme-admin/lock-unlock-user/demo/demo.sh
```

The chat leg needs the identity-service port-forward on `18081` **and** the
platform-gateway port-forward on `18083`, because it issues tokens for both
identities itself.

## Key observations

1. **The card is `action` because nothing was bound.** `flow` is reserved for a
   bound browser flow, where one approval unlocks the rest of the flow's
   write-tier interactions (ADR-0007). This skill opens no browser, so its one
   gated call gets one decision.
2. **`risk_class: write` did not create the gate.** `http.post`'s registry tier
   did. The declaration keeps the catalogue honest and keeps the skill
   graduable under SPEC-055 — and, since SPEC-055 R-3, it no longer requires a
   `web_target`, so a mutating skill that never opens a browser declares the
   first and not the second.
3. **Legibility is a safety property.** An approver who reads `url: *** body:
   ***` is not approving anything; they are recording that someone asked. The
   origin, the path and the field name are the minimum that makes the decision
   real.
4. **Verification is a separate skill**, so the two halves can be run by
   different people at different times, and so a composition (SPEC-057) can put
   them in either order. A skill that mutates *and* verifies hides which half
   produced the evidence.

## Next rung

[`../password-reset/WALKTHROUGH.md`](../password-reset/WALKTHROUGH.md) performs
the same class of change through a browser flow and parks one card of kind
**`flow`**, headed by the skill's authored `flow_intent`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `TOOL_NOT_FOUND` for `http.post` | `GATEWAY_HTTP_ENABLED` or `GATEWAY_MUTATING_TOOLS_ENABLED` is false. Check both in the live runtime config and report which |
| No card appears and the call just runs | `AGENT_HITL_CONFIRM_TIMEOUT=0` excludes write-tier tools from the toolkit, or you invoked the gateway directly rather than through the agent — see the caveat above |
| The card shows no Approve button | correct: you are signed in as `luban-operator`, who holds no decider role. Decide it in the `luban-approver` window's **Approvals** inbox |
| `403 not_a_designated_approver` | you posted the decision as the operator. Same fix |
| `403 self_approval` | a designated decider tried to decide a session they own. Tier 2 blocks that even for an approver — use a second identity |
| `409 NO_OP_MUTATION` | the target was already in that state. Pick an active target for a lock (`dave` starts locked), or reverse the direction |
| `HTTP_ORIGIN_NOT_ALLOWED` | the origin is not on `GATEWAY_HTTP_ALLOW_ORIGINS`. It belongs in the runtime profile, never in `dev-k8s/base` |
| `HTTP_URL_SECRET_NOT_ALLOWED` | the URL carried a secret-bearing query parameter. Rebuild it from the path alone — this skill's URLs never need one |
| `401` from the app | the credential set does not match `ACME_ADMIN_PASSWORD`. Re-run `sync-browser-credentials.sh` |
| The agent tries the browser instead after a denial | it must not. A denial is final: report it and stop |
| The skill is not found | `make deploy-samples` (`SAMPLE=<one>` drops the others) |
