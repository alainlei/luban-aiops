"""Prometheus metrics surface for audit-service (SPEC-005 R-1/R-2, SPEC-013).

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

from audit_service.core.telemetry import MetricsMirror

# SPEC-065 R-2: every prometheus family in this module is mirrored to an OTel
# instrument of the same exposed name + bounded label set when OTEL_ENABLED, so
# domain metrics reach dashboards over the OTLP push path (ADR-0014) with no
# scraper. The mirror is lazy, fail-open, and a no-op when disabled (see
# core/telemetry.py). Names are exposed sample names (counters keep ``_total``).
OTEL_MIRROR_FAMILIES = (
    ("http_requests_total", "counter", ("method", "handler", "status")),
    ("http_request_duration_seconds", "histogram", ("method", "handler")),
    ("audit_events_ingested_total", "counter", ("service", "event_type")),
    ("audit_ingest_rejected_total", "counter", ("reason",)),
    ("audit_query_total", "counter", ()),
    ("audit_summary_query_total", "counter", ()),
    ("audit_exports_total", "counter", ()),
    ("audit_evicted_total", "counter", ()),
    ("audit_store_errors_total", "counter", ("operation",)),
    ("audit_store_events", "gauge", ()),
)

_MIRROR = MetricsMirror("audit_service", OTEL_MIRROR_FAMILIES)

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

AUDIT_INGESTED = Counter(
    "audit_events_ingested_total",
    "Audit events accepted by the ingest endpoint.",
    ["service", "event_type"],
)

AUDIT_REJECTED = Counter(
    "audit_ingest_rejected_total",
    "Ingest requests rejected (malformed events, auth failures).",
    ["reason"],
)

AUDIT_QUERIES = Counter(
    "audit_query_total",
    "Audit trail query requests served.",
)

AUDIT_SUMMARY_QUERIES = Counter(
    "audit_summary_query_total",
    "Audit summary aggregate requests served (SPEC-046 R-1).",
)

AUDIT_EXPORTS = Counter(
    "audit_exports_total",
    "Audit trail CSV exports generated (SPEC-046 R-2).",
)

AUDIT_EVICTED = Counter(
    "audit_evicted_total",
    "Audit events evicted by retention.",
)

AUDIT_STORE_ERRORS = Counter(
    "audit_store_errors_total",
    "Audit store operation failures.",
    ["operation"],
)

AUDIT_STORE_EVENTS = Gauge(
    "audit_store_events",
    "Approximate number of events held by the store.",
)


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
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def record_ingested(service: str, event_type: str, count: int = 1) -> None:
    AUDIT_INGESTED.labels(service=service, event_type=event_type).inc(count)
    _MIRROR.count(
        "audit_events_ingested_total",
        count,
        {"service": service, "event_type": event_type},
    )


def record_rejected(reason: str) -> None:
    AUDIT_REJECTED.labels(reason=reason).inc()
    _MIRROR.count("audit_ingest_rejected_total", 1, {"reason": reason})


def record_query() -> None:
    AUDIT_QUERIES.inc()
    _MIRROR.count("audit_query_total", 1)


def record_summary_query() -> None:
    AUDIT_SUMMARY_QUERIES.inc()
    _MIRROR.count("audit_summary_query_total", 1)


def record_export() -> None:
    AUDIT_EXPORTS.inc()
    _MIRROR.count("audit_exports_total", 1)


def record_evicted(count: int) -> None:
    if count > 0:
        AUDIT_EVICTED.inc(count)
        _MIRROR.count("audit_evicted_total", count)


def record_store_error(operation: str) -> None:
    AUDIT_STORE_ERRORS.labels(operation=operation).inc()
    _MIRROR.count("audit_store_errors_total", 1, {"operation": operation})


def set_store_size(count: int) -> None:
    AUDIT_STORE_EVENTS.set(count)
    _MIRROR.set_gauge("audit_store_events", count)


def record_store_growth(delta: int) -> None:
    """Incremental store-size update for hot paths (ingest); retention
    reconciles the exact size via ``set_store_size`` on every sweep."""
    if delta:
        # Prometheus-only: an OTel synchronous gauge has no increment, so the
        # push surface takes the authoritative value from ``set_store_size`` on
        # every retention sweep instead of tracking a running delta (SPEC-065 R-2).
        AUDIT_STORE_EVENTS.inc(delta)
