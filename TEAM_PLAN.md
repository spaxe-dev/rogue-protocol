# Rogue Protocol — 4-Way Team Plan (Round 1)

Source of truth: `source-repo/rogue-protocol/` (train 6000 / val 1000 / test 3000).
Scoring: 10 valid + up to 80 F1 (baseline→best, linear) + 10 card. Val F1 ±0.02 = noise.
Deadlines: upload `<teamid>.csv` by 12:10, card at desk by 12:10, NINE question 11:30.

## Ownership (no overlap)

| Member | Owns | Files | Delivers |
|--------|------|-------|----------|
| Kunal (features) | EDA + feature pipeline | `features_kunal.py` | `make_preprocessor()` that takes raw log rows → model-ready matrix. Keyword flags + TF-IDF + cat/num. Never uses `log_id`/label as feature. |
| Aadit (model) | Bake-off + training | `train_aadit.py` | `model.joblib`, `threshold.txt`, `metrics.md`. Order: LogReg floor → HGB primary → LGBM only if `pip install lightgbm` passed in <15 min. Promote only on >+0.02 val F1. |
| Anubhav (validation) | Gates + hardening + explanation | `validate_anubhav.py`, `explanation.md` | `check()` passes, fault-injection green, `metrics.md` + error analysis. Blocks any submit that fails. |
| Swayam (submission/captain) | Threshold, submission, uploads, card, clock | `submit_swayam.py`, `submission.csv` | Final `submission.csv` (exact `log_id,is_true_fault`), checker `TRANSMISSION VALID`, uploaded as `<teamid>.csv`, card at desk. Only Swayam writes final submission. |

## Merge protocol (avoids notebook conflicts)

1. Nobody co-edits `starter_round1.ipynb`. Experiments are `*.py` scripts.
2. Contract: Kunal's preprocessor output → Aadit's model input → Anubhav validates → Swayam submits.
3. `threshold.txt` holds ONE float (e.g. `0.40`). Only Swayam updates it, on Aadit's recommendation + Anubhav's sign-off.
4. First 30 min: everyone runs notebook top-to-bottom once → early valid upload. Then diverge to roles.

## Commands (run in `source-repo/rogue-protocol/`)

```powershell
pip install -r requirements.txt
python -m jupyter notebook starter_round1.ipynb   # once, for early valid file
python train_aadit.py          # Aadit: trains, writes model.joblib + threshold.txt + metrics.md
python validate_anubhav.py     # Anubhav: checks model + CSV + fault injection
python submit_swayam.py        # Swayam: writes submission.csv + runs checker
python check_submission.py submission.csv
```

## Kill criteria

- Any change gaining <0.02 val F1 is rejected.
- No new deps after T-45 min. No transformer/BERT as primary.
- `REDACTED` flag is unstable (0.56 train → 0.35 val P(fault)): use as feature, never as rule.
- Invalid CSV = 0 for whole round. Checker must print `TRANSMISSION VALID` before every upload.
