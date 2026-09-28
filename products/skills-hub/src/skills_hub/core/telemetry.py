"""Opt-in OpenTelemetry push pipeline (SPEC-005 R-3/R-4).

Gated by OTEL_ENABLED (default false): when disabled nothing is initialized
and the /metrics surface is unaffected. Fail-open: setup errors are logged,
never raised into the request path.

Signals are exported via OTLP HTTP/protobuf to OTEL_EXPORTER_OTLP_ENDPOINT
(the exporters append the per-signal ``/v1/{traces,metrics,logs}`` paths),
which matches the OpenObserve ingest contract ``/api/{org}/v1/{signal}``.
Authentication rides on OTEL_EXPORTER_OTLP_HEADERS, provisioned into the
runtime secrets (never committed). Conventions:
shared/shared-contracts/observability-conventions.md.

SPEC-065 R-2: ``MetricsMirror`` additionally re-emits each service's own
prometheus domain families as OTel instruments (same exposed name, same
bounded label set) so they reach dashboards over the OTLP push path
(ADR-0014) instead of via a scraper. It stays generic — byte-identical
across all eight services (TelemetryParityTest) — so it names no
service-specific metric: the caller supplies the family list.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI

LOGGER = logging.getLogger(__name__)

_providers_initialized = False
_log_bridge_attached = False


def _flag_enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_enabled() -> bool:
    """True when the OTel push pipeline is switched on via OTEL_ENABLED."""
    return _flag_enabled(os.getenv("OTEL_ENABLED"))


def _attach_log_bridge(resource) -> None:
    """Mirror structured logs into the OTLP log pipeline.

    The JSON lines on stdout remain the source of truth for the audit
    trail; this bridge ships the same records over OTLP so the backend
    can correlate them with traces (trace/span ids attach automatically
    when a span is active). OTel's own loggers are detached from the root
    logger so exporter failures cannot recurse back into the bridge.
    """
    global _log_bridge_attached
    if _log_bridge_attached:
        return
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import (
        OTLPLogExporter,
    )
    from opentelemetry.instrumentation.logging.handler import LoggingHandler
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter())
    )
    set_logger_provider(logger_provider)
    logging.getLogger("opentelemetry").propagate = False
    logging.getLogger().addHandler(
        LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    )
    _log_bridge_attached = True


def setup_telemetry(app: FastAPI, service_name: str) -> None:
    """Initialize traces + metrics + logs push to the configured OTLP endpoint."""
    global _providers_initialized
    if not is_enabled():
        return
    try:
        from opentelemetry import metrics as otel_metrics
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        if not _providers_initialized:
            resource = Resource.create(
                {"service.name": os.getenv("OTEL_SERVICE_NAME", service_name)}
            )
            tracer_provider = TracerProvider(resource=resource)
            tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            trace.set_tracer_provider(tracer_provider)

            reader = PeriodicExportingMetricReader(OTLPMetricExporter())
            otel_metrics.set_meter_provider(
                MeterProvider(resource=resource, metric_readers=[reader])
            )

            _attach_log_bridge(resource)
            HTTPXClientInstrumentor().instrument()
            _providers_initialized = True

        FastAPIInstrumentor.instrument_app(app)
        LOGGER.info(
            "otel telemetry enabled",
            extra={
                "service_name": service_name,
                "endpoint": os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
            },
        )
    except Exception:
        LOGGER.exception("otel telemetry setup failed; continuing without push")


def current_trace_id() -> str | None:
    """Return the active span's W3C trace_id (32 hex chars), if tracing is on."""
    if not is_enabled():
        return None
    try:
        from opentelemetry import trace

        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            return format(context.trace_id, "032x")
    except Exception:
        return None
    return None


class MetricsMirror:
    """Re-emit prometheus domain families as OTel instruments (SPEC-065 R-2).

    The always-on ``prometheus_client`` ``/metrics`` surface stays the source of
    truth (SPEC-005). When ``OTEL_ENABLED`` this mirror *additionally* pushes the
    same families — same exposed name, same bounded label set — as OTel
    instruments on the meter from the provider :func:`setup_telemetry` installed,
    so domain metrics reach dashboards over the OTLP push path (ADR-0014) instead
    of via a scraper.

    Constraints honoured here:

    * **Lazy.** Instruments are built on the first record, never at import time,
      because ``setup_metrics`` runs before ``setup_telemetry`` sets the
      ``MeterProvider``. ``meter_provider`` may be injected (tests); production
      passes ``None`` and uses the global provider.
    * **No-op when disabled.** With ``OTEL_ENABLED`` false no instrument is
      created and ``/metrics`` is untouched (SPEC-005 always-on guarantee).
    * **Fail-open.** Any OTel error is logged and swallowed; it never propagates
      into the request path.
    * **Generic.** Byte-identical across all eight services, so it references no
      service-specific metric name: the caller supplies ``(name, kind, labels)``.

    ``kind`` is one of ``counter`` / ``histogram`` / ``gauge``; ``labels`` is the
    bounded label-name tuple (possibly empty). ``name`` is the exposed prometheus
    sample name (counters keep their ``_total`` suffix) so both surfaces agree.
    """

    def __init__(self, meter_name, families, meter_provider=None):
        self._meter_name = meter_name
        self._meter_provider = meter_provider
        self._families = tuple(
            (str(name), str(kind), tuple(labels))
            for (name, kind, labels) in families
        )
        # None = not built yet; {} = built empty (disabled-after-failure).
        self._instruments = None

    def _build(self):
        if self._meter_provider is not None:
            meter = self._meter_provider.get_meter(self._meter_name)
        else:
            from opentelemetry import metrics as otel_metrics

            meter = otel_metrics.get_meter(self._meter_name)
        instruments = {}
        for name, kind, _labels in self._families:
            if kind == "counter":
                instruments[name] = meter.create_counter(name)
            elif kind == "histogram":
                instruments[name] = meter.create_histogram(name)
            elif kind == "gauge":
                instruments[name] = meter.create_gauge(name)
        return instruments

    def _ensure(self):
        if self._instruments is not None:
            return self._instruments
        if not is_enabled():
            return None
        try:
            self._instruments = self._build()
        except Exception:
            LOGGER.exception(
                "otel metrics mirror setup failed; continuing without push"
            )
            self._instruments = {}
        return self._instruments

    def _instrument(self, name):
        instruments = self._ensure()
        if not instruments:
            return None
        return instruments.get(name)

    @staticmethod
    def _attributes(labels):
        return {k: v for k, v in (labels or {}).items() if v is not None}

    def count(self, name, amount, labels=None):
        """Mirror a counter increment beside the prometheus ``.inc()``."""
        instrument = self._instrument(name)
        if instrument is None:
            return
        try:
            instrument.add(amount, self._attributes(labels))
        except Exception:
            LOGGER.exception("otel counter mirror failed for %s", name)

    def observe(self, name, value, labels=None):
        """Mirror a histogram observation beside the prometheus ``.observe()``."""
        instrument = self._instrument(name)
        if instrument is None:
            return
        try:
            instrument.record(value, self._attributes(labels))
        except Exception:
            LOGGER.exception("otel histogram mirror failed for %s", name)

    def set_gauge(self, name, value, labels=None):
        """Mirror a gauge set beside the prometheus ``.set()``."""
        instrument = self._instrument(name)
        if instrument is None:
            return
        try:
            instrument.set(value, self._attributes(labels))
        except Exception:
            LOGGER.exception("otel gauge mirror failed for %s", name)
