"""Forensics black box: persistent per-incident store + timeline + recurrence + reports.

Incident store: <state_dir>/state/incidents/{log_id}.json (plain JSON files,
readable across processes/restarts). incident_id == log_id everywhere.

Timeline event: {ts, actor, event, detail}
Escalation event: {incident_id, log_id, type, reason, ts}

Read-only contract: this module never imports or mutates orchestrator,
historian internals, schemas, logistics, communications, or triage. It only
reads their artifacts (trace.jsonl, dispatch_log.csv, schedule_audit.jsonl,
tickets.jsonl, memory query interface) and the orchestrator output dict.
"""

import csv
import json
import os
from datetime import datetime, timezone

CONFIRMED_DUPLICATE_THRESHOLD = 0.97
SIMILAR_THRESHOLD = 0.80

DEFAULT_THRESHOLD = 0.54


def store_dir(state_dir):
    """Directory holding per-incident JSON files."""
    return os.path.join(state_dir, "state", "incidents")


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _default_threshold():
    try:
        import classifier  # noqa: PLC0415
        return float(classifier.THR)
    except Exception:
        return DEFAULT_THRESHOLD


def _disagreement_decision(risk):
    rationale = risk.get("rationale", []) if isinstance(risk, dict) else []
    joined = " ".join(str(r) for r in rationale).lower()
    source = risk.get("source", "") if isinstance(risk, dict) else ""
    if "disagree" in joined:
        escalated = bool(risk.get("escalate", False)) if isinstance(risk, dict) else False
        return "laya/deterministic disagreement -> %s" % (
            "escalated" if escalated else "noted without escalation")
    if source == "laya+rules":
        return "laya agreed within tolerance (no disagreement)"
    if source == "fallback":
        return "deterministic fallback (laya unavailable/invalid)"
    return "no disagreement signal (%s)" % (source or "unknown source")


def _outcome_and_unresolved(incident):
    status = str(incident.get("status", ""))
    sched = incident.get("schedule", {}) or {}
    sched_state = str(sched.get("state", "pending"))
    notif = incident.get("notification", {}) or {}
    mail = str(notif.get("status", ""))
    unresolved = []
    if status in ("needs_review", "auto_needs_review"):
        unresolved.append("status=%s requires human review" % status)
    if sched_state in ("failed", "pending"):
        unresolved.append("schedule state=%s: %s" % (
            sched_state, sched.get("reason", "no reason recorded")))
    if mail in ("failed",):
        unresolved.append("notification failed: %s" % notif.get("path", ""))
    if mail == "suppressed" and not incident.get("is_duplicate_of"):
        unresolved.append("notification suppressed (see trace for cause)")
    if incident.get("is_duplicate_of"):
        unresolved.append("duplicate of %s (actions intentionally skipped/suppressed)"
                           % incident.get("is_duplicate_of"))
    if unresolved:
        return "pending", unresolved
    if sched_state in ("done", "skipped") and status in ("auto", "reviewed"):
        return "closed:%s sched=%s mail=%s" % (status, sched_state, mail), unresolved
    return "pending", unresolved or ["outcome not yet determined"]


def store_incident(state_dir, incident_dict, threshold=None):
    """Persist one incident's black-box record. Write-once per log_id.

    incident_dict: orchestrator output dict (Incident.model_dump()).
    Returns the JSON file path. If the file already exists it is left
    untouched (idempotent re-runs must not duplicate or overwrite).
    """
    log_id = str(incident_dict.get("log_id", ""))
    if not log_id:
        raise ValueError("incident_dict must contain log_id")
    dest_dir = store_dir(state_dir)
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, log_id + ".json")
    if os.path.exists(path):
        return path
    thr = float(threshold) if threshold is not None else _default_threshold()
    risk = incident_dict.get("risk", {}) or {}
    notif = incident_dict.get("notification", {}) or {}
    sched = incident_dict.get("schedule", {}) or {}
    outcome, unresolved = _outcome_and_unresolved(incident_dict)
    record = {
        "incident_id": log_id,
        "log_id": log_id,
        "telemetry": dict(incident_dict.get("raw", {}) or {}),
        "predicted_module": incident_dict.get("predicted_module", "unknown"),
        "verdict": incident_dict.get("verdict", 0),
        "proba": incident_dict.get("proba", 0.0),
        "threshold": thr,
        "above_threshold": bool((incident_dict.get("proba", 0.0) or 0.0) >= thr),
        "laya": {
            "priority": risk.get("urgency", "low"),
            "score": risk.get("score", 0),
            "source": risk.get("source", "fallback"),
            "escalate": bool(risk.get("escalate", False)),
            "contradiction": bool(risk.get("contradiction", False)),
            "rationale": list(risk.get("rationale", []) or []),
            "disagreement_decision": _disagreement_decision(risk),
        },
        "neighbors": list(incident_dict.get("neighbors", []) or []),
        "is_duplicate_of": incident_dict.get("is_duplicate_of"),
        "crew_assignment": {
            "crew_id": incident_dict.get("routed_to", "review_queue"),
            "status": incident_dict.get("status", "needs_review"),
        },
        "notification_attempts": [dict(notif)],
        "notification": dict(notif),
        "schedule_decision": dict(sched),
        "repair": incident_dict.get("repair"),
        "deception_flags": list(incident_dict.get("deception_flags", []) or []),
        "trace": list(incident_dict.get("trace", []) or []),
        "outcome": outcome,
        "unresolved_items": unresolved,
        "stored_ts": _utcnow(),
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    os.replace(tmp, path)
    return path


def get_incident(state_dir, log_id):
    """Retrieve a stored incident by ID (works across processes)."""
    path = os.path.join(store_dir(state_dir), str(log_id) + ".json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_incidents(state_dir):
    """Sorted list of stored incident IDs."""
    d = store_dir(state_dir)
    if not os.path.isdir(d):
        return []
    return sorted(p[:-5] for p in os.listdir(d) if p.endswith(".json"))


def make_escalation_event(log_id, type, reason, ts=None):
    """Build one escalation event {incident_id, log_id, type, reason, ts}."""
    return {
        "incident_id": str(log_id),
        "log_id": str(log_id),
        "type": str(type),
        "reason": str(reason),
        "ts": ts or _utcnow(),
    }


def escalations_for_incident(record):
    """Derive escalation events purely from a stored record (evidence only)."""
    if not record:
        return []
    log_id = str(record.get("log_id", ""))
    out = []
    laya = record.get("laya", {}) or {}
    if laya.get("escalate"):
        out.append(make_escalation_event(
            log_id, "escalation",
            "risk escalate=true priority=%s score=%s" % (
                laya.get("priority"), laya.get("score")),
            ts=record.get("stored_ts", "")))
    for flag in record.get("deception_flags", []) or []:
        out.append(make_escalation_event(log_id, "deception-flag", str(flag),
                                         ts=record.get("stored_ts", "")))
    if record.get("is_duplicate_of"):
        out.append(make_escalation_event(
            log_id, "duplicate",
            "duplicate of %s" % record.get("is_duplicate_of"),
            ts=record.get("stored_ts", "")))
    sched = record.get("schedule_decision", {}) or {}
    if str(sched.get("state", "")) == "failed":
        out.append(make_escalation_event(log_id, "schedule-failed",
                                         str(sched.get("reason", "")),
                                         ts=record.get("stored_ts", "")))
    return out


def _sort_key(ts):
    if not ts:
        return (1, "")
    try:
        return (0, datetime.fromisoformat(str(ts)))
    except Exception:
        return (0, str(ts))


def _actor_from_trace_line(line):
    # Trace lines look like "NOVA->LYRA assessed critical" or "classified ...".
    if "->" in line:
        try:
            head, _ = line.split("->", 1)
            actor = head.strip().split()[-1]
            rest = line.split("->", 1)[1].strip()
            crew, _, remainder = rest.partition(" ")
            return crew.strip() or "NOVA", remainder.strip() or rest
        except Exception:
            return "NOVA", line
    return "NOVA", line


def build_timeline(state_dir, log_id):
    """Merge trace.jsonl + dispatch_log.csv + schedule_audit.jsonl + tickets
    into a chronological list of {ts, actor, event, detail} for one incident.
    Missing files contribute nothing (never raises for absent artifacts).
    """
    log_id = str(log_id)
    events = []

    trace_path = os.path.join(state_dir, "trace.jsonl")
    if os.path.exists(trace_path):
        with open(trace_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if str(entry.get("log_id", "")) != log_id:
                    continue
                ts = str(entry.get("ts", ""))
                incident = entry.get("incident", {}) or {}
                for t in incident.get("trace", []) or []:
                    actor, evt = _actor_from_trace_line(str(t))
                    events.append({"ts": ts, "actor": actor, "event": evt,
                                   "detail": str(t)})

    tickets_path = os.path.join(state_dir, "tickets.jsonl")
    if os.path.exists(tickets_path):
        with open(tickets_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if str(rec.get("incident_id", "")) != log_id:
                    continue
                events.append({
                    "ts": str(rec.get("ts", "")),
                    "actor": "ATLAS",
                    "event": "ticket filed",
                    "detail": "module=%s crew=%s priority=%s job=%s" % (
                        rec.get("module"), rec.get("crew_id"),
                        rec.get("priority"), rec.get("job")),
                })

    ledger_path = os.path.join(state_dir, "dispatch_log.csv")
    if os.path.exists(ledger_path):
        with open(ledger_path, newline="", encoding="utf-8") as f:
            try:
                for row in csv.DictReader(f):
                    if str(row.get("log_id", "")) != log_id:
                        continue
                    events.append({
                        "ts": str(row.get("ts", "")),
                        "actor": "PULSE",
                        "event": "dispatch %s" % row.get("status", ""),
                        "detail": "crew=%s status=%s" % (
                            row.get("crew_id"), row.get("status")),
                    })
            except Exception:
                pass

    for candidate in (os.path.join(state_dir, "schedule_audit.jsonl"),
                      os.path.join(state_dir, "state", "schedule_audit.jsonl"),
                      os.path.join(state_dir, "reports", "schedule_audit.jsonl")):
        if os.path.exists(candidate):
            with open(candidate, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if str(rec.get("log_id", rec.get("incident_id", ""))) != log_id:
                        continue
                    events.append({
                        "ts": str(rec.get("ts", "")),
                        "actor": "ORBIT",
                        "event": str(rec.get("event", "schedule audit")),
                        "detail": str(rec.get("detail", rec.get("reason", ""))),
                    })
            break

    events.sort(key=lambda e: _sort_key(e.get("ts", "")))
    return events


def check_recurrence(memory, log_id, text, module=None, k=3):
    """Classify memory matches as evidence (never assert below evidence).

    score > 0.97            -> confirmed-duplicate
    0.80 <= score <= 0.97   -> similar
    score < 0.80            -> below evidence (reported, never asserted)
    Self-matches (same log_id) are excluded.
    """
    log_id = str(log_id)
    try:
        hits = memory.query(text, k=k, module=module) or []
    except Exception:
        hits = []
    matches = []
    for h in hits:
        if str(h.get("log_id", "")) == log_id:
            continue
        try:
            score = float(h.get("score", 0.0))
        except (TypeError, ValueError):
            continue
        if score > CONFIRMED_DUPLICATE_THRESHOLD:
            verdict = "confirmed-duplicate"
        elif score >= SIMILAR_THRESHOLD:
            verdict = "similar"
        else:
            verdict = "below-evidence"
        matches.append({
            "log_id": str(h.get("log_id", "")),
            "score": score,
            "module": h.get("module", ""),
            "text": str(h.get("text", ""))[:160],
            "verdict": verdict,
        })
    asserted = [m for m in matches if m["verdict"] in ("confirmed-duplicate", "similar")]
    dup = next((m for m in matches if m["verdict"] == "confirmed-duplicate"), None)
    if dup:
        status = "confirmed-duplicate"
    elif any(m["verdict"] == "similar" for m in matches):
        status = "similar"
    else:
        status = "no-evidence"
    return {
        "incident_id": log_id,
        "log_id": log_id,
        "status": status,
        "duplicate_of": dup["log_id"] if dup else None,
        "matches": matches,
        "asserted": asserted,
    }


def generate_report(state_dir, log_id, memory=None, output_dir=None):
    """Write a Markdown forensics report. Returns (markdown_str, path)."""
    log_id = str(log_id)
    record = get_incident(state_dir, log_id)
    if record is None:
        raise FileNotFoundError("no stored incident %s" % log_id)
    timeline = build_timeline(state_dir, log_id)
    recurrence = None
    if memory is not None:
        telemetry = record.get("telemetry", {}) or {}
        recurrence = check_recurrence(
            memory, log_id, str(telemetry.get("message", "")),
            module=record.get("predicted_module") or None)
    laya = record.get("laya", {}) or {}
    notif = record.get("notification", {}) or {}
    sched = record.get("schedule_decision", {}) or {}
    lines = []
    lines.append("# Forensics report — %s" % log_id)
    lines.append("")
    lines.append("## Incident ID")
    lines.append("")
    lines.append("- incident_id: `%s`" % record.get("incident_id", log_id))
    lines.append("- log_id: `%s`" % log_id)
    lines.append("- module: %s" % record.get("predicted_module", "unknown"))
    lines.append("- stored: %s" % record.get("stored_ts", "unknown"))
    lines.append("")
    lines.append("## Severity")
    lines.append("")
    lines.append("- verdict: %s (proba=%.4f, threshold=%.2f, above=%s)" % (
        record.get("verdict"), float(record.get("proba", 0.0) or 0.0),
        float(record.get("threshold", 0.0) or 0.0),
        record.get("above_threshold")))
    lines.append("- priority: %s (score=%s, escalate=%s, contradiction=%s, source=%s)" % (
        laya.get("priority"), laya.get("score"), laya.get("escalate"),
        laya.get("contradiction"), laya.get("source")))
    lines.append("- crew status: %s" % (record.get("crew_assignment", {}) or {}).get("status"))
    lines.append("")
    lines.append("## Evidence")
    lines.append("")
    telemetry = record.get("telemetry", {}) or {}
    for key in ("timestamp", "module", "mode", "node", "status", "reading",
                "delay_ms", "retry_count", "message"):
        if key in telemetry:
            lines.append("- %s: %s" % (key, telemetry.get(key)))
    for flag in record.get("deception_flags", []) or []:
        lines.append("- deception flag: %s" % flag)
    lines.append("")
    lines.append("## Decisions")
    lines.append("")
    lines.append("- classifier: verdict=%s p=%.4f vs threshold %.2f" % (
        record.get("verdict"), float(record.get("proba", 0.0) or 0.0),
        float(record.get("threshold", 0.0) or 0.0)))
    lines.append("- laya priority: %s; rationale: %s" % (
        laya.get("priority"), "; ".join(laya.get("rationale", []) or ["(none)"])))
    lines.append("- disagreement decision: %s" % laya.get("disagreement_decision"))
    lines.append("- duplicate link: %s" % (record.get("is_duplicate_of") or "none"))
    lines.append("- crew assignment: %s" % json.dumps(record.get("crew_assignment", {})))
    lines.append("")
    lines.append("## Actions")
    lines.append("")
    lines.append("- notification: channel=%s status=%s path=%s" % (
        notif.get("channel"), notif.get("status"), notif.get("path")))
    lines.append("- repair proposal: %s" % json.dumps(record.get("repair")))
    lines.append("- timeline (%d events):" % len(timeline))
    for e in timeline:
        lines.append("  - [%s] %s: %s — %s" % (
            e.get("ts"), e.get("actor"), e.get("event"), e.get("detail")))
    if not timeline:
        lines.append("  - (no timeline events found)")
    lines.append("")
    lines.append("## Schedule")
    lines.append("")
    lines.append("- state=%s row=%s reason=%s" % (
        sched.get("state"), sched.get("row"), sched.get("reason")))
    lines.append("")
    lines.append("## Historical matches")
    lines.append("")
    hist = recurrence.get("matches", []) if recurrence else list(record.get("neighbors", []) or [])
    if recurrence:
        lines.append("- recurrence status: %s (duplicate_of=%s)" % (
            recurrence.get("status"), recurrence.get("duplicate_of")))
    for m in hist:
        score = m.get("score", "?")
        try:
            score_s = "%.4f" % float(score)
        except (TypeError, ValueError):
            score_s = str(score)
        lines.append("- %s score=%s verdict=%s module=%s :: %s" % (
            m.get("log_id"), score_s, m.get("verdict", "neighbor"),
            m.get("module"), m.get("text", "")))
    if not hist:
        lines.append("- (no historical matches)")
    lines.append("")
    lines.append("## Unresolved items")
    lines.append("")
    lines.append("- outcome: %s" % record.get("outcome", "pending"))
    for item in record.get("unresolved_items", []) or []:
        lines.append("- [ ] %s" % item)
    if not (record.get("unresolved_items", []) or []):
        lines.append("- (none — all actions resolved)")
    lines.append("")
    md = "\n".join(lines)
    out_dir = output_dir or os.path.join(state_dir, "reports")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "forensics_%s.md" % log_id)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return md, path


def record_incident(state_dir, incident_dict, threshold=None, memory=None):
    """One-call hook: store the incident then write its report.

    Returns (store_path, report_markdown, report_path).
    """
    store_path = store_incident(state_dir, incident_dict, threshold=threshold)
    md, report_path = generate_report(
        state_dir, str(incident_dict.get("log_id", "")), memory=memory)
    return store_path, md, report_path
