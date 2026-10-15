"""Causal timeline replay (Round 2, Phase C) — from actual trace/activity artifacts.

Writes reports/TIMELINE.md. Only events the run actually recorded are shown.
trace.jsonl stores no per-event timestamps, so each incident's single record
`ts` is printed once and its steps are kept in the order the orchestrator
recorded them (labelled "recorded order"). Non-fault incidents are not traced
(the orchestrator stops before log_trace for verdict 0); that is stated, not
hidden. A missing or malformed artifact never crashes this reader.

CLI:  python round2/src/tools/timeline.py <state_dir>
"""
import glob
import json
import os
from datetime import datetime, timezone

try:
    from tools import handover
except ImportError:  # run directly as a script
    import handover


def activity_counts(state_dir):
    counts = {}
    for p in glob.glob(os.path.join(state_dir, "state", "activity", "*.jsonl")):
        cid = os.path.basename(p)[:-6]
        try:
            counts[cid] = sum(1 for line in open(p, encoding="utf-8") if line.strip())
        except OSError:
            counts[cid] = None
    return counts


def seen_counts(state_dir):
    path = os.path.join(state_dir, "state", "seen.json")
    if not os.path.exists(path):
        return None
    try:
        seen = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    non_fault = sum(1 for v in seen.values() if v == "non-fault")
    return {"total": len(seen), "non_fault": non_fault,
            "processed": len(seen) - non_fault}


def events(inc):
    """Ordered (label, detail) events actually derivable from a recorded incident."""
    raw = inc.get("raw") or {}
    risk = inc.get("risk") or {}
    sched = inc.get("schedule") or {}
    notif = inc.get("notification") or {}
    nb = inc.get("neighbors") or []
    ev = [("log received", "module=%s status=%s mode=%s node=%s" % (
        raw.get("module"), raw.get("status"), raw.get("mode"), raw.get("node"))),
        ("classifier verdict", "%s (p=%s)" % (inc.get("verdict"), inc.get("proba"))),
        ("triage", "source=%s urgency=%s score=%s escalate=%s contradiction=%s" % (
            risk.get("source"), risk.get("urgency"), risk.get("score"),
            risk.get("escalate"), risk.get("contradiction")))]
    ds, dr = handover.deception_detector.score(inc.get("raw") or {}, inc.get("proba") or 0.0)
    ev.insert(3, ("deception risk", "%d/3 [%s] (evidence, not intent)"
                  % (ds, ",".join(dr) or "none")))
    nbtxt = ", ".join("%s:%s" % (n.get("log_id"), n.get("score")) for n in nb)
    ev.append(("historian lookup", "%d neighbor(s)%s" % (len(nb), (" [" + nbtxt + "]") if nbtxt else "")))
    if inc.get("is_duplicate_of"):
        ev.append(("duplicate detected", "of `%s`" % inc.get("is_duplicate_of")))
    ev.append(("specialist selected", str(inc.get("routed_to"))))
    for step in inc.get("trace", []):
        if isinstance(step, str) and "AEGIS notify" in step:
            ev.append(("AEGIS notification gate", step.split("AEGIS notify", 1)[1].strip()))
    ev.append(("notification", "%s — %s%s" % (
        notif.get("status"), handover.truth(notif.get("status")),
        (" -> %s" % notif.get("path")) if notif.get("path") else "")))
    for step in inc.get("trace", []):
        if isinstance(step, str) and "AEGIS schedule" in step:
            ev.append(("AEGIS schedule gate", step.split("AEGIS schedule", 1)[1].strip()))
    ev.append(("schedule", "state=%s%s" % (
        sched.get("state"), (" (%s)" % sched.get("reason")) if sched.get("reason") else "")))
    mem = next((s for s in inc.get("trace", [])
                if isinstance(s, str) and s.startswith("memory=")), "")
    if mem:
        ev.append(("memory persistence", mem[len("memory="):]))
    ev.append(("final status", str(inc.get("status"))))
    return ev


def generate(state_dir, out_path=None):
    state_dir = os.path.abspath(state_dir)
    out_path = out_path or os.path.join(state_dir, "reports", "TIMELINE.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    incidents, malformed = handover.load_trace(state_dir)
    inc_list = incidents or []
    counts = activity_counts(state_dir)
    seen = seen_counts(state_dir)

    L = ["# Timeline Replay", "",
         "State dir: `%s`  " % state_dir,
         "Generated: %s (UTC) by `src/tools/timeline.py` (reader-only).  " %
         datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "Source: `trace.jsonl`. Per-event timestamps are **not recorded**; each incident's "
         "record `ts` is shown once and its steps are listed in the order the orchestrator "
         "recorded them.", ""]

    L.append("## Summary")
    L.append("")
    if incidents is None:
        L.append("- trace.jsonl: **unavailable** (no run records in this state dir).")
    else:
        genuine = sum(1 for i in inc_list if i.get("verdict") == 1)
        L.append("- traced records: %d (genuine verdicts: %d)" % (len(inc_list), genuine))
        if malformed:
            L.append("- malformed trace lines skipped: %d" % malformed)
    L.append("- non-fault incidents are not written to `trace.jsonl` (the orchestrator stops "
             "before tracing them); they appear only in `state/seen.json`.")
    if seen is not None:
        L.append("- seen.json: %d logs (%d non-fault, %d processed)" % (
            seen["total"], seen["non_fault"], seen["processed"]))
    L.append("")
    if counts:
        L.append("## Per-member activity counts (`state/activity/`)")
        L.append("")
        for cid in sorted(counts):
            L.append("- %s: %s actions" % (cid, counts[cid] if counts[cid] is not None else "unavailable"))
        L.append("")

    if not inc_list:
        L.append("## Incidents")
        L.append("")
        L.append("- None to replay.")
    for inc in inc_list:
        L.append("## %s — verdict %s, p=%s, module %s" % (
            inc.get("log_id"), inc.get("verdict"), inc.get("proba"),
            inc.get("predicted_module")))
        L.append("")
        L.append("Recorded: %s (recorded order below)." % (inc.get("_recorded_ts") or "unavailable"))
        L.append("")
        for n, (label, detail) in enumerate(events(inc), 1):
            L.append("%d. **%s** — %s" % (n, label, detail))
        flags = inc.get("deception_flags") or []
        if flags:
            L.append("")
            L.append("Risk indicators (evidence, not proof of intent): %s" % "; ".join(flags))
        L.append("")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return out_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("usage: python timeline.py <state_dir>")
    print("timeline: %s" % generate(sys.argv[1]))
