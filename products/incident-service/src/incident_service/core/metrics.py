"""Prometheus metrics surface for incident-service (SPEC-005 R-1/R-2, SPEC-015).

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

from incident_service.core.telemetry import MetricsMirror

# SPEC-065 R-2: every prometheus family in this module is mirrored to an OTel
# instrument of the same exposed name + bounded label set when OTEL_ENABLED, so
# domain metrics reach dashboards over the OTLP push path (ADR-0014) with no
# scraper. The mirror is lazy, fail-open, and a no-op when disabled (see
# core/telemetry.py). Names are exposed sample names (counters keep ``_total``).
OTEL_MIRROR_FAMILIES = (
    ("http_requests_total", "counter", ("method", "handler", "status")),
    ("http_request_duration_seconds", "histogram", ("method", "handler")),
    ("incident_intakes_total", "counter", ("source", "result")),
    ("incident_triages_total", "counter", ("result",)),
    ("incident_connector_dispatches_total", "counter", ("connector", "result")),
    ("incidents_open", "gauge", ()),
)

_MIRROR = MetricsMirror("incident_service", OTEL_MIRROR_FAMILIES)

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

INCIDENTS_INTAKES = Counter(
    "incident_intakes_total",
    "Incidents accepted per intake channel.",
    ["source", "result"],
)

INCIDENT_TRIAGES = Counter(
    "incident_triages_total",
    "Triage runs completed per outcome.",
    ["result"],
)

INCIDENT_DISPATCHES = Counter(
    "incident_connector_dispatches_total",
    "Connector dispatch attempts per connector and outcome.",
    ["connector", "result"],
)

INCIDENTS_OPEN = Gauge(
    "incidents_open",
    "Number of incidents not yet resolved.",
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


def record_intake(source: str, result: str) -> None:
    INCIDENTS_INTAKES.labels(source=source, result=result).inc()
    _MIRROR.count("incident_intakes_total", 1, {"source": source, "result": result})


def record_triage(result: str) -> None:
    INCIDENT_TRIAGES.labels(result=result).inc()
    _MIRROR.count("incident_triages_total", 1, {"result": result})


def record_dispatch(connector: str, result: str) -> None:
    INCIDENT_DISPATCHES.labels(connector=connector, result=result).inc()
    _MIRROR.count(
        "incident_connector_dispatches_total",
        1,
        {"connector": connector, "result": result},
    )


def set_open_incidents(count: int) -> None:
    INCIDENTS_OPEN.set(count)
    _MIRROR.set_gauge("incidents_open", count)
