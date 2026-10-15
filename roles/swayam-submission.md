# Role Sheet — Swayam (Submission / Captain)

You own the clock, the threshold, the final file, and the card. Only you write `submission.csv` and upload.

## Owned files
- `source-repo/rogue-protocol/submit_swayam.py` — loads `model.joblib` + `threshold.txt`, writes `submission.csv`, runs checker.
- `submission.csv` → rename to `<teamid>.csv` for upload. Paper card at desk.

## Deadlines (from `README.md:154-197`)
- 11:30 — NINE asks one question out loud. Write answer on same card.
- 12:10 — form closes (CSV + card). Best upload counts, not last. Scores 12:20.

## Tasks (in order)
1. [15 min] Early safety: run notebook top-to-bottom once → valid `submission.csv` → `python check_submission.py submission.csv` → upload as `<teamid>.csv`. Do this before any tuning.
2. [ongoing] Threshold keeper: `threshold.txt` holds ONE float. Update only on Aadit's number + Anubhav's APPROVE. Re-run Act 3+4 after every model change.
3. [per attempt] `python submit_swayam.py` → assert `TRANSMISSION VALID` → upload renamed copy → log val F1 + thr + time in `uploads_log.md`. Never upload an unchecked file.
4. [T-60 min] Freeze: no new deps, no model swaps without full re-validation. Final 15 min: resubmit best file + confirm receipt + card at desk (team id, features, model, trick, NINE answer).

## Done when
- Checker prints `TRANSMISSION VALID — 3,000 verdicts` before every upload.
- `uploads_log.md` has ≥1 early + ≥1 tuned upload. Card at desk by 12:10.

## Do NOT
- Let anyone else overwrite `submission.csv`. Upload a file you didn't check. Edit features/model files (request via owner). Chase a <0.02 gain past freeze.
