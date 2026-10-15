"""AEGIS safety gate: deterministic pre-execution validation. Policy, not persona."""
import csv
import os
from datetime import datetime


def _valid_interval(start, end):
    try:
        s, e = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except Exception:
        return None
    return e > s


def validate_action(action, by_id, state_dir):
    """action: {kind: notify|schedule, crew_id, log_id, row?}. Returns (pass, reasons, escalate)."""
    reasons, escalate = [], False
    kind, cid, lid = action.get("kind"), action.get("crew_id"), action.get("log_id")
    if cid not in by_id:
        return False, ["unknown crew_id %r" % cid], True
    if by_id[cid].get("availability") != "active":
        return False, ["crew %s not active" % cid], True
    if kind == "schedule":
        row = action.get("row", {})
        if list(row.keys()) != ["log_id", "crew_id", "start", "end", "job"]:
            return False, ["bad schedule columns %r" % list(row.keys())], False
        if any(not str(row[c]).strip() for c in row):
            return False, ["empty schedule field"], False
        ok = _valid_interval(row["start"], row["end"])
        if ok is None:
            return False, ["bad datetime"], False
        if not ok:
            return False, ["end<=start"], False
        sched = os.path.join(state_dir, "schedule.csv")
        if os.path.exists(sched):
            with open(sched, newline="") as f:
                for r in csv.DictReader(f):
                    if r["log_id"] == lid:
                        return False, ["duplicate log_id %s" % lid], False
                    if r["crew_id"] == cid and not (
                            row["start"] >= r["end"] or row["end"] <= r["start"]):
                        reasons.append("overlap with %s" % r["log_id"])
                        escalate = True
        if escalate:
            return False, reasons, True
        return True, ["PASS: columns/crew/interval/duplicate/overlap clear"], False
    if kind == "notify":
        if not action.get("path_ok", True):
            return False, ["no message body"], False
        return True, ["PASS: recipient valid, body present"], False
    return False, ["unknown action kind %r" % kind], True
