# Skills and Guidance Operations Guide

Operator-facing guide for managing the skill content that powers grounded
guidance (SPEC-014): how to add, revise, and remove skills and skill sources,
how the content reaches the agent, and how to verify and troubleshoot it.

For deployment-level configuration (secrets, environment variables, the
retrieval chain), see the
[Configuration Reference](configuration-reference.md); for the agent-side
tools, see the [Tool and Connector Guide](tool-configuration.md).

## How skills reach the agent

```
team skill sources ──sync──► skills-hub ──store──► postgres (skills DB)
(local dirs / git repos)      (validate)                │
                                                        ▼
        agent ◄── skills.search / .get / .list ◄── tool-gateway
```

1. **Sources** are directories of Markdown skill documents — either `local`
   paths mounted into the skills-hub pod or `git` repositories the service
   clones. Each source has an operator-assigned `source_id`.
2. **skills-hub** syncs every source every `SKILLS_SYNC_INTERVAL_SECONDS`
   (default 300s), validates every document, and atomically replaces the
   source's slice in the store. A failed sync keeps the previous slice —
   bad content never poisons a source that used to work.
3. **The agent** reaches skills only through the tool-gateway's read-only
   tools (`skills.search`, `skills.get`, `skills.list`), inheriting policy,
   audit, and evidence-panel behavior. There is no write path from the agent.

Skill identity: `skill_id = <source_id>/<slug>`, where the slug is derived
from the file path (not frontmatter). See
[skill-format.md](../../shared/shared-contracts/skill-format.md) for the full
contract.

## Asking for a runbook without naming it

You do not have to know a skill's id — or name it at all — to use it. The agent
reaches runbooks the way it reaches every skill: it calls `skills.search` with
the words you typed, reads the best match with `skills.get`, and follows it. Its
default system prompt tells it to discover guidance by intent and *not* to demand
a `skill_id` you were never given.

So in regular use, describe the outcome and supply only what a skill cannot infer
for itself:

```
dave's locked out of acme-admin — reset his password to 'TempPass-2026!' and
unlock him.
```

The agent finds `samples/composition-recoveracmeaccount` on its own. Everything
the runbook already grounds — the credential set, the target URL, the surface
(browser vs. API), the order of steps — belongs in the skill, not in your
message. The only inputs it cannot infer are the ones the skill's preconditions
name as the caller's to supply (for a recovery: the **target user**, the **new
one-time password**, and the **intent**). Omit one and the agent asks rather than
guesses.

**When to name a skill anyway.** Naming the `skill_id` (or its title) removes the
one non-deterministic step in the exchange — whether the model picks the runbook
you meant. The `samples/` walkthroughs and their `demo.sh` chat legs name it for
exactly that reason: an assertion about an exact card count or a specific tool
sequence has to reproduce. That is a *testing* need, not a usage requirement. Day
to day, ask conversationally and let `skills.search` do the matching.

## The skill format in one minute

A skill is a Markdown file with YAML frontmatter:

```markdown
---
title: KubePodNotReady
description: Pod stuck in a not-ready state — triage and remediation steps.
tags: [kubernetes, pod, alerting, KubePodNotReady]
version: "1.0"
source_url: https://github.com/prometheus-operator/runbooks
---

Markdown body ...
```

Rules that matter for day-2 operations:

- `title` (≤ 200 chars) and `description` (≤ 500 chars) are **required**;
  `tags` (≤ 10), `version`, `source_url` are optional. Unknown keys are
  rejected.
- **Web-check skills (SPEC-049):** the optional `web_target` key declares
  the flow's target URL (absolute http/https, ≤ 2048 chars) and
  `risk_class` (`read` or `write`) declares the *effect* of the skill's
  steps. When the agent opens `web_target` with
  `web.navigate(skill_id=...)`, the gateway binds the flow and enforces
  its risk class (write-class flows get exactly one HITL gate before any
  interaction).
- **`risk_class` does not require `web_target`** (SPEC-055 R-3 decoupled
  them): a non-browser mutating skill — one whose steps are `k8s.*` or
  `http.post` — declares `risk_class: write` on its own. `flow_intent`
  still requires `web_target`, because it is a *flow* card's headline.
  Omitting `risk_class` means `read`; see
  [Read-only skills](#read-only-skills-what-declaring-nothing-buys-you).
- **Declared step intent (SPEC-053):** the optional `flow_intent` key
  (≤ 200 chars, requires `web_target`) authors in plain language what the
  flow's single gated mutating step achieves. The confirmation card a
  write-class flow parks leads with this line above the parsed
  DOM/technical detail, so the approver reads the decision in the skill
  author's words. It is display-only — never a security input (the
  deviation guard and signed execution are unchanged) — and skills that
  omit it render exactly as before.
- Body ≤ 64 KiB. Split long guides.
- Moving or renaming a file changes its `skill_id` — intentionally, so stale
  citations become visible. Duplicate slugs within one source are rejected;
  across sources they are fine (ids are namespaced).
- `README.md` and `NOTICE` files are skipped by ingestion.
- No secrets in skill bodies. `web_target` may name the check target's
  host, but credentials always come from the gateway's credential sets
  (`web.fill_credential`) — never from a skill.
- Adapted open-source content must keep `source_url` pointing upstream and a
  `NOTICE` file in the source root (project, URL, license).

## Read-only skills: what declaring nothing buys you

The gate follows the **effect** of a skill, not the tooling it uses. A skill
that changes nothing parks nothing, whichever surface it reads through — and
the way to declare that is to declare nothing at all: no `risk_class`, and no
`web_target` unless the skill really binds a browser flow.

The repository ships the two shapes side by side under
[`samples/acme-admin`](../../samples/acme-admin/), which is the only place you
can see them compared against one target.

**Shape 1 — read-only over HTTP, no flow declaration at all.**
[`health-check/skill/CheckServiceHealth.md`](../../samples/acme-admin/health-check/skill/CheckServiceHealth.md)
performs two `http.get` calls:

```yaml
---
title: Check ACME Admin Service Health
description: >
  Verify that the acme-admin user-administration console is up and
  answering, over its JSON API. … Read-only: it changes nothing and parks
  no confirmation card.
tags: [acme-admin, health, healthz, http, service-check, read-only, api, uptime, monitoring]
version: "1.0"
---
```

There is no `web_target` and no `risk_class`, because there is no flow to bind
and no effect to gate. `http.get` is registered at `risk_level: read`, so the
kernel's HITL bridge never asks anyone for a decision. This is the
repository's first genuinely card-free sample.

**Shape 2 — read-only through a browser, with a flow declaration.**
[`user-status/skill/CheckUserStatus.md`](../../samples/acme-admin/user-status/skill/CheckUserStatus.md)
drives the same target's rendered console and adds exactly one key:

```yaml
web_target: http://acme-admin:8080/admin/
```

Still no `risk_class`, so the bound flow is read class — and it still parks
nothing, even though it navigates, snapshots, fills credentials and extracts.
What the declaration buys is **enforcement rather than intent**: inside a
read-class flow the gateway refuses any write-tier interaction outright with
`BROWSER_FLOW_DENIED`. Ask the agent to lock a user in that same session and
the click is refused — not parked, not approved, refused. The skill document
did not stop the model from trying; the binding did.

Read together with the two mutating rungs
([`lock-unlock-user`](../../samples/acme-admin/lock-unlock-user/), one `action`
card over `http.post`; [`password-reset`](../../samples/acme-admin/password-reset/),
one `flow` card through the browser), the four make the point a single sample
cannot: rungs 1 and 3 both talk to the JSON API and differ, and rungs 2 and 4
both drive a browser and differ.

**Two authoring mistakes this section exists to prevent:**

- **Declaring `risk_class: read` to "be explicit" on a non-browser skill.** It
  is harmless but it buys nothing, and it reads as though a flow is bound when
  none is. Declare `web_target` only when the skill really navigates.
- **Omitting `web_target` from a browser skill.** The steps still run — the
  agent can navigate anywhere its allowlist permits — but nothing binds, so
  nothing enforces the read class and the origin guard and step budget attach
  to no declaration at all. A read-only browser skill without `web_target` is
  a read-only browser skill on trust.

Verify either shape against a live cluster with its `WALKTHROUGH.md`, or
unattended with its `demo/demo.sh` (the chat legs are opt-in behind
`RUN_CHAT_LEG=true`).

## Composition runbooks: ordering skills that already exist (SPEC-057)

A third skill class, `kind: composition`, names an **ordered list of existing
single-target skills** (`sub_skills`) so one document can express a multi-step
runbook — reset the password, *then* unlock the account — without widening any
skill's scope. The full contract lives in
[`skill-format.md`](../../shared/shared-contracts/skill-format.md#composition-skills-v3);
the day-2 facts an operator needs are these:

- **A composition carries no authority of its own.** It never mints a token,
  unlocks a flow, or auto-approves a gate. Each sub-skill keeps its **own** HITL
  gate, so a run parks once per mutating sub-skill: a browser write flow parks a
  `flow` card, an infra write parks an `action` card. Approving the first never
  approves the second — when the session moves to the next sub-skill the prior
  flow authority no longer matches and the next write re-parks.
- **Its `risk_class` badge is derived, not declared.** The Skills list shows
  `write` when any sub-skill writes, else `read`. You never author a `risk_class`
  on a composition (ingestion rejects it), and nothing in the gate path reads
  the derived value — it is display only.
- **It is not a transaction — report-and-stop.** On a sub-skill failure the
  agent reports *which* sub-skill failed and stops; there is no rollback or
  compensation, and targets already touched stay touched. Author that
  instruction into the runbook `body` (the shipped sample states it verbatim) so
  it reaches the model as grounded guidance.
- **Re-entry is a 30-day window.** There is no runbook-progress record. The
  completed prefix of a stopped run is reconstructable from the session's signed
  execution receipts, which are swept at **30 days** — inside that window an
  operator can see which sub-skills already ran and restart from the next one;
  outside it, restart the runbook from the beginning. Each sub-skill re-gates on
  re-entry, so a restart never auto-signs a write nobody re-approved.

A composition and its sub-skills must resolve within the served catalog: a
sub-skill that is missing, or is itself a composition (no nesting in Phase 1),
is **rejected** at sync — never silently served, never degraded to a plain
knowledge doc. Cross-source compositions are eventually consistent: a sub-skill
in a source that has not synced yet is rejected on this cycle and accepted on a
later one. The count is capped by `SKILLS_COMPOSITION_MAX_SUB_SKILLS` (default
8). See
[`samples/acme-admin/composition`](../../samples/acme-admin/composition/) for a
runnable example composing `password-reset` + `lock-unlock-user`.

## Generate and hand over a password (SPEC-062)

The knowledge skill
[`GeneratePassword.md`](../../shared/platform-ops/skills/platform-runbooks/guides/GeneratePassword.md)
is available through the `platform-skills` git source, which ingests all of
`shared/platform-ops/skills/`. Search `generate a password`;
it cites the canonical policy without duplicating strength numbers. It grants no
authority and declares no executable flow.

Example request: “Reset dave's acme-admin password and give me a strong one.”
The [reset skill](../../samples/acme-admin/password-reset/skill/ResetAcmePassword.md)
generates with `secrets.generate_password(policy="default", handoff="portal_copy")`
when no temporary value was supplied, performs the separately approved reset,
and points to **Copy password** without restating the value. The
[recovery composition](../../samples/acme-admin/composition/skill/RecoverAcmeAccount.md)
retains its two independent mutation approvals; read-tier generation adds none.

Email is opt-in: “Generate a password and email it to the named recipient” uses
`secrets.deliver(channel="email", password=<working value>, recipient=<address>)`
and a separate action approval. Never treat a flow/composition approval as email
authority. Disabled tools or expired handoffs are a reason to stop, not to invent
or print a password. See the [configuration reference](configuration-reference.md#secure-password-generation-and-delivery-spec-062).

## Pre-flight validation

Always validate before publishing — the CLI uses the same code path as the
service:

```sh
# One-time setup: create the skills-hub venv
(cd products/skills-hub && uv sync)

# From the repo root, using that venv's interpreter:
products/skills-hub/.venv/bin/python -m skills_hub.validate \
  shared/platform-ops/skills/<source_id>
```

Exit code 0 means the source is safe to publish; otherwise each rejection is
reported as `(path, reason)`.

The same validation code path is also exposed as a read-only service route —
`POST /api/v1/skills/validate` on skills-hub, behind the Basic
query-credential registry (`SKILLS_QUERY_CLIENTS`). The agent service calls
it to validate generated skill drafts before they reach an operator
(SPEC-044); you can use it in CI the same way, sending
`{"document": "<raw markdown>"}` and reading `{"valid": true}` or
`{"valid": false, "reason": ...}`.

## Authoring a skill from a session record (SPEC-044)

The platform can draft a skill from the durable record of one of your own
sessions, so a good triage run becomes reusable guidance without a blank
page.

1. Open the session in the portal chat view and press **Draft as skill**
   (visible to `platform-admin`, `approver`, and `operator`). The agent
   service assembles the session's digest — plus the validated triage
   report when the session is incident-linked — and shapes it into Skill
   Format v1; raw transcripts and alert payloads never enter the draft.
2. The draft is validated on skills-hub's own ingestion code path before
   it is returned — an unvalidated draft is never handed out. If
   validation cannot run (dependency not configured or unreachable) the
   request fails closed with 503/502 instead.
3. The draft opens in a read-only **preview modal** (SPEC-045): a
   rendered view plus a **Raw** toggle showing the full markdown
   (including the provenance block), a mode badge, the validation
   status, and the suggested filename. **Download .md** hands over
   `<suggested-slug>.md`; **Discard** drops the draft without
   downloading. The badge tells you whether you hold a **generated**
   draft or the facts-only **skeleton** (the honest degradation for
   quiet sessions or generation failures — always format-valid).
4. Review, edit, and merge the draft into a skill source as usual
   ([Adding a skill to an existing source](#adding-a-skill-to-an-existing-source)).
   Every draft carries an HTML-comment provenance block (session, covered
   incident when present, date, platform version, mode) — body content
   you may keep or strip without breaking ingestion. Nothing about the
   draft is persisted on the platform: it exists only in your download.

Content guardrails are deterministic, not model obedience: the gateway's
redaction vocabulary scrubs the generated body and the Skill Format caps
are enforced by post-processing regardless of what the model emitted.

## Authoring a skill from an incident's validated triage (SPEC-045)

A triaged incident is team property — anyone holding the grant can turn
its validated triage into a skill draft, no matter who ran the triage
session:

1. Open the incident in the portal Incidents view and press **Draft as
   skill** beside **Run/Re-run triage** and **Continue in chat**
   (visible to `platform-admin`, `approver`, and `operator`; the gateway
   checks both `incident:skill_draft` and `incident:read` on every
   request).
2. The draft is generated from the incident envelope (minus the raw
   failed-triage output and the triage session reference) and the
   validated triage report only — never from anyone's session —
   validated on the same skills-hub code path,
   with the same fail-closed 503/502 postures and the same skeleton
   degradation.
3. An incident without a validated triage report (new, triaging, or
   failed triage) returns a deterministic **409** — the toast names the
   precondition: run triage first, then draft the skill. The platform
   never guesses.
4. The same read-only preview modal opens; the provenance block carries
   the incident id and no session line. Download or discard as above.

Each generation — session- or incident-anchored, downloaded or discarded
— is recorded once in the audit trail (`skill_draft_generated` /
`incident_skill_draft_generated`); the audit event is the platform's only
trace of an ephemeral draft.

## Adding a skill to an existing source

The dev-k8s platform documents (`sre-alerting`, `platform-runbooks`) live under
`shared/platform-ops/skills/` and reach the pod through the `platform-skills`
**git** source, which ingests that whole tree. Adding one is therefore a commit,
not a manifest change.

1. Create the Markdown file under the source directory (e.g.
   `shared/platform-ops/skills/sre-alerting/alerts/MyNewAlert.md`), with
   frontmatter as above. For alert runbooks, tag the skill with the alert
   name so alert → runbook lookups rank well.
2. Validate it, then merge to the branch the source tracks (`main`):

   ```sh
   python -m skills_hub.validate shared/platform-ops/skills/sre-alerting
   ```

   The next sync picks the file up within one interval (default 5 minutes).
   To force an immediate re-sync: `kubectl -n dev-luban-aiops rollout restart
   deployment/skills-hub`.

3. Verify (see [Verification](#verification)).

The resulting `skill_id` is source-prefixed — here
`platform-skills/sre-alerting/alerts/mynewalert`.

> **ConfigMap-backed `local` sources need GitOps wiring instead.** ConfigMap
> keys cannot contain `/`, so keys are flattened `<dir>-<file>` and mapped back
> to nested paths in two places: an entry under the source's ConfigMap in
> `shared/platform-ops/gitops/dev-k8s/base/kustomization.yaml` (e.g.
> `alerts-MyNewAlert.md=../../../skills/my-source/alerts/MyNewAlert.md`) and the
> matching `items:` entry in
> `shared/platform-ops/gitops/dev-k8s/base/skills-hub/skills-hub-deployment.yaml`,
> then `make build && make deploy` (the ConfigMap content is baked at render
> time). The dev overlay's only `local` source is now `samples`, whose ConfigMap
> is created out-of-band by `make deploy-samples`.
>
> **Never register the same files twice.** Mounting a tree as a `local` source
> while a `git` source's `path` also covers it stores every document twice under
> two `skill_id`s, and because ranking does no content de-duplication the copies
> consume result slots — measured at **32 of 63** recorded queries before the
> duplicate `sre-alerting`/`platform-runbooks` mounts were removed on
> 2026-10-01. See
> [the retrieval evaluation set](../workspace/semantic-skill-retrieval-eval-set.md).

## Revising a skill

Edit the file in place and re-validate. Same propagation path as adding:
ConfigMap-backed sources require `make build && make deploy` (the ConfigMap
content is baked at render time); git sources propagate on the next sync
after merge.

Keep the file path stable unless you intend to change the `skill_id` —
citations in past agent answers reference the old id, and a path change makes
that visible rather than silently breaking it.

## Removing a skill

1. Delete the Markdown file from the source.
2. For ConfigMap-backed local sources, remove the corresponding entries in
   `kustomization.yaml` and `skills-hub-deployment.yaml` (a ConfigMap entry
   pointing at a deleted file breaks `kustomize build`).
3. `make build && make deploy`. The next sync atomically replaces the
   source's slice, and the skill disappears from search, list, and get.

Git sources: merge the deletion; the next sync picks it up.

## Adding a new skill source

Choose the source type:

- **`local`** (the dev overlay now uses this only for `samples`): commit the
  documents under `shared/platform-ops/skills/<source_id>/` with a `README.md`
  (the team contribution template) and a `NOTICE` if content is adapted. Then
  wire the ConfigMap (`kustomization.yaml`), the volume + mount + `items`
  (`skills-hub-deployment.yaml`), and append the source entry to
  `SKILLS_SOURCES` in
  `shared/platform-ops/gitops/dev-k8s/base/skills-hub/runtime-config.env`.
  Pick a `path` that no `git` source's `path` already covers, or every document
  in the overlap is stored twice under two `skill_id`s:

  ```json
  {"source_id":"my-team","type":"local","path":"/skills/my-team"}
  ```

- **`git`** (production pattern — each team owns its repo): append an entry
  to `SKILLS_SOURCES`:

  ```json
  {"source_id":"payments","type":"git","url":"https://git.example/payments/skills.git","ref":"main","path":"runbooks"}
  ```

  Fields: `url` (https clone URL), `ref` (branch/tag to track, default
  `HEAD`), and optional `path` — the subdirectory within the checkout to
  ingest. Real team repos keep skills next to other code, so `path` scopes
  ingestion (a missing subpath fails the sync with a clear error instead of
  ingesting the whole tree).

  Production-parity secret split (the dev-k8s overlay follows it with the
  `platform-skills` source pointed at this repository):

  - **Non-secret** federation config (`url`/`ref`/`path`) lives in the
    ConfigMap (`SKILLS_SOURCES` in `runtime-config.env`).
  - **Secret** material lives only in the `skills-hub-runtime-secrets`
    Secret: add `"payments": "<read-only-token>"` to `SKILLS_GIT_TOKENS`
    (JSON map source_id → token, injected into the clone URL as
    `x-access-token`). In dev-k8s, export the PAT and run the provisioning
    script — the token is never echoed or committed:

    ```sh
    SKILLS_GIT_TOKEN=<pat> shared/platform-ops/gitops/sync-skills-secrets.sh
    ```

    In production the same Secret comes from your secret manager.

  The service clones into `SKILLS_DATA_PATH` and re-syncs on the interval.
  Resilience: a failing git source (unreachable URL, expired token, missing
  subpath) keeps serving its previous snapshot, reports a scrubbed error on
  the status endpoint, and never affects other sources.

Rules for both: `source_id` must match `[a-z0-9][a-z0-9-]*` and be unique;
unknown types or missing type-specific fields fail fast at startup. A failed
source sync never affects other sources.

## Removing a source

1. Remove its entry from `SKILLS_SOURCES` (and `SKILLS_GIT_TOKENS` if any).
2. For local sources, remove the ConfigMap, volume, and mount wiring.
3. `make build && make deploy`. At startup skills-hub prunes records whose
   source is no longer configured, so the removed source's skills stop
   appearing in search, list, and get immediately.

## Using skills

**Through the agent** (the intended path): the agent consults skills
automatically for procedure/remediation questions and cites what it uses.
When a `skills.*` tool succeeds, the portal's tool-evidence card shows the
matched skills as **Cited guidance** chips (title + namespaced id), so the
guidance behind an answer is visible without expanding the data summary.
Operators can ask directly:

- *"What guidance do we have for KubePodNotReady?"* → `skills.search`
- *"List all the skills we have"* → `skills.list`
- *"Show me the full runbook for platform-skills/sre-alerting/alerts/kubepodnotready"* →
  `skills.get`

**Directly against the API** (for debugging and content checks; requires the
query credential from `skills-hub-runtime-secrets`):

```sh
QUERY_CLIENTS=$(kubectl -n dev-luban-aiops get secret skills-hub-runtime-secrets \
  -o jsonpath='{.data.SKILLS_QUERY_CLIENTS}' | base64 -d)
QUERY_SECRET="${QUERY_CLIENTS#tool-gateway=}"

# Catalog (what skills.list sees)
kubectl -n dev-luban-aiops exec deployment/skills-hub -- \
  curl -fsS -u "tool-gateway:${QUERY_SECRET}" \
  "http://localhost:8000/api/v1/skills?limit=100"

# Search (multi-word queries match OR-wise; the shared scorer ranks them)
kubectl -n dev-luban-aiops exec deployment/skills-hub -- \
  curl -fsS -u "tool-gateway:${QUERY_SECRET}" \
  "http://localhost:8000/api/v1/skills/search?q=kubernetes%20incident"

# One full record
kubectl -n dev-luban-aiops exec deployment/skills-hub -- \
  curl -fsS -u "tool-gateway:${QUERY_SECRET}" \
  "http://localhost:8000/api/v1/skills/platform-skills/sre-alerting/alerts/kubepodnotready"
```

**End-to-end smoke test** after any content change:

```sh
sh shared/platform-ops/e2e/skills-demo.sh   # set SKIP_CHAT_LEG=true to skip the chat leg
```

## Verification

The status endpoint is auth-exempt and reports per-source sync outcomes:

```sh
kubectl -n dev-luban-aiops exec deployment/skills-hub -- \
  curl -fsS http://localhost:8000/api/v1/skills/status
```

Check per source: `accepted` counts match your file counts, `rejections` is
empty, and `last_error` is `null`.

Prometheus metrics on `/metrics`:

| Metric | Meaning |
|---|---|
| `skills_syncs_total{source,result}` | sync cycles by outcome; watch `result="error"` |
| `skills_ingest_rejected_total{reason}` | documents rejected at validation |
| `skills_store_skills{source}` | currently served skills (per source) |
| `skills_searches_total` | search traffic |

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| New/revised skill not visible | Sync not yet run, or (for a `local` source) ConfigMap wiring missed a file | Wait one interval or `kubectl rollout restart deployment/skills-hub`; for a `local` source check kustomization + deployment `items`, for a git source check the merge reached the tracked `ref` |
| Source reports rejections | Document violates the format contract | Read the `rejections` reasons in `/api/v1/skills/status`; fix and re-validate |
| Source reports `last_error` | Unreachable git URL / bad token / unreadable path | Fix credentials or path; the previous slice keeps serving until then |
| Git source errors mention auth, others healthy | `SKILLS_GIT_TOKENS` missing the source's token | Re-run `sync-skills-secrets.sh` with `SKILLS_GIT_TOKEN` exported (dev) or update the Secret (prod) |
| Git source errors mention a subpath | Configured `path` absent from the repo checkout | Fix `path` in `SKILLS_SOURCES` or move the skills directory |
| Search returns no matches | Query words co-occur nowhere, or source never synced | Try `skills.list` / the catalog endpoint to confirm the skill exists; check status |
| The same document appears twice in search results | One tree is registered both as a `local` mount and inside a `git` source's `path` | Keep exactly one route per tree. `skill_id` is source-prefixed, so both copies rank separately and consume result slots |
| `kustomize build` fails | A ConfigMap generator entry points at a deleted/renamed file | Align the generator's keys with the files on disk (the base overlay generates `platform-policy` and `postgres-initdb`; skill ConfigMaps are created by `make deploy-samples`) |
| Agent claims no skills exist | skills connector not registered | Check `GATEWAY_SKILLS_SERVICE_URL` and the query-secret match (see [Configuration Reference](configuration-reference.md)) |

For deployment-level symptoms (CrashLoopBackOff, ErrImagePull, secrets),
see [Troubleshooting](troubleshooting.md).
