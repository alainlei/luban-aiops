"""OTel push pipeline gating tests (SPEC-005): log bridge + disabled state.

Hermetic: the exporters are pointed at a black-hole endpoint and no test
touches the network. Module guards are reset around each test so ordering
never matters.
"""

from __future__ import annotations

import logging
import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI

import agent_service.core.metrics as metrics_module
import agent_service.core.telemetry as telemetry


class TelemetryGatingTests(unittest.TestCase):
    def setUp(self) -> None:
        from opentelemetry.instrumentation.logging.handler import LoggingHandler

        self._logging_handler_cls = LoggingHandler
        self._initialized = telemetry._providers_initialized
        self._attached = telemetry._log_bridge_attached
        telemetry._providers_initialized = False
        telemetry._log_bridge_attached = False

    def tearDown(self) -> None:
        root = logging.getLogger()
        for handler in list(root.handlers):
            if isinstance(handler, self._logging_handler_cls):
                root.removeHandler(handler)
        telemetry._providers_initialized = self._initialized
        telemetry._log_bridge_attached = self._attached

    def _root_has_bridge(self) -> bool:
        root = logging.getLogger()
        return any(
            isinstance(handler, self._logging_handler_cls)
            for handler in root.handlers
        )

    def test_disabled_initializes_nothing(self) -> None:
        with patch.dict(os.environ, {"OTEL_ENABLED": "false"}):
            telemetry.setup_telemetry(FastAPI(), "agent-service")
        self.assertFalse(telemetry._providers_initialized)
        self.assertFalse(telemetry._log_bridge_attached)
        self.assertFalse(self._root_has_bridge())

    def test_enabled_attaches_logging_handler_to_root(self) -> None:
        env = {
            "OTEL_ENABLED": "true",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:1",
        }
        with patch.dict(os.environ, env):
            telemetry.setup_telemetry(FastAPI(), "agent-service")
        self.assertTrue(telemetry._providers_initialized)
        self.assertTrue(self._root_has_bridge())
        # OTel's own loggers must not recurse back through the root bridge.
        self.assertFalse(logging.getLogger("opentelemetry").propagate)


class MetricsMirrorTests(unittest.TestCase):
    """SPEC-065 R-2: domain families mirror to OTel with name + label parity.

    ``MetricsMirror`` lives in the byte-identical ``telemetry.py`` (guarded by
    ``TelemetryParityTest``), so its behaviour is exercised once here against
    agent-platform's own declared families. Every test injects an in-memory
    ``MeterProvider`` so none touches the process-global provider or network.
    """

    def _prom_families(self) -> dict[str, tuple[str, tuple[str, ...]]]:
        from prometheus_client.metrics import MetricWrapperBase

        families: dict[str, tuple[str, tuple[str, ...]]] = {}
        for obj in vars(metrics_module).values():
            if isinstance(obj, MetricWrapperBase):
                kind = obj._type
                exposed = obj._name + "_total" if kind == "counter" else obj._name
                families[exposed] = (kind, tuple(obj._labelnames))
        return families

    def _declared(self) -> dict[str, tuple[str, tuple[str, ...]]]:
        return {
            name: (kind, tuple(labels))
            for (name, kind, labels) in metrics_module.OTEL_MIRROR_FAMILIES
        }

    def _exported(self, reader) -> dict[str, frozenset]:
        emitted: dict[str, frozenset] = {}
        for resource in reader.get_metrics_data().resource_metrics:
            for scope in resource.scope_metrics:
                for metric in scope.metrics:
                    keys: set[str] = set()
                    for point in metric.data.data_points:
                        keys |= set(point.attributes.keys())
                    emitted[metric.name] = frozenset(keys)
        return emitted

    def _mirror_over_all(self, reader) -> telemetry.MetricsMirror:
        from opentelemetry.sdk.metrics import MeterProvider

        return telemetry.MetricsMirror(
            "agent_service",
            metrics_module.OTEL_MIRROR_FAMILIES,
            meter_provider=MeterProvider(metric_readers=[reader]),
        )

    def test_declared_families_match_prometheus_objects(self) -> None:
        # Same exposed name + same bounded label set on both surfaces, covering
        # every prometheus family with no drift and no extras.
        self.assertEqual(self._declared(), self._prom_families())

    def test_r1_token_family_is_mirrored(self) -> None:
        self.assertIn(
            ("agent_llm_tokens_total", "counter", ("provider", "model", "direction")),
            metrics_module.OTEL_MIRROR_FAMILIES,
        )

    def test_enabled_mirror_emits_every_family_with_matching_labels(self) -> None:
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader

        reader = InMemoryMetricReader()
        with patch.dict(os.environ, {"OTEL_ENABLED": "true"}):
            mirror = self._mirror_over_all(reader)
            for name, kind, labels in metrics_module.OTEL_MIRROR_FAMILIES:
                attrs = {label: "v" for label in labels}
                if kind == "counter":
                    mirror.count(name, 1, attrs)
                elif kind == "histogram":
                    mirror.observe(name, 0.5, attrs)
                else:
                    mirror.set_gauge(name, 1, attrs)

        exported = self._exported(reader)
        declared = self._declared()
        self.assertEqual(set(exported), set(declared))
        for name, (_kind, labels) in declared.items():
            self.assertEqual(exported[name], frozenset(labels), name)

    def test_disabled_creates_no_instrument_and_leaves_metrics_intact(self) -> None:
        from prometheus_client import generate_latest

        env = {k: v for k, v in os.environ.items() if k != "OTEL_ENABLED"}
        with patch.dict(os.environ, env, clear=True):
            mirror = telemetry.MetricsMirror(
                "agent_service", metrics_module.OTEL_MIRROR_FAMILIES
            )
            mirror.count("agent_sessions_created_total", 1)
            mirror.observe(
                "http_request_duration_seconds",
                0.1,
                {"method": "GET", "handler": "/"},
            )
            # Never built while disabled...
            self.assertIsNone(mirror._instruments)
        # ...and the always-on prometheus pull surface is untouched.
        self.assertIn("agent_sessions_created_total", generate_latest().decode())

    def test_build_failure_fails_open(self) -> None:
        class _Boom:
            def get_meter(self, *_a, **_k):
                raise RuntimeError("exporter unavailable")

        with patch.dict(os.environ, {"OTEL_ENABLED": "true"}):
            mirror = telemetry.MetricsMirror(
                "agent_service",
                (("agent_sessions_created_total", "counter", ()),),
                meter_provider=_Boom(),
            )
            mirror.count("agent_sessions_created_total", 1)  # must not raise
        self.assertEqual(mirror._instruments, {})

    def test_record_failure_fails_open(self) -> None:
        class _BadInstrument:
            def add(self, *_a, **_k):
                raise RuntimeError("export failed")

        class _Meter:
            def create_counter(self, *_a, **_k):
                return _BadInstrument()

        class _Provider:
            def get_meter(self, *_a, **_k):
                return _Meter()

        with patch.dict(os.environ, {"OTEL_ENABLED": "true"}):
            mirror = telemetry.MetricsMirror(
                "agent_service",
                (("agent_sessions_created_total", "counter", ()),),
                meter_provider=_Provider(),
            )
            mirror.count("agent_sessions_created_total", 1)  # must not raise

    def test_record_llm_tokens_mirrors_end_to_end(self) -> None:
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader

        reader = InMemoryMetricReader()
        bound = self._mirror_over_all(reader)
        with patch.dict(os.environ, {"OTEL_ENABLED": "true"}), patch.object(
            metrics_module, "_MIRROR", bound
        ):
            metrics_module.record_llm_tokens("dashscope", "qwen-plus", "input", 42)

        exported = self._exported(reader)
        self.assertEqual(
            exported.get("agent_llm_tokens_total"),
            frozenset({"provider", "model", "direction"}),
        )


if __name__ == "__main__":
    unittest.main()
