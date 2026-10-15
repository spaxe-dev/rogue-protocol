# Validation handoff — Anubhav (Round 2)

Owner: Anubhav. Scope: schedule auditor + offline acceptance/adversarial tests.
No shared files edited (triage, historian, orchestrator, AEGIS gate, schemas untouched).

## Base

* Commit: `6ecf4cb` (local, ahead of `origin/main`; push needs an authenticated terminal — no creds in this env).
* Prior baseline: `0a269fb` / `95b959c` (12-member registry, AEGIS gate, dossier + roster/status CLI).
* Env: Win Python 3.14.2, pytest 9.1.1, sklearn 1.9.1 (note drift vs Round 1 pin 1.7.2 — see risks). WSL python has no pip/pytest.

## Delivered (my files only)

* `round2/src/tools/schedule_auditor.py` — read-only `audit_file()` → `{valid, rows, findings}` (`severity/row/log_id/rule/message`); rules HEADER, MALFORMED_ROW, MISSING/EMPTY_FIELD, BAD_DATETIME (parsed via `fromisoformat`, never string-compared), END_BEFORE_START (incl. zero-duration), UNKNOWN_CREW (vs `config/crew.json`), DUPLICATE_LOG_ID (2nd+ only; job-text dup allowed), OVERLAP (same crew, parsed tz-aware). CLI exit 0/1. Swayam integrates via `audit_file()` — no orchestrator change.
* `round2/tests/test_schedule_auditor.py` — 15 tests.
* `round2/tests/test_validation_anubhav.py` — 13 tests: gate/append reject unknown crew, bad datetime, end≤start; overlap rejected/escalated; duplicate rejected idempotent; malformed safe; memory distinct-not-conflated + missing/corrupt handling; notify `queued-local` never `sent` + suppressed re-send; registry + roster CLI; 10-case schedule matrix.

## Test results

* Targeted: `round2> py -m pytest tests/test_validation_anubhav.py tests/test_schedule_auditor.py tests/test_crew.py -q` → **33 passed**.
* Full: `py -m pytest tests/ -q` → **39 passed, 1 skipped** (faiss absent, TF-IDF fallback OK), **4 failed** — all one cause (see Takesh1).
* CLI demo: good schedule → `VALID` exit 0; bad schedule → 5 findings (`EMPTY_FIELD`, `BAD_DATETIME`×2, `UNKNOWN_CREW`, `OVERLAP`) exit 1. Audited files byte- and mtime-unchanged.

## Owner notifications (exact repros, no unilateral patches)

### Takeshi — missing `model.joblib` blocks all e2e (4 failures)

* Failing: `test_genuine_triggers_workflow`, `test_nonfault_triggers_nothing`, `test_idempotent_rerun`, `test_malformed_safe`.
* Input: any `run(input_csv, state_dir, KIT)` call, e.g. `tests/test_round2.py:40-44`.
* Trace: `src/classifier.py:14 joblib.load(kit_dir + "/model.joblib")` → `FileNotFoundError: .../rogue-protocol/model.joblib` (file gitignored, absent from checkout).
* Expected: model present (or documented retrieval) so e2e + demo can run. I did not train it (your ownership). E2E items C1, C2, C8-e2e, C15 stay open until then.

### Safety owner — overlap gate string-compares timestamps

* Failing behavior (current, not a test failure — gate returns wrong verdict): `src/crew/safety.py:40-41` compares `row["start"] >= r["end"]` as strings.
* Input: existing booking `start=05:00+00:00/end=06:00+00:00`, new `start=10:00+05:30` (=04:30Z, overlaps) `end=11:00+05:30` — strings say no overlap, parsed UTC says overlap. Reverse case false-rejects.
* Expected: parse both sides with `fromisoformat` like `logistics.py:82-83`. My auditor already does; regression test `test_timezone_aware_comparison` proves the difference. Minimal one-spot fix proposed, not applied (your gate).

### Kunal — corrupt memory raises instead of reporting

* Repro: write `{corrupt json!!!` to `memory_store/docs.json`, then `open_memory(path, "tfidf")` + `query()` → raises from `historian.py:18 json.load` (my test `test_corrupt_memory_does_not_claim_success` documents the raise).
* Expected per audit C11: report corrupt backend, never falsely claim retrieval succeeded. Missing-dir case already clean (`persisted False`, empty hits).

## Acceptance mapping (`ANUBHAV_VALIDATION_AUDIT.md:99-106`)

* Auditor exists, read-only — pass. Invalid dates parsed/rejected — pass. Duplicate/overlap covered — pass.
* Full offline suite green — **blocked** (Takeshi). E2E artifacts inspected — **blocked** (same). Simulated-vs-live — open: `send()` correctly returns `queued`/`queued-local`, never `sent`; no live adapter exercised.
* This file is the handoff: commands, counts, artifacts, risks.

## Risks

* `model.joblib` missing (blocker). Sklearn drift 1.9.1 vs pinned 1.7.2 (threshold 0.54→0.48 per `a5fa2a7`) — re-verify thresholds in a pinned env once e2e runs. Live-Laya checkpoint not cached (fallback verified only). Push pending (no creds here).

## Next

1. Push `6ecf4cb` from an authenticated terminal.
2. Owners resolve Takeshi/safety/Kunal items above; ping Swayam on `reports/` path for the final version of this note.
3. Re-run: full suite + `python -m src.main --input demo_logs.csv --state <dir> --no-laya --memory tfidf`, inspect `schedule.csv/outbox/trace.jsonl/reports/memory_store/dossier`.
