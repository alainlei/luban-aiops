"""Skill store strategy (SPEC-014 R-2/R-3, SPEC-013 strategy-pattern precedent).

``build_skill_store`` selects the backend from ``SKILLS_STORE_BACKEND``:
``memory`` for tests/dev, ``postgres`` for deployed environments. Records
carry ``source_id`` so per-source replacement is exact, and both backends
delegate ranking to the shared scorer so ordering is byte-identical.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Protocol, Sequence

from skills_hub.core.config import SkillsSettings
from skills_hub.schemas.skill import Skill
from skills_hub.services.scoring import (
    EMPTY_STATS,
    CorpusStats,
    SearchHit,
    compute_stats,
    rank,
    tokenize_query,
)

LOGGER = logging.getLogger(__name__)


class StoreError(Exception):
    """Raised when a store operation cannot be completed."""


def _tag_matches(skill: Skill, tag: str) -> bool:
    return any(t.lower() == tag.lower() for t in skill.tags or [])


class SkillStore(Protocol):
    """Backend contract shared by the in-memory and PostgreSQL stores."""

    async def initialize(self) -> None: ...

    async def replace_source(
        self, source_id: str, records: Sequence[Skill]
    ) -> int: ...

    async def prune_sources(self, source_ids: Sequence[str]) -> int:
        """Drop records whose source is no longer configured; return the
        number of removed records."""
        ...

    async def get(self, skill_id: str) -> Skill | None: ...

    async def list(
        self,
        offset: int,
        limit: int,
        source: str | None = None,
        tag: str | None = None,
    ) -> tuple[list[Skill], int]: ...

    async def search(
        self,
        query: str,
        limit: int,
        source: str | None = None,
        tag: str | None = None,
    ) -> list[SearchHit]: ...

    async def refresh_statistics(self) -> None:
        """Recompute the corpus statistics (SPEC-066 R-2 IDF ``df``) over the
        whole catalog and persist them. Called after each successful
        ``replace_source`` so the shared scorer's weighting tracks the
        population; ``df`` is global, so a per-source swap refreshes all of
        it. Bounded staleness: it rides the sync cycle, so ``df`` lags a
        catalog change by at most one sync interval."""
        ...

    async def count(self) -> int: ...

    async def ready(self) -> bool: ...

    async def close(self) -> None: ...


# --- In-memory store (tests / dev) -------------------------------------------


class InMemorySkillStore:
    """Per-source snapshot map; loses its index on restart (dev/test only).

    ``replace_source`` builds the new snapshot map first and swaps the
    reference in one assignment — readers always see a complete slice.
    """

    def __init__(self) -> None:
        self._by_source: dict[str, list[Skill]] = {}
        # SPEC-066 R-2: the corpus statistics (IDF ``df``) the shared scorer
        # weights by. Neutral (``EMPTY_STATS`` -> idf 1.0) until
        # ``refresh_statistics`` runs, so a store that has not refreshed yet
        # scores exactly as the shipped scorer does.
        self._stats: CorpusStats = EMPTY_STATS

    async def initialize(self) -> None:
        return None

    async def replace_source(
        self, source_id: str, records: Sequence[Skill]
    ) -> int:
        snapshot = {**self._by_source, source_id: list(records)}
        self._by_source = snapshot
        return len(records)

    async def prune_sources(self, source_ids: Sequence[str]) -> int:
        keep = set(source_ids)
        removed = sum(
            len(records)
            for source_id, records in self._by_source.items()
            if source_id not in keep
        )
        self._by_source = {
            source_id: records
            for source_id, records in self._by_source.items()
            if source_id in keep
        }
        return removed

    def _all_records(
        self, source: str | None = None, tag: str | None = None
    ) -> list[Skill]:
        records: list[Skill] = []
        for source_id in sorted(self._by_source):
            if source and source_id != source:
                continue
            for skill in self._by_source[source_id]:
                if tag and not _tag_matches(skill, tag):
                    continue
                records.append(skill)
        return records

    async def get(self, skill_id: str) -> Skill | None:
        source_id, _, _ = skill_id.partition("/")
        for skill in self._by_source.get(source_id, []):
            if skill.skill_id == skill_id:
                return skill
        return None

    async def list(
        self,
        offset: int,
        limit: int,
        source: str | None = None,
        tag: str | None = None,
    ) -> tuple[list[Skill], int]:
        records = self._all_records(source, tag)
        records.sort(key=lambda skill: skill.skill_id)
        return records[offset : offset + limit], len(records)

    async def search(
        self,
        query: str,
        limit: int,
        source: str | None = None,
        tag: str | None = None,
    ) -> list[SearchHit]:
        return rank(query, self._all_records(source, tag), limit, self._stats)

    async def refresh_statistics(self) -> None:
        # SPEC-066 R-2: a full-catalog pass with the scorer's own
        # ``tokenize()``/``compute_stats``, so ``df`` is global (never
        # per-source) and both backends derive the identical statistic from the
        # identical population — the numeric half of the R-6 parity claim.
        self._stats = compute_stats(self._all_records())

    async def count(self) -> int:
        return sum(len(records) for records in self._by_source.values())

    async def ready(self) -> bool:
        return True

    async def close(self) -> None:
        return None


# --- PostgreSQL store (deployed environments) --------------------------------

# SPEC-066 R-5: the single tsvector expression shared **verbatim** by the GIN
# index (``idx_skills_search_v2``) and the ``_SEARCH_VECTOR`` prefilter, so the
# two cannot drift and the index stays usable (a test asserts the equality, but
# sharing one constant makes drift impossible by construction). ``skill_id``
# joins the covered columns, separator-normalized (``/`` and ``-`` -> space)
# because the default parser otherwise types a slash-containing slug as one
# opaque ``file`` lexeme (tokid 19) that matches **0 rows**; ``replace`` is
# IMMUTABLE (``provolatile = i``), so this stays a legal expression index.
# ``tags`` stay out — ``array_to_string``/``array_out`` are STABLE, not
# IMMUTABLE, fine in a filter but not in an index expression.
_SEARCH_TSVECTOR = (
    "to_tsvector('simple', "
    "replace(replace(skill_id, '/', ' '), '-', ' ') "
    "|| ' ' || title || ' ' || body)"
)

_DDL = f"""
CREATE TABLE IF NOT EXISTS skills (
    skill_id    TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_ref  TEXT NOT NULL,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    tags        TEXT[],
    version     TEXT,
    source_url  TEXT,
    updated_at  TIMESTAMPTZ NOT NULL,
    body        TEXT NOT NULL,
    web_target  TEXT,
    risk_class  TEXT,
    flow_intent TEXT,
    kind        TEXT,
    steps       JSONB,
    sub_skills  JSONB
);
-- SPEC-049 R-3: web-check declaration columns; the idempotent ALTERs
-- migrate tables created before 0.31.0 (CREATE TABLE IF NOT EXISTS never
-- adds columns to an existing table).
ALTER TABLE skills ADD COLUMN IF NOT EXISTS web_target TEXT;
ALTER TABLE skills ADD COLUMN IF NOT EXISTS risk_class TEXT;
-- SPEC-053 R-1: optional card-level flow intent; idempotent ALTER migrates
-- tables created before it existed (existing rows get NULL -> omitted).
ALTER TABLE skills ADD COLUMN IF NOT EXISTS flow_intent TEXT;
-- SPEC-055 R-3: executable-flow class (Skill v2). ``kind`` discriminates the
-- class and ``steps`` holds the ordered replay list; both idempotent ALTERs
-- migrate tables created before them, and existing rows get NULL — a
-- knowledge skill with no replay list, i.e. exactly the v1 shape.
ALTER TABLE skills ADD COLUMN IF NOT EXISTS kind TEXT;
ALTER TABLE skills ADD COLUMN IF NOT EXISTS steps JSONB;
-- SPEC-057 R-1: composition class (Skill v3). ``sub_skills`` holds the
-- ordered sub-skill reference list; the idempotent ALTER migrates tables
-- created before it, and existing rows get NULL — a knowledge/executable_flow
-- skill with no reference list, i.e. exactly the pre-v3 shape.
ALTER TABLE skills ADD COLUMN IF NOT EXISTS sub_skills JSONB;
CREATE INDEX IF NOT EXISTS idx_skills_source_id
    ON skills (source_id);
-- SPEC-066 R-2: persisted corpus statistics for IDF weighting. One snapshot
-- row (id = 1) holds the document count ``n`` and the ``df`` map as JSONB,
-- written by ``refresh_statistics`` at sync time and read back at
-- ``initialize`` so a restarted replica scores against the last-synced
-- population instead of a neutral empty snapshot until the next refresh.
CREATE TABLE IF NOT EXISTS skills_corpus_stats (
    id      SMALLINT PRIMARY KEY,
    n       INTEGER NOT NULL,
    df      JSONB NOT NULL
);
-- The GIN expression must only use IMMUTABLE functions; array_to_string /
-- array_out are STABLE in PostgreSQL, so tags stay out of the index and are
-- pre-filtered at query time instead (negligible at skill-catalog scale).
-- SPEC-014's original index, retained one release so a rollback is a plain
-- code revert with an index still present; dropped the release after v2 ships.
CREATE INDEX IF NOT EXISTS idx_skills_search
    ON skills USING GIN (
        to_tsvector('simple', title || ' ' || body)
    );
-- SPEC-066 R-5: the widened prefilter index, on the shared ``_SEARCH_TSVECTOR``
-- expression (``skill_id`` covered + separator-normalized). Versioned name
-- because ``CREATE INDEX IF NOT EXISTS`` matches on *name*: reusing
-- ``idx_skills_search`` under a changed expression would silently keep the old
-- index and leave the new expression unindexed. Plain ``CREATE INDEX`` (not
-- CONCURRENTLY): ``_DDL`` runs as one multi-statement string on an
-- ``autocommit=False`` connection committed afterwards, and CONCURRENTLY cannot
-- run inside a transaction block; at catalog scale a plain build is
-- milliseconds.
CREATE INDEX IF NOT EXISTS idx_skills_search_v2
    ON skills USING GIN (
        {_SEARCH_TSVECTOR}
    );
"""

_INSERT = """
INSERT INTO skills (
    skill_id, source_id, source_path, source_ref, title, description,
    tags, version, source_url, updated_at, body, web_target, risk_class,
    flow_intent, kind, steps, sub_skills
) VALUES (
    %(skill_id)s, %(source_id)s, %(source_path)s, %(source_ref)s,
    %(title)s, %(description)s, %(tags)s, %(version)s, %(source_url)s,
    %(updated_at)s, %(body)s, %(web_target)s, %(risk_class)s,
    %(flow_intent)s, %(kind)s, %(steps)s, %(sub_skills)s
)
ON CONFLICT (skill_id) DO UPDATE SET
    source_path = EXCLUDED.source_path,
    source_ref = EXCLUDED.source_ref,
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    tags = EXCLUDED.tags,
    version = EXCLUDED.version,
    source_url = EXCLUDED.source_url,
    updated_at = EXCLUDED.updated_at,
    body = EXCLUDED.body,
    web_target = EXCLUDED.web_target,
    risk_class = EXCLUDED.risk_class,
    flow_intent = EXCLUDED.flow_intent,
    kind = EXCLUDED.kind,
    steps = EXCLUDED.steps,
    sub_skills = EXCLUDED.sub_skills
"""

_ROW_COLUMNS = (
    "skill_id, source_id, source_path, source_ref, title, description, "
    "tags, version, source_url, updated_at, body, web_target, risk_class, "
    "flow_intent, kind, steps, sub_skills"
)

# The tsvector half is ``_SEARCH_TSVECTOR`` — the *same* expression
# idx_skills_search_v2 indexes — so the GIN index can apply; the tags branch
# keeps tag-only matches in the candidate set (tags cannot join the index
# expression: array_to_string/array_out are STABLE, not IMMUTABLE, in
# PostgreSQL — fine in a filter, not in an index).
# The caller OR-joins the query lexemes: the prefilter must keep every
# record the shared scorer could rank above zero (per-token OR scoring).
# plainto_tsquery would AND the words instead and silently drop partial
# matches ("kubernetes incident" finding nothing lacking both words).
_SEARCH_VECTOR = (
    f"({_SEARCH_TSVECTOR} "
    "@@ to_tsquery('simple', %(query)s) "
    "OR to_tsvector('simple', coalesce(array_to_string(tags, ' '), '')) "
    "@@ to_tsquery('simple', %(query)s))"
)

ConnectFactory = Callable[[], AsyncIterator[Any]]


def _row_to_skill(row: dict[str, Any]) -> Skill:
    # ``steps`` comes back from JSONB as a Python list; the isinstance guard
    # keeps a NULL column (and anything a driver hands back un-decoded) on the
    # knowledge-skill path instead of raising inside the read.
    steps = row["steps"]
    # ``sub_skills`` (SPEC-057 R-1) is the same JSONB shape for a composition's
    # reference list; the identical guard keeps a NULL column (a
    # knowledge/executable_flow skill) omitted rather than raising.
    sub_skills = row["sub_skills"]
    return Skill(
        skill_id=row["skill_id"],
        source_id=row["source_id"],
        source_path=row["source_path"],
        source_ref=row["source_ref"],
        title=row["title"],
        description=row["description"],
        tags=list(row["tags"]) if row["tags"] is not None else None,
        version=row["version"],
        source_url=row["source_url"],
        updated_at=row["updated_at"],
        body=row["body"],
        web_target=row["web_target"],
        risk_class=row["risk_class"],
        flow_intent=row["flow_intent"],
        kind=row["kind"],
        steps=steps if isinstance(steps, list) else None,
        sub_skills=sub_skills if isinstance(sub_skills, list) else None,
    )


def _row_names() -> tuple[str, ...]:
    return tuple(name.strip() for name in _ROW_COLUMNS.split(","))


def _stats_from_row(row: Any) -> CorpusStats:
    """Decode a ``skills_corpus_stats`` row into ``CorpusStats`` (SPEC-066 R-2).

    A missing row (a store that has never refreshed) yields ``EMPTY_STATS``,
    whose ``idf`` is the neutral ``1.0`` — so an unrefreshed store scores
    exactly as the shipped scorer does rather than failing or skewing.
    """
    if row is None:
        return EMPTY_STATS
    return CorpusStats(n=int(row[0]), df=dict(row[1] or {}))


class PostgresSkillStore:
    """Durable store over a single ``skills`` table in the ``skills`` database.

    Connections are opened per operation (retrieval traffic is low-volume);
    the ``connect`` factory is injectable so tests can substitute a fake
    driver. Search pre-filters candidates with full-text matching, then
    re-ranks them with the shared scorer for byte-identical ordering.
    """

    def __init__(
        self,
        db_url: str,
        connect: ConnectFactory | None = None,
    ) -> None:
        self._db_url = db_url
        self._connect = connect or self._default_connect
        # SPEC-066 R-2: neutral until ``initialize`` loads the persisted
        # snapshot or ``refresh_statistics`` recomputes it, so an unrefreshed
        # store scores exactly as the shipped scorer does.
        self._stats: CorpusStats = EMPTY_STATS

    @asynccontextmanager
    async def _default_connect(self) -> AsyncIterator[Any]:
        import psycopg

        conn = await psycopg.AsyncConnection.connect(
            self._db_url, autocommit=False
        )
        try:
            yield conn
        finally:
            await conn.close()

    async def initialize(self) -> None:
        async with self._connect() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_DDL)
                # SPEC-066 R-2: load the last-persisted statistics so a
                # restarted replica scores against the last-synced population
                # rather than a neutral empty snapshot until the next refresh.
                await cur.execute(
                    "SELECT n, df FROM skills_corpus_stats WHERE id = 1"
                )
                row = await cur.fetchone()
            await conn.commit()
        self._stats = _stats_from_row(row)

    async def replace_source(
        self, source_id: str, records: Sequence[Skill]
    ) -> int:
        """Atomic per-source swap: delete + insert inside one transaction."""
        from psycopg.types.json import Jsonb

        async with self._connect() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM skills WHERE source_id = %(source_id)s",
                    {"source_id": source_id},
                )
                for skill in records:
                    payload = skill.model_dump(mode="json")
                    # SPEC-055 R-3: ``steps`` is JSONB, and psycopg adapts a
                    # bare list/dict only through the explicit ``Jsonb``
                    # wrapper (the SPEC-051 "cannot adapt type 'dict'"
                    # lesson). An absent step list stays SQL NULL rather than
                    # JSON ``null`` so both backends round-trip identically.
                    # SPEC-057 R-1: ``sub_skills`` is the same JSONB shape and
                    # takes the same wrapper + NULL-when-absent treatment.
                    steps = payload.get("steps")
                    sub_skills = payload.get("sub_skills")
                    await cur.execute(
                        _INSERT,
                        {
                            "skill_id": payload["skill_id"],
                            "source_id": payload["source_id"],
                            "source_path": payload["source_path"],
                            "source_ref": payload["source_ref"],
                            "title": payload["title"],
                            "description": payload["description"],
                            "tags": payload.get("tags"),
                            "version": payload.get("version"),
                            "source_url": payload.get("source_url"),
                            "updated_at": skill.updated_at,
                            "body": payload["body"],
                            "web_target": payload.get("web_target"),
                            "risk_class": payload.get("risk_class"),
                            "flow_intent": payload.get("flow_intent"),
                            "kind": payload.get("kind"),
                            "steps": (
                                Jsonb(steps) if steps is not None else None
                            ),
                            "sub_skills": (
                                Jsonb(sub_skills)
                                if sub_skills is not None
                                else None
                            ),
                        },
                    )
            await conn.commit()
        return len(records)

    async def prune_sources(self, source_ids: Sequence[str]) -> int:
        # Sources removed from SKILLS_SOURCES never sync again, so their
        # rows would otherwise keep serving stale skills forever; prune at
        # startup keeps the catalog equal to the federation entry.
        async with self._connect() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM skills WHERE NOT (source_id = ANY(%(keep)s))",
                    {"keep": list(source_ids)},
                )
                removed = cur.rowcount or 0
            await conn.commit()
        return int(removed)

    async def refresh_statistics(self) -> None:
        # SPEC-066 R-2: the sync-time full-catalog pass the plan endorses. A
        # per-*request* whole-catalog read is what the prefilter exists to
        # avoid; a per-*sync* one is trivial next to sync's git clone. Reads
        # every row, computes ``df`` in Python with the scorer's own
        # document-side ``tokenize()``, and persists the snapshot so every
        # replica derives the identical statistic. Computing it in Python — not
        # SQL — is what guarantees ``df`` is keyed by exactly the tokens
        # ``score`` matches against: ``to_tsvector('simple')`` and the
        # ``[a-z0-9]+`` rule agree on this corpus but are not identical parsers
        # in general, and R-4 (amended) keeps the document side unsplit precisely
        # so the two stay aligned. ``df`` is global, so a per-source swap
        # refreshes all of it.
        from psycopg.types.json import Jsonb

        async with self._connect() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"SELECT {_ROW_COLUMNS} FROM skills")
                rows = [
                    dict(zip(_row_names(), row))
                    for row in await cur.fetchall()
                ]
                stats = compute_stats(_row_to_skill(row) for row in rows)
                await cur.execute(
                    "INSERT INTO skills_corpus_stats (id, n, df) "
                    "VALUES (1, %(n)s, %(df)s) "
                    "ON CONFLICT (id) DO UPDATE SET "
                    "n = EXCLUDED.n, df = EXCLUDED.df",
                    {"n": stats.n, "df": Jsonb(dict(stats.df))},
                )
            await conn.commit()
        self._stats = stats

    async def get(self, skill_id: str) -> Skill | None:
        async with self._connect() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT {_ROW_COLUMNS} FROM skills "
                    "WHERE skill_id = %(skill_id)s",
                    {"skill_id": skill_id},
                )
                row = await cur.fetchone()
        if row is None:
            return None
        return _row_to_skill(dict(zip(_row_names(), row)))

    async def list(
        self,
        offset: int,
        limit: int,
        source: str | None = None,
        tag: str | None = None,
    ) -> tuple[list[Skill], int]:
        where, params = self._filter_clause(source, tag)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        async with self._connect() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT count(*) FROM skills {clause}", params
                )
                count_row = await cur.fetchone()
                total = int(count_row[0]) if count_row else 0
                await cur.execute(
                    f"SELECT {_ROW_COLUMNS} FROM skills {clause} "
                    "ORDER BY skill_id LIMIT %(limit)s OFFSET %(offset)s",
                    {**params, "limit": limit, "offset": offset},
                )
                rows = [
                    dict(zip(_row_names(), row)) for row in await cur.fetchall()
                ]
        return [_row_to_skill(row) for row in rows], total

    async def search(
        self,
        query: str,
        limit: int,
        source: str | None = None,
        tag: str | None = None,
    ) -> list[SearchHit]:
        # Tokenized lexemes keep to_tsquery safe (no operator characters)
        # and mirror the scorer's matching unit; a tokenless query can
        # never score above zero, so skip the round-trip entirely.
        tokens = tokenize_query(query)
        if not tokens:
            return []
        where, params = self._filter_clause(source, tag)
        where.append(_SEARCH_VECTOR)
        # SPEC-066 R-5: OR each token's exact **and** prefix form so a
        # CamelCase-derived query part reaches the single SQL lexeme it prefixes
        # (``reset:*`` matches the indexed ``resetpasswordadhoc``; a bare
        # ``reset`` does not, because ``to_tsvector('simple')`` does not split
        # CamelCase the way Python's ``tokenize_query()`` splits the query). The
        # document side is never split (``tokenize``), so it is byte-identical to
        # these SQL lexemes and every exact ``score`` match — which is exact token
        # membership — is covered by the exact term below. The prefilter therefore
        # stays an over-approximation of the scorer's non-zero set: over-admission
        # is invisible (Python still re-ranks), under-admission is a silent recall
        # bug. Tokens are ``[a-z0-9]+``, so no to_tsquery operator can be
        # injected, and the OR-join is kept (never plainto_tsquery, which would
        # AND the words and drop partial matches).
        params["query"] = " | ".join(f"{token} | {token}:*" for token in tokens)
        clause = f"WHERE {' AND '.join(where)}"
        async with self._connect() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT {_ROW_COLUMNS} FROM skills {clause}", params
                )
                rows = [
                    dict(zip(_row_names(), row)) for row in await cur.fetchall()
                ]
        candidates = [_row_to_skill(row) for row in rows]
        return rank(query, candidates, limit, self._stats)

    @staticmethod
    def _filter_clause(
        source: str | None, tag: str | None
    ) -> tuple[list[str], dict[str, Any]]:
        where: list[str] = []
        params: dict[str, Any] = {}
        if source:
            where.append("source_id = %(source)s")
            params["source"] = source
        if tag:
            # Exact case-insensitive match, mirroring the in-memory store and
            # the scorer; ILIKE would interpret the parameter as a pattern
            # ('%'/'_') and diverge between backends.
            where.append(
                "EXISTS (SELECT 1 FROM unnest(tags) AS t "
                "WHERE lower(t) = lower(%(tag)s))"
            )
            params["tag"] = tag
        return where, params

    async def count(self) -> int:
        async with self._connect() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT count(*) FROM skills")
                row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def ready(self) -> bool:
        try:
            async with self._connect() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
                    await cur.fetchone()
            return True
        except Exception:  # noqa: BLE001 - readiness must never raise
            return False

    async def close(self) -> None:
        return None


# --- Factory ------------------------------------------------------------------


def build_skill_store(settings: SkillsSettings) -> SkillStore:
    """Select the store backend from settings (default: in-memory)."""
    if settings.store_backend == "postgres":
        if not settings.db_url:
            raise StoreError(
                "SKILLS_DB_URL is required when SKILLS_STORE_BACKEND=postgres"
            )
        return PostgresSkillStore(settings.db_url)
    return InMemorySkillStore()
