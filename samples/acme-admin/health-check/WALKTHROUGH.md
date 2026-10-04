# Live Walkthrough: ACME Admin Service Health Check

Rung 1 of the five. You will ask the agent, in **Chat**, to check the health of
the `acme-admin` service — and the point of the walkthrough is what does *not*
happen: no confirmation card appears, at any point, for any reason.

Everything below is also exercised unattended by
[`demo/demo.sh`](demo/demo.sh); the mapping is tabulated at the end.

**Portal surface: Chat.** This is an operational session, not skill
development, so it lives in **Chat** and never in **Studio** (SPEC-056). If you
want to see the authoring workspace, that is
[`samples/acme-admin/skill-graduation/WALKTHROUGH.md`](../skill-graduation/WALKTHROUGH.md);
nothing here uses it.

## Prerequisites

| Component | What must be true | Check it with |
|---|---|---|
| Cluster | dev-k8s deployed | `kubectl -n dev-luban-aiops get pods` |
| HTTP surface | `GATEWAY_HTTP_ENABLED=true` | `kubectl -n dev-luban-aiops get cm platform-runtime-config -o jsonpath='{.data.GATEWAY_HTTP_ENABLED}'` |
| HTTP allowlist | lists `http://acme-admin:8080` | same ConfigMap, key `GATEWAY_HTTP_ALLOW_ORIGINS` |
| `acme-admin` app | deployed and ready | `make deploy-sample-app` (it asserts before it exits 0) |
| Skill installed | `/skills/samples/health-check-CheckServiceHealth.md` | `make deploy-samples`, then `kubectl -n dev-luban-aiops exec deployment/skills-hub -- ls -1 /skills/samples` |
| `http.get` registered | `risk_level: read` in discovery | the demo's `require_tools_registered` leg |
| Portal | reachable at the canonical origin | open `https://aiops.luban.metasync.cc` |

The `browser-dev` runtime profile is what turns the HTTP surface on in dev; the
base overlay keeps `GATEWAY_HTTP_ENABLED=false`. `GATEWAY_MUTATING_TOOLS_ENABLED`
is **not** needed for this rung — no write-tier tool is involved, which is
exactly the claim being demonstrated.

## Step 1: Look at the app yourself first

```sh
kubectl -n dev-luban-aiops port-forward svc/acme-admin 8080:8080 &
curl -s localhost:8080/healthz
```

You should see eight keys:

```json
{"status":"ok","service":"acme-admin","version":"...","hostname":"acme-admin-...",
 "uptime_seconds":...,"started_at":"...","users_seeded":4,"store_revision":0}
```

`store_revision` is `0` on a freshly started pod and on a pod that has just
been reseeded; it increments once per mutation. Keep it in mind — rungs 3 and 4
are only legible because this number moves.

> **Why a port-forward works at all:** the sample's ingress NetworkPolicy
> admits only pods labelled `app: tool-gateway`. `kubectl port-forward` is
> tunnelled by the kubelet straight into the pod's network namespace, so it
> never traverses pod ingress and needs no second rule. That is deliberate: a
> human reader gets in, and nothing else in the cluster does.

The agent's own calls do **not** use this port-forward. They go from the
tool-gateway pod to `http://acme-admin:8080`, in-cluster, through the rule the
policy admits.

## Step 2: Sign in to the portal

Open **https://aiops.luban.metasync.cc** — the canonical dev-k8s entry point —
and sign in as **`luban-operator`**.

Do not reach the portal through a `svc/web-ui` port-forward instead. The broker
builds every authorization URL from `OIDC_REDIRECT_URI`, which is the canonical
origin above, so a localhost tab never receives the code and stays signed out
however correctly the port-forward serves the shell. See the `Runtime Wiring`
section of `shared/platform-ops/gitops/dev-k8s/README.md`.

**No second identity is needed for this rung.** There is nothing to approve.
That is the observation, not an omission — rungs 3 and 4 both need
`luban-approver` in a private window, and the contrast is the lesson.

## Step 3: Open a Chat session

Click **Chat** in the sidebar and start a new session.

## Step 4: Ask for the health check

Paste this into the composer as one block. **Enter sends**, so typing it line by
line submits the first line on its own and leaves the rest in the box
(Shift+Enter makes a newline):

```
Check the health of the acme-admin service and tell me what you found.
Use skill samples/health-check-checkservicehealth. No credentials are needed
for the health endpoint.
```

Naming the skill is what `demo.sh`'s chat leg sends and it is the reliable
form: it closes the ambiguity that makes a model stall or wander. You can
instead send the bare request ("is acme-admin healthy?") and watch the agent
find the skill itself through `skills.search` → `skills.get`, but if it asks
whether it may proceed rather than calling the tool, re-send the message above.
The skill's title (`Check ACME Admin Service Health`) works in place of its id.
See [Asking for a runbook without naming it](../../../docs/guides/skills-guide.md#asking-for-a-runbook-without-naming-it)
for the general principle.

## Step 5: What you should see

The turn should contain:

1. A `skills.search` and/or `skills.get` if you did not name the skill.
2. **Two `http.get` tool calls** in the evidence chain:
   - `http://acme-admin:8080/healthz`
   - `http://acme-admin:8080/api/hello?name=luban`
3. Each result carrying the fixed projection — `url`, `status`, `elapsed_ms`,
   `headers`, `content_type`, `content_length`, `truncated`, `body`. Expand one
   and check `headers`: it carries only safe response headers, and **never**
   `set-cookie` or `authorization`.
4. A prose summary reporting `status`, `version`, `hostname`, `uptime_seconds`,
   `users_seeded` (`4`) and `store_revision`.
5. **No confirmation card. No Approve/Deny control. Nothing parked.** The turn
   runs start to finish without a decision from anyone.

If you want to be sure the absence is real rather than merely unnoticed, check
the session afterwards:

```sh
kubectl -n dev-luban-aiops exec deployment/tool-gateway -c tool-gateway -- \
  curl -s -H "Authorization: Bearer <token>" http://localhost:8000/api/v2/tools | head -c 400
```

and confirm `http.get` is listed with `"risk_level": "read"`. The tier is half
of why nothing parks. The other half is agent-platform's auto-allow list. Since
v0.39.1 `http.get` is no longer in the built-in `DEFAULT_AUTO_ALLOWED_TOOLS`
(outbound-egress HITL bypass is opt-in); the dev cluster opts it back in with
`AGENT_GATEWAY_TOOL_AUTO_ALLOW_EXTRA=http.get`, so it still parks no card here,
while `http.post` is write-tier and never auto-allows. A read-tier tool *off*
the resolved list still gets an explicit ASK and parks an `action` card. The
model has no vote in either half.

## Honest caveats

- **`uptime_seconds` and `started_at` change between runs.** They count from
  process start and are deliberately *not* reset by the reseed endpoint, so
  two runs of this walkthrough report different values. That is correct, not
  flaky.
- **`store_revision` is `0` only if nothing has mutated since the last reseed
  or pod start.** If you ran rung 3 or 4 first, it will be higher. Reseed with
  `curl -s -X POST -H 'X-Luban-Demo-Reset: 1' localhost:8080/internal/reset-demo`
  through the port-forward. Note that the agent **cannot** make this call:
  `http.post` publishes no `headers` parameter, so the header gate is
  structural rather than a convention.
- **A non-2xx upstream status is not a tool failure.** If the agent reports
  `/api/hello?name=…` answering `422`, that is the app refusing a name outside
  `^[A-Za-z0-9 _.-]{1,64}$`, arriving as a *successful tool result* carrying
  that status. A skill that treated it as "the tool broke" would report a
  healthy app as down.
- **`AGENT_GATEWAY_TOOL_AUTO_ALLOW` replaces the built-in list; it does not
  extend it.** Setting it to admit one extra read tool of your own silently
  withdraws `http.get` and the browser reads from auto-approval, and step 5
  starts parking a card. Name every tool you still want auto-approved, or
  leave the variable unset.
- **This walkthrough proves the platform's tier logic, not your production
  health endpoint.** The app is a tutorial target with an in-memory store.

## What just happened

```
Operator                Agent                    tool-gateway            acme-admin
   │                      │                           │                      │
   │ "check the health"   │                           │                      │
   │─────────────────────>│                           │                      │
   │                      │ skills.get (read)         │                      │
   │                      │──────────────────────────>│                      │
   │                      │ http.get /healthz (read)  │                      │
   │                      │──────────────────────────>│─────────────────────>│
   │                      │        projection: 8 keys │<─────────────────────│
   │                      │<──────────────────────────│                      │
   │                      │ http.get /api/hello (read)│                      │
   │                      │──────────────────────────>│─────────────────────>│
   │                      │<──────────────────────────│<─────────────────────│
   │  "status ok, rev 0"  │                           │                      │
   │<─────────────────────│                           │                      │
   │                      │                           │                      │
   │      (no card, no approval, nothing parked — every call was read tier)   │
```

## Step ↔ demo mapping

Every step above is exercised by `demo.sh`; the walkthrough never asks you to
click something the demo does not also assert (SPEC-059 R-8).

| Walkthrough step | Demo leg |
|---|---|
| Step 1 — the eight `/healthz` keys | leg 2, `/healthz` in-cluster: eight keys and the seeded state |
| Step 1 — the port-forward / in-cluster reachability | `deploy.sh`'s in-cluster assertions, from the tool-gateway pod |
| Step 4 — the agent picks `http.get` | chat leg: `require_zero_cards` plus a grep for `"tool_name":"http.get"` |
| Step 5.2 — two calls, fixed projection | leg 3: projection keys, `truncated: false`, `content_type` |
| Step 5.3 — no `set-cookie`/`authorization` header | leg 3: the forbidden-header assertion |
| Step 5.3 — `/api/hello` echoes | leg 3: `message == "hello, luban!"` and the URL survives verbatim |
| Step 5.5 — nothing parked | chat leg: `require_zero_cards` on the stream **and** `require_card_count … 0` on the durable session |
| Caveat — 422 is a result, not an error | leg 3: the bounded-name refusal arrives with `status: 422` at tool-layer 200 |
| The skill declares no `risk_class` | leg 4: `require_no_risk_class` |

```sh
# deterministic legs only:
sh samples/acme-admin/health-check/demo/demo.sh
# including the chat leg that asserts zero cards:
RUN_CHAT_LEG=true sh samples/acme-admin/health-check/demo/demo.sh
```

## Key observations

1. **Zero cards is a property of the tier, not of the prompt.** Nothing in the
   skill document, the message or the model's behaviour decides it. `http.get`
   is registered `read`, and read-tier calls are not gated.
2. **A read-only skill declares neither `risk_class` nor `web_target`.** Both
   are browser-flow vocabulary. The demo asserts the omission, because a
   read-only sample that quietly declared `risk_class: write` would still park
   nothing and would teach the wrong rule.
3. **The projection is fixed.** A skill can be written against the key set
   instead of against prose, and nothing outside it can leak.

## Next rung

[`../user-status/WALKTHROUGH.md`](../user-status/WALKTHROUGH.md) opens a
browser, signs into the same console, reads a rendered table — and still parks
zero cards. That is the rung which removes the "API calls are safe, browsers
are dangerous" explanation.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `TOOL_NOT_FOUND` for `http.get` | `GATEWAY_HTTP_ENABLED` is false. Deploy with the `browser-dev` runtime profile, then restart tool-gateway |
| `HTTP_ORIGIN_NOT_ALLOWED` | `GATEWAY_HTTP_ALLOW_ORIGINS` does not list `http://acme-admin:8080`. Check the rendered `platform-runtime-config` — the entry belongs in the runtime profile, never in `dev-k8s/base` |
| `HTTP_SCHEME_NOT_ALLOWED` / `HTTP_REDIRECT_NOT_ALLOWED` | the URL was not plain `http://`, or the app redirected. Use the exact origin above |
| The agent reports the service as down on a 422 | it treated an upstream status as a tool error. Re-send naming the skill; the skill's Interpretation section covers this |
| `connection refused` on the port-forward | the pod is not ready: `kubectl -n dev-luban-aiops get pods -l app=acme-admin` and `kubectl logs -n dev-luban-aiops deployment/acme-admin` |
| The app refuses to start, naming `ACME_ADMIN_PASSWORD` | run `shared/platform-ops/gitops/sync-browser-credentials.sh` — it writes both secret sinks from one generated value |
| The skill is not found | `make deploy-samples` (no `SAMPLE=` installs all six skill-bearing samples; `SAMPLE=<one>` *drops* the others) |
