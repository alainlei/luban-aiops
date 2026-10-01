"""S0 proves the measuring apparatus, not the future execution protocol."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
import pytest

from execution_runtime.services.execution_signing import canonical_digest, sign_envelope
from support import host_clock
from support.barriers import CONTEXT, NAMES
from support.http_services import FAULTS, counts
from support.infrastructure import ROOT, DisposablePostgres, PrerequisiteError, prerequisites
from support.ledger import signed_request
from support.negative_controls import (
    assert_honest_no_effect, assert_no_replay_release, assert_single_dispatch, bypass_claim,
)
from support.postgres_faults import CommitAckProxy, CommitFaultConnection, independent_count
from support.scenarios import CASES, REPEATED, coverage_errors


def post(url, token, body=None, path="/api/v2/tools/invoke", request_id="harness-original"):
    with httpx.Client(trust_env=False, timeout=20, follow_redirects=False) as client:
        headers = {"x-request-id": request_id}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return client.post(url + path, headers=headers, json=body or {
                               "tool_name": "test.increment", "parameters": {},
                               "request_id": request_id})


def envelope(token):
    request = {"execution_id": str(uuid4()), "confirm_id": str(uuid4()),
               "call_id": str(uuid4()), "session_id": str(uuid4()),
               "owner_user_id": "test-owner", "decider_user_id": "test-decider",
               "tool_name": "test.increment", "args_digest": canonical_digest({}),
               "approval_kind": "action",
               "requested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    request["signature"] = sign_envelope(request, token)
    return {"request": request, "arguments": {}, "delegated_token": token}


def table(database):
    name = "harness_" + uuid4().hex
    with database.connect() as conn:
        conn.execute(sql.SQL("CREATE TABLE {} (id integer PRIMARY KEY)").format(sql.Identifier(name)))
    return name


def hit_barrier(barrier, name):
    barrier.hit(name)


def release_probe(unsafe=False):
    script = Path(__file__).parent / "support/agent_release_probe.py"
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "TMPDIR"}}
    result = subprocess.run([str(ROOT / "products/agent-platform/.venv/bin/python"),
                             str(script), *(["--unsafe"] if unsafe else [])],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, "agent release probe failed (no raw output retained)"
    return json.loads(result.stdout)["release_count"]


@pytest.mark.scenario("F-36", "prerequisites")
def test_missing_prerequisites_fail_without_fallback(monkeypatch, evidence):
    monkeypatch.setattr("support.infrastructure.shutil.which", lambda _: None)
    with pytest.raises(PrerequisiteError, match="install docker"):
        prerequisites()
    evidence(asserted="missing executable fails before any resource starts")


@pytest.mark.scenario("F-36", "prerequisites")
def test_cleanup_refuses_wrong_owner(monkeypatch, evidence):
    database = DisposablePostgres()
    database.started = True
    invoked = []

    def fake_command(args, **kwargs):
        invoked.append(args)
        return "foreign-container" if args[1] == "ps" else "different-owner"

    monkeypatch.setattr("support.infrastructure.command", fake_command)
    with pytest.raises(PrerequisiteError, match="unowned"):
        database.close()
    assert not any("down" in args for args in invoked)
    evidence(asserted="unowned resource blocks teardown before compose down")


@pytest.mark.scenario("F-36", "independent_counters")
def test_missing_counter_is_not_zero(tmp_path, evidence):
    import sqlite3
    with pytest.raises(sqlite3.OperationalError):
        counts(tmp_path / "missing.sqlite")
    evidence(asserted="counter collection failure is not a zero-effect observation")


@pytest.mark.scenario("F-36", "coverage_gate")
def test_missing_scenarios_parameters_and_schedules_fail(evidence):
    assert coverage_errors({}, stage="campaign") == ["zero asserting tests selected"]
    selected = {(row, case): set(range(20 if row in REPEATED else 1))
                for row, cases in CASES.items() if row != "F-35" for case in cases}
    assert coverage_errors(selected, stage="campaign") == []
    selected[("F-03", "two_processes")].remove(19)
    assert coverage_errors(selected, stage="campaign") == ["F-03/two_processes: 19/20 schedules selected"]
    del selected[("F-15", "receipt_signature")]
    assert any("receipt_signature" in error for error in coverage_errors(selected, stage="campaign"))
    evidence(asserted="zero tests, missing parameter, and fewer than twenty schedules fail")


@pytest.mark.scenario("F-36", "clock_reconciliation")
def test_envelope_timestamps_follow_the_database_clock(ledger_database, services, monkeypatch, evidence):
    """Admission reads the database clock, so envelopes must be stamped from it.

    A host sleep leaves the container clock behind the host's by more than any
    static margin, which once read as a spurious ``request_not_yet_valid`` in
    legs that assert nothing about time. This is the apparatus invariant that
    keeps such a failure from being attributed to the protocol.
    """
    db = ledger_database
    with db.connect() as conn:
        database_now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    envelope = signed_request(services.token, db.epoch)

    def stamped(field):
        return datetime.fromisoformat(envelope[field].replace("Z", "+00:00"))

    # The inequality admission enforces, and the lifetime bound the protocol does.
    assert stamped("requested_at") <= database_now < stamped("expires_at")
    assert stamped("expires_at") - stamped("requested_at") <= timedelta(seconds=900)

    assert host_clock.installed() is not None, "no database clock registered for stamping"
    # The inequality above would also survive a lucky static backdate, so prove the
    # mechanism: a database clock skewed far outside any margin must carry
    # requested_at with it. monkeypatch restores the session-wide clock after.
    skewed = host_clock.DatabaseClock(lambda: time.time() + 600.0)
    monkeypatch.setattr(host_clock, "_installed", [skewed])
    moved = signed_request(services.token, db.epoch)
    offset = datetime.fromisoformat(moved["requested_at"].replace("Z", "+00:00")) - database_now
    assert abs(offset.total_seconds() - 570) < 5, "requested_at ignored the database clock"

    # A suspension is a wall/monotonic divergence. A threshold below zero fires the
    # detector on every read, proving it re-measures rather than reusing a stale
    # offset, without waiting for an actual host sleep.
    probe = host_clock.DatabaseClock(lambda: time.time(), threshold=-1.0)
    before = probe.facts()
    probe.now()
    probe.now()
    after = probe.facts()
    assert after["suspensions"] >= 1
    assert after["measurements"] > before["measurements"]
    evidence(mode="clock_reconciliation",
             asserted="window straddles the DB clock, follows a skewed one, and re-measures on divergence")


@pytest.mark.scenario("F-36", "barriers")
@pytest.mark.parametrize("name", NAMES)
def test_acknowledged_process_barriers(services, name, evidence):
    gate = services.barrier(name)
    child = CONTEXT.Process(target=hit_barrier, args=(gate, name))
    child.start()
    try:
        acknowledgment = gate.wait(name)
        assert acknowledgment["pid"] == child.pid != os.getpid()
        assert child.is_alive()
        gate.release(name)
        child.join(timeout=5)
        assert child.exitcode == 0
        evidence(barriers=[name], worker_pids=[child.pid])
    finally:
        if child.is_alive():
            child.kill()
            child.join(timeout=5)
        child.close()


@pytest.mark.scenario("F-36", "commit_wrapper")
@pytest.mark.parametrize("mode,expected", [("ack_lost", 1), ("rollback", 0)])
def test_real_commit_and_rollback_are_distinguished(postgres, mode, expected, evidence):
    name = table(postgres)
    with postgres.connect() as connection:
        wrapped = CommitFaultConnection(connection, mode)
        wrapped.execute(sql.SQL("INSERT INTO {} VALUES (1)").format(sql.Identifier(name)))
        with pytest.raises(psycopg.OperationalError, match="commit uncertainty"):
            wrapped.commit()
    observed = independent_count(postgres.dsn, name)
    assert observed["count"] == expected
    assert observed["pid"] != os.getpid()
    evidence(mode=mode, claim_count=expected, observer_pid=observed["pid"])


@pytest.mark.scenario("F-36", "commit_wire")
def test_wire_proxy_drops_ack_after_real_commit(postgres, evidence):
    name = table(postgres)
    proxy = CommitAckProxy(postgres.dsn)
    try:
        connection = psycopg.connect(proxy.dsn)
        try:
            connection.execute(sql.SQL("INSERT INTO {} VALUES (1)").format(sql.Identifier(name)))
            proxy.armed.set()
            with pytest.raises(psycopg.OperationalError):
                connection.commit()
            assert proxy.dropped.wait(5), "proxy did not observe COMMIT completion"
        finally:
            connection.close()
        observed = independent_count(postgres.dsn, name)
        assert observed["count"] == 1
        evidence(mode="wire_ack_lost", claim_count=1, observer_pid=observed["pid"])
    finally:
        proxy.close()


@pytest.mark.scenario("F-36", "independent_counters")
def test_target_is_non_idempotent_and_gateway_is_independent(services, evidence):
    gate = services.barrier("B2")
    target = services.http()
    gateway = services.http(upstream=target.url, barrier=gate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(post, gateway.url, services.token)
        gate.wait("B2")
        assert services.facts(gateway, target) == {
            "gateway_attempts": 1, "target_accepted": 0, "target_effects": 0}
        gate.release("B2")
        assert first.result(timeout=10).status_code == 200
    assert post(gateway.url, services.token).status_code == 200
    facts = services.facts(gateway, target)
    assert facts == {"gateway_attempts": 2, "target_accepted": 2, "target_effects": 2}
    operations = counts(target.counter_path)["operations"]
    assert len({op for kind, op in operations if kind == "effect"}) == 2
    evidence(**facts, barriers=["B2"])


@pytest.mark.scenario("F-36", "http_faults")
@pytest.mark.parametrize("leg", ["agent_worker", "worker_gateway"])
@pytest.mark.parametrize("fault", sorted(FAULTS - {"none"}))
def test_proxy_faults_never_retry(services, leg, fault, evidence):
    target = services.http()
    gate = services.barrier("B5") if fault == "delayed_headers" else services.barrier()
    inner = services.http(upstream=target.url,
                          fault=fault if leg == "worker_gateway" else "none",
                          barrier=gate if leg == "worker_gateway" else None)
    outer = services.http(upstream=inner.url,
                          fault=fault if leg == "agent_worker" else "none",
                          barrier=gate if leg == "agent_worker" else None)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(post, outer.url, services.token)
        if fault == "delayed_headers":
            gate.wait("B5")
            assert counts(target.counter_path)["effect"] == 1
            assert not result.done()
            gate.release("B5")
        if fault in {"drop_reply", "disconnect_read", "disconnect_write", "truncated"}:
            with pytest.raises(httpx.HTTPError):
                result.result(timeout=15)
        else:
            response = result.result(timeout=15)
            if fault == "malformed":
                with pytest.raises(ValueError):
                    response.json()
            elif fault == "http_error":
                assert response.status_code == 502
            else:
                assert response.status_code == 200
    expected = 0 if fault == "disconnect_write" else 1
    facts = services.facts(inner, target)
    assert facts == {"gateway_attempts": expected, "target_accepted": expected, "target_effects": expected}
    assert counts(outer.counter_path)["attempt"] == (0 if fault == "disconnect_write" and leg == "agent_worker" else 1)
    evidence(**facts, mode=f"{leg}:{fault}")


@pytest.mark.scenario("F-36", "process_death")
def test_actual_worker_kill_does_not_cancel_target(services, ledger_database, evidence):
    from support.ledger import signed_request, register, body
    postgres = ledger_database
    envelope_v3 = signed_request(services.token, postgres.epoch)
    register(postgres, envelope_v3)
    gate = services.barrier("B2")
    target = services.http()
    gateway = services.http(upstream=target.url, barrier=gate)
    worker = services.worker(gateway=gateway, database=postgres)
    original_pid = worker.pid
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(post, worker.url, services.token, body(envelope_v3, services.token),
                             "/api/v1/executions/handoff")
        gate.wait("B2")
        worker.kill()
        with pytest.raises(httpx.HTTPError):
            result.result(timeout=10)
        assert counts(target.counter_path)["effect"] == 0
        gate.release("B2")
    # Bounded independent observation after releasing the acknowledged B2 pause.
    deadline = time.monotonic() + 5
    while counts(target.counter_path)["effect"] == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert counts(target.counter_path)["effect"] == 1
    restarted = services.worker(gateway=gateway, database=postgres)
    assert restarted.pid != original_pid
    assert target.process.is_alive() and gateway.process.is_alive()
    evidence(**services.facts(gateway, target), worker_pids=[original_pid, restarted.pid], barriers=["B2"])


@pytest.mark.parametrize("mode", [
    pytest.param("bypass", marks=pytest.mark.scenario("F-36", "negative_duplicate")),
    pytest.param("takeover", marks=pytest.mark.scenario("F-36", "negative_takeover")),
])
def test_duplicate_and_takeover_negative_controls(services, postgres, mode, evidence):
    name = table(postgres)
    with postgres.connect() as conn:
        conn.execute(sql.SQL("INSERT INTO {} VALUES (1)").format(sql.Identifier(name)))
    target = services.http()
    gateway = services.http(upstream=target.url)
    sends = [CONTEXT.Event(), CONTEXT.Event()]
    ready = [CONTEXT.Event(), CONTEXT.Event()]
    children = [CONTEXT.Process(target=bypass_claim, args=(gateway.url, services.token, ready[i], sends[i]))
                for i in range(2)]
    try:
        for child in children:
            child.start()
        assert all(event.wait(10) for event in ready)
        assert independent_count(postgres.dsn, name)["count"] == 1
        if mode == "takeover":
            # Replacement sends while the original still owns its right and is
            # paused; resuming the original exposes the unsafe takeover.
            sends[1].set()
            children[1].join(timeout=15)
            assert children[1].exitcode == 0
        else:
            sends[1].set()
        sends[0].set()
        for child in children:
            child.join(timeout=15)
            assert child.exitcode == 0
        facts = services.facts(gateway, target)
        assert facts["target_effects"] == 2
        with pytest.raises(AssertionError, match="duplicate worker dispatch"):
            assert_single_dispatch(counts(gateway.counter_path), counts(target.counter_path))
        evidence(**facts, claim_count=1, mode=mode, negative_detected=True,
                 worker_pids=[child.pid for child in children])
    finally:
        for child in children:
            if child.is_alive():
                child.kill()
                child.join(timeout=5)
            child.close()


@pytest.mark.scenario("F-36", "negative_no_effect")
def test_lost_reply_false_no_effect_control(services, evidence):
    target = services.http()
    gateway = services.http(upstream=target.url, fault="drop_reply")
    with pytest.raises(httpx.HTTPError):
        post(gateway.url, services.token)
    with pytest.raises(AssertionError, match="false no-effect"):
        assert_honest_no_effect("not_dispatched", counts(target.counter_path))
    evidence(**services.facts(gateway, target), negative_detected=True)


@pytest.mark.scenario("F-36", "negative_release")
def test_replay_release_negative_control(evidence):
    releases = release_probe(unsafe=True)
    with pytest.raises(AssertionError, match="replay released"):
        assert_no_replay_release(releases)
    evidence(release_count=releases, negative_detected=True)


@pytest.mark.baseline_red
def test_baseline_two_actual_workers_violate_single_dispatch(services, postgres, evidence):
    target = services.http()
    gateway = services.http(upstream=target.url)
    workers = [services.worker(gateway=gateway, database=postgres) for _ in range(2)]
    assert workers[0].pid != workers[1].pid
    body = envelope(services.token)
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(post, worker.url, services.token, body,
                             "/api/v1/executions/handoff") for worker in workers]
        assert all(call.result(timeout=20).status_code == 200 for call in calls)
    evidence(**services.facts(gateway, target), worker_pids=[w.pid for w in workers])
    assert_single_dispatch(counts(gateway.counter_path), counts(target.counter_path))


@pytest.mark.baseline_red
def test_baseline_replayed_success_must_not_release(evidence):
    releases = release_probe()
    evidence(release_count=releases)
    assert_no_replay_release(releases)
