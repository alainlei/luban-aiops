# ACME Admin Service Health Check (`http.get`, zero cards)

Rung 1 of the five-rung `acme-admin` ladder (SPEC-059 R-7). A read-only skill
over the HTTP service-check surface that parks **zero** confirmation cards —
the repository's first genuinely card-free sample.

The point of this rung is negative, and that is why it comes first: every
sample shipped before it parks at least one card, so a reader who has only
seen those cannot tell whether "no card" is a property the platform can
express or an accident of the demos they happened to run. This one shows it
being expressed, and shows the two facts that make the zero count true rather
than lucky.

## What this sample contains

| Path | Purpose |
|---|---|
| `skill/CheckServiceHealth.md` | The skill document — two `http.get` calls, annotated with why a read-only skill declares neither `risk_class` nor `web_target` |
| `demo/demo.sh` | Standalone demo: surface enablement → app health → the `http.get` projection → skill ingestion → optional chat leg |
| `WALKTHROUGH.md` | The same story driven by hand through the operator portal's **Chat** |

Skill id: **`samples/health-check-checkservicehealth`** (derived by
[`deploy-samples.sh`](../../deploy-samples.sh) from the sample directory's leaf
name plus the file name — the category directory is *not* part of it).

## Prerequisites

| Requirement | Why this rung needs it |
|---|---|
| `make deploy` with the `browser-dev` runtime profile | sets `GATEWAY_HTTP_ENABLED=true` and lists `http://acme-admin:8080` on `GATEWAY_HTTP_ALLOW_ORIGINS` |
| `make deploy-sample-app` | builds and deploys the app the skill reads |
| `make deploy-samples` | packs the skill document into the skills-hub `samples` source |
| identity-service port-forward on `18081` | the demo issues its own dev token to call the gateway directly |
| `GATEWAY_MUTATING_TOOLS_ENABLED` | **not** needed — this rung registers no write-tier tool |

The `browser-dev` profile is what enables the HTTP surface in dev; the base
overlay keeps `GATEWAY_HTTP_ENABLED=false`. See
[`../README.md`](../README.md) for the app and
[`../../../docs/guides/tool-configuration.md`](../../../docs/guides/tool-configuration.md)
for the full activation checklist — HTTP tools need the flag, the allowlist
*and* a `tools:invoke` grant, and any one of the three missing produces a
different error.

## How it works

Two calls, both read tier:

1. `http.get` on `http://acme-admin:8080/healthz` — no credential, because
   the health endpoint is unauthenticated by design. Reports the eight keys
   the app serves: `status`, `service`, `version`, `hostname`,
   `uptime_seconds`, `started_at`, `users_seeded`, `store_revision`.
2. `http.get` on `http://acme-admin:8080/api/hello?name=luban` — a bounded
   echo that proves the query string survives the trip intact, and that a
   name outside `^[A-Za-z0-9 _.-]{1,64}$` comes back as a *successful tool
   result carrying 422* rather than as a tool error.

Neither call parks a card under the default kernel configuration. `http.get`
is registered at `risk_level: read` and belongs to the kernel's default
`AGENT_GATEWAY_TOOL_AUTO_ALLOW` list. Removing it from a custom auto-allow
list can make a read park a card; the tier alone is not the auto-allow grant.
Gateway authorization still requires `tools:invoke`.

## Key design decisions

### Why no `risk_class` and no `web_target`

`web_target` declares where a bound browser flow starts, while `risk_class`
declares an *effect* for browser and non-browser skills alike. A skill that
opens no browser and changes nothing declares neither. The omission is load-bearing
rather than cosmetic — `demo.sh` asserts it
(`require_no_risk_class`), because a read-only sample that quietly declared
`risk_class: write` would still park nothing and would teach the wrong rule
about what causes a card.

### Why the projection is asserted key by key

`http.get` returns a **fixed** key set — `url`, `status`, `elapsed_ms`,
`headers`, `content_type`, `content_length`, `truncated`, `body` — and the
demo asserts every one of them is present plus that `headers` carries neither
`set-cookie` nor `authorization`. A skill can therefore be written against the
shape instead of against prose, and nothing outside the shape can leak. That
is SPEC-058 R-1, and this rung is where a reader can see it holding.

### Why an upstream 422 is a pass

The `/api/hello` name bound is asserted *because* it fails. An upstream 4xx is
a successful tool result carrying that status, so a skill that treated any
non-2xx as "the tool broke" would report a healthy app as down. Rung 1 is
where that distinction is cheapest to demonstrate.

## Running the demo

```sh
# Install this sample's skill (drops any other sample's — see the note below):
make deploy-samples SAMPLE=acme-admin/health-check

# Deterministic legs only (no model interaction):
sh samples/acme-admin/health-check/demo/demo.sh

# Including the chat leg, which asserts the turn parks zero cards:
RUN_CHAT_LEG=true sh samples/acme-admin/health-check/demo/demo.sh
```

The chat leg additionally needs a platform-gateway port-forward on `18083`
and a running agent. `make deploy-samples` with no `SAMPLE=` installs all
six skill documents (the five-rung ladder plus `adhoc-password-reset`), which is
what the suite wants: `SAMPLE=<one>` is declarative and *drops* the others.

## Where this rung sits

| rung | sample | surface | tier | cards |
|---|---|---|---|---|
| **1** | **`health-check/` (this one)** | **`http.get`** | **read** | **0** |
| 2 | [`../user-status/`](../user-status/) | bound browser flow | read | 0 |
| 3 | [`../lock-unlock-user/`](../lock-unlock-user/) | `http.post` | write | 1 (`action`) |
| 4 | [`../password-reset/`](../password-reset/) | bound browser flow | write | 1 (`flow`) |
| 5 | [`../composition/`](../composition/) | runbook (4 then 3) | write (derived) | 2 (`flow` + `action`) |

Rungs 1 and 3 both talk to the same JSON API and differ only in effect; rungs
2 and 4 both drive a browser and differ the same way; rung 5 composes rungs 3
and 4 and shows their gates do not merge. [`../demo-suite.sh`](../demo-suite.sh)
runs all five in order and then asserts the claim none of them makes alone.

## Adapting for your own target

1. Copy this directory to `samples/<your-category>/<your-sample>/`.
2. Point the two `http.get` URLs at your service and replace the asserted
   payload keys with the ones your health endpoint really serves. Keep the
   projection assertions — they are about the gateway, not your app, and they
   are what makes "zero cards" a checked fact.
3. Add your origin to `GATEWAY_HTTP_ALLOW_ORIGINS` in the runtime profile you
   deploy with. Never in `dev-k8s/base`: SPEC-050 R-11 keeps sample names out
   of the base overlay, allowlist entries included.
4. Leave `risk_class` and `web_target` out of the frontmatter, and keep
   `require_no_risk_class` in your demo.
5. Install with `make deploy-samples SAMPLE=<your-category>/<your-sample>` —
   no base-overlay edits; the platform exposes one generic `samples` skill
   source that packs whatever `skill/*.md` your sample ships.

If your health endpoint needs a credential, use `credential_set: "<name>"`
rather than reaching for a header: neither `http.get` nor `http.post`
publishes a `headers` parameter, so a secret can only ever be a reference the
gateway resolves server-side.
