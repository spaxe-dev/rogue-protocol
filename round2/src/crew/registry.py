"""Crew registry: load, validate, dispatch. Single source of truth: config/crew.json."""
import json
import os

REQUIRED = ["crew_id", "name", "callsign", "rank", "role", "specialties", "personality",
            "communication_style", "tools", "input_contract", "output_contract",
            "escalation_target", "availability", "avatar_emoji"]


def load_registry(path):
    with open(path, encoding="utf-8") as f:
        crew = json.load(f)["crew"]
    ids = [c["crew_id"] for c in crew]
    assert len(ids) == len(set(ids)), "duplicate crew_id"
    for field in ("callsign", "avatar_emoji"):
        vals = [c[field] for c in crew]
        assert len(vals) == len(set(vals)), "duplicate " + field
    by_id = {c["crew_id"]: c for c in crew}
    for c in crew:
        for k in REQUIRED:
            assert k in c, "%s missing %s" % (c.get("crew_id"), k)
        assert c["escalation_target"] in by_id, "%s bad escalation %s" % (c["crew_id"], c["escalation_target"])
        for t in c["tools"]:
            assert t in TOOLS, "%s unknown tool %s" % (c["crew_id"], t)
    return crew, by_id


def log_activity(state_dir, crew_id, action, detail, ok=True):
    d = os.path.join(state_dir, "state", "activity")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, crew_id + ".jsonl"), "a") as f:
        f.write(json.dumps({"crew_id": crew_id, "action": action,
                            "detail": detail, "ok": ok}) + "\n")


def dispatch(by_id, crew_id, handler, **ctx):
    """Resolve crew_id to a real handler; reject unknown IDs safely."""
    if crew_id not in by_id:
        raise ValueError("unknown crew_id %r" % crew_id)
    return handler(**ctx)


from crew import triage, engineer, logistics, communications, safety  # noqa: E402
from memory.historian import open_memory  # noqa: E402
from tools import deception_detector  # noqa: E402


def _h_triage(row, proba, use_laya=True):
    return triage.assess(row, proba, use_laya=use_laya)


TOOLS = {
    "classify_log": None,  # wired by orchestrator (classifier adapter)
    "create_incident": None,  # orchestrator-owned
    "dispatch_crew": None,  # orchestrator-owned (dispatch below)
    "record_trace": None,  # orchestrator-owned
    "assess_risk": _h_triage,
    "detect_deception": deception_detector.detect,
    "resolve_specialist": engineer.resolve_specialist,
    "diagnose_fault": engineer.diagnose,
    "propose_repair": engineer.propose_job,
    "file_ticket": engineer.file_ticket,
    "memory_add": None,  # store-bound, wired at runtime
    "memory_query": None,  # store-bound, wired at runtime
    "append_booking": logistics.append_booking,
    "audit_schedule": logistics.schedule_audit_main,
    "send_notification": communications.send,
    "validate_action": safety.validate_action,
}

OFFICER_CHAIN = ["NOVA", "LYRA", "ECHO", "ATLAS", "AEGIS", "ORBIT", "PULSE"]
