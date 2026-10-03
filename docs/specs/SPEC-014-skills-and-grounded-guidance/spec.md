# SPEC-014: Skills And Grounded Guidance (Release 2)

## Status

- status: `delivered`
- owner: workspace maintainers
- created: 2026-08-14
- approved: 2026-08-14
- delivered: 2026-08-15
- release slice: `R2` (Skills and Grounded Guidance)
- related ADRs: none yet

## Summary

Deliver Release 2: team-owned Markdown skills (runbooks, procedures, tribal
knowledge) are ingested from a federation of team-owned Git repositories,
validated, indexed, and made searchable to the agent, so operator answers
blend live cluster evidence with cited team-owned guidance. Skills reach the
agent exclusively as a read-only `skills.search` tool through the existing
tool execution framework, inheriting policy, audit, redaction, and
evidence-panel behavior with no new trust surface.

## Motivation

- R1 proved the platform useful for live status and diagnostics, but every
  answer stops at raw evidence: the platform has no access to how *this team*
  says to interpret or act on that evidence. The delivery roadmap
  (`delivery-roadmap.md`, R2) names this as the next trust-and-utility layer.
- The `skills-hub` product boundary already exists as a placeholder
  (`products/skills-hub/README.md`, `docs/workspace/product-boundaries.md`)
  with its responsibilities pre-declared: Git-based ingestion, Markdown
  validation, metadata normalization, indexing, and retrieval support.
- All the guardrails R2 needs are already delivered and battle-tested:
  deny-by-default policy (SPEC-004), the read-only tool framework
  (SPEC-007), service identity (SPEC-008), redaction (SPEC-009), evidence
  frames and portal evidence panels (SPEC-011), and the durable audit trail
  (SPEC-013). Routing skill retrieval through that same framework means R2
  adds capability without widening the trust model.
- Grounded guidance is the prerequisite for R3 (incident triage) and R4
  (bounded actions): recommendations and approvals must cite team procedure,
  not just raw telemetry.

## Requirements

Each requirement is stable once the spec is `approved` and carries testable acceptance criteria.

### R-1: Skill document contract

Skills are Markdown documents with YAML frontmatter, governed by a shared
JSON schema so ingestion, retrieval, and UI rendering agree on one shape.

Acceptance criteria:

- new `shared/shared-contracts/schemas/skill.schema.json` defines the skill
  envelope: `skill_id` (`<source_id>/<slug>`, globally unique via source
  namespacing), `source_id` (operator-assigned source name), `source_path`
  (file path within the source repo), `source_ref` (synced Git ref or
  local marker), `title`, `description`, `tags` (bounded string list),
  `version`, and `updated_at`
- frontmatter contract documented in `shared/shared-contracts`: required
  keys (`title`, `description`), optional keys (`tags`, `version`,
  `source_url` — upstream attribution link for adapted open-source
  content), size caps (body ≤ 64 KiB, description ≤ 500 chars, ≤ 10 tags);
  the slug is derived from the file path, not from frontmatter, so moves
  within a repo are visible as id changes
- contract tests bind skills-hub Pydantic models to the schema, matching the
  SPEC-013 audit-event contract-test pattern

### R-2: skills-hub product with federated multi-source ingestion

A new `products/skills-hub` service ingests skills from a federation of
team-owned sources (Git repositories, or local directories in dev), validates
them, and serves the validated set; invalid documents are rejected with a
reportable reason, never silently dropped or partially indexed.

Acceptance criteria:

- new FastAPI product following the service-family conventions: frozen
  dataclass `SKILLS_*` settings from environment, structured JSON logging,
  `/health`, `/metrics` (per `observability-conventions.md`), per-product
  Makefile with uv lockfile, containerized on the shared base-uv image as a
  non-root user
- sources are configured as a list (`SKILLS_SOURCES`), each entry carrying
  `source_id`, a type discriminator, and type-specific fields: `git`
  (`SKILLS_GIT_REPO_URL`-style URL, ref, and a credential reference for
  private repos) or `local` (directory path); admission of a team is the
  operator adding a source entry — skills-hub never crawls or auto-discovers
  repositories
- each source is checked out into its own isolated working directory under
  the service data path; checkouts are disposable caches (a re-clone or
  re-copy is always safe) and the store/index is authoritative
- sync runs on a configurable interval per source; git sources clone/pull,
  local sources re-read; each source's validated set swaps atomically and
  independently, so one source's failed sync never blocks or disturbs
  another source's served skills
- validation on ingest: frontmatter parses, required keys present, size caps
  from R-1 honored, duplicate slug within one source rejected (cross-source
  duplicates are legal because ids are namespaced); each rejection produces
  a structured validation error (source + path + reason) exposed via the
  status endpoint
- store backends behind a `SkillStore` protocol: `InMemorySkillStore`
  (dev/tests) and `PostgresSkillStore` (psycopg v3), selected via
  `SKILLS_STORE_BACKEND`, following the SPEC-013 audit-service precedent;
  records carry `source_id` so per-source replacement is exact
- a `GET /api/v1/skills/status` endpoint reports the last sync outcome per
  source: timestamp, ref, accepted count, and the per-document rejection list

### R-3: Search and retrieval API

skills-hub serves deterministic, explainable retrieval to platform callers,
searching across all federated sources as one knowledge pool.

Acceptance criteria:

- `GET /api/v1/skills` (list with optional `source` and tag filters +
  pagination), `GET /api/v1/skills/{skill_id}` (full document), and
  `GET /api/v1/skills/search?q=<query>` (ranked matches across all sources,
  optional `source` filter) are available
- search ranking is deterministic and explainable: keyword matching against
  title, tags, and body with fixed weighting (title > tags > body); equal
  scores break ties by `skill_id`; no machine-learning retrieval in this
  slice
- every search hit carries provenance (`source_id`, `source_path`,
  `source_ref`, `updated_at`) so downstream citations can name the team and
  document the guidance came from
- search results are bounded (`limit` capped, excerpt snippets ≤ 400 chars)
  so payloads stay safe for LLM context injection
- authentication follows the SPEC-013 credential vocabulary but with a
  distinct query registry from day one: static Basic clients via
  `SKILLS_QUERY_CLIENTS` or projected workload tokens (`SKILLS_WORKLOAD_*`);
  unauthenticated requests receive 401
- unknown skill ids return 404; malformed parameters return 400 with a
  structured error; no unhandled 500 paths for caller-controlled input
- all ingested skills are retrievable by all authenticated platform callers;
  per-team read scoping is out of scope for this slice

> **Superseded in part (2026-10-03, SPEC-066 R-9, delivered).** The "keyword
> matching against title, tags, and body with fixed weighting" and "`skill_id`
> tie-break" wording above is no longer complete: SPEC-066 made four
> lexical-fidelity fixes unconditional in `services/scoring.py` — `skill_id` is a
> **fourth scored field** (tag weight), every term is **IDF-weighted**, the capped
> body term is **length-normalized**, and the **query** is CamelCase-split
> (document fields stay unsplit, so Postgres `to_tsvector('simple')` parity holds
> by construction). The determinism/explainability guarantee, the field-weight
> *ordering* (title > tags > body), the ascending `skill_id` tie-break, and "no
> machine-learning retrieval in this slice" all still hold. The criterion text is
> preserved as delivered history; see
> `docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/`.

### R-4: skills.search read-only tool in the tool execution framework

The agent reaches skills exclusively through tool-gateway, as a registered
read-only tool, so skill access is policy-checked, audited, redacted, and
evidenced like every other tool call.

Acceptance criteria:

- new `skills_connector.py` in tool-gateway registers `skills.search` (and
  `skills.get` for full-document retrieval by id) with
  `risk_level="read"`, `category="skills"`, and parameter schemas matching
  the R-3 API
- the connector authenticates to skills-hub with a gateway-held credential
  (`GATEWAY_SKILLS_CLIENT_ID` / `GATEWAY_SKILLS_CLIENT_SECRET` ↔
  `SKILLS_QUERY_CLIENTS`), never forwarding the user's token
- unsetting `GATEWAY_SKILLS_SERVICE_URL` leaves the gateway exactly as
  before this spec (tools simply do not register); a configured but
  unreachable skills-hub yields structured `TOOL_EXECUTION_ERROR` results
- invocations flow through the existing choke points unchanged: policy
  (`tools:invoke`), output redaction, `tool_invoked` audit emission, and
  SPEC-011 `tool_call`/`tool_result` stream frames
- the tool is on the read-only auto-approval allow-list for the AgentScope
  permission engine (same mechanism as the existing read-only tools)

### R-5: Runbook-aware answers with visible citations

Answers cite the team guidance they used, and operators can see the cited
skills.

Acceptance criteria:

- the agent's default system prompt (`DEFAULT_SYSTEM_PROMPT`) is extended
  with a skills discipline: when a question involves procedure,
  interpretation, or remediation, consult `skills.search` and cite the
  skills used by title; never present skill guidance as live cluster data
  and never present tool evidence as procedure
- when `skills.search` is invoked, its `tool_result` frame carries the
  matched skills (id, title, excerpt) in `data_summary`, rendered by the
  existing portal evidence panel without new portal chrome
- the agent's reply names the cited skills so citations survive outside the
  evidence panel (e.g. in plain chat transcripts)
- with zero skills ingested, `skills.search` returns a success result with an
  empty match list and the agent reports that no team guidance matched,
  rather than failing or fabricating

### R-6: Deployment, configuration, and living-state docs

Acceptance criteria:

- dev-k8s overlay deploys skills-hub (Deployment, Service, runtime-config
  ConfigMap, runtime-secrets Secret) behind `make deploy`, configured with
  two sample `local` sources seeded from skill sets checked into the
  workspace: `sre-alerting` (adapted from the open-source
  prometheus-operator runbooks, Apache-2.0, tagged with their alert names)
  and `platform-runbooks` (adapted from the Kubernetes troubleshooting
  guides, CC-BY-4.0), each carrying a NOTICE file with upstream attribution
  — so the dev cluster boots with real, community-trusted multi-source
  guidance and exercises namespacing end to end
- an end-to-end demo smoke script (`shared/platform-ops/e2e/skills-demo.sh`)
  runs after `make deploy` and asserts deterministic outcomes only: both
  sample sources synced with non-zero accepted counts and zero rejections;
  the alert-name search returns the expected runbook first with provenance;
  a scripted chat through platform-gateway produces a `skills.search`
  `tool_call`/`tool_result` frame pair with non-empty matches — LLM prose
  is left to human validation
- the operator guide gains a scripted "Skills demo tour" section (golden
  questions covering the alert→runbook loop, cross-source citation, and the
  honest no-match path) usable both as UAT checklist and operator training
- tool-gateway runtime config gains `GATEWAY_SKILLS_SERVICE_URL` and client
  credentials wired by the same secrets-sync pattern as the audit chain;
  unset URL preserves pre-spec behavior
- living-state docs updated on delivery: root `README.md`,
  `products/skills-hub/README.md` (placeholder → real product doc),
  tool-gateway README, `docs/guides/configuration-reference.md`,
  `docs/guides/tool-configuration.md`, `docs/guides/architecture-overview.md`
- delivery artifacts: CHANGELOG entry, release note, spec index updated to
  `delivered`

### R-7: Tests and verification gate

Acceptance criteria:

- skills-hub unit suite covers: frontmatter validation failures (each rule),
  atomic sync swap, duplicate-id conflict, search ranking determinism and
  tie-breaking, pagination, auth (401/200 paths), and the Postgres store
  against a fake driver double
- tool-gateway suite covers the skills connector: registration gating on
  `GATEWAY_SKILLS_SERVICE_URL`, credential handling, unreachable-service
  error mapping, and contract tests binding connector payloads to the R-1
  schema
- agent-platform suite covers the extended system prompt default and the
  empty-match `skills.search` behavior contract
- `make verify` passes: all product suites green and all overlays render

## Non-Goals

- semantic/vector retrieval (embeddings, vector stores) — keyword retrieval
  first; a follow-up spec may upgrade ranking once real skill content exists
- webhook/event-driven ingestion — scheduled sync plus local-directory mode
  only; Git push integration is a later operational concern
- per-team read scoping of skills — all ingested skills are visible to all
  authenticated platform callers; source-level visibility is a possible
  follow-up if team-private runbooks become a requirement
- skill authoring UX, version history, or diffing — Git review is the
  authoring and approval workflow; skills-hub only consumes committed content
- skill write/mutation tools and any execution guidance automation —
  read-only retrieval; acting on guidance belongs to R4 approval-gated
  actions
- incident intake, triage, or ticketing integration — R3 territory
- a separate `knowledge-service` product — the roadmap's generic naming maps
  onto `skills-hub` per this workspace's product boundaries; no new product
  beyond it

## Impact

- products touched: `products/skills-hub` (new), `products/tool-gateway`
  (skills connector + settings), `products/agent-platform` (system prompt),
  `products/operator-portal` (none expected — existing evidence rendering)
- contracts touched: new `shared/shared-contracts/schemas/skill.schema.json`;
  frontmatter convention documented in `shared/shared-contracts`
- identity / policy / audit / execution safety impact: no new policy actions
  (existing `tools:invoke` covers the tool); no new user-facing
  authorization; audit coverage inherited from the tool-invoke choke point;
  skills-hub adopts a distinct query-credential registry from day one,
  deliberately avoiding the SPEC-013 shared ingest/query credential
  limitation
- living state docs to update on delivery: root `README.md`, product READMEs
  (skills-hub, tool-gateway), `docs/guides/configuration-reference.md`,
  `docs/guides/tool-configuration.md`, `docs/guides/architecture-overview.md`,
  `CHANGELOG.md`

## Open Questions

None — all resolved (see Changelog).

## Changelog

- 2026-08-14: created as `draft` for the R2 release slice
- 2026-08-14: Q-1 resolved — federated multi-source ingestion selected over
  a single aggregation repo: teams own their skill repositories and the
  platform admits them via `SKILLS_SOURCES` entries; skill ids are
  namespaced `<source_id>/<slug>`; sync atomicity is per-source; dev seeds
  two sample local sources. R-1, R-2, R-3, and R-6 updated accordingly.
  Per-team read scoping explicitly deferred (R-3).
- 2026-08-14: Q-2 resolved — `PostgresSkillStore` reuses the dev-k8s
  `postgres` instance with a separate `skills` database (audit-service
  precedent); `InMemorySkillStore` remains for tests and bare local runs.
  Status → `approved`.
- 2026-08-15: agreed change to the approved spec — sample content strategy
  finalized: the two dev sample sources are adapted from community-trusted
  open-source content (`sre-alerting` ← prometheus-operator runbooks
  Apache-2.0 with alert-name tags; `platform-runbooks` ← Kubernetes
  troubleshooting guides CC-BY-4.0) with per-source NOTICE attribution,
  replacing invented placeholder runbooks; a third vendor-derived source
  was evaluated and rejected (young repo, vendor-tied). R-1 gains the
  optional `source_url` frontmatter key for upstream attribution; R-6
  gains the e2e demo smoke script and the operator-guide Skills demo tour
  as acceptance criteria.
- 2026-10-03: R-3's ranking criterion annotated (not edited) — SPEC-066
  (`delivered`) made four lexical-fidelity fixes unconditional in
  `services/scoring.py`: `skill_id` is now a fourth scored field, terms are
  IDF-weighted, the capped body term is length-normalized, and the query is
  CamelCase-split (document side unsplit, so Postgres parity holds by
  construction). Determinism/explainability, the title > tags > body ordering,
  the `skill_id` tie-break, and the no-ML boundary are unchanged.
