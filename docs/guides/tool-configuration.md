# Tool and Connector Guide

An inventory of available tools and a per-connector activation checklist for operators
configuring the platform's tool execution framework.

## Tool Inventory

Tools are registered with a risk tier (`read`, `write`, or `admin`). Read tools are invoked
under the `tools:invoke` action; mutating tools (`write`/`admin`) additionally require the
deny-by-default `tools:mutate` action and always execute behind a human confirmation
(SPEC-021). The agent discovers available tools via `tools:list` and invokes them via
`tools:invoke`. All actions are governed by the policy bundle; the full approval model is
covered in the [Approval and HITL Governance Guide](approval-and-hitl.md).

### Kubernetes Connector Tools

| Tool | Description | Parameters | Risk |
|---|---|---|---|
| `k8s.list_pods` | List pods in a namespace with optional label filtering | `namespace` (optional), `label_selector` (optional) | read |
| `k8s.get_pod` | Get detailed status of a specific pod | `name` (required), `namespace` (optional) | read |
| `k8s.get_events` | List Kubernetes events in a namespace | `namespace` (optional), `field_selector` (optional) | read |
| `k8s.get_pod_logs` | Retrieve recent logs from a pod container | `name` (required), `namespace` (optional), `container` (optional), `tail_lines` (default 100, max 1000) | read |
| `k8s.delete_pod` | Delete a single named pod — the platform's bounded "restart" primitive; the owning controller recreates the pod. One named object per invocation, no selector/wildcard variants. Requires `GATEWAY_MUTATING_TOOLS_ENABLED=true` plus opt-in pod-delete RBAC; every execution parks for human confirmation (SPEC-021) | `name` (required), `namespace` (optional) | write |

### Elastic Connector Tools

| Tool | Description | Parameters | Risk |
|---|---|---|---|
| `elastic.search_logs` | Search logs using KQL or simple text | `query` (required), `index` (default `*`), `time_range_minutes` (default 15, max 1440), `max_results` (default 50, max 200) | read |
| `elastic.get_service_health` | Get aggregated health metrics for a service | `service_name` (required), `time_range_minutes` (default 15, max 1440) | read |
| `elastic.get_active_alerts` | List active alerts, optionally filtered by severity | `severity` (optional: `critical`, `warning`, `info`), `max_results` (default 50, max 200) | read |

### Skills Connector Tools

| Tool | Description | Parameters | Risk |
|---|---|---|---|
| `skills.search` | Search team-owned skills across all federated sources, ranked deterministically; query words match OR-wise, so partial matches still rank | `query` (required), `source` (optional), `tag` (optional), `limit` (default 5, max 20) | read |
| `skills.get` | Fetch one full skill record by namespaced id | `skill_id` (required, `<source_id>/<slug>`) | read |
| `skills.list` | List registered skills (summaries, no bodies) to discover what guidance exists | `source` (optional), `tag` (optional), `limit` (default/max 20), `offset` (default 0) | read |

### Incidents Connector Tools

| Tool | Description | Parameters | Risk |
|---|---|---|---|
| `incidents.list` | List tracked incidents (summary fields, newest first) with optional status/severity/source filters | `status` (optional: `new`, `triaging`, `triaged`, `triage_failed`, `resolved`), `severity` (optional: `critical`, `warning`, `info`), `source` (optional: `alertmanager`, `manual`), `limit` (default 20), `offset` (default 0) | read |
| `incidents.get` | Fetch one full incident record including the latest triage report and connector dispatch outcomes | `incident_id` (required, `inc-...`) | read |

### Browser Connector Tools (SPEC-049)

Bounded web-application checks through a headless browser. The tools
run in the per-chat-session browser context whose page state they
share — the pool is keyed by the chat session id (forwarded as a
trusted correlation handle with an identity-subject fallback), so a
flow the owner binds on the read path survives the approver's HITL
resume on the write path. Navigation is deny-by-default: only origins
in `GATEWAY_BROWSER_ALLOW_ORIGINS` are visited (redirect landings are
re-checked too).

| Tool | Description | Parameters | Risk |
|---|---|---|---|
| `web.navigate` | Open a URL in the session's browser and wait for load; optionally bind a skill's declared flow (`web_target`/`risk_class`) | `url` (required), `skill_id` (optional) | read |
| `web.snapshot` | Enumerate the page's interactive elements with addressable refs (`[n] <tag> ...`); values are masked for password fields and filled credentials | none | read |
| `web.screenshot` | Capture a bounded JPEG screenshot (base64), with `title`/`url` beside it | none | read |
| `web.fill_credential` | Fill a ref's field from a platform-managed credential set; never echoes the value, never runs without a bound flow | `ref` (required), `credential_set` (required), `field` (required: `username`/`password`) | read |
| `web.extract` | Extract structured data from DOM elements matching a CSS selector; a `<table>` yields headers and rows, other elements yield a list of text items | `selector` (required), `max_rows` (optional, default 100, cap 500) | read |
| `web.wait_for` | Wait for an element matching a CSS selector to reach a state — useful for pages that load data asynchronously | `selector` (required), `state` (optional: `attached`/`detached`/`visible`/`hidden`, default `visible`), `timeout_ms` (optional, default 5000, cap 30000) | read |
| `web.hover` | Hover over an element identified by a snapshot ref to reveal tooltips, dropdown menus, or popover actions | `ref` (required) | read |
| `web.scroll` | Scroll the page by the given pixel offsets | `delta_x` (optional, default 0), `delta_y` (optional, default 300) | read |
| `web.switch_frame` | Switch the browser context into an iframe; later operations target the frame's document, and a `web.navigate` resets to the main frame | `selector` (required) | read |
| `web.click` | Click a snapshot ref inside a bound `write`-class flow; one HITL gate per flow, step budget enforced | `ref` (required) | write |
| `web.type` | Type text into a snapshot ref inside a bound `write`-class flow | `ref` (required), `text` (required) | write |
| `web.select` | Select an option from a `<select>` element by ref; write tier because the model-chosen value is the payload of the change | `ref` (required), `value` (required) | write |
| `web.press_key` | Press a keyboard key (e.g. `Enter`, `Escape`, `Tab`); an optional ref is focused first, otherwise the key goes to the active page/frame | `key` (required), `ref` (optional) | write |
| `web.upload_file` | Upload a file to an `<input type=file>` element by ref; the filename resolves against the configured upload directory (path traversal denied) | `ref` (required), `filename` (required) | write |
| `web.evaluate` | Execute JavaScript in the page context; write tier because arbitrary JS can mutate the DOM and read back masked secrets, so it inherits the HITL gate | `expression` (required) | write |

> **Browser checks are layered with the HITL model (SPEC-049/SPEC-050).** The
> nine read-class tools (`web.navigate`, `web.snapshot`, `web.screenshot`,
> `web.fill_credential`, `web.extract`, `web.wait_for`, `web.hover`,
> `web.scroll`, `web.switch_frame`) are auto-allowed. The six write-class tools
> (`web.click`, `web.type`, `web.select`, `web.press_key`, `web.upload_file`,
> `web.evaluate`) always park for confirmation. A write call runs either under a
> bound, approved `write`-class flow — where the deviation guard refuses it if
> the live origin drifts off the flow's target, the flow is denied or read-only,
> or its `GATEWAY_BROWSER_FLOW_MAX_STEPS` budget is spent — or ad-hoc with no
> flow bound, where it parks its own per-action card and the live origin is
> still re-checked against the allowlist (SPEC-054 R-2). It never runs silently.

> **Mutating tools are triple-gated (SPEC-021).** A `write`/`admin` tool registers only when
> `GATEWAY_MUTATING_TOOLS_ENABLED=true`, invokes only for roles granted the deny-by-default
> `tools:mutate` policy action, and never executes without an operator confirmation through
> the HITL bridge. See the [Approval and HITL Governance Guide](approval-and-hitl.md) for
> the full model and the activation checklist below for `k8s.delete_pod`.

### HTTP Connector Tools (SPEC-058)

Bounded HTTP service checks against a server-side origin allowlist. Unlike
the config-base-URL connectors below (the `cmdb.lookup` shape documented in
[Adding a Tool](adding-a-tool.md)), the **model supplies the full URL**, so
these tools inherit `web.navigate`'s discipline rather than `cmdb.lookup`'s:
deny-by-default origins, GET redirects that halt the moment they leave the
allowlist (at most three hops), and refusal of any loopback / link-local /
multicast literal even if it is listed. POST redirects are never followed:
the approved mutation is confined to the URL shown on the card. Both report
through the standard `ToolResult` envelope, and
there is deliberately **no `headers` parameter** — a credential resolves by
reference from a named set, never as a model-supplied literal.

| Tool | Description | Parameters | Risk |
|---|---|---|---|
| `http.get` | Fetch a URL and report its status, projected headers and body — the read-only "is this service healthy / what does its API say" check. The origin must be allowlisted; an upstream 4xx/5xx is reported as the status, not as a tool failure | `url` (required), `timeout_ms` (default 10000, max 30000), `max_bytes` (default/cap `GATEWAY_HTTP_MAX_RESPONSE_BYTES`), `credential_set` (optional) | read |
| `http.post` | POST a small JSON body to an allowlisted origin — a non-browser HTTP mutating primitive; parks exactly one `action` confirmation card. One URL per call; the body is bounded to depth 2, 32 keys and `GATEWAY_HTTP_MAX_REQUEST_BYTES`. A non-2xx response reports `mutation_confirmed: false`. Requires `GATEWAY_MUTATING_TOOLS_ENABLED=true` | `url` (required), `body` (optional JSON object), `timeout_ms` (default 10000, max 30000), `credential_set` (optional) | write |

> **The allowlist is the bound (SPEC-058 R-2).** `http.get`/`http.post` are
> gated on `GATEWAY_HTTP_ENABLED`; even when enabled, a request is refused
> unless its origin is in `GATEWAY_HTTP_ALLOW_ORIGINS`, and a redirect that
> leaves the allowlist halts with `HTTP_REDIRECT_NOT_ALLOWED`. `http.post` is
> write-tier, so it registers only when `GATEWAY_MUTATING_TOOLS_ENABLED=true`
> and rides the same triple gate as `k8s.delete_pod`.

A projected `location` header is query-masked just like `url`. A POST redirect
refusal stops further requests but cannot undo the initial POST: inspect the
target state before retrying, since the first request may already have mutated it.

### Secrets Connector Tools (SPEC-062)

| Tool | Parameters | Risk / permission |
|---|---|---|
| `secrets.generate_password` | `policy` (default `default`), optional `length`, `exclude_ambiguous`, `handoff` (`portal_copy` default or `none`) | read; `tools:invoke`; no approval |
| `secrets.deliver` | `channel="email"`, `password`, `recipient` | write; `tools:invoke` + `tools:mutate` + `secrets:deliver`; action approval |

Generation reads [the password-policy contract](../../shared/shared-contracts/policies/password-policy.yaml)
and uses a CSPRNG. `generated_password` is raw only in working context; evidence,
prose, snapshots and approval projections mask it. Portal-copy is folded into
generation and is **not** a `secrets.deliver` channel. The metadata-only delivery
frame produces an explicit one-time **Copy password** control. Replay never
redeems automatically. Expired/spent values are not recoverable from history.

Activation checklist:

- Enable `GATEWAY_SECRETS_ENABLED`; ensure the configured policy is readable.
- Verify delegation and `tools:invoke`; portal copy needs HTTPS or localhost and
  browser clipboard permission. No SMTP or mutating switch is needed.
- For email, enable mutating tools, HITL and the signed execution worker; review
  `tools:mutate` and `secrets:deliver` policy grants, then `make sync-policy`.
- Configure STARTTLS SMTP host/sender and optional authentication using the
  dedicated Secret. Keep the agent/gateway recipient allowlists in sync.
  Outside-list approvals require an explicit checkbox acknowledgment; strict
  mode refuses them. Tier-2 self-approval remains blocked.
- Use one replica for memory; for scale-out select Redis and verify no startup
  fallback. See [configuration and Redis constraints](configuration-reference.md#secure-password-generation-and-delivery-spec-062).

Errors: `INVALID_PARAMETERS` covers invalid/unsatisfiable policy or inputs;
`EMAIL_NOT_CONFIGURED` means no TLS-enabled SMTP sender is available;
`EMAIL_RECIPIENT_NOT_ALLOWED` is a strict-list refusal; `UPSTREAM_ERROR` is a
buffer/transport failure. Nothing is sent on the configuration/list refusals.
A timeout after SMTP acceptance can leave delivery uncertain; do not retry blindly.

Extension seam: `DeliveryChannel.send(value, recipient, context)` returns a
metadata-only `DeliveryOutcome`. Register a new external sender with
`SecretsConnector.register_channel`; generation and the buffer stay unchanged.
The dispatcher emits `secret_delivered` after successful external delivery;
`PortalCopyChannel` defers that event until actual redemption. New senders must
never log values and must preserve write-tier authorization.

### Mutating Tool Activation Checklist (`k8s.delete_pod`)

- [ ] **`GATEWAY_MUTATING_TOOLS_ENABLED=true`** — the base commits `false`
      (while false, mutating tools are absent from discovery and invoke);
      dev-k8s opts in through the `runtime-profiles/mutating-dev` profile,
      which merges the flag into the runtime ConfigMap (SPEC-022 R-3)
- [ ] **`GATEWAY_K8S_ENABLED=true`** — the Kubernetes connector must be active
- [ ] **Pod-delete RBAC** — the Role/RoleBinding rides the `mutating-dev`
      profile (`tool-gateway-pod-delete.yaml`); it is never part of the
      default read-only ClusterRole
- [ ] **HITL confirmation enabled** — `AGENT_HITL_CONFIRM_TIMEOUT > 0` on agent-platform;
      while bridging is disabled, agent-platform excludes mutating tools from the toolkit
      entirely
- [ ] **`tools:mutate` grants reviewed** — the default bundle grants the action to
      `platform-admin` and `operator` only; confirm the live matrix
      (`GET /api/v1/policy/matrix`) matches your intent
- [ ] **`chat:confirm` grants reviewed** — the confirmer needs `chat:confirm` (granted to
      `platform-admin`, `approver`, `operator`, `developer` by default)

### Browser Tool Activation Checklist (`web.*`, SPEC-049)

- [ ] **`GATEWAY_BROWSER_ENABLED=true`** — the base commits `false`
      (while false, `web.*` tools are absent from discovery and invoke);
      dev-k8s opts in through the `runtime-profiles/browser-dev` profile,
      which merges the flag into the runtime ConfigMap and adds the
      `chromium-headless-shell` sidecar
- [ ] **`GATEWAY_BROWSER_ALLOW_ORIGINS=<origins>`** — comma-separated;
      deny-by-default: an empty list refuses all navigation
- [ ] **CDP endpoint reachable** — `GATEWAY_BROWSER_CDP_ENDPOINT`
      (default `ws://localhost:9222`); the dev sidecar runs in the
      tool-gateway pod, so the default works in the `browser-dev`
      posture
- [ ] **Credential sets (optional)** — `GATEWAY_BROWSER_CREDENTIAL_SETS`
      points at a secret-mounted JSON file; dev provides
      `sync-browser-credentials.sh`; without it `web.fill_credential`
      fails closed at call time
- [ ] **HITL confirmation enabled for write-class flows** —
      `AGENT_HITL_CONFIRM_TIMEOUT > 0` on agent-platform; `web.click` and
      `web.type` are write-tier, so a `write`-class flow parks exactly one
      confirmation card before its first interaction, on top of the
      write-tier admission (`GATEWAY_MUTATING_TOOLS_ENABLED`) and the
      `tools:mutate` policy grant
- [ ] **Skills with `web_target`/`risk_class`** — flows bind to a
      skill's declared target; see the Skills Guide's frontmatter
      section

### HTTP Tool Activation Checklist (`http.*`, SPEC-058)

- [ ] **`GATEWAY_HTTP_ENABLED=true`** — the base commits `false`
      (while false, `http.*` tools are absent from discovery and invoke
      returns `TOOL_NOT_FOUND`); dev-k8s opts in through the
      `runtime-profiles/browser-dev` profile, which merges the flag and the
      `acme-admin` dev origin (SPEC-059 R-5)
- [ ] **`GATEWAY_HTTP_ALLOW_ORIGINS=<origins>`** — comma-separated;
      deny-by-default: an empty list refuses every URL with
      `HTTP_ORIGIN_NOT_ALLOWED`. The base names no origin (SPEC-050 R-11)
- [ ] **`GATEWAY_MUTATING_TOOLS_ENABLED=true` for `http.post`** — `http.post`
      is write-tier, so it registers only under the mutating flag with the
      `tools:mutate` policy grant reviewed; `http.get` (read-tier) needs no
      bundle change
- [ ] **HITL confirmation enabled for `http.post`** —
      `AGENT_HITL_CONFIRM_TIMEOUT > 0` on agent-platform; while bridging is
      disabled, agent-platform excludes write-tier tools from the toolkit
      entirely, so `http.post` never reaches the model
- [ ] **Credential sets (optional)** — `GATEWAY_HTTP_CREDENTIAL_SETS` points at
      a secret-mounted JSON file and **defaults to the browser path**
      (`GATEWAY_BROWSER_CREDENTIAL_SETS`) when unset, so one mounted secret
      serves both surfaces; without it a `credential_set` reference fails
      closed at call time with `CREDENTIAL_SET_NOT_FOUND`

> **Dev target.** The repository ships one: [`samples/acme-admin`](../../samples/acme-admin/),
> a FastAPI console deployed out-of-band with `make deploy-sample-app` (the
> platform base overlay names no sample origin, per SPEC-050 R-11). It is on
> both allowlists in the `browser-dev` profile, so `http.get`, `http.post` and
> `web.*` all reach the same store — which is what lets
> [`samples/acme-admin/lock-unlock-user`](../../samples/acme-admin/lock-unlock-user/)
> change something over HTTP and
> [`samples/acme-admin/user-status`](../../samples/acme-admin/user-status/)
> read it back off a rendered page. `make deploy-sample-app` asserts the
> allowlists, the credential set and `GATEWAY_HTTP_ENABLED` in the live config
> before it exits 0, so a failed run names the checkbox you missed.

**HTTP connector error codes.** Both tools report a structured code in the
`ToolResult`: `INVALID_PARAMETERS` (missing/bad `url`, URL userinfo, malformed
body, or body depth/key overflow), `HTTP_SCHEME_NOT_ALLOWED` (non-http/https),
`HTTP_ORIGIN_NOT_ALLOWED` (origin not allowlisted, or a
loopback/link-local/multicast literal — a `denied` result),
`HTTP_REDIRECT_NOT_ALLOWED` (a GET hop left the allowlist, exceeded the
three-hop limit, or a POST returned a redirect), `HTTP_URL_SECRET_NOT_ALLOWED`
(a POST URL carried a secret-bearing query parameter), `HTTP_BODY_TOO_LARGE`
(serialized body over the byte limit),
`HTTP_TIMEOUT`, `TOOL_EXECUTION_ERROR` (connection failure), `UPSTREAM_ERROR`,
and `CREDENTIAL_SET_NOT_FOUND`. An upstream 4xx/5xx is **not** an error: it is
reported as `status: "success"` with the real code in `data.status` (and
`data.mutation_confirmed: false` for a non-2xx POST), so a skill can assert on
the fact rather than having the gateway swallow it.

## Kubernetes Connector

The Kubernetes connector provides read-only access to pod status, events, and logs using the
official `kubernetes-client/python` library. It uses in-cluster config when running inside
Kubernetes, falling back to kubeconfig for local development.

### Activation Checklist

- [ ] **`GATEWAY_K8S_ENABLED=true`** — set in `tool-gateway/runtime-config.env`
- [ ] **`GATEWAY_K8S_NAMESPACE=<namespace>`** — default namespace for tool queries (e.g. `dev-luban-aiops`)
- [ ] **Service account** — the tool-gateway pod runs with service account `tool-gateway`
- [ ] **RBAC** — a Role and RoleBinding grant the service account read-only access to pods, pod logs, and events in the target namespace

### RBAC Configuration

The dev-k8s overlay includes the necessary RBAC resources. For a new namespace or cluster,
create:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: tool-gateway-readonly
  namespace: <target-namespace>
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/log", "events"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: tool-gateway-readonly
  namespace: <target-namespace>
subjects:
  - kind: ServiceAccount
    name: tool-gateway
    namespace: dev-luban-aiops
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: tool-gateway-readonly
```

### Verification

```bash
# Port-forward tool-gateway and check tool listing:
kubectl -n dev-luban-aiops port-forward service/tool-gateway 18100:8000
curl -s http://127.0.0.1:18100/api/v1/tools | jq '.[].name'
# Should include: k8s.list_pods, k8s.get_pod, k8s.get_events, k8s.get_pod_logs
```

If the K8s client is not configured (no in-cluster config or kubeconfig available), all K8s tools
return a structured `K8S_NOT_CONFIGURED` error.

## Elastic Connector

The Elastic connector provides read-only access to log search, service health metrics, and
alert listing using the official `elasticsearch` Python client. It supports API-key
authentication (preferred) or basic auth.

### Activation Checklist

- [ ] **`GATEWAY_ELASTIC_ENABLED=true`** — enable the connector
- [ ] **`GATEWAY_ELASTIC_URL=<url>`** — Elasticsearch cluster URL (e.g. `https://elastic.example.com:9243`)
- [ ] **Authentication** — provide one of:
  - `GATEWAY_ELASTIC_API_KEY=<base64-api-key>` (API key auth, preferred), or
  - `GATEWAY_ELASTIC_USERNAME=<user>` + `GATEWAY_ELASTIC_PASSWORD=<pass>` (basic auth)
- [ ] **`GATEWAY_ELASTIC_VERIFY_TLS`** — set to `false` only for self-signed certs in dev (default `true`)
- [ ] **`GATEWAY_ELASTIC_ALERTS_INDEX`** — alert index pattern (default `.alerts-*`)
- [ ] **Network reachability** — the tool-gateway pod must be able to reach the Elastic cluster

### Verification

```bash
# After enabling, check readiness:
kubectl -n dev-luban-aiops exec deployment/tool-gateway -- curl -s localhost:8000/health/ready | jq
# Should show status: ok and the expected number of tools including elastic.*

# List tools to confirm elastic tools are registered:
kubectl -n dev-luban-aiops port-forward service/tool-gateway 18100:8000
curl -s http://127.0.0.1:18100/api/v1/tools | jq '.[].name'
# Should include: elastic.search_logs, elastic.get_service_health, elastic.get_active_alerts
```

If the Elastic connector is enabled but the URL is unreachable, tools return an
`ELASTIC_CONNECTION_ERROR`. If the connector is not enabled, tools return
`ELASTIC_NOT_CONFIGURED`.

## Skills Connector

The skills connector provides read-only access to team-owned guidance through the
standalone `skills-hub` service (SPEC-014). It searches across all federated skill
sources, lists the registered catalog, and fetches full skill records. The connector
registers only when `GATEWAY_SKILLS_SERVICE_URL` is set.

Managing the skill content itself — adding, revising, and removing skills and
sources — is covered in the [Skills and Guidance Guide](skills-guide.md).

### Activation Checklist

- [ ] **skills-hub deployed** — the `skills-hub` service is running with at least one
      source configured (`SKILLS_SOURCES`) and synced (`/api/v1/skills/status`)
- [ ] **`GATEWAY_SKILLS_SERVICE_URL=<url>`** — skills-hub base URL (dev-k8s commits
      `http://skills-hub:8000`)
- [ ] **`GATEWAY_SKILLS_CLIENT_ID`** — query client id (default `tool-gateway`)
- [ ] **`GATEWAY_SKILLS_CLIENT_SECRET`** — must match the entry in the skills-hub's
      `SKILLS_QUERY_CLIENTS` registry (`skills-hub-runtime-secrets`)
- [ ] **Network reachability** — the tool-gateway pod must be able to reach skills-hub

**Provisioning shortcut (dev-k8s):** `make deploy` runs `sync-skills-secrets.sh`,
which creates the `skills` database, generates one shared query secret, and writes
both K8s secrets. Use `SKIP_SKILLS_SECRETS=true make deploy` when CI injects them.

### Verification

```bash
# Confirm the skills tools are registered:
kubectl -n dev-luban-aiops port-forward service/tool-gateway 18100:8000
curl -s http://127.0.0.1:18100/api/v1/tools | jq '.[].name'
# Should include: skills.search, skills.get, skills.list

# Confirm skills-hub synced its sources:
kubectl -n dev-luban-aiops exec deployment/skills-hub -- \
  curl -fsS http://localhost:8000/api/v1/skills/status
```

If a skill id does not exist, `skills.get` returns a structured `SKILL_NOT_FOUND`
error. If skills-hub is unreachable, the skills tools return `TOOL_EXECUTION_ERROR`.
An empty search or list result is a success (`{"matches": [], "total": 0}` /
`{"skills": [], "total": 0}`), not an error — the agent reports that no team
guidance matched.

## Incidents Connector

The incidents connector provides read-only access to tracked incidents and
their triage reports through the standalone `incident-service` product
(SPEC-015). It lets the agent ground answers in the live incident record
("what else is open?", "what did triage conclude for this incident?"). The
connector registers only when `GATEWAY_INCIDENTS_SERVICE_URL` is set. There
is deliberately no mutating incident tool — reporting and triage flow
through platform-gateway under the `incident:create` / `incident:triage`
policy actions instead.

### Activation Checklist

- [ ] **incident-service deployed** — the `incident-service` workload is
      running and ready (`/health/ready`)
- [ ] **`GATEWAY_INCIDENTS_SERVICE_URL=<url>`** — incident-service base URL
      (dev-k8s commits `http://incident-service:8000`)
- [ ] **`GATEWAY_INCIDENTS_CLIENT_ID`** — query client id (default `tool-gateway`)
- [ ] **`GATEWAY_INCIDENTS_CLIENT_SECRET`** — must match the entry in the
      incident-service's `INCIDENT_QUERY_CLIENTS` registry
      (`incident-service-runtime-secrets`)
- [ ] **Network reachability** — the tool-gateway pod must be able to reach
      incident-service

**Provisioning shortcut (dev-k8s):** `make deploy` runs
`sync-incident-secrets.sh`, which creates the `incidents` database, generates
the webhook token and one shared query secret, and writes the K8s secrets.
Use `SKIP_INCIDENT_SECRETS=true make deploy` when CI injects them.

### Verification

```bash
# Confirm the incidents tools are registered:
kubectl -n dev-luban-aiops port-forward service/tool-gateway 18100:8000
curl -s http://127.0.0.1:18100/api/v1/tools | jq '.[].name'
# Should include: incidents.list, incidents.get
```

If an incident id does not exist, `incidents.get` returns a structured
`INCIDENT_NOT_FOUND` error. If incident-service is unreachable, the incidents
tools return `TOOL_EXECUTION_ERROR`. An empty list result is a success
(`{"incidents": [], "total": 0}`), not an error.

## Output Redaction

All tool results pass through a redaction engine before being returned to the agent and
recorded in the audit log. The engine replaces credential-shaped content with `[REDACTED]`:

| Pattern | What It Catches |
|---|---|
| JWT tokens | `eyJ...` base64-encoded tokens |
| Bearer/Basic values | `Authorization: Bearer <token>`, `Basic <credentials>` |
| PEM private keys | `-----BEGIN ... PRIVATE KEY-----` blocks |
| AWS access keys | Strings starting with `AKIA` |
| Sensitive field values | Case-insensitive key match for `password`, `secret`, `token`, `api_key`, and similar |

**Fail-closed:** if the fraction of redacted content exceeds
`GATEWAY_REDACTION_OVERFLOW_FRACTION` (default 20%), the entire tool output is withheld with
a `REDACTION_OVERFLOW` error. This prevents accidental credential leakage when a tool result
is predominantly secrets.

**Dev opt-out:** for debugging, set `GATEWAY_REDACTION_ENABLED=false` in
`tool-gateway/runtime-config.env`. Do not carry this into non-dev overlays.

## Audit Service Activation (SPEC-013)

The durable audit trail is delivered by the standalone `audit-service` product, not a
tool-gateway connector. Emitters (tool-gateway, platform-gateway, identity-service,
incident-service) forward audit events fire-and-forget; with no URL configured they keep
today's log-only behavior.

### Activation Checklist

- [ ] **Store backend** — `AUDIT_STORE_BACKEND=postgres` with `AUDIT_DB_URL` pointing at a
      reachable PostgreSQL (dev-k8s deploys the `postgres` StatefulSet and commits both)
- [ ] **Ingest registry** — `AUDIT_INGEST_CLIENTS=client_id=secret,...` in
      `audit-service-runtime-secrets` (one entry per emitter)
- [ ] **Emitter URLs** — `GATEWAY_AUDIT_SERVICE_URL`, `PLATFORM_GATEWAY_AUDIT_SERVICE_URL`,
      `IDENTITY_AUDIT_SERVICE_URL`, `INCIDENT_AUDIT_SERVICE_URL` (dev-k8s commits
      `http://audit-service:8000`)
- [ ] **Emitter client ids** — `GATEWAY_AUDIT_CLIENT_ID`, `PLATFORM_GATEWAY_AUDIT_CLIENT_ID`,
      `IDENTITY_AUDIT_CLIENT_ID`, `INCIDENT_AUDIT_CLIENT_ID` must match the registry entries
- [ ] **Emitter secrets** — `*_AUDIT_CLIENT_SECRET` in each emitter's `*-runtime-secrets`
      must match the secret registered for its client id
- [ ] **Retention** — `AUDIT_RETENTION_DAYS` (default 30) and `AUDIT_MAX_EVENTS`
      (default 100000) sized for the environment
- [ ] **Query access** — the policy bundle grants `audit:read` to `auditor` and
      `platform-admin` (rule `allow-auditors-audit-read`); the portal audit view is
      client-gated to the same roles

**Provisioning shortcut (dev-k8s):** `make deploy` runs `sync-audit-secrets.sh`, which
generates one shared ingest secret and writes all five K8s secrets. Use
`SKIP_AUDIT_SECRETS=true make deploy` when CI injects them.

### Verification

```bash
# Store readiness and approximate size:
kubectl -n dev-luban-aiops port-forward service/audit-service 18003:8000
curl -s http://127.0.0.1:18003/health/ready | jq

# Emitter delivery counters (result="ok" should dominate):
kubectl -n dev-luban-aiops exec deployment/tool-gateway -- curl -s localhost:8000/metrics | grep audit_emits
```

If an emitter cannot reach the audit service, delivery degrades to log-only auditing and
`audit_emits_total{result="error"}` counts the failures; the user-facing request is never
blocked. See the [Troubleshooting Guide](troubleshooting.md) for audit-specific symptoms.

## Adding a New Connector

New connectors follow the pattern established by the Kubernetes and Elastic connectors
(SPEC-007 / SPEC-011). The step-by-step contributor walkthrough — connector class, tool
definition, error envelope, configuration, wiring, authorization, deployment, and tests —
is a worked example in [Adding a Tool to the Tool Gateway](adding-a-tool.md).

In short: a connector class under `products/tool-gateway/src/tool_gateway/tools/`
registers tool classes extending `BaseTool`; configuration uses `GATEWAY_<CONNECTOR>_*`
variables in `core/config.py`; wiring is gated in `app.py`; the policy bundle governs who
may invoke the tools; and this document gains the operator activation checklist.

All tool results automatically pass through the redaction engine — no additional work is
needed for credential protection.
