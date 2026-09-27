"""SPEC-039 R-2/R-5: agent document routes, visibility matrix, audit.

End-to-end through the v2 app: creation (bounded input, foreign
gating), the visibility matrix (drafts owner-only; published
team-visible), one-way publish, owner delete, cross-owner read audit,
and contract validation against operation-document.schema.json.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient

from agent_service.api.v2 import routes as v2_routes
from agent_service.app import create_app
from agent_service.services.incident_client import (
    IncidentClientRejected,
    IncidentDependencyNotConfigured,
    IncidentNotFound,
    IncidentServiceUnavailable,
)
from agent_service.services.operation_documents import (
    OPERATION_DOCUMENT_STORE,
)
from agent_service.services.session_store import SESSION_STORE

SCHEMAS_DIR = (
    Path(__file__).resolve().parents[3]
    / "shared"
    / "shared-contracts"
    / "schemas"
)


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _clean_stores(monkeypatch):
    documents = getattr(OPERATION_DOCUMENT_STORE, "_by_document_id", None)
    sessions = getattr(SESSION_STORE, "_sessions", None)
    last_accessed = getattr(SESSION_STORE, "_last_accessed", None)
    if documents is not None:
        documents.clear()
    if sessions is not None:
        sessions.clear()
    if last_accessed is not None:
        last_accessed.clear()

    emitted: list[dict] = []

    def _capture(settings, event: dict) -> None:
        emitted.append(event)

    monkeypatch.setattr(v2_routes, "emit_audit_event", _capture)
    yield emitted
    if documents is not None:
        documents.clear()
    if sessions is not None:
        sessions.clear()
    if last_accessed is not None:
        last_accessed.clear()


def _session(client: TestClient, user: str) -> str:
    response = client.post("/api/v2/sessions", headers={"X-User-ID": user})
    assert response.status_code == 201
    return response.json()["session_id"]


def _development_session(client: TestClient, user: str) -> str:
    """A Studio-born ``development`` session (SPEC-056 R-4)."""
    response = client.post(
        "/api/v2/sessions",
        json={"session_type": "development"},
        headers={"X-User-ID": user},
    )
    assert response.status_code == 201
    assert response.json()["session_type"] == "development"
    return response.json()["session_id"]


def _create_draft(client: TestClient, user: str, session_ids: list[str], **extra):
    body = {
        "document_type": "shift_summary",
        "session_ids": session_ids,
        "label": "night shift",
        "include_prose": False,
        **extra,
    }
    return client.post("/api/v2/documents", json=body, headers={"X-User-ID": user})


class TestCreateDocument:
    def test_create_own_draft(self) -> None:
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        response = _create_draft(app_client, "alice", [session_id])
        assert response.status_code == 201
        document = response.json()
        assert document["state"] == "draft"
        assert document["document_type"] == "shift_summary"
        assert document["owner_user_id"] == "alice"
        assert document["prose_status"] == "not_requested"
        assert document["prose"] is None
        entry = document["digest"]["sessions"][0]
        assert entry["coverage"] == "owner"
        # SPEC-040 R-1: the route-created document carries the
        # deterministic handover skeleton alongside the sessions.
        handover = document["digest"]["handover"]
        assert handover["covered_session_count"] == 1
        assert handover["own_session_count"] == 1
        assert handover["quiet"] is True
        # SPEC-041 R-4: the counts-only list summary is derived at
        # creation from the handover skeleton.
        assert (
            document["summary"]
            == "Quiet shift \u2014 no recorded decisions or executions."
        )
        assert document["provenance"]["sessions"][0]["session_id"] == session_id
        # The envelope validates against the shared contract.
        jsonschema.validate(document, _load_schema("operation-document.schema.json"))

    def test_narrative_defaults_on_without_include_prose(
        self, monkeypatch
    ) -> None:
        # SPEC-040 R-2: omitting include_prose now requests the
        # narrative; the generate boundary is exercised exactly once.
        calls: list[tuple] = []

        async def _fake_generate(kernel, document_type, digest):
            calls.append((document_type, digest))
            return (
                "A quiet shift with no recorded decisions.",
                "A quiet shift, nothing to inherit.",
                "included",
            )

        monkeypatch.setattr(v2_routes, "generate_prose", _fake_generate)
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        response = app_client.post(
            "/api/v2/documents",
            json={
                "document_type": "shift_summary",
                "session_ids": [session_id],
                "label": "night shift",
            },
            headers={"X-User-ID": "alice"},
        )
        assert response.status_code == 201
        document = response.json()
        assert document["prose_status"] == "included"
        assert document["prose"].startswith("A quiet shift")
        # v0.23.3: the AI one-liner rides with the narrative.
        assert document["blurb"] == "A quiet shift, nothing to inherit."
        assert len(calls) == 1
        assert calls[0][0] == "shift_summary"
        # The prompt contract's sole input: the assembled digest.
        assert "handover" in calls[0][1]

    def test_create_emits_document_created_audit(self, _clean_stores) -> None:
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        response = _create_draft(app_client, "alice", [session_id])
        assert response.status_code == 201
        events = [e for e in _clean_stores if e["event_type"] == "document_created"]
        assert len(events) == 1
        details = events[0]["details"]
        assert details["own_session_count"] == 1
        assert details["foreign_session_count"] == 0
        assert details["prose_status"] == "not_requested"
        assert events[0]["username"] == "alice"

    def test_unknown_session_ids_rejected_structurally(self) -> None:
        app_client = TestClient(create_app())
        response = _create_draft(app_client, "alice", ["nope-1", "nope-2"])
        assert response.status_code == 400
        assert "nope-1" in response.json()["detail"]

    def test_bounded_input_enforced(self) -> None:
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        response = _create_draft(
            app_client, "alice", [session_id] + [f"x-{i}" for i in range(25)]
        )
        # 26 ids violate the contract bound (max 20) before assembly.
        assert response.status_code == 422

    def test_blank_label_rejected(self) -> None:
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        response = app_client.post(
            "/api/v2/documents",
            json={
                "document_type": "shift_summary",
                "session_ids": [session_id],
                "label": "   ",
            },
            headers={"X-User-ID": "alice"},
        )
        # Whitespace-only labels fail the trimmed-length check.
        assert response.status_code == 400

    def test_foreign_session_without_capability_rejected(self) -> None:
        app_client = TestClient(create_app())
        foreign_id = _session(app_client, "carol")
        response = _create_draft(app_client, "alice", [foreign_id])
        assert response.status_code == 403
        assert "approvals:list" in response.json()["detail"]

    def test_foreign_session_with_capability_metadata_only(
        self, _clean_stores
    ) -> None:
        app_client = TestClient(create_app())
        foreign_id = _session(app_client, "carol")
        response = app_client.post(
            "/api/v2/documents",
            json={
                "document_type": "shift_summary",
                "session_ids": [foreign_id],
                "label": "covering carol",
            },
            headers={
                "X-User-ID": "alice",
                "X-Foreign-Coverage": "allowed",
            },
        )
        assert response.status_code == 201
        entry = response.json()["digest"]["sessions"][0]
        assert entry["coverage"] == "foreign"
        assert "title" not in entry
        events = [e for e in _clean_stores if e["event_type"] == "document_created"]
        assert events[0]["details"]["foreign_session_count"] == 1


class TestDocumentSummary:
    """SPEC-041 R-4: counts-only summary in the envelope-only listing."""

    def test_list_envelope_carries_summary_without_content(self) -> None:
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        created = _create_draft(app_client, "alice", [session_id]).json()
        response = app_client.get(
            "/api/v2/documents", headers={"X-User-ID": "alice"}
        )
        assert response.status_code == 200
        [row] = response.json()["documents"]
        assert row["document_id"] == created["document_id"]
        assert row["summary"] == created["summary"]
        # The envelope-only posture holds: content stays behind the
        # audited single fetch.
        assert "digest" not in row
        assert "prose" not in row

    def test_published_listing_carries_summary(self) -> None:
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        created = _create_draft(app_client, "alice", [session_id]).json()
        publish = app_client.post(
            f"/api/v2/documents/{created['document_id']}/publish",
            headers={"X-User-ID": "alice"},
        )
        assert publish.status_code == 200
        response = app_client.get(
            "/api/v2/documents?scope=published", headers={"X-User-ID": "bob"}
        )
        assert response.status_code == 200
        [row] = response.json()["documents"]
        assert row["summary"] == created["summary"]

    def test_legacy_record_degrades_without_summary(self) -> None:
        app_client = TestClient(create_app())
        # Records created before SPEC-041 carry no summary key at all.
        # created_at must be relative to now: the store sweeps rows older than
        # RETENTION_DAYS on write, so a hardcoded date silently ages out.
        recent = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        OPERATION_DOCUMENT_STORE.create(
            {
                "document_id": "doc-legacy",
                "document_type": "shift_summary",
                "state": "draft",
                "owner_user_id": "alice",
                "label": "legacy shift",
                "created_at": recent,
                "published_at": None,
                "provenance": {"sessions": []},
                "digest": {"sessions": []},
                "prose": None,
                "prose_status": "not_requested",
            }
        )
        response = app_client.get(
            "/api/v2/documents", headers={"X-User-ID": "alice"}
        )
        assert response.status_code == 200
        [row] = response.json()["documents"]
        assert "summary" not in row


class TestVisibilityMatrix:
    def _seed_published(self, client: TestClient) -> str:
        session_id = _session(client, "alice")
        created = _create_draft(client, "alice", [session_id]).json()
        published = client.post(
            f"/api/v2/documents/{created['document_id']}/publish",
            headers={"X-User-ID": "alice"},
        )
        assert published.status_code == 200
        return created["document_id"]

    def test_mine_scope_is_owner_scoped(self) -> None:
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        _create_draft(app_client, "alice", [session_id])
        bob_rows = app_client.get(
            "/api/v2/documents", params={"scope": "mine"},
            headers={"X-User-ID": "bob"},
        ).json()["documents"]
        assert bob_rows == []

    def test_published_scope_never_carries_drafts(self, _clean_stores) -> None:
        app_client = TestClient(create_app())
        draft_id = _create_draft(
            app_client, "alice", [_session(app_client, "alice")]
        ).json()["document_id"]
        published_id = self._seed_published(app_client)
        rows = app_client.get(
            "/api/v2/documents",
            params={"scope": "published"},
            headers={"X-User-ID": "bob"},
        ).json()["documents"]
        ids = [row["document_id"] for row in rows]
        assert published_id in ids
        assert draft_id not in ids

    def test_list_rows_are_envelope_only(self) -> None:
        app_client = TestClient(create_app())
        document_id = self._seed_published(app_client)
        # Both scopes omit digest/prose: the full content is only
        # served by the single fetch, which is the audited surface.
        published_rows = app_client.get(
            "/api/v2/documents",
            params={"scope": "published"},
            headers={"X-User-ID": "bob"},
        ).json()["documents"]
        mine_rows = app_client.get(
            "/api/v2/documents",
            params={"scope": "mine"},
            headers={"X-User-ID": "alice"},
        ).json()["documents"]
        for rows in (published_rows, mine_rows):
            assert [row["document_id"] for row in rows] == [document_id]
            for row in rows:
                assert "digest" not in row
                assert "prose" not in row
        # The single fetch still carries the full document.
        full = app_client.get(
            f"/api/v2/documents/{document_id}", headers={"X-User-ID": "alice"}
        ).json()
        assert "digest" in full

    def test_foreign_draft_is_indistinguishable_from_unknown(self) -> None:
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        draft_id = _create_draft(app_client, "alice", [session_id]).json()[
            "document_id"
        ]
        foreign = app_client.get(
            f"/api/v2/documents/{draft_id}", headers={"X-User-ID": "bob"}
        )
        unknown = app_client.get(
            "/api/v2/documents/doc-does-not-exist", headers={"X-User-ID": "bob"}
        )
        assert foreign.status_code == unknown.status_code == 404

    def test_cross_owner_read_is_audited_own_read_is_not(
        self, _clean_stores
    ) -> None:
        app_client = TestClient(create_app())
        document_id = self._seed_published(app_client)
        own = app_client.get(
            f"/api/v2/documents/{document_id}", headers={"X-User-ID": "alice"}
        )
        assert own.status_code == 200
        cross = app_client.get(
            f"/api/v2/documents/{document_id}", headers={"X-User-ID": "bob"}
        )
        assert cross.status_code == 200
        reads = [e for e in _clean_stores if e["event_type"] == "document_read"]
        assert len(reads) == 1
        assert reads[0]["username"] == "bob"
        assert reads[0]["details"]["owner_user_id"] == "alice"


class TestPublishAndDelete:
    def test_publish_is_one_way_and_audited(self, _clean_stores) -> None:
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        document_id = _create_draft(app_client, "alice", [session_id]).json()[
            "document_id"
        ]
        first = app_client.post(
            f"/api/v2/documents/{document_id}/publish",
            headers={"X-User-ID": "alice"},
        )
        assert first.status_code == 200
        assert first.json()["state"] == "published"
        assert first.json()["published_at"] is not None
        # Publishing is one-way: a second publish is a conflict.
        again = app_client.post(
            f"/api/v2/documents/{document_id}/publish",
            headers={"X-User-ID": "alice"},
        )
        assert again.status_code == 409
        events = [
            e for e in _clean_stores if e["event_type"] == "document_published"
        ]
        assert len(events) == 1
        assert events[0]["details"]["document_id"] == document_id

    def test_publish_foreign_document_404(self) -> None:
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        document_id = _create_draft(app_client, "alice", [session_id]).json()[
            "document_id"
        ]
        response = app_client.post(
            f"/api/v2/documents/{document_id}/publish",
            headers={"X-User-ID": "bob"},
        )
        assert response.status_code == 404

    def test_delete_own_document(self) -> None:
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        document_id = _create_draft(app_client, "alice", [session_id]).json()[
            "document_id"
        ]
        foreign = app_client.delete(
            f"/api/v2/documents/{document_id}", headers={"X-User-ID": "bob"}
        )
        assert foreign.status_code == 404
        own = app_client.delete(
            f"/api/v2/documents/{document_id}", headers={"X-User-ID": "alice"}
        )
        assert own.status_code == 200
        assert own.json() == {"document_id": document_id, "deleted": True}
        gone = app_client.get(
            f"/api/v2/documents/{document_id}", headers={"X-User-ID": "alice"}
        )
        assert gone.status_code == 404


class TestSessionRename:
    def test_owner_rename_overwrites_minted_title(self) -> None:
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        response = app_client.patch(
            f"/api/v2/sessions/{session_id}/title",
            json={"title": "  night shift 2026-08-27  "},
            headers={"X-User-ID": "alice"},
        )
        assert response.status_code == 200
        assert response.json()["title"] == "night shift 2026-08-27"
        # The list surface reflects the new title.
        rows = app_client.get(
            "/api/v2/sessions", headers={"X-User-ID": "alice"}
        ).json()["sessions"]
        assert rows[0]["title"] == "night shift 2026-08-27"

    def test_rename_foreign_or_unknown_session_404(self) -> None:
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        foreign = app_client.patch(
            f"/api/v2/sessions/{session_id}/title",
            json={"title": "hijack"},
            headers={"X-User-ID": "bob"},
        )
        unknown = app_client.patch(
            "/api/v2/sessions/nope/title",
            json={"title": "hijack"},
            headers={"X-User-ID": "bob"},
        )
        assert foreign.status_code == unknown.status_code == 404

    def test_rename_blank_title_rejected(self) -> None:
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        response = app_client.patch(
            f"/api/v2/sessions/{session_id}/title",
            json={"title": "    "},
            headers={"X-User-ID": "alice"},
        )
        assert response.status_code == 400

    def test_rename_supersedes_minted_title(self) -> None:
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        # Mint a title through a chat-turn bookkeeping call.
        from agent_service.services.session_service import mark_session_turn

        mark_session_turn(session_id, "investigate the payment outage")
        response = app_client.patch(
            f"/api/v2/sessions/{session_id}/title",
            json={"title": "renamed by owner"},
            headers={"X-User-ID": "alice"},
        )
        assert response.status_code == 200
        assert response.json()["title"] == "renamed by owner"


# --- SPEC-043: the incident_report document type ------------------------------

INCIDENT_BUNDLE = {
    "incident": {
        "incident_id": "inc-abc123",
        "fingerprint": "fp-1",
        "source": "webhook",
        "severity": "critical",
        "status": "triaged",
        "title": "Payment API latency",
        "summary": "p99 latency spike on the payment API",
        "labels": {"team": "payments"},
        "reported_by": "alertmanager",
        "session_id": None,  # tests override per case
        "created_at": "2026-08-28T10:00:00Z",
        "updated_at": "2026-08-28T10:05:00Z",
        "resolved_at": None,
        "triage_raw": "RAW ALERT PAYLOAD",
    },
    "report": {
        "incident_id": "inc-abc123",
        "severity_assessment": "critical",
        "summary": "Database pool exhaustion on the payment service",
        "evidence": [{"source": "metrics", "description": "pool saturation"}],
        "hypotheses": ["connection pool exhaustion"],
        "next_steps": [
            {
                "title": "raise pool size",
                "priority": "immediate",
                "rationale": "saturation",
            }
        ],
        "skills_cited": ["sre-database"],
        "session_id": "ses-triage",
        "generated_at": "2026-08-28T10:10:00Z",
        "generated_by": "triage-agent",
    },
    "dispatches": [
        {
            "connector": "pagerduty",
            "status": "sent",
            "reference": "PD-1",
            "error": None,
            "created_at": "2026-08-28T10:02:00Z",
        }
    ],
}


def _bundle_with(session_id):
    bundle = json.loads(json.dumps(INCIDENT_BUNDLE))
    bundle["incident"]["session_id"] = session_id
    return bundle


def _create_incident_report(
    client: TestClient, user: str, incident_id: str = "inc-abc123", **extra
):
    body = {
        "document_type": "incident_report",
        "incident_id": incident_id,
        "label": "payment latency post-mortem",
        "include_prose": False,
        **extra,
    }
    return client.post("/api/v2/documents", json=body, headers={"X-User-ID": user})


class TestIncidentReportDocument:
    def _patch_fetch(self, monkeypatch, bundle):
        async def _fetch(settings, request_id, incident_id):
            return bundle

        monkeypatch.setattr(v2_routes, "fetch_incident_bundle", _fetch)

    def _patch_fetch_error(self, monkeypatch, exc):
        async def _fetch(settings, request_id, incident_id):
            raise exc

        monkeypatch.setattr(v2_routes, "fetch_incident_bundle", _fetch)

    def test_create_incident_report_own_session(
        self, monkeypatch, _clean_stores
    ) -> None:
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        self._patch_fetch(monkeypatch, _bundle_with(session_id))
        response = _create_incident_report(app_client, "alice")
        assert response.status_code == 201
        document = response.json()
        assert document["document_type"] == "incident_report"
        digest = document["digest"]
        # Four deterministic sections; raw triage stays out of the digest.
        assert digest["incident"]["incident_id"] == "inc-abc123"
        assert "triage_raw" not in digest["incident"]
        assert digest["incident"]["has_triage_raw"] is True
        assert digest["triage"]["severity_assessment"] == "critical"
        assert digest["dispatches"][0]["connector"] == "pagerduty"
        assert digest["session"]["status"] == "owner"
        # Coverage is server-derived: exactly the incident's session.
        assert document["provenance"]["incident_id"] == "inc-abc123"
        assert document["provenance"]["sessions"][0]["session_id"] == session_id
        # Counts-only summary, contract envelope validation.
        assert "triage report present" in document["summary"]
        assert "own session" in document["summary"]
        jsonschema.validate(
            document, _load_schema("operation-document.schema.json")
        )
        # SPEC-043 R-5: document_created carries the incident id; no
        # new event type is introduced.
        events = [
            e for e in _clean_stores if e["event_type"] == "document_created"
        ]
        assert len(events) == 1
        assert events[0]["details"]["incident_id"] == "inc-abc123"
        assert events[0]["details"]["document_type"] == "incident_report"

    def test_not_triaged_and_missing_session_markers(self, monkeypatch) -> None:
        app_client = TestClient(create_app())
        bundle = _bundle_with(None)
        bundle["report"] = None
        bundle["dispatches"] = []
        self._patch_fetch(monkeypatch, bundle)
        response = _create_incident_report(app_client, "alice")
        assert response.status_code == 201
        digest = response.json()["digest"]
        assert digest["triage"] == {"status": "not_triaged"}
        assert digest["session"] == {"status": "missing"}
        assert digest["dispatches"] == []
        assert "not triaged" in response.json()["summary"]

    def test_foreign_linked_session_denied_rides_marker(self, monkeypatch) -> None:
        app_client = TestClient(create_app())
        foreign_session = _session(app_client, "carol")
        self._patch_fetch(monkeypatch, _bundle_with(foreign_session))
        # No X-Foreign-Coverage header: creation still succeeds and the
        # session section degrades to the foreign_denied marker.
        response = _create_incident_report(app_client, "alice")
        assert response.status_code == 201
        document = response.json()
        assert document["digest"]["session"] == {
            "status": "foreign_denied",
            "session_id": foreign_session,
        }
        assert document["provenance"]["sessions"] == []

    def test_foreign_linked_session_metadata_with_capability(
        self, monkeypatch
    ) -> None:
        app_client = TestClient(create_app())
        foreign_session = _session(app_client, "carol")
        self._patch_fetch(monkeypatch, _bundle_with(foreign_session))
        response = app_client.post(
            "/api/v2/documents",
            json={
                "document_type": "incident_report",
                "incident_id": "inc-abc123",
                "label": "cross-owner incident",
                "include_prose": False,
            },
            headers={"X-User-ID": "alice", "X-Foreign-Coverage": "allowed"},
        )
        assert response.status_code == 201
        document = response.json()
        assert document["digest"]["session"]["status"] == "foreign"
        assert document["provenance"]["sessions"][0]["coverage"] == "foreign"

    def test_unknown_incident_answers_structural_404(self, monkeypatch) -> None:
        app_client = TestClient(create_app())
        self._patch_fetch_error(
            monkeypatch, IncidentNotFound("inc-nope")
        )
        response = _create_incident_report(app_client, "alice", "inc-nope")
        assert response.status_code == 404
        assert "unknown incident id: inc-nope" in response.json()["detail"]

    def test_not_configured_answers_503(self, monkeypatch) -> None:
        app_client = TestClient(create_app())
        self._patch_fetch_error(
            monkeypatch,
            IncidentDependencyNotConfigured("incident service not configured"),
        )
        response = _create_incident_report(app_client, "alice")
        assert response.status_code == 503

    def test_upstream_unreachable_answers_502(self, monkeypatch) -> None:
        app_client = TestClient(create_app())
        self._patch_fetch_error(
            monkeypatch, IncidentServiceUnavailable("incident service unavailable")
        )
        response = _create_incident_report(app_client, "alice")
        assert response.status_code == 502

    def test_upstream_4xx_passes_through(self, monkeypatch) -> None:
        app_client = TestClient(create_app())
        self._patch_fetch_error(
            monkeypatch, IncidentClientRejected(401, "bad credential")
        )
        response = _create_incident_report(app_client, "alice")
        assert response.status_code == 401
        assert response.json()["detail"] == "bad credential"

    def test_cross_type_field_mixing_rejected(self, monkeypatch) -> None:
        app_client = TestClient(create_app())
        session_id = _session(app_client, "alice")
        self._patch_fetch(monkeypatch, _bundle_with(session_id))
        # Incident report with a session list.
        with_sessions = app_client.post(
            "/api/v2/documents",
            json={
                "document_type": "incident_report",
                "incident_id": "inc-abc123",
                "session_ids": [session_id],
                "label": "mixed",
            },
            headers={"X-User-ID": "alice"},
        )
        assert with_sessions.status_code == 422
        # Shift summary with an incident id.
        with_incident = app_client.post(
            "/api/v2/documents",
            json={
                "document_type": "shift_summary",
                "session_ids": [session_id],
                "incident_id": "inc-abc123",
                "label": "mixed",
            },
            headers={"X-User-ID": "alice"},
        )
        assert with_incident.status_code == 422
        # Incident report without an incident id.
        missing_id = app_client.post(
            "/api/v2/documents",
            json={"document_type": "incident_report", "label": "missing id"},
            headers={"X-User-ID": "alice"},
        )
        assert missing_id.status_code == 422
        # The contract pattern bounds the incident id shape.
        bad_pattern = _create_incident_report(app_client, "alice", "INC-BAD")
        assert bad_pattern.status_code == 422


# --- SPEC-056 R-4: the shift-summary create-path guard -----------------------


class TestDevelopmentSessionCreateGuard:
    """The create-path guard beside the scoped list query.

    A hand-crafted ``session_ids`` list naming a ``development`` session is
    rejected whole at ``POST /api/v2/documents`` (shift_summary only), matching
    the unknown-session (400) / foreign-denied (403) structural posture. The
    incident-report path is untouched: it anchors to ``incident_id``, never a
    session-ids coverage list, so a development session linked to an incident
    still renders.
    """

    def test_shift_summary_rejects_development_session(self) -> None:
        app_client = TestClient(create_app())
        dev_id = _development_session(app_client, "alice")
        response = _create_draft(app_client, "alice", [dev_id])
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "development sessions are not shift-summary material" in detail
        assert dev_id in detail

    def test_shift_summary_rejects_mixed_operation_and_development(self) -> None:
        # Never silently dropped: one development id rejects the whole request.
        app_client = TestClient(create_app())
        op_id = _session(app_client, "alice")
        dev_id = _development_session(app_client, "alice")
        response = _create_draft(app_client, "alice", [op_id, dev_id])
        assert response.status_code == 400
        assert dev_id in response.json()["detail"]

    def test_all_operation_shift_summary_still_accepted(self) -> None:
        app_client = TestClient(create_app())
        op_id = _session(app_client, "alice")
        response = _create_draft(app_client, "alice", [op_id])
        assert response.status_code == 201

    def test_incident_report_path_unaffected(self, monkeypatch) -> None:
        # The guard is shift_summary-only: an incident whose linked session is a
        # development session still renders (owner coverage), because the
        # incident path anchors to incident_id, never a session-ids list.
        app_client = TestClient(create_app())
        dev_id = _development_session(app_client, "alice")

        async def _fetch(settings, request_id, incident_id):
            return _bundle_with(dev_id)

        monkeypatch.setattr(v2_routes, "fetch_incident_bundle", _fetch)
        response = _create_incident_report(app_client, "alice")
        assert response.status_code == 201
        assert response.json()["digest"]["session"]["status"] == "owner"

