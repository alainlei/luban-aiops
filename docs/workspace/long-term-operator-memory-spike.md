# Spike: Long-Term Operator Memory

Status: assessment — **do not adopt; close the backlog row**. **Accepted by the operator 2026-10-01** (§11 gate 5), so the [Exploration Backlog](../agentic-aiops-platform/delivery-roadmap.md#exploration-backlog) row is recorded as closed and reopening needs the §9 conditions. **No implementation, dependency install, middleware wiring, storage table, ADR, or spec is authorized by this memo.**
Date: 2026-10-01
Roadmap home: [Exploration Backlog](../agentic-aiops-platform/delivery-roadmap.md#exploration-backlog), "Long-term operator memory"
Prior evaluation: [agentscope-utilization-audit.md](./agentscope-utilization-audit.md) §2 row "Long-term memory middlewares (Mem0 / ReME / Agentic)" — ReME evaluated 2026-08-20, "does not fit as-is"
Evidence baseline: repository at v0.45.0 (`02e8e99`, with the 2026-10-01 skills-source cleanup uncommitted in the working tree); static read of `agentscope.middleware._longterm_memory` in the pinned **agentscope 2.0.8** venv (`products/agent-platform/.venv`), of the kernel middleware and state path in `products/agent-platform/src/agent_service/`, and read-only SQL against the live dev cluster's `audit`, `sessions`, and `incidents` databases on `postgres-0`. **Entirely read-only** — nothing was installed, embedded, wired, deployed, mutated, or committed by this pass.

## 1. Question and recommendation

> Do agentscope long-term-memory middlewares (mem0 / ReME) add real triage
> continuity across sessions, and where would that state live?

Recommendation: **no, on the evidence available — and the second half of the
question has no answer that fits this platform's retention model.** Four
verified findings drive it:

1. **The continuity need is not visible in the platform's own record.** Of 124
   attributed sessions in the audit trail, **107 carried exactly one chat turn**
   (11 carried two, 5 three, 1 four). Sessions arrive in test-campaign bursts
   (24 in one day, 21 in another, 16 in a third) rather than a triage rhythm,
   and **every table in the `sessions` and `incidents` databases currently holds
   0 rows** — the whole durable substrate is TTL-swept by design (§2.1, §2.2).
   There is no observed case of an operator returning to unfinished work that a
   memory store would have resumed.
2. **The one repetition signal in the trail is a vocabulary problem, not a
   memory problem.** `reset user password admin portal`, `admin portal password
   reset user`, `admin portal reset user password`, `admin portal user password
   reset`, `ResetUserPassword admin portal`, `reset alice acme-admin password`,
   `reset acme-admin password` — seven phrasings of one intent across five days
   (§2.2). That is the *agent* re-searching the skill catalogue in different
   words, which the
   [semantic-retrieval memo](./semantic-skill-retrieval-spike.md#44-option-d--improve-the-lexical-baseline-first-cheapest-may-be-sufficient)
   addresses deterministically with a curated alias map. Remembering that the
   operator asked yesterday does not make today's search rank better.
3. **All three agentscope surfaces fail SPEC-018's four-point adoption gate as
   shipped** (§4), and two of the three are not even installable without a new
   dependency: `mem0` and `reme` are **absent** from the pinned venv, and mem0's
   default vector store is **Qdrant** — a new server, the same rejection the
   semantic-retrieval memo recorded for `agentscope.rag`'s `QdrantStore`.
4. **The platform already ships a governed cross-session knowledge path, and it
   is in use.** 8 `skill_graduated`, 6 `skill_draft_generated`, 2
   `incident_skill_draft_generated`, 6 `document_created`, 4
   `document_published` events (§2.3). SPEC-039 operation documents and the
   SPEC-044/045 draft-and-graduate path do what a memory store claims to do —
   carry knowledge from one session to the next — but as **immutable,
   human-reviewed, role-gated, audited artifacts** assembled verbatim from the
   durable stores. An LLM-written private memory is the same function with the
   governance removed.

So the honest answer to "where would that state live?" is: **nowhere that
exists.** Every durable store on this platform is either session-bound (1-hour
idle TTL) or window-bound (30 days) and capped (§2.1). "Long-term" is a new
*retention class*, not a new table — and a retention class is a policy decision
about deletion, rectification, and cross-operator visibility that no middleware
can make.

The recommendation is therefore **Option D — close the row** (§8.4), with
**Option C** (§8.3) recorded as the direction to fund instead if operator
continuity ever becomes a stated need, and **Option B** (§8.2) recorded as the
only shape that could clear the gate if a real requirement arrives.

## 2. Verified baseline — what the platform already remembers

### 2.1 The durability substrate, and its three retention classes

The [session-handover spike](./session-handover-spike.md) (2026-08-27)
established that "all handover-relevant facts are already durable and
attributed". That is still true, and the retention boundaries are the point:

| Store | Spec | Scope | Retention | Verified at |
|---|---|---|---|---|
| `sessions` | SPEC-006/016/022 | per session, owner-scoped | idle TTL **3600 s**, opportunistic sweep on write | [`session_store.py:30,955-966`](../../products/agent-platform/src/agent_service/services/session_store.py) |
| `agent_states` (kernel snapshot: `AgentState.model_dump_json()` → JSONB) | SPEC-017 R-3 | per session | idle TTL **3600 s** | [`agent_state_store.py:1-11,29`](../../products/agent-platform/src/agent_service/services/agent_state_store.py) |
| `session_evidence` | SPEC-025 | per session, grouped by assistant turn | `AGENT_STATE_TTL_SECONDS` sweep | [`evidence_store.py:509-520`](../../products/agent-platform/src/agent_service/services/evidence_store.py) |
| `confirmation_records` | SPEC-031 R-1 | per session, `PER_SESSION_CAP` | **30-day** history window, swept on write | [`confirmation_records.py:14-17,42`](../../products/agent-platform/src/agent_service/services/confirmation_records.py) |
| `execution_records`, `execution_runs`, `execution_intents` | SPEC-037/063 | per run | bounded, session-linked | `execution_records.py`, `execution_recovery.py` |
| `operation_documents` | SPEC-039 R-1 | per owner, `PER_OWNER_CAP = 20` | **`RETENTION_DAYS = 30`**, aligned with the inbox window | [`operation_documents.py:1-40`](../../products/agent-platform/src/agent_service/services/operation_documents.py) |
| `audit_events` | SPEC-029 | platform-wide | **unbounded** — the only store with no TTL | `shared/shared-contracts/schemas/audit-event.schema.json` |

Three retention classes, and only one of them is long-term:

- **Session class (1 h idle).** Dies with the conversation. This is where a
  middleware's injected context would land.
- **Window class (30 d, capped).** The approval inbox and the document
  repository. Deliberately bounded so a governance surface cannot grow without
  limit.
- **Unbounded class.** The audit trail alone — append-only, facts-only,
  envelope-column-queryable (SPEC-046 deliberately never excavates `details`).

**A per-operator long-term memory would be the first unbounded, mutable,
LLM-written, per-user store on the platform.** It is not window-class (its whole
purpose is to outlive 30 days) and it is not audit-class (it is rewritten and
deleted by a model, not appended by a service). Nothing in the codebase has a
sweeper, a cap, or a deletion path for that shape, and the two 30-day windows
exist precisely because an unbounded operator-facing store was judged
undesirable.

### 2.2 The real usage record (live, read-only, 2026-10-01)

From the `audit` database on `postgres-0` (34,677+ events, 2026-08-31 →
2026-09-30). Event-type totals:

| Event type | Count | | Event type | Count |
|---|---|---|---|---|
| `skills_synced` | 15,809 | | `skill_searched` | 96 |
| `policy_decision` | 14,607 | | `chat_completed` | 84 |
| `tool_invoked` | 1,749 | | `session_deleted` | 50 |
| `token_exchange` | 451 | | `skill_graduated` | 8 |
| `skill_retrieved` | 341 | | `incident_triaged` | 7 |
| `execution_completed` | 306 | | `document_created` | 6 |
| `chat_started` | 191 | | `skill_draft_generated` | 6 |
| `execution_requested` | 154 | | `document_published` | 4 |
| `confirmation_decided` | 154 | | `secret_delivered` | 3 |
| `session_created` | 140 | | `document_read` | 2 |
| | | | `incident_skill_draft_generated` | 2 |
| | | | `execution_rejected` | 1 |

Per identity:

| Username | Sessions | Chats | Triaged | Active window |
|---|---|---|---|---|
| `luban-operator` | **133** | 187 | 7 | 2026-09-01 → 09-27 |
| `luban-obs-livecheck` | 4 | 3 | 0 | 2026-09-28 |
| `luban-admin` | 2 | 0 | 0 | 2026-08-31 → 09-22 |
| `luban-developer` | 1 | 1 | 0 | 2026-09-10 → 09-13 |
| `luban-approver` / `-auditor` / `-observer` | 0 | 0 | 0 | — |

**One identity does essentially all of the work**, which matters twice over: a
"per-operator" memory has one real tenant in the evidence, and any isolation
defect would be invisible in a single-tenant trail.

Turns per session, over the 124 sessions carrying a `session_id`:

| Chat turns in the session | Sessions |
|---|---|
| **1** | **107** |
| 2 | 11 |
| 3 | 5 |
| 4 | 1 |

Session creation is bursty, not diurnal — 24 on 2026-09-10, 21 on 09-13, 16 on
09-17, 14 each on 09-09 and 09-15, 13 on 09-02, across 16 active days. That is
a test-campaign signature.

And the substrate itself is empty right now:

| Database | Tables | Rows |
|---|---|---|
| `sessions` | 15 (`sessions`, `agent_states`, `session_evidence`, `confirmation_records`, `operation_documents`, `authoring_trace`, `authoring_trace_target`, `execution_records`, `execution_runs`, `execution_intents`, `execution_observations`, `execution_observation_state`, `execution_dispatch_claims`, `execution_protocol_state`, `model_discovery_cache`) | **0 in every table** |
| `incidents` | 3 (`incidents`, `triage_reports`, `connector_dispatches`) | **0 in every table** |

Read honestly, with its limits:

- **This is demo, e2e, and verification traffic**, the same caveat the
  semantic-retrieval memo records for the skill-search trail. The absence of a
  continuity need here is *weak* evidence — it does not prove operators would
  never benefit. It does mean **the backlog row's premise is unevidenced**, and
  the burden sits on whoever asserts the need.
- **The emptiness is by design, not by neglect.** The TTL sweeps ran; nothing
  was deleted by hand. A platform whose session substrate is 0-rowed after
  three hours of idleness has made a deliberate statement that conversation
  state is transient. Long-term memory contradicts that statement and should
  say so explicitly if it is ever pursued.
- **`chat_started` carries no message text** — its `details` keys are exactly
  `input_modality` and `model`. So the audit trail *cannot* show whether
  operators re-ask the same question across sessions. That is a real
  measurement gap, and §9 names closing it as a precondition for reopening this
  row: the question cannot be answered from the record the platform keeps.
- **The skill-search trail carries no identity at all.** All 96
  `skill_searched` events have `username IS NULL` and `session_id IS NULL`
  (96 of 96 do carry `request_id`) — SPEC-029 forwards correlation ids, not user
  identity. So the repetition signal below is attributable to *no one*.

Repeated `skill_searched` queries — the only cross-time repetition the record
can show:

| Query | Occurrences | Distinct days |
|---|---|---|
| `KubePodNotReady` | 9 | 4 |
| `argocd health check` | 7 | 5 |
| `reset user password admin portal` | 7 | 5 |
| `admin portal password reset user` | 5 | 3 |
| `admin portal reset user password` | 4 | 3 |
| `restart pod` | 2 | 2 |
| `KubePodNotReady alert` | 2 | 2 |
| `ResetUserPassword admin portal` | 2 | 1 |
| `admin portal user password reset` | 2 | 2 |
| `reset alice acme-admin password` | 2 | 1 |
| `reset acme-admin password` | 2 | 1 |

The last seven rows are one intent in seven phrasings. A memory store would
record "this operator works on ACME admin password resets" — which the platform
already knows structurally, because that sample skill is what is installed. What
would actually help is the search returning the same document for all seven
strings, which is a tokenizer/alias-map change
([memo §4.4](./semantic-skill-retrieval-spike.md#44-option-d--improve-the-lexical-baseline-first-cheapest-may-be-sufficient)),
needs no model, no store, and no retention policy.

### 2.3 The governed knowledge-capture path already shipped

The platform does not lack cross-session knowledge transfer. It has two
deliberate, audited mechanisms, and the trail shows both in use:

- **SPEC-039 operation documents** (6 created, 4 published, 2 read). Immutable
  typed snapshots; "the assembly copies facts verbatim from the durable stores,
  record ids are provenance anchors (not live references), and a document never
  depends on its source records' lifetimes". One-way `draft → published`,
  drafts visible only to their owner (*including from admins*), published
  documents visible to every `documents:read` holder, publishing and deletion
  owner-only, published documents deletable but never editable
  ([`operation_documents.py:1-27`](../../products/agent-platform/src/agent_service/services/operation_documents.py)).
  Capped at 20 per owner, aged out at 30 days.
- **SPEC-044/045 skill drafting and graduation** (6 `skill_draft_generated`, 2
  `incident_skill_draft_generated`, 8 `skill_graduated`). A triaged session or
  incident becomes a **draft skill** that an approver previews, downloads, or
  discards before it can enter the catalogue. The operator who ran the triage
  cannot self-promote it (SPEC-045 records a 409 on that path).

Both are the same idea a memory store implements, with three properties the
middleware path cannot match: **a human decides what persists**, **the persisted
thing is attributable and auditable**, and **it is visible to the people who
need it** (by role, not by accident of who ran the session).

The [session-handover spike](./session-handover-spike.md) already named the
risk of the alternative: an LLM-generated summary "introduces fabrication risk
on a surface whose whole purpose is trustworthy handover". A long-term memory
store is that risk, recurring on every turn, with no reviewer.

## 3. The three agentscope 2.0.8 surfaces

`agentscope.middleware` exports exactly three long-term memory middlewares
(`agentscope/middleware/_longterm_memory/`, 3,721 lines across the three). All
three subclass `MiddlewareBase`, so all three are wire-compatible with the
kernel's existing stack; none is installed or referenced anywhere in this
repository.

**Dependency status in the pinned venv (measured, not assumed):**

| Middleware | Vendor package | Present in `products/agent-platform/.venv`? |
|---|---|---|
| `AgenticMemoryMiddleware` | none — pure agentscope | **yes, constructible today** |
| `Mem0Middleware` | `mem0` | **no** — `ModuleNotFoundError: No module named 'mem0'` |
| `ReMeMiddleware` | `reme` | **no** — `ModuleNotFoundError: No module named 'reme'` |

Of 155 installed distributions, the only memory-adjacent one is
`openai-3.5.0`. So two of the three candidates are a **new third-party
dependency** before they are a design question, and the one that is not is the
one whose storage model fits this platform worst.

### 3.1 `AgenticMemoryMiddleware` — filesystem plus shell

> "Filesystem-backed long-term memory middleware. The middleware keeps a
> workspace-local Markdown memory store, injects a bounded `MEMORY.md` index
> into the system prompt, and can asynchronously surface relevant topic files
> as hint blocks during the reasoning loop."
> — [`_agentic_memory/_middleware.py:1-7`](../../products/agent-platform/.venv/lib/python3.12/site-packages/agentscope/middleware/_longterm_memory/_agentic_memory/_middleware.py)

- Constructor: `(workdir, memory_dir="Memory", parameters=None, backend=None)`,
  with `self._backend = backend or LocalBackend()` and the `backend` argument
  documented as "the backend to switch between local and remote storage".
- **That abstraction is not a storage abstraction.** `BackendBase` declares 19
  methods including `exec_shell`, `scandir`, `stat`, `stat_mtime`, `is_dir`,
  `read_stream`, `write_stream`, `delete_path`, and `expanduser`. In 2.0.8
  `BackendBase.__subclasses__()` returns **exactly one** implementation:
  `LocalBackend`. Backing this with Postgres means implementing a **shell
  executor** and a directory scanner over SQL — not a repository, an
  anti-pattern.
- **It does not ship any tools.** `list_tools()` is not overridden, so it
  inherits `MiddlewareBase.list_tools()` returning `[]`. Instead its
  `DEFAULT_MEMORY_INSTRUCTIONS` tell the model: "write to it directly with the
  `Write` tool (do not run mkdir or check for its existence)" and "use the
  `Read` tool with offset". Those are agentscope's own builtins
  (`agentscope.tool` exports `Bash`, `Edit`, `Glob`, `Grep`, `PowerShell`,
  `Read`, `Write`) — **none of which this platform registers**.
  `_ensure_toolkit` builds gateway tools plus the opt-in
  `TaskCreate/TaskGet/TaskList/TaskUpdate` and nothing else
  ([`runtime_kernel.py:409-472,521-529`](../../products/agent-platform/src/agent_service/runtime_kernel.py)).
  Adopting this middleware means giving the agent a **filesystem write tool and
  a shell**, on a platform whose gate point 1 is "tool-gateway the only
  execution surface".
- Memory is four typed Markdown files per topic (`user` / `feedback` /
  `project` / `reference`) plus a `MEMORY.md` index that is "always loaded into
  your conversation context", truncated to a token budget.
- On this deployment `workdir` would be
  `AGENTSCOPE_WORKSPACE_DIR=/var/lib/luban-aiops/workspaces/agent-platform`,
  which is an **`emptyDir: {}`** volume on a `replicas: 1` Deployment
  ([`agent-service-deployment.yaml:63-68`](../../shared/platform-ops/gitops/dev-k8s/base/agent-platform/agent-service-deployment.yaml),
  [`runtime-config.env:8-9`](../../shared/platform-ops/gitops/dev-k8s/base/agent-platform/runtime-config.env)).
  That is verbatim the SPEC-064 R-2 objection to the compression offloader:
  pod-local state "invisible to other replicas and lost on reschedule" while the
  authoritative rows survive in Postgres
  ([`runtime_kernel.py:602-610`](../../products/agent-platform/src/agent_service/runtime_kernel.py)).

### 3.2 `Mem0Middleware` — a vendor store in two deployment shapes

> "Works with either `mem0.AsyncMemory` (open-source) or
> `mem0.AsyncMemoryClient` (hosted Platform). Both clients converge on the same
> call shape: `search(query, filters={"user_id":..., "agent_id":...}, top_k=...)`
> / `add(messages, user_id=..., agent_id=...)`."
> — [`_mem0/_middleware.py:1-12`](../../products/agent-platform/.venv/lib/python3.12/site-packages/agentscope/middleware/_longterm_memory/_mem0/_middleware.py)

Constructor (keyword-only): `user_id` (**required**), `client`, `chat_model`,
`embedding_model`, `mem0_config`, `mode="both"`, `agent_id`, `top_k=5`,
`threshold`, `scope_search_by_agent=True`, `await_write=True`, plus three prompt
strings.

| Fact | Consequence here |
|---|---|
| OSS path builds `mem0.AsyncMemory` with "**mem0's default Qdrant for storage**" | A **new vector server**. The semantic-retrieval memo rejected `agentscope.rag.QdrantStore` on exactly this ground ("strictly worse than reusing the Postgres that already holds the skills") |
| Needs a `chat_model` "for memory extraction" and an `embedding_model` whose "dimensions must match mem0's vector store (**the default Qdrant expects 1536**)" | An **LLM in the write path** and an embedding dependency. The in-cluster Ollama answers `/api/embed` with **501** (embeddings not enabled) and holds only a chat model, so 1536-dim embeddings mean either an Ollama reconfiguration plus a model pull, or DashScope — spend, egress, a new secret, and **operator conversation text leaving the cluster** |
| Hosted `AsyncMemoryClient(api_key="m0-...")` | A third-party SaaS holding operator triage transcripts |
| `mode="both"` (the **default**) = auto-retrieval **and** auto write-back | The unaudited-write-back objection applies at the default setting |
| `mode="agent_control"` = tools only, "**No automatic retrieval or write-back**" | The objection is **mode-dependent, not intrinsic** — the one genuinely useful distinction between mem0 and ReME |
| `_dispatch_write` wraps `add()` in `except Exception: logger.warning(...)` on **both** the awaited and the `asyncio.create_task` background path | A failed memory write is **invisible** except in application logs: no audit event, no metric, no hook, no operator surface |
| Retrieved memories are appended to `agent.state.context` as `AssistantMsg(name="memory", content=[HintBlock(...)])`, and "the memory note **persists in `state.context` across turns**. Long sessions will accumulate one per turn" | Rides the SPEC-017 snapshot into Postgres JSONB and grows the snapshot without bound (§5) |
| `user_id` required at construction; `scope_search_by_agent=True` filters on `user_id` **and** `agent_id` | Per-user isolation **exists** — this is the one 2026-08-20 objection mem0 answers. But the kernel does not know the user at agent-construction time (§6) |

### 3.3 `ReMeMiddleware` — an embedded file vault that always writes

> "ReMe is a file-based memory toolkit built on AgentScope. This middleware
> **embeds the ReMe application in-process** (no separate service to run)…
> ReMe records memory by **listening to the conversation through the `on_reply`
> hook** — after every reply the new exchange is written back via ReMe's
> `auto_memory` job, **in *all* modes**. The agent never writes memory itself;
> there is no manual add tool. The `mode` parameter only controls **retrieval**…
> ReMe scopes writes by `session_id`, which is read from `agent.state.session_id`
> at hook time (not configured on the middleware)… **search runs over the whole
> workspace**."
> — [`_reme/_middleware.py:1-33`](../../products/agent-platform/.venv/lib/python3.12/site-packages/agentscope/middleware/_longterm_memory/_reme/_middleware.py)

Constructor: `(workspace_dir=".reme", parameters=None)`. `_config.py` builds a
ReMe app config with a `file_store`, an `embedding_store`, and
`vector_weight=0.7` — so it needs an `EmbeddingModelBase` and a `ChatModelBase`
too.

The 2026-08-20 evaluation holds at 2.0.8, and two of its three objections are
**worse** than recorded:

- *File-based vault vs Postgres durability* — unchanged, and `workspace_dir`
  defaults to `.reme` inside the working directory, i.e. the same `emptyDir`.
- *Unaudited LLM write-back* — **not configurable away.** Where mem0's
  `agent_control` disables auto write-back, ReME writes on every reply in every
  mode and exposes no add tool. There is no setting that makes ReME's write path
  governed.
- *No per-user isolation* — **not configurable away.** Writes are scoped by
  `agent.state.session_id`, and **search runs over the whole workspace**. On a
  multi-operator platform that is a cross-operator disclosure channel by
  construction.
- **New finding — the scope key is one the platform never sets.**
  `AgentState.session_id` is a required field whose default factory mints a
  random UUID per instantiation (`AgentState().session_id` →
  `'30cf92f8…'`), and nothing in `products/agent-platform/src/` ever assigns it:
  `_build_agent` passes `state=self._restore_state(session_id)` and never
  reconciles agentscope's id with the platform's `ses-…`
  ([`runtime_kernel.py:773-808`](../../products/agent-platform/src/agent_service/runtime_kernel.py)).
  ReME would therefore bucket writes under an identifier that is **random per
  agent construction** and meaningless to every platform surface — while its
  search ignores that bucket anyway.
- **New finding — retrieval is non-deterministic by design.** "Retrieval runs
  concurrently with the reply, so injection is best-effort: **a single-shot
  reply may finish first.**" Since **107 of 124 observed sessions are
  single-turn** (§2.2), the dominant session shape on this platform is exactly
  the one where ReME's injection may not land at all. A memory that silently
  fails to apply on 86% of sessions is not a continuity feature.

### 3.4 Side by side

| | `AgenticMemory` | `Mem0` | `ReME` |
|---|---|---|---|
| New dependency | none | `mem0` (+ Qdrant or a hosted account) | `reme` |
| Storage | Markdown files under `workdir` | Qdrant (default) / hosted Platform | file vault under `workspace_dir` |
| Survives pod reschedule | **no** (`emptyDir`) | yes (external server) | **no** (`emptyDir`) |
| Write trigger | the **model**, via `Write` | auto after each reply (`static_control`/`both`) or the model via `add_memory` | auto after each reply, **all modes** |
| Can write-back be turned off | only by not registering `Write` | **yes** — `mode="agent_control"` | **no** |
| Needs an LLM in the write path | yes (the agent itself) | yes (extraction) | yes (`auto_memory` jobs) |
| Needs an embedder | no | **yes** (1536-dim default) | **yes** |
| Per-user scoping | none (one workspace) | **`user_id` required**, `agent_id` optional | none — search is workspace-wide |
| Tools it adds | none (assumes `Write`/`Read` exist) | `search_memory`, `add_memory` | `memory_search` |
| Failure visibility | log | **log only** (`except Exception: logger.warning`) | log |
| Deterministic retrieval | yes (`MEMORY.md` always in prompt) | yes (pre-reply search) | **no** (races the reply) |

## 4. Scoring against SPEC-018's four-point adoption gate

The gate the platform already applies to every agentscope surface
([compression/GoalPipeline spike §1](./agentscope-compression-goal-pipeline-spike.md),
[utilization audit §2](./agentscope-utilization-audit.md)):

> (1) deny-by-default policy + audit preserved, tool-gateway the only execution
> surface; (2) identity carried only by the gateway-forwarded delegated token;
> (3) read-only operational posture; (4) no agentscope types leak through the
> platform-owned v2 contract.

| Gate | `AgenticMemory` | `Mem0` | `ReME` |
|---|---|---|---|
| **1** deny-by-default + audit; gateway is the only execution surface | **FAIL** — requires registering agentscope's `Write`/`Read` (and realistically `Bash`) builtins, which are neither gateway tools nor on any allow-list | **FAIL** — `search_memory`/`add_memory` are non-gateway tools executing against an external store | **FAIL** — `memory_search` likewise, plus an in-process app performing file and embedding work |
| **2** identity only via the delegated token | **FAIL** — no identity model at all (one shared workspace) | **FAIL as wired** — `user_id` is a constructor argument, and `_build_agent` receives no user identity (§6); threading one in is a *new* identity edge | **FAIL** — scopes on an `agent.state.session_id` the platform never sets |
| **3** read-only operational posture | **FAIL** — writes files to the pod workspace; the SPEC-064 R-2 offloader was refused for precisely this | **FAIL** — writes to an external store after every reply; `await_write=False` makes it fire-and-forget | **FAIL** — writes after every reply in every mode, with no off switch |
| **4** no agentscope types leak through the v2 contract | **PASS** — nothing new crosses the contract | **PASS, with a caveat** — the injected `HintBlock` stays inside `AgentState`; the v2 stream and transcript do not carry it (§5) | **PASS**, same caveat |

Gate 1 has a concrete, non-obvious consequence worth stating plainly.
`GatewayPermissionMiddleware` is deny-by-default: a tool that is neither in
`DEFAULT_AUTO_ALLOWED_TOOLS` nor in `KERNEL_LOCAL_TOOL_NAMES` is answered with
an explicit **ASK**, which parks the batch on `RequireUserConfirmEvent` and
bridges to a portal confirmation card
([`kernel_middleware.py:119-149,271-297,331-344`](../../products/agent-platform/src/agent_service/services/kernel_middleware.py)).
So wiring a memory middleware **as-is** would park an approval card on **every
memory read and every memory write** — in mem0's default `both` mode, at least
two cards per turn. The only way to avoid that is to add the memory tools to
`KERNEL_LOCAL_TOOL_NAMES`, whose membership rule is *state-local tools that the
SPEC-017 snapshot persists for free* (today: the four task tools,
`STRUCTURED_OUTPUT_TOOL_NAME`, `COMPRESS_CONTEXT_TOOL_NAME`). A memory tool is
the opposite of state-local. Adding it there would create an always-allowed,
non-gateway, unaudited execution surface — a gate-1 failure by decision rather
than by accident.

**All three fail three of the four gate points.** No configuration of any of
them passes. That is a materially stronger result than the 2026-08-20 note,
which recorded ReME alone as "does not fit as-is".

## 5. The defect no configuration fixes: memory that no operator can see

Trace one retrieved memory through the platform's projections. mem0's
`static_control`/`both` path appends `AssistantMsg(name="memory",
content=[HintBlock(hint=…)])` to `agent.state.context`:

| Projection | Does the memory note appear? | Why |
|---|---|---|
| Sent to the model | **yes** | it is in `state.context` |
| SPEC-017 durable snapshot | **yes** | `_snapshot_state` serializes the whole state through `redact_structure` and saves it as JSONB ([`runtime_kernel.py:653-670`](../../products/agent-platform/src/agent_service/runtime_kernel.py)) |
| SPEC-022 reconstructed transcript | **no** | `_TRANSCRIPT_ROLES` admits `assistant`, but `_extract_text` keeps only blocks with `type == "text"`, and `HintBlock.type == "hint"` ([`session_transcript.py:34,75-92`](../../products/agent-platform/src/agent_service/services/session_transcript.py)) |
| SPEC-025 evidence panel | **no** | `ToolEvidenceMiddleware.on_acting` returns early when the tool has no `gateway_tool_name` ([`kernel_middleware.py:458-463`](../../products/agent-platform/src/agent_service/services/kernel_middleware.py)) |
| Audit trail | **no** | the 22-value `event_type` enum is closed and has no memory event; adding one is a contract change plus a portal vocabulary and drift-guard change |
| Application log | only as `logger.info` lines | and mem0's *write* failures are `logger.warning` and otherwise swallowed |

So the injected content is **model-visible and durably persisted, but absent
from every operator-facing and governance-facing projection.** An operator
reading the transcript of a session cannot tell that the reply was conditioned
on retrieved memories; an auditor cannot enumerate what was retrieved; and the
snapshot grows by one accumulated note per turn, without bound, for a session
whose whole retention class is one hour.

This is the sharpest conflict with the platform's stated posture, and it is
structural rather than a wiring detail. The kernel's own anti-fabrication
design works the other way round: when the toolkit is empty it injects a
`NO_TOOLS_NOTICE` **and** surfaces the posture to the operator, because "a
standing system prompt is only a probabilistic hint"
([`runtime_kernel.py:98-123`](../../products/agent-platform/src/agent_service/runtime_kernel.py)).
Grounded guidance (ADR-0011 / SPEC-057) is deliberately *visible* guidance —
skills are retrieved through an audited, evidence-bearing gateway tool
(`skills.search` → `skill_searched`, then `skills.get` → `skill_retrieved`, 96
and 341 events respectively). A memory middleware replaces that with a channel
that produces no evidence, no audit event, and no transcript line.

Fixing it is not a flag. It requires **all** of: a new audit event type
(contract + portal vocabulary + drift guard + audit-service enum), an evidence
frame for a non-gateway tool (which breaks the `gateway_tool_name` invariant
every consumer relies on), transcript rendering for `hint` blocks (which changes
what operators see in every session), and a redaction pass over memory content
before it is written — because `redact_structure` runs on the *snapshot*, not on
the copy mem0 already sent to Qdrant. **The platform's redaction boundary is the
snapshot; a side-channel store is written before that boundary and never passes
through it.**

## 6. Identity: the kernel does not know who is asking

`Mem0Middleware` requires `user_id` at construction. The kernel cannot supply it:

- `_build_middlewares(self)` takes no arguments and returns one list
  ([`runtime_kernel.py:531-570`](../../products/agent-platform/src/agent_service/runtime_kernel.py));
- `_build_agent(self, session_id, bearer_token=None, model_id=None,
  read_only=False)` has **no user parameter**
  ([`runtime_kernel.py:773-808`](../../products/agent-platform/src/agent_service/runtime_kernel.py));
- `owner_user_id` exists only further out, on the execution-signing and
  confirmation paths (`recovery.create_run(session_id, owner_user_id)`,
  `RunIdentity(run_id, session_id, owner_user_id)`), never on agent
  construction;
- identity at the tool boundary is carried **only** by the delegated token in a
  contextvar (gate point 2, SPEC-018 R-2) — deliberately, so a cached toolkit
  keeps working across portal token refresh.

And the cache invariant is explicit: "Agents are keyed by session so
**conversation memory never crosses sessions**"
([`runtime_kernel.py:817-827`](../../products/agent-platform/src/agent_service/runtime_kernel.py)).
Long-term operator memory is defined by breaking that invariant.

The consequence is not merely plumbing. A per-user middleware constructed once
and shared across sessions would leak one operator's memories into another's
context; a per-session construction would need identity threaded through
`ensure_agent` → `_build_agent` → `_build_middlewares`, plus a decision about
the `read_only` twin cache entry (which restores the same persisted memory under
a different toolkit) and about agent eviction (the LRU holds up to 1,000 agents;
a middleware per agent means a mem0 client per agent). That is a real
multi-operator isolation surface being introduced to serve a need §2.2 cannot
evidence.

Ownership enforcement today is by **404, not 403** — foreign session ids are
indistinguishable from unknown ones, and the handover spike's rule was that any
cross-owner surface must be "a **separate, role-gated endpoint family** — never
a relaxation of the owner check". A memory store scoped by a `user_id` string
supplied at construction is the opposite of that discipline.

## 7. Where the state would have to live

The roadmap row asks the question directly, so answer it directly. Four
candidates, none free:

| Candidate | Shape | Objection |
|---|---|---|
| **Pod filesystem** (`emptyDir` at `AGENTSCOPE_WORKSPACE_DIR`) | what `AgenticMemory` and ReME do by default | Lost on reschedule, invisible to any second replica. Already rejected once, for the SPEC-064 offloader, in a comment that is still in the kernel source |
| **New vector server** (Qdrant, mem0's default) | a new StatefulSet, PVC, backup story, and NetworkPolicy | The semantic-retrieval memo rejected `QdrantStore`/Elasticsearch/MongoDB as "strictly worse than reusing the Postgres that already holds the skills". Note also that `pgvector` is **not installed** on the stock `postgres:16-alpine` (0 of 61 available extensions match `%vector%`), so "just put the vectors in Postgres" is an image swap on the StatefulSet holding all four databases |
| **New Postgres table in `sessions`** | the honest answer if the platform built its own | It would be the first **unbounded, mutable, per-user, LLM-written** table there (§2.1). Needs a retention class decision, a cap, a sweeper, a deletion/rectification path, and an ownership model — none of which exist for that shape. And retrieval over it needs either the lexical `rank()` (whose defects are measured in the sibling memo) or embeddings, which needs an embedder, which the cluster does not have |
| **Hosted SaaS** (`mem0.AsyncMemoryClient`) | an API key and egress | Operator triage transcripts, including any secret material the redaction layer would have masked in the snapshot, sent to a third party. Contradicts the egress posture SPEC-039/SPEC-049 were built around |

**Recommendation: none.** If a requirement ever arrives, **Option B** (§8.2) is
the only shape consistent with the gate — and it does not reuse any of
the three middlewares.

## 8. Options considered

### 8.1 Option A — adopt a middleware as shipped (rejected)

Fails three of four gate points for all three candidates (§4), introduces an
unbounded retention class (§2.1, §7), produces memory no operator can see (§5),
and needs an identity edge the kernel deliberately does not have (§6) — to serve
a need the record does not evidence (§2.2). Two of the three also need a new
dependency and an embedder the cluster cannot currently supply.

### 8.2 Option B — a gateway-fronted memory connector (the only shape that could clear the gate)

Recorded so the work is not repeated if a real requirement arrives. Not
recommended now.

Build memory as a **tool-gateway connector**, exactly like `skills.*`:

- `memory.search` / `memory.record` as gateway tools with `risk_level="read"`
  and `"mutate"` respectively, so gate 1 holds: deny-by-default policy, admission,
  and an audit event on every call come free from the gateway path.
- `memory.search` joins `DEFAULT_AUTO_ALLOWED_TOOLS` only if it is genuinely
  read-only; `memory.record` parks a confirmation card — which is *correct*,
  because persisting a claim about an operator's environment is a mutating act.
- Storage is a platform-owned Postgres table with an explicit retention class,
  a per-owner cap mirroring `operation_documents.PER_OWNER_CAP`, and a sweeper
  mirroring `HISTORY_WINDOW_DAYS`.
- Identity comes from the delegated token the gateway already forwards — no new
  identity edge, so gate 2 holds.
- Content is written **only** from text that has passed
  `prose_redaction`/`redact_structure`, so the redaction boundary is respected
  rather than bypassed.
- Results surface as evidence frames, so gate 4 holds and §5's invisibility
  defect disappears.

Cost: a connector, a table, a retention policy, an audit event type (contract
change), a portal vocabulary entry, and a drift-guard update — i.e. **a spec's
worth of work in which the three agentscope middlewares contribute nothing but
their prompt strings.** At that point "adopt agentscope long-term memory" is no
longer the description of the work, and the backlog row's framing is wrong.

### 8.3 Option C — extend the governed artifact path already shipped (recommended if anything is done)

If operator continuity becomes a stated need, fund the mechanisms that already
exist and already have governance, rather than adding a parallel ungoverned one:

- **SPEC-039 operation documents**: a shift summary is already the platform's
  answer to "what did the previous operator learn". Its 30-day window and
  20-per-owner cap are the retention decision; changing them is a small,
  reviewable product change.
- **SPEC-044/045 skill drafting and graduation**: 8 graduations in the trail.
  When a triage produces reusable knowledge, the governed route is a draft skill
  an approver reviews — which then becomes retrievable by `skills.search` for
  *every* operator, not just the one who happened to run the session.
- **The alias map** from the
  [semantic-retrieval memo §4.4](./semantic-skill-retrieval-spike.md#44-option-d--improve-the-lexical-baseline-first-cheapest-may-be-sufficient):
  it addresses the only repetition actually observed (§2.2), deterministically,
  with the synonym list itself reviewable as an artifact.

All three keep a human in the write path. That is the property a memory store
removes.

### 8.4 Option D — close the row (recommended, and accepted 2026-10-01)

The row asks whether the middlewares "add real triage continuity across
sessions". On the evidence: the continuity need is unobserved, the surfaces fail
the adoption gate three points each, and the platform already ships two governed
mechanisms for the same function. **Close the row** with the reopen conditions
in §9 recorded, and let Option C absorb any future requirement.

A null result is a publishable outcome — the same posture the semantic-retrieval
memo takes, and the reason its gate 1 says "without these numbers, no retrieval
change is approved".

**The operator accepted this option on 2026-10-01** (§11 gate 5); the backlog row
is closed and the acceptance authorized no implementation.

## 9. What would have to be true to reopen

Recorded as conditions, not as a promise to revisit:

1. **A stated operator need, from operations, not from a library's feature
   list.** Concretely: operators reporting that they re-establish context by
   hand at shift change, or re-run diagnostics a colleague already ran.
2. **A measurement the platform can actually make.** Today it cannot: `chat_started.details`
   carries only `input_modality` and `model`, so no transcript text is retained,
   and `skill_searched` carries no `username` or `session_id` at all (§2.2).
   Reopening requires first deciding **what** to record — and recording operator
   conversation content in the audit trail is itself a governance decision, not
   a prerequisite to be waved through.
3. **A retention-class decision.** An explicit answer to: how long does a
   platform-held claim about an operator's environment live, who can delete it,
   who can read another operator's, and what happens on offboarding. The
   existing answers are 1 hour (session) and 30 days (window); "indefinitely" is
   a new one.
4. **An embedder decision**, if retrieval is semantic: enable embeddings on the
   in-cluster Ollama and pull a pinned model (no egress, no spend, no new
   secret), or accept DashScope (egress, spend, a new secret, and conversation
   text leaving the cluster). The semantic-retrieval memo §10.4 frames the same
   choice for skill bodies; the two should be decided together.
5. **Evidence that Option C is insufficient** — i.e. that governed, reviewed,
   role-visible artifacts do not carry the knowledge, and an ungoverned private
   store is genuinely required.

Conditions 1, 3, and 5 are product and governance decisions. None is a
technology question, and no middleware answers any of them.

## 10. Boundaries — what this memo authorizes

**Nothing beyond itself.** Specifically, this memo does **not** authorize:

- installing `mem0`, `reme`, or any embedding/vector dependency in any product;
- wiring, constructing, or feature-flagging any of the three middlewares, in any
  mode, in any environment including dev;
- any schema change, table, migration, or retention-policy change;
- any audit `event_type` addition, contract change, or portal vocabulary change;
- assigning `AgentState.session_id`, or any other change to the kernel's
  identity or cache invariants;
- registering agentscope's builtin filesystem or shell tools (`Write`, `Read`,
  `Edit`, `Bash`, `Glob`, `Grep`, `PowerShell`) in any toolkit;
- any ADR, spec, or roadmap promotion.

The one thing this memo *does* recommend changing is documentation: the
[utilization audit](./agentscope-utilization-audit.md) row for long-term memory
middlewares, which currently says "Spike needed (ReME evaluated, does not fit
as-is)" and should record that the spike has now been done, that all three
surfaces were scored, and that the verdict is keep-out with the §9 reopen
conditions. That edit is a docs change and needs no further authorization beyond
the operator's approval of this memo.

## 11. Go / no-go gates

1. **Accept the evidence finding.** The continuity need is unobserved in the
   platform's own record: 107 of 124 sessions single-turn, all session and
   incident tables TTL-swept to 0 rows, one identity doing all the work, and the
   only repetition signal being seven phrasings of one skill search. **Gate: if
   operations cannot state a concrete continuity need, the row closes here.**
2. **Accept the gate scoring.** All three middlewares fail gate points 1, 2, and
   3 as shipped, and no configuration of any of them passes. **Gate: any proposal
   to adopt one must first say which gate point it now clears and what changed.**
3. **Decide the retention class before the technology.** If a need is stated,
   the first deliverable is a written answer to §9.3 — not a prototype. **Gate:
   no storage decision is approved without it.**
4. **If anything is built, it is Option B, and the middlewares are not in it.**
   A gateway-fronted `memory.*` connector with an explicit retention class,
   delegated-token identity, redaction before write, evidence frames, and an
   audited event type. **Gate: no middleware wiring is approved; a connector spec
   is the only promotable shape.**
5. **Otherwise close the row** and let Option C absorb the requirement. **Gate: a
   null result closes the backlog row, and reopening needs §9 conditions 1, 3,
   and 5 — not a library upgrade.**

## 12. Open questions

- Should `chat_started` retain a redacted first-turn digest so cross-session
  repetition becomes measurable at all? That is an audit contract change with a
  real privacy cost, and it is a prerequisite for §9.2 rather than a consequence
  of it.
- Is `AgentState.session_id` a latent defect independent of memory? Nothing sets
  it, so every snapshot carries a random UUID that no platform surface can join
  against. If any future agentscope feature keys on it, the platform will be
  relying on an identifier it does not control. Worth a one-line reconciliation
  in the kernel **as its own change**, with its own test — not folded into a
  memory spike.
- Does the 30-day window on `confirmation_records` and `operation_documents`
  still match operations' actual retention expectation, now that both are the
  platform's longest-lived operator-facing state? If it does not, that is a
  cheaper and better-governed change than any memory store.
- Would a `documents:read`-gated "recent published summaries for my role"
  surface deliver most of the perceived benefit of operator memory, using only
  artifacts that already exist, are already reviewed, and are already audited?
- If mem0's `agent_control` mode were adopted hypothetically — no auto
  write-back, tools only — would the confirmation-card-per-write behaviour
  (§4) be acceptable, or is a mutating memory tool fundamentally incompatible
  with a HITL posture designed for infrastructure changes?

## Changelog

- 2026-10-01 — initial assessment. Evidence: static read of all three
  middlewares in `agentscope/middleware/_longterm_memory/` under the pinned
  **agentscope 2.0.8** venv (`AgenticMemoryMiddleware` 953 lines,
  `Mem0Middleware` 741 + a 439-line adapter + 270 lines of tools,
  `ReMeMiddleware` 552 + 376 lines of config), including constructors, mode
  semantics, write paths, exception handling, and the `BackendBase` surface;
  import probes establishing that `mem0` and `reme` are **absent** from
  `products/agent-platform/.venv` (155 distributions) while `AgenticMemory` is
  constructible; `AgentState.model_fields` and a live instantiation confirming
  `session_id` is a random per-instance default; static read of
  `runtime_kernel.py` (`_build_middlewares`, `_build_agent`, `ensure_agent`,
  `_build_kernel_configs` and its SPEC-064 R-2 offloader comment,
  `_snapshot_state`, `NO_TOOLS_NOTICE`), `kernel_middleware.py`
  (`KERNEL_LOCAL_TOOL_NAMES`, `DEFAULT_AUTO_ALLOWED_TOOLS`,
  `GatewayPermissionMiddleware`, `ToolEvidenceMiddleware`), and
  `session_transcript.py` (`_TRANSCRIPT_ROLES`, `_extract_text`); retention
  constants read from `session_store.py`, `agent_state_store.py`,
  `confirmation_records.py`, `operation_documents.py`, and `evidence_store.py`;
  the closed 22-value `event_type` enum in
  `shared/shared-contracts/schemas/audit-event.schema.json`; the agent-platform
  `emptyDir` workspace volume and `AGENTSCOPE_WORKSPACE_DIR` in the dev-k8s base.
  Read-only live-cluster queries against `postgres-0`: `audit` event-type
  totals, per-username aggregates, turns-per-session distribution, session
  creation by day, repeated `skill_searched` queries, and null-attribution
  counts for `skill_searched` vs `chat_started`; `pg_stat_user_tables` row
  counts for the `sessions` (15 tables) and `incidents` (3 tables) databases.
  Prior art re-read: the 2026-08-20 long-term-memory row in
  `agentscope-utilization-audit.md`, `session-handover-spike.md`, SPEC-018's
  four-point adoption gate, and the SPEC-064 R-1 compression/GoalPipeline spike.
  Recommendation: **do not adopt; close the backlog row** (Option D), with
  Option C (extend the governed SPEC-039 / SPEC-044 / SPEC-045 artifact path and
  the retrieval alias map) recorded as the direction to fund instead, and Option
  B (a gateway-fronted `memory.*` connector) recorded as the only shape that
  could clear the gate. **Assessment only — no dependency installed, no
  middleware wired, no schema, contract, audit-vocabulary, manifest, ADR, or
  spec change, and nothing committed or pushed by this pass.**
- 2026-10-01 — §10's one recommended documentation change applied, on the
  operator's instruction to start this spike: the
  [utilization audit](./agentscope-utilization-audit.md) §2 long-term-memory row
  now reads **kept out** with all three surfaces scored per gate point and its
  `Scope:` line records the resolution alongside SPEC-064's; this memo is indexed
  in [docs/workspace/README.md](./README.md); and the
  [Exploration Backlog](../agentic-aiops-platform/delivery-roadmap.md#exploration-backlog)
  "Long-term operator memory" row carries the assessment. The roadmap row records
  the disposition as **memo recommends closing the row, pending the operator's
  acceptance** rather than as closed — this memo is a recommendation, and §11
  gate 5 is the operator's to pass, not the author's. Still no product, config,
  dependency, schema, contract, or manifest change; no CHANGELOG entry, matching
  the docs-only-memo precedent (`mcp-ingestion-spike.md` has none).
- 2026-10-01 — **§11 gate 5 passed: the operator accepted Option D.** The
  backlog row is now recorded as **closed 2026-10-01** rather than as
  recommended-pending, and the [utilization audit](./agentscope-utilization-audit.md)
  §2 row drops its "pending the operator's acceptance" qualifier. Reopening
  requires §9 conditions 1, 3, and 5 — a stated operator continuity need, a
  written retention-class decision, and evidence that the governed Option C path
  is insufficient — and not a library upgrade. No implementation was authorized
  or performed by the acceptance.
