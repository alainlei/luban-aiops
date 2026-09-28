"""Prometheus metrics surface for execution-runtime (SPEC-005 parity, SPEC-038).

Always-on, collector-independent debug surface implemented directly with
prometheus_client: a minimal RED middleware plus GET /metrics. Metric objects
live at module level so repeated create_app() calls (tests) never
double-register them in the default registry. Conventions:
shared/shared-contracts/observability-conventions.md.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from execution_runtime.core.telemetry import MetricsMirror

# SPEC-065 R-2: every prometheus family in this module is mirrored to an OTel
# instrument of the same exposed name + bounded label set when OTEL_ENABLED, so
# domain metrics reach dashboards over the OTLP push path (ADR-0014) with no
# scraper. The mirror is lazy, fail-open, and a no-op when disabled (see
# core/telemetry.py). Names are exposed sample names (counters keep ``_total``).
OTEL_MIRROR_FAMILIES = (
    ("http_requests_total", "counter", ("method", "handler", "status")),
    ("http_request_duration_seconds", "histogram", ("method", "handler")),
    ("execution_handoffs_total", "counter", ()),
    ("execution_handoff_rejections_total", "counter", ("reason",)),
    ("execution_completions_total", "counter", ("status",)),
    ("execution_late_completions_total", "counter", ()),
    ("audit_emits_total", "counter", ("result",)),
    ("execution_duplicate_claims_total", "counter", ()),
    ("execution_conflicts_total", "counter", ("kind",)),
    ("execution_store_write_failures_total", "counter", ()),
    ("execution_admission_available", "gauge", ()),
    ("execution_unresolved_count", "gauge", ()),
    ("execution_unresolved_oldest_age_seconds", "gauge", ()),
    ("execution_drain_state", "gauge", ()),
)

_MIRROR = MetricsMirror("execution_runtime", OTEL_MIRROR_FAMILIES)

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests processed.",
    ["method", "handler", "status"],
)

HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "handler"],
)

EXECUTION_HANDOFFS = Counter(
    "execution_handoffs_total",
    "Handoff requests accepted past authentication and verification.",
)

EXECUTION_REJECTIONS = Counter(
    "execution_handoff_rejections_total",
    "Handoff requests rejected before any execution (fail-closed).",
    ["reason"],
)

EXECUTION_COMPLETIONS = Counter(
    "execution_completions_total",
    "Executions closed with a signed receipt, by receipt status.",
    ["status"],
)

EXECUTION_LATE_COMPLETIONS = Counter(
    "execution_late_completions_total",
    "Receipt closes that found the row already closed (late arrival).",
)

AUDIT_EMITS = Counter(
    "audit_emits_total",
    "Audit event emission attempts to the audit service (SPEC-013).",
    ["result"],
)

# SPEC-063 R-7c operational surface. Fixed cardinality only: bounded enum
# labels, never identity/session/request values (observability-conventions.md).
EXECUTION_DUPLICATE_CLAIMS = Counter(
    "execution_duplicate_claims_total",
    "Handoffs answered metadata-only from an existing single-use claim.",
)

EXECUTION_CONFLICTS = Counter(
    "execution_conflicts_total",
    "Conflicts refused without minting dispatch authority, by bounded kind.",
    ["kind"],
)

EXECUTION_STORE_WRITE_FAILURES = Counter(
    "execution_store_write_failures_total",
    "Durable ledger writes that failed or were left unconfirmed.",
)

EXECUTION_ADMISSION_AVAILABLE = Gauge(
    "execution_admission_available",
    "1 when durable admission is enabled, the epoch matches, and the store is reachable.",
)

EXECUTION_UNRESOLVED_COUNT = Gauge(
    "execution_unresolved_count",
    "Claimed executions with no recorded outcome on a live run.",
)

EXECUTION_UNRESOLVED_OLDEST_AGE_SECONDS = Gauge(
    "execution_unresolved_oldest_age_seconds",
    "Age of the oldest unresolved claim, measured with the database clock.",
)

EXECUTION_DRAIN_STATE = Gauge(
    "execution_drain_state",
    "1 while the worker is draining (refusing new handoffs, unready).",
)

# Bound readiness/metrics DB reads: at most one bounded aggregate refresh per
# interval regardless of scrape frequency (SPEC-063 R-7c).
GAUGE_REFRESH_INTERVAL_SECONDS = 5.0
_gauge_refresh_deadline = 0.0

_CONFLICT_KINDS = frozenset({"identity", "integrity"})


def _handler_label(request: Request) -> str:
    # Templated route path (bounded cardinality), never the raw URL.
    route = request.scope.get("route")
    return getattr(route, "path", "unmatched")


def setup_metrics(app: FastAPI) -> None:
    """Attach the RED middleware and expose GET /metrics (always on)."""

    @app.middleware("http")
    async def record_http_metrics(request: Request, call_next):
        started_at = time.perf_counter()
        response = await call_next(request)
        handler = _handler_label(request)
        if handler != "/metrics":
            elapsed = time.perf_counter() - started_at
            status = str(response.status_code)
            HTTP_REQUESTS.labels(
                method=request.method, handler=handler, status=status
            ).inc()
            HTTP_REQUEST_DURATION.labels(
                method=request.method, handler=handler
            ).observe(elapsed)
            _MIRROR.count(
                "http_requests_total",
                1,
                {"method": request.method, "handler": handler, "status": status},
            )
            _MIRROR.observe(
                "http_request_duration_seconds",
                elapsed,
                {"method": request.method, "handler": handler},
            )
        return response

    @app.get("/metrics", include_in_schema=False)
    def metrics_endpoint() -> Response:
        # Refresh the bounded gauges from at most one cached DB read; scraping
        # never triggers execution work and fails open on an unreachable store.
        refresh_ledger_gauges(
            getattr(app.state, "ledger", None),
            bool(getattr(app.state, "draining", False)),
        )
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def record_handoff() -> None:
    EXECUTION_HANDOFFS.inc()
    _MIRROR.count("execution_handoffs_total", 1)


def record_rejection(reason: str) -> None:
    EXECUTION_REJECTIONS.labels(reason=reason).inc()
    _MIRROR.count("execution_handoff_rejections_total", 1, {"reason": reason})


def record_completion(status: str) -> None:
    EXECUTION_COMPLETIONS.labels(status=status).inc()
    _MIRROR.count("execution_completions_total", 1, {"status": status})


def record_late_completion() -> None:
    EXECUTION_LATE_COMPLETIONS.inc()
    _MIRROR.count("execution_late_completions_total", 1)


def record_audit_emit(result: str) -> None:
    """Record an audit emission outcome (``ok`` or ``error``)."""
    AUDIT_EMITS.labels(result=result).inc()
    _MIRROR.count("audit_emits_total", 1, {"result": result})


def record_duplicate() -> None:
    """A handoff answered metadata-only from an existing single-use claim."""
    EXECUTION_DUPLICATE_CLAIMS.inc()
    _MIRROR.count("execution_duplicate_claims_total", 1)


def record_conflict(kind: str) -> None:
    """Record a refused conflict; ``kind`` is a bounded enum, never identity."""
    bounded = kind if kind in _CONFLICT_KINDS else "identity"
    EXECUTION_CONFLICTS.labels(kind=bounded).inc()
    _MIRROR.count("execution_conflicts_total", 1, {"kind": bounded})


def record_store_write_failure() -> None:
    """A durable ledger write failed or was left unconfirmed."""
    EXECUTION_STORE_WRITE_FAILURES.inc()
    _MIRROR.count("execution_store_write_failures_total", 1)


def record_drain_state(draining: bool) -> None:
    """Publish the in-process drain state (1 while refusing new handoffs)."""
    value = 1 if draining else 0
    EXECUTION_DRAIN_STATE.set(value)
    _MIRROR.set_gauge("execution_drain_state", value)


def refresh_ledger_gauges(ledger, draining: bool) -> None:
    """Publish admission/unresolved gauges from at most one bounded DB read.

    The drain gauge is in-process and always current. The DB-backed gauges are
    refreshed at most once per :data:`GAUGE_REFRESH_INTERVAL_SECONDS` so a scrape
    storm cannot amplify into a read storm, and the refresh fails open: an
    unreachable store never breaks ``/metrics``. Scraping performs no execution
    work and mints no dispatch authority (SPEC-063 R-7c).
    """
    global _gauge_refresh_deadline
    record_drain_state(draining)
    if ledger is None:
        return
    now = time.monotonic()
    if now < _gauge_refresh_deadline:
        return
    _gauge_refresh_deadline = now + GAUGE_REFRESH_INTERVAL_SECONDS
    try:
        snapshot = ledger.metrics_snapshot()
    except Exception:  # a gauge refresh must never break the scrape
        return
    EXECUTION_ADMISSION_AVAILABLE.set(1 if snapshot.get("admission_available") else 0)
    EXECUTION_UNRESOLVED_COUNT.set(int(snapshot.get("unresolved_count", 0)))
    EXECUTION_UNRESOLVED_OLDEST_AGE_SECONDS.set(
        float(snapshot.get("oldest_unresolved_age_seconds", 0.0))
    )
    _MIRROR.set_gauge(
        "execution_admission_available",
        1 if snapshot.get("admission_available") else 0,
    )
    _MIRROR.set_gauge(
        "execution_unresolved_count", int(snapshot.get("unresolved_count", 0))
    )
    _MIRROR.set_gauge(
        "execution_unresolved_oldest_age_seconds",
        float(snapshot.get("oldest_unresolved_age_seconds", 0.0)),
    )
