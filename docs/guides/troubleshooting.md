# Troubleshooting Guide

A symptom-based diagnostic guide for the most common deployment and runtime issues.
Each symptom includes the likely cause, diagnostic commands, and resolution steps.

## General Diagnostic Commands

```bash
# List all pods and their status
kubectl -n dev-luban-aiops get pods

# View logs for a specific service
kubectl -n dev-luban-aiops logs deployment/<service-name> --tail=50

# Check readiness of a specific service
kubectl -n dev-luban-aiops exec deployment/<service-name> -- \
  curl -s localhost:8000/health/ready | jq

# View environment variables of a running pod
kubectl -n dev-luban-aiops exec deployment/<service-name> -- env | sort

# Port-forward for direct service access
kubectl -n dev-luban-aiops port-forward service/<service-name> <local-port>:8000

# View Prometheus metrics
kubectl -n dev-luban-aiops exec deployment/<service-name> -- \
  curl -s localhost:8000/metrics
```

---

## Symptom: Worker is alive but unready, or execution recovery is uncertain

SPEC-063 separates process liveness from safe mutation admission. A 200 from
`/health/live` with 503 from `/health/ready` is expected while admission is
explicitly disabled. Do not enable it merely to make a rollout green.

| Symptom | Check and safe response |
|---|---|
| Worker remains unready | Inspect the bounded readiness reason. Check actual Postgres connectivity/backend, schema verification, signing/handoff configuration, both service admission flags, and the catalog's admission flag/epoch. Runtime startup never creates or repairs the ledger. |
| `epoch_mismatch` after a restore | Keep mutations disabled. Reconcile the external epoch and retained evidence through the [cutover/restore runbook](execution-cutover-restore.md); a restored same-epoch snapshot cannot detect its own rollback. |
| Disconnect, timeout, or `outcome_unknown` after approval | Reload the owner's session and inspect recovery history. Correlate execution ID and original request ID with gateway/target evidence; a missing receipt or audit event is inconclusive. Never retry/reset the consumed claim. |
| Recovery reports unavailable | Treat this as a failed status read, not empty history or success. Restore the dependency's availability without enabling mutations or clearing run stops. Read-only investigation keeps existing policy gates. |
| A late success appears but the run remains stopped | Expected: metadata recovery does not recreate the original response or reopen continuation. Account for still-running downstream work and independently verify the target before considering a fresh, separately approved action. |
| Copy password never appears after an interrupted reset | Held delivery requires the original validated result and durable agent acceptance. Restart, replay, uncertainty, or lost acceptance cannot release it; the hold is discarded or expires. Recovery cannot reconstruct the password. |

Use readiness metadata and scoped logs, not raw environment/Secret dumps: never
paste DSNs, tokens, passwords, or delivery bodies into troubleshooting artifacts.
Stopping a worker does not cancel remote work or release its dispatch claim.

## Symptom: "Agent says access not granted" or "no tools available"

**Most likely cause:** Token delegation secrets are missing or mismatched.

The agent needs a working token delegation chain to invoke tools. platform-gateway exchanges
the user's portal JWT for a short-lived delegated token via identity-service. Without matching
secrets, the exchange fails and tool calls are silently skipped.

**Diagnostic:**

```bash
# Check delegation metrics
kubectl -n dev-luban-aiops exec deployment/platform-gateway -- \
  curl -s localhost:8000/metrics | grep delegation

# Check identity-service logs for exchange errors
kubectl -n dev-luban-aiops logs deployment/identity-service --tail=30 | grep -i exchange

# Verify both secrets exist
kubectl -n dev-luban-aiops get secret platform-gateway-runtime-secrets identity-service-runtime-secrets
```

**Resolution:**

```bash
# Re-provision delegation secrets (generates a new shared secret if not exported)
shared/platform-ops/gitops/sync-delegation-secrets.sh

# Restart the affected deployments
kubectl -n dev-luban-aiops rollout restart deployment/platform-gateway deployment/identity-service
kubectl -n dev-luban-aiops rollout status deployment/platform-gateway --timeout=120s
kubectl -n dev-luban-aiops rollout status deployment/identity-service --timeout=120s
```

After restart, verify `delegation_exchange_total{result="success"}` increments when you send
a chat message.

---

## Symptom: "Agent has no tools" or tool list is empty

**Most likely cause:** `TOOL_GATEWAY_URL` is unset, the tool-gateway pod is unhealthy, or the
Kubernetes connector is not configured.

**Diagnostic:**

```bash
# Check agent-service environment
kubectl -n dev-luban-aiops exec deployment/agent-service -- env | grep TOOL_GATEWAY

# Check tool-gateway readiness
kubectl -n dev-luban-aiops exec deployment/tool-gateway -- \
  curl -s localhost:8000/health/ready | jq

# List registered tools directly
kubectl -n dev-luban-aiops port-forward service/tool-gateway 18100:8000
curl -s http://127.0.0.1:18100/api/v1/tools | jq '.[].name'
```

**Resolution:**

- If `TOOL_GATEWAY_URL` is empty: set `TOOL_GATEWAY_URL=http://tool-gateway:8000` in
  `agent-platform/runtime-config.env` and redeploy.
- If tool-gateway readiness shows `degraded` with a `policy_error`: the policy ConfigMap is
  missing or malformed. Re-apply the overlay: `make deploy`.
- If the K8s connector returns `K8S_NOT_CONFIGURED`: verify `GATEWAY_K8S_ENABLED=true` and
  the RBAC Role/RoleBinding exist. See [Tool Configuration](tool-configuration.md).

---

## Symptom: Portal login fails

**Most likely cause:** OIDC misconfiguration or Keycloak unreachable.

**Diagnostic:**

```bash
# Check identity-service logs for OIDC errors
kubectl -n dev-luban-aiops logs deployment/identity-service --tail=30 | grep -i oidc

# Verify Keycloak is reachable from the cluster
kubectl -n dev-luban-aiops exec deployment/identity-service -- \
  curl -s -o /dev/null -w '%{http_code}' \
  $(kubectl -n dev-luban-aiops exec deployment/identity-service -- printenv KEYCLOAK_BASE_URL)/realms/$(kubectl -n dev-luban-aiops exec deployment/identity-service -- printenv KEYCLOAK_REALM)/.well-known/openid-configuration

# Check OIDC configuration
kubectl -n dev-luban-aiops exec deployment/identity-service -- env | grep -E 'KEYCLOAK|OIDC'
```

**Resolution:**

- If Keycloak is unreachable: check network policies, DNS resolution, and the
  `KEYCLOAK_BASE_URL` value.
- If the OIDC callback fails with a redirect URI mismatch: verify `OIDC_REDIRECT_URI` (plus
  `OIDC_EXTRA_REDIRECT_URIS`) cover the browser-accessible URL. The broker always starts
  the flow with the primary `OIDC_REDIRECT_URI` (`https://aiops.luban.metasync.cc/callback`);
  the extras (`https://aiops.luban.k8s.orb.local/callback`,
  `http://localhost:18080/callback`) are registered with Keycloak for reachability only
  and are never selected as the callback — a sign-in started on one of those origins
  therefore lands back on the canonical hostname instead. Reconcile the
  Keycloak client: `shared/platform-ops/gitops/dev-k8s/reconcile-portal-oidc-client.sh`.
- If login completes but the portal shows an error: check the platform-gateway logs for JWT
  verification failures (`kubectl logs deployment/platform-gateway | grep -i token`).

---

## Symptom: Stream never completes or agent returns empty response

**Most likely cause:** agent-service is not configured with an LLM provider or the API key is
invalid.

**Diagnostic:**

```bash
# Check agent-service runtime metadata
kubectl -n dev-luban-aiops port-forward service/agent-service 18000:8000
curl -s http://127.0.0.1:18000/api/v2/runtime | jq
# Look for: runtime_mode, runtime_state, provider, model_name

# Check health endpoint
curl -s http://127.0.0.1:18000/api/v2/health | jq
# Look for: configured: true

# Check agent-service logs for provider errors
kubectl -n dev-luban-aiops logs deployment/agent-service --tail=30 | grep -iE 'provider|error|api_key'
```

**Resolution:**

- If `runtime_state` is `placeholder` or `configured` is `false`: the API key is missing or
  invalid. Re-provision: `shared/platform-ops/gitops/sync-runtime-secret.sh <profile>`, then
  restart: `kubectl -n dev-luban-aiops rollout restart deployment/agent-service`.
- If the provider returns 401/403: the API key is expired or invalid. Update the secret and
  re-sync.
- If the stream starts but stalls: check the chat timeout
  (`CHAT_RESPONSE_TIMEOUT_SECONDS`, default 120s) and the provider's rate limits.

---

## Symptom: Tool returns "denied by policy"

**Most likely cause:** The user's role lacks the required action in the policy bundle.

**Diagnostic:**

```bash
# Check tool-gateway logs for policy decisions
kubectl -n dev-luban-aiops logs deployment/tool-gateway --tail=30 | grep "policy decision"
# Look for: action, decision, subject, roles

# Verify the mounted policy bundle
kubectl -n dev-luban-aiops exec deployment/tool-gateway -- \
  cat /etc/luban/policy/policy.yaml

# Check the user's roles from the platform-gateway logs
kubectl -n dev-luban-aiops logs deployment/platform-gateway --tail=30 | grep "identity verified"
```

**Resolution:**

- If the user has an unexpected role: check their OIDC group membership in Keycloak (realm
  `luban-aiops`). The role mapping is: `ops-admins` → `platform-admin`,
  `ops-approvers` → `approver`, `ops-operators` → `operator`,
  `ops-observers` → `read-only-observer`, `ops-auditors` → `auditor`,
  `ops-developers` → `developer`.
- If the policy bundle is outdated: follow the
  [Policy Bundle Rollout runbook](configuration-reference.md#policy-bundle-rollout-spec-048) —
  edit the canonical source
  (`shared/shared-contracts/policies/policy-default.yaml`, bumping `version`),
  record the intent in `policy-scenarios.yaml`, `make sync-policy`,
  `make verify`, and redeploy. Confirm the enforced bundle via the
  `policy_bundle_sha256` fingerprint on each gateway's `/health/ready`
  (bundles are cached keyed on the configured path — a changed ConfigMap
  takes effect on pod restart).
- Users with no matching OIDC group default to `read-only-observer`, which has tool access
  for read-only tools.

---

## Symptom: Tool returns "ELASTIC_NOT_CONFIGURED"

**Most likely cause:** The Elastic connector is not enabled or not configured.

**Diagnostic:**

```bash
# Check tool-gateway configuration
kubectl -n dev-luban-aiops exec deployment/tool-gateway -- env | grep ELASTIC
```

**Resolution:**

1. Set `GATEWAY_ELASTIC_ENABLED=true` in `tool-gateway/runtime-config.env`.
2. Set `GATEWAY_ELASTIC_URL` to your Elasticsearch cluster URL.
3. Provide authentication: `GATEWAY_ELASTIC_API_KEY` (preferred) or
   `GATEWAY_ELASTIC_USERNAME` + `GATEWAY_ELASTIC_PASSWORD`.
4. Redeploy: `make build && make deploy`.

See the [Elastic Connector Checklist](tool-configuration.md#elastic-connector) for the full
activation procedure.

---

## Symptom: Pods fail with ErrImagePull after deployment

**Most likely cause:** Image tags were reset to the `dev-local` placeholder by a raw
`kubectl apply -k` command.

**Diagnostic:**

```bash
kubectl -n dev-luban-aiops get pods
# Look for: ErrImagePull or ImagePullBackOff

kubectl -n dev-luban-aiops get deployment -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.template.spec.containers[0].image}{"\n"}{end}'
# If images show :dev-local, tags were not patched
```

**Resolution:**

Always deploy via `make deploy` (which handles image tag patching). To fix manually:

```bash
# Re-run the deploy overlay script which sets correct image tags
shared/platform-ops/gitops/deploy-overlay.sh
```

---

## Symptom: Policy bundle fails to load (readiness shows "degraded")

**Most likely cause:** The policy ConfigMap is missing or the YAML is malformed.

**Diagnostic:**

```bash
# Check readiness — the policy_error field explains the failure, and
# policy_bundle_sha256 fingerprints the exact loaded bundle text
kubectl -n dev-luban-aiops exec deployment/tool-gateway -- \
  curl -s localhost:8000/health/ready | jq
# Look for: policy_error field

# Check if the ConfigMap exists
kubectl -n dev-luban-aiops get configmap platform-policy -o yaml | head -20

# Check the mounted policy file
kubectl -n dev-luban-aiops exec deployment/tool-gateway -- \
  cat /etc/luban/policy/policy.yaml | head -20
```

**Resolution:**

1. Validate the canonical policy file: `make validate-policy`
   (the scenario guard `make validate-policy-scenarios` catches semantic
   regressions the schema cannot)
2. Re-sync to all locations: `make sync-policy`
3. Re-apply the overlay: `make deploy`

---

## Symptom: "Stream never completes" with token expiry errors

**Most likely cause:** The delegated token TTL has expired during a long-running operation.

**Diagnostic:**

```bash
# Check delegated token TTL
kubectl -n dev-luban-aiops exec deployment/identity-service -- \
  env | grep DELEGATED_TOKEN_TTL

# Check platform-gateway delegation cache behavior
kubectl -n dev-luban-aiops logs deployment/platform-gateway --tail=30 | grep delegation
```

**Resolution:**

Increase `IDENTITY_DELEGATED_TOKEN_TTL_SECONDS` (default 300s) in the identity-broker
runtime config, or investigate why tool invocations are taking longer than the TTL window.

---

## Symptom: Audit view is empty or recent events are missing

**Most likely cause:** An emitter's `*_AUDIT_SERVICE_URL` is unset, the audit-service is
unhealthy, or the ingest credential is mismatched (events then fail with 401 and are only
counted, not stored).

Audit delivery is fire-and-forget: a broken audit path never fails a user-facing request,
so missing events show up silently.

**Diagnostic:**

```bash
# Emitter delivery counters — result="error" means delivery is failing
kubectl -n dev-luban-aiops exec deployment/tool-gateway -- \
  curl -s localhost:8000/metrics | grep audit_emit
kubectl -n dev-luban-aiops exec deployment/platform-gateway -- \
  curl -s localhost:8000/metrics | grep audit_emit
kubectl -n dev-luban-aiops exec deployment/identity-service -- \
  curl -s localhost:8000/metrics | grep audit_emit

# Audit-service readiness (also reports store backend and size)
kubectl -n dev-luban-aiops exec deployment/audit-service -- \
  curl -s localhost:8000/health/ready | jq

# Emitter configuration
kubectl -n dev-luban-aiops exec deployment/tool-gateway -- env | grep AUDIT
```

**Resolution:**

- If `*_AUDIT_SERVICE_URL` is empty: the emitter is in log-only mode by design. Set the URL
  (dev-k8s default `http://audit-service:8000`) in the emitter's `runtime-config.env` and
  redeploy.
- If readiness shows the store is not ready: check the `postgres` StatefulSet
  (`kubectl -n dev-luban-aiops get pods -l app=postgres`) and `AUDIT_DB_URL`.
- If counters show `result="error"` with 401s in the audit-service logs: see the next
  symptom.
- Remember retention: events older than `AUDIT_RETENTION_DAYS` (default 30) are evicted by
  design, and the store is capped at `AUDIT_MAX_EVENTS`.

---

## Symptom: Audit ingest rejected with 401

**Most likely cause:** An emitter's `*_AUDIT_CLIENT_SECRET` does not match the secret
registered for its client id in `AUDIT_INGEST_CLIENTS`.

**Diagnostic:**

```bash
# Audit-service logs name the rejected client id
kubectl -n dev-luban-aiops logs deployment/audit-service --tail=30 | grep -i ingest

# Verify the registry secret exists
kubectl -n dev-luban-aiops get secret audit-service-runtime-secrets
```

**Resolution:**

```bash
# Regenerate one shared ingest secret and sync all four K8s secrets
shared/platform-ops/gitops/sync-audit-secrets.sh

# Restart the emitters and the audit service
kubectl -n dev-luban-aiops rollout restart \
  deployment/audit-service deployment/tool-gateway \
  deployment/platform-gateway deployment/identity-service
```

---

## Symptom: Audit query returns 403 in the portal or via platform-gateway

**Most likely cause:** The caller's roles do not hold `audit:read`. The action is granted
only to `auditor` and `platform-admin` (rule `allow-auditors-audit-read`); all other roles
are denied by default. The portal also hides the audit navigation entry for unauthorized
identities.

**Diagnostic:**

```bash
# The structured 403 body names the denied action
kubectl -n dev-luban-aiops logs deployment/platform-gateway --tail=30 | grep "audit:read"

# Confirm the deployed policy bundle contains the audit rule
kubectl -n dev-luban-aiops exec deployment/platform-gateway -- \
  cat /etc/luban/policy/policy.yaml | grep -A6 allow-auditors-audit-read
```

**Resolution:**

- Check the user's OIDC group membership: `audit:read` is held by `platform-admin`
  (from `ops-admins`) and `auditor` (from `ops-auditors`). The dev realm ships test users
  for both (`luban-admin`, `luban-auditor`).
- If the bundle is missing the rule, it drifted from the canonical source: run
  `make sync-policy` and redeploy.

---

## Symptom: Skills searches return nothing or the agent reports no guidance

**Most likely cause:** One of — a skill source never synced (rejections or a sync
error), the skills connector is not registered in tool-gateway, or the query
secret halves do not match.

**Diagnostic:**

```bash
# Per-source sync state (auth-exempt): check accepted counts, rejections, last_error
kubectl -n dev-luban-aiops exec deployment/skills-hub -- \
  curl -fsS http://localhost:8000/api/v1/skills/status

# Catalog as the agent sees it (requires the query credential)
QUERY_CLIENTS=$(kubectl -n dev-luban-aiops get secret skills-hub-runtime-secrets \
  -o jsonpath='{.data.SKILLS_QUERY_CLIENTS}' | base64 -d)
kubectl -n dev-luban-aiops exec deployment/skills-hub -- \
  curl -fsS -u "tool-gateway:${QUERY_CLIENTS#tool-gateway=}" \
  "http://localhost:8000/api/v1/skills?limit=100"

# Connector registration is gated on this URL
kubectl -n dev-luban-aiops exec deployment/tool-gateway -- \
  sh -c 'echo "${GATEWAY_SKILLS_SERVICE_URL:-<unset>}"'
```

**Resolution:**

- Source shows `rejections`: fix the reported documents
  (`python -m skills_hub.validate <dir>`), then redeploy or restart skills-hub.
- Source shows `last_error`: fix the git URL/credential or mount path; the
  previous slice keeps serving until the next successful sync.
- `GATEWAY_SKILLS_SERVICE_URL` unset or the secrets mismatched: re-run
  `shared/platform-ops/gitops/sync-skills-secrets.sh` and
  `kubectl rollout restart deployment/tool-gateway deployment/skills-hub`.
- Content-level operations (add/revise/remove skills and sources) are covered
  by the [Skills and Guidance Guide](skills-guide.md).

## Symptom: Alertmanager alerts never create incidents (401/503 from webhook)

**Most likely cause:** One of — the bearer token Alertmanager sends does not
match `INCIDENT_WEBHOOK_TOKEN` (401 `UNAUTHORIZED`), or the token was never
provisioned and the webhook fails closed (503 `WEBHOOK_NOT_CONFIGURED`).

**Diagnostic:**

```bash
# Is the token configured at all?
kubectl -n dev-luban-aiops get secret incident-service-runtime-secrets \
  -o jsonpath='{.data.INCIDENT_WEBHOOK_TOKEN}' | base64 -d | wc -c

# Probe the webhook from inside the cluster with the configured token
TOKEN=$(kubectl -n dev-luban-aiops get secret incident-service-runtime-secrets \
  -o jsonpath='{.data.INCIDENT_WEBHOOK_TOKEN}' | base64 -d)
kubectl -n dev-luban-aiops exec deployment/incident-service -- \
  curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"status":"resolved","groupKey":"probe://diag","commonLabels":{}}' \
  http://localhost:8000/api/v1/webhooks/alertmanager
# expected: 200 (idempotent "ignored" resolution for an unknown fingerprint)
```

**Resolution:**

- 503: run `shared/platform-ops/gitops/sync-incident-secrets.sh` and roll
  `deployment/incident-service` so the new secret is mounted.
- 401 with a configured token: rotate both halves together — re-run the sync
  script with an exported `INCIDENT_WEBHOOK_TOKEN` and update the
  Alertmanager receiver's `bearer_token`. Alertmanager retries on 401, so no
  alerts are lost once the token matches.
- Full intake semantics (dedupe, resolve) are covered by the
  [Incident Triage and Collaboration Guide](incident-guide.md).

## Symptom: Run triage fails or an incident is stuck in "triaging"/"triage_failed"

**Most likely cause:** One of — the incident-service → platform-gateway relay
or the token-delegation chain is down (surfaced as a triage error banner),
agent-platform rejected both candidate triage sessions, or the agent turn
timed out. A stuck `triaging` status means the triage turn never completed.

**Diagnostic:**

```bash
# Triage runs are logged structured with the incident id and session used
kubectl -n dev-luban-aiops logs deployment/incident-service --tail=100 \
  | grep -E 'triage|incident-'

# The relay target and credential must be configured on platform-gateway
kubectl -n dev-luban-aiops exec deployment/platform-gateway -- \
  sh -c 'echo "${PLATFORM_GATEWAY_INCIDENT_SERVICE_URL:-<unset>}"'

# Delegation chain health (platform-gateway exchanges the operator token at
# identity-service and relays it to incident-service as X-Delegated-Token)
kubectl -n dev-luban-aiops logs deployment/platform-gateway --tail=100 \
  | grep -iE 'delegat|exchange'
```

**Resolution:**

- Relay 401s: re-run `shared/platform-ops/gitops/sync-incident-secrets.sh`
  (it keeps `INCIDENT_QUERY_CLIENTS` and the gateway client secret in sync)
  and roll incident-service and platform-gateway.
- Session 404 errors in the logs: triage tries `incident-<id>` then
  `incident-<id>--<operator>`; both failing means agent-platform is
  unreachable or its session store is degraded — check agent-platform logs.
- `triage_failed` is terminal-by-design: fix the underlying cause and click
  **Re-run triage**; the latest successful outcome replaces the failure.

## Symptom: Agent cannot see incidents ("incidents.list" tool missing)

**Most likely cause:** The incidents connector is not registered in
tool-gateway — `GATEWAY_INCIDENTS_SERVICE_URL` is unset, or the query secret
halves do not match between tool-gateway and incident-service.

**Diagnostic:**

```bash
# Connector registration is gated on this URL
kubectl -n dev-luban-aiops exec deployment/tool-gateway -- \
  sh -c 'echo "${GATEWAY_INCIDENTS_SERVICE_URL:-<unset>}"'

# Query visibility as the agent sees it (HTTP Basic service credential)
QUERY_CLIENTS=$(kubectl -n dev-luban-aiops get secret incident-service-runtime-secrets \
  -o jsonpath='{.data.INCIDENT_QUERY_CLIENTS}' | base64 -d)
kubectl -n dev-luban-aiops exec deployment/incident-service -- \
  curl -fsS -u "tool-gateway:${QUERY_CLIENTS##*tool-gateway=}" \
  "http://localhost:8000/api/v1/incidents?limit=5"
```

**Resolution:**

- URL unset or secrets mismatched: re-run
  `shared/platform-ops/gitops/sync-incident-secrets.sh` and
  `kubectl rollout restart deployment/tool-gateway deployment/incident-service`.
- The connector is read-only by design; mutating flows (report, triage) go
  through the portal and platform-gateway — see the
  [Incident Triage and Collaboration Guide](incident-guide.md).

## Symptom: No traces/metrics/logs appear in OpenObserve

**Most likely cause:** One of — the OTLP ingest auth header is missing from a
service's secret (OpenObserve answers 401 and the exporter drops batches),
`OTEL_ENABLED` is false, or `OTEL_EXPORTER_OTLP_ENDPOINT` points at the wrong
org/path. Telemetry always fails open, so services themselves look healthy.

**Diagnostic:**

```bash
# Gate + endpoint come from the shared ConfigMap
kubectl -n dev-luban-aiops get configmap platform-runtime-config \
  -o jsonpath='{.data.OTEL_ENABLED}{"\n"}{.data.OTEL_EXPORTER_OTLP_ENDPOINT}{"\n"}'

# The auth header must be present in each service's runtime-secrets Secret
kubectl -n dev-luban-aiops get secret skills-hub-runtime-secrets \
  -o jsonpath='{.data.OTEL_EXPORTER_OTLP_HEADERS}' | base64 -d | cut -c1-40

# Exporter errors surface in pod logs ("otel telemetry setup failed",
# "401" from the batch exporter)
kubectl -n dev-luban-aiops logs deployment/skills-hub --tail=50 | grep -i otel
```

**Resolution:**

- Header missing or 401s in the logs: export the OpenObserve root credentials
  (luban-bootstrapper `openobserve/secrets/openobserve.env`) and re-run
  `shared/platform-ops/gitops/sync-otel-secrets.sh` (or `make deploy` with the
  variables exported); it upserts the header into all seven secrets and restarts
  the workloads.
- `OTEL_ENABLED=false`: set it to `true` in
  `dev-k8s/base/shared/runtime.env` and redeploy.
- Endpoint wrong: it must stop at the org prefix
  (`.../api/default`); the exporters append `/v1/{traces,metrics,logs}`.
- Conventions and the log-bridge semantics:
  `shared/shared-contracts/observability-conventions.md`.

## Symptom: Mutating tool absent from discovery ("k8s.delete_pod" not listed)

**Most likely cause:** Mutating tools are deny-by-default at the execution
boundary (SPEC-021). `GATEWAY_MUTATING_TOOLS_ENABLED` is `false` (the shipped
default), so write/admin tools are never registered — they are absent from
`GET /api/v2/tools` and invoke answers `TOOL_NOT_FOUND`.

**Diagnostic:**

```bash
kubectl -n dev-luban-aiops exec deployment/tool-gateway -- \
  sh -c 'echo "${GATEWAY_MUTATING_TOOLS_ENABLED:-<unset>}"'
kubectl -n dev-luban-aiops logs deployment/tool-gateway --tail=200 \
  | grep "mutating tool not registered"
```

**Resolution:**

- This is the intended default posture. To opt in, follow the full activation
  checklist in the
  [Tool and Connector Guide](tool-configuration.md#mutating-tool-activation-checklist-k8sdelete_pod)
  — gateway flag, opt-in pod-delete RBAC, HITL bridging, and `tools:mutate`
  grants all need to hold together.
- If the flag is already `true` but the tool is missing, the Kubernetes
  connector itself is off (`GATEWAY_K8S_ENABLED=false`).

## Symptom: Mutating tool invoke returns 403 "denied"

**Most likely cause:** The caller holds `tools:invoke` but not `tools:mutate`.
Read tools keep requiring only `tools:invoke`; write/admin tools additionally
require `tools:mutate`, granted by default to `platform-admin`, `approver`,
and `operator` (SPEC-021, amended by SPEC-030 R-4 so a tier_2-approved call
resumed under the approver's delegated token passes admission).

**Diagnostic:**

```bash
# The deny is policy-decision logged and audited with action=tools:mutate
kubectl -n dev-luban-aiops logs deployment/tool-gateway --tail=200 \
  | grep "mutating tool invocation denied"

# Live matrix: check the caller's role against tools:mutate. Since
# SPEC-030 the default bundle answers require_approval on tools:mutate,
# so the boolean cell reads false for everyone — the approval requirement
# (tier and decider roles) rides the additive approval_requirements map.
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:18000/api/v1/policy/matrix \
  | jq '.matrix["operator"]["tools:mutate"], .approval_requirements["operator"]["tools:mutate"]'
```

**Resolution:**

- Expected behavior for `developer`, `auditor`, and
  `read-only-observer`. Extending the grant is a deliberate policy-bundle
  edit — see the
  [Approval and HITL Governance Guide](approval-and-hitl.md#defining-approval-requirements-today).

## Symptom: Confirming a parked mutating call returns 403

**Most likely cause:** The default bundle puts `tools:mutate` under a
`tier_2` approval requirement (SPEC-030): only designated approvers
(`approver`, `platform-admin`) may approve, and the requester cannot
approve their own parked call. The gateway bridge rejects both with a
structured 403 naming the reason (`not_a_designated_approver` or
`self_approval`); the parked call stays parked.

**Diagnostic:**

```bash
# The blocked attempt is audited as confirmation_decided with blocked=true
kubectl -n dev-luban-aiops logs deployment/platform-gateway --tail=200 \
  | grep confirmation_decided

# The parked batch's action and owner are inspectable without deciding
# (agent-platform v2 surface; port-forward service/agent-service first)
kubectl -n dev-luban-aiops port-forward service/agent-service 18000:8000
curl -s -H "X-User-ID: $USER" \
  "http://127.0.0.1:18000/api/v2/chat/pending-confirmation?session_id=<session_id>" | jq
```

**Resolution:**

- Have a different user holding a designated decider role approve the
  parked call; deny stays open to any `chat:confirm` holder, so the
  requester can always cancel their own parked call.

## Symptom: Agent proposes an action but no confirmation card appears

**Most likely cause:** HITL confirmation bridging is disabled
(`AGENT_HITL_CONFIRM_TIMEOUT=0`). With bridging off, agent-platform excludes
mutating tools from the toolkit entirely, so the agent should not offer them;
if the model still describes an action it cannot perform, the turn carries a
system notice saying mutating actions are unavailable — no card ever appears
and nothing silently runs.

**Diagnostic:**

```bash
kubectl -n dev-luban-aiops exec deployment/agent-service -- \
  sh -c 'echo "${AGENT_HITL_CONFIRM_TIMEOUT:-<unset>}"'
kubectl -n dev-luban-aiops logs deployment/agent-service --tail=200 \
  | grep "HITL bridging disabled"
```

**Resolution:**

- Set `AGENT_HITL_CONFIRM_TIMEOUT` to a positive value (dev-k8s ships `600`)
  and restart agent-service; mutating tools reappear in the toolkit and park
  for confirmation as designed.

## Symptom: Approved a mutating confirmation but it fails with K8S_PERMISSION_DENIED

**Most likely cause:** The platform gates passed (policy + confirmation), but
the tool-gateway's Kubernetes service account lacks `delete` on pods. The
opt-in pod-delete RBAC manifest was not applied.

**Diagnostic:**

```bash
kubectl -n dev-luban-aiops auth can-i delete pods \
  --as=system:serviceaccount:dev-luban-aiops:tool-gateway
# expected: yes (only after the opt-in Role/RoleBinding is applied)
```

**Resolution:**

- Apply the pod-delete Role/RoleBinding
  (`shared/platform-ops/gitops/runtime-profiles/mutating-dev/tool-gateway-pod-delete.yaml`)
  and retry. The structured error, the `confirmation_decided` audit event, and
  the failed `tool_invoked` event all stay in the trail — nothing half-deleted:
  pod deletion is a single API call that either succeeded or did not.

## Symptom: Session workspace shows no history (`transcript_available: false`)

**Most likely cause:** The session API (SPEC-022 R-1) reconstructs transcripts
best-effort from the kernel state snapshot. `transcript_available: false` with
an empty `transcript` is an explicit fallback, not an error, and it is normal
when no snapshot exists yet (a session created but never chatted, or the
snapshot was dropped with the session's state store entry). It also covers a
corrupted snapshot, which is logged as a warning by agent-platform.

**Diagnostic:**

```bash
# Session detail carries the fallback flag explicitly
curl -s -H "X-User-ID: $USER" \
  http://localhost:8080/api/v1/sessions/<session_id> | jq '.transcript_available, .transcript'

# agent-platform logs a warning when a snapshot cannot be parsed
kubectl -n dev-luban-aiops logs deployment/agent-service | grep -i transcript
```

**Resolution:**

- For a fresh session, send a chat turn first — the snapshot appears after the
  first completed turn and the transcript follows.
- For an older session with a warning in the logs, the snapshot is corrupt;
  the session itself remains usable (chat continues), only its history view
  falls back. Transcripts exclude system and tool frames by design, so a
  transcript shorter than the raw stream is expected.

## Symptom: Session detail returns `evidence_turns: null`

**Most likely cause:** The evidence store (SPEC-025) is unreadable for that
request — for example, the Postgres backend dropped. `null` is an explicit
degradation (like `transcript_available: false`), never a 500: the session,
its transcript, and chat all keep working, only replayed evidence cards are
absent. An empty list (`[]`) instead means the session simply stored no tool
evidence (no tool calls ran in it). Evidence persistence itself is
best-effort, so a failed write never fails a turn — it logs and increments
`evidence_store_writes_total{result="error"}`.

**Diagnostic:**

```bash
# null = store unreadable, [] = nothing stored
curl -s -H "X-User-ID: $USER" \
  http://localhost:8080/api/v1/sessions/<session_id> | jq '.evidence_turns'

# agent-platform logs a warning per unreadable read and failed write
kubectl -n dev-luban-aiops logs deployment/agent-service | grep -i evidence

# write failures and truncation are observable via metrics
curl -s http://localhost:8000/metrics | grep evidence_
```

**Resolution:**

- Check the agent state database health (`AGENT_STATE_DB_URL`); the evidence
  store shares the backend knob and fails open to memory when Postgres is
  unreachable at startup.
- Truncation notes are not faults: an `entry_cap` marker means one payload
  exceeded `AGENT_EVIDENCE_ENTRY_MAX_CHARS`, and a `session_budget` marker
  means the oldest payloads of that session were evicted to fit
  `AGENT_EVIDENCE_SESSION_MAX_BYTES` (metadata survives both).

## Symptom: Session delete returns 409 (cannot delete a session)

**Most likely cause:** The session holds an unresolved parked HITL
confirmation (SPEC-020). Deleting it would orphan the parked decision, so the
API refuses the delete until the confirmation is resolved. A foreign or
unknown session id returns `404` instead — both anti-enumeration by design.

**Diagnostic:**

```bash
# The session detail flags the pending confirmation
curl -s -H "X-User-ID: $USER" \
  http://localhost:8080/api/v1/sessions/<session_id> | jq '.pending_confirmation'
```

**Resolution:**

- Resolve the parked confirmation first — approve or deny it through the
  portal's confirmation card (or `POST /api/v1/chat/confirm`) — then retry
  the delete. Expired parks still block deletion until they are resolved:
  the flag is TTL-agnostic on purpose, so a stale confirmation card is
  closed deliberately rather than silently dropped.

## Symptom: Portal shows a stale UI after a redeploy

**Most likely cause:** A browser tab opened before the deploy kept the old
`index.html`. The rebuilt portal (SPEC-023) serves hashed `/assets/*` with
`Cache-Control: immutable`, so the only mutable document is `index.html`
(`no-store`); a stale tab keeps referencing the previous bundle until it
reloads the shell.

**Diagnostic:**

```bash
# Shell must be no-store; hashed assets immutable
curl -sI http://localhost:18080/ | grep -i cache-control
curl -sI http://localhost:18080/assets/<hashed>.js | grep -i cache-control
```

**Resolution:**

- Reload the tab (the fresh `index.html` points at the new hashed bundle).
  No manual cache busting is needed: asset filenames change with every
  build, so old assets are never reused by a new shell.

## Symptom: Voice input microphone button is missing or does nothing

**Most likely cause:** Voice composition uses the browser's Web Speech API
(SPEC-023 R-4). Browsers without `SpeechRecognition`/`webkitSpeechRecognition`
(e.g. Firefox) show a disabled microphone with a tooltip; nothing is sent to
the backend. Recognition also requires microphone permission and a browser
supporting the selected language.

**Resolution:**

- Use Chrome or Edge (desktop), grant microphone permission, and retry.
- If recognition errors appear above the composer (not-allowed, no-speech,
  audio-capture, network), they map 1:1 to the browser's error codes.
- Switch the recognition language in the composer selector (en-US / zh-CN);
  the choice drives the recognizer only and is never sent to the platform.
- Voice turns are audited with `details.input_modality: voice` on the
  `chat_started` event; approval/HITL behavior never changes with modality.

## Symptom: Approving a confirmation returns "already_resolved" (409)

**Most likely cause:** The confirmation was already decided by someone else
(or by you in another tab). Confirmations resolve exactly once; since
SPEC-031 the confirm route answers a structured `409 already_resolved`
carrying the winner's outcome (status, decider, decision, decided-at)
instead of re-executing. The portal flips the card to that outcome with
attribution — this is the race-safe path, not an error.

**Resolution:**

- No action needed for the owner: the recorded outcome is authoritative,
  and the durable card in the transcript shows who decided and when.
- Approvers can verify the outcome in the Approvals view's History section
  (decisions stay listed for 30 days).
- A `404` on confirm, by contrast, means the confirm id is unknown or was
  never parked — re-check the session/card you are acting on.

## Symptom: A pending confirmation shows "expired" after a service restart

**Most likely cause:** A parked kernel reply never survives its process
(SPEC-020 posture). At startup, agent-platform flips `pending`
confirmation records older than the HITL confirmation TTL
(`AGENT_HITL_CONFIRM_TIMEOUT`, default 10 minutes) to `expired`
(SPEC-031), so the card stays visible in
the transcript and the approver inbox with an accurate state instead of
hanging forever. Younger pending rows stay untouched — they may still be
answerable on a live replica.

**Resolution:**

- The operator simply re-sends the request; the new confirmation parks
  fresh under the restarted service.
- Approvals made before the restart are unaffected — decided records keep
  their outcome and attribution.
