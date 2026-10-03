# SPEC-014 Tasks: Skills And Grounded Guidance (Release 2)

Task states: `[ ]` pending, `[x]` done. Keep tasks small and tied to requirement IDs.

## R-1: Skill document contract

- [x] add `skill.schema.json` envelope incl. optional `source_url` attribution field (`shared/shared-contracts/schemas/`)
- [x] write `skill-format.md` frontmatter convention incl. size caps, slug rule, and a "where to find open-source skills" discovery appendix (`shared/shared-contracts/`)
- [x] implement Pydantic skill models (`products/skills-hub/src/skills_hub/schemas/skill.py`)
- [x] contract tests binding models to the schema (`products/skills-hub/tests/test_contracts.py`)

## R-2: skills-hub product with federated multi-source ingestion

- [x] scaffold product: Dockerfile, Makefile (image+python fragments), pyproject + uv lock, metadata, README scaffold (`products/skills-hub/`)
- [x] port core chassis: config, metrics, observability, request_context, runtime, telemetry, health route (mirror audit-service)
- [x] `SKILLS_SOURCES` / `SKILLS_GIT_TOKENS` parsing with fail-fast startup errors (`services/source_config.py` + `tests/test_source_config.py`)
- [x] ingestion: directory walk, frontmatter parse, validation rules, slug derivation (`services/ingestion.py` + `tests/test_ingestion.py`)
- [x] local source sync (read → validate → atomic swap) (`services/sync.py` + tests)
- [x] git source sync via subprocess clone/fetch/reset in `asyncio.to_thread` (tests with a `file://` repo fixture)
- [x] `SkillStore` protocol + `InMemorySkillStore` with `replace_source` semantics (`services/skill_store.py` + `tests/test_skill_store.py`)
- [x] `PostgresSkillStore` (psycopg v3 pool, parameterized SQL, per-source replace) against a fake driver double
- [x] per-source sync loop tasks with jitter, `skills_syncs_total{source,result}` counter, failure keeps prior slice (`tests/test_sync.py`)
- [x] standalone validator CLI `python -m skills_hub.validate <dir>` reusing the service validation path (+ test against a fixture tree)

## R-3: Search and retrieval API

- [x] deterministic scorer: title ×3 / tags ×2 / body ×1 saturating, `skill_id` tie-break (`services/scoring.py` + `tests/test_scoring.py`)
  - **Correction (2026-10-03, SPEC-066 R-9, delivered).** SPEC-014 is `delivered`, so this is recorded by annotation rather than silent edit. SPEC-066 made four lexical-fidelity fixes unconditional in the same `services/scoring.py`, so this frozen weighting summary is superseded: `skill_id` is now a **fourth scored field** at tag weight (×2), not only the tie-break; every per-token contribution is scaled by a corpus-derived **IDF**; the capped body term is **length-normalized**; and the **query** is CamelCase-split (document fields stay unsplit, so Postgres `to_tsvector('simple')` parity holds by construction). The field-weight *ordering* (title 3 > tags 2 > body 1) and the ascending `skill_id` tie-break are **unchanged**, so the determinism/explainability guarantee still holds. See `docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/` and the `services/scoring.py` module docstring.
- [x] query auth: `SKILLS_QUERY_CLIENTS` Basic registry + workload tokens, 401 path (`services/query_auth.py` + `tests/test_query_auth.py`)
- [x] `GET /api/v1/skills` list with source/tag filters + capped offset pagination (`api/routes/skills.py` + tests)
- [x] `GET /api/v1/skills/{skill_id:path}` full record, structured 404 (tests)
- [x] `GET /api/v1/skills/search` ranked hits with excerpt ≤ 400 chars and provenance; 400 on malformed params (tests)
- [x] Postgres candidate selection (`to_tsvector`/`plainto_tsquery`) re-ranked by the shared scorer; byte-identical ordering parity test vs in-memory store
  - **Correction (2026-10-03, SPEC-066 R-6).** Two claims on the line above drifted from the shipped code. SPEC-014 is `delivered`, so this is recorded by annotation rather than silent edit. **(1)** The prefilter never used `plainto_tsquery`: it OR-joins `to_tsquery` lexemes, and `test_search_joins_multi_word_queries_with_or` documents that `plainto_tsquery` (which ANDs the words) would silently drop partial matches. **(2)** The "byte-identical ordering parity test vs in-memory store" was documented but never delivered — the existing Postgres tests ran against a fake driver that cannot exercise the `to_tsvector` prefilter. SPEC-066 R-6 (`products/skills-hub/tests/test_parity.py`) is the harness that actually enforces byte-identical ordering *and* numeric score equality across both backends over a committed 81-query set, against a real PostgreSQL 16. See `docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/`.

## R-4: skills.search read-only tool in the tool execution framework

- [x] settings: `skills_service_url`, `skills_client_id`, `skills_client_secret` (`products/tool-gateway/.../core/config.py` + settings tests)
- [x] `SkillsConnector` with `skills.search` / `skills.get` definitions and parameter schemas (`tools/skills_connector.py`)
- [x] httpx transport with Basic auth, 10s timeout, error mapping (404 → `SKILL_NOT_FOUND`, unreachable → `TOOL_EXECUTION_ERROR`) (`tests/test_skills_connector.py`)
- [x] registration in `_build_tool_registry()` gated on `GATEWAY_SKILLS_SERVICE_URL` (tests incl. unset-URL byte-parity)
- [x] empty-match success result contract test against a fake skills-hub double
- [x] contract tests binding connector payloads to `skill.schema.json`

## R-5: Runbook-aware answers with visible citations

- [x] extend `DEFAULT_SYSTEM_PROMPT` with the skills discipline (cite by title, guidance ≠ live data, report no-match honestly) (`products/agent-platform/.../runtime_settings.py` + tests)
- [x] add `skills.search`, `skills.get` to `DEFAULT_AUTO_ALLOWED_TOOLS` (sanitized-name test) (`tools/gateway_tools.py`)
- [x] verify portal evidence panel renders `skills.search` `data_summary` without changes (manual check during delivery; fix as portal bug if needed)

## R-6: Deployment, configuration, and living-state docs

- [x] author sample source `sre-alerting`: adapt 5–6 prometheus-operator runbooks (Apache-2.0) with frontmatter, `source_url`, alert-name tags, NOTICE (`shared/platform-ops/skills/sre-alerting/`)
- [x] author sample source `platform-runbooks`: adapt 4–5 Kubernetes troubleshooting guides (CC-BY-4.0) with deliberate pod-troubleshooting overlap, NOTICE (`shared/platform-ops/skills/platform-runbooks/`)
- [x] write per-source READMEs as the team contribution template (format, tagging, validator pre-flight command)
- [x] validate both sample sources with the validator CLI; fix any rejections before wiring into the overlay
- [x] skills-hub overlay base: deployment (ConfigMap volume for `/skills`, data path), service, runtime-config.env, runtime-secrets.env + example (`dev-k8s/base/skills-hub/`)
- [x] postgres: initdb ConfigMap + mount creating `skills` database for fresh clusters (`dev-k8s/base/infra/`)
- [x] `sync-skills-secrets.sh`: idempotent `CREATE DATABASE skills` via kubectl exec + write `skills-hub-runtime-secrets` and gateway secret, `SKIP_SKILLS_SECRETS` opt-out (`shared/platform-ops/gitops/`)
- [x] wire deploy: `deploy.sh` calls the sync script, `deploy-overlay.sh` handles the skills-hub image, overlay kustomization includes the new base
- [x] tool-gateway runtime-config/secrets fragments: `GATEWAY_SKILLS_SERVICE_URL=http://skills-hub:8000`, client id + secret
- [x] e2e demo smoke script `shared/platform-ops/e2e/skills-demo.sh`: status assertions, alert-name search ranking check, scripted chat asserting the `skills.search` frame pair
- [x] write the Skills demo tour section in `getting-started.md` (alert→runbook loop, cross-source citation, no-match path) as UAT checklist + operator training
- [x] update living docs: root README, skills-hub README, tool-gateway README, dev-k8s README, configuration-reference, tool-configuration, architecture-overview

## R-7: Tests and verification gate

- [x] all new suites green per product (`make test`)
- [x] `make verify` green: all product suites + all overlay renders

## Delivery Gate

- [x] all acceptance criteria in `spec.md` verified
- [x] living state docs updated (see spec `Impact` section)
- [x] `CHANGELOG.md` entry added referencing the spec ID
- [x] release note written (`docs/agentic-aiops-platform/release-notes/`)
- [x] spec index in `docs/specs/README.md` updated
- [x] spec status set to `delivered`
