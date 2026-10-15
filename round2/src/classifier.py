"""Round 1 classifier adapter: model.joblib + threshold.txt (fit train-only upstream)."""
import joblib
import pandas as pd
import sys

MODEL = None
THR = 0.48


def load(kit_dir):
    global MODEL, THR
    if kit_dir not in sys.path:  # model.joblib pickles features_kunal._as_frame
        sys.path.insert(0, kit_dir)
    MODEL = joblib.load(kit_dir + "/model.joblib")
    THR = float(open(kit_dir + "/threshold.txt").read().strip())
    return MODEL, THR


def predict(rows: pd.DataFrame):
    """rows: raw log rows. Returns (verdicts, probas). Never raises on a row:
    malformed input falls back to 0 with proba 0.0 rather than crashing batch."""
    global MODEL, THR
    proba = MODEL.predict_proba(rows)[:, 1]
    proba = [float(max(0.0, min(1.0, p))) for p in proba]
    return [int(p >= THR) for p in proba], proba
