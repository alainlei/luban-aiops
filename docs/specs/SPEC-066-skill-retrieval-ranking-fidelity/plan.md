# SPEC-066 Plan: Skill Retrieval Ranking Fidelity — The Four Measured Lexical Fixes, Cross-Backend Parity, And A De-Duplication Guardrail

> **PROVISIONAL — pending scope approval.** This plan is authored alongside
> `spec.md` at drafting time per the SPEC-064/SPEC-065 same-session precedent, but
> **it is not binding**: SPEC-066 is `draft` with **six unresolved Open
> Questions**, and unlike SPEC-065 those questions were *not* pre-resolved by
> operator decision in the source memo. OQ-1 (`skill_id` weight), OQ-2 (where IDF
> statistics come from) and OQ-5 (the GIN migration) each change the design below
> materially. Every section that depends on an unresolved OQ says so at its head.
> Nothing here is implemented. Implementation, commit/push, deployment and the
> migration are separate authorization boundaries not granted by approval alone.

## Approach

The measurement says four cheap lexical changes close the ordering gap. Reading the
shipped code says those four changes were measured on a path the product does not
serve: the evaluation ran `rank()` over a corpus export, while the deployed
Postgres backend runs `rank()` over whatever a `to_tsvector` prefilter admitted.
So the work is **not** "edit `score()`" — it is five stages, and the scoring stages
are the easy ones:

1. **Enforce** (R-6) — build the cross-backend parity harness **first**, before any
   scoring change, so the invariant SPEC-014 documents but does not test becomes
   the thing that catches R-1..R-5 breaking it. This is the only stage with no
   dependency on an Open Question, and it is the reason the sequencing below is
   not "scorer first".
2. **Score** (R-1..R-4) — the four measured fixes, behind flags, each
   fidelity-gated on reproducing the shipped scorer exactly with its own flag off,
   exactly as the eval-set gated its candidates (**38/38 identical**). Flags are a
   measurement instrument, not a permanent feature set; see "Flag discipline".
3. **Reach** (R-5) — the prefilter/index co-change that makes R-1 ship and R-4 not
   regress, plus its migration.
4. **Guard** (R-7) — content-hash de-duplication in `rank()`.
5. **Prove** (R-8) — re-measure on the Postgres path against the committed label
   fixture and publish the result, including a null result.

Stage 1 has no prerequisites and can start the moment the spec is approved. Stages
2–4 are individually implementable but **not individually shippable**: no single fix
reaches significance alone, so merging a subset would ship an unmeasured change.
Stage 5 gates the merge.

## Flag discipline

The eval-set's fidelity gate is the mechanism that makes the measurement credible,
and it is reproducible in the product's own tests: each candidate must reproduce the
shipped scorer **exactly** with its own flag off. Carry that into implementation as
four independent module-level flags (naming fixed at implementation, e.g.
`SCORE_SKILL_ID`, `USE_IDF`, `USE_LENGTH_NORM`, `SPLIT_CAMEL_CASE`) so that:

- a test can assert the shipped behaviour is recoverable, which is the parity
  harness's baseline;
- R-8 can attribute a Postgres-path regression to one fix rather than to the
  package;
- the flags can be **removed** at delivery once R-8 passes, leaving the four fixes
  unconditional. Shipping four permanent feature flags for a measured-sufficient
  package is worse than shipping the package.

Flag removal is a task in `tasks.md`, not an assumption.

## Design Per Requirement

### R-1: Score the `skill_id` slug — *depends on OQ-1(b)*

- affected: `services/scoring.py::score()` only.
- approach: add a fourth token set,
  `id_tokens = set(tokenize(skill.skill_id))`, credited at the weight OQ-1(b)
  fixes. The measurement used `TAG_WEIGHT` (2.0) and every published number assumes
  it, so the **default design is `TAG_WEIGHT`** and any other value requires
  re-measurement, not a code review decision.
- alternatives considered: a distinct `SKILL_ID_WEIGHT` constant (cleaner to tune,
  but an unmeasured value — rejected); folding the slug into `title_tokens` (would
  silently credit it at 3.0, also unmeasured — rejected).
- note: `skill_id` is the primary key, so **no column is added** anywhere. The
  "no schema change" claim in memo §4.4 is true of the table and false of the
  index — see R-5.

### R-2: Corpus-derived IDF weighting — *depends on OQ-2, the largest design risk*

- affected: `services/scoring.py` (a signature change — `score()` is pure over
  **one** skill today and IDF is a corpus property), plus whatever supplies the
  statistics.
- approach, **recommended**: introduce an explicit, immutable statistics value
  (`CorpusStats` holding `N` and a `df` mapping) computed **once per request over
  the whole catalog, ignoring `source`/`tag` filters**, and pass it to `score()`.
  Both backends then compute the same table from the same population, which is what
  makes the score backend-independent (OQ-2 option (i)).
- alternatives considered and why rejected:
  - *Statistics over the pool passed to `rank()`* (OQ-2 (iii)) — **rejected**: the
    two callers pass different pools (`_all_records(source, tag)` vs prefiltered
    `candidates`), so the same query would score differently per backend. This
    breaks the byte-identical invariant directly and is the single most likely way
    to implement IDF wrongly.
  - *A statistics table maintained at sync time* (OQ-2 (ii)) — **not rejected, but
    deferred**: it removes a per-request aggregation, at the cost of a new table, a
    staleness window between sync and query, and a second migration in the same
    slice as R-5. At 18 documents the aggregation is trivially cheap; the trigger to
    revisit is the same catalog-growth signal as the pgvector scale trigger
    (>2,000 skills). If OQ-2 chooses it, the `df` map must still be computed with
    R-4's tokenizer or `df` is wrong.
- **Signature-change consequence.** `score(query, skill)` becoming
  `score(query, skill, stats)` touches its callers and its tests. Check for callers
  outside `skill_store.py` before designing the signature (the tool-gateway has
  none; the portal has none). A default argument preserves the old call shape but
  hides a wrong-by-default corpus — prefer an explicit required parameter.
- tokenizer coupling: `df` must be computed with the **same** `tokenize()` the
  scorer uses, including R-4's CamelCase rule and R-4's whole-token decision. Two
  tokenizers in one file is the failure mode.

### R-3: Sublinear body-length normalization — *no OQ dependency*

- affected: `services/scoring.py::score()`, one line.
- approach: multiply the capped body contribution by
  `1 / log2(2 + len(body) / 1000)`. Keep `BODY_OCCURRENCE_CAP = 5` and apply the
  norm to the capped value.
- why it is safe: the factor depends only on the document, so it is
  backend-neutral by construction — the one fix of the four that needs no corpus
  state and no prefilter change. `2 + len/1000 ≥ 2`, so `log2 ≥ 1` and the factor
  is in `(0, 1]`; there is no reachable division by zero, and an empty body gives
  exactly 1.0 (harmless, since an empty body also has zero occurrences).
- alternatives considered: `len(tokens)` instead of `len(body)` (arguably a truer
  length measure, but **not what was measured** — rejected); removing the cap in
  favour of the norm alone (unmeasured — rejected).

### R-4: CamelCase-splitting tokenization — *depends on OQ-2 for the whole-token rule*

- affected: `services/scoring.py::tokenize()`, and by consequence R-2's `df`, R-5's
  prefilter, and 8 assertions in `tests/test_scoring.py`.
- approach: replace `TOKEN_PATTERN = re.compile(r"[a-z0-9]+")` with a two-step
  tokenize — first split the CamelCase/digit boundaries of the lowercased-and-
  original text, then apply the existing alphanumerics rule to each part. The
  existing pattern is retained as the final step so no behaviour changes for text
  that has no CamelCase.
- the case table is **fixed at implementation and committed as tests**, because the
  rule determines `df` and the prefilter: `KubePodNotReady`, `CrashLoopBackOff`,
  `HTTP503` (acronym run — `http` + `503`, or `h` `t` `t` `p` `503` if done
  naively), `pgBouncer`, `v0211`, `RealPlayer2`, plus the already-lowercase and
  digit-only cases that must be unaffected.
- **whole-token decision (OQ-2).** Two coherent rules:
  - *keep both* — `KubePodNotReady` → `kubepodnotready`, `kube`, `pod`, `not`,
    `ready`. Preserves today's exact-match behaviour for a document whose title is
    the whole token, and keeps `df` well-defined for both forms. **Recommended**:
    it is strictly additive on the query side, so it cannot lose a match the
    shipped scorer makes.
  - *parts only* — smaller index and simpler `df`, but a document containing only
    the whole token stops matching a query containing only the whole token unless
    the document side splits too, which is exactly the R-5 mirror problem.
  A mixed application (whole token in `tokenize()`, parts in `df`) is silently
  wrong and is what R-4's acceptance criterion exists to prevent.
- the 8 exact-score assertions in `tests/test_scoring.py` change **deliberately and
  visibly**: `score("KubePodNotReady", skill) == 7.0` encodes the defect. Review
  must see the old and new expected values, not a loosened comparison.

### R-5: Cross-backend parity for the new scorer — *depends on OQ-5; the highest-risk stage*

- affected: `services/skill_store.py` — `_SEARCH_VECTOR`, the `idx_skills_search`
  DDL, and a migration; no change to `rank()`'s call sites beyond what R-2's
  signature requires.
- the invariant to preserve: the prefilter is an **over-approximation** of the
  scorer's non-zero set. Over-admitting costs a little Python re-ranking time and
  is invisible; under-admitting is a **silent recall bug** that no test currently
  catches.
- **Prefilter strategy** — two coherent designs, chosen at OQ-5:
  1. *Mirror the tokenizer in SQL.* Add `skill_id` to the `to_tsvector`
     expression, and express R-4's split as an **IMMUTABLE** SQL function so the
     document side matches the query side. Cleanest and keeps the index selective,
     but the DDL already records the constraint that bites here: the GIN expression
     may only use IMMUTABLE functions, which is why `array_to_string` /
     `array_out` (STABLE) keep tags out of the index today. A hand-written
     IMMUTABLE SQL/PLpgSQL split function must be proven IMMUTABLE and must not
     drift from Python's rule — two implementations of one tokenizer, in two
     languages, is a maintenance liability that must be pinned by a test comparing
     them over the case table.
  2. *Widen the prefilter instead.* Keep `to_tsvector('simple', …)` as-is (no
     CamelCase splitting in SQL), **add `skill_id`** to the covered columns, and
     additionally admit rows via a case-insensitive substring/`LIKE` path for query
     tokens that CamelCase-splitting produced. Over-admits more, needs no SQL
     tokenizer, and therefore cannot drift from Python. Cost: a `LIKE` arm is not
     GIN-served, so at catalog scale this is a sequential scan — acceptable at 18
     documents, and the >2,000-skill trigger is the point to revisit.
     **Recommended for this slice**, because the failure mode is a slow query
     (loud, measurable) rather than a missing row (silent).
- **Migration.** `_DDL` uses `CREATE INDEX IF NOT EXISTS`, so an existing
  deployment keeps the **old** index after a code change — the new expression
  would then be unindexed. The migration must drop and recreate. `CREATE INDEX
  CONCURRENTLY` cannot run inside a transaction block, so the migration cannot be
  a single transactional step; decide between (a) concurrent create-then-drop with
  a window where both exist, or (b) a transactional drop-and-recreate with a
  window where search is unindexed. At 18 rows (b) is instantaneous; the answer
  must still be written down because the row count is not the point of the
  requirement.
- **Blast radius.** The `skills` database shares the `postgres-0` StatefulSet's
  1 Gi PVC with `audit`, `incidents` and `sessions`. A migration failure here is
  not contained to skills. Rollback must be tested, not assumed.
- latency: measured **end to end** on the Postgres path against the tool-gateway's
  10.0 s `REQUEST_TIMEOUT_SECONDS`. The eval-set's p50 2.726 ms is pure-Python
  `rank()` offline and must not be cited as an end-to-end figure.

### R-6: An enforced cross-backend parity harness — *no OQ dependency; do this first*

- affected: `products/skills-hub/tests/test_skill_store.py` (new test class), plus
  a correction to `docs/specs/SPEC-014-skills-and-grounded-guidance/tasks.md`.
- approach: one test class that builds the **same** corpus into both an
  `InMemorySkillStore` and a `PostgresSkillStore` and asserts identical
  `skill_id` ordering for a committed query set. The Postgres side needs a real or
  faithfully-faked `to_tsvector` — the existing tests use a `_fake_connect`
  returning canned rows, which cannot exercise the prefilter at all. **This is the
  one genuinely new test-infrastructure decision in the spec**: either drive a real
  Postgres (as SPEC-063's campaign does) or assert on a recorded prefilter
  behaviour. Decide at implementation; a fake that returns every row would make the
  harness pass vacuously and must not be accepted.
- query set: the union of the 63-query audit pool (eval-set §6.1 strata A + B) and
  the 18 authored stratum-C paraphrases, committed as a fixture so the harness is
  reproducible. The labeled 38 are 20 stratum-B queries plus those 18, so the
  stratum-B half is already inside the 63 — **confirm the distinct count from the
  fixture at implementation rather than assuming it**, since the harness's value is
  that it covers every query whose behaviour could change.
- sequencing: land **before** R-1..R-5 so the baseline is established and any
  pre-existing violation is found by the harness rather than blamed on the new
  code.
- SPEC-014 bookkeeping: its `tasks.md` line 32 claims a delivered *"byte-identical
  ordering parity test vs in-memory store"* and names `plainto_tsquery`, while the
  shipped code OR-joins `to_tsquery` lexemes and
  `test_search_joins_multi_word_queries_with_or` documents that `plainto_tsquery`
  would be wrong. SPEC-014 is `delivered`, so correct it by **annotation** (a dated
  note recording the drift and pointing at this spec), not by silent edit.

### R-7: Product-side de-duplication guardrail — *depends on OQ-6 for the sync half*

- affected: `services/scoring.py::rank()`; optionally `services/sync.py` if OQ-6
  adds ingestion-time rejection.
- approach: in `rank()`, after scoring and before `hits.sort(...)`, collapse hits
  whose body hash matches one already kept, retaining the **lowest `skill_id`**
  (consistent with the existing ascending tie-break, so the survivor is
  deterministic and explainable). Then sort, then `[:limit]` — de-duplication must
  precede truncation, since the measured defect was wasted slots.
- hash choice: `md5(body)`, matching the `body_md5` the label fixture already pins,
  so the identity key is consistent with the measurement artifact. MD5 here is a
  **content-identity key, not a security digest** — record that explicitly so a
  future security review does not flag it as a weak hash in a security context.
- **not `parse_sources`.** `core/config.py::parse_sources` validates
  `SKILLS_SOURCES` JSON (duplicate `source_id`, malformed ids, missing
  type-specific fields) and never sees file content, so it cannot detect content
  overlap. Memo §4.4 and the CHANGELOG both describe it as "still accepting two
  sources covering the same files", which is imprecise; this plan records the
  correction.
- if OQ-6 chooses sync-time rejection: the body hash exists at sync, so a duplicate
  can be detected there and surfaced as an operator-visible error. Decide the
  failure posture (reject the source, or ingest and warn) deliberately — rejecting
  a source registration is an availability change for whoever configured it.
- audit consequence: `skill_searched` details `result_count` and `skill_ids` change
  when duplicates collapse. Existing event type, existing fields, new values; no
  vocabulary change.

### R-8: Re-measurement on the shipped path — *the merge gate*

- affected: the eval-set artifact (a new section, appended — it is a measurement
  record and its published numbers are not rewritten), plus a committed harness.
- approach: reuse the offline harness that produced §8, but drive it through
  `PostgresSkillStore.search()` rather than `rank()` directly, so the prefilter is
  in the measured path. Assert the fixture's `body_md5` per document **first** and
  fail loudly on mismatch.
- report per backend, and report the full required metric set: zero-relevant rate
  (**not** zero-hit rate alone), distinct-document variants, P@5, R@5/@10, MRR,
  MRR(2), nDCG@10, rank stability, and latency p50/p95 measured end to end.
- statistics: reuse the pre-registered method unchanged — paired bootstrap, 10,000
  resamples, seed 20261001, 95% CIs on per-query deltas, plus an exact two-sided
  sign test on discordant top-1 pairs. Do **not** rely on Precision@5 (its baseline
  CI lower bound rounds to zero; the eval-set already flags it borderline).
- disclose: the Q63 regression, and abstention unchanged at 4/38.
- **null-result path.** If the Postgres-path gain is not outside the noise band,
  publish that, do not merge R-1..R-5, and record the outcome on the backlog row.
  This is a real possible ending and `tasks.md` carries it as a task rather than
  treating it as a failure.

### R-9: Contract and living-doc updates — *no OQ dependency, but OQ-3 shapes the docstring*

- affected: `products/skills-hub/README.md` (the endpoint summary restates the
  weighting), `docs/guides/skills-guide.md` (check for restated weighting),
  `services/scoring.py`'s module docstring (states the fixed weighting and the
  byte-identical rationale as load-bearing documentation), SPEC-014's R-3
  annotation, the memo + eval-set status headers (pointer only — they are
  measurement artifacts and their text is not rewritten), `CHANGELOG.md`,
  `VERSION` + lockstep, `docs/specs/README.md`, the delivery-roadmap row.
- no JSON schema work. `score` is published on the HTTP response but appears in no
  `shared/shared-contracts` schema; `skill-format.md` covers the document format.
  Record the published-vs-validated distinction in the README so the next change
  does not have to re-derive it.

## Sequencing And Dependencies

1. **R-6 parity harness** — depends on nothing. Land first; establishes the
   baseline and the enforcement mechanism everything else is measured against.
2. **OQ resolution** — OQ-1(b), OQ-2, OQ-5 must be answered before stage 3; OQ-3
   and OQ-4 before stage 5; OQ-6 any time before R-7's sync half.
3. **R-3** (length norm) then **R-1** (`skill_id`) then **R-4** (CamelCase) then
   **R-2** (IDF) — each behind its flag, each fidelity-gated. Ordered cheapest and
   least-coupled first: R-3 is one line and backend-neutral; R-1 is one field; R-4
   changes the tokenizer that R-2's `df` depends on, so R-4 precedes R-2; R-2 is
   the signature change and comes last.
4. **R-5** prefilter + migration — depends on R-4's tokenizer rule being final,
   since the prefilter must mirror it (or deliberately over-admit instead).
5. **R-7** de-duplication in `rank()` — independent of 3 and 4; can land in
   parallel. Its sync-time half waits on OQ-6.
6. **R-8** re-measurement — depends on 3, 4 and 5 all being in place. **This is
   the merge gate**, not a post-merge report.
7. **R-9** docs + flag removal + version — after 6 passes.

Stages 3, 4 and 5 are **not separately shippable**. No single fix reaches
significance alone, so a partial merge ships an unmeasured subset.

## Test Strategy

- **unit** (`tests/test_scoring.py`): the CamelCase case table; the IDF formula
  against hand-computed `N`/`df`; the length-norm factor's bounds including empty
  and single-character bodies; the cap-then-normalize order; `skill_id` credited at
  the OQ-1(b) weight; **all four flags off reproduces the shipped scorer exactly**
  (the fidelity gate). The 8 existing exact-score assertions are updated with old
  and new values both visible in review.
- **parity** (`tests/test_skill_store.py`, R-6): both backends, same corpus, same
  committed query set (R-6 above), identical `skill_id` ordering — plus identical
  **scores**, since backend-independent IDF (R-6/R-2) is a numeric claim, not only
  an ordering one.
- **prefilter** (R-5): the `_SEARCH_VECTOR` and GIN index expressions are compared
  for equality so the index cannot silently stop being used; a slug-only query
  returns rows on Postgres; **no query in the 63-query pool returns fewer rows than
  it does today**.
- **de-duplication** (R-7): a corpus with two byte-identical bodies under different
  `source_id`s returns one hit and the freed slot is filled by the next distinct
  document; collapse happens before `[:limit]`.
- **migration** (R-5): the index is actually rebuilt on an existing database (not
  silently skipped by `CREATE INDEX IF NOT EXISTS`), and the rollback path runs.
- **evaluation** (R-8): the fixture's `body_md5` is asserted before any metric is
  computed; results are reported per backend; the null-result path is a coded
  outcome, not an unwritten one.
- **regression sweep**: `products/tool-gateway/tests/test_skills_connector.py`
  (asserts the request path, not scores, so it should pass unchanged — verify, do
  not assume), and `shared/platform-ops/e2e/skills-demo.sh`, which searches
  `q=KubePodNotReady` and is directly affected by R-4.
- **full root `make verify`** green at delivery, per ADR-0008: every `R-x`
  criterion maps to at least one asserting test.

## Rollout And Migration

- **deployment change: one index migration** (R-5). No new environment variable is
  proposed for the delivered state — the four flags are measurement instruments and
  are removed at R-9. If OQ-2 chooses a sync-time statistics table, that is a
  **second** migration and a new staleness consideration.
- **backward compatibility:** the HTTP response shape is unchanged; `score` values
  change and are not schema-validated, not portal-rendered, and dropped by the
  tool-gateway connector, so no consumer reads them. **Ordering changes** — that is
  the intended effect, is measured, and carries one known mild regression (OQ-4).
  `skill_searched` audit detail values change when R-7 collapses duplicates.
- **rollback:** revert the scorer to the four flags off (the fidelity gate
  guarantees this reproduces today's behaviour exactly) and restore the previous GIN
  expression. The rollback must be **tested**, because the `skills` database shares
  its PVC with `audit`, `incidents` and `sessions`.
- **no feature gate at delivery.** Unlike SPEC-064's `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED`,
  this is not an opt-in behaviour: a partially-improved retrieval path is worse
  than either extreme, and the fixes are measured sufficient. If the operator wants
  a gate, that is a scope change and belongs in OQ-1's resolution.

## Risks

| Risk | Why it is real | Mitigation |
|---|---|---|
| Silent Postgres under-admission | The prefilter's failure mode is a *missing row*, which no current test detects | R-5's "no query returns fewer rows than today" criterion + R-6 harness over the 63-query pool |
| Two tokenizers drifting (Python vs SQL) | R-4's rule would exist in two languages | Prefer the widened-prefilter design (no SQL tokenizer); if a SQL split function is used, pin it against the Python case table by test |
| IDF computed over the wrong pool | `rank()`'s two callers pass different pools; the obvious implementation is the wrong one | R-2's backend-independence criterion asserts numeric equality across backends, not just ordering |
| Migration silently skipped | `CREATE INDEX IF NOT EXISTS` keeps the old index after an expression change | R-5 test asserts the index is actually rebuilt on an existing database |
| Measured gain does not reproduce on the shipped path | 0.711 is a memory-path upper bound | R-8 is the merge gate, with a coded null-result path |
| Test suite "fixed" by weakening assertions | 8 exact-score assertions encode the old behaviour | R-4's criterion forbids loosening to vague comparisons; review sees old and new values |
| Shared-PVC blast radius | `skills` shares `postgres-0`'s 1 Gi PVC with `audit`, `incidents`, `sessions` | Tested rollback; OQ-5 must state the concurrency window explicitly |
