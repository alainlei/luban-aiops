# Live Walkthrough: Reset a Password in the ACME Admin Console

Rung 4 of the five, and the last single-skill rung. You will ask the agent, in
**Chat**, to reset an `acme-admin` account's password *through the console's own
UI*. It will bind a browser flow, sign in, open the pre-filled reset form, and
make **one** write-tier click — which parks **exactly one** confirmation card,
of kind **`flow`**, headed by the skill's authored `flow_intent`. A **second
identity** approves it, and the password really changes.

This is also the rung the shipped static target could not honestly claim. That
target's confirmation page echoed its own query parameters, so it reported
success for any user — including users that did not exist — and its walkthrough
had to warn the reader that the URL they had just been shown was a lie. This app
mutates a store, bumps a revision, records `password_changed_at`, and answers the
confirmation page *from that store*. Step 7 shows you how to tell the difference
yourself.

Everything below is also exercised unattended by
[`demo/demo.sh`](demo/demo.sh); the mapping is tabulated at the end.

**Portal surface: Chat** — for both identities. The operator asks in Chat; the
approver decides in **Approvals**. Nothing here uses **Studio** (SPEC-056); for
the authoring workspace see
[`samples/acme-admin/skill-graduation/WALKTHROUGH.md`](../skill-graduation/WALKTHROUGH.md).

## Prerequisites

| Component | What must be true | Check it with |
|---|---|---|
| Cluster | dev-k8s deployed | `kubectl -n dev-luban-aiops get pods` |
| Browser surface | `GATEWAY_BROWSER_ENABLED=true`, origin on `GATEWAY_BROWSER_ALLOW_ORIGINS` | `platform-runtime-config` |
| Mutating surface | `GATEWAY_MUTATING_TOOLS_ENABLED=true`, or `web.click` is not registered and the flow cannot complete | same ConfigMap |
| HTTP surface | `GATEWAY_HTTP_ENABLED=true`, origin on `GATEWAY_HTTP_ALLOW_ORIGINS` — step 9 of the skill verifies over `http.get` | same ConfigMap |
| Browser sidecar | 2/2 containers in the tool-gateway pod | `kubectl logs -n dev-luban-aiops deploy/tool-gateway -c browser` |
| HITL bridging | `AGENT_HITL_CONFIRM_TIMEOUT` not `0` **on agent-platform** — it is not a gateway ConfigMap key | `kubectl -n dev-luban-aiops exec deploy/agent-service -- printenv AGENT_HITL_CONFIRM_TIMEOUT`; empty output (exit 1) means unset, so the default `600` applies |
| Credential set | `acme-admin` present with a non-empty password | the demo's `require_credential_set` leg |
| `acme-admin` app | deployed and ready | `make deploy-sample-app` |
| Skill installed | `/skills/samples/password-reset-ResetAcmePassword.md` | `make deploy-samples` |
| Two identities | `luban-operator` **and** `luban-approver` | step 2 |
| Password source | supply a one-time value, or opt in to platform generation below | step 4 |

## Optional: Generate the temporary password (SPEC-062)

The supplied-value steps below remain supported. With `GATEWAY_SECRETS_ENABLED=true`
and the delegation chain configured, you can instead ask:

> Reset alice's acme-admin password through the console. Generate a strong one and let me copy it.

The runbook calls `secrets.generate_password(handoff="portal_copy")`; generation
adds no approval. The reset still needs its one flow approval and authoritative
verification. **Copy password** can appear before reset completion: the button
proves only generation, not that the account changed. Copy once from the original
requester's signed-in portal in a secure clipboard context. Never ask the agent
to print the value. Expired/spent handles cannot recover it; generating another
password does not update the account without another approved reset. Email is a
separate, explicitly requested outbound action with its own approval.

`make secret-delivery-demo` runs the local sample handoff proof (including the
clipboard test) without a cluster, email, or account mutation. It is also part of
`make verify`; install the portal's npm dependencies first. For an explicitly
approved live **generation-only** handoff, use
`sh samples/acme-admin/password-reset/demo/demo.sh --secret-delivery-live` with
the token and log-access prerequisites documented in
[`secret-delivery-demo.sh`](../../../shared/platform-ops/e2e/secret-delivery-demo.sh).
The live leg consumes a throwaway handle through the same API as Copy password;
it does not manipulate the browser clipboard or reset an account. The remaining
walkthrough/demo continues to verify the reset separately.

## Step 1: Prepare a starting state you can compare against

```sh
kubectl -n dev-luban-aiops port-forward svc/acme-admin 8080:8080 &
curl -s -X POST -H 'X-Luban-Demo-Reset: 1' localhost:8080/internal/reset-demo
```

The reseed answer names `status: reseeded`, `store_revision: 0`,
`seed_revision: 0` and the four seeded users. Then open
**http://localhost:8080/admin/** and sign in (`admin`, plus the password from
`secret/acme-admin-credentials` — rung 2's Step 1 prints the command that reads
it) and note your target's **Revision** cell.

> **The agent cannot make that reseed call.** `/internal/reset-demo` requires the
> `X-Luban-Demo-Reset` header, and `http.post` publishes no `headers` parameter
> at all — so the one endpoint that could wipe demo state mid-run is closed
> structurally, on an origin that is otherwise allowlisted. There is also no
> OpenAPI document and no `/docs`, because both are unauthenticated by nature and
> would publish that endpoint to anything which can reach the pod.

Choose a target: `alice`, `bob`, `carol` or `dave`. Any of them works here —
unlike rung 3, a reset is never a no-op.

Choose a **one-time** password, e.g. `TempPass-2026!`. It is a throwaway value
for a store that discards it: the app records *when* the reset happened and which
revision it produced, and never stores the password.

## Step 2: Sign in twice

Open **https://aiops.luban.metasync.cc** as **`luban-operator`**, then open a
**private window or second profile** as **`luban-approver`**. Tier-2 approval,
and the requester cannot decide their own call (SPEC-030 R-4).

Do not use a `svc/web-ui` port-forward: the broker builds every authorization
URL from `OIDC_REDIRECT_URI`, so a localhost tab never receives the code. See
`Runtime Wiring` in `shared/platform-ops/gitops/dev-k8s/README.md`.

## Step 3: Open a Chat session as the operator

Click **Chat** and start a new session.

## Step 4: Ask for the reset

Paste this into the composer as one block — **Enter sends**, so typing it line
by line submits the first line on its own (Shift+Enter makes a newline):

```
Reset the acme-admin password for 'alice' through the admin console UI.
Use skill samples/password-reset-resetacmepassword. The new temporary password
is 'TempPass-2026!'. Admin credentials are in the acme-admin credential set.
```

Naming the skill, the credential set and the one-time value is what `demo.sh`'s
chat leg sends. The value must be in the message: it is a chat-supplied
one-time secret, never stored in the skill, never committed, and — as step 6
shows — never present in any tool output.

> **Regular use is shorter.** You do not have to name the skill or the credential
> set — "reset alice's acme-admin password to 'TempPass-2026!'" is enough, and the
> agent finds the runbook through `skills.search`. The explicit form above is what
> `demo.sh` sends so its assertions reproduce. See
> [Asking for a runbook without naming it](../../../docs/guides/skills-guide.md#asking-for-a-runbook-without-naming-it).

**The session title in the sidebar masks it.** It reads

```
Reset the acme-admin password for 'alice' through the admin console UI. Use sk
```

or, depending on where the cap falls, `… temporary password is *** …`. The title
is minted from your own message, which is the one credential carrier no
tool-side redactor ever sees — you typed the value into the chat, so it is in the
prompt text, not in a tool argument — and it is the label an approver's inbox
lists this session by, so it reaches a second identity. Masking runs *before* the
80-character cap, which is why nothing of the secret survives: truncating first
would leave its leading characters readable (SPEC-049 R-5).

**So is the reply prose, and your own turn when it is read back.** The model
reads the value in its own prompt and can write it back out. Both now mask: the
live stream as it arrives, and the durable transcript on reload, for the
assistant's reply *and* for your own message.

Two boundaries, because a walkthrough that overclaims is worse than one that
underclaims:

- **Your own bubble reads plaintext while the turn is live.** It is rendered from
  your composer in your own browser, not from a stream frame; where the kernel
  does echo your message — its unconfigured and provider-error fallbacks — it
  masks it first. The bubble reads `***` once the session is reloaded.
- **The value stays real in the agent's own context at rest**, because the model
  needs it to perform the reset. Masking is a property of every *human-readable
  projection* — title, transcript, live stream, cards, evidence — not of the
  machine input the reset runs from.

## Step 5: What the agent does before the gate

The turn should contain, in order:

1. `web.navigate` to `http://acme-admin:8080/admin/` with
   `skill_id: samples/password-reset-resetacmepassword`. **This binds the
   flow** — origin guard, step budget, and the flow's single approval all attach
   here.
2. `web.snapshot` of the login form, to pick up element **refs**.
3. Two `web.fill_credential` calls from set `acme-admin` (username, then
   password). Read tier, and the arguments carry no value.
4. The login **auto-submits** (~100 ms) and the flow settles with `web.wait_for`
   on `#user-table`. Nothing is clicked.
5. A read of the table — the target's row and their current **Revision**.
6. `web.navigate` to
   `http://acme-admin:8080/admin/users/reset/?user=alice&newpw=TempPass-2026!`.
   Read tier, because navigating is not interacting. The page's own script
   pre-fills both password fields from the query string and deliberately does
   **not** submit.

**Expand that `web.navigate` in the tool evidence.** Its arguments read
`?user=alice&newpw=***` — the secret query value masked, every other byte of the
URL intact. A `tool_call` frame is the record of what was actually invoked, so
it keeps its shape and loses only the secret; that is a deliberately narrower
projection than the fail-closed one SPEC-055 R-7 applies to an *action* card's
arguments, which would render `{ "url": "***" }` and destroy the evidence the
panel exists to show.

## Step 6: The one card, and who decides it

The agent's next step is `web.click` on `#confirm-reset` — the flow's **single
write-tier interaction** — and that is where the card parks. It shows:

- `approval_kind` = **`flow`**, not `action`. One approval covers the flow's
  remaining write-tier interactions (ADR-0007), so following the confirmation
  link afterwards parks no second card.
- The **`flow_intent` headline**, above the demoted DOM/technical detail:

  > Submit the password reset for the target acme-admin account, permanently
  > replacing that user's console password.

  That sentence is authored in the skill's frontmatter (SPEC-053 R-4). It is
  display-only — never a security input — and it carries no credential.
- The target origin, and the write-tier interaction being authorised.
- **No plaintext one-time value.** `demo.sh` asserts this against the
  confirmation frames themselves, before and after the approval.

**The operator cannot approve it.** On an `operator`'s screen the card renders
**no Approve or Deny button**, only the note "This request needs a designated
approver — your current role cannot approve or deny it." That note is a display
hint (SPEC-030 R-5); the gateway stays authoritative and answers a
self-posted decision with `403 not_a_designated_approver`,
`approval_tier: tier_2`.

Switch to the **`luban-approver`** window, open **Approvals**, and approve the
card there. It renders identically to the operator's copy (same component),
under a provenance header naming the session and its owner. The operator's stream
resumes and the click executes.

## Step 7: Verify — and prove the verification is real

The agent reads `#reset-status` with `web.extract`, expecting:

```
Password for alice has been reset successfully.
```

Do **not** go looking for that sentence in a `web.snapshot`: a snapshot
enumerates interactive elements only, and the status line is a plain
`<p role="status">`, so it is legitimately absent from every snapshot in the
transcript. This is the single most common false alarm in this walkthrough.

Then the skill verifies from a **second surface**: one `http.get` with
`credential_set: "acme-admin"` against `/api/users/alice`, reporting the bumped
`revision` and `password_changed_at`, plus a `web.screenshot` as visual evidence.

**Now do the check that separates this app from the static one it replaces.** In
your own browser, open the confirmation page while asking it about a *different*
user than the one you reset:

```
http://localhost:8080/admin/users/reset/done/?user=dave&at=whenever
```

It reports **`Password for alice has been reset successfully.`** — the store's
record, not the query string it was handed. The static target echoed `dave` back
at you and would have claimed success for a user who was never touched.
`demo.sh` performs exactly this check and fails if the page echoes its input.

Reload the user list too: the target's **Revision** moved, their
`password_changed_at` is set, the "Recent Password Resets" panel names them, and
the footer's **store revision** matches.

## Honest caveats

- **The reset is permanent for the life of the pod.** The store is in memory, so
  a restart reverts to the seed — which is why the Deployment pins
  `replicas: 1` and why step 1 reseeds.
- **A refusal spends the gate.** If the app answers `PASSWORD_MISMATCH`,
  `INVALID_PASSWORD` or `UNKNOWN_USER`, the form stays usable but the flow's
  single approval has been consumed. Restart the flow rather than clicking
  again.
- **`Error: passwords do not match.`** means the two fields were not both
  pre-filled, so the new password did not arrive intact. Report it; do not type
  into the fields directly (`web.type` is write tier and would move the gate).
- **A redirect back to `/admin/`** means the session cookie was not set or was
  dropped. Re-run from the beginning.
- **The gate has moved before, and that history matters.** An earlier revision of
  the shipped sample gated the *sign-in* click and auto-submitted the reset —
  which asked an approver to authorise a login and then changed a password they
  had never seen mentioned. SPEC-051 moved the gate onto the mutation, and this
  app preserves that asymmetry in code: the login form auto-submits, the reset
  form does not. `demo.sh` asserts the served page never calls `.submit()`.
- **The one-time value is masked, not absent.** It stays real in the agent's own
  context, because the model needs it to perform the reset. Every
  human-readable projection masks it; the machine input does not.

## What just happened

```
Operator          Agent          browser sidecar     Approver      acme-admin
   │                │                  │                │              │
   │ "reset alice"  │                  │                │              │
   │───────────────>│                  │                │              │
   │                │ web.navigate (bind flow)          │              │
   │                │─────────────────>│───────────────────────────────>│
   │                │ web.snapshot / fill_credential ×2 │              │
   │                │─────────────────>│───────────────────────────────>│
   │                │        (login auto-submits; no click)            │
   │                │ web.navigate ?user=alice&newpw=*** │              │
   │                │─────────────────>│───────────────────────────────>│
   │                │ web.click #confirm-reset (WRITE)  │              │
   │                │─────────> PARK    │                │              │
   │  ┌───────────┐ │                  │   ┌──────────┐ │              │
   │  │ flow card │ │                  │   │Approvals │ │              │
   │  │ + intent  │ │                  │   │  inbox   │ │              │
   │  └───────────┘ │                  │   └──────────┘ │              │
   │                │                  │<───────────────│ approve      │
   │                │─────────────────>│───────────────────────────────>│
   │                │                  │  200 revision=N password_changed_at
   │                │ web.extract #reset-status         │              │
   │                │─────────────────>│───────────────────────────────>│
   │                │ http.get /api/users/alice (verify)│              │
   │                │──────────────────────────────────────────────────>│
   │  "reset done"  │                  │                │              │
   │<───────────────│                  │                │              │
```

## Step ↔ demo mapping

| Walkthrough step | Demo leg |
|---|---|
| Step 1 — the reseed restores a known state, and the header gate refuses a headerless POST | `reseed_demo` (run by every demo in the suite via `acme_demo_init`): 403 `DEMO_RESET_HEADER_REQUIRED` without the header, then `status: reseeded`, revision 0, four users |
| Step 5.1–5.4 — the flow's tools are read tier, and the click is not | leg 1: `web.navigate`/`web.fill_credential`/`web.wait_for`/`web.extract` at `read`, `web.click` at `write` |
| Step 5.6 — the page pre-fills client-side | leg 4: the served reset page is asserted **not** to contain the one-time value |
| Step 6 — one card, kind `flow` | chat leg: `require_card_shape … flow` against the write-tier web tool set |
| Step 6 — the `flow_intent` headline | chat leg: `flow_summary.flow_intent` must be present |
| Step 6 — no plaintext in any confirmation frame | chat leg: `require_no_plaintext_in_cards` on the parked stream **and** on the resumed one |
| Step 6 — a second identity approves | chat leg: `chat_confirm` as `luban-approver`, asserting `"status": "approved"` |
| Step 6 — no second card after approval | chat leg: `count_cards` on the resumed stream must be `0`, and `require_card_count … 1` on the durable session |
| Step 7 — the reset really mutates | leg 2: `ok: true`, revision `1`, `password_changed_at` set, `redirect` to the done page |
| Step 7 — the JSON API corroborates | leg 2: `GET /api/users/<target>` carries `password_changed_at` and revision `1` |
| Step 7 — **the confirmation page reports the store, not the query** | leg 2: the done page is asked about `dave` and must still report the target, and must not echo `dave` |
| Step 7 — the user list surfaces the reset | leg 2: `last-reset-user` and `store-revision` are `1` |
| Caveat — refusals | leg 3: `400 PASSWORD_MISMATCH`, `404 UNKNOWN_USER`, `401 SESSION_REQUIRED` for a forged cookie |
| Caveat — the form never submits itself | leg 4: the page is bound to `doReset` and asserted to contain no `.submit()` |
| Step 5 — the gateway masks the value in the URL it projects | leg 4: `http.get` on a URL carrying `newpw` must come back `newpw=***` with `user=alice` intact |
| The skill declares `web_target`, `risk_class: write` and a `flow_intent` | leg 1's `require_skill` patterns |

```sh
sh samples/acme-admin/password-reset/demo/demo.sh
RUN_CHAT_LEG=true sh samples/acme-admin/password-reset/demo/demo.sh  # + the card and the approval
TARGET_USER=bob NEW_PASSWORD='Another-Temp-1!' sh samples/acme-admin/password-reset/demo/demo.sh
```

The chat leg needs the identity-service port-forward on `18081` **and** the
platform-gateway port-forward on `18083`.

## Key observations

1. **One write-tier interaction, one card — on the mutation.** Signing in,
   navigating and reading are all read tier. The gate lands on the action the
   operator actually means to approve.
2. **`flow` buys exactly one thing over `action`:** the approval covers the
   flow's remaining write-tier interactions. Run rung 3 and rung 4 back to back
   and the discriminator is something you have seen twice rather than read once.
3. **The confirmation is evidence because the store answers it.** A page that
   reports its own query parameters is a sentence, not a fact. Asking it about
   the wrong user is the cheapest way to tell the two apart.
4. **Two surfaces, one store.** The browser performs the reset; `http.get`
   confirms it. `http.post` could not have performed it — it refuses a
   secret-bearing query outright (`HTTP_URL_SECRET_NOT_ALLOWED`) and publishes no
   `headers` parameter — and that refusal is the correct design, not a gap this
   skill works around.

## Where to go next

- Run [`../demo-suite.sh`](../demo-suite.sh) for all five rungs in order plus the
  cross-skill verification, or `make e2e` for the whole verification path.
- The other two `acme-admin` browser samples drive this *same* console under the
  two other approval models; together the three are the entry points to the
  browser surface, and this walkthrough is the **flow** model — the bound,
  one-gate artifact the graduation sample produces:
  - [`../adhoc-password-reset/WALKTHROUGH.md`](../adhoc-password-reset/WALKTHROUGH.md)
    — the **action** model: no bound flow, so every write parks its own
    per-action card (SPEC-054).
  - [`../skill-graduation/WALKTHROUGH.md`](../skill-graduation/WALKTHROUGH.md)
    — **author, then graduate**: do the work ad hoc, then turn the approved
    mutations into the bound flow this walkthrough replays, collapsing N cards
    to one gate (SPEC-055).

## Troubleshooting

| Symptom | Fix |
|---|---|
| No `web.*` tools | `GATEWAY_BROWSER_ENABLED` is false, or the sidecar is not ready |
| `web.click` reports `TOOL_NOT_FOUND` | `GATEWAY_MUTATING_TOOLS_ENABLED` is false — the flow cannot complete without it |
| No card appears | `AGENT_HITL_CONFIRM_TIMEOUT=0` excludes write-tier tools from the toolkit |
| The card shows no Approve button | correct: you are `luban-operator`. Decide it in the `luban-approver` window's **Approvals** inbox |
| `Error: passwords do not match.` | the pre-fill did not land in both fields. Restart the flow; do not type into the fields |
| `PASSWORD_MISMATCH` / `INVALID_PASSWORD` / `UNKNOWN_USER` | the app refused the reset and reports its own wording. The gate is spent — restart the flow |
| `#reset-status` missing from every snapshot | expected: it is a plain `<p role="status">`, invisible to `web.snapshot`. Use `web.extract` |
| `BROWSER_ORIGIN_NOT_ALLOWED` | the origin is not on `GATEWAY_BROWSER_ALLOW_ORIGINS`. Runtime profile, never `dev-k8s/base` |
| `BROWSER_FLOW_DENIED` | a write-tier interaction outside the flow's approval, or a read-class flow. Restart from `web.navigate` |
| `BROWSER_FLOW_ORIGIN_DEVIATED` | a navigation left the bound origin. Restart; the binding is first-wins |
| `BROWSER_FLOW_EXHAUSTED` | the step budget (`GATEWAY_BROWSER_FLOW_MAX_STEPS`, default 20) ran out — the flow wandered. Restart it |
| `HTTP_URL_SECRET_NOT_ALLOWED` on the verification call | a `newpw` parameter leaked into the API URL. Rebuild it from the path alone |
| Redirected back to `/admin/` | the session cookie was dropped, or the credential set does not match `ACME_ADMIN_PASSWORD`. Re-run `sync-browser-credentials.sh` |
| The confirmation page names a user you did not reset | you are reading the query string, not the store. Reload `/admin/users/` and check the Revision cell |
| The skill is not found | `make deploy-samples` (`SAMPLE=<one>` drops the others) |
