# ACME Admin User Status Check (browser flow, zero cards)

Rung 2 of the five-rung `acme-admin` ladder (SPEC-059 R-7). A read-only skill
that opens a browser, signs into a console, reads a rendered table — and
still parks **zero** confirmation cards.

This is the rung the ladder exists to show. Rung 1 proved a card-free skill
over HTTP, which a reader can explain away: "API calls are safe, browsers are
dangerous." This one removes that explanation. It drives the same headless
browser the mutating samples drive, against the same console, and parks
nothing — because every step it takes is read tier. A card is a property of
*effect*, not of tooling.

## What this sample contains

| Path | Purpose |
|---|---|
| `skill/CheckUserStatus.md` | The skill document — six read-tier steps, annotated with why the declaration is enforced rather than advisory |
| `demo/demo.sh` | Standalone demo: surface + credential + tier assertions → the rendered table → the element-id contract → skill ingestion → optional chat leg |
| `WALKTHROUGH.md` | The same story driven by hand through the operator portal's **Chat** |

Skill id: **`samples/user-status-checkuserstatus`**.

## Prerequisites

| Requirement | Why this rung needs it |
|---|---|
| `make deploy` with the `browser-dev` runtime profile | sets `GATEWAY_BROWSER_ENABLED=true`, lists `http://acme-admin:8080` on `GATEWAY_BROWSER_ALLOW_ORIGINS`, and points `GATEWAY_BROWSER_CREDENTIAL_SETS` at the mounted sets file |
| Browser sidecar ready | 2/2 containers in the tool-gateway pod (`kubectl logs -n dev-luban-aiops deploy/tool-gateway -c browser`) |
| `make deploy-sample-app` | builds and deploys the app whose console the skill reads |
| `make deploy-samples` | packs the skill document into the skills-hub `samples` source |
| `sync-browser-credentials.sh` already run | the `acme-admin` credential set must exist, and must carry the *same* password the app was started with |
| identity-service port-forward on `18081` | the demo issues its own dev token to call the gateway directly |

The credential arrangement is the one thing that can silently break this rung:
`sync-browser-credentials.sh` generates one value and writes it to two sinks —
the gateway's credential-sets file and the app's `ACME_ADMIN_PASSWORD` secret.
If you rotate one without the other, the sign-in is rejected and the app
redirects back to `/admin/`, which the skill's Interpretation section names.
Re-run the sync script; it restarts both deployments.

## How it works

Six steps, all read tier:

1. `web.navigate` to `http://acme-admin:8080/admin/` with
   `skill_id: samples/user-status-checkuserstatus` — this **binds** the flow,
   attaching the origin guard and the step budget.
2. `web.snapshot` to enumerate the login form and pick up its element **refs**.
3. Two `web.fill_credential` calls from credential set `acme-admin` — field
   `username`, then field `password`. Filling submits nothing, so both stay
   read tier and the value never enters the prompt, the arguments, or a
   result.
4. `web.wait_for` on `#user-table` while the console's login form
   **auto-submits** (~100 ms after both fields are filled). Clicking "Sign in"
   would be write tier and would park the suite's only unwanted card.
5. `web.extract` on `#user-table` for the whole list (returns `headers` plus
   `rows`), or on `#user-row-<username>` for one user (returns that row's cell
   texts).
6. Report **Status**, **Last modified** and **Revision** — quoting the cells
   rather than inferring from them.

## Key design decisions

### Why `web_target` with no `risk_class`

`web_target` declares where a bound flow starts; `risk_class` declares an
effect. Omitting the second is *the* read declaration: the contract treats a
`web_target` with no `risk_class` as `read`, and the gateway then binds a
read-class flow that **refuses** write-tier interactions with
`BROWSER_FLOW_DENIED`. So the skill cannot mutate the console even if the
model decides to try — the declaration is enforced, not advisory. Rung 4
declares both keys and parks a card; the pair is what makes the difference
legible.

### Why the element ids are asserted from outside the app

`web.extract` takes a CSS selector and `web.snapshot` hands back refs into the
same elements, so renaming one id in a template silently breaks a shipped
skill. The app's own test suite walks every page for its id set; `demo.sh`
additionally asserts the contract **over HTTP against the deployed image** —
`user-table`, the four `user-row-*` ids, `store-revision`, `no-resets`, and
the reset page's `confirm-reset` / `reset-status`. A template edit that breaks
a skill fails the demo rather than the next chat session.

### Why the one-time value must not appear in served HTML

The demo loads `/admin/users/reset/?user=alice&newpw=TempPass-2026!` and
asserts the served page does **not** contain `TempPass-2026!`. The pre-fill is
client-side, so a `web.snapshot` of that page cannot leak a value the gateway
would otherwise have to mask. Rung 4 depends on this property; rung 2 is where
it is checked.

### Why read rendered state rather than the JSON API

Because "what would an operator see?" is a different question from "what does
the service report?", and an API check cannot tell you the console is broken
for humans while the JSON is fine. Rung 1 already answers the second
question; answering it twice would teach nothing.

## Running the demo

```sh
make deploy-samples SAMPLE=acme-admin/user-status

# Deterministic legs only (no model interaction):
sh samples/acme-admin/user-status/demo/demo.sh

# Including the chat leg, which asserts zero cards and at least one web.extract:
RUN_CHAT_LEG=true sh samples/acme-admin/user-status/demo/demo.sh
```

Override the reported user with `TARGET_USER=bob` (default `alice`). The chat
leg additionally needs a platform-gateway port-forward on `18083` and a
running agent.

## Where this rung sits

| rung | sample | surface | tier | cards |
|---|---|---|---|---|
| 1 | [`../health-check/`](../health-check/) | `http.get` | read | 0 |
| **2** | **`user-status/` (this one)** | **bound browser flow** | **read** | **0** |
| 3 | [`../lock-unlock-user/`](../lock-unlock-user/) | `http.post` | write | 1 (`action`) |
| 4 | [`../password-reset/`](../password-reset/) | bound browser flow | write | 1 (`flow`) |
| 5 | [`../composition/`](../composition/) | runbook (4 then 3) | write (derived) | 2 (`flow` + `action`) |

This is also the suite's **verification** skill: `LockUnlockUser` mutates over
HTTP and reports the API's revision, and re-running this skill reads the
console's Status cell for the same user. [`../demo-suite.sh`](../demo-suite.sh)
asserts exactly that agreement — two surfaces, one store — which is the
sentence that turns four demos into one runbook and the shape SPEC-057
composes.

## Adapting for your own target

1. Copy this directory to `samples/<your-category>/<your-sample>/`.
2. Set `web_target` to your console's entry URL and add its origin to
   `GATEWAY_BROWSER_ALLOW_ORIGINS` in your runtime profile — never in
   `dev-k8s/base` (SPEC-050 R-11 applies to allowlist entries exactly as it
   does to Deployments).
3. Give your pages stable ids for the elements you extract, and assert them
   from outside the app the way `demo.sh` does. A selector that only works
   against your development build is a broken skill in production.
4. Add your credential set to `sync-browser-credentials.sh` so one generated
   value reaches both the gateway's sets file and your app.
5. If your login form does not auto-submit, either make it do so or accept
   that clicking through it is a write-tier step — which means your read-only
   skill is not read-only, and the honest fix is to declare `risk_class` and
   move the gate onto the mutation you actually mean to approve.
6. Install with `make deploy-samples SAMPLE=<your-category>/<your-sample>`.
