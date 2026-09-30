# Eval set: Lexical Skill-Retrieval Baseline

Status: **measurement artifact — gate 1 of the spike memo. Authorizes no implementation, ADR, or spec.**
Date: 2026-09-30 · Revised: 2026-10-01 (§2.4 correction applied to the memo; catalogue and pool regenerated against the de-duplicated 18-row corpus)
Companion to: [semantic-skill-retrieval-spike.md](./semantic-skill-retrieval-spike.md) — this file instantiates its [§7.1 Evaluation set](./semantic-skill-retrieval-spike.md#71-evaluation-set)
Roadmap home: [Exploration Backlog](../agentic-aiops-platform/delivery-roadmap.md#exploration-backlog), "Semantic (vector) skill retrieval"
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
| **A** | 14 | Audit queries containing a target identifier (`DemoTriage`, `ResetPasswordAdHoc`, `ResetUserPassword`, `scratch-restart-demo`, `browser-check-target`, `svc-check`, `SPEC-015`) | **Regression check only.** Excluded from headline metrics — they match trivially and would flatter any retriever |
| **B** | 49 | Remaining audit queries, in searcher-composed operator vocabulary | **Headline metrics.** This is the real-traffic baseline |
| **C** | ≥18 to author | Paraphrases sharing **no token** with the target document, plus negative controls | **The decisive stratum.** The audit trail cannot supply it (§2.4); it is the only stratum that can separate lexical from semantic |

Stratum C seeds, derived from the measured defects rather than guessed:

| # | Paraphrase | Expected target | Why it discriminates |
|---|---|---|---|
| C01 | pod won't start | `D12` / `D06` | No shared token with `KubePodNotReady` |
| C02 | container keeps dying | `D11` / `D01` | Tests the CamelCase opacity of §2.2 |
| C03 | app crash looping after deploy | `D11` | `crash looping` ≠ `crashloopbackoff` |
| C04 | process out of memory killed | `D01` / `D09` | `oom` tag unreachable from prose |
| C05 | disk full on node | `D09` | Memo §7.1's named example |
| C06 | node went offline | `D10` | No token overlap with `KubeNodeNotReady` |
| C07 | image won't download | `D05` | `pull` vs `download` |
| C08 | pod stuck in pending | `D06` | `scheduling` vs `pending` |
| C09 | service name not resolving | `D03` | `dns` vs `name resolving` |
| C10 | user locked out of admin console | `D14` / `D16` | Memo §7.1's named example |
| C11 | issue a temporary password for alice | `D17` / `D04` | Two plausible targets — graded labels matter |
| C12 | is the admin portal up | `D15` | `healthz`/`uptime` vs `is it up` |
| C13 | check whether the account is suspended | `D18` / `D16` | `suspend` is a tag, not a title token |
| C14 | replica count is wrong | `D08` | CamelCase title, prose query |
| C15 | container waiting to start | `D07` | CamelCase title, prose query |
| C16 | certificate expired on the ingress | **none** | Negative control |
| C17 | argocd sync keeps failing | **none** | Negative control — the §2.3 Q31 failure, made explicit |
| C18 | database connection pool exhausted | **none** | Negative control |

**Negative controls are mandatory, not optional.** C16–C18 have no relevant
document, so they are the only queries that can measure *zero-relevant rate* and
detect a retriever that answers confidently when it should say "nothing applies".
Q31 shows the current system scores 20.0 on exactly that failure.

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
5. **The labeler must own the runbooks.** Per memo §7.1, an unreviewed set measures
   the author's guesses.

### 6.4 Minimum viable effort

Full coverage is ~500 pooled judgments plus whole-catalogue additions. A defensible
first pass is **20 stratum-B queries spanning all four document families
(`D01`–`D06` guides, `D07`–`D12` alerts, `D13`–`D18` samples) plus all 18
stratum-C queries** — 38 queries, roughly 250 judgments. Report it as a 38-query
sample with confidence intervals, and treat any difference inside the noise band as
**no evidence of improvement** (memo §7.1).

## 7. Label sheet

Copy this block per labeler. One row per (query, document) pair judged; omit pairs
graded 0 only if the labeler confirms they reviewed the full catalogue.

```
Labeler: ______________________   Date: __________   Corpus snapshot: 2026-10-01 (18 rows)

| Query | Doc | Grade (0/1/2) | Note (required for grade 2 on a negative control) |
|-------|-----|---------------|----------------------------------------------------|
| Q__   | D__ |               |                                                    |
| C__   | D__ |               |                                                    |

Negative controls judged (must include C16, C17, C18): ______
Whole-catalogue review confirmed (Y/N): ______
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

## Changelog

| Date | Change |
|---|---|
| 2026-09-30 | Created. Instantiates memo §7.1: 18-document catalogue, 63-query pool at depth 10 reproduced with the real scorer (validated against audit `skill_ids`, with two catalog-drift mismatches documented), strata A/B/C, grading scale, label sheet, and a cost-ordered pre-registered decision rule. Records three measured lexical defects — duplicate-source crowding (32/63 queries), opaque CamelCase titles, and confidently scored irrelevant top-1s — none of which requires a vector store to fix. Flags the correction owed to memo §2.2 on query shape. |
| 2026-10-01 | §2.4 correction **applied** to the memo: its §2.2 query-shape claim is rewritten (masking hypothesis untested, not disproved — 14 of 63 queries carry a target identifier), a new memo §2.3 carries the three measured defects, §4.4 gains the two cheapest fixes, §7.2 gains zero-relevant rate and distinct-document metric variants, §1 and §10 are re-ordered cost-first, and the memo is retitled for an 18-document corpus. The delivery-roadmap backlog row is aligned to the same evidence. |
| 2026-10-01 (2) | **Regenerated against the de-duplicated 18-row corpus** after the operator authorized both §9 cleanups. `_idx_probe` dropped; the two local ConfigMap skill sources removed so `platform-skills` (git) is the only route to those trees. §2.1 rewritten as a resolved defect with a before/after table (crowding **32 of 63 → 0 of 63**; distinct documents in top-5 windows 265 → 309 of 315; pool entries 582 → 526) and the verified claim that the change was purely subtractive — **no top-1 changed** and the old de-duplicated pool is an exact prefix of the new one for all 63 queries. §2.2 gains the Q03 paraphrase measurements and records that defect 2 survives (Q46 still ranks `D06` above `D11` on an alphabetical tie-break at 10.0). §2.3 records that defect 3 is unchanged. §3 replaces the now-unusable audit cross-check with a three-part validation and warns that live searches append audit events. §4 collapses to one row per code. §5 pool regenerated; summary re-tabulated as two corpora. §8 step 1 marked half-done — `rank()` still de-duplicates nothing and `parse_sources` still accepts overlapping coverage. |
