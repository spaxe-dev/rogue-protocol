# ROGUE PROTOCOL — Round 2 autonomous crew demo

One command proves the whole workflow and leaves judge-readable evidence:

```bash
cd round2
rm -rf demo_state
python -m src.main --input demo_logs.csv --state demo_state
```

Expected: `logs=5 genuine=2`, exit code `0`, plus four printed artifact paths:
`run_report.md`, `HANDOVER.md`, `TIMELINE.md`. Produced in `<state>/`:

- `trace.jsonl` — one auditable record per genuine incident
- `tickets.jsonl`, `schedule.csv`, `dispatch_log.csv` — outcomes
- `outbox/*.eml`, `reports/brief_<id>.md` — generated locally, **not delivered**
- `reports/run_report.md`, `reports/HANDOVER.md`, `reports/TIMELINE.md`
- `state/seen.json`, `state/activity/*.jsonl`, `memory_store/` — idempotency, audit, memory

Exit code is `1` if any booking or notification recorded `failed`
(see `HANDOVER.md` §7); otherwise `0`. Single-report runs:

```bash
python src/tools/handover.py <state_dir>
python src/tools/timeline.py <state_dir>
python -m src.main --roster
python -m src.main --status <state_dir>
```

Tests (offline): `pytest tests/ -q` from `round2/`.

Honest limits on a bare checkout: without `faiss` the memory backend is
`tfidf` (not FAISS); without `laya` triage falls back to the deterministic
policy; the outbox is a local file adapter, never proof of delivery.
