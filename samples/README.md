# Samples

Self-contained tutorial samples for the Luban AIOps platform. Each sample
demonstrates a complete automation pattern — skill document, demo script, and
any sample-specific target infrastructure — so you can discover, run, and
adapt it for your own use case. Sample skills install into a running cluster
with `make deploy-samples`; the platform never hard-wires a specific sample.

## Available samples

### ACME Admin

All seven samples drive **one** application — `acme-admin`, a stateful FastAPI
console with a real JSON store — so each can prove its writes actually landed
rather than trusting a rendered URL. Five form a progressive ladder on the *card
count*; the other two share the same target to contrast the *approval models*.

**The five-rung ladder.** Read together these make a claim none of them makes
alone: **the card count tracks the *effect* of a skill, not the surface it
uses.** Rungs 1 and 3 both talk to the JSON API and differ; rungs 2 and 4 both
drive a browser and differ; rung 5 composes rungs 3 and 4 and shows that
ordering two mutating skills does not merge their gates.

| Sample | Description |
|---|---|
| [acme-admin/health-check](acme-admin/health-check/) | Read `/healthz` over the `http.get` service-check surface — **0 cards**, the repository's first genuinely card-free skill (SPEC-058) |
| [acme-admin/user-status](acme-admin/user-status/) | Read a user's status off the rendered console through a **bound read-class browser flow** — still **0 cards**, which is the observation this rung exists to produce |
| [acme-admin/lock-unlock-user](acme-admin/lock-unlock-user/) | Lock or unlock an account with one `http.post` — **1 card**, `approval_kind: action`, decided by a second identity |
| [acme-admin/password-reset](acme-admin/password-reset/) | Reset a password through the console UI — **1 card**, `approval_kind: flow`, headed by the skill's authored `flow_intent` |
| [acme-admin/composition](acme-admin/composition/) | A `kind: composition` runbook ordering rung 4 then rung 3 into one account recovery — **2 cards** (a `flow` and an `action`), one per mutating sub-skill, because ordering never merges gates (SPEC-057, ADR-0011) |

**The two approval-model samples** take the same console password reset and show
where rung 4's bound flow comes from — and what the work costs before one
exists:

| Sample | Description |
|---|---|
| [acme-admin/adhoc-password-reset](acme-admin/adhoc-password-reset/) | The console reset driven **ad-hoc with no bound flow**, so each mutating browser action parks its own per-action change-request card (`approval_kind: action`) — the unbound counterpart to `password-reset`, demonstrating SPEC-054 |
| [acme-admin/skill-graduation](acme-admin/skill-graduation/) | Author that same reset **ad hoc**, then **graduate** the approved mutations into an executable-flow skill and replay it under one gate — N `action` cards to author, 1 `flow` card thereafter, demonstrating SPEC-055. Ships **no `skill/`**: the skill is the artifact the demo produces |

See [acme-admin/README.md](acme-admin/README.md) for the app and the suite.

`acme-admin` is the **first sample to own a container image**, and the first
category to hold infrastructure shared by all its samples rather than one:

```
samples/acme-admin/
├── README.md              # the app's own operator-facing document
├── app/                   # the FastAPI application (image, tests, its own Makefile)
├── deploy/                # kustomization, deployment, service, networkpolicy
├── deploy.sh              # build + apply + ASSERT (make deploy-sample-app)
├── demo-lib.sh            # shared plumbing the demos source
├── demo-suite.sh          # the five rungs in ladder order + the cross-skill leg
├── health-check/          # ┐
├── user-status/           # │ the five ladder rungs: the usual
├── lock-unlock-user/      # │ per-sample layout — README,
├── password-reset/        # │ WALKTHROUGH, skill/, demo/
├── composition/           # ┘ (rung 5 — the composition runbook)
├── adhoc-password-reset/  # ┐ the two approval-model samples
└── skill-graduation/      # ┘ (graduation ships no skill/)
```

Deploy it out-of-band, after the platform:

```sh
make deploy-sample-app     # build the image, apply deploy/, then assert it works
make deploy-samples        # install the six skill documents
make undeploy-sample-app   # remove it again
```

**`browser-check-target` is retired.** The static page bundle in platform GitOps
was the target these browser samples once drove; SPEC-060 rebased all three onto
the stateful `acme-admin` app above and retired the static
`web-checks/password-reset` sample outright, so the `samples/web-checks/`
category is gone. SPEC-061 then removed the static target itself along with its
last *platform* consumers — the `platform-runbooks/web-checks/InventoryHealth.md`
runbook, the `shared/platform-ops/e2e/browser-check-demo.sh` smoke test, and the
`browser-dev` allowlist origin and credential fixtures — because the
`acme-admin` suite (which *is* in `make e2e`) already demonstrates the same
browser flow gate against a target that really mutates. The `browser-dev`
profile remains as the browser *posture* profile, now permitting the one
`acme-admin` origin.

## Directory structure

Each sample follows this layout:

```
samples/
└── <category>/
    └── <sample-name>/
        ├── README.md           # Tutorial walkthrough
        ├── WALKTHROUGH.md      # Live, click-by-click run against a cluster (optional)
        ├── skill/              # Skill document(s) — installed by `make deploy-samples`
        ├── demo/               # Demo/test script(s)
        └── target/             # Sample-specific target infrastructure (optional)
```

Not every sample needs all subdirectories. `skill/` may even be absent by
design: `acme-admin/skill-graduation` ships none because its skill is the
artifact the demo *produces*, and `deploy-samples.sh` discovers samples by
`find -type d -name skill`, so such a sample is simply invisible to the
installer (and `SAMPLE=<that-sample>` exits non-zero saying so). A category may
also hold more than samples: `acme-admin/` carries the application, its deploy
manifests and the shared demo plumbing its samples all use, because they are one
suite against one store rather than seven independent stories.

Infrastructure shared with the platform or other samples (browser target pages,
NetworkPolicy, credential sets) lives in the platform's GitOps directory and is
referenced from the sample's README — the dependency arrow is always tutorial →
platform, never the reverse. Sample skills need no GitOps wiring at all:
`make deploy-samples` installs them into a generic `samples` source (see below).

## Relationship to platform skills

Platform skills (under `shared/platform-ops/skills/`) are built-in runbooks
shipped with the platform — SRE alert handlers, Kubernetes troubleshooting
guides, and the like — ingested from the `platform-skills` git source alone; the
base overlay generates no skill ConfigMaps. Sample skills are separate: they
install out-of-band via `make deploy-samples` into a dedicated `samples` source,
so a tutorial can be added or removed without touching platform GitOps. Samples
are also richer: they bundle the skill with the demo script (and any
sample-specific target) needed to run the pattern end-to-end.

## Installing samples into a cluster

Sample skills are **not** part of `make deploy` — the platform base overlay
ships no tutorial content. After the cluster is up, install samples with:

```sh
make deploy-samples                                    # install every sample
make deploy-samples SAMPLE=acme-admin/password-reset   # install just one
make undeploy-samples                                  # remove them all again
```

`deploy-samples` packs the selected samples' `skill/*.md` files into the
optional `skills-samples` ConfigMap that skills-hub mounts read-only at
`/skills/samples` (source id `samples`), then restarts skills-hub to
re-ingest. Each skill's id becomes `samples/<slug>` (the mounted file name,
lowercased, non-alphanumerics collapsed to `-`). The ConfigMap is declarative
— it always holds exactly the selected set — and is not base-managed, so it
survives subsequent `make deploy` runs.

## Adding a new sample

1. Create a directory under the appropriate category
2. Add a `README.md` explaining the automation pattern
3. Add the skill document under `skill/` — unless the sample's point is that
   the platform produces it, in which case say so in the README
4. Add a demo script under `demo/`, mode `755`
5. If your sample needs its own target infrastructure, add it under `target/`
   (shared infra used by more than one consumer stays in platform GitOps)
6. Install it into your cluster with
   `make deploy-samples SAMPLE=<category>/<sample-name>` — no GitOps edits
   needed; the platform exposes one generic `samples` skill source

Two things that do not happen automatically:

- **`make e2e` has a hardcoded script list.** A new `demo.sh` does not join it
  by existing; add the path to the `e2e` target's loop in the root `Makefile`.
- **Skill ids are derived from the mounted file name**, which
  `deploy-samples.sh` builds as `<sample-dir>-<file-name>.md` — the *category*
  directory drops out. Two samples whose derived names collide silently re-id
  each other, and two `--from-file` arguments with the same ConfigMap key is a
  hard failure. `acme-admin/password-reset` names its document
  `ResetAcmePassword.md` for exactly this reason: SPEC-059 shipped it beside a
  static `password-reset` sample whose `ResetUserPassword.md` would otherwise
  collide byte-identically. SPEC-060 retired that static sample, but the name
  stays — renaming a delivered skill would re-id it.
