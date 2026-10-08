# Dev K8s Overlay

## Purpose

This directory contains the development Kubernetes overlay for the platform baseline services:

- `web-ui`
- `platform-gateway`
- `tool-gateway`
- `agent-service`
- `execution-runtime`
- `identity-service`
- `audit-service`
- `skills-hub`
- `incident-service`
- `redis`
- `postgres`

## Scope

These manifests are intended to:

- establish service names and ports
- define baseline environment variables
- show the expected request path between services
- provide an in-cluster `Redis` dependency for AgentScope coordination
- provide an in-cluster `PostgreSQL` dependency for the durable audit trail (SPEC-013), the skills store (SPEC-014), the incidents store (SPEC-015), the agent session store (SPEC-016), and agent state persistence (SPEC-017)

The `dev-k8s` overlay is the single development deployment for the platform. It deploys the v2 agent-service contract surface consumed by `platform-gateway` (portal chat/session proxying) and the tool contract consumed by `agent-service` via `tool-gateway` (SPEC-010).

These manifests do not yet provide:

- production hardening
- ingress policy
- autoscaling
- durable `Redis` persistence beyond the pod lifecycle

## SPEC-063 execution admission and first cutover

The 0.43.0 protocol requires a coordinated, mutation-disabled
[cutover](../../../../docs/guides/execution-cutover-restore.md). Stock `make deploy`
is not this procedure: it does not migrate the ledger, set its external epoch,
invoke the downgrade guard, or authorize admission. Its rollout wait expects
readiness, while the disabled worker intentionally reports 503 readiness and
healthy process liveness. Do not enable mutations just to satisfy that wait.

- Agent: explicitly provision `AGENT_EXECUTION_STATE_DB_URL`,
  `AGENT_EXECUTION_ADMISSION_EPOCH`, and `AGENT_EXECUTION_ADMISSION_ENABLED`
  (defaults false).
- Worker: actual Postgres at `EXECUTION_STATE_DB_URL`, matching
  `EXECUTION_ADMISSION_EPOCH`, and `EXECUTION_ADMISSION_ENABLED` (defaults false).
- Catalog: explicitly migrate/verify with admission disabled; enable only after
  old senders are stopped, matching consumers are deployed, evidence is reconciled,
  and operational approval is granted. No memory-backed mutation fallback.
- Keep one worker replica and `Recreate`; 5s preStop plus 35s drain fits the 45s
  pod grace. Durable claims, not replica count, provide duplicate protection.
  Process termination never cancels downstream work or releases a claim.
- The `mutating-dev` profile only opts the gateway into tool availability/RBAC;
  it does not enable durable execution. The new settings are not automatically
  provisioned by the existing secret-sync/deploy path.

Downgrade and database restore require disabled recovery, external epoch/credential
management, old-sender inventory, and the documented validity wait. A direct old
image deployment or same-epoch snapshot restoration bypasses those operational
checks and is not a safe executable rollback.

## Expected Images

The base deployment manifest uses neutral placeholder image tags:

- `luban-aiops/web-ui:dev-local`
- `luban-aiops/platform-gateway:dev-local`
- `luban-aiops/tool-gateway:dev-local`
- `luban-aiops/agent-service:dev-local`
- `luban-aiops/execution-runtime:dev-local`
- `luban-aiops/identity-service:dev-local`
- `luban-aiops/audit-service:dev-local`
- `luban-aiops/skills-hub:dev-local`
- `luban-aiops/incident-service:dev-local`

`make build` and `make deploy` replace those placeholders with the generated `IMAGE_TAG` for each rollout.

This development baseline also uses the upstream `redis:7.2-alpine` image for in-cluster kernel coordination, and `postgres:16-alpine` for the durable audit store, the skills store, the incidents store, and the session store.

## Runtime Wiring

The `platform-runtime-config` `ConfigMap` is assembled from product-scoped env fragments:

- `shared/platform-ops/gitops/dev-k8s/base/shared/runtime.env`
- `shared/platform-ops/gitops/dev-k8s/base/agent-platform/runtime-config.env`
- `shared/platform-ops/gitops/dev-k8s/base/execution-runtime/runtime-config.env`
- `shared/platform-ops/gitops/dev-k8s/base/platform-gateway/runtime-config.env`
- `shared/platform-ops/gitops/dev-k8s/base/tool-gateway/runtime-config.env`
- `shared/platform-ops/gitops/dev-k8s/base/identity-broker/runtime-config.env`
- `shared/platform-ops/gitops/dev-k8s/base/audit-service/runtime-config.env`
- `shared/platform-ops/gitops/dev-k8s/base/skills-hub/runtime-config.env`
- `shared/platform-ops/gitops/dev-k8s/base/incident-service/runtime-config.env`

Because the fragments merge into one `ConfigMap`, each key may appear only once: `IDENTITY_SERVICE_URL` lives in the shared fragment and is consumed by both gateways. The execution-runtime fragment likewise omits `TOOL_GATEWAY_URL` — it inherits the value from the agent-platform fragment.

`execution-runtime` (SPEC-038) ships as an isolated worker: its own Deployment (`replicas: 1`) and ClusterIP Service, no HTTPRoute or gateway route, and two dedicated secrets — `execution-signing-secret` (`EXECUTION_SIGNING_KEY`, shared with agent-service) and `execution-handoff-secret` (`EXECUTION_HANDOFF_TOKEN`, also mapped to `AGENT_EXECUTION_HANDOFF_TOKEN` on agent-service). `deploy.sh` provisions the handoff token via `sync-execution-handoff-secret.sh`; approved mutating calls reach the worker only through the internal authenticated handoff from agent-service (`AGENT_EXECUTION_WORKER_URL`).

The identity-broker config fragment defines the browser callback and logout redirect defaults for the `OIDC` flow. The committed baseline targets a **self-contained** `luban-aiops` realm on the shared development Keycloak, so live testing no longer depends on users from other applications:

- `KEYCLOAK_BASE_URL=https://idp.apps.metasync.cc`
- `KEYCLOAK_REALM=luban-aiops`
- `OIDC_CLIENT_ID=luban-aiops-portal`
- `OIDC_REDIRECT_URI=https://aiops.luban.metasync.cc/callback`
- `OIDC_POST_LOGOUT_REDIRECT_URI=https://aiops.luban.metasync.cc/`
- `OIDC_EXTRA_REDIRECT_URIS=https://aiops.luban.k8s.orb.local/callback,http://localhost:18080/callback`
- `OIDC_EXTRA_POST_LOGOUT_REDIRECT_URIS=https://aiops.luban.k8s.orb.local/,http://localhost:18080/`
- `OIDC_SCOPES=openid groups`

Only `OIDC_REDIRECT_URI` is ever selected as the sign-in callback — the broker starts
every login there, so `https://aiops.luban.metasync.cc` is the canonical portal
entrypoint and the only origin where sign-in round-trips. The extra URIs are registered
with Keycloak for reachability: post-logout redirects select the portal's own origin
from the registered set, but sign-in never does.

The corresponding keys remain:

- `KEYCLOAK_BASE_URL`
- `KEYCLOAK_REALM`
- `OIDC_CLIENT_ID`
- `OIDC_REDIRECT_URI`
- `OIDC_POST_LOGOUT_REDIRECT_URI`
- `OIDC_EXTRA_REDIRECT_URIS`
- `OIDC_EXTRA_POST_LOGOUT_REDIRECT_URIS`
- `OIDC_SCOPES`

### Self-Contained Realm and Test Users

The overlay carries a Git-tracked reconciliation script that provisions the whole
identity surface on the shared Keycloak:

- `shared/platform-ops/gitops/reconcile-luban-realm.sh`

It is idempotent and ensures, in the `luban-aiops` realm:

- the realm itself (registration/password-reset disabled)
- a `groups` client scope mapping Keycloak group membership to the `groups` token claim
- the six role groups expected by identity-broker `ROLE_MAPPINGS`: `ops-admins`,
  `ops-approvers`, `ops-operators`, `ops-observers`, `ops-auditors`, `ops-developers`
- one test user per group, each placed in exactly that group

| Test User | Group | Platform Role |
|---|---|---|
| `luban-admin` | `ops-admins` | `platform-admin` |
| `luban-approver` | `ops-approvers` | `approver` |
| `luban-operator` | `ops-operators` | `operator` |
| `luban-observer` | `ops-observers` | `read-only-observer` |
| `luban-auditor` | `ops-auditors` | `auditor` |
| `luban-developer` | `ops-developers` | `developer` |

All six share a single **development-only** password, defaulting to `luban-dev-2026`
and overridable via `LUBAN_TEST_USER_PASSWORD`. This is deliberately not a secret: the
users exist only for live testing against the dev IdP. Never reuse this setup for real
environments.

The realm script runs before the browser-client reconcile during `make deploy`.

### Browser Portal Client Reconciliation

A second Git-tracked script reconciles the shared Keycloak browser client:

- `shared/platform-ops/gitops/dev-k8s/reconcile-portal-oidc-client.sh`

It treats the overlay `identity-broker/runtime-config.env` values as the desired
browser client contract for `luban-aiops-portal`. It reconciles:

- client existence and PKCE/public-client settings
- direct-access grants (resource-owner password) enabled **for dev testing only**, so
  the `luban-*` test users can obtain tokens via `curl` without driving the browser
  flow; disable this for any real environment
- `redirectUris` (primary + `OIDC_EXTRA_REDIRECT_URIS`)
- `webOrigins` (derived from every callback origin)
- `post.logout.redirect.uris` (primary + `OIDC_EXTRA_POST_LOGOUT_REDIRECT_URIS`)
- client protocol mappers for `preferred_username` and `email`

The `agent-service` deployment runs the v2 FastAPI adapter entrypoint (`uv run agent-service`). The `platform-gateway` connects to `http://agent-service:8000` and consumes the `/api/v2/` contract exclusively (see SPEC-002 and ADR-0003); `agent-service` in turn calls `tool-gateway` (`TOOL_GATEWAY_URL`) for tool execution.

The active runtime provider is selected via the root `kustomization.yaml`, which includes the single generic LLM profile:

- `shared/platform-ops/gitops/runtime-profiles/default`

The profile contributes a committed non-secret `ConfigMap` named `agent-platform-runtime-profile`, which injects:

- `AGENTSCOPE_PROFILE`
- `AGENTSCOPE_PROVIDER`
- `AGENTSCOPE_MODEL_NAME`
- `AGENTSCOPE_BASE_URL`

That keeps provider switching Git-diffable and aligned with a future GitOps reconciliation flow.

The `web-ui` image serves the rebuilt SPA portal (Vite + React on antd / Ant Design X, SPEC-023) through `nginx` and proxies `/api/` requests to the in-cluster `platform-gateway` service. That keeps the browser entrypoint simple for development verification and avoids a separate CORS layer in this first slice. The image build is multi-stage: a Node stage compiles the bundle from `products/operator-portal/web-ui/app/` (injecting the root `VERSION` as `PLATFORM_VERSION`), and the runtime stage serves it with immutable-cache hashed `/assets/*` plus a `no-store` `index.html` SPA fallback — deploys roll over on reload with no cache busting.

### Portal Ingress (HTTPRoute)

The overlay ships a Gateway API `HTTPRoute` (`base/operator-portal/web-ui-httproute.yaml`)
that exposes the portal through the shared Envoy Gateway (`luban-gateway` in namespace
`gateway`), so live testing does not require a per-session `kubectl port-forward`.

The canonical portal entrypoint is:

- `https://aiops.luban.metasync.cc`

The OrbStack wildcard hostname serves the same portal as a reachability fallback:

- `https://aiops.luban.k8s.orb.local`

Both resolve to the same `web-ui:8080` backend; the gateway's wildcard HTTPS listeners
accept routes from all namespaces, so the route only declares hostnames and the backend.
Use the canonical hostname for any browser flow: the identity broker's OIDC callback is
pinned to `https://aiops.luban.metasync.cc/callback`, and the portal's PKCE pending
request lives in per-origin browser storage, so a sign-in started on the orb.local
hostname cannot round-trip back to it. Because `web-ui` proxies `/api/` to
`platform-gateway`, no other service needs its own route. Port-forwarding
`service/web-ui` reaches the same shell and the same proxied `/api/` path, but it
is **not** a fallback for a browser flow: the callback is still pinned to the
canonical hostname, so if neither wildcard DNS resolves from your browser the
authorization code has nowhere to land either, and no origin can complete sign-in
until DNS or ingress reachability is fixed. Use a port-forward to inspect assets
and the proxied gateway path, not to sign in.

The `redis` deployment uses `emptyDir` storage in this development baseline. That keeps setup simple for Kubernetes development testing, but it is not a durable production persistence model.

All app deployments set `enableServiceLinks: false`. Kubernetes otherwise injects legacy service-link env vars (for example `AGENT_SERVICE_PORT=tcp://…`) that collide with the services' own `*_PORT` settings; service discovery in this platform uses DNS names exclusively.

## Runtime Secrets

The `agent-service` deployment in this overlay supports an optional Kubernetes secret named `agent-platform-runtime-secrets`.

At minimum, provide:

- `AGENTSCOPE_API_KEY`

If Luban CI injects secrets for this deployment, that pipeline can provide the same secret contract directly and you can skip the local fallback workflow below.

Use the example file of the `default` runtime profile:

- `shared/platform-ops/gitops/runtime-profiles/default/runtime-secrets.example.env`

For manual local testing only, create the local secret file, for example:

```bash
cp shared/platform-ops/gitops/runtime-profiles/default/runtime-secrets.example.env \
  shared/platform-ops/gitops/runtime-profiles/default/runtime-secrets.env
```

Edit the copied `runtime-secrets.env` file and replace the placeholder value with your real key, then sync the profile secret into the cluster:

```bash
shared/platform-ops/gitops/sync-runtime-secret.sh default
```

Restart `agent-service` so it picks up the new secret:

```bash
kubectl -n dev-luban-aiops rollout restart deployment/agent-service
kubectl -n dev-luban-aiops rollout status deployment/agent-service --timeout=120s
```

You can verify that the runtime left placeholder mode by port-forwarding `agent-service` directly:

```bash
kubectl -n dev-luban-aiops port-forward service/agent-service 18000:8000
curl http://127.0.0.1:18000/api/v2/runtime
```

When configured correctly, `runtime_mode` should be `agentscope` and `runtime_state` should be `ready`, and the response shows the active provider and model. `/api/v2/health` reports `configured: true`.

## Profile Selection

To switch the active provider profile for the `dev-k8s` overlay:

```bash
shared/platform-ops/gitops/select-runtime-profile.sh default
```

This updates the root `kustomization.yaml` files so the selected profile becomes the declared desired state in Git.

Verify the active profile overlays still render cleanly:

```bash
shared/platform-ops/gitops/verify-runtime-profile.sh
```

The runtime settings layer also validates that `AGENTSCOPE_PROFILE` matches `AGENTSCOPE_PROVIDER`, so a mismatched overlay fails fast at service startup.

For confidential `OIDC` clients, the `identity-service` deployment also supports an optional Kubernetes secret named `identity-service-runtime-secrets`.

At minimum, provide:

- `OIDC_CLIENT_SECRET`

For broker-mediated token delegation (SPEC-008), two optional secrets carry the service-identity credential. The non-secret halves (`PLATFORM_GATEWAY_TOKEN_AUDIENCE`, `PLATFORM_GATEWAY_SERVICE_CLIENT_ID`, `IDENTITY_TOKEN_AUDIENCE`, `IDENTITY_DELEGATED_TOKEN_TTL_SECONDS`) are committed in the `runtime-config.env` fragments above; only the secrets live here:

- `platform-gateway-runtime-secrets` (optional, referenced by the `platform-gateway` deployment), providing `PLATFORM_GATEWAY_SERVICE_CLIENT_SECRET` — see `base/platform-gateway/runtime-secrets.example.env`
- `identity-service-runtime-secrets` (optional, referenced by the `identity-service` deployment), additionally providing `IDENTITY_SERVICE_CLIENTS` (the service-client registry, format `client_id:secret:aud1|aud2`) — see `base/identity-broker/runtime-secrets.example.env`

The platform-gateway's `PLATFORM_GATEWAY_SERVICE_CLIENT_SECRET` must match the secret registered for client `platform-gateway` in the broker's `IDENTITY_SERVICE_CLIENTS` (SPEC-010 renamed the client; delegated tokens keep `aud = tool-gateway`). The credential confers no user authority; it only authorizes the token-exchange operation. In this dev overlay the static secret remains the configured path; projected workload-identity tokens (SPEC-009) are the production upgrade — see below.

## Tool Output Redaction (SPEC-009)

Tool-output redaction is on by default in `tool-gateway` and needs no overlay change: every tool result passes through a single choke point that replaces credential-shaped spans (JWTs, `Bearer`/`Basic` values, PEM private keys, sensitive key-list fields) with `[REDACTED]` before the response and the audit log. When the redacted fraction of a result exceeds the threshold, the output is withheld with a `REDACTION_OVERFLOW` error (fail-closed).

The only knob is a dev-debugging opt-out, added to the `tool-gateway` fragment of `runtime-config.env` when needed:

```env
GATEWAY_REDACTION_ENABLED=false
```

Do not carry this into non-dev overlays; the redaction metrics (`gateway_tool_redacted_spans_total`) are the diagnostic surface instead.

## Workload-Identity Service Tokens (SPEC-009)

The exchange endpoint accepts Kubernetes projected service-account tokens as the service credential (`Authorization: Bearer`) instead of the static client secret. This dev overlay keeps the static secret as the fallback (dev clusters have no registered workload registry); a non-dev deployment wires the projected path with:

- platform-gateway: `PLATFORM_GATEWAY_WORKLOAD_TOKEN_PATH=/var/run/secrets/tokens/identity-broker` plus a projected volume, e.g.

  ```yaml
  volumes:
    - name: workload-token
      projected:
        sources:
          - serviceAccountToken:
              audience: identity-broker
              expirationSeconds: 3600
              path: identity-broker
  volumeMounts:
    - name: workload-token
      mountPath: /var/run/secrets/tokens
      readOnly: true
  ```

- broker: `IDENTITY_WORKLOAD_ISSUER_URL` (the cluster OIDC issuer), `IDENTITY_WORKLOAD_AUDIENCE` (default `identity-broker`), and `IDENTITY_WORKLOAD_CLIENTS` mapping the service-account subject to a registered client (`system:serviceaccount:<ns>:<sa>=<client_id>:<aud1>|<aud2>`)

When `PLATFORM_GATEWAY_WORKLOAD_TOKEN_PATH` is set but the token file is missing, the platform-gateway falls back to the static secret and warns once per process. Unsetting the path is the rollback switch; the dev path (no workload issuer configured) is unchanged.

## Build Images

```bash
make build
```

This builds all product images with a coordinated `IMAGE_TAG` (delegating to each product's Makefile) and saves the resulting image names in:

- `shared/platform-ops/gitops/dev-k8s/.images.env`

By default the generated tag carries the platform semver (root `VERSION` file) plus the overlay name for clarity:

- clean build: `<semver>-dev-k8s-<gitsha>` (e.g. `0.46.0-dev-k8s-d2596c2`)
- dirty local build: `<semver>-dev-k8s-<gitsha>-dirty-<timestamp>`

If you want extra traceability in local experiments, you can optionally add a profile suffix:

```bash
make build IMAGE_TAG_PROFILE=experiment
```

That avoids the stale same-tag rollout problem caused by reusing a single static placeholder tag across multiple development rebuilds.

If your development cluster does not automatically see Docker images from the host runtime, you can load the images into `kind` as part of the same step:

```bash
make build AUTO_LOAD_KIND=true KIND_CLUSTER_NAME=<your-kind-cluster>
```

## Token Delegation Secrets (SPEC-008)

The agent needs a working **token delegation chain** to discover and invoke
tools through tool-gateway. Without it, platform-gateway cannot exchange the
user's portal JWT for a delegated token, and tool calls fail silently (the
agent reports "access not granted" or "no tools available").

`make deploy` provisions these secrets automatically via
`sync-delegation-secrets.sh`. To skip (e.g. when secrets are injected by CI):

```bash
SKIP_DELEGATION_SECRETS=true make deploy
```

To provision manually or regenerate the shared secret:

```bash
shared/platform-ops/gitops/sync-delegation-secrets.sh
```

The script generates a random shared client secret (or uses
`DELEGATION_CLIENT_SECRET` if exported), creates both K8s secrets, and
restarts the affected deployments:

- `platform-gateway-runtime-secrets` — `PLATFORM_GATEWAY_SERVICE_CLIENT_SECRET`
- `identity-service-runtime-secrets` — `IDENTITY_SERVICE_CLIENTS` (format: `platform-gateway:<secret>:tool-gateway`)

Verify delegation is working:

```bash
kubectl -n dev-luban-aiops logs deployment/platform-gateway --tail=20 | grep delegation
# Look for delegation_exchange_total{result=success} in metrics:
kubectl -n dev-luban-aiops exec deployment/platform-gateway -- curl -s localhost:8000/metrics | grep delegation
```

## Durable Audit Trail (SPEC-013)

The overlay deploys `audit-service` backed by a `postgres` StatefulSet
(`postgres:16-alpine`, 1Gi PVC, dev-only credentials committed in
`base/infra/postgres-statefulset.yaml`). The audit-service fragment of
`runtime-config.env` commits the non-secret halves:

- `AUDIT_STORE_BACKEND=postgres`, `AUDIT_DB_URL` (points at the in-cluster
  `postgres` service), `AUDIT_RETENTION_DAYS=30`, `AUDIT_MAX_EVENTS=100000`,
  `AUDIT_EVICTION_INTERVAL_SECONDS=3600`

The seven emitters point at the service with matching client ids:

- tool-gateway: `GATEWAY_AUDIT_SERVICE_URL=http://audit-service:8000`, `GATEWAY_AUDIT_CLIENT_ID=tool-gateway`
- platform-gateway: `PLATFORM_GATEWAY_AUDIT_SERVICE_URL=http://audit-service:8000`, `PLATFORM_GATEWAY_AUDIT_CLIENT_ID=platform-gateway`
- identity-service: `IDENTITY_AUDIT_SERVICE_URL=http://audit-service:8000`, `IDENTITY_AUDIT_CLIENT_ID=identity-broker`
- agent-service: `AGENT_AUDIT_SERVICE_URL=http://audit-service:8000`, `AGENT_AUDIT_CLIENT_ID=agent-service`
- skills-hub: `SKILLS_AUDIT_SERVICE_URL=http://audit-service:8000`, `SKILLS_AUDIT_CLIENT_ID=skills-hub`
- incident-service: `INCIDENT_AUDIT_SERVICE_URL=http://audit-service:8000`, `INCIDENT_AUDIT_CLIENT_ID=incident-service`
- execution-runtime: `EXECUTION_AUDIT_SERVICE_URL=http://audit-service:8000`, `EXECUTION_AUDIT_CLIENT_ID=execution-runtime`

The shared ingest secret lives in eight optional secrets and is provisioned
by `sync-audit-secrets.sh` (one random secret shared across all parties):

- `audit-service-runtime-secrets` — `AUDIT_INGEST_CLIENTS`
  (format `client_id=secret,...`; see `base/audit-service/runtime-secrets.example.env`)
- `tool-gateway-runtime-secrets` — `GATEWAY_AUDIT_CLIENT_SECRET`
- `platform-gateway-runtime-secrets` — `PLATFORM_GATEWAY_AUDIT_CLIENT_SECRET`
- `identity-service-runtime-secrets` — `IDENTITY_AUDIT_CLIENT_SECRET`
- `incident-service-runtime-secrets` — `INCIDENT_AUDIT_CLIENT_SECRET`
- `skills-hub-runtime-secrets` — `SKILLS_AUDIT_CLIENT_SECRET`
- `agent-platform-runtime-secrets` — `AGENT_AUDIT_CLIENT_SECRET`
- `execution-runtime-runtime-secrets` — `EXECUTION_AUDIT_CLIENT_SECRET`

`make deploy` runs the script automatically; to skip (e.g. when secrets are
injected by CI):

```bash
SKIP_AUDIT_SECRETS=true make deploy
```

To provision manually or regenerate the shared secret:

```bash
shared/platform-ops/gitops/sync-audit-secrets.sh
```

Unset the emitter's `*_AUDIT_SERVICE_URL` to fall back to log-only auditing.
Verify ingest and query are working:

```bash
# ingest health: audit_emits_total{result="ok"} on each emitter
kubectl -n dev-luban-aiops exec deployment/tool-gateway -- curl -s localhost:8000/metrics | grep audit_emits
# store readiness and size
kubectl -n dev-luban-aiops port-forward service/audit-service 18003:8000
curl http://127.0.0.1:18003/health/ready
```

## Skills and Grounded Guidance (SPEC-014)

The overlay deploys `skills-hub`, which federates two sample skill sources
(shipped as ConfigMap volumes under `/skills`) and serves them to the agent
through the tool-gateway's read-only `skills.search` / `skills.get` /
`skills.list` tools. Day-2 content operations (adding, revising, and removing
skills and sources) are covered by the Skills and Guidance Guide
(`docs/guides/skills-guide.md`).

Sample sources (committed under `shared/platform-ops/skills/`):

- `sre-alerting` — six adapted Prometheus Operator alert runbooks (Apache-2.0)
- `platform-runbooks` — five adapted Kubernetes troubleshooting guides (CC-BY-4.0)

Both trees reach the pod through the single `platform-skills` **git** source,
which ingests `shared/platform-ops/skills/` from the tracked `ref`. They were
additionally mounted as `local` ConfigMap sources until 2026-10-01; because
`skill_id` is source-prefixed that stored every document twice, and since
ranking does no content de-duplication the copies consumed result slots.

The skills-hub fragment of `runtime-config.env` commits the non-secret halves:

- `SKILLS_STORE_BACKEND=postgres`, `SKILLS_DB_URL` (points at the in-cluster
  `postgres` service, database `skills`), `SKILLS_SYNC_INTERVAL_SECONDS=300`,
  `SKILLS_DATA_PATH=/var/lib/skills-hub`, and the `SKILLS_SOURCES` federation
  list — the `platform-skills` git source plus `samples`, now the only `local`
  source, whose ConfigMap `make deploy-samples` creates out-of-band

The tool-gateway fragment commits the caller halves:

- `GATEWAY_SKILLS_SERVICE_URL=http://skills-hub:8000`, `GATEWAY_SKILLS_CLIENT_ID=tool-gateway`

The platform-gateway fragment commits its portal inventory proxy halves
(SPEC-019):

- `PLATFORM_GATEWAY_SKILLS_HUB_URL=http://skills-hub:8000`,
  `PLATFORM_GATEWAY_SKILLS_CLIENT_ID=platform-gateway`, and
  `PLATFORM_GATEWAY_TOOL_GATEWAY_URL=http://tool-gateway:8000` (the Tools
  proxy rides the delegation chain, so it needs no extra secret)

The shared query secret lives in three optional secrets and is provisioned by
`sync-skills-secrets.sh` (one random secret shared across all callers):

- `skills-hub-runtime-secrets` — `SKILLS_QUERY_CLIENTS`
  (format `client_id=secret,...`; see `base/skills-hub/runtime-secrets.example.env`)
- `tool-gateway-runtime-secrets` — `GATEWAY_SKILLS_CLIENT_SECRET`
- `platform-gateway-runtime-secrets` — `PLATFORM_GATEWAY_SKILLS_CLIENT_SECRET`

`make deploy` runs the script automatically (after the audit secrets); to skip
(e.g. when secrets are injected by CI):

```bash
SKIP_SKILLS_SECRETS=true make deploy
```

To provision manually or regenerate the shared secret:

```bash
shared/platform-ops/gitops/sync-skills-secrets.sh
```

The script also creates the `skills` database idempotently for existing
clusters (fresh clusters get it via the `postgres-initdb` ConfigMap mounted at
`/docker-entrypoint-initdb.d`). Verify sync and search are working:

```bash
# per-source sync status (last_error should be null for both sources)
kubectl -n dev-luban-aiops exec deployment/skills-hub -- \
  python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/v1/skills/status').read().decode())"
# deterministic smoke test (status + search ranking + optional chat leg)
shared/platform-ops/e2e/skills-demo.sh
```

## Incident Triage (SPEC-015)

The overlay deploys `incident-service`, which ingests Alertmanager webhooks
and manual operator reports, runs operator-initiated agent triage, and
dispatches validated triage reports through its connector framework (the
built-in `audit` sink emits `incident_triaged` events to audit-service).

The incident-service fragment of `runtime-config.env` commits the non-secret
halves:

- `INCIDENT_STORE_BACKEND=postgres`, `INCIDENT_DB_URL` (points at the
  in-cluster `postgres` service, database `incidents`),
  `INCIDENT_AGENT_SERVICE_URL=http://agent-service:8000`,
  `INCIDENT_CONNECTORS=audit`, and the `INCIDENT_AUDIT_*` emitter halves

The gateway fragments commit the caller halves:

- platform-gateway: `PLATFORM_GATEWAY_INCIDENT_SERVICE_URL=http://incident-service:8000`,
  `PLATFORM_GATEWAY_INCIDENT_CLIENT_ID=platform-gateway`
- tool-gateway: `GATEWAY_INCIDENTS_SERVICE_URL=http://incident-service:8000`,
  `GATEWAY_INCIDENTS_CLIENT_ID=tool-gateway`

The webhook token and shared query secret live in three optional secrets and
are provisioned by `sync-incident-secrets.sh`:

- `incident-service-runtime-secrets` — `INCIDENT_WEBHOOK_TOKEN` and
  `INCIDENT_QUERY_CLIENTS` (format `client_id=secret,...`; see
  `base/incident-service/runtime-secrets.example.env`)
- `platform-gateway-runtime-secrets` — `PLATFORM_GATEWAY_INCIDENT_CLIENT_SECRET`
- `tool-gateway-runtime-secrets` — `GATEWAY_INCIDENTS_CLIENT_SECRET`

`make deploy` runs the script automatically (after the skills secrets); to
skip (e.g. when secrets are injected by CI):

```bash
SKIP_INCIDENT_SECRETS=true make deploy
```

To provision manually or regenerate the secrets:

```bash
shared/platform-ops/gitops/sync-incident-secrets.sh
```

The script also creates the `incidents` database idempotently for existing
clusters (fresh clusters get it via the `postgres-initdb` ConfigMap mounted
at `/docker-entrypoint-initdb.d`). `sync-audit-secrets.sh` registers
incident-service as an audit emitter (`INCIDENT_AUDIT_CLIENT_SECRET` plus the
`AUDIT_INGEST_CLIENTS` entry). Point Alertmanager at the webhook with the
provisioned bearer token:

```
POST http://incident-service:8000/api/v1/webhooks/alertmanager
Authorization: Bearer <INCIDENT_WEBHOOK_TOKEN>
```

Verify intake, dedupe, triage, and the audit dispatch with the deterministic
smoke test:

```bash
shared/platform-ops/e2e/incident-demo.sh
# cluster-side assertions only (no port-forwards needed):
SKIP_TRIAGE_LEG=true shared/platform-ops/e2e/incident-demo.sh
```

First deploy to an existing cluster: `make deploy` applies the overlay and
waits for every rollout before the sync scripts run, so incident-service can
CrashLoopBackOff (the `incidents` database does not exist yet) and the deploy
can exit with `exceeded its progress deadline`. That is harmless — run the
sync scripts above once (they create the database, sync the secrets, and
restart the affected deployments) and the rollout completes.

## Session Store on Postgres (SPEC-016)

The agent-platform session store persists chat sessions in the shared
`postgres` instance (database `sessions`) instead of Redis. The
agent-platform fragment of `runtime-config.env` commits:

- `SESSION_STORE_BACKEND=postgres`
- `SESSION_DB_URL=postgresql://audit:audit-dev-local@postgres:5432/sessions`

Redis stays deployed for AgentScope kernel coordination only
(`AGENTSCOPE_REDIS_*`). No secrets are involved: the DSN uses the committed
dev credentials, like the audit/skills/incidents stores.

Fresh clusters get the `sessions` database via the `postgres-initdb`
ConfigMap; existing clusters get it from `sync-sessions-db.sh` (idempotent
`CREATE DATABASE` plus an agent-service restart), which `make deploy` runs
automatically after the incident secrets step. If Postgres is unreachable at
startup, the store fails open on its in-memory fallback
(`session_store_fallbacks_total` counts this).

## Agent State on Postgres (SPEC-017)

The agent-platform agent state store persists kernel-serializable
conversation state (so conversations survive restarts) in the same
`sessions` database. The agent-platform fragment of `runtime-config.env`
commits:

- `AGENT_STATE_STORE_BACKEND=postgres`
- `AGENT_STATE_DB_URL=postgresql://audit:audit-dev-local@postgres:5432/sessions`

The `agent_states` table DDL is applied idempotently by agent-service at
startup (no initdb change needed), and an unreachable database fails open
to the in-memory backend (`agent_state_fallbacks_total`). The kernel
tuning knobs (`AGENTSCOPE_MAX_ITERS`, `AGENTSCOPE_CONTEXT_TRIGGER_RATIO`,
`AGENTSCOPE_TOOL_RESULT_LIMIT`, `AGENTSCOPE_TIMEZONE`,
`AGENTSCOPE_MODEL_MAX_RETRIES`) are intentionally unset in dev so the
agentscope defaults apply.

## Bounded Mutating Actions (SPEC-021, dev posture via SPEC-022 R-3)

The platform's first mutating capability is the bounded pod-delete primitive
(`k8s.delete_pod`: delete one named pod; the owning controller recreates
it). Every gate fails closed independently:

- the **base** commits `GATEWAY_MUTATING_TOOLS_ENABLED=false` in the
  tool-gateway fragment of `runtime-config.env`; while false, mutating
  tools are absent from discovery and invoke returns `TOOL_NOT_FOUND`
- the committed RBAC (`base/tool-gateway/rbac.yaml`) grants read-only verbs
  only
- the policy bundle grants the deny-by-default `tools:mutate` action to
  `platform-admin` and `operator` only
- agent-platform never auto-approves mutating tools and, without HITL
  bridging (`AGENT_HITL_CONFIRM_TIMEOUT=0`), excludes them from the toolkit
  entirely

**Dev-k8s opts in through a committed runtime profile (SPEC-022 R-3).**
The `runtime-profiles/mutating-dev/` profile is wired into this overlay
permanently: the overlay merges the profile's
`GATEWAY_MUTATING_TOOLS_ENABLED=true` into the `platform-runtime-config`
ConfigMap and applies the pod-delete Role/RoleBinding that rides the
profile (`mutating-dev/tool-gateway-pod-delete.yaml` — delete on pods,
`dev-luban-aiops` only). This opts in the gateway posture, not SPEC-063
execution admission: the ledger and both consumers still require the coordinated
cutover above. Any overlay without the profile retains the deny-by-default base.

```bash
# Deploy the opted-in dev posture (profile already wired into dev-k8s)
make deploy

# Verify the grant
kubectl auth can-i delete pods -n dev-luban-aiops \
  --as=system:serviceaccount:dev-luban-aiops:tool-gateway

# Run the deterministic smoke test (denied-by-default + opt-in chain)
shared/platform-ops/e2e/mutating-demo.sh
```

Config-only changes (such as toggling this posture on an existing cluster
without a new image build) do not need a full `make deploy`: regenerate
just the ConfigMap and restart the affected deployment. The overlay pins
image tags via `.images.env`, so never apply a raw `kustomize build` of
the base for drills:

```bash
# Same-tag rollout: refresh the ConfigMap, restart only tool-gateway
kubectl -n dev-luban-aiops rollout restart deployment/tool-gateway
kubectl -n dev-luban-aiops rollout status deployment/tool-gateway
```

**Deactivation runbook.** To return this environment to the deny-by-default
posture: remove `- ../runtime-profiles/mutating-dev` (and the merge
`configMapGenerator` block) from `dev-k8s/kustomization.yaml`, then
`make deploy` (or the targeted ConfigMap regeneration above) and delete the
RBAC: `kubectl delete -f
shared/platform-ops/gitops/runtime-profiles/mutating-dev/tool-gateway-pod-delete.yaml`.
The tool immediately disappears from discovery and invoke fails closed.

The full approval model, including how to manage the auto-allow list and
approval requirements, is covered by `docs/guides/approval-and-hitl.md`.

## Browser Web-Check Posture (SPEC-049)

The `runtime-profiles/browser-dev/` profile is wired into this overlay
permanently, like `mutating-dev`: the overlay merges the profile's
`GATEWAY_BROWSER_ENABLED=true` and the dev origin allowlist into the
`platform-runtime-config` ConfigMap and applies the strategic merge patch
that adds the `chromium-headless-shell` sidecar (plus the credential-set
volume mount) to the tool-gateway Deployment. The profile no longer ships
a target of its own — SPEC-061 retired the static `browser-check-target`
mock — so the one origin on the dev allowlist is `acme-admin`, the sample
app deployed out-of-band by `make deploy-sample-app`. The base commits
`GATEWAY_BROWSER_ENABLED=false` and an empty allowlist, so any overlay
without the profile stays deny-by-default.

`deploy.sh` provisions the credential-set secret
(`tool-gateway-browser-credentials`, key `credential-sets.json`) via
`sync-browser-credentials.sh`; a dev `acme-admin` set is generated with a
random password, or provide `BROWSER_CREDENTIAL_SETS_FILE=<path>` / skip
with `SKIP_BROWSER_CREDENTIALS=true`. The dev default is a single `basic`
set, so the SPEC-068 credential-scheme extension stays inert until an
operator provisions a `bearer`/`oauth2_client_credentials` set through that
override (documented in `docs/guides/tool-configuration.md`).

```bash
# Deploy the opted-in dev posture (profile already wired into dev-k8s)
make deploy

# Exercise the browser flow gate end to end against the stateful sample
# app (part of `make e2e`; opt-in chat leg with RUN_CHAT_LEG=true)
samples/acme-admin/demo-suite.sh
```

## Apply

```bash
make deploy
```

One-time cleanup for namespaces deployed before SPEC-010: the combined
`api-gateway` deployment and service no longer render from this overlay, so
remove the orphaned objects once after upgrading:

```bash
kubectl -n dev-luban-aiops delete deployment/api-gateway service/api-gateway --ignore-not-found
```

This apply path uses the latest `IMAGE_TAG` from `.images.env`, applies the active root GitOps overlay, updates each deployment to the explicit image tag, waits for rollout completion, then reconciles the shared Keycloak browser client for the committed `OIDC` settings.

If you need to override the namespace or image tag manually:

```bash
NAMESPACE=dev-luban-aiops IMAGE_TAG=<explicit-tag> \
  shared/platform-ops/gitops/dev-k8s/deploy.sh
```

If you want to skip the Keycloak step temporarily:

```bash
RECONCILE_OIDC_PORTAL_CLIENT=false \
  shared/platform-ops/gitops/dev-k8s/deploy.sh
```

To reconcile only the browser client without redeploying the workloads:

```bash
shared/platform-ops/gitops/dev-k8s/reconcile-portal-oidc-client.sh
```

## Verify

```bash
kubectl -n dev-luban-aiops get pods,svc
kubectl -n dev-luban-aiops logs deployment/redis
```

To reach the portal's shell and its proxied `/api/` path without the canonical hostname:

```bash
kubectl -n dev-luban-aiops port-forward service/web-ui 18080:8080
```

Then open `http://localhost:18080`; `nginx` forwards `/api/` calls to `platform-gateway`. That makes this origin useful for inspecting built assets and the proxied gateway path, but it is **not** a sign-in entrypoint, and the committed `OIDC` redirect URIs do not make it one. As `Runtime Wiring` above records, `/api/v1/auth/login` takes no redirect override and always builds the authorization URL from `OIDC_REDIRECT_URI`, so a login started from this tab delivers its code to `https://aiops.luban.metasync.cc/callback` and the localhost tab stays signed out. The `http://localhost:18080/callback` entry in `OIDC_EXTRA_REDIRECT_URIS` is registered for reachability — post-logout selects the portal's own origin — and sign-in never selects it. Run the browser checks below on the canonical origin.

Once the pods are running, verify that `agent-service` starts successfully and that the portal, on `https://aiops.luban.metasync.cc`, can:

- start `SSO` login
- complete the callback back into the portal shell
- create a session through `platform-gateway`
- send one prompt and receive one streamed response through the proxied gateway path

You can also verify that the platform-gateway proxies the agent-service runtime metadata directly:

```bash
kubectl -n dev-luban-aiops port-forward service/platform-gateway 18080:8000
curl http://127.0.0.1:18080/api/v1/runtime
```

The platform-gateway's `/api/v1/runtime` mirrors the agent-service `/api/v2/runtime` metadata and should include:

- `runtime_mode` (`agentscope` when configured)
- `runtime_state` (`ready` when healthy)
- `provider` and `model_name`
