# Operator Portal

## Purpose

`operator-portal` is the operator-facing web application for the platform.

It is responsible for:

- portal login and session entry
- chat and interaction UX
- evidence and incident context views
- approval queue and approval actions
- operator-visible execution status and audit visibility

## Ownership

Recommended owner:

- frontend or user experience team

## Current Scope

This project covers:

- portal shell and navigation
- chat and evidence presentation flows
- approval queue and approval response UX
- operator-visible audit and status views

Current implementation artifacts:

- `Dockerfile` (multi-stage: Node build → nginx runtime)
- `nginx.conf` (immutable-cache hashed assets, no-store SPA shell, `/api/` proxy)
- `web-ui/app/` — Vite + React 18 + TypeScript SPA on antd / Ant Design X
  (SPEC-023 rebuild; sources under `src/`, Vitest unit tests under `src/**/__tests__/`)

Build and develop:

- `npm ci && npm run dev` inside `web-ui/app/` (proxies `/api` to localhost:8080)
- `npm test` runs the Vitest suite; `make build` produces the image with the
  root `VERSION` injected as `PLATFORM_VERSION` at bundle time

Current browser baseline capabilities:

- multi-session workspace: a session panel lists operator–agent sessions with
  titles, relative last-active, and amber *awaiting approval* badges;
  switching sessions aborts/repoints the stream, loads the transcript, and
  keeps confirmation cards anchored to the parking session; sessions can be
  deleted with an in-UI confirm (parked sessions refuse with 409) (SPEC-022,
  SPEC-023); reloading a session re-attaches its persisted tool evidence
  (`evidence_turns`) to the matching assistant turns, so the replayed
  evidence cards are prop-identical to the live ones (SPEC-025)
- voice input: a composer microphone button performs browser speech-to-text
  (Web Speech API, no audio stored) and submits turns with
  `input_modality=voice`; a language selector (en-US / zh-CN, defaulting from
  the browser locale and persisted locally) drives the recognizer only
  (SPEC-023)
- model selector: a selection bar under the message input (extensible to
  future per-turn selections) shows the credential-gated model catalog
  (`GET /api/v1/models`) with the deploy-time default pre-selected; options
  are grouped by provider and labeled by model name (SPEC-026). Exactly
  one configured model renders as a fixed label, and any discovery failure
  hides the selector without affecting chat. The selection rides the stream
  request and switching sessions re-seeds the selector from the session's
  pinned model (SPEC-024)
- two-column app shell: a left sidebar carries the logo and the function
  list; the main column shows one function view at a time (Chat, Settings &
  Debug, Audit trail) with state preserved across switches; narrow
  screens collapse the sidebar into a hamburger-triggered off-canvas
  drawer
- sectioned sidebar navigation: Chat and (for studio roles) Studio stand
  alone as top-level entries; Control gathers Incidents, Approvals, Audit
  trail, and Permissions; Workspace gathers Documents, Tools, Skills, and
  Settings & Debug; section headers hide automatically when every entry
  in the section is hidden (SPEC-019)
- sidebar footer: a user card (initials avatar, username, icon-only
  Sign in / Sign out with tooltips; clicking the user opens a popup menu
  showing granted roles and — later — other user-related info), kept
  separate from the function list; the platform version renders as a muted
  chip in the logo row
- `OIDC` login start through `platform-gateway`
- authorization-code callback completion through `identity-broker`
- authenticated portal logout entry point
- silent background token refresh roughly 60 seconds before JWT expiry (via
  `POST /api/v1/auth/refresh`); on failure the session is cleared and
  re-authentication is prompted
- session creation, prompt send, and streamed response rendering through the
  proxied gateway path
- request ID visibility for debug-oriented validation
- evidence panel rendering tool trace events (`tool_call` and `tool_result`)
  as cards with status badges, collapsible parameters and data summaries, and
  evidence metadata — when a `tool_result` frame carries the full `data`
  payload (stream schema v5), the card offers a "Show full output" expander
  with the complete tool result — multi-line text fields (such as pod logs)
  render as raw log-style blocks rather than escaped JSON; visible when the
  agent invokes tools, hidden otherwise (SPEC-011); store-added truncation
  markers render as notes — an entry-cap-truncated payload flags its
  original size and partial preview, a session-budget-evicted payload hides
  the data expander and keeps its metadata (SPEC-025)
- inline HITL confirmation card: when the agent parks a tool batch awaiting
  approval, the chat renders a warning-toned card listing the pending tools
  with collapsible parameters plus Approve/Deny buttons; the decision posts
  to `/api/v1/chat/confirm` and the resumed stream renders in place; expired
  or already-decided cards lock with a status badge; buttons hide for roles
  without `chat:confirm` (the gateway re-enforces server-side) (SPEC-020)
- read-only durable audit trail view: filter bar, newest-first table, cursor
  pagination with a persistent "Load more" bar, and expandable event
  envelopes; the navigation entry renders only for identities whose roles
  hold `audit:read` (the gateway re-enforces the action server-side)
  (SPEC-013)
- Incidents panel: filterable incident list with auto-refresh, incident
  detail with the full triage report (severity assessment, evidence,
  hypotheses, ranked advisory next steps, cited skills), connector dispatch
  outcomes, Run triage with live triaging/failed states (failed runs expose
  the raw agent text), a Report incident form, and Continue in chat on the
  incident's dedicated session; viewing is gated by `incident:read`, acting
  by `incident:create` / `incident:triage` (SPEC-015)
- Permissions view: the live role × action matrix evaluated from the policy
  bundle platform-gateway actually enforces (`GET /api/v1/policy/matrix`),
  with bundle version/source provenance and server-side row scoping
  (platform-admin sees all roles, everyone else their own rows); visible to
  every signed-in user under `policy:read` (SPEC-019)
- Workspace resource views: read-only Tools catalog
  (`GET /api/v1/tools`, delegated-bearer proxy to tool-gateway under
  `tools:list`) and Skills inventory (`GET /api/v1/skills`, gateway-held
  query credential under `skills:read`) with source/tag filters (SPEC-019)

## Execution recovery (SPEC-063)

Decided cards in the owner's transcript expose read-only **Recovery detail**:
current state, bounded observation history, late results, integrity conflicts,
and explicit unavailable status. Session reads carry cursor paging; visibility-aware
polling is bounded to 120-second windows and rejects stale session responses.
The approver inbox remains decision-only. No retry, reset-claim, mark-success,
or secret-reveal control is added; reload never reconstructs a lost original result.

New document digests and Markdown exports retain execution uncertainty. Existing
published snapshots remain unchanged. A successful tool report is not independent
verification of target effects; operators must account for possibly running work.
See [the recovery guide](../../docs/guides/portal-user-guide.md#recovering-an-uncertain-execution).

`make portal-test` at the repository root runs the full Vitest suite and typechecked
production build; both are required by `make verify`.

## Expected Integration Points

- `identity-broker` for `SSO` and normalized identity context
- `agent-platform` for chat sessions and streaming responses
- `policy-center` for approval queue and decision state
- `shared/shared-contracts` for typed API and event payloads

## Boundary

This project does not own policy decisions, identity normalization, or privileged execution logic.
