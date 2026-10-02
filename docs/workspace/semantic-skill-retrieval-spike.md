# Spike: Semantic Skill Retrieval — pgvector vs. the Lexical Baseline on an 18-Document Corpus

Status: assessment — **gate 1 executed 2026-10-01 and the cost-ordered measurement closed the row.** The recommendation was *measure before building*; the measurement is now in hand and says the cheap lexical fixes close the ordering gap while the recall gap a vector store would address **does not exist**. **No implementation, embedding run, extension install, image swap, ADR, or spec is authorized by this memo** (eval-set [§8.5](./semantic-skill-retrieval-eval-set.md#85-decision-rule-outcome)).
Date: 2026-09-30 · Revised: 2026-10-01 (§2.3 measured defects; §2.2 query-shape claim corrected; §4.4, §7, §10 re-ordered by cost) · Revised again 2026-10-01 (§2.3 defect 1 resolved by configuration; corpus figures re-measured at 18 rows / 2 sources) · **Third pass 2026-10-01** (§2.3 gains defects 4–5; §4.4 gains the `skill_id`/IDF/length-norm fixes and strikes the tie-break fix; §10 gate 1 closed, gate 2 measured, gate 3 not reached) · **Self-correction 2026-10-02** (§4.4's "where body hashes exist" is false — no hashing exists anywhere in `skills-hub`; marked inline, measurement text untouched)
Evaluation set: [semantic-skill-retrieval-eval-set.md](./semantic-skill-retrieval-eval-set.md) — built, regenerated against the 18-row corpus, and **labeled**: 38 queries × 18 documents = 684 judgments, committed as [semantic-skill-retrieval-labels.json](./semantic-skill-retrieval-labels.json), with the lexical baseline and the candidate comparison published in its §8
Roadmap home: [Exploration Backlog](../agentic-aiops-platform/delivery-roadmap.md#exploration-backlog), "Semantic (vector) skill retrieval"
Promoted to: [SPEC-066 skill retrieval ranking fidelity](../specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md) — **`draft` 2026-10-01, `approved` 2026-10-02**, covering §4.4's four measured fixes plus the cross-backend parity work this memo could not see and §11's open questions. **Approval does not weaken this memo's boundary any more than drafting did**: the six Open Questions were resolved 2026-10-02, and approval authorizes implementation to *begin* — it authorizes no merge, no index migration, no deployment and no version bump, and nothing below is retroactively authorized. §4.4's claim that indexing `skill_id` needs "no schema change" is true of `score()` and **false of the deployed Postgres backend** — `skill_id` is in neither `_SEARCH_VECTOR` nor `idx_skills_search`, so slug-only matches return zero rows there today; SPEC-066 R-1/R-5 carry the correction. §4.4's "`parse_sources` still accepts two sources covering the same files" is likewise imprecise — `parse_sources` validates `SKILLS_SOURCES` JSON and never sees file content, so it cannot detect content overlap at all; SPEC-066 R-7 puts de-duplication in `rank()` and routes any ingestion-time rejection to sync.
Evidence baseline: repository at v0.45.0 (`3c87723`); static read of the skills-hub retrieval path plus queries against the live dev cluster (`postgres-0` `skills` and `audit` databases, the `llm-hosting/ollama` deployment) and the pinned agentscope 2.0.8 venv. **The 2026-09-30 pass was entirely read-only** — nothing was installed, embedded, deployed, mutated, or committed. The 2026-10-01 revision follows two operator-authorized mutations (dropping the leftover `_idx_probe` table and removing the duplicate skill sources, §2.3 defect 1) and re-measures the corpus afterwards; **no product code was changed in either pass, and no embedding was computed.**

## 1. Question and recommendation

> Does a vector store measurably beat skills-hub's lexical `rank()` scoring
> (title/tag/body substring weighting) on our corpus?

Recommendation: **answered 2026-10-01 — by measurement, not implementation, and the
answer is that no vector store is needed.** When this memo was first written the
question was genuinely not answerable and the honest next step was a measurement;
that measurement has now been made (eval-set §8, on a labeled 684-judgment set). The
three findings below reshaped the question, and the labels settled it: **the recall
gap a vector store exists to close is measured absent** (0 of 38 queries have a
grade-2 document outside the top 10), while the *ordering* gap is real and is closed
by four cheap lexical fixes that need no model, no extension, and no image change
(combined top-1 correctness **0.500 → 0.711**, sign test **p = 0.0117**).

1. **The defect the backlog row assumes is not visible in the evidence.** All 96
   `skill_searched` audit events (2026-09-02 → 2026-09-22, 63 distinct queries)
   returned **at least one hit** — a zero-hit rate of **0/96**, mean **4.72** hits
   against the default `limit=5` (§2.2). The top-5 is *saturated*. That makes the
   live risk **ranking quality inside a full result set** (precision@k, MRR), not
   "nothing comes back". A vector store is primarily a recall instrument, and the
   measured symptom is not a recall failure. **Update (§2.3): that ranking risk is
   no longer abstract** — building the evaluation set measured three concrete
   causes, and none of them needs a vector store.
2. **`pgvector` is not a zero-infrastructure change.** The deployed
   `postgres:16-alpine` image offers **0 of 61** available extensions matching
   `%vector%`, so `CREATE EXTENSION vector` would fail today; enabling it means an
   image swap on the single StatefulSet that also holds the `audit`, `incidents`,
   and `sessions` databases (§3.1–3.2). The roadmap row's "avoiding new
   infrastructure" is true of a new *server* and false of a new *image*.
3. **At this corpus size, no vector store is needed to test the hypothesis at all.**
   The catalog is **18 rows across 2 sources, and 18 distinct documents** — it was 30
   rows across 4 sources until the duplicate registration was removed on 2026-10-01
   (§2.1, §2.3 defect 1) — totalling 75,398 characters of body text. Exact
   brute-force cosine over 18 documents in process is sub-millisecond
   and needs no extension, no image swap, and no ANN index. `pgvector` earns its
   place only when catalog scale makes SQL-side filtering or ANN necessary.

So: build a labeled evaluation set and measure the lexical baseline first (§7) —
**the set is built, labeled, and measured**: [semantic-skill-retrieval-eval-set.md](./semantic-skill-retrieval-eval-set.md)
holds the deduplicated 18-document catalogue, all 63 audit queries with their
lexical candidate pools at depth 10, the strata, the grading scale, a
pre-registered decision rule, and now the **684 judgments** that instantiate it plus
the baseline and candidate metrics in its §8. Candidates were evaluated in **cost
order, and a cheaper candidate that closes the gap ends the exercise — it did**:

1. **Finish de-duplication in the product and fix the tokenizer** (§4.4, defects 1–5
   of §2.3) — no model, no vector, no new dependency, no image change. Defect 1's
   *configuration* half is done; its *product* half is not, and is now defensible
   only as a **guardrail against regression** rather than as a retrieval improvement,
   because with the dev corpus already clean there is no crowding left to measure a
   fix against. The tokenizer half — IDF weighting, sublinear length norm, CamelCase
   splitting, and indexing `skill_id` — **is measured as sufficient** for the ordering
   gap. Whether to promote those four to a spec is a *separate* decision this memo
   still does not make.
2. ~~**Then** the heavier lexical options — cover-density ranking, trigram tolerance,
   a curated alias map.~~ **Cancelled by step 1's result.** They were never measured,
   and the rule this memo pre-committed to cancels them: each is more expensive than
   the fixes that already closed the gap.
3. ~~**Only then** semantics.~~ **Not authorized.** The precondition was that
   semantics beat the best of steps 1–2 outside the noise band, and they cannot on
   this evidence because the defect they would address does not exist. If the row is
   ever reopened, the cheapest substrate remains a **sidecar embedding table over
   `real[]` with in-process exact cosine** (§4.3, §5.2), reversible into `pgvector`
   later without a data migration.

## 2. Verified baseline — what "lexical" means today

### 2.1 The scorer and the store

| Fact | Where verified |
|---|---|
| Matching unit is `[a-z0-9]+` lowercase tokens; no stemming, no synonyms, no fuzzy/prefix match | [`scoring.py:20,28-30`](../../products/skills-hub/src/skills_hub/services/scoring.py) |
| Weights: title **3.0**, tag **2.0**, each body occurrence **1.0**, saturating at `BODY_OCCURRENCE_CAP = 5` | [`scoring.py:21-24,44-52`](../../products/skills-hub/src/skills_hub/services/scoring.py) |
| Zero-score records are **excluded**; ties break by `skill_id` ascending; ordering is `(-score, skill_id)` | [`scoring.py:85-96`](../../products/skills-hub/src/skills_hub/services/scoring.py) |
| Excerpt is a ≤400-char window around the first body match, falling back to the description head | [`scoring.py:55-75`](../../products/skills-hub/src/skills_hub/services/scoring.py) |
| One pure `rank()` is shared by **both** backends so ordering is byte-identical — a **documented** invariant (the `scoring.py` docstring, SPEC-014 R-3) that is **not** test-pinned: no test drives both backends over one corpus and compares ordering. SPEC-066 R-6 adds that harness | [`scoring.py:1-9`](../../products/skills-hub/src/skills_hub/services/scoring.py), [`skill_store.py:1-6,144,463`](../../products/skills-hub/src/skills_hub/services/skill_store.py) |
| Postgres pre-filters with a GIN index over `to_tsvector('simple', title \| ' ' \| body)` and re-ranks in Python | [`skill_store.py:202-205,437-463`](../../products/skills-hub/src/skills_hub/services/skill_store.py) |
| Lexemes are **OR**-joined (`" \| ".join(tokens)`), because `plainto_tsquery` ANDs and silently drops partial matches | [`skill_store.py:243-256,452`](../../products/skills-hub/src/skills_hub/services/skill_store.py) |
| `tags` cannot join the index expression (`array_to_string`/`array_out` are STABLE, not IMMUTABLE) and are matched in a second tsvector branch + query-time filter | [`skill_store.py:199-205,251-256,474-482`](../../products/skills-hub/src/skills_hub/services/skill_store.py) |
| DDL is idempotent by convention: `CREATE TABLE IF NOT EXISTS` then `ALTER ... ADD COLUMN IF NOT EXISTS` per spec version, run in `initialize()` | [`skill_store.py:158-206,324-328`](../../products/skills-hub/src/skills_hub/services/skill_store.py) |
| Backend selection is a `Protocol` + factory (`build_skill_store`) on `SKILLS_STORE_BACKEND` (`memory` default / `postgres`) | [`skill_store.py:30-67,509-517`](../../products/skills-hub/src/skills_hub/services/skill_store.py), [`config.py:181-230`](../../products/skills-hub/src/skills_hub/core/config.py) |
| Connections are opened per operation — retrieval is treated as low-volume | [`skill_store.py:295-322`](../../products/skills-hub/src/skills_hub/services/skill_store.py) |
| Tool surface: `skills.search` is `risk_level="read"`, `query` described as "Free-text search terms", `limit` default **5** / max **20**, upstream timeout **10.0 s** | [`skills_connector.py:31-38,154-196`](../../products/tool-gateway/src/tool_gateway/tools/skills_connector.py) |

The recall gap is real *in principle*: "pod won't start" shares no token with a
runbook titled `KubePodNotReady`, so it scores 0 and is excluded. What §2.2 shows
is that this has **not been observed** in the platform's own audit trail.

### 2.2 The corpus and the real query record (live; corpus re-measured 2026-10-01)

Corpus, from the `skills` database on `postgres-0`. The left column is the
2026-09-30 measurement, before the duplicate sources were removed; the right is the
current one:

| Measure | 2026-09-30 | 2026-10-01 |
|---|---|---|
| Skills (corpus rows) | 30 | **18** |
| Distinct documents (`md5(body)`) | 18 — 12 rows byte-identical duplicates (§2.3) | **18** — one row each |
| Distinct sources | 4 | **2** (`platform-skills` git 12, `samples` local 6) |
| Body length min / avg / max | 1,094 / 3,083 / 11,778 chars | **1,094 / 4,189 / 11,778** chars |
| Total body text | 92,486 chars | **75,398** chars (75,680 UTF-8 bytes, ~74 KB) |
| `skills` database size | 8,999 kB | **8,927 kB** |

The average body length *rises* after de-duplication because the 12 removed rows were
the short platform runbooks and alerts (≈1,400 chars each); the six `samples`
documents are the long ones and were never duplicated. Note also that the 2026-09-30
"total body bytes" figure was a `length(body)` **character** sum, not an octet sum —
the two differ by 282 non-ASCII characters in the current corpus. The label is
corrected here rather than silently carried forward.

Query record, from `skill_searched` events in the `audit` database (SPEC-029
records `query`, `limit`, `result_count`, and `skill_ids` in `details` — see
[`skills.py:146-158`](../../products/skills-hub/src/skills_hub/api/routes/skills.py)):

| Measure | Value |
|---|---|
| Searches recorded | **96** (all `service=skills-hub`, 2026-09-02 → 2026-09-22) |
| Distinct query strings | **63** |
| **Zero-hit searches** | **0 of 96** |
| Mean / max `result_count` | **4.72 / 5** |
| `limit` used | **5** on all 96 (the tool default) |
| Query length | 1–12 words; mode **5 words** (33 queries); only 10 single-word |
| `skill_retrieved` events | **341** (≈3.6 retrievals per search) |

Read honestly, with its limits:

- **Zero-hit headroom does not exist.** A retrieval change justified by "queries
  return nothing" has no supporting observation here. Any business case must be
  made on *ordering* — which of the five returned runbooks is first — not on
  emptiness.
- **`result_count` measures non-emptiness, not correctness.** 4.72/5 says the
  scorer found tokens, not that it found the *right* skill. Precision is unmeasured
  today, which is precisely why §7 asks for labels before code.
- **Query shape does not establish natural phrasing.** The tool description says
  "Free-text search terms" and the system prompt tells the agent to consult
  `skills.search` FIRST and not to conclude it lacks grounding until a search
  returns no match ([`runtime_settings.py:25-34`](../../products/agent-platform/src/agent_service/runtime_settings.py)).
  Nothing *instructs* keyword normalization — but the observed queries do not show
  natural phrasing either. **14 of the 63 already contain the identifier of the
  document they were seeking** (`DemoTriage`, `ResetPasswordAdHoc`,
  `ResetUserPassword`, `scratch-restart-demo`, `browser-check-target`, `svc-check`),
  and many more are visibly keyword-enumerated (`argocd application-server
  repo-server deployment pod`). A 5-word mode is as consistent with keyword
  stuffing as with prose. This memo originally concluded the masking hypothesis was
  "not supported"; that was overstated. The correct statement is that the
  hypothesis is **untested, and this pool cannot test it** — which is why §7.1's
  paraphrase stratum is mandatory rather than optional.
- **The traffic is not sustained operator triage.** All 96 events fall in a
  three-week window ending 2026-09-22, with none in the eight days to today; the
  pattern is demo, e2e, and verification traffic. The absence of zero-hit queries
  is therefore *weak* evidence, not proof that operators never hit the gap.

### 2.3 Five measured defects in the lexical baseline — defect 1 resolved 2026-10-01

Building the §7.1 evaluation set
([semantic-skill-retrieval-eval-set.md](./semantic-skill-retrieval-eval-set.md))
required re-running the real scorer over the real corpus, which produced evidence
this memo did not have when first written. All five defects below are measured,
reproducible, and **fixable without a vector store** — which is why §4.4 and §10
now put them ahead of the substrate decision. Defect 1 has since been fixed in the
dev overlay; defects 2 and 3 are unchanged and still reproduce today. **Defects 4
and 5 were found later, by gate 1's labeling pass** (2026-10-01): they change
*which document wins* rather than how many slots are filled, so the pool analysis
alone could not see them.

| # | Defect | Measured |
|---|---|---|
| 1 | **The corpus was 18 documents in 30 rows — *resolved by configuration 2026-10-01; the product gap behind it is not*.** [`runtime-config.env`](../../shared/platform-ops/gitops/dev-k8s/base/skills-hub/runtime-config.env) registered `platform-skills` as a git source at `shared/platform-ops/skills` while the base `kustomization.yaml` generated two local ConfigMap sources from *those same files*. One file reached the store by two routes under two `source_id`s. `rank()` does no content de-duplication and breaks ties on `skill_id` ascending | `md5(body)` grouping: **12 byte-identical pairs + 6 singletons**. **32 of 63 queries (50.8%)** returned fewer distinct documents than result slots; 22 of 49 in the discriminating stratum. **After** dropping the two local sources: **0 of 63**, 18 rows / 18 distinct bodies, no top-1 changed, and 28 pools widened (+88 candidates). Still open: `rank()` de-duplicates nothing and `parse_sources` accepts overlapping coverage, so any overlapping registration reproduces 32-of-63 |
| 2 | **CamelCase titles are opaque.** `tokenize("KubePodCrashLooping")` → `['kubepodcrashlooping']`, a single token, so no `sre-alerting` title can match a sub-word query term at the 3.0 title weight. Matching is strict token equality with no stemming, so `crashloop` cannot reach the `CrashLoopBackOff` tag | For `pod keeps restarting CrashLoopBackOff` the exactly-right document ranks **2nd** (was 3rd before de-duplication), tied at 10.0 with a *scheduling-failures* guide that takes the slot on alphabetical tie-break alone (`platform-runbooks` < `sre-alerting`). Adding the single word "restart" moves it to 1st at 11.0 |
| 3 | **A non-zero `result_count` is not a useful answer.** §2.2's zero-hit finding is true and, read alone, misleading | `argocd health check` — 7 occurrences, the trail's second most frequent query — scores **20.0** on "Check ACME Admin Service Health". **No ArgoCD document exists in the corpus.** Unchanged by de-duplication |
| 4 | **Document length and function words are unweighted.** `score()` sums `BODY_WEIGHT × min(occurrences, 5)` with no normalisation for document length, and weights every query token identically — so a long document wins by volume and a stopword scores as much as the subject | Eval-set [§2.5](./semantic-skill-retrieval-eval-set.md#25-document-length-bias-and-unweighted-function-words--measured-2026-10-01): `samples/*` bodies average **9,718 chars** against **1,424** for `platform-*` runbooks (**6.8×**). Body matches supply **70–100%** of the winning score on every stratum-C query whose lexical top-1 is graded 0, and samples take top-1 on **10 of 18** paraphrase queries though only 4 of 18 concern them. `D17` earns a full **3.0** from a *title* match on the stopword "the" on a TLS-certificate query |
| 5 | **`skill_id` is not an indexed field.** `score()` reads `skill.title`, `skill.tags` and `skill.body` and never `skill.skill_id`, so an operator who types an exact skill name gets zero signal from the one field guaranteed to carry it | Eval-set [§2.6](./semantic-skill-retrieval-eval-set.md#26-skill_id-is-not-an-indexed-field--measured-2026-10-01), confirmed by reading the shipped function: `ResetPasswordAdHoc` and `RecoverAcmeAccount` appear *only* in their own document's slug and match **nothing**; `LockUnlockUser` and `CheckServiceHealth` score body credit for **non-owners** (`D14`/`D17`/`D18` and `D18`) while their owner scores **0**. Of the 14 stratum-A queries only 3 name an identifier that exists, and the shipped scorer ranks the owning document first for **0 of those 3** |

Defect 2 also cuts the other way, and the eval-set measures it: the exact identifier
`KubePodNotReady` matches only **2 of 18** documents, while the prose paraphrase
`pod not ready` matches 5 and *still* ranks the scheduling guide above the alert;
whether the right document leads turns on the searcher appending the word
`kubernetes`, worth 2.0 as a tag.

Two consequences for the rest of this memo:

- The metric that detects defect 3 is **zero-relevant rate** — the fraction of
  queries whose whole top-5 holds nothing an operator would accept — not zero-hit
  rate. §7.2 now lists it.
- Every rank-sensitive metric must be reported **twice**: as returned, and over
  de-duplicated documents. Otherwise a de-duplication fix and a ranking fix are
  indistinguishable in the aggregate. Since 2026-10-01 the two coincide on the dev
  corpus — which is exactly why the variant must be kept: it is the only thing that
  would notice a regression if overlapping sources were re-registered.

The offline reproduction was validated against the audit trail's recorded `skill_ids`
for every cross-checked query whose catalog had not drifted, so it is a valid harness.
It can no longer be validated that way — the trail records the 30-row era — and the
eval-set §3 now validates the 18-row re-run three other ways (reproducing the pinned
32-of-63 from the old pool column, old-pool-is-a-prefix-of-new for all 63 queries,
and corpus agreement with Postgres and the service's own status endpoint). Where the
trail *does* differ — `argocd health check` formerly led with the now-retired
`platform-runbooks/web-checks/inventoryhealth` — that is catalog drift, and it is why
labels must pin a snapshot rather than reuse recorded results.

## 3. Infrastructure reality — corrections to the roadmap framing

### 3.1 `pgvector` is absent from the deployed image

`postgres-0` runs `postgres:16-alpine`
([`postgres-statefulset.yaml:18`](../../shared/platform-ops/gitops/dev-k8s/base/infra/postgres-statefulset.yaml)).
Queried live: `pg_available_extensions` returns **61** rows, and **none** matches
`%vector%` — the catalog view that lists what the server *can* install does not
offer it, so a `CREATE EXTENSION vector` issued today fails. Enabling it requires an
image change (the usual candidate being a pgvector-bundled Postgres 16 image), i.e. a
deployment-manifest edit, a new image reference in the gitops base, and a
StatefulSet rollout — not a `SKILLS_*` env toggle.

### 3.2 The Postgres StatefulSet is shared — the blast radius is all durable state

One `postgres` StatefulSet with a **1 Gi** `local-path` PVC
(`postgres-data-postgres-0`) hosts **four** databases: `audit`, `skills`,
`incidents`, `sessions`. Current usage is small — audit 33 MB, sessions ~10 MB,
skills 9 MB, incidents 8 MB, postgres ~7.5 MB, ≈67 MB of 1 Gi — so *storage* is not
the constraint (18 × 768-dim × 4 B ≈ 55 KB; even 10,000 × 1024-dim ≈ 41 MB).
The constraint is that swapping the image touches the audit trail, the session
store, and the incident store at the same time. That is a real, reviewable change
with a rollback story to write, and it should not be presented as free.

### 3.3 An embedding host already exists — with embeddings switched off

The SPEC-028 reference hosting is deployed and running: namespace `llm-hosting`,
`ollama/ollama:latest`, up 36 days, reachable in-cluster as
`http://ollama.llm-hosting.svc:11434/v1` — already wired into agent-service as
`LUBAN_BASE_URL`. Probed read-only:

| Probe | Result |
|---|---|
| `POST /api/embed` | **HTTP 501** — error body: "This server does not support embeddings. Start it with `--embeddings`" |
| `POST /v1/embeddings` | Same message, OpenAI error shape |
| `GET /api/tags` | 200 — one model: `qwen3:1.7b` (chat, 1.4 GB) |
| Deployment `args`/`command` | **empty** — the container serves with defaults |

So the cheapest embedding path is *nearly* free: the server exists and is already
in the cluster's trust boundary, but it needs the embeddings flag enabled and an
embedding model pulled (no embedding model is present). Two hygiene notes:
`ollama/ollama:latest` is an **unpinned tag**, against the SPEC-028 R-3
fixed-point-pinning convention; and `OLLAMA_API_KEY` *is* set on the live
deployment, yet an unauthenticated loopback probe was answered with 200/501 rather
than 401 — whether that is loopback trust or an unenforced key needs a deliberate
check (§11) before skills-hub depends on it.

### 3.4 skills-hub holds no model credential today

skills-hub's pod environment comes from the shared `platform-runtime-config`
ConfigMap plus `skills-hub-runtime-secrets`. Live inspection shows only `SKILLS_*`
variables — **no** `DASHSCOPE_API_KEY`, `LUBAN_API_KEY`, or `AGENTSCOPE_API_KEY`
(those are on agent-service, whose secret ref is separate). Its outbound
dependencies today are the `skills` database, configured git/local sources, and
audit-service. No NetworkPolicy restricts skills-hub egress (the namespace has
only `acme-admin-allow-tool-gateway` and `tool-gateway-browser-sidecar-deny-cdp`).

Consequence: choosing an **external** embedding API adds a new secret, a new egress
path, and a billable call to a service that currently has none of the three.
Choosing the **in-cluster** Ollama adds a service-to-service call inside the
cluster and no credential at all. That asymmetry should drive the provider
decision (§6.3), and the external option carries a data-egress question that is a
decision, not plumbing: skill bodies quote internal hostnames, URLs, and procedure
detail.

## 4. Substrate options

### 4.1 Option A — `pgvector` via image swap (the roadmap's current assumption)

Add the extension to the shared Postgres and store `vector(dim)` in a sidecar table
(§5.2). SQL-side similarity, mature ANN indexes (HNSW / IVFFlat), and the vector
lives next to the rows it describes, so source/tag filters and similarity compose
in one query.

Cost: an image swap on the StatefulSet holding all four databases (§3.2), a gitops
base change, a rollout and rollback plan for durable state, plus an ANN tuning
surface (`m`, `ef_construction`, `ef_search`, or `lists` + `ANALYZE`) that buys
nothing at 18 rows. This is the right answer at catalog scale and the wrong first
step now.

### 4.2 Option B — adopt an agentscope RAG store (rejected)

agentscope 2.0.8 ships `agentscope.rag` with `VectorStoreBase`, `VectorRecord`,
`VectorSearchResult`, `KnowledgeBase`, `ApproxTokenChunker`, and four concrete
stores: **`ElasticsearchStore`, `MilvusLiteStore`, `QdrantStore`, `MongoDBStore`**.
There is **no pgvector store**.

So adopting the RAG module wholesale means either standing up a new server
(Qdrant / MongoDB / Elasticsearch — strictly worse than reusing the Postgres that
already holds the skills) or accepting `MilvusLiteStore`'s embedded, pod-local file
store. The latter fails for the same reasons the SPEC-064 context offloader was
kept unwired: the deployment is `replicas: 1` with ephemeral storage, so a
pod-local index is invisible to any future replica and lost on reschedule, while
the authoritative skill rows survive in Postgres. A retrieval index that can vanish
while its source of truth persists is a split-brain, not a cache.

The adopt-worthy surface is `agentscope.embedding` (§6.2), not `agentscope.rag`.

### 4.3 Option C — sidecar `real[]` + in-process exact cosine (recommended first substrate)

Store the vector as a plain Postgres array in a sidecar table (§5.2), load the
catalog's vectors, and compute exact cosine in Python. At 18 documents × 768
dimensions that is 13,824 floats — a single small query and a few hundred
microseconds of arithmetic, exact and with **no ANN recall loss at all**. Since
2026-10-01 the stored row count and the distinct-document count are the same 18
(§2.3 defect 1), so there is no longer a cheaper-to-embed subset to aim at; when the
corpus carried 30 rows for 18 documents, embedding rows rather than documents would
have cost 23,040 floats and twice the embedding work for identical content — which
is why §4.4's de-duplication still comes first, and why it has to be enforced in the
product rather than left to a tidy dev config.

Properties that matter here:

- **No extension, no image swap, no new server.** Works on the `postgres:16-alpine`
  that is running now.
- **Identical schema to Option A.** Only the column type (`real[]` → `vector(n)`)
  and the index change, so promoting to `pgvector` later is an ALTER, not a data
  migration or a redesign.
- **Explainable.** Exact similarity over the whole catalog is auditable and
  reproducible; an approximate index is neither, which matters when a retrieval
  decision has to be defended in an incident review.
- **Bounded by scale, honestly.** It stops being sensible when the catalog grows
  past a few thousand skills or when per-query latency budgets tighten. That is a
  *recorded trigger* (§10), not a reason to pre-buy the index now.

### 4.4 Option D — improve the lexical baseline first (cheapest; may be sufficient)

The paraphrase failure has deterministic fixes that need no model, no vector, and
no new dependency. **The first two are now measured against live evidence (§2.3)
and are cheaper than anything else in this memo:**

- **Finish collapsing duplicate content in `rank()`.** *Configuration half done
  2026-10-01.* 12 of 30 corpus rows were byte-identical and 32 of 63 real queries
  returned fewer distinct documents than result slots (§2.3 defect 1); removing the
  overlapping `SKILLS_SOURCES` registration took that to **0 of 63** and reclaimed
  the wasted slots — measured, not predicted. But nothing in the *product* changed:
  `rank()` still has no content-hash de-duplication before truncating to `limit`, and
  `parse_sources` still accepts two sources covering the same files, so the next
  overlapping registration silently reproduces the defect. De-duplicating in `rank()`
  (or rejecting the overlap at ingestion) is the remaining highest-value change here
  and needs no ranking change at all.
- **Index `skill_id` — the cheapest fix on the list, and the only one that reaches
  defect 5.** One added scored field: no new dependency, no schema change, no image
  question. Measured on its own it moves combined top-1 correctness **0.500 → 0.526**
  and stratum-A identifier recovery **0/3 → 1/3**; combined with CamelCase splitting
  it reaches **3 of 3** (eval-set [§8.2](./semantic-skill-retrieval-eval-set.md#82-candidates-in-the-pre-registered-cost-order)).
- **Weight tokens by document frequency, and damp document length.** A corpus-derived
  IDF table (`ln((1+N)/(1+df))+1`) removes the stopword problem with no hand-written
  list to maintain, and a sublinear length norm (`1/log2(2 + len(body)/1000)`) removes
  the **6.8×** sample-vs-runbook advantage (§2.3 defect 4).
- **Tokenize CamelCase.** Splitting `KubePodCrashLooping` into `kube/pod/crash/looping`
  makes every alert title matchable at the 3.0 weight, and a stemming or trigram step
  lets `crashloop` reach the `CrashLoopBackOff` tag (§2.3 defect 2).

  **The alphabetical tie-break change this memo recommended is struck.** Replacing the
  `skill_id`-ascending tie-break with anything relevance-aware was listed here as part
  of defect 2's fix. Measured, it contributes **nothing**: it is numerically identical
  to CamelCase splitting alone on every metric for every stratum, because IDF weighting
  already breaks the `D06`/`D11` tie on the merits, so the alphabetical fallback never
  fires. Dropping it removes a change that would touch the byte-identical-ordering
  invariant for zero measured gain.
- **Cover-density ranking.** PostgreSQL `ts_rank_cd` / `ts_rank` over the existing
  `to_tsvector` GIN index weights phrase proximity and term frequency, which the
  current flat per-token point total ignores. This is an ordering improvement —
  exactly the axis §2.2 identifies as unmeasured.
- **Trigram tolerance.** A `pg_trgm` GIN index (also absent from the stock image —
  it needs the `postgresql-contrib` package, a smaller ask than pgvector but still
  an image question) gives typo and partial-token tolerance.
- **A curated alias map.** `KubePodNotReady ↔ "pod won't start" ↔ "pod not ready"`,
  `PVC storage exhaustion ↔ "disk full"`, and so on, expanded into the query token
  set before scoring. This fixes the precise case the vector store is invoked for,
  deterministically, with the synonym list itself reviewable as an artifact.

Honest cost: an alias map is manual curation and scales badly — but at 18 documents
across 2 sources it is a bounded, reviewable artifact, and every entry is
explainable to an operator in a way a cosine score is not. The first two bullets are
cheaper still and address defects that are already measured rather than
hypothesised. **If Option D closes the measured gap, no embedding work is needed at
all**, which is why §10 puts it before the substrate decision rather than after.

### 4.5 Comparison

| | A — pgvector | B — agentscope RAG store | **C — sidecar `real[]`** | D — better lexical |
|---|---|---|---|---|
| New server | no | **yes** (or pod-local file) | no | no |
| Extension / image swap | **yes** | no | no | trigram: yes; rank/alias: no |
| Model dependency | yes | yes | yes | **no** |
| New credential in skills-hub | maybe | maybe | maybe | **no** |
| ANN recall loss | possible | possible | **none (exact)** | n/a |
| Explainable to an operator | weak | weak | medium | **strong** |
| Fixes paraphrase recall | yes | yes | yes | alias map: yes |
| Improves ordering in a saturated top-5 | yes | yes | yes | **yes** |
| Reversible without migration | no | no | **yes** | **yes** |
| Scales to 10k+ skills | **yes** | yes | no | partly |

## 5. Schema design on the `skills` table

### 5.1 Do not add vector columns to `skills`

Three concrete couplings make an in-table column expensive:

1. `_ROW_COLUMNS` / `_row_names()` / `_row_to_skill()` enumerate the row shape by
   hand ([`skill_store.py:237-292`](../../products/skills-hub/src/skills_hub/services/skill_store.py));
   every `SELECT` in the store lists columns explicitly, so a new column is touched
   in five places, including the insert and its `ON CONFLICT` update list.
2. Rows round-trip through the Pydantic `Skill` model, which is a **shared
   contract** surface (`shared/shared-contracts/schemas/skill.schema.json` and
   `skill-format.md`, enforced by the ingestion pipeline). A vector field would
   either leak into every API response — 768 floats per skill in a search result —
   or require a contract change and schema version bump to *hide* it again.
3. `replace_source` does a per-source `DELETE` + insert inside one transaction, so
   an in-table vector is recomputed or lost on every sync cycle, with no way to
   tell a stale vector from a fresh one.

Vectors are an **index artifact, not skill content**. They belong beside the table,
not in it.

### 5.2 Sidecar table (recommended shape)

```sql
CREATE TABLE IF NOT EXISTS skill_embedding (
    skill_id     TEXT PRIMARY KEY
                 REFERENCES skills(skill_id) ON DELETE CASCADE,
    model_id     TEXT        NOT NULL,  -- e.g. nomic-embed-text:v1.5
    dim          INTEGER     NOT NULL,  -- must match SKILLS_EMBEDDING_DIM
    content_hash TEXT        NOT NULL,  -- sha256 of the embedded text
    embedding    real[]      NOT NULL,  -- pgvector variant: vector(768)
    embedded_at  TIMESTAMPTZ NOT NULL
);
```

Why each element is there:

- **Idempotent DDL** matches the store's existing convention
  (`CREATE TABLE IF NOT EXISTS` + `ALTER ... ADD COLUMN IF NOT EXISTS`, run from
  `initialize()`), so no migration tool is introduced.
- **`ON DELETE CASCADE` is required, not decorative.** `replace_source` deletes by
  `source_id` and re-inserts; without the cascade, orphan vectors survive every
  sync and a re-added skill could be matched against a vector computed from its
  previous content.
- **`model_id` + `dim` + `content_hash` make staleness a query, not a guess.** A
  model change invalidates every row (`model_id` differs); a body edit invalidates
  one row (`content_hash` differs). Backfill and re-embed become
  `SELECT ... WHERE content_hash <> ...`, and a half-migrated catalog is
  detectable instead of silently mixing embedding spaces.
- **`real[]` vs `vector(n)` is the only Option-C/Option-A difference.** Everything
  above — the table, the cascade, the provenance columns, the sync integration —
  is identical, so the pgvector decision stays open and reversible.
- **Storage is a non-issue** (§3.2): 18 rows ≈ 55 KB; 10,000 rows at 1024 dims
  ≈ 41 MB against ≈67 MB used of 1 Gi today.

### 5.3 Index posture

- **At 18 rows: no index.** A sequential scan is exact, and an ANN index would add
  tuning parameters and recall loss to a table that fits in a single page range.
- **pgvector at scale:** HNSW with `vector_cosine_ops` (tune `m`,
  `ef_construction`, query-time `ef_search`) is the default choice; IVFFlat needs a
  populated table, a chosen `lists`, and `ANALYZE` before it is useful. Either way
  exact scan remains *correct* without an index, which is exactly why the ANN
  decision can be deferred to a recorded scale trigger.
- **Cosine, not L2 or inner product.** Skill bodies differ in length by an order of
  magnitude (1,094–11,778 chars), so magnitude carries document length rather than
  relevance; normalize and use cosine distance consistently on both sides.

### 5.4 Where a vector must never go

- Not in the `Skill` model or any search/list/get response payload.
- Not in an audit `details` blob. `skill_searched` already carries `query`,
  `limit`, `result_count`, and `skill_ids`; 96 searches × 768 floats would swamp
  the audit store and make the trail unreadable. Record the **retrieval mode** and
  semantic hit count instead (§8).
- Not in evidence frames or session transcripts.

## 6. Embedding strategy

### 6.1 What gets embedded

One vector per skill over `title + tags + description + body`. At an average of
3,083 characters (max 11,778) the whole document fits inside every common embedder's
window, so **no chunking is needed** at this scale. Chunking
(`agentscope.rag.ApproxTokenChunker`) becomes relevant only if bodies grow past the
model window; it also multiplies rows per skill, which breaks the `skill_id`
primary key in §5.2 and needs a chunk-level table. Defer it, and record it as a
trigger.

The query must be embedded with the **same** `model_id`, and a mismatch must fail
closed rather than silently compare incompatible spaces — comparing a 768-dim query
against 1024-dim rows is either an error or nonsense, never a result.

### 6.2 Build vs adopt — what agentscope 2.0.8 already ships

Verified in the pinned venv (`agentscope.__version__ == "2.0.8"`, specifier
`>=2.0.4,<3.0`):

- `agentscope.embedding` exports `EmbeddingModelBase`, `EmbeddingModelCard`,
  `EmbeddingUsage`, `EmbeddingResponse`, and concrete **`DashScopeEmbeddingModel`,
  `OpenAIEmbeddingModel`, `OllamaEmbeddingModel`, `GeminiEmbeddingModel`**, plus
  `EmbeddingCacheBase` / `FileEmbeddingCache`.
- `agentscope.rag` exports the store and chunker surface described in §4.2.

Per the standing SPEC-018 discipline (prefer agentscope's out-of-box surfaces over
bespoke clients, and score them against the four-point adoption gate), the
**embedding client should be adopted, not written**: `OllamaEmbeddingModel` matches
the in-cluster host already deployed (§3.3), and `DashScopeEmbeddingModel` matches
the provider whose key agent-service already holds. Both need an adoption-gate
pass in a spec — neither is adopted by this memo.

Two platform guardrails must survive any adoption:

- **Embedders must never enter the chat model catalog.**
  [`providers/base.py:13-17`](../../products/agent-platform/src/agent_service/providers/base.py)
  defines `_NON_CHAT_MARKERS` including `"embedding"`, and tests pin that
  `text-embedding-v3`, `bge-large-embedding`, and `deepseek-embeddings` are dropped
  by live discovery. An embedding model appearing in the operator-facing SPEC-026/027
  model list would be a regression, and the filter must stay test-pinned.
- **`FileEmbeddingCache` must not be used as deployed.** It writes each vector as a
  binary file under `cache_dir` (default `./.cache/embeddings`) on the local
  filesystem. With `replicas: 1` and ephemeral pod storage that cache is lost on
  reschedule and invisible to any second replica — the SPEC-064 offloader objection
  again. The Postgres sidecar **is** the cache; a second, pod-local one adds a
  divergence path for no benefit.

### 6.3 Where the embedding call lives, and which provider

Placement:

| Placement | Assessment |
|---|---|
| **skills-hub calls the embedder** | Recommended. Keeps the retrieval boundary intact — callers still ask skills-hub for ranked skills and never see a vector. Costs skills-hub a new outbound dependency and (for an external provider) a new secret. |
| Caller embeds and passes a vector | Rejected. Leaks model coupling into the HTTP contract, lets each caller pick the embedding space, and turns `skills.search` into an unauthenticated-by-shape vector oracle. |
| tool-gateway embeds | Rejected. The gateway is a policy/dispatch choke point, not a retrieval engine; it would also put a model call on the tool hot path. |

Provider:

| Provider | Cost / egress | What it needs |
|---|---|---|
| **In-cluster Ollama** (`llm-hosting`) | Free, no egress, inside the existing trust boundary; already reachable at the URL agent-service uses | Embeddings enabled on the server (currently **501**, §3.3), an embedding model pulled (none present), and the image **pinned** rather than `:latest` |
| DashScope `text-embedding-v4` | **Billable**, external egress | A new entry in `skills-hub-runtime-secrets`, plus an operator decision on skill body text leaving the cluster (§3.4) |

Recommendation: if a model embedder is used at all, **in-cluster Ollama with
skills-hub as the caller**. It is the only option that adds no credential, no
egress, and no spend — and it keeps a retrieval-quality change from becoming a
cost line. Note that this makes retrieval quality dependent on a
reference-hosting deployment that is documented as an optional, out-of-band
install; that dependency has to be explicit in the gating posture (§9), including
what happens on a cluster where `llm-hosting` does not exist.

### 6.4 Determinism, versioning, and cost accounting

- **Pin the model id and version** and store both per row (§5.2). An embedding is
  an artifact of a specific model; an unpinned `:latest` server plus an unpinned
  model name means the index can silently change meaning across a restart.
- **Treat a model change as a full re-embed**, driven by the `model_id` column,
  never as an in-place mix.
- **Embedding is billable the same way a chat turn is.** SPEC-065 R-1 established
  `agent_llm_tokens_total{provider,model,direction}` for model calls; an embedder
  call consumes tokens too. Any external provider needs the same accounting
  posture, and §7 lists embed cost per sync and per query as a measured criterion.

### 6.5 When embeddings are computed

- **Sync path (recommended).** `replace_source` is the only place that knows a
  document changed, so computing embeddings there keeps model latency off the
  search hot path entirely. The hard requirement is **fail-open**: an embedder
  timeout must not fail a sync, or a model outage silently stops the catalog from
  updating — a worse failure than degraded ranking. Log it, emit a metric, leave
  the row unembedded, and let search fall back to lexical for that skill.
- **Lazy on first query (rejected).** Puts a model round-trip on the search path,
  makes p95 non-deterministic, and risks the tool-gateway's 10.0 s timeout.
- **Backfill** is trivial at this scale: 18 distinct documents, one pass, seconds.

## 7. Recall and latency assessment criteria — the gate

This is the section that decides whether anything gets built. It is deliberately
written so that a **null result is a publishable outcome**: "lexical is good enough
on our corpus" closes the backlog row as honestly as "vectors win" opens a spec.

### 7.1 Evaluation set

- **Seed from real traffic.** The audit trail already holds **63 distinct queries**
  in `skill_searched.details->>'query'` (§2.2), and they have been extracted — see
  [semantic-skill-retrieval-eval-set.md](./semantic-skill-retrieval-eval-set.md).
  Extracting them is a read-only query and needs no new instrumentation, which is
  the strongest argument for measuring first: the seed data already existed. Note
  that 14 of the 63 bear a target identifier and cannot discriminate retrieval
  quality (§2.2), so they are held as a regression stratum and excluded from
  headline metrics.
- **Extend with a targeted paraphrase set** aimed at the hypothesised failure mode:
  "pod won't start" vs a runbook titled `KubePodNotReady`; "disk full" vs PVC
  storage exhaustion; "can't log in" vs an account-recovery runbook; "cert expired"
  vs TLS rotation. These are the queries lexical provably cannot match, and they
  must be labeled rather than assumed.
- **Operations must review the labels.** Each (query, skill) pair gets an explicit
  relevance judgment from someone who owns the runbooks. An unreviewed set measures
  the author's guesses, not retrieval quality, and the whole exercise is worthless
  without it.
- **Version and store the labeled set** (a committed fixture, not a spreadsheet)
  so a future catalog change re-runs the same evaluation instead of trusting a
  stale one.
- **State the sample size honestly.** 63 real queries (49 of them discriminating)
  plus a paraphrase set over an **18-document catalog carried in 18 rows across 2
  sources** is *small*. Report confidence intervals, and treat any difference inside
  the noise band as **no evidence of improvement**.

### 7.2 Metrics, and the baseline each must beat

Every metric is computed for the **lexical baseline first**, on the same set, with
the same harness. Nothing is promoted on an unmeasured baseline.

| Metric | Definition | Why it matters here |
|---|---|---|
| **Zero-hit rate** | fraction of queries returning 0 hits | **Already 0/96 live.** There is no headroom on this axis — do not build a recall instrument to fix a non-existent recall failure |
| **Zero-relevant rate** | fraction of queries whose entire top-5 holds no grade ≥1 document | **The metric that actually matters here.** §2.3 defect 3 shows zero-hit cannot detect a useless answer: `argocd health check` scores 20.0 on an unrelated document. Report for every candidate, lexical included |
| **Distinct-document variants** | every rank-sensitive metric computed twice — as returned, and over de-duplicated documents | Without both, a de-duplication fix and a ranking fix are indistinguishable in the aggregate (§2.3 defect 1) |
| **Precision@5** | relevant hits within the top 5 | The top-5 is saturated (mean 4.72/5), so *ordering inside it* is what an operator or the agent actually experiences |
| **Recall@5 / Recall@10** | relevant hits found within k | The classic vector-store claim; must be shown against labels, not asserted |
| **MRR** | mean reciprocal rank of the first relevant hit | Single-number summary of "is the right runbook first" |
| **nDCG@10** | graded relevance, position-discounted | Only worth computing if labels are graded (e.g. 0/1/2) rather than binary |
| **Rank stability** | fraction of queries whose top-1 changes vs baseline, and how many changes are *improvements* | A hybrid that reshuffles already-correct answers is a regression even at equal nDCG |
| **Search latency p50/p95** | end-to-end route time, reported with and without the embed call | Must stay well inside the tool-gateway's **10.0 s** `REQUEST_TIMEOUT_SECONDS` |
| **Sync-path embed cost** | time and tokens per document embedded during `replace_source` | Sync currently has no model dependency; adding one has a budget |
| **Embed spend** | tokens/bytes sent to any external embedder per sync and per query | Billable the same way a chat turn is (§6.4); zero for the in-cluster option |

### 7.3 Go condition

Promote to a spec **only if all** of the following hold:

1. Hybrid (or vector) retrieval beats the lexical baseline on **Precision@5 or MRR**
   by a margin **outside the noise band** on the operations-reviewed set.
2. It does **not regress** the queries lexical already answers correctly — measured
   by rank stability, not by aggregate score alone.
3. Added p95 latency stays comfortably inside the 10 s tool timeout, including the
   query-embedding call, with the embedder cold.
4. The fail-open path is demonstrated: with the embedder unreachable, search still
   returns correct lexical results and the pod stays `ready`.

Otherwise: **record the measurement, keep lexical, and close or re-gate the backlog
row** with the numbers attached. Revisit on a recorded trigger — catalog growth past
the scale threshold in §10, a named operator complaint with a reproducible query, or
a real cluster of zero-hit searches appearing in production audit data.

## 8. Retrieval contract — hybrid, and what must not silently change

If §7 says go, the design is a **candidate-expansion hybrid**, not a replacement:

1. Keep `rank()` authoritative for lexical scoring — unchanged, still shared by
   both backends.
2. Add semantic top-K as an **extra candidate source**, unioned into the candidate
   set before ranking.
3. Fuse with an explicit, explainable rule. **Reciprocal-rank fusion** is the usual
   choice precisely because it needs no score calibration between an unbounded point
   total and a cosine in [0,1].

Four things must be decided explicitly, because each is currently an invariant:

- **`SearchHit.score` is a public, explainable number.** It is returned as `score`
  in the search response and means "title 3 / tag 2 / body 1×≤5". A cosine
  similarity is not comparable to it. Either keep `score` as the lexical component
  and add a separate additive field (a **contract change**, versioned, with the JSON
  schema and portal rendering updated), or make fusion **rank-only** and leave
  `score` untouched. **Do not silently redefine `score`** — the explainability is
  part of why the current design is defensible in an incident review.
- **The byte-identical-ordering invariant must be narrowed on purpose.**
  `InMemorySkillStore` has no Postgres and therefore no sidecar table. Either
  (a) semantic retrieval is **Postgres-only** and the guarantee becomes "identical
  when semantic is disabled", pinned by a test, or (b) the memory store grows the
  same cosine fusion, which would require embedding vectors in unit tests — an
  unacceptable model dependency in CI. **Recommend (a).**
- **A similarity floor is a safety control, not a tuning knob.** Under the
  grounded-guidance and anti-fabrication posture, a weak semantic match must not be
  presented to the agent as team-owned runbook authority. Below the floor, fall back
  to lexical-only and say so; a confident-looking but irrelevant runbook is worse
  than no runbook, because the agent is instructed to cite what it finds.
- **Governance stays exactly where it is.** Reads keep flowing
  `skills.search` → tool-gateway policy → skills-hub → `skill_searched` /
  `skill_retrieved` (SPEC-029). Semantic retrieval must not become a path that
  bypasses the gateway or the audit vocabulary; record the retrieval mode
  (`lexical` / `hybrid`) and the semantic hit count in `details` — never the vector
  (§5.4).

## 9. Feature-gating posture

Default-off and additive, following the SPEC-011 / SPEC-064 precedent that an unset
deployment stays byte-identical:

| Knob | Default | Effect when unset |
|---|---|---|
| `SKILLS_SEMANTIC_ENABLED` | `false` | Retrieval is exactly today's lexical path; no embedder is contacted, no sidecar table is required |
| `SKILLS_EMBEDDING_BASE_URL` | unset | In-cluster Ollama URL when enabled; absent + enabled must fail startup |
| `SKILLS_EMBEDDING_MODEL` | unset | Pinned model id, stored per row (§5.2) |
| `SKILLS_EMBEDDING_DIM` | unset | Must match stored rows; a mismatch fails startup rather than corrupting a comparison |
| `SKILLS_SEMANTIC_TOP_K` / `SKILLS_SEMANTIC_MIN_SCORE` | bounded defaults | Candidate-set size and the safety floor (§8) |

Non-negotiables:

- **Fail open to lexical.** Any embedder error, timeout, dim mismatch, or missing
  row yields lexical results. The search route must never 500 because a model is
  down — the same never-raise posture `skill_draft.py` already holds (it falls back
  to a facts-only skeleton rather than failing).
- **Readiness must not gain a model dependency.** `PostgresSkillStore.ready()` is a
  bare `SELECT 1`, and `/health/ready` is dependency-aware. An unreachable embedder
  must degrade ranking, never take the pod out of service — otherwise an optional
  retrieval enhancement becomes an availability single point of failure, and on a
  cluster where the optional `llm-hosting` install is absent skills-hub would never
  become ready.
- **Startup validation follows the existing convention.** New `SKILLS_*` settings
  get `parse_*` helpers raising `SettingsError` in
  [`config.py`](../../products/skills-hub/src/skills_hub/core/config.py), so a
  malformed value fails fast instead of surfacing mid-search.
- **Metrics parity is a build gate, not a nicety.** A new `skills_*` family must be
  added to skills-hub's `OTEL_MIRROR_FAMILIES`: `validate-dashboards` in
  `make verify` AST-cross-references every dashboard metric against the eight
  services' mirrored families, so an unmirrored family fails the gate.
- **The chat model catalog stays chat-only.** `_NON_CHAT_MARKERS` keeps embedding
  models out of live discovery (§6.2) and must remain test-pinned.

## 10. Go/no-go gates and next decision

1. **CLOSED 2026-10-01 — the measurement-first step is done.** The evaluation set is
   **built and labeled** (eval-set [§7.1](./semantic-skill-retrieval-eval-set.md#71-the-labeled-set),
   [labels fixture](./semantic-skill-retrieval-labels.json)) over its §6.4 minimum
   viable scope: **38 queries × 18 documents = 684 judgments** (173 non-zero), pinned
   to a `body_md5` per document so that a catalog move invalidates them explicitly
   rather than silently. The lexical baseline is published with every metric this gate
   asked for (eval-set §8.1). **The gate is satisfied, so a retrieval change is now
   approvable — and the measurement says the expensive one is not needed.** Two limits
   recorded rather than glossed: this is an *author-proposed, operator-ratified* label
   set, not blind operations labeling, so Cohen's κ is uncomputable (a deviation from
   eval-set §6.3 rules 4–5, authorized by the operator); and the traffic behind
   stratum B is demo/e2e rather than sustained operator triage.
2. **Work the lexical fixes in cost order, measuring each — *measured 2026-10-01, and
   the cheap step closed the gap*.** First the *product* half of de-duplication and
   the tokenizer fixes (§4.4, measured as defects in §2.3); then `ts_rank_cd` cover
   density and a curated alias map; then, only if an image change is already accepted,
   `pg_trgm`. **If any cheaper step closes the measured gap, everything below is
   cancelled and the backlog row closes** — a null result is a publishable outcome,
   not a failure.

   **That condition is now met.** Simulating the §4.4 fixes offline against the
   labeled set — each candidate fidelity-gated on reproducing the shipped scorer
   exactly with its own flags off, **38/38 identical** — moves combined top-1
   correctness **0.500 → 0.711** and stratum-C top-1 **0.333 → 0.611**, with MRR,
   MRR(2) and nDCG@10 gains whose bootstrap 95% CIs exclude zero and an exact sign
   test at **p = 0.0117** (eval-set §8.2–§8.3). The winning combination is
   IDF weighting + sublinear length norm + CamelCase splitting + indexing `skill_id`;
   no single one of them reaches significance alone. **Gate 3 is therefore not
   reached: no embedding work is authorized and the backlog row closes** (eval-set
   [§8.5](./semantic-skill-retrieval-eval-set.md#85-decision-rule-outcome)). The
   decisive fact is that **there is no recall gap to recover** — zero grade-2
   documents are missing from the top 10 on any of the 38 queries, under the baseline
   as well as under every candidate, and `R@5(=2)` on real traffic is already 1.000.

   De-duplication's *configuration* half was executed on 2026-10-01 under separate
   operator authorization, and its effect is now measured rather than predicted:
   crowding **32 of 63 → 0 of 63**, no top-1 changed, 28 pools widened. That changes
   what remains of this step — it is no longer "does de-duplication help" but "should
   the product enforce what the dev config happens to get right", i.e. content-hash
   de-duplication in `rank()` and/or overlap rejection in `parse_sources`. It is
   still the cheapest item on the list and still needs no labels to justify, though
   the labels remain the gate for anything that reorders results.

   Defects 2 and 3 are untouched by it: `pod keeps restarting CrashLoopBackOff`
   still ranks the scheduling guide above `KubePodCrashLooping` on an alphabetical
   tie-break at 10.0, and `argocd health check` still scores 20.0 on a sample app's
   health check. **Those are now graded rather than awaiting labels.** Defect 2's fix
   is inside the winning combination. Defect 3's is not, and is not available to any
   lexical candidate at all — which is the one part of this gate that stays open.

   **What the cheap step does *not* fix: abstention.** Zero-relevant rate is unchanged
   at **4/38** by every candidate including the best, and the same four queries still
   return confident, wholly irrelevant answers. This is structural, not a tuning
   failure: a scorer that admits any document with `score > 0` **cannot abstain**, and
   better ranking cannot create an abstention it was never able to express — a dense
   retriever is worse still, since it always finds a nearest neighbour. Fixing it needs
   a score threshold or an explicit "nothing applies" path, and a threshold is a
   **product decision** that trades this failure against silently dropping documents
   that are genuinely relevant but weakly matched. The labels do not authorize that
   trade-off and this memo does not make it. Two of the four are vocabulary gaps no
   retriever can close — there is no ArgoCD and no database-pool document in the
   corpus — which is a content problem. **This warrants its own backlog row**
   (eval-set [§8.4](./semantic-skill-retrieval-eval-set.md#84-what-no-lexical-candidate-fixes)).
3. **Not reached — 2026-10-01.** Gate 2's cheap step closed the measured gap, so the
   substrate question this gate exists to answer is not live. *If it ever becomes
   live*, approve the substrate: sidecar `real[]` + in-process
   exact cosine (Option C — no extension, no image swap, reversible), **or** the
   `postgres:16-alpine` → pgvector image swap on the shared StatefulSet now,
   accepting the blast radius over `audit`, `skills`, `incidents`, and `sessions`
   plus a written rollback plan. Nothing measured supports either today, because the
   **recall** premise that would justify a vector store is measured absent: 0 of 38
   queries have a grade-2 document outside the top 10 (gate 2, eval-set §8.1).
   **Gates 4, 5 and 6 are conditional on this one and are therefore also not
   reached** — they are retained as written so that a reopened row inherits them
   unchanged rather than having to re-derive them.
4. **If a model embedder is used, approve the provider and its egress posture:**
   in-cluster Ollama (enable embeddings, pull and pin an embedding model, no new
   secret, no egress, no spend) **or** DashScope (billable, external egress, a new
   `skills-hub-runtime-secrets` entry, and skill body text leaving the cluster).
5. **Record the scale trigger for pgvector now, as a number.** Exact in-process
   cosine is the right substrate at 18 documents and the wrong one at some larger
   count; "when it feels slow" is not a trigger. Propose: promote to pgvector at
   **>2,000 skills** or **search p95 >300 ms**, whichever comes first.
6. **Only then promote a spec.** Promotion needs §7's measurements in hand, the §8
   `score`-contract decision made, the byte-identical-invariant narrowing agreed,
   and the §9 gating posture accepted. **This memo authorizes none of it.**

## 11. Open questions for the first spec

- ~~Which fusion rule, and is `score` allowed to change meaning (contract version
  bump, portal rendering, JSON schema) or must fusion stay rank-only?~~ **Answered
  2026-10-02 as SPEC-066 OQ-1.** No fusion rule ships — the row closed against
  vectors — so the question reduces to whether the four lexical fixes may redefine
  `score`, and they may, **with no contract version bump**: `score` is in no
  `shared/shared-contracts` schema, is not portal-rendered, and is dropped by the
  tool-gateway connector's `_MATCH_KEYS`. Its *weighting* is nevertheless published
  prose in four places, which SPEC-066 R-9 updates. `skill_id` enters at
  `TAG_WEIGHT` (2.0), and the "do not silently redefine `score`" caution survives as
  a **decomposability** requirement (`weight × idf(token) × norm(document)`).
- ~~Is the byte-identical ordering invariant narrowed (semantic Postgres-only,
  recommended) or preserved (no semantic retrieval at all in the memory backend)?~~
  **Answered 2026-10-02 as SPEC-066 OQ-3: preserved as written, and this memo's
  recommendation to narrow it is not taken.** No ADR is raised. Narrowing was
  contingent on a semantic backend, which the measurement cancelled; what remains is
  a *lexical* scorer that must order identically on both backends, and SPEC-066 R-6
  makes that invariant **enforced** rather than documented, because SPEC-014 claims a
  parity test that does not exist. OQ-3 and OQ-5 are one decision — preserving the
  invariant forces widening the prefilter and rules out a SQL-side tokenizer.
- Does the in-cluster Ollama actually enforce `OLLAMA_API_KEY`? A loopback
  port-forward probe was answered with 200/501 rather than 401 (§3.3). Whether that
  is loopback trust or an unenforced key must be settled deliberately before
  skills-hub depends on the endpoint — and it is a question about the hosting
  manifests, not about retrieval.
- Should `ollama/ollama:latest` be pinned as part of this work, given the SPEC-028
  R-3 fixed-point-pinning convention?
- ~~Who owns the relevance labels, and how is the labeled set versioned so a catalog
  change re-runs the evaluation?~~ **Half-answered 2026-10-01.** Versioning is solved:
  the labels are a committed fixture pinning a `body_md5` per document, so a catalog
  move is mechanically detectable and forces re-grading rather than silently
  invalidating the numbers. **Ownership is not settled** — the set is
  author-proposed and operator-ratified, not operations-owned, and no second labeler
  has produced the κ §6.3 rule 4 requires. If this row is ever reopened, operations
  ownership of the label set is a precondition, not a follow-up.
- What is the pgvector scale trigger (§10.5), and who re-measures it?
- Does an embedding call belong in the audit vocabulary (e.g. a `skill_embedded`
  event per sync) or is a metric sufficient? Audit-event-type additions are a
  contract change and should not be made casually.
- If skill bodies are ever sent to an external embedder, does that need its own
  redaction pass? Skill bodies are already produced under the shared redaction
  vocabulary, but retrieval-time egress is a new direction for that text.

## Changelog

- 2026-09-30 — initial assessment. Evidence: static read of
  [`scoring.py`](../../products/skills-hub/src/skills_hub/services/scoring.py),
  [`skill_store.py`](../../products/skills-hub/src/skills_hub/services/skill_store.py),
  [`config.py`](../../products/skills-hub/src/skills_hub/core/config.py),
  [`skills.py`](../../products/skills-hub/src/skills_hub/api/routes/skills.py),
  [`skills_connector.py`](../../products/tool-gateway/src/tool_gateway/tools/skills_connector.py),
  [`providers/base.py`](../../products/agent-platform/src/agent_service/providers/base.py),
  and [`runtime_settings.py`](../../products/agent-platform/src/agent_service/runtime_settings.py);
  read-only live-cluster queries against `postgres-0` (`skills` corpus stats, `audit`
  `skill_searched` aggregates, `pg_available_extensions`, database sizes, PVC) and
  the `llm-hosting/ollama` deployment (image, args, model list, embeddings probe);
  inspection of `agentscope.embedding` and `agentscope.rag` in the pinned 2.0.8 venv.
  Recommendation: measurement-first; if semantics are then justified, sidecar
  `real[]` + exact cosine over pgvector, with lexical improvement (Option D) tried
  first. **Assessment only — no implementation, no embedding generated, no extension
  installed, no image swapped, no manifest changed, no ADR, and no spec promotion.**
- 2026-10-01 — **correction pass** after building the §7.1 evaluation set
  ([semantic-skill-retrieval-eval-set.md](./semantic-skill-retrieval-eval-set.md)),
  which required re-running the real
  [`scoring.py`](../../products/skills-hub/src/skills_hub/services/scoring.py)
  over a full corpus export and re-reading
  [`runtime-config.env`](../../shared/platform-ops/gitops/dev-k8s/base/skills-hub/runtime-config.env)
  and [`kustomization.yaml`](../../shared/platform-ops/gitops/dev-k8s/base/kustomization.yaml).
  Added **§2.3** with three measured defects: the corpus is 18 distinct documents
  carried in 30 rows (`md5(body)`: 12 byte-identical pairs) because a git source and
  two ConfigMap sources ingest the same files, so 32 of 63 queries return fewer
  distinct documents than result slots; CamelCase titles tokenize to one opaque
  token, so the exactly-right alert ranks 3rd for `pod keeps restarting
  CrashLoopBackOff` and loses its slot to an alphabetical tie-break; and `argocd
  health check` scores 20.0 on an unrelated document, proving zero-hit rate is not a
  recall proxy. **Corrected §2.2**: the claim that the 5-word query mode "confirms
  natural phrasing" was overstated — 14 of 63 queries carry a target identifier, so
  the masking hypothesis is untested rather than disproved. Retitled for the 18-document
  corpus; added zero-relevant rate and distinct-document metric variants (§7.2); added
  the two cheapest Option D fixes (§4.4); re-ordered §1 and §10 so candidates are
  measured in cost order and any cheaper fix that closes the gap cancels the rest.
  Read-only throughout: no product code, manifest, or configuration was changed.
- 2026-10-01 (second pass) — **§2.3 defect 1 resolved by configuration, and every
  corpus figure in this memo re-measured against the result.** The operator
  authorized the two cleanups the eval-set had surfaced and declined: the leftover
  `_idx_probe` table was dropped from the dev `skills` database (confirmed 0 rows,
  referenced by nothing in the repository), and the two local ConfigMap skill sources
  were removed from
  [`runtime-config.env`](../../shared/platform-ops/gitops/dev-k8s/base/skills-hub/runtime-config.env),
  the base [`kustomization.yaml`](../../shared/platform-ops/gitops/dev-k8s/base/kustomization.yaml)
  and the skills-hub deployment, leaving the `platform-skills` git source as the only
  route to `shared/platform-ops/skills`. Deployed to the dev overlay and verified:
  `source_count: 2`, `skill_count: 18`, 18 rows / 18 distinct `md5(body)`, both
  sources `last_error: null`. Re-running the real scorer over the re-exported corpus
  gives crowding **0 of 63** (was 32 of 63; 0 of 49 in the discriminating stratum,
  was 22 of 49), distinct documents in top-5 windows **309 of 315** (was 265), pool
  entries **526** (was 582), and — verified rather than assumed — **no query's top-1
  document changed**, with the de-duplicated old pool an exact prefix of the new one
  for all 63 queries and 28 pools widening by 88 candidates. Updated: front matter
  and evidence baseline (the pass was **not** read-only and is recorded as such),
  §1 finding 3 and its cost-ordered candidate list, §2.2 corpus table (re-tabulated
  as two dates, with the
  "total body bytes" label corrected — the 2026-09-30 figure was a `length(body)`
  character sum), §2.3 defect table and validation paragraph, §3.2 and §5.2 storage
  arithmetic, §4.1, §4.3, §4.4's first bullet, §5.3, §7.1 and §10 gates 1–2.
  **Defects 2 and 3 are unchanged and still reproduce**: `pod keeps restarting
  CrashLoopBackOff` still ranks the scheduling guide first on an alphabetical
  tie-break at 10.0 (the right alert moved 3rd → 2nd and no further), and `argocd
  health check` still scores 20.0 on an unrelated sample. §4.4 and §10 now frame the
  remaining de-duplication work as *enforcement in the product* — `rank()` still
  collapses nothing and `parse_sources` still accepts two sources covering the same
  files — rather than as an open measurement. No product code was modified; the
  changes are dev-overlay configuration, e2e/guide documentation, and this memo.
- 2026-10-01 (third pass) — **gate 1 executed and closed; the row's question is
  answered and the answer is a null result for vectors.** The eval-set's labeling
  pass ran over its §6.4 minimum viable scope (**38 queries × 18 documents = 684
  judgments**, 173 non-zero), was ratified by the operator, and is committed as
  [`semantic-skill-retrieval-labels.json`](./semantic-skill-retrieval-labels.json)
  with a `body_md5` per document so a catalog move invalidates it explicitly. Two
  more defects were measured and added to §2.3: **defect 4**, document-length bias
  and unweighted function words (`samples/*` bodies average **9,718 chars** against
  **1,424** for runbooks, a **6.8×** advantage, and body matches supply **70–100%**
  of the winning score wherever the lexical top-1 is graded 0), and **defect 5**,
  **`skill_id` is not an indexed field** — verified by reading the shipped `score()`,
  which touches `title`/`tags`/`body` and never the slug, so `ResetPasswordAdHoc`
  matches nothing and `LockUnlockUser`/`CheckServiceHealth` score body credit for
  *non-owners* while their owner scores 0. Defect 5 falsified §6.1's premise that the
  identifier-bearing stratum "matches trivially": the shipped scorer recovers the
  owner at top-1 for **0 of the 3** stratum-A queries whose identifier exists. §4.4
  accordingly gains the three fixes that were measured (`skill_id` indexing, IDF
  weighting, sublinear length norm) and **strikes the relevance-aware tie-break it
  had recommended** — that change is numerically identical to CamelCase splitting
  alone on every metric for every stratum, because IDF already breaks the tie on the
  merits, so it would touch the byte-identical-ordering invariant for zero gain.
  §10's gates were then decided rather than deferred: **gate 1 closed**, **gate 2
  measured** (combined top-1 **0.500 → 0.711**, stratum C **0.333 → 0.611**,
  MRR/MRR(2)/nDCG@10 CIs excluding zero, exact sign test **p = 0.0117**, stratum-A
  identifier recovery **0/3 → 3/3**, one mild regression), and **gate 3 not reached**
  — the recall premise is measured absent (**0** grade-2 documents outside the top 10
  on any query; `R@5(=2)` already **1.000** on real traffic), so per the
  pre-registered rule no embedding work is authorized and the backlog row closes.
  Gates 4–6 are retained as conditional-on-3 rather than deleted. Recorded honestly:
  the label set is **author-proposed and operator-ratified**, not blind operations
  labeling, so Cohen's κ is uncomputable (a deviation from eval-set §6.3 rules 4–5,
  operator-authorized); zero-relevant rate is **4/38** and is fixed by *no* lexical
  candidate, because a scorer admitting any `score > 0` cannot abstain — so §10
  gate 2 now carries an abstention note recommending a **separate backlog row** for
  it as a product/contract question. No product code, manifest, or configuration was
  changed in this pass; the work was labeling, offline scoring, and documentation.
- 2026-10-01 — **promoted to [SPEC-066](../specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md)
  as `draft`.** Documentation-only; this memo's boundary and its "authorizes no
  implementation" standing are unchanged, and the spec carries six unresolved Open
  Questions. Drafting read the shipped `scoring.py`, `skill_store.py` and
  `config.py`, both store backends, the tool-gateway connector, the portal and the
  skills-hub test suite, which produced three corrections to this memo and one to
  SPEC-014: (1) §4.4's "no schema change" for `skill_id` indexing holds for
  `score()` but **not for the deployed Postgres backend** — `skill_id` is in neither
  `_SEARCH_VECTOR` nor `idx_skills_search`, so a slug-only match returns zero rows
  there while scoring positive in memory, and stratum-A recovery is exactly the class
  that would not ship; (2) §4.4's "`parse_sources` still accepts two sources covering
  the same files" is imprecise — `parse_sources` validates `SKILLS_SOURCES` JSON and
  never sees file content, so it structurally cannot detect content overlap, which
  relocates the fix to `rank()` (or to sync, where body hashes exist —
  **[corrected 2026-10-02] no body hashes exist anywhere in `skills-hub`; see the
  changelog entry of that date**); (3) the eval's
  **0.500 → 0.711 is a memory-path upper bound**, since it ran `rank()` over a corpus
  export with no prefilter — and because no single fix reaches significance alone, a
  backend-neutral *subset* would be an unmeasured subset, against eval-set §8's own
  rule; (4) SPEC-014's `tasks.md` claims a delivered "byte-identical ordering parity
  test vs in-memory store" that **does not exist** in the suite, and names
  `plainto_tsquery` where the shipped code OR-joins `to_tsquery` lexemes. §11's first
  two open questions are inherited by the spec as OQ-1 and OQ-3; the label-ownership
  question stays unsettled. Two consequential edits to this memo's own text: §2.1's
  "byte-identical … a test-pinned invariant" row now records that the invariant is
  **documented but not test-pinned** (finding 4 above), and its adjacent
  `to_tsvector` row escapes the `||` inside the code span, which rendered as six
  cells in a two-column table. No product code, manifest, configuration, or
  measurement was changed in this pass.
- 2026-10-02 — **self-correction: this memo asserted machinery that does not
  exist.** The 2026-10-01 entry above relocates the duplicate-content fix to
  "`rank()` (or to sync, where body hashes exist)". **There are no body hashes.**
  `md5`, `sha256`, `hashlib` and `blake2` appear nowhere in `products/skills-hub`
  outside `uv.lock`'s dependency hashes. The `body_md5` values in
  [the label fixture](semantic-skill-retrieval-labels.json) were computed by the
  **offline evaluation harness**, not by the product — so the parenthetical
  described an existing sync-time capability when it was in fact describing
  something the harness did off to the side. Sync does hold the body *text*
  (`Skill.body`), so a hash is trivially computable there; the error is claiming it
  already was. Found while resolving SPEC-066's OQ-6, which asked whether sync-time
  overlap rejection was feasible: the answer is that it is *feasible* but rests on
  machinery that would have to be built, and it is **deferred** on three structural
  grounds (nondeterministic precedence across independently-jittered sync loops;
  the eventual-consistency hole `_resolve_compositions` already documents; no store
  surface returning all bodies) with a named trigger to revisit. The same false
  claim was made in four other committed places — SPEC-066's `spec.md`, `plan.md`
  and `tasks.md`, and the evaluation-set artifact — and all five are corrected.
  Marked inline above rather than silently edited, because this memo is a
  measurement record and its history is not rewritten. The same pass updates this
  memo's **status header** for SPEC-066's `draft` → `approved` transition: the
  "Promoted to" line said "the spec is not approved, six Open Questions block
  `approved`", which the approval made false, and it now records that approval
  authorizes implementation to begin and no merge, migration, deployment, or version
  bump. The header states current status rather than measurement, so updating it is
  not a rewrite of the record. §11's first two questions — the two SPEC-066
  inherited as OQ-1 and OQ-3 — are struck and answered in place, following the
  pattern §11's own label-ownership bullet set on 2026-10-01; its remaining six
  concern embeddings, hosting manifests, or label ownership and are untouched.
  No measurement, label, catalogue, pool, metric, or product code is changed by
  this pass.
