"""Forensics black-box tests (offline). Run: pytest tests/test_forensics.py -q from round2/."""
import importlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import forensics  # noqa: E402


def make_incident(lid="F1", **kw):
    inc = {
        "log_id": lid,
        "raw": {"log_id": lid, "timestamp": "2187-03-14 21:29:53",
                "module": "Life-Support", "mode": "ALERT", "node": "N4",
                "status": "CRIT", "reading": "16.7", "delay_ms": "1500",
                "retry_count": "3",
                "message": "NINE: nothing to see. O2 partial pressure falling"},
        "proba": 0.95,
        "verdict": 1,
        "predicted_module": "Life-Support",
        "risk": {"urgency": "critical", "score": 5, "escalate": True,
                 "contradiction": True,
                 "rationale": ["status=CRIT base=3",
                               "laya=x vs deterministic=y disagree >1 level -> escalate"],
                 "source": "laya+rules"},
        "routed_to": "C-LIFE",
        "status": "auto",
        "neighbors": [{"log_id": "OLD1", "score": 0.88, "module": "Life-Support",
                       "text": "oxygen falling"}],
        "is_duplicate_of": None,
        "repair": {"crew_id": "C-LIFE", "job": "inspect",
                   "start": "2187-04-15T08:30:00+00:00", "end": "2187-04-15T10:30:00+00:00"},
        "notification": {"channel": "local-outbox", "status": "queued", "path": "outbox/F1.eml"},
        "schedule": {"state": "done", "row": "F1,C-LIFE", "reason": "appended"},
        "deception_flags": [],
        "trace": ["classified verdict=1 p=0.950", "NOVA->LYRA assessed critical"],
    }
    inc.update(kw)
    return inc


class StubMemory:
    def __init__(self, hits):
        self._hits = hits

    def query(self, text, k=3, module=None):
        return list(self._hits[:k])


def test_id_stability_same_log_same_file_no_dup(tmp_path):
    st = str(tmp_path / "st")
    inc = make_incident("F1")
    p1 = forensics.store_incident(st, inc, threshold=0.54)
    assert p1.endswith(os.path.join("state", "incidents", "F1.json"))
    before = open(p1, encoding="utf-8").read()
    p2 = forensics.store_incident(st, dict(inc, proba=0.11), threshold=0.54)
    assert p1 == p2
    assert open(p1, encoding="utf-8").read() == before  # write-once, not overwritten
    assert forensics.list_incidents(st) == ["F1"]
    rec = forensics.get_incident(st, "F1")
    assert rec["incident_id"] == rec["log_id"] == "F1"  # incident_id = log_id


def test_timeline_chronological(tmp_path):
    st = str(tmp_path / "st")
    os.makedirs(st, exist_ok=True)
    with open(os.path.join(st, "trace.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"log_id": "F1", "ts": "2026-10-15T10:00:03+00:00",
                            "incident": {"trace": ["NOVA->ORBIT booked appended"]}}) + "\n")
        f.write(json.dumps({"log_id": "F1", "ts": "2026-10-15T10:00:01+00:00",
                            "incident": {"trace": ["classified verdict=1 p=0.950"]}}) + "\n")
        f.write(json.dumps({"log_id": "OTHER", "ts": "2026-10-15T09:00:00+00:00",
                            "incident": {"trace": ["classified nope"]}}) + "\n")
    with open(os.path.join(st, "tickets.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"incident_id": "F1", "module": "Life-Support",
                            "crew_id": "C-LIFE", "job": "inspect",
                            "priority": "critical", "ts": "2026-10-15T10:00:02+00:00"}) + "\n")
    with open(os.path.join(st, "dispatch_log.csv"), "w", newline="", encoding="utf-8") as f:
        f.write("log_id,crew_id,status,ts\nF1,C-LIFE,queued-local,2026-10-15T10:00:04+00:00\n")
    tl = forensics.build_timeline(st, "F1")
    assert len(tl) == 4
    for e in tl:
        assert set(e) == {"ts", "actor", "event", "detail"}
    tss = [e["ts"] for e in tl]
    assert tss == sorted(tss)
    assert all("OTHER" not in e["detail"] and e["detail"] != "classified nope" for e in tl)


def test_recurrence_evidence_thresholds():
    mem_dup = StubMemory([{"log_id": "D1", "score": 0.991, "module": "M", "text": "t"}])
    r = forensics.check_recurrence(mem_dup, "F9", "t")
    assert r["status"] == "confirmed-duplicate" and r["duplicate_of"] == "D1"

    mem_sim = StubMemory([{"log_id": "D2", "score": 0.85, "module": "M", "text": "t"}])
    r = forensics.check_recurrence(mem_sim, "F9", "t")
    assert r["status"] == "similar" and r["duplicate_of"] is None

    mem_low = StubMemory([{"log_id": "D3", "score": 0.79, "module": "M", "text": "t"}])
    r = forensics.check_recurrence(mem_low, "F9", "t")
    assert r["status"] == "no-evidence" and r["asserted"] == []

    mem_self = StubMemory([{"log_id": "F9", "score": 1.0, "module": "M", "text": "t"}])
    r = forensics.check_recurrence(mem_self, "F9", "t")
    assert r["status"] == "no-evidence"


def test_report_contains_all_sections(tmp_path):
    st = str(tmp_path / "st")
    forensics.store_incident(st, make_incident("F1"), threshold=0.54)
    md, path = forensics.generate_report(st, "F1")
    assert os.path.exists(path)
    for section in ("Incident ID", "Severity", "Evidence", "Decisions",
                    "Actions", "Schedule", "Historical matches", "Unresolved items"):
        assert section in md, section
    assert "F1" in md and "OLD1" in md and "0.88" in md


def test_restart_retrieval_fresh_process(tmp_path):
    st = str(tmp_path / "st")
    forensics.store_incident(st, make_incident("F7"), threshold=0.54)
    code = ("import sys, json; sys.path.insert(0, %r); "
            "from forensics import get_incident; "
            "rec = get_incident(%r, 'F7'); "
            "assert rec and rec['incident_id'] == 'F7'; "
            "print('restart-ok:' + rec['log_id'])" % (
                os.path.join(os.path.dirname(__file__), "..", "src"), st))
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "restart-ok:F7" in proc.stdout
    # Fresh import in-process also sees the plain-JSON store.
    fresh = importlib.reload(sys.modules["forensics"])
    assert fresh.get_incident(st, "F7")["log_id"] == "F7"
