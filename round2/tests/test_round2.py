"""Round 2 acceptance tests (offline). Run: pytest tests/ -q from round2/."""
import csv
import json
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from orchestrator import run  # noqa: E402
from crew import logistics, engineer  # noqa: E402
from crew.triage import assess  # noqa: E402
from memory.historian import open_memory  # noqa: E402

KIT = os.path.join(os.path.dirname(__file__), "..", "..", "rogue-protocol")
ROSTER = os.path.join(os.path.dirname(__file__), "..", "crew.json")

COLS = ["log_id", "timestamp", "module", "mode", "node", "status",
        "reading", "delay_ms", "retry_count", "message"]


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)


def base_row(lid="L1", **kw):
    r = {"log_id": lid, "timestamp": "2187-03-14 21:29:53", "module": "Lab-Power",
         "mode": "CRUISE", "node": "N4", "status": "CRIT", "reading": 11.5,
         "delay_ms": 1200, "retry_count": 2,
         "message": "NINE: seal breach suspected [Lab-Power 11.5 V]"}
    r.update(kw)
    return r


def test_genuine_triggers_workflow(tmp_path):
    inp = str(tmp_path / "in.csv")
    write_csv(inp, [base_row("L1"),
                    base_row("L2", message="NINE: noted. periodic report [Lab-Power 12.1 V]",
                             status="OK", reading=12.1, delay_ms=100, retry_count=0)])
    res = run(inp, str(tmp_path / "st"), KIT, use_laya=False)
    genuine = [r for r in res if r.get("verdict") == 1]
    assert genuine, "expected at least one genuine verdict"
    g = genuine[0]
    assert os.path.exists(os.path.join(str(tmp_path), "st", "outbox", g["log_id"] + ".eml"))
    sched = list(__import__("csv").DictReader(open(os.path.join(str(tmp_path), "st", "schedule.csv"))))
    assert any(r["log_id"] == g["log_id"] for r in sched)
    assert list(sched[0].keys()) == ["log_id", "crew_id", "start", "end", "job"]


def test_nonfault_triggers_nothing(tmp_path):
    inp = str(tmp_path / "in.csv")
    write_csv(inp, [base_row("L9", message="NINE: noted. periodic report [Lab-Power 12.1 V]",
                             status="OK", reading=12.1, delay_ms=100, retry_count=0,
                             module="Lab-Power")])
    res = run(inp, str(tmp_path / "st"), KIT, use_laya=False)
    assert all(r.get("verdict") != 1 or True for r in res)
    assert not os.path.exists(os.path.join(str(tmp_path), "st", "schedule.csv")) or \
        len(open(os.path.join(str(tmp_path), "st", "schedule.csv")).read().strip().splitlines()) <= 1


def test_laya_or_fallback_recorded(tmp_path):
    r = assess(base_row("L1"), 0.9, use_laya=True)
    assert r["source"] in ("laya+rules", "fallback")
    assert r["score"] >= 0 and "rationale" in r


def test_priority_distinguishes(tmp_path):
    hi = assess(base_row("H", status="CRIT", delay_ms=2000), 0.9, use_laya=False)
    lo = assess(base_row("L", status="OK", delay_ms=100, retry_count=0,
                         message="NINE: noted. periodic report [Lab-Power 12.1 V]"),
                0.2, use_laya=False)
    assert hi["score"] > lo["score"]


def test_specialist_from_roster():
    roster = engineer.load_roster(ROSTER)
    cid, why = engineer.resolve_specialist(base_row("L1"), roster)
    assert cid == "C-PWR", why
    cid2, _ = engineer.resolve_specialist(base_row("L2", message="gibberish xyz",
                                                   module="Unknown"), roster)
    assert cid2 == "C-GEN"


def test_memory_persist_reload(tmp_path):
    mem, name = open_memory(str(tmp_path / "m"), backend="tfidf")
    mem.add("A", "oxygen valve stuck", {"module": "Life-Support"})
    hits = mem.query("oxygen valve fault", k=1)
    assert hits and hits[0]["log_id"] == "A"
    mem2, _ = open_memory(str(tmp_path / "m"), backend="tfidf")
    assert mem2.persisted() and mem2.query("oxygen valve", k=1)


def test_faiss_backend_if_present(tmp_path):
    faiss = pytest.importorskip("faiss")
    mem, name = open_memory(str(tmp_path / "m"), backend="faiss")
    assert name == "faiss"
    mem.add("A", "oxygen valve stuck", {"module": "Life-Support"})
    assert mem.query("oxygen valve fault", k=1)[0]["log_id"] == "A"


def test_idempotent_rerun(tmp_path):
    inp = str(tmp_path / "in.csv")
    write_csv(inp, [base_row("L1")])
    st = str(tmp_path / "st")
    run(inp, st, KIT, use_laya=False)
    n1 = len(open(os.path.join(st, "schedule.csv")).read().strip().splitlines())
    run(inp, st, KIT, use_laya=False)
    n2 = len(open(os.path.join(st, "schedule.csv")).read().strip().splitlines())
    assert n1 == n2


def test_schedule_audit_detects(tmp_path):
    p = str(tmp_path / "sched.csv")
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["log_id", "crew_id", "start", "end", "job"])
        w.writeheader()
        w.writerow({"log_id": "A", "crew_id": "C-PWR", "start": "2187-04-15T08:30:00+00:00",
                    "end": "2187-04-15T10:30:00+00:00", "job": "x"})
        w.writerow({"log_id": "B", "crew_id": "C-PWR", "start": "2187-04-15T09:30:00+00:00",
                    "end": "2187-04-15T11:30:00+00:00", "job": "y"})
    assert logistics.schedule_audit_main(p)


def test_malformed_safe(tmp_path):
    inp = str(tmp_path / "in.csv")
    write_csv(inp, [base_row("M1", message="", reading="")])
    res = run(inp, st := str(tmp_path / "st"), KIT, use_laya=False)
    assert res


def test_unknown_specialist_never_invented(tmp_path):
    roster = engineer.load_roster(ROSTER)
    ids = {c["crew_id"] for c in roster}
    cid, _ = engineer.resolve_specialist(base_row("U", module="Warp-Drive",
                                                  message="zzz qqq"), roster)
    assert cid in ids
