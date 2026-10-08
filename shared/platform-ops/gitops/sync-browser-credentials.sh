#!/bin/sh

# Provision the browser credential-set secret for the dev-k8s overlay
# (SPEC-049 R-5), and the matching application secret for the
# `acme-admin` sample app (SPEC-059 R-3).
#
# The tool-gateway's web.fill_credential and http.post tools resolve
# named credential sets from the JSON file mounted at
# GATEWAY_BROWSER_CREDENTIAL_SETS (/etc/luban/browser-credentials/
# credential-sets.json) out of the tool-gateway-browser-credentials
# secret. Values never travel through skills, prompts, or tool results.
#
# One generator, two sinks. The `acme-admin` password is generated once
# and written to BOTH consumers:
#
#   tool-gateway-browser-credentials  credential-sets.json gains an
#                                     `acme-admin` entry, which is what
#                                     web.fill_credential(credential_set=
#                                     "acme-admin") and http.post(
#                                     credential_set="acme-admin") resolve
#   acme-admin-credentials            ACME_ADMIN_PASSWORD, consumed by
#                                     the sample app's Deployment, which
#                                     seeds its `admin` user with it
#
# Deriving the second from the first (rather than generating twice) is
# the only arrangement in which the browser surface, the HTTP surface and
# the application cannot disagree about the password.
#
# Provide your own sets via BROWSER_CREDENTIAL_SETS_FILE (a JSON object
# mapping set name -> {"username": ..., "password": ...}); otherwise a
# dev set for the `acme-admin` sample app is generated with a random
# password (never echoed, never committed). An entry may instead carry an
# optional "scheme" — "bearer" (a "token") or "oauth2_client_credentials"
# ("token_url"/"client_id"/"client_secret") per SPEC-068 — for the http.*
# connectors; the full shape is documented in
# docs/guides/tool-configuration.md. The `acme-admin` entry must stay a
# basic username/password set regardless, because the app-side secret is
# derived from it. The override path still produces that app-side secret,
# taken from your file's `acme-admin` entry — an operator supplying their
# own sets supplies the app's password too, or the app cannot start.
#
# Usage:
#   shared/platform-ops/gitops/sync-browser-credentials.sh [namespace]
#
# Override with your own file:
#   BROWSER_CREDENTIAL_SETS_FILE=./cred-sets.json \
#     shared/platform-ops/gitops/sync-browser-credentials.sh
#
# Skip in CI when secrets are injected externally:
#   SKIP_BROWSER_CREDENTIALS=true make deploy
#
# Skipping leaves BOTH secrets unwritten. The sample app then fails
# closed at startup and names this script in its log, rather than
# starting against a well-known default password.

set -eu

NAMESPACE="${1:-dev-luban-aiops}"

if [ "${SKIP_BROWSER_CREDENTIALS:-}" = "true" ]; then
  echo "SKIP_BROWSER_CREDENTIALS=true; skipping browser credential and acme-admin secret provisioning."
  exit 0
fi

SOURCE_FILE="${BROWSER_CREDENTIAL_SETS_FILE:-}"
CLEANUP=""

if [ -n "$SOURCE_FILE" ]; then
  if [ ! -f "$SOURCE_FILE" ]; then
    echo "BROWSER_CREDENTIAL_SETS_FILE not found: $SOURCE_FILE" >&2
    exit 1
  fi
  CRED_FILE="$SOURCE_FILE"
else
  # Dev default: one credential set, for the acme-admin sample app
  # (SPEC-061 retired the static browser-check-target mock and the two
  # sets that served it). Random password; stays inside the cluster
  # secrets.
  CRED_FILE=$(mktemp)
  CLEANUP="$CRED_FILE"
  ACME_PASSWORD=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24)
  cat > "$CRED_FILE" <<EOF
{
  "acme-admin": {
    "username": "admin",
    "password": "${ACME_PASSWORD}"
  }
}
EOF
fi

kubectl -n "$NAMESPACE" create secret generic tool-gateway-browser-credentials \
  --from-file=credential-sets.json="$CRED_FILE" \
  --dry-run=client -o yaml | kubectl apply -f -

# Second sink: the app-side secret, taken from the same file so the two
# surfaces cannot drift. python3 is the JSON parser the repository's
# other shell helpers use (shared/platform-ops/e2e/*.sh); jq is not a
# precondition of `make deploy`.
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found; cannot derive ACME_ADMIN_PASSWORD from the credential-set file." >&2
  echo "Install python3, or create the acme-admin-credentials secret yourself." >&2
  exit 1
fi

# Written to a temp file rather than passed as --from-literal so the
# value never appears in this process's argv (visible to `ps`).
ACME_SECRET_FILE=$(mktemp)
if [ -n "$CLEANUP" ]; then
  CLEANUP="$CLEANUP $ACME_SECRET_FILE"
else
  CLEANUP="$ACME_SECRET_FILE"
fi

python3 -c '
import json, sys

with open(sys.argv[1], encoding="utf-8") as handle:
    sets = json.load(handle)

entry = sets.get("acme-admin")
if not isinstance(entry, dict) or not entry.get("password"):
    sys.stderr.write(
        "credential-set file carries no non-empty \"acme-admin\" password, so the "
        "acme-admin sample app has nothing to authenticate its operator account "
        "with. Add an \"acme-admin\": {\"username\": ..., \"password\": ...} entry "
        "to BROWSER_CREDENTIAL_SETS_FILE.\n"
    )
    raise SystemExit(1)

# No trailing newline: the app compares this value verbatim.
with open(sys.argv[2], "w", encoding="utf-8") as out:
    out.write(entry["password"])
' "$CRED_FILE" "$ACME_SECRET_FILE"

kubectl -n "$NAMESPACE" create secret generic acme-admin-credentials \
  --from-file=ACME_ADMIN_PASSWORD="$ACME_SECRET_FILE" \
  --dry-run=client -o yaml | kubectl apply -f -

for path in $CLEANUP; do
  rm -f "$path"
done

echo "Browser credential sets synced (secret: tool-gateway-browser-credentials)."
echo "acme-admin app password synced (secret: acme-admin-credentials)."

# The gateway reloads the mounted file by mtime, but restart anyway so a
# first deploy does not race the mount.
kubectl -n "$NAMESPACE" rollout restart deployment/tool-gateway >/dev/null
echo "tool-gateway rollout restarted in namespace '$NAMESPACE'."

# The app reads ACME_ADMIN_PASSWORD from its environment at startup, so a
# regenerated secret only takes effect on a new pod. Restart it when it
# is deployed — it is absent on a plain `make deploy`, because samples
# install out-of-band (SPEC-050 R-11).
if kubectl -n "$NAMESPACE" get deployment acme-admin >/dev/null 2>&1; then
  kubectl -n "$NAMESPACE" rollout restart deployment/acme-admin >/dev/null
  echo "acme-admin rollout restarted in namespace '$NAMESPACE'."
fi
