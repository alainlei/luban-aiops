# SPEC-066: Skill Retrieval Ranking Fidelity — The Four Measured Lexical Fixes, Cross-Backend Parity, And A De-Duplication Guardrail

## Status

- status: `approved`
- owner: luban-platform-team
- created: 2026-10-01
- approved: 2026-10-02 — the six Open Questions were resolved against the shipped
  code and the operator ratified the resolutions, including the two that were
  product decisions rather than code questions (OQ-4 accept the Q63
  re-ordering; OQ-6 defer sync-time overlap rejection).
- release slice: **none assigned.** R5 closed at v0.45.0 (SPEC-065, delivered
  2026-09-29) and no R6 theme exists yet. This spec's roadmap home is the
  [Exploration Backlog](../../agentic-aiops-platform/delivery-roadmap.md#exploration-backlog)
  row "Semantic (vector) skill retrieval", **closed 2026-10-01** with the explicit
  condition that *"promoting them needs its own spec"* — this is that spec.
- target version: unassigned (next minor after v0.45.0, pending an R6 theme
  decision)
- related ADRs: **none.** OQ-3 resolved to *preserve* the cross-backend
  byte-identical ordering invariant as written, so no architectural narrowing
  occurs and ADR-0015 is not needed. The invariant is preserved **by mechanism**
  rather than by assertion: R-5 widens the prefilter into a strict
  over-approximation of the scorer's non-zero set, which keeps Python the sole
  decider of ordering on both backends.
- lineage: promoted from the
  [semantic skill retrieval spike](../../workspace/semantic-skill-retrieval-spike.md)
  §4.4 (the fix list) and the
  [evaluation-set artifact](../../workspace/semantic-skill-retrieval-eval-set.md)
  §8 (the measurement, including the committed
  [label fixture](../../workspace/semantic-skill-retrieval-labels.json)).
  **Extends SPEC-014 R-3** — that criterion states ranking matches "title, tags,
  and body with fixed weighting"; this spec adds `skill_id` as a fourth scored
  field and replaces the flat weighting with a corpus-derived one, so R-3's
  wording and the `skills-hub` README's published "title ×3, tags ×2, body ×1"
  summary both change. Builds on SPEC-029 (the `skill_searched` audit details,
  whose `result_count` and `skill_ids` are observable consequences of R-7).

> **Approval note (SDD discipline).** The full scaffold (`spec.md` + `plan.md` +
> `tasks.md`) was authored together per the SPEC-064/SPEC-065 same-session
> precedent. At drafting this spec was deliberately *not* decision-complete —
> unlike SPEC-065, whose five scope questions had already been resolved by
> operator decision in its memo §7, this memo authorizes **no implementation** and
> its §11 hands the scope questions to "the first spec", i.e. to this document.
> Six Open Questions therefore blocked `approved`, and `plan.md`/`tasks.md` were
> banner-marked provisional.
>
> **Approved 2026-10-02.** All six are resolved below in *Open Questions*,
> each against the shipped code rather than against the memo's framing, and the
> provisional banners are lifted from `plan.md` and `tasks.md`. Resolving them
> surfaced **two corrections to claims this spec itself had made** — that body
> hashes exist at sync (they do not; no hashing exists anywhere in `skills-hub`),
> and that R-8 could "reuse" the offline evaluation harness (it is not committed
> and must be reconstructed). Both are recorded in *Open Questions* and fixed
> in the requirements. Two items remain as **Stage 0 verification tasks** rather
> than open questions, because they are checkable facts about a running cluster
> and an uncommitted harness rather than decisions: the PostgreSQL prefix-lexeme
> behaviour R-5 relies on, and which CamelCase-splitting variant produced 0.711.
> Approval authorizes implementation to begin; it does not authorize a merge —
> R-8's re-measurement through the Postgres path is the merge gate, and it has a
> coded null-result outcome.

## Summary

Ship the four lexical retrieval fixes that the 2026-10-01 measurement proved
sufficient — **index `skill_id`, IDF weighting, sublinear body-length
normalization, and CamelCase-splitting tokenization** — as one indivisible
package, together with the **cross-backend parity work the measurement could not
see** and a **product-side de-duplication guardrail**. Combined on the labeled
set these move top-1 correctness **0.500 → 0.711** and stratum-C (paraphrase)
top-1 **0.333 → 0.611**, with bootstrap 95% CIs excluding zero on MRR, MRR(2)
and nDCG@10 and an exact sign test at **p = 0.0117**.

The measurement was taken on the **in-memory path only** — `rank()` over a corpus
export, with no Postgres prefilter in front of it. Three of the four fixes are
therefore **not backend-neutral as measured**, and two of them would silently
under-deliver or actively regress on the deployed Postgres backend without the
co-change R-5 specifies. **This spec's central requirement is parity, not
scoring**: the package must produce the *same ordering on both backends* and be
*re-measured on the shipped path* before it is called a win.

## Motivation

### What the measurement licenses

The spike's gate 2 pre-registered a cost-ordered decision rule and the cheap step
met it (eval-set §8.5). The winning candidate **V6** is IDF + sublinear length
norm + CamelCase splitting + `skill_id`, and every candidate was fidelity-gated
on reproducing the shipped scorer exactly with its own flags off — **38/38
identical** — so the comparison is against the real baseline, not a
reimplementation. Each fix maps to a defect that was *measured*, not hypothesised:

| Fix | Defect it reaches | Measured evidence |
|---|---|---|
| Index `skill_id` (R-1) | defect 5 — `score()` never reads the slug | identifier owner at top-1: **0 of 3 → 3 of 3** on stratum A; **+0.026** combined top-1 alone |
| IDF weighting (R-2) | defect 4b — no stoplist, no frequency weighting | `certificate expired on the ingress` earns **3.0 from a title match on the stopword "the"**, making a password-reset runbook the top answer to a TLS question |
| Sublinear length norm (R-3) | defect 4a — no length normalization | sample bodies average **6.8×** runbook length; body matches supply **70–100%** of the winning score wherever the lexical top-1 is graded 0 |
| CamelCase splitting (R-4) | defect 2 — opaque single tokens | `KubePodCrashLooping` tokenizes to one token, so for `pod keeps restarting CrashLoopBackOff` the exactly-right alert ranks **2nd**, losing to an alphabetical tie-break at the same 10.0 |

**No single fix reaches significance alone** (sign test: V5 p = 1.0000, V1
p = 0.3750, V2 p = 0.2891, V3 p = 0.0215). The result is a property of the
*combination*. That is why this spec ships all four or none, and why a
"backend-neutral subset" is explicitly rejected (Non-Goals).

### What the measurement does not license

Five facts, each established by reading the shipped code rather than the memo:

1. **0.500 → 0.711 is a memory-path number.** The evaluation ran `rank()` over a
   corpus export. The deployed Postgres backend does not call `rank()` over the
   corpus — it calls it over the rows a `to_tsvector` prefilter admitted
   (`skill_store.py`). The measured gain is therefore an **upper bound** for
   deployed environments, and its latency figures (p50 2.726 ms) explicitly
   exclude the prefilter, HTTP, auth and the audit write.
2. **Indexing `skill_id` alone would not reach deployed environments.**
   `_SEARCH_VECTOR` covers `to_tsvector('simple', title || ' ' || body)` and the
   tags array — **not `skill_id`** — and `idx_skills_search` indexes the same
   expression. A query matching only the slug scores positive in memory and
   returns **zero rows** on Postgres. Stratum-A identifier recovery, the one
   defect nothing else reaches, is precisely the class that would not ship. The
   memo's "no schema change" is true of `score()` and false of the backend.
3. **CamelCase splitting can regress Postgres recall.** The prefilter's own
   comment states its lexemes "mirror the scorer's matching unit". Query side is
   Python `tokenize()`; document side is PostgreSQL `to_tsvector('simple', …)`.
   `'simple'` lowercases and splits on non-alphanumerics but does **not** stem
   and does **not** split CamelCase — so the two tokenizers agree today *only
   because neither splits CamelCase*. Splitting on the query side alone breaks
   the mirror: `KubePodNotReady` would query `kube | pod | not | ready` against a
   vector holding the single lexeme `kubepodnotready`, and Postgres can stop
   returning rows it returns today.
4. **IDF has no backend-independent corpus to be computed over.** `rank()` has
   exactly two callers, and they pass **different pools**: the in-memory backend
   passes `_all_records(source, tag)` (no text filter) while the Postgres backend
   passes prefiltered `candidates`. IDF derived from the pool would therefore
   differ between backends for the same query — which breaks the byte-identical
   invariant directly, and makes the score a function of what the prefilter
   happened to admit. *Refinement established while resolving OQ-2:* both callers
   **do** apply the same `source`/`tag` filters, so the divergence is the
   tsvector prefilter **alone**. That matters — it makes "IDF over the filtered
   catalog" well-defined and identical on both paths, and it is the option R-2
   takes.
5. **The invariant this stresses is documented but not enforced.** SPEC-014's
   `tasks.md` claims a *"byte-identical ordering parity test vs in-memory store"*
   as delivered. No such test exists in the current suite:
   `products/skills-hub/tests/test_skill_store.py` has `InMemoryStoreTests` and
   `PostgresStoreAdapterTests` as separate classes, and the three Postgres search
   tests assert on generated SQL and params against a fake connection, never on
   ordering versus the memory backend. That task line is also stale on the query
   operator (it says `plainto_tsquery`; the shipped code OR-joins `to_tsquery`
   lexemes, and `test_search_joins_multi_word_queries_with_or` documents that
   `plainto_tsquery` would be wrong). R-6 closes this gap, because a parity claim
   with no parity test cannot survive four simultaneous scoring changes.

Also **not** licensed, and deliberately out of scope: abstention. Zero-relevant
rate is **4/38** under the shipped scorer and **4/38** under V6 — unchanged by
every candidate — because a scorer admitting any `score > 0` structurally cannot
abstain. That is its own Exploration Backlog row and its own product decision.

### Why now

The row is closed and its closure condition names this spec. The label fixture is
committed and pins a `body_md5` per document, so the corpus that justifies the
change is reproducible and a catalog move forces re-grading rather than silently
invalidating the numbers. Deferring costs nothing measurable but lets the
de-duplication guardrail stay absent — and the guardrail is the part that needs
no labels at all, since the *configuration* half already proved the defect real
(32 of 63 pools crowded before the fix, 0 of 63 after) while leaving the product
free to reproduce it on the next overlapping `SKILLS_SOURCES` registration.

## Requirements

Each requirement is stable once this spec is `approved` and carries testable
acceptance criteria. Requirement IDs use `R-x` and are referenced by `tasks.md`.

### R-1: Score the `skill_id` slug

Add `skill_id` as a fourth scored field in `score()`, so an operator who types a
skill's exact name gets signal from the one field guaranteed to carry it.

Acceptance criteria:

- `score()` reads `skill.skill_id` and credits its tokens at **`TAG_WEIGHT`
  (2.0)** — the weight the measurement used, so every published number in this
  spec applies to it. OQ-1(b) is resolved: a different weight is a *different,
  unmeasured candidate* and is not substitutable here. If another weight is ever
  wanted it is tested as a fifth candidate under R-8, not chosen by argument.
- The slug's separators are tokenized consistently with the title, so
  `samples/password-reset-resetacmepassword` contributes `samples`, `password`,
  `reset`, `resetacmepassword` — and, with R-4 active, the CamelCase-derived
  tokens of any slug that carries them.
- The stratum-A objective check reproduces the measurement: for each of the 3
  stratum-A queries naming an identifier that exists in the corpus, the
  document that **owns** the identifier ranks first. Asserted against the
  committed label fixture, not against a hand-written expectation.
- The 11 stratum-A queries naming an identifier that matches **no** document are
  not made worse, and their behaviour is recorded (they still return 7–10
  confident hits — abstention, out of scope).
- With R-5 delivered, a slug-only match returns the **same** rows on both
  backends; a test asserts that a query whose only match is in `skill_id` is
  non-empty on Postgres as well as in memory.

### R-2: Corpus-derived IDF weighting

Weight each query token by inverse document frequency so that function words stop
competing with domain terms, using a corpus-derived table rather than a
hand-written stoplist.

Acceptance criteria:

- The IDF formula is exactly **`ln((1+N)/(1+df))+1`**, where `N` is the document
  count and `df` the number of documents containing the token. No hand-maintained
  stopword list is introduced anywhere in the path.
- Tokens are weighted identically for the title, tag and body contributions of a
  given query token — IDF is a property of the *token*, not of the field. The
  field weights (title 3.0 > tags 2.0 > body 1.0) are unchanged in their
  **ordering**, so SPEC-014 R-3's "title > tags > body" guarantee still holds.
- **`N` and `df` are backend-independent** (see R-6): the same query over the
  same catalog produces the same IDF table on both backends. A test asserts
  numeric equality of scores across backends, not merely equal ordering.
- **Statistics are computed in Python and persisted at sync time** — OQ-2's
  resolution, and the only option that satisfies the criterion above. Two code
  facts force it. First, `rank()` is **synchronous and pure** while both stores
  are `async`, so statistics cannot be fetched inside it: the caller must compute
  them and pass them in, which makes a **`rank()` signature change** the
  load-bearing part of this requirement. Second, once R-4 splits CamelCase,
  Python's `tokenize()` and PostgreSQL's `to_tsvector('simple', …)` **disagree**,
  so any `df` computed in SQL differs from the `df` the scorer uses and parity
  breaks — `df` is therefore not computable in SQL at all after R-4. Computing
  per request over the whole catalog on the Postgres path is also rejected: it
  would read the corpus the prefilter exists to avoid reading, and it scales
  badly against the memo's own >2,000-skill trigger.
- The statistics refresh rides the existing sync cycle: recomputed after each
  successful `replace_source`, in the same Python tokenizer, and shared by both
  backends (a table on Postgres, the equivalent structure in memory). Staleness
  is bounded by `SKILLS_SYNC_INTERVAL_SECONDS` (default **300**) and is recorded
  as a known property, not hidden. Because `df` is global, a per-source swap
  invalidates all of it, so the refresh is a **full catalog pass** — trivial at
  18 documents and still cheap against sync's git clone at 2,000.
- The score stays **explainable as a sum of per-token, per-field contributions**
  (`weight × idf(token) × norm(document)`). This is the surviving obligation from
  the memo's *"do not silently redefine `score`"* — a prohibition written about
  cosine fusion, which this spec does not do, but whose *reason* (a reviewer must
  be able to answer "why did this rank first?" during an incident) binds here
  too. A fused, learned or otherwise non-decomposable score is out of scope.
- IDF is computed over the **document** population and its tokenization matches
  R-4's exactly, so `df` for a CamelCase-derived part is the count of documents
  whose tokenization contains that part, and — because R-4 retains the whole
  token alongside its parts — the unsplit token has its own `df` like any other.
  A mismatch between the statistics tokenizer and the scoring tokenizer is a
  **silent** correctness bug, so both call the same `tokenize()` and a test
  asserts they do.
- The `certificate expired on the ingress` case stops ranking a password-reset
  runbook first, and the specific mechanism is assertable: "the" contributes
  materially less than `certificate` / `expired` / `ingress`.
- Corpus statistics are derived from documents skills-hub already ingests; **no
  new dependency, no external service, no model, and no embedding** is
  introduced. The persisted statistics table (Postgres) and its in-memory
  equivalent are the only new state, and they are derived data — rebuildable from
  the catalog at any time, so losing them is a staleness problem, not a data-loss
  problem.

### R-3: Sublinear body-length normalization

Damp the body contribution by document length so a long sample cannot outrank a
short runbook on occurrence count alone.

Acceptance criteria:

- The normalization factor is exactly **`1/log2(2 + len(body)/1000)`** applied to
  the body contribution. `len(body)` is the character length of the same string
  `score()` already tokenizes.
- The factor is **1.0 or less and strictly positive** for every possible body,
  including an empty body (asserted, including the empty-string and
  single-character cases, so no division by zero or `log2(0)` is reachable).
- The existing `BODY_OCCURRENCE_CAP` of 5 is **retained** — the norm is applied
  to the already-capped contribution, not instead of it. Removing the cap is not
  measured and is not part of this spec.
- This is the one fix that is per-document and therefore backend-neutral by
  construction; a test asserts identical scores for the same `Skill` on both
  paths without needing corpus state.
- The measured 6.8× sample-vs-runbook advantage is reduced, asserted as a
  monotonic property: for two documents with equal capped occurrence counts, the
  longer body contributes strictly less.

### R-4: CamelCase-splitting tokenization

Split CamelCase runs into their component words so alert titles and skill names
become matchable, in `tokenize()` — the single matching unit for the whole path.

Acceptance criteria:

- `tokenize("KubePodCrashLooping")` yields **at least** `kube`, `pod`, `crash`,
  `looping`, and — per the retention rule below — also the whole token
  `kubepodcrashlooping`. The exact rule for digits, acronyms and mixed runs
  (`KubePodNotReady`, `HTTP503`, `pgBouncer`, `v0211`) is fixed in `plan.md` and
  covered by a table of cases, because the rule determines `df` in R-2 and the
  prefilter in R-5.
- **The whole token is retained alongside its parts.** OQ-2's second half is
  resolved: `tokenize("KubePodNotReady")` yields `kubepodnotready` **and**
  `kube`, `pod`, `not`, `ready`. Retention is chosen because it is a strict
  superset for matching, so it cannot reduce recall relative to today, and it
  preserves exact-identifier lookups — an operator who types a whole skill name
  still matches it as one token, which is the behaviour R-1 exists to add. The
  rule is applied consistently in `tokenize()`, in the R-2 `df` computation, and
  in the R-5 prefilter; a partial application (whole token in one place, parts in
  another) is the failure mode this criterion exists to prevent.
- **Retention must not change the score of text that has no CamelCase.** This is a
  hard criterion, and it is not satisfiable by changing `tokenize()` alone:
  `score()` aggregates `title` and `tags` through a `set` (idempotent) but `body`
  through `Counter(tokenize(body))` and `query` through a loop over a **list**
  (neither idempotent — multiplicity *is* the value). Emitting the whole token
  alongside its parts therefore **doubles every ordinary query** and, on the body
  side, reaches `BODY_OCCURRENCE_CAP` at half the real occurrence count — measured
  against the shipped scorer: a title match 3.0 → **6.0**, a tag match 2.0 →
  **4.0**, three body occurrences 3.0 → **10.0**. The required shape is
  **position-aware** — one token set per surface alphanumerics run, the whole token
  admitted only when it differs from its parts, body occurrences counted per run,
  and query tokens de-duplicated before the scoring loop — with which **7 of the 8**
  existing exact-score assertions keep their current value. Numbers and the
  implementation shape are in `plan.md`.
- **This requirement must not ship without R-2.** Retention makes sub-tokens
  score-bearing — `KubePodNotReady` contributes `not` and `ready`, which the
  shipped tokenizer never produced — and R-2 forbids a stoplist by design, so the
  only thing keeping `not` from carrying full title weight is its IDF. An R-4-alone
  measurement is measuring the inflated column, so the R-4 fidelity gate runs with
  R-2's flag on.
- **Caveat carried into Stage 0, not hidden:** the offline harness that produced
  0.711 is **not committed** (`git ls-files` shows only the label fixture and the
  two prose artifacts), and the eval-set records the tokenizer change only as
  "tokenizer regex" (§8.2's candidate row 2c). So *which* variant was measured
  cannot be confirmed from the
  repository. Retention is the recommended default on its merits; if Stage 0
  establishes that the measurement dropped the whole token, R-8 must re-measure
  this variant rather than assume 0.711 carries over to it.
- Of the **8** exact-score assertions in
  `products/skills-hub/tests/test_scoring.py`, exactly **one** changes value under
  this requirement: `score("KubePodNotReady", skill) == 7.0` encodes the defect and
  must change. The other 7 staying put is what the criterion above means, so **more
  than one changed assertion is evidence of a wrong implementation, not of a stale
  test**. Every change is visible in review; no assertion is weakened to
  `assertGreater`-style vagueness, and where R-3's norm makes a body contribution
  non-integral the expected value is computed **from the formula in the test**
  rather than hard-coded as a rounded literal. R-1 additionally requires two of
  these fixtures to change their `skill_id` rather than their expected number —
  `a/pod` matches the query `pod` once the slug is scored, which would make a
  title-weight assertion read 5.0 and collide with the saturating-cap value asserted
  beside it. Details in `plan.md`.
- With R-5 delivered, no query that returns rows on Postgres **today** returns
  fewer rows after this change. Asserted by the R-6 parity harness over the
  63-query real-traffic pool, not by a spot check.
- Stemming and trigram tolerance are **not** part of this requirement. The memo
  lists them adjacent to CamelCase splitting, but they are not in the winning
  combination and were never measured; `crashloop` reaching `CrashLoopBackOff`
  remains an open vocabulary gap (Non-Goals).

### R-5: Cross-backend parity for the new scorer

Make the Postgres prefilter and its index admit **every** record the new scorer
can rank above zero, so the deployed backend delivers the measured fix instead of
a subset of it. This is the requirement the measurement could not see, and it is
not optional: without it R-1 does not ship and R-4 regresses recall.

Acceptance criteria:

- `_SEARCH_VECTOR` covers `skill_id` as well as `title || ' ' || body` and the
  tags array, so a slug-only match is returned by the prefilter.
- The prefilter remains an **over-approximation** of the scorer's non-zero set.
  The shipped comment's contract is preserved verbatim in intent: *"the prefilter
  must keep every record the shared scorer could rank above zero (per-token OR
  scoring)"*. Over-admitting is safe — Python re-ranks and zero scores are
  dropped; under-admitting is a silent recall bug.
- The OR-join of query lexemes is **retained**; `plainto_tsquery` is not
  introduced (it ANDs the words and would silently drop partial matches, as
  `test_search_joins_multi_word_queries_with_or` already documents).
- **No user-defined SQL tokenizer is introduced.** OQ-5's second half is
  resolved: expressing R-4's rule as an IMMUTABLE PL/pgSQL function is
  technically possible but rejected. There is **no `CREATE FUNCTION` anywhere in
  the repository** (every `IMMUTABLE` match in a source grep is inside `.venv`),
  so it would be the platform's first user-defined SQL function *and* a second
  implementation of the tokenizer that must stay in exact sync with Python's
  regex — precisely the drift hazard R-6 exists to detect. Python stays the
  single tokenizer.
- CamelCase reach on the Postgres path is obtained by **widening the prefilter
  with prefix lexemes**: for each split part, OR a `part:*` term alongside the
  exact token, so `reset:*` reaches the indexed single lexeme
  `resetpasswordadhoc`. Over-admission is safe here by construction — Python
  still decides — and the failure mode of getting it wrong is a slower query
  (loud) rather than a missing row (silent). **This rests on PostgreSQL
  prefix-search semantics that have not been exercised against the live cluster**;
  Stage 0 verifies it before implementation relies on it, and if it does not hold
  the fallback is to drop the tsvector prefilter for CamelCase-derived tokens
  entirely, which is correct and merely slower.
- Adding `skill_id` to the indexed expression needs **no new function and no new
  column**: `to_tsvector('simple', skill_id || ' ' || title || ' ' || body)` uses
  only text concatenation and the two-argument `to_tsvector` with a constant
  `regconfig`, both IMMUTABLE. `skill_id` is already the table's `TEXT PRIMARY
  KEY`. `tags` stay out of the expression for the reason the DDL already records
  (`array_to_string` / `array_out` are STABLE).
- The **GIN index expression and the `_SEARCH_VECTOR` expression stay identical**,
  asserted by a test that compares them, so the index cannot silently stop being
  used.
- **Migration (OQ-5 resolved).** `CREATE INDEX IF NOT EXISTS` matches on *name*,
  so changing the expression under the existing name silently keeps the old
  index. The migration therefore creates **`idx_skills_search_v2`** on the new
  expression and **retains `idx_skills_search` for one release** before dropping
  it — idempotent on re-run, never a window without an index, and rollback is a
  plain code revert while the old index still exists. `CREATE INDEX CONCURRENTLY`
  is **not** used: `_DDL` executes as one multi-statement string on a connection
  opened `autocommit=False` and committed afterwards, so CONCURRENTLY would fail
  inside the transaction block; at this catalog size a plain `CREATE INDEX` is
  milliseconds. If the catalog ever grows enough to need CONCURRENTLY that is a
  separate migration path with its own autocommit connection, not an edit here.
- **Blast radius recorded, not assumed.** The `skills` database shares
  `postgres-0`'s **1 Gi** PVC with `audit`, `incidents` and `sessions`, and that
  PVC is a StatefulSet `volumeClaimTemplates` entry — **immutable on a live
  StatefulSet**, so `kubectl apply` cannot grow it and GitOps cannot raise the
  figure without deleting the PVC or editing it by hand. At 18 rows the index is
  kilobytes, so this is not a blocker; it is the reason the migration must be
  planned rather than attempted. Index size is measured before and after and
  recorded in the delivery note.
- Search latency p95 stays inside the tool-gateway's **10.0 s**
  `REQUEST_TIMEOUT_SECONDS`, measured **end to end** on the Postgres path, not as
  the offline pure-Python figure the eval-set reports.
- No query that the shipped code answers today is answered with fewer rows after
  this spec, on the Postgres path. This is the R-4 regression guard, enforced
  here where it is actually observable.

### R-6: An enforced cross-backend parity harness

Replace the documented-but-untested byte-identical invariant with a test that
actually enforces it, before any of R-1..R-5 lands.

Acceptance criteria:

- A committed harness drives **both** backends over the **same** corpus and the
  **same** query set and asserts the resulting `skill_id` ordering is identical.
  It runs in the ordinary test suite (`make test` / `make verify`), not as a
  manual step.
- The query set is the union of the eval-set's **63-query audit pool** (strata
  A + B) and its **18 authored stratum-C paraphrases**, committed as a fixture, so
  the harness covers both the ordering and the recall regressions R-4/R-5 guard
  against. The distinct count is confirmed from the fixture at implementation (the
  labeled 38 are 20 stratum-B queries plus those 18, so part of the set overlaps).
- The harness **fails on the current code if the invariant is already violated**,
  or passes and thereby establishes the baseline — either outcome is recorded. It
  must not be written so that it can only pass.
- SPEC-014's stale `tasks.md` line (claiming a delivered parity test, and naming
  `plainto_tsquery`) is corrected, and the correction is recorded rather than
  silently edited, since SPEC-014 is `delivered`.
- **The invariant is preserved as written and not narrowed** — OQ-3's
  resolution. The memo §11 narrowing recommendation was scoped to *semantic*
  retrieval (a vector path cannot be byte-identical); nothing in this spec is
  semantic, so it does not apply. No ADR is raised. The harness therefore asserts
  byte-identical ordering **and** numeric score equality across both backends,
  over the whole query set, with no Postgres-only carve-out. OQ-3 and OQ-5 turn
  out to be one decision rather than two: preserving the invariant is what forces
  the widen-the-prefilter strategy in R-5 and rules out a SQL-side tokenizer,
  because a superset prefilter keeps Python the sole decider of ordering.

### R-7: Product-side de-duplication guardrail

Make the retrieval path collapse byte-identical content, so an overlapping source
registration cannot reproduce the measured crowding defect regardless of how
`SKILLS_SOURCES` is configured.

Acceptance criteria:

- `rank()` de-duplicates by content before truncating to `limit`, so identical
  bodies cannot consume distinct result slots. The identity key is a content hash
  of the body, **computed new by this requirement** — `md5(body)`, chosen to match
  the `body_md5` the label fixture pins so the key is consistent with the
  measurement artifact. No hashing exists anywhere in `skills-hub` today (see the
  correction below), so this introduces it. Which record survives is a **fixed,
  documented rule** (lowest `skill_id` ascending, matching the existing
  tie-break), not incidental iteration order.
- De-duplication happens **before** `[:limit]`, not after — the measured defect
  was wasted slots, and collapsing post-truncation returns fewer results than the
  limit for no reason.
- The guardrail is justified as **regression protection, not a retrieval
  improvement**, and is documented that way: with the dev corpus already clean
  (**0 of 63** pools contain a duplicate) there is no crowding left to measure a
  gain against. It therefore needs no label evidence, and none is claimed for it.
- **Overlap rejection does not go in `parse_sources`.** `parse_sources`
  (`core/config.py`) parses `SKILLS_SOURCES` JSON and validates duplicate
  `source_id` values, patterns and type-specific fields; it **never sees file
  content**, so it structurally cannot detect two sources covering the same
  files. The memo's framing ("`parse_sources` still accepts two sources covering
  the same files") is imprecise on this point and is corrected here.
- **Correction to this spec's own earlier text.** The draft said ingestion-time
  rejection belongs at sync time "where body hashes exist". **They do not.**
  `md5` / `sha256` / `hashlib` appear nowhere in `products/skills-hub` outside
  `uv.lock`'s dependency hashes; the fixture's `body_md5` was computed by the
  *offline evaluation harness*, not by the product. Sync holds the body **text**
  (`Skill.body`), so a hash is trivially computable there — but the claim as
  drafted asserted existing machinery that does not exist.
- **Sync-time overlap rejection is deferred (OQ-6 resolved), with a named
  trigger.** It is feasible — `_resolve_compositions` (SPEC-057 R-2) is the exact
  precedent, running between `ingest_directory` and `replace_source` where the
  store is reachable, and its rejections ride the existing per-source status and
  `skills_synced` event with no new event type. It is nonetheless the wrong layer
  here, for three structural reasons: **(1) nondeterministic precedence** —
  sources sync on independent asyncio loops with ±5% jitter, so when two sources
  carry the same document, whichever syncs *second* sees the other's copy, and
  the served version depends on timing, restarts and jitter rather than on
  configuration; **(2) an eventual-consistency hole** the composition code
  already documents — on a fresh cluster the first cycle cannot detect overlap at
  all; **(3) no store surface for it** — nothing returns all bodies or hashes, and
  `store.get()` needs the id, so detection would page through `list()`, a full
  catalog read per source per cycle. R-7 already removes the operator-visible
  symptom deterministically, at every request, regardless of sync order.
  **Trigger to revisit:** when duplicate *ingestion* cost (storage, sync time)
  rather than duplicate *ranking* becomes the problem, or when an operator needs
  to be **told** about a misconfiguration rather than silently protected from it.
  If it is ever built, precedence must come from configured `SKILLS_SOURCES`
  order — which is stable — and not from arrival order, a new bounded label must
  join `_rejection_category()`'s cardinality guard, and the rejection text must
  stay safe for the **auth-exempt** `/api/v1/skills/status` surface that exposes
  `Rejection.reason` verbatim.
- The `skill_searched` audit details (`result_count`, `skill_ids`) change
  observably when duplicates collapse. That is correct and is recorded in the
  spec's Impact; it is **not** a new audit event type and needs no contract
  change.
- A test reproduces the original defect: a corpus with two byte-identical bodies
  under different `source_id`s returns them as **one** hit and the freed slot is
  filled by the next-ranked distinct document.

### R-8: Re-measurement on the shipped path

Re-run the evaluation against the committed label fixture **through the Postgres
backend**, and publish the result whether or not it reproduces the offline gain.

Acceptance criteria:

- **The harness is reconstructed and committed, not reused.** Correction to this
  spec's own earlier text: `plan.md` said to "reuse the offline harness that
  produced §8", but `git ls-files` shows only the label fixture and the two prose
  artifacts — **no harness is committed**. R-8 is the merge gate, so its
  instrument must exist in the repository: the harness is rebuilt, committed, and
  driven through `PostgresSkillStore.search()` rather than `rank()` directly, so
  the prefilter is inside the measured path. Its fidelity is re-established the
  same way §8's was — it must reproduce the **shipped** scorer's published
  baseline (19/38 combined top-1) before any candidate number from it is
  believed.
- The evaluation reuses the committed fixture
  (`semantic-skill-retrieval-labels.json`, 38 queries × 18 documents = 684
  judgments, 173 non-zero, pinned by `body_md5`) **without re-grading**. A
  `body_md5` mismatch fails the run loudly rather than silently invalidating the
  comparison.
- Because the harness is rebuilt, the **CamelCase variant that produced 0.711 is
  re-derived, not assumed** (see R-4's caveat). If the rebuilt harness with
  whole-token retention does not reproduce the offline candidate numbers, the
  discrepancy is published and the shipped configuration is the one that was
  actually measured — not the one the memo described.
- The reported metric set is the one the roadmap row requires: **zero-relevant
  rate** and distinct-document variants, **not zero-hit rate alone**.
- Results are reported **per backend**. A gain that appears in memory and not on
  Postgres is published as such.
- The pre-registered significance method is reused unchanged: paired bootstrap
  over queries (10,000 resamples, seed 20261001) giving 95% CIs on per-query
  metric deltas, plus an exact two-sided sign test on discordant top-1 pairs.
  **Precision@5 is not relied on** — its baseline CI lower bound rounds to zero
  and the eval-set already flags it as borderline.
- The **one known regression is disclosed, not buried**: Q63 `web check sign in
  inventory portal does not transition successful login troubleshooting` moves
  top-1 from `D18` (grade 2) to `D13` (grade 1), with `D18` falling to rank 2 of
  5 so `R@5(=2)` is unaffected. **OQ-4 is resolved: the operator accepts it**, on
  two conditions enforced here. (1) It must be reported on the **Postgres** path
  too, because a prefilter change could convert a re-ordering into a
  *disappearance* — a different severity, and one the offline measurement cannot
  see. If `D18` leaves the returned window entirely on the shipped path, the
  acceptance does not cover it and the merge gate fails. (2) It is named in the
  delivery release note as a known behaviour change rather than left for an
  operator to discover.
- Abstention is reported as **unchanged** (4/38), so the result cannot be
  over-read as fixing the zero-relevant problem.
- If the Postgres-path measurement does **not** reproduce a gain outside the noise
  band, this spec's outcome is a published null result and R-1..R-5 are reverted
  or not merged. "Nothing is promoted on an unmeasured baseline" applies to the
  shipped path, not only to the offline one.

### R-9: Contract and living-doc updates

Record the new weighting, the new scored field, and the de-duplication behaviour
in the living docs, so documentation cannot drift from shipped behaviour.

Acceptance criteria:

- `products/skills-hub/README.md`'s endpoint summary — currently *"deterministic
  ranked matches (title ×3, tags ×2, body ×1, `skill_id` tie-break)"* — is
  updated to the new weighting and to name `skill_id` as a scored field rather
  than only a tie-break.
- **No published prose may imply that `score` values are comparable across
  queries.** R-4's retention makes the score depend on how many tokens a query's
  surface form yields: measured, an exact identifier match (`KubePodNotReady`
  against a `KubePodNotReady` title) scores **15.0** where the equivalent
  three-word phrase scores **9.0**. Nothing consumes the magnitude — the
  tool-gateway connector drops it and the portal never renders it — so this is a
  documentation obligation rather than a behavioural one, but it also constrains
  the separate abstention backlog row: a threshold over `score` cannot be
  re-derived from these numbers without accounting for query shape.
- SPEC-014 R-3's "keyword matching against title, tags, and body with fixed
  weighting" is amended or annotated, and the relationship is stated in both
  specs, because SPEC-014 is `delivered` and its criterion is now inaccurate.
- `docs/guides/skills-guide.md` is updated in **three** specific places, not
  merely "checked for restated weighting":
  - its **"Never register the same files twice"** warning justifies itself with
    *"because ranking does no content de-duplication the copies consume result
    slots"* — a clause R-7 makes **false**. The warning stays (duplicates still
    cost ingestion, storage and sync time) but its rationale is rewritten, and the
    measured 32-of-63 figure is reframed as history.
  - its authoring advice to *"name so alert → runbook lookups rank well"* becomes
    materially stronger: with R-1 the slug is a **scored field** and with R-4 its
    CamelCase parts are matchable, so authors should be told the `skill_id` is now
    a retrieval surface and how to name for it. This is an improvement the fixes
    make possible, not just a correction.
  - its search prose ("multi-word queries match OR-wise; the shared scorer ranks
    them") is checked against the shipped behaviour and updated if the OR
    semantics or the prefilter widening change what an operator would expect.
- The `scoring.py` module docstring — which currently states the fixed weighting
  and the byte-identical rationale as load-bearing documentation — is rewritten to
  match the shipped behaviour. The byte-identical invariant is **preserved**
  (OQ-3), so the docstring keeps asserting it and adds that R-6 now enforces it.
- **The delivered release note is not edited.**
  `docs/agentic-aiops-platform/release-notes/2026-08-15-skills-and-grounded-guidance.md`
  states "Deterministic scorer: title ×3, tags ×2, body ×1, saturating", which
  this spec makes inaccurate — but it is **delivered release history**, so the
  change is recorded in SPEC-066's own delivery release note and the old note is
  left untouched. Recorded explicitly because "update the docs that state the old
  weighting" would otherwise reasonably reach for it.
- The retrieval spike memo and eval-set gain a status-header pointer to this spec,
  so a reader arriving from the closed backlog row finds the promotion. The
  memos' own text is **not** rewritten; they are measurement artifacts.
- `CHANGELOG.md` gains an entry referencing SPEC-066; `VERSION` and the lockstep
  version files bump at delivery. `docs/specs/README.md` and the
  delivery-roadmap row are updated through the draft → approved → delivered
  lifecycle.
- **No JSON schema changes.** The search response's `score` field is published on
  `GET /api/v1/skills/search` but appears in **no** `shared/shared-contracts`
  schema (`skill-format.md` covers the document format, not the search payload),
  so changing score *values* is not a contract-schema change. R-9 records this
  explicitly so the distinction between "published field" and "validated
  contract" is not lost.

## Non-Goals

- **No embedding, vector store, pgvector, `real[]` sidecar table, or image
  swap.** Gate 3 is **not reached**: zero grade-2 documents are missing from the
  top 10 on any of the 38 queries, `R@5(=2)` on real traffic is already 1.000
  under the *baseline*, and the row's pre-registered rule cancels everything below
  the cheap step. The recorded scale trigger (**>2,000 skills** or **search p95
  >300 ms**, whichever first) is the only reopening condition.
- **No abstention, score threshold, or "nothing applies" path.** Unchanged at
  4/38 by every candidate including the best; it is a product/contract decision
  with its own backlog row, and the labels do not authorize the trade-off.
- **No relevance-aware tie-break.** **Struck by measurement** — numerically
  identical to CamelCase splitting alone on every metric for every stratum,
  because IDF already breaks the `D06`/`D11` tie on the merits and the
  alphabetical fallback never fires. The `skill_id`-ascending tie-break stays, so
  this spec touches the byte-identical *ordering* invariant only through R-7's
  content collapse and not through the sort key.
- **No `ts_rank_cd` cover density, no `pg_trgm`, no curated alias map.** All
  three are cancelled by the result — never measured, and each more expensive than
  the fixes that already closed the gap. Cancelled for *this* row's ordering
  question, not refuted on their own merits: an alias map remains the natural
  instrument for a *vocabulary* gap, which is why the long-term-operator-memory
  row's Option C still names it.
- **No stemming.** Listed adjacent to CamelCase splitting in memo §4.4 but not in
  the winning combination. `crashloop` reaching `CrashLoopBackOff` stays an open
  vocabulary gap.
- **No "backend-neutral subset" shipment.** Only R-3 is per-document and
  backend-neutral by construction. Shipping the neutral subset alone would ship an
  *unmeasured* subset — and since no single fix reaches significance alone, an
  unmeasured subset has no evidence behind it at all. All four ship together with
  R-5, or none ship.
- **No content authoring.** Two of the four zero-relevant queries are vocabulary
  gaps no retriever can close — there is no ArgoCD and no database-pool document
  in the corpus. That is a content problem and belongs to the skill owners.
- **No change to the `Skill` contract, the search payload shape, the query
  registry, or the auth model.** `score` stays a float on the response; only its
  value distribution changes.
- **No new audit event type.** R-7 changes the *values* of existing
  `skill_searched` details; audit-event-type additions are a contract change and
  are not made casually.
- **No dependency install.** IDF is derived from the catalog skills-hub already
  holds.

## Impact

- products touched:
  - `products/skills-hub/` — `services/scoring.py` (R-1..R-4, R-7: `tokenize()`,
    `score()`, `rank()`, and the module docstring per R-9),
    `services/skill_store.py` (R-5: `_SEARCH_VECTOR`, `idx_skills_search`, the
    `_DDL` migration; R-6: whatever the parity harness needs to drive both
    backends), `services/sync.py` (**R-2 only** — the statistics refresh point
    after each successful `replace_source`. **R-7 adds nothing here**: OQ-6
    resolved by deferring sync-time overlap rejection, so the de-duplication
    lives in `rank()` alone).
    Tests: `test_scoring.py` (**1 of its 8** exact-score assertions changes
    value deliberately — see R-4; two more change their *fixture*, not their
    expected number), `test_skill_store.py` (the new parity harness),
    `test_routes.py`, `test_contracts.py`.
  - `products/tool-gateway/` — **no code change expected.** `_MATCH_KEYS` in
    `tools/skills_connector.py` projects `skill_id`, `title`, `excerpt`,
    `source_id`, `source_path`, `source_ref`, `updated_at` and **drops `score`**,
    so the agent and the evidence panel never see a score value; only ordering
    and excerpts are agent-visible. `test_skills_connector.py` is checked, not
    assumed.
  - `products/operator-portal/` — **no change.** The portal does not render
    `score`: there are **zero** occurrences of the word anywhere in
    `products/operator-portal` (its SPA lives in `web-ui`, not `src`), so
    score-value changes are invisible
    in the UI and ordering changes are the only observable effect.
- shared / platform-ops touched:
  - `shared/platform-ops/e2e/skills-demo.sh` searches `q=KubePodNotReady` and so
    is directly affected by R-4; it must still pass, and if its assertions encode
    the old tokenization they are updated deliberately.
- contracts touched: **none.** No `shared/shared-contracts` JSON schema changes;
  `skill-format.md` is unchanged (it specifies the document format, not
  retrieval). `shared/shared-contracts/observability-conventions.md` is unchanged
  (no new metric family is proposed; if R-5's latency gate needs a metric it uses
  the existing RED families).
- database impact: **yes — one migration.** `idx_skills_search` is a GIN index on
  an expression; R-5 changes that expression, and `CREATE INDEX IF NOT EXISTS`
  will not rebuild an existing index. **OQ-5 resolved** the shape: a versioned
  **`idx_skills_search_v2`** on the new expression, with the old index retained for
  one release so rollback is a plain code revert; **no `CREATE INDEX CONCURRENTLY`**
  (unusable here — `_DDL` runs as one multi-statement string on a connection opened
  `autocommit=False`); and **no user-defined SQL tokenizer** (prefix lexemes widen
  the prefilter instead). Blast radius: `postgres-0`'s 1 Gi PVC also holds the
  `audit`, `incidents` and `sessions` databases, and a StatefulSet's
  `volumeClaimTemplates` is immutable on a live object, so index growth cannot be
  answered by enlarging the claim in place. The `skills` table's **columns do not
  change** — `skill_id` is already the primary key, so R-1/R-5 add no column.
- identity / policy / audit / execution safety impact: **no identity, policy or
  execution-safety change.** No new credential, no new tool, no new permission, no
  HITL surface, no dispatch path. Audit impact is limited to the *values* of
  existing `skill_searched` details (`result_count`, `skill_ids`) when R-7
  collapses duplicates — no new event type, no vocabulary change.
- living state docs to update on delivery: `products/skills-hub/README.md`,
  `docs/guides/skills-guide.md`, SPEC-014's R-3 annotation and its stale
  `tasks.md` parity line, the retrieval memo + eval-set status headers (their
  `approved` pointers are already updated; the `delivered` pointer remains),
  `CHANGELOG.md`, `VERSION` + lockstep version files,
  `docs/specs/README.md`, and the delivery-roadmap Exploration Backlog row.
- risk: **the ordering of search results changes for real operators.** That is the
  point, and it is measured — but it is a behaviour change on a path the agent
  calls, with one known mild regression (R-8) and a prefilter co-change whose
  failure mode is *silent* under-admission. R-5 and R-6 exist to make that failure
  mode loud.

## Open Questions

**None blocking.** The six questions that blocked `approved` are resolved as of
**2026-10-02**, following the SPEC-064/SPEC-065 practice of keeping this heading
and recording the resolution under it rather than renaming the section. They were
the memo's §11 questions that survive its closure, plus the ones reading the
shipped code surfaced. Each resolution below records the *evidence* it rests on,
so a reader can disagree with the reasoning rather than only with the conclusion.
Two items are **not** resolutions but Stage 0 verification tasks, because they are
checkable facts rather than decisions; they are listed at the end.

- **OQ-1 — May `score` change meaning, and at what weight does `skill_id`
  enter?** → **Yes, with no contract version bump; weight fixed at `TAG_WEIGHT`
  (2.0).** (a) `score` is published on `GET /api/v1/skills/search` but appears in
  **no** `shared/shared-contracts` schema (`skill-format.md` covers the document
  format, not the search payload), is **not** rendered by the operator portal, and
  is **dropped** by the tool-gateway connector's `_MATCH_KEYS` projection — so the
  only consumer is a raw HTTP caller, and only *ordering* and *excerpts* are
  agent-visible. Its semantics are nonetheless published in prose in four places:
  the `skills-hub` README endpoint summary, the `scoring.py` docstring, the
  skills-guide's search prose, and the **delivered** 2026-08-15 release note. R-9
  updates the three living ones and explicitly leaves the release note alone. The
  memo's *"do not silently redefine `score`"* was written about cosine fusion and
  is not triggered; its underlying reason survives as an R-2 criterion — the score
  must stay decomposable into per-token, per-field contributions. (b) The
  measurement indexed `skill_id` at 2.0 and every published number assumes it, so
  a different weight is a *different, unmeasured candidate* — testable under R-8,
  not choosable by argument. The stratum-A ladder supports 2.0 in combination:
  `+skill_id` alone moved identifier recovery 0/3 → 1/3, and `+CamelCase and
  skill_id` moved it to 3/3.
- **OQ-2 — Where do IDF's corpus statistics come from?** → **Computed in Python
  and persisted at sync time** (the memo's option ii). Three code facts decide it.
  `rank()` is **synchronous and pure** while both stores are `async`, so
  statistics cannot be fetched inside it — the caller must pass them in, making a
  **`rank()` signature change** the load-bearing part of R-2. After R-4, Python's
  `tokenize()` splits CamelCase and PostgreSQL's `to_tsvector('simple', …)` does
  not, so `df` computed in SQL **cannot** match the scorer's `df` and parity
  breaks — SQL-side statistics are eliminated outright, not merely disfavoured.
  And a per-request whole-catalog read on the Postgres path would read exactly
  what the prefilter exists to avoid, scaling badly against the memo's own
  >2,000-skill trigger. Option (iii), statistics over the pool passed to `rank()`,
  stays rejected: the two callers' pools differ by the prefilter. The refresh
  rides the existing sync cycle (`SKILLS_SYNC_INTERVAL_SECONDS`, default **300**),
  so staleness is bounded and there is no per-request cost; because `df` is
  global, a per-source swap invalidates all of it and the refresh is a full
  catalog pass. An in-process cache was considered and rejected — it would not
  diverge at the dev deployment's `replicas: 1`, but that makes correctness
  depend on a deployment shape. **Second half: `tokenize()` retains the whole
  CamelCase token alongside its parts**, a strict superset for matching that
  cannot reduce recall and preserves exact-identifier lookups.
- **OQ-3 — Is the byte-identical cross-backend ordering invariant preserved or
  narrowed?** → **Preserved as written; no ADR.** The memo §11 narrowing
  recommendation was scoped to *semantic* retrieval, where a vector path cannot be
  byte-identical; nothing in this spec is semantic. (Verified that ADR-0015 would
  have been the correct number — the highest existing ADR is 0014 — and it is not
  needed.) The substantive content is that **OQ-3 and OQ-5 are one decision**:
  preserving the invariant is what forces R-5's widen-the-prefilter strategy and
  rules out a SQL-side tokenizer, because a superset prefilter keeps Python the
  sole decider of ordering. R-6 turns the invariant from documented into enforced.
- **OQ-4 — Is the Q63 re-ordering regression accepted?** → **Accepted by operator
  decision, conditionally.** Top-1 moves from `D18` (grade 2) to `D13` (grade 1);
  `D18` falls to **rank 2 of 5**, so `R@5(=2)` is unaffected (0.977 combined,
  1.000 on stratum B) and the correct document stays inside the returned window.
  The sign test remains **p = 0.0117** with the regression counted, so the
  measured cost is one re-ordering on 1 of 38 queries. The two conditions are
  enforced in R-8: the regression must also be reported on the **Postgres** path,
  because a prefilter change could convert a re-ordering into a *disappearance*
  (a different severity, and if `D18` leaves the window entirely the acceptance
  does not cover it and the merge gate fails); and it must be named in the
  delivery release note rather than left to be discovered.
- **OQ-5 — What is the migration and rollback plan for the GIN index, and can
  R-4's rule be an IMMUTABLE SQL function?** → **Versioned index name, old index
  retained one release, no SQL function, no CONCURRENTLY.** `CREATE INDEX IF NOT
  EXISTS` matches on *name*, so changing the expression under the existing name
  silently keeps the old index; the migration creates `idx_skills_search_v2` and
  **keeps `idx_skills_search` for one release**, which makes rollback a plain code
  revert and leaves no window without an index. `CREATE INDEX CONCURRENTLY` is
  unusable here: `_DDL` runs as one multi-statement string on a connection opened
  `autocommit=False` and committed afterwards, and at 18 rows a plain
  `CREATE INDEX` is milliseconds. Adding `skill_id` needs **no function and no
  column** — text concatenation plus two-argument `to_tsvector` with a constant
  `regconfig` are both IMMUTABLE, and `skill_id` is already the `TEXT PRIMARY KEY`
  (`tags` stay out for the STABLE-`array_to_string` reason the DDL records). An
  IMMUTABLE PL/pgSQL CamelCase splitter is **rejected**: there is no
  `CREATE FUNCTION` anywhere in the repository, so it would be the platform's
  first, and it would create a second tokenizer implementation that must stay in
  exact sync with Python's regex — the drift hazard R-6 exists to detect.
  CamelCase reach comes from **prefix lexemes** in the prefilter instead. Blast
  radius is recorded rather than assumed: the 1 Gi PVC is shared with `audit`,
  `incidents` and `sessions` and is a StatefulSet `volumeClaimTemplates` entry,
  which is **immutable on a live StatefulSet**, so GitOps cannot grow it without
  deleting the PVC.
- **OQ-6 — Does overlap rejection belong at sync time?** → **Deferred, with a
  named trigger; R-7's `rank()` de-duplication is the one that ships.** It is
  feasible, and `_resolve_compositions` (SPEC-057 R-2) is the exact precedent — it
  already runs between `ingest_directory` and `replace_source` where the store is
  reachable, and its rejections ride the existing status plus `skills_synced`
  event with no new event type. Three structural problems make it the wrong layer
  here: sources sync on **independent loops with ±5% jitter**, so with two sources
  carrying the same document the served copy depends on timing rather than
  configuration; the **eventual-consistency hole** the composition code already
  documents means a fresh cluster's first cycle cannot detect overlap at all; and
  **no store method** returns all bodies or hashes, so detection would page
  through `list()` — a full catalog read per source per cycle. R-7 removes the
  operator-visible symptom deterministically at every request regardless of sync
  order, so sync-time rejection would add nondeterminism, a precedence policy, a
  new bounded rejection category and a catalog read to prevent a state R-7
  already renders harmless. **Trigger to revisit:** when duplicate *ingestion*
  cost rather than duplicate *ranking* becomes the problem, or when an operator
  needs to be **told** about a misconfiguration rather than silently protected
  from it. "Doing neither is not an option" still holds — R-7 is the one done.

**Two Stage 0 verification tasks, not decisions.** Both are checkable facts that
resolving the questions above exposed, and neither may be assumed:

1. **PostgreSQL prefix-lexeme behaviour on the live cluster.** R-5's prefilter
   widening relies on `to_tsquery('simple', 'reset:*')` reaching the indexed
   lexeme `resetpasswordadhoc`, and on GIN serving that prefix search. This is
   standard PostgreSQL semantics but has **not** been exercised against
   `postgres-0`. If it does not hold, the fallback is to drop the tsvector
   prefilter for CamelCase-derived tokens entirely — correct, merely slower.
2. **Which CamelCase-splitting variant produced 0.711.** The offline harness is
   **not committed** and the eval-set records the change only as "tokenizer
   regex", so whole-token retention is recommended on its merits rather than
   confirmed as the measured configuration. R-8 re-derives it and publishes any
   discrepancy.

Also inherited and **not** resolved here: **label-set ownership is unsettled.**
The fixture is author-proposed and operator-ratified, not operations-owned, and no
second labeler has produced the Cohen's κ the eval-set's §6.3 rules 4–5 require
(a deviation authorized by the operator). Versioning *is* solved. R-8 re-uses the
set as-is; operations ownership becomes a precondition only if the row is ever
reopened for embedding work.

## Changelog

- 2026-10-01: created as `draft`. Promoted from the closed "Semantic (vector)
  skill retrieval" backlog row, whose closure authorized **no implementation** and
  named this spec as the condition for promoting the four measured lexical fixes.
  Full scaffold (`spec.md` + `plan.md` + `tasks.md`) authored together per the
  SPEC-064/065 precedent, with `plan.md` and `tasks.md` **provisional pending
  scope approval**. Research for this draft read the shipped
  `scoring.py` / `skill_store.py` / `config.py`, both store backends, the
  tool-gateway connector, the portal, and the skills-hub test suite, which
  established the five Motivation facts — most consequentially that **three of the
  four measured fixes are not backend-neutral as measured**, that the 0.711 figure
  is a memory-path upper bound, and that the byte-identical parity invariant
  SPEC-014 claims as tested **has no test**. Took the `SPEC-066` number, which was
  previously earmarked by the parked "Stable API productization" backlog row; that
  row is de-numbered and the three `SPEC-066` references in
  `mcp-ingestion-spike.md` are updated to match, so an unwritten spec stops
  reserving a number. Six Open Questions block `approved`.
- 2026-10-02: **advanced `draft` → `approved`.** All six Open Questions resolved
  against the shipped code and ratified by the operator; the *Open Questions*
  section now opens "None blocking" and each entry records the evidence it rests on
  rather than the question it asks, following the SPEC-064/SPEC-065 practice of
  keeping the heading rather than renaming it. Resolutions: **OQ-1** `score` may
  change meaning with no contract version bump (no schema, not portal-rendered,
  dropped by the
  tool-gateway connector's `_MATCH_KEYS`) and `skill_id` is fixed at `TAG_WEIGHT`
  2.0; **OQ-2** IDF statistics are Python-computed and persisted at sync time,
  because `rank()` is sync-and-pure so statistics must be passed in, and because
  after R-4 a SQL-computed `df` cannot match Python's `tokenize()` — with
  whole-token retention chosen for CamelCase; **OQ-3** the byte-identical
  invariant is **preserved**, no ADR, and OQ-3/OQ-5 are recorded as one decision;
  **OQ-4** the Q63 re-ordering is accepted conditionally on R-8 reporting it on
  the Postgres path; **OQ-5** a versioned `idx_skills_search_v2` with the old
  index retained one release, no `CONCURRENTLY`, and **no** user-defined SQL
  tokenizer — prefix lexemes widen the prefilter instead; **OQ-6** sync-time
  overlap rejection deferred with a named trigger, R-7 alone shipping.
  Requirements gained the criteria those resolutions imply (R-2's signature change
  and explainability obligation, R-4's retention rule, R-5's migration and blast
  radius, R-6's no-carve-out scope, R-8's Postgres-path regression condition,
  R-9's three specific skills-guide edits and its do-not-touch-the-release-note
  rule). **Two corrections to this spec's own draft text**, both found while
  resolving the questions and both recorded in the requirements rather than
  silently fixed: sync-time overlap rejection was justified as belonging "where
  body hashes exist", but **no hashing exists anywhere in `skills-hub`** (the
  fixture's `body_md5` came from the offline harness), and R-8 was written to
  "reuse" an offline evaluation harness that **is not committed** and must be
  reconstructed — which matters because R-8 is the merge gate. Two items are
  demoted from open questions to **Stage 0 verification tasks**: PostgreSQL
  prefix-lexeme behaviour on the live cluster, and which CamelCase variant
  actually produced 0.711. `plan.md` and `tasks.md` provisional banners lifted.
  Bookkeeping recorded in the same pass: `docs/specs/README.md` and the
  delivery-roadmap Exploration Backlog row both moved to `approved`, and the two
  source artifacts' **"Promoted to" status headers** were updated from `draft` —
  the retrieval memo's said "the spec is not approved, six Open Questions block
  `approved`", which this transition made false. Their measurement text is
  untouched; a status header states current status, so it is edited rather than
  annotated, and each artifact's changelog discloses the edit.
  Approval authorizes implementation to begin; it does **not** authorize a merge,
  which R-8 still gates with a coded null-result outcome.
- 2026-10-02 (2): **post-approval verification pass against the shipped code — six
  findings, one of them material.** Every load-bearing code claim in this spec was
  re-checked rather than trusted. Confirmed as written: `TAG_WEIGHT = 2.0`,
  `TOKEN_PATTERN = re.compile(r"[a-z0-9]+")`, `SKILLS_SYNC_INTERVAL_SECONDS`
  default `300`, `_SEARCH_VECTOR` and `idx_skills_search` both omitting `skill_id`,
  `_DDL` as one string on an `autocommit=False` connection, no `CREATE FUNCTION`
  anywhere in the repository, `postgres-0`'s 1 Gi `volumeClaimTemplates` PVC, ADR
  numbering stopping at 0014, `skills-demo.sh` searching `q=KubePodNotReady`, and
  exactly 8 exact-score assertions in `tests/test_scoring.py`. What changed:
  1. **R-4 is not a `tokenize()`-only change — the material finding.** `score()`
     aggregates `title`/`tags` through a `set` but `body` through
     `Counter(tokenize(body))` and `query` through a loop over a **list**, so
     emitting the whole token alongside its parts inflates the two non-idempotent
     paths. Measured by running the shipped `score()` with a prototype retention
     tokenizer: a title match 3.0 → **6.0**, a tag match 2.0 → **4.0**, three body
     occurrences 3.0 → **10.0**, with `BODY_OCCURRENCE_CAP` reached at **half** the
     real count. Naive retention therefore breaks R-4's own "already-lowercase text
     is unaffected" criterion. R-4 gains a hard criterion and a required
     **position-aware** shape (one token set per surface run, whole token admitted
     only when distinct, body counted per run, query tokens de-duplicated), with
     which 7 of the 8 assertions are unchanged.
  2. **"the 8 exact-score assertions change" was wrong — it is 1 of 8.** Only
     `test_weights_compose_per_token` (7.0 → 27.0) changes value; the other seven
     staying put is now the criterion, so a second changed value indicates a wrong
     implementation rather than a stale test. Two fixtures must additionally change
     their **`skill_id`**, not their expected number, because R-1 scores `a/pod`
     against the query `pod` and would turn a title-weight assertion into 5.0 — the
     value asserted for the saturating cap two lines later. The Impact section's
     test list was aligned with this correction.
  3. **`HTTP503` does not split under the described rule.** The draft glossed it as
     "`http` + `503`, or `h`/`t`/`t`/`p`/`503` if done naively"; measured, the two
     standard CamelCase boundaries do not fire inside it at all, so the output is
     the single token `http503`, and `v0211` likewise stays whole. A letter↔digit
     boundary is a **third** rule that must be decided explicitly, because without
     it `503 error` cannot reach a document titled `HTTP503`.
  4. **R-4 must not ship without R-2.** Retention makes `not` and `ready`
     score-bearing and R-2 forbids a stoplist, so IDF is the only thing keeping them
     honest; R-4's fidelity gate runs with R-2's flag on. Relatedly, `score` becomes
     **incomparable across query shapes** (an exact identifier match measures 15.0
     against the phrase's 9.0), which R-9's published prose must not contradict and
     which constrains the separate abstention row's threshold work.
  5. **Two citation errors corrected.** This spec placed the operator portal's SPA
     in `src`; it is `web-ui`, and the underlying claim is stronger than stated —
     there are **zero** occurrences of `score` anywhere in
     `products/operator-portal`. And `products/skills-hub/README.md`'s endpoint
     summary is at line **38**, not 36.
  6. **This pass contradicted itself on `services/sync.py`, and the contradiction
     is now removed.** Correcting the Impact section's stale OQ-6 conditional
     produced an unqualified "`services/sync.py` is not touched" — false, because
     OQ-2's resolution puts R-2's statistics refresh *in that file*. The claim is
     now scoped everywhere it appears (Impact, `plan.md`'s R-7 `affected:` and
     sequencing, `tasks.md`'s banner, Stage 4 blockquote and delivery gate): R-7
     adds no overlap logic there, R-2 does change it. A delivery gate asserting the
     file "unchanged" would have failed on a correct implementation.
  Also disambiguated `plan.md`'s "Stages 3, 4 and 5 are not separately shippable",
  which used *step* numbers from its own list where `tasks.md` uses different
  *Stage* numbers. No requirement's scope, and no OQ resolution, changed in this
  pass; the additions are criteria that make the approved design implementable.
  Product code was read and executed but **not modified**.
