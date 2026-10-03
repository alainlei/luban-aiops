# Eval set: Lexical Skill-Retrieval Baseline

Status: **measurement artifact — gate 1 of the spike memo. Authorizes no implementation, ADR, or spec.**
Date: 2026-09-30 · Revised: 2026-10-01 (§2.4 correction applied to the memo; catalogue and pool regenerated against the de-duplicated 18-row corpus)
Companion to: [semantic-skill-retrieval-spike.md](./semantic-skill-retrieval-spike.md) — this file instantiates its [§7.1 Evaluation set](./semantic-skill-retrieval-spike.md#71-evaluation-set)
Roadmap home: [Exploration Backlog](../agentic-aiops-platform/delivery-roadmap.md#exploration-backlog), "Semantic (vector) skill retrieval"
Promoted to: [SPEC-066 skill retrieval ranking fidelity](../specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md) — **`draft` 2026-10-01, `approved` 2026-10-02, `delivered` 2026-10-03 as v0.46.0.** §8's measurement is the spec's evidence base and the committed label fixture (§7.1) is what its R-8 must re-measure against, **through the Postgres backend** rather than through `rank()` directly: §8's numbers were produced offline over a corpus export with no prefilter in the path, so **0.500 → 0.711 is a memory-path upper bound for deployed environments**, not a shipped figure. R-8 therefore **reconstructs and commits** §3's harness rather than reusing it — §3's is not in the repository — and the rebuilt instrument must first reproduce §8.1's published **19/38** combined top-1 baseline before any number from it is believed. §9's boundary is unchanged by the draft and by the approval, which authorizes implementation to begin and no merge, migration, deployment, or version bump.
Evidence baseline: 2026-09-30 extraction at repository v0.45.0 (`26fbd9b`); 2026-10-01 re-export at `02e8e99` with the `SKILLS_SOURCES` change still uncommitted in the working tree. Corpus exported from the `skills` database and queries from the `audit` database on `postgres-0` in the `dev-luban-aiops` cluster. **The 2026-09-30 extraction was entirely read-only** — nothing was installed, embedded, deployed, mutated, or labeled. The 2026-10-01 revision **was not**: it re-exports the same two databases after the operator-authorized `SKILLS_SOURCES` change described in §2.1, which mutated the dev cluster. The 63 queries and their audit statistics are byte-identical between the two passes, and **no product code was modified in either**. Scoring is still the real `scoring.py`, run offline (§3).

## 1. What this file is, and what it is not

The spike memo's central recommendation is *measure before building*: no vector
substrate, embedding run, or spec is justified until the lexical baseline has a
labeled precision number. This file is the **input** to that measurement. It
contains:

- a deduplicated snapshot of the corpus the scorer runs over (§4),
- the complete pool of 63 real queries extracted from the audit trail, each with
  the candidates the current lexical scorer returns at depth 10 (§5),
- the labeling protocol operations must follow to turn that pool into ground
  truth (§6), a blank label sheet (§7), and the metrics and pre-registered
  decision rule the labels feed (§8).

It is **not** a labeled set. Nothing here has been judged relevant or irrelevant
by anyone who owns the runbooks, and per the memo an unreviewed set measures the
author's guesses rather than retrieval quality. Every number in §2 is a property
of the scorer and the corpus, not of answer quality.

Two constraints on reuse:

- **The pool is pinned to the 2026-10-01 corpus — 18 rows, one per document.** The
  catalog has already moved twice: historical audit results include
  `platform-runbooks/web-checks/inventoryhealth`, which no longer exists (retired
  with the `web-checks` samples), and the 2026-09-30 extraction's 12 duplicate rows
  were pruned on 2026-10-01 (§2.1). Re-running this extraction against a changed
  catalog silently invalidates prior labels, so the snapshot in §4 is part of the
  fixture, not decoration. Labels recorded against the 2026-09-30 pool would still
  be *usable* — no query's top-1 moved and every code→document mapping is unchanged
  — but any pool regenerated after a further catalog move must be re-pinned here.
- **The traffic is demo/e2e, not sustained operator triage.** All 96 recorded
  searches fall between 2026-09-02 and 2026-09-22. The pool is a real but narrow
  sample; §6 therefore requires a paraphrase stratum that the audit trail cannot
  supply.

## 2. What the extraction measured — three lexical defects, one since fixed by configuration

Extracting the pool required re-running the real scorer, which produced evidence
the memo did not have. All three findings below are measured and reproducible (§3),
and **none of them requires a vector store to fix**. They materially strengthen
[Option D — improve the lexical baseline first](./semantic-skill-retrieval-spike.md#44-option-d--improve-the-lexical-baseline-first-cheapest-may-be-sufficient).
Defect 1 (§2.1) was resolved by a configuration change on 2026-10-01 and its
measurement is retained as history; defects 2 and 3 (§2.2, §2.3) are unchanged and
still reproduce against the current corpus.

### 2.1 The corpus was 18 documents in 30 rows — resolved by configuration 2026-10-01

*Measured 2026-09-30 against a 30-row corpus; resolved 2026-10-01. The measurement
is retained in full because it is the evidence for a product gap the configuration
change does **not** close.*

`SKILLS_SOURCES` in
[`runtime-config.env`](../../shared/platform-ops/gitops/dev-k8s/base/skills-hub/runtime-config.env)
registered four sources. Two were local ConfigMap mounts (`/skills/platform-runbooks`,
`/skills/sre-alerting`); the fourth, `platform-skills`, is a **git** source pointed
at `shared/platform-ops/skills` — the parent directory of exactly those same two
trees. The ConfigMaps were generated from the *same files* that git source
ingested (the base `kustomization.yaml` mapped `../../../skills/sre-alerting/alerts/*.md`
and `../../../skills/platform-runbooks/guides/*.md`), so this was not similar
content but literally one file reaching the store by two routes under two
`source_id`s. Grouping on `md5(body)` confirmed it in the database: **12 groups of
2 byte-identical bodies plus 6 singletons**.

Because `skill_id` is source-prefixed, the two routes produced two distinct ids, and
`rank()` — which has no content-level de-duplication — scored both copies
identically and gave them separate slots in a `limit=5` window, ties broken on
`skill_id` ascending so the `platform-runbooks/…` copy always preceded the
`platform-skills/platform-runbooks/…` copy.

The worst observed case was Q03 `KubePodNotReady` — 9 occurrences, the most
frequent query in the entire trail — returning 4 hits that contained **2 distinct
documents**, ranks 3–4 being a second copy of `KubeDeploymentReplicasMismatch` at
score 1.0, a document with no plausible bearing on a pod-readiness alert.

**Resolution.** The two local sources were dropped on 2026-10-01, leaving `samples`
(local) and `platform-skills` (git, ref `main`). The startup prune removed the 12
orphaned rows and the two ConfigMaps were deleted. Before and after, measured with
the same offline harness over the same 63 queries:

| Measure | 2026-09-30 | 2026-10-01 |
|---|---|---|
| Corpus rows | 30 | **18** |
| Distinct documents (`md5(body)`) | 18 | 18 |
| Byte-identical duplicate rows | 12 | **0** |
| Queries with duplicate crowding in the top 5 | **32 of 63 (50.8%)** | **0 of 63** |
| …restricted to stratum B (§6.1) | 22 of 49 (44.9%) | **0 of 49** |
| Distinct documents across all 63 top-5 windows | 265 of a possible 315 | **309 of 315** |
| Pool entries at depth 10, all queries summed | 582 | 526 (−56, every one a duplicate) |
| Queries filling the depth-10 pool | 43 | 24 |

The change was purely subtractive, and that is verified rather than assumed:

- **No query's top-1 document changed** (0 of 63).
- For all 63 queries, the de-duplicated 2026-09-30 pool is an exact **prefix** of
  the 2026-10-01 pool — same documents, same relative order, same per-document
  scores. Nothing was re-ranked.
- **28 queries gained candidates** at depth 10 (+88 slots): documents the duplicates
  had pushed out of the window are now visible to labelers, so the pool is strictly
  wider than the one §5 pinned on 2026-09-30.
- The 6 top-5 slots that remain unfilled are exactly those of Q03/Q04
  (`KubePodNotReady`, `KubePodNotReady alert`), which return 2 hits in total — a
  tokenizer problem (§2.2), not crowding.

**What the fix does not do.** Crowding was a *configuration* overlap exposing a
*missing product capability*, and only the configuration half is gone. `rank()`
still collapses nothing, so any deployment that registers two sources covering the
same files reproduces the 32-of-63 result exactly — including a production one.
Nothing would reject that configuration: `parse_sources`
([`core/config.py:51-115`](../../products/skills-hub/src/skills_hub/core/config.py))
validates the JSON shape, the id pattern, required per-type keys, and duplicate
`source_id` values, but two sources with **distinct** ids covering the same files
are well-formed and ingest happily. The duplicate-`skill_id` check in
[`ingestion.py`](../../products/skills-hub/src/skills_hub/services/ingestion.py) is
scoped to a single source, so it cannot see across the federation either. The
dev-overlay change makes the baseline measurable; it is not a guardrail. Step 1 of
the §8 decision rule therefore remains open on its product half, and the guidance
added to [`skills-guide.md`](../../docs/guides/skills-guide.md) ("never register the
same files twice") is documentation, not enforcement.

### 2.2 CamelCase titles are opaque to the tokenizer

`tokenize()` is `re.findall(r"[a-z0-9]+", text.lower())`
([`scoring.py:20,28-30`](../../products/skills-hub/src/skills_hub/services/scoring.py)).
Measured directly:

| Input | Tokens |
|---|---|
| `KubePodCrashLooping` | `['kubepodcrashlooping']` — **one opaque token** |
| `Crash Loops and OOM Kills` | `['crash', 'loops', 'and', 'oom', 'kills']` |

Every `sre-alerting` document is titled in CamelCase, so **no alert title can ever
match a sub-word query term in the highest-weighted field (3.0)**. Matching is also
strict token equality with no stemming, so the `CrashLoopBackOff` tag on
`KubePodCrashLooping` is unreachable from the query token `crashloop`
(`'crashloop' == 'crashloopbackoff'` → `False`).

The consequence is measured, not inferred. For Q46 `pod keeps restarting CrashLoopBackOff`,
scored against the current 18-row corpus:

| Rank | Code | Document | Score |
|---|---|---|---|
| 1 | `D06` | Pod Scheduling Failures | 10.0 |
| 2 | `D11` | **KubePodCrashLooping** | 10.0 |
| 3 | `D01` | Crash Loops and OOM Kills | 8.0 |
| 4 | `D02` | Debug Pods | 8.0 |
| 5 | `D12` | KubePodNotReady | 8.0 |

The single most on-point document in the corpus is ranked **second**, behind a guide
about *scheduling* failures — and because the two are tied at 10.0, that ordering is
decided by **alphabetical `skill_id` sort, not relevance**:
`platform-skills/platform-runbooks/…` precedes `platform-skills/sre-alerting/…`
because `p` < `s`. Removing the duplicate rows (§2.1) lifted `D11` from third to
second and changed nothing else; the tie-break still picks the wrong document.
Adding one word flips it: Q47 `pod keeps restarting CrashLoopBackOff restart`
puts `D11` first at 11.0 against `D06` at 10.0. A one-token query change reordering
the top result is exactly the variance the memo's §7.2 "rank stability" metric exists
to catch, and it is why defect 2 survives the configuration fix.

The same opacity bounds how much the corpus can answer at all, and Q03 shows it in
both directions. `tokenize('KubePodNotReady')` is the single token
`kubepodnotready`, so the exact alert name — the most frequent query in the trail, 9
occurrences — matches only **2 of 18 documents** (`D12` at 6.0 from title 3 + tag 2 +
one body occurrence, `D08` at 1.0). Those two hits are the only unfilled top-5 slots
left in the pool (§2.1). Rewriting the same problem in prose does not help either:

| Query | Hits | Top 3 (score) |
|---|---|---|
| `KubePodNotReady` | 2 | `D12` (6.0), `D08` (1.0) |
| `pod not ready` | 5 | `D06` (12.0), **`D12` (11.0)**, `D02` (10.0) |
| `pod is not ready kubernetes` | 5 | **`D12` (18.0)**, `D06` (15.0), `D02` (14.0) |

The exact identifier under-matches; the natural paraphrase matches five documents but
still ranks `D06` *Pod Scheduling Failures* above `D12`; and whether `D12` leads is
decided by whether the searcher happened to append the word `kubernetes` — which is a
tag on `D12` worth 2.0. One optional query word moving the top result is the rank
instability §8 measures, and it is why stratum C (§6.1) cannot be skipped: the audit
trail contains no paraphrase of this query, so it cannot see this failure at all.

### 2.3 A non-zero `result_count` is not evidence of a useful answer

The memo records zero-hit searches as **0 of 96** and correctly warns that
`result_count` measures non-emptiness rather than correctness. The pool makes the
warning concrete:

| Query | Occurrences | Top hit | Score | Problem |
|---|---|---|---|---|
| Q31 `argocd health check` | **7** (2nd most frequent) | `D15` Check ACME Admin Service Health | **20.0** | No ArgoCD document exists in the corpus. A high-confidence top score on an HTTP `healthz` check against a *sample admin app* |
| Q01/Q02 `DemoTriage … SPEC-015 triage` | 2 | `D08` KubeDeploymentReplicasMismatch | 9.0 | No `DemoTriage` document exists (that sample was retired) |

So the trail simultaneously shows **zero empty results** and **confidently scored,
wholly irrelevant top-1 answers**. Zero-hit rate is not a recall proxy and must not
be reported as one; the metric that captures this failure is *zero-relevant rate*
— the fraction of queries whose entire top-5 contains no document an operator
would accept (§8).

Both rows above are **unchanged by the 2026-10-01 de-duplication**: `D15` still
scores 20.0 and leads Q31, and `D08` still scores 9.0 and leads Q01/Q02. That is the
point — neither is a crowding artifact. They are vocabulary gaps, and no amount of
source-list hygiene touches them.

### 2.4 Correction to the memo — applied 2026-10-01

Memo [§2.2](./semantic-skill-retrieval-spike.md#22-the-corpus-and-the-real-query-record-live-corpus-re-measured-2026-10-01)
originally asserted that "the observed 5-word mode confirms natural phrasing reaches
the scorer" and that the "agent already adapts to lexical" masking hypothesis is
**not** supported. The stratification in §6.1 undercuts that: **14 of 63 queries
already contain the identifier of the document they were looking for**
(`DemoTriage`, `ResetPasswordAdHoc`, `ResetUserPassword`, `scratch-restart-demo`,
`browser-check-target`, `svc-check`, `SPEC-015`), and many others are visibly
keyword-enumerated (`argocd application-server repo-server deployment pod`,
`pod health check readiness verify running ready conditions`). A 5-word mode is
consistent with keyword stuffing as readily as with natural phrasing.

The honest statement is weaker and better: **the query mix is dominated by
searcher-composed keyword sets, so the pool cannot measure paraphrase tolerance at
all** — which is precisely why §6.1 requires a paraphrase stratum that the audit
trail cannot supply. The memo's conclusion is unchanged; its supporting argument
was overstated, and the memo's 2026-10-01 revision pass has corrected it — §2.2 now
records the hypothesis as **untested rather than disproved**, and its new §2.3
carries the three defects above.

### 2.5 Document-length bias and unweighted function words — measured 2026-10-01

Grading the labelled set exposed a fourth defect that the pool analysis could not
see, because it changes *which* document wins rather than how many slots are
filled. `score()` sums `BODY_WEIGHT × min(occurrences, 5)` with no normalisation
for document length, and weights every query token identically.

Measured over the 18-row snapshot:

| Family | Documents | Mean body size |
|---|---|---|
| `samples/*` (acme-admin) | 6 | **9,718 chars** |
| `platform-skills/*` (guides + alerts) | 12 | **1,424 chars** |

The sample documents are **6.8× longer**, so at the cap of 5 occurrences a sample
earns up to `5 × 1.0` per matched token where a runbook earns fewer simply by being
short. Decomposing `score()` into its title/tag/body contributions for every
stratum-C query where the lexical top-1 is graded 0:

| Query | Lexical top-1 (grade) | Body's share of the winning score | Correct document |
|---|---|---|---|
| C03 `app crash looping after deploy` | `D17` Reset a Password in the ACME Admin Console (0) | 100% | `D01`/`D11` |
| C04 `process out of memory killed` | `D14` Recover a Locked-Out ACME Admin Account (0) | 100% | `D01`/`D09` |
| C09 `service name not resolving` | `D15` Check ACME Admin Service Health (0) | **15.0 of 20.0** (`D03` scores 9.0) | `D03` |
| C14 `replica count is wrong` | `D14` Recover a Locked-Out ACME Admin Account (0) | 100% | `D08` |

Body matches supply **70–100% of the winning score in every one of these cases**.
The tally across stratum C: the six sample documents take top-1 on **10 of 18**
paraphrases, although only 4 of the 18 are about the samples at all, and **8 of 18
top-1 results are graded 0**.

Token weighting compounds it. Because every token counts the same, a function word
in a *title* scores the full `TITLE_WEIGHT`: for C16 `certificate expired on the
ingress`, `D17` earns **3.0 from a title match on the stopword "the"** — enough to
make a password-reset runbook the top answer to a TLS-certificate question. There
is no stoplist and no inverse-document-frequency weighting anywhere in the path.

Both halves are purely lexical and neither needs a model. They are measured here
rather than fixed, because §9 authorises no change to `scoring.py`.

### 2.6 `skill_id` is not an indexed field — measured 2026-10-01

`score()` reads exactly three fields:

```python
title_tokens = set(tokenize(skill.title))
tag_tokens = {token for tag in skill.tags or [] for token in tokenize(tag)}
body_counts = Counter(tokenize(skill.body))
```

`skill.skill_id` is never read. The consequence is that **an operator who types a
skill's exact name gets zero signal from it**, because the name lives in the slug
and nowhere else. Probing each identifier §6.1 lists against every indexed field of
every document:

| Identifier typed by an operator | Appears in | Effect under the shipped scorer |
|---|---|---|
| `ResetPasswordAdHoc` | `D13`'s `skill_id` only | **invisible** — contributes 0 |
| `RecoverAcmeAccount` | `D14`'s `skill_id` only | **invisible** — contributes 0 |
| `LockUnlockUser` | `D16`'s `skill_id`; bodies of `D14`/`D17`/`D18` | owner gets **0**, three non-owners get body credit |
| `CheckServiceHealth` | `D15`'s `skill_id`; body of `D18` | owner gets **0**, `D18` gets the credit |
| `CheckUserStatus` | `D18`'s `skill_id`; bodies of `D14`/`D15`/`D16`/`D18` | owner gets body credit; so do three non-owners |
| `DemoTriage` | **nothing anywhere** | retired sample (§2.3) — unmatchable |
| `ResetUserPassword` | **nothing anywhere** | retired by SPEC-060 — unmatchable |

The cross-reference rows are worse than the invisible ones: where a skill name
appears in *other* documents' bodies as a cross-reference, those documents earn the
credit that the owner cannot.

Measured effect on stratum A, using an objective check that needs no relevance
labels — *is the document that owns the identifier ranked first?* Only 3 of the 14
stratum-A queries name an identifier that exists in the corpus, and all three name
`ResetPasswordAdHoc` (owner `D13`):

| Candidate | Identifier owner recovered at top-1 |
|---|---|
| Shipped scorer | **0 of 3** (`D17` wins each time) |
| + `skill_id` indexed at `TAG_WEIGHT` | 1 of 3 |
| + IDF | 1 of 3 |
| + CamelCase splitting | 2 of 3 |
| + CamelCase **and** `skill_id` | **3 of 3** |

The remaining 11 stratum-A queries name an identifier that matches no document at
all, yet each still returns 7–10 confident hits (§2.3's failure mode, inside the
stratum that was excluded from the zero-relevant metric).

Indexing `skill_id` is **cheaper than any tokenizer fix** — one added field, no IDF
table, no stemming, no change to the tie-break — so §8's cost order requires it to
be measured first. It is recorded here as a measurement; implementing it touches
`scoring.py` and the `to_tsvector` pre-filter in `skill_store.py`, which §9 forbids.

## 3. Reproduction

Every number above is reproducible read-only. No product code was modified, and
no scorer logic was reimplemented — the analysis imports the real
[`scoring.py`](../../products/skills-hub/src/skills_hub/services/scoring.py)
module and calls its `rank()` directly.

1. **Export the corpus** (18 rows as of 2026-10-01; 30 before it: `skill_id`,
   `title`, `tags`, `body`):

   ```
   kubectl --context orbstack -n dev-luban-aiops exec postgres-0 -- \
     psql -U audit -d skills -c "COPY (SELECT skill_id, title, \
       coalesce(array_to_string(tags, E'\x1f'),''), body FROM skills \
       ORDER BY skill_id) TO STDOUT WITH (FORMAT csv)" > skills.csv
   ```

2. **Export the query pool and its audit statistics** from the `audit` database:

   ```
   SELECT DISTINCT details->>'query' FROM audit_events
    WHERE event_type='skill_searched' ORDER BY 1;

   SELECT details->>'query', count(*),
          round(avg((details->>'result_count')::int),2)
     FROM audit_events WHERE event_type='skill_searched' GROUP BY 1;
   ```

3. **Score offline.** Load `scoring.py` (its only import is a type-only
   annotation), build records exposing `skill_id`, `title`, `tags`, `body`, and
   call `rank(query, corpus, 10)`. Python 3.9 caveat: register the module in
   `sys.modules` *before* `exec_module`, or `@dataclass` fails resolving
   `SearchHit`'s annotations.

**Do not validate by calling the search API.** A `skills.search` call appends a
`skill_searched` audit event (SPEC-029), which changes the `n` and `avg hits`
columns of §5 and can add a distinct query to the pool. Reproduce offline against
the exported CSV instead; the corpus counts can be cross-checked read-only via
`/health/ready` (`source_count`, `skill_count`) and `/api/v1/skills/status`, neither
of which is audited as a search.

**Validation (2026-09-30, 30-row corpus).** The offline reproduction returned the
same documents in the same order as the `skill_ids` arrays recorded in the audit
trail for every cross-checked query whose catalog had not drifted — Q03
`KubePodNotReady`, Q46 `pod keeps restarting CrashLoopBackOff`, and Q56 `restart
pod`, including the duplicate pairs and their `skill_id` tie-break order.

Two cross-checked queries **did not** match, and the mismatch is itself evidence:

| Query | Historical `skill_ids` | 2026-09-30 pool | Cause |
|---|---|---|---|
| Q31 `argocd health check` | led by `platform-runbooks/web-checks/inventoryhealth` | led by `D15` | that document was retired with the `web-checks` samples |
| Q40 `password reset` | one `generatepassword` row | `D04` in **two** slots | the duplicate row did not exist at search time — same scores and the same `skill_id` tie-break would have surfaced it had the `platform-skills` source already contributed it |

So the audit trail's recorded results are **not** reusable as ground truth for a
later corpus. Labels must be computed against a pinned snapshot, which is why §5
regenerates the pool rather than replaying `skill_ids`.

**Validation (2026-10-01, 18-row corpus).** The audit trail can no longer serve as
the cross-check — it records the 30-row era — so the regenerated pool is validated
three other ways, all reproducible from §5 alone:

1. *Metric definitions.* Recomputing crowding from the **pinned 2026-09-30 pool
   column** reproduces §2.1's `32 of 63` and `22 of 49 (44.9%)` exactly, and agrees
   with all 63 of that table's `distinct@5` cells. The 2026-10-01 figures therefore
   use identical definitions, not looser ones.
2. *Cross-run consistency.* For all 63 queries the de-duplicated 2026-09-30 pool is
   an exact prefix of the 2026-10-01 pool, codes **and** scores. Two independent
   runs of the real scorer over two different exports agree on every overlapping
   candidate; only the duplicates and the newly-reachable tail differ.
3. *Corpus agreement.* The CSV holds 18 rows with 18 distinct `md5(body)`, matching
   Postgres `count(*)`/`count(DISTINCT md5(body))`, the service's own
   `skill_count: 18` / `source_count: 2`, and the per-source accepted counts
   (`platform-skills` 12, `samples` 6). Every exported `skill_id` maps to exactly one
   `D01`–`D18` code in §4, with none left over.

## 4. Document catalogue — 18 documents, one corpus row each

Codes `D01`–`D18` are the labeling unit, and they are unchanged by the 2026-10-01
re-export: same titles, same tags, same order. What changed is the last column —
each code now maps to exactly **one** `skill_id`, because the unprefixed
`platform-runbooks/…` and `sre-alerting/…` rows were pruned with the two local
sources (§2.1). Any label sheet written against the 2026-09-30 catalogue still
grades the same documents; only the row ids it would cite have moved.

Labels attach to a **document**, never to a corpus row. That rule is still
load-bearing rather than merely tidy: `rank()` performs no content de-duplication,
so a deployment that re-registers overlapping sources would put the same runbook
back into two slots, and row-level grading would double-count it and launder the
defect into the metric.

| Code | Title | Tags | Corpus row (`skill_id`) |
|---|---|---|---|
| `D01` | Crash Loops and OOM Kills | kubernetes, pod, troubleshooting, oom, crashloop | `platform-skills/platform-runbooks/guides/crashloopsandoom` |
| `D02` | Debug Pods | kubernetes, pod, troubleshooting, debugging | `platform-skills/platform-runbooks/guides/debugpods` |
| `D03` | Debug Services | kubernetes, service, troubleshooting, dns, networking | `platform-skills/platform-runbooks/guides/debugservices` |
| `D04` | Generate a Password and Deliver It Securely | password, generate, secret, delivery, reset, account-recovery, portal-copy, email | `platform-skills/platform-runbooks/guides/generatepassword` |
| `D05` | Image Pull Failures | kubernetes, pod, troubleshooting, image | `platform-skills/platform-runbooks/guides/imagepullfailures` |
| `D06` | Pod Scheduling Failures | kubernetes, pod, troubleshooting, scheduling | `platform-skills/platform-runbooks/guides/podschedulingfailures` |
| `D07` | KubeContainerWaiting | kubernetes, pod, alerting, KubeContainerWaiting | `platform-skills/sre-alerting/alerts/kubecontainerwaiting` |
| `D08` | KubeDeploymentReplicasMismatch | kubernetes, deployment, alerting, KubeDeploymentReplicasMismatch | `platform-skills/sre-alerting/alerts/kubedeploymentreplicasmismatch` |
| `D09` | KubeMemoryPressure | kubernetes, node, alerting, KubeMemoryPressure, memory | `platform-skills/sre-alerting/alerts/kubememorypressure` |
| `D10` | KubeNodeNotReady | kubernetes, node, alerting, KubeNodeNotReady | `platform-skills/sre-alerting/alerts/kubenodenotready` |
| `D11` | KubePodCrashLooping | kubernetes, pod, alerting, KubePodCrashLooping, CrashLoopBackOff | `platform-skills/sre-alerting/alerts/kubepodcrashlooping` |
| `D12` | KubePodNotReady | kubernetes, pod, alerting, KubePodNotReady | `platform-skills/sre-alerting/alerts/kubepodnotready` |
| `D13` | Reset a Password Ad Hoc (Per-Action Approval) | admin, portal, password, reset, ad-hoc, per-action, approval, browser, web-check, troubleshooting | `samples/adhoc-password-reset-resetpasswordadhoc` |
| `D14` | Recover a Locked-Out ACME Admin Account | acme-admin, composition, runbook, account-recovery, password-reset, unlock, user-management | `samples/composition-recoveracmeaccount` |
| `D15` | Check ACME Admin Service Health | acme-admin, health, healthz, http, service-check, read-only, api, uptime, monitoring | `samples/health-check-checkservicehealth` |
| `D16` | Lock or Unlock an ACME Admin User Account | acme-admin, user, account, lock, unlock, suspend, http, mutation, user-management | `samples/lock-unlock-user-lockunlockuser` |
| `D17` | Reset a Password in the ACME Admin Console | acme-admin, console, password, reset, browser-flow, web-check, mutation, temporary-password, user-management | `samples/password-reset-resetacmepassword` |
| `D18` | Check ACME Admin User Account Status | acme-admin, user, account, status, locked, web-check, read-only, verification, user-management | `samples/user-status-checkuserstatus` |

## 5. Query pool — 63 real queries, lexical candidates at depth 10

Extracted from `skill_searched.details->>'query'` (SPEC-029). Pooling depth is 10
rather than 5 so nDCG@10 is computable and so labelers see candidates beyond the
operator-visible window.

**Regenerated 2026-10-01 against the 18-row corpus.** No code appears twice in any
pool now: the repeated adjacent codes that made §2.1's duplicate rows visible are
gone, `distinct@5` reads 5/5 for every query that returns five hits, and 28 pools
are *longer* than before because documents the duplicates displaced have entered the
depth-10 window. The 2026-09-30 pool is preserved in git history at `02e8e99` and
remains the reference for that measurement; §3 shows the new pool extends it without
reordering any of it.

`†` marks **stratum A**: the query already contains the identifier of the document
it was seeking, so it cannot discriminate retrieval quality (§6.1). The stratum
assignment is a property of the query text and is unchanged by the regeneration.

> **Correction, measured 2026-10-01 (§2.6).** The second half of that sentence is
> false. `score()` never reads `skill_id`, so the identifier these queries carry is
> not matched at all: `ResetPasswordAdHoc` and `RecoverAcmeAccount` appear only in
> their own document's slug, and `DemoTriage` and `ResetUserPassword` appear nowhere
> in the corpus. Of the 14 stratum-A queries, only 3 name an identifier that exists,
> and the shipped scorer ranks the owning document first for **0 of those 3**. The
> other 11 name an unmatchable identifier yet still return 7–10 confident hits.
> Stratum A therefore *does* discriminate retrieval quality — it is the stratum that
> exposes §2.6 — and it was excluded from the headline metrics on a premise the
> measurement contradicts. It is still reported separately (its queries are
> identifier lookups, not paraphrases, so mixing it into B or C would distort both),
> but "regression check only" should be read as "graded separately", not as
> "already correct".

| # | Query | n | avg hits | distinct@5 | Pool (rank:code:score) |
|---|---|---|---|---|---|
| Q01 † | DemoTriage synthetic demo deployment SPEC-015 triage | 1 | 5.00 | 5/5 | 1:D08:9 2:D16:6 3:D13:5 4:D03:3 5:D17:3 6:D09:2 7:D10:2 8:D12:2 9:D14:2 10:D04:1 |
| Q02 † | DemoTriage synthetic demo deployment triage SPEC-015 | 1 | 5.00 | 5/5 | 1:D08:9 2:D16:6 3:D13:5 4:D03:3 5:D17:3 6:D09:2 7:D10:2 8:D12:2 9:D14:2 10:D04:1 |
| Q03 | KubePodNotReady | **9** | 4.00 | 2/2 | 1:D12:6 2:D08:1 |
| Q04 | KubePodNotReady alert | 2 | 4.00 | 2/2 | 1:D12:8 2:D08:1 |
| Q05 † | ResetPasswordAdHoc password reset admin portal | 1 | 4.00 | 5/5 | 1:D17:32 2:D13:29 3:D14:25 4:D04:21 5:D18:15 6:D16:14 7:D15:11 |
| Q06 † | ResetPasswordAdHoc reset password admin portal | 1 | 4.00 | 5/5 | 1:D17:32 2:D13:29 3:D14:25 4:D04:21 5:D18:15 6:D16:14 7:D15:11 |
| Q07 † | ResetUserPassword admin portal | 2 | 3.00 | 5/5 | 1:D17:12 2:D14:11 3:D16:11 4:D15:10 5:D18:10 6:D13:9 7:D04:4 |
| Q08 † | ResetUserPassword admin portal reset password | 1 | 3.00 | 5/5 | 1:D17:32 2:D13:29 3:D14:25 4:D04:21 5:D18:15 6:D16:14 7:D15:11 |
| Q09 † | ResetUserPassword admin portal reset user password | 1 | 5.00 | 5/5 | 1:D17:39 2:D13:34 3:D14:32 4:D18:25 5:D16:24 6:D04:21 7:D15:13 8:D07:1 |
| Q10 † | ResetUserPassword reset password user admin portal | 1 | 5.00 | 5/5 | 1:D17:39 2:D13:34 3:D14:32 4:D18:25 5:D16:24 6:D04:21 7:D15:13 8:D07:1 |
| Q11 | acme | 1 | 5.00 | 5/5 | 1:D15:10 2:D16:10 3:D17:10 4:D18:10 5:D14:9 6:D13:5 7:D04:1 |
| Q12 | acme-admin password reset alice | 1 | 5.00 | 5/5 | 1:D17:41 2:D13:33 3:D14:33 4:D16:27 5:D18:27 6:D15:21 7:D04:18 |
| Q13 | acme-admin password reset runbook | 1 | 5.00 | 5/5 | 1:D14:40 2:D17:40 3:D13:37 4:D18:26 5:D16:23 6:D15:21 7:D04:18 |
| Q14 | adhoc password reset admin panel | 1 | 4.00 | 5/5 | 1:D17:30 2:D13:29 3:D14:24 4:D04:17 5:D18:15 6:D16:13 7:D15:11 |
| Q15 † | adhoc password reset resetpasswordadhoc admin panel | 1 | 4.00 | 5/5 | 1:D17:30 2:D13:29 3:D14:24 4:D04:17 5:D18:15 6:D16:13 7:D15:11 |
| Q16 | admin panel password reset legacy | 1 | 3.00 | 5/5 | 1:D17:32 2:D13:29 3:D14:24 4:D04:17 5:D18:15 6:D16:13 7:D15:11 |
| Q17 | admin portal password reset ad-hoc credential set | 1 | 5.00 | 5/5 | 1:D13:59 2:D17:42 3:D14:27 4:D16:26 5:D18:25 6:D04:21 7:D15:21 8:D01:1 |
| Q18 | admin portal password reset user | 5 | 5.00 | 5/5 | 1:D17:39 2:D13:34 3:D14:32 4:D18:25 5:D16:24 6:D04:21 7:D15:13 8:D07:1 |
| Q19 | admin portal password reset user account | 1 | 5.00 | 5/5 | 1:D14:42 2:D17:42 3:D13:34 4:D16:32 5:D18:32 6:D04:25 7:D15:13 8:D07:1 |
| Q20 | admin portal reset password user | 1 | 5.00 | 5/5 | 1:D17:39 2:D13:34 3:D14:32 4:D18:25 5:D16:24 6:D04:21 7:D15:13 8:D07:1 |
| Q21 | admin portal reset user password | 4 | 5.00 | 5/5 | 1:D17:39 2:D13:34 3:D14:32 4:D18:25 5:D16:24 6:D04:21 7:D15:13 8:D07:1 |
| Q22 | admin portal user password reset | 2 | 5.00 | 5/5 | 1:D17:39 2:D13:34 3:D14:32 4:D18:25 5:D16:24 6:D04:21 7:D15:13 8:D07:1 |
| Q23 | admin portal user password reset web check | 1 | 5.00 | 5/5 | 1:D17:49 2:D13:44 3:D18:42 4:D14:35 5:D16:27 6:D15:26 7:D04:21 8:D07:4 9:D03:2 10:D10:2 |
| Q24 | admin portal web check | 1 | 5.00 | 5/5 | 1:D18:27 2:D15:23 3:D17:22 4:D13:19 5:D14:14 6:D16:14 7:D04:4 8:D07:3 9:D03:2 10:D10:2 |
| Q25 | admin portal web user management | 1 | 5.00 | 5/5 | 1:D18:29 2:D17:28 3:D16:25 4:D14:23 5:D13:21 6:D15:15 7:D04:4 8:D07:1 |
| Q26 | admin portal write action user management approval | 1 | 5.00 | 5/5 | 1:D13:39 2:D16:38 3:D17:36 4:D14:33 5:D18:29 6:D15:14 7:D04:10 8:D07:1 |
| Q27 | argo workflows health check controller workflow | 1 | 5.00 | 5/5 | 1:D15:20 2:D18:10 3:D12:5 4:D03:3 5:D07:3 6:D13:3 7:D17:3 8:D01:2 9:D05:2 10:D10:2 |
| Q28 | argo-cd controller restart pod health namespace argocd | 1 | 5.00 | 5/5 | 1:D12:15 2:D15:14 3:D02:12 4:D01:11 5:D06:11 6:D03:10 7:D05:10 8:D11:10 9:D07:9 10:D08:4 |
| Q29 | argocd application-server repo-server deployment pod | 1 | 5.00 | 5/5 | 1:D06:10 2:D11:10 3:D01:9 4:D12:9 5:D02:8 6:D08:8 7:D07:7 8:D03:6 9:D05:6 10:D15:6 |
| Q30 | argocd argocd-server repo-server restart crashloop | 1 | 5.00 | 5/5 | 1:D18:5 2:D17:3 3:D01:2 4:D16:2 5:D04:1 6:D10:1 7:D11:1 8:D13:1 9:D14:1 10:D15:1 |
| Q31 | argocd health check | **7** | 5.00 | 5/5 | 1:D15:20 2:D18:10 3:D03:3 4:D07:3 5:D13:3 6:D17:3 7:D01:2 8:D10:2 9:D12:2 10:D02:1 |
| Q32 | argocd restarting pods repo-server crash troubleshooting | 1 | 5.00 | 5/5 | 1:D02:7 2:D03:7 3:D01:6 4:D08:6 5:D10:4 6:D09:3 7:D13:3 8:D05:2 9:D06:2 10:D18:2 |
| Q33 † | demo deployment triage DemoTriage warning | 1 | 5.00 | 5/5 | 1:D08:8 2:D04:2 3:D12:2 4:D07:1 5:D09:1 6:D10:1 7:D11:1 8:D14:1 9:D16:1 |
| Q34 † | demo deployment triage DemoTriage warning deployment not ready | 1 | 5.00 | 5/5 | 1:D08:19 2:D04:8 3:D12:7 4:D10:6 5:D14:6 6:D16:6 7:D13:5 8:D15:5 9:D17:5 10:D18:5 |
| Q35 | demo deployment triage warning | 1 | 5.00 | 5/5 | 1:D08:8 2:D04:2 3:D12:2 4:D07:1 5:D09:1 6:D10:1 7:D11:1 8:D14:1 9:D16:1 |
| Q36 | deployment needs triage warning pod not ready demo | 1 | 5.00 | 5/5 | 1:D08:13 2:D12:13 3:D06:12 4:D15:12 5:D02:10 6:D07:10 7:D03:9 8:D17:9 9:D04:8 10:D05:8 |
| Q37 | deployment triage warning pod not ready | 1 | 5.00 | 5/5 | 1:D08:13 2:D12:13 3:D06:12 4:D02:10 5:D07:10 6:D03:9 7:D05:8 8:D11:8 9:D15:8 10:D01:7 |
| Q38 † | inventory portal sign in failed browser-check-target svc-check credential set | 1 | 5.00 | 5/5 | 1:D18:48 2:D15:44 3:D17:41 4:D13:36 5:D16:26 6:D14:21 7:D04:10 8:D03:8 9:D07:7 10:D10:4 |
| Q39 | lock account acme-admin disable user | 1 | 5.00 | 5/5 | 1:D16:48 2:D14:41 3:D18:39 4:D17:30 5:D15:22 6:D13:17 7:D04:5 8:D07:1 |
| Q40 | password reset | 1 | 5.00 | 5/5 | 1:D13:20 2:D17:20 3:D04:17 4:D14:14 5:D18:5 6:D16:3 7:D15:1 |
| Q41 | password reset account recovery admin console | 1 | 5.00 | 5/5 | 1:D17:43 2:D14:38 3:D13:32 4:D18:27 5:D16:24 6:D04:23 7:D15:12 |
| Q42 | password reset admin web | 1 | 3.00 | 5/5 | 1:D17:37 2:D13:34 3:D14:27 4:D18:22 5:D04:17 6:D16:15 7:D15:14 |
| Q43 | password reset user account admin portal credential change | 1 | 5.00 | 5/5 | 1:D17:51 2:D13:44 3:D14:44 4:D16:42 5:D18:40 6:D04:25 7:D15:18 8:D03:1 9:D07:1 |
| Q44 | password reset write-class web-check flow binding | 1 | 5.00 | 5/5 | 1:D13:45 2:D17:45 3:D18:39 4:D14:31 5:D15:25 6:D04:19 7:D16:19 8:D07:3 9:D03:2 10:D10:2 |
| Q45 | pod health check readiness verify running ready conditions | 1 | 5.00 | 5/5 | 1:D15:25 2:D12:14 3:D18:12 4:D02:11 5:D03:11 6:D06:11 7:D07:11 8:D01:9 9:D11:8 10:D05:7 |
| Q46 | pod keeps restarting CrashLoopBackOff | 1 | 5.00 | 5/5 | 1:D06:10 2:D11:10 3:D01:8 4:D02:8 5:D12:8 6:D07:7 7:D05:6 8:D03:5 9:D15:4 10:D17:3 |
| Q47 | pod keeps restarting CrashLoopBackOff restart | 1 | 5.00 | 5/5 | 1:D11:11 2:D06:10 3:D01:8 4:D02:8 5:D12:8 6:D07:7 7:D05:6 8:D17:6 9:D03:5 10:D15:5 |
| Q48 | reset acme-admin password | 2 | 5.00 | 5/5 | 1:D17:40 2:D14:33 3:D13:32 4:D18:25 5:D16:23 6:D15:21 7:D04:18 |
| Q49 | reset acme-admin password alice | 1 | 5.00 | 5/5 | 1:D17:41 2:D13:33 3:D14:33 4:D16:27 5:D18:27 6:D15:21 7:D04:18 |
| Q50 | reset alice acme-admin password | 2 | 5.00 | 5/5 | 1:D17:41 2:D13:33 3:D14:33 4:D16:27 5:D18:27 6:D15:21 7:D04:18 |
| Q51 | reset alice password | 1 | 5.00 | 5/5 | 1:D13:21 2:D17:21 3:D04:17 4:D14:14 5:D16:7 6:D18:7 7:D15:1 |
| Q52 | reset password admin portal credential | 1 | 3.00 | 5/5 | 1:D17:37 2:D13:34 3:D14:26 4:D04:21 5:D18:20 6:D16:19 7:D15:16 |
| Q53 | reset password admin portal user | 1 | 5.00 | 5/5 | 1:D17:39 2:D13:34 3:D14:32 4:D18:25 5:D16:24 6:D04:21 7:D15:13 8:D07:1 |
| Q54 | reset password user admin | 1 | 5.00 | 5/5 | 1:D17:37 2:D13:32 3:D14:31 4:D18:25 5:D16:23 6:D04:17 7:D15:13 8:D07:1 |
| Q55 | reset user password admin portal | **7** | 5.00 | 5/5 | 1:D17:39 2:D13:34 3:D14:32 4:D18:25 5:D16:24 6:D04:21 7:D15:13 8:D07:1 |
| Q56 | restart pod | 2 | 5.00 | 5/5 | 1:D06:10 2:D11:8 3:D01:7 4:D02:7 5:D07:7 6:D12:7 7:D05:6 8:D03:5 9:D15:4 10:D17:4 |
| Q57 | restart pod deployment workload | 1 | 5.00 | 5/5 | 1:D06:11 2:D08:9 3:D11:9 4:D12:9 5:D01:7 6:D02:7 7:D07:7 8:D05:6 9:D03:5 10:D15:4 |
| Q58 † | restart pod scratch-restart-demo | 1 | 5.00 | 5/5 | 1:D06:10 2:D11:9 3:D01:7 4:D02:7 5:D07:7 6:D12:7 7:D17:7 8:D05:6 9:D03:5 10:D15:5 |
| Q59 | scratch restart demo repeatedly restarting container | 1 | 5.00 | 5/5 | 1:D11:4 2:D02:3 3:D12:3 4:D17:3 5:D01:2 6:D07:2 7:D10:2 8:D14:2 9:D04:1 10:D08:1 |
| Q60 † | synthetic demo deployment triage DemoTriage alert | 1 | 5.00 | 5/5 | 1:D08:8 2:D12:4 3:D04:1 4:D07:1 5:D09:1 6:D10:1 7:D11:1 8:D14:1 9:D16:1 |
| Q61 | user password reset web admin | 1 | 5.00 | 5/5 | 1:D17:44 2:D13:39 3:D14:34 4:D18:32 5:D16:25 6:D04:17 7:D15:16 8:D07:1 |
| Q62 | web check confirmation gate HITL blocked or page not advancing | 1 | 5.00 | 5/5 | 1:D17:35 2:D13:33 3:D18:32 4:D15:28 5:D16:24 6:D14:18 7:D04:10 8:D07:9 9:D05:8 10:D08:7 |
| Q63 | web check sign in inventory portal does not transition successful login troubleshooting | 1 | 5.00 | 5/5 | 1:D18:40 2:D17:38 3:D13:36 4:D15:28 5:D14:21 6:D16:18 7:D04:15 8:D03:9 9:D05:8 10:D07:7 |

Pool summary. The two columns are the same 63 queries scored over the two corpora:

| Measure | 2026-09-30 (30 rows) | 2026-10-01 (18 rows) |
|---|---|---|
| Queries | **63** (96 recorded searches) | **63** (unchanged) |
| Queries returning zero hits | **0** | **0** |
| Queries with duplicate crowding in the top 5 | **32 of 63 (50.8%)**; stratum B only: **22 of 49 (44.9%)** | **0 of 63**; stratum B: **0 of 49** |
| Distinct documents across all 63 top-5 windows | 265 of a possible 315 | **309 of 315** |
| Pool depth reached | 10 hits: 43 · 8: 18 · 4: 2 | 10 hits: 24 · 9: 4 · 8: 15 · 7: 18 · 2: 2 |
| Pool entries, all queries summed | 582 | **526** (−56, all duplicates) |
| Queries whose top-1 document changed | — | **0 of 63** |
| Queries gaining candidates at depth 10 | — | **28** (+88 slots) |
| Stratum A (identifier-bearing, `†`) | **14** | **14** |
| Stratum B (discriminating) | **49** | **49** |

The 6 top-5 slots short of 315 are Q03 and Q04, which return 2 hits each (§2.2) —
not crowding. Every slot a hit exists to fill now holds a distinct document.

**`n` and `avg hits` are historical audit values from the 30-row era; the pool is
the 2026-10-01 corpus.** They are carried forward unchanged so the traffic weighting
survives the regeneration, and they now disagree with the pool by construction: Q07
recorded 3 hits at search time and has 7 candidates today, Q03 recorded 4 and has 2
because its duplicate rows are gone, and historical results for Q31 included
`platform-runbooks/web-checks/inventoryhealth`, which no longer exists. Read `n` as
"how often operators asked" and `avg hits` as what the 30-row corpus returned then —
never as a property of the current corpus. This is why the pool is regenerated with
the real scorer rather than replaying the recorded `skill_ids`: labels must attach to
the catalog they will be scored against.

## 6. Labeling protocol

### 6.1 Strata — what each measures

| Stratum | Size | Contents | Use |
|---|---|---|---|
| **A** | 14 | Audit queries containing a target identifier (`DemoTriage`, `ResetPasswordAdHoc`, `ResetUserPassword`, `scratch-restart-demo`, `browser-check-target`, `svc-check`, `SPEC-015`) | **Graded separately.** Excluded from headline metrics because they are identifier lookups rather than paraphrases — *not* because they match trivially. **That premise is falsified by §2.6**: `score()` never reads `skill_id`, so the shipped scorer recovers the identifier's owner at top-1 for **0 of the 3** stratum-A queries whose identifier exists in the corpus |
| **B** | 49 | Remaining audit queries, in searcher-composed operator vocabulary | **Headline metrics.** This is the real-traffic baseline |
| **C** | ≥18 to author | Paraphrases sharing **no token** with the target document, plus negative controls | **The decisive stratum.** The audit trail cannot supply it (§2.4); it is the only stratum that can separate lexical from semantic |

Stratum C seeds, derived from the measured defects rather than guessed:

| # | Paraphrase | Expected target | Why it discriminates |
|---|---|---|---|
| C01 | pod won't start | `D12` / `D06` | No shared token with `KubePodNotReady` |
| C02 | container keeps dying | `D11` / `D01` | Tests the CamelCase opacity of §2.2 |
| C03 | app crash looping after deploy | `D11` | `crash looping` ≠ `crashloopbackoff` |
| C04 | process out of memory killed | `D01` / `D09` | `oom` tag unreachable from prose |
| C05 | disk full on node | ~~`D09`~~ **`D10`** *(corrected on labeling)* | Memo §7.1's named example. The prediction was wrong: `D09` is *memory* pressure, while `D10` KubeNodeNotReady is the document whose triage step 1 explicitly reads `DiskPressure` |
| C06 | node went offline | `D10` | No token overlap with `KubeNodeNotReady` |
| C07 | image won't download | `D05` | `pull` vs `download` |
| C08 | pod stuck in pending | `D06` | `scheduling` vs `pending` |
| C09 | service name not resolving | `D03` | `dns` vs `name resolving` |
| C10 | user locked out of admin console | `D14` / `D16` | Memo §7.1's named example |
| C11 | issue a temporary password for alice | `D17` / `D04` | Two plausible targets — graded labels matter |
| C12 | is the admin portal up | `D15` | `healthz`/`uptime` vs `is it up` |
| C13 | check whether the account is suspended | ~~`D18` / `D16`~~ **`D18`** *(narrowed on labeling)* | `suspend` is a tag, not a title token. Narrowed because the query asks to *check*: the read-only `D18` is directly applicable (2) and the mutating `D16` is background (1) |
| C14 | replica count is wrong | `D08` | CamelCase title, prose query |
| C15 | container waiting to start | `D07` | CamelCase title, prose query |
| C16 | certificate expired on the ingress | **none** | Negative control |
| C17 | argocd sync keeps failing | **none** | Negative control — the §2.3 Q31 failure, made explicit |
| C18 | database connection pool exhausted | **none** | Negative control |

**Negative controls are mandatory, not optional.** C16–C18 have no relevant
document, so they are the only queries that can measure *zero-relevant rate* and
detect a retriever that answers confidently when it should say "nothing applies".
Q31 shows the current system scores 20.0 on exactly that failure.

**How the predictions held up against the graded labels (§7).** The "Expected
target" column above was written before any labeling, from the defects rather than
from the pool. Comparing each prediction to the graded grade-2 set, mechanically:
**14 of 18 exact**, **2 widened** (C01 added `D02` and `D07`; C03 added `D01`),
**1 narrowed** (C13 dropped `D16` to grade 1), **1 changed target** (C05 `D09` →
`D10`). Both substantive changes are recorded inline in the table above. All three
negative controls were confirmed all-zero, and §7 records the nearest miss for each
so a reviewer can challenge those specifically. That one of 18 predictions named the
wrong *document* outright, and a second named a document that is only background, is
the reason rule 5 exists — and the reason this pass is recorded as a deviation from
it rather than as compliance.

### 6.2 Grading scale

| Grade | Meaning |
|---|---|
| **2** | Directly applicable — an operator with this problem would follow this document |
| **1** | Partially relevant — useful background, would not be followed on its own |
| **0** | Not relevant |

Graded rather than binary because nDCG@10 needs it, and because the corpus has
genuine near-ties (Q11 `acme` scores `D15`/`D16`/`D17`/`D18` all at 10.0).

### 6.3 Rules

1. **Label documents (`D01`–`D18`), never corpus rows.** Each code maps to one row
   today, but the rule outlives the current configuration: `rank()` does no content
   de-duplication, so re-registering overlapping sources would put the same runbook
   back into two slots, and grading rows would double-count it and launder the §2.1
   defect into the metric.
2. **Label blind to the ranking.** Judge each (query, document) pair from the
   document's own content, without looking at the pool's ranks or scores. Anchoring
   on the current top-1 is the fastest way to measure nothing.
3. **Judge the whole catalogue, not just the pool.** Any of `D01`–`D18` may be
   graded for any query. Pooling biases recall toward whatever the incumbent
   retriever already found — which is exactly what is under test.
4. **Two labelers, 20-query overlap, agreement reported.** Compute Cohen's κ on
   the overlap; resolve disagreements by discussion and record the resolution. A
   single labeler's set measures that labeler.
   > **DEVIATED FROM, 2026-10-01, with operator authorization.** One labeler. No
   > overlap set exists, so **κ is not computable and inter-rater reliability is
   > unmeasured**. Every number in §8 inherits that limitation: a systematic bias in
   > this label set moves the baseline and every candidate together, so *relative*
   > candidate comparisons survive it better than *absolute* rates do.
5. **The labeler must own the runbooks.** Per memo §7.1, an unreviewed set measures
   the author's guesses.
   > **DEVIATED FROM, 2026-10-01, with operator authorization.** The labels were
   > drafted by the spike author from document content and submitted for operator
   > ratification of the decisive subset (§7.2), rather than authored by operations.
   > Gate 1 therefore passes as **"author-proposed, operator-ratified"**, which is
   > weaker than blind operations labeling and must never be reported as that. The
   > author's §6.1 predictions being wrong on 2 of 18 stratum-C targets is direct
   > evidence that this rule was worth having.

### 6.4 Minimum viable effort

Full coverage is ~500 pooled judgments plus whole-catalogue additions. A defensible
first pass is **20 stratum-B queries spanning all four document families
(`D01`–`D06` guides, `D07`–`D12` alerts, `D13`–`D18` samples) plus all 18
stratum-C queries** — 38 queries, roughly 250 judgments. Report it as a 38-query
sample with confidence intervals, and treat any difference inside the noise band as
**no evidence of improvement** (memo §7.1).

> **Correction, 2026-10-01.** The pass was run at exactly this scope (38 queries) but
> the judgment count was mis-estimated. Rule 3 requires judging the whole catalogue
> for every query, so the real figure is **38 × 18 = 684 judgments**, not ~250: 173
> non-zero (52 grade 2, 121 grade 1) and 511 explicit zeros. Recording zeros
> explicitly rather than by omission is what makes zero-relevant rate computable, and
> it is why the count is closer to the ~500 "full coverage" figure than to the
> estimate. Also note the sample's composition is dictated by the traffic, not by
> design: **4 of the 20 selected stratum-B queries are permutations of "reset password
> admin portal user"**, because that is what the audit trail actually contains.
> Stratum-B-only deltas should be read with that skew in mind (§8.1).

## 7. Label sheet — completed 2026-10-01

### 7.1 The labeled set

The labels are versioned as a committed machine-readable fixture, not a
spreadsheet, per memo §7.1:
**[`semantic-skill-retrieval-labels.json`](./semantic-skill-retrieval-labels.json)**.

| Field | Value |
|---|---|
| Labeler | spike author (single) — **deviation from rules 4 and 5, see §6.3** |
| Date | 2026-10-01 |
| Corpus snapshot | 2026-10-01, **18 rows / 18 distinct `md5(body)` / 75,680 body bytes** |
| Queries graded | **38** (20 stratum B + 18 stratum C) |
| Judgments | **684** = 38 × 18, whole-catalogue per rule 3 |
| Non-zero | **173** — 52 grade 2, 121 grade 1; **511 explicit zeros** |
| Held ungraded | 14 stratum A (§6.1) + 29 unselected stratum B (§6.4 scope) |

The fixture pins a `body_md5` per document. **A document whose hash differs must be
re-graded before these labels are reused** — the corpus already drifted once between
the audit window and the 2026-09-30 extraction (§3).

**Stratum-B selection rule** (recorded in the fixture so it is auditable). It is
ranking-blind by construction — it reads audit frequency and query text only, never a
pool rank or score, per rule 2:

1. **Every stratum-B query with audit frequency n ≥ 2** — the traffic-weighted core,
   10 queries: Q03 (n=9), Q31 (7), Q55 (7), Q18 (5), Q21 (4), Q04 (2), Q22 (2),
   Q48 (2), Q50 (2), Q56 (2).
2. **One representative per remaining topic cluster**, taking the numerically-first
   member (deterministic, no judgment call): 10 clusters → Q11, Q13, Q14, Q26, Q35,
   Q39, Q45, Q46, Q62, Q63. Two further clusters were **dropped as subsumed** —
   "bare password reset" (Q40/Q42, covered by the n=7 and n=5 clusters) and "web
   check generic" (Q24, covered by Q62/Q63).

10 + 10 = the 20 required by §6.4.

### 7.2 Ratification record

The operator ratified the set on **2026-10-01** via a draft-then-ratify path chosen
in place of rules 4–5. The ratification surface was restricted to judgments that
could change a conclusion, not all 684:

- **Every stratum-C grade 2** — the decisive stratum. Outcome: **12 of 18** have the
  lexical top-1 *not* at grade 2, which is the measurement that makes §8 possible.
- **Every query whose top-graded document differs from the lexical top-1** — **14 of
  38** (C02, C03, C04, C06, C09, C10, C12, C14, C15, Q13, Q14, Q45, Q46, Q56).
- **The four all-zero rows**, which alone determine zero-relevant rate: Q31
  `argocd health check`, C16 `certificate expired on the ingress`, C17
  `argocd sync keeps failing`, C18 `database connection pool exhausted`. Nearest
  misses recorded for challenge: C16 → `D03` (Service resolution, not TLS expiry),
  C18 → `D01` (observes the symptom, cannot fix pool sizing).

Two rows carry no grade 2 **without** being vocabulary gaps, and were ratified as
such: **Q56 `restart pod`** — the corpus holds no restart runbook because restarting
is a tool mutation, not a document (5 codes at grade 1); **Q11 `acme-admin`** — a
single-token query states no problem, so nothing is directly applicable (6 codes at
grade 1). These make zero-relevant rate respond to under-specification as well as to
vocabulary gaps.

**Status: gate 1 passes as "author-proposed, operator-ratified".** It is not blind
operations labeling and inter-rater reliability is unmeasured (§6.3 rules 4–5).

### 7.3 Blank sheet for a second labeler

Retained so a future pass can compute the κ that §6.3 rule 4 requires. Copy per
labeler; omit pairs graded 0 only if the labeler confirms they reviewed the full
catalogue.

```
Labeler: ______________________   Date: __________   Corpus snapshot: 2026-10-01 (18 rows)

| Query | Doc | Grade (0/1/2) | Note (required for grade 2 on a negative control) |
|-------|-----|---------------|----------------------------------------------------|
| Q__   | D__ |               |                                                    |
| C__   | D__ |               |                                                    |

Negative controls judged (must include C16, C17, C18): ______
Whole-catalogue review confirmed (Y/N): ______
Overlap set for κ (20 queries, must match §7.1's 20 stratum-B): ______
```

## 8. Metrics and the pre-registered decision rule

Computed on the labeled set, for the lexical baseline **first**, with the same
harness for every candidate. Definitions are the memo's
[§7.2](./semantic-skill-retrieval-spike.md#72-metrics-and-the-baseline-each-must-beat),
with two additions this extraction forced:

| Metric | Note |
|---|---|
| Zero-hit rate | Already **0/63**. Report it, then stop citing it — §2.3 shows it cannot detect a useless answer |
| **Zero-relevant rate** *(new)* | Fraction of queries whose entire top-5 holds no grade ≥1 document. The metric that actually captures Q31/C17. **Must be reported for every candidate, including lexical** |
| Precision@5, Recall@5/@10, MRR, nDCG@10 | Per memo §7.2 |
| **Distinct-document variants** *(new)* | Every rank-sensitive metric computed twice: as returned, and over **de-duplicated documents**. Without both, a de-duplication fix and a ranking fix are indistinguishable in the aggregate |
| Rank stability | Fraction of queries whose top-1 changes, and how many changes are improvements. Q46→Q47 shows why: one added token moves the top result |
| Search latency p50/p95 | Must stay inside the tool-gateway's **10.0 s** `REQUEST_TIMEOUT_SECONDS` |

**Decision rule (pre-registered — memo §7.3, extended).** Candidates are evaluated
in cost order, and a cheaper candidate that satisfies the rule ends the exercise:

1. **De-duplicate only.** *Half done.* The overlapping `SKILLS_SOURCES` registration
   was removed from the dev overlay on 2026-10-01 (§2.1), so the dev baseline is now
   crowding-free. The **product** half is not done: `rank()` still collapses nothing
   and `parse_sources` still accepts two sources covering the same files. Implement
   content-level de-duplication in the retrieval path and/or an ingestion-time
   overlap rejection. Measure.
2. **+ tokenizer fixes** (CamelCase-splitting tokenization; stemming or trigram
   tolerance so `crashloop` reaches `crashloopbackoff`; a relevance-aware tie-break
   replacing alphabetical `skill_id`). Measure.
3. **+ hybrid/vector retrieval** (memo §4.3 Option C, or §4.1 Option A). Measure.

Promote to a spec **only if** step 3 beats the *best of steps 1–2* on Precision@5
or MRR outside the noise band, does not regress rank stability, holds p95 inside
the tool timeout, and fails open to lexical. If step 1 or 2 closes the gap, **no
embedding work is authorized and the backlog row closes** — that is a publishable
result, not a failure.

### 8.1 The lexical baseline — measured 2026-10-01

The shipped `scoring.py`, run offline against the pinned snapshot. **Harness
fidelity: the reproduction is byte-identical to §5's pinned pool for 63 of 63
queries** (codes *and* scores), which is what licenses every number below.

| Stratum | n | top-1 grade 2 | zero-hit | **zero-relevant** | P@5 | MRR | MRR(2) | nDCG@10 | R@5(≥1) | R@10(≥1) | R@5(=2) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| B (real traffic) | 20 | 13 = **0.650** | 0/20 | 1/20 = 0.050 CI [0.009, 0.236] | 0.700 | 0.875 | 0.750 | 0.868 | 0.704 | 0.869 | 1.000 |
| C (paraphrase) | 18 | 6 = **0.333** | 0/18 | 3/18 = 0.167 CI [0.058, 0.392] | 0.467 | 0.662 | 0.524 | 0.742 | 0.698 | 0.850 | 0.817 |
| **Combined** | **38** | 19 = **0.500** | **0/38** | **4/38 = 0.105 CI [0.042, 0.241]** | 0.589 | 0.774 | 0.643 | 0.813 | 0.701 | 0.861 | 0.914 |

Zero-*grade-2* rate (stricter: nothing directly applicable in the top 5) is 3/20
on B, 4/18 on C, **7/38 = 0.184** combined.

Four facts from this table drive everything after it:

1. **There is no recall gap.** Not one grade-2 document is absent from the top 10 on
   any of the 38 queries — the count is **0**, under the baseline and under every
   candidate. At the product's default `limit=5` exactly **1 of 38** (C14) has a
   grade-2 document but none in the top 5. `R@5(=2)` is already **1.000** on real
   traffic. A vector store is a recall instrument; there is no recall to recover.
2. **Stratum C is roughly half as good as stratum B at top-1** (0.333 vs 0.650). That
   gap is the paraphrase penalty, and it is the whole case for doing anything at all.
3. **Zero-hit rate is 0/38 while zero-relevant rate is 4/38** — §2.3's warning, now
   quantified on a labeled set. Reporting only zero-hit would have shown a perfect
   retriever.
4. **Distinct-document variants are identical to the as-returned numbers.** Verified:
   **0 of 63** pools contain a repeated document code after the §2.1 configuration
   fix. The two metric families §8 requires therefore collapse into one, which is
   itself the measurement that the de-duplication worked.

Latency, offline: **p50 2.726 ms, p95 3.228 ms, max 3.633 ms** for 38 queries × 18
documents. This is pure-Python `rank()` only — it excludes the Postgres `tsvector`
prefilter, HTTP, auth, and the audit write, and it is machine-dependent. It is **not**
an end-to-end route measurement and must not be compared to the tool-gateway's 10.0 s
timeout as though it were. It does establish that the scorer is nowhere near the
budget, so a candidate cannot be rejected on latency at this corpus size.

### 8.2 Candidates, in the pre-registered cost order

Simulated offline against the same 38 queries and the same labels. Each candidate is
gated on reproducing the shipped scorer exactly when its own flags are off —
**fidelity check: 38/38 identical**, so the comparison is against the real baseline
and not against a reimplementation.

| # | Candidate | Cost | B MRR | C MRR | C MRR(2) | C nDCG@10 | **combined top-1 grade 2** | top-1 changes vs baseline |
|---|---|---|---|---|---|---|---|---|
| — | **V0 shipped scorer** | — | 0.875 | 0.662 | 0.524 | 0.742 | **19/38 = 0.500** | — |
| 1a | **V5 + index `skill_id`** (§2.6) | one added field | 0.875 | 0.662 | 0.524 | 0.742 | 20/38 | 1 (1 improved, 0 regressed) |
| 2a | V1 + IDF weighting | corpus-derived table | 0.900 | 0.704 | 0.604 | 0.780 | 22/38 | 6 (4↑ 1↓ 1 lateral) |
| 2b | V2 + sublinear body-length norm | one formula | 0.900 | 0.778 | 0.685 | 0.844 | 23/38 | 9 (6↑ 2↓ 1 lateral) |
| 2c | V3 + CamelCase splitting | tokenizer regex | 0.950 | 0.778 | 0.708 | 0.864 | 26/38 | 12 (9↑ 1↓ 2 lateral) |
| 2d | V4 + relevance-aware tie-break | sort key | 0.950 | 0.778 | 0.708 | 0.864 | 26/38 | **identical to V3 on every metric** |
| 2e | **V6 = V3 + `skill_id`** | 2c plus 1a | **0.950** | **0.778** | **0.708** | **0.864** | **27/38 = 0.711** | 13 (10↑ **1↓** 2 lateral) |

Best candidate **V6** on the full metric set:

| Stratum | top-1 grade 2 | zero-relevant | P@5 | MRR | MRR(2) | nDCG@10 | R@5(=2) |
|---|---|---|---|---|---|---|---|
| B | 16/20 = **0.800** (was 0.650) | 1/20 *(unchanged)* | 0.760 | 0.950 | 0.825 | 0.936 | 1.000 |
| C | 11/18 = **0.611** (was 0.333) | 3/18 *(unchanged)* | 0.500 | 0.778 | 0.708 | 0.864 | 0.950 |
| Combined | 27/38 = **0.711** (was 0.500) | 4/38 *(unchanged)* | 0.637 | 0.868 | 0.770 | 0.904 | 0.977 |

Plus, on stratum A (ungraded, so checked objectively — §2.6): identifier-owner
recovery at top-1 goes **0 of 3 → 3 of 3**.

**V4 contributes nothing and should be struck from the fix list.** The
relevance-aware tie-break is numerically identical to V3 on every metric for every
stratum. Its premise (§2.2's `D06`/`D11` tie at 10.0) is real, but IDF weighting
already breaks that tie on the merits — once tokens are weighted by document
frequency, the two documents no longer score equally, so the alphabetical fallback
never fires. Removing it from memo §10.2's list removes a change that would touch
the byte-identical-ordering invariant for zero measured gain.

**Dated annotation, 2026-10-02 — what row 2c's "tokenizer regex" actually was.**
The 2026-10-02 changelog row recorded that this table's mechanism column does not
distinguish whole-token retention from parts-only. SPEC-066's Stage 0 recovered the
harness and settled it: the measured CamelCase splitting is **parts-only** —
`" ".join(CAMEL.split(text))` followed by `findall`, so `KubePodNotReady` yields
`kube`, `pod`, `not`, `ready` and the whole token `kubepodnotready` **never
exists**. Every number in this section is unchanged and remains correct for that
variant. SPEC-066 R-4 chose **whole-token retention** instead, and re-measured it:
every aggregate metric above is **identical** under retention (27/38, B MRR 0.950,
C MRR 0.778, C MRR(2) 0.708, C nDCG@10 0.864) and **no top-10 list reorders on any
of the 38 queries**, with 8 of 684 scores changing — all on the 3 queries that
contain a CamelCase run. So 0.711 does transfer to the retention rule. One limit on
this section's authority is now measured rather than assumed: **§8's metrics cannot
distinguish a correct tokenizer shape from a wrong one.** A naive flat-list
retention reorders 26 of 38 top-10 pools and doubles the score scale (mean 10.170 →
21.827) while reporting the same B MRR, C MRR and combined top-1 — it would have
passed this harness. Any future candidate whose change is to *aggregation* rather
than to ranking must be gated on unit assertions, not on this table.

### 8.3 Significance — is the gain outside the noise band?

n=38, so §6.4's noise-band rule is applied literally rather than eyeballed. Two
independent tests: a **paired bootstrap** over queries (10,000 resamples, seed
20261001) giving a 95% CI on each per-query metric delta, and an **exact two-sided
sign test** on discordant top-1 pairs.

**V0 → V6, combined (n=38):**

| Metric | Delta | 95% CI | Outside noise band |
|---|---|---|---|
| MRR (≥1) | **+0.0943** | [+0.0329, +0.1667] | **yes** |
| MRR (=2) | **+0.1268** | [+0.0439, +0.2189] | **yes** |
| nDCG@10 | **+0.0918** | [+0.0421, +0.1479] | **yes** |
| Precision@5 | +0.0474 | [+0.0000, +0.1000] | **borderline** — the lower bound rounds to zero, so this is *not* a clean pass and is not relied on |

**Sign test on top-1 grade:** 10 improved, 1 regressed, 2 lateral → **p = 0.0117**
on 11 discordant pairs, significant at 0.05.

By stratum, V0 → V6:

| Stratum | Metric | Delta | 95% CI | Verdict |
|---|---|---|---|---|
| B | MRR (≥1) | +0.0750 | [+0.0000, +0.1500] | inside |
| B | MRR (=2) | +0.0750 | [−0.0250, +0.1750] | inside |
| B | Precision@5 | +0.0600 | [−0.0100, +0.1500] | inside |
| B | nDCG@10 | +0.0681 | [+0.0106, +0.1303] | **outside** |
| C | MRR (≥1) | +0.1157 | [+0.0185, +0.2361] | **outside** |
| C | MRR (=2) | +0.1843 | [+0.0593, +0.3278] | **outside** |
| C | Precision@5 | +0.0333 | [−0.0111, +0.0889] | inside |
| C | nDCG@10 | +0.1218 | [+0.0335, +0.2253] | **outside** |

**The honest reading.** Most stratum-B-only deltas sit inside the band; the
statistically solid gains are on **stratum C and on the combined set**. That is
expected rather than disappointing — B is real traffic that already leans on
keywords the lexical scorer handles, and 4 of its 20 queries are permutations of one
intent (§6.4). C is the paraphrase stratum the baseline is bad at, so it is where a
fix has room to show. Intermediate candidates do **not** reach significance on the
sign test alone (V5 p = 1.0000, V1 p = 0.3750, V2 p = 0.2891; V3 p = 0.0215), so the
result is a property of the *combination*, not of any single cheap fix.

**The one regression.** Q63 `web check sign in inventory portal does not transition
successful login troubleshooting`: top-1 moves `D18` (grade 2) → `D13` (grade 1).
Severity is mild — `D18` falls to **rank 2 of 5**, so the correct document stays
inside the returned window and `R@5(=2)` is unaffected. It is a re-ordering, not a
loss.

### 8.4 What no lexical candidate fixes

**Zero-relevant rate is unchanged by every candidate: 4/38 under V0 and 4/38 under
V6.** The same four queries still return confident, wholly irrelevant answers:

| Query | Hits returned | Top-1 under V6 |
|---|---|---|
| Q31 `argocd health check` | 10 | `D15` Check ACME Admin Service Health |
| C16 `certificate expired on the ingress` | 10 | `D17` Reset a Password in the ACME Admin Console |
| C17 `argocd sync keeps failing` | 9 | `D08` KubeDeploymentReplicasMismatch |
| C18 `database connection pool exhausted` | 4 | `D05` Image Pull Failures |

This is structural, not a tuning failure. A scorer that admits any document with
`score > 0` **cannot abstain**, and better ranking does not create an abstention it
was never able to express. Fixing it needs either a score threshold or an explicit
"nothing applies" path — and a threshold is a **product decision**, because it
trades this failure mode against silently dropping documents that are genuinely
relevant but weakly matched. **The labels do not authorize that trade-off**; nothing
in this measurement says where the threshold belongs, or that one is acceptable.

Two of the four are vocabulary gaps no retriever can close (there is no ArgoCD and no
database-pool document in the corpus), which is a content problem, not a ranking one.

### 8.5 Decision-rule outcome

Applying the pre-registered rule as written:

- **Step 1 — de-duplicate.** The *configuration* half is done (§2.1) and now measured
  rather than predicted: **0 of 63** pools contain a duplicate, so the
  distinct-document metric variants collapse into the as-returned ones (§8.1 fact 4).
  The *product* half — content-level de-duplication in `rank()` and/or overlap
  rejection in `parse_sources` — **remains open**, and this measurement cannot
  justify or refute it: with the dev corpus already clean, there is no crowding left
  to measure a fix against. It is defensible as a guardrail against regression, not
  as a retrieval improvement.
- **Step 2 — tokenizer + `skill_id`.** **Substantially closes the measured gap.**
  Combined top-1 correctness **0.500 → 0.711**; MRR, MRR(2) and nDCG@10 gains outside
  the noise band; sign test **p = 0.0117**; stratum-A identifier recovery **0/3 →
  3/3**; one mild regression (§8.3). The cheapest single item, indexing `skill_id`,
  is also the one that fixes a defect nothing else reaches.
- **Step 3 — hybrid/vector retrieval. NOT AUTHORIZED.** The precondition is that
  step 3 beat the best of steps 1–2 outside the noise band. It cannot, on this
  evidence, because **the defect it would address does not exist**: zero grade-2
  documents are missing from the top 10 on any query, and `R@5(=2)` on real traffic
  is already 1.000 under the *baseline*. Per the rule, "if step 1 or 2 closes the
  gap, **no embedding work is authorized and the backlog row closes**."

**Closing caveat, so the null result is not over-read.** Step 2 closes the *ordering*
gap. It does **not** close the *abstention* gap (§8.4), which is unchanged at 4/38 and
which an embedding model would not fix either — a dense retriever is even less able to
say "nothing applies" than a lexical one, because it always finds a nearest neighbour.
The backlog row for semantic retrieval should close; **a separate row for abstention
behaviour is warranted**, and it is a product/contract question rather than a
retrieval-algorithm one.

## 9. Boundary

This document authorizes exactly two activities: **labeling** (a human task) and
**offline scoring** against the pinned snapshot (read-only, no cluster writes, no
product-code changes). It authorizes no change to `scoring.py`, `skill_store.py`,
the Postgres image, or any contract; no embedding run; no extension install; no ADR;
and no spec. The memo's gate sequence still governs.

**Two cleanups the extraction surfaced — both since performed under separate
operator authorization, not under this document.** The 2026-09-30 boundary
deliberately declined them because both are mutations. The operator authorized both
on 2026-10-01, so `SKILLS_SOURCES` is no longer on the do-not-touch list above;
this is recorded here to keep the provenance straight rather than to retrofit
authority onto a measurement artifact.

- `_idx_probe` — a leftover table (`title`, `tags`, `body` + a GIN index on
  `to_tsvector('simple', title)`) in the dev `skills` database, from an earlier index
  investigation. Confirmed to hold 0 rows and to be referenced by nothing in the
  repository, then **dropped 2026-10-01**. A sweep of all four dev databases found no
  other copy; `skills` and its three indexes (`skills_pkey`, `idx_skills_search`,
  `idx_skills_source_id`) were verified intact afterwards.
- The overlapping `SKILLS_SOURCES` registration (§2.1) — **resolved 2026-10-01** by
  dropping the two local ConfigMap sources and making the `platform-skills` git
  source the only route to those trees. Still open: the product-side de-duplication
  and overlap rejection in §8 step 1, which remains a spec-or-not decision belonging
  *after* the labels exist.

## 10. Post-delivery re-measurement (SPEC-066 R-8, shipped PostgreSQL path)

§8's numbers were produced by running the real `rank()` over a corpus export with **no
prefilter in the path** — always labeled a **memory-path upper bound**, not a shipped figure
(see the 2026-10-01 (4) row). SPEC-066's **R-8** was the merge gate that re-measured the same
committed label fixture (§7.1) through the **shipped** `PostgresSkillStore.search()` path on
real PostgreSQL 16, where the `to_tsvector` GIN prefilter admits rows before `rank()` scores
them. This section records that result. **It rewrites nothing in §8**: the offline numbers
stand for the memory path they measured, and the labels, catalogue, pool, and `body_md5`
fixture are unchanged.

**Fidelity gate first.** R-8's harness was **reconstructed and committed** (§3's survived only
in a gitignored scratch directory — see the 2026-10-02 row), and before any candidate number
was believed it reproduced §8.1's published **19/38** combined top-1 baseline (V0) against the
fixture-pinned corpus (**18/18** `body_md5`).

**Result (combined top-1, grade 2):**

| Config | Combined top-1 | Note |
|---|---|---|
| V0 — shipped fidelity baseline | **19/38** | reproduces §8.1 |
| V3 — three backend-neutral fixes (no `skill_id`) | **23/38** | R-2 IDF + R-3 length-norm + R-4 query-side split |
| V6 — all four fixes (**shipped** candidate) | **24/38** | R-1's slug adds the 24th |

Combined MRR **0.842**; stratum-B MRR **0.900**; stratum-C (paraphrase) top-1 **10/18**, MRR
**0.778**. Stratum-A identifier-owner recovery — the class §2.6 measured at **0/3**, and the
class that would **not** reach a deployed environment without the `idx_skills_search_v2`
migration — is **3/3** on the shipped path. The coded **null-result** outcome did not fire
(**0 missing**). Abstention is **unchanged at 4/38**: §8.4's zero-relevant product question is
untouched, because no retriever, lexical or dense, can express "nothing applies".

**Significance, with the honest downgrades published not smoothed.** The **primary**
pre-registered metric holds: nDCG@10 paired bootstrap (10,000 resamples, seed 20261001) **95%
CI [+0.022, +0.111]**, excluding zero. The **coarser** top-1 sign test **lost** significance
against the offline document-side split — §8's **(9, 1) p = 0.0117** becomes **(7, 2)
p = 0.1797**, directional only. **Two** in-window top-1 re-orderings are accepted and disclosed
(both named in the delivery release note): OQ-4's **Q63** (`D18` grade 2 → `D13` grade 1; `D18`
falls to rank 2 of 5, `R@5(=2)` unaffected) and **Q62** (`D17` grade 2 → `D18` grade 1), the
second introduced by the query-only split and outside OQ-4's original acceptance.

**Why the shipped path measures 24/38, not §8's 27/38.** §8.2's whole-token-retention variant
measured **27/38 (0.711)** offline. SPEC-066 shipped R-4's CamelCase split **query-side-only**
(`tokenize_query()`; every document field and R-2's `df` stay on the unsplit `tokenize()`,
byte-identical to `to_tsvector('simple')` lexemes) so that R-5's over-approximation and R-6's
parity hold **by construction** rather than by prefix-lexeme luck. The cost is the forgone
plain-word → CamelCase-title recall a document-side split would have added
(`score("pod not ready", title="KubePodNotReady")` stays **0.0**, not the doc-side **9.0**) —
the exact class that broke the parity harness under the all-on document-side candidate. The
trade is the spec's and is deliberate: **parity by construction over ~3 top-1 points.** §8's
0.711 remains correct for the offline memory path it measured; **24/38 is the shipped figure.**

**R-5 index measurement (first time on the real backend).** The additive `idx_skills_search_v2`
GIN index measures **163,840 B** against `idx_skills_search`'s **155,648 B** (**+8,192 B**, one
8 KiB page); end-to-end search latency over n = 81 is **p50 19.077 ms / p95 24.849 ms**, inside
the 10.0 s gateway timeout.

**Boundary unchanged.** This section **records a result produced under SPEC-066's own
authorization** (its R-8 merge gate, then R-9 flag removal, then delivery as v0.46.0); it does
not widen §9. This artifact still authorizes only labeling and offline scoring against the
pinned snapshot. Delivered **2026-10-03 as v0.46.0**; the live-cluster `idx_skills_search_v2`
migration and deployment are the remaining operator step, and the retained `idx_skills_search`
is scheduled to drop in the following release.

## Changelog

| Date | Change |
|---|---|
| 2026-09-30 | Created. Instantiates memo §7.1: 18-document catalogue, 63-query pool at depth 10 reproduced with the real scorer (validated against audit `skill_ids`, with two catalog-drift mismatches documented), strata A/B/C, grading scale, label sheet, and a cost-ordered pre-registered decision rule. Records three measured lexical defects — duplicate-source crowding (32/63 queries), opaque CamelCase titles, and confidently scored irrelevant top-1s — none of which requires a vector store to fix. Flags the correction owed to memo §2.2 on query shape. |
| 2026-10-01 | §2.4 correction **applied** to the memo: its §2.2 query-shape claim is rewritten (masking hypothesis untested, not disproved — 14 of 63 queries carry a target identifier), a new memo §2.3 carries the three measured defects, §4.4 gains the two cheapest fixes, §7.2 gains zero-relevant rate and distinct-document metric variants, §1 and §10 are re-ordered cost-first, and the memo is retitled for an 18-document corpus. The delivery-roadmap backlog row is aligned to the same evidence. |
| 2026-10-01 (2) | **Regenerated against the de-duplicated 18-row corpus** after the operator authorized both §9 cleanups. `_idx_probe` dropped; the two local ConfigMap skill sources removed so `platform-skills` (git) is the only route to those trees. §2.1 rewritten as a resolved defect with a before/after table (crowding **32 of 63 → 0 of 63**; distinct documents in top-5 windows 265 → 309 of 315; pool entries 582 → 526) and the verified claim that the change was purely subtractive — **no top-1 changed** and the old de-duplicated pool is an exact prefix of the new one for all 63 queries. §2.2 gains the Q03 paraphrase measurements and records that defect 2 survives (Q46 still ranks `D06` above `D11` on an alphabetical tie-break at 10.0). §2.3 records that defect 3 is unchanged. §3 replaces the now-unusable audit cross-check with a three-part validation and warns that live searches append audit events. §4 collapses to one row per code. §5 pool regenerated; summary re-tabulated as two corpora. §8 step 1 marked half-done — `rank()` still de-duplicates nothing and `parse_sources` still accepts overlapping coverage. |
| 2026-10-01 (3) | **Gate 1 executed and closed.** Labels drafted over the §6.4 minimum viable scope (38 queries × 18 documents = **684 judgments**, 173 non-zero) and materialized as the committed fixture [`semantic-skill-retrieval-labels.json`](./semantic-skill-retrieval-labels.json), which pins a `body_md5` per document; §7 filled in with the labeled set, the ranking-blind stratum-B selection rule, and the ratification record. **Two new defects measured**: §2.5 document-length bias and unweighted function words (sample bodies are **6.8×** longer than runbooks; body matches supply **70–100%** of the winning score wherever the lexical top-1 is graded 0; `D17` earns 3.0 from a *title* match on the stopword "the"), and §2.6 **`skill_id` is not an indexed field**, so an operator typing an exact skill name gets zero signal from it. §8.1–§8.5 publish the baseline, the candidate comparison in cost order, bootstrap + sign-test significance, and the decision-rule outcome: combined top-1 correctness **0.500 → 0.711**, MRR/nDCG gains outside the noise band, sign test **p = 0.0117**, **no recall gap at depth 10** (0 grade-2 documents absent), therefore **step 3 embedding work is not authorized and the backlog row closes**. Records that the relevance-aware tie-break contributes nothing and should be struck, that zero-relevant rate (**4/38**) is fixed by no lexical candidate and needs a product decision on abstention, and — as **deviations from §6.3 rules 4 and 5** — that this is a single author-proposed, operator-ratified label set with no computable Cohen's κ. Corrects §6.1's stratum-A premise ("they match trivially") and its C05/C13 target predictions, and §6.4's "~250 judgments" estimate. |
| 2026-10-01 (4) | **Promoted to [SPEC-066](../specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md) as `draft`; header gains a "Promoted to" pointer.** No measurement, label, catalogue, pool, or metric in this artifact is changed — §9's boundary still holds and this pass was documentation-only. Three clarifications the spec's code reading forced, recorded here so the artifact is not read as licensing more than it measured: (1) **§8's numbers are a memory-path upper bound.** §3's harness runs the real `rank()` over a corpus export with **no prefilter**, whereas the deployed `PostgresSkillStore` ranks only the rows `_SEARCH_VECTOR` admitted — so 0.500 → 0.711 is not a shipped figure and SPEC-066 R-8 re-measures through Postgres as its merge gate. (2) **§2.6's closing note understates the co-change.** It says implementing `skill_id` indexing "touches `scoring.py` and the `to_tsvector` pre-filter"; it is stronger than that — `skill_id` is in neither `_SEARCH_VECTOR` nor the `idx_skills_search` GIN expression, so without a migration a slug-only match returns **zero rows** on Postgres while scoring positive in memory, and the stratum-A recovery §2.6 measures (0/3 → 3/3) is precisely the class that would not reach a deployed environment. The same applies in reverse to §2.2's CamelCase fix: the prefilter's lexemes "mirror the scorer's matching unit" only because Python's `tokenize()` and PostgreSQL's `to_tsvector('simple', …)` both decline to split CamelCase, so splitting on the query side alone can **reduce** the rows Postgres returns. (3) **§8.5 step 1's `parse_sources` framing is imprecise.** `core/config.py::parse_sources` validates `SKILLS_SOURCES` JSON (duplicate `source_id`, malformed ids, missing type-specific fields) and **never sees file content**, so it cannot accept or reject overlapping coverage at all; the product-side fix belongs in `rank()` (SPEC-066 R-7) or at sync time, where body hashes exist — **[corrected 2026-10-02: no body hashes exist anywhere in `skills-hub`; see the row of that date]**. Also recorded in the spec: because no single candidate reaches significance alone (§8.3: V5 p = 1.0000, V1 p = 0.3750, V2 p = 0.2891, V3 p = 0.0215), shipping only the backend-neutral subset would ship an **unmeasured** subset, which §8's own rule forbids. |
| 2026-10-02 | **Self-correction pass on two claims this artifact and its promoting spec made; SPEC-066 advanced `draft` → `approved`.** No measurement, label, catalogue, pool, metric, or §8 number in this artifact is changed — the corrections are about *provenance*, not results. (1) **`body_md5` is not a product capability.** The 2026-10-01 (4) row above placed the duplicate-content fix at sync time "where body hashes exist". **There are none**: `md5`, `sha256`, `hashlib` and `blake2` appear nowhere in `products/skills-hub` outside `uv.lock`'s dependency hashes. The `body_md5` this artifact's own fixture pins was computed by the **offline harness** described in §3, not by the product; the row described harness-side work as though it were shipped machinery. Sync holds body *text* (`Skill.body`), so a hash is trivially computable there — the error is the tense, not the location. SPEC-066 OQ-6 consequently **defers** sync-time overlap rejection (feasible, but nondeterministic precedence across independently-jittered sync loops, the eventual-consistency hole `_resolve_compositions` already documents, and no store surface returning all bodies) and ships R-7's `rank()` de-duplication alone. (2) **§3's harness is not committed, so SPEC-066 R-8 cannot "reuse" it.** `git ls-files` shows only this artifact, [the spike memo](./semantic-skill-retrieval-spike.md) and [the label fixture](./semantic-skill-retrieval-labels.json) — no harness. R-8 is SPEC-066's **merge gate**, so its instrument must exist in the repository: it is rebuilt, committed, and given its own fidelity gate (it must reproduce the shipped scorer's published §8.1 baseline of **19/38** combined top-1 before any candidate number from it is believed). This also means the CamelCase-splitting **variant** behind §8's 0.711 cannot be confirmed from the repository — §8.2's candidate row 2c records the mechanism in one column as "tokenizer regex" and §8.5 step 2 only as "tokenizer", neither of which distinguishes whole-token retention from parts-only — so R-8 re-derives it rather than assuming 0.711 transfers to the whole-token-retention rule SPEC-066 R-4 chose. Both false claims were made in five committed places (this row, the memo's 2026-10-01 entry, and SPEC-066's `spec.md`/`plan.md`/`tasks.md`); all five are corrected and marked, not silently edited, because both artifacts are measurement records. The same pass updates this artifact's **"Promoted to" status header** (`draft` → `approved`) and records there that R-8 reconstructs rather than reuses §3's harness; a status header states current status rather than measurement, so it is edited in place rather than annotated. No measurement, label, catalogue, pool, metric, or §8 number is changed. |
| 2026-10-02 (2) | **SPEC-066 Stage 0 answered the re-derivation obligation the row above opened; §8.2 gains a dated annotation.** No measurement, label, catalogue, pool, metric, or §8 number is changed — the annotation records *provenance*, and every published figure still holds for the variant that was actually measured. The row above said the CamelCase-splitting **variant** behind §8's 0.711 could not be confirmed from the repository and that R-8 must re-derive it. Stage 0 did, read-only: the harness described in §3 **survived in the gitignored scratch directory** (still not committed, so R-8's obligation to rebuild and commit it is unchanged) and re-ran unmodified — §5's pinned pool **63/63 byte-identical including scores**, the shipped scorer **38/38**, every §8.2 number reproduced. Fidelity gate first: a `COPY … TO STDOUT` export of the live `skills` table matches this artifact's fixture pins exactly (**18/18** `body_md5` and `body_bytes`, 18 distinct hashes, **75,680** bytes), so the labels remain valid for the corpus as deployed. **The answer: §8.2 row 2c's "tokenizer regex" was parts-only** — `" ".join(CAMEL.split(text))` then `findall`, dropping the whole token — i.e. the variant SPEC-066 R-4 *rejects*. Re-measured under R-4's position-aware whole-token retention, every aggregate metric is **identical** and **no top-10 list reorders on any of the 38 queries** (8 of 684 scores change, all on the 3 CamelCase queries), so **0.711 does transfer** and R-8 may carry it over. **One new limit on §8's authority, measured rather than assumed:** these metrics **cannot distinguish a correct tokenizer shape from a wrong one** — a naive flat-list retention reorders **26 of 38** top-10 pools, changes **464 of 684** scores and doubles the score scale (mean 10.170 → **21.827**, max 63.786 → 129.898) while reporting the *same* B MRR (0.950), C MRR (0.778) and combined top-1 (**27/38**), so it would have passed this harness. Aggregation changes must be gated on unit assertions, not on §8. Also recorded there: none of the 38 queries is a whole *lowercase* identifier, the one case where retention changes a document's token set without the query being CamelCase, so this set cannot observe it. Separately, Stage 0 **falsified a claim in SPEC-066, not in this artifact**: its approved GIN expression added `skill_id` by plain text concatenation, but PostgreSQL's default parser types a slash-containing slug as **`file` ("File or path name")** and emits one opaque lexeme, so that expression matches **0 rows** where separator normalization matches **1**. §2.6 and the 2026-10-01 (4) row are unaffected — both say only that `skill_id` is absent from `_SEARCH_VECTOR` and `idx_skills_search`, which remains true. |
| 2026-10-03 | **Delivered as v0.46.0; §10 added recording SPEC-066 R-8's re-measurement through the shipped PostgreSQL path.** No measurement, label, catalogue, pool, metric, or §8 number is changed — §10 is an append, and §8's offline figures stand as the memory-path upper bound they were always labeled. The "Promoted to" status header gains `delivered 2026-10-03 as v0.46.0` (a status header states current status rather than measurement, so it is edited in place per the 2026-10-02 row's convention). §10 records: the reconstructed-and-committed harness reproduced §8.1's **19/38** baseline before any candidate number was believed; the shipped candidate measures **24/38** combined top-1 (V3, the three backend-neutral fixes, is **23/38**; R-1's slug adds the 24th), combined MRR **0.842**, stratum-B MRR **0.900**, stratum-C top-1 **10/18** / MRR **0.778**, stratum-A owner recovery **0/3 → 3/3**, null result **0 missing**, abstention **unchanged 4/38**; the primary nDCG@10 bootstrap CI **[+0.022, +0.111]** excludes zero while the coarser top-1 sign test is **downgraded** to **(7, 2) p = 0.1797** (directional only) from §8's offline **(9, 1) p = 0.0117**; **two** in-window re-orderings (**Q62 + Q63**) are accepted and disclosed; and the shipped **24/38** vs §8's offline **27/38 (0.711)** gap is R-4's deliberate **query-side-only** scoping (parity by construction over ~3 top-1 points). §9's boundary is unchanged — §10 records a result produced under SPEC-066's own authorization, not a widening of this artifact's. |
