"""Priority-pipeline tests (offline; Laya mocked — no download)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from crew import triage  # noqa: E402

ROW = {"log_id": "T1", "module": "Life-Support", "mode": "ALERT", "node": "N4",
       "status": "CRIT", "reading": 16.7, "delay_ms": 1500, "retry_count": 3,
       "message": "NINE: nothing to see. O2 partial pressure falling [Life-Support 16.7 %O2]"}


def test_genuine_laya_priority_flows_downstream(monkeypatch):
    monkeypatch.setattr(triage, "laya_assess",
                        lambda state: {"priority": "critical", "escalate": False,
                                       "contradiction": True})
    r = triage.assess(dict(ROW), 0.95, use_laya=True)
    assert r["urgency"] == "critical" and r["score"] == 4
    assert r["source"] == "laya+rules"
    assert any("laya choice" in x for x in r["rationale"])


def test_false_alarm_never_escalates():
    # Architectural truth: the VERDICT gate (not the score) keeps false alarms out
    # of response actions (see test_nonfault_triggers_nothing). Here: proba only
    # feeds the calm-contradiction branch — a benign row must never auto-escalate.
    benign = dict(ROW, status="OK", delay_ms=100, retry_count=0,
                  message="NINE: noted. periodic report [Lab-Power 12.1 V]")
    hi = triage.assess(benign, 0.9, use_laya=False)
    lo = triage.assess(benign, 0.05, use_laya=False)
    assert hi["score"] >= lo["score"]
    assert not lo["escalate"] and not hi["escalate"]


def test_invalid_laya_falls_back_explicitly(monkeypatch):
    for bad in ({"priority": "bogus", "escalate": False, "contradiction": False},):
        monkeypatch.setattr(triage, "laya_assess", lambda state: bad)
        r = triage.assess(dict(ROW), 0.9, use_laya=True)
        assert r["source"] == "fallback"
        assert any("fallback" in x for x in r["rationale"])
    def boom(state):
        raise RuntimeError("no checkpoint")
    monkeypatch.setattr(triage, "laya_assess", boom)
    r = triage.assess(dict(ROW), 0.9, use_laya=True)
    assert r["source"] == "fallback"


def test_disagreement_escalates(monkeypatch):
    monkeypatch.setattr(triage, "laya_assess",
                        lambda state: {"priority": "low", "escalate": False,
                                       "contradiction": False})
    r = triage.assess(dict(ROW), 0.95, use_laya=True)  # deterministic says critical
    assert r["urgency"] == "low" and r["escalate"] is True
    assert any("disagree" in x for x in r["rationale"])
