# ROGUE PROTOCOL — Round 1: PREDICT (100 pts = 10 valid file + 80 hidden-test F1 + 10 card)

**Team: <teamid> | Model: HistGradientBoosting + TF-IDF/SVD + keyword flags | Val F1 0.6832 @thr 0.54**

NINE floods the crew with false alarms and hides real faults inside calm messages.
Our classifier gives every test log a verdict — 1 true fault, 0 lie — from readings,
modules, delays, and log text.

## Architecture

```
logs.csv ─▶ derive (clean text, 13 keyword/phrase flags, missing markers)
      ─▶ ColumnTransformer ─┬─ numerics → median-impute + scale
      ─▶                    ├─ module/mode/node/status → one-hot (unknown-safe)
      ─▶                    └─ message → TF-IDF 8k (1,2-gram) → SVD-64
      ─▶ HistGradientBoosting (300 trees, lr 0.06, 31→15 leaves, balanced)
      ─▶ probability ─▶ threshold 0.54 ─▶ submission.csv (log_id,is_true_fault)
```

Deterministic (seed 42). Fit on train only; val/test transformed. ~8s CPU, `python train_aadit.py`.

## Features (what we used)

- **Readings/delays:** `reading`, `delay_ms`, `retry_count` (+ missing flag). Faults run hotter and later: delay 468 vs 379ms, retries 1.04 vs 0.77.
- **Modules:** one-hot `module/mode/node/status`. `status` is strongest tabular signal (CRIT 45% fault vs OK 12%); `module` is flat (~21% each) so no target encoding.
- **Log text:** word TF-IDF (8k, 1–2g) compressed to 64 SVD dims for the tree, plus flags for NINE's lying patterns — calming phrases (`all is well…`, P(fault) 0.36 vs 0.20 base), `REDACTED` (kept as feature only: 0.56 train → 0.35 val, too unstable to trust), and 8 rare-phrase flags (e.g. `seal breach`, `queue overflow` faulty; `drill`, `duplicate of earlier` benign).

## Model (what we used)

HistGradientBoosting, class-balanced, early regularization (15 leaves, SVD-64).
SVD-64 alone beat SVD-128 by +0.018; shallower leaves added +0.013 (total +0.031 over first HGB).

## Trick that helped (and how we know)

**Threshold 0.54, tuned — not 0.5.** Val sweep 0.10–0.90: 0.54 gives F1 0.6832 (tp=138 fn=71 fp=57 tn=734); blind 0.5 gives 0.6698. The starter's numeric-only model scores 0.36 tuned / 0.01 @0.5 — threshold + status + text is the whole game.

## Validation

Stratified val (n=1000, 20.9% fault): floor LogReg 0.6022 → HGB 0.6832. Rejected with measurement:
LGBM 0.646, char n-grams 0.582, word+char concat 0.513, blends ≤0.668, status×delay flags −0.001.
3-fold CV note: leaves31 0.6286 vs leaves15 0.6216 (within noise) — val is the organizer scoreboard, kept leaves15.
Known risk: `has_redacted` and module rates shift train→val, so hidden test may move a few points either way.

## Reproduce

```powershell
pip install -r requirements.txt
python train_aadit.py        # → model.joblib, threshold.txt, metrics.md
python check_submission.py submission.csv   # → TRANSMISSION VALID
```
