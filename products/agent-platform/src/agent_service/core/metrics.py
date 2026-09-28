"""Prometheus metrics surface (SPEC-005 R-1/R-2).

Always-on, collector-independent debug surface implemented directly with
prometheus_client: a minimal RED middleware plus GET /metrics. Metric objects
live at module level so repeated create_app() calls (tests) never
double-register them. Conventions:
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

from agent_service.core.telemetry import MetricsMirror

# SPEC-065 R-2: every prometheus family in this module is mirrored to an OTel
# instrument of the same exposed name + bounded label set when OTEL_ENABLED, so
# domain metrics reach dashboards over the OTLP push path (ADR-0014) with no
# scraper. The mirror is lazy, fail-open, and a no-op when disabled (see
# core/telemetry.py). Names are exposed sample names (counters keep ``_total``).
# MetricsMirrorTests pins this list to the prometheus objects declared below.
OTEL_MIRROR_FAMILIES = (
    ("http_requests_total", "counter", ("method", "handler", "status")),
    ("http_request_duration_seconds", "histogram", ("method", "handler")),
    ("agent_sessions_created_total", "counter", ()),
    ("agent_chat_requests_total", "counter", ()),
    ("session_store_backend", "gauge", ("backend",)),
    ("session_store_errors_total", "counter", ("operation",)),
    ("session_store_fallbacks_total", "counter", ()),
    ("agent_state_backend", "gauge", ("backend",)),
    ("agent_state_errors_total", "counter", ("operation",)),
    ("agent_state_fallbacks_total", "counter", ()),
    ("evidence_store_writes_total", "counter", ("result",)),
    ("evidence_frames_persisted_total", "counter", ()),
    ("evidence_frames_truncated_total", "counter", ("reason",)),
    ("audit_emits_total", "counter", ("result",)),
    ("agent_model_discovery_refreshes_total", "counter", ("provider", "result")),
    ("agent_model_discovery_models", "gauge", ("provider",)),
    ("agent_llm_tokens_total", "counter", ("provider", "model", "direction")),
)

_MIRROR = MetricsMirror("agent_service", OTEL_MIRROR_FAMILIES)

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

SESSIONS_CREATED = Counter(
    "agent_sessions_created_total",
    "Agent sessions created.",
)

CHAT_REQUESTS = Counter(
    "agent_chat_requests_total",
    "Chat requests handled (blocking and streaming).",
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


def record_session_created() -> None:
    SESSIONS_CREATED.inc()
    _MIRROR.count("agent_sessions_created_total", 1)


def record_chat_request() -> None:
    CHAT_REQUESTS.inc()
    _MIRROR.count("agent_chat_requests_total", 1)


# --- Session store observability (SPEC-006 R-3/R-4) ---

SESSION_STORE_BACKEND_GAUGE = Gauge(
    "session_store_backend",
    "Active session store backend (1 = active).",
    ["backend"],
)

SESSION_STORE_ERRORS = Counter(
    "session_store_errors_total",
    "Session store operation failures.",
    ["operation"],
)

SESSION_STORE_FALLBACKS = Counter(
    "session_store_fallbacks_total",
    "Times the session store fell back to in-memory due to backend failure.",
)


def record_session_store_backend(backend: str) -> None:
    """Set the active backend gauge (1 for active, 0 for others)."""
    for label in ("redis", "memory", "postgres"):
        value = 1 if label == backend else 0
        SESSION_STORE_BACKEND_GAUGE.labels(backend=label).set(value)
        _MIRROR.set_gauge("session_store_backend", value, {"backend": label})


def record_session_store_error(operation: str) -> None:
    SESSION_STORE_ERRORS.labels(operation=operation).inc()
    _MIRROR.count("session_store_errors_total", 1, {"operation": operation})


def record_session_store_fallback() -> None:
    SESSION_STORE_FALLBACKS.inc()
    _MIRROR.count("session_store_fallbacks_total", 1)


# --- Agent state store observability (SPEC-017 R-5) ---

AGENT_STATE_BACKEND_GAUGE = Gauge(
    "agent_state_backend",
    "Active agent state store backend (1 = active).",
    ["backend"],
)

AGENT_STATE_ERRORS = Counter(
    "agent_state_errors_total",
    "Agent state store operation failures.",
    ["operation"],
)

AGENT_STATE_FALLBACKS = Counter(
    "agent_state_fallbacks_total",
    "Times the agent state store fell back to in-memory due to backend failure.",
)


def record_agent_state_backend(backend: str) -> None:
    """Set the active backend gauge (1 for active, 0 for others)."""
    for label in ("memory", "postgres"):
        value = 1 if label == backend else 0
        AGENT_STATE_BACKEND_GAUGE.labels(backend=label).set(value)
        _MIRROR.set_gauge("agent_state_backend", value, {"backend": label})


def record_agent_state_error(operation: str) -> None:
    AGENT_STATE_ERRORS.labels(operation=operation).inc()
    _MIRROR.count("agent_state_errors_total", 1, {"operation": operation})


def record_agent_state_fallback() -> None:
    AGENT_STATE_FALLBACKS.inc()
    _MIRROR.count("agent_state_fallbacks_total", 1)


# --- Evidence store observability (SPEC-025 R-4) ---

EVIDENCE_STORE_WRITES = Counter(
    "evidence_store_writes_total",
    "Evidence turn persistence attempts.",
    ["result"],
)

EVIDENCE_FRAMES_PERSISTED = Counter(
    "evidence_frames_persisted_total",
    "Evidence frames persisted for session replay.",
)

EVIDENCE_FRAMES_TRUNCATED = Counter(
    "evidence_frames_truncated_total",
    "Evidence frames truncated by size caps.",
    ["reason"],
)


def record_evidence_write(result: str) -> None:
    EVIDENCE_STORE_WRITES.labels(result=result).inc()
    _MIRROR.count("evidence_store_writes_total", 1, {"result": result})


def record_evidence_frames_persisted(count: int) -> None:
    EVIDENCE_FRAMES_PERSISTED.inc(count)
    _MIRROR.count("evidence_frames_persisted_total", count)


def record_evidence_frame_truncated(reason: str) -> None:
    EVIDENCE_FRAMES_TRUNCATED.labels(reason=reason).inc()
    _MIRROR.count("evidence_frames_truncated_total", 1, {"reason": reason})


# --- Audit emission observability (SPEC-037 R-5) ---

AUDIT_EMITS = Counter(
    "audit_emits_total",
    "Audit event emission attempts to the audit service (SPEC-013).",
    ["result"],
)


def record_audit_emit(result: str) -> None:
    """Record an audit emission outcome (``ok`` or ``error``)."""
    AUDIT_EMITS.labels(result=result).inc()
    _MIRROR.count("audit_emits_total", 1, {"result": result})


# --- Model discovery observability (SPEC-027) ---

MODEL_DISCOVERY_REFRESHES = Counter(
    "agent_model_discovery_refreshes_total",
    "Model discovery refresh cycles by ladder outcome.",
    ["provider", "result"],
)

MODEL_DISCOVERY_MODELS = Gauge(
    "agent_model_discovery_models",
    "Models currently published per provider after discovery.",
    ["provider"],
)


def record_model_discovery_refresh(provider: str, result: str) -> None:
    """result in {override, disabled, live, memory, cache, curated}."""
    MODEL_DISCOVERY_REFRESHES.labels(provider=provider, result=result).inc()
    _MIRROR.count(
        "agent_model_discovery_refreshes_total",
        1,
        {"provider": provider, "result": result},
    )


def record_model_discovery_models(provider: str, count: int) -> None:
    MODEL_DISCOVERY_MODELS.labels(provider=provider).set(count)
    _MIRROR.set_gauge(
        "agent_model_discovery_models", count, {"provider": provider}
    )


# --- LLM token usage (SPEC-065 R-1) ---

# Bounded ``direction`` label set: the four token counts agentscope's ChatUsage
# exposes (input/output plus the two cache counts). There is deliberately NO
# cost counter or direction here — agentscope 2.0.8 reports no provider-derived
# cost and the platform holds no price table, so R-1 is tokens-only and the
# dollar metric is deferred (SPEC-065 plan.md Stage-0 finding). Nothing is ever
# estimated or synthesized: a provider that reports no usage records nothing.
LLM_TOKEN_DIRECTIONS = ("input", "output", "cache_input", "cache_creation")

LLM_TOKENS = Counter(
    "agent_llm_tokens_total",
    "Provider-reported LLM token usage by model and direction.",
    ["provider", "model", "direction"],
)


def record_llm_tokens(provider: str, model: str, direction: str, amount: int) -> None:
    """Record provider-reported token usage for one direction (SPEC-065 R-1).

    ``amount`` is a provider-reported count; a non-positive amount records
    nothing (never synthesize or estimate a value). Labels stay bounded:
    ``provider``/``model`` resolve to the credential-gated catalog (else the
    ``unknown`` sentinel) and ``direction`` is one of ``LLM_TOKEN_DIRECTIONS``.
    """
    if amount <= 0:
        return
    LLM_TOKENS.labels(provider=provider, model=model, direction=direction).inc(amount)
    _MIRROR.count(
        "agent_llm_tokens_total",
        amount,
        {"provider": provider, "model": model, "direction": direction},
    )
