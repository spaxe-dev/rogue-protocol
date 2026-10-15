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

## Model (what we used — and why)

HistGradientBoosting, class-balanced (300 trees, lr 0.06, 15 leaves, SVD-64 input).
Why this, measured in order:

- **Why not the starter (LogReg on 3 numerics)?** It scores 0.36 tuned / 0.01 @0.5 — numerics alone can't see NINE's lies. Text + status carry the signal; any model without them is capped.
- **Why HGB over LogReg-TFIDF?** Same features, HGB 0.6832 vs LogReg 0.6022 (+0.08). Trees exploit status×delay×text interactions a linear model can't.
- **Why HGB over LightGBM?** Tested: LGBM 0.646 vs HGB 0.683. HGB also needs zero extra installs (in sklearn) — one fewer venue-laptop failure mode.
- **Why not CatBoost / XGBoost / transformers?** CatBoost's wheel is ~160MB and CPU-slow; XGBoost duplicates LGBM's tuning budget for no expected gain; BERT needs downloads + GPU time we don't have and overfits code-like logs. Rejected on cost, not fashion.
- **Why TF-IDF + SVD-64, not embeddings?** Word TF-IDF is inspectable (top terms go on the card) and offline-safe. SVD-64 beat SVD-128 by +0.018 and SVD-256 — compression regularizes. Char n-grams alone scored 0.582 and word+char concat collapsed to 0.513, so word-only stayed.
- **Why threshold 0.54, why F1?** Only ~21% of logs are faults, so accuracy lies (all-zero = 79% accurate, useless). F1 rewards catching faults without crying wolf — and it's the round's metric. Blind 0.5 costs 0.013.
- **Why keep phrase flags that read neutral on val?** The 5 benign-phrase flags are large-n with train/val agreement (e.g. recovered-after-retry 212 train / 45 val cases); they encode stable generator behavior, not val luck. The 3 fault-phrase flags are small-n but point the same way on both splits. Neutral today, principled for hidden logs.

## Obstacles we hit

1. **The starter lies by omission** — 0.01 F1 at its own default threshold. First decision: never trust defaults; sweep everything.
2. **REDACTED is a trap** — P(fault|redacted) 0.56 train → 0.35 val. Strongest single flag on train, unreliable across splits. Kept as a feature the tree can down-weight, never as a rule.
3. **The data shifts under us** — Life-Support fault rate 0.22 → 0.16 train→val, ERROR 0.37 → 0.44. So no target encoding, no module-specific tuning without >0.02 proof, and `handle_unknown='ignore'` everywhere.
4. **Val is noisy (±0.02 on 1000 rows)** — adopted a hard bar: promote only on >+0.02. Killed LGBM, blends, char concat, and status×delay flags (−0.001) on this rule.
5. **CV disagreed with val** — 3-fold CV favored leaves31 (0.6286 vs 0.6216) while val favored leaves15 (0.6832 vs 0.652). Within noise; val is the organizer's scoreboard, so val won — recorded here, not hidden.

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
