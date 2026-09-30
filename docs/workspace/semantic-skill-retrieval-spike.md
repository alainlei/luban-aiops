# Spike: Semantic Skill Retrieval — pgvector vs. the Lexical Baseline on a 30-Document Corpus

Status: assessment — recommends **measure before building**. **No implementation, embedding run, extension install, image swap, ADR, or spec is authorized by this memo.**
Date: 2026-09-30
Roadmap home: [Exploration Backlog](../agentic-aiops-platform/delivery-roadmap.md#exploration-backlog), "Semantic (vector) skill retrieval"
Evidence baseline: repository at v0.45.0 (`3c87723`); static read of the skills-hub retrieval path plus **read-only** queries against the live dev cluster (`postgres-0` `skills` and `audit` databases, the `llm-hosting/ollama` deployment) and the pinned agentscope 2.0.8 venv. Nothing was installed, embedded, deployed, mutated, or committed.

## 1. Question and recommendation

> Does a vector store measurably beat skills-hub's lexical `rank()` scoring
> (title/tag/body substring weighting) on our corpus?

Recommendation: **the question is not yet answerable, and the honest next step is a
measurement, not an implementation.** Three verified findings reshape it:

1. **The defect the backlog row assumes is not visible in the evidence.** All 96
   `skill_searched` audit events (2026-09-02 → 2026-09-22, 63 distinct queries)
   returned **at least one hit** — a zero-hit rate of **0/96**, mean **4.72** hits
   against the default `limit=5` (§2.2). The top-5 is *saturated*. That makes the
   live risk **ranking quality inside a full result set** (precision@k, MRR), not
   "nothing comes back". A vector store is primarily a recall instrument, and the
   measured symptom is not a recall failure.
2. **`pgvector` is not a zero-infrastructure change.** The deployed
   `postgres:16-alpine` image offers **0 of 61** available extensions matching
   `%vector%`, so `CREATE EXTENSION vector` would fail today; enabling it means an
   image swap on the single StatefulSet that also holds the `audit`, `incidents`,
   and `sessions` databases (§3.1–3.2). The roadmap row's "avoiding new
   infrastructure" is true of a new *server* and false of a new *image*.
3. **At this corpus size, no vector store is needed to test the hypothesis at all.**
   The catalog is **30 skills across 4 sources, 92,486 bytes of body text total**
   (§2.1). Exact brute-force cosine over 30 documents in process is sub-millisecond
   and needs no extension, no image swap, and no ANN index. `pgvector` earns its
   place only when catalog scale makes SQL-side filtering or ANN necessary.

So: build a labeled evaluation set and measure the lexical baseline first (§7). If
semantics are then shown to help, the cheapest substrate is a **sidecar embedding
table over `real[]` with in-process exact cosine** (§4.3, §5.2) — reversible into
`pgvector` later without a data migration. Cheaper still, and worth trying first,
is **improving the lexical baseline itself** (§4.4): cover-density ranking,
trigram tolerance, or a curated alias map that fixes exactly the paraphrase case
the vector store is invoked for, deterministically and explainably.

## 2. Verified baseline — what "lexical" means today

### 2.1 The scorer and the store

| Fact | Where verified |
|---|---|
| Matching unit is `[a-z0-9]+` lowercase tokens; no stemming, no synonyms, no fuzzy/prefix match | [`scoring.py:20,28-30`](../../products/skills-hub/src/skills_hub/services/scoring.py) |
| Weights: title **3.0**, tag **2.0**, each body occurrence **1.0**, saturating at `BODY_OCCURRENCE_CAP = 5` | [`scoring.py:21-24,44-52`](../../products/skills-hub/src/skills_hub/services/scoring.py) |
| Zero-score records are **excluded**; ties break by `skill_id` ascending; ordering is `(-score, skill_id)` | [`scoring.py:85-96`](../../products/skills-hub/src/skills_hub/services/scoring.py) |
| Excerpt is a ≤400-char window around the first body match, falling back to the description head | [`scoring.py:55-75`](../../products/skills-hub/src/skills_hub/services/scoring.py) |
| One pure `rank()` is shared by **both** backends so ordering is byte-identical — a test-pinned invariant | [`scoring.py:1-9`](../../products/skills-hub/src/skills_hub/services/scoring.py), [`skill_store.py:1-6,144,463`](../../products/skills-hub/src/skills_hub/services/skill_store.py) |
| Postgres pre-filters with a GIN index over `to_tsvector('simple', title || ' ' || body)` and re-ranks in Python | [`skill_store.py:202-205,437-463`](../../products/skills-hub/src/skills_hub/services/skill_store.py) |
| Lexemes are **OR**-joined (`" \| ".join(tokens)`), because `plainto_tsquery` ANDs and silently drops partial matches | [`skill_store.py:243-256,452`](../../products/skills-hub/src/skills_hub/services/skill_store.py) |
| `tags` cannot join the index expression (`array_to_string`/`array_out` are STABLE, not IMMUTABLE) and are matched in a second tsvector branch + query-time filter | [`skill_store.py:199-205,251-256,474-482`](../../products/skills-hub/src/skills_hub/services/skill_store.py) |
| DDL is idempotent by convention: `CREATE TABLE IF NOT EXISTS` then `ALTER ... ADD COLUMN IF NOT EXISTS` per spec version, run in `initialize()` | [`skill_store.py:158-206,324-328`](../../products/skills-hub/src/skills_hub/services/skill_store.py) |
| Backend selection is a `Protocol` + factory (`build_skill_store`) on `SKILLS_STORE_BACKEND` (`memory` default / `postgres`) | [`skill_store.py:30-67,509-517`](../../products/skills-hub/src/skills_hub/services/skill_store.py), [`config.py:181-230`](../../products/skills-hub/src/skills_hub/core/config.py) |
| Connections are opened per operation — retrieval is treated as low-volume | [`skill_store.py:295-322`](../../products/skills-hub/src/skills_hub/services/skill_store.py) |
| Tool surface: `skills.search` is `risk_level="read"`, `query` described as "Free-text search terms", `limit` default **5** / max **20**, upstream timeout **10.0 s** | [`skills_connector.py:31-38,154-196`](../../products/tool-gateway/src/tool_gateway/tools/skills_connector.py) |

The recall gap is real *in principle*: "pod won't start" shares no token with a
runbook titled `KubePodNotReady`, so it scores 0 and is excluded. What §2.2 shows
is that this has **not been observed** in the platform's own audit trail.

### 2.2 The corpus and the real query record (live, 2026-09-30)

Corpus, from the `skills` database on `postgres-0`:

| Measure | Value |
|---|---|
| Skills | **30** |
| Distinct sources | **4** |
| Body length min / avg / max | **1,094 / 3,083 / 11,778** chars |
| Total body bytes | **92,486** (~90 KB) |
| `skills` database size | **8,999 kB** |

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
- **Query shape is a fair sample of agent phrasing.** The tool description says
  "Free-text search terms" and the system prompt tells the agent to consult
  `skills.search` FIRST and not to conclude it lacks grounding until a search
  returns no match ([`runtime_settings.py:25-34`](../../products/agent-platform/src/agent_service/runtime_settings.py)).
  Nothing normalizes queries to keywords, and the observed 5-word mode confirms
  natural phrasing reaches the scorer. So the "the agent already adapts to lexical"
  masking hypothesis is **not** supported.
- **The traffic is not sustained operator triage.** All 96 events fall in a
  three-week window ending 2026-09-22, with none in the eight days to today; the
  pattern is demo, e2e, and verification traffic. The absence of zero-hit queries
  is therefore *weak* evidence, not proof that operators never hit the gap.

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
the constraint (30 × 768-dim × 4 B ≈ 92 KB; even 10,000 × 1024-dim ≈ 41 MB).
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
nothing at 30 rows. This is the right answer at catalog scale and the wrong first
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
catalog's vectors, and compute exact cosine in Python. At 30 documents × 768
dimensions that is 23,040 floats — a single small query and a few hundred
microseconds of arithmetic, exact and with **no ANN recall loss at all**.

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
no new dependency:

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

Honest cost: an alias map is manual curation and scales badly — but at 30 skills
across 4 sources it is a bounded, reviewable document, and every entry is
explainable to an operator in a way a cosine score is not. **If Option D closes the
measured gap, no embedding work is needed at all**, which is why §10 puts it before
the substrate decision rather than after.

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
- **Storage is a non-issue** (§3.2): 30 rows ≈ 92 KB; 10,000 rows at 1024 dims
  ≈ 41 MB against ≈67 MB used of 1 Gi today.

### 5.3 Index posture

- **At 30 rows: no index.** A sequential scan is exact, and an ANN index would add
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
- **Backfill** is trivial at this scale: 30 documents, one pass, seconds.

## 7. Recall and latency assessment criteria — the gate

This is the section that decides whether anything gets built. It is deliberately
written so that a **null result is a publishable outcome**: "lexical is good enough
on our corpus" closes the backlog row as honestly as "vectors win" opens a spec.

### 7.1 Evaluation set

- **Seed from real traffic.** The audit trail already holds **63 distinct operator-
  shaped queries** in `skill_searched.details->>'query'` (§2.2). Extracting them is
  a read-only query and needs no new instrumentation — this is the strongest
  argument for measuring first, because the seed data already exists.
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
- **State the sample size honestly.** 63 real queries plus a paraphrase set over a
  30-document catalog with 4 sources is *small*. Report confidence intervals, and
  treat any difference inside the noise band as **no evidence of improvement**.

### 7.2 Metrics, and the baseline each must beat

Every metric is computed for the **lexical baseline first**, on the same set, with
the same harness. Nothing is promoted on an unmeasured baseline.

| Metric | Definition | Why it matters here |
|---|---|---|
| **Zero-hit rate** | fraction of queries returning 0 hits | **Already 0/96 live.** There is no headroom on this axis, which is itself the central finding — do not build a recall instrument to fix a non-existent recall failure |
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

1. **Approve the measurement-first step — no code, no infrastructure.** Extract the
   63 distinct audit queries, have operations label relevance against the 30-skill
   catalog, add a reviewed paraphrase set, and publish the lexical baseline
   (Precision@5, MRR, nDCG@10, zero-hit rate, p50/p95). This is the cheapest
   possible next step and it either justifies or kills everything below it.
   **Gate: without these numbers, no retrieval change is approved.**
2. **Decide whether Option D is tried first** — `ts_rank_cd` cover density, a
   curated alias map, and (only if an image change is already accepted) `pg_trgm`.
   If D closes the measured gap, no embedding work is needed at all.
3. **If semantics proceed, approve the substrate:** sidecar `real[]` + in-process
   exact cosine (Option C — no extension, no image swap, reversible), **or** the
   `postgres:16-alpine` → pgvector image swap on the shared StatefulSet now,
   accepting the blast radius over `audit`, `skills`, `incidents`, and `sessions`
   plus a written rollback plan.
4. **If a model embedder is used, approve the provider and its egress posture:**
   in-cluster Ollama (enable embeddings, pull and pin an embedding model, no new
   secret, no egress, no spend) **or** DashScope (billable, external egress, a new
   `skills-hub-runtime-secrets` entry, and skill body text leaving the cluster).
5. **Record the scale trigger for pgvector now, as a number.** Exact in-process
   cosine is the right substrate at 30 skills and the wrong one at some larger
   count; "when it feels slow" is not a trigger. Propose: promote to pgvector at
   **>2,000 skills** or **search p95 >300 ms**, whichever comes first.
6. **Only then promote a spec.** Promotion needs §7's measurements in hand, the §8
   `score`-contract decision made, the byte-identical-invariant narrowing agreed,
   and the §9 gating posture accepted. **This memo authorizes none of it.**

## 11. Open questions for the first spec

- Which fusion rule, and is `score` allowed to change meaning (contract version
  bump, portal rendering, JSON schema) or must fusion stay rank-only?
- Is the byte-identical ordering invariant narrowed (semantic Postgres-only,
  recommended) or preserved (no semantic retrieval at all in the memory backend)?
- Does the in-cluster Ollama actually enforce `OLLAMA_API_KEY`? A loopback
  port-forward probe was answered with 200/501 rather than 401 (§3.3). Whether that
  is loopback trust or an unenforced key must be settled deliberately before
  skills-hub depends on the endpoint — and it is a question about the hosting
  manifests, not about retrieval.
- Should `ollama/ollama:latest` be pinned as part of this work, given the SPEC-028
  R-3 fixed-point-pinning convention?
- Who owns the relevance labels, and how is the labeled set versioned so a catalog
  change re-runs the evaluation?
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
