#!/bin/sh
# Apply the config-as-code OpenObserve dashboards (SPEC-065 R-3).
#
# Idempotently imports every ``*.dashboard.json`` in this directory into the
# in-cluster OpenObserve, matching each file by its stable ``dashboardId``:
# an existing dashboard is updated (PUT), a missing one is created (POST). Re-
# running never duplicates.
#
# This is a LIVE, state-mutating operation against the observability backend,
# so it is deliberately NOT part of ``make verify`` (that runs the offline
# ``validate_dashboards.py`` render/import gate). Run it as an operator step, or
# from the SPEC-065 R-4 gated live-check, after the R-2 OTel push is enabled.
#
# Prerequisites
#   1. Reach the OpenObserve router. Locally, port-forward it:
#        kubectl port-forward -n openobserve svc/openobserve-router 5080:5080
#      then use the default OO_ENDPOINT=http://localhost:5080. In-cluster, set
#      OO_ENDPOINT=http://openobserve-router.openobserve.svc.cluster.local:5080.
#   2. Export the OpenObserve root credentials (the same pair that provisions
#      the OTLP ingest Basic-auth header via sync-otel-secrets.sh). They are
#      used for HTTP Basic auth on the management API and are never echoed:
#        OO_ROOT_USER_EMAIL=... OO_ROOT_USER_PASSWORD=... \
#          shared/platform-ops/dashboards/apply-dashboards.sh
#
# Configuration (env, with defaults):
#   OO_ENDPOINT   OpenObserve base URL        (default http://localhost:5080)
#   OO_ORG        organization                (default default)
#   OO_FOLDER     dashboard folder            (default default)
#
# The script fails loudly (non-zero exit) on the first dashboard that OpenObserve
# rejects, printing the HTTP status and response body.

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

OO_ENDPOINT="${OO_ENDPOINT:-http://localhost:5080}"
OO_ORG="${OO_ORG:-default}"
OO_FOLDER="${OO_FOLDER:-default}"

if [ -z "${OO_ROOT_USER_EMAIL:-}" ] || [ -z "${OO_ROOT_USER_PASSWORD:-}" ]; then
  echo "ERROR: OO_ROOT_USER_EMAIL / OO_ROOT_USER_PASSWORD are not exported." >&2
  echo "OpenObserve's management API needs Basic auth; export the root" >&2
  echo "credentials (as for sync-otel-secrets.sh) and re-run." >&2
  exit 2
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "ERROR: curl is required but not on PATH." >&2
  exit 2
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required (to read dashboardId/title) but not on PATH." >&2
  exit 2
fi

API="$OO_ENDPOINT/api/$OO_ORG/dashboards"
AUTH="-u ${OO_ROOT_USER_EMAIL}:${OO_ROOT_USER_PASSWORD}"

# Field-extract from a dashboard JSON file without a JSON lib dependency in the
# happy path; python3 keeps it exact.
_field() {
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2],""))' "$1" "$2"
}

echo "OpenObserve dashboards: endpoint=$OO_ENDPOINT org=$OO_ORG folder=$OO_FOLDER"

# Fetch the current dashboard list once (id -> title) to decide create vs update.
# shellcheck disable=SC2086  # AUTH is intentionally word-split (-u user:pass).
LIST=$(curl -sS $AUTH "$API?folder=$OO_FOLDER" || true)

applied=0
created=0
updated=0
for file in "$SCRIPT_DIR"/*.dashboard.json; do
  [ -e "$file" ] || continue
  applied=$((applied + 1))
  name=$(basename "$file")
  did=$(_field "$file" dashboardId)
  title=$(_field "$file" title)
  if [ -z "$did" ]; then
    echo "ERROR: $name has no dashboardId; refusing to apply." >&2
    exit 1
  fi

  # Does a dashboard with this id already exist in the folder?
  exists=$(printf '%s' "$LIST" | python3 -c '
import json,sys
did=sys.argv[1]
try:
    data=json.load(sys.stdin)
except Exception:
    print(""); raise SystemExit
for d in data.get("dashboards",[]) if isinstance(data,dict) else []:
    if str(d.get("dashboardId",""))==did:
        print("yes"); break
else:
    print("")
' "$did")

  if [ "$exists" = "yes" ]; then
    method=PUT
    url="$API/$did?folder=$OO_FOLDER"
  else
    method=POST
    url="$API?folder=$OO_FOLDER"
  fi

  # shellcheck disable=SC2086
  body=$(curl -sS $AUTH -X "$method" "$url" \
    -H 'Content-Type: application/json' \
    --data-binary "@$file" \
    -w '\n%{http_code}')
  status=$(printf '%s' "$body" | tail -n1)
  payload=$(printf '%s' "$body" | sed '$d')

  case "$status" in
    2*)
      if [ "$method" = "PUT" ]; then updated=$((updated + 1)); else created=$((created + 1)); fi
      echo "  ✓ $method $name  [$status]  id=$did  \"$title\""
      ;;
    *)
      echo "  ✗ $method $name  [$status]  id=$did  \"$title\"" >&2
      echo "    response: $payload" >&2
      echo "ERROR: OpenObserve rejected $name (HTTP $status)." >&2
      exit 1
      ;;
  esac
done

if [ "$applied" -eq 0 ]; then
  echo "ERROR: no *.dashboard.json found in $SCRIPT_DIR." >&2
  exit 1
fi

echo "Applied $applied dashboard(s): $created created, $updated updated."
echo "Reach them in the OpenObserve UI: Dashboards → folder '$OO_FOLDER'."
