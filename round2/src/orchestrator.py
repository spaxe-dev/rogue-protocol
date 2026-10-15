"""Mission Commander: normalize -> classify -> incident -> crew -> audit.

One command runs the whole workflow. Each action tracked separately;
failures degrade (review queue / outbox / pending ticket) without repeating
already-successful side effects. Idempotent re-runs via state/seen.json.
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas import Incident, RiskAssessment, RepairProposal, NotificationStatus, ScheduleStatus  # noqa: E402
import classifier  # noqa: E402
from crew import triage, engineer, logistics, communications  # noqa: E402
from memory.historian import open_memory  # noqa: E402
from tools import deception_detector  # noqa: E402


HERE = os.path.dirname(os.path.abspath(__file__))
ROUND2_ROOT = os.path.normpath(os.path.join(HERE, ".."))


def log_trace(state_dir, entry):
    with open(os.path.join(state_dir, "trace.jsonl"), "a") as f:
        f.write(json.dumps(entry) + "\n")


def run(input_csv, state_dir, kit_dir, memory_backend="auto", use_laya=True,
        crew_path=None):
    os.makedirs(state_dir, exist_ok=True);
    for d in ("outbox", "reports", "memory_store", "state"):
        os.makedirs(os.path.join(state_dir, d), exist_ok=True)
    classifier.load(kit_dir)
    roster = engineer.load_roster(crew_path or os.path.join(ROUND2_ROOT, "crew.json"))
    roster_ids = [c["crew_id"] for c in roster]
    sched_path = os.path.join(state_dir, "schedule.csv")
    seen_path = os.path.join(state_dir, "state", "seen.json")
    seen = json.load(open(seen_path)) if os.path.exists(seen_path) else {}
    mem, mem_name = open_memory(os.path.join(state_dir, "memory_store"), memory_backend)
    print("memory backend: %s (persisted=%s)" % (mem_name, mem.persisted()))

    import pandas as pd
    logs = pd.read_csv(input_csv)
    verdicts, probas = classifier.predict(logs)
    seen_hashes, results = set(), []
    for (_, row), verdict, proba in zip(logs.iterrows(), verdicts, probas):
        row = row.to_dict()
        lid = str(row.get("log_id"))
        if lid in seen:
            results.append({"log_id": lid, "replay": "skipped duplicate run"})
            continue
        inc = Incident(log_id=lid, raw={k: str(v) for k, v in row.items()},
                       proba=round(float(proba), 4), verdict=int(verdict),
                       predicted_module=str(row.get("module", "unknown")))
        inc.trace.append("classified verdict=%d p=%.3f" % (verdict, proba))
        if verdict == 0:
            inc.status = "reviewed"
            inc.trace.append("non-fault: no response actions")
            seen[lid] = "non-fault"
            results.append(inc.model_dump())
            continue
        # urgency (A) + deception (B)
        risk = triage.assess(row, proba, use_laya=use_laya)
        inc.risk = RiskAssessment(**risk)
        inc.deception_flags = deception_detector.detect(row, proba, seen_hashes)
        # history (D): retrieve before routing so neighbors inform specialist choice
        neighbors = mem.query(str(row.get("message", "")), k=3,
                              module=inc.predicted_module)
        inc.neighbors = neighbors
        dup = next((n for n in neighbors if n["score"] > 0.97), None)
        if dup:
            inc.is_duplicate_of = dup["log_id"]
        # engineer: specialist + diagnosis + ticket (C)
        crew_id, why = engineer.resolve_specialist(row, roster, neighbors)
        inc.routed_to = crew_id
        findings = engineer.diagnose(row, proba)
        priority = risk["urgency"]
        if risk["score"] >= 4 or dup:
            inc.status = "auto"
        elif risk["score"] >= 2:
            inc.status = "auto_needs_review"
        else:
            inc.status = "needs_review"
        crew_name = next(c["name"] for c in roster if c["crew_id"] == crew_id)
        engineer.file_ticket(state_dir, lid, inc.predicted_module, crew_id,
                             "inspect", priority, findings)
        # comms (E): notify unless low-confidence review or duplicate
        if inc.status == "needs_review" or dup:
            inc.notification = NotificationStatus(
                channel="local-outbox", status="suppressed", path="",
            )
            inc.trace.append("email suppressed: %s" % inc.status)
        else:
            inc.notification = NotificationStatus(**communications.send(
                state_dir, lid, crew_id, crew_name, inc.predicted_module,
                proba, priority, findings, neighbors))
        # logistics: schedule (skip duplicates/low-review without crew need)
        if dup:
            inc.schedule = ScheduleStatus(state="skipped", row="",
                                          reason="duplicate of " + dup["log_id"])
        else:
            existing = logistics.read_schedule(sched_path)
            latest = ""
            for r in existing:
                if r["crew_id"] == crew_id and r["end"] > latest:
                    latest = r["end"]
            job = engineer.propose_job(row, crew_id, state_dir, not_before=latest or None)
            ok, reason = logistics.append_booking(
                sched_path, {"log_id": lid, **job}, roster_ids)
            inc.repair = RepairProposal(**job)
            inc.schedule = ScheduleStatus(state="done" if ok else "failed",
                                          row=",".join([lid, job["crew_id"]]),
                                          reason=reason)
        # historian: persist AFTER actions so memory holds outcomes
        mem.add(lid, str(row.get("message", "")),
                {"module": inc.predicted_module, "verdict": verdict,
                 "crew": crew_id, "priority": priority})
        inc.trace.append("memory=%s specialist=%s (%s)" % (mem_name, crew_id, why))
        seen[lid] = "processed"
        log_trace(state_dir, {"log_id": lid, "incident": inc.model_dump(),
                              "ts": datetime.now(timezone.utc).isoformat()})
        results.append(inc.model_dump())
    json.dump(seen, open(seen_path, "w"))
    # post-incident report (F)
    n_fault = sum(1 for r in results if r.get("verdict") == 1)
    rep = os.path.join(state_dir, "reports", "run_report.md")
    with open(rep, "w") as f:
        f.write("# Run report\n\nlogs=%d genuine=%d backend=%s\n\n" % (len(results), n_fault, mem_name))
        for r in results:
            if r.get("verdict") == 1:
                f.write("- %s p=%s pri=%s spec=%s sched=%s mail=%s\n" % (
                    r["log_id"], r.get("proba"), r["risk"]["urgency"], r.get("routed_to"),
                    r["schedule"].get("state"), r["notification"].get("status")))
    print("logs=%d genuine=%d report=%s" % (len(results), n_fault, rep))
    return results
