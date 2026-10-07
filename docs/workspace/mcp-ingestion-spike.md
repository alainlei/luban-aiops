# Spike: MCP Tool Ingestion — Consuming External MCP Servers Beneath tool-gateway

Status: assessment — the 2026-09-23 reopen trigger is **met** (three named targets); recommends a capability-substrate direction plus staged, separately-approved target pilots. **No implementation, pilot, ADR, or spec is authorized by this memo.**
Date: 2026-09-30
Roadmap home: [Exploration Backlog](../agentic-aiops-platform/delivery-roadmap.md#exploration-backlog), "Independent MCP toolsets consumed by tool-gateway"
Builds on: [mcp-exposure-spike.md](mcp-exposure-spike.md) (2026-09-23). That assessment established the trust boundary (§5) and the ingestion invariants (§6); this memo **inherits them and does not restate them**. Where the two differ, this memo is the current direction for *ingestion*.
Evidence baseline: repository at v0.45.0 (R5 closed, `117bb5d`); static code/manifest inspection plus the 2026-09-23 memo. **No MCP server has been installed, tested, or deployed.**
Promoted to: [SPEC-067 ServiceNow ITSM MCP-ingestion pilot](../specs/SPEC-067-servicenow-mcp-ingestion-pilot/spec.md) — `draft` 2026-10-06, the first (ServiceNow, read-tier) of the staged pilots this memo recommends, with R6 framed as its release theme. Drafting authorizes no implementation, pilot, ADR, or adapter; five Open Questions block `approved` (OQ-3, the transport decision, resolved 2026-10-07 — official `mcp` SDK against ServiceNow's own MCP server, REST fallback), and Ansible/Windows remain separate later specs.

## 1. Question and recommendation

> Now that operations has named concrete external systems, should Luban consume
> their MCP servers as governed tools, and in what order?

Recommendation: **yes in direction, no in immediate implementation.** Build one
generic **MCP-ingestion connector** beneath `tool-gateway` (the gateway becomes
the MCP *client*), then onboard targets **one separately-approved pilot at a
time in risk order: ServiceNow → Ansible → Windows.** Each pilot admits only the
operations its use case needs, keeps Luban's local risk classification and
approval/audit path, and proves governance survives the boundary before the next
target is considered. This is a candidate **new release theme (R6)** — R0–R5 are
closed, and "operational *action* through external integrations" is a distinct
value theme, not a backlog row.

## 2. What changed — the recorded reopen trigger is met

The 2026-09-23 assessment parked MCP consumption as **no-go, retain native
connectors**, reopenable only on a recorded trigger. The operator has now named
three targets, workflows, and a sponsor:

| Target | Workflow named | Trigger category (2026-09-23 §2) |
|---|---|---|
| **Ansible** | Ops team already authors Ansible runbooks for task automation; expose them as Luban tools/skills | missing operational capability; credential-local execution (control node near infra) |
| **ServiceNow** | Automate ITSM ticket handling end to end | missing operational capability |
| **Windows** | UI automation for desktop-application / Windows-service health checks | missing operational capability; credential-local execution (Windows host) |

This satisfies the "New operational capabilities" trigger. That trigger carries
an explicit guardrail the pilots must honor: *"An operator identifies a missing
task and acceptance criteria. Admit only the required operations; a large
catalog is not itself a use case."* Ingesting an entire upstream server's tool
list is out of scope; each pilot admits a named, minimal operation set.

## 3. Direction clarification — ingestion, not exposure

Two concerns must stay separate (the 2026-09-23 memo §1 drew this line):

- **This memo — INBOUND consumption.** `tool-gateway` is an MCP *client* of
  external servers; Luban retains policy, approval, evidence, and audit. This is
  the "Independent MCP toolsets **consumed by** tool-gateway" backlog row.
- **The parked "stable API productization / external consumption" backlog row —
  OUTBOUND exposure** (formerly earmarked `SPEC-066`; that number was taken by
  [skill retrieval ranking fidelity](../specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md)
  on 2026-10-01, so this row is de-numbered and gets its number at drafting):
  another application consumes *Luban's* workflows/APIs. That
  stays **parked** — no second consumer exists, and machine-consumer attribution
  is unsolved (identity-broker wires only `authorization_code` + `refresh_token`,
  no `client_credentials`). Nothing in this memo advances that row.

## 4. Non-negotiable architecture

The trust boundary is fixed (2026-09-23 §5) and re-affirmed here:

```text
operator -> agent-platform policy / HITL
         -> signed execution + execution-runtime (mutations)
         -> tool-gateway: admission, dispatch, redaction, audit
              -> native connector -> target
              -> MCP-ingestion connector -> external MCP server -> target   <-- new
```

- **The MCP adapter sits *beneath* `tool-gateway`.** The gateway is the only
  execution surface; the kernel must **never** become an independent MCP client
  (AgentScope adoption-gate point 1; `agentscope-utilization-audit.md` §2).
- **Mutations still traverse the existing governed path** — HITL confirmation
  (one gate per mutating flow, ADR-0007), signed execution requests, and the
  isolated `execution-runtime` worker. An MCP-backed mutation rides this path;
  it never replaces it.
- **The connector reuses the existing seam.** `BaseTool` / `ToolDefinition` /
  `ToolRegistry` (SPEC-007) already model "local definition +
  `execute(parameters, identity) -> ToolResult` + evidence envelope." An
  MCP-backed tool is another `BaseTool` implementation, registered beside the
  native `k8s.*`, `elastic.*`, `skills.*`, `incidents.*`, `web.*`, `http.*`
  connectors — same risk tiers (`read`/`write`/`admin`), same `tools:invoke` /
  `tools:mutate` gating, same redaction choke point, same `tool_invoked` audit.

## 5. The generic capability — ingestion connector requirements

One connector, configured per target. It inherits every invariant from
2026-09-23 §6; the load-bearing ones for design:

- **Explicit, operator-owned admission allowlist.** Fail closed on missing
  tools, incompatible schemas, name collisions, and unknown required arguments.
  Remote discovery changes must **not** silently add capabilities or replace a
  canonical implementation.
- **Local static risk tiers.** Luban assigns `read`/`write`/`admin` per admitted
  tool. A server's `readOnlyHint`/annotations are **never** permission authority
  and never grant auto-allow (the kernel auto-allows a gateway tool only when it
  is both read-tier *and* explicitly vetted).
- **Canonical name/schema mapping + response normalization.** Deterministic
  translation to Luban tool names and result envelopes; validate types and size
  before normalization; preserve redaction/overflow behavior.
- **Credential/audience boundary.** Never forward the `aud=tool-gateway`
  delegated token upstream (ADR-0004; MCP authorization spec prohibits token
  passthrough). Each server gets its own authenticated credential. **Open gap:**
  per-target *service* credentials need a machine-consumer model identity-broker
  does not yet provide (`client_credentials` is unwired).
- **Untrusted results.** Do not auto-fetch returned resource links; do not let
  remote prompts/sampling/elicitation introduce side effects; admit only what the
  connector needs.
- **Uncertain outcomes.** A disconnect/timeout after dispatch may follow a
  completed mutation. Define how uncertainty is surfaced and reconciled; **no
  blind retry** and no automatic native fallback after a possibly-dispatched
  mutation. Where the target supports it, prefer an idempotency key / precondition.
- **Attribution.** Retain Luban's verified user/service attribution and add an
  explicit remote-execution correlation strategy; do not assume request IDs
  propagate. Document that one dedicated target identity is **not** per-user
  target RBAC.
- **Deployment topology.** Prefer in-cluster/sidecar reachability on a bound
  endpoint, mirroring the browser engine (a `chromedp/headless-shell` sidecar the
  gateway drives over loopback CDP, `127.0.0.1:9222`, so nothing off-pod can
  bypass the gateway). A remote server needs verified TLS, caller authentication,
  controlled egress (NetworkPolicy), and Origin/Host protection. Endpoint URLs,
  executable paths, and credential sources are **operator configuration, never
  model-selected arguments.**

## 6. Per-target assessment and sequencing

| Target | Risk tier | Blast radius | Topology | Order |
|---|---|---|---|---|
| **ServiceNow** | read → write | System of record (tickets); reversible, auditable | Remote HTTP MCP server (SaaS/self-hosted) + egress | **1st** |
| **Ansible** | write/admin | Live infrastructure; broad credentials; bundled multi-step | Control node near infra (sidecar or remote) | **2nd** |
| **Windows UI** | read → write | Native apps/services; state-changing UI clicks | **Windows host/VM outside the cluster** | **3rd** |

### 6.1 ServiceNow — prove the substrate on the lowest-risk target
Ticket reads are a clean read-tier fit (like existing `elastic.*`/`incidents.*`
reads); writes (create/assign/close) are mutating but land in a *record system*,
not live infra — reversible and auditable. **Design decision to settle first:**
ServiceNow overlaps the existing `incident-service` — decide whether ServiceNow
becomes the incident *system of record* (sync) or is only a tool target, so the
two incident models do not diverge.

> **Caution on "ServiceNowAgent."** An autonomous agent that handles tickets end
> to end is *platform-side control flow*, which collides with ADR-0011 /
> SPEC-057 ("no control flow; composition carries no authority") and the
> bounded-autonomy posture — the same reason AgentScope's `GoalPipeline` was kept
> out. Frame this as **ServiceNow tools + skills for the operator-driven agent,
> writes behind HITL** — not a separate autonomous agent edge.

### 6.2 Ansible — highest value, highest blast radius
Playbooks *execute* arbitrary infrastructure change with broad privileges — a
step-change beyond today's single exact-name `k8s.delete_pod`. Every meaningful
action is a gated mutating flow. Two hard problems:
- **A playbook is a bundled N-step mutation.** Luban's model is per-tool static
  risk tier + one gate per flow. Map "run playbook X" to a scoped, pre-declared
  blast radius, and resolve the uncertain-outcome/idempotency question (§5)
  before any write pilot.
- **Philosophy shift.** Luban skills are *advisory* ("the platform executes
  nothing"); Ansible integration means Luban *executes* ops procedures. That is a
  legitimate but deliberate expansion of "diagnose before act / read before
  write," and must be gated accordingly. If a read/inventory/`--check` (dry-run)
  capability exists, stage it first as read-tier.

### 6.3 Windows UI automation — strongest pattern precedent, hardest topology
It is the native-app analog of the shipped browser tools (SPEC-049→061): a UI
engine as a deployment-level concern, reached by the gateway over a bound
endpoint, mutating UI flows behind one-gate-per-flow HITL. Two blockers:
- **Topology.** It cannot be a Linux in-pod sidecar — it needs a **Windows
  host/VM outside the cluster** (the platform is Linux k8s/OrbStack). The
  loopback-binding safety model becomes a cross-network egress + mTLS +
  NetworkPolicy + Windows-credential-boundary problem.
- **Verification / anti-fabrication.** The samples deliberately moved *away* from
  static screen-scraping toward store-backed verification (the acme-admin
  rebase). Desktop UI state read via screenshots/UI-tree/OCR is far less
  deterministic, which strains evidence quality and the anti-fabrication
  guardrail. Reads (scrape a health status) are tractable; state-changing clicks
  are gated mutations that are hard to verify idempotently. This target warrants
  its **own boundary study** before a pilot — the 2026-09-23 memo already judged
  even *browser* mechanics "coupled to Luban semantics."

## 7. Go/no-go gates and next decision

This memo authorizes **no** implementation. Recommended next decisions, in order:

1. **Approve the capability-substrate direction** (one ingestion connector
   beneath `tool-gateway`; gateway is the MCP client; kernel is not).
2. **Select ServiceNow as the first pilot** and settle the incident-system-of-record
   question (§6.1).
3. **Promote a per-target pilot spec** following the 2026-09-23 §7 gate
   structure: pin an upstream release/artifact and inspect license, provenance,
   auth behavior, and output schemas; admit only the required operations behind
   an explicit allowlist; contract-test discovery/admission/redaction/errors/
   timeout/unavailability; prove the operator workflow, evidence, replay, and
   end-to-end correlation; validate rollback to "tool not admitted" without
   widening permissions. Writes only after the read gate passes, under the
   existing HITL/signed-worker path.
4. **Resolve the machine-consumer credential gap** (identity-broker
   `client_credentials` / approved-machine-consumer registration) as a
   prerequisite for any per-target service credential — this is shared with the
   parked stable-API-productization backlog row and should be scoped once.
5. **Frame R6.** If approved, record a new roadmap release theme ("External
   system integration via MCP ingestion") rather than leaving these as loose
   backlog rows.

**Adopt** a target only if its benefit and the compatibility/security gates pass
without substantial custom server behavior. **Stop and retain native** if a
server requires authority widening, contracts cannot be preserved, or cost
outweighs the measured benefit. Failure to adopt one target is not approval to
build a replacement.

## 8. Open questions for the first pilot spec

- Machine-consumer credential model: how does a per-target service credential
  reconcile with per-user attribution and the `client_credentials` gap?
- Risk-tier assignment UX: how does an operator declare and version the
  admission allowlist + local tier for discovered tools?
- Topology per target: sidecar vs remote, and the egress/NetworkPolicy posture.
- Ansible: blast-radius scoping for a bundled playbook + uncertain-outcome
  reconciliation / idempotency.
- ServiceNow: tool target vs incident system of record (overlap with
  `incident-service`).
- Windows: the boundary study — verification/evidence quality for UI-derived
  state, and the non-cluster host trust model.

## Changelog

- 2026-09-30, initial draft: the 2026-09-23 reopen trigger is met (Ansible,
  ServiceNow, Windows named with workflows and a sponsor). Records the
  ingestion-vs-exposure distinction, the fixed trust boundary, the generic
  connector requirements, and staged ServiceNow → Ansible → Windows sequencing
  with per-target risk analysis. Inherits `mcp-exposure-spike.md` §5–§6.
  **Assessment only — no implementation, pilot, ADR, or spec promotion, and no
  approval of any of these, is part of this memo.**
