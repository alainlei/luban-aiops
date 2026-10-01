# SPEC-066: Skill Retrieval Ranking Fidelity — The Four Measured Lexical Fixes, Cross-Backend Parity, And A De-Duplication Guardrail

## Status

- status: `draft`
- owner: luban-platform-team
- created: 2026-10-01
- release slice: **none assigned.** R5 closed at v0.45.0 (SPEC-065, delivered
  2026-09-29) and no R6 theme exists yet. This spec's roadmap home is the
  [Exploration Backlog](../../agentic-aiops-platform/delivery-roadmap.md#exploration-backlog)
  row "Semantic (vector) skill retrieval", **closed 2026-10-01** with the explicit
  condition that *"promoting them needs its own spec"* — this is that spec.
- target version: unassigned at draft (next minor after v0.45.0, pending an R6
  theme decision)
- related ADRs: none proposed by this spec. **One may be required** — whether the
  cross-backend byte-identical ordering invariant (SPEC-014 R-3; the
  `scoring.py` module docstring) is *preserved* or *narrowed* is an architectural
  decision with a real trade-off, and is OQ-3 below. If the answer is anything
  other than "preserve as written", record it as ADR-0015.
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
> `tasks.md`) is authored together per the SPEC-064/SPEC-065 same-session
> precedent, **but `plan.md` and `tasks.md` are provisional pending scope
> approval** and say so at their heads. This spec is *not* decision-complete at
> drafting, which is a deliberate difference from SPEC-065: that spec's five
> scope questions had already been resolved by operator decision in its memo §7,
> whereas this memo authorizes **no implementation** and its §11 hands the scope
> questions to "the first spec" — i.e. to this document. **Six Open Questions
> below must be resolved before this spec can advance to `approved`.** Drafting
> is documentation-only: no `scoring.py` change, no migration, no re-measurement,
> and no version bump are part of it.

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
   happened to admit.
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

- `score()` reads `skill.skill_id` and credits its tokens; the weight is fixed by
  OQ-1's resolution (the measurement used **`TAG_WEIGHT`**, i.e. 2.0, and every
  published number in this spec assumes that value).
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
- IDF is computed over the **document** population and its tokenization matches
  R-4's, so `df` for a CamelCase-split token is the count of documents containing
  any of its parts. Recorded in `plan.md`; a mismatch between the indexing
  tokenizer and the scoring tokenizer is a silent correctness bug.
- The `certificate expired on the ingress` case stops ranking a password-reset
  runbook first, and the specific mechanism is assertable: "the" contributes
  materially less than `certificate` / `expired` / `ingress`.
- Corpus statistics are derived from data skills-hub already holds; **no new
  dependency, no external service, no model, and no embedding** is introduced.

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

- `tokenize("KubePodCrashLooping")` yields `kube`, `pod`, `crash`, `looping`.
  The exact rule for digits, acronyms and mixed runs (`KubePodNotReady`,
  `HTTP503`, `pgBouncer`, `v0211`) is fixed in `plan.md` and covered by a table
  of cases, because the rule determines `df` in R-2 and the prefilter in R-5.
- **The whole token is retained alongside its parts**, or the whole token is
  dropped — one rule, chosen at OQ-2 and applied consistently in `tokenize()`,
  in the R-2 `df` computation, and in the R-5 prefilter. A partial application
  (whole token in one place, parts in another) is the failure mode this criterion
  exists to prevent.
- The existing 8 exact-score assertions in
  `products/skills-hub/tests/test_scoring.py` are **updated deliberately**, and
  the update is visible in review: `score("KubePodNotReady", skill) == 7.0`
  encodes the defect this requirement removes, so it *must* change. No assertion
  is weakened to `assertGreater`-style vagueness to make the change pass.
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
- Any CamelCase-aware document-side expression is **IMMUTABLE**. The DDL already
  records why this matters: `array_to_string` / `array_out` are STABLE in
  PostgreSQL, which is why tags stay out of the index today. If R-4's rule cannot
  be expressed as an IMMUTABLE SQL function, the prefilter widens instead (see
  `plan.md` "Prefilter strategy") rather than the index gaining a non-IMMUTABLE
  expression.
- The **GIN index expression and the `_SEARCH_VECTOR` expression stay identical**,
  asserted by a test that compares them, so the index cannot silently stop being
  used. The change is a real migration: `_DDL` uses `CREATE INDEX IF NOT EXISTS`,
  so an existing deployment keeps the old index unless the migration drops and
  recreates it. R-5 must state the migration path and the rollback (OQ-5).
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
- The invariant's final scope is whatever OQ-3 decides; the harness asserts the
  decided scope, and the decision is recorded in an ADR if it narrows the
  invariant.

### R-7: Product-side de-duplication guardrail

Make the retrieval path collapse byte-identical content, so an overlapping source
registration cannot reproduce the measured crowding defect regardless of how
`SKILLS_SOURCES` is configured.

Acceptance criteria:

- `rank()` de-duplicates by content before truncating to `limit`, so identical
  bodies cannot consume distinct result slots. The identity key is a content hash
  of the body (the eval-set already uses `md5(body)` for its `body_md5` pin, so
  the key is consistent with the fixture); which record survives is a **fixed,
  documented rule** (e.g. lowest `skill_id` ascending, matching the existing
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
  the same files") is imprecise on this point and is corrected here. If
  ingestion-time rejection is wanted it belongs at **sync** time, where body
  hashes exist, and is OQ-6.
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

- The evaluation reuses the committed fixture
  (`semantic-skill-retrieval-labels.json`, 38 queries × 18 documents = 684
  judgments, 173 non-zero, pinned by `body_md5`) **without re-grading**. A
  `body_md5` mismatch fails the run loudly rather than silently invalidating the
  comparison.
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
  5 so `R@5(=2)` is unaffected. Accepting it is OQ-4.
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
- SPEC-014 R-3's "keyword matching against title, tags, and body with fixed
  weighting" is amended or annotated, and the relationship is stated in both
  specs, because SPEC-014 is `delivered` and its criterion is now inaccurate.
- `docs/guides/skills-guide.md` is checked for any restated weighting and updated
  if present.
- The `scoring.py` module docstring — which currently states the fixed weighting
  and the byte-identical rationale as load-bearing documentation — is rewritten to
  match the shipped behaviour and the OQ-3 outcome.
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
    backends), and possibly `services/sync.py` if OQ-6 chooses ingestion-time
    overlap rejection. Tests: `test_scoring.py` (8 exact-score assertions change
    **deliberately**), `test_skill_store.py` (the new parity harness),
    `test_routes.py`, `test_contracts.py`.
  - `products/tool-gateway/` — **no code change expected.** `_MATCH_KEYS` in
    `tools/skills_connector.py` projects `skill_id`, `title`, `excerpt`,
    `source_id`, `source_path`, `source_ref`, `updated_at` and **drops `score`**,
    so the agent and the evidence panel never see a score value; only ordering
    and excerpts are agent-visible. `test_skills_connector.py` is checked, not
    assumed.
  - `products/operator-portal/` — **no change.** The portal does not render
    `score` (verified: no reference in `src`), so score-value changes are invisible
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
  will not rebuild an existing index. The migration, its concurrency behaviour
  (`CREATE INDEX CONCURRENTLY` cannot run inside a transaction) and its rollback
  are OQ-5. The `skills` table's **columns do not change** — `skill_id` is already
  the primary key, so R-1/R-5 add no column.
- identity / policy / audit / execution safety impact: **no identity, policy or
  execution-safety change.** No new credential, no new tool, no new permission, no
  HITL surface, no dispatch path. Audit impact is limited to the *values* of
  existing `skill_searched` details (`result_count`, `skill_ids`) when R-7
  collapses duplicates — no new event type, no vocabulary change.
- living state docs to update on delivery: `products/skills-hub/README.md`,
  `docs/guides/skills-guide.md`, SPEC-014's R-3 annotation and its stale
  `tasks.md` parity line, the retrieval memo + eval-set status headers (pointer
  only), `CHANGELOG.md`, `VERSION` + lockstep version files,
  `docs/specs/README.md`, and the delivery-roadmap Exploration Backlog row.
- risk: **the ordering of search results changes for real operators.** That is the
  point, and it is measured — but it is a behaviour change on a path the agent
  calls, with one known mild regression (R-8) and a prefilter co-change whose
  failure mode is *silent* under-admission. R-5 and R-6 exist to make that failure
  mode loud.

## Open Questions

**Six questions block `approved`.** They are the memo's §11 questions that survive
its closure, plus the ones reading the shipped code surfaced.

- **OQ-1 — May `score` change meaning, and at what weight does `skill_id` enter?**
  Two parts. (a) The published `score` value becomes non-integer and
  corpus-dependent. Verified: it is not in any contract schema, not rendered by
  the portal, and **dropped by the tool-gateway connector**, so the only consumer
  is a raw HTTP caller. Is that sufficient to proceed without a version bump, or
  does the operator want the field's semantics documented as unstable? (b) The
  measurement indexed `skill_id` at `TAG_WEIGHT` (2.0). Every number in this spec
  assumes that. A different weight is a **different, unmeasured candidate**.
- **OQ-2 — Where do IDF's corpus statistics come from?** This decides both R-2 and
  R-6. Candidates: (i) compute `N`/`df` per request over the **whole catalog**
  ignoring `source`/`tag` filters — backend-independent by construction, but an
  extra query on the Postgres path; (ii) maintain a statistics table at **sync**
  time — no per-request cost, but a new table, a staleness window, and a second
  migration; (iii) compute over the **pool passed to `rank()`** — cheapest, and
  **rejected here** because the two callers pass different pools, which breaks
  backend parity. Relatedly: does `tokenize()` keep the whole CamelCase token
  alongside its parts (R-4), since that changes `df`?
- **OQ-3 — Is the byte-identical cross-backend ordering invariant preserved or
  narrowed?** The memo §11 recommends narrowing it *for semantic retrieval*
  (Postgres-only), which does not apply here — nothing in this spec is semantic.
  The recommendation is therefore to **preserve it as written**, and R-6 makes it
  enforced rather than documented. Confirm, or record the narrowing as ADR-0015.
- **OQ-4 — Is the Q63 re-ordering regression accepted?** Top-1 moves from a
  grade-2 to a grade-1 document; the grade-2 document falls to rank 2 of 5, so
  `R@5(=2)` is unaffected and the correct document stays in the returned window.
  Measured severity is mild. Accepting it is a decision, not a default.
- **OQ-5 — What is the migration and rollback plan for the GIN index?** The
  expression changes, `CREATE INDEX IF NOT EXISTS` will not rebuild it, and
  `CREATE INDEX CONCURRENTLY` cannot run inside a transaction block. Also: can
  R-4's rule be expressed as an **IMMUTABLE** SQL function at all, or must the
  prefilter widen instead? The `postgres-0` StatefulSet's 1 Gi PVC also holds the
  `audit`, `incidents` and `sessions` databases, so a botched migration has a
  blast radius beyond skills.
- **OQ-6 — Does overlap rejection belong at sync time?** R-7 puts de-duplication
  in `rank()` and rules out `parse_sources` on structural grounds. Whether
  ingestion should *also* reject an overlapping registration — and with what
  operator-visible error, since today's dev config was fixed by hand — is a
  separate decision. Doing both is defensible; doing neither is not.

Also inherited and **not** resolved here: **label-set ownership is unsettled.**
The fixture is author-proposed and operator-ratified, not operations-owned, and no
second labeler has produced the Cohen's κ the eval-set's §6.3 rules 4–5 require
(a deviation authorized by the operator). Versioning *is* solved. If this spec is
approved, R-8 re-uses the set as-is; operations ownership becomes a precondition
only if the row is ever reopened for embedding work.

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
