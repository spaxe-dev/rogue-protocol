"""Ack / escalation tracker tests (Agent 3). No sleeps: injectable now_iso."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ack import (  # noqa: E402
    assign_owner,
    acknowledge,
    sweep,
    engineer_brief,
    commander_brief,
    logistics_brief,
    mission_control_digest,
)

T0 = "2026-10-15T00:00:00+00:00"
T_LATE = "2026-10-15T00:10:00+00:00"  # 600s later


def _incident(log_id="L1"):
    return {
        "log_id": log_id,
        "predicted_module": "power",
        "proba": 0.91,
        "status": "auto",
        "verdict": 1,
        "routed_to": "C-PWR",
        "risk": {"urgency": "high", "score": 4},
        "findings": ["bus voltage below threshold", "relay chatter"],
        "neighbors": [{"log_id": "L0", "score": 0.9}],
        "schedule": {"state": "done", "row": "L1,C-PWR", "reason": "booked"},
        "repair": {"job": "inspect", "start": "t0", "end": "t1"},
    }


def _escalation_events(state_dir):
    path = os.path.join(state_dir, "state", "escalations.jsonl")
    if not os.path.exists(path):
        return []
    return [json.loads(line) for line in open(path) if line.strip()]


def test_acked_in_time_no_escalation(tmp_path):
    state = str(tmp_path)
    assign_owner(state, "L1", "C-PWR", timeout_s=300, now_iso=T0)
    acknowledge(state, "L1", by="C-PWR", now_iso=T0)
    fired = sweep(state, now_iso=T_LATE)  # past deadline, but already acked
    assert fired == []
    assert _escalation_events(state) == []


def test_timeout_fires_escalation_once(tmp_path):
    state = str(tmp_path)
    assign_owner(state, "L1", "C-PWR", timeout_s=60, now_iso=T0)
    fired = sweep(state, now_iso=T_LATE)
    assert len(fired) == 1
    ev = fired[0]
    assert ev == {
        "incident_id": "L1",
        "log_id": "L1",
        "type": "ack-timeout",
        "reason": ev["reason"],
        "ts": ev["ts"],
    }
    assert "C-PWR" in ev["reason"]
    assert _escalation_events(state) == fired  # file matches return

    email = os.path.join(state, "state", "escalation_L1.eml")
    assert os.path.exists(email)
    before = open(email).read()

    # Second sweep: single escalation event + single email file (no dupes).
    fired2 = sweep(state, now_iso=T_LATE)
    assert fired2 == []
    assert len(_escalation_events(state)) == 1
    assert open(email).read() == before


def test_sweep_with_notify_fn_called_once(tmp_path):
    state = str(tmp_path)
    assign_owner(state, "L1", "C-PWR", timeout_s=60, now_iso=T0)
    calls = []
    fired = sweep(state, now_iso=T_LATE, notify_fn=lambda ev: calls.append(ev) or "ok")
    assert len(fired) == 1 and len(calls) == 1
    assert calls[0]["type"] == "ack-timeout"
    assert not os.path.exists(os.path.join(state, "state", "escalation_L1.eml"))
    assert sweep(state, now_iso=T_LATE, notify_fn=calls.append) == []


def test_retry_idempotent(tmp_path):
    state = str(tmp_path)
    first = assign_owner(state, "L1", "C-PWR", timeout_s=300, now_iso=T0)
    second = assign_owner(state, "L1", "C-PWR", timeout_s=300, now_iso=T0)
    assert first == second  # retry does not reset the timer
    ack1 = acknowledge(state, "L1", by="C-PWR", now_iso=T0)
    ack2 = acknowledge(state, "L1", by="C-PWR", now_iso=T_LATE)
    assert ack1 == ack2 and ack2["ack_ts"] == ack1["ack_ts"]


def test_late_ack_recorded_not_lost(tmp_path):
    state = str(tmp_path)
    assign_owner(state, "L1", "C-PWR", timeout_s=60, now_iso=T0)
    assert len(sweep(state, now_iso=T_LATE)) == 1
    rec = acknowledge(state, "L1", by="C-PWR", now_iso=T_LATE)
    assert rec["status"] == "escalated"  # escalation stands
    assert rec["ack_ts"] is not None  # late ack still recorded
    assert len(_escalation_events(state)) == 1  # no duplicate event


def test_missing_credentials_pending_local(tmp_path):
    state = str(tmp_path)
    assign_owner(state, "L1", "C-PWR", timeout_s=60, now_iso=T0)
    sweep(state, now_iso=T_LATE, notify_fn=None)
    email = os.path.join(state, "state", "escalation_L1.eml")
    assert os.path.exists(email)
    text = open(email).read()
    assert "pending-local" in text
    assert "NOT DELIVERED" in text
    assert "successfully delivered" not in text.lower()
    assert "delivered to" not in text.lower()
    with open(os.path.join(state, "state", "acks", "L1.json")) as f:
        rec = json.load(f)
    assert rec["delivery"]["status"] == "pending-local"
    assert rec["status"] == "escalated"


def test_role_briefs_contain_required_fields():
    inc = _incident("L7")
    eng = engineer_brief(inc)
    cmd = commander_brief(inc)
    log = logistics_brief(inc)
    digest = mission_control_digest([inc, _incident("L8")])
    for brief in (eng, cmd, log):
        assert brief["subject"] and brief["body"]
        assert "L7" in brief["subject"] and "L7" in brief["body"]
    assert "power" in eng["body"] and "bus voltage" in eng["body"]
    assert "high" in eng["body"] and "L0" in eng["body"]
    assert "auto" in cmd["body"] and "high" in cmd["body"]
    assert "C-PWR" in cmd["body"] and "0.91" in cmd["body"]
    assert "C-PWR" in log["body"] and "done" in log["body"]
    assert "L7" in digest["body"] and "L8" in digest["body"]
    assert "2 unresolved" in digest["subject"]


def test_briefs_use_only_incident_fields():
    sparse = {"log_id": "LX"}
    for brief in (engineer_brief(sparse), commander_brief(sparse),
                  logistics_brief(sparse)):
        assert "LX" in brief["subject"]
    digest = mission_control_digest([])
    assert "0 unresolved" in digest["subject"]
