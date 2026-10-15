"""Aadit (model) — bake-off + training. Run from the kit folder:
    python train_aadit.py
Writes: model.joblib, threshold.txt, metrics.md

Preprocessing comes from Kunal's features_kunal.make_preprocessor
(latest recorded validation result: F1 0.6713 @0.48).
Model + threshold logic below is Aadit's and stays untouched.
"""
import time
import joblib
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, f1_score
from sklearn.pipeline import make_pipeline

from features_kunal import make_preprocessor

SEED = 42


def build_sparse_pre():
    """Sparse path: LogReg / LGBM consume TF-IDF directly (Kunal)."""
    return make_preprocessor(dense=False)


def build_dense_pre():
    """Dense path: HGB needs dense input, TF-IDF via SVD-64 (Kunal)."""
    return make_preprocessor(dense=True)


def sweep_threshold(proba, y):
    best_t, best_f1 = 0.5, -1.0
    for t in [x / 100 for x in range(10, 90, 2)]:
        f1 = f1_score(y, (proba >= t).astype(int))
        if f1 > best_f1:
            best_t, best_f1 = t, f1
    return best_t, best_f1


def main():
    t0 = time.time()
    tr = pd.read_csv("train.csv")
    va = pd.read_csv("val.csv")
    ytr, yva = tr["is_true_fault"], va["is_true_fault"]

    # Floor: LogReg sparse
    floor = make_pipeline(
        build_sparse_pre(),
        LogisticRegression(max_iter=3000, class_weight="balanced",
                           solver="saga", random_state=SEED),
    )
    floor.fit(tr, ytr)
    p_floor = floor.predict_proba(va)[:, 1]
    thr_floor, f1_floor = sweep_threshold(p_floor, yva)

    # Primary: HGB dense (promoted config: svd64 + phrase flags + leaves15;
    # latest recorded sweep winner 0.6713 @0.48; CV caveat in metrics.md)
    primary = make_pipeline(
        build_dense_pre(),
        HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.06, max_leaf_nodes=15,
            min_samples_leaf=30, class_weight="balanced", random_state=SEED),
    )
    primary.fit(tr, ytr)
    p_hgb = primary.predict_proba(va)[:, 1]
    thr_hgb, f1_hgb = sweep_threshold(p_hgb, yva)

    # Challenger: LGBM sparse (only if installed)
    lgbm_line = "LGBM skipped (not installed)"
    try:
        from lightgbm import LGBMClassifier
        lgbm = make_pipeline(
            build_sparse_pre(),
            LGBMClassifier(num_leaves=21, min_child_samples=50,
                           n_estimators=500, class_weight="balanced",
                           random_state=SEED, verbose=-1),
        )
        lgbm.fit(tr, ytr)
        p_lgb = lgbm.predict_proba(va)[:, 1]
        thr_lgb, f1_lgb = sweep_threshold(p_lgb, yva)
        lgbm_line = f"LGBM sparse: tuned thr={thr_lgb:.2f} F1={f1_lgb:.4f} (@0.5={f1_score(yva, (p_lgb >= 0.5).astype(int)):.4f})"
        if f1_lgb > f1_hgb + 0.02:
            print(f"PROMOTE LGBM (+{f1_lgb - f1_hgb:.3f} over HGB)")
    except ImportError:
        pass

    # Winner: HGB unless floor beats it outright (simpler + calibrated wins ties)
    if f1_floor >= f1_hgb - 0.01:
        winner, winner_name, p_win, thr_win, f1_win = floor, "logreg-tfidf", p_floor, thr_floor, f1_floor
    else:
        winner, winner_name, p_win, thr_win, f1_win = primary, "hgb-svd64-leaves15+flags", p_hgb, thr_hgb, f1_hgb

    joblib.dump(winner, "model.joblib")
    with open("threshold.txt", "w") as f:
        f.write(f"{thr_win:.2f}\n")

    tn, fp, fn, tp = confusion_matrix(yva, (p_win >= thr_win).astype(int)).ravel()
    with open("metrics.md", "w") as f:
        f.write(f"""# metrics (val, n={len(yva)})
- winner: {winner_name}
- threshold: {thr_win:.2f}
- F1 tuned: {f1_win:.4f} | F1 @0.5: {f1_score(yva, (p_win >= 0.5).astype(int)):.4f}
- confusion @thr: tp={tp} fn={fn} fp={fp} tn={tn}
- floor LogReg: thr={thr_floor:.2f} F1={f1_floor:.4f}
- HGB: thr={thr_hgb:.2f} F1={f1_hgb:.4f}
- {lgbm_line}
- train time: {time.time() - t0:.1f}s, seed={SEED}
- rule: promote challenger only on >+0.02 val F1
""")
    print(f"floor LogReg: thr={thr_floor:.2f} F1={f1_floor:.4f}")
    print(f"HGB: thr={thr_hgb:.2f} F1={f1_hgb:.4f}")
    print(lgbm_line)
    print(f"WINNER={winner_name} thr={thr_win:.2f} F1={f1_win:.4f} ({time.time() - t0:.1f}s)")


if __name__ == "__main__":
    main()
