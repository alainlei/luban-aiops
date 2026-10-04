# Live Walkthrough: ACME Admin User Status Check

Rung 2 of the five. You will ask the agent, in **Chat**, to read a user's
account status off the `acme-admin` console — and it will open a headless
browser, sign in with a platform-managed credential, and read the rendered
table. **No confirmation card appears**, at any point.

That is the observation this rung exists to produce. Rung 1 parked nothing over
HTTP, which is easy to explain away as "API calls are safe, browsers are
dangerous." This one drives the same browser the mutating rungs drive, against
the same console, and parks nothing — because every step it takes is read tier.

Everything below is also exercised unattended by
[`demo/demo.sh`](demo/demo.sh); the mapping is tabulated at the end.

**Portal surface: Chat.** This is an operational session, not skill
development, so it lives in **Chat** and never in **Studio** (SPEC-056). The
authoring workspace is demonstrated by
[`samples/acme-admin/skill-graduation/WALKTHROUGH.md`](../skill-graduation/WALKTHROUGH.md);
nothing here uses it.

## Prerequisites

| Component | What must be true | Check it with |
|---|---|---|
| Cluster | dev-k8s deployed | `kubectl -n dev-luban-aiops get pods` |
| Browser surface | `GATEWAY_BROWSER_ENABLED=true` | `kubectl -n dev-luban-aiops get cm platform-runtime-config -o jsonpath='{.data.GATEWAY_BROWSER_ENABLED}'` |
| Browser allowlist | lists `http://acme-admin:8080` | same ConfigMap, key `GATEWAY_BROWSER_ALLOW_ORIGINS` |
| Browser sidecar | 2/2 containers in the tool-gateway pod | `kubectl -n dev-luban-aiops get pods -l app=tool-gateway`; logs with `-c browser` |
| Credential set | `acme-admin` present, username `admin`, non-empty password | the demo's `require_credential_set` leg |
| `acme-admin` app | deployed and ready | `make deploy-sample-app` |
| Skill installed | `/skills/samples/user-status-CheckUserStatus.md` | `make deploy-samples` |
| Portal | reachable at the canonical origin | open `https://aiops.luban.metasync.cc` |

`GATEWAY_MUTATING_TOOLS_ENABLED` is **not** needed: this flow performs no
write-tier interaction, so no write-tier tool is called.

> **The one thing that silently breaks this rung.** The admin password reaches
> two places from one generated value — the gateway's credential-sets file and
> the app's `ACME_ADMIN_PASSWORD` secret — both written by
> `sync-browser-credentials.sh`. Rotate one without the other and the sign-in is
> rejected: the console redirects back to `/admin/` and the skill reports "no
> users". Re-run the sync script; it restarts both deployments.

## Step 1: Look at the console yourself first

```sh
kubectl -n dev-luban-aiops port-forward svc/acme-admin 8080:8080 &
```

Open **http://localhost:8080/admin/**. You will see a login form. Sign in with
username `admin` and the password from the secret:

```sh
kubectl -n dev-luban-aiops get secret acme-admin-credentials \
  -o go-template='{{index .data "ACME_ADMIN_PASSWORD" | base64decode}}'; echo
```

The user list has four rows and seven columns — Name, Email, Role, **Status**,
Last modified, **Revision**, Action:

| Name | Email | Role | Status | Revision |
|---|---|---|---|---|
| Alice Johnson | alice@example.com | viewer | active | 0 |
| Bob Smith | bob@example.com | editor | active | 0 |
| Carol Williams | carol@example.com | admin | active | 0 |
| Dave Brown | dave@example.com | viewer | **locked** | 0 |

**Dave starts locked.** That is deliberate: a read-only skill needs a
non-uniform table to describe on the very first run, so the seed pre-locks one
user. It also means `dave` is a poor target for rung 3 — locking an
already-locked user is a `409 NO_OP_MUTATION` that changes nothing.

Note the footer's **store revision**. Every mutation increments it, so it is
the honest answer to "did anything happen at all?".

> The port-forward works even though the ingress NetworkPolicy admits only
> `app: tool-gateway` pods: `kubectl port-forward` is tunnelled by the kubelet
> into the pod's network namespace and never traverses pod ingress. The agent's
> browser does **not** use it — the sidecar reaches `http://acme-admin:8080`
> in-cluster, from the tool-gateway pod, through the rule the policy admits.

## Step 2: Sign in to the portal

Open **https://aiops.luban.metasync.cc** and sign in as **`luban-operator`**.

Do not use a `svc/web-ui` port-forward: the broker builds every authorization
URL from `OIDC_REDIRECT_URI` (the canonical origin), so a localhost tab never
receives the code and stays signed out. See `Runtime Wiring` in
`shared/platform-ops/gitops/dev-k8s/README.md`.

**No second identity is needed.** There is nothing to approve.

## Step 3: Open a Chat session

Click **Chat** in the sidebar and start a new session.

## Step 4: Ask for the status

Paste this into the composer as one block — **Enter sends**, so typing it line
by line submits the first line on its own (Shift+Enter makes a newline):

```
Read the current status of the acme-admin user 'alice' from the admin console
and tell me whether the account is active or locked, plus its revision.
Use skill samples/user-status-checkuserstatus. Admin credentials are in the
acme-admin credential set.
```

Naming the skill and the credential set is what `demo.sh`'s chat leg sends. It
closes the two ambiguities that make a model stall — which runbook to follow,
and where the admin password comes from. Asking for the whole list instead
("show me the acme-admin user list and who is locked") is equally valid; the
skill extracts `#user-table` for that and `#user-row-<username>` for one user.

> **You do not have to name the skill either.** "is alice's acme-admin account
> active or locked?" is enough — the agent finds the runbook through
> `skills.search`. The explicit form above is what `demo.sh` sends so its
> assertions reproduce. See
> [Asking for a runbook without naming it](../../../docs/guides/skills-guide.md#asking-for-a-runbook-without-naming-it).

**Do not paste the admin password into the chat.** The credential set exists so
that nobody has to, and the value never enters the prompt, the tool arguments
or any result.

## Step 5: What you should see

The turn should contain:

1. `web.navigate` to `http://acme-admin:8080/admin/` with
   `skill_id: samples/user-status-checkuserstatus`. **This binds the flow** —
   the origin guard and the step budget attach here.
2. `web.snapshot` of the login form. The snapshot enumerates *interactive*
   elements and assigns each a **ref**; note that the refs are integers, not
   selectors.
3. Two `web.fill_credential` calls against those refs, from credential set
   `acme-admin` — field `username`, then field `password`. Expand one: the
   argument carries a ref, a set name and a field name, and **no value**.
4. `web.wait_for` on `#user-table`. The console's login form auto-submits about
   100 ms after both fields are filled, so there is nothing to click — and
   clicking "Sign in" would have been write tier.
5. `web.extract` on `#user-table` (headers plus rows) or on `#user-row-alice`
   (that row's cell texts).
6. A prose reply quoting the **Status** cell verbatim (`active` or `locked`),
   the **Last modified** timestamp, and the **Revision**.
7. **No confirmation card. Nothing parked. No decision from anyone.**

## Step 6: See the declaration being enforced

This is optional and is the most instructive thing you can do in this rung. In
the same session, ask the agent to change something:

```
Now lock alice in that console.
```

The flow this skill bound is **read class**, so a write-tier interaction inside
it cannot run. What you see depends on whether the model attempts one, and
**both outcomes are the control working**:

- **It attempts the write.** A `web.click` (or similar) appears in the tool
  evidence and fails with **`BROWSER_FLOW_DENIED`** — not a confirmation card,
  and not a mutation. That is the gateway's flow binding refusing the call, and
  it is the refusal the skill's Interpretation section names.
- **It declines in prose and makes no tool call at all.** The skill document it
  just read says a read-class flow cannot mutate, so the model says so and
  points you at rung 3 instead. There is then no `BROWSER_FLOW_DENIED` in the
  evidence — the string may appear only *quoted* in the reply — and no
  expandable failing call to inspect.

The second is the more common of the two and is not a failure of the step. What
is being demonstrated is the invariant both outcomes share: **no confirmation
card, and no mutation** — check that alice is still `active` at the same
revision. The difference between them is only *which* control spoke first: the
skill document, or the binding behind it.

The honest reading: the skill document cannot be relied on to stop the agent
from trying — when it does not, the *binding* is what stops the mutation. If you
want the lock to succeed, that is rung 3, which declares `risk_class: write`
and parks a card.

## Honest caveats

- **`web.snapshot` will not show the status text if you ask it to.** A snapshot
  enumerates interactive elements (`a`, `button`, `input`, `select`, `textarea`
  and a few ARIA roles). The Status cell is a plain `<td>` inside a table, so
  `web.extract` is the tool that reads it. A transcript full of snapshots and no
  extract is a transcript that never read the table.
- **A redirect back to `/admin/` means the credential was rejected.** The login
  page renders the failure in `admin-login-status` and sets no session cookie.
  The symptom downstream is an `web.extract` returning no rows — which looks
  like "no users" but is really "not signed in".
- **The rendered table is server-side state, not a cache.** Both surfaces read
  one in-memory store, so a mutation made over HTTP in rung 3 is visible here
  immediately. That agreement is what [`../demo-suite.sh`](../demo-suite.sh)
  asserts, and it is the claim the whole slice makes.
- **Revisions move.** If you ran rung 3 or rung 4 first, the Revision cells
  will not read `0`. Reseed through the port-forward with
  `curl -s -X POST -H 'X-Luban-Demo-Reset: 1' localhost:8080/internal/reset-demo`.
  The agent cannot make that call — `http.post` publishes no `headers`
  parameter.
- **The step budget is finite.** `BROWSER_FLOW_EXHAUSTED` means the flow
  wandered past `GATEWAY_BROWSER_FLOW_MAX_STEPS` (default 20). Restart it rather
  than continuing.

## What just happened

```
Operator                Agent              browser sidecar        acme-admin
   │                      │                       │                    │
   │ "is alice locked?"   │                       │                    │
   │─────────────────────>│                       │                    │
   │                      │ web.navigate (bind)   │                    │
   │                      │──────────────────────>│───────────────────>│
   │                      │ web.snapshot          │                    │
   │                      │──────────────────────>│───────────────────>│
   │                      │ web.fill_credential ×2│  (no value in the  │
   │                      │──────────────────────>│   arguments)       │
   │                      │        (login auto-submits ~100ms)         │
   │                      │ web.wait_for          │                    │
   │                      │──────────────────────>│───────────────────>│
   │                      │ web.extract           │                    │
   │                      │──────────────────────>│───────────────────>│
   │  "active, rev 0"     │                       │                    │
   │<─────────────────────│                       │                    │
   │                      │                       │                    │
   │   (no card, no approval — a bound *read* flow gates nothing,      │
   │    and refuses write-tier interactions outright)                  │
```

## Step ↔ demo mapping

| Walkthrough step | Demo leg |
|---|---|
| Step 1 — the four rows, Status agreeing with `data-locked`, revision 0 | leg 2, "the human surface renders real state" |
| Step 1 — signed out, `/admin/users/` redirects rather than serving an empty table | leg 2: `302` to `/admin/`, asserted as a redirect and not as a 200 |
| Step 1 — all six routes answer | leg 2's route loop |
| Step 4 — the login form's element ids | leg 2: `admin-login-form`, `admin-username`, `admin-password`, `admin-sign-in`, `admin-login-status` |
| Step 5.2 — the refs a snapshot hands back | leg 3: the element-id contract, asserted from outside the app |
| Step 5.4 — nothing is clicked | leg 1: `web.click:write` registered, every tool the skill uses registered `read` |
| Step 5.5 — `web.extract` reads the table | chat leg: a grep for `"tool_name":"web.extract"` |
| Step 5.7 — nothing parked | chat leg: `require_zero_cards` plus `require_card_count … 0` |
| Step 6 — a write-tier interaction cannot run in this flow | not driven by the demo (the deterministic legs never bind a live flow). Leg 1's tier table (`web.click:write`, everything the skill uses `read`) is what makes the outcome predictable, and the skill's Interpretation section is what makes the model *say* it; which of the two you observe is the model's choice |
| Caveat — the one-time value never reaches served HTML | leg 3: the reset page is fetched with `?newpw=…` and asserted *not* to contain it |
| The skill declares `web_target` and no `risk_class` | leg 4: `require_skill` plus `require_no_risk_class` |

```sh
sh samples/acme-admin/user-status/demo/demo.sh
RUN_CHAT_LEG=true sh samples/acme-admin/user-status/demo/demo.sh   # + zero-card assertions
TARGET_USER=bob sh samples/acme-admin/user-status/demo/demo.sh     # report a different user
```

## Key observations

1. **A card is a property of effect, not of tooling.** Same browser, same
   console, same credential set as rung 4 — and zero cards here, one there.
2. **`web_target` without `risk_class` *is* the read declaration**, and it is
   enforced: the gateway refuses write-tier interactions in the bound flow.
   Writing `risk_class: read` would behave identically today; omitting it is the
   honest choice for a check whose entire procedure is read tier.
3. **Authentication stayed read tier** because `web.fill_credential` submits
   nothing and the form auto-submits itself. One click on "Sign in" would have
   parked the suite's only unwanted card.
4. **Rendered state and API state are different questions.** Rung 1 answers
   "what does the service report?"; this one answers "what would an operator
   see?". An API check cannot tell you the console is broken for humans while
   the JSON is fine.

## Next rung

[`../lock-unlock-user/WALKTHROUGH.md`](../lock-unlock-user/WALKTHROUGH.md)
mutates one of these accounts over `http.post` and parks exactly one
confirmation card, of kind `action` — approved by a second identity. Then
re-running *this* skill is how you verify the lock landed: a mutation made over
HTTP, observed over HTML, against one store.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `BROWSER_ORIGIN_NOT_ALLOWED` | `GATEWAY_BROWSER_ALLOW_ORIGINS` does not list `http://acme-admin:8080`. The entry belongs in the runtime profile, never in `dev-k8s/base` |
| Redirected back to `/admin/`, extract returns no rows | the credential set does not match the app's password. Re-run `sync-browser-credentials.sh` |
| `CREDENTIAL_SET_NOT_FOUND` | the `acme-admin` set is missing from the mounted sets file. Same fix |
| `BROWSER_FLOW_DENIED` on a `web.*` call | expected — you asked a read-class flow to mutate (step 6). Use rung 3 |
| Step 6 produced prose and no tool call at all | also expected, and the more common of the two outcomes: the model read the skill's own Interpretation section and declined rather than attempting a write the binding would refuse. Check the invariant instead — no card, and alice unchanged |
| `BROWSER_FLOW_ORIGIN_DEVIATED` | a navigation left the bound origin. Restart the flow; the binding is first-wins and cannot be widened |
| `BROWSER_FLOW_EXHAUSTED` | the step budget ran out, which means the flow wandered. Restart it |
| "No web.* tools available" | `GATEWAY_BROWSER_ENABLED` is false, or the sidecar is not ready: `kubectl logs -n dev-luban-aiops deploy/tool-gateway -c browser` |
| The agent clicks "Sign in" anyway | the click is write tier, so the read-class flow refuses it with `BROWSER_FLOW_DENIED` rather than parking a card — you lose the flow and must restart. Re-send naming the skill; step 4 of the skill document says explicitly not to click |
| The skill is not found | `make deploy-samples` (`SAMPLE=<one>` drops the others) |
