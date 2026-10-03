"""R-8 evaluation merge gate + R-1 stratum-A owner recovery (SPEC-066).

This module is SPEC-066's **merge gate**. It drives the rebuilt harness in
``support.eval_harness`` through a store's async ``search()`` — never ``rank()``
directly — so that on the Postgres backend the ``to_tsvector`` prefilter is
inside the measured path (a memory-only gain the prefilter silently turns into a
disappearance is exactly what R-8 exists to catch; OQ-4's first condition).

**Post-R-9 state.** The four lexical-fidelity fixes are now unconditional: R-9
removed the measurement flags that gated them during R-8's re-measurement, so
the scorer this harness drives through ``search()`` *is* the configuration R-8
selected — the former "all-flags-on" candidate (V6), which measures combined
top-1 grade-2 = **24/38**. The pre-R-9 shipped baseline (all flags off, V0,
**19/38**) can no longer be produced live; it was captured to the committed
fixture ``tests/fixtures/v0_baseline_ranks.json`` *before* the flags were
removed. Every comparison below — the pre-registered significance tests, the
owner-recovery headline, the Q63/Q45 re-orderings, the null result — now runs
the **live unconditional scorer against that frozen V0 baseline**, so the
evidence R-8 recorded stays reviewable without shipping a second scorer.

The ordering of the classes below is deliberate and load-bearing:

1. ``TestFidelityGate`` runs **first**. It proves two things before any later
   number is believed: (a) the frozen V0 fixture, run through this harness's
   metric math, reproduces the published §8.1 baseline (combined top-1 =
   **19/38**, all 33 values) — so the comparison target is the genuine
   artifact; and (b) the live scorer, driven through ``store.search()`` on the
   md5-pinned corpus, reproduces the measured candidate headline (**24/38**) —
   so the instrument is sound on the shipped configuration and the flag removal
   demonstrably took effect.
2. ``TestStratumAOwnerRecovery`` is R-1's headline (§2.6 / spec.md OQ-1):
   identifier-owner recovery at top-1 goes **0/3 → 3/3** — 0/3 read from the
   frozen V0 fixture, 3/3 measured live. (The R-8 decomposition that showed
   neither R-1 nor R-4 reaches 3/3 alone was measured across partial flag
   configs that no longer exist; it is recorded in eval-set §8.5 and the
   delivery note rather than re-run here.)
3. ``TestQ63Regression`` pins OQ-4's accepted re-ordering (a grade-2 document
   falls to rank 2 but stays **inside** the returned window): frozen V0 top-1
   ``D18`` → shipped top-1 ``D13``.
4. ``TestShippedV6Discrepancy`` is the honest core of R-8. The shipped scorer
   measures **24/38**, below both the memo's **27/38** and the doc-side split's
   **26/38**; the widened gap is R-4's query-only scope giving up plain-word →
   CamelCase-title recall (Q45 is the worked example), and it is **published,
   not hidden**.
5. ``TestSignificance`` and ``TestNullResult`` carry the pre-registered
   bootstrap / sign test and the coded null-result path, live-vs-frozen-V0. The
   nDCG@10 bootstrap CI still excludes zero; the coarser top-1 sign test is
   directional (7:2) and does not reach 0.05 at n=38 — recorded, not smoothed
   (no recall gap → no embedding work authorized; abstention gap unchanged).
6. ``TestPostgresPath`` re-checks the load-bearing outcomes on the real deployed
   backend. It **fails loudly** without Docker (conftest's ``postgres_server``);
   it runs in the ordinary suite under ``make verify``, not as a manual step.

Every expected value below was reproduced against
``docs/workspace/semantic-skill-retrieval-eval-set.md`` §8 before being pinned.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path

from skills_hub.services.skill_store import InMemorySkillStore, PostgresSkillStore
from support import corpus
from support import eval_harness as harness

# --- Graded set + code maps, derived from the committed label fixture. ---------
_LABELS = corpus.load_labels()
GRADED = harness.load_graded(_LABELS)
ID_TO_CODE, CODE_TO_ID = harness.code_maps(_LABELS)
_QUERIES = corpus.load_queries()
QUERY_BY_ID = {q["id"]: q for q in _QUERIES}

# --- Frozen pre-R-9 baseline (all measurement flags off; V0 in §8.1). ---------
# Captured to a committed fixture *before* R-9 removed the flags, so the R-8
# comparison/significance evidence stays live without shipping a second scorer.
_V0_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "v0_baseline_ranks.json"


def _v0_ranks() -> dict[str, list[str]]:
    """The frozen V0 baseline: depth-10 ranked document codes keyed by query id.

    Covers the 38 graded queries plus the three stratum-A owner queries
    (Q05/Q06/Q15). ``TestFidelityGate`` asserts these ranks reproduce §8.1's
    published 33 values before any test trusts them as the comparison target.
    """
    return json.loads(_V0_FIXTURE.read_text(encoding="utf-8"))


# --- Published §8.1 baseline (V0, all flags off, measured 2026-10-01). --------
# Transcribed verbatim from eval-set §8.1. TestFidelityGate asserts the frozen
# V0 fixture reproduces every one of these 33 values; a single mismatch means the
# fixture (not the scorer) is wrong, and no comparison below is trustworthy.
V0_PUBLISHED = {
    "B": {
        "n": 20, "top1_grade2": 13, "zero_hit": 0, "zero_relevant": 1,
        "precision_at_5": 0.700, "mrr": 0.875, "mrr2": 0.750, "ndcg_at_10": 0.868,
        "recall_at_5_ge1": 0.704, "recall_at_10_ge1": 0.869, "recall_at_5_eq2": 1.000,
    },
    "C": {
        "n": 18, "top1_grade2": 6, "zero_hit": 0, "zero_relevant": 3,
        "precision_at_5": 0.467, "mrr": 0.662, "mrr2": 0.524, "ndcg_at_10": 0.742,
        "recall_at_5_ge1": 0.698, "recall_at_10_ge1": 0.850, "recall_at_5_eq2": 0.817,
    },
    "combined": {
        "n": 38, "top1_grade2": 19, "zero_hit": 0, "zero_relevant": 4,
        "precision_at_5": 0.589, "mrr": 0.774, "mrr2": 0.643, "ndcg_at_10": 0.813,
        "recall_at_5_ge1": 0.701, "recall_at_10_ge1": 0.861, "recall_at_5_eq2": 0.914,
    },
}

# The stratum-A identifier-owner queries and the document that owns them. Q05/Q06
# name "ResetPasswordAdHoc" (CamelCase) and Q15 its lowercase slug form; D13 is
# ``samples/adhoc-password-reset-resetpasswordadhoc`` (§2.6, spec.md OQ-1).
OWNER = "D13"
OWNER_QUERIES = ("Q05", "Q06", "Q15")
# The one grade-2 → grade-0 regression the memo records (§8.3) and OQ-4 accepts.
Q63 = "Q63"


async def _populate(store, records) -> None:
    """Initialize ``store``, load ``records`` per source, refresh statistics.

    Mirrors conftest's ``_populate`` so the evaluation path loads a store exactly
    the way the parity fixtures do.
    """
    by_source: dict[str, list] = defaultdict(list)
    for skill in records:
        by_source[skill.source_id].append(skill)
    await store.initialize()
    for source_id in sorted(by_source):
        await store.replace_source(source_id, by_source[source_id])
    await store.refresh_statistics()


def _measure(records):
    """The live (unconditional) scorer's metrics by stratum + raw ranks."""
    store = InMemorySkillStore()
    asyncio.run(_populate(store, records))
    ranks = asyncio.run(harness.collect_ranks(store.search, GRADED, ID_TO_CODE))
    return harness.metrics_by_stratum(ranks, GRADED), ranks


def _codes(records, text):
    """The ranked document codes for one query text (live scorer, memory)."""
    store = InMemorySkillStore()
    asyncio.run(_populate(store, records))
    hits = asyncio.run(store.search(text, harness.DEPTH))
    return [ID_TO_CODE.get(h.skill.skill_id, h.skill.skill_id) for h in hits]


def _assert_metrics(actual: harness.Metrics, expected: dict, ctx: str) -> None:
    got = actual.as_dict()
    for key, want in expected.items():
        have = got[key]
        have = round(have, 3) if isinstance(have, float) else have
        assert have == want, f"{ctx}: {key} = {have!r}, published {want!r}"


# ---------------------------------------------------------------------------
# 1. Fidelity gate — must pass before any later number is believed.
# ---------------------------------------------------------------------------
class TestFidelityGate:
    """The instrument is sound and the frozen baseline is the genuine artifact."""

    def test_corpus_matches_graded_fixture(self, corpus_records):
        """R-8's first gate: the built corpus is byte-identical to the labels.

        ``verify_corpus_md5`` compares the full ``skill_id`` set and each
        document's ``body_md5``/``body_bytes`` against the committed fixture. A
        drifted corpus would invalidate every metric downstream, so it is checked
        before anything is computed. (MD5 here is a content-identity key, not a
        security digest.)
        """
        corpus.verify_corpus_md5(corpus_records)

    def test_v0_fixture_reproduces_published_baseline(self):
        """The frozen V0 ranks reproduce eval-set §8.1 exactly (33 values).

        This validates the *comparison target*: the fixture captured before R-9
        removed the flags, run through this harness's metric math, must yield the
        published all-flags-off baseline value for value — combined top-1 grade-2
        = **19/38**. It is non-circular: the expected table is transcribed from
        the published artifact the *offline* harness produced, and this *rebuilt*
        harness reproduces it from the frozen ranks. If it drifts, the fixture
        (not the scorer) is wrong and no comparison below is trustworthy.
        """
        by_stratum = harness.metrics_by_stratum(_v0_ranks(), GRADED)
        for stratum, expected in V0_PUBLISHED.items():
            _assert_metrics(by_stratum[stratum], expected, f"V0 {stratum}")
        assert by_stratum["combined"].top1_grade2 == 19

    def test_shipped_scorer_reproduces_measured_candidate(self, corpus_records):
        """The live scorer reproduces the aggregate R-8 selected (24/38).

        R-9 made the four fixes unconditional, so the scorer this harness drives
        through ``store.search()`` on the md5-pinned corpus is the former
        all-flags-on candidate: combined top-1 grade-2 = **24/38**, not the frozen
        V0's 19/38. This is the hard gate on the shipped configuration — it proves
        the flag removal took effect (24, not 19) and that the instrument
        reproduces the measured candidate end to end, prefilter included. The full
        per-stratum aggregate and its divergence from the memo are pinned by
        ``TestShippedV6Discrepancy``.
        """
        by_stratum, _ = _measure(corpus_records)
        assert by_stratum["combined"].top1_grade2 == 24, (
            "the unconditional scorer must reproduce the measured 24/38, not the "
            "frozen V0 19/38 — the flag removal did not take effect"
        )


# ---------------------------------------------------------------------------
# 2. R-1 stratum-A owner recovery — the headline (0/3 frozen → 3/3 live).
# ---------------------------------------------------------------------------
class TestStratumAOwnerRecovery:
    """Identifier-owner recovery at top-1 goes 0/3 → 3/3 (§2.6, spec.md OQ-1).

    Stratum A is ungraded, so the check is objective: does the document that owns
    the identifier the query names (``D13`` = ResetPasswordAdHoc) reach top-1? The
    0/3 baseline is read from the frozen V0 fixture; the 3/3 recovery is measured
    live on the unconditional scorer. The R-8 decomposition (neither R-1 nor R-4
    reaches 3/3 alone) was measured across partial flag configs that no longer
    exist and is recorded in eval-set §8.5, not re-run here.
    """

    def _owner_hits(self, records) -> int:
        return sum(
            1
            for qid in OWNER_QUERIES
            if _codes(records, QUERY_BY_ID[qid]["text"])[0] == OWNER
        )

    def test_shipped_recovers_three_of_three(self, corpus_records):
        """The unconditional scorer recovers the owner on all three queries."""
        assert self._owner_hits(corpus_records) == 3

    def test_v0_baseline_recovered_zero_of_three(self):
        """Frozen baseline: under V0 the owner was never top-1 (``D17`` won all
        three), which is the 0/3 the recovery headline is measured against. The
        owner still sat inside the returned window, so V0's failure was an
        ordering one, not a disappearance."""
        v0 = _v0_ranks()
        assert sum(1 for qid in OWNER_QUERIES if v0[qid][0] == OWNER) == 0
        for qid in OWNER_QUERIES:
            codes = v0[qid]
            assert codes[0] == "D17", f"{qid}: V0 top-1 should be D17"
            assert OWNER in codes[:5], f"{qid}: owner should be in the V0 window"


# ---------------------------------------------------------------------------
# 3. Q63 — the one accepted re-ordering (OQ-4).
# ---------------------------------------------------------------------------
class TestQ63Regression:
    """OQ-4 accepts Q63's re-ordering conditionally: no disappearance."""

    def test_q63_reorders_but_owner_stays_in_window(self, corpus_records):
        """Frozen V0 top-1 ``D18`` (grade 2) → shipped top-1 ``D13`` (grade 1).

        §8.3: severity is mild because ``D18`` falls to **rank 2**, staying inside
        the returned window, so ``R@5(=2)`` is unaffected — a re-ordering, not a
        loss. The gate is that ``D18`` remains present; a disappearance (the
        prefilter dropping it) would fail OQ-4's first condition.
        """
        text = QUERY_BY_ID[Q63]["text"]
        shipped = _codes(corpus_records, text)
        assert _v0_ranks()[Q63][0] == "D18", "V0 top-1 for Q63 is the grade-2 D18"
        assert shipped[0] == "D13", "shipped promotes D13 (grade 1) to top-1"
        assert "D18" in shipped[:5], "D18 must stay inside the returned window"
        assert shipped.index("D18") == 1, "D18 falls to rank 2, not out of view"


# ---------------------------------------------------------------------------
# 4. The V6 discrepancy — published, not hidden (the honest core of R-8).
# ---------------------------------------------------------------------------
class TestShippedV6Discrepancy:
    """The shipped scorer measures 24/38 — below the memo's 27/38 and doc-side 26/38.

    eval-set §8.2 row 2e and its 2026-10-02 annotation publish **V6 = 27/38**
    combined top-1 with **B MRR 0.950** and combined MRR 0.868. The doc-side-split
    rebuild measured **26/38**. The configuration R-9 shipped — R-4 amended to
    split the query only, so the R-5 prefilter is a sound over-approximation and
    R-6 parity holds by construction — measures **24/38**, **B MRR 0.900**,
    combined MRR **0.842**, C top-1 **10/18**, C MRR **0.778**. The widened gap is
    the price of parity: giving up document-side splitting forgoes plain-word →
    CamelCase-title recall (``pod`` no longer matches the title
    ``KubePodNotReady``).

    R-8's rule is explicit: *publish the discrepancy and ship the configuration
    that was actually measured — not the one the memo described.* These tests pin
    the measured numbers and the mechanism, so the difference is a recorded
    finding an operator can review, never a silent edit of the artifact.
    """

    def test_shipped_measured_not_memo(self, corpus_records):
        """Pin the shipped scorer's actual aggregate (differs from §8.2)."""
        by_stratum, _ = _measure(corpus_records)
        combined = by_stratum["combined"]
        assert combined.top1_grade2 == 24, "measured 24/38, not the memo's 27/38"
        assert round(by_stratum["B"].mrr, 3) == 0.900, "B MRR 0.900, not 0.950"
        assert round(combined.mrr, 3) == 0.842, "combined MRR 0.842, not 0.868"
        # Stratum C's MRR is unchanged from the doc-side rebuild (0.778); its
        # top-1 slips 11 -> 10 because the query-only split also drops a C
        # plain-word -> camel-title match. Both are asserted so the discrepancy is
        # quantified, not hidden.
        assert by_stratum["C"].top1_grade2 == 10
        assert round(by_stratum["C"].mrr, 3) == 0.778

    def test_r4_query_only_scope_is_the_gap(self, corpus_records):
        """The mechanism: the unsplit document side costs Q45 its D12 title match.

        Q45 ``pod health check readiness verify running ready conditions`` is owned
        by ``D12`` (``KubePodNotReady``, grade **2**). Under the doc-side split the
        bare query word ``pod`` matched the ``pod`` part Python split out of
        ``KubePodNotReady``, so ``D12`` was top-1. Under the shipped query-only
        split the document side is never split — ``KubePodNotReady`` stays one
        opaque token, byte-identical to ``to_tsvector('simple')`` — so ``pod`` no
        longer matches it and ``D15`` (``samples/health-check-checkservicehealth``,
        grade **0**) is top-1, exactly as it already was under frozen V0. This is
        not an R-1 regression: it is the concrete recall price of
        parity-by-construction. ``D12`` still ranks **2nd**, inside the returned
        window (so R@10 and the null result are unaffected) — a top-1 loss, not a
        disappearance.
        """
        text = QUERY_BY_ID["Q45"]["text"]
        shipped = _codes(corpus_records, text)
        q45 = next(q for q in GRADED if q.id == "Q45")
        assert q45.grades.get("D12", 0) == 2
        assert q45.grades.get("D15", 0) == 0
        # D15 (grade 0) is top-1 both under frozen V0 and on the shipped scorer —
        # the query-only split introduces no *new* Q45 regression.
        assert _v0_ranks()["Q45"][0] == "D15"
        assert shipped[0] == "D15"
        # The grade-2 owner stays at rank 2, inside the window (not lost).
        assert shipped[1] == "D12", "D12 must stay in-window at rank 2"


# ---------------------------------------------------------------------------
# 5. Significance + the coded null-result path.
# ---------------------------------------------------------------------------
class TestSignificance:
    """The pre-registered tests (§8.3): the nDCG@10 bootstrap CI excludes zero
    (the gain is outside the noise band), but the coarser top-1 sign test is
    directional only (7:2, p = 0.18) and does not reach 0.05 at n = 38. Both
    compare the live shipped scorer against the frozen V0 baseline."""

    def test_shipped_ndcg_gain_outside_noise_band(self, corpus_records):
        """Paired bootstrap (seed 20261001, 10k resamples) CI excludes 0.

        Measured V0 → shipped per-query nDCG@10 delta CI is [+0.022, +0.111]; the
        doc-side rebuild was [+0.036, +0.133] and the published §8.3 CI was
        [+0.042, +0.148] for the memo's 27/38 candidate. All three exclude zero,
        so the primary pre-registered verdict ("outside the noise band") survives;
        the interval is lower because query-only splitting forgoes some plain-word
        → CamelCase-title nDCG. This is the significance claim the shipped scorer
        keeps.
        """
        _, shipped = _measure(corpus_records)
        base = harness.per_query_ndcg(_v0_ranks(), GRADED)
        cand = harness.per_query_ndcg(shipped, GRADED)
        lo, hi = harness.paired_bootstrap_ci(base, cand, [q.id for q in GRADED])
        assert lo > 0.0, f"CI lower bound {lo:.4f} must exclude 0"
        assert round(lo, 3) == 0.022 and round(hi, 3) == 0.111

    def test_shipped_top1_sign_test_directional_not_significant(self, corpus_records):
        """Exact two-sided sign test on discordant top-1 pairs: **p = 0.18**, n.s.

        This is the honest cost the shipped scorer accepts on the secondary
        pre-registered test. Measured 7 improved / 2 regressed → **p = 0.1797**,
        which does **not** reach 0.05 — unlike the doc-side rebuild (9/1,
        p = 0.0215) or the memo's candidate (10/1, p = 0.0117). The two
        regressions are Q62 and Q63 (both stratum-B grade-2 → grade-1, both still
        in-window). The top-1 sign test discards magnitude and every rank below 1,
        so at 9 discordant pairs it is under-powered; the primary test — the
        nDCG@10 bootstrap above, which uses the full ranked list — still excludes
        zero. Recorded, not smoothed: the shipped scorer trades top-1 sign-test
        significance for cross-backend parity.
        """
        _, shipped = _measure(corpus_records)
        improved, regressed, _lateral = harness.top1_grade_deltas(
            _v0_ranks(), shipped, GRADED
        )
        assert (improved, regressed) == (7, 2)
        p = harness.sign_test_p((improved, regressed))
        assert round(p, 4) == 0.1797
        assert p >= 0.05, "documented: the top-1 sign test is NOT significant"


class TestNullResult:
    """The pre-registered null result is a coded outcome, not an omission."""

    def test_no_recall_gap_at_depth_10(self, corpus_records):
        """Zero grade-2 documents are absent from the top-10, V0 and shipped.

        §8.1 fact 1 / §8.5 step 3: this is the finding that closes the
        semantic-retrieval backlog row — a vector store is a recall instrument and
        there is no recall to recover, so **no embedding work is authorized**. The
        gate asserts the count is exactly 0 for both the frozen V0 baseline and
        the live shipped scorer.
        """
        _, shipped = _measure(corpus_records)
        for label, ranks in (("V0", _v0_ranks()), ("shipped", shipped)):
            missing = 0
            for q in GRADED:
                top10 = set(ranks[q.id][:10])
                missing += len(q.exactly(2) - top10)
            assert missing == 0, f"{label}: {missing} grade-2 docs fell out of top-10"

    def test_abstention_gap_unchanged_by_shipped_scorer(self, corpus_records):
        """Zero-relevant rate is 4/38 under both frozen V0 and shipped (§8.4).

        No lexical configuration fixes the four confidently-irrelevant answers;
        the abstention gap is structural (a ``score > 0`` scorer cannot say
        "nothing applies") and is a product decision, not a ranking one. Pinning
        it here keeps the null result honest: the shipped scorer improves
        ordering, not abstention.
        """
        v0 = harness.metrics_by_stratum(_v0_ranks(), GRADED)
        shipped, _ = _measure(corpus_records)
        assert v0["combined"].zero_relevant == 4, "V0: zrel != 4"
        assert shipped["combined"].zero_relevant == 4, "shipped: zrel != 4"


# ---------------------------------------------------------------------------
# 6. The deployed Postgres path (Docker; fails loudly without it).
# ---------------------------------------------------------------------------
class TestPostgresPath:
    """R-8's merge gate is measured through Postgres, not the memory upper bound.

    eval-set changelog 2026-10-01 (4): "§8's numbers are a memory-path upper
    bound … the deployed ``PostgresSkillStore`` ranks only the rows
    ``_SEARCH_VECTOR`` admitted." These tests re-check the load-bearing outcomes
    on the real backend so a prefilter that silently drops a row cannot pass.
    """

    def _pg_store(self, url, records):
        store = PostgresSkillStore(url)
        asyncio.run(_populate(store, records))
        return store

    def test_pg_reproduces_shipped_baseline(self, pg_database, corpus_records):
        """The shipped aggregate (24/38) holds on the Postgres backend.

        R-6 parity means the deployed path ranks identically to memory, so the
        unconditional scorer reproduces the same **24/38** through the real
        ``to_tsvector`` prefilter — not the frozen V0 19/38. A prefilter that
        silently dropped a row the scorer ranks above zero would move this number,
        which is exactly the deployment-path fidelity R-8 gates on.
        """
        store = self._pg_store(pg_database, corpus_records)
        ranks = asyncio.run(harness.collect_ranks(store.search, GRADED, ID_TO_CODE))
        by_stratum = harness.metrics_by_stratum(ranks, GRADED)
        assert by_stratum["combined"].top1_grade2 == 24

    def test_pg_owner_recovery_reaches_deployed_path(self, pg_database, corpus_records):
        """R-1's stratum-A gain is reachable on Postgres, not memory-only.

        changelog 2026-10-01 (4) warned the stratum-A recovery (0/3 → 3/3) is
        "precisely the class that would not reach a deployed environment" without
        R-5's migration, because ``skill_id`` was in neither ``_SEARCH_VECTOR`` nor
        the GIN index. With R-5's separator-normalized ``skill_id`` + prefix
        lexemes, Q15 (owner recovered only via the slug) must return ``D13`` top-1
        through the real prefilter.
        """
        store = self._pg_store(pg_database, corpus_records)
        for qid in OWNER_QUERIES:
            hits = asyncio.run(store.search(QUERY_BY_ID[qid]["text"], harness.DEPTH))
            codes = [ID_TO_CODE.get(h.skill.skill_id, h.skill.skill_id) for h in hits]
            assert codes[0] == OWNER, f"{qid}: PG top-1 should be the owner D13"

    def test_pg_q63_owner_stays_in_window(self, pg_database, corpus_records):
        """OQ-4 condition 1 on the deployed path: Q63's D18 does not vanish.

        The accepted re-ordering is only acceptable if the grade-2 document stays
        *returnable*. On Postgres that means the widened prefilter must still admit
        ``D18`` for Q63; a disappearance here (not a re-ordering) fails the gate.
        """
        store = self._pg_store(pg_database, corpus_records)
        hits = asyncio.run(store.search(QUERY_BY_ID[Q63]["text"], harness.DEPTH))
        codes = [ID_TO_CODE.get(h.skill.skill_id, h.skill.skill_id) for h in hits]
        assert "D18" in codes, "the prefilter must not drop D18 for Q63"
