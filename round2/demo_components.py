"""Per-crew demos: AEGIS, ECHO, LYRA, ATLAS, ORBIT, PULSE + forensics/tickets/ack.
Run from round2/:  python demo_components.py   (offline, FAISS optional)"""
import json
import os
import sys

os.environ["JIRA_ENABLED"] = "0"  # component demo stays offline; live path proven separately

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

ROW = {"log_id": "D1", "timestamp": "2187-03-14 21:29:53", "module": "Life-Support",
       "mode": "ALERT", "node": "N4", "status": "CRIT", "reading": 16.7,
       "delay_ms": 1500, "retry_count": 3,
       "message": "NINE: nothing to see. O2 partial pressure falling [Life-Support 16.7 %O2]"}


def head(name):
    print("\n===== %s =====" % name)


head("AEGIS safety gate (pass / reject / overlap / duplicate)")
from crew import safety  # noqa: E402
_, by_id = __import__("crew.registry", fromlist=["x"]).load_registry("config/crew.json")
good = {"log_id": "D1", "crew_id": "C-LIFE", "start": "2187-04-15T08:30:00+00:00",
        "end": "2187-04-15T10:30:00+00:00", "job": "Inspect O2"}
print("valid booking:", safety.validate_action(
    {"kind": "schedule", "crew_id": "C-LIFE", "log_id": "D1", "row": good}, by_id, ".")[0])
print("unknown crew:", safety.validate_action(
    {"kind": "schedule", "crew_id": "C-XX", "log_id": "D1", "row": good}, by_id, "."))
print("bad interval:", safety.validate_action(
    {"kind": "schedule", "crew_id": "C-LIFE", "log_id": "D1",
     "row": dict(good, end="2187-04-15T07:00:00+00:00")}, by_id, "."))

head("ECHO historian (add / query / persist / reload / report)")
from memory.historian import open_memory  # noqa: E402
import shutil
shutil.rmtree("_demomem", ignore_errors=True)
mem, backend = open_memory("_demomem", backend="auto")
mem.add("D1", ROW["message"], {"module": "Life-Support", "verdict": 1})
print("backend:", backend, "| query:", mem.query("O2 partial pressure falling", k=1))
mem2, _ = open_memory("_demomem", backend="auto")
print("reload hits:", mem2.query("O2 partial pressure falling", k=1)[0]["log_id"],
      "| report:", mem2.report())
shutil.rmtree("_demomem", ignore_errors=True)

head("LYRA triage (deterministic; Laya when available)")
from crew import triage  # noqa: E402
r = triage.assess(dict(ROW), 0.95, use_laya=False)
print("urgency:", r["urgency"], "| score:", r["score"], "| source:", r["source"])
print("rationale:", r["rationale"])

head("ATLAS engineer (resolve + diagnose + repair + ticket)")
from crew import engineer  # noqa: E402
roster = engineer.load_roster("config/crew.json")
cid, why = engineer.resolve_specialist(ROW, [c for c in roster if c.get("kind") == "specialist"])
print("specialist:", cid, "(%s)" % why)
print("findings:", engineer.diagnose(ROW, 0.95))
print("job:", engineer.propose_job(ROW, cid, ".")["job"])

head("ORBIT logistics (audit + append + overlap reject)")
from crew import logistics  # noqa: E402
os.makedirs("_demost", exist_ok=True)
sp = "_demost/sched.csv"
if os.path.exists(sp):
    os.remove(sp)
print("append:", logistics.append_booking(sp, {"log_id": "D1", **{k: v for k, v in {
    "crew_id": "C-LIFE", "start": "2187-04-15T08:30:00+00:00",
    "end": "2187-04-15T10:30:00+00:00", "job": "Inspect O2"}.items()}}))
print("overlap rejected:", logistics.append_booking(sp, {"log_id": "D2", "crew_id": "C-LIFE",
      "start": "2187-04-15T09:00:00+00:00", "end": "2187-04-15T11:00:00+00:00", "job": "x"}))
print("audit:", logistics.schedule_audit_main(sp))
shutil.rmtree("_demost", ignore_errors=True)

head("PULSE comms (send + ledger + idempotent resend)")
from crew import communications  # noqa: E402
os.makedirs("_democom", exist_ok=True)
print("send:", communications.send("_democom", "D1", "C-LIFE", "A. Reyes",
                                    "Life-Support", 0.95, "critical", ["O2 falling"], [])["status"])
print("resend:", communications.send("_democom", "D1", "C-LIFE", "A. Reyes",
                                      "Life-Support", 0.95, "critical", ["O2 falling"], [])["status"])
shutil.rmtree("_democom", ignore_errors=True)

head("FORENSICS (store + timeline + report)")
from forensics import record_incident, build_timeline  # noqa: E402
os.makedirs("_demofor", exist_ok=True)
sp, md, rp = record_incident("_demofor", {"log_id": "D1", "verdict": 1, "proba": 0.95,
    "predicted_module": "Life-Support", "risk": r, "routed_to": "C-LIFE",
    "neighbors": [], "notification": {"status": "queued"}, "schedule": {"state": "done"},
    "trace": ["classified verdict=1"]})
print("stored:", sp, "| report:", rp, "| timeline events:",
      len(build_timeline("_demofor", "D1")))
shutil.rmtree("_demofor", ignore_errors=True)

head("TICKETS (dry-run queue + idempotency, no creds needed)")
from tickets import ticket_escalation  # noqa: E402
os.makedirs("_demotix", exist_ok=True)
out1 = ticket_escalation("_demotix", {"log_id": "D1", "verdict": 1,
    "risk": {"urgency": "critical", "score": 5, "rationale": ["disagree"],
             "source": "laya+rules", "escalate": True, "contradiction": False},
    "routed_to": "C-LIFE", "neighbors": [], "notification": {"status": "queued"},
    "schedule": {"state": "done"}}, {"type": "disagreement", "reason": "demo"})
out2 = ticket_escalation("_demotix", {"log_id": "D1", "verdict": 1,
    "risk": {"urgency": "critical"}, "routed_to": "C-LIFE"},
    {"type": "disagreement", "reason": "demo"})
print("first:", out1["status"], "| replay:", out2["status"], "|",
      "no duplicate" in out2["detail"])
shutil.rmtree("_demotix", ignore_errors=True)

head("ACK (assign / ack / timeout-escalate, injectable clock)")
from ack import assign_owner, acknowledge, sweep  # noqa: E402
os.makedirs("_demoack", exist_ok=True)
assign_owner("_demoack", "D1", "C-LIFE", timeout_s=60,
             now_iso="2026-10-15T00:00:00+00:00")
print("ack in time:", acknowledge("_demoack", "D1", by="C-LIFE",
                                  now_iso="2026-10-15T00:00:30+00:00")["status"])
assign_owner("_demoack", "D2", "C-PWR", timeout_s=60,
             now_iso="2026-10-15T00:00:00+00:00")
print("timeout sweep:", sweep("_demoack", now_iso="2026-10-15T00:05:00+00:00"))
shutil.rmtree("_demoack", ignore_errors=True)
print("\nALL COMPONENT DEMOS DONE")
