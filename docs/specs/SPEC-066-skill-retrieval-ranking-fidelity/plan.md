# SPEC-066 Plan: Skill Retrieval Ranking Fidelity — The Four Measured Lexical Fixes, Cross-Backend Parity, And A De-Duplication Guardrail

> **Provisional banner lifted 2026-10-02.** This plan was authored alongside
> `spec.md` at drafting time per the SPEC-064/SPEC-065 same-session precedent, and
> was banner-marked provisional because SPEC-066 was `draft` with six unresolved
> Open Questions. All six are now resolved in `spec.md`'s *Open Questions* section,
> each against the shipped code, and the spec is `approved`. **The resolutions
> changed this plan in three places**, and those sections carry the change inline
> rather than being left as the draft's recommendation: R-2 (sync-time persisted
> statistics, not a per-request catalog read), R-5 (prefix lexemes plus a
> versioned index name, no SQL tokenizer and no `CONCURRENTLY`), and R-7 (the
> sync-time half is deferred, and one claim in the draft was false — see the
> correction recorded there).
> Nothing here is implemented. Implementation, commit/push, deployment and the
> migration remain separate authorization boundaries not granted by approval.

## Approach

The measurement says four cheap lexical changes close the ordering gap. Reading the
shipped code says those four changes were measured on a path the product does not
serve: the evaluation ran `rank()` over a corpus export, while the deployed
Postgres backend runs `rank()` over whatever a `to_tsvector` prefilter admitted.
So the work is **not** "edit `score()`" — it is six stages, and the scoring stages
are the easy ones:

0. **Verify** (Stage 0) — two facts the resolutions could not settle from the
   repository, because they are properties of a running cluster and of an
   uncommitted harness rather than decisions: whether PostgreSQL prefix lexemes
   behave as R-5 assumes against `postgres-0`, and which CamelCase-splitting
   variant actually produced 0.711. Both have named fallbacks, so neither blocks
   approval; both block *implementation* of the stage that depends on them.
1. **Enforce** (R-6) — build the cross-backend parity harness **first**, before any
   scoring change, so the invariant SPEC-014 documents but does not test becomes
   the thing that catches R-1..R-5 breaking it.
2. **Score** (R-1..R-4) — the four measured fixes, behind flags, each
   fidelity-gated on reproducing the shipped scorer exactly with its own flag off,
   exactly as the eval-set gated its candidates (**38/38 identical**). Flags are a
   measurement instrument, not a permanent feature set; see "Flag discipline".
3. **Reach** (R-5) — the prefilter/index co-change that makes R-1 ship and R-4 not
   regress, plus its migration.
4. **Guard** (R-7) — content-hash de-duplication in `rank()`.
5. **Prove** (R-8) — re-measure on the Postgres path against the committed label
   fixture and publish the result, including a null result.

Stage 1 has no prerequisites. Stages 2–4 are individually implementable but **not
individually shippable**: no single fix reaches significance alone, so merging a
subset would ship an unmeasured change. Stage 5 gates the merge.

## Resolved At Plan Time

The six Open Questions were resolved against the shipped code on 2026-10-02;
`spec.md`'s *Open Questions* section carries the evidence for each. The design
decisions that follow, in one place:

- **`score` semantics (OQ-1a).** May change meaning with **no contract version
  bump** — it is in no `shared-contracts` schema, is not portal-rendered, and is
  dropped by the tool-gateway connector's `_MATCH_KEYS`. Its *weighting* is
  nonetheless published prose in four places, so R-9 reaches all four.
- **`skill_id` weight (OQ-1b).** `TAG_WEIGHT` (2.0), the value the measurement
  used. Any other value is a fifth, unmeasured candidate under R-8.
- **IDF statistics (OQ-2).** Computed in **Python at sync time** and persisted,
  passed into `rank()` by the caller. SQL-side `df` is *impossible* after R-4; a
  per-request whole-catalog read defeats the prefilter. `tokenize()` **retains the
  whole CamelCase token alongside its parts**.
- **Byte-identical invariant (OQ-3).** **Preserved as written; no ADR.** The memo's
  narrowing recommendation was scoped to *semantic* retrieval and does not apply.
  This and OQ-5 are one decision: preserving the invariant is what forces the
  widen-the-prefilter strategy and rules out a SQL tokenizer.
- **Q63 re-ordering (OQ-4).** **Accepted**, on two conditions enforced in R-8:
  reported on the Postgres path (where a re-ordering could become a
  *disappearance*, which fails the merge gate) and named in the delivery release
  note.
- **GIN migration (OQ-5).** Versioned index name — create `idx_skills_search_v2`,
  retain `idx_skills_search` for one release. No SQL function. **No
  `CONCURRENTLY`** — unusable, because `_DDL` runs as one multi-statement string on
  a connection opened `autocommit=False`.
- **Sync-time overlap rejection (OQ-6).** **Deferred with a named trigger.** Only
  R-7's `rank()` de-duplication ships. Feasible (`_resolve_compositions` is the
  precedent) but the wrong layer: nondeterministic precedence across jittered sync
  loops, the eventual-consistency hole the composition code already documents, and
  no store surface that returns all bodies.

Two items are **Stage 0 verification tasks** rather than decisions, because they
are checkable facts about a running cluster and an uncommitted harness: the
PostgreSQL prefix-lexeme behaviour R-5 relies on, and which CamelCase variant
produced 0.711.

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

### R-1: Score the `skill_id` slug — *OQ-1(b) resolved: `TAG_WEIGHT` (2.0)*

- affected: `services/scoring.py::score()` only.
- approach: add a fourth token set,
  `id_tokens = set(tokenize(skill.skill_id))`, credited at **`TAG_WEIGHT` (2.0)**.
  OQ-1(b) is resolved, not merely defaulted: the measurement used 2.0 and every
  published number in this spec assumes it, so any other value is a *different,
  unmeasured candidate*. If another weight is ever wanted it is tested as a fifth
  candidate under R-8 — it is not chosen by argument in code review.
- alternatives considered: a distinct `SKILL_ID_WEIGHT` constant (cleaner to tune,
  but an unmeasured value — rejected); folding the slug into `title_tokens` (would
  silently credit it at 3.0, also unmeasured — rejected).
- note: `skill_id` is the primary key, so **no column is added** anywhere. The
  "no schema change" claim in memo §4.4 is true of the table and false of the
  index — see R-5.

### R-2: Corpus-derived IDF weighting — *OQ-2 resolved: sync-time statistics, Python-computed*

- affected: `services/scoring.py` (a signature change — `score()` is pure over
  **one** skill today and IDF is a corpus property), `services/skill_store.py`
  (both backends compute and carry the statistics), and `services/sync.py` (the
  refresh point).
- approach, **chosen at OQ-2**: introduce an explicit, immutable statistics value
  (`CorpusStats` holding `N` and a `df` mapping) computed **in Python at sync
  time** — after each successful `replace_source` — persisted (a table on
  Postgres, the equivalent structure in memory), and passed into `rank()` by the
  caller. Both backends then score against the same table derived from the same
  population, which is what makes the score backend-independent.
- **Why the draft's recommendation was overturned.** This plan originally
  recommended computing the table *once per request over the whole catalog,
  ignoring `source`/`tag` filters*, and treated a sync-time table as "not rejected,
  but deferred". Resolving OQ-2 against the shipped code eliminated that option for
  three reasons, in increasing order of force:
  - *It reads the corpus the prefilter exists to avoid reading.* A per-request
    whole-catalog aggregation on the Postgres path defeats the point of
    `_SEARCH_VECTOR`, and scales badly against the memo's own >2,000-skill trigger.
  - *`rank()` is **synchronous and pure** while both stores are `async`.* The
    statistics therefore cannot be fetched inside it — the caller must compute them
    and pass them in. This makes the **`rank()` signature change** the load-bearing
    part of R-2 rather than an incidental refactor, and it is true of both options.
  - *After R-4, SQL-computed `df` is **impossible**, not merely disfavoured.*
    Python's `tokenize()` splits CamelCase and `to_tsvector('simple', …)` does not,
    so a `df` derived from SQL lexemes is a different statistic from the one the
    scorer uses, and the byte-identical invariant breaks numerically. Any surviving
    option must compute `df` in Python. Only the sync-time option does that without
    a per-request catalog read.
- alternatives considered and why rejected:
  - *Statistics over the pool passed to `rank()`* (OQ-2 (iii)) — **rejected**: the
    two callers pass different pools (`_all_records(source, tag)` vs prefiltered
    `candidates`), so the same query would score differently per backend. This
    breaks the byte-identical invariant directly and is the single most likely way
    to implement IDF wrongly. *Refinement established while resolving OQ-2:* both
    callers **do** apply the same `source`/`tag` filters, so the divergence is the
    tsvector prefilter **alone** — which is exactly why the pool is unusable and
    why a global `df` is well-defined.
  - *Per-request whole-catalog read* (OQ-2 (i), the draft's recommendation) —
    **rejected** for the three reasons above.
  - *In-process cache instead of persisted state* — **rejected on principle, not
    on cost.** At `skills-hub-deployment.yaml`'s `replicas: 1` it would not
    observably diverge, but that makes correctness depend on a deployment shape
    rather than on the design. Persisting it keeps the invariant true at any
    replica count.
- **Staleness is a recorded property, not a hidden one.** The refresh rides the
  existing sync cycle, so `df` lags a catalog change by up to
  `SKILLS_SYNC_INTERVAL_SECONDS` (default **300**). Because `df` is global, a
  per-source swap invalidates all of it and the refresh is a **full catalog pass**
  — trivial at 18 documents, and still cheap next to sync's git clone at 2,000.
- **Signature-change consequence.** `score(query, skill)` becoming
  `score(query, skill, stats)` touches its callers and its tests, and `rank()`
  gains the same parameter. Check for callers outside `skill_store.py` before
  designing the signature (the tool-gateway has none; the portal has none). A
  default argument preserves the old call shape but hides a wrong-by-default
  corpus — prefer an explicit required parameter.
- tokenizer coupling: `df` must be computed with the **same** `tokenize()` the
  scorer uses, including R-4's CamelCase rule and R-4's whole-token retention. Two
  tokenizers in one file is the failure mode; a test asserts the statistics path
  and the scoring path call the same function.
- **Explainability survives as a criterion.** The score must stay decomposable
  into per-token, per-field contributions (`weight × idf(token) × norm(document)`).
  This is the surviving obligation from the memo's *"do not silently redefine
  `score`"* — a prohibition written about cosine fusion, which this spec does not
  do, but whose *reason* (a reviewer must be able to answer "why did this rank
  first?" during an incident review) binds here too.

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

### R-4: CamelCase-splitting tokenization — *OQ-2's second half resolved: retain the whole token*

- affected: `services/scoring.py::tokenize()` **and `score()`'s aggregation**, and
  by consequence R-2's `df`, R-5's prefilter, and the assertions in
  `tests/test_scoring.py`.
- approach: replace `TOKEN_PATTERN = re.compile(r"[a-z0-9]+")` with a two-step
  tokenize — first split the CamelCase/digit boundaries of the **original-cased**
  text, then apply the existing alphanumerics rule to each part and lowercase. The
  existing pattern is retained as the final step so no behaviour changes for text
  that has no CamelCase. **Case must survive until after the split**: lowercasing
  first, then splitting, splits nothing.
- **R-4 is not a `tokenize()`-only change. Measured, not reasoned.** `score()`
  aggregates its four inputs two different ways: `title` and `tags` through a
  `set` (idempotent — duplicate tokens collapse) but `body` through
  `Counter(tokenize(body))` and `query` through a `for` loop over a **list**
  (neither idempotent — multiplicity *is* the value). Running the shipped `score()`
  with a naive retention tokenizer that concatenates the whole token with its parts
  inflates every one of them: `test_title_match_scores_three` 3.0 → **6.0**,
  `test_tag_match_scores_two` 2.0 → **4.0**, and
  `test_body_occurrences_score_one_and_saturate` 3.0 → **10.0** for three
  occurrences and 5.0 → **10.0** for the saturating cap, so the pair becomes
  indistinguishable. Only `test_weights_compose_per_token` (7.0 → 29.0) and the
  three zero cases (0.0 → 0.0) behave sanely. The position-aware shape below
  restores **every one** of those to its shipped value except
  `test_weights_compose_per_token`, which becomes **27.0**.
  - The naive shape **breaks R-4's own "already-lowercase text is unaffected"
    criterion**: `"pod"` tokenizes to `["pod", "pod"]` because for a non-CamelCase
    run the whole token *is* the only part, and every ordinary query silently
    doubles. On the body side the inflation is worse than doubling — each surface
    occurrence emits two tokens, so `BODY_OCCURRENCE_CAP` is reached at **half** the
    real occurrence count, which changes the cap's meaning rather than the score's
    scale.
- the required shape is therefore **position-aware**: one token *set* per surface
  alphanumerics run, the whole token admitted only when it differs from its parts,
  body occurrences counted **per run** rather than per emitted token, and query
  tokens de-duplicated before the scoring loop. With that shape **7 of the 8
  existing exact-score assertions are unchanged** and only
  `test_weights_compose_per_token` moves (7.0 → 27.0), which is the honest reading
  of "8 assertions change deliberately" — see the correction below.
- **R-4 must not ship without R-2.** Retention makes sub-tokens score-bearing:
  `KubePodNotReady` now contributes `not` and `ready` as query tokens, which the
  shipped tokenizer never produced. R-2 forbids a stoplist by design, so the only
  thing that keeps `not` from carrying full title weight is its **IDF** — a high-`df`
  token is down-weighted automatically. Stage 2's order (R-3 → R-1 → R-4 → R-2)
  therefore measures R-4 **with R-2's flag on**, or not at all; an R-4-alone fidelity
  gate would be measuring the inflated column above.
- retention also introduces a **query-shape asymmetry** worth recording rather than
  hiding: measured, `score("KubePodNotReady", title="KubePodNotReady")` = **15.0**
  while `score("pod not ready", title="pod not ready")` = **9.0**, because one
  identifier-shaped surface form yields five credit-bearing tokens and the phrase
  yields three. Scores are therefore **not comparable across query shapes**, which
  matters for R-9's published prose and for any future threshold work (the separate
  abstention backlog row), and is harmless for ordering *within* one query only to
  the extent every candidate matches the same number of the query's tokens — which
  they do not. The intended win is real and measured alongside it:
  `score("pod not ready", title="KubePodNotReady")` goes **0.0 → 9.0**, exactly
  matching the plain-title case.
- the case table is **fixed at implementation and committed as tests**, because the
  rule determines `df` and the prefilter: `KubePodNotReady`, `CrashLoopBackOff`,
  `HTTP503`, `pgBouncer`, `v0211`, `RealPlayer2`, plus the already-lowercase and
  digit-only cases that must be unaffected.
  - **Correction to this plan's own earlier text.** The draft glossed `HTTP503` as
    "acronym run — `http` + `503`, or `h` `t` `t` `p` `503` if done naively".
    **Neither is what the described rule produces.** The two standard CamelCase
    boundaries (`lower|Upper` and `Upper|UpperLower`) do not fire inside `HTTP503`
    at all — there is no lowercase before the capitals and `P5` is not
    upper-then-lower — so measured output is the **single token `http503`**. `v0211`
    likewise stays whole. Splitting an acronym run from a trailing number needs an
    **explicit letter↔digit boundary** as a third rule, and that choice is
    consequential: without it a query `503 error` cannot reach a document titled
    `HTTP503`, and with it `v0211` risks becoming `v` + `0211`. Decide it in the
    case table, in both directions, and pin it — do not inherit the draft's gloss.
- **whole-token decision — resolved: keep both.** `KubePodNotReady` →
  `kubepodnotready`, `kube`, `pod`, `not`, `ready`. Retention is a strict superset
  for matching, so it cannot reduce recall relative to today, and it preserves
  exact-identifier lookups — an operator who types a whole skill name still matches
  it as one token, which is the behaviour R-1 exists to add. It also keeps `df`
  well-defined for both forms, so R-2 needs no special case.
  - *parts only* — rejected: smaller index and simpler `df`, but a document
    containing only the whole token stops matching a query containing only the whole
    token unless the document side splits too, which is exactly the R-5 mirror
    problem, and it would regress the exact-name lookup R-1 adds.
  A mixed application (whole token in `tokenize()`, parts in `df`) is silently
  wrong and is what R-4's acceptance criterion exists to prevent.
- **Carry the caveat, do not bury it.** The offline harness that produced 0.711 is
  **not committed** — `git ls-files` shows only the label fixture and the two prose
  artifacts, and the eval-set records this change only as "tokenizer regex" (§8.2's
  candidate row 2c). So
  *which* variant was actually measured cannot be confirmed from the repository.
  Retention is the default on its merits; Stage 0 re-derives the measured variant,
  and if it turns out the whole token was dropped, R-8 re-measures this variant
  rather than assuming 0.711 carries over to it.
- the exact-score assertions in `tests/test_scoring.py` change **deliberately and
  visibly**: `score("KubePodNotReady", skill) == 7.0` encodes the defect. Review
  must see the old and new expected values, not a loosened comparison.
  - **Correction to this plan's own earlier text: it is 1 of 8, not 8 of 8.** The
    draft said "the 8 exact-score assertions change". Verified against the file,
    there are exactly 8 `assertEqual(score(...), <value>)` calls, and with the
    position-aware shape above **7 keep their current value unchanged** — which is
    the point of the "already-lowercase text is unaffected" criterion. Only
    `test_weights_compose_per_token` (7.0 → 27.0) must change. Two consequences the
    draft missed:
    - If more than one assertion changes, **the implementation is wrong**, not the
      test. That makes the count a usable review signal rather than a chore.
    - `test_body_occurrences_score_one_and_saturate` asserts **3.0** for three
      occurrences and **5.0** for the saturating cap, in the same test, on fixtures
      whose `skill_id`s are `a/pod` and `a/long`. R-1 scores `skill_id` at
      `TAG_WEIGHT`, so the `a/pod` fixture's slug matches the query `pod` and adds
      2.0 — turning 3.0 into 5.0, **the very value the next line asserts for the
      cap**, which would make the pair indistinguishable and hide the cap. The right
      fix for that assertion and for `test_title_match_scores_three` (also on an
      `a/pod` fixture) is to change the **fixture's `skill_id`** to a slug sharing no
      token with the query, not to change the expected number — otherwise the tests
      stop isolating the field their names claim to test.
    - R-3's length norm makes body contributions **non-integral** (`3 × 1/log2(2 +
      12/1000)` ≈ 2.974), so those two assertions cannot stay `assertEqual` against
      a decimal literal. Compute the expected value **from the formula in the test**
      — spelling out the norm — rather than hard-coding a rounded number or relaxing
      to a vague comparison. That keeps the assertion exact and self-documenting,
      which is what "do not weaken" means here.

### R-5: Cross-backend parity for the new scorer — *OQ-5 resolved; still the highest-risk stage*

- affected: `services/skill_store.py` — `_SEARCH_VECTOR`, the `idx_skills_search`
  DDL, and the migration; no change to `rank()`'s call sites beyond what R-2's
  signature requires.
- the invariant to preserve: the prefilter is an **over-approximation** of the
  scorer's non-zero set. Over-admitting costs a little Python re-ranking time and
  is invisible; under-admitting is a **silent recall bug** that no test currently
  catches.
- **Prefilter strategy — resolved: widen it.** Keep `to_tsvector('simple', …)` as
  the document side (no CamelCase splitting in SQL), **add `skill_id`** to the
  covered columns, and obtain CamelCase reach with **prefix lexemes**: for each
  split part, OR a `part:*` term alongside the exact token, so `reset:*` reaches
  the indexed single lexeme `resetpasswordadhoc`.
  - *why not a SQL tokenizer:* expressing R-4's rule as an IMMUTABLE PL/pgSQL
    function is technically possible but **rejected**. There is **no
    `CREATE FUNCTION` anywhere in the repository** (every `IMMUTABLE` match in a
    source grep is inside `.venv`), so it would be the platform's first
    user-defined SQL function *and* a second implementation of the tokenizer that
    must stay in exact sync with Python's regex — precisely the drift hazard R-6
    exists to detect. Python stays the single tokenizer.
  - *why widening is safe:* over-admission is invisible because Python still
    decides, and the failure mode of getting it wrong is a **slower query (loud,
    measurable)** rather than a **missing row (silent)**.
  - **Stage 0 must verify the prefix-lexeme assumption.** This design rests on
    PostgreSQL prefix-search semantics that have **not** been exercised against
    `postgres-0`. Fallback if it does not hold: drop the tsvector prefilter for
    CamelCase-derived tokens entirely — correct, merely slower.
  - The `LIKE`/substring arm the draft floated is **not** used: prefix lexemes are
    GIN-served, so they do not introduce a sequential scan.
- **Migration — resolved: versioned index name, old index retained one release.**
  `CREATE INDEX IF NOT EXISTS` matches on *name*, so changing the expression under
  the existing name silently keeps the old index and leaves the new expression
  unindexed. The migration therefore creates **`idx_skills_search_v2`** on the new
  expression and **keeps `idx_skills_search`** for one release before dropping it.
  Properties this buys: idempotent on re-run; never a window without an index; and
  **rollback is a plain code revert** while the old index still exists, so the
  shared-PVC blast radius below is not exercised by a rollback.
  - `CREATE INDEX CONCURRENTLY` is **not** used. The draft listed it as a choice
    between two windows; neither is available, because `_DDL` executes as **one
    multi-statement string** on a connection opened `autocommit=False` and
    committed afterwards (`initialize()`), and CONCURRENTLY cannot run inside a
    transaction block. At 18 rows a plain `CREATE INDEX` is milliseconds. If the
    catalog ever grows enough to need CONCURRENTLY that is a separate migration
    path with its own autocommit connection, not an edit here.
  - Adding `skill_id` needs **no function and no column**:
    `to_tsvector('simple', skill_id || ' ' || title || ' ' || body)` uses only text
    concatenation and the two-argument `to_tsvector` with a constant `regconfig`,
    both IMMUTABLE, and `skill_id` is already the table's `TEXT PRIMARY KEY`.
    `tags` stay out of the expression for the reason the DDL already records
    (`array_to_string` / `array_out` are STABLE).
  - The **GIN index expression and the `_SEARCH_VECTOR` expression stay identical**,
    asserted by a test that compares them, so the index cannot silently stop being
    used.
- **Blast radius — recorded, not assumed.** The `skills` database shares
  `postgres-0`'s **1 Gi** PVC with `audit`, `incidents` and `sessions`, and that
  PVC is a StatefulSet `volumeClaimTemplates` entry — **immutable on a live
  StatefulSet**, so `kubectl apply` cannot grow it and GitOps cannot raise the
  figure without deleting the PVC or editing it by hand. At 18 rows the index is
  kilobytes, so this is not a blocker; it is the reason the migration must be
  planned rather than attempted. Index size is measured before and after and
  recorded in the delivery note.
- latency: measured **end to end** on the Postgres path against the tool-gateway's
  10.0 s `REQUEST_TIMEOUT_SECONDS`. The eval-set's p50 2.726 ms is pure-Python
  `rank()` offline and must not be cited as an end-to-end figure.

### R-6: An enforced cross-backend parity harness — *OQ-3 resolved: invariant preserved as written, no ADR; do this first*

- affected: `products/skills-hub/tests/test_skill_store.py` (new test class), plus
  a correction to `docs/specs/SPEC-014-skills-and-grounded-guidance/tasks.md`.
- **the invariant is not narrowed, so no ADR is raised.** OQ-3 resolved to
  *preserve* the cross-backend byte-identical ordering invariant as written (the
  highest existing ADR is `0014-domain-metrics-via-otel-push.md`, so ADR-0015 would
  have been next). The memo §11 narrowing recommendation was scoped to *semantic*
  retrieval — a vector path cannot be byte-identical — and nothing in this spec is
  semantic, so it does not apply. The harness therefore asserts byte-identical
  ordering **and** numeric score equality across both backends, over the whole
  query set, with no Postgres-only carve-out.
- **OQ-3 and OQ-5 turned out to be one decision.** Preserving the invariant is what
  forces R-5's widen-the-prefilter strategy and rules out a SQL-side tokenizer: a
  superset prefilter keeps Python the sole decider of ordering on both backends, so
  the invariant holds **by mechanism** rather than by assertion.
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

### R-7: Product-side de-duplication guardrail — *OQ-6 resolved: `rank()` de-duplication only, sync half deferred*

- affected: `services/scoring.py::rank()` only. **R-7 adds nothing to
  `services/sync.py`** (see the deferral below) — though R-2's statistics refresh
  does, so the file is not untouched by this spec as a whole.
- approach: in `rank()`, after scoring and before `hits.sort(...)`, collapse hits
  whose body hash matches one already kept, retaining the **lowest `skill_id`**
  (consistent with the existing ascending tie-break, so the survivor is
  deterministic and explainable). Then sort, then `[:limit]` — de-duplication must
  precede truncation, since the measured defect was wasted slots.
- hash choice: `md5(body)`, matching the `body_md5` the label fixture already pins,
  so the identity key is consistent with the measurement artifact. MD5 here is a
  **content-identity key, not a security digest** — record that explicitly so a
  future security review does not flag it as a weak hash in a security context.
  **This introduces hashing to `skills-hub`; none exists today** (see the
  correction below).
- **not `parse_sources`.** `core/config.py::parse_sources` validates
  `SKILLS_SOURCES` JSON (duplicate `source_id`, malformed ids, missing
  type-specific fields) and never sees file content, so it cannot detect content
  overlap. Memo §4.4 and the CHANGELOG both describe it as "still accepting two
  sources covering the same files", which is imprecise; this plan records the
  correction.
- **Correction to this plan's own earlier text.** The draft said "if OQ-6 chooses
  sync-time rejection: the body hash exists at sync". **It does not.** `md5` /
  `sha256` / `hashlib` appear nowhere in `products/skills-hub` outside `uv.lock`'s
  dependency hashes; the fixture's `body_md5` was computed by the *offline
  evaluation harness*, not by the product. Sync does hold the body **text**
  (`Skill.body`), so a hash is trivially computable there — but the claim as
  drafted asserted existing machinery that does not exist, and the same false claim
  was made in `spec.md`, `tasks.md`, the eval-set and the spike memo. All five are
  corrected.
- **Sync-time overlap rejection is deferred, with a named trigger.** It is
  feasible — `_resolve_compositions` (SPEC-057 R-2) is the exact precedent, running
  between `ingest_directory` and `replace_source` where the store is reachable, and
  its rejections ride the existing per-source status and `skills_synced` event with
  no new event type. It is nonetheless the wrong layer here, for three structural
  reasons:
  - **nondeterministic precedence** — sources sync on independent asyncio loops
    with ±5% jitter (`sync.py::_loop`), so when two sources carry the same document
    whichever syncs *second* sees the other's copy, and the served version depends
    on timing, restarts and jitter rather than on configuration;
  - **an eventual-consistency hole** the composition code already documents — on a
    fresh cluster the first cycle cannot detect overlap at all;
  - **no store surface for it** — nothing returns all bodies or hashes, and
    `store.get()` needs the id, so detection would page through `list()`, a full
    catalog read per source per cycle.

  R-7's `rank()` de-duplication already removes the operator-visible symptom
  deterministically, at every request, regardless of sync order. **Trigger to
  revisit:** when duplicate *ingestion* cost (storage, sync time) rather than
  duplicate *ranking* becomes the problem, or when an operator needs to be **told**
  about a misconfiguration rather than silently protected from it. If it is ever
  built, precedence must come from configured `SKILLS_SOURCES` order — which is
  stable — and not from arrival order; a new bounded label must join
  `_rejection_category()`'s cardinality guard (`MAX_REPORTED_REJECTIONS = 50`); and
  the rejection text must stay safe for the **auth-exempt**
  `/api/v1/skills/status` surface that exposes `Rejection.reason` verbatim.
- audit consequence: `skill_searched` details `result_count` and `skill_ids` change
  when duplicates collapse. Existing event type, existing fields, new values; no
  vocabulary change.

### R-8: Re-measurement on the shipped path — *the merge gate; OQ-4 resolved: accept Q63 conditionally*

- affected: the eval-set artifact (a new section, appended — it is a measurement
  record and its published numbers are not rewritten), plus a **newly committed**
  harness.
- **Correction to this plan's own earlier text: the harness is reconstructed, not
  reused.** The draft said "reuse the offline harness that produced §8". `git
  ls-files` shows only the label fixture and the two prose artifacts — **no harness
  is committed**. R-8 is the merge gate, so its instrument must exist in the
  repository: it is rebuilt, committed, and driven through
  `PostgresSkillStore.search()` rather than `rank()` directly, so the prefilter is
  inside the measured path. Assert the fixture's `body_md5` per document **first**
  and fail loudly on mismatch.
- **the rebuilt harness has its own fidelity gate.** Before any candidate number
  from it is believed, it must reproduce the **shipped** scorer's published
  baseline (**19/38** combined top-1), the same way §8's harness gated every
  candidate on 38/38 identity with its flags off. A rebuilt instrument that cannot
  reproduce the known baseline measures nothing.
- because the harness is rebuilt, the **CamelCase variant that produced 0.711 is
  re-derived, not assumed** (R-4's caveat). If the rebuilt harness with whole-token
  retention does not reproduce the offline candidate numbers, the discrepancy is
  published and the shipped configuration is the one that was actually measured —
  not the one the memo described.
- report per backend, and report the full required metric set: zero-relevant rate
  (**not** zero-hit rate alone), distinct-document variants, P@5, R@5/@10, MRR,
  MRR(2), nDCG@10, rank stability, and latency p50/p95 measured end to end.
- statistics: reuse the pre-registered method unchanged — paired bootstrap, 10,000
  resamples, seed 20261001, 95% CIs on per-query deltas, plus an exact two-sided
  sign test on discordant top-1 pairs. Do **not** rely on Precision@5 (its baseline
  CI lower bound rounds to zero; the eval-set already flags it borderline).
- **disclose the Q63 regression, under the two conditions OQ-4 attached to its
  acceptance.** Q63 (`web check sign in inventory portal does not transition
  successful login troubleshooting`) moves top-1 from `D18` (grade 2) to `D13`
  (grade 1), with `D18` falling to rank 2 of 5 so `R@5(=2)` is unaffected and the
  sign test still gives p = 0.0117. The operator accepted it. The conditions:
  1. it must be reported on the **Postgres** path too, because a prefilter change
     could convert a re-ordering into a *disappearance* — a different severity, and
     one the offline measurement cannot see. **If `D18` leaves the returned window
     entirely on the shipped path, the acceptance does not cover it and the merge
     gate fails.**
  2. it is named in the delivery release note as a known behaviour change rather
     than left for an operator to discover.
- also disclose: abstention unchanged at 4/38, so the result cannot be over-read as
  fixing the zero-relevant problem.
- **null-result path.** If the Postgres-path gain is not outside the noise band,
  publish that, do not merge R-1..R-5, and record the outcome on the backlog row.
  This is a real possible ending and `tasks.md` carries it as a task rather than
  treating it as a failure.

### R-9: Contract and living-doc updates — *no OQ dependency; OQ-1(a) and OQ-3 shape it*

- affected: `products/skills-hub/README.md` (the endpoint summary restates the
  weighting), `docs/guides/skills-guide.md` (**three** specific places, listed
  below), `services/scoring.py`'s module docstring (states the fixed weighting and
  the byte-identical rationale as load-bearing documentation), SPEC-014's R-3
  annotation, the memo + eval-set status headers (pointer only — they are
  measurement artifacts and their text is not rewritten), `CHANGELOG.md`,
  `VERSION` + lockstep, `docs/specs/README.md`, the delivery-roadmap row, and
  SPEC-066's own delivery release note.
- **`score` may change meaning without a contract version bump** — OQ-1(a)'s
  resolution, and the reason this section is smaller than it looks. `score` appears
  in no `shared/shared-contracts` schema, is not portal-rendered, and is **dropped**
  by the tool-gateway connector's `_MATCH_KEYS`, so only ordering and excerpts are
  agent-visible. No JSON schema work. Record the published-vs-validated distinction
  in the README so the next change does not have to re-derive it.
- **but the weighting is published prose in four places**, all of which R-9 must
  reach: `products/skills-hub/README.md:38` (the `GET /api/v1/skills/search`
  endpoint summary), the `scoring.py` module docstring,
  `docs/guides/skills-guide.md:502`, and the **delivered** release note
  `2026-08-15-skills-and-grounded-guidance.md:81`.
- **the delivered release note is not edited.** It states "Deterministic scorer:
  title ×3, tags ×2, body ×1, saturating", which this spec makes inaccurate — but
  it is delivered release history. The change is recorded in SPEC-066's own
  delivery release note and the old note is left as the record of what shipped on
  2026-08-15.
- **the three skills-guide places**, because "checked for restated weighting" would
  have missed two of them:
  - its **"Never register the same files twice"** warning justifies itself with
    *"because ranking does no content de-duplication the copies consume result
    slots"* — a clause R-7 makes **false**. The warning stays (duplicates still cost
    ingestion, storage and sync time) but its rationale is rewritten and the
    measured 32-of-63 figure is reframed as history.
  - its authoring advice to *"name so alert → runbook lookups rank well"* becomes
    materially stronger: with R-1 the slug is a scored field and with R-4 its
    CamelCase parts are matchable, so authors should be told the `skill_id` is now
    a retrieval surface and how to name for it. This is an improvement the fixes
    make possible, not just a correction.
  - its search prose ("multi-word queries match OR-wise; the shared scorer ranks
    them") is checked against the shipped behaviour and updated if the OR semantics
    or the prefilter widening change what an operator would expect.
- **the `scoring.py` docstring keeps asserting the byte-identical invariant** —
  OQ-3 preserved it — and adds that R-6 now enforces it rather than leaving it
  documented-but-untested.

## Sequencing And Dependencies

1. **Stage 0 verification** — two facts, neither a decision: (a) exercise
   PostgreSQL prefix-lexeme behaviour against `postgres-0` before R-5 relies on it
   (fallback: drop the tsvector prefilter for CamelCase-derived tokens); (b)
   re-derive which CamelCase-splitting variant produced 0.711, since the harness
   that measured it is not committed. Depends on nothing. (a) blocks R-5; (b)
   blocks R-4's final rule and is closed out by R-8 either way.
2. **R-6 parity harness** — depends on nothing. Land before any scoring change;
   establishes the baseline and the enforcement mechanism everything else is
   measured against.
3. **R-3** (length norm) then **R-1** (`skill_id`) then **R-4** (CamelCase) then
   **R-2** (IDF) — each behind its flag, each fidelity-gated. Ordered cheapest and
   least-coupled first: R-3 is one line and backend-neutral; R-1 is one field; R-4
   changes the tokenizer that R-2's `df` depends on, so R-4 precedes R-2; R-2 is
   the signature change plus the sync-time statistics table and comes last.
   **Implementation order is not measurement order** — R-4's retention makes
   sub-tokens score-bearing and only R-2's IDF keeps them honest, so R-4's fidelity
   gate runs with R-2's flag on.
4. **R-5** prefilter + migration — depends on R-4's tokenizer rule being final and
   on Stage 0(a). The prefilter deliberately over-admits rather than mirroring the
   tokenizer (OQ-3/OQ-5), so it does not have to track R-4's rule exactly — but it
   does have to know which tokens are CamelCase-derived.
5. **R-7** de-duplication in `rank()` — independent of 3 and 4; can land in
   parallel. **R-7 has no sync-time half** (OQ-6 deferred).
6. **R-8** re-measurement — depends on 3, 4 and 5 all being in place, and on its
   own rebuilt harness passing its fidelity gate first. **This is the merge gate**,
   not a post-merge report.
7. **R-9** docs + flag removal + version — after 6 passes. Includes dropping
   `idx_skills_search` in the **following** release, which is a deliberate
   one-release tail on this slice rather than an unfinished task.

**Steps 3, 4 and 5 above are not separately shippable** — they are one merge, gated
by step 6. No single fix reaches significance alone, so a partial merge ships an
unmeasured subset. (*Steps*, not `tasks.md`'s *Stages*: the numbering differs, and
`tasks.md` Stage 2 is this step 3.)

## Test Strategy

- **unit** (`tests/test_scoring.py`): the CamelCase case table **including
  whole-token retention**; the IDF formula against hand-computed `N`/`df`; the
  length-norm factor's bounds including empty and single-character bodies; the
  cap-then-normalize order; `skill_id` credited at `TAG_WEIGHT`; **all four flags
  off reproduces the shipped scorer exactly** (the fidelity gate). The 8 existing
  exact-score assertions are updated with old and new values both visible in
  review.
- **statistics** (R-2): the `df` computation and the scoring path call the **same**
  `tokenize()` — asserted, not assumed, since a mismatch is a silent correctness
  bug; a sync cycle refreshes `N`/`df` after `replace_source`; a stale table is
  still *usable* (bounded staleness, not an error); both backends produce
  numerically equal statistics for the same catalog.
- **parity** (`tests/test_skill_store.py`, R-6): both backends, same corpus, same
  committed query set (R-6 above), identical `skill_id` ordering — plus identical
  **scores**, since backend-independent IDF (R-6/R-2) is a numeric claim, not only
  an ordering one. No Postgres-only carve-out: OQ-3 preserved the invariant as
  written.
- **prefilter** (R-5): the `_SEARCH_VECTOR` and GIN index expressions are compared
  for equality so the index cannot silently stop being used; a slug-only query
  returns rows on Postgres; **prefix lexemes actually reach an unsplit indexed
  lexeme** (this is Stage 0(a) promoted into the suite, so the assumption is
  continuously verified rather than verified once); **no query in the 63-query pool
  returns fewer rows than it does today**.
- **de-duplication** (R-7): a corpus with two byte-identical bodies under different
  `source_id`s returns one hit and the freed slot is filled by the next distinct
  document; collapse happens before `[:limit]`; the survivor is the lowest
  `skill_id`, asserted explicitly so the rule cannot drift into iteration order.
- **migration** (R-5): `idx_skills_search_v2` is created on an existing database
  (not silently skipped by `CREATE INDEX IF NOT EXISTS`); `idx_skills_search`
  **still exists** after the migration, so there is never a window without an
  index; the migration is idempotent on re-run; and the rollback path — a plain
  code revert with the old index still present — runs.
- **evaluation** (R-8): the rebuilt harness reproduces the shipped scorer's
  **19/38** combined top-1 baseline before any candidate number is believed; the
  fixture's `body_md5` is asserted before any metric is computed; results are
  reported per backend; **Q63's `D18` is asserted present in the Postgres-path
  window**, since its disappearance would fail the merge gate; the null-result path
  is a coded outcome, not an unwritten one.
- **regression sweep**: `products/tool-gateway/tests/test_skills_connector.py`
  (asserts the request path, not scores — and `_MATCH_KEYS` drops `score` entirely,
  so it should pass unchanged; verify, do not assume), and
  `shared/platform-ops/e2e/skills-demo.sh`, which searches `q=KubePodNotReady` and
  is directly affected by R-4.
- **full root `make verify`** green at delivery, per ADR-0008: every `R-x`
  criterion maps to at least one asserting test.

## Rollout And Migration

- **deployment change: two schema objects, one release apart.** R-5's
  `idx_skills_search_v2` index, and R-2's persisted statistics (a table on
  Postgres, the equivalent structure in memory). No new environment variable is
  proposed for the delivered state — the four flags are measurement instruments
  and are removed at R-9. **`idx_skills_search` is dropped in the *following*
  release**, which is a deliberate one-release tail, not an unfinished task; until
  then both indexes exist and both are maintained on write.
- **staleness becomes a deployment property.** Because R-2's statistics refresh on
  the sync cycle, `df` lags a catalog change by up to
  `SKILLS_SYNC_INTERVAL_SECONDS` (default **300**). This is recorded in the
  operator-facing docs rather than left as an implementation detail: a newly
  ingested document is searchable immediately but its arrival does not rebalance
  token weights until the next sync.
- **backward compatibility:** the HTTP response shape is unchanged; `score` values
  change and are not schema-validated, not portal-rendered, and dropped by the
  tool-gateway connector's `_MATCH_KEYS`, so no consumer reads them (OQ-1a — no
  contract version bump). **Ordering changes** — that is the intended effect, is
  measured, and carries one known mild regression (Q63, accepted at OQ-4 on the
  two conditions R-8 enforces). `skill_searched` audit detail values change when
  R-7 collapses duplicates.
- **rollback:** revert the scorer to the four flags off (the fidelity gate
  guarantees this reproduces today's behaviour exactly). The index needs **no
  rollback step at all** while `idx_skills_search` still exists — a code revert
  simply goes back to using it, which is the property the versioned name was
  chosen for. The rollback must still be **tested**, because the `skills` database
  shares `postgres-0`'s 1 Gi PVC with `audit`, `incidents` and `sessions`, and
  that PVC is a StatefulSet `volumeClaimTemplates` entry that cannot be grown by
  `kubectl apply`.
- **no feature gate at delivery.** Unlike SPEC-064's `AGENTSCOPE_COMPRESS_CONTEXT_ENABLED`,
  this is not an opt-in behaviour: a partially-improved retrieval path is worse
  than either extreme, and the fixes are measured sufficient. OQ-1's resolution
  confirmed no gate is needed rather than deferring the question.

## Risks

| Risk | Why it is real | Mitigation |
|---|---|---|
| Silent Postgres under-admission | The prefilter's failure mode is a *missing row*, which no current test detects | R-5's "no query returns fewer rows than today" criterion + R-6 harness over the 63-query pool |
| Prefix-lexeme assumption is wrong | R-5's CamelCase reach depends on PostgreSQL prefix-search semantics **not yet exercised against `postgres-0`** | Stage 0(a) verifies it before R-5 is implemented, promoted into the test suite so it stays verified; named fallback is dropping the tsvector prefilter for CamelCase-derived tokens |
| Two tokenizers drifting (Python vs SQL) | R-4's rule would exist in two languages | **Eliminated by OQ-5** — no user-defined SQL function is introduced; Python stays the single tokenizer and the prefilter over-admits instead |
| IDF computed over the wrong pool | `rank()`'s two callers pass different pools; the obvious implementation is the wrong one | **Eliminated by OQ-2** — statistics are global and sync-derived, never pool-derived; R-2's criterion asserts numeric equality across backends |
| Statistics tokenizer diverges from the scoring tokenizer | `df` is computed at sync, scoring at request; a mismatch is silent | Both call the same `tokenize()`, asserted by a test rather than by convention |
| Migration silently skipped | `CREATE INDEX IF NOT EXISTS` matches on *name*, so a changed expression under the old name keeps the old index | Versioned `idx_skills_search_v2`; a test asserts the new index exists on an already-initialized database |
| No window without an index | The catalog is live and shared with three other databases | The old index is retained for one release, so create-then-drop-later never leaves search unindexed |
| Measured gain does not reproduce on the shipped path | 0.711 is a memory-path upper bound | R-8 is the merge gate, with a coded null-result path |
| Whole-token retention silently doubles every score | `score()` aggregates `body` via `Counter` and `query` via a loop over a **list** — neither is idempotent, so a tokenizer emitting whole + parts inflates both. Measured on the shipped scorer: title 3.0 → 6.0, tag 2.0 → 4.0, three body occurrences 3.0 → 10.0, and `BODY_OCCURRENCE_CAP` reached at half the real count | R-4's position-aware aggregation, plus the hard criterion that CamelCase-free text scores **identically**; with the correct shape 7 of the 8 existing exact-score assertions are unchanged, so a second changed value is the alarm |
| Retention makes stopword-like sub-tokens score-bearing | `KubePodNotReady` now contributes `not` and `ready` as query tokens; R-2 forbids a stoplist by design | IDF is the mechanism that keeps them honest, so **R-4's fidelity gate runs with R-2's flag on** — implementation order is not measurement order |
| Scores become incomparable across query shapes | Measured: an exact identifier match scores **15.0** where the equivalent three-word phrase scores **9.0**, because one surface form yields five credit-bearing tokens | Recorded rather than hidden: `score` is not agent-visible (`_MATCH_KEYS` drops it) so nothing consumes the magnitude, but R-9's published prose must not imply scores are comparable across queries, and the separate abstention backlog row must not treat the value as a threshold without re-deriving it |
| The rebuilt harness measures the wrong thing | The original harness is **not committed**, so R-8's instrument is new | Its own fidelity gate: it must reproduce the shipped scorer's 19/38 baseline before any candidate number is believed |
| Q63's `D18` disappears rather than re-orders | A prefilter change can turn a re-ordering into a missing row, which the offline acceptance did not cover | R-8 asserts `D18` is present in the Postgres-path window; its absence fails the merge gate |
| Test suite "fixed" by weakening assertions | 8 exact-score assertions pin the current behaviour | R-4's criterion forbids loosening to vague comparisons; review sees old and new values. **Only 1 of the 8 should change value** — with the position-aware shape the other 7 are unchanged, so a diff touching several expected numbers is the tell |
| Shared-PVC blast radius | `skills` shares `postgres-0`'s 1 Gi PVC with `audit`, `incidents`, `sessions`, and the PVC cannot be grown by GitOps | Tested rollback; index size measured before and after and recorded in the delivery note |
