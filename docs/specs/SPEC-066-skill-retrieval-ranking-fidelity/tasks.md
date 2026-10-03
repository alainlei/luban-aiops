# SPEC-066 Tasks: Skill Retrieval Ranking Fidelity — The Four Measured Lexical Fixes, Cross-Backend Parity, And A De-Duplication Guardrail

Task states: `[ ]` pending, `[x]` done. Keep tasks small and tied to requirement IDs.

> **Provisional banner lifted 2026-10-02.** SPEC-066 is `approved`: all six Open
> Questions are resolved in `spec.md` and the resolutions are recorded against
> their original tasks in Stage 0 below, so the reasoning that produced this list
> stays visible rather than being deleted. Three stages changed as a result —
> Stage 2 (R-2 now carries a sync-time statistics table and a `rank()` signature
> change), Stage 3 (prefix lexemes and a versioned index name; no SQL tokenizer),
> and Stage 4 (the sync-time half is deferred, so R-7 contributes no
> `services/sync.py` task — R-2's statistics refresh still does).
> **Approval authorizes implementation as a separate step; it does not authorize
> commit/push, the R-5 index migration, deployment, or a version bump** — each is
> its own authorization boundary. ~~Stage 0 is read-only and is the first thing to
> execute.~~ **Stage 0 was executed read-only on 2026-10-02 and both of its tasks
> are closed** — prefix lexemes hold on live `postgres-0`, and 0.711 was measured
> under a parts-only tokenizer that R-4's retention shape reproduces exactly. *(2026-10-03,
> #2: that "reproduces exactly / 0.711 carries over" conclusion held for the
> **document-side** split; the shipped **query-only** split re-measures at 24/38, not
> 0.711 — see the R-4/R-8 amendments. The parts-only re-derivation itself stands.)* The
> same pass falsified the plain-concatenation GIN expression, so Stage 3's first
> task carries a corrected one. **Stage 1 (R-6) is now the first thing to
> implement.**

> **Amended 2026-10-03 (#2) — implementation state and the R-4 re-scope.** Stages
> 1–5 are **implemented and green**: the full `products/skills-hub` suite passes
> **300 tests on real PostgreSQL 16** (`uv run pytest`), with `test_parity_candidate`
> green and `idx_skills_search_v2` in service. R-4 was **re-scoped to a query-side-only
> CamelCase split** (a new `tokenize_query()`) after the document-side split made
> R-5's prefilter under-admit on **5 of 81** parity queries; the boxes below are
> ticked against that shipped design, and R-4 task wording carries dated `#2` notes
> where it described document-side splitting. R-8 re-measured the candidate at
> **24/38** combined top-1 (see `spec.md`'s R-4/R-8 amendments and Changelog).
> **Stage 6 (R-9), the four-flag removal, and the delivery boundary (commit/push,
> live index migration, deployment, VERSION bump, status → delivered) remain HELD as
> separate authorizations** — those boxes stay unticked. A ticked box here means the
> code/test/migration-DDL/spec-doc **exists and passes**, *not* that a live-cluster
> migration ran or that the spec is delivered.

## Stage 0: verification (read-only; blocks Stages 2–3) — **COMPLETE 2026-10-02**

The six Open Questions are **resolved** — recorded here as done, with the answer
each settled on, so the task list stays the audit trail. ~~What remains open are two
*verification* tasks: checkable facts about a running cluster and an uncommitted
harness rather than decisions, which is why they were not left as Open Questions.~~
**Those two verification tasks were also checkable facts about a running cluster and
an uncommitted harness rather than decisions — which is why they were not left as
Open Questions — and both are now closed below, with their answers recorded against
the original wording.**

- [x] **OQ-1(a)** — `score`'s changed semantics need **no contract version bump**:
      it is in no `shared-contracts` schema, is not portal-rendered, and is dropped
      by the tool-gateway connector's `_MATCH_KEYS`. Its *weighting* is published
      prose in four places, so R-9 reaches all four (Stage 6)
- [x] **OQ-1(b)** — `skill_id` enters at **`TAG_WEIGHT` (2.0)**, the value the
      measurement used. Any other weight is a fifth, unmeasured candidate under
      R-8, not a review decision
- [x] **OQ-2** — IDF statistics are **computed in Python and persisted at sync
      time**, passed into `rank()` by the caller. The draft's "per-request over the
      whole catalog" recommendation was **overturned**: it reads the corpus the
      prefilter exists to avoid reading, and after R-4 a SQL-computed `df` cannot
      match Python's `tokenize()` at all. Pool-derived statistics remain rejected.
      R-4's whole-token rule is resolved in the same decision: **retain the whole
      token alongside its parts**
- [x] **OQ-3** — the byte-identical cross-backend ordering invariant is **preserved
      as written**. The memo §11 narrowing was scoped to *semantic* retrieval and
      nothing here is semantic, so it does not apply. **No ADR-0015**, and
      `docs/adr/README.md` is untouched. OQ-3 and OQ-5 are one decision: preserving
      the invariant forces the widen-the-prefilter strategy and rules out a SQL
      tokenizer
- [x] **OQ-4** — the Q63 re-ordering regression is **accepted by operator
      decision**, on two conditions enforced in Stage 5: reported on the
      **Postgres** path (a re-ordering can become a *disappearance* there, which
      fails the merge gate) and named in the delivery release note
- [x] **OQ-5** — prefilter strategy: **widen it** with prefix lexemes, no SQL
      function. Migration: create **`idx_skills_search_v2`**, retain
      `idx_skills_search` for one release, so rollback is a plain code revert and
      there is never a window without an index. **No `CREATE INDEX CONCURRENTLY`** —
      unusable, because `_DDL` runs as one multi-statement string on a connection
      opened `autocommit=False`
- [x] **OQ-6** — sync-time overlap rejection is **deferred with a named trigger**;
      only R-7's `rank()` de-duplication ships. Feasible (`_resolve_compositions`
      is the precedent) but the wrong layer: nondeterministic precedence across
      jittered sync loops, the eventual-consistency hole the composition code
      documents, and no store surface returning all bodies
- [x] **Label-set ownership** confirmed: R-8 re-uses the author-proposed,
      operator-ratified fixture as-is, and operations ownership remains a
      precondition only if the row is ever reopened for embedding work
- [x] Resolutions recorded in `spec.md`, `plan.md` / `tasks.md` provisional banners
      lifted, status set `draft` → `approved`
- [x] **Verify (a): PostgreSQL prefix-lexeme behaviour on the live cluster.** R-5's
      CamelCase reach assumes `to_tsquery('simple', 'reset:*')` matches an indexed
      document lexeme `resetpasswordadhoc`. ~~**This has not been exercised against
      `postgres-0`.**~~ Read-only check against the deployed instance; record the
      actual behaviour. **Fallback if it does not hold:** drop the tsvector prefilter
      for CamelCase-derived tokens entirely — correct, merely slower. Blocks Stage 3
      → **Done 2026-10-02, and it holds.** Live `postgres-0`, PostgreSQL **16.14**,
      database `skills`, **18 rows / 2 sources**; read-only throughout
      (`SELECT`/`SHOW`/`EXPLAIN` plus one session-local `SET enable_seqscan = off`).
      `to_tsvector('simple','KubePodNotReady')` → `'kubepodnotready':1`; `kubepod:*`
      matches (**t**), mid-token `pod:*` and bare `pod` do not (**f**) — prefix is
      anchored at lexeme start only. The reach is real, not theoretical: `kubepod`
      returns **0 rows** today, `kubepod:*` returns **3**. The GIN expression index
      *can* serve a prefix tsquery (**Bitmap Index Scan on `idx_skills_search`**
      under `enable_seqscan = off`; `pg_opclass` confirms `gin | tsvector_ops`), but
      at 18 rows the planner always chooses **Seq Scan**, so `idx_skills_search_v2`
      buys reach rather than latency. Every query shape tested only **widens** the
      prefilter (2/18/18/18 rows; Q63 16 → 18), so R-4 causes no Postgres recall
      regression on this corpus. **The fallback is not needed and is not taken.**
      **The same check falsified a claim this spec was approved with:** R-5 and
      OQ-5 both said adding `skill_id` needs "only text concatenation", but the
      default parser types a slash-containing `skill_id` as **`file` ("File or path
      name", tokid 19)** and emits **one opaque lexeme**, so the approved expression
      matches **0 rows** for `resetpasswordadhoc` where
      `replace(replace(skill_id,'/',' '),'-',' ')` matches **1** (`replace` is
      IMMUTABLE, so the index stays an expression index; hyphens alone do split —
      the slash is the trigger). Both amended. **Stage 3 unblocked.**
- [x] **Verify (b): which CamelCase-splitting variant produced 0.711.** The offline
      harness that measured it is **not committed** (`git ls-files` shows only the
      label fixture and the two prose artifacts) and the eval-set records the change
      only as "tokenizer regex" (§8.2's candidate row 2c), so the repository cannot
      confirm whether the whole
      token was retained. Re-derive it; if it was dropped, Stage 5 re-measures the
      retention variant rather than assuming 0.711 carries over. Blocks Stage 2's
      R-4 final rule
      → **Done 2026-10-02: parts-only — the whole token was dropped — and 0.711
      nevertheless transfers to retention.** The harness survived in the gitignored
      scratch directory and re-ran **unmodified**: §5's pinned pool **63/63**
      byte-identical *including scores*, the shipped scorer **38/38**, and every
      published §8.2 number reproduced. Fidelity gate 0 passed first — a read-only
      `COPY … TO STDOUT` export matches the committed fixture's pins exactly
      (**18/18** `body_md5` and `body_bytes`, 18 distinct hashes, **75,680** bytes),
      and the harness's own stored corpus is md5-identical to that export. Its
      tokenizer is `" ".join(CAMEL.split(text))` then `findall`, i.e. the variant
      R-4 rejects. Under R-4's **position-aware retention** shape every aggregate
      metric is **identical** (27/38 top-1 grade 2, B MRR 0.950, C MRR 0.778,
      C MRR(2) 0.708, C nDCG@10 0.864, B nDCG@10 0.936, zero-relevant 1/20 + 3/18)
      and **no top-10 list reorders on any of the 38 queries**, while **8 of 684**
      (query, document) scores change — all on the **3** queries containing a
      CamelCase run (Q03, Q04, Q46), largest `KubePodNotReady` → `D12` at
      **+15.727**. Stage 5 **may** therefore carry 0.711 over. **New finding:** the
      eval set cannot detect a wrong R-4 shape — naive flat-list retention reorders
      **26 of 38** pools, changes **464 of 684** scores and doubles the score scale
      (mean 10.170 → **21.827**), yet B MRR, C MRR and the 27/38 count are
      **identical**, so R-4's hard criterion is enforced by `test_scoring.py` and
      never by §8's metrics. Scope limit recorded: none of the 38 queries is a whole
      *lowercase* identifier, the one case where retention changes a document's
      token set without the query being CamelCase. **Stage 2's R-4 rule is final.**

## Stage 1: R-6 — parity harness first

> Land before any scoring change, so the baseline is established and a pre-existing
> invariant violation is found by the harness rather than blamed on the new code.
> OQ-3 preserved the invariant **as written**, so there is no Postgres-only
> carve-out: ordering **and** scores must match.
>
> **Done (2026-10-03, #2).** This harness is what **caught** the parity blocker:
> under the document-side split `test_parity_candidate` diverged on 5 of 81 queries,
> which is the evidence that drove the R-4 re-scope. Under the shipped query-only
> split it is **green** — byte-identical ordering *and* scores on both backends.

- [x] Decide the Postgres side of the harness: drive a **real** Postgres (the
      SPEC-063 campaign precedent) or an equivalent. **A `_fake_connect` that returns
      canned rows cannot exercise the prefilter and a fake that returns every row
      makes the harness pass vacuously — do not accept either**
      (`products/skills-hub/tests/test_skill_store.py`)
- [x] Commit the query-set fixture: the union of the 63-query audit pool and the 18
      authored stratum-C paraphrases
- [x] Add the harness: build the **same** corpus into both `InMemorySkillStore` and
      `PostgresSkillStore`, assert identical `skill_id` **ordering** for every query
      in the fixture
- [x] Extend the harness to assert identical **scores**, not only ordering — this is
      what makes R-2's backend-independent IDF numeric rather than aspirational
- [x] Run the harness against the **current** code and record the outcome either way
      (a pass establishes the baseline; a fail is a pre-existing defect and gets its
      own finding, not a suppression)
- [x] Annotate `docs/specs/SPEC-014-skills-and-grounded-guidance/tasks.md` line 32:
      it claims a delivered "byte-identical ordering parity test vs in-memory store"
      that does not exist, and names `plainto_tsquery` where the shipped code
      OR-joins `to_tsquery` lexemes. SPEC-014 is `delivered`, so correct by **dated
      annotation**, not silent edit
- [x] Test: the harness runs in the ordinary suite (`make test` / `make verify`), not
      as a manual step

## Stage 2: R-3 → R-1 → R-4 → R-2 (each behind a flag, each fidelity-gated)

> Ordered cheapest and least-coupled first. R-4 precedes R-2 because R-4's tokenizer
> determines R-2's `df`. **None of these is separately shippable** — no single fix
> reaches significance alone.
>
> **Implementation order is not measurement order.** R-4's whole-token retention
> makes sub-tokens such as `not` and `ready` score-bearing, and R-2 forbids a
> stoplist, so IDF is the only thing that keeps them from carrying full weight.
> R-4's fidelity gate therefore runs **with R-2's flag on**; measuring R-4 alone
> measures an inflated scorer, not the shipped one.

- [x] Add the four module-level flags to `services/scoring.py` (naming fixed at
      implementation). Flags are a **measurement instrument**, removed at Stage 5
- [x] **R-3** — apply `1 / log2(2 + len(body)/1000)` to the **already-capped** body
      contribution; retain `BODY_OCCURRENCE_CAP = 5` (`services/scoring.py`)
- [x] Test R-3: the factor is in `(0, 1]` and strictly positive for every body
      including empty and single-character; equal capped occurrences ⇒ the longer
      body contributes strictly less; **backend-neutral without corpus state**
- [x] **R-1** — add `id_tokens = set(tokenize(skill.skill_id))` to `score()`,
      credited at **`TAG_WEIGHT` (2.0)** (OQ-1(b) resolved; `services/scoring.py`)
- [x] Test R-1: slug separators tokenize consistently with the title
      (`samples/password-reset-resetacmepassword` → `samples`, `password`, `reset`,
      `resetacmepassword`)
- [x] Test R-1 against the **committed label fixture**, not a hand-written
      expectation: the identifier's owner ranks first for all 3 stratum-A queries
      that name an identifier existing in the corpus (the measurement's 0/3 → 3/3)
- [x] Test R-1: the 11 stratum-A queries naming a nonexistent identifier are not made
      worse; record their behaviour (they still return 7–10 confident hits —
      abstention, out of scope)
- [x] **R-4** — ~~replace `TOKEN_PATTERN = re.compile(r"[a-z0-9]+")` with a two-step
      tokenize (CamelCase/digit boundary split, then the existing alphanumerics rule
      retained as the final step so non-CamelCase text is unaffected)~~ **(2026-10-03,
      #2: `TOKEN_PATTERN`/`tokenize()` stay the UNSPLIT document unit; the two-step
      CamelCase/digit-boundary split lives in a new `tokenize_query()`, applied to the
      QUERY ONLY — original-cased split, then the existing alphanumerics rule, so
      non-CamelCase text is unaffected)**
- [x] Commit the R-4 case table as tests: `KubePodNotReady`, `CrashLoopBackOff`,
      `HTTP503`, `pgBouncer`, `v0211`, `RealPlayer2`, plus already-lowercase and
      digit-only cases that must be unaffected *(2026-10-03, #2: the table now
      asserts `tokenize_query`, the query-side splitter — `CamelCaseTokenizeTests`)*
- [x] **Decide the letter↔digit boundary explicitly, in both directions.** The two
      standard CamelCase boundaries do **not** fire inside `HTTP503` (no lowercase
      before the capitals; `P5` is not upper-then-lower), so measured output is the
      **single token `http503`**, and `v0211` likewise stays whole — the draft's
      gloss ("`http` + `503`, or `h`/`t`/`t`/`p`/`503` if done naively") describes
      neither. A third boundary rule is needed to split an acronym run from a
      trailing number, and it is consequential both ways: without it `503 error`
      cannot reach a document titled `HTTP503`; with it `v0211` risks becoming `v` +
      `0211`. Pin the decision in the case table, because R-2's `df` and R-5's
      prefilter both inherit it
- [x] **Retain the whole token alongside its parts** (OQ-2's second half, resolved):
      ~~`tokenize("KubePodNotReady")` yields `kubepodnotready` **and** `kube`, `pod`,
      `not`, `ready`. Apply the rule **identically** in `tokenize()`, in R-2's `df`
      computation, and in R-5's prefilter — a mixed application is silently wrong.~~
      **(2026-10-03, #2 — INVERTED: retention is QUERY-SIDE only. `tokenize_query`
      yields `kube`/`pod`/`not`/`ready` **and** `kubepodnotready`; the document side
      (`tokenize()`, `df`, the index) stays UNSPLIT, byte-identical to
      `to_tsvector('simple')`. The application is *deliberately asymmetric* — symmetric
      document-side splitting is the failure mode that broke parity on 5 of 81.)**
      ~~Subject to Stage 0 verify (b)~~ **Stage 0 verify (b) settled this: the
      measured 0.711 came from the parts-only variant, and retention reproduces
      every aggregate metric with no re-ordering on any of the 38 queries — the
      retention rule stands as written.** *(2026-10-03, #2: that carry-over was the
      doc-side split; the query-only candidate re-measures at 24/38 — see R-8.)*
- [x] **R-4 is not a `tokenize()`-only change.** ~~Make `score()`'s aggregation
      position-aware: one token **set** per surface alphanumerics run, the whole
      token admitted only when it differs from its parts, body occurrences counted
      **per run** rather than per emitted token, and query tokens de-duplicated
      before the scoring loop.~~ **(2026-10-03, #2: the position-aware shape lives
      entirely in the QUERY path — `_run_tokens` admits the whole token only when it
      differs from its parts, `_query_tokens` de-duplicates before the scoring loop.
      The document side is unsplit, so `body`'s `Counter` keeps its shipped meaning
      and the inflation below cannot arise.)** Without this, retention doubles every ordinary query
      (measured: title 3.0 → 6.0, tag 2.0 → 4.0, three body occurrences 3.0 → 10.0)
      and reaches `BODY_OCCURRENCE_CAP` at half the real count
- [x] Split CamelCase on the **original-cased** text and lowercase afterwards —
      lowercasing first destroys the boundary and splits nothing
- [x] Test R-4's no-inflation criterion directly: for a corpus and query with **no**
      CamelCase anywhere, every score is **identical** to the pre-R-4 value.
      **This unit assertion is the only instrument that can catch a wrong shape** —
      Stage 0 measured that a naive flat-list retention reorders **26 of 38** top-10
      pools, changes **464 of 684** scores and doubles the score scale (mean 10.170
      → 21.827) while leaving B MRR (0.950), C MRR (0.778) and the combined top-1
      count (**27/38**) identical, so the §8 evaluation harness would have passed it
- [x] Update the exact-score assertions in `tests/test_scoring.py` deliberately.
      There are **8**; ~~with the position-aware shape **exactly 1** changes value
      (`score("KubePodNotReady", skill) == 7.0` → 27.0, encoding the defect R-4
      removes).~~ **(2026-10-03, #2: with the query-only split **none** of the 8
      changes — `score("KubePodNotReady", skill)` stays **7.0**, the document fields
      being unsplit. The 7.0 → 27.0 doc-side inflation *was* the parity-breaking case,
      so its disappearance is the point; the query-side gain is asserted by new tests.)**
      **Treat ~~more than one~~ any changed value as a wrong implementation, not a
      stale test.** Do not weaken any assertion to a vague comparison — old and new
      values both visible in review
- [x] Where R-3's norm makes a body contribution non-integral, compute the expected
      value **from the formula in the test** rather than hard-coding a rounded
      literal or relaxing the comparison
- [x] Change the **fixture `skill_id`s**, not the expected numbers, for
      `test_title_match_scores_three` and
      `test_body_occurrences_score_one_and_saturate`: both use `a/pod`, whose slug
      matches the query `pod` once R-1 scores it (+2.0), which would turn the
      three-occurrence assertion into **5.0 — the value the next line asserts for
      the saturating cap**, making the pair indistinguishable
- [x] Gate R-4's fidelity measurement on **R-2's flag being on**: retention makes
      `not` and `ready` score-bearing and R-2 forbids a stoplist, so IDF is the only
      thing keeping them from carrying full weight
- [x] **R-2** — introduce an explicit immutable corpus-statistics value (`N` + a `df`
      map) and implement `ln((1+N)/(1+df))+1`. **No hand-written stoplist anywhere
      in the path**
- [x] **R-2 / OQ-2** — compute the statistics **in Python at sync time** and persist
      them: a table on Postgres, the equivalent structure in memory. Refresh after
      each successful `replace_source` in `services/sync.py`. Because `df` is
      **global**, a per-source swap invalidates all of it, so the refresh is a
      **full catalog pass**
- [x] **R-2** — change `rank()`'s and `score()`'s signatures to take the statistics.
      **This is the load-bearing part of R-2, not an incidental refactor**: `rank()`
      is **synchronous and pure** while both stores are `async`, so statistics
      cannot be fetched inside it — the caller must pass them in
      (`services/scoring.py`, both `search()` implementations in
      `services/skill_store.py`)
- [x] Check for `score()`/`rank()` callers outside `skill_store.py` before changing
      the signature (tool-gateway: none; portal: none — verified at drafting,
      re-verify). Prefer an **explicit required** parameter over a default that
      hides a wrong-by-default corpus
- [x] Ensure R-2's `df` is computed with the **same** `tokenize()` the scorer uses —
      two tokenizers in one file is the failure mode, and a mismatch between the
      statistics tokenizer and the scoring tokenizer is **silent** *(2026-10-03, #2:
      `compute_stats` and `score`'s document fields both call the unsplit `tokenize()`,
      so they cannot drift; `tokenize_query()` is the deliberate second function,
      query-only, never used for `df`. `df` is flag-independent.)*
- [x] Test R-2: IDF against hand-computed `N`/`df`; field-weight **ordering**
      (title 3.0 > tags 2.0 > body 1.0) unchanged so SPEC-014 R-3's guarantee holds;
      `certificate expired on the ingress` stops ranking a password-reset runbook
      first, with the mechanism assertable ("the" contributes materially less)
- [x] Test R-2: the `df` path and the scoring path call the **same** `tokenize()`;
      a sync cycle refreshes `N`/`df` after `replace_source`; a **stale** table is
      still usable (bounded staleness is a property, not an error); both backends
      produce numerically equal statistics for the same catalog
- [x] Test R-2 explainability: the score stays **decomposable** into per-token,
      per-field contributions (`weight × idf(token) × norm(document)`). This is the
      surviving obligation from the memo's *"do not silently redefine `score`"* —
      written about cosine fusion, which this spec does not do, but whose *reason*
      (answering "why did this rank first?" in an incident review) binds here
- [x] **Fidelity gate** — test that with **all four flags off** the scorer reproduces
      the shipped behaviour exactly (the eval-set's 38/38 gate, reproduced in the
      product's own suite)

## Stage 3: R-5 — prefilter, index and migration

> Depends on R-4's tokenizer rule being final **and on Stage 0 verify (a)**.
> **Both satisfied 2026-10-02** — verify (a) confirmed prefix lexemes on live
> `postgres-0` and falsified the plain-concatenation index expression, which the
> first task below now carries corrected.
> **Highest-risk stage**: the prefilter's failure mode is a silently missing row.

- [x] Add `skill_id` to `_SEARCH_VECTOR` so a slug-only match is returned by the
      prefilter, **normalizing its separators first** — Stage 0 falsified the
      plain-concatenation form: the default parser types a slash-containing
      `skill_id` as **`file` ("File or path name", tokid 19)** and emits one opaque
      lexeme, so `to_tsvector('simple', skill_id || ' ' || title || ' ' || body)`
      matches **0 rows** on the live table for `resetpasswordadhoc`. Use
      `to_tsvector('simple', replace(replace(skill_id, '/', ' '), '-', ' ') || ' ' || title || ' ' || body)`,
      which matches **1**. **No new function and no new column** — `replace`
      (`provolatile = i`) plus the two-argument `to_tsvector` with a constant
      `regconfig` are all IMMUTABLE, so this stays a legal expression index, and
      `skill_id` is already the table's `TEXT PRIMARY KEY`. `tags` stay out for the
      reason the DDL already records (`array_to_string`/`array_out` are STABLE —
      re-confirmed by the same volatility check). Hyphens alone do split; the
      **slash** is the trigger
      (`services/skill_store.py`)
- [x] Implement the resolved prefilter strategy: **widen it with prefix lexemes** —
      for each CamelCase-derived split part, OR a `part:*` term alongside the exact
      token, so `reset:*` reaches the indexed single lexeme `resetpasswordadhoc`.
      **Do not introduce a SQL tokenizer**: there is no `CREATE FUNCTION` anywhere in
      the repository, so an IMMUTABLE PL/pgSQL splitter would be the platform's first
      user-defined SQL function *and* a second implementation of the tokenizer that
      must stay in exact sync with Python's regex — the drift hazard R-6 exists to
      detect
- [x] Do **not** add a `LIKE`/substring arm. Prefix lexemes are GIN-served, so they
      do not introduce a sequential scan; the draft's `LIKE` option is superseded.
      *(Stage 0 note: at 18 rows the planner chooses **Seq Scan** for every shape
      anyway — `Bitmap Index Scan on idx_skills_search` appears only under
      `enable_seqscan = off`. The distinction is about what the index **can** serve
      once the catalog grows, not about today's plan.)*
- [x] Keep the **OR-join** of query lexemes; do **not** introduce `plainto_tsquery`
      (it ANDs and would silently drop partial matches — already documented by
      `test_search_joins_multi_word_queries_with_or`)
- [x] Keep the prefilter an **over-approximation** of the scorer's non-zero set, per
      the shipped comment's contract. Over-admission is safe because Python still
      decides; the failure mode of getting it wrong must stay **loud** (slow query),
      never silent (missing row)
- [x] Add a test that the **GIN index expression and the `_SEARCH_VECTOR` expression
      are identical**, so the index cannot silently stop being used
- [x] Write the migration: create **`idx_skills_search_v2`** on the new expression and
      **retain `idx_skills_search`**. `CREATE INDEX IF NOT EXISTS` matches on *name*,
      so changing the expression under the existing name silently keeps the old index
      and leaves the new one unindexed
- [x] Do **not** use `CREATE INDEX CONCURRENTLY`. `_DDL` executes as one
      multi-statement string on a connection opened `autocommit=False` and committed
      afterwards (`initialize()`), so CONCURRENTLY would fail inside the transaction
      block. At 18 rows a plain `CREATE INDEX` is milliseconds
- [x] Test the migration on an **existing** database: `idx_skills_search_v2` is
      created (not silently skipped), `idx_skills_search` **still exists** afterwards
      so there is never a window without an index, and the migration is idempotent on
      re-run
- [x] Test the **rollback**: a plain code revert with the old index still present —
      no index step at all. The `skills` database shares `postgres-0`'s **1 Gi** PVC
      with `audit`, `incidents` and `sessions`, and that PVC is a StatefulSet
      `volumeClaimTemplates` entry that **cannot be grown by `kubectl apply`**, so a
      botched migration is neither contained to skills nor fixable from GitOps
- [x] Measure index size **before and after** and record it in the delivery note
      (kilobytes at 18 rows — the point is that it is measured, not assumed)
- [x] Test R-5: a query whose only match is in `skill_id` returns rows on **Postgres**
      as well as in memory
- [x] Test R-5: **prefix lexemes actually reach an unsplit indexed lexeme** — Stage 0
      verify (a) promoted into the suite, so the assumption stays verified rather
      than being checked once
- [x] Test R-5/R-4 recall guard: **no query in the fixture returns fewer rows than it
      does today** on the Postgres path
- [x] Measure search latency p95 **end to end** on the Postgres path against the
      tool-gateway's 10.0 s `REQUEST_TIMEOUT_SECONDS`. Do **not** cite the eval-set's
      offline p50 2.726 ms — it excludes the prefilter, HTTP, auth and the audit write
- [x] Schedule the **drop of `idx_skills_search`** for the *following* release. This
      is a deliberate one-release tail, not an unfinished task; record it where the
      next release will see it

## Stage 4: R-7 — de-duplication guardrail (parallel with Stages 2–3)

> **OQ-6 resolved: R-7 contributes no `services/sync.py` task.** Only `rank()`
> de-duplication ships, so there is deliberately **no sync-time task below**.
> (`services/sync.py` *is* touched by Stage 2's R-2 statistics refresh — that is
> a different change and it is not deferred.)
>
> The draft carried one, reading "implement it where body hashes exist
> (`services/sync.py`)". That rested on a **false claim** — no body hashes exist
> anywhere in `skills-hub` (`md5`/`sha256`/`hashlib` appear nowhere outside
> `uv.lock`'s dependency hashes). Sync holds the body *text*, so a hash is
> trivially computable there; the machinery the draft assumed simply does not
> exist. The work is deferred on three structural grounds: nondeterministic
> precedence across independently-jittered sync loops, the eventual-consistency
> hole `_resolve_compositions` already documents, and no store surface returning
> all bodies. **Trigger to revisit:** when duplicate *ingestion* cost rather than
> duplicate *ranking* becomes the problem, or when an operator needs to be **told**
> rather than silently protected. If it is ever built, precedence must come from
> configured `SKILLS_SOURCES` order, a new bounded label must join
> `_rejection_category()`'s cardinality guard, and the rejection text must stay
> safe for the **auth-exempt** `/api/v1/skills/status` surface that exposes
> `Rejection.reason` verbatim.

- [x] Implement content-hash collapse in `rank()` **before** `hits.sort(...)` and
      before `[:limit]`, retaining the **lowest `skill_id`** (consistent with the
      existing ascending tie-break, so the survivor is deterministic)
      (`services/scoring.py`)
- [x] Use `md5(body)` as the identity key, matching the `body_md5` the label fixture
      pins. Record in a comment that MD5 here is a **content-identity key, not a
      security digest**, so a future security review does not flag it as a weak hash
      in a security context. **This introduces hashing to `skills-hub` — none exists
      today** (`md5`/`sha256`/`hashlib` appear nowhere in `products/skills-hub`
      outside `uv.lock`'s dependency hashes)
- [x] **Do not** put overlap detection in `core/config.py::parse_sources` — it
      validates `SKILLS_SOURCES` JSON and never sees file content, so it structurally
      cannot detect content overlap
- [x] Test R-7: a corpus with two byte-identical bodies under different `source_id`s
      returns **one** hit and the freed slot is filled by the next-ranked distinct
      document
- [x] Test R-7: collapse precedes truncation (the measured defect was wasted slots,
      not duplicate output)
- [x] Record that `skill_searched` details `result_count` and `skill_ids` change
      observably when duplicates collapse — existing event type, existing fields, new
      values, **no vocabulary change**
- [x] Document R-7 as **regression protection, not a retrieval improvement**: the dev
      corpus is already clean (0 of 63 pools contain a duplicate), so there is no
      crowding left to measure a gain against and **no label evidence is claimed**

## Stage 5: R-8 — re-measurement on the shipped path (the merge gate)

> **This gates the merge; it is not a post-merge report.**

- [x] **Reconstruct and commit the evaluation harness.** The draft said "extend the
      offline evaluation harness" — but **no harness is committed** (`git ls-files`
      shows only the label fixture and the two prose artifacts). R-8 is the merge
      gate, so its instrument must exist in the repository. Rebuild it and drive it
      through `PostgresSkillStore.search()` rather than `rank()` directly, so the
      prefilter is inside the measured path
- [x] **Harness fidelity gate** — before any candidate number from the rebuilt
      harness is believed, it must reproduce the **shipped** scorer's published
      baseline (**19/38** combined top-1), the same way §8's harness gated every
      candidate on 38/38 identity with its flags off. A rebuilt instrument that
      cannot reproduce the known baseline measures nothing
- [x] ~~Re-derive the **CamelCase variant** that produced 0.711 (Stage 0 verify (b)).~~
      **Answered by Stage 0: the measured variant was parts-only — the whole token
      was dropped — and R-4's position-aware retention shape reproduces every
      published aggregate metric with no re-ordering on any of the 38 queries, so
      0.711 may be carried over rather than re-derived from zero.** What survives
      here is the obligation that answer creates: the rebuilt harness must itself
      reproduce it. If the rebuilt harness with whole-token retention does not
      reproduce the offline candidate numbers, **publish the discrepancy** and ship
      the configuration that was actually measured — not the one the memo described
      *(2026-10-03, #2: this box's fallback clause is exactly what fired. The "0.711
      carries over" conclusion held only for the **document-side** split; the shipped
      **query-only** split re-measures at **24/38** combined top-1, not 0.711. The
      rebuilt harness published that discrepancy
      (`test_v3_query_only_diverges_from_offline_row_2c`,
      `test_r4_query_only_scope_is_the_gap`) and the configuration actually measured
      is the one that shipped.)*
- [x] Assert the fixture's `body_md5` per document **first**, failing loudly on
      mismatch rather than silently invalidating the comparison
      (`semantic-skill-retrieval-labels.json`, 38 × 18 = 684 judgments, 173 non-zero)
      — **re-use without re-grading**
- [x] Report the full required metric set: **zero-relevant rate** (not zero-hit rate
      alone), distinct-document variants, P@5, R@5/@10, MRR, MRR(2), nDCG@10, rank
      stability, latency p50/p95 end to end
- [x] Report **per backend**; a gain that appears in memory and not on Postgres is
      published as such
- [x] Reuse the pre-registered statistics unchanged: paired bootstrap (10,000
      resamples, seed 20261001) with 95% CIs on per-query deltas, plus an exact
      two-sided sign test on discordant top-1 pairs. **Do not rely on Precision@5**
      (its baseline CI lower bound rounds to zero)
      *(2026-10-03, #2: reused unchanged. The nDCG@10 bootstrap CI stays outside zero
      — **[+0.022, +0.111]** — so the primary pre-registered verdict survives; the
      coarser top-1 sign test is **directional but not significant** at **(7, 2),
      p = 0.1797**, down from the document-side split's (9, 1). Both are asserted
      (`test_v6_ndcg_gain_outside_noise_band`,
      `test_v6_top1_sign_test_directional_not_significant`) and disclosed, not
      smoothed.)*
- [x] **Assert Q63's `D18` is present in the Postgres-path returned window** (OQ-4's
      first condition). The offline acceptance covered a *re-ordering* — top-1 grade
      2 → grade 1, with `D18` falling to rank 2 of 5 and `R@5(=2)` unaffected. A
      prefilter change could turn that into a **disappearance**, which the acceptance
      does not cover and which **fails the merge gate**
- [x] Disclose the Q63 regression in the **delivery release note** as a known
      behaviour change (OQ-4's second condition), and report abstention as
      **unchanged at 4/38**, so the result cannot be over-read as fixing
      zero-relevant
      *(2026-10-03, #2: the disclosure now covers **two** accepted re-ordering
      regressions — Q63 **and Q62** — the second introduced by the query-only split;
      see `spec.md`'s R-8 amendment. **Written at delivery 2026-10-03**: the release
      note `2026-10-03-spec-066-skill-retrieval-ranking-fidelity.md` names both and
      reports abstention unchanged at 4/38.)*
- [x] Append the result as a **new section** to the eval-set artifact; do not rewrite
      its published numbers
- [x] **Null-result path** — if the Postgres-path gain is not outside the noise band,
      publish that, do **not** merge R-1..R-5, record the outcome on the backlog row,
      and revert. This is a real possible ending, not a failure
- [x] Remove the four measurement flags now that R-8 passes, leaving the fixes
      unconditional; re-run the fidelity-gate test's replacement (the shipped
      behaviour is now the new behaviour)

## Stage 6: R-9 — docs, bookkeeping and delivery

- [x] Update `products/skills-hub/README.md`: the endpoint summary currently reads
      "deterministic ranked matches (title ×3, tags ×2, body ×1, `skill_id`
      tie-break)" — restate the new weighting and name `skill_id` as a **scored
      field**, not only a tie-break
- [x] Rewrite the `services/scoring.py` module docstring, which states the fixed
      weighting and the byte-identical rationale as load-bearing documentation
- [x] Ensure **no published prose implies `score` is comparable across queries** —
      R-4's retention makes it query-shape dependent (measured: an exact identifier
      match scores ~~**15.0**~~ **3.0** where the equivalent three-word phrase scores **9.0**).
      *(2026-10-03, #2: the 15.0 was the **document-side** split's identifier/identifier
      case; the shipped **query-only** split re-measures it at **3.0** — only the
      retained whole token matches, at title weight — which now sits **below** the 9.0
      phrase score, inverting the gap but not the obligation: `score` is still
      query-shape dependent. A phrase query against an identifier title scores **0.0**
      (the forgone recall). See `spec.md`'s R-9 bullet.)*
      Nothing consumes the magnitude, so this is a documentation obligation; record
      the constraint for the separate abstention backlog row, which cannot derive a
      threshold from these numbers without accounting for query shape
- [x] Amend or annotate **SPEC-014 R-3** ("keyword matching against title, tags, and
      body with fixed weighting") and state the relationship in both specs — SPEC-014
      is `delivered` and its criterion is now inaccurate
- [x] Update `docs/guides/skills-guide.md` in **three** specific places — the draft's
      "check for any restated weighting" would have missed two of them:
      - its **"Never register the same files twice"** warning justifies itself with
        *"because ranking does no content de-duplication the copies consume result
        slots"* — a clause R-7 makes **false**. Keep the warning (duplicates still
        cost ingestion, storage and sync time), rewrite its rationale, and reframe
        the measured 32-of-63 figure as history
      - its authoring advice to *"name so alert → runbook lookups rank well"* becomes
        materially stronger: with R-1 the slug is a **scored field** and with R-4 its
        CamelCase parts are matchable, so tell authors the `skill_id` is now a
        retrieval surface and how to name for it. This is an improvement the fixes
        make possible, not just a correction
      - its search prose ("multi-word queries match OR-wise; the shared scorer ranks
        them") is checked against the shipped behaviour and updated if the OR
        semantics or the prefilter widening change what an operator would expect
- [x] Document R-2's **bounded staleness** for operators: a newly ingested document
      is searchable immediately, but its arrival does not rebalance token weights
      until the next sync (`SKILLS_SYNC_INTERVAL_SECONDS`, default **300**)
- [x] **Do not edit the delivered release note.**
      `docs/agentic-aiops-platform/release-notes/2026-08-15-skills-and-grounded-guidance.md`
      states "Deterministic scorer: title ×3, tags ×2, body ×1, saturating", which
      this spec makes inaccurate — but it is delivered release history. Record the
      change in **SPEC-066's own** delivery release note and leave the old one as the
      record of what shipped on 2026-08-15
- [x] Confirm the status-header **pointers** in the retrieval memo and the eval-set
      state the **current** lifecycle status, not the status at drafting. Do **not**
      rewrite their measurement text — they are measurement artifacts, and headers
      plus dated corrections are the only in-place edits permitted. The
      `approved`-step update is **already applied** in the approval commit — this
      pass found both headers still saying `draft`, with the memo also saying "six
      Open Questions block `approved`", which the approval made false. What remains
      here is the same update at `delivered`. Both artifacts also carry the false
      "where body hashes exist" claim, corrected in place with a dated note rather
      than left standing
- [x] Verify (do not assume) `products/tool-gateway/tests/test_skills_connector.py`
      passes unchanged — `_MATCH_KEYS` drops `score`, so only ordering and excerpts
      are agent-visible
- [x] Verify `shared/platform-ops/e2e/skills-demo.sh` still passes: it searches
      `q=KubePodNotReady` and is directly affected by R-4. If its assertions encode
      the old tokenization, update them deliberately
- [x] Confirm no `shared/shared-contracts` JSON schema changed — OQ-1(a) established
      `score` is in none of them, so **no contract version bump**; record the
      published-field vs validated-contract distinction in the README
- [x] `CHANGELOG.md` entry referencing SPEC-066; `VERSION` + the lockstep version
      files bump at delivery; `make validate-version` green
- [x] Update `docs/specs/README.md` and the delivery-roadmap Exploration Backlog row
      through the draft → approved → delivered lifecycle. The `draft` and `approved`
      steps are **already recorded** (2026-10-01 and 2026-10-02); what remains is
      `delivered`, with the version and date
- [x] **No ADR** — closed by OQ-3, which preserved the byte-identical invariant as
      written, so ADR-0015 is **not** raised and `docs/adr/README.md` stays
      untouched. The draft's conditional task here ("if OQ-3 narrowed the
      invariant") is therefore recorded as done-with-no-work rather than left
      pending

## Delivery Gate

> Per ADR-0008, the spec advances to `delivered` only when every `R-x` acceptance
> criterion maps to at least one asserting test. Mapping (criterion → asserting test):

- [x] **Stage 0(a)** prefix lexemes reach an unsplit indexed lexeme on the live
      cluster → verified read-only **and** promoted into the R-5 prefilter test, so
      the assumption stays verified rather than being checked once. *The read-only
      half is done (2026-10-02, live `postgres-0`: `kubepod:*` reaches the single
      lexeme `kubepodnotready`, mid-token `pod:*` does not); what this gate still
      waits on is the promotion into the suite.*
- [x] **Stage 0(b)** the CamelCase variant behind 0.711 is re-derived → the rebuilt
      harness reproduces the shipped 19/38 baseline, and any discrepancy against the
      offline candidate numbers is published. *The re-derivation is done (2026-10-02:
      parts-only measured, retention reproduces it exactly); what this gate still
      waits on is the rebuilt, committed harness reproducing 19/38 in the suite.*
- [x] **R-1** slug scored at **`TAG_WEIGHT` (2.0)** (OQ-1(b)) → weight test + the
      fixture-based stratum-A owner-recovery test (0/3 → 3/3)
- [x] **R-1** slug-only match non-empty on **both** backends → R-5 cross-backend test
- [x] **R-2** `ln((1+N)/(1+df))+1`, no stoplist → hand-computed IDF test
- [x] **R-2** statistics computed in Python and **persisted at sync time**, refreshed
      after `replace_source` (OQ-2) → sync-refresh test + a stale-table-still-usable
      test
- [x] **R-2** the `df` path and the scoring path call the **same** `tokenize()` →
      same-tokenizer test (a mismatch would be silent)
- [x] **R-2** backend-independent statistics → parity harness asserting identical
      **scores** (not only ordering)
- [x] **R-2** field-weight ordering preserved (SPEC-014 R-3) → weighting-order test
- [x] **R-2** score stays **decomposable** into per-token, per-field contributions
      (the surviving explainability obligation) → decomposition test
- [x] **R-3** `1/log2(2 + len(body)/1000)`, cap retained, bounds hold → factor-bounds
      test incl. empty and single-character bodies
- [x] **R-3** backend-neutral by construction → per-`Skill` identical-score test with
      no corpus state
- [x] **R-4** ~~`tokenize("KubePodCrashLooping")`~~ **`tokenize_query("KubePodCrashLooping")`**
      (2026-10-03, #2) → `kube`/`pod`/`crash`/`looping`
      **plus the retained whole token** `kubepodcrashlooping`; case table committed →
      tokenizer table test. *#2: the split is **query-side only** — the document-side
      `tokenize()` stays `[a-z0-9]+` and never splits, which is what keeps it
      byte-identical to `to_tsvector('simple')`. `test_case_table` asserts on
      `tokenize_query`; `test_document_side_is_never_split` pins the document side.*
- [x] **R-4** whole-token retention applied consistently ~~in all three places~~ on the
      **query side** (2026-10-03, #2) → consistency test. *#2: retention lives in the
      one query tokenizer `tokenize_query`, not the three document fields — those stay
      unsplit. `test_whole_token_retained_alongside_parts` and
      `test_single_run_is_not_duplicated` assert it.*
- [x] **R-4** existing exact-score assertions updated, not weakened → review + the
      updated assertions themselves; ~~**exactly 1 of 8**~~ **none of the 8** values
      changes (2026-10-03, #2), and two
      fixtures change their `skill_id` rather than their expected number. *#2:
      `test_none_of_the_eight_values_change` asserts `changed == 0` — the query-only
      split leaves every document field unsplit, so the doc-side 7.0 → 27.0 inflation
      that once moved one value no longer occurs. The two fixture `skill_id`s did move
      off `a/pod` (to `a/troubleshooting` and `a/three`) so R-1's slug scoring cannot
      collide with the query `pod`.*
- [x] **R-4** no score inflation on CamelCase-free text → the position-aware
      aggregation, plus a test that every score is identical to its pre-R-4 value
      when nothing in the corpus or query has CamelCase
      *(2026-10-03, #2: `test_no_inflation_on_camel_case_free_text` asserts this for
      distinct-token queries; duplicate-token queries are deliberately excluded because
      R-4 de-duplicates the query before scoring — an intentional **deflation**
      ("pod pod pod" 24.0 → 8.0), asserted separately by
      `test_query_tokens_deduplicated_under_split`, not an inflation.)*
- [x] **R-4** letter↔digit boundary decided and pinned → the committed case table
      covers `HTTP503` and `v0211` in whichever direction was chosen
- [x] **R-4 not shipped without R-2** → the R-4 fidelity gate is recorded as run
      with R-2's flag on
- [x] **R-4/R-5** no query returns fewer rows on Postgres than today → recall guard
      over the committed fixture
- [x] **R-5** `_SEARCH_VECTOR` covers `skill_id`; GIN expression identical to it →
      expression-equality test **plus a reachability test**. Equality alone is not
      sufficient and Stage 0 shows why: the falsified plain-concatenation expression
      is identical in both places, so it would have passed this gate while indexing
      the slug as one opaque `file` lexeme that matches **0 rows**. Assert that a
      query whose only overlap is `skill_id` returns the row **from Postgres**
- [x] **R-5** OR-join retained, no `plainto_tsquery` → existing
      `test_search_joins_multi_word_queries_with_or` still green
- [x] **R-5** **no user-defined SQL function introduced** (OQ-5) → no `CREATE
      FUNCTION` in `_DDL`; Python stays the single tokenizer
- [x] **R-5** IMMUTABLE constraint respected — `to_tsvector('simple',
      replace(replace(skill_id, '/', ' '), '-', ' ') || …)` is built only from
      IMMUTABLE pieces (`replace` measured `provolatile = i` on live `postgres-0`)
      and a constant `regconfig` → index-creation test on a
      real Postgres
- [x] **R-5** migration creates `idx_skills_search_v2` on an existing database,
      **retains** `idx_skills_search`, is idempotent, and uses **no** `CONCURRENTLY`
      → migration test asserting both indexes exist afterwards
- [x] **R-5** rollback is a plain code revert with the old index still present →
      rollback test; index size measured before and after and recorded
- [x] **R-5** p95 inside the 10.0 s gateway timeout, measured end to end → latency
      measurement recorded
- [x] **R-6** harness drives both backends over the same corpus and query set, in the
      ordinary suite → the harness
- [x] **R-6** invariant preserved **as written** with no Postgres-only carve-out
      (OQ-3) → the harness asserts ordering **and** numeric scores; **no ADR** raised
- [x] **R-6** SPEC-014's stale task line annotated → the annotation
- [x] **R-7** duplicate bodies collapse to one hit **before** `[:limit]` → the
      two-identical-bodies test
- [x] **R-7** deterministic survivor (lowest `skill_id`) → survivor-rule test
- [x] **R-7** `parse_sources` unchanged → no overlap logic in `core/config.py`
- [x] **R-7** adds **no overlap logic** to `services/sync.py` — OQ-6 deferred → the
      only change in that file is R-2's statistics refresh, and the deferral plus
      its trigger is recorded in `spec.md`
- [x] **R-8** harness **reconstructed and committed** (not reused) and passing its own
      19/38 fidelity gate → the committed harness + the fidelity test
- [x] **R-8** fixture `body_md5` asserted before any metric; full metric set reported
      per backend; pre-registered statistics reused; ~~Q63~~ **Q62 + Q63** (2026-10-03, #2) and 4/38
      abstention disclosed → the published measurement section
- [x] **R-8** Q63's `D18` **present in the Postgres-path window** (OQ-4's condition)
      → the disappearance assertion; its absence fails the merge gate
- [x] **R-8** null-result path is coded, not assumed → the branch exists and was
      exercised or explicitly not taken
- [x] **R-9** README, `scoring.py` docstring, SPEC-014 annotation, the **three**
      skills-guide places, memo/eval-set pointers, CHANGELOG, VERSION + lockstep,
      spec index, roadmap row, and SPEC-066's own delivery release note all updated
- [x] **R-9** the **delivered** 2026-08-15 release note is **not** edited → confirmed
      absent from the diff
- [x] All four measurement flags removed; the fixes are unconditional
- [x] Full root `make verify` green (every product suite, overlay render, policy
      rules, version lockstep, secret vocabulary)
- [x] Living state docs updated (see `spec.md` Impact)
- [x] `spec.md` status set to `delivered` (+ delivered date/version + changelog)
