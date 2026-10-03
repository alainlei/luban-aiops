# v0.46.0 — Skill-Retrieval Ranking Fidelity: The Four Measured Lexical Fixes (SPEC-066)

Date: 2026-10-03
Release type: minor (a `skills-hub` retrieval-ranking fidelity slice — no new
route, action, contract, JSON schema, audit event type, or execution path; the only
database change is the additive, idempotent `idx_skills_search` →
`idx_skills_search_v2` GIN expression-index swap, +8 KiB)

## Summary

This release ships
[SPEC-066](../../specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md), the
cheap-lexical step that closes the "Semantic (vector) skill retrieval"
[delivery-roadmap](../delivery-roadmap.md#exploration-backlog) backlog row. It
fixes four measured ranking defects in the `skills-hub` scorer, adds an enforced
cross-backend parity harness and a product-side de-duplication guardrail, and
re-measures the result on the shipped PostgreSQL path — publishing what was
measured rather than what the offline memo predicted.

It **extends** [SPEC-014](../../specs/SPEC-014-skills-and-grounded-guidance/spec.md)
R-3, whose "keyword matching against title, tags, and body with fixed weighting"
criterion is annotated **superseded in part**: `skill_id` becomes a fourth scored
field and the flat weighting becomes corpus-derived. The delivered SPEC-014
release note
([2026-08-15](2026-08-15-skills-and-grounded-guidance.md)) states the old
"title ×3, tags ×2, body ×1, saturating" scorer and is **left untouched** as
delivered release history; the change is recorded here instead.

**Vector retrieval is still not authorized.** Gate 1 found zero grade-2 documents
missing from the top 10 on any of the 38 queries, so there is no recall gap for a
vector store to recover; under the row's pre-registered cost-ordered rule the cheap
lexical step closes it. The recorded scale trigger (**>2,000 skills** or **search
p95 >300 ms**, whichever first) is the only reopening condition. No embedding,
pgvector, `ts_rank_cd`, `pg_trgm`, alias map, or stemming ships.

## What shipped

The four fixes were measured incrementally behind flags during R-8 and are made
**unconditional** at R-9 (the flags are removed, so the measured-best
configuration is now the only shipped scorer):

- **R-1 — Score the `skill_id` slug.** The slug becomes a fourth scored field at
  the tag weight (×2), so an identifier-owner query (`KubePodNotReady`) recovers
  its runbook. `skill_id` is the primary key, so no column is added anywhere.
  Headline effect: stratum-A identifier-owner recovery **0/3 → 3/3**.
- **R-2 — Corpus-derived IDF weighting.** The flat per-field weighting is scaled
  by a smoothed inverse document frequency, `ln((1+N)/(1+df))+1`, with **no
  stoplist** — a high-`df` token such as "the" is down-weighted by its own
  frequency. `df` is computed in Python over the whole catalog at sync time
  (`compute_stats`) and refreshed after each successful `replace_source`; an
  unrefreshed store passes `EMPTY_STATS`, whose neutral `idf = 1.0` degrades
  scoring gracefully to plain field weighting.
- **R-3 — Sublinear body-length normalization.** The capped body contribution
  (occurrence cap 5) is damped by `1/log2(2+len(body)/1000)`, so a long sample can
  no longer out-score a short runbook on raw term count. Per-document and
  backend-neutral by construction.
- **R-4 — Query-side-only CamelCase splitting.** A CamelCase/digit identifier run
  is split into its parts *and* the whole token retained (`KubePodNotReady` →
  `kube`, `pod`, `not`, `ready`, `kubepodnotready`), but **on the query side only**
  (`tokenize_query`). Every document field (`title`, `tags`, `body`, `skill_id`)
  and R-2's `df` stay on the unsplit `tokenize` (`[a-z0-9]+`), which is
  byte-identical to PostgreSQL's `to_tsvector('simple', …)` lexemes. Because
  `score()` matches by **exact** token membership, query-side splitting only ever
  **widens** the candidate set — it can never under-admit.
- **R-5 / R-6 — Cross-backend parity, by construction.** The query-only split is
  what makes R-5's GIN prefilter a sound **over-approximation** of the scorer's
  non-zero set and R-6's parity invariant hold **by construction** rather than by
  prefix-lexeme luck, keeping Python the sole decider of ordering on both backends.
  An enforced parity harness drives both stores and fails on any divergence. The
  migration swaps the `idx_skills_search` expression index for
  `idx_skills_search_v2` (**155,648 B → 163,840 B, +8,192 B** — one 8 KiB page at
  18 rows); measured search latency is unchanged (n=81, p50 19.1 ms / p95 24.8 ms).
- **R-7 — Product-side de-duplication guardrail.** `rank()` collapses hits sharing
  an `md5(body)` **before** the sort and **before** `[:limit]`, retaining the
  lowest `skill_id` (consistent with the ascending tie-break, so the survivor is
  deterministic). This generalizes the dev-overlay `SKILLS_SOURCES` single-route
  cleanup so an overlapping source registration can no longer consume distinct
  result slots regardless of configuration. It is **regression protection, not a
  ranking gain** — a no-op on the now duplicate-free dev corpus, so it needs and
  claims no label evidence. This introduces the only hashing in `skills-hub`; MD5
  is used strictly as a content-identity key, not a security digest.

## Measured outcome (R-8, on the shipped PostgreSQL path)

Re-run against the committed label fixture (38 queries × 18 documents = 684
judgments, pinned by `body_md5`, no re-grading), through `PostgresSkillStore.search()`
so the prefilter is inside the measured path. The rebuilt harness first reproduces
the shipped scorer's baseline before any candidate number is believed:

| Config | Combined top-1 (grade 2) | Note |
|---|---|---|
| V0 (baseline, fixes off) | **19/38** | fidelity gate — reproduces the published baseline |
| V3 (IDF + length-norm + query-split, no `skill_id`) | **23/38** | the three backend-neutral fixes |
| **V6 (all four — shipped)** | **24/38** | R-1's `skill_id` adds the 24th |

Combined MRR **0.842**; stratum-B MRR **0.900**; stratum-C top-1 grade 2 **10/18**
and MRR **0.778**. The null result holds: **0** grade-2 documents leave the
returned window, and zero-relevant abstention is **unchanged at 4/38** (so the
result cannot be over-read as fixing the abstention gap — that stays its own
backlog row). The offline memo's 27/38 and an earlier document-side rebuild's
26/38 are **not** reproduced and are **not** claimed: the query-only split forgoes
the plain-word → CamelCase-title recall that document-side splitting bought, and
**24/38 is the number that ships**.

## Disclosed regressions and significance

Recorded, not smoothed, under R-8's "ship what was measured" rule:

1. **The pre-registered top-1 sign test lost significance.** Offline
   document-side it was (9 improved, 1 regressed) **p = 0.0117**; re-measured under
   the query-only split it is **(7, 2) p = 0.1797** — *directional only, not
   significant at α = 0.05*. The **primary** significance result still holds: the
   paired nDCG@10 bootstrap (10,000 resamples, seed 20261001) gives a 95% CI of
   **[+0.022, +0.111]**, which **excludes zero**. The claim narrows to "a real
   nDCG@10 gain whose top-1 win count is directional", and the spec prose says so
   rather than citing p = 0.0117 unqualified.
2. **Two accepted in-window top-1 re-orderings, not one.** OQ-4 accepted **Q63**
   (`D18` grade 2 → `D13` grade 1, `D18` to rank 2 of 5, `R@5(=2)` unaffected).
   The re-measurement adds **Q62** (`D17` grade 2 → `D18` grade 1) of the *same*
   severity class. Both are stratum-C paraphrases whose grade-2 document **remains
   returned** — an in-window re-ordering, not a disappearance — so the null result
   stays 0 missing. Q62 was not in OQ-4's original single-regression acceptance;
   it is disclosed here and named as a known behavior change rather than left for an
   operator to discover.

One earlier story was **corrected by measurement**: Q45's `D15`-over-`D12`
ordering is top-1 in *all three* configs, so it is not an R-1 slug regression but
the **R-4 query-only recall cost** — `D12` (`KubePodNotReady`) no longer matches a
bare plain-word query because the document side is unsplit.

## Changed

- **R-9 — Contract and living docs.** The `skills-hub` README restates the search
  endpoint's weighting (four scored fields; `skill_id` at ×2; IDF and sublinear
  length-norm) and records that a `score` is an **ordering key within one query's
  result set, never comparable across queries** — R-4's whole-token retention makes
  the magnitude query-shape dependent (measured: an exact `KubePodNotReady`
  identifier query scores its title-matching owner **3.0**, the equivalent
  three-word phrase scores **9.0**, and a plain-word query against an
  identifier-only title scores **0.0**). The `scoring.py` module docstring is
  rewritten to the shipped behavior while still asserting the byte-identical
  invariant (now enforced by R-6); SPEC-014 R-3 gains a dated superseded-in-part
  annotation; `docs/guides/skills-guide.md` is updated in four places (the
  `skill_id` as a scored retrieval surface, the rewritten de-duplication-warning
  rationale, the search prose, and a bounded-staleness operator note); and the
  retrieval memo + evaluation set gain status-header pointers to this spec without
  rewriting their measurement text. **No JSON schema changes** — `score` is
  published on `GET /api/v1/skills/search` but appears in no
  `shared/shared-contracts` schema, so a changed value distribution is not a
  contract-schema change.

## Verification

- `make verify` green, including the `skills-hub` suite (the reconstructed
  evaluation harness `test_evaluation.py`, the enforced parity harness
  `test_parity.py`, and the de-flagged `test_prefilter.py`) and the tool-gateway
  `test_skills_connector.py` (33 passed, unchanged — the connector's `_MATCH_KEYS`
  projection drops `score`, so it is flag-agnostic).
- The R-6 parity harness was run against real PostgreSQL 16 (the former
  candidate-parity XFAIL is now green with `idx_skills_search_v2` in service), and
  R-8's re-measurement is driven through the Postgres backend, not `rank()`
  directly, so the prefilter is inside the measured path.
- `make validate-version` green at **0.46.0** across the eight products and the
  portal.

## Posture

Behavior-changing on retrieval **ordering and excerpts only**; additive and safe on
everything else. No route, action, contract, JSON schema, audit-event-type, or
execution-path change; no new audit event type (R-7 changes the *values* of the
existing `skill_searched` details, which is recorded, not a new type). The
`score` field keeps its shape and its float type; only its value distribution
changes, and no consumer reads its magnitude. The migration is additive and
idempotent: it creates `idx_skills_search_v2` and **retains** the old
`idx_skills_search` for one release as a rollback safety, so the drop of
`idx_skills_search` is a deliberate one-release tail **scheduled for the following
release** (recorded here so the next release sees it). Identity, policy, and
execution-safety semantics are unchanged. The delivered SPEC-014 release note is
deliberately left untouched.
