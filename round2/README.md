# ROGUE PROTOCOL — Round 2: Autonomous Spacecraft Crew

## Workflow (start → end)

```
logs.csv (NINE ship logs)
  │
  ▼
┌─────────────────────────┐
│ 1. CLASSIFY (R1 model)  │  model.joblib + threshold 0.54 → verdict 1/0 + proba
└────────┬────────────────┘
         │ verdict==0 → reviewed, STOP (no actions)
         │ verdict==1 ↓
┌─────────────────────────┐
│ 2. TRIAGE (LYRA)        │  Laya priority choice (critical/high/medium/low)
│                         │  + deterministic policy; disagree>1 level → escalate
└────────┬────────────────┘
         ↓
┌─────────────────────────┐
│ 3. REMEMBER (ECHO)      │  FAISS query top-3 + exact-fingerprint dup check
└────────┬────────────────┘
         ↓
┌─────────────────────────┐
│ 4. DIAGNOSE (ATLAS)     │  exact→fuzzy→semantic→generalist specialist,
│                         │  evidence findings, repair proposal, ticket filed
└────────┬────────────────┘
         ↓
┌─────────────────────────┐
│ 5. GATE (AEGIS)         │  deterministic PASS/REJECT on every notify + booking
└────┬───────────┬────────┘
     │ PASS      │ REJECT → escalate, skip action, log reason
     ↓           ↓
┌──────────┐  ┌──────────┐
│ 6a. MAIL │  │ 6b. BOOK │  outbox/*.eml + ledger  │  schedule.csv (atomic,
│ (PULSE)  │  │ (ORBIT)  │  suppressed on review/ │   overlap-checked, idempotent)
│          │  │          │  duplicate/failure     │
└────┬─────┘  └────┬─────┘
     │             │
     ▼             ▼
┌─────────────────────────────────┐
│ 7. TICKET (disagreement only)   │  Jira create (or dry-run queue) + report attach,
│                                 │  idempotent on incident:escalation-type
└────────┬────────────────────────┘
         ↓
┌─────────────────────────────────┐
│ 8. ARCHIVE (forensics)          │  state/incidents/{id}.json + timeline +
│                                 │  forensics_*.md + recurrence.md + run_report.md
└─────────────────────────────────┘
```

Idempotency: re-runs skip seen `log_id`s; schedule/email/tickets all dedupe by ID.
Fallbacks: Laya→deterministic, FAISS→TF-IDF, Jira→dry-run queue. Nothing fails silently.

## Run

```powershell
cd round2
pip install -r ..\rogue-protocol\requirements.txt   # pinned env (sklearn 1.7.2)
python -m pytest tests/ -q -p no:cacheprovider       # 50 passed, 1 env-gated skip
powershell -ExecutionPolicy Bypass -File demo.ps1    # full dry-run demo
python -m src.main --roster                          # crew board
python -m src.main --status <state_dir>              # live action counts
```

Live Jira (needs `.env` creds, never committed):
`JIRA_ENABLED=1` + ticket fires automatically on disagreement escalation.
Verified live: KAN-6/KAN-7 created and read back by label.

## Layout

- `src/main.py` — CLI entry · `src/orchestrator.py` — mission controller
- `src/schemas.py` — incident contract · `src/classifier.py` — R1 adapter
- `src/crew/` — triage, engineer, logistics, communications, safety, registry
- `src/memory/` — FAISS/TFIDF historian · `src/tools/` — audit, dossier, recurrence, deception
- `src/ack.py`, `src/forensics.py`, `src/tickets.py` — ack escalation, black box, Jira
- `config/crew.json` — 12-member registry · `crew.json` removed (single source of truth)
- `tests/` — 50 green · `demo_logs.csv`, `demo.ps1` — 5-log demo (D1 books+mails, D4 deduped)
