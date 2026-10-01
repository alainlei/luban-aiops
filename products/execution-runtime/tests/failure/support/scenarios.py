"""Required parameter coverage, independent of collected test names."""
from __future__ import annotations

# This register is a gate, not evidence. Cases enter evidence only after actual
# asserting nodes run. F-35 belongs to separately authorized live acceptance.
CASES = {
    "F-01": ("action",),
    "F-02": ("auth_missing", "auth_invalid", "signing_missing", "schema", "signature",
             "args_digest", "gateway_missing", "credential_missing", "provenance"),
    "F-03": ("same_process", "two_processes"),
    "F-04": ("tool", "args", "owner", "decider", "provenance", "expiry", "reminted_id"),
    "F-05": ("cache_eviction", "restart"),
    "F-06": ("startup", "before_claim", "backend", "schema", "constraint"),
    "F-07": ("commit_wrapper", "commit_wire", "rollback"),
    "F-08": ("kill_B1",),
    "F-09": ("resume_original", "explicit_stop"),
    "F-10": ("kill_B2", "kill_B3"),
    "F-11": ("lost_gateway_reply",),
    "F-12": ("rollback", "commit_wrapper", "commit_wire", "kill_B4"),
    "F-13": ("lost_handoff_reply", "agent_death"),
    "F-14": ("late_worker_result",),
    "F-15": ("timeout", "disconnect_read", "disconnect_write", "malformed", "truncated",
             "shape", "receipt_signature", "observation_signature", "execution_id", "run_id",
             "epoch", "request_digest", "request_id", "tool", "status", "outcome_digest"),
    "F-16": ("http_error", "partial_effect", "upstream_500"),
    "F-17": ("identical", "same_id_conflict", "different_final", "overflow"),
    "F-18": ("store_outage", "read_tool_available"),
    "F-19": ("action_denied", "action_expired", "flow_denied", "flow_expired", "flow_stale"),
    "F-20": ("duplicate_flow", "unknown_next_write", "new_card_bypass"),
    "F-21": ("stale_allowed", "stale_flow", "failed_stop", "unclaimed_intent", "missing_run"),
    "F-22": ("remote_operations", "multiple_claims", "send_stop_race"),
    "F-23": ("original_success", "unknown", "receipt_failure", "replay", "late", "release_race"),
    "F-24": ("owner", "foreign", "inbox", "forged_id", "paging", "stale_poll"),
    "F-25": ("correlation", "audit_outage"),
    "F-26": ("summary", "incident", "authoring", "foreign", "published_snapshot"),
    "F-27": ("args", "result", "malformed", "exception", "url", "oversize"),
    "F-28": ("before_expiry", "at_expiry", "future", "lifetime", "legacy", "version", "epoch"),
    "F-29": ("session_delete", "presentation_sweep", "cache_eviction"),
    "F-30": ("retention_boundary", "expired_replay", "remint"),
    "F-31": ("success", "timeout", "open", "interrupted"),
    "F-32": ("disabled_cutover", "overlap", "drain", "abrupt"),
    "F-33": ("downgrade", "restore", "epoch_mismatch"),
    "F-34": ("store_failure", "duplicate_storm", "conflict", "unknown_age", "receipt_failure"),
    "F-35": ("normal", "denied_expired", "interrupted", "owner_reload", "held_secret"),
    "F-36": ("prerequisites", "barriers", "process_death", "independent_counters",
             "commit_wrapper", "commit_wire", "http_faults", "coverage_gate",
             "negative_duplicate", "negative_takeover", "negative_no_effect", "negative_release",
             "clock_reconciliation"),
}
REPEATED = {"F-03", "F-07", "F-08", "F-09", "F-12", "F-14", "F-20", "F-22", "F-32"}


def coverage_errors(selected, *, stage):
    if not selected:
        return ["zero asserting tests selected"]
    required = {"F-36"} if stage == "harness" else set(CASES) - {"F-35"}
    errors = []
    for scenario in sorted(required):
        for case in CASES[scenario]:
            seeds = selected.get((scenario, case), set())
            minimum = 20 if scenario in REPEATED else 1
            if len(seeds) < minimum:
                errors.append(f"{scenario}/{case}: {len(seeds)}/{minimum} schedules selected")
    return errors
