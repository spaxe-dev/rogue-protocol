# Role Sheet — Kunal (Features)

You own the feature pipeline. No one else edits your file.

## Owned file
- `source-repo/rogue-protocol/features_kunal.py` — must expose `make_preprocessor()` that takes raw log rows and returns a model-ready matrix.

## Read-only inputs
- `train.csv` (6000), `val.csv` (1000), `test.csv` (3000). Cols: `log_id,timestamp,module,mode,node,status,reading,delay_ms,retry_count,message[,is_true_fault]`.

## Verified signals to encode (measured 14 Oct)
- `status`: CRIT 45% fault vs OK 11.6% — one-hot it.
- `module` ~flat, `mode` MAINT lower, `node` N7 lower — one-hot all three, `handle_unknown='ignore'`.
- Text calming phrases (`all is well|nothing to see|crew need not worry`): 27% rows, P(fault)=0.36 vs 0.20 base — add `calm_flag`.
- `REDACTED`: P(fault) 0.56 train → 0.35 val — UNSTABLE. Add `has_redacted` as feature, never as a rule.
- `reading` has 158 NaNs train / 23 val — median-impute + add `reading_missing` flag.
- Numeric: `reading, delay_ms, retry_count` + `mlen`, `log1p(delay_ms)`. Scale only for LogReg branch.

## Tasks (in order)
1. [30 min] EDA dump: `df.nunique()`, nulls, `message.str.len()` by label, top-20 messages per label. Save to `eda_kunal.md`.
2. [45 min] Build `make_preprocessor()`:
   - num → median-impute + StandardScaler
   - cat (`module,mode,node,status`) → OneHotEncoder(handle_unknown='ignore')
   - text `message` → word TF-IDF 1-2g (max 5-8k, min_df=2, sublinear) + char 3-5g (max 2-5k) + keyword flags above
   - HGB path: add TruncatedSVD-128 bridge (HGB needs dense); LogReg/LGBM path keeps sparse.
3. [15 min] Prove contract: fit preprocessor on train-only, transform val/test without crash on unseen categories; assert no NaN output.

## Done when
- `from features_kunal import make_preprocessor` works from kit folder.
- `pre.fit(train).transform(val)` exits 0, no NaN, handles unseen `module` value.
- Handoff to Aadit: tell him import name + sparse-vs-dense note.

## Do NOT
- Use `log_id` or `is_true_fault` as features. Fit vectorizer on full data (leakage). Hand-edit `submission.csv`.
