"""SPEC-065 R-4: mocked-I/O proof of the observability live-check pipeline.

The shipped ``observability-livecheck.sh`` embeds its ``--live`` pipeline in a
``python3 - <<'PY'`` heredoc. This test extracts that heredoc, compiles it, and
executes it with ``subprocess.run`` (kubectl) and ``urllib.request.build_opener``
(HTTP) mocked, across a success/failure scenario matrix — so the script's
assertion logic and its loud, secret-free failure path are exercised in the
ordinary suite with no cluster, no network and no paid model call. The paid live
leg itself stays an explicitly gated operator step (``LUBAN_OBS_DRIVE_PAID_TURN=1``).
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

TRACE_ID = "63d9bd754cd3ebcc3cda4527991f37f9"  # 32 hex = the W3C trace_id
SCRIPT = (Path(__file__).resolve().parents[3]
          / "shared/platform-ops/e2e/observability-livecheck.sh")
PASSWORD = "fixture-oo-secret"

# Scenarios that set LUBAN_OBS_DRIVE_PAID_TURN=1 (the gated paid leg).
_TURN_SCENARIOS = {"live-turn", "missing-trace", "bad-trace-id", "metric-cold-start"}
_SUCCESS = {"live-readonly", "live-turn", "metric-cold-start"}


def _pipeline_source() -> str:
    text = SCRIPT.read_text()
    return text.split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]


class _Response:
    def __init__(self, body, status: int = 200) -> None:
        self._body = body
        self.status = status
        self.headers: dict[str, str] = {}

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args) -> bool:
        return False

    def read(self) -> bytes:
        raw = self._body if isinstance(self._body, str) else json.dumps(self._body)
        return raw.encode()


def _sse(frames: list[dict]) -> str:
    lines = ["data: " + json.dumps(frame) for frame in frames]
    lines.append("data: [DONE]")
    return "\n\n".join(lines) + "\n"


@pytest.mark.parametrize("scenario", [
    "live-readonly", "live-turn", "missing-otel-env", "missing-token-metric",
    "openobserve-unreachable", "missing-trace", "bad-trace-id", "metric-cold-start",
])
def test_observability_livecheck_pipeline(scenario, monkeypatch, capsys) -> None:
    compiled = compile(_pipeline_source(), str(SCRIPT), "exec")
    deletes: list = []
    searches: list[str] = []
    chat_requests: list = []

    def open_request(request, timeout):
        parts = urlsplit(request.full_url)
        path, query = parts.path, parse_qs(parts.query)
        method = request.get_method()
        if path == "/api/default/streams":
            if scenario == "openobserve-unreachable":
                raise URLError("connection refused")
            return _Response({"list": [{"name": "http_requests_total"},
                                       {"name": "agent_llm_tokens_total"}]})
        if path == "/api/v1/auth/token":
            assert json.loads(request.data)["roles"] == ["operator"]
            return _Response({"access_token": "fixture-platform-token"})
        if path == "/api/v1/sessions" and method == "POST":
            assert json.loads(request.data) == {}
            return _Response({"session_id": "ses-obs-livecheck"})
        if path == "/api/v1/sessions/ses-obs-livecheck" and method == "DELETE":
            deletes.append(request)
            return _Response({})
        if path == "/api/v1/chat/stream":
            chat_requests.append(request)
            rid = "not-a-trace-id" if scenario == "bad-trace-id" else TRACE_ID
            return _Response(_sse([{"type": "message_delta",
                                    "session_id": "ses-obs-livecheck",
                                    "request_id": rid, "delta": "healthy"}]))
        if path == "/api/default/_search":
            stream_type = query.get("type", [""])[0]
            searches.append(stream_type)
            if stream_type == "traces":
                if scenario == "missing-trace":
                    return _Response({"hits": []})
                return _Response({"hits": [{"name": "chat deepseek-v4-flash",
                                            "trace_id": TRACE_ID,
                                            "gen_ai_usage_input_tokens": 5352,
                                            "gen_ai_usage_output_tokens": 1}]})
            if stream_type == "metrics":
                # Cold cluster: the token stream is not ingested until the first
                # export lands, so the opening metrics _search answers 400. The
                # script must tolerate it and retry rather than fail outright.
                if scenario == "metric-cold-start" and searches.count("metrics") == 1:
                    raise HTTPError(request.full_url, 400, "stream not found", {}, None)
                return _Response({"hits": [{"provider": "deepseek",
                                            "model": "deepseek-v4-flash",
                                            "direction": "input", "value": 5352}]})
        raise AssertionError("unexpected livecheck request: %s %s" % (method, request.full_url))

    def fake_run(command, **kwargs):
        assert command[0] == "kubectl" and "exec" in command
        if "printenv" in command:
            stdout = "false\ntrue\n" if scenario == "missing-otel-env" else "true\ntrue\n"
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        if "curl" in command:
            body = ("# TYPE http_requests_total counter\n" if scenario == "missing-token-metric"
                    else "# HELP agent_llm_tokens_total LLM tokens\n"
                         "# TYPE agent_llm_tokens_total counter\n")
            return SimpleNamespace(returncode=0, stdout=body, stderr="")
        raise AssertionError("unexpected kubectl invocation: %r" % (command,))

    monkeypatch.setenv("OO_ROOT_USER_EMAIL", "obs@luban-aiops.local")
    monkeypatch.setenv("OO_ROOT_USER_PASSWORD", PASSWORD)
    monkeypatch.setenv("OO_ENDPOINT", "http://oo.invalid")
    monkeypatch.setenv("GATEWAY_URL", "http://gw.invalid")
    monkeypatch.setenv("IDENTITY_URL", "http://id.invalid")
    monkeypatch.setenv("NAMESPACE", "dev-luban-aiops")
    if scenario in _TURN_SCENARIOS:
        monkeypatch.setenv("LUBAN_OBS_DRIVE_PAID_TURN", "1")
    else:
        monkeypatch.delenv("LUBAN_OBS_DRIVE_PAID_TURN", raising=False)
    monkeypatch.setattr(urllib.request, "build_opener",
                        lambda *a, **k: SimpleNamespace(open=open_request))
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    if scenario in _SUCCESS:
        exec(compiled, {"__name__": "__main__"})
        out = capsys.readouterr().out
        if scenario == "live-readonly":
            assert "OBSERVABILITY_LIVECHECK_LIVE_OK" in out
            assert deletes == [] and searches == []  # pre-flight never drives a turn
        else:
            assert "OBSERVABILITY_LIVECHECK_TURN_OK" in out and TRACE_ID in out
            assert len(deletes) == 1  # the throwaway session is always cleaned up
            assert "traces" in searches and "metrics" in searches
            if scenario == "metric-cold-start":
                # The opening 400 (stream not yet ingested) must be tolerated and
                # retried to success, not surfaced as a failure.
                assert searches.count("metrics") >= 2
            # The turn must NOT pin an X-Request-ID, so the gateway bridges the
            # request_id to the active OTel trace_id (the correlation invariant).
            assert chat_requests and chat_requests[0].get_header("X-request-id") is None
    else:
        with pytest.raises(SystemExit) as excinfo:
            exec(compiled, {"__name__": "__main__"})
        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "OBSERVABILITY_LIVECHECK_FAILED" in err
        assert PASSWORD not in err and "fixture-platform-token" not in err  # secret-free
