# ACME Admin Password Reset (bound browser flow, one `flow` card)

Rung 4 of the five-rung `acme-admin` ladder (SPEC-059 R-7). A bound browser
flow with exactly one write-tier interaction — the "Confirm reset" click —
parking exactly one confirmation card, of kind **`flow`**.

This is the last single-skill rung and the one rung the shipped static target
could not honestly claim. A page that echoes its own query parameters reports
success for a user who does not exist, so the walkthrough that used it had to
warn the reader that the URL they had just been shown was a lie. This app
mutates a store, bumps a revision, records `password_changed_at`, and answers
the confirmation page *from that store* — so the confirmation is evidence
rather than a sentence the page always printed.

## What this sample contains

| Path | Purpose |
|---|---|
| `skill/ResetAcmePassword.md` | The skill document — nine steps, one gated, annotated with why the gate sits on the mutation and not on sign-in |
| `demo/demo.sh` | Standalone demo: flow preconditions → the reset really mutates → the app's refusals → masking and no-auto-submit → optional chat leg |
| `WALKTHROUGH.md` | The same story driven by hand through the operator portal's **Chat**, approved by a second identity |

Skill id: **`samples/password-reset-resetacmepassword`**.

The filename is deliberate, and its rationale is now historical.
`deploy-samples.sh` derives an id from the sample directory's leaf name plus the
file name, so a `password-reset/skill/ResetUserPassword.md` here would produce
`samples/password-reset-resetuserpassword` — which is why SPEC-059 named this
document `ResetAcmePassword.md`: the static `samples/web-checks/password-reset/`
sample already owned that id, and two `--from-file` arguments with the same
ConfigMap key is a hard failure. SPEC-060 retired that static sample, so the
collision it was named around no longer exists — but the name stays, because
renaming a delivered skill would re-id it. All five ids in the repository are
asserted pairwise distinct by [`../demo-suite.sh`](../demo-suite.sh) (and, from
the source tree, by
`app/tests/test_packaging.py::test_derived_skill_ids_are_unique`).

## Prerequisites

| Requirement | Why this rung needs it |
|---|---|
| `make deploy` with the `browser-dev` runtime profile | `GATEWAY_BROWSER_ENABLED=true`, the origin on `GATEWAY_BROWSER_ALLOW_ORIGINS`, the credential-sets file mounted |
| `make deploy` with the `mutating-dev` runtime profile | `GATEWAY_MUTATING_TOOLS_ENABLED=true`, or `web.click` is not registered and the flow cannot complete |
| Browser sidecar ready | 2/2 containers in the tool-gateway pod |
| `AGENT_HITL_CONFIRM_TIMEOUT` not `0` on agent-platform | otherwise write-tier tools are excluded from the toolkit |
| A **designated approver** distinct from the operator | tier-2 approval; `luban-approver` decides, `luban-operator` cannot |
| `make deploy-sample-app`, `make deploy-samples`, `sync-browser-credentials.sh` | the app, the skill, the `acme-admin` credential set |
| The caller supplies the **new temporary password** in the chat message | a one-time value: never stored in the skill, never committed, never present in any tool output |

Because the store is in memory, a pod restart reverts it to the seed — which
is why every demo leg starts from `POST /internal/reset-demo` and why the
Deployment pins `replicas: 1`.

## How it works

Nine steps, **one** of them write tier:

1. `web.navigate` to `http://acme-admin:8080/admin/` with
   `skill_id: samples/password-reset-resetacmepassword` — binds the flow, so
   the origin guard, the step budget and the flow's single approval all attach
   here.
2. `web.snapshot` to pick up the login form's element **refs**.
3. Two `web.fill_credential` calls from set `acme-admin` (username, then
   password) — read tier, and the value never enters the prompt or a result.
4. Let the login **auto-submit** and settle with `web.wait_for` on
   `#user-table`. Do *not* click "Sign in".
5. Locate the target in the table and note their current **Revision**.
6. `web.navigate` to
   `/admin/users/reset/?user=<target>&newpw=<new-password>` — read tier,
   because navigating is not interacting. The page pre-fills client-side and
   deliberately does **not** submit. `newpw` is masked to `***` in the result
   and in the evidence.
7. `web.click` on `#confirm-reset` — the flow's **single write-tier
   interaction**, and therefore where the one card parks.
8. `web.extract` on `#reset-status`, expecting
   `Password for <username> has been reset successfully.` A `web.snapshot`
   will *not* show it: the status line is a plain `<p role="status">` and a
   snapshot enumerates interactive elements only.
9. One `http.get` with `credential_set: "acme-admin"` against
   `/api/users/<target>` for the bumped `revision` and `password_changed_at`,
   plus a `web.screenshot` as visual evidence.

## Key design decisions

### Why the gate is on "Confirm reset" and not on sign-in

The one-gate-per-flow invariant (SPEC-049 R-4/D-3, ADR-0007) requires exactly
one write-tier interaction per mutating flow, and it should land on the action
the operator means to approve. Resetting a password is the mutation; signing
in is not. An earlier revision of the shipped sample gated the sign-in click
and auto-submitted the reset, which asked an approver to authorise a login and
then changed a password they had never seen mentioned. SPEC-051 moved the gate
onto the mutation, and this app preserves that asymmetry **in code**: the login
form auto-submits, the reset form does not. `demo.sh` asserts the served page
never calls `.submit()`.

### Why the card is `flow` and not `action`

A browser flow binds an origin, a step budget and an approval that covers its
subsequent write-tier interactions. So the one approval is enough for the rest
of the flow, and the demo asserts the resumed turn parks **zero** further
cards. Rung 3 makes one call and needs one decision, so it parks an `action`
card.

### Why the new password travels in a URL at all

Because legacy admin panels that accept pre-filled batch URLs are real, and a
tutorial that only shows the safe shape teaches nothing about the unsafe one.
The value is a one-time temporary password, not a long-lived service
credential, so it does not belong in a credential set. It is masked at every
seam: by the gateway in the results it returns, and by the kernel in the
tool-call arguments it streams and persists — which no gateway-side redactor
ever sees. The app additionally keeps the pre-fill client-side, so the value
never appears in served HTML and a `web.snapshot` cannot leak it.

### Why not reset through `http.post` instead

Because `http.post` refuses a URL carrying a secret-bearing query parameter
(`HTTP_URL_SECRET_NOT_ALLOWED`, asserted in rung 3's demo) and publishes no
`headers` parameter, so there is no way to hand it a one-time password safely.
That refusal is the correct design and this skill works with it: the browser
surface is the right tool for a form-driven console flow, and the HTTP surface
is the right tool for verifying the result. Using both in one skill is the
point.

## Running the demo

```sh
make deploy-samples SAMPLE=acme-admin/password-reset

# Deterministic legs only (no model, no approval):
sh samples/acme-admin/password-reset/demo/demo.sh

# Including the chat leg: one flow card headed by the authored flow_intent, a
# tier-2 approval, no plaintext in any confirmation frame, and the store
# checked afterwards:
RUN_CHAT_LEG=true sh samples/acme-admin/password-reset/demo/demo.sh
```

Overrides: `TARGET_USER` (default `alice`), `NEW_PASSWORD` (default
`TempPass-2026!` — a throwaway value for a store that discards it).

## Where this rung sits

| rung | sample | surface | tier | cards |
|---|---|---|---|---|
| 1 | [`../health-check/`](../health-check/) | `http.get` | read | 0 |
| 2 | [`../user-status/`](../user-status/) | bound browser flow | read | 0 |
| 3 | [`../lock-unlock-user/`](../lock-unlock-user/) | `http.post` | write | 1 (`action`) |
| **4** | **`password-reset/` (this one)** | **bound browser flow** | **write** | **1 (`flow`)** |
| 5 | [`../composition/`](../composition/) | runbook (4 then 3) | write (derived) | 2 (`flow` + `action`) |

Rungs 2 and 4 drive the same browser against the same console and differ only
in effect, which is the pair that breaks "browser means dangerous".

## Adapting for your own target

1. Copy this directory to `samples/<your-category>/<your-sample>/`, and choose
   a **filename that yields an unused id** — check against every existing
   `samples/*/skill/*.md`, since the category directory is not part of the id.
2. Declare `web_target`, `risk_class: write` and a `flow_intent` for the gated
   step. `flow_intent` is the card's lead decision line, above the demoted DOM
   detail; it is display-only, never a security input, and must carry no
   credential.
3. Give your form exactly **one** write-tier interaction, and put it on the
   mutation. Anything your page can auto-submit, let it auto-submit.
4. Keep one-time secrets out of served HTML so a snapshot cannot leak them, and
   out of every durable record by relying on the shared URL redactor rather
   than on a bespoke mask.
5. Make the success page report **stored state**, not the query string it was
   handed — and assert the difference the way `demo.sh` does, by asking the
   confirmation page about a *different* user than the one just reset.
6. Verify from a second surface at the end. A page that says "success" is a
   claim; an API read of the row is a fact.
