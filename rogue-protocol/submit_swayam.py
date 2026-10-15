"""Swayam (submission) — generate + check submission.csv. Run from kit folder."""
import joblib
import pandas as pd
from check_submission import check

thr = float(open("threshold.txt").read().strip())
model = joblib.load("model.joblib")
test = pd.read_csv("test.csv")
verdict = (model.predict_proba(test)[:, 1] >= thr).astype(int)
sub = pd.DataFrame({"log_id": test["log_id"], "is_true_fault": verdict})
sub.to_csv("submission.csv", index=False)
print("wrote submission.csv: %d rows, %d flagged" % (len(sub), int(verdict.sum())))
ok = check("submission.csv")
raise SystemExit(0 if ok else 1)
