# Round 2 interface request (Swayam → Aadit / Kunal / Anubhav)

Status: drafted, not yet sent (no teammate channel in this session). Current
contracts below are read straight from the code (commit `0a269fb` + local
`swayam/round2-handover-timeline` branch).

## To Aadit (model + triage)
- I call `triage.assess(row, proba, use_laya=...)` and expect keys
  `urgency, score, escalate, contradiction, rationale, source`. Confirm this
  stays the contract; if Laya changes `source` values, list them.
- I read deception evidence from `tools/deception_detector.score(row, proba)`
  → `(score 0-3, [rule_ids])` and `explain(ids)`. Orchestrator already threads
  it into the brief header, `run_report.md`, `HANDOVER.md §9`, `TIMELINE.md`.
- Please do not change these signatures without a heads-up; `schemas.py` untouched.

## To Kunal (features + memory)
- I call `memory.open_memory(name, path)` → `(memory, backend_name)` with
  `add(log_id, text, meta)` / `query(text, k, module)` /
  `persist()` returning `True/False`. Confirm.
- Recurrence: I currently compute `handover.recurrence(incidents)` →
  `(counts_by_module, [(dup, original)])` inside my own reader. If you add a
  `historian.recurrence(...)` helper, tell me its signature and I will import
  it instead of duplicating logic. I did not touch `historian.py`.

## To Anubhav (validation + auditor)
- My reports read `schedule.csv` (`log_id,crew_id,start,end,job`) and the
  per-incident trace booking states `done | skipped | failed (+reason)`.
  Confirm your schedule-auditor result schema so HANDOVER §7 matches it.
- New tests live in `round2/tests/test_reports.py` only; I did not edit your
  `test_round2.py` / `test_crew.py`. Full suite must stay green: `pytest tests/ -q`.
