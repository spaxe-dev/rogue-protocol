"""Mission Commander: normalize -> classify -> incident -> crew -> audit.

One command runs the whole workflow. Each action tracked separately;
failures degrade (review queue / outbox / pending ticket) without repeating
already-successful side effects. Idempotent re-runs via state/seen.json.
"""
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas import Incident, RiskAssessment, RepairProposal, NotificationStatus, ScheduleStatus  # noqa: E402
import classifier  # noqa: E402
from crew import triage, engineer, logistics, communications, registry, safety  # noqa: E402
from memory.historian import open_memory  # noqa: E402
from tools import deception_detector  # noqa: E402
from tools.recurrence import analyze_recurrence, render_report  # noqa: E402


HERE = os.path.dirname(os.path.abspath(__file__))
ROUND2_ROOT = os.path.normpath(os.path.join(HERE, ".."))


def log_trace(state_dir, entry):
    with open(os.path.join(state_dir, "trace.jsonl"), "a") as f:
        f.write(json.dumps(entry) + "\n")


def row_fingerprint(row):
    """Stable exact-source fingerprint; excludes only the assigned log ID."""
    payload = {str(k): str(v) for k, v in row.items() if k != "log_id"}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run(input_csv, state_dir, kit_dir, memory_backend="auto", use_laya=True,
        crew_path=None):
    os.makedirs(state_dir, exist_ok=True);
    for d in ("outbox", "reports", "memory_store", "state"):
        os.makedirs(os.path.join(state_dir, d), exist_ok=True)
    classifier.load(kit_dir)
    crew_cfg = crew_path or os.path.join(ROUND2_ROOT, "config", "crew.json")
    _, by_id = registry.load_registry(crew_cfg)  # validated at startup
    roster = [c for c in by_id.values() if c.get("kind") == "specialist"]
    roster_ids = [c["crew_id"] for c in roster]
    sched_path = os.path.join(state_dir, "schedule.csv")
    seen_path = os.path.join(state_dir, "state", "seen.json")
    seen = json.load(open(seen_path)) if os.path.exists(seen_path) else {}
    memory_path = os.path.join(state_dir, "memory_store")
    memory_errors = []
    try:
        mem, mem_name = open_memory(memory_path, memory_backend)
        mem_status = mem.report()
    except Exception as exc:
        mem, mem_name = None, "unavailable"
        mem_status = {"backend": mem_name, "record_count": 0, "persisted": False,
                      "error": "%s: %s" % (type(exc).__name__, exc)}
        memory_errors.append(mem_status["error"])
    print("memory: %s" % json.dumps(mem_status, sort_keys=True))

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
        # NOVA -> LYRA: urgency (A) + deception (B)
        risk = registry.dispatch(by_id, "LYRA", triage.assess, row=row, proba=proba,
                                 use_laya=use_laya)
        registry.log_activity(state_dir, "LYRA", "assess",
                              {"urgency": risk["urgency"], "source": risk["source"]})
        inc.risk = RiskAssessment(**risk)
        inc.trace.append("NOVA->LYRA assessed %s" % risk["urgency"])
        inc.deception_flags = deception_detector.detect(row, proba, seen_hashes)
        # NOVA -> ECHO: history (D) before routing so neighbors inform specialist choice
        neighbors = []
        fingerprint = row_fingerprint(row)
        exact_prior = None
        if mem is not None:
            try:
                neighbors = mem.query(str(row.get("message", "")), k=3,
                                      module=inc.predicted_module)
                exact_prior = mem.find_exact(fingerprint, module=inc.predicted_module)
            except Exception as exc:
                detail = "query %s: %s" % (type(exc).__name__, exc)
                memory_errors.append(detail)
                inc.trace.append("NOVA->ECHO degraded: " + detail)
        registry.log_activity(state_dir, "ECHO", "query", {"hits": len(neighbors)})
        inc.neighbors = neighbors
        inc.trace.append("NOVA->ECHO %d neighbors" % len(neighbors))
        # Similarity alone never suppresses work. Only a byte-stable source-row
        # fingerprint match against persisted metadata qualifies as a duplicate.
        dup = {"log_id": exact_prior} if exact_prior else None
        if dup:
            inc.is_duplicate_of = exact_prior
        # NOVA -> ATLAS: specialist + diagnosis + ticket (C)
        crew_id, why = registry.dispatch(by_id, "ATLAS", engineer.resolve_specialist,
                                         row=row, roster=roster, neighbors=neighbors)
        registry.log_activity(state_dir, "ATLAS", "resolve", {"crew_id": crew_id, "why": why})
        inc.routed_to = crew_id
        inc.trace.append("NOVA->ATLAS routed %s (%s)" % (crew_id, why))
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
        # NOVA -> AEGIS: gate the notification before PULSE sends
        mail_ok, mail_why, mail_esc = (True, ["routine"], False)
        if inc.status != "needs_review" and not dup:
            mail_ok, mail_why, mail_esc = safety.validate_action(
                {"kind": "notify", "crew_id": crew_id, "log_id": lid}, by_id, state_dir)
        registry.log_activity(state_dir, "AEGIS", "gate-notify",
                              {"pass": mail_ok, "reasons": mail_why}, ok=mail_ok)
        inc.trace.append("NOVA->AEGIS notify %s" % ("PASS" if mail_ok else "REJECT"))
        # comms (E): notify unless gated out, low-confidence review, or duplicate
        if inc.status == "needs_review" or dup or not mail_ok:
            if mail_esc:
                inc.status = "needs_review"
            inc.notification = NotificationStatus(
                channel="local-outbox", status="suppressed", path="",
            )
            inc.trace.append("NOVA->PULSE suppressed: %s" % inc.status)
            registry.log_activity(state_dir, "PULSE", "suppress", {"status": inc.status})
        else:
            inc.notification = NotificationStatus(**communications.send(
                state_dir, lid, crew_id, crew_name, inc.predicted_module,
                proba, priority, findings, neighbors))
            inc.trace.append("NOVA->PULSE dispatched %s" % inc.notification.status)
            registry.log_activity(state_dir, "PULSE", "send",
                                  {"path": inc.notification.path})
        # NOVA -> AEGIS -> ORBIT: gate then book
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
            gate_ok, gate_why, gate_esc = safety.validate_action(
                {"kind": "schedule", "crew_id": crew_id, "log_id": lid,
                 "row": {"log_id": lid, **job}}, by_id, state_dir)
            registry.log_activity(state_dir, "AEGIS", "gate-schedule",
                                  {"pass": gate_ok, "reasons": gate_why}, ok=gate_ok)
            inc.trace.append("NOVA->AEGIS schedule %s" % ("PASS" if gate_ok else "REJECT"))
            if not gate_ok:
                if gate_esc:
                    inc.status = "needs_review"
                inc.schedule = ScheduleStatus(state="failed", row=",".join([lid, crew_id]),
                                              reason="; ".join(gate_why))
                registry.log_activity(state_dir, "ORBIT", "reject",
                                      {"reasons": gate_why}, ok=False)
            else:
                ok, reason = logistics.append_booking(
                    sched_path, {"log_id": lid, **job}, roster_ids)
                inc.repair = RepairProposal(**job)
                inc.schedule = ScheduleStatus(state="done" if ok else "failed",
                                              row=",".join([lid, job["crew_id"]]),
                                              reason=reason)
                inc.trace.append("NOVA->ORBIT booked %s" % reason)
                registry.log_activity(state_dir, "ORBIT", "book", {"reason": reason}, ok=ok)
        # historian: persist AFTER actions so memory holds outcomes
        if mem is not None:
            try:
                mem.add(lid, str(row.get("message", "")),
                        {"module": inc.predicted_module, "verdict": verdict,
                         "crew": crew_id, "priority": priority,
                         "fingerprint": fingerprint})
                mem_status = mem.report()
                registry.log_activity(state_dir, "ECHO", "persist", {"log_id": lid})
            except Exception as exc:
                detail = "persist %s: %s" % (type(exc).__name__, exc)
                memory_errors.append(detail)
                inc.trace.append("NOVA->ECHO degraded: " + detail)
        else:
            inc.trace.append("NOVA->ECHO unavailable: incident actions continued")
        registry.log_activity(state_dir, "NOVA", "close",
                              {"status": inc.status,
                               "sched": inc.schedule.state, "mail": inc.notification.status})
        inc.trace.append("memory=%s specialist=%s (%s)" % (mem_name, crew_id, why))
        seen[lid] = "processed"
        log_trace(state_dir, {"log_id": lid, "incident": inc.model_dump(),
                              "ts": datetime.now(timezone.utc).isoformat()})
        results.append(inc.model_dump())
    json.dump(seen, open(seen_path, "w"))
    # post-incident report (F)
    n_fault = sum(1 for r in results if r.get("verdict") == 1)
    rep = os.path.join(state_dir, "reports", "run_report.md")
    recurrence_path = os.path.join(state_dir, "reports", "recurrence.md")
    recurrence = analyze_recurrence(results)
    render_report(recurrence, recurrence_path)
    with open(rep, "w") as f:
        f.write("# Run report\n\nlogs=%d genuine=%d backend=%s memory_records=%d\n\n" %
                (len(results), n_fault, mem_status.get("backend", mem_name),
                 mem_status.get("record_count", 0)))
        if memory_errors:
            f.write("Memory degraded; actions continued without some history operations:\n\n")
            for error in memory_errors:
                f.write("- %s\n" % error)
            f.write("\n")
        f.write("Recurrence report: `recurrence.md` (counts are for this run).\n\n")
        for r in results:
            if r.get("verdict") == 1:
                f.write("- %s p=%s pri=%s spec=%s sched=%s mail=%s\n" % (
                    r["log_id"], r.get("proba"), r["risk"]["urgency"], r.get("routed_to"),
                    r["schedule"].get("state"), r["notification"].get("status")))
    print("logs=%d genuine=%d report=%s" % (len(results), n_fault, rep))
    return results
