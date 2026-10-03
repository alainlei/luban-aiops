"""R-6 enforced cross-backend parity harness (SPEC-066).

SPEC-014 documented a "byte-identical ordering parity test vs in-memory store"
that was **never delivered** (its `tasks.md` line 32 also names `plainto_tsquery`,
which the shipped OR-join proves wrong). OQ-3 resolved to *preserve* that
invariant as written and raise no ADR, so R-6 replaces the claim with a harness
that actually enforces it: the **same** corpus in an `InMemorySkillStore` and a
`PostgresSkillStore` must produce **identical `skill_id` ordering *and* identical
numeric scores**, over the whole committed query set, **with no Postgres-only
carve-out** (spec.md R-6). The invariant holds *by mechanism*: R-4 splits the
**query** only, so every document field stays byte-identical to
`to_tsvector('simple')` and R-5's prefilter is a superset — Python's shared
`rank()` is the sole decider on both backends.

R-6 forbids a fake: a `_fake_connect` returning canned rows cannot exercise the
`to_tsvector` prefilter, and one returning every row would pass vacuously. So the
Postgres side is **real** (conftest's `postgres_server`), provisioned lazily and
**failing loudly** without Docker — it runs in the ordinary suite (`make verify`),
not as a manual step. The memory-determinism half needs no Docker and runs
everywhere.

`CANDIDATE_DIVERGENCE_QUERIES` pins the five queries (Q17, Q19, Q39, Q41, C09)
that diverged under the *original* R-4, which split the **document** side too: a
plain query word then matched a part Python extracted from an identifier (`set`
from `StatefulSet`, `account` from `ServiceAccount`, `name` from `nodeName`) that
`to_tsvector('simple')` kept whole and a prefix term could not reach, so the
prefilter under-admitted (all five rows were grade-0 noise). R-9 made the
query-only split unconditional, closing that gap by construction; the five stay
named here so any regression is attributable to a specific query.
"""

from __future__ import annotations

import asyncio
import random
from collections import defaultdict

from skills_hub.services.skill_store import InMemorySkillStore

# The five queries that diverged under the *original* (document-side-splitting)
# R-4; kept as a regression pin now that the query-only amendment — made
# unconditional at R-9 — closes the gap (see the module docstring). They must
# agree across backends.
CANDIDATE_DIVERGENCE_QUERIES = ("Q17", "Q19", "Q39", "Q41", "C09")


async def _populate(store, records) -> None:
    by_source: dict[str, list] = defaultdict(list)
    for skill in records:
        by_source[skill.source_id].append(skill)
    await store.initialize()
    for source_id in sorted(by_source):
        await store.replace_source(source_id, by_source[source_id])
    await store.refresh_statistics()


def _ranked(store, text: str, limit: int) -> list[tuple[str, float]]:
    """The full ordered ``(skill_id, score)`` list for one query.

    ``limit`` is the whole corpus, so no truncation hides a tail divergence: the
    comparison is over the complete non-zero result, ordering *and* scores.
    """
    hits = asyncio.run(store.search(text, limit))
    return [(h.skill.skill_id, h.score) for h in hits]


def _memory_store(records):
    store = InMemorySkillStore()
    asyncio.run(_populate(store, records))
    return store


# ---------------------------------------------------------------------------
# Memory determinism — no Docker; the reproducibility half of the invariant.
# ---------------------------------------------------------------------------
class TestMemoryDeterminism:
    """The in-memory backend is deterministic, so parity has a stable target."""

    def test_repeated_build_is_identical(self, corpus_records, parity_queries):
        """Two stores built from the same corpus rank every query identically."""
        limit = len(corpus_records)
        first = _memory_store(corpus_records)
        second = _memory_store(corpus_records)
        for query in parity_queries:
            assert _ranked(first, query["text"], limit) == _ranked(
                second, query["text"], limit
            ), f"{query['id']} not reproducible"

    def test_ingestion_order_is_irrelevant(self, corpus_records, parity_queries):
        """Shuffling the ingest order cannot change the ranked output.

        ``rank()`` orders by ``(-score, skill_id)`` and R-7's de-duplication keeps
        the lowest ``skill_id``, so the result is independent of iteration order —
        a precondition for two backends (which load rows in different orders) to
        agree byte-for-byte.
        """
        limit = len(corpus_records)
        shuffled = list(corpus_records)
        random.Random(20261001).shuffle(shuffled)
        ordered = _memory_store(corpus_records)
        scrambled = _memory_store(shuffled)
        for query in parity_queries:
            assert _ranked(ordered, query["text"], limit) == _ranked(
                scrambled, query["text"], limit
            ), f"{query['id']} depends on ingest order"


# ---------------------------------------------------------------------------
# Cross-backend parity — real Postgres; fails loudly without Docker.
# ---------------------------------------------------------------------------
class TestCrossBackendParity:
    """Both backends, same corpus, same queries: identical ordering *and* scores."""

    def test_cross_backend_parity(self, mem_store, pg_store, corpus_records, parity_queries):
        """The preserved R-6 invariant on the shipped (now unconditional) scorer.

        ``mem_store``/``pg_store`` are both built from the same pinned corpus with
        the single shipped configuration. Full equality, no carve-out: every
        query's complete ``(skill_id, score)`` list matches, ordering *and*
        numbers. It holds by mechanism — R-4 splits the query only, so R-5's
        prefilter is a superset and Python's shared ``rank()`` is the sole decider
        on both backends (spec.md R-6).
        """
        limit = len(corpus_records)
        for query in parity_queries:
            memory = _ranked(mem_store, query["text"], limit)
            postgres = _ranked(pg_store, query["text"], limit)
            assert memory == postgres, (
                f"{query['id']} diverged across backends:\n"
                f"  memory  ={memory}\n  postgres={postgres}"
            )

    def test_former_candidate_divergences_now_agree(
        self, mem_store, pg_store, corpus_records, parity_queries
    ):
        """Regression pin: the five pre-amendment divergences now agree.

        Under the *original* R-4 (document-side splitting) these five under-admitted
        a grade-0 noise row on Postgres; the query-only split R-9 made
        unconditional closes that by construction. Naming them keeps any future
        regression attributable to a specific query rather than buried in the
        whole-set equality above.
        """
        by_id = {q["id"]: q for q in parity_queries}
        limit = len(corpus_records)
        for qid in CANDIDATE_DIVERGENCE_QUERIES:
            text = by_id[qid]["text"]
            assert _ranked(mem_store, text, limit) == _ranked(pg_store, text, limit), (
                f"{qid} (a pre-amendment divergence) still differs across backends"
            )
