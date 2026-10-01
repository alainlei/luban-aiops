"""Mandatory failure proofs are explicit, never skipped into a green gate."""
from __future__ import annotations

import json
from pathlib import Path
import secrets
import time

import pytest

from support import host_clock
from support.barriers import Barriers
from support.http_services import counts, launch_http
from support.infrastructure import DisposablePostgres
from support.processes import ProcessService, launch_worker
from support.scenarios import CASES, coverage_errors


def pytest_addoption(parser):
    parser.addoption("--proof-stage", choices=("campaign", "harness", "baseline-red", "development"))
    parser.addoption("--proof-evidence")


def pytest_configure(config):
    config.addinivalue_line("markers", "scenario(row, case): required matrix parameter case")
    config.addinivalue_line("markers", "baseline_red: intentionally failing pre-fix invariant")
    config.proof_records = {}
    config.proof_metadata = {}
    config.proof_nodes = {}
    # Session-level suspension detector. The wall clock follows the RTC across a
    # host sleep while the monotonic clock does not advance, so their divergence
    # measures time the host spent asleep and the tests did not run. Recorded
    # independently of the database clock so a run that never stamps an envelope
    # still reports whether it was suspended.
    config.proof_started = (time.time(), time.monotonic())


def pytest_collection_modifyitems(config, items):
    stage = config.getoption("--proof-stage")
    if not stage or not config.getoption("--proof-evidence"):
        raise pytest.UsageError("use the failure-proof runner; no implicit integration skip")
    selected = {}
    keep, deselected = [], []
    for item in items:
        baseline = item.get_closest_marker("baseline_red") is not None
        if baseline != (stage == "baseline-red"):
            deselected.append(item)
            continue
        markers = list(item.iter_markers("scenario"))
        if not markers and not baseline:
            raise pytest.UsageError(f"missing scenario attribution: {item.nodeid}")
        seed = getattr(item, "callspec", None)
        seed = seed.params.get("seed", 0) if seed else 0
        for marker in markers:
            row, case = marker.args
            if row not in CASES or case not in CASES[row]:
                raise pytest.UsageError(f"invalid scenario case: {row}/{case}")
            selected.setdefault((row, case), set()).add(seed)
        keep.append(item)
        config.proof_nodes[item.nodeid] = {"cases": [list(m.args) for m in markers], "seed": seed}
    items[:] = keep
    config.hook.pytest_deselected(items=deselected)
    errors = coverage_errors(selected, stage=stage) if stage not in {"baseline-red", "development"} else []
    if not keep:
        errors.append("zero asserting tests selected")
    if errors:
        config.proof_metadata["coverage_errors"] = errors
        summary = errors[:16] + ([f"... {len(errors) - 16} more gaps recorded in evidence"] if len(errors) > 16 else [])
        raise pytest.UsageError("incomplete failure proof:\n" + "\n".join(summary))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" or report.failed or report.skipped:
        record = item.config.proof_records.setdefault(item.nodeid, {})
        record[report.when] = report.outcome
        if report.skipped:
            item.config.proof_metadata["invalid_skip"] = True


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    destination = config.getoption("--proof-evidence")
    if not destination:
        return
    if config.proof_metadata.get("invalid_skip"):
        session.exitstatus = 1
    if config.getoption("--proof-stage") == "development":
        config.proof_nodes = {item.nodeid: config.proof_nodes[item.nodeid] for item in session.items}
    for nodeid in config.proof_nodes:
        record = config.proof_records.setdefault(nodeid, {})
        if record.get("call") != "passed":
            session.exitstatus = int(session.exitstatus) or 1
        if record.get("call") == "passed" and "facts" not in record:
            record["missing_evidence"] = True
            session.exitstatus = 1
    started_wall, started_monotonic = getattr(config, "proof_started", (None, None))
    if started_wall is not None:
        wall = time.time() - started_wall
        monotonic = time.monotonic() - started_monotonic
        config.proof_metadata["host_suspension"] = {
            "wall_seconds": round(wall, 3), "monotonic_seconds": round(monotonic, 3),
            "divergence_seconds": round(wall - monotonic, 3),
            "suspended": (wall - monotonic) > host_clock.SUSPENSION_THRESHOLD}
    manifest = {"stage": config.getoption("--proof-stage"),
                "delivery_complete": False, "exit_code": int(session.exitstatus),
                "metadata": config.proof_metadata,
                "selected": config.proof_nodes, "results": config.proof_records}
    Path(destination).write_text(json.dumps(manifest, indent=2) + "\n")


@pytest.fixture(scope="session")
def postgres(request):
    database = DisposablePostgres().start()
    # Envelope timestamps are stamped from this clock, not the host's: admission
    # evaluates requested_at against the database, so host/containers skew is a
    # harness variable that has to be measured away rather than given margin.
    clock = host_clock.use_database_clock(database)
    request.config.proof_metadata["database"] = database.metadata
    request.config.proof_metadata["database_clock"] = clock.facts()
    try:
        yield database
    finally:
        # Re-read after the run so the manifest carries the final measurement and
        # suspension counts, which is what makes a skew failure diagnosable.
        request.config.proof_metadata["database_clock"] = clock.facts()
        database.close()


@pytest.fixture(scope="session")
def ledger_database(postgres):
    from uuid import uuid4
    from execution_runtime.services.execution_migration import migrate
    postgres.epoch = str(uuid4())
    migrate(postgres.dsn, postgres.epoch)
    with postgres.connect() as conn:
        conn.execute("UPDATE execution_protocol_state SET admission_enabled=true")
    return postgres


@pytest.fixture
def empty_database(postgres):
    """Fresh catalog inside this harness's owned container, never a shared DB."""
    from types import SimpleNamespace
    from uuid import uuid4
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    name = "case_" + uuid4().hex
    dsn = make_conninfo(postgres.dsn, dbname=name)
    with postgres.connect() as admin:
        admin.autocommit = True
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    database = SimpleNamespace(dsn=dsn, epoch=str(uuid4()), name=name,
                               connect=lambda: psycopg.connect(dsn, options="-c statement_timeout=2000 -c lock_timeout=2000"))
    try:
        yield database
    finally:
        with postgres.connect() as admin:
            admin.autocommit = True
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def evidence(request):
    def write(**facts):
        # Only test-authored, bounded, safe facts. No exception/result/request dump.
        allowed = {"gateway_attempts", "target_accepted", "target_effects", "claim_count",
                   "observer_pid", "worker_pids", "barriers", "negative_detected", "mode",
                   "release_count", "asserted", "original_request_id", "replay_request_id"}
        assert set(facts) <= allowed
        assert len(json.dumps(facts)) <= 8192
        request.config.proof_records.setdefault(request.node.nodeid, {})["facts"] = facts
    return write


@pytest.fixture
def services(tmp_path):
    children, gates = [], []
    token = secrets.token_hex(24)

    class Services:
        def barrier(self, *armed, **kwargs):
            barrier = Barriers.create(*armed, **kwargs)
            gates.append(barrier)
            return barrier

        def http(self, *, upstream=None, fault="none", barrier=None, auth=None, report=None, audit_status=None,
                 canaries=(), malformed_body=None):
            path = tmp_path / f"counter-{len(children)}.sqlite"
            service = ProcessService(launch_http, str(path), auth or token,
                                     barrier or self.barrier(), upstream, fault, report, audit_status,
                                     canaries, malformed_body)
            service.counter_path = path
            children.append(service)
            return service

        def worker(self, *, gateway, database, hooks=None, connection_factory=None, minimization=None, **settings):
            env = {"EXECUTION_HANDOFF_TOKEN": token, "EXECUTION_SIGNING_KEY": token,
                   "EXECUTION_STATE_STORE_BACKEND": "postgres", "EXECUTION_STATE_DB_URL": database.dsn,
                   "TOOL_GATEWAY_URL": gateway.url,
                   "EXECUTION_ADMISSION_EPOCH": getattr(database, "epoch", ""),
                   "EXECUTION_ADMISSION_ENABLED": "true" if hasattr(database, "epoch") else "false",
                   **settings}
            service = ProcessService(launch_worker, env, hooks, connection_factory, minimization)
            children.append(service)
            return service

        def facts(self, gateway, target):
            g, t = counts(gateway.counter_path), counts(target.counter_path)
            return {"gateway_attempts": g["attempt"], "target_accepted": t["accepted"],
                    "target_effects": t["effect"]}

    result = Services()
    result.token = token
    try:
        yield result
    finally:
        for gate in gates:
            gate.release_all()
        for child in reversed(children):
            child.close()
        for gate in gates:
            gate.close()
