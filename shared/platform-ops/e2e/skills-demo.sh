#!/bin/sh

# Skills demo smoke test (SPEC-014 R-6).
#
# Deterministic end-to-end assertions for the skills and grounded guidance
# slice, runnable after `make deploy`:
#   1. skills-hub status reports the platform-skills git source synced with
#      skills and no source reporting an error
#   2. an alert-name search ranks the matching runbook first (deterministic
#      scoring regression check)
#   3. a scripted chat against the gateway shows the agent invoking
#      skills.search (tool_call + tool_result SSE frame pair)
#
# Prerequisites:
#   - kubectl context pointed at the dev cluster
#   - a port-forward for the platform-gateway (chat leg), e.g.:
#       kubectl -n dev-luban-aiops port-forward svc/platform-gateway 18083:8000
#   - a port-forward for the identity broker (chat leg token issuance):
#       kubectl -n dev-luban-aiops port-forward svc/identity-service 18081:8000
#
# Environment overrides:
#   NAMESPACE          (default dev-luban-aiops)
#   GATEWAY_URL        (default http://localhost:18083)
#   IDENTITY_URL       (default http://localhost:18081)
#   CHAT_MESSAGE       (default: the KubePodNotReady prompt)
#   SKIP_CHAT_LEG=true to run only the cluster-side assertions.

set -eu

NAMESPACE="${NAMESPACE:-dev-luban-aiops}"
GATEWAY_URL="${GATEWAY_URL:-http://localhost:18083}"
IDENTITY_URL="${IDENTITY_URL:-http://localhost:18081}"
TEST_USER="${TEST_USER:-luban-operator}"
CHAT_MESSAGE="${CHAT_MESSAGE:-The KubePodNotReady alert is firing for our demo workload. What does our guidance say to check?}"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

echo "==> [1/3] skills-hub status"

STATUS=$(kubectl -n "$NAMESPACE" exec deployment/skills-hub -- \
  curl -fsS http://localhost:8000/api/v1/skills/status)
echo "$STATUS"

# Platform runbooks and SRE alerts arrive only through the `platform-skills`
# git source; the duplicate local ConfigMap sources were removed 2026-10-01.
echo "$STATUS" | grep -q '"source_id":"platform-skills"' \
  || echo "$STATUS" | grep -q '"source_id": "platform-skills"' \
  || fail "status does not report the platform-skills git source"
echo "$STATUS" | grep -qi '"last_error": *null\|"last_error":null' \
  || fail "a source reports a sync error"

echo "==> [2/3] alert-name search ranking (deterministic scoring)"

# Pull the query credential from the provisioned secret.
QUERY_CLIENTS=$(kubectl -n "$NAMESPACE" get secret skills-hub-runtime-secrets \
  -o jsonpath='{.data.SKILLS_QUERY_CLIENTS}' | base64 -d)
QUERY_SECRET=$(printf '%s' "$QUERY_CLIENTS" | tr ',' '\n' \
  | grep '^tool-gateway=' | cut -d= -f2-)

SEARCH_RESULT=$(kubectl -n "$NAMESPACE" exec deployment/skills-hub -- \
  curl -fsS -u "tool-gateway:${QUERY_SECRET}" \
  "http://localhost:8000/api/v1/skills/search?q=KubePodNotReady&limit=5")

TOP_SKILL=$(printf '%s' "$SEARCH_RESULT" | python3 -c "
import json, sys
payload = json.load(sys.stdin)
matches = payload.get('matches', [])
if not matches:
    sys.exit(2)
print(matches[0]['skill_id'])
") || fail "search for KubePodNotReady returned no matches"
# The git-federated platform-skills source is now the only route to this
# document, so the top match must carry its source prefix. Accepting the
# unprefixed local-source id as well would hide a re-introduced duplicate.
case "$TOP_SKILL" in
  "platform-skills/sre-alerting/alerts/kubepodnotready") ;;
  *) fail "expected top match to be the KubePodNotReady runbook, got $TOP_SKILL" ;;
esac
echo "top match: $TOP_SKILL"

if [ "${SKIP_CHAT_LEG:-}" = "true" ]; then
  echo "==> [3/3] chat leg skipped (SKIP_CHAT_LEG=true)"
  echo "Skills smoke test passed."
  exit 0
fi

echo "==> [3/3] scripted chat asserting the skills.search frame pair"

# The gateway verifies broker-issued platform tokens only (issuer
# luban-identity-broker), so the scripted leg asks the identity broker for a
# dev platform token instead of using the raw Keycloak access token.
TOKEN_RESPONSE=$(
  curl -fsS -X POST "$IDENTITY_URL/api/v1/auth/token" \
    -H "Content-Type: application/json" \
    -d "{\"username\": \"$TEST_USER\", \"email\": \"$TEST_USER@luban-aiops.local\", \"roles\": [\"operator\"], \"groups\": [\"ops-operators\"]}"
) || fail "failed to obtain a platform token for $TEST_USER"

ACCESS_TOKEN=$(printf '%s' "$TOKEN_RESPONSE" | python3 -c "
import json, sys
print(json.load(sys.stdin).get('access_token', ''))
")
[ -n "$ACCESS_TOKEN" ] || fail "Keycloak response carried no access_token"

STREAM_OUTPUT=$(curl -fsS --max-time 120 -N \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  "$GATEWAY_URL/api/v1/chat/stream?message=$(python3 -c "
import urllib.parse, sys
print(urllib.parse.quote(sys.argv[1]))" "$CHAT_MESSAGE")") \
  || fail "chat stream request failed"

echo "$STREAM_OUTPUT" | grep -q '"tool_name": *"skills.search"\|"tool_name":"skills.search"' \
  || fail "no skills.search tool_call frame in the SSE stream"
echo "$STREAM_OUTPUT" | grep -q '"type": *"tool_result"\|"type":"tool_result"' \
  || fail "no tool_result frame in the SSE stream"

echo ""
echo "Skills smoke test passed:"
echo "  - both sample sources synced"
echo "  - alert-name search ranks the matching runbook first ($TOP_SKILL)"
echo "  - agent invoked skills.search during the chat leg"
