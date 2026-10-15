import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from memory.historian import TfidfMemory
from tools.recurrence import analyze_recurrence, write_report


def test_tfidf_restart_preserves_ids_metadata_and_report(tmp_path):
    path = str(tmp_path / "memory")
    first = TfidfMemory(path)
    first.add("INC-17", "oxygen scrubber pressure falling", {
        "module": "Life-Support", "verdict": 1, "crew": "C-LIFE",
        "fingerprint": "exact-row-hash"})
    assert first.add("INC-17", "replacement must not win", {"module": "Other"}) == "INC-17"

    restarted = TfidfMemory(path)
    hits = restarted.query("oxygen scrubber pressure", k=1, module="Life-Support")
    assert hits[0]["log_id"] == "INC-17"
    assert hits[0]["metadata"]["crew"] == "C-LIFE"
    assert restarted.docs[0]["crew"] == "C-LIFE"
    assert restarted.find_exact("exact-row-hash", "Life-Support") == "INC-17"
    assert restarted.find_exact("near-match", "Life-Support") is None
    assert restarted.report() == {
        "backend": "tfidf", "record_count": 1, "persisted": True,
        "search": "tf-idf lexical similarity"}


def test_corrupt_memory_has_clear_diagnostic(tmp_path):
    path = tmp_path / "memory"
    path.mkdir()
    (path / "docs.json").write_text("{bad json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid historian state.*docs.json"):
        TfidfMemory(str(path))


def test_empty_memory_and_query_are_predictable(tmp_path):
    memory = TfidfMemory(str(tmp_path / "memory"))
    assert memory.query("", k=3) == []
    assert memory.query("anything", k=0) == []
    assert memory.query("anything", k=3) == []


def test_recurrence_counts_only_explicit_links_and_reports_run_scope(tmp_path):
    rows = [
        {"log_id": "A", "incident": {"log_id": "A", "verdict": 1,
         "predicted_module": "Life-Support", "neighbors": []}},
        {"log_id": "B", "incident": {"log_id": "B", "verdict": 1,
         "predicted_module": "Life-Support", "is_duplicate_of": "A",
         "schedule": {"state": "skipped"}, "neighbors": [{"log_id": "A", "score": .99}]}},
        {"log_id": "C", "incident": {"log_id": "C", "verdict": 1,
         "predicted_module": "unknown", "neighbors": [{"log_id": "A", "score": .98}]}},
        {"log_id": "N", "incident": {"log_id": "N", "verdict": 0,
         "predicted_module": "Life-Support"}},
    ]
    facts = analyze_recurrence(rows, burst_threshold=2)
    assert facts["scope"] == "this run"
    assert facts["genuine_fault_count"] == 3
    assert facts["faults_by_module"] == {"Life-Support": 2, "unknown": 1}
    assert facts["duplicate_links"] == [{
        "log_id": "B", "prior_log_id": "A", "suppressed": True}]
    assert facts["similar_without_duplicate_link"] == [{
        "log_id": "C", "neighbor_ids": ["A"]}]
    assert facts["repeat_offenders"] == [{"log_id": "A", "repeat_count": 1}]
    assert facts["module_bursts"] == [{
        "module": "Life-Support", "fault_count": 2, "threshold": 2}]


def test_faiss_restart_rebuilds_missing_index(tmp_path):
    pytest.importorskip("faiss")
    from memory.historian import FaissMemory

    path = str(tmp_path / "memory")
    first = FaissMemory(path)
    first.add("INC-29", "antenna dish actuator stalled", {
        "module": "Antenna", "verdict": 1, "crew": "C-ANT"})
    os.unlink(os.path.join(path, "index.faiss"))
    restarted = FaissMemory(path)
    hits = restarted.query("antenna dish actuator stalled", k=1, module="Antenna")
    assert hits[0]["log_id"] == "INC-29"
    assert restarted.docs[0]["crew"] == "C-ANT"
def test_recurrence_report_reads_trace_jsonl(tmp_path):
    trace = tmp_path / "trace.jsonl"
    trace.write_text(json.dumps({"log_id": "X", "incident": {
        "log_id": "X", "verdict": 1, "predicted_module": "Antenna",
        "is_duplicate_of": "W", "schedule": {"state": "skipped"}}}) + "\n",
        encoding="utf-8")
    output = tmp_path / "reports" / "recurrence.md"
    facts = write_report(str(trace), str(output))
    assert facts["suppressed_duplicate_ids"] == ["X"]
    assert "Scope: **trace records**" in output.read_text(encoding="utf-8")
    assert "prior `W` (suppressed duplicate)" in output.read_text(encoding="utf-8")
