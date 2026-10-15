"""Self-healing mission scheduler tests (Agent 1, Round 2 sprint).

Run from round2/: pytest tests/test_scheduler.py -q
Covers propose_reschedule + append-only audit log in crew/logistics.py.
"""
import csv
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from crew import logistics  # noqa: E402

HEADER = ["log_id", "crew_id", "start", "end", "job"]


def sched_path(tmp_path, name="schedule.csv"):
    return str(tmp_path / name)


def audit_path(sched):
    return os.path.join(os.path.dirname(os.path.abspath(sched)), "state",
                        "schedule_audit.jsonl")


def read_audit(sched):
    p = audit_path(sched)
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def file_hash(path):
    if not os.path.exists(path):
        return None
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def row(lid, crew="C-PWR", start="2187-04-15T08:30:00+00:00",
        end="2187-04-15T10:30:00+00:00", job="inspect", prio=None):
    r = {"log_id": lid, "crew_id": crew, "start": start, "end": end, "job": job}
    if prio is not None:
        r["_priority"] = prio
    return r


# 1. critical preempts lower: proposal valid + full-schedule audit clean.
def test_critical_preempts_lower():
    rows = [row("A", start="2187-04-15T08:30:00+00:00",
                end="2187-04-15T10:30:00+00:00", prio="low")]
    booking = row("B", start="2187-04-15T09:30:00+00:00",
                  end="2187-04-15T11:30:00+00:00", prio="critical")
    snapshot = [dict(r) for r in rows]
    out = logistics.propose_reschedule(rows, booking, "critical")
    assert out["escalate"] is False, out
    prop = out["proposal"]
    assert prop and prop["move_log_id"] == "A", out
    for k in ("move_log_id", "old_start", "old_end", "new_start", "new_end", "reason"):
        assert k in prop, prop
    assert prop["old_start"] == "2187-04-15T08:30:00+00:00"
    # pure: input rows untouched, nothing committed
    assert rows == snapshot
    # apply proposal manually -> entire schedule audits clean
    moved = {"log_id": "A", "crew_id": "C-PWR", "start": prop["new_start"],
             "end": prop["new_end"], "job": "inspect"}
    resulting = [moved, {c: booking[c] for c in HEADER}]
    assert logistics.audit(resulting) == []
    # moved slot must start later in 30-min steps, same duration (2h)
    from datetime import datetime
    assert (datetime.fromisoformat(prop["new_start"])
            - datetime.fromisoformat(prop["old_start"])).total_seconds() % 1800 == 0
    assert (datetime.fromisoformat(prop["new_end"])
            - datetime.fromisoformat(prop["new_start"])).total_seconds() == 7200
    # priority via booking dict fallback (no explicit arg)
    out2 = logistics.propose_reschedule([row("A", prio="low")], row("B", prio="critical"))
    assert out2["proposal"] is not None and out2["escalate"] is False


def test_equal_or_higher_priority_escalates():
    rows = [row("A", prio="high")]
    for incoming in ("high", "medium", "low"):
        out = logistics.propose_reschedule(rows, row("B", prio=incoming), incoming)
        assert out["proposal"] is None and out["escalate"] is True, (incoming, out)
    # unknown existing priority -> escalate (cannot prove lower)
    out = logistics.propose_reschedule([row("A")], row("B", prio="critical"), "critical")
    assert out["proposal"] is None and out["escalate"] is True
    # unknown incoming priority -> escalate
    out = logistics.propose_reschedule([row("A", prio="low")], row("B"), None)
    assert out["proposal"] is None and out["escalate"] is True


# 2. overlap rejected + file byte-identical + audit entry.
def test_overlap_rejected_and_file_unchanged(tmp_path):
    sched = sched_path(tmp_path)
    ok, _ = logistics.append_booking(sched, row("A", prio="low"), ["C-PWR"])
    assert ok
    before = file_hash(sched)
    ok2, reason = logistics.append_booking(
        sched, row("B", start="2187-04-15T09:30:00+00:00",
                   end="2187-04-15T11:30:00+00:00"), ["C-PWR"])
    assert ok2 is False and "overlap" in reason
    assert file_hash(sched) == before
    evs = read_audit(sched)
    assert len(evs) == 2
    assert evs[-1]["result"] == "rejected" and "overlap" in evs[-1]["reason"]


# 3. rollback / no-slot: escalate + file unchanged hash.
def test_no_slot_escalates_and_file_unchanged(tmp_path):
    sched = sched_path(tmp_path)
    # Victim A (low) 08:00-10:00 + wall C 10:00-18:00 blocks every +30min
    # relocation of A given incoming B (critical) 09:00-09:30 (overlaps A only).
    assert logistics.append_booking(
        sched, row("A", start="2187-04-15T08:00:00+00:00",
                   end="2187-04-15T10:00:00+00:00"), ["C-PWR"])[0]
    assert logistics.append_booking(
        sched, row("C", start="2187-04-15T10:00:00+00:00",
                   end="2187-04-15T18:00:00+00:00"), ["C-PWR"])[0]
    rows = [dict(r, _priority=p) for r, p in
            zip(logistics.read_schedule(sched), ("low", "high"))]
    booking = row("B", start="2187-04-15T09:00:00+00:00",
                  end="2187-04-15T09:30:00+00:00", prio="critical")
    out = logistics.propose_reschedule(rows, booking, "critical")
    assert out["proposal"] is None and out["escalate"] is True, out
    assert "8x30min" in out["reason"]
    before = file_hash(sched)
    ok, reason = logistics.append_booking(sched, booking, ["C-PWR"])
    assert ok is False and "overlap" in reason  # rejected, never half-written
    assert file_hash(sched) == before
    # validation failures also leave the file byte-identical
    ok, _ = logistics.append_booking(
        sched, row("D", start="bad", end="worse"), ["C-PWR"])
    assert ok is False
    assert file_hash(sched) == before


# 4. audit-log entries carry the exact contract fields.
def test_audit_log_fields(tmp_path):
    sched = sched_path(tmp_path)
    logistics.append_booking(sched, row("A", prio="critical"), ["C-PWR"])
    logistics.append_booking(sched, row("B", start="2187-04-15T09:00:00+00:00",
                                        end="2187-04-15T11:00:00+00:00"), ["C-PWR"])
    evs = read_audit(sched)
    assert len(evs) == 2
    for ev in evs:
        assert set(ev.keys()) == {"ts", "log_id", "action", "previous",
                                  "proposed", "reason", "result"}, ev
        assert ev["action"] == "append"
        assert ev["result"] in ("appended", "rejected")
        assert set(ev["proposed"].keys()) == set(HEADER)  # _priority never stored
        assert "_priority" not in ev["proposed"]
        from datetime import datetime
        datetime.fromisoformat(ev["ts"])  # parseable timestamp
    assert evs[0]["log_id"] == "A" and evs[0]["result"] == "appended"
    assert evs[0]["previous"] is None  # no prior row on first append
    assert evs[1]["log_id"] == "B" and evs[1]["result"] == "rejected"
    # CSV keeps the exact header and no _priority column
    with open(sched, newline="") as f:
        rdr = csv.DictReader(f)
        assert rdr.fieldnames == HEADER
        content = open(sched).read()
        assert "_priority" not in content


# 5. idempotent re-append: duplicate leaves file unchanged, still audited.
def test_idempotent_reappend(tmp_path):
    sched = sched_path(tmp_path)
    ok, _ = logistics.append_booking(sched, row("A"), ["C-PWR"])
    assert ok
    h1 = file_hash(sched)
    ok2, reason = logistics.append_booking(sched, row("A"), ["C-PWR"])
    assert ok2 is False and "duplicate" in reason
    assert file_hash(sched) == h1
    rows = logistics.read_schedule(sched)
    assert len(rows) == 1
    evs = read_audit(sched)
    assert len(evs) == 2 and evs[1]["result"] == "rejected"
    assert evs[1]["previous"] is not None  # duplicate links to prior row
    assert evs[1]["previous"]["log_id"] == "A"
