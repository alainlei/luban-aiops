"""Deterministic scorer tests (SPEC-014 R-3; SPEC-066 R-1/R-2/R-3/R-4/R-7).

Weighting must be fixed and explainable (title > tags > body, body occurrences
saturating) and ordering byte-identical across runs (ties by ``skill_id``
ascending).

SPEC-066's four lexical-fidelity fixes are **unconditional** — R-9 removed the
measurement flags that gated them during R-8's re-measurement. ``skill_id`` is a
fourth scored field at ``TAG_WEIGHT`` (R-1); every per-token contribution is
scaled by a corpus-derived IDF (R-2, neutral under ``EMPTY_STATS``); the capped
body term is damped sublinearly by document length (R-3); and the **query** is
CamelCase-split while every document field stays unsplit (R-4), which is what
keeps R-5's prefilter a sound over-approximation and R-6 parity exact.

``ScoreTests``/``RankTests``/``ExcerptTests``/``DeduplicationTests`` assert the
shipped scorer end to end; the per-fix classes are ``CamelCaseTokenizeTests``
(R-4), ``SkillIdScoringTests`` (R-1), ``IdfWeightingTests`` (R-2) and
``LengthNormTests`` (R-3). Where R-3 applies, the expected value is computed from
``_length_norm`` so the test states the formula rather than a magic number.
"""

from __future__ import annotations

import math
import unittest
from datetime import datetime, timezone

from skills_hub.schemas.skill import Skill
from skills_hub.services.scoring import (
    EMPTY_STATS,
    CorpusStats,
    _length_norm,
    compute_stats,
    excerpt,
    rank,
    score,
    tokenize,
    tokenize_query,
)

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)


def _skill(skill_id: str, title: str = "T", tags=None, body: str = "") -> Skill:
    return Skill(
        skill_id=skill_id,
        source_id=skill_id.split("/")[0],
        source_path=f"{skill_id}.md",
        source_ref="local",
        title=title,
        description="summary",
        tags=tags,
        updated_at=NOW,
        body=body,
    )


class ScoreTests(unittest.TestCase):
    """The shipped scorer, unconditional (SPEC-066 R-9 removed the flags).

    Fixtures keep the ``skill_id`` slug off the query token so each assertion
    isolates one field's weight (title 3 > tag 2 > body 1, occurrences
    saturating at 5); where R-3's length norm applies the expected value is
    computed from ``_length_norm`` rather than hard-coded.
    """

    def test_title_match_scores_three(self) -> None:
        skill = _skill("a/troubleshooting", title="Pod Troubleshooting", body="")
        self.assertEqual(score("pod", skill, EMPTY_STATS), 3.0)

    def test_tag_match_scores_two(self) -> None:
        skill = _skill("a/tags", title="Other", tags=["kubernetes"], body="")
        self.assertEqual(score("kubernetes", skill, EMPTY_STATS), 2.0)

    def test_body_occurrences_score_and_saturate(self) -> None:
        # R-3 damps the capped body term by length, so the expected value is the
        # occurrence count (saturating at BODY_OCCURRENCE_CAP=5) times the
        # document's length factor.
        short = _skill("a/three", title="Other", body="pod " * 3)
        self.assertAlmostEqual(
            score("pod", short, EMPTY_STATS), 3.0 * _length_norm(short.body)
        )
        long = _skill("a/long", title="Other", body="pod " * 100)
        self.assertAlmostEqual(
            score("pod", long, EMPTY_STATS), 5.0 * _length_norm(long.body)  # capped
        )

    def test_weights_compose_per_token(self) -> None:
        skill = _skill(
            "a/full",
            title="KubePodNotReady",
            tags=["KubePodNotReady"],
            body="kubepodnotready kubepodnotready",
        )
        # The query splits (R-4) but only the retained whole token matches the
        # unsplit document fields: title 3 + tag 2 + body 2 (x length norm). The
        # slug ``a/full`` shares no token with the query, so R-1 adds nothing.
        expected = 3.0 + 2.0 + 2.0 * _length_norm(skill.body)
        self.assertAlmostEqual(score("KubePodNotReady", skill, EMPTY_STATS), expected)

    def test_zero_when_no_token_matches(self) -> None:
        skill = _skill("a/pod", title="Pod", body="pod")
        self.assertEqual(score("dns", skill, EMPTY_STATS), 0.0)

    def test_empty_query_scores_zero(self) -> None:
        self.assertEqual(score("", _skill("a/pod", title="Pod"), EMPTY_STATS), 0.0)
        self.assertEqual(
            score("!!!", _skill("a/pod", title="Pod"), EMPTY_STATS), 0.0
        )


class RankTests(unittest.TestCase):
    def test_shipped_password_skill_is_discoverable(self) -> None:
        from pathlib import Path
        from skills_hub.services.ingestion import ingest_directory

        root = Path(__file__).resolve().parents[3]
        result = ingest_directory(
            "platform-runbooks", root / "shared/platform-ops/skills/platform-runbooks",
            "local", NOW,
        )
        self.assertEqual(result.rejections, [])
        hits = rank(
            "generate a password", result.records, limit=5, stats=EMPTY_STATS
        )
        skill = next(h.skill for h in hits if h.skill.source_path.endswith("GeneratePassword.md"))
        self.assertEqual(skill.kind, "knowledge")
        self.assertIn("shared/shared-contracts/policies/password-policy.yaml", skill.body)
        self.assertIn('handoff="portal_copy"', skill.body)

    def test_zero_score_records_excluded(self) -> None:
        hits = rank(
            "pod",
            [_skill("a/match", title="Pod"), _skill("a/other", title="Node")],
            limit=5,
            stats=EMPTY_STATS,
        )
        self.assertEqual([h.skill.skill_id for h in hits], ["a/match"])

    def test_ties_break_by_skill_id_ascending(self) -> None:
        # Distinct bodies so R-7's md5(body) de-duplication is a no-op here (the
        # real corpus is duplicate-free); the records still tie on the title
        # match, which is what the ascending skill_id tie-break resolves.
        records = [
            _skill("b/doc", title="Pod", body="beta"),
            _skill("a/doc", title="Pod", body="alpha"),
            _skill("c/doc", title="Pod", body="gamma"),
        ]
        hits = rank("pod", records, limit=5, stats=EMPTY_STATS)
        self.assertEqual(
            [h.skill.skill_id for h in hits], ["a/doc", "b/doc", "c/doc"]
        )

    def test_ranking_is_deterministic_across_input_order(self) -> None:
        # Distinct bodies keep R-7 a no-op so all three field-match shapes
        # survive to be ordered by score (title 3 > tag 2 > body 1).
        records = [
            _skill("a/only-tags", tags=["pod"], body="tags doc"),
            _skill("a/in-title", title="Pod", body="title doc"),
            _skill("a/only-body", body="pod"),
        ]
        forward = [
            h.skill.skill_id
            for h in rank("pod", records, limit=5, stats=EMPTY_STATS)
        ]
        backward = [
            h.skill.skill_id
            for h in rank(
                "pod", list(reversed(records)), limit=5, stats=EMPTY_STATS
            )
        ]
        self.assertEqual(forward, backward)
        self.assertEqual(forward, ["a/in-title", "a/only-tags", "a/only-body"])

    def test_limit_caps_results(self) -> None:
        records = [
            _skill(f"a/doc{i}", title="Pod", body=f"body {i}") for i in range(5)
        ]
        self.assertEqual(
            len(rank("pod", records, limit=2, stats=EMPTY_STATS)), 2
        )


class ExcerptTests(unittest.TestCase):
    def test_excerpt_starts_at_first_body_match(self) -> None:
        skill = _skill(
            "a/pod", body="leading text " + "filler " * 20 + "pod crash details"
        )
        snippet = excerpt("pod", skill)
        self.assertTrue(snippet.startswith("pod crash details"))
        self.assertLessEqual(len(snippet), 401)

    def test_excerpt_bounded_to_cap(self) -> None:
        skill = _skill("a/pod", body="pod" + "x" * 1000)
        self.assertLessEqual(len(excerpt("pod", skill)), 401)

    def test_excerpt_falls_back_to_description(self) -> None:
        skill = _skill("a/pod", title="Pod", body="no match tokens here")
        self.assertEqual(excerpt("pod", skill), "summary")


class CamelCaseTokenizeTests(unittest.TestCase):
    """R-4: position-aware CamelCase tokenization of the **query** side.

    The committed case table is the query-side rule (``tokenize_query``), now
    unconditional. The document side (``tokenize``) never splits — asserted by
    ``test_document_side_is_never_split`` — which is what keeps it byte-identical
    to PostgreSQL's ``to_tsvector('simple')`` lexemes and R-6 parity sound.
    """

    CASE_TABLE = {
        "KubePodNotReady": {"kubepodnotready", "kube", "pod", "not", "ready"},
        "CrashLoopBackOff": {"crashloopbackoff", "crash", "loop", "back", "off"},
        # The two standard boundaries do not fire inside an acronym+number run,
        # so HTTP503 and v0211 stay whole — the letter<->digit boundary is
        # deliberately absent (tasks.md R-4: pin the decision).
        "HTTP503": {"http503"},
        "v0211": {"v0211"},
        "pgBouncer": {"pgbouncer", "pg", "bouncer"},
        "RealPlayer2": {"realplayer2", "real", "player2"},
        # Already-lowercase and digit-only runs are unaffected.
        "pod": {"pod"},
        "503": {"503"},
        "already lowercase text": {"already", "lowercase", "text"},
    }

    def test_case_table(self) -> None:
        for text, expected in self.CASE_TABLE.items():
            with self.subTest(text=text):
                self.assertEqual(set(tokenize_query(text)), expected)

    def test_document_side_is_never_split(self) -> None:
        # The core of R-4: tokenize() — every document field and R-2's df — is
        # the plain [a-z0-9]+ rule, so it stays byte-identical to
        # to_tsvector('simple'); only tokenize_query() splits. This is the single
        # property that makes the R-5 prefilter a sound over-approximation
        # without a SQL tokenizer.
        self.assertEqual(tokenize("KubePodNotReady"), ["kubepodnotready"])
        self.assertEqual(tokenize("HTTP503 v0211"), ["http503", "v0211"])
        self.assertEqual(
            set(tokenize_query("KubePodNotReady")),
            {"kubepodnotready", "kube", "pod", "not", "ready"},
        )

    def test_whole_token_retained_alongside_parts(self) -> None:
        tokens = tokenize_query("KubePodNotReady")
        self.assertIn("kubepodnotready", tokens)
        self.assertIn("kube", tokens)

    def test_single_run_is_not_duplicated(self) -> None:
        # The whole token is admitted only when it differs from its parts, so a
        # run with no internal boundary yields one token, not two — the rule
        # that makes retention non-inflating on the query side.
        self.assertEqual(tokenize_query("pod"), ["pod"])

    def test_query_tokens_deduplicated(self) -> None:
        # "pod pod" emits [pod, pod] across two runs; _query_tokens de-duplicates
        # before the scoring loop, so the title is credited once (3.0, not 6.0).
        skill = _skill("a/x", title="Pod", body="")
        self.assertEqual(score("pod pod", skill, EMPTY_STATS), 3.0)

    def test_document_identifier_is_one_unsplit_body_token(self) -> None:
        # The document side never splits, so a CamelCase identifier in the body is
        # ONE token counted once — not five parts. A query for the whole
        # identifier matches that one occurrence (damped by R-3); a query for a
        # part ("pod") matches nothing (0.0). That 0.0 is the parity fix: there is
        # no split document part for the SQL prefilter to fail to reach, so the
        # grade-0 false positive document-side splitting used to create is gone.
        skill = _skill("a/x", title="Other", body="KubePodNotReady")
        self.assertEqual(tokenize(skill.body), ["kubepodnotready"])
        self.assertAlmostEqual(
            score("kubepodnotready", skill, EMPTY_STATS),
            1.0 * _length_norm(skill.body),
        )
        self.assertEqual(score("pod", skill, EMPTY_STATS), 0.0)

    def test_query_split_is_a_noop_on_camel_free_text(self) -> None:
        # R-4 must not perturb ordinary text: with no CamelCase anywhere the
        # query tokenizer emits exactly the document tokenizer's tokens, so the
        # split adds nothing. (Duplicate-token queries are separately
        # de-duplicated — see test_query_tokens_deduplicated.)
        for text in ("pod", "pod restart", "restart guide", "already lowercase text"):
            with self.subTest(text=text):
                self.assertEqual(tokenize_query(text), tokenize(text))

    def test_query_side_split_is_the_surviving_gain(self) -> None:
        # The win R-4 delivers: a CamelCase alert-name query reaches a runbook
        # written with the plain constituent words, even though NO document field
        # is split to meet it. Querying the unsplit whole identifier matches
        # nothing (0.0); the query-side split turns one dead lookup into three
        # real matches (pod / not / ready), each hitting the title (3.0), the
        # slug (2.0, R-1) and one body occurrence (damped by R-3). Parity-safe
        # because the document tokens matched are ordinary unsplit words that
        # to_tsvector indexes identically.
        skill = _skill(
            "platform-runbooks/pod-not-ready",
            title="Pod Not Ready",
            body="the pod is not ready",
        )
        self.assertEqual(score("kubepodnotready", skill, EMPTY_STATS), 0.0)
        expected = 3.0 * (3.0 + 2.0 + 1.0 * _length_norm(skill.body))
        self.assertAlmostEqual(score("KubePodNotReady", skill, EMPTY_STATS), expected)


class SkillIdScoringTests(unittest.TestCase):
    """R-1: the ``skill_id`` slug is a fourth scored field at ``TAG_WEIGHT``."""

    def test_slug_separators_tokenize_consistently_with_title(self) -> None:
        self.assertEqual(
            set(tokenize("samples/password-reset-resetacmepassword")),
            {"samples", "password", "reset", "resetacmepassword"},
        )

    def test_skill_id_match_scores_at_tag_weight(self) -> None:
        skill = _skill("samples/resetacmepassword", title="Unrelated", body="")
        self.assertEqual(score("resetacmepassword", skill, EMPTY_STATS), 2.0)

    def test_slug_and_title_and_tags_compose(self) -> None:
        # "reset" appears in the slug, the title and a tag: 2 (id) + 3 (title)
        # + 2 (tag) = 7, each field credited once for the shared token. The
        # slug uses a hyphen separator so "reset" is a real token of it (a bare
        # "resetacmepassword" slug would tokenize whole and not contain "reset").
        skill = _skill(
            "samples/password-reset-resetacmepassword",
            title="Reset the account",
            tags=["reset"],
        )
        self.assertEqual(score("reset", skill, EMPTY_STATS), 7.0)


class IdfWeightingTests(unittest.TestCase):
    """R-2: corpus-derived inverse document frequency (no stoplist)."""

    def test_idf_formula(self) -> None:
        stats = CorpusStats(n=10, df={"pod": 4})
        self.assertAlmostEqual(stats.idf("pod"), math.log(11 / 5) + 1.0)

    def test_unseen_token_takes_df_zero(self) -> None:
        stats = CorpusStats(n=10, df={})
        self.assertAlmostEqual(stats.idf("missing"), math.log(11 / 1) + 1.0)

    def test_empty_corpus_is_neutral(self) -> None:
        self.assertEqual(EMPTY_STATS.n, 0)
        self.assertEqual(EMPTY_STATS.idf("anything"), 1.0)

    def test_high_df_token_down_weighted_without_stoplist(self) -> None:
        # "the" in 9 of 10 docs is down-weighted by its own frequency, not by a
        # hand-written list; a rare token outweighs it.
        stats = CorpusStats(n=10, df={"the": 9, "kubepodnotready": 1})
        self.assertLess(stats.idf("the"), stats.idf("kubepodnotready"))

    def test_compute_stats_counts_documents_not_occurrences(self) -> None:
        skills = [
            _skill("a/one", title="pod restart", body="pod pod pod"),
            _skill("a/two", title="node debug", body="pod"),
        ]
        stats = compute_stats(skills)
        self.assertEqual(stats.n, 2)
        self.assertEqual(stats.df["pod"], 2)  # both docs, once each
        self.assertEqual(stats.df["restart"], 1)

    def test_compute_stats_covers_all_four_fields(self) -> None:
        skills = [_skill("samples/resetacme", title="T", tags=["alert"], body="b")]
        stats = compute_stats(skills)
        for token in ("samples", "resetacme", "t", "alert", "b"):
            self.assertIn(token, stats.df)

    def test_idf_scales_score(self) -> None:
        # R-2 is unconditional and the score stays decomposable: supplying real
        # statistics scales the neutral (EMPTY_STATS) score by exactly the
        # token's idf, which is the "why did this rank first?" a reviewer needs.
        skill = _skill("a/one", title="pod", body="")
        stats = CorpusStats(n=10, df={"pod": 4})
        neutral = score("pod", skill, EMPTY_STATS)
        weighted = score("pod", skill, stats)
        self.assertAlmostEqual(weighted, neutral * stats.idf("pod"))

    def test_empty_stats_are_neutral(self) -> None:
        # A store that has not refreshed yet (EMPTY_STATS) scores by plain field
        # weighting, because every idf is the neutral 1.0.
        skill = _skill("a/one", title="pod", body="")
        self.assertEqual(score("pod", skill, EMPTY_STATS), 3.0)


class LengthNormTests(unittest.TestCase):
    """R-3: sublinear body-length normalization (backend-neutral, no state)."""

    def test_factor_in_unit_interval_and_strictly_positive(self) -> None:
        for body in ("", "x", "pod", "x" * 5000, "x" * 100000):
            with self.subTest(length=len(body)):
                factor = _length_norm(body)
                self.assertGreater(factor, 0.0)
                self.assertLessEqual(factor, 1.0)

    def test_empty_body_is_neutral(self) -> None:
        self.assertEqual(_length_norm(""), 1.0)

    def test_longer_body_contributes_strictly_less_at_equal_cap(self) -> None:
        short = _skill("a/s", title="Other", body="pod " * 5)  # 5 occurrences
        long = _skill("a/l", title="Other", body="pod " * 5 + "x" * 5000)
        self.assertGreater(
            score("pod", short, EMPTY_STATS), score("pod", long, EMPTY_STATS)
        )

    def test_expected_value_computed_from_formula(self) -> None:
        body = "pod " * 3  # 3 occurrences, len 12
        skill = _skill("a/x", title="Other", body=body)
        expected = 3.0 * (1.0 / math.log2(2.0 + len(body) / 1000.0))
        self.assertAlmostEqual(score("pod", skill, EMPTY_STATS), expected)

    def test_length_factor_is_independent_of_corpus_state(self) -> None:
        # R-3's factor depends only on the document body, so changing the corpus
        # statistics scales the score by exactly the IDF ratio — the length norm
        # is the common factor that cancels. (IDF, R-2, is the stateful one.)
        skill = _skill("a/x", title="Other", body="pod " * 3)
        stats = CorpusStats(n=999, df={"pod": 500})
        neutral = score("pod", skill, EMPTY_STATS)
        weighted = score("pod", skill, stats)
        self.assertAlmostEqual(
            weighted / neutral, stats.idf("pod") / EMPTY_STATS.idf("pod")
        )


class DeduplicationTests(unittest.TestCase):
    """R-7: md5(body) content de-duplication in ``rank``, before truncation."""

    def test_identical_bodies_collapse_to_lowest_skill_id(self) -> None:
        records = [
            _skill("b/dup", title="Pod", body="identical body"),
            _skill("a/dup", title="Pod", body="identical body"),
        ]
        hits = rank("pod", records, limit=5, stats=EMPTY_STATS)
        self.assertEqual([h.skill.skill_id for h in hits], ["a/dup"])

    def test_dedup_precedes_truncation(self) -> None:
        # A duplicate must not waste a result slot: with limit 3 the three
        # DISTINCT documents are returned, not two distinct plus the duplicate.
        records = [
            _skill("a/top", title="Pod", body="shared body"),
            _skill("z/top-dup", title="Pod", body="shared body"),
            _skill("b/mid", title="Pod", body="other body"),
            _skill("c/low", title="Pod", body="third body"),
        ]
        hits = rank("pod", records, limit=3, stats=EMPTY_STATS)
        ids = [h.skill.skill_id for h in hits]
        self.assertEqual(ids, ["a/top", "b/mid", "c/low"])
        self.assertNotIn("z/top-dup", ids)

    def test_distinct_bodies_are_all_retained(self) -> None:
        records = [
            _skill(f"a/d{i}", title="Pod", body=f"body {i}") for i in range(3)
        ]
        hits = rank("pod", records, limit=5, stats=EMPTY_STATS)
        self.assertEqual(len(hits), 3)

    def test_dedup_is_a_noop_on_a_duplicate_free_corpus(self) -> None:
        # With distinct bodies the ordering is exactly the shipped
        # (-score, skill_id) order — R-7 changes nothing on a clean corpus.
        records = [
            _skill("b/one", title="Pod", body="b"),
            _skill("a/two", title="Pod", body="a"),
        ]
        hits = rank("pod", records, limit=5, stats=EMPTY_STATS)
        self.assertEqual([h.skill.skill_id for h in hits], ["a/two", "b/one"])


if __name__ == "__main__":
    unittest.main()
