"""Shift-handover digest (Round 2, Phase B) — a pure reader of run artifacts.

Reads only what the run already wrote (trace.jsonl, tickets.jsonl,
schedule.csv, dispatch_log.csv, outbox/*.eml, memory_store/, state/) and
writes reports/HANDOVER.md. It never invents values: a missing or malformed
artifact is reported as "unavailable". Notifications are described truthfully:
the local outbox is a generated artifact, not proof of delivery.

CLI:  python round2/src/tools/handover.py <state_dir>
"""
import csv
import glob
import json
import os
from datetime import datetime, timezone

NOTIFY_TRUTH = {
    "queued": "generated locally (outbox .eml) — NOT delivered",
    "sent": "sent/confirmed by adapter",
    "failed": "FAILED (adapter error)",
    "suppressed": "suppressed (no send attempted)",
}


def load_trace(state_dir):
    """Return (incidents, malformed_count). Missing trace -> (None, 0)."""
    path = os.path.join(state_dir, "trace.jsonl")
    if not os.path.exists(path):
        return None, 0
    incidents, malformed = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                malformed += 1
                continue
            inc = rec.get("incident")
            if isinstance(inc, dict):
                inc = dict(inc)
                inc["_recorded_ts"] = rec.get("ts", "")
                incidents.append(inc)
            else:
                malformed += 1
    return incidents, malformed


def load_jsonl(path):
    if not os.path.exists(path):
        return None
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def load_csv(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except (OSError, csv.Error):
        return None


def memory_info(incidents, state_dir):
    """Backend name from the recorded trace, plus on-disk store count. No guesses."""
    backend = None
    for inc in incidents or []:
        for step in inc.get("trace", []):
            if isinstance(step, str) and step.startswith("memory="):
                backend = step[len("memory="):].split(" ", 1)[0]
                break
        if backend:
            break
    docs_path = os.path.join(state_dir, "memory_store", "docs.json")
    persisted = os.path.exists(docs_path)
    count = None
    if persisted:
        try:
            count = len(json.load(open(docs_path, encoding="utf-8")))
        except (OSError, ValueError):
            count = None
    return backend, persisted, count


def recurrence(incidents):
    """(counts_by_module, duplicate_edges) from genuine verdicts only."""
    counts, dup_edges = {}, []
    for inc in incidents or []:
        if inc.get("verdict") == 1:
            mod = inc.get("predicted_module", "unknown")
            counts[mod] = counts.get(mod, 0) + 1
        if inc.get("is_duplicate_of"):
            dup_edges.append((inc.get("log_id"), inc.get("is_duplicate_of")))
    return counts, dup_edges


def truth(status):
    return NOTIFY_TRUTH.get(status, status or "unknown")


def _table(lines, header, rows):
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    for r in rows:
        lines.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")


def generate(state_dir, out_path=None):
    state_dir = os.path.abspath(state_dir)
    out_path = out_path or os.path.join(state_dir, "reports", "HANDOVER.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    incidents, malformed = load_trace(state_dir)
    tickets = load_jsonl(os.path.join(state_dir, "tickets.jsonl"))
    schedule = load_csv(os.path.join(state_dir, "schedule.csv"))
    dispatch = load_csv(os.path.join(state_dir, "dispatch_log.csv"))
    outbox = sorted(os.path.basename(p)
                    for p in glob.glob(os.path.join(state_dir, "outbox", "*.eml")))
    backend, persisted, memcount = memory_info(incidents, state_dir)
    inc_list = incidents or []
    genuine = [i for i in inc_list if i.get("verdict") == 1]

    L = ["# Shift Handover", "",
         "State dir: `%s`  " % state_dir,
         "Generated: %s (UTC) by `src/tools/handover.py` (reader-only)." %
         datetime.now(timezone.utc).isoformat(timespec="seconds")]
    if incidents is None:
        L += ["", "> **trace.jsonl unavailable** — no run records in this state dir; "
              "sections below reflect only the artifacts that exist."]
    if malformed:
        L += ["", "> **%d malformed trace line(s) skipped** while reading." % malformed]
    L.append("")

    # 1. open critical/high
    L.append("## 1. Open critical/high incidents")
    L.append("")
    open_items = []
    for i in genuine:
        if i.get("is_duplicate_of"):
            continue
        urg = (i.get("risk") or {}).get("urgency", "low")
        sched_state = (i.get("schedule") or {}).get("state", "")
        notif = (i.get("notification") or {}).get("status", "")
        actioned = sched_state == "done" and notif in ("queued", "sent")
        if urg in ("critical", "high") and not actioned:
            open_items.append(i)
    if incidents is None:
        L.append("- unavailable (no trace records).")
    elif not open_items:
        L.append("- None. Every genuine critical/high incident this run has a completed "
                 "booking or is a suppressed duplicate.")
    else:
        _table(L, ["incident", "module", "urgency", "assigned crew", "status",
                   "booking", "notification"],
               [[i.get("log_id"), i.get("predicted_module"),
                 (i.get("risk") or {}).get("urgency"), i.get("routed_to"),
                 i.get("status"), (i.get("schedule") or {}).get("state"),
                 truth((i.get("notification") or {}).get("status"))] for i in open_items])
    L.append("")

    # 2. bookings
    L.append("## 2. Repair bookings")
    L.append("")
    if schedule is None:
        L.append("- unavailable (`schedule.csv` not found).")
    elif not schedule:
        L.append("- No bookings recorded.")
    else:
        _table(L, ["log_id", "crew_id", "start", "end", "job"],
               [[r.get("log_id"), r.get("crew_id"), r.get("start"), r.get("end"),
                 r.get("job")] for r in schedule])
        states = {}
        for i in inc_list:
            s = (i.get("schedule") or {}).get("state")
            if s:
                states[s] = states.get(s, 0) + 1
        if states:
            L.append("")
            L.append("Booking outcomes across traced incidents: " +
                     ", ".join("%s=%d" % kv for kv in sorted(states.items())) + ".")
    L.append("")

    # 3. review / escalation
    L.append("## 3. Incidents requiring review or escalation")
    L.append("")
    review = [i for i in inc_list
              if i.get("status") in ("needs_review", "auto_needs_review")]
    if incidents is None:
        L.append("- unavailable (no trace records).")
    elif not review:
        L.append("- Requires human review (workflow status): none.")
    else:
        L.append("- Requires human review (workflow status):")
        _table(L, ["incident", "module", "urgency", "status", "rationale"],
               [[i.get("log_id"), i.get("predicted_module"),
                 (i.get("risk") or {}).get("urgency"), i.get("status"),
                 "; ".join((i.get("risk") or {}).get("rationale", []))] for i in review])
    flagged = [i for i in inc_list if (i.get("risk") or {}).get("escalate")]
    if flagged:
        L.append("- Triage `escalate` flag raised on (handled automatically this run, "
                 "listed for transparency): " +
                 ", ".join("`%s` (%s)" % (i.get("log_id"),
                           (i.get("risk") or {}).get("urgency")) for i in flagged) + ".")
    L.append("")

    # 4. duplicates
    L.append("## 4. Duplicates suppressed")
    L.append("")
    _, dup_edges = recurrence(inc_list)
    dups = [i for i in inc_list if i.get("is_duplicate_of")]
    if incidents is None:
        L.append("- unavailable (no trace records).")
    elif not (dups or dup_edges):
        L.append("- None.")
    else:
        for i in dups:
            L.append("- `%s` — duplicate of `%s` (booking %s, notification %s)." % (
                i.get("log_id"), i.get("is_duplicate_of"),
                (i.get("schedule") or {}).get("state"),
                (i.get("notification") or {}).get("status")))
    L.append("")

    # 5. memory
    L.append("## 5. Memory")
    L.append("")
    if backend is None and not persisted:
        L.append("- unavailable (no memory evidence in trace or `memory_store/`).")
    else:
        L.append("- backend: %s | persisted: %s | records: %s" % (
            backend or "unknown (not recorded in trace)", persisted,
            memcount if memcount is not None else "unavailable"))
    L.append("")

    # 6. notifications (truthful)
    L.append("## 6. Notifications")
    L.append("")
    L.append("- Live transport: none configured. The local outbox is a **generated artifact, "
             "not proof of delivery**.")
    statuses = {}
    for i in inc_list:
        s = (i.get("notification") or {}).get("status")
        if s:
            statuses[s] = statuses.get(s, 0) + 1
    if incidents is None and not outbox:
        L.append("- unavailable (no trace records and no outbox files).")
    else:
        for s in sorted(statuses):
            L.append("- %s: %d — %s" % (s, statuses[s], truth(s)))
        if outbox:
            L.append("- outbox files generated locally: %s" % ", ".join(outbox))
    if dispatch is not None:
        dstat = {}
        for r in dispatch:
            dstat[r.get("status")] = dstat.get(r.get("status"), 0) + 1
        L.append("- dispatch_log.csv: " +
                 (", ".join("%s=%d" % kv for kv in sorted(dstat.items())) or "empty"))
    L.append("")

    # 7. unresolved failures
    L.append("## 7. Unresolved integration failures and next action")
    L.append("")
    fails = []
    for i in inc_list:
        if (i.get("schedule") or {}).get("state") == "failed":
            fails.append("`%s`: booking failed (%s)" %
                         (i.get("log_id"), (i.get("schedule") or {}).get("reason")))
        if (i.get("notification") or {}).get("status") == "failed":
            fails.append("`%s`: notification failed" % i.get("log_id"))
    if incidents is None:
        fails.append("trace.jsonl unavailable")
    if malformed:
        fails.append("%d malformed trace line(s)" % malformed)
    if backend is None and incidents:
        fails.append("memory backend not recorded in trace")
    if not fails:
        L.append("- None recorded.")
    else:
        for f in fails:
            L.append("- " + f)
        L.append("")
        L.append("Next action: rerun the workflow with `python -m src.main --input <logs.csv> "
                 "--state <dir>` after resolving the above; failed bookings are re-attempted on "
                 "a fresh state dir or once the offending row is corrected.")
    L.append("")

    # 8. recurrence
    L.append("## 8. Recurrence by module (this run, genuine verdicts only)")
    L.append("")
    counts, edges = recurrence(inc_list)
    if not counts:
        L.append("- unavailable / no genuine incidents recorded.")
    else:
        for mod in sorted(counts):
            n = counts[mod]
            L.append("- %s: %d genuine%s" % (mod, n, "  **(burst)**" if n >= 2 else ""))
    if edges:
        L.append("")
        L.append("Duplicate links: " + ", ".join("`%s`->`%s`" % e for e in edges))
    L.append("")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return out_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("usage: python handover.py <state_dir>")
    print("handover: %s" % generate(sys.argv[1]))
