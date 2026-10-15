"""Communications Officer: local file-outbox adapter + delivery ledger + brief.

The outbox is a demonstrable local adapter, NOT proof of delivery. No live
transport (SMTP/webhook/Jira) is configured, so this never reports "sent":
status is `queued` (a local artifact was written), `suppressed` (idempotent),
or `failed` (the caller records it). SMTP/webhook adapters plug in here when
authorized and available.
"""
import csv
import os
from datetime import datetime, timezone

TRANSPORT = "local-file-outbox"


def send(state_dir, log_id, crew_id, crew_name, module, proba, priority, findings,
         neighbors, deception=None):
    outbox = os.path.join(state_dir, "outbox")
    os.makedirs(outbox, exist_ok=True)
    subject = "[Aurora %s] %s fault %s (p=%.2f)" % (priority.upper(), module, log_id, proba)
    lines = ["To: %s <%s@aurora.ship>" % (crew_name, crew_id),
             "Subject: %s" % subject, "",
             "Specialist %s (%s)," % (crew_name, crew_id),
             "NINE log %s classified GENUINE FAULT (p=%.2f), priority %s." % (log_id, proba, priority),
             "Module: %s" % module, "Findings:"]
    lines += ["- " + f for f in findings]
    if deception and deception.get("score"):
        lines.append("Deception risk indicators (score %d/%d): %s" % (
            deception["score"], deception.get("total", 3),
            "; ".join(deception.get("rules") or []) or "none"))
    if neighbors:
        lines.append("Similar past incidents:")
        lines += ["- %s (score %s)" % (n["log_id"], n["score"]) for n in neighbors]
    lines += ["", "Transport: %s — generated locally, NOT proof of delivery." % TRANSPORT]
    body = "\n".join(lines)
    path = os.path.join(outbox, log_id + ".eml")
    if os.path.exists(path):
        return {"channel": TRANSPORT, "status": "suppressed", "path": path,
                "reason": "already dispatched (idempotent)"}
    with open(path, "w") as f:
        f.write("Subject: %s\n\n%s" % (subject, body))
    ledger = os.path.join(state_dir, "dispatch_log.csv")
    new = not os.path.exists(ledger)
    with open(ledger, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["log_id", "crew_id", "status", "ts"])
        w.writerow([log_id, crew_id, "queued-local", datetime.now(timezone.utc).isoformat()])
    brief = os.path.join(state_dir, "reports", "brief_%s.md" % log_id)
    os.makedirs(os.path.dirname(brief), exist_ok=True)
    with open(brief, "w") as f:
        f.write("# Incident brief %s\n\n%s\n" % (log_id, body))
    return {"channel": TRANSPORT, "status": "queued", "path": path}
