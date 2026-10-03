"""Per-source sync engine (SPEC-014 R-2).

One asyncio task per configured source, each running an independent loop:
materialize the source (git checkout or local directory), ingest + validate
every document, then swap the validated snapshot into the store atomically.
A failed cycle keeps the previously served snapshot and is recorded in the
per-source status plus the ``skills_syncs_total`` counter — one source's
failure never disturbs another source.
"""

from __future__ import annotations

import asyncio
import logging
import random
import shutil
import subprocess
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from opentelemetry import trace

from skills_hub.core import metrics
from skills_hub.core.config import SkillsSettings, SourceSpec
from skills_hub.schemas.skill import Skill
from skills_hub.services.audit_emitter import build_audit_event, emit_audit_event
from skills_hub.services.ingestion import (
    COMPOSITION_KIND,
    Rejection,
    ingest_directory,
)
from skills_hub.services.skill_store import SkillStore

LOGGER = logging.getLogger(__name__)

# No-op until a TracerProvider is installed (OTEL_ENABLED), so importing this
# module never activates telemetry on its own.
TRACER = trace.get_tracer("skills_hub.sync")

MAX_REPORTED_REJECTIONS = 50
GIT_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class SourceStatus:
    """Last sync outcome for one source (served by the status endpoint)."""

    source_id: str
    source_type: str
    last_sync_at: datetime | None = None
    last_error: str | None = None
    ref: str | None = None
    accepted: int = 0
    rejections: tuple[Rejection, ...] = field(default_factory=tuple)


def _rejection_category(reason: str) -> str:
    """Bounded label for the rejection counter (cardinality guard)."""
    lowered = reason.lower()
    if lowered.startswith("duplicate"):
        return "duplicate_slug"
    # SPEC-057 R-2: the composition *resolution* rejections (an unresolved or
    # nested sub-skill, rendered by sync's ``_resolve_compositions``) are a
    # distinct failure mode from a structural frontmatter error, so they get
    # their own bounded label. The *structural* composition rejections render as
    # "sub_skill N: ...", "a composition declares no ...", "more than N
    # sub_skills", "kind: composition requires ...", or "sub_skills requires
    # kind: composition" — none start with "composition", so they stay in the
    # frontmatter bucket exactly as the other per-field bounds do.
    if lowered.startswith("composition"):
        return "composition"
    if "body exceeds" in lowered:
        return "size"
    # SPEC-055 R-3: the step list is the second size-bounded artifact, so its
    # two resource ceilings (step count, encoded bytes) belong in this bucket
    # rather than falling through to ``frontmatter``. Gated on ``steps`` so the
    # neighbouring "more than N tags" bound stays where it always was.
    if "steps" in lowered and (
        "exceed" in lowered or "more than" in lowered
    ):
        return "size"
    if "unreadable" in lowered:
        return "unreadable"
    if "slug" in lowered:
        return "path"
    if "not found" in lowered:
        return "missing_source"
    return "frontmatter"


# --- Git materialization ------------------------------------------------------


def _with_token(url: str, token: str | None) -> str:
    """Inject an x-access-token into an https clone URL (pod-local only)."""
    if not token or not url.startswith("https://"):
        return url
    parts = urlsplit(url)
    netloc = f"x-access-token:{token}@{parts.hostname}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _git(args: list[str]) -> None:
    subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def _git_checkout(
    source_id: str, url: str, ref: str, dest: Path, token: str | None
) -> str:
    """Clone or update a disposable checkout; return the resolved commit SHA.

    Any corruption is unrecoverable by design: the directory is a cache, so
    failures fall back to a fresh clone on the next cycle.
    """
    with TRACER.start_as_current_span(
        "skills.git.checkout",
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        span.set_attribute("source.id", source_id)
        span.set_attribute("source.ref", ref)
        try:
            auth_url = _with_token(url, token)
            if (dest / ".git").is_dir():
                _git(["-C", str(dest), "fetch", "--depth", "1", "origin", ref])
                _git(["-C", str(dest), "reset", "--hard", "FETCH_HEAD"])
            else:
                if dest.exists():
                    shutil.rmtree(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                clone_args = ["clone", "--depth", "1"]
                if ref != "HEAD":
                    clone_args += ["--branch", ref]
                _git([*clone_args, auth_url, str(dest)])
            result = subprocess.run(
                ["git", "-C", str(dest), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
            )
            return result.stdout.strip()
        except Exception as exc:
            # git quotes its argv (including the token-injected clone URL) in
            # error text; scrub the credential before it lands in a span event.
            message = str(exc)
            if token:
                message = message.replace(token, "***")
            span.set_status(
                trace.Status(trace.StatusCode.ERROR, "git checkout failed")
            )
            span.add_event("checkout.error", {"message": message})
            raise


# --- Sync manager --------------------------------------------------------------


class SyncManager:
    """Owns the per-source sync loops and the status registry."""

    def __init__(self, settings: SkillsSettings, store: SkillStore) -> None:
        self._settings = settings
        self._store = store
        self._statuses: dict[str, SourceStatus] = {
            spec.source_id: SourceStatus(
                source_id=spec.source_id, source_type=spec.type
            )
            for spec in settings.sources
        }
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        for spec in self._settings.sources:
            self._tasks.append(
                asyncio.create_task(self._loop(spec), name=f"sync-{spec.source_id}")
            )

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def _loop(self, spec: SourceSpec) -> None:
        while True:
            await self.sync_once(spec)
            # Small jitter so multiple sources never stampede together.
            jitter = random.uniform(-0.05, 0.05)
            interval = max(1.0, self._settings.sync_interval_seconds * (1 + jitter))
            await asyncio.sleep(interval)

    async def sync_once(self, spec: SourceSpec) -> SourceStatus:
        """Run one sync cycle for a source; never raises."""
        now = datetime.now(timezone.utc)
        with TRACER.start_as_current_span(
            "skills.sync",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            span.set_attribute("source.id", spec.source_id)
            span.set_attribute("source.type", spec.type)
            try:
                root, ref = await self._materialize(spec)
                result = await asyncio.to_thread(
                    ingest_directory,
                    spec.source_id,
                    root,
                    ref,
                    now,
                    self._settings.composition_max_sub_skills,
                )
                # SPEC-057 R-2: resolve each composition's sub-skill references
                # against the catalog — this source's fresh records overlaid on
                # ``store.get()`` for cross-source ids — dropping + rejecting any
                # composition whose sub-skill is unresolved or is itself a
                # composition, and deriving the survivors' display risk_class.
                # The rejections ride the existing per-source status, rejected
                # count and ``skills_synced`` event: no new audit event type.
                resolved_records, composition_rejections = (
                    await self._resolve_compositions(
                        spec.source_id, result.records
                    )
                )
                result.records = resolved_records
                result.rejections.extend(composition_rejections)
                await self._store.replace_source(spec.source_id, result.records)
                # SPEC-066 R-2: refresh the corpus statistics (IDF ``df``) now
                # that the catalog changed, so the shared scorer's weighting
                # tracks the population. A full-catalog Python pass that rides
                # this cycle, so ``df`` lags a change by at most one sync
                # interval (bounded staleness, recorded in the plan). It runs
                # only after a successful ``replace_source``; a failed cycle
                # raises before this point and leaves the prior snapshot — and
                # the prior statistics — intact.
                await self._store.refresh_statistics()
                status = SourceStatus(
                    source_id=spec.source_id,
                    source_type=spec.type,
                    last_sync_at=now,
                    last_error=None,
                    ref=ref,
                    accepted=len(result.records),
                    rejections=tuple(result.rejections[:MAX_REPORTED_REJECTIONS]),
                )
                metrics.record_sync(spec.source_id, "ok")
                metrics.set_source_size(spec.source_id, status.accepted)
                for rejection in result.rejections:
                    metrics.record_rejected(_rejection_category(rejection.reason))
                # SPEC-029 R-4: one usage-trail event per cycle; sync has no
                # inbound request, so the builder's "unknown" fallback applies.
                emit_audit_event(
                    self._settings,
                    build_audit_event(
                        "skills_synced",
                        None,
                        "success",
                        details={
                            "source_id": spec.source_id,
                            "source_type": spec.type,
                            "ref": ref,
                            "accepted": status.accepted,
                            "rejected": len(result.rejections),
                        },
                    ),
                )
                span.set_attribute("result", "ok")
                span.set_attribute("accepted", status.accepted)
                span.set_status(trace.Status(trace.StatusCode.OK))
                LOGGER.info(
                    "source synced",
                    extra={
                        "source_id": spec.source_id,
                        "ref": ref,
                        "accepted": status.accepted,
                        "rejected": len(result.rejections),
                    },
                )
            except Exception as exc:  # noqa: BLE001 - a cycle must never die
                previous = self._statuses[spec.source_id]
                # A failed `git clone` quotes its argv verbatim in the exception,
                # which includes the token-injected URL; error messages reach the
                # auth-exempt status endpoint and the logs, so the credential
                # must never appear in them.
                message = str(exc)
                token = self._settings.git_tokens.get(spec.source_id)
                if token:
                    message = message.replace(token, "***")
                status = replace(previous, last_sync_at=now, last_error=message)
                metrics.record_sync(spec.source_id, "error")
                emit_audit_event(
                    self._settings,
                    build_audit_event(
                        "skills_synced",
                        None,
                        "error",
                        details={
                            "source_id": spec.source_id,
                            "source_type": spec.type,
                            "error": message,
                        },
                    ),
                )
                span.set_attribute("result", "error")
                span.set_status(
                    trace.Status(trace.StatusCode.ERROR, "sync failed")
                )
                LOGGER.error(
                    "source sync failed; keeping previous snapshot",
                    extra={"source_id": spec.source_id, "error": message},
                )
            self._statuses[spec.source_id] = status
            return status

    async def _resolve_compositions(
        self, source_id: str, records: list[Skill]
    ) -> tuple[list[Skill], list[Rejection]]:
        """Resolve each composition's sub-skill references (SPEC-057 R-2).

        Runs between ``ingest_directory`` (pure per-document parsing, no store
        handle) and ``replace_source``, where ``self._store`` is reachable. The
        structural facts a document proves alone were already checked in
        ingestion; the *cross-skill* facts — does each referenced sub-skill
        resolve, is it itself a composition — need the catalog and are checked
        here.

        The resolution index is *this source's fresh records overlaid on
        ``store.get()`` for cross-source ids*, so a composition and its sub-skills
        in one source resolve within a single cycle, while a cross-source
        reference resolves only after its own source has synced at least once
        (eventual consistency — sync repeats every ``SKILLS_SYNC_INTERVAL_
        SECONDS``). A composition whose sub-skill is unresolved or is itself a
        composition is **dropped and rejected** — never silently served, never
        degraded to a knowledge skill. Single-target needs no check: a sub-skill's
        ``web_target`` is a scalar, so it declares exactly one browser target or
        none (infra), never several, and SPEC-055 R-4 already validated its blast
        radius at graduation (R-2 re-checks presence + single-target, not the
        trace). A surviving composition's display ``risk_class`` is derived
        (``write`` if any resolved sub-skill is ``write``, else ``read``) and
        persisted via ``model_copy`` so ``summary()`` carries it to the list badge.
        """
        fresh = {record.skill_id: record for record in records}
        resolved: list[Skill] = []
        rejections: list[Rejection] = []
        for record in records:
            if record.kind != COMPOSITION_KIND:
                resolved.append(record)
                continue
            derived_risk_class = "read"
            failure: str | None = None
            for ref in record.sub_skills or []:
                # Prefer this source's fresh record; fall back to the store for a
                # cross-source id, which resolves only once that source synced.
                sub_skill = fresh.get(ref.skill_id) or await self._store.get(
                    ref.skill_id
                )
                if sub_skill is None:
                    failure = (
                        f"composition sub_skill '{ref.skill_id}' does not "
                        "resolve to a published skill"
                    )
                    break
                if sub_skill.kind == COMPOSITION_KIND:
                    failure = (
                        f"composition sub_skill '{ref.skill_id}' is itself a "
                        "composition (no nesting in Phase 1)"
                    )
                    break
                if sub_skill.risk_class == "write":
                    derived_risk_class = "write"
            if failure is not None:
                rejections.append(
                    Rejection(source_id, record.source_path, failure)
                )
                continue
            resolved.append(
                record.model_copy(update={"risk_class": derived_risk_class})
            )
        return resolved, rejections

    async def _materialize(self, spec: SourceSpec) -> tuple[Path, str]:
        """Return (readable root directory, ref marker) for one source."""
        if spec.type == "local":
            return Path(spec.path), "local"
        dest = Path(self._settings.data_path) / "sources" / spec.source_id
        token = self._settings.git_tokens.get(spec.source_id)
        sha = await asyncio.to_thread(
            _git_checkout, spec.source_id, spec.url, spec.ref, dest, token
        )
        root = dest / spec.path if spec.path else dest
        if not root.is_dir():
            raise FileNotFoundError(
                f"configured subpath {spec.path!r} not found in checkout "
                f"of source {spec.source_id}"
            )
        return root, sha

    def status_report(self) -> list[dict]:
        """JSON-ready per-source report (bounded rejection lists)."""
        report = []
        for source_id in sorted(self._statuses):
            status = self._statuses[source_id]
            report.append(
                {
                    "source_id": status.source_id,
                    "type": status.source_type,
                    "last_sync_at": (
                        status.last_sync_at.isoformat()
                        if status.last_sync_at
                        else None
                    ),
                    "last_error": status.last_error,
                    "ref": status.ref,
                    "accepted": status.accepted,
                    "rejections": [
                        {"path": r.path, "reason": r.reason}
                        for r in status.rejections
                    ],
                }
            )
        return report
