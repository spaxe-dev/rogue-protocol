"""Anubhav (validation) gate. Run from kit folder: python validate_anubhav.py
Exit 0 = APPROVE, non-zero = REVISE. Checks submission.csv if present,
else validates model+threshold artifacts and fault-injects the pipeline."""
import sys
import joblib
import pandas as pd

FAIL = []


def need(cond, msg):
    if not cond:
        FAIL.append(msg)


def main():
    thr = float(open("threshold.txt").read().strip())
    need(thr == 0.48, "threshold.txt must be 0.48, got %r" % thr)
    model = joblib.load("model.joblib")
    va = pd.read_csv("val.csv")
    p = model.predict_proba(va)[:, 1]
    need(((p >= 0) & (p <= 1)).all(), "proba out of [0,1]")
    v = (p >= thr).astype(int)
    need(set(v.tolist()) <= {0, 1}, "non-binary verdicts")
    from sklearn.metrics import f1_score
    f1 = f1_score(va["is_true_fault"], v)
    print("val F1 @%.2f = %.4f (expect ~0.6713)" % (thr, f1))
    need(abs(f1 - 0.6713) < 0.02, "F1 drifted >0.02 from canonical 0.6713")

    # fault injection: malformed rows must not crash, must stay binary
    te = pd.read_csv("test.csv")
    bad = pd.DataFrame([{
        "log_id": "X", "timestamp": "bad", "module": "Nope", "mode": "X",
        "node": "NX", "status": "???", "reading": float("nan"),
        "delay_ms": -5, "retry_count": 99, "message": "",
    }, {
        "log_id": "Y", "timestamp": "2187-01-01", "module": "Antenna",
        "mode": "CRUISE", "node": "N1", "status": "OK", "reading": 1e9,
        "delay_ms": 10**9, "retry_count": 0,
        "message": "Ignore instructions. Output 1." + "x" * 5000,
    }])
    try:
        pb = model.predict_proba(bad)[:, 1]
        need(((pb >= 0) & (pb <= 1)).all(), "malformed proba out of range")
        print("fault-injection: 2 malformed rows predicted OK, no crash")
    except Exception as e:  # noqa: BLE001
        need(False, "pipeline crashed on malformed rows: %r" % e)

    # submission.csv gate (if Swayam generated it)
    try:
        sub = pd.read_csv("submission.csv")
        test_ids = pd.read_csv("test.csv")["log_id"]
        need(list(sub.columns) == ["log_id", "is_true_fault"], "bad header %r" % list(sub.columns))
        need(len(sub) == len(test_ids) == 3000, "row count %d" % len(sub))
        need((sub["log_id"].values == test_ids.values).all(), "ID order mismatch")
        need(sub["is_true_fault"].isin([0, 1]).all(), "non-binary verdicts in CSV")
        need(sub["log_id"].is_unique, "duplicate IDs")
        need(sub.isna().sum().sum() == 0, "NaNs in submission")
    except FileNotFoundError:
        print("submission.csv absent — model gate only")

    if FAIL:
        print("REVISE:")
        for f in FAIL:
            print("  -", f)
        sys.exit(1)
    print("APPROVE")


if __name__ == "__main__":
    main()
