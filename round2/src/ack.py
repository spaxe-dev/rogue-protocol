"""Ownership / acknowledgement-timeout / escalation tracker (Agent 3).

No sleeps anywhere: expiry is evaluated by `sweep()` against an injectable
`now_iso`, so tests use tiny `timeout_s` values and synthetic timestamps.

Storage (all under `state_dir`):
  state/acks/{log_id}.json   Ack record:
      {log_id, owner, notified_ts, ack_ts|None, timeout_s,
       status: pending|acknowledged|escalated}
  state/escalations.jsonl    Shared contract with the ticket agent. One line
      per escalation event:
      {incident_id, log_id, type ("ack-timeout"), reason, ts}
  state/escalation_{log_id}.eml  Fallback outbox entry written when no
      `notify_fn` (no SMTP credentials / adapter) is available. Status
      `pending-local`: explicitly NOT a delivery claim.

Only this module's files are touched; communications.send() is not modified.
"""
import json
import os
from datetime import datetime, timezone, timedelta


def _acks_dir(state_dir):
    return os.path.join(state_dir, "state", "acks")


def _record_path(state_dir, log_id):
    return os.path.join(_acks_dir(state_dir), "%s.json" % log_id)


def _escalations_path(state_dir):
    return os.path.join(state_dir, "state", "escalations.jsonl")


def _fallback_path(state_dir, log_id):
    return os.path.join(state_dir, "state", "escalation_%s.eml" % log_id)


def _now_iso(now_iso=None):
    return now_iso or datetime.now(timezone.utc).isoformat()


def _parse_ts(ts):
    # Accept trailing Z as well as explicit offsets.
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def _load_record(state_dir, log_id):
    path = _record_path(state_dir, log_id)
    if not os.path.exists(path):
        raise FileNotFoundError("no ack record for log %s" % log_id)
    with open(path) as f:
        return json.load(f)


def _save_record(state_dir, record):
    os.makedirs(_acks_dir(state_dir), exist_ok=True)
    with open(_record_path(state_dir, record["log_id"]), "w") as f:
        json.dump(record, f, indent=2)
    return record


def assign_owner(state_dir, log_id, owner_crew_id, timeout_s=300, now_iso=None):
    """Register ownership of `log_id`. Retry-idempotent: an existing record
    is returned unchanged (the notification timer is not reset)."""
    existing_path = _record_path(state_dir, log_id)
    if os.path.exists(existing_path):
        with open(existing_path) as f:
            return json.load(f)
    record = {
        "log_id": log_id,
        "owner": owner_crew_id,
        "notified_ts": _now_iso(now_iso),
        "ack_ts": None,
        "timeout_s": timeout_s,
        "status": "pending",
    }
    return _save_record(state_dir, record)


def acknowledge(state_dir, log_id, by, now_iso=None):
    """Mark `log_id` acknowledged by `by`. Idempotent: a repeat ack keeps the
    original `ack_ts`. A late ack (after escalation) is still recorded
    (`ack_ts`/`acked_by`) rather than lost; status stays `escalated`."""
    record = _load_record(state_dir, log_id)
    ts = _now_iso(now_iso)
    if record.get("status") == "acknowledged":
        return record
    if record.get("status") == "escalated":
        if record.get("ack_ts") is None:
            record["ack_ts"] = ts
            record["acked_by"] = by
            record["late"] = True
            _save_record(state_dir, record)
        return record
    record["ack_ts"] = ts
    record["acked_by"] = by
    record["status"] = "acknowledged"
    return _save_record(state_dir, record)


def _append_escalation(state_dir, event):
    os.makedirs(os.path.dirname(_escalations_path(state_dir)), exist_ok=True)
    with open(_escalations_path(state_dir), "a") as f:
        f.write(json.dumps(event) + "\n")


def _write_fallback_email(state_dir, record, escalation):
    """Missing-credentials path: local pending file. Never claims delivery."""
    path = _fallback_path(state_dir, record["log_id"])
    if os.path.exists(path):
        return path
    body = "\n".join([
        "To: ticket-agent (escalation queue)",
        "Subject: [ACK-TIMEOUT] log %s owner %s unacknowledged" % (
            record["log_id"], record["owner"]),
        "Status: pending-local",
        "",
        "NOT DELIVERED - no SMTP credentials / adapter configured.",
        "This is a local pending outbox entry only, not proof of delivery.",
        "",
        "incident_id: %s" % escalation["incident_id"],
        "log_id: %s" % escalation["log_id"],
        "type: %s" % escalation["type"],
        "reason: %s" % escalation["reason"],
        "ts: %s" % escalation["ts"],
        "owner: %s" % record["owner"],
        "notified_ts: %s" % record["notified_ts"],
        "timeout_s: %s" % record["timeout_s"],
    ])
    with open(path, "w") as f:
        f.write(body)
    return path


def sweep(state_dir, now_iso=None, notify_fn=None):
    """Escalate every expired, unacknowledged record exactly once.

    For each record with status `pending` past `notified_ts + timeout_s`:
      * append the escalation event to state/escalations.jsonl,
      * call `notify_fn(escalation)` when given, else write the
        pending-local fallback email file,
      * mark the record `escalated`.
    Already-acknowledged / already-escalated records are skipped, so a
    repeated sweep never duplicates events or email files. Returns the list
    of escalation events fired by this sweep.
    """
    now = _parse_ts(_now_iso(now_iso))
    ack_dir = _acks_dir(state_dir)
    if not os.path.isdir(ack_dir):
        return []
    fired = []
    for name in sorted(os.listdir(ack_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(ack_dir, name)) as f:
            record = json.load(f)
        if record.get("status") != "pending":
            continue
        try:
            deadline = _parse_ts(record["notified_ts"]) + timedelta(
                seconds=float(record.get("timeout_s", 300)))
        except (KeyError, TypeError, ValueError):
            continue
        if now <= deadline:
            continue
        escalation = {
            "incident_id": record["log_id"],
            "log_id": record["log_id"],
            "type": "ack-timeout",
            "reason": "owner %s did not acknowledge log %s within %ss" % (
                record.get("owner"), record["log_id"],
                record.get("timeout_s", 300)),
            "ts": now.isoformat(),
        }
        if notify_fn is not None:
            try:
                outcome = notify_fn(escalation)
            except Exception as exc:  # delivery adapter failed: keep local proof
                path = _write_fallback_email(state_dir, record, escalation)
                record["delivery"] = {"status": "pending-local", "path": path,
                                      "error": str(exc)}
            else:
                record["delivery"] = {"status": "notified", "outcome": outcome}
        else:
            path = _write_fallback_email(state_dir, record, escalation)
            record["delivery"] = {"status": "pending-local", "path": path}
        record["status"] = "escalated"
        _save_record(state_dir, record)
        _append_escalation(state_dir, escalation)
        fired.append(escalation)
    return fired


# ---------------------------------------------------------------------------
# Role-specific message builders (pure functions).
# They use only fields present on the incident dict and invent no outcomes.
# Each returns {"subject": ..., "body": ...}.
# ---------------------------------------------------------------------------

def _incident_get(incident, *keys, default="unknown"):
    for key in keys:
        if isinstance(incident, dict) and incident.get(key) not in (None, ""):
            return incident.get(key)
    return default


def _priority_of(incident):
    if isinstance(incident, dict):
        risk = incident.get("risk") or {}
        if isinstance(risk, dict) and risk.get("urgency"):
            return risk["urgency"]
        for key in ("priority", "urgency"):
            if incident.get(key):
                return incident.get(key)
    return "unknown"


def _findings_of(incident):
    findings = (incident or {}).get("findings") or (incident or {}).get("diagnosis") or []
    if isinstance(findings, str):
        return [findings]
    return list(findings)


def engineer_brief(incident):
    """Technical brief for the assigned specialist engineer."""
    log_id = _incident_get(incident, "log_id")
    module = _incident_get(incident, "predicted_module", "module")
    proba = _incident_get(incident, "proba", default="n/a")
    priority = _priority_of(incident)
    owner = _incident_get(incident, "routed_to", "owner")
    findings = _findings_of(incident)
    neighbors = (incident or {}).get("neighbors") or []
    lines = [
        "Log %s: suspected fault in module %s (p=%s, priority %s)." % (
            log_id, module, proba, priority),
        "Assigned owner: %s." % owner,
        "Findings:",
    ]
    lines += ["- %s" % f for f in findings] or ["- (no findings recorded)"]
    if neighbors:
        lines.append("Similar past incidents:")
        lines += ["- %s" % (n.get("log_id", "?") if isinstance(n, dict) else n)
                  for n in neighbors]
    return {
        "subject": "[ENGINEER] fault %s in %s (p=%s)" % (log_id, module, proba),
        "body": "\n".join(lines),
    }


def commander_brief(incident):
    """Command summary: status, priority, routing, audit-relevant fields."""
    log_id = _incident_get(incident, "log_id")
    module = _incident_get(incident, "predicted_module", "module")
    proba = _incident_get(incident, "proba", default="n/a")
    priority = _priority_of(incident)
    status = _incident_get(incident, "status")
    routed = _incident_get(incident, "routed_to", "owner")
    lines = [
        "Commander summary for log %s." % log_id,
        "Module: %s; fault probability: %s; priority: %s." % (module, proba, priority),
        "Status: %s; routed to: %s." % (status, routed),
        "Verdict: %s." % _incident_get(incident, "verdict"),
    ]
    return {
        "subject": "[COMMAND] incident %s status %s priority %s" % (log_id, status, priority),
        "body": "\n".join(lines),
    }


def logistics_brief(incident):
    """Scheduling brief: who does the work and when it is booked."""
    log_id = _incident_get(incident, "log_id")
    crew = _incident_get(incident, "routed_to", "owner", "crew_id")
    schedule = (incident or {}).get("schedule") or {}
    repair = (incident or {}).get("repair") or {}
    if isinstance(schedule, dict):
        sched_state = schedule.get("state", "unknown")
        sched_row = schedule.get("row", "")
        sched_reason = schedule.get("reason", "")
    else:
        sched_state, sched_row, sched_reason = str(schedule), "", ""
    if isinstance(repair, dict):
        job = repair.get("job", "unknown")
        window = "%s -> %s" % (repair.get("start", "?"), repair.get("end", "?"))
    else:
        job, window = str(repair), "?"
    body = "\n".join([
        "Logistics booking for log %s." % log_id,
        "Assigned crew: %s; job: %s." % (crew, job),
        "Window: %s." % window,
        "Schedule state: %s; row: %s; reason: %s." % (sched_state, sched_row, sched_reason),
    ])
    return {
        "subject": "[LOGISTICS] booking %s crew %s" % (log_id, crew),
        "body": body,
    }


def mission_control_digest(unresolved_list):
    """Multi-incident digest for mission control. Lists only given fields."""
    items = unresolved_list or []
    lines = ["Mission control digest: %d unresolved incident(s)." % len(items)]
    for incident in items:
        if not isinstance(incident, dict):
            lines.append("- %s" % incident)
            continue
        lines.append("- %s module=%s p=%s priority=%s status=%s owner=%s" % (
            _incident_get(incident, "log_id"),
            _incident_get(incident, "predicted_module", "module"),
            _incident_get(incident, "proba", default="n/a"),
            _priority_of(incident),
            _incident_get(incident, "status"),
            _incident_get(incident, "routed_to", "owner"),
        ))
    return {
        "subject": "[MISSION-CONTROL] %d unresolved incident(s)" % len(items),
        "body": "\n".join(lines),
    }
