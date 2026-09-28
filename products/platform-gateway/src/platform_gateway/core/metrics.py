"""Prometheus metrics surface (SPEC-005 R-1/R-2).

Always-on, collector-independent debug surface implemented directly with
prometheus_client: a minimal RED middleware plus GET /metrics.
(prometheus-fastapi-instrumentator was evaluated but its route introspection
is incompatible with the pinned starlette; see SPEC-005 changelog.)

Metric objects live at module level so repeated create_app() calls (tests)
never double-register them in the default registry. Conventions:
shared/shared-contracts/observability-conventions.md.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)

from platform_gateway.core.telemetry import MetricsMirror

# SPEC-065 R-2: every prometheus family in this module is mirrored to an OTel
# instrument of the same exposed name + bounded label set when OTEL_ENABLED, so
# domain metrics reach dashboards over the OTLP push path (ADR-0014) with no
# scraper. The mirror is lazy, fail-open, and a no-op when disabled (see
# core/telemetry.py). Names are exposed sample names (counters keep ``_total``).
OTEL_MIRROR_FAMILIES = (
    ("http_requests_total", "counter", ("method", "handler", "status")),
    ("http_request_duration_seconds", "histogram", ("method", "handler")),
    ("gateway_policy_decisions_total", "counter", ("action", "decision")),
    ("gateway_token_verification_total", "counter", ("result",)),
    ("delegation_exchange_total", "counter", ("result",)),
    ("delegation_cache_total", "counter", ("result",)),
    ("audit_emits_total", "counter", ("result",)),
)

_MIRROR = MetricsMirror("platform_gateway", OTEL_MIRROR_FAMILIES)

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

POLICY_DECISIONS = Counter(
    "gateway_policy_decisions_total",
    "Policy decisions evaluated by the gateway.",
    ["action", "decision"],
)

TOKEN_VERIFICATIONS = Counter(
    "gateway_token_verification_total",
    "Bearer token verification outcomes.",
    ["result"],
)

DELEGATION_EXCHANGES = Counter(
    "delegation_exchange_total",
    "Delegated-token exchange attempts at the gateway.",
    ["result"],
)

DELEGATION_CACHE = Counter(
    "delegation_cache_total",
    "Per-user delegated-token cache lookups.",
    ["result"],
)

AUDIT_EMITS = Counter(
    "audit_emits_total",
    "Audit event emission attempts to the audit service (SPEC-013).",
    ["result"],
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


def record_policy_decision(action: str, decision: str) -> None:
    POLICY_DECISIONS.labels(action=action, decision=decision).inc()
    _MIRROR.count(
        "gateway_policy_decisions_total", 1, {"action": action, "decision": decision}
    )


def record_token_verification(result: str) -> None:
    TOKEN_VERIFICATIONS.labels(result=result).inc()
    _MIRROR.count("gateway_token_verification_total", 1, {"result": result})


def record_delegation_exchange(result: str) -> None:
    DELEGATION_EXCHANGES.labels(result=result).inc()
    _MIRROR.count("delegation_exchange_total", 1, {"result": result})


def record_delegation_cache(result: str) -> None:
    DELEGATION_CACHE.labels(result=result).inc()
    _MIRROR.count("delegation_cache_total", 1, {"result": result})


def record_audit_emit(result: str) -> None:
    """Record an audit emission outcome (``ok`` or ``error``)."""
    AUDIT_EMITS.labels(result=result).inc()
    _MIRROR.count("audit_emits_total", 1, {"result": result})
