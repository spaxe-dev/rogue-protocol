"""Anubhav (validation) — read-only schedule auditor.

Ownership: Anubhav. New file under round2/src/tools/, per ANUBHAV_VALIDATION_AUDIT.md
Phase B. Does NOT modify orchestrator, AEGIS gate, schemas, triage, or historian.

Contract:
- Schedule header is exactly log_id,crew_id,start,end,job (crew/logistics.py:9,
  crew/safety.py:25). Anything else is a HEADER finding.
- Read-only: never writes, corrects, or deletes. Returns structured findings.
- Datetimes are parsed with datetime.fromisoformat, never string-compared
  (regression cover for the string-compare timestamp bug).
- Duplicate policy mirrors the gate: duplicate log_id rejected
  (crew/safety.py:38-39, crew/logistics.py:76-77). Duplicate job TEXT across
  different log_ids is allowed and NOT flagged.
- Overlap policy mirrors append_booking: same-crew intervals must not overlap
  (crew/logistics.py:78-84). Cross-crew overlap is allowed.
- Unknown crew checked against round2/config/crew.json when available.
- No long-booking threshold invented: no documented limit exists, so only
  zero/negative duration (end <= start) is flagged. Zero duration is included
  in END_BEFORE_START.
- Severity is "error" for every policy violation (the gate would return
  pass=False). No warning tier invented. Valid schedule -> valid=True.

Swayam integration: call audit_file(path) — no orchestrator change needed.
CLI: python -m tools.schedule_auditor --schedule <csv> [--registry <json>]
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_ROOT = os.path.normpath(os.path.join(HERE, ".."))
ROUND2_ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
DEFAULT_REGISTRY = os.path.join(ROUND2_ROOT, "config", "crew.json")

HEADER = ["log_id", "crew_id", "start", "end", "job"]


def _parse(ts):
    """Parse ISO datetime. Returns datetime or None (never raises)."""
    try:
        if ts is None:
            return None
        text = str(ts).strip()
        if not text:
            return None
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _finding(rule, log_id, row, message):
    return {
        "severity": "error",
        "rule": rule,
        "log_id": log_id or "",
        "row": row,  # 1-based data-row index; 0 = file-level (header/missing file)
        "message": message,
    }


def _load_crew_ids(registry_path=None, crew_ids=None):
    """Resolve known crew IDs. Returns set or None (skip unknown-crew check)."""
    if crew_ids is not None:
        return set(crew_ids)
    path = registry_path or DEFAULT_REGISTRY
    try:
        with open(path, encoding="utf-8") as f:
            return {c["crew_id"] for c in json.load(f)["crew"]}
    except Exception:
        return None


def audit_rows(rows, crew_ids=None):
    """Audit in-memory schedule rows (list of dicts). Pure, no I/O.

    Detects: missing/empty fields, bad datetime, end<=start (incl. zero
    duration), duplicate log_id, same-crew overlap, unknown crew.
    Malformed csv rows surface here as None values -> MISSING_FIELD.
    """
    findings = []
    seen_log_ids = {}
    # Per-row checks first (so overlap/duplicate reference parsed values).
    parsed = {}  # row_idx -> (start_dt, end_dt, crew_id)
    for idx, row in enumerate(rows, start=1):
        lid = row.get("log_id") if isinstance(row, dict) else ""
        lid = "" if lid is None else str(lid)
        if not isinstance(row, dict):
            findings.append(_finding("MALFORMED_ROW", lid, idx,
                                     "row %d is not a valid record" % idx))
            continue
        # Extra columns from csv (restkey) indicate malformed row.
        if None in row:
            findings.append(_finding("MALFORMED_ROW", lid, idx,
                                     "row %d has extra columns beyond %s" % (idx, HEADER)))
        for col in HEADER:
            val = row.get(col)
            if val is None:
                findings.append(_finding("MISSING_FIELD", lid, idx,
                                         "row %d (%s): missing column '%s'" % (idx, lid or "?", col)))
            elif not str(val).strip():
                findings.append(_finding("EMPTY_FIELD", lid, idx,
                                         "row %d (%s): empty/whitespace-only '%s'" % (idx, lid or "?", col)))
        # Duplicate log_id: only 2nd+ occurrences flagged (first is canonical).
        if lid and lid.strip():
            if lid in seen_log_ids:
                findings.append(_finding(
                    "DUPLICATE_LOG_ID", lid, idx,
                    "row %d (%s): duplicate log_id, first seen at row %d (policy: idempotent reject)"
                    % (idx, lid, seen_log_ids[lid])))
            else:
                seen_log_ids[lid] = idx
        # Datetime checks (parsed, never string-compared).
        start_dt = _parse(row.get("start"))
        end_dt = _parse(row.get("end"))
        if row.get("start") is not None and str(row.get("start")).strip() and start_dt is None:
            findings.append(_finding("BAD_DATETIME", lid, idx,
                                     "row %d (%s): unparseable start %r" % (idx, lid, row.get("start"))))
        if row.get("end") is not None and str(row.get("end")).strip() and end_dt is None:
            findings.append(_finding("BAD_DATETIME", lid, idx,
                                     "row %d (%s): unparseable end %r" % (idx, lid, row.get("end"))))
        if start_dt is not None and end_dt is not None and not (end_dt > start_dt):
            findings.append(_finding("END_BEFORE_START", lid, idx,
                                     "row %d (%s): end <= start (%s <= %s)"
                                     % (idx, lid, row.get("end"), row.get("start"))))
        # Unknown crew (only when registry available).
        cid = row.get("crew_id")
        if crew_ids is not None and cid is not None and str(cid).strip():
            if str(cid).strip() not in crew_ids:
                findings.append(_finding("UNKNOWN_CREW", lid, idx,
                                         "row %d (%s): unknown crew_id %r" % (idx, lid, cid)))
        if start_dt is not None and end_dt is not None:
            parsed[idx] = (start_dt, end_dt, str(row.get("crew_id", "")).strip(), lid)
    # Overlap: same crew only, parsed intervals, sorted by start.
    by_crew = {}
    for idx, (s, e, cid, lid) in parsed.items():
        if cid:
            by_crew.setdefault(cid, []).append((s, e, idx, lid))
    for cid, intervals in by_crew.items():
        intervals.sort(key=lambda t: t[0])
        for (s1, e1, i1, l1), (s2, e2, i2, l2) in zip(intervals, intervals[1:]):
            if s2 < e1:  # parsed-datetime comparison, not string comparison
                findings.append(_finding(
                    "OVERLAP", l2, i2,
                    "crew %s: row %d (%s) overlaps row %d (%s)" % (cid, i2, l2, i1, l1)))
    return findings


def audit_file(path, crew_ids=None, registry_path=None, skip_registry=False):
    """Read-only audit of a schedule CSV. Returns {valid, rows, findings}.

    Never writes to path. Missing file, bad header, and malformed rows are
    findings (row=0 for file-level problems). Pass skip_registry=True to
    skip the unknown-crew check even when round2/config/crew.json exists.
    """
    if skip_registry and crew_ids is None:
        known = None
    else:
        known = _load_crew_ids(registry_path=registry_path, crew_ids=crew_ids)
    if not os.path.exists(path):
        return {"valid": False, "rows": 0,
                "findings": [_finding("FILE_NOT_FOUND", "", 0,
                                      "schedule file not found: %s" % path)]}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != HEADER:
                return {"valid": False, "rows": 0,
                        "findings": [_finding(
                            "HEADER", "", 0,
                            "schedule header must be %s, got %s" % (HEADER, reader.fieldnames))]}
            rows = list(reader)
    except Exception as e:
        return {"valid": False, "rows": 0,
                "findings": [_finding("UNREADABLE", "", 0,
                                      "could not read %s: %s: %s" % (path, e.__class__.__name__, e))]}
    findings = audit_rows(rows, crew_ids=known)
    return {"valid": not findings, "rows": len(rows), "findings": findings}


def report_text(result, path):
    lines = ["schedule_audit: %s (%d rows, %d problems)"
             % (path, result["rows"], len(result["findings"]))]
    if result["valid"]:
        lines.append("VALID — no problems found.")
    for f in result["findings"]:
        lines.append("  [%s] row=%s log=%s %s: %s"
                     % (f["severity"], f["row"], f["log_id"] or "?", f["rule"], f["message"]))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only schedule auditor (Anubhav).")
    ap.add_argument("--schedule", required=True, help="path to schedule.csv")
    ap.add_argument("--registry", default=None, help="path to crew.json (default: round2/config/crew.json)")
    ap.add_argument("--no-registry", action="store_true",
                    help="skip unknown-crew check even if registry exists")
    a = ap.parse_args(argv)
    if a.no_registry:
        result = audit_file(a.schedule, skip_registry=True)
    else:
        known = _load_crew_ids(registry_path=a.registry)
        result = audit_file(a.schedule, crew_ids=known,
                            registry_path=a.registry or DEFAULT_REGISTRY)
    print(report_text(result, a.schedule))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    if "src" not in sys.path and SRC_ROOT not in sys.path:
        sys.path.insert(0, SRC_ROOT)
    raise SystemExit(main())
