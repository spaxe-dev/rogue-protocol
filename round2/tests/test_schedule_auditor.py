"""Anubhav (validation) — schedule auditor acceptance tests (offline).

Run: pytest tests/test_schedule_auditor.py -q from round2/
Covers ANUBHAV_VALIDATION_AUDIT.md Phase C items 3,4,5,6,7,9 and Phase D
schedule cases at the auditor layer (no classifier/memory/live service needed).

Out of scope here (blocked on missing rogue-protocol/model.joblib, Aadit's
ownership): e2e fault/non-fault routing, Laya fallback, memory corruption,
live-delivery distinction. Those stay in test_round2.py once the model exists.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "tools"))

from schedule_auditor import HEADER, audit_file, audit_rows, main  # noqa: E402

CREW = {"C-PWR", "C-LIFE", "C-GEN"}


def write_sched(path, rows, header=HEADER):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in header})


def good_row(lid="L1", crew="C-PWR", start="2187-04-15T08:30:00+00:00",
             end="2187-04-15T10:30:00+00:00", job="Inspect Lab-Power"):
    return {"log_id": lid, "crew_id": crew, "start": start, "end": end, "job": job}


def test_valid_schedule_passes(tmp_path):
    p = str(tmp_path / "s.csv")
    write_sched(p, [good_row("A"), good_row("B", start="2187-04-15T11:00:00+00:00",
                                            end="2187-04-15T12:00:00+00:00")])
    r = audit_file(p, crew_ids=CREW)
    assert r["valid"] and r["findings"] == [] and r["rows"] == 2


def test_bad_header_rejected(tmp_path):
    p = str(tmp_path / "s.csv")
    write_sched(p, [good_row()], header=["log_id", "crew_id", "start", "end"])
    r = audit_file(p, crew_ids=CREW)
    assert not r["valid"] and r["findings"][0]["rule"] == "HEADER"


def test_missing_file():
    r = audit_file("/nonexistent/schedule.csv", crew_ids=CREW)
    assert not r["valid"] and r["findings"][0]["rule"] == "FILE_NOT_FOUND"


def test_empty_and_whitespace_job(tmp_path):
    p = str(tmp_path / "s.csv")
    write_sched(p, [good_row("A", job="   ")])
    rules = {f["rule"] for f in audit_file(p, crew_ids=CREW)["findings"]}
    assert "EMPTY_FIELD" in rules


def test_bad_datetime_parsed_not_string_compared(tmp_path):
    # String compare would say "worse" > "bad" (valid); parser must reject.
    p = str(tmp_path / "s.csv")
    write_sched(p, [good_row("Z", start="bad", end="worse")])
    rules = {f["rule"] for f in audit_file(p, crew_ids=CREW)["findings"]}
    assert "BAD_DATETIME" in rules


def test_end_before_start_and_zero_duration(tmp_path):
    p = str(tmp_path / "s.csv")
    write_sched(p, [good_row("A", start="2187-04-15T10:30:00+00:00",
                             end="2187-04-15T09:30:00+00:00"),
                    good_row("B", start="2187-04-15T08:00:00+00:00",
                             end="2187-04-15T08:00:00+00:00")])
    rules = [f["rule"] for f in audit_file(p, crew_ids=CREW)["findings"]]
    assert rules.count("END_BEFORE_START") == 2


def test_timezone_aware_comparison(tmp_path):
    # Same instant written with different offsets: string compare is wrong,
    # parsed comparison is right. 10:00+05:30 == 04:30Z < 05:00Z (valid).
    p = str(tmp_path / "s.csv")
    write_sched(p, [good_row("A", start="2187-04-15T10:00:00+05:30",
                             end="2187-04-15T05:00:00+00:00")])
    assert audit_file(p, crew_ids=CREW)["valid"]
    # Reverse is invalid in UTC but looks valid as strings ("10" > "05").
    write_sched(p, [good_row("A", start="2187-04-15T05:00:00+00:00",
                             end="2187-04-15T10:00:00+05:30")])
    rules = {f["rule"] for f in audit_file(p, crew_ids=CREW)["findings"]}
    assert "END_BEFORE_START" in rules


def test_unknown_crew_rejected(tmp_path):
    p = str(tmp_path / "s.csv")
    write_sched(p, [good_row("A", crew="NOPE")])
    r = audit_file(p, crew_ids=CREW)
    assert any(f["rule"] == "UNKNOWN_CREW" for f in r["findings"])
    write_sched(p, [good_row("A", crew="C-PWR")])
    assert audit_file(p, crew_ids=CREW)["valid"]


def test_duplicate_log_id_second_flagged(tmp_path):
    p = str(tmp_path / "s.csv")
    write_sched(p, [good_row("A"), good_row("A", start="2187-04-15T11:00:00+00:00",
                                            end="2187-04-15T12:00:00+00:00")])
    findings = audit_file(p, crew_ids=CREW)["findings"]
    dup = [f for f in findings if f["rule"] == "DUPLICATE_LOG_ID"]
    assert len(dup) == 1 and dup[0]["row"] == 2


def test_duplicate_job_text_allowed(tmp_path):
    p = str(tmp_path / "s.csv")
    write_sched(p, [good_row("A", job="same job"),
                    good_row("B", job="same job",
                             start="2187-04-15T11:00:00+00:00", end="2187-04-15T12:00:00+00:00")])
    assert audit_file(p, crew_ids=CREW)["valid"]


def test_same_crew_overlap_detected_cross_crew_allowed(tmp_path):
    p = str(tmp_path / "s.csv")
    write_sched(p, [good_row("A"), good_row("B", start="2187-04-15T09:30:00+00:00",
                                            end="2187-04-15T11:30:00+00:00")])
    assert any(f["rule"] == "OVERLAP"
               for f in audit_file(p, crew_ids=CREW)["findings"])
    write_sched(p, [good_row("A", crew="C-PWR"), good_row("B", crew="C-LIFE",
                    start="2187-04-15T09:30:00+00:00", end="2187-04-15T11:30:00+00:00")])
    assert audit_file(p, crew_ids=CREW)["valid"]


def test_malformed_extra_column(tmp_path):
    p = str(tmp_path / "s.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        f.write("log_id,crew_id,start,end,job\n")
        f.write("A,C-PWR,2187-04-15T08:30:00+00:00,2187-04-15T10:30:00+00:00,x,EXTRA\n")
    rules = {f["rule"] for f in audit_file(p, crew_ids=CREW)["findings"]}
    assert "MALFORMED_ROW" in rules


def test_read_only(tmp_path):
    p = str(tmp_path / "s.csv")
    write_sched(p, [good_row("A", crew="NOPE")])
    before = open(p, "rb").read()
    mtime = os.path.getmtime(p)
    audit_file(p, crew_ids=CREW)
    assert open(p, "rb").read() == before and os.path.getmtime(p) == mtime


def test_findings_shape(tmp_path):
    findings = audit_rows([good_row("A", crew="NOPE")], crew_ids=CREW)
    assert findings and all(set(f) == {"severity", "rule", "log_id", "row", "message"}
                            for f in findings)
    assert all(f["severity"] == "error" for f in findings)


def test_cli_exit_codes(tmp_path, capsys):
    good = str(tmp_path / "good.csv")
    bad = str(tmp_path / "bad.csv")
    write_sched(good, [good_row("A")])
    write_sched(bad, [good_row("A", crew="NOPE")])
    assert main(["--schedule", good, "--registry", "/nonexistent.json"]) in (0, 1)
    # Unknown registry path -> skip unknown-crew check -> valid
    assert main(["--schedule", good, "--registry", "/nonexistent.json"]) == 0
    assert main(["--schedule", bad, "--no-registry"]) == 0  # check skipped
    # Direct crew_ids path is the strict one:
    assert not audit_file(bad, crew_ids=CREW)["valid"]
