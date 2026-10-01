"""Test-only preparation of immutable intents, independent of worker authority."""
from datetime import timedelta
from uuid import uuid4

from psycopg.types.json import Jsonb

from execution_runtime.services.execution_protocol import iso
from execution_runtime.services.execution_signing import canonical_digest, sign_envelope

from . import host_clock


def signed_request(key, epoch, **overrides):
    now = host_clock.now()
    value = {"protocol_version": 3, "execution_id": str(uuid4()), "confirm_id": str(uuid4()),
             "call_id": str(uuid4()), "run_id": str(uuid4()), "admission_epoch": epoch,
             "session_id": str(uuid4()), "owner_user_id": "test-owner", "decider_user_id": "test-decider",
             "approval_kind": "action", "tool_name": "test.increment", "args_digest": canonical_digest({}),
             # Admission compares requested_at against the disposable Postgres
             # clock (requested_at <= database_now), so `now` is host time
             # corrected by an offset measured against that same clock rather
             # than a bare host read: the skew is not budgetable. At rest it is
             # small and unstable — measured +3ms and +7ms with the container
             # ahead, where an earlier revision assumed a ~0.75s lag — and a 973s
             # host sleep drove it far past any static margin, which read as a
             # spurious request_not_yet_valid (see support/host_clock.py). The 30s
             # backdate is now drift-only headroom for the gap between signing
             # here and evaluating there; lifetime stays 630s, well under the
             # 900s protocol max.
             "requested_at": iso(now - timedelta(seconds=30)), "expires_at": iso(now + timedelta(seconds=600)),
             **overrides}
    value["signature"] = sign_envelope(value, key)
    return value


def register(database, envelope, request_id="harness-original"):
    # This helper does not claim or execute. Agent registration is tested at the
    # product seam separately; this is explicit setup for worker/storage proofs.
    with database.connect() as conn:
        conn.execute("INSERT INTO execution_runs (run_id,session_id,owner_user_id) VALUES (%s,%s,%s) "
                     "ON CONFLICT DO NOTHING", (envelope["run_id"], envelope["session_id"], envelope["owner_user_id"]))
        conn.execute("INSERT INTO execution_intents (execution_id,confirm_id,call_id,run_id,request_digest,"
                     "request_envelope,attempt_request_id,requested_at,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                     (envelope["execution_id"], envelope["confirm_id"], envelope["call_id"], envelope["run_id"],
                      canonical_digest(envelope), Jsonb(envelope), request_id, envelope["requested_at"], envelope["expires_at"]))
        conn.execute("INSERT INTO execution_observation_state(execution_id) VALUES (%s)", (envelope["execution_id"],))


def body(envelope, token):
    return {"request": envelope, "arguments": {}, "delegated_token": token}


def claim_count(database, execution_id):
    with database.connect() as conn:
        return conn.execute("SELECT count(*) FROM execution_dispatch_claims WHERE execution_id=%s",
                            (execution_id,)).fetchone()[0]
