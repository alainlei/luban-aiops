# Eval set: Lexical Skill-Retrieval Baseline

Status: **measurement artifact — gate 1 of the spike memo. Read-only. No implementation, ADR, or spec is authorized by this document.**
Date: 2026-09-30
Companion to: [semantic-skill-retrieval-spike.md](./semantic-skill-retrieval-spike.md) — this file instantiates its [§7.1 Evaluation set](./semantic-skill-retrieval-spike.md#71-evaluation-set)
Roadmap home: [Exploration Backlog](../agentic-aiops-platform/delivery-roadmap.md#exploration-backlog), "Semantic (vector) skill retrieval"
Evidence baseline: repository at v0.45.0 (`26fbd9b`); corpus exported from the `skills` database and queries from the `audit` database on `postgres-0` in the `dev-luban-aiops` cluster. **Every query was read-only.** Nothing was installed, embedded, deployed, mutated, or labeled.

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

- **The pool is pinned to the 2026-09-30 corpus.** The catalog has already moved
  once — historical audit results include `platform-runbooks/web-checks/inventoryhealth`,
  which no longer exists (retired with the `web-checks` samples). Re-running this
  extraction against a changed catalog silently invalidates prior labels, so the
  snapshot in §4 is part of the fixture, not decoration.
- **The traffic is demo/e2e, not sustained operator triage.** All 96 recorded
  searches fall between 2026-09-02 and 2026-09-22. The pool is a real but narrow
  sample; §6 therefore requires a paraphrase stratum that the audit trail cannot
  supply.

## 2. What the extraction measured — three lexical defects

Extracting the pool required re-running the real scorer, which produced evidence
the memo did not have. All three findings below are measured, reproducible (§3),
and **none of them requires a vector store to fix**. They materially strengthen
[Option D — improve the lexical baseline first](./semantic-skill-retrieval-spike.md#44-option-d--improve-the-lexical-baseline-first-cheapest-may-be-sufficient).

### 2.1 The corpus is 18 documents, not 30 — and the duplicates eat result slots

`SKILLS_SOURCES` in
[`runtime-config.env:19`](../../shared/platform-ops/gitops/dev-k8s/base/skills-hub/runtime-config.env)
registers four sources. Two are local ConfigMap mounts (`/skills/platform-runbooks`,
`/skills/sre-alerting`); the fourth, `platform-skills`, is a **git** source pointed
at `shared/platform-ops/skills` — the parent directory of exactly those same two
trees. And the ConfigMaps are generated from the *same files* that git source
ingests ([`kustomization.yaml:25-40`](../../shared/platform-ops/gitops/dev-k8s/base/kustomization.yaml)
maps `../../../skills/sre-alerting/alerts/*.md` and
`../../../skills/platform-runbooks/guides/*.md`), so this is not similar content but
literally one file reaching the store by two routes under two `source_id`s.

Verified in the database by grouping on `md5(body)`: **12 groups of 2 byte-identical
bodies plus 6 singletons**.

| Measure | Value |
|---|---|
| Corpus rows | **30** |
| Distinct documents (`md5(body)`) | **18** |
| Byte-identical duplicate rows | **12** (every `platform-runbooks` guide and every `sre-alerting` alert) |

`rank()` has no content-level de-duplication, so both copies of a document score
identically and occupy separate slots in a `limit=5` window. Ties break on
`skill_id` ascending, so the `platform-runbooks/…` copy always precedes the
`platform-skills/platform-runbooks/…` copy.

**Measured: 32 of 63 queries (50.8%) return fewer distinct documents than result
slots in the top 5.** Restricted to the discriminating stratum (§6.1), **22 of 49
(44.9%)**. The worst observed case is Q03 `KubePodNotReady` — 9 occurrences, the
most frequent query in the entire trail — which returns 4 hits containing **2
distinct documents**, ranks 3–4 being `KubeDeploymentReplicasMismatch` at score
1.0, a document with no plausible bearing on a pod-readiness alert.

This is a *configuration* overlap exposing a *missing product capability*. Both
halves matter: fixing the dev source list alone would hide the fact that any
deployment registering overlapping sources gets the same crowding, because nothing
in the retrieval path collapses identical content.

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

The consequence is measured, not inferred. For Q46 `pod keeps restarting CrashLoopBackOff`:

| Rank | Code | Document | Score |
|---|---|---|---|
| 1–2 | `D06` | Pod Scheduling Failures | 10.0 |
| 3–4 | `D11` | **KubePodCrashLooping** | 10.0 |
| 5 | `D01` | Crash Loops and OOM Kills | 8.0 |

The single most on-point document in the corpus is ranked **third**, behind two
copies of a guide about *scheduling* failures — and because the two are tied at
10.0, that ordering is decided by **alphabetical `skill_id` sort, not relevance**.
Adding one word flips it: Q47 `pod keeps restarting CrashLoopBackOff restart`
puts `D11` first at 11.0. A one-token query change reordering the top result is
exactly the variance the memo's §7.2 "rank stability" metric exists to catch.

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

### 2.4 Correction owed to the memo

Memo [§2.2](./semantic-skill-retrieval-spike.md#22-the-corpus-and-the-real-query-record-live-2026-09-30)
asserts that "the observed 5-word mode confirms natural phrasing reaches the
scorer" and that the "agent already adapts to lexical" masking hypothesis is
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
was overstated and should be corrected.

## 3. Reproduction

Every number above is reproducible read-only. No product code was modified, and
no scorer logic was reimplemented — the analysis imports the real
[`scoring.py`](../../products/skills-hub/src/skills_hub/services/scoring.py)
module and calls its `rank()` directly.

1. **Export the corpus** (30 rows: `skill_id`, `title`, `tags`, `body`):

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

**Validation.** The offline reproduction returns the same documents in the same
order as the `skill_ids` arrays recorded in the audit trail for every cross-checked
query whose catalog has not drifted — Q03 `KubePodNotReady`, Q46 `pod keeps restarting CrashLoopBackOff`,
and Q56 `restart pod`, including the duplicate pairs and their `skill_id` tie-break
order. The reproduction is therefore a faithful model of deployed behavior and can
serve as the evaluation harness without touching the cluster.

Two cross-checked queries **do not** match, and the mismatch is itself evidence:

| Query | Historical `skill_ids` | Today's pool | Cause |
|---|---|---|---|
| Q31 `argocd health check` | led by `platform-runbooks/web-checks/inventoryhealth` | led by `D15` | that document was retired with the `web-checks` samples |
| Q40 `password reset` | one `generatepassword` row | `D04` in **two** slots | the duplicate row did not exist at search time — same scores and the same `skill_id` tie-break would have surfaced it had the `platform-skills` source already contributed it |

So the audit trail's recorded results are **not** reusable as ground truth for
today's corpus. Labels must be computed against a pinned snapshot, which is why §5
regenerates the pool rather than replaying `skill_ids`.

## 4. Document catalogue — 18 distinct documents

Codes `D01`–`D18` are the labeling unit. Labels attach to a **document**, never to
a corpus row: `D01` and its duplicate row are the same runbook, and grading them
separately would double-count.

| Code | Title | Tags | Rows | Corpus rows |
|---|---|---|---|---|
| `D01` | Crash Loops and OOM Kills | kubernetes, pod, troubleshooting, oom, crashloop | 2 | `platform-runbooks/guides/crashloopsandoom`<br>`platform-skills/platform-runbooks/guides/crashloopsandoom` |
| `D02` | Debug Pods | kubernetes, pod, troubleshooting, debugging | 2 | `platform-runbooks/guides/debugpods`<br>`platform-skills/platform-runbooks/guides/debugpods` |
| `D03` | Debug Services | kubernetes, service, troubleshooting, dns, networking | 2 | `platform-runbooks/guides/debugservices`<br>`platform-skills/platform-runbooks/guides/debugservices` |
| `D04` | Generate a Password and Deliver It Securely | password, generate, secret, delivery, reset, account-recovery, portal-copy, email | 2 | `platform-runbooks/guides/generatepassword`<br>`platform-skills/platform-runbooks/guides/generatepassword` |
| `D05` | Image Pull Failures | kubernetes, pod, troubleshooting, image | 2 | `platform-runbooks/guides/imagepullfailures`<br>`platform-skills/platform-runbooks/guides/imagepullfailures` |
| `D06` | Pod Scheduling Failures | kubernetes, pod, troubleshooting, scheduling | 2 | `platform-runbooks/guides/podschedulingfailures`<br>`platform-skills/platform-runbooks/guides/podschedulingfailures` |
| `D07` | KubeContainerWaiting | kubernetes, pod, alerting, KubeContainerWaiting | 2 | `platform-skills/sre-alerting/alerts/kubecontainerwaiting`<br>`sre-alerting/alerts/kubecontainerwaiting` |
| `D08` | KubeDeploymentReplicasMismatch | kubernetes, deployment, alerting, KubeDeploymentReplicasMismatch | 2 | `platform-skills/sre-alerting/alerts/kubedeploymentreplicasmismatch`<br>`sre-alerting/alerts/kubedeploymentreplicasmismatch` |
| `D09` | KubeMemoryPressure | kubernetes, node, alerting, KubeMemoryPressure, memory | 2 | `platform-skills/sre-alerting/alerts/kubememorypressure`<br>`sre-alerting/alerts/kubememorypressure` |
| `D10` | KubeNodeNotReady | kubernetes, node, alerting, KubeNodeNotReady | 2 | `platform-skills/sre-alerting/alerts/kubenodenotready`<br>`sre-alerting/alerts/kubenodenotready` |
| `D11` | KubePodCrashLooping | kubernetes, pod, alerting, KubePodCrashLooping, CrashLoopBackOff | 2 | `platform-skills/sre-alerting/alerts/kubepodcrashlooping`<br>`sre-alerting/alerts/kubepodcrashlooping` |
| `D12` | KubePodNotReady | kubernetes, pod, alerting, KubePodNotReady | 2 | `platform-skills/sre-alerting/alerts/kubepodnotready`<br>`sre-alerting/alerts/kubepodnotready` |
| `D13` | Reset a Password Ad Hoc (Per-Action Approval) | admin, portal, password, reset, ad-hoc, per-action, approval, browser, web-check, troubleshooting | 1 | `samples/adhoc-password-reset-resetpasswordadhoc` |
| `D14` | Recover a Locked-Out ACME Admin Account | acme-admin, composition, runbook, account-recovery, password-reset, unlock, user-management | 1 | `samples/composition-recoveracmeaccount` |
| `D15` | Check ACME Admin Service Health | acme-admin, health, healthz, http, service-check, read-only, api, uptime, monitoring | 1 | `samples/health-check-checkservicehealth` |
| `D16` | Lock or Unlock an ACME Admin User Account | acme-admin, user, account, lock, unlock, suspend, http, mutation, user-management | 1 | `samples/lock-unlock-user-lockunlockuser` |
| `D17` | Reset a Password in the ACME Admin Console | acme-admin, console, password, reset, browser-flow, web-check, mutation, temporary-password, user-management | 1 | `samples/password-reset-resetacmepassword` |
| `D18` | Check ACME Admin User Account Status | acme-admin, user, account, status, locked, web-check, read-only, verification, user-management | 1 | `samples/user-status-checkuserstatus` |

## 5. Query pool — 63 real queries, lexical candidates at depth 10

Extracted from `skill_searched.details->>'query'` (SPEC-029). Pooling depth is 10
rather than 5 so nDCG@10 is computable and so labelers see candidates beyond the
operator-visible window. Repeated codes at adjacent ranks are the duplicate rows
of §2.1 — they are the defect, left visible rather than collapsed.

`†` marks **stratum A**: the query already contains the identifier of the document
it was seeking, so it cannot discriminate retrieval quality (§6.1).

| # | Query | n | avg hits | distinct@5 | Pool (rank:code:score) |
|---|---|---|---|---|---|
| Q01 † | DemoTriage synthetic demo deployment SPEC-015 triage | 1 | 5.00 | 4/5 | 1:D08:9 2:D08:9 3:D16:6 4:D13:5 5:D03:3 6:D03:3 7:D17:3 8:D09:2 9:D10:2 10:D12:2 |
| Q02 † | DemoTriage synthetic demo deployment triage SPEC-015 | 1 | 5.00 | 4/5 | 1:D08:9 2:D08:9 3:D16:6 4:D13:5 5:D03:3 6:D03:3 7:D17:3 8:D09:2 9:D10:2 10:D12:2 |
| Q03 | KubePodNotReady | **9** | 4.00 | **2/4** | 1:D12:6 2:D12:6 3:D08:1 4:D08:1 |
| Q04 | KubePodNotReady alert | 2 | 4.00 | **2/4** | 1:D12:8 2:D12:8 3:D08:1 4:D08:1 |
| Q05 † | ResetPasswordAdHoc password reset admin portal | 1 | 4.00 | 4/5 | 1:D17:32 2:D13:29 3:D14:25 4:D04:21 5:D04:21 6:D18:15 7:D16:14 8:D15:11 |
| Q06 † | ResetPasswordAdHoc reset password admin portal | 1 | 4.00 | 4/5 | 1:D17:32 2:D13:29 3:D14:25 4:D04:21 5:D04:21 6:D18:15 7:D16:14 8:D15:11 |
| Q07 † | ResetUserPassword admin portal | 2 | 3.00 | 5/5 | 1:D17:12 2:D14:11 3:D16:11 4:D15:10 5:D18:10 6:D13:9 7:D04:4 8:D04:4 |
| Q08 † | ResetUserPassword admin portal reset password | 1 | 3.00 | 4/5 | 1:D17:32 2:D13:29 3:D14:25 4:D04:21 5:D04:21 6:D18:15 7:D16:14 8:D15:11 |
| Q09 † | ResetUserPassword admin portal reset user password | 1 | 5.00 | 5/5 | 1:D17:39 2:D13:34 3:D14:32 4:D18:25 5:D16:24 6:D04:21 7:D04:21 8:D15:13 9:D07:1 10:D07:1 |
| Q10 † | ResetUserPassword reset password user admin portal | 1 | 5.00 | 5/5 | 1:D17:39 2:D13:34 3:D14:32 4:D18:25 5:D16:24 6:D04:21 7:D04:21 8:D15:13 9:D07:1 10:D07:1 |
| Q11 | acme | 1 | 5.00 | 5/5 | 1:D15:10 2:D16:10 3:D17:10 4:D18:10 5:D14:9 6:D13:5 7:D04:1 8:D04:1 |
| Q12 | acme-admin password reset alice | 1 | 5.00 | 5/5 | 1:D17:41 2:D13:33 3:D14:33 4:D16:27 5:D18:27 6:D15:21 7:D04:18 8:D04:18 |
| Q13 | acme-admin password reset runbook | 1 | 5.00 | 5/5 | 1:D14:40 2:D17:40 3:D13:37 4:D18:26 5:D16:23 6:D15:21 7:D04:18 8:D04:18 |
| Q14 | adhoc password reset admin panel | 1 | 4.00 | 4/5 | 1:D17:30 2:D13:29 3:D14:24 4:D04:17 5:D04:17 6:D18:15 7:D16:13 8:D15:11 |
| Q15 † | adhoc password reset resetpasswordadhoc admin panel | 1 | 4.00 | 4/5 | 1:D17:30 2:D13:29 3:D14:24 4:D04:17 5:D04:17 6:D18:15 7:D16:13 8:D15:11 |
| Q16 | admin panel password reset legacy | 1 | 3.00 | 4/5 | 1:D17:32 2:D13:29 3:D14:24 4:D04:17 5:D04:17 6:D18:15 7:D16:13 8:D15:11 |
| Q17 | admin portal password reset ad-hoc credential set | 1 | 5.00 | 5/5 | 1:D13:59 2:D17:42 3:D14:27 4:D16:26 5:D18:25 6:D04:21 7:D04:21 8:D15:21 9:D01:1 10:D01:1 |
| Q18 | admin portal password reset user | 5 | 5.00 | 5/5 | 1:D17:39 2:D13:34 3:D14:32 4:D18:25 5:D16:24 6:D04:21 7:D04:21 8:D15:13 9:D07:1 10:D07:1 |
| Q19 | admin portal password reset user account | 1 | 5.00 | 5/5 | 1:D14:42 2:D17:42 3:D13:34 4:D16:32 5:D18:32 6:D04:25 7:D04:25 8:D15:13 9:D07:1 10:D07:1 |
| Q20 | admin portal reset password user | 1 | 5.00 | 5/5 | 1:D17:39 2:D13:34 3:D14:32 4:D18:25 5:D16:24 6:D04:21 7:D04:21 8:D15:13 9:D07:1 10:D07:1 |
| Q21 | admin portal reset user password | 4 | 5.00 | 5/5 | 1:D17:39 2:D13:34 3:D14:32 4:D18:25 5:D16:24 6:D04:21 7:D04:21 8:D15:13 9:D07:1 10:D07:1 |
| Q22 | admin portal user password reset | 2 | 5.00 | 5/5 | 1:D17:39 2:D13:34 3:D14:32 4:D18:25 5:D16:24 6:D04:21 7:D04:21 8:D15:13 9:D07:1 10:D07:1 |
| Q23 | admin portal user password reset web check | 1 | 5.00 | 5/5 | 1:D17:49 2:D13:44 3:D18:42 4:D14:35 5:D16:27 6:D15:26 7:D04:21 8:D04:21 9:D07:4 10:D07:4 |
| Q24 | admin portal web check | 1 | 5.00 | 5/5 | 1:D18:27 2:D15:23 3:D17:22 4:D13:19 5:D14:14 6:D16:14 7:D04:4 8:D04:4 9:D07:3 10:D07:3 |
| Q25 | admin portal web user management | 1 | 5.00 | 5/5 | 1:D18:29 2:D17:28 3:D16:25 4:D14:23 5:D13:21 6:D15:15 7:D04:4 8:D04:4 9:D07:1 10:D07:1 |
| Q26 | admin portal write action user management approval | 1 | 5.00 | 5/5 | 1:D13:39 2:D16:38 3:D17:36 4:D14:33 5:D18:29 6:D15:14 7:D04:10 8:D04:10 9:D07:1 10:D07:1 |
| Q27 | argo workflows health check controller workflow | 1 | 5.00 | 4/5 | 1:D15:20 2:D18:10 3:D12:5 4:D12:5 5:D03:3 6:D03:3 7:D07:3 8:D13:3 9:D17:3 10:D07:3 |
| Q28 | argo-cd controller restart pod health namespace argocd | 1 | 5.00 | **3/5** | 1:D12:15 2:D12:15 3:D15:14 4:D02:12 5:D02:12 6:D01:11 7:D06:11 8:D01:11 9:D06:11 10:D03:10 |
| Q29 | argocd application-server repo-server deployment pod | 1 | 5.00 | **3/5** | 1:D06:10 2:D06:10 3:D11:10 4:D11:10 5:D01:9 6:D01:9 7:D12:9 8:D12:9 9:D02:8 10:D02:8 |
| Q30 | argocd argocd-server repo-server restart crashloop | 1 | 5.00 | 4/5 | 1:D18:5 2:D17:3 3:D01:2 4:D01:2 5:D16:2 6:D04:1 7:D04:1 8:D10:1 9:D11:1 10:D13:1 |
| Q31 | argocd health check | **7** | 5.00 | 4/5 | 1:D15:20 2:D18:10 3:D03:3 4:D03:3 5:D07:3 6:D13:3 7:D17:3 8:D07:3 9:D01:2 10:D01:2 |
| Q32 | argocd restarting pods repo-server crash troubleshooting | 1 | 5.00 | **3/5** | 1:D02:7 2:D03:7 3:D02:7 4:D03:7 5:D01:6 6:D01:6 7:D08:6 8:D08:6 9:D10:4 10:D10:4 |
| Q33 † | demo deployment triage DemoTriage warning | 1 | 5.00 | **3/5** | 1:D08:8 2:D08:8 3:D04:2 4:D04:2 5:D12:2 6:D12:2 7:D07:1 8:D09:1 9:D10:1 10:D11:1 |
| Q34 † | demo deployment triage DemoTriage warning deployment not ready | 1 | 5.00 | **3/5** | 1:D08:19 2:D08:19 3:D04:8 4:D04:8 5:D12:7 6:D12:7 7:D10:6 8:D14:6 9:D16:6 10:D10:6 |
| Q35 | demo deployment triage warning | 1 | 5.00 | **3/5** | 1:D08:8 2:D08:8 3:D04:2 4:D04:2 5:D12:2 6:D12:2 7:D07:1 8:D09:1 9:D10:1 10:D11:1 |
| Q36 | deployment needs triage warning pod not ready demo | 1 | 5.00 | **3/5** | 1:D08:13 2:D12:13 3:D08:13 4:D12:13 5:D06:12 6:D06:12 7:D15:12 8:D02:10 9:D02:10 10:D07:10 |
| Q37 | deployment triage warning pod not ready | 1 | 5.00 | **3/5** | 1:D08:13 2:D12:13 3:D08:13 4:D12:13 5:D06:12 6:D06:12 7:D02:10 8:D02:10 9:D07:10 10:D07:10 |
| Q38 † | inventory portal sign in failed browser-check-target svc-check credential set | 1 | 5.00 | 5/5 | 1:D18:48 2:D15:44 3:D17:41 4:D13:36 5:D16:26 6:D14:21 7:D04:10 8:D04:10 9:D03:8 10:D03:8 |
| Q39 | lock account acme-admin disable user | 1 | 5.00 | 5/5 | 1:D16:48 2:D14:41 3:D18:39 4:D17:30 5:D15:22 6:D13:17 7:D04:5 8:D04:5 9:D07:1 10:D07:1 |
| Q40 | password reset | 1 | 5.00 | 4/5 | 1:D13:20 2:D17:20 3:D04:17 4:D04:17 5:D14:14 6:D18:5 7:D16:3 8:D15:1 |
| Q41 | password reset account recovery admin console | 1 | 5.00 | 5/5 | 1:D17:43 2:D14:38 3:D13:32 4:D18:27 5:D16:24 6:D04:23 7:D04:23 8:D15:12 |
| Q42 | password reset admin web | 1 | 3.00 | 5/5 | 1:D17:37 2:D13:34 3:D14:27 4:D18:22 5:D04:17 6:D04:17 7:D16:15 8:D15:14 |
| Q43 | password reset user account admin portal credential change | 1 | 5.00 | 5/5 | 1:D17:51 2:D13:44 3:D14:44 4:D16:42 5:D18:40 6:D04:25 7:D04:25 8:D15:18 9:D03:1 10:D03:1 |
| Q44 | password reset write-class web-check flow binding | 1 | 5.00 | 5/5 | 1:D13:45 2:D17:45 3:D18:39 4:D14:31 5:D15:25 6:D04:19 7:D04:19 8:D16:19 9:D07:3 10:D07:3 |
| Q45 | pod health check readiness verify running ready conditions | 1 | 5.00 | 4/5 | 1:D15:25 2:D12:14 3:D12:14 4:D18:12 5:D02:11 6:D03:11 7:D06:11 8:D02:11 9:D03:11 10:D06:11 |
| Q46 | pod keeps restarting CrashLoopBackOff | 1 | 5.00 | **3/5** | 1:D06:10 2:D06:10 3:D11:10 4:D11:10 5:D01:8 6:D02:8 7:D01:8 8:D02:8 9:D12:8 10:D12:8 |
| Q47 | pod keeps restarting CrashLoopBackOff restart | 1 | 5.00 | **3/5** | 1:D11:11 2:D11:11 3:D06:10 4:D06:10 5:D01:8 6:D02:8 7:D01:8 8:D02:8 9:D12:8 10:D12:8 |
| Q48 | reset acme-admin password | 2 | 5.00 | 5/5 | 1:D17:40 2:D14:33 3:D13:32 4:D18:25 5:D16:23 6:D15:21 7:D04:18 8:D04:18 |
| Q49 | reset acme-admin password alice | 1 | 5.00 | 5/5 | 1:D17:41 2:D13:33 3:D14:33 4:D16:27 5:D18:27 6:D15:21 7:D04:18 8:D04:18 |
| Q50 | reset alice acme-admin password | 2 | 5.00 | 5/5 | 1:D17:41 2:D13:33 3:D14:33 4:D16:27 5:D18:27 6:D15:21 7:D04:18 8:D04:18 |
| Q51 | reset alice password | 1 | 5.00 | 4/5 | 1:D13:21 2:D17:21 3:D04:17 4:D04:17 5:D14:14 6:D16:7 7:D18:7 8:D15:1 |
| Q52 | reset password admin portal credential | 1 | 3.00 | 4/5 | 1:D17:37 2:D13:34 3:D14:26 4:D04:21 5:D04:21 6:D18:20 7:D16:19 8:D15:16 |
| Q53 | reset password admin portal user | 1 | 5.00 | 5/5 | 1:D17:39 2:D13:34 3:D14:32 4:D18:25 5:D16:24 6:D04:21 7:D04:21 8:D15:13 9:D07:1 10:D07:1 |
| Q54 | reset password user admin | 1 | 5.00 | 5/5 | 1:D17:37 2:D13:32 3:D14:31 4:D18:25 5:D16:23 6:D04:17 7:D04:17 8:D15:13 9:D07:1 10:D07:1 |
| Q55 | reset user password admin portal | **7** | 5.00 | 5/5 | 1:D17:39 2:D13:34 3:D14:32 4:D18:25 5:D16:24 6:D04:21 7:D04:21 8:D15:13 9:D07:1 10:D07:1 |
| Q56 | restart pod | 2 | 5.00 | **3/5** | 1:D06:10 2:D06:10 3:D11:8 4:D11:8 5:D01:7 6:D02:7 7:D01:7 8:D02:7 9:D07:7 10:D12:7 |
| Q57 | restart pod deployment workload | 1 | 5.00 | 4/5 | 1:D06:11 2:D06:11 3:D08:9 4:D11:9 5:D12:9 6:D08:9 7:D11:9 8:D12:9 9:D01:7 10:D02:7 |
| Q58 † | restart pod scratch-restart-demo | 1 | 5.00 | **3/5** | 1:D06:10 2:D06:10 3:D11:9 4:D11:9 5:D01:7 6:D02:7 7:D01:7 8:D02:7 9:D07:7 10:D12:7 |
| Q59 | scratch restart demo repeatedly restarting container | 1 | 5.00 | **3/5** | 1:D11:4 2:D11:4 3:D02:3 4:D02:3 5:D12:3 6:D17:3 7:D12:3 8:D01:2 9:D01:2 10:D07:2 |
| Q60 † | synthetic demo deployment triage DemoTriage alert | 1 | 5.00 | **3/5** | 1:D08:8 2:D08:8 3:D12:4 4:D12:4 5:D04:1 6:D04:1 7:D07:1 8:D09:1 9:D10:1 10:D11:1 |
| Q61 | user password reset web admin | 1 | 5.00 | 5/5 | 1:D17:44 2:D13:39 3:D14:34 4:D18:32 5:D16:25 6:D04:17 7:D04:17 8:D15:16 9:D07:1 10:D07:1 |
| Q62 | web check confirmation gate HITL blocked or page not advancing | 1 | 5.00 | 5/5 | 1:D17:35 2:D13:33 3:D18:32 4:D15:28 5:D16:24 6:D14:18 7:D04:10 8:D04:10 9:D07:9 10:D07:9 |
| Q63 | web check sign in inventory portal does not transition successful login troubleshooting | 1 | 5.00 | 5/5 | 1:D18:40 2:D17:38 3:D13:36 4:D15:28 5:D14:21 6:D16:18 7:D04:15 8:D04:15 9:D03:9 10:D03:9 |

Pool summary:

| Measure | Value |
|---|---|
| Queries | **63** (96 recorded searches) |
| Queries returning zero hits against the current corpus | **0** |
| Queries with duplicate crowding in the top 5 | **32 of 63 (50.8%)**; stratum B only: **22 of 49 (44.9%)** |
| Pool depth reached | 10 hits: 43 queries · 8 hits: 18 · 4 hits: 2 |
| Stratum A (identifier-bearing, `†`) | **14** |
| Stratum B (discriminating) | **49** |

**`n` and `avg hits` are historical audit values; the pool is today's.** They
disagree where the catalog moved — Q07 recorded 3 hits at search time but has 8
candidates now, and historical results for Q31 included
`platform-runbooks/web-checks/inventoryhealth`, which no longer exists. This is why
the pool was regenerated with the real scorer rather than reusing the recorded
`skill_ids`: labels must attach to the catalog they will be scored against.

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

1. **Label documents (`D01`–`D18`), never corpus rows.** Duplicate rows are one
   document; grading both double-counts and launders the §2.1 defect into the metric.
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
Labeler: ______________________   Date: __________   Corpus snapshot: 2026-09-30

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

1. **De-duplicate only** (collapse identical content in `rank()`, and/or fix the
   overlapping `SKILLS_SOURCES` registration). Measure.
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
`SKILLS_SOURCES`, the Postgres image, or any contract; no embedding run; no
extension install; no ADR; and no spec. The memo's gate sequence still governs.

Two cleanups surfaced by the extraction and **not** performed, because both are
mutations:

- `_idx_probe` — a leftover table (`title`, `tags`, `body` + a GIN index on
  `to_tsvector('simple', title)`) in the dev `skills` database, from an earlier
  index investigation. Harmless but cruft; safe to drop.
- The overlapping `SKILLS_SOURCES` registration (§2.1). Fixing it is a GitOps
  change with retrieval consequences and belongs in a spec-or-not decision made
  *after* the labels exist — not before.

## Changelog

| Date | Change |
|---|---|
| 2026-09-30 | Created. Instantiates memo §7.1: 18-document catalogue, 63-query pool at depth 10 reproduced with the real scorer (validated against audit `skill_ids`, with two catalog-drift mismatches documented), strata A/B/C, grading scale, label sheet, and a cost-ordered pre-registered decision rule. Records three measured lexical defects — duplicate-source crowding (32/63 queries), opaque CamelCase titles, and confidently scored irrelevant top-1s — none of which requires a vector store to fix. Flags the correction owed to memo §2.2 on query shape. |
