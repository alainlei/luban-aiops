Layered FastAPI application with a clear dependency direction: `api/` routes depend on `services/`, which depend on `schemas/` and `core/`; nothing in `core/` imports upward.

- Entry point: `main.py` loads `SkillsRunSettings` (host/port) and starts uvicorn; `app.create_app()` wires lifespan, middleware, metrics, telemetry, and includes the router.
- API layer (`api/routes/`): thin HTTP handlers under `/api/v1` (`health`, `status`, `skills`) registered via `api/router.py`. Route order is deliberate — `status` and `search`/`validate` are declared before the `{skill_id:path}` catch-all so FastAPI matches them first.
- Services layer:
  - `ingestion.py`: pure validation of Markdown frontmatter + body against the shared skill contract (SPEC-044 / SPEC-055 / SPEC-057), producing `Skill` records plus `Rejection`s; deterministic traversal over sorted paths.
  - `skill_store.py`: strategy-pattern backend selection via `build_skill_store(settings)` returning either `InMemorySkillStore` (dev/test) or `PostgresSkillStore` (deployed), both implementing the `SkillStore` Protocol. DDL is idempotent (`CREATE TABLE IF NOT EXISTS` + `ALTER ... ADD COLUMN IF NOT EXISTS`) to migrate across spec versions.
  - `scoring.py`: shared tokenization/ranking used by both backends for byte-identical search ordering.
  - `sync.py` + `audit_emitter.py`: background sync manager that walks configured sources, calls ingestion, atomically replaces per-source snapshots, prunes unconfigured sources at startup, and emits audit events.
  - `query_auth.py`: authenticates callers against static Basic credentials or projected workload tokens (JWT).
- Core layer (`core/`): frozen `dataclass` settings loaded from `SKILLS_*` env vars (`config.py`), OpenTelemetry + Prometheus setup (`telemetry.py`, `metrics.py`), structured logging (`observability.py`), request-id propagation (`request_context.py`), and `runtime.py` for CLI run settings.
- Schema: `schemas/skill.py` defines the Pydantic `Skill` model that both ingestion and persistence round-trip through.
- Build/runtime: `pyproject.toml` declares `uv_build` as build backend, `skills-hub` console script, and a Dockerfile ships the app; tests live under `tests/` using pytest.