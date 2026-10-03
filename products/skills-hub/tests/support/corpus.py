"""Pinned 18-document retrieval corpus and committed query-set loader (SPEC-066).

R-6 (parity) and R-8 (evaluation) both need the *same* corpus the label fixture
was graded against, rebuilt deterministically offline — no network, no running
cluster. This module reproduces ``semantic-skill-retrieval-labels.json``'s 18
``corpus_snapshot.documents`` byte-for-byte from the repository's own skill
sources:

* **12 platform documents** — a recursive ``ingest_directory`` of
  ``shared/platform-ops/skills`` under ``source_id="platform-skills"``, whose
  path-derived slugs (``slug_from_path`` keeps ``/`` between segments) give the
  ``platform-skills/platform-runbooks/guides/…`` and
  ``platform-skills/sre-alerting/alerts/…`` ids the fixture pins (D01–D12).
* **6 sample documents** — ``samples/acme-admin/<leaf>/skill/*.md`` flat-mounted
  exactly the way ``samples/deploy-samples.sh`` mounts them for the demo suite:
  each document is copied to ``<leaf>-<relpath with '/' → '-'>.md``, dropping the
  ``skill`` category directory, so ``ingest_directory("samples", …)`` yields the
  flattened slugs the fixture pins (D13–D18), e.g.
  ``samples/adhoc-password-reset-resetpasswordadhoc``.

``build_corpus()`` asserts the record counts and zero rejections so a drifted
source tree fails loudly here rather than silently invalidating a measurement.
``verify_corpus_md5()`` is R-8's *first* gate: it asserts every built body's
``md5`` and byte length against the committed fixture before any metric is
computed. The MD5 use here and in R-7's ``rank()`` de-duplication is a
**content-identity key, not a security digest** — it matches the ``body_md5``
the label fixture already pins.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from skills_hub.schemas.skill import Skill
from skills_hub.services.ingestion import ingest_directory

# tests/support/corpus.py -> parents[4] is the repository root.
ROOT = Path(__file__).resolve().parents[4]
# The pinned corpus snapshot date (eval-set §5's "2026-10-01 (18 rows)" corpus).
# ``updated_at`` never enters ``body_md5``, so this only needs to be stable.
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)

PLATFORM_SKILLS_DIR = ROOT / "shared/platform-ops/skills"
SAMPLES_ACME_DIR = ROOT / "samples/acme-admin"
LABELS_PATH = ROOT / "docs/workspace/semantic-skill-retrieval-labels.json"
QUERIES_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "retrieval_queries.json"

EXPECTED_PLATFORM_RECORDS = 12
EXPECTED_SAMPLE_RECORDS = 6
EXPECTED_CORPUS_SIZE = EXPECTED_PLATFORM_RECORDS + EXPECTED_SAMPLE_RECORDS


def _platform_records() -> list[Skill]:
    result = ingest_directory("platform-skills", PLATFORM_SKILLS_DIR, "local", NOW)
    if result.rejections:
        raise AssertionError(
            f"platform-skills ingest rejected {len(result.rejections)} document(s): "
            f"{[r.reason for r in result.rejections]}"
        )
    if len(result.records) != EXPECTED_PLATFORM_RECORDS:
        raise AssertionError(
            f"expected {EXPECTED_PLATFORM_RECORDS} platform-skills records, "
            f"got {len(result.records)} — the source tree drifted from the "
            "pinned corpus"
        )
    return list(result.records)


def _sample_records() -> list[Skill]:
    """Replicate ``deploy-samples.sh``'s flat mount, then ingest it.

    Only ``acme-admin/<leaf>/skill`` directories are walked (the ``app`` and
    ``skill-graduation`` subtrees have no ``skill`` directory, and the ``.venv``
    under ``app`` is never reached), so exactly the six demo skills are mounted.
    """
    with tempfile.TemporaryDirectory(prefix="spec066-samples-") as tmp:
        mount = Path(tmp)
        skill_dirs = sorted(
            path for path in SAMPLES_ACME_DIR.glob("*/skill") if path.is_dir()
        )
        for skill_dir in skill_dirs:
            leaf = skill_dir.parent.name
            for doc in sorted(skill_dir.rglob("*.md")):
                rel = doc.relative_to(skill_dir).as_posix()
                shutil.copyfile(doc, mount / f"{leaf}-{rel.replace('/', '-')}")
        result = ingest_directory("samples", mount, "local", NOW)
    if result.rejections:
        raise AssertionError(
            f"samples ingest rejected {len(result.rejections)} document(s): "
            f"{[r.reason for r in result.rejections]}"
        )
    if len(result.records) != EXPECTED_SAMPLE_RECORDS:
        raise AssertionError(
            f"expected {EXPECTED_SAMPLE_RECORDS} samples records, got "
            f"{len(result.records)} — the sample skill tree drifted from the "
            "pinned corpus"
        )
    return list(result.records)


def build_corpus() -> list[Skill]:
    """The pinned 18-document corpus, deterministically ordered by ``skill_id``."""
    records = _platform_records() + _sample_records()
    records.sort(key=lambda skill: skill.skill_id)
    if len(records) != EXPECTED_CORPUS_SIZE:
        raise AssertionError(
            f"expected a {EXPECTED_CORPUS_SIZE}-document corpus, got {len(records)}"
        )
    ids = [skill.skill_id for skill in records]
    if len(set(ids)) != len(ids):
        raise AssertionError(f"corpus skill_ids are not distinct: {ids}")
    return records


def body_md5(skill: Skill) -> str:
    """The content-identity key the label fixture pins (not a security digest)."""
    return hashlib.md5(skill.body.encode("utf-8")).hexdigest()


def load_labels() -> dict:
    return json.loads(LABELS_PATH.read_text(encoding="utf-8"))


def verify_corpus_md5(records: list[Skill]) -> None:
    """R-8's first gate: assert the built corpus matches the fixture exactly.

    Fails loudly on any mismatch rather than silently invalidating every metric
    computed downstream. Compares the full ``skill_id`` set, then per-document
    ``body_md5`` and ``body_bytes``.
    """
    documents = load_labels()["corpus_snapshot"]["documents"]
    expected = {doc["skill_id"]: doc for doc in documents}
    built = {skill.skill_id: skill for skill in records}
    if set(expected) != set(built):
        missing = sorted(set(expected) - set(built))
        extra = sorted(set(built) - set(expected))
        raise AssertionError(
            f"corpus skill_id set diverged from the label fixture — "
            f"missing={missing} extra={extra}"
        )
    for skill_id, doc in expected.items():
        skill = built[skill_id]
        actual_md5 = body_md5(skill)
        actual_bytes = len(skill.body.encode("utf-8"))
        if actual_md5 != doc["body_md5"] or actual_bytes != doc["body_bytes"]:
            raise AssertionError(
                f"{doc.get('code', '?')} {skill_id}: body_md5/body_bytes mismatch "
                f"(built {actual_md5}/{actual_bytes} vs pinned "
                f"{doc['body_md5']}/{doc['body_bytes']}) — the corpus source "
                "drifted from the graded fixture"
            )


def load_queries() -> list[dict]:
    """The committed R-6 query set: the 63-pool ∪ 18 stratum-C (81 distinct)."""
    data = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    queries = data["queries"]
    texts = [query["text"] for query in queries]
    if len(set(texts)) != len(texts):
        raise AssertionError("the committed query fixture contains duplicate texts")
    return queries
