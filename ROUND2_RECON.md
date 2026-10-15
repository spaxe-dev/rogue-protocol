# ROUND2_RECON — verified 2026-10-15 (Phase 1)

## Verified facts

- Repo `spaxe-dev/rogue-protocol`, branch `main`, HEAD `a5fa2a7`. Round 1 kit at `rogue-protocol/rogue-protocol/`
  (train 6000 / val 1000 / test 3000, `model.joblib` + `threshold.txt` 0.54 + `submission.csv` VALID).
- **No Round 2 starter files, no crew roster, no schedule.csv, no email endpoint exist** (globbed repo-wide).
  Roster/schedule/email are OURS to design (mission explicitly permits).
- Round 1 contract: `model.joblib` (HGB pipeline on raw rows) + thr 0.54, val F1 0.6832.
  `submission.csv` exact spec `log_id,is_true_fault`; schedule schema mandated:
  `log_id,crew_id,start,end,job`.
- Env (measured `pip list`): py 3.10.11, sklearn 1.7.2, pandas 2.3.3, pydantic 2.13.5,
  rapidfuzz 3.14.5, filelock 3.24.3, torch 2.14 present. **Missing:** chromadb,
  sentence-transformers. **Present after check:** faiss 1.15.1 (was preinstalled),
  laya 0.4.7 (installed; NO checkpoint cached — HF hub has only an unrelated model,
  so live Laya would need a 421MB+ download: deferred per 10-min rule, fallback verified).
- Laya (web-fetch of README): Apache-2.0, `pip install laya`, Router with choice/score/noul
  questions; routing-only works offline, `--predict` downloads checkpoint first use.
- Laya (web-fetch of README): Apache-2.0, `pip install laya`, Router with choice/score/noul
  questions; needs torch + ~421M-param checkpoint download from HF Hub on first use (~2.3GB all).
  Routing-only call works offline; `--predict` needs the download. Heavy for remaining time.

## Assumptions (estimates, must hold)

- Judges inspect artifacts (schedule.csv, outbox mail, memory dir, trace.jsonl, reports), not live infra.
- CPU-only venue, network flaky/slow. Offline-capable paths win.
- Round 1 model file loads in this env (same pinned versions).

## Unresolved questions (for organizers)

1. Is there a Round 2 starter/validator drop, or is format-compliance self-attested?
2. schedule.csv: starting file provided or we create? Time format/timezone? What makes a booking "valid"
   (skill match? overlap rule? working hours)?
3. Email: real send required or local adapter accepted? Recipient source?
4. Vector memory: FAISS/Chroma mandatory-by-name or any persistent searchable memory?
5. Bonus custom tools: capped? What counts?

## Implementation decisions (evidence-based)

1. **Memory: TF-IDF + JSON persistence primary, FAISS/Chroma shims.** faiss pip timed out;
   retry in background — if it lands, factory prefers FAISS, else TF-IDF. Zero new hard deps.
2. **Laya: adapter + deterministic fallback primary.** Attempt `pip install laya` in background;
   checkpoint download likely too heavy — pipeline must pass with fallback from the start.
   Classifier keeps the genuine-fault verdict always; Laya only adds urgency signals.
3. **Roster: our design** (4 module specialists + generalist fallback), explicit `crew.json`.
   Specialist resolution: exact module map → fuzzy → semantic → generalist. Never invent crew_id.
4. **Email: file-outbox adapter** (`outbox/*.eml` + ledger csv) with SMTP/webhook adapter stubs.
   Local file = demonstrable adapter, documented as such, never claimed as delivered.
5. **Scheduler: greedy earliest-fit + overlap guard + filelock + atomic append.** Exact header.
6. **Orchestrator: plain Python loop + pydantic schemas.** No LangGraph/smolagents (per R1 lesson).
7. Layout: `round2/src/...` inside kit folder? NO — kit folder must stay clean for R1 checker
   (it reads test.csv relatively; extra files harmless, but keep separation): build at
   `rogue-protocol/round2/` (repo root level, sibling of kit) importing model by path.
   Decided: `rogue-protocol/round2/{src,tests,outbox,reports,memory_store}`.
