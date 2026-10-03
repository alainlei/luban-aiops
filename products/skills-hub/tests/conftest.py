"""Shared fixtures for the skills-hub suite (SPEC-066).

Two concerns live here:

* the **pinned retrieval corpus** and **committed query set** that R-6 (parity)
  and R-8 (evaluation) both measure against, rebuilt deterministically offline
  by ``support.corpus``;
* the **real PostgreSQL 16** harness those stages require. R-6 forbids a fake:
  a ``_fake_connect`` returning canned rows cannot exercise the ``to_tsvector``
  prefilter, and a fake returning every row would make the parity harness pass
  vacuously. So the Postgres is real, provisioned by ``support.postgres_infra``.

The ``postgres_server`` fixture is **lazy and session-scoped**: it provisions
only when a test actually requests it (directly or via ``pg_database``), so the
pure-Python majority of the suite still runs without Docker. When a test does
request it and the local Docker toolchain is unavailable, the fixture **fails
loudly** (``pytest.fail``) rather than skipping — R-6 requires the harness to run
in the ordinary suite (``make test`` / ``make verify``), not as a manual step,
and a skip would be the same silent pass the spec forbids. Root ``make verify``
already requires Docker (SPEC-063's ``execution-failure-test``), so this adds no
new class of prerequisite to the gate.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

import pytest

from skills_hub.services.skill_store import InMemorySkillStore, PostgresSkillStore
from support import corpus as corpus_support
from support.postgres_infra import DisposablePostgres, PrerequisiteError


@pytest.fixture(scope="session")
def corpus_records():
    """The pinned 18-document corpus, built once per session."""
    return corpus_support.build_corpus()


@pytest.fixture(scope="session")
def parity_queries():
    """The committed R-6 query set: 63-pool ∪ 18 stratum-C (81 distinct)."""
    return corpus_support.load_queries()


@pytest.fixture(scope="session")
def postgres_server():
    """A disposable real PostgreSQL 16, provisioned lazily, torn down at exit.

    ``DisposablePostgres.start()`` already cleans itself up on any failure, so
    only the loud ``PrerequisiteError`` → ``pytest.fail`` translation is needed
    here; any other startup error propagates as a red fixture (never a skip).
    """
    server = DisposablePostgres()
    try:
        server.start()
    except PrerequisiteError as exc:
        pytest.fail(
            "the SPEC-066 retrieval tests require a local Docker PostgreSQL 16 "
            "and run in the ordinary suite by design (not a manual step); the "
            f"Docker prerequisite is unavailable: {exc}",
            pytrace=False,
        )
    try:
        yield server
    finally:
        server.close()


@pytest.fixture
def pg_database(postgres_server):
    """A fresh, uniquely-named database for one test, dropped afterwards."""
    from uuid import uuid4

    name = f"spec066_{uuid4().hex}"
    url = postgres_server.create_database(name)
    try:
        yield url
    finally:
        postgres_server.drop_database(name)


async def _populate(store, records) -> None:
    """Initialize ``store``, load ``records`` per source, refresh statistics.

    Shared by both backends so the parity harness loads them identically. The
    ``refresh_statistics`` pass is what makes R-2's IDF backend-independent: it
    is a full-catalog Python computation persisted per backend, so both derive
    the same ``df`` from the same population.
    """
    by_source: dict[str, list] = defaultdict(list)
    for skill in records:
        by_source[skill.source_id].append(skill)
    await store.initialize()
    for source_id in sorted(by_source):
        await store.replace_source(source_id, by_source[source_id])
    await store.refresh_statistics()


@pytest.fixture
def mem_store(corpus_records):
    """An in-memory store loaded with the pinned corpus."""
    store = InMemorySkillStore()
    asyncio.run(_populate(store, corpus_records))
    return store


@pytest.fixture
def pg_store(corpus_records, pg_database):
    """A real-Postgres store loaded with the same pinned corpus."""
    store = PostgresSkillStore(pg_database)
    asyncio.run(_populate(store, corpus_records))
    return store
