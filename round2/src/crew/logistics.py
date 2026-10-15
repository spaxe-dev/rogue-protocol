"""Logistics Officer: schedule validation + atomic append + audit tool."""
import csv
import os
from datetime import datetime

from filelock import FileLock

HEADER = ["log_id", "crew_id", "start", "end", "job"]


def _parse(ts):
    return datetime.fromisoformat(ts)


def read_schedule(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        if r.fieldnames != HEADER:
            raise ValueError("schedule header must be %s, got %s" % (HEADER, r.fieldnames))
        return list(r)


def audit(rows):
    """Return list of problem strings. Overlap per crew, end<=start, empty fields."""
    problems = []
    for r in rows:
        if not all(str(r.get(c, "")).strip() for c in HEADER):
            problems.append("empty field in %s" % r.get("log_id"))
        try:
            if not (_parse(r["end"]) > _parse(r["start"])):
                problems.append("end<=start in %s" % r.get("log_id"))
        except Exception:
            problems.append("bad datetime in %s" % r.get("log_id"))
    by_crew = {}
    for r in rows:
        by_crew.setdefault(r["crew_id"], []).append(r)
    for crew, rs in by_crew.items():
        try:
            rs = sorted(rs, key=lambda r: _parse(r["start"]))
        except Exception:
            continue
        for a, b in zip(rs, rs[1:]):
            try:
                if _parse(b["start"]) < _parse(a["end"]):
                    problems.append("overlap %s: %s vs %s" % (crew, a["log_id"], b["log_id"]))
            except Exception:
                pass
    return problems


def schedule_audit_main(path):
    rows = read_schedule(path)
    problems = audit(rows)
    print("schedule_audit: %d rows, %d problems" % (len(rows), len(problems)))
    for p in problems:
        print("  !", p)
    return problems


def append_booking(path, booking, crew_roster_ids=None):
    """Idempotent atomic append. Returns (appended: bool, reason)."""
    if not all(str(booking.get(c, "")).strip() for c in HEADER):
        return False, "empty required field"
    try:
        if not (_parse(booking["end"]) > _parse(booking["start"])):
            return False, "end<=start"
    except Exception:
        return False, "bad datetime"
    if crew_roster_ids and booking["crew_id"] not in crew_roster_ids:
        return False, "unknown crew %s" % booking["crew_id"]
    lock = FileLock(path + ".lock")
    with lock:
        rows = read_schedule(path)
        if any(r["log_id"] == booking["log_id"] for r in rows):
            return False, "duplicate log_id"
        for r in rows:
            if r["crew_id"] != booking["crew_id"]:
                continue
            try:
                if not (_parse(booking["start"]) >= _parse(r["end"])
                        or _parse(booking["end"]) <= _parse(r["start"])):
                    return False, "overlap with %s" % r["log_id"]
            except Exception:
                return False, "bad datetime in existing row"
        new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=HEADER)
            if new:
                w.writeheader()
            w.writerow({c: booking[c] for c in HEADER})
    return True, "appended"
