# Skills Hub

## Purpose

`skills-hub` ingests team-owned Markdown skills from federated sources and serves them to the agent as grounded guidance.

It is responsible for:

- federated multi-source ingestion (`local` directories and `git` repositories)
- frontmatter validation and metadata normalization (`shared/shared-contracts/schemas/skill.schema.json`)
- namespaced skill ids (`<source_id>/<slug>`) with per-source atomic sync
- deterministic ranked search and full-record retrieval
- making team-owned knowledge available to the agent via `tool-gateway` (SPEC-014)

Operator documentation: the [Skills and Guidance Guide](../../docs/guides/skills-guide.md) covers day-2 content operations (adding, revising, and removing skills and sources).

## Ownership

Recommended owner:

- knowledge platform or operations enablement team

## Current Scope

Current implementation status (SPEC-014):

- frozen-dataclass `SKILLS_*` settings with fail-fast parsing of `SKILLS_SOURCES` and `SKILLS_GIT_TOKENS`
- ingestion pipeline: directory walk, YAML frontmatter parse, size caps, slug derivation, duplicate-slug rejection within a source
- local source sync (read → validate → atomic swap) and git source sync (subprocess clone/fetch/reset under `asyncio.to_thread`); a failed sync keeps the prior skill slice and counts `skills_syncs_total{source,result="error"}`; sources removed from `SKILLS_SOURCES` are pruned from the store at startup
- `SkillStore` protocol with two backends: `InMemorySkillStore` (dev/tests) and `PostgresSkillStore` (psycopg v3, `to_tsvector` candidate selection re-ranked by the shared scorer), selected via `SKILLS_STORE_BACKEND`
- query auth via a dedicated static Basic registry `SKILLS_QUERY_CLIENTS` (deliberately distinct from ingest vocabularies) plus projected workload tokens (`SKILLS_WORKLOAD_*`)
- standalone validator CLI for team pre-flight checks: `python -m skills_hub.validate <dir>`
- usage audit trail (SPEC-029): `skill_searched`/`skill_retrieved` events per authenticated query and one `skills_synced` event per sync cycle, emitted fire-and-forget to the audit service and correlated with the caller's `tool_invoked` events via `x-request-id`

API surface (all query routes require Basic/workload auth unless noted):

- `GET /api/v1/skills` — list skills with `source`/`tag` filters and capped offset pagination
- `GET /api/v1/skills/search?q=...` — deterministic ranked matches across four scored fields (title ×3; tags ×2; `skill_id` ×2 — a **scored field** since SPEC-066, not only the tie-break; body ×1, saturating at 5 occurrences), every term IDF-weighted and the body term length-normalized, with excerpt ≤ 400 chars and provenance. Ties break by `skill_id` ascending; `score` orders one result set and is not comparable across queries
- `GET /api/v1/skills/{source_id}/{slug}` — full skill record conforming to `skill.schema.json`
- `GET /api/v1/skills/status` — per-source sync state (auth-exempt health surface)
- `/health/live`, `/health/ready`, `/metrics`

Current runtime environment knobs:

- `SKILLS_SOURCES`
  - JSON list of admitted sources: `{"source_id": "...", "type": "local", "path": "..."}` or `{"source_id": "...", "type": "git", "url": "...", "ref": "HEAD"}`
- `SKILLS_GIT_TOKENS`
  - JSON map `{"<source_id>": "<token>"}` for private git sources
- `SKILLS_SYNC_INTERVAL_SECONDS`
  - per-source sync loop period; defaults to `300`
- `SKILLS_DATA_PATH`
  - working directory for git checkouts; defaults to `/var/lib/skills-hub`
- `SKILLS_STORE_BACKEND`
  - `memory` or `postgres`; defaults to `memory`
- `SKILLS_DB_URL`
  - PostgreSQL connection URL (required for the postgres backend)
- `SKILLS_QUERY_CLIENTS`
  - static query credential registry (`client_id=secret,...`); lives in `skills-hub-runtime-secrets`
- `SKILLS_WORKLOAD_ISSUER_URL`, `SKILLS_WORKLOAD_AUDIENCE`, `SKILLS_WORKLOAD_CLIENTS`
  - projected workload-token auth (production upgrade path, SPEC-009 vocabulary)
- `SKILLS_AUDIT_SERVICE_URL`, `SKILLS_AUDIT_CLIENT_ID`, `SKILLS_AUDIT_CLIENT_SECRET`
  - audit-service ingest endpoint and Basic credential for usage events (SPEC-029); an empty URL disables emission

## Expected Integration Points

- `tool-gateway` is the only platform caller: the skills connector registers `skills.search`, `skills.get`, and `skills.list`, authenticated against `SKILLS_QUERY_CLIENTS`
- `agent-platform` reaches skills indirectly through those tools; its system prompt carries the skills discipline (consult, cite, separate guidance from live data, honest no-match)
- `operator-portal` surfaces `skills.search` evidence frames in the evidence panel without changes
- `shared/shared-contracts` owns `skill.schema.json` and the `skill-format.md` frontmatter convention. The search `score` is a **published API field, not a validated-contract field** — it appears in no `shared-contracts` schema (SPEC-066 OQ-1(a)), so SPEC-066's re-weighting shipped with **no contract version bump**; only this README's prose describes it

## Boundary

This project does not execute tools, authorize actions, or own live session orchestration. It serves guidance content only; the agent is responsible for separating skill guidance from live cluster evidence.
