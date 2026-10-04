# Getting Started

A task-oriented walkthrough that takes you from "I have a Kubernetes cluster" to "the agent
can invoke tools and I can see evidence in the portal."

## Prerequisites

| Tool | Minimum Version | Purpose |
|---|---|---|
| Kubernetes cluster | 1.28+ | Target deployment environment (kind, minikube, or real cluster) |
| `kubectl` | 1.28+ | Cluster interaction |
| `make` (GNU) | 4.x | Build and deploy orchestration |
| Docker or Podman | 24+ | Container image builds |
| `kustomize` | 5.x | Overlay rendering (bundled with `kubectl` 1.28+) |
| `uv` | 0.8+ | Python dependency management (installed automatically by Makefile targets) |

For local development, [kind](https://kind.sigs.k8s.io/) is recommended. The build system
supports auto-loading images into kind via `AUTO_LOAD_KIND=true`.

## Step 1: Clone and Sync Dependencies

```bash
git clone <repository-url> && cd luban-aiops
make sync
```

This runs `uv sync --frozen` for each Python product, installing dependencies from the
committed lockfiles.

## Step 2: Select a Runtime Profile

Choose an LLM runtime profile before building:

```bash
shared/platform-ops/gitops/select-runtime-profile.sh default
```

The `default` profile is the single generic LLM profile; the active provider is a
ConfigMap knob (`AGENTSCOPE_PROVIDER`). This updates the Kustomize overlay to
include the profile's ConfigMap.

## Step 3: Provision the LLM API Key

Copy the example secrets file and fill in your real API key:

```bash
cp shared/platform-ops/gitops/runtime-profiles/default/runtime-secrets.example.env \
   shared/platform-ops/gitops/runtime-profiles/default/runtime-secrets.env
```

Edit `runtime-secrets.env` and replace the placeholder with your actual API key. Then sync
the secret into the cluster:

```bash
shared/platform-ops/gitops/sync-runtime-secret.sh default
```

## Step 4: Build Images

```bash
make build
```

This builds all product images with a coordinated image tag (e.g. `0.46.0-dev-k8s-<gitsha>`) and
writes the tag to `shared/platform-ops/gitops/dev-k8s/.images.env`.

For kind clusters, auto-load images:

```bash
make build AUTO_LOAD_KIND=true KIND_CLUSTER_NAME=<your-cluster-name>
```

## Step 5: Deploy

```bash
make deploy
```

This single command:

1. Applies the Kustomize overlay (`kubectl apply -k`)
2. Sets the correct image tags on all deployments (from `.images.env`)
3. Waits for rollout completion
4. Provisions token delegation secrets (shared credential between platform-gateway and
   identity-service)
5. Reconciles the portal's Keycloak OIDC client
6. Provisions audit, execution, skills, incident, browser-credential, and OTel push
   secrets (`sync-audit-secrets.sh`, `sync-execution-signing-secret.sh`,
   `sync-execution-handoff-secret.sh`, `sync-skills-secrets.sh`,
   `sync-incident-secrets.sh`, `sync-browser-credentials.sh`, `sync-otel-secrets.sh`),
   creating the `skills` and `incidents` Postgres databases idempotently, and ensures
   the `sessions` database for the agent-platform session store exists
   (`sync-sessions-db.sh`, no secrets involved)

> **Important:** Never deploy with raw `kubectl apply -k` — it resets image tags to the
> `dev-local` placeholder, causing `ErrImagePull`. Always use `make deploy` or run the
> deploy-overlay script which handles image tag patching.

To skip delegation secret provisioning (e.g. when secrets are managed externally):

```bash
SKIP_DELEGATION_SECRETS=true make deploy
```

## Step 6: Verify Pods

```bash
kubectl -n dev-luban-aiops get pods,svc
```

All eleven platform workloads should be `Running`. Every pod is `READY 1/1` except
`tool-gateway`, which is `2/2` in the dev-k8s environment because the `browser-dev`
runtime profile (SPEC-049 R-7) ships a chromium headless-shell sidecar next to it:

```
NAME                              READY   STATUS
web-ui-...                        1/1     Running
platform-gateway-...              1/1     Running
tool-gateway-...                  2/2     Running
agent-service-...                 1/1     Running
execution-runtime-...             1/1     Running
identity-service-...              1/1     Running
audit-service-...                 1/1     Running
skills-hub-...                    1/1     Running
incident-service-...              1/1     Running
redis-...                         1/1     Running
postgres-0                        1/1     Running
```

Eleven platform workloads in total. (The `acme-admin-...` sample pod appears only after
the separate `make deploy-sample-app` step in the Skills Demo Tour below — it is not
part of `make deploy`.)

## Step 7: Access the Portal

The dev-k8s overlay ships an `HTTPRoute` exposing the portal through the shared Envoy
Gateway. If your cluster's wildcard DNS is reachable, the canonical portal entrypoint
is:

- `https://aiops.luban.metasync.cc`

Use it for any browser flow: the identity broker's OIDC callback is pinned to this
hostname, so a sign-in always round-trips back here. The OrbStack wildcard hostname
`https://aiops.luban.k8s.orb.local` serves the same portal and stays reachable as a
fallback, but a sign-in started there cannot round-trip back to it.

A `web-ui` port-forward serves the same portal shell and proxies `/api/` to the
Gateway, which is handy for inspecting built assets or the proxied API path:

```bash
kubectl -n dev-luban-aiops port-forward service/web-ui 18080:8080
```

Open `http://localhost:18080` for that, but do not treat it as an alternative
sign-in entrypoint. `/api/v1/auth/login` takes no redirect override and always
builds the authorization URL from `OIDC_REDIRECT_URI`, so a login started from a
port-forwarded tab still delivers its code to `https://aiops.luban.metasync.cc/callback`
and that tab stays signed out. It follows that if the canonical hostname is not
reachable from your browser, no origin is: fix DNS/ingress reachability rather
than falling back to a port-forward, because the callback has to land somewhere
your browser can load.

> Login uses the self-contained `luban-aiops` Keycloak realm. `make deploy` reconciles the
> realm, role groups, and one test user per role (`luban-admin`, `luban-approver`,
> `luban-operator`, `luban-observer`, `luban-auditor`, `luban-developer`); see the dev-k8s
> README for the shared dev password.

## End-to-End Verification Checklist

Use this checklist to confirm the full platform is operational:

- [ ] **Portal login**: click Login, complete Keycloak OIDC authentication, return to the portal
- [ ] **Session creation**: create a new chat session (the session panel lists it with
  title and relative last-active; multiple sessions can coexist and be switched)
- [ ] **Agent reply**: send a prompt (e.g. "What pods are running?") and receive a streamed
  response
- [ ] **Voice input** *(optional, Chrome/Edge)*: click the microphone in the composer,
  dictate a prompt, and confirm the turn submits (audited with `input_modality: voice`)
- [ ] **Tool invocation**: the agent should invoke `k8s.list_pods` (visible in the response)
- [ ] **Evidence panel**: tool call details appear in the collapsible evidence group below
  the reply (tool name, status badge, duration, data summary)
- [ ] **Delegation working**: check metrics for successful token exchange:

```bash
kubectl -n dev-luban-aiops exec deployment/platform-gateway -- \
  curl -s localhost:8000/metrics | grep delegation
```

Look for `delegation_exchange_total{result="success"}` with a non-zero count.

## Secrets Summary

The following secrets must be provisioned before the platform is fully operational:

| Secret | K8s Secret Name | Purpose | Provisioning |
|---|---|---|---|
| LLM API key | `agent-platform-runtime-secrets` | Agent LLM calls | `sync-runtime-secret.sh <profile>` |
| Token delegation | `platform-gateway-runtime-secrets` + `identity-service-runtime-secrets` | Tool invocation auth | `sync-delegation-secrets.sh` (automatic with `make deploy`) |
| OIDC client secret | `identity-service-runtime-secrets` | Confidential OIDC client | Manual (if required by your IdP) |
| Skills query | `skills-hub-runtime-secrets` + `tool-gateway-runtime-secrets` | Grounded guidance retrieval | `sync-skills-secrets.sh` (automatic with `make deploy`) |
| Incident intake and query | `incident-service-runtime-secrets` + `platform-gateway-runtime-secrets` + `tool-gateway-runtime-secrets` | Alertmanager webhook token, incident query credentials, audit ingest credential | `sync-incident-secrets.sh` (automatic with `make deploy`) |
| Audit ingest | `audit-service-runtime-secrets` | Authenticated audit-event ingest and query | `sync-audit-secrets.sh` (automatic with `make deploy`) |
| Execution signing | `execution-signing-secret` | Signs execution requests handed from agent-service to execution-runtime | `sync-execution-signing-secret.sh` (automatic with `make deploy`) |
| Execution handoff | `execution-handoff-secret` | Bearer token authenticating the mutating-execution handoff | `sync-execution-handoff-secret.sh` (automatic with `make deploy`) |
| Browser credentials | `tool-gateway-browser-credentials` | Stored web credentials for browser tools (`web.fill_credential`) | `sync-browser-credentials.sh` (automatic with `make deploy`) |
| OTel push | the seven `*-runtime-secrets` | `OTEL_EXPORTER_OTLP_HEADERS` for OTLP ingest auth | `sync-otel-secrets.sh` (automatic with `make deploy`) |

## Skills Demo Tour (SPEC-014)

This tour exercises the grounded-guidance slice end to end and doubles as the UAT
checklist and operator training path. It assumes a deployed dev-k8s overlay with
skills secrets provisioned (automatic via `make deploy`).

To manage the skill content itself (add, revise, remove skills and sources), see
the [Skills and Guidance Guide](skills-guide.md).

Automated smoke test first (status, deterministic search ranking, and an optional
scripted chat leg):

```bash
shared/platform-ops/e2e/skills-demo.sh
# cluster-side assertions only (no port-forwards needed):
SKIP_CHAT_LEG=true shared/platform-ops/e2e/skills-demo.sh
```

Then walk the three scenarios through the portal chat (log in as `luban-operator`):

1. **Alert → runbook loop.** Ask: *"The KubePodNotReady alert is firing for our demo
   workload. What does our guidance say to check?"* The agent should invoke
   `skills.search`, cite the `sre-alerting` runbook by title, and keep its triage
   steps clearly separated from any live cluster facts it pulls with `k8s.*` tools.
2. **Cross-source citation.** Ask a pod-troubleshooting question that both sample
   sources cover (e.g. *"How do I debug a pod stuck in CrashLoopBackOff?"*). Both
   `sre-alerting` and `platform-runbooks` match; the agent may cite either or both,
   and the evidence panel should show the `skills.search` frames with their excerpts.
3. **Honest no-match.** Ask for guidance on a topic the sample sources do not cover
   (e.g. *"What is our runbook for database failover?"*). The agent should report that
   no team guidance matched instead of inventing steps.

Verification points:

- [ ] `skills.search` / `skills.get` appear in the evidence panel for scenario 1
- [ ] the cited skill title (or `skill_id`) is visible in the reply
- [ ] guidance and live cluster evidence are presented as distinct in the reply
- [ ] scenario 3 produces an explicit no-match statement, not fabricated steps

## Incident Triage Tour (SPEC-015)

This tour exercises the Release 3 incident slice end to end and doubles as the
UAT checklist and operator training path. It assumes a deployed dev-k8s overlay
with incident secrets provisioned (automatic via `make deploy`). For alert
source integration and triage interpretation beyond this tour, see the
[Incident Triage and Collaboration Guide](incident-guide.md).

Automated smoke test first (webhook auth control checks, intake → dedupe →
resolve, query visibility, operator triage through the gateway, and the audit
dispatch):

```bash
shared/platform-ops/e2e/incident-demo.sh
# cluster-side assertions only (no port-forwards needed):
SKIP_TRIAGE_LEG=true shared/platform-ops/e2e/incident-demo.sh
```

The triage leg needs two port-forwards (platform-gateway and identity-service);
the script header documents them.

Then walk the workflow through the portal (log in as `luban-operator`):

1. **Report an incident.** Open the Incidents panel, expand the Report
   incident form, and submit a manual incident (title, summary, severity,
   optional `key=value` labels). The panel opens the new incident's detail
   view with status `new`.
2. **Run triage.** Click Run triage. The button shows `Triaging…` while the
   agent runs one turn in the incident's dedicated session; on success the
   detail view renders the triage report: severity assessment, summary,
   evidence gathered from the read-only tools, hypotheses, and ranked
   advisory next steps with priorities.
3. **Continue in chat.** Click Continue in chat — the chat view opens on the
   incident's session (`incident-<id>`) so follow-up questions carry the
   triage context. Ask what else is open and confirm the agent can use
   `incidents.list` / `incidents.get`.
4. **Check the durable trail.** Open the Audit view and filter by event type
   `incident_triaged`: the triage outcome for your incident is on the trail,
   dispatched by the built-in `audit` connector.
5. **Alert intake (optional).** Point a real or scripted Alertmanager at
   `POST /api/v1/webhooks/alertmanager` with the `INCIDENT_WEBHOOK_TOKEN`
   bearer (see `incident-demo.sh` for the payload shape); confirm the alert
   group appears in the Incidents list, dedupes on re-fire, and resolves on
   the `resolved` payload.

Verification points:

- [ ] a manual incident reaches `triaged` with a rendered report and ranked
      next steps
- [ ] Run triage is unavailable to read-only observers (policy
      `incident:triage`), while the list stays visible (`incident:read`)
- [ ] `incidents.list` / `incidents.get` appear in the evidence panel when
      the chat references live incidents
- [ ] the `incident_triaged` event is visible in the Audit view
- [ ] an unauthenticated webhook post is rejected with `401`

## Next Steps

- [Configuration Reference](configuration-reference.md) — full environment variable map
- [Tool and Connector Guide](tool-configuration.md) — enable Elastic, understand K8s RBAC
- [Troubleshooting](troubleshooting.md) — resolve common deployment issues
