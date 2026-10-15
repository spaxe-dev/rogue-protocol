"""Chief Engineer: specialist resolution + diagnostic tool + repair proposal + tickets.

Resolution cascade: exact module map -> fuzzy skill match (rapidfuzz) ->
semantic (memory neighbors) -> generalist fallback. Never invents crew_id.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None

EVIDENCE_PATTERNS = [
    (r"reading outside nominal window", "reading out of nominal window"),
    (r"seal breach suspected", "possible seal breach — inspect seals"),
    (r"O2 partial pressure falling|oxygen", "O2 trend falling — check scrubber/flow"),
    (r"bus arbitration deadlock|heartbeat missing", "bus coordination fault — check nodes"),
    (r"queue overflow, packets dropped", "packet loss — inspect queue depth"),
    (r"dish actuator stalled", "actuator stalled — inspect drive"),
    (r"duplicate of earlier alert", "repeat of earlier alert — see recurrence"),
    (r"recovered after retry", "self-recovered — monitor, low action"),
    (r"scheduled calibration|self-test pattern|simulated drill", "routine/self-test signature"),
]

# Rough per-module nominal bands observed in training data (documented heuristic,
# not a safety limit): used only to flag out-of-band readings in diagnostics.
NOMINAL_HINTS = {"Lab-Power": (10.0, 14.0), "Life-Support": (18.0, 24.0)}


def load_roster(path):
    with open(path) as f:
        return json.load(f)["crew"]


def resolve_specialist(row, roster, neighbors=None):
    module = str(row.get("module", "unknown"))
    for c in roster:
        if module in c.get("modules", []):
            return c["crew_id"], "exact module map"
    msg = str(row.get("message", "")).lower()
    best, best_hit = None, ""
    for c in roster:
        for skill in c.get("skills", []):
            if skill and skill in msg:
                return c["crew_id"], "skill keyword '%s'" % skill
            if fuzz and skill:
                s = fuzz.partial_ratio(skill, msg)
                if s > 85 and (best is None or s > best[1]):
                    best, best_hit = (c["crew_id"], s), skill
    if best:
        return best[0], "fuzzy skill '%s'" % best_hit
    if neighbors:
        for n in neighbors:
            cm = n.get("module")
            for c in roster:
                if cm in c.get("modules", []):
                    return c["crew_id"], "neighbor incident %s module" % n.get("log_id")
    return "C-GEN", "fallback generalist"


def diagnose(row, proba):
    """Custom diagnostic tool: evidence-backed findings from log fields only."""
    msg = str(row.get("message", ""))
    findings = []
    for pat, meaning in EVIDENCE_PATTERNS:
        if re.search(pat, msg, re.IGNORECASE):
            findings.append(meaning)
    try:
        reading = float(row.get("reading", float("nan")))
    except (TypeError, ValueError):
        reading = float("nan")
    band = NOMINAL_HINTS.get(str(row.get("module")))
    if band and reading == reading and not (band[0] <= reading <= band[1]):
        findings.append("reading %.2f outside typical %s band %s (heuristic)" % (reading, row.get("module"), band))
    if not findings:
        findings.append("no specific pattern matched; verdict driven by classifier (p=%.2f)" % proba)
    return findings


def propose_job(row, crew_id, state_dir, not_before=None):
    from datetime import datetime as _dt
    base = datetime(2187, 4, 15, 8, 0, tzinfo=timezone.utc)
    start = base + timedelta(minutes=30)
    if not_before:
        try:
            nb = _dt.fromisoformat(not_before) + timedelta(minutes=30)
            start = max(start, nb)
        except Exception:
            pass
    end = start + timedelta(hours=2)
    summary = diagnose(row, 0.0)[0]
    job = "Inspect %s: %s" % (row.get("module"), summary[:120])
    return {"crew_id": crew_id, "start": start.isoformat(), "end": end.isoformat(), "job": job}


def file_ticket(state_dir, incident_id, module, crew_id, job, priority, evidence):
    path = os.path.join(state_dir, "tickets.jsonl")
    rec = {"incident_id": incident_id, "module": module, "crew_id": crew_id,
           "job": job, "priority": priority, "evidence": evidence,
           "status": "open", "ts": datetime.now(timezone.utc).isoformat()}
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec
