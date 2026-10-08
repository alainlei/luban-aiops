Each subdirectory under `products/` is a self-contained FastAPI application with its own `pyproject.toml`, `uv.lock`, Dockerfile, Makefile, `.python-version`, and test suite. The shared internal layout across services is:
- `src/<service>/app.py` — FastAPI factory (`create_app`) wiring logging, metrics, telemetry, request-id middleware, and router inclusion.
- `src/<service>/main.py` — entrypoint (uvicorn bootstrap).
- `src/<service>/api/router.py` + `api/routes/*.py` — route definitions per concern.
- `src/<service>/core/{config,metrics,observability,request_context,runtime,telemetry}.py` — cross-service infrastructure helpers.
- `src/<service>/schemas/` — Pydantic models for API contracts.
- `src/<service>/services/` — domain logic (store clients, policy engines, connectors, etc.).
- `tests/` — unit tests; some services add integration/failure suites (e.g. `execution-runtime/tests/failure/`).

The product boundary is defined by stable HTTP APIs between services rather than shared code: `platform-gateway` is the external-facing edge proxy routing to `agent-platform`, `skills-hub`, `tool-gateway`, `incident-service`, `audit-service`, and `identity-broker`; `execution-runtime` is a separate worker process invoked by agents via handoff contracts in `contracts/` (shared JSON schemas plus an `execution-ledger-v1.sql` migration). `operator-portal/web-ui` is the only non-Python component — a Vite/React SPA served behind nginx. `policy-center/README.md` documents the YAML policy format consumed by `platform-gateway` and `tool-gateway` but has no code here.