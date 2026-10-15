"""Crew registry acceptance tests (offline)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

ROSTER = os.path.join(os.path.dirname(__file__), "..", "config", "crew.json")


def test_registry_valid_unique():
    from crew import registry
    crew, by_id = registry.load_registry(ROSTER)
    assert len(crew) == 12 and len(by_id) == 12
    assert {"NOVA", "LYRA", "ATLAS", "ECHO", "ORBIT", "PULSE", "AEGIS"} <= set(by_id)


def test_tools_registered():
    from crew import registry
    crew, _ = registry.load_registry(ROSTER)
    for c in crew:
        for t in c["tools"]:
            assert t in registry.TOOLS, (c["crew_id"], t)


def test_dispatch_and_invalid_id():
    from crew import registry
    _, by_id = registry.load_registry(ROSTER)
    out = registry.dispatch(by_id, "LYRA", lambda row, proba, use_laya=True: {"ok": True},
                            row={}, proba=0.0)
    assert out == {"ok": True}
    with pytest.raises(ValueError):
        registry.dispatch(by_id, "NOPE", lambda: None)


def test_specialist_failure_escalates_logged(tmp_path):
    from crew import registry, safety
    _, by_id = registry.load_registry(ROSTER)
    ok, reasons, esc = safety.validate_action(
        {"kind": "schedule", "crew_id": "C-PWR", "log_id": "Z",
         "row": {"log_id": "Z", "crew_id": "C-PWR", "start": "bad",
                 "end": "worse", "job": "j"}}, by_id, str(tmp_path))
    assert not ok and reasons
    registry.log_activity(str(tmp_path), "AEGIS", "gate-schedule",
                          {"pass": ok, "reasons": reasons}, ok=ok)
    assert os.path.exists(os.path.join(str(tmp_path), "state", "activity", "AEGIS.jsonl"))


def test_dossier_matches_registry(tmp_path):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "tools"))
    from crew_dossier import generate
    path, n = generate(ROSTER, str(tmp_path / "dossier.md"))
    crew = json.load(open(ROSTER, encoding="utf-8"))["crew"]
    text = open(path, encoding="utf-8").read()
    assert n == len(crew)
    for c in crew:
        assert c["crew_id"] in text and c["callsign"] in text
