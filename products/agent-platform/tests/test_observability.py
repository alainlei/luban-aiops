"""SPEC-005 observability tests: /metrics surface, domain counters, OTel gating."""

from __future__ import annotations

import logging
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from agent_service.app import create_app
from agent_service.core.observability import configure_logging
from agent_service.services.session_service import create_session


def _sample(name: str, labels: dict[str, str] | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


class MetricsEndpointTests(unittest.TestCase):
    def test_metrics_returns_prometheus_exposition(self) -> None:
        client = TestClient(create_app())
        client.get("/api/v2/health")
        response = client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/plain"))
        body = response.text
        for expected in (
            "http_requests_total",
            "http_request_duration_seconds",
            "agent_sessions_created_total",
            "agent_chat_requests_total",
            # SPEC-025 R-1 evidence counters.
            "evidence_store_writes_total",
            "evidence_frames_persisted_total",
            "evidence_frames_truncated_total",
        ):
            self.assertIn(expected, body)

    def test_metrics_available_with_otel_enabled(self) -> None:
        with patch.dict(os.environ, {"OTEL_ENABLED": "true"}):
            client = TestClient(create_app())
            self.assertEqual(client.get("/metrics").status_code, 200)


class DomainCounterTests(unittest.TestCase):
    def test_session_creation_increments_counter(self) -> None:
        before = _sample("agent_sessions_created_total")
        create_session("user-1")
        self.assertEqual(_sample("agent_sessions_created_total"), before + 1)

    def test_session_create_route_increments_counter(self) -> None:
        client = TestClient(create_app())
        before = _sample("agent_sessions_created_total")
        response = client.post("/api/v2/sessions", headers={"X-User-ID": "user-1"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(_sample("agent_sessions_created_total"), before + 1)


class LlmTokenMetricTests(unittest.TestCase):
    """SPEC-065 R-1: the token family surfaces on GET /metrics with ``_total``."""

    def test_token_family_appears_on_metrics_endpoint(self) -> None:
        from agent_service.core.metrics import record_llm_tokens

        # Recording a token creates the child series; the always-on /metrics
        # surface then exposes it under the ``_total`` counter name (naming
        # conventions), with the bounded direction label.
        record_llm_tokens("dashscope", "qwen-plus", "input", 1)
        body = TestClient(create_app()).get("/metrics").text
        self.assertIn("agent_llm_tokens_total", body)
        self.assertIn('direction="input"', body)


class LoggingConfigTests(unittest.TestCase):
    def test_defaults_to_info_so_audit_events_survive(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "LOG_LEVEL"}
        with patch.dict(os.environ, env, clear=True):
            configure_logging()
        self.assertEqual(logging.getLogger().level, logging.INFO)

    def test_log_level_env_overrides(self) -> None:
        with patch.dict(os.environ, {"LOG_LEVEL": "WARNING"}):
            configure_logging()
        self.assertEqual(logging.getLogger().level, logging.WARNING)
        configure_logging()  # restore default for later tests


if __name__ == "__main__":
    unittest.main()
