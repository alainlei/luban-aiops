"""R-5 prefilter/index invariants (SPEC-066).

R-5 widens the Postgres candidate prefilter so R-1's ``skill_id`` scoring and
R-4's CamelCase reach are actually *reachable* on the deployed backend, and it
does so under a versioned ``idx_skills_search_v2`` migration that retains
SPEC-014's ``idx_skills_search`` for one release. Two layers of guarantee live
here:

* **Static expression/DDL invariants** (``TestPrefilterExpression``) run
  everywhere, no Docker. They pin the properties the plan resolved by argument
  and Stage-0 measurement: the GIN index expression and ``_SEARCH_VECTOR``'s
  tsvector arm are the *same* string; ``skill_id`` is covered and
  separator-normalized; ``tags`` stay out of the index (``array_to_string`` is
  STABLE, not IMMUTABLE); the v1 index is retained; and there is **no**
  ``CREATE FUNCTION``, **no** ``CONCURRENTLY``, **no** ``plainto_tsquery``.

* **Real-Postgres behaviour** (``TestPrefilterReachability`` /
  ``TestPrefilterMigration`` / ``TestPrefilterMeasurements``) needs Docker and
  fails loudly without it (conftest's ``postgres_server``), because the plan is
  explicit that **expression equality alone is not a sufficient gate**: the
  falsified plain-concatenation expression is identical in both places yet
  matches 0 rows. So a reachability assertion goes with the equality — a
  slug-only match and a mid-CamelCase partial identifier must actually return
  rows from Postgres — and the over-approximation invariant (the prefilter never
  under-admits a row the scorer ranks above zero) is enforced here, where it is
  observable, as R-4's regression guard.

The query-construction half (each token ORs its exact **and** ``token:*`` prefix
form; the OR-join is kept; ``plainto_tsquery`` is not used) is already asserted
against a fake driver in ``test_skill_store.py`` and is not duplicated here.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from collections import defaultdict

import pytest

from skills_hub.services import scoring
from skills_hub.services.skill_store import (
    InMemorySkillStore,
    PostgresSkillStore,
    _DDL,
    _SEARCH_TSVECTOR,
    _SEARCH_VECTOR,
)

# The tool-gateway's REQUEST_TIMEOUT_SECONDS (spec.md R-5): the end-to-end
# Postgres search p95 must stay inside it.
GATEWAY_TIMEOUT_SECONDS = 10.0

# Stage-0's concrete reach example, measured on live postgres-0 (16.14):
# to_tsvector('simple', 'KubePodNotReady') is the single lexeme
# 'kubepodnotready', so a bare 'kubepod' matches 0 rows while 'kubepod:*'
# reaches it. The corpus is md5-pinned (support.corpus.verify_corpus_md5), so
# this stays deterministic.
PARTIAL_IDENTIFIER = "kubepod"


async def _populate(store, records) -> None:
    by_source: dict[str, list] = defaultdict(list)
    for skill in records:
        by_source[skill.source_id].append(skill)
    await store.initialize()
    for source_id in sorted(by_source):
        await store.replace_source(source_id, by_source[source_id])
    await store.refresh_statistics()


async def _fetchall(store, sql, params=None):
    async with store._connect() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


async def _scalar(store, sql, params=None):
    rows = await _fetchall(store, sql, params)
    return rows[0][0] if rows else None


def _ddl_code() -> str:
    """``_DDL`` with SQL line comments stripped and upper-cased.

    The DDL's comments *name* the constructs it deliberately avoids (they record
    why ``CONCURRENTLY`` is not used), so a keyword assertion must test the
    executable statements rather than the prose that explains them. ``_DDL`` has
    no ``--`` inside any string literal, so line-comment stripping is exact.
    """
    return re.sub(r"--[^\n]*", "", _DDL).upper()


async def _pg_admitted(store, text: str) -> set[str]:
    """The skill_ids the prefilter admits for ``text`` (before Python re-ranks).

    Mirrors ``PostgresSkillStore.search``'s candidate selection exactly — same
    ``_SEARCH_VECTOR``, same ``tokenize_query`` token set, same ``token | token:*``
    OR-join — so the result is the prefilter's own output, not the final ranked
    list. Uses ``tokenize_query`` (not the document-side ``tokenize``) because
    that is what ``search`` builds the tsquery from under R-4 (amended).
    """
    tokens = scoring.tokenize_query(text)
    if not tokens:
        return set()
    query = " | ".join(f"{token} | {token}:*" for token in tokens)
    rows = await _fetchall(
        store, f"SELECT skill_id FROM skills WHERE {_SEARCH_VECTOR}", {"query": query}
    )
    return {row[0] for row in rows}


def _slug_only_case(records) -> tuple[str, str]:
    """Derive a ``(token, skill_id)`` whose only overlap is the slug.

    A token that appears in some record's ``skill_id`` but in **no** record's
    title/body/tags proves the prefilter reaches ``skill_id`` on its own — the
    plan's named reachability assertion. Derived from the corpus rather than
    hardcoded so a drifted source tree fails loudly instead of passing a stale
    example. Uses shipped (non-CamelCase-splitting) tokenization so the token is
    a whole slug part.
    """
    def words(text: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", text.lower()))

    body_words: set[str] = set()
    for skill in records:
        body_words |= words(skill.title) | words(skill.body)
        body_words |= words(" ".join(skill.tags or []))
    for skill in sorted(records, key=lambda s: s.skill_id):
        for token in sorted(words(skill.skill_id)):
            if token not in body_words:
                return token, skill.skill_id
    pytest.fail(
        "no slug-only token in the pinned corpus — cannot exercise skill_id "
        "prefilter reachability (the source tree drifted)"
    )


# ---------------------------------------------------------------------------
# Static expression / DDL invariants — no Docker.
# ---------------------------------------------------------------------------
class TestPrefilterExpression:
    """The prefilter and index expressions, pinned by string/DDL inspection."""

    def test_gin_v2_expression_equals_search_vector_tsvector(self):
        """The v2 GIN expression and ``_SEARCH_VECTOR``'s tsvector arm are one
        string, so the index cannot silently stop being used (spec.md R-5)."""
        match = re.search(
            r"idx_skills_search_v2\s+ON skills USING GIN \(\s*(.+?)\s*\)\s*;",
            _DDL,
            re.DOTALL,
        )
        assert match, "idx_skills_search_v2 GIN expression not found in _DDL"
        assert match.group(1) == _SEARCH_TSVECTOR
        # The prefilter's first arm is the identical expression, so the index
        # applies to it. (Equality alone is not sufficient — see the
        # reachability tests — but it is necessary.)
        assert _SEARCH_TSVECTOR in _SEARCH_VECTOR

    def test_skill_id_covered_and_separator_normalized(self):
        """``skill_id`` joins the covered columns, ``/`` and ``-`` normalized to
        spaces so the parser does not emit one opaque ``file`` lexeme (tokid 19)
        that matches 0 rows (spec.md R-5, Stage-0 falsification)."""
        assert "skill_id" in _SEARCH_TSVECTOR
        assert "replace(replace(skill_id, '/', ' '), '-', ' ')" in _SEARCH_TSVECTOR

    def test_tags_stay_out_of_the_index_expression(self):
        """``array_to_string``/``array_out`` are STABLE, not IMMUTABLE, so tags
        cannot join an index expression; they stay in the prefilter's OR arm."""
        assert "tags" not in _SEARCH_TSVECTOR
        assert "array_to_string(tags" in _SEARCH_VECTOR

    def test_v1_index_retained_v2_present(self):
        """``idx_skills_search`` is retained one release (rollback is a plain
        code revert with an index still present) and ``idx_skills_search_v2`` is
        created on the new expression — never a window without an index."""
        assert "CREATE INDEX IF NOT EXISTS idx_skills_search\n" in _DDL
        assert "to_tsvector('simple', title || ' ' || body)" in _DDL
        assert "CREATE INDEX IF NOT EXISTS idx_skills_search_v2\n" in _DDL

    def test_corpus_stats_table_present(self):
        """R-2's persisted IDF snapshot table ships in the same idempotent DDL."""
        assert "CREATE TABLE IF NOT EXISTS skills_corpus_stats" in _DDL

    def test_no_sql_function_no_concurrently_no_plainto(self):
        """OQ-5 resolved: Python stays the single tokenizer (no user-defined SQL
        function); ``CONCURRENTLY`` cannot run in the ``autocommit=False`` DDL
        transaction; ``plainto_tsquery`` would AND the words and drop partials.
        Asserted against the comment-stripped DDL, since the comments name these
        constructs to record why they are avoided."""
        code = _ddl_code()
        assert "CREATE FUNCTION" not in code
        assert "CREATE OR REPLACE FUNCTION" not in code
        assert "CONCURRENTLY" not in code
        assert "PLAINTO_TSQUERY" not in code
        assert "plainto_tsquery" not in _SEARCH_VECTOR


# ---------------------------------------------------------------------------
# Real-Postgres reachability — Docker; the gate equality alone cannot provide.
# ---------------------------------------------------------------------------
class TestPrefilterReachability:
    """The prefilter actually reaches skill_id and CamelCase parts on PG 16."""

    def test_partial_identifier_reaches_via_prefix(self, pg_store):
        """Stage-0's live measurement, asserted: a mid-CamelCase partial
        identifier is one opaque lexeme to ``to_tsvector('simple')``, so a bare
        exact term matches 0 rows while the ``:*`` prefix form reaches it.
        Pure SQL against the indexed expression — independent of the scorer."""
        bare = asyncio.run(
            _scalar(
                pg_store,
                f"SELECT count(*) FROM skills "
                f"WHERE {_SEARCH_TSVECTOR} @@ to_tsquery('simple', %(q)s)",
                {"q": PARTIAL_IDENTIFIER},
            )
        )
        prefix = asyncio.run(
            _scalar(
                pg_store,
                f"SELECT count(*) FROM skills "
                f"WHERE {_SEARCH_TSVECTOR} @@ to_tsquery('simple', %(q)s)",
                {"q": f"{PARTIAL_IDENTIFIER}:*"},
            )
        )
        assert bare == 0, f"bare {PARTIAL_IDENTIFIER!r} should match no lexeme"
        assert prefix >= 1, f"{PARTIAL_IDENTIFIER}:* should reach the identifier"

    def test_slug_only_match_returns_row(self, pg_database, corpus_records):
        """A query whose only overlap is ``skill_id`` returns the owning row on
        Postgres *and* matches in-memory — R-1 ships only because R-5 reaches
        the slug (plan.md R-5: "equality alone is not a sufficient gate"). The
        slug is a fourth scored field unconditionally (R-9), so the R-1↔R-5
        dependency is exercised on the shipped scorer with no flag scaffolding."""
        token, owner = _slug_only_case(corpus_records)
        pg = PostgresSkillStore(pg_database)
        asyncio.run(_populate(pg, corpus_records))
        mem = InMemorySkillStore()
        asyncio.run(_populate(mem, corpus_records))
        pg_ids = [h.skill.skill_id for h in asyncio.run(pg.search(token, 10))]
        mem_ids = [h.skill.skill_id for h in asyncio.run(mem.search(token, 10))]
        assert owner in pg_ids, (
            f"slug-only token {token!r} did not reach its owner {owner!r} on PG"
        )
        assert pg_ids == mem_ids, (
            f"slug-only query {token!r} diverged across backends: "
            f"pg={pg_ids} mem={mem_ids}"
        )

    def test_prefilter_over_approximates_scorer(
        self, pg_store, mem_store, corpus_records, parity_queries
    ):
        """R-5's core invariant / R-4's regression guard: on the shipped scorer
        the prefilter never under-admits a row the scorer ranks above zero, for
        any committed query. Over-admission is invisible (Python re-ranks);
        under-admission is a silent recall bug — this is where it is observable.
        ``pg_store``/``mem_store`` are built with the shipped (unconditional)
        scorer."""
        limit = len(corpus_records)
        for query in parity_queries:
            positive = {
                h.skill.skill_id
                for h in asyncio.run(mem_store.search(query["text"], limit))
            }
            admitted = asyncio.run(_pg_admitted(pg_store, query["text"]))
            assert positive <= admitted, (
                f"{query['id']}: prefilter under-admitted "
                f"{sorted(positive - admitted)}"
            )


# ---------------------------------------------------------------------------
# Real-Postgres migration — Docker.
# ---------------------------------------------------------------------------
class TestPrefilterMigration:
    """The versioned index migration on a real PostgreSQL 16."""

    async def _indexes(self, store) -> set[str]:
        rows = await _fetchall(
            store,
            "SELECT indexname FROM pg_indexes WHERE tablename = 'skills'",
        )
        return {row[0] for row in rows}

    def test_both_search_indexes_present(self, pg_store):
        """v1 retained + v2 created: never a window without an index, and a
        rollback stays a plain code revert because v1 still exists."""
        present = asyncio.run(self._indexes(pg_store))
        assert {"idx_skills_search", "idx_skills_search_v2"} <= present

    def test_migration_is_idempotent(self, pg_database, corpus_records):
        """Re-running ``initialize`` (all ``IF NOT EXISTS``) is a safe no-op:
        both indexes survive and search still works."""
        store = PostgresSkillStore(pg_database)
        asyncio.run(_populate(store, corpus_records))
        asyncio.run(store.initialize())  # second DDL pass
        asyncio.run(store.initialize())  # third, for good measure
        present = asyncio.run(self._indexes(store))
        assert {"idx_skills_search", "idx_skills_search_v2"} <= present
        assert asyncio.run(store.count()) == len(corpus_records)


# ---------------------------------------------------------------------------
# Real-Postgres measurements — Docker; the R-5 delivery-note figures.
# ---------------------------------------------------------------------------
class TestPrefilterMeasurements:
    """Index size and end-to-end search latency, measured on the PG path.

    These are the figures spec.md R-5 requires *recorded* (index size before/
    after; latency p95 end to end, not the offline pure-Python number). They are
    printed so the ``make verify`` log captures them, and bounded so a regression
    fails loudly. A wedged local Docker daemon blocks the run — the numbers are
    then pending a Docker-capable environment, not fabricated.
    """

    def test_index_size_is_kilobytes_at_catalog_scale(self, pg_store):
        """At 18 rows both GIN indexes are kilobytes, so the shared 1 Gi PVC
        blast radius is not a blocker (spec.md R-5). Measured, not assumed."""
        v1 = asyncio.run(
            _scalar(pg_store, "SELECT pg_relation_size('idx_skills_search')")
        )
        v2 = asyncio.run(
            _scalar(pg_store, "SELECT pg_relation_size('idx_skills_search_v2')")
        )
        print(f"\n[R-5 index size] idx_skills_search={v1}B idx_skills_search_v2={v2}B")
        assert v1 > 0 and v2 > 0
        # Kilobytes at catalog scale; 1 MiB is a generous ceiling that still
        # fails loudly if the expression ever indexes something unexpected.
        assert v2 < 1024 * 1024, f"idx_skills_search_v2 unexpectedly large: {v2}B"

    def test_search_latency_p95_within_gateway_timeout(self, pg_store, parity_queries):
        """End-to-end p95 across the committed query set stays inside the
        tool-gateway's 10.0 s REQUEST_TIMEOUT_SECONDS (spec.md R-5)."""
        latencies: list[float] = []
        for query in parity_queries:
            start = time.perf_counter()
            asyncio.run(pg_store.search(query["text"], 10))
            latencies.append(time.perf_counter() - start)
        latencies.sort()
        p95 = latencies[math.ceil(0.95 * len(latencies)) - 1]
        p50 = latencies[math.ceil(0.50 * len(latencies)) - 1]
        print(
            f"\n[R-5 latency] n={len(latencies)} p50={p50 * 1000:.3f}ms "
            f"p95={p95 * 1000:.3f}ms (end to end, Postgres path)"
        )
        assert p95 < GATEWAY_TIMEOUT_SECONDS, (
            f"search p95 {p95:.3f}s exceeds the gateway timeout "
            f"{GATEWAY_TIMEOUT_SECONDS}s"
        )
