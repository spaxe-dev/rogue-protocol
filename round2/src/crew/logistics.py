"""Logistics Officer: schedule validation + atomic append + audit tool."""
import csv
import json
import os
from datetime import datetime, timedelta, timezone

from filelock import FileLock

HEADER = ["log_id", "crew_id", "start", "end", "job"]

PRIORITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}

AUDIT_ACTIONS = ("append",)

# Number of 30-minute forward shifts tried when relocating a preempted row.
RESCHEDULE_MAX_SHIFTS = 8
RESCHEDULE_SHIFT = timedelta(minutes=30)


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


def _rank(priority):
    """Map a priority string to its rank (higher = more urgent). None if unknown."""
    if priority is None:
        return None
    return PRIORITY_RANK.get(str(priority).strip().lower())


def _strip(row):
    """Return the HEADER-only projection of a booking/row (drops _priority etc.)."""
    return {c: row.get(c, "") for c in HEADER}


def _overlaps(s1, e1, s2, e2):
    return not (s1 >= e2 or e1 <= s2)


def _audit_log_path(schedule_path):
    state_dir = os.path.join(os.path.dirname(os.path.abspath(schedule_path)), "state")
    return os.path.join(state_dir, "schedule_audit.jsonl")


def _write_schedule_audit(schedule_path, event):
    """Append-only audit event. Never raises (booking outcome takes precedence)."""
    try:
        path = _audit_log_path(schedule_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass


def _audit_event(log_id, previous, proposed, reason, result):
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "log_id": str(log_id),
        "action": "append",
        "previous": previous,
        "proposed": proposed,
        "reason": str(reason),
        "result": str(result),
    }


def propose_reschedule(rows, booking, priority=None):
    """Propose moving a lower-priority row to fit an incoming booking.

    Pure function: never touches the filesystem, never commits anything.

    - ``rows``: existing schedule rows (each may carry ``_priority``).
    - ``booking``: proposed row; may carry ``_priority`` (never written to CSV).
    - ``priority``: incoming urgency string; falls back to ``booking["_priority"]``.

    Returns ``{"proposal": {...}|None, "escalate": bool, "reason": str}`` where a
    proposal is ``{move_log_id, old_start, old_end, new_start, new_end, reason}``.
    The entire resulting schedule (existing minus victim plus victim-moved plus
    incoming booking) is validated with :func:`audit` before a proposal is
    returned. Escalates when there is no conflict-free slot within
    8x30min forward shifts, when the conflict is with equal/higher (or unknown)
    priority, or on malformed input.
    """
    incoming_prio = priority if priority is not None else booking.get("_priority")
    rank_new = _rank(incoming_prio)
    if rank_new is None:
        return {"proposal": None, "escalate": True,
                "reason": "unknown incoming priority %r: cannot preempt" % (incoming_prio,)}
    try:
        b_start = _parse(booking["start"])
        b_end = _parse(booking["end"])
    except Exception:
        return {"proposal": None, "escalate": True,
                "reason": "bad datetime in proposed booking"}
    if not (b_end > b_start):
        return {"proposal": None, "escalate": True, "reason": "end<=start in proposed booking"}
    crew = booking.get("crew_id")
    if not str(crew or "").strip():
        return {"proposal": None, "escalate": True, "reason": "empty crew_id in proposed booking"}

    conflicts = []
    for r in rows:
        if r.get("crew_id") != crew:
            continue
        try:
            if _overlaps(b_start, b_end, _parse(r["start"]), _parse(r["end"])):
                conflicts.append(r)
        except Exception:
            return {"proposal": None, "escalate": True,
                    "reason": "bad datetime in existing row %s" % r.get("log_id")}
    if not conflicts:
        return {"proposal": None, "escalate": False,
                "reason": "no conflict: booking fits current schedule"}
    # Never preempt equal/higher (or unknown) priority.
    for r in conflicts:
        er = _rank(r.get("_priority"))
        if er is None:
            return {"proposal": None, "escalate": True,
                    "reason": "conflict with %s of unknown priority: escalate" % r.get("log_id")}
        if er >= rank_new:
            return {"proposal": None, "escalate": True,
                    "reason": "conflict with equal/higher priority %s (%s>=%s): escalate"
                    % (r.get("log_id"), r.get("_priority"), incoming_prio)}
    if len(conflicts) != 1:
        return {"proposal": None, "escalate": True,
                "reason": "multiple lower-priority conflicts (%d): escalate"
                % len(conflicts)}
    victim = conflicts[0]
    try:
        v_start = _parse(victim["start"])
        v_end = _parse(victim["end"])
    except Exception:
        return {"proposal": None, "escalate": True,
                "reason": "bad datetime in row %s" % victim.get("log_id")}
    duration = v_end - v_start
    if duration.total_seconds() <= 0:
        return {"proposal": None, "escalate": True,
                "reason": "end<=start in row %s" % victim.get("log_id")}
    others = [r for r in rows if r.get("log_id") != victim.get("log_id")]
    incoming_stripped = _strip(booking)
    for i in range(1, RESCHEDULE_MAX_SHIFTS + 1):
        ns = v_start + RESCHEDULE_SHIFT * i
        ne = ns + duration
        clash = False
        for r in [incoming_stripped] + [_strip(o) for o in others]:
            if r.get("crew_id") != crew:
                continue
            try:
                if _overlaps(ns, ne, _parse(r["start"]), _parse(r["end"])):
                    clash = True
                    break
            except Exception:
                clash = True
                break
        if clash:
            continue
        moved = dict(_strip(victim))
        moved["start"] = ns.isoformat()
        moved["end"] = ne.isoformat()
        resulting = [_strip(o) for o in others] + [moved, dict(incoming_stripped)]
        if not audit(resulting):
            return {"proposal": {
                        "move_log_id": victim.get("log_id"),
                        "old_start": victim.get("start"),
                        "old_end": victim.get("end"),
                        "new_start": ns.isoformat(),
                        "new_end": ne.isoformat(),
                        "reason": "preempt %s (%s) for %s (%s)"
                        % (victim.get("log_id"), victim.get("_priority"),
                           booking.get("log_id"), incoming_prio),
                    },
                    "escalate": False,
                    "reason": "safe slot found at +%dmin" % (30 * i)}
    return {"proposal": None, "escalate": True,
            "reason": "no safe slot within 8x30min shifts for %s: escalate"
            % victim.get("log_id")}


def append_booking(path, booking, crew_roster_ids=None):
    """Idempotent atomic append. Returns (appended: bool, reason).

    Every call (success and each rejection) appends an audit event
    ``{ts, log_id, action, previous, proposed, reason, result}`` to
    ``<dirname(schedule_path)>/state/schedule_audit.jsonl``. ``_priority``
    and any other non-HEADER keys in ``booking`` are ignored for the CSV
    (never written) but the HEADER-only projection is stored as ``proposed``.
    Failed ops never modify ``schedule.csv``.
    """
    log_id = booking.get("log_id", "")
    proposed = _strip(booking)

    def _log(previous, reason, result):
        _write_schedule_audit(path, _audit_event(log_id, previous, proposed, reason, result))

    if not all(str(booking.get(c, "")).strip() for c in HEADER):
        _log(None, "empty required field", "rejected")
        return False, "empty required field"
    try:
        if not (_parse(booking["end"]) > _parse(booking["start"])):
            _log(None, "end<=start", "rejected")
            return False, "end<=start"
    except Exception:
        _log(None, "bad datetime", "rejected")
        return False, "bad datetime"
    if crew_roster_ids and booking["crew_id"] not in crew_roster_ids:
        _log(None, "unknown crew %s" % booking["crew_id"], "rejected")
        return False, "unknown crew %s" % booking["crew_id"]
    lock = FileLock(path + ".lock")
    with lock:
        rows = read_schedule(path)
        previous = next((dict(_strip(r)) for r in rows if r["log_id"] == booking["log_id"]), None)
        if any(r["log_id"] == booking["log_id"] for r in rows):
            _log(previous, "duplicate log_id", "rejected")
            return False, "duplicate log_id"
        for r in rows:
            if r["crew_id"] != booking["crew_id"]:
                continue
            try:
                if not (_parse(booking["start"]) >= _parse(r["end"])
                        or _parse(booking["end"]) <= _parse(r["start"])):
                    _log(previous, "overlap with %s" % r["log_id"], "rejected")
                    return False, "overlap with %s" % r["log_id"]
            except Exception:
                _log(previous, "bad datetime in existing row", "rejected")
                return False, "bad datetime in existing row"
        new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=HEADER)
            if new:
                w.writeheader()
            w.writerow({c: booking[c] for c in HEADER})
    _log(previous, "appended", "appended")
    return True, "appended"
