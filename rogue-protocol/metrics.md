# metrics (val, n=1000)
- winner: hgb-svd128
- threshold: 0.40
- F1 tuned: 0.6517 | F1 @0.5: 0.6339
- confusion @thr: tp=131 fn=78 fp=62 tn=729
- floor LogReg: thr=0.54 F1=0.6000
- HGB: thr=0.40 F1=0.6517
- LGBM skipped (not installed)
- train time: 7.7s, seed=42
- rule: promote challenger only on >+0.02 val F1
