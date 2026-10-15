"""Ticket/alert integration tests (mocked HTTP, offline)."""
import csv
import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import tickets  # noqa: E402
from tickets import (JiraError, build_description_md, create_ticket,  # noqa: E402
                     reconcile, retry_pending, ticket_escalation)

INC = {"log_id": "L1", "verdict": 1, "proba": 0.95,
       "predicted_module": "Life-Support",
       "raw": {"module": "Life-Support", "status": "CRIT", "reading": 16.7,
               "delay_ms": 1500, "retry_count": 3, "mode": "ALERT",
               "message": "NINE: nothing to see. O2 falling"},
       "risk": {"urgency": "critical", "score": 5, "escalate": True,
                "contradiction": True, "rationale": ["laya=low vs deterministic=critical disagree >1 level"],
                "source": "laya+rules"},
       "routed_to": "C-LIFE",
       "neighbors": [{"log_id": "L0", "score": 0.91}],
       "notification": {"channel": "local-outbox", "status": "queued", "path": "outbox/L1.eml"},
       "schedule": {"state": "done", "row": "L1,C-LIFE", "reason": "appended"},
       "repair": {"job": "Inspect Life-Support"}}

ESC = {"incident_id": "L1", "log_id": "L1", "type": "disagreement",
       "reason": "priority split", "ts": "2026-10-15T00:00:00+00:00"}


class FakeProvider:
    provider = "jira"

    def __init__(self, script):
        self.script = list(script)
        self.posts = 0

    def create_issue(self, request):
        self.posts += 1
        action = self.script.pop(0) if self.script else ("ok", "AUR-1")
        if action[0] == "ok":
            return {"provider": "jira", "key": action[1],
                    "url": "https://x/browse/" + action[1],
                    "status": "created", "detail": "mocked"}
        raise action[1]

    def search_by_label(self, label):
        return getattr(self, "hits", [])


def test_auth_error_failed_not_created(tmp_path):
    p = FakeProvider([("err", JiraError("Jira HTTP 401: Unauthorized", retryable=False))])
    req = {"incident_id": "L9", "log_id": "L9", "escalation_type": "ack-timeout",
           "priority": "high", "summary": "s", "description_md": "d"}
    res = create_ticket(req, str(tmp_path), p)
    assert res["status"] == "failed" and res["key"] is None
    pend = [json.loads(l) for l in open(os.path.join(str(tmp_path), "state", "jira_pending.jsonl"))]
    assert pend and pend[0]["retryable"] is False


def test_transient_then_retry_succeeds(tmp_path):
    st = str(tmp_path)
    bad = FakeProvider([("err", JiraError("Jira HTTP 503", retryable=True))])
    req = {"incident_id": "L2", "log_id": "L2", "escalation_type": "disagreement",
           "priority": "critical", "summary": "s", "description_md": "d"}
    r1 = create_ticket(req, st, bad)
    assert r1["status"] == "failed"
    good = FakeProvider([("ok", "AUR-2")])
    out = retry_pending(st, good)
    assert out and out[0]["status"] == "created" and out[0]["key"] == "AUR-2"


def test_timeout_reconciles_without_duplicate_post(tmp_path):
    st = str(tmp_path)
    down = FakeProvider([("err", JiraError("Jira network error: timeout", retryable=True))])
    req = {"incident_id": "L3", "log_id": "L3", "escalation_type": "disagreement",
           "priority": "high", "summary": "s", "description_md": "d"}
    assert create_ticket(req, st, down)["status"] == "failed"
    finder = FakeProvider([])
    finder.hits = [{"key": "AUR-3", "url": "https://x/browse/AUR-3", "summary": "s"}]
    adopted = reconcile(st, req, finder)
    assert adopted["key"] == "AUR-3" and "no duplicate" in adopted["detail"]
    assert finder.posts == 0
    again = create_ticket(req, st, finder)  # idempotent replay via map
    assert "no duplicate" in again["detail"] and finder.posts == 0


def test_description_has_report_sections():
    md = build_description_md(INC, "disagreement", "priority split")
    for section in ["Identity", "Verdict", "Priority assessment", "Telemetry",
                    "Similar past incidents", "Actions", "Unresolved",
                    "L1", "C-LIFE", "disagreement"]:
        assert section in md, section


def _row(lid="L1", **kw):
    r = {"log_id": lid, "timestamp": "2187-03-14 21:29:53", "module": "Life-Support",
         "mode": "ALERT", "node": "N4", "status": "CRIT", "reading": 16.7,
         "delay_ms": 1500, "retry_count": 3,
         "message": "NINE: seal breach suspected [Life-Support 16.7 V]"}
    r.update(kw)
    return r


def _csv(path, rows):
    import pandas as pd  # noqa
    cols = ["log_id", "timestamp", "module", "mode", "node", "status",
            "reading", "delay_ms", "retry_count", "message"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _assess_disagree(row, proba, use_laya=True):
    return {"urgency": "critical", "score": 4, "escalate": True,
            "contradiction": False,
            "rationale": ["laya=critical vs deterministic=low disagree >1 level"],
            "source": "laya+rules"}


def test_alert_attempted_when_ticket_fails(monkeypatch, tmp_path):
    from orchestrator import run
    import tickets as tmod
    monkeypatch.setattr(tmod, "ticket_escalation",
                        lambda *a, **k: {"provider": "jira", "key": None,
                                         "url": None, "status": "failed",
                                         "detail": "forced failure"})
    monkeypatch.setattr("crew.triage.assess", _assess_disagree)
    inp = os.path.join(str(tmp_path), "in.csv")
    _csv(inp, [_row("L1")])
    kit = os.path.join(os.path.dirname(__file__), "..", "..", "rogue-protocol")
    res = run(inp, os.path.join(str(tmp_path), "st"), kit, use_laya=True)
    g = [r for r in res if r.get("verdict") == 1][0]
    assert g["notification"]["status"] in ("queued", "sent")
    assert os.path.exists(os.path.join(str(tmp_path), "st", "outbox", "L1.eml"))


def test_ticket_created_when_alert_fails(monkeypatch, tmp_path):
    from orchestrator import run
    import crew.communications as comms
    import tickets as tmod
    seen = {}

    def boom(*a, **k):
        raise IOError("smtp down")

    def fake_ticket(state_dir, incident, escalation, provider=None):
        seen["called"] = True
        return {"provider": "jira", "key": None, "url": None,
                "status": "queued", "detail": "dry-run queued"}

    monkeypatch.setattr(comms, "send", boom)
    monkeypatch.setattr(tmod, "ticket_escalation", fake_ticket)
    monkeypatch.setattr("crew.triage.assess", _assess_disagree)
    inp = os.path.join(str(tmp_path), "in.csv")
    _csv(inp, [_row("L1")])
    kit = os.path.join(os.path.dirname(__file__), "..", "..", "rogue-protocol")
    res = run(inp, os.path.join(str(tmp_path), "st"), kit, use_laya=True)
    g = [r for r in res if r.get("verdict") == 1][0]
    assert g["notification"]["status"] == "failed"
    assert seen.get("called") is True  # ticket still attempted
    assert any("disagree" in r for r in g["risk"]["rationale"])


def test_false_alarm_creates_no_ticket(tmp_path):
    from orchestrator import run
    inp = os.path.join(str(tmp_path), "in.csv")
    _csv(inp, [_row("L9", message="NINE: noted. periodic report [Lab-Power 12.1 V]",
                    status="OK", reading=12.1, delay_ms=100, retry_count=0)])
    kit = os.path.join(os.path.dirname(__file__), "..", "..", "rogue-protocol")
    st = os.path.join(str(tmp_path), "st")
    run(inp, st, kit, use_laya=False)
    for f in ("jira_queue.jsonl", "jira_map.json", "jira_pending.jsonl"):
        assert not os.path.exists(os.path.join(st, "state", f)), f


def test_timeline_records_ticket_outcome(monkeypatch, tmp_path):
    from orchestrator import run
    import tickets as tmod
    monkeypatch.setattr(tmod, "ticket_escalation",
                        lambda *a, **k: {"provider": "jira", "key": "AUR-9",
                                         "url": "https://x/browse/AUR-9",
                                         "status": "created", "detail": "mocked"})
    monkeypatch.setattr("crew.triage.laya_assess",
                        lambda m: {"priority": "low", "escalate": False,
                                   "contradiction": False})
    inp = os.path.join(str(tmp_path), "in.csv")
    _csv(inp, [_row("L1")])
    kit = os.path.join(os.path.dirname(__file__), "..", "..", "rogue-protocol")
    st = os.path.join(str(tmp_path), "st")
    run(inp, st, kit, use_laya=True)
    trace = open(os.path.join(st, "trace.jsonl"), encoding="utf-8").read()
    assert "AUR-9" in trace
    from forensics import build_timeline
    tl = build_timeline(st, "L1")
    assert any("AUR-9" in str(e) for e in tl)
    assert [e["ts"] for e in tl] == sorted(e["ts"] for e in tl)
