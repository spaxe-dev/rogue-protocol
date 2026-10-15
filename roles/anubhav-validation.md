# Role Sheet — Anubhav (Validation)

You own gates, hardening, and explanation. You can block any submit. No one else edits your files.

## Owned files
- `source-repo/rogue-protocol/validate_anubhav.py` — gates + fault-injection.
- `source-repo/rogue-protocol/explanation.md` — R1 explanation + card draft (features / model / trick + evidence).

## Contracts to enforce
- Submission must be exactly `log_id,is_true_fault`, 3000 rows, IDs == test IDs in order, 1/0 ints only — `check_submission.py:29-39`. Invalid = 0 for whole round.
- Val F1 ±0.02 = noise — reject changes below that.
- Scoring: 10 valid + 80 F1 linear + 10 card. Missing card = 0 of 10.

## Tasks (in order)
1. [20 min] Gate: wrap `check_submission.check()` + asserts (row-count==3000, ID order, no NaN/dupe, labels ⊆ {0,1}, byte-stable rerun). Exit non-zero on fail.
2. [30 min] Fault-injection (all must pass without crash): empty message, NaN reading, 200k-char line, binary bytes, unseen module, duplicate log_id, shuffled test order, vectorizer fit-train-only audit (grep `fit_transform.*test` → empty).
3. [20 min] Error analysis: confusion matrix @thr vs @0.5, top-20 FP/FN messages, FP cost vs FN cost note, calibration check. Write into `explanation.md`.
4. [15 min] Card draft: team id + 3 lines (features / model / trick + how-you-know with val F1 numbers) + leave space for NINE 11:30 answer.

## Done when
- `python validate_anubhav.py` green on dummy + real outputs.
- `explanation.md` exists: model + features + threshold + val F1 + 2 error examples + 1 limitation.
- Explicit APPROVE / REVISE to Swayam before every upload.

## Do NOT
- Tune the model yourself (flag it to Aadit). Approve an unchecked CSV. Let anyone skip the checker.
