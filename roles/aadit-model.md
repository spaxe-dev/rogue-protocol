# Role Sheet — Aadit (Model)

You own model training and the bake-off. No one else edits your file.

## Owned files
- `source-repo/rogue-protocol/train_aadit.py` — trains, writes `model.joblib`, `threshold.txt`, `metrics.md`.
- Reads Kunal's `make_preprocessor()` — do not reimplement features.

## Ladder to beat (val F1, measured 14 Oct)
- Starter numeric-only: 0.36 tuned / 0.01 @0.5 (broken — never ship @0.5 blind).
- num+cat LogReg: 0.53. +TF-IDF LogReg: 0.60. HGB+SVD+keywords: 0.65 @thr 0.40, 8.4s CPU.

## Tasks (in order, stop when time <2h to deadline)
1. [15 min] Floor: LogReg + Kunal preprocessor, `class_weight='balanced'`, `max_iter=3000`. Log val F1 @0.5 and @tuned. This is the fallback that always ships.
2. [45 min] Primary: HGB (`max_iter=300, lr=0.06, leaves=31, min_leaf=30, balanced, seed=42`) on dense path. Threshold sweep 0.10–0.90 step 0.02 on val, maximize F1. Save `threshold.txt` (one float).
3. [30 min, only if `pip install lightgbm` passed in <15 min] Challenger LGBM-sparse. Promote only if val F1 > HGB +0.02 on both strat split and time/group check.
4. [15 min] Calibration (only for R2 reuse): sigmoid prefit on holdout; keep only if Brier improves. Never calibrate on test.

## Done when
- `python train_aadit.py` exits 0, writes `model.joblib` + `threshold.txt` + `metrics.md` (val F1, confusion matrix, thr).
- Determinism: re-run → identical `threshold.txt` (seed 42 everywhere).
- Handoff to Anubhav: model path + threshold value + val F1. Handoff to Swayam: which `model.joblib` is final.

## Do NOT
- Grid-search >15 trials. SMOTE on TF-IDF. BERT/fine-tune as primary. Single train_test_split or accuracy-only. Ship any model without tuned threshold.
