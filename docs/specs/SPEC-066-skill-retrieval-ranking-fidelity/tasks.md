# SPEC-066 Tasks: Skill Retrieval Ranking Fidelity — The Four Measured Lexical Fixes, Cross-Backend Parity, And A De-Duplication Guardrail

Task states: `[ ]` pending, `[x]` done. Keep tasks small and tied to requirement IDs.

> **PROVISIONAL — pending scope approval.** SPEC-066 is `draft` with **six
> unresolved Open Questions** in `spec.md`. This task list is derived from the
> provisional `plan.md` and will change when OQ-1(b), OQ-2 and OQ-5 are answered.
> **No task below may be started until the spec is `approved`.** Approval itself
> authorizes implementation as a separate step; it does not authorize commit/push,
> the R-5 index migration, deployment, or a version bump — each is its own
> authorization boundary. Stage 0 is read-only and is the first thing to execute
> after approval.

## Stage 0: Open-Question resolution (read-only; blocks everything else)

- [ ] **OQ-1(a)** — decide whether the published `score` field's changed semantics
      need documenting as unstable, given it is in no contract schema, is not
      portal-rendered, and is dropped by the tool-gateway connector (verified at
      drafting). Record the decision in `spec.md`
- [ ] **OQ-1(b)** — fix the weight `skill_id` enters at. Default `TAG_WEIGHT` (2.0),
      which is what the measurement used; **any other value is an unmeasured
      candidate and requires re-measurement**, not a review decision
- [ ] **OQ-2** — choose the IDF corpus-statistics source: per-request over the whole
      catalog (recommended), a sync-time statistics table (defers a second
      migration), **or** over the `rank()` pool (**rejected** — the two callers pass
      different pools and it breaks backend parity). Also fix R-4's whole-token rule
      here, since it changes `df`
- [ ] **OQ-3** — confirm the byte-identical cross-backend ordering invariant is
      **preserved as written** (recommended; nothing here is semantic retrieval, so
      the memo §11 narrowing does not apply). If narrowed, record as **ADR-0015**
      and update `docs/adr/README.md`
- [ ] **OQ-4** — accept or reject the known Q63 re-ordering regression (top-1 grade
      2 → grade 1; the grade-2 document falls to rank 2 of 5, `R@5(=2)` unaffected)
- [ ] **OQ-5** — fix the GIN migration and rollback plan, the prefilter strategy
      (mirror the tokenizer in an IMMUTABLE SQL function **vs** widen the prefilter,
      recommended), and the concurrency window (`CREATE INDEX CONCURRENTLY` cannot
      run in a transaction)
- [ ] **OQ-6** — decide whether sync-time overlap rejection is wanted in addition to
      R-7's `rank()` de-duplication, and if so its failure posture (reject the source
      vs ingest and warn)
- [ ] Confirm the **label-set ownership** position: R-8 re-uses the author-proposed,
      operator-ratified fixture as-is, and operations ownership remains a
      precondition only if the row is ever reopened for embedding work
- [ ] Record all resolutions in `spec.md` (Open Questions → resolved), lift the
      `plan.md` / `tasks.md` provisional banners, and set status `draft` → `approved`

## Stage 1: R-6 — parity harness first (no OQ dependency)

> Land before any scoring change, so the baseline is established and a pre-existing
> invariant violation is found by the harness rather than blamed on the new code.

- [ ] Decide the Postgres side of the harness: drive a **real** Postgres (the
      SPEC-063 campaign precedent) or an equivalent. **A `_fake_connect` that returns
      canned rows cannot exercise the prefilter and a fake that returns every row
      makes the harness pass vacuously — do not accept either**
      (`products/skills-hub/tests/test_skill_store.py`)
- [ ] Commit the query-set fixture: the union of the 63-query audit pool and the 18
      authored stratum-C paraphrases
- [ ] Add the harness: build the **same** corpus into both `InMemorySkillStore` and
      `PostgresSkillStore`, assert identical `skill_id` **ordering** for every query
      in the fixture
- [ ] Extend the harness to assert identical **scores**, not only ordering — this is
      what makes R-2's backend-independent IDF numeric rather than aspirational
- [ ] Run the harness against the **current** code and record the outcome either way
      (a pass establishes the baseline; a fail is a pre-existing defect and gets its
      own finding, not a suppression)
- [ ] Annotate `docs/specs/SPEC-014-skills-and-grounded-guidance/tasks.md` line 32:
      it claims a delivered "byte-identical ordering parity test vs in-memory store"
      that does not exist, and names `plainto_tsquery` where the shipped code
      OR-joins `to_tsquery` lexemes. SPEC-014 is `delivered`, so correct by **dated
      annotation**, not silent edit
- [ ] Test: the harness runs in the ordinary suite (`make test` / `make verify`), not
      as a manual step

## Stage 2: R-3 → R-1 → R-4 → R-2 (each behind a flag, each fidelity-gated)

> Ordered cheapest and least-coupled first. R-4 precedes R-2 because R-4's tokenizer
> determines R-2's `df`. **None of these is separately shippable** — no single fix
> reaches significance alone.

- [ ] Add the four module-level flags to `services/scoring.py` (naming fixed at
      implementation). Flags are a **measurement instrument**, removed at Stage 5
- [ ] **R-3** — apply `1 / log2(2 + len(body)/1000)` to the **already-capped** body
      contribution; retain `BODY_OCCURRENCE_CAP = 5` (`services/scoring.py`)
- [ ] Test R-3: the factor is in `(0, 1]` and strictly positive for every body
      including empty and single-character; equal capped occurrences ⇒ the longer
      body contributes strictly less; **backend-neutral without corpus state**
- [ ] **R-1** — add `id_tokens = set(tokenize(skill.skill_id))` to `score()`,
      credited at the OQ-1(b) weight (`services/scoring.py`)
- [ ] Test R-1: slug separators tokenize consistently with the title
      (`samples/password-reset-resetacmepassword` → `samples`, `password`, `reset`,
      `resetacmepassword`)
- [ ] Test R-1 against the **committed label fixture**, not a hand-written
      expectation: the identifier's owner ranks first for all 3 stratum-A queries
      that name an identifier existing in the corpus (the measurement's 0/3 → 3/3)
- [ ] Test R-1: the 11 stratum-A queries naming a nonexistent identifier are not made
      worse; record their behaviour (they still return 7–10 confident hits —
      abstention, out of scope)
- [ ] **R-4** — replace `TOKEN_PATTERN = re.compile(r"[a-z0-9]+")` with a two-step
      tokenize (CamelCase/digit boundary split, then the existing alphanumerics rule
      retained as the final step so non-CamelCase text is unaffected)
- [ ] Commit the R-4 case table as tests: `KubePodNotReady`, `CrashLoopBackOff`,
      `HTTP503` (acronym run — verify it does not become `h`/`t`/`t`/`p`/`503`),
      `pgBouncer`, `v0211`, plus already-lowercase and digit-only cases that must be
      unaffected
- [ ] Apply the OQ-2 whole-token rule **identically** in `tokenize()`, in R-2's `df`
      computation, and in R-5's prefilter — a mixed application is silently wrong
- [ ] Update the **8 exact-score assertions** in `tests/test_scoring.py`
      deliberately: `score("KubePodNotReady", skill) == 7.0` encodes the defect R-4
      removes, so it must change. **Do not weaken any assertion to a vague
      comparison to make the change pass** — old and new values both visible in
      review
- [ ] **R-2** — introduce an explicit immutable corpus-statistics value (`N` + a `df`
      map) and pass it to `score()`; implement `ln((1+N)/(1+df))+1`. **No
      hand-written stoplist anywhere in the path**
- [ ] Check for `score()` callers outside `skill_store.py` before changing the
      signature (tool-gateway: none; portal: none — verified at drafting, re-verify).
      Prefer an **explicit required** parameter over a default that hides a
      wrong-by-default corpus
- [ ] Ensure R-2's `df` is computed with the **same** `tokenize()` the scorer uses —
      two tokenizers in one file is the failure mode
- [ ] Test R-2: IDF against hand-computed `N`/`df`; field-weight **ordering**
      (title 3.0 > tags 2.0 > body 1.0) unchanged so SPEC-014 R-3's guarantee holds;
      `certificate expired on the ingress` stops ranking a password-reset runbook
      first, with the mechanism assertable ("the" contributes materially less)
- [ ] **Fidelity gate** — test that with **all four flags off** the scorer reproduces
      the shipped behaviour exactly (the eval-set's 38/38 gate, reproduced in the
      product's own suite)

## Stage 3: R-5 — prefilter, index and migration

> Depends on R-4's tokenizer rule being final. **Highest-risk stage**: the prefilter's
> failure mode is a silently missing row.

- [ ] Add `skill_id` to `_SEARCH_VECTOR` so a slug-only match is returned by the
      prefilter (`services/skill_store.py`)
- [ ] Implement the OQ-5 prefilter strategy: **widen the prefilter** (recommended —
      no SQL tokenizer, so nothing can drift from Python; the failure mode is a slow
      query, which is loud) **or** mirror R-4 in an **IMMUTABLE** SQL function
- [ ] If a SQL split function is used: prove it IMMUTABLE (the DDL already records
      that `array_to_string`/`array_out` are STABLE, which is why tags stay out of
      the index) and pin it against the Python case table by test
- [ ] Keep the **OR-join** of query lexemes; do **not** introduce `plainto_tsquery`
      (it ANDs and would silently drop partial matches — already documented by
      `test_search_joins_multi_word_queries_with_or`)
- [ ] Keep the prefilter an **over-approximation** of the scorer's non-zero set, per
      the shipped comment's contract
- [ ] Change the `idx_skills_search` GIN expression to match `_SEARCH_VECTOR`
      **exactly**, and add a test that compares the two so the index cannot silently
      stop being used
- [ ] Write the migration: `_DDL` uses `CREATE INDEX IF NOT EXISTS`, so an existing
      deployment keeps the **old** index and the new expression goes unindexed
- [ ] Test the migration **actually rebuilds** the index on an existing database
      (not silently skipped), and test the **rollback** — the `skills` database shares
      `postgres-0`'s 1 Gi PVC with `audit`, `incidents` and `sessions`, so a botched
      migration is not contained to skills
- [ ] Test R-5: a query whose only match is in `skill_id` returns rows on **Postgres**
      as well as in memory
- [ ] Test R-5/R-4 recall guard: **no query in the fixture returns fewer rows than it
      does today** on the Postgres path
- [ ] Measure search latency p95 **end to end** on the Postgres path against the
      tool-gateway's 10.0 s `REQUEST_TIMEOUT_SECONDS`. Do **not** cite the eval-set's
      offline p50 2.726 ms — it excludes the prefilter, HTTP, auth and the audit write

## Stage 4: R-7 — de-duplication guardrail (parallel with Stages 2–3)

- [ ] Implement content-hash collapse in `rank()` **before** `hits.sort(...)` and
      before `[:limit]`, retaining the **lowest `skill_id`** (consistent with the
      existing ascending tie-break, so the survivor is deterministic)
      (`services/scoring.py`)
- [ ] Use `md5(body)` as the identity key, matching the `body_md5` the label fixture
      pins. Record in a comment that MD5 here is a **content-identity key, not a
      security digest**, so a future security review does not flag it as a weak hash
      in a security context
- [ ] **Do not** put overlap detection in `core/config.py::parse_sources` — it
      validates `SKILLS_SOURCES` JSON and never sees file content, so it structurally
      cannot detect content overlap
- [ ] Test R-7: a corpus with two byte-identical bodies under different `source_id`s
      returns **one** hit and the freed slot is filled by the next-ranked distinct
      document
- [ ] Test R-7: collapse precedes truncation (the measured defect was wasted slots,
      not duplicate output)
- [ ] If OQ-6 chose sync-time rejection: implement it where body hashes exist
      (`services/sync.py`), with the decided failure posture and an operator-visible
      error; test both the reject and warn paths
- [ ] Record that `skill_searched` details `result_count` and `skill_ids` change
      observably when duplicates collapse — existing event type, existing fields, new
      values, **no vocabulary change**
- [ ] Document R-7 as **regression protection, not a retrieval improvement**: the dev
      corpus is already clean (0 of 63 pools contain a duplicate), so there is no
      crowding left to measure a gain against and **no label evidence is claimed**

## Stage 5: R-8 — re-measurement on the shipped path (the merge gate)

> **This gates the merge; it is not a post-merge report.**

- [ ] Extend the offline evaluation harness to drive `PostgresSkillStore.search()`
      rather than `rank()` directly, so the prefilter is inside the measured path
- [ ] Assert the fixture's `body_md5` per document **first**, failing loudly on
      mismatch rather than silently invalidating the comparison
      (`semantic-skill-retrieval-labels.json`, 38 × 18 = 684 judgments, 173 non-zero)
      — **re-use without re-grading**
- [ ] Report the full required metric set: **zero-relevant rate** (not zero-hit rate
      alone), distinct-document variants, P@5, R@5/@10, MRR, MRR(2), nDCG@10, rank
      stability, latency p50/p95 end to end
- [ ] Report **per backend**; a gain that appears in memory and not on Postgres is
      published as such
- [ ] Reuse the pre-registered statistics unchanged: paired bootstrap (10,000
      resamples, seed 20261001) with 95% CIs on per-query deltas, plus an exact
      two-sided sign test on discordant top-1 pairs. **Do not rely on Precision@5**
      (its baseline CI lower bound rounds to zero)
- [ ] Disclose the Q63 regression and report abstention as **unchanged at 4/38**, so
      the result cannot be over-read as fixing zero-relevant
- [ ] Append the result as a **new section** to the eval-set artifact; do not rewrite
      its published numbers
- [ ] **Null-result path** — if the Postgres-path gain is not outside the noise band,
      publish that, do **not** merge R-1..R-5, record the outcome on the backlog row,
      and revert. This is a real possible ending, not a failure
- [ ] Remove the four measurement flags now that R-8 passes, leaving the fixes
      unconditional; re-run the fidelity-gate test's replacement (the shipped
      behaviour is now the new behaviour)

## Stage 6: R-9 — docs, bookkeeping and delivery

- [ ] Update `products/skills-hub/README.md`: the endpoint summary currently reads
      "deterministic ranked matches (title ×3, tags ×2, body ×1, `skill_id`
      tie-break)" — restate the new weighting and name `skill_id` as a **scored
      field**, not only a tie-break
- [ ] Rewrite the `services/scoring.py` module docstring, which states the fixed
      weighting and the byte-identical rationale as load-bearing documentation
- [ ] Amend or annotate **SPEC-014 R-3** ("keyword matching against title, tags, and
      body with fixed weighting") and state the relationship in both specs — SPEC-014
      is `delivered` and its criterion is now inaccurate
- [ ] Check `docs/guides/skills-guide.md` for any restated weighting and update if
      present
- [ ] Add a status-header **pointer** to this spec in the retrieval memo and the
      eval-set. Do **not** rewrite their text — they are measurement artifacts
- [ ] Verify (do not assume) `products/tool-gateway/tests/test_skills_connector.py`
      passes unchanged — `_MATCH_KEYS` drops `score`, so only ordering and excerpts
      are agent-visible
- [ ] Verify `shared/platform-ops/e2e/skills-demo.sh` still passes: it searches
      `q=KubePodNotReady` and is directly affected by R-4. If its assertions encode
      the old tokenization, update them deliberately
- [ ] Confirm no `shared/shared-contracts` JSON schema changed; record the
      published-field vs validated-contract distinction in the README
- [ ] `CHANGELOG.md` entry referencing SPEC-066; `VERSION` + the lockstep version
      files bump at delivery; `make validate-version` green
- [ ] Update `docs/specs/README.md` and the delivery-roadmap Exploration Backlog row
      through the draft → approved → delivered lifecycle
- [ ] If OQ-3 narrowed the invariant: add ADR-0015 and update `docs/adr/README.md`

## Delivery Gate

> Per ADR-0008, the spec advances to `delivered` only when every `R-x` acceptance
> criterion maps to at least one asserting test. Mapping (criterion → asserting test):

- [ ] **R-1** slug scored at the OQ-1(b) weight → weight test + the fixture-based
      stratum-A owner-recovery test (0/3 → 3/3)
- [ ] **R-1** slug-only match non-empty on **both** backends → R-5 cross-backend test
- [ ] **R-2** `ln((1+N)/(1+df))+1`, no stoplist → hand-computed IDF test
- [ ] **R-2** backend-independent statistics → parity harness asserting identical
      **scores** (not only ordering)
- [ ] **R-2** field-weight ordering preserved (SPEC-014 R-3) → weighting-order test
- [ ] **R-3** `1/log2(2 + len(body)/1000)`, cap retained, bounds hold → factor-bounds
      test incl. empty and single-character bodies
- [ ] **R-3** backend-neutral by construction → per-`Skill` identical-score test with
      no corpus state
- [ ] **R-4** `tokenize("KubePodCrashLooping")` → `kube`/`pod`/`crash`/`looping`;
      case table committed → tokenizer table test
- [ ] **R-4** whole-token rule applied consistently in all three places → consistency
      test
- [ ] **R-4** existing exact-score assertions updated, not weakened → review + the
      updated assertions themselves
- [ ] **R-4/R-5** no query returns fewer rows on Postgres than today → recall guard
      over the committed fixture
- [ ] **R-5** `_SEARCH_VECTOR` covers `skill_id`; GIN expression identical to it →
      expression-equality test
- [ ] **R-5** OR-join retained, no `plainto_tsquery` → existing
      `test_search_joins_multi_word_queries_with_or` still green
- [ ] **R-5** IMMUTABLE constraint respected → index-creation test on a real
      Postgres
- [ ] **R-5** migration actually rebuilds + rollback tested → migration and rollback
      tests
- [ ] **R-5** p95 inside the 10.0 s gateway timeout, measured end to end → latency
      measurement recorded
- [ ] **R-6** harness drives both backends over the same corpus and query set, in the
      ordinary suite → the harness
- [ ] **R-6** SPEC-014's stale task line annotated → the annotation
- [ ] **R-7** duplicate bodies collapse to one hit **before** `[:limit]` → the
      two-identical-bodies test
- [ ] **R-7** deterministic survivor (lowest `skill_id`) → survivor-rule test
- [ ] **R-7** `parse_sources` unchanged → no overlap logic in `core/config.py`
- [ ] **R-8** fixture `body_md5` asserted before any metric; full metric set reported
      per backend; pre-registered statistics reused; Q63 regression and 4/38
      abstention disclosed → the published measurement section
- [ ] **R-8** null-result path is coded, not assumed → the branch exists and was
      exercised or explicitly not taken
- [ ] **R-9** README, `scoring.py` docstring, SPEC-014 annotation, guide, memo/eval-set
      pointers, CHANGELOG, VERSION + lockstep, spec index, roadmap row all updated
- [ ] All four measurement flags removed; the fixes are unconditional
- [ ] Full root `make verify` green (every product suite, overlay render, policy
      rules, version lockstep, secret vocabulary)
- [ ] Living state docs updated (see `spec.md` Impact)
- [ ] `spec.md` status set to `delivered` (+ delivered date/version + changelog)
