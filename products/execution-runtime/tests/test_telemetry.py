"""OTel metrics-mirror parity test for execution-runtime (SPEC-065 R-2).

execution-runtime has no SPEC-005 gating suite of its own; its ``telemetry.py``
is covered by the byte-identical ``TelemetryParityTest`` in tool-gateway. This
module guards the service-specific piece: the OTel mirror family list must match
the prometheus families declared in ``core/metrics.py`` (same exposed name, same
bounded label set), so no domain metric is silently left un-mirrored to
dashboards.
"""

from __future__ import annotations

import unittest

import execution_runtime.core.metrics as metrics_module


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
