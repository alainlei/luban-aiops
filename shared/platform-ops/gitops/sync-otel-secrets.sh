#!/bin/sh

# Provision OTLP ingest credentials for the OTel push pipeline (SPEC-005
# completion slice: OpenObserve backend).
#
# Every service pushes traces/metrics/logs over OTLP HTTP to the endpoint in
# the shared ConfigMap (OTEL_EXPORTER_OTLP_ENDPOINT). OpenObserve requires
# Basic auth on ingest, delivered via OTEL_EXPORTER_OTLP_HEADERS. This script
# computes the header from the OpenObserve root credentials and MERGES it
# cluster-side into every service's runtime-secrets Secret (kubectl patch
# touches only the OTEL key, preserving all other keys), then restarts the
# workloads.
#
# The merge is deliberately independent of the local runtime-secrets.env
# files: sibling sync scripts (delegation/audit/skills/incident)
# regenerate those files and re-apply their Secrets wholesale, which would
# wipe any header written through the env files. Merging in the cluster
# keeps OTel provisioning durable across those regenerations.
# Best-effort mirror into existing local env files (and the active runtime
# profile file) keeps local re-provisioning paths consistent.
#
# Usage:
#   OO_ROOT_USER_EMAIL=... OO_ROOT_USER_PASSWORD=... \
#     shared/platform-ops/gitops/sync-otel-secrets.sh [namespace]
#
# Dev credentials live in the luban-bootstrapper repo
# (openobserve/secrets/openobserve.env); source them at provision time only.
# They are never echoed and never committed.
#
# Unset variables: the script skips provisioning with a clear message. Push
# then authenticates as anonymous, OpenObserve answers 401, and the exporters
# fail open — services are unaffected.
#
# Skip in CI when secrets are injected externally:
#   SKIP_OTEL_SECRETS=true make deploy

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
NAMESPACE="${1:-dev-luban-aiops}"

if [ "${SKIP_OTEL_SECRETS:-}" = "true" ]; then
  echo "SKIP_OTEL_SECRETS=true; skipping OTel secret provisioning."
  exit 0
fi

if [ -z "${OO_ROOT_USER_EMAIL:-}" ] || [ -z "${OO_ROOT_USER_PASSWORD:-}" ]; then
  echo "OO_ROOT_USER_EMAIL / OO_ROOT_USER_PASSWORD not exported; skipping."
  echo "OTLP push will authenticate as anonymous (OpenObserve answers 401)"
  echo "and the exporters fail open until the headers are provisioned."
  exit 0
fi

# base64 without line wrapping; the value never reaches the terminal.
AUTH_B64=$(printf '%s:%s' "$OO_ROOT_USER_EMAIL" "$OO_ROOT_USER_PASSWORD" \
  | base64 | tr -d '\n')
OTEL_HEADER_LINE="OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic ${AUTH_B64}"

# Insert or replace KEY=VALUE in an env file, preserving all other lines.
upsert_env_line() {
  upsert_file="$1"
  upsert_key="$2"
  upsert_line="$3"
  touch "$upsert_file"
  if grep -q "^${upsert_key}=" "$upsert_file"; then
    sed -i.bak "s|^${upsert_key}=.*|${upsert_line}|" "$upsert_file"
    rm -f "${upsert_file}.bak"
  else
    printf '%s\n' "$upsert_line" >> "$upsert_file"
  fi
}

# Merge the OTLP header into an existing cluster Secret without touching any
# other key; create the Secret with just the header if it does not exist yet
# (sibling sync scripts fill in the remaining keys on their next run).
merge_secret() {
  secret_name="$1"
  value_b64=$(printf '%s' "${OTEL_HEADER_LINE#OTEL_EXPORTER_OTLP_HEADERS=}" \
    | base64 | tr -d '\n')
  if kubectl -n "$NAMESPACE" get secret "$secret_name" >/dev/null 2>&1; then
    kubectl -n "$NAMESPACE" patch secret "$secret_name" \
      --type merge \
      -p "{\"data\":{\"OTEL_EXPORTER_OTLP_HEADERS\":\"${value_b64}\"}}"
    echo "Merged OTel header into existing secret '$secret_name'."
  else
    kubectl -n "$NAMESPACE" create secret generic "$secret_name" \
      --from-literal="${OTEL_HEADER_LINE}"
    echo "Created secret '$secret_name' with the OTel header only."
  fi
}

BASE_DIR="$SCRIPT_DIR/dev-k8s/base"

# The agent-platform secret comes from the active runtime profile
# (runtime-profiles/<name>/runtime-secrets.env feeds
# agent-platform-runtime-secrets); resolve the profile from the overlay.
PROFILE_DIR=$(sed -n 's|^ *- *\.\./runtime-profiles/||p' \
  "$SCRIPT_DIR/dev-k8s/kustomization.yaml" | head -1)
PROFILE_FILE="$SCRIPT_DIR/runtime-profiles/$PROFILE_DIR/runtime-secrets.env"
if [ -n "$PROFILE_DIR" ] && [ -f "$PROFILE_FILE" ]; then
  # The local profile file is the authoritative source for this Secret (its
  # model/API keys only exist there), so sync it wholesale with the header
  # upserted. This path never loses the header: the upsert runs on every
  # invocation before the secret is re-applied.
  upsert_env_line "$PROFILE_FILE" OTEL_EXPORTER_OTLP_HEADERS "$OTEL_HEADER_LINE"
  kubectl -n "$NAMESPACE" create secret generic agent-platform-runtime-secrets \
    --from-env-file="$PROFILE_FILE" \
    --dry-run=client -o yaml | kubectl apply -f -
  echo "Synced secret 'agent-platform-runtime-secrets' from profile '$PROFILE_DIR'."
else
  echo "No local runtime-profile secret file (profile: ${PROFILE_DIR:-none});"
  echo "merging the OTel header into the cluster Secret instead."
  merge_secret agent-platform-runtime-secrets
fi

for secret_name in \
  audit-service-runtime-secrets \
  execution-runtime-runtime-secrets \
  identity-service-runtime-secrets \
  incident-service-runtime-secrets \
  platform-gateway-runtime-secrets \
  skills-hub-runtime-secrets \
  tool-gateway-runtime-secrets
do
  merge_secret "$secret_name"
done

# Best-effort mirror into the local env files so later sibling syncs that
# happen to rebuild a Secret from one of them do not resurrect a headerless
# state from stale local files. Missing files are simply skipped.
for env_file in \
  "$BASE_DIR/audit-service/runtime-secrets.env" \
  "$BASE_DIR/execution-runtime/runtime-secrets.env" \
  "$BASE_DIR/identity-broker/runtime-secrets.env" \
  "$BASE_DIR/incident-service/runtime-secrets.env" \
  "$BASE_DIR/platform-gateway/runtime-secrets.env" \
  "$BASE_DIR/skills-hub/runtime-secrets.env" \
  "$BASE_DIR/tool-gateway/runtime-secrets.env"
do
  if [ -f "$env_file" ]; then
    upsert_env_line "$env_file" OTEL_EXPORTER_OTLP_HEADERS "$OTEL_HEADER_LINE"
  fi
done

# --- restart all eight workloads ----------------------------------------------

for deployment in agent-service audit-service execution-runtime identity-service \
  incident-service platform-gateway skills-hub tool-gateway
do
  kubectl -n "$NAMESPACE" rollout restart "deployment/$deployment"
done

echo ""
echo "OTel ingest credentials provisioned. Waiting for rollout..."
for deployment in agent-service audit-service execution-runtime identity-service \
  incident-service platform-gateway skills-hub tool-gateway
do
  kubectl -n "$NAMESPACE" rollout status "deployment/$deployment" --timeout=120s
done

echo ""
echo "Telemetry push is now authenticated against OpenObserve."
echo "Traces/metrics/logs flow to OTEL_EXPORTER_OTLP_ENDPOINT (shared ConfigMap)."
