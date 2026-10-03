"""Skill store tests (SPEC-014 R-2/R-3).

Exercises the in-memory store (per-source atomic swap, get/list/search with
filters, pagination) and the Postgres adapter against a fake driver double.
"""

from __future__ import annotations

import asyncio
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from skills_hub.core.config import SkillsSettings
from skills_hub.schemas.skill import Skill
from skills_hub.services.skill_store import (
    InMemorySkillStore,
    PostgresSkillStore,
    StoreError,
    build_skill_store,
)

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)


def _run(coro):
    return asyncio.run(coro)


def _skill(
    skill_id: str,
    tags=None,
    body: str = "body",
    title="T",
    web_target=None,
    risk_class=None,
    flow_intent=None,
    kind=None,
    steps=None,
    sub_skills=None,
) -> Skill:
    return Skill(
        skill_id=skill_id,
        source_id=skill_id.split("/")[0],
        source_path=f"{skill_id.split('/')[-1]}.md",
        source_ref="local",
        title=title,
        description="summary",
        tags=tags,
        web_target=web_target,
        risk_class=risk_class,
        flow_intent=flow_intent,
        kind=kind,
        steps=steps,
        sub_skills=sub_skills,
        updated_at=NOW,
        body=body,
    )


# SPEC-055 R-3: a graduated browser flow's replay list — credential values are
# references to a named credential set, never literals.
EXECUTABLE_STEPS = [
    {"tool": "web.navigate", "args": {"url": "https://admin.internal/login"}},
    {
        "tool": "web.fill_credential",
        "args": {"ref": 1, "credential_set": "admin-portal", "field": "password"},
    },
    {
        "tool": "web.click",
        "args": {"selector": "#submit"},
        "expect": "the user list renders",
    },
]


def _executable_skill(skill_id: str = "a/reset-password") -> Skill:
    return _skill(
        skill_id,
        web_target="https://admin.internal/login",
        risk_class="write",
        kind="executable_flow",
        steps=EXECUTABLE_STEPS,
    )


# SPEC-057 R-1: a composition's ordered sub-skill reference list. The derived
# display ``risk_class`` is persisted at sync (write because a sub-skill is
# write); the composition itself declares no web_target, steps, or author
# risk_class.
COMPOSITION_SUB_SKILLS = [
    {"skill_id": "samples/password-reset-resetacmepassword", "note": "Reset first."},
    {"skill_id": "samples/lock-unlock-user-lockunlockuser"},
]


def _composition_skill(skill_id: str = "a/incident-runbook") -> Skill:
    return _skill(
        skill_id,
        kind="composition",
        risk_class="write",
        sub_skills=COMPOSITION_SUB_SKILLS,
    )


class InMemoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemorySkillStore()

    def test_replace_source_swaps_atomically(self) -> None:
        _run(self.store.replace_source("a", [_skill("a/one")]))
        _run(self.store.replace_source("a", [_skill("a/two"), _skill("a/three")]))
        self.assertEqual(_run(self.store.count()), 2)
        self.assertIsNone(_run(self.store.get("a/one")))
        self.assertIsNotNone(_run(self.store.get("a/two")))

    def test_replace_source_isolates_sources(self) -> None:
        _run(self.store.replace_source("a", [_skill("a/one")]))
        _run(self.store.replace_source("b", [_skill("b/one")]))
        _run(self.store.replace_source("a", []))  # source a fails sync -> empty
        self.assertEqual(_run(self.store.count()), 1)
        self.assertIsNotNone(_run(self.store.get("b/one")))

    def test_cross_source_duplicate_slugs_are_legal(self) -> None:
        _run(self.store.replace_source("a", [_skill("a/runbook")]))
        _run(self.store.replace_source("b", [_skill("b/runbook")]))
        self.assertEqual(_run(self.store.count()), 2)

    def test_list_orders_by_skill_id_and_paginates(self) -> None:
        _run(
            self.store.replace_source(
                "a", [_skill("a/c"), _skill("a/a"), _skill("a/b")]
            )
        )
        page, total = _run(self.store.list(0, 2))
        self.assertEqual([s.skill_id for s in page], ["a/a", "a/b"])
        self.assertEqual(total, 3)
        page, _ = _run(self.store.list(2, 2))
        self.assertEqual([s.skill_id for s in page], ["a/c"])

    def test_list_filters_by_source_and_tag(self) -> None:
        _run(
            self.store.replace_source(
                "a",
                [_skill("a/one", tags=["Alert"]), _skill("a/two")],
            )
        )
        _run(self.store.replace_source("b", [_skill("b/one", tags=["alert"])]))
        page, total = _run(self.store.list(0, 100, source="b"))
        self.assertEqual(total, 1)
        # Tag filter is case-insensitive.
        page, total = _run(self.store.list(0, 100, tag="alert"))
        self.assertEqual(total, 2)

    def test_search_ranks_and_excludes_zero_scores(self) -> None:
        _run(
            self.store.replace_source(
                "a",
                [
                    _skill("a/hit", title="Pod Troubleshooting"),
                    _skill("a/miss", title="Node Debugging"),
                ],
            )
        )
        hits = _run(self.store.search("pod", 5))
        self.assertEqual([h.skill.skill_id for h in hits], ["a/hit"])

    def test_get_unknown_returns_none(self) -> None:
        self.assertIsNone(_run(self.store.get("a/nope")))

    def test_get_round_trips_flow_intent(self) -> None:
        # SPEC-053 R-1: the in-memory backend stores whole Skill objects, so
        # flow_intent round-trips without a column list — the parity check
        # against the Postgres backend's explicit persistence.
        _run(
            self.store.replace_source(
                "a",
                [
                    _skill(
                        "a/check",
                        web_target="http://target:8080/",
                        risk_class="write",
                        flow_intent="Submit the password reset for the user.",
                    )
                ],
            )
        )
        skill = _run(self.store.get("a/check"))
        self.assertIsNotNone(skill)
        self.assertEqual(
            skill.flow_intent, "Submit the password reset for the user."
        )
        self.assertEqual(
            skill.summary()["flow_intent"],
            "Submit the password reset for the user.",
        )

    def test_get_round_trips_executable_flow_steps(self) -> None:
        # SPEC-055 R-3: the in-memory backend stores whole Skill objects, so
        # the replay list round-trips for free — which is exactly why the
        # Postgres backend's explicit column persistence needs its own test
        # (the SPEC-050 dual-backend field-drop lesson).
        _run(self.store.replace_source("a", [_executable_skill()]))
        skill = _run(self.store.get("a/reset-password"))
        self.assertIsNotNone(skill)
        self.assertEqual(skill.kind, "executable_flow")
        self.assertEqual([step.tool for step in skill.steps], [
            "web.navigate", "web.fill_credential", "web.click",
        ])
        # Order and arguments are the replay contract; a re-sorted or
        # arg-stripped list would replay the wrong flow.
        self.assertEqual(
            skill.steps[1].args,
            {"ref": 1, "credential_set": "admin-portal", "field": "password"},
        )
        self.assertEqual(skill.steps[2].expect, "the user list renders")
        self.assertEqual(skill.summary()["kind"], "executable_flow")

    def test_a_knowledge_skill_omits_the_new_keys(self) -> None:
        # Additive: the v1 shape is byte-identical, so no existing consumer
        # sees a ``kind``/``steps`` key it did not ask for.
        _run(self.store.replace_source("a", [_skill("a/knowledge")]))
        skill = _run(self.store.get("a/knowledge"))
        self.assertIsNotNone(skill)
        self.assertIsNone(skill.kind)
        self.assertIsNone(skill.steps)
        self.assertNotIn("kind", skill.summary())
        self.assertNotIn("steps", skill.summary())

    def test_get_round_trips_composition_sub_skills(self) -> None:
        # SPEC-057 R-1: the in-memory backend stores whole Skill objects, so
        # the ordered sub-skill reference list round-trips for free — the
        # parity check against the Postgres backend's explicit column
        # persistence (the SPEC-050 dual-backend field-drop lesson). Order and
        # note are the runbook contract; a re-sorted or note-stripped list
        # would ground the wrong sequence.
        _run(self.store.replace_source("a", [_composition_skill()]))
        skill = _run(self.store.get("a/incident-runbook"))
        self.assertIsNotNone(skill)
        self.assertEqual(skill.kind, "composition")
        self.assertEqual(skill.risk_class, "write")
        self.assertEqual(
            [ref.skill_id for ref in skill.sub_skills],
            [
                "samples/password-reset-resetacmepassword",
                "samples/lock-unlock-user-lockunlockuser",
            ],
        )
        self.assertEqual(skill.sub_skills[0].note, "Reset first.")
        self.assertIsNone(skill.sub_skills[1].note)
        # The derived risk_class rides summary() to the Skills-list badge.
        self.assertEqual(skill.summary()["risk_class"], "write")
        self.assertEqual(len(skill.summary()["sub_skills"]), 2)

    def test_a_non_composition_skill_omits_sub_skills(self) -> None:
        # Additive: a knowledge/executable_flow skill carries no reference
        # list, so ``sub_skills`` stays absent from its served shape.
        _run(self.store.replace_source("a", [_executable_skill()]))
        skill = _run(self.store.get("a/reset-password"))
        self.assertIsNotNone(skill)
        self.assertIsNone(skill.sub_skills)
        self.assertNotIn("sub_skills", skill.summary())

    def test_ready_and_close_are_noops(self) -> None:
        self.assertTrue(_run(self.store.ready()))
        self.assertIsNone(_run(self.store.close()))

    def test_prune_sources_drops_unconfigured_sources(self) -> None:
        _run(self.store.replace_source("a", [_skill("a/one")]))
        _run(self.store.replace_source("b", [_skill("b/one"), _skill("b/two")]))
        removed = _run(self.store.prune_sources(["b"]))
        self.assertEqual(removed, 1)
        self.assertIsNone(_run(self.store.get("a/one")))
        self.assertEqual(_run(self.store.count()), 2)

    def test_prune_sources_with_empty_config_clears_the_store(self) -> None:
        _run(self.store.replace_source("a", [_skill("a/one")]))
        removed = _run(self.store.prune_sources([]))
        self.assertEqual(removed, 1)
        self.assertEqual(_run(self.store.count()), 0)


class PostgresStoreAdapterTests(unittest.TestCase):
    """SQL shape against a fake psycopg driver (audit-service pattern)."""

    def _fake_connect(self, calls: list[dict], rows=None):
        class FakeCursor:
            rowcount = 1

            async def execute(self, sql, params=None):
                calls.append({"sql": sql, "params": params})

            async def fetchall(self):
                return rows or []

            async def fetchone(self):
                return (rows[0] if rows else None)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        class FakeConn:
            def cursor(self):
                return FakeCursor()

            async def commit(self):
                return None

            async def close(self):
                return None

        @asynccontextmanager
        async def connect():
            yield FakeConn()

        return connect

    def test_replace_source_deletes_then_inserts_in_one_connection(self) -> None:
        calls: list[dict] = []
        store = PostgresSkillStore(
            "postgresql://fake", connect=self._fake_connect(calls)
        )
        replaced = _run(
            store.replace_source("a", [_skill("a/one"), _skill("a/two")])
        )
        self.assertEqual(replaced, 2)
        self.assertIn("DELETE FROM skills", calls[0]["sql"])
        self.assertEqual(calls[0]["params"], {"source_id": "a"})
        self.assertEqual(calls[1]["sql"].lstrip()[:6], "INSERT")
        self.assertEqual(calls[1]["params"]["skill_id"], "a/one")
        self.assertEqual(calls[1]["params"]["tags"], None)
        self.assertEqual(len(calls), 3)

    def test_replace_source_persists_web_flow_declaration(self) -> None:
        # SPEC-049 R-3: web_target/risk_class must survive the Postgres
        # round-trip — the gateway binds flows from the detail response.
        calls: list[dict] = []
        store = PostgresSkillStore(
            "postgresql://fake", connect=self._fake_connect(calls)
        )
        _run(
            store.replace_source(
                "a",
                [
                    _skill(
                        "a/check",
                        web_target="http://target:8080/",
                        risk_class="write",
                    )
                ],
            )
        )
        self.assertIn("web_target", calls[1]["sql"])
        self.assertEqual(calls[1]["params"]["web_target"], "http://target:8080/")
        self.assertEqual(calls[1]["params"]["risk_class"], "write")

    def test_replace_source_persists_flow_intent(self) -> None:
        # SPEC-053 R-1: flow_intent must survive the Postgres round-trip on
        # both the INSERT params and the column list, or the deployed backend
        # silently drops the card's decision line (the SPEC-050 dual-backend
        # field-drop lesson — the in-memory backend carries it for free).
        calls: list[dict] = []
        store = PostgresSkillStore(
            "postgresql://fake", connect=self._fake_connect(calls)
        )
        _run(
            store.replace_source(
                "a",
                [
                    _skill(
                        "a/check",
                        web_target="http://target:8080/",
                        risk_class="write",
                        flow_intent="Submit the password reset for the user.",
                    )
                ],
            )
        )
        self.assertIn("flow_intent", calls[1]["sql"])
        self.assertEqual(
            calls[1]["params"]["flow_intent"],
            "Submit the password reset for the user.",
        )

    def test_replace_source_persists_executable_flow_columns(self) -> None:
        # SPEC-055 R-3: ``kind``/``steps`` must survive the Postgres
        # round-trip on both the INSERT params and the column list, or the
        # deployed backend silently serves a knowledge skill for a graduated
        # flow — and R-5 replay then has no step list to drive.
        from psycopg.types.json import Jsonb

        calls: list[dict] = []
        store = PostgresSkillStore(
            "postgresql://fake", connect=self._fake_connect(calls)
        )
        _run(store.replace_source("a", [_executable_skill()]))
        insert = calls[1]
        self.assertIn("kind", insert["sql"])
        self.assertIn("steps", insert["sql"])
        self.assertEqual(insert["params"]["kind"], "executable_flow")
        # ``steps`` is JSONB: psycopg adapts a bare list only through the
        # explicit ``Jsonb`` wrapper ("cannot adapt type 'list'").
        self.assertIsInstance(insert["params"]["steps"], Jsonb)
        # The column stores the envelope's own dump, so a step that does not
        # declare ``expect`` materializes it as JSON null. Both backends still
        # read the step back as ``expect=None``, and ``summary()``'s
        # ``exclude_none`` keeps the served shape identical either way.
        self.assertEqual(
            insert["params"]["steps"].obj,
            [
                {
                    "tool": "web.navigate",
                    "args": {"url": "https://admin.internal/login"},
                    "expect": None,
                },
                {
                    "tool": "web.fill_credential",
                    "args": {
                        "ref": 1,
                        "credential_set": "admin-portal",
                        "field": "password",
                    },
                    "expect": None,
                },
                {
                    "tool": "web.click",
                    "args": {"selector": "#submit"},
                    "expect": "the user list renders",
                },
            ],
        )

    def test_replace_source_keeps_a_knowledge_skill_steps_null(self) -> None:
        # An absent step list is SQL NULL, never JSON ``null``: the row-map
        # guard reads NULL back as ``None``, so the two backends agree.
        calls: list[dict] = []
        store = PostgresSkillStore(
            "postgresql://fake", connect=self._fake_connect(calls)
        )
        _run(store.replace_source("a", [_skill("a/knowledge")]))
        self.assertIsNone(calls[1]["params"]["kind"])
        self.assertIsNone(calls[1]["params"]["steps"])

    def test_get_maps_web_flow_columns(self) -> None:
        calls: list[dict] = []
        row = (
            "a/check", "a", "check.md", "local", "T", "summary",
            None, None, None, NOW, "body",
            "http://target:8080/", "write", "Submit the reset.",
            None, None, None,
        )
        store = PostgresSkillStore(
            "postgresql://fake", connect=self._fake_connect(calls, rows=[row])
        )
        skill = _run(store.get("a/check"))
        self.assertIsNotNone(skill)
        self.assertEqual(skill.web_target, "http://target:8080/")
        self.assertEqual(skill.risk_class, "write")
        self.assertEqual(skill.flow_intent, "Submit the reset.")

    def test_get_maps_executable_flow_columns(self) -> None:
        # JSONB decodes to a Python list, which the model coerces back into
        # ``SkillStep`` objects — the shape R-5 replay reads.
        calls: list[dict] = []
        row = (
            "a/reset-password", "a", "reset.md", "local", "T", "summary",
            None, None, None, NOW, "body",
            "https://admin.internal/login", "write", None,
            "executable_flow", EXECUTABLE_STEPS, None,
        )
        store = PostgresSkillStore(
            "postgresql://fake", connect=self._fake_connect(calls, rows=[row])
        )
        skill = _run(store.get("a/reset-password"))
        self.assertIsNotNone(skill)
        self.assertEqual(skill.kind, "executable_flow")
        self.assertEqual(len(skill.steps), 3)
        self.assertEqual(skill.steps[0].tool, "web.navigate")
        self.assertEqual(skill.steps[2].expect, "the user list renders")

    def test_replace_source_persists_composition_sub_skills(self) -> None:
        # SPEC-057 R-1: ``sub_skills`` must survive the Postgres round-trip on
        # both the INSERT params and the column list, or the deployed backend
        # silently serves a composition with no reference list — the runbook
        # would ground nothing (the SPEC-050 dual-backend field-drop lesson).
        from psycopg.types.json import Jsonb

        calls: list[dict] = []
        store = PostgresSkillStore(
            "postgresql://fake", connect=self._fake_connect(calls)
        )
        _run(store.replace_source("a", [_composition_skill()]))
        insert = calls[1]
        self.assertIn("sub_skills", insert["sql"])
        self.assertEqual(insert["params"]["kind"], "composition")
        # ``sub_skills`` is JSONB: psycopg adapts a bare list only through the
        # explicit ``Jsonb`` wrapper. The derived display risk_class is
        # persisted beside it so summary() carries it to the list badge.
        self.assertIsInstance(insert["params"]["sub_skills"], Jsonb)
        self.assertEqual(insert["params"]["risk_class"], "write")
        # The column stores the envelope's own dump, so an item that omits
        # ``note`` materializes it as JSON null — read back as note=None.
        self.assertEqual(
            insert["params"]["sub_skills"].obj,
            [
                {
                    "skill_id": "samples/password-reset-resetacmepassword",
                    "note": "Reset first.",
                },
                {
                    "skill_id": "samples/lock-unlock-user-lockunlockuser",
                    "note": None,
                },
            ],
        )

    def test_replace_source_keeps_a_non_composition_sub_skills_null(self) -> None:
        # An absent reference list is SQL NULL, never JSON ``null``: the
        # row-map guard reads NULL back as ``None``, so the two backends agree.
        calls: list[dict] = []
        store = PostgresSkillStore(
            "postgresql://fake", connect=self._fake_connect(calls)
        )
        _run(store.replace_source("a", [_executable_skill()]))
        self.assertIsNone(calls[1]["params"]["sub_skills"])

    def test_get_maps_composition_sub_skills(self) -> None:
        # JSONB decodes to a Python list, which the model coerces back into
        # ``SubSkillRef`` objects in declared order — the shape R-6's read-path
        # projection and the portal viewer read.
        calls: list[dict] = []
        row = (
            "a/incident-runbook", "a", "runbook.md", "local", "T", "summary",
            None, None, None, NOW, "body",
            None, "write", None,
            "composition", None, COMPOSITION_SUB_SKILLS,
        )
        store = PostgresSkillStore(
            "postgresql://fake", connect=self._fake_connect(calls, rows=[row])
        )
        skill = _run(store.get("a/incident-runbook"))
        self.assertIsNotNone(skill)
        self.assertEqual(skill.kind, "composition")
        self.assertEqual(skill.risk_class, "write")
        self.assertIsNone(skill.steps)
        self.assertEqual(len(skill.sub_skills), 2)
        self.assertEqual(
            skill.sub_skills[0].skill_id,
            "samples/password-reset-resetacmepassword",
        )
        self.assertEqual(skill.sub_skills[0].note, "Reset first.")
        self.assertIsNone(skill.sub_skills[1].note)

    def test_search_uses_full_text_prefilter(self) -> None:
        calls: list[dict] = []
        row = (
            "a/hit", "a", "hit.md", "local", "Pod", "summary",
            ["pod"], None, None, NOW, "pod body", None, None, None,
            None, None, None,
        )
        store = PostgresSkillStore(
            "postgresql://fake", connect=self._fake_connect(calls, rows=[row])
        )
        hits = _run(store.search("pod", 5))
        self.assertIn("to_tsquery", calls[0]["sql"])
        # SPEC-066 R-5: each token ORs its exact and prefix form so a
        # CamelCase-derived part reaches the single indexed lexeme it prefixes.
        self.assertEqual(calls[0]["params"]["query"], "pod | pod:*")
        self.assertEqual([h.skill.skill_id for h in hits], ["a/hit"])

    def test_search_joins_multi_word_queries_with_or(self) -> None:
        """OR semantics keep partial matches for the shared scorer;
        plainto_tsquery would AND the words and return nothing."""
        calls: list[dict] = []
        store = PostgresSkillStore(
            "postgresql://fake", connect=self._fake_connect(calls, rows=[])
        )
        hits = _run(store.search("kubernetes incident", 5))
        self.assertEqual(hits, [])
        # SPEC-066 R-5: the OR-join is kept (never plainto_tsquery, which would
        # AND the words and drop partial matches); each token now also ORs its
        # prefix form so a CamelCase part reaches the lexeme it prefixes.
        self.assertEqual(
            calls[0]["params"]["query"],
            "kubernetes | kubernetes:* | incident | incident:*",
        )
        self.assertNotIn("plainto_tsquery", calls[0]["sql"])

    def test_search_without_tokens_skips_the_query(self) -> None:
        calls: list[dict] = []
        store = PostgresSkillStore(
            "postgresql://fake", connect=self._fake_connect(calls, rows=[])
        )
        hits = _run(store.search("!!!", 5))
        self.assertEqual(hits, [])
        self.assertEqual(calls, [])

    def test_list_applies_source_filter(self) -> None:
        calls: list[dict] = []
        # No page rows: the count query consumes the fake result, so the
        # recorded SQL still shows the WHERE clause shape.
        store = PostgresSkillStore(
            "postgresql://fake", connect=self._fake_connect(calls, rows=[])
        )
        _run(store.list(0, 10, source="a"))
        self.assertTrue(
            any("source_id = %(source)s" in call["sql"] for call in calls)
        )

    def test_tag_filter_uses_exact_case_insensitive_match(self) -> None:
        """ILIKE would treat the parameter as a pattern ('kube%' matching
        wildcards) and diverge from the in-memory backend; exact
        case-insensitive equality keeps the backends byte-identical."""
        calls: list[dict] = []
        store = PostgresSkillStore(
            "postgresql://fake", connect=self._fake_connect(calls, rows=[])
        )
        _run(store.list(0, 10, tag="kube%"))
        tag_calls = [
            call
            for call in calls
            if call["params"] and call["params"].get("tag") == "kube%"
        ]
        self.assertTrue(tag_calls)
        self.assertIn("lower(t) = lower(%(tag)s)", tag_calls[0]["sql"])
        self.assertNotIn("ILIKE", tag_calls[0]["sql"])

    def test_prune_sources_deletes_unconfigured_source_rows(self) -> None:
        calls: list[dict] = []
        store = PostgresSkillStore(
            "postgresql://fake", connect=self._fake_connect(calls, rows=[])
        )
        removed = _run(store.prune_sources(["a", "b"]))
        self.assertEqual(removed, 1)  # fake cursor rowcount
        self.assertIn("DELETE FROM skills", calls[0]["sql"])
        self.assertIn("NOT (source_id = ANY(%(keep)s))", calls[0]["sql"])
        self.assertEqual(calls[0]["params"], {"keep": ["a", "b"]})


class BuildSkillStoreTests(unittest.TestCase):
    def test_defaults_to_memory_backend(self) -> None:
        store = build_skill_store(SkillsSettings())
        self.assertIsInstance(store, InMemorySkillStore)

    def test_postgres_backend_requires_db_url(self) -> None:
        with self.assertRaises(StoreError):
            build_skill_store(SkillsSettings(store_backend="postgres", db_url=""))

    def test_postgres_backend_selected_with_url(self) -> None:
        store = build_skill_store(
            SkillsSettings(store_backend="postgres", db_url="postgresql://x")
        )
        self.assertIsInstance(store, PostgresSkillStore)


if __name__ == "__main__":
    unittest.main()
