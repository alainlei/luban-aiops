"""SPEC-039 R-1: typed operation document repository store.

Covers the operation document store (in-memory semantics, Postgres SQL
shape via a fake driver, factory backend selection): draft->published
one-way lifecycle, owner-scoped publish/delete, per-owner cap with
oldest eviction, 30-day retention sweep, and the visibility matrix at
the query boundary (drafts never leave ``list_for_owner``).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from agent_service.services.operation_documents import (
    PER_OWNER_CAP,
    RETENTION_DAYS,
    InMemoryOperationDocumentStore,
    PostgresOperationDocumentStore,
    build_operation_document_store,
    make_document,
)


def _doc(
    document_id: str = "doc-1",
    owner: str = "alice",
    created_at: str | None = None,
    prose: str | None = None,
    prose_status: str = "not_requested",
) -> dict:
    document = make_document(
        document_id=document_id,
        document_type="shift_summary",
        owner_user_id=owner,
        label=f"shift {document_id}",
        provenance={
            "sessions": [
                {"session_id": "ses-1", "coverage": "owner", "cited_record_ids": []}
            ]
        },
        digest={"sessions": []},
        prose=prose,
        prose_status=prose_status,
    )
    if created_at is not None:
        document["created_at"] = created_at
    return document


def _iso(days_ago: int) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("AGENT_STATE_STORE_BACKEND", raising=False)
    monkeypatch.delenv("AGENT_STATE_DB_URL", raising=False)


# --- In-memory store semantics ---


class TestInMemoryStore:
    def test_create_and_load(self) -> None:
        store = InMemoryOperationDocumentStore()
        store.create(_doc())
        record = store.load("doc-1")
        assert record is not None
        assert record["state"] == "draft"
        assert record["document_type"] == "shift_summary"
        assert record["published_at"] is None
        assert record["provenance"]["sessions"][0]["session_id"] == "ses-1"
        # Loads are copies: mutating the result never touches the store.
        record["label"] = "tampered"
        assert store.load("doc-1")["label"] == "shift doc-1"

    def test_publish_is_one_way_and_owner_only(self) -> None:
        store = InMemoryOperationDocumentStore()
        store.create(_doc())
        assert store.publish("bob", "doc-1") is False
        assert store.publish("alice", "doc-1") is True
        record = store.load("doc-1")
        assert record["state"] == "published"
        assert record["published_at"] is not None
        # A repeated publish is a no-op (never re-stamps published_at).
        first_published_at = record["published_at"]
        assert store.publish("alice", "doc-1") is False
        assert store.load("doc-1")["published_at"] == first_published_at

    def test_publish_unknown_document(self) -> None:
        store = InMemoryOperationDocumentStore()
        assert store.publish("alice", "nope") is False

    def test_list_for_owner_is_owner_scoped_and_newest_first(self) -> None:
        store = InMemoryOperationDocumentStore()
        # Timestamps must be relative to now: create() sweeps rows older than
        # RETENTION_DAYS, so a hardcoded date silently ages out once the wall
        # clock passes it. doc-2 stays newer than doc-1 for the ordering assert.
        now = datetime.now(timezone.utc)
        store.create(
            _doc(
                "doc-1",
                created_at=(now - timedelta(minutes=2)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            )
        )
        store.create(
            _doc(
                "doc-2",
                created_at=(now - timedelta(minutes=1)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            )
        )
        store.create(_doc("doc-9", owner="bob"))
        rows = store.list_for_owner("alice")
        assert [row["document_id"] for row in rows] == ["doc-2", "doc-1"]

    def test_visibility_matrix_published_only(self) -> None:
        store = InMemoryOperationDocumentStore()
        store.create(_doc("doc-1"))
        store.create(_doc("doc-2"))
        store.publish("alice", "doc-2")
        published = store.list_published()
        # Drafts never appear on the team-visible surface.
        assert [row["document_id"] for row in published] == ["doc-2"]

    def test_delete_is_owner_scoped(self) -> None:
        store = InMemoryOperationDocumentStore()
        store.create(_doc())
        assert store.delete("bob", "doc-1") is False
        assert store.delete("alice", "doc-1") is True
        assert store.delete("alice", "doc-1") is False
        assert store.load("doc-1") is None

    def test_cap_evicts_oldest_per_owner(self) -> None:
        store = InMemoryOperationDocumentStore()
        now = datetime.now(timezone.utc)
        for index in range(PER_OWNER_CAP + 3):
            # Timestamps must be relative to now: create() sweeps rows older
            # than RETENTION_DAYS, so a hardcoded date would silently age out
            # once the wall clock passes it and corrupt the cap assertion.
            stamp = now - timedelta(minutes=PER_OWNER_CAP + 3 - index)
            store.create(
                _doc(
                    f"doc-{index:02d}",
                    created_at=stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
            )
        rows = store.list_for_owner("alice")
        assert len(rows) == PER_OWNER_CAP
        # Oldest rows (lowest created_at) were evicted first.
        kept = {row["document_id"] for row in rows}
        assert {"doc-00", "doc-01", "doc-02"} & kept == set()

    def test_cap_is_per_owner(self) -> None:
        store = InMemoryOperationDocumentStore()
        for index in range(PER_OWNER_CAP):
            store.create(_doc(f"alice-{index}", owner="alice"))
        store.create(_doc("bob-0", owner="bob"))
        assert len(store.list_for_owner("alice")) == PER_OWNER_CAP
        assert len(store.list_for_owner("bob")) == 1

    def test_expired_documents_swept_on_write(self) -> None:
        store = InMemoryOperationDocumentStore()
        store.create(_doc("old", created_at=_iso(RETENTION_DAYS + 1)))
        store.create(_doc("fresh"))
        assert store.load("old") is None
        assert store.load("fresh") is not None

    def test_is_ready(self) -> None:
        assert InMemoryOperationDocumentStore().is_ready() is True


# --- Postgres backend (fake driver) ---


class _FakeCursor:
    def __init__(self, calls: list[dict], rows=None, rowcount: int = 0) -> None:
        self._calls = calls
        self._rows = rows or []
        self.rowcount = rowcount

    def execute(self, sql, params=None):
        self._calls.append({"sql": sql, "params": params})

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_connect(calls: list[dict], rows=None, rowcount: int = 0):
    @contextmanager
    def connect():
        class FakeConn:
            def cursor(self):
                return _FakeCursor(calls, rows, rowcount)

            def commit(self):
                calls.append({"commit": True})

        yield FakeConn()

    return connect


class TestPostgresStore:
    def test_initialize_runs_ddl_and_sweep(self) -> None:
        calls: list[dict] = []
        store = PostgresOperationDocumentStore(
            db_url="postgresql://fake", connect=_fake_connect(calls)
        )
        store.initialize()
        sqls = [call["sql"] for call in calls if "sql" in call]
        assert any(
            "CREATE TABLE IF NOT EXISTS operation_documents" in s for s in sqls
        )
        # SPEC-041 R-4: the additive summary migration rides initialize.
        assert any(
            "ADD COLUMN IF NOT EXISTS summary" in s for s in sqls
        )
        # v0.23.3: the additive blurb migration rides initialize too.
        assert any(
            "ADD COLUMN IF NOT EXISTS blurb" in s for s in sqls
        )
        sweep = next(
            call
            for call in calls
            if "sql" in call and "DELETE FROM operation_documents" in call["sql"]
        )
        assert sweep["params"]["retention_days"] == RETENTION_DAYS

    def test_create_inserts_evicts_and_sweeps(self) -> None:
        from psycopg.types.json import Jsonb

        calls: list[dict] = []
        store = PostgresOperationDocumentStore(
            db_url="postgresql://fake", connect=_fake_connect(calls)
        )
        store.create(_doc())
        executed = [call for call in calls if "sql" in call]
        insert = executed[0]
        assert "INSERT INTO operation_documents" in insert["sql"]
        assert "ON CONFLICT (document_id) DO NOTHING" in insert["sql"]
        assert "'draft'" in insert["sql"]
        assert isinstance(insert["params"]["provenance"], Jsonb)
        assert isinstance(insert["params"]["digest"], Jsonb)
        # SPEC-041 R-4: the summary lands beside the content fields.
        assert insert["params"]["summary"] is None
        # v0.23.3: the AI one-liner lands beside the summary.
        assert insert["params"]["blurb"] is None
        evict = next(
            call for call in executed[1:] if "OFFSET" in call["sql"]
        )
        assert evict["params"]["cap"] == PER_OWNER_CAP
        assert any(
            "DELETE FROM operation_documents" in call["sql"]
            and "OFFSET" not in call["sql"]
            for call in executed[1:]
        )

    def test_publish_only_touches_own_draft_rows(self) -> None:
        calls: list[dict] = []
        store = PostgresOperationDocumentStore(
            db_url="postgresql://fake",
            connect=_fake_connect(calls, rowcount=1),
        )
        assert store.publish("alice", "doc-1") is True
        update = next(call for call in calls if "sql" in call)
        assert "UPDATE operation_documents" in update["sql"]
        assert "AND state = 'draft'" in update["sql"]
        assert "AND owner_user_id = %(owner_user_id)s" in update["sql"]
        assert update["params"]["owner_user_id"] == "alice"

    def test_publish_reports_no_row(self) -> None:
        calls: list[dict] = []
        store = PostgresOperationDocumentStore(
            db_url="postgresql://fake",
            connect=_fake_connect(calls, rowcount=0),
        )
        assert store.publish("alice", "doc-1") is False

    def test_load_maps_row(self) -> None:
        calls: list[dict] = []
        row = (
            "doc-1",
            "shift_summary",
            "published",
            "alice",
            "night shift",
            datetime(2026, 8, 27, 8, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 27, 9, 0, 0, tzinfo=timezone.utc),
            {"sessions": [{"session_id": "ses-1", "coverage": "owner"}]},
            {"sessions": []},
            "narrative text",
            "included",
            "Quiet shift \u2014 no recorded decisions or executions.",
            "Quiet shift, nothing to inherit.",
        )
        store = PostgresOperationDocumentStore(
            db_url="postgresql://fake", connect=_fake_connect(calls, rows=[row])
        )
        record = store.load("doc-1")
        assert record is not None
        assert record["created_at"] == "2026-08-27T08:00:00Z"
        assert record["published_at"] == "2026-08-27T09:00:00Z"
        assert record["prose_status"] == "included"
        assert record["provenance"]["sessions"][0]["coverage"] == "owner"
        assert record["summary"] == (
            "Quiet shift \u2014 no recorded decisions or executions."
        )
        assert record["blurb"] == "Quiet shift, nothing to inherit."

    def test_list_published_filters_at_the_query(self) -> None:
        calls: list[dict] = []
        store = PostgresOperationDocumentStore(
            db_url="postgresql://fake", connect=_fake_connect(calls)
        )
        store.list_published()
        select = next(call for call in calls if "sql" in call)
        assert "WHERE state = 'published'" in select["sql"]

    def test_delete_is_owner_scoped(self) -> None:
        calls: list[dict] = []
        store = PostgresOperationDocumentStore(
            db_url="postgresql://fake",
            connect=_fake_connect(calls, rows=[("doc-1",)]),
        )
        assert store.delete("alice", "doc-1") is True
        delete = next(call for call in calls if "sql" in call)
        assert "AND owner_user_id = %(owner_user_id)s" in delete["sql"]
        empty = PostgresOperationDocumentStore(
            db_url="postgresql://fake", connect=_fake_connect(calls)
        )
        assert empty.delete("alice", "doc-1") is False


# --- Factory backend selection ---


class TestFactory:
    def test_defaults_to_memory(self, monkeypatch) -> None:
        monkeypatch.setenv("AGENT_STATE_STORE_BACKEND", "memory")
        store = build_operation_document_store()
        assert store.backend_name == "memory"

    def test_postgres_without_url_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("AGENT_STATE_STORE_BACKEND", "postgres")
        with pytest.raises(ValueError, match="AGENT_STATE_DB_URL"):
            build_operation_document_store()

    def test_postgres_unreachable_falls_back_to_memory(self, monkeypatch) -> None:
        monkeypatch.setenv("AGENT_STATE_STORE_BACKEND", "postgres")
        monkeypatch.setenv("AGENT_STATE_DB_URL", "postgresql://fake")

        @contextmanager
        def fail_connect(self):
            raise RuntimeError("connection refused")
            yield  # pragma: no cover

        monkeypatch.setattr(
            PostgresOperationDocumentStore, "_default_connect", fail_connect
        )
        store = build_operation_document_store()
        assert store.backend_name == "memory"

    def test_unknown_backend_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("AGENT_STATE_STORE_BACKEND", "redis")
        with pytest.raises(ValueError, match="Unknown AGENT_STATE_STORE_BACKEND"):
            build_operation_document_store()
