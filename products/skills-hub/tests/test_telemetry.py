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

import skills_hub.core.metrics as metrics_module
import skills_hub.core.telemetry as telemetry


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
            telemetry.setup_telemetry(FastAPI(), "skills-hub")
        self.assertFalse(telemetry._providers_initialized)
        self.assertFalse(telemetry._log_bridge_attached)
        self.assertFalse(self._root_has_bridge())

    def test_enabled_attaches_logging_handler_to_root(self) -> None:
        env = {
            "OTEL_ENABLED": "true",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:1",
        }
        with patch.dict(os.environ, env):
            telemetry.setup_telemetry(FastAPI(), "skills-hub")
        self.assertTrue(telemetry._providers_initialized)
        self.assertTrue(self._root_has_bridge())
        # OTel's own loggers must not recurse back through the root bridge.
        self.assertFalse(logging.getLogger("opentelemetry").propagate)


class MetricsMirrorParityTest(unittest.TestCase):
    """SPEC-065 R-2: the OTel mirror list matches this service's prometheus families."""

    def test_declared_families_match_prometheus_objects(self) -> None:
        from prometheus_client.metrics import MetricWrapperBase

        prom: dict[str, tuple[str, tuple[str, ...]]] = {}
        for obj in vars(metrics_module).values():
            if isinstance(obj, MetricWrapperBase):
                kind = obj._type
                exposed = obj._name + "_total" if kind == "counter" else obj._name
                prom[exposed] = (kind, tuple(obj._labelnames))
        declared = {
            name: (kind, tuple(labels))
            for (name, kind, labels) in metrics_module.OTEL_MIRROR_FAMILIES
        }
        self.assertEqual(declared, prom)


if __name__ == "__main__":
    unittest.main()
