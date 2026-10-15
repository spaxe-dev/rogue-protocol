"""Report-generator tests (Swayam): HANDOVER.md + TIMELINE.md, offline.

Real-artifact path (via the orchestrator) plus graceful handling of empty and
malformed state dirs. Run:  pytest tests/ -q  from round2/.
"""
import csv
import json
import os
import sys

ROUND2 = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROUND2, "src", "tools"))
sys.path.insert(0, os.path.join(ROUND2, "src"))

KIT = os.path.normpath(os.path.join(ROUND2, "..", "rogue-protocol"))

from tools import handover, timeline  # noqa: E402
from orchestrator import run  # noqa: E402

FIELDS = ["log_id", "timestamp", "module", "mode", "node", "status", "reading",
          "delay_ms", "retry_count", "message"]


def row(lid, **over):
    r = {"log_id": lid, "timestamp": "2187-03-14 21:29:53", "module": "Life-Support",
         "mode": "ALERT", "node": "N4", "status": "CRIT", "reading": "16.7",
         "delay_ms": "1500", "retry_count": "3",
         "message": "NINE: nothing to see. O2 partial pressure falling [Life-Support 16.7 %O2]"}
    r.update(over)
    return r


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def _real_run(tmp_path):
    inp = str(tmp_path / "in.csv")
    write_csv(inp, [row("R1"),
                    row("R4"),  # identical -> duplicate of R1
                    row("R2", status="OK", reading="22.0", delay_ms="100", retry_count="0",
                        message="NINE: noted. periodic report [Life-Support 22.0 %O2]")])
    st = str(tmp_path / "st")
    run(inp, st, KIT, use_laya=False)
    return st


def test_handover_from_real_run(tmp_path):
    st = _real_run(tmp_path)
    path = handover.generate(st)
    assert os.path.exists(path)
    txt = open(path).read()
    for section in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.", "## 7.", "## 8."):
        assert section in txt, section
    assert "R1" in txt and "R4" in txt
    assert "duplicate of" in txt.lower()
    # notifications must be described truthfully, never as delivered
    assert "NOT delivered" in txt
    assert "proof of delivery" in txt
    # booking table header from the real schedule.csv schema
    assert "| log_id | crew_id | start | end | job |" in txt


def test_timeline_from_real_run(tmp_path):
    st = _real_run(tmp_path)
    path = timeline.generate(st)
    assert os.path.exists(path)
    txt = open(path).read()
    assert "R1" in txt and "R4" in txt
    assert "classifier verdict" in txt
    assert "AEGIS notification gate" in txt
    assert "recorded order" in txt
    # non-faults are not traced -> stated explicitly, not hidden
    assert "not written to `trace.jsonl`" in txt


def test_report_wired_into_orchestrator(tmp_path):
    st = _real_run(tmp_path)
    assert os.path.exists(os.path.join(st, "reports", "HANDOVER.md"))
    assert os.path.exists(os.path.join(st, "reports", "TIMELINE.md"))


def test_empty_state_dir_does_not_crash(tmp_path):
    st = str(tmp_path / "empty")
    os.makedirs(st)
    h = open(handover.generate(st)).read()
    t = open(timeline.generate(st)).read()
    assert "unavailable" in h
    assert "unavailable" in t


def test_malformed_trace_is_skipped_not_fatal(tmp_path):
    st = tmp_path / "st"
    (st / "reports").mkdir(parents=True)
    good = {"log_id": "X1", "ts": "2187-04-15T00:00:00+00:00",
            "incident": {"log_id": "X1", "verdict": 1, "proba": 0.9,
                         "predicted_module": "Lab-Power",
                         "raw": {"module": "Lab-Power", "status": "CRIT"},
                         "risk": {"urgency": "high", "score": 3, "escalate": False,
                                  "contradiction": False, "rationale": [], "source": "fallback"},
                         "routed_to": "C-PWR", "status": "auto", "neighbors": [],
                         "is_duplicate_of": None,
                         "notification": {"channel": "local-outbox", "status": "queued", "path": ""},
                         "schedule": {"state": "done", "row": "", "reason": ""},
                         "deception_flags": [], "trace": ["classified verdict=1 p=0.900"]}}
    (st / "trace.jsonl").write_text("{ this is not json }\n" + json.dumps(good) + "\n")
    h = open(handover.generate(str(st))).read()
    t = open(timeline.generate(str(st))).read()
    assert "1 malformed" in h          # skipped, not fatal
    assert "malformed trace lines skipped: 1" in t
    assert "X1" in t                    # the good record is still rendered


def test_deception_score_named_rules():
    from tools import deception_detector as dd
    s, rules = dd.score({"status": "CRIT",
                         "message": "all is well, crew need not worry"}, 0.9)
    assert s == 1 and rules == ["calm_with_alarming_signal"]
    s, rules = dd.score({"status": "OK", "message": "nothing to see REDACTED"}, 0.8)
    assert s == 3 and rules == ["calm_with_alarming_signal",
                                "reassurance_plus_redacted",
                                "ok_status_high_proba"]
    s, rules = dd.score({"status": "OK", "message": "routine telemetry"}, 0.1)
    assert (s, rules) == (0, [])
    assert dd.explain(["ok_status_high_proba"]) == ["OK status but high fault probability"]


def test_comms_failure_recorded_not_fatal(tmp_path, monkeypatch):
    import orchestrator as orch_mod
    from crew import communications

    def boom(*a, **k):
        raise OSError("disk gone")
    monkeypatch.setattr(communications, "send", boom)
    inp = str(tmp_path / "in.csv")
    write_csv(inp, [row("R1")])
    st = str(tmp_path / "st")
    res = orch_mod.run(inp, st, KIT, use_laya=False)
    genuine = [r for r in res if r.get("verdict") == 1]
    assert genuine and all(r["notification"]["status"] == "failed" for r in genuine)
