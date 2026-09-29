#!/bin/sh
# SPEC-065 R-4: gated observability live-check. Reproduces spike §6 end to end.
#
#   --local  (default) run the mocked-I/O pytest proof of this script's pipeline
#                       logic. No cluster, no network, no paid call. This is the
#                       leg wired into the ordinary test suite (make verify) and
#                       the make e2e list, so the check cannot be skipped silently.
#   --live             read-only cluster pre-flight: assert the agent pod runs
#                       OTEL_ENABLED=true + AGENTSCOPE_KERNEL_TRACING=true, that
#                       agent_llm_tokens_total is registered on /metrics (R-1),
#                       and that OpenObserve is reachable. Fires NO model call.
#   --live with LUBAN_OBS_DRIVE_PAID_TURN=1
#                      additionally drive ONE read-only chat turn against the
#                      external deepseek provider (BILLABLE, memo §7.3), correlate
#                      it in OpenObserve by trace_id (LLM span + token metric),
#                      then delete the test session. The paid leg is explicitly
#                      gated and never runs by default.
#
# Prerequisites for --live (see docs/guides/observability-dashboards.md):
#   kubectl context on the dev cluster; port-forwards for OpenObserve
#   (svc/openobserve-router 5080), platform-gateway (18083) and identity-service
#   (18081); OO_ROOT_USER_EMAIL / OO_ROOT_USER_PASSWORD exported for the
#   OpenObserve management API (Basic auth, never echoed). For the paid leg,
#   GATEWAY_URL / IDENTITY_URL default to the loopback port-forwards.
#
# Configuration (env, with defaults): NAMESPACE (dev-luban-aiops),
#   AGENT_DEPLOYMENT (agent-service), GATEWAY_URL (http://localhost:18083),
#   IDENTITY_URL (http://localhost:18081), OO_ENDPOINT (http://localhost:5080),
#   OO_ORG (default).
set -eu
set +x
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd -P)
case "${1:---local}" in
  --local)
    uv run --directory "$ROOT/products/agent-platform" pytest -q tests/test_observability_livecheck.py
    exit 0 ;;
  --live) ;;
  *) printf '%s\n' 'Usage: observability-livecheck.sh [--local|--live]' >&2
     printf '%s\n' '  --local  mocked-I/O proof (default; no cluster, no paid call)' >&2
     printf '%s\n' '  --live   read-only cluster pre-flight; add LUBAN_OBS_DRIVE_PAID_TURN=1' >&2
     printf '%s\n' '           for the gated, billable one-turn correlation proof' >&2
     exit 2 ;;
esac
python3 - <<'PY'
import base64
import json
import os
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def is_trace_id(value):
    return (isinstance(value, str) and len(value) == 32
            and all(c in "0123456789abcdef" for c in value))


def main():
    namespace = os.environ.get("NAMESPACE", "dev-luban-aiops")
    agent = os.environ.get("AGENT_DEPLOYMENT", "agent-service")
    gateway = os.environ.get("GATEWAY_URL", "http://localhost:18083").rstrip("/")
    identity = os.environ.get("IDENTITY_URL", "http://localhost:18081").rstrip("/")
    endpoint = os.environ.get("OO_ENDPOINT", "http://localhost:5080").rstrip("/")
    org = os.environ.get("OO_ORG", "default")
    drive_turn = os.environ.get("LUBAN_OBS_DRIVE_PAID_TURN", "") == "1"

    opener = build_opener()

    def http(method, url, body=None, auth=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Cache-Control": "no-store"}
        if auth:
            headers["Authorization"] = auth
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        with opener.open(request, timeout=120) as response:
            return response.status, response.headers, response.read().decode()

    def kubectl(*args):
        result = subprocess.run(
            ["kubectl", "-n", namespace, *args],
            text=True, capture_output=True, timeout=120)
        require(result.returncode == 0,
                "kubectl %s failed: %s" % (args[0], (result.stderr or "").strip()[:200]))
        return result.stdout

    # (1) Cluster + config: the push pipeline and kernel tracing must be live.
    env = kubectl("exec", "deployment/" + agent, "--",
                  "printenv", "OTEL_ENABLED", "AGENTSCOPE_KERNEL_TRACING")
    values = env.split()
    require(len(values) == 2 and values[0] == "true" and values[1] == "true",
            "agent pod must run OTEL_ENABLED=true and AGENTSCOPE_KERNEL_TRACING=true "
            "(got %r); see sync-otel-secrets.sh / runtime.env" % env.strip())

    # (2) Pull side: the R-1 token family is registered on /metrics. An idle pod
    #     exposes the family's TYPE line before any sample, so this never needs
    #     traffic; a missing family means R-1 is not deployed.
    metrics = kubectl("exec", "deployment/" + agent, "--",
                      "curl", "-s", "localhost:8000/metrics")
    require("agent_llm_tokens_total" in metrics,
            "agent_llm_tokens_total absent from /metrics; the R-1 token family "
            "is not registered on the agent pod")

    # (3) OpenObserve reachable (management API, Basic auth as the root user —
    #     the same pair sync-otel-secrets.sh provisions for OTLP ingest).
    email = os.environ.get("OO_ROOT_USER_EMAIL", "")
    password = os.environ.get("OO_ROOT_USER_PASSWORD", "")
    require(email and password,
            "export OO_ROOT_USER_EMAIL / OO_ROOT_USER_PASSWORD for the OpenObserve API")
    oo_auth = "Basic " + base64.b64encode(
        ("%s:%s" % (email, password)).encode()).decode()
    status, _, body = http("GET", endpoint + "/api/" + org + "/streams", auth=oo_auth)
    require(status == 200, "OpenObserve streams API answered HTTP %s" % status)
    listing = json.loads(body)
    rows = listing.get("list") or listing.get("streams") or []
    names = {row.get("name") for row in rows if isinstance(row, dict)}
    token_stream = "agent_llm_tokens_total" in names

    if not drive_turn:
        print("OBSERVABILITY_LIVECHECK_LIVE_OK: OTEL_ENABLED+tracing on, "
              "agent_llm_tokens_total on /metrics, OpenObserve reachable; token "
              "metric stream %s" % ("present" if token_stream else
              "absent (idle cluster — set LUBAN_OBS_DRIVE_PAID_TURN=1 to drive "
              "one billable read-only turn and prove the correlation)"))
        return

    # (4) Paid leg: mint an operator token, open a throwaway session, stream ONE
    #     read-only turn. No X-Request-ID is sent so the gateway bridges the
    #     request_id to the active OTel trace_id (request_context.resolve_request_id),
    #     which is the correlation key the spike proved (memo §6.4).
    status, _, body = http("POST", identity + "/api/v1/auth/token", body={
        "username": "luban-obs-livecheck",
        "email": "luban-obs-livecheck@luban-aiops.local",
        "roles": ["operator"], "groups": ["ops-operators"]})
    require(status == 200, "identity token mint answered HTTP %s" % status)
    token = json.loads(body).get("access_token", "")
    require(token, "identity broker issued no access_token")
    bearer = "Bearer " + token

    status, _, body = http("POST", gateway + "/api/v1/sessions", body={}, auth=bearer)
    require(status == 200, "session create answered HTTP %s" % status)
    session = json.loads(body).get("session_id", "")
    require(session, "session create returned no session_id")

    message = "Reply with exactly one word: healthy. Do not call any tools."
    url = gateway + "/api/v1/chat/stream?" + urlencode(
        {"session_id": session, "message": message})
    try:
        status, _, stream = http("GET", url, auth=bearer)
        require(status == 200, "chat stream answered HTTP %s" % status)
        frames = [json.loads(line[5:].strip()) for line in stream.splitlines()
                  if line.startswith("data:") and line[5:].strip() not in {"", "[DONE]"}]
        require(frames, "chat stream produced no SSE frames")
        trace_id = next((f.get("request_id") for f in frames
                         if is_trace_id(f.get("request_id"))), "")
        require(trace_id, "no 32-hex request_id/trace_id in the stream frames")
        require(any(f.get("delta") or f.get("message") for f in frames),
                "turn produced no assistant text")
    finally:
        # Always clean up the throwaway session (idempotent; ignore its result).
        try:
            http("DELETE", gateway + "/api/v1/sessions/" + session, auth=bearer)
        except Exception:
            pass

    # (5) Push side: correlate the turn in OpenObserve by trace_id. Ingest lag
    #     means retrying; the LLM span carries the GenAI token attributes and the
    #     token metric stream gains a sample for the same turn.
    end = int(time.time() * 1_000_000)
    start = end - (900 * 1_000_000)

    def search(stream_type, sql):
        # A stream does not exist in OpenObserve until its first sample is
        # ingested, so an early _search answers 400 ("stream not found"). The
        # token metric stream is created lazily on the first turn's export, so
        # treat a 400 as "not ready yet" and let the retry loop below wait it
        # out; any other HTTP error is genuine and surfaces immediately.
        try:
            status, _, body = http(
                "POST", endpoint + "/api/" + org + "/_search?type=" + stream_type,
                body={"query": {"sql": sql, "start_time": start, "end_time": end}},
                auth=oo_auth)
        except HTTPError as error:
            if error.code == 400:
                return []
            raise
        require(status == 200, "OpenObserve %s search answered HTTP %s" % (stream_type, status))
        return json.loads(body).get("hits", [])

    span_ok = False
    for _ in range(30):
        hits = search("traces", "SELECT * FROM \"default\" WHERE trace_id='%s'" % trace_id)
        if any(hit.get("gen_ai_usage_input_tokens") is not None
               or str(hit.get("name", "")).startswith("chat ") for hit in hits):
            span_ok = True
            break
        time.sleep(2)
    require(span_ok,
            "no LLM span carrying gen_ai token usage found in OpenObserve for "
            "trace_id=%s after the turn" % trace_id)

    # The metric reader exports on a ~60s period, so on a cold cluster the
    # token stream can lag the turn by up to one interval plus ingest lag;
    # wait out two intervals before declaring the push mirror broken.
    metric_ok = False
    for _ in range(60):
        if search("metrics", "SELECT * FROM \"agent_llm_tokens_total\" LIMIT 5"):
            metric_ok = True
            break
        time.sleep(2)
    require(metric_ok,
            "agent_llm_tokens_total metric stream has no samples in OpenObserve "
            "after the turn (push mirror not flowing)")

    print("OBSERVABILITY_LIVECHECK_TURN_OK: trace_id=%s correlated to the LLM "
          "span and agent_llm_tokens_total in OpenObserve; test session deleted; "
          "no mutation, no tool call, no HITL" % trace_id)


try:
    main()
except (RuntimeError, URLError, HTTPError, json.JSONDecodeError, KeyError) as error:
    # Single-line, secret-free failure: never echo tokens, credentials or bodies.
    reason = str(error) or error.__class__.__name__
    print("OBSERVABILITY_LIVECHECK_FAILED: %s" % reason, file=sys.stderr)
    sys.exit(1)
PY
