# metrics (val, n=1000)
- winner: hgb-svd64-leaves15+flags
- threshold: 0.48
- F1 tuned: 0.6713 | F1 @0.5: 0.6667
- confusion @thr: tp=145 fn=64 fp=78 tn=713
- floor LogReg: thr=0.54 F1=0.6022
- HGB: thr=0.48 F1=0.6713
- LGBM sparse: tuned thr=0.50 F1=0.6462 (@0.5=0.6462)
- train time: 6.0s, seed=42
- rule: promote challenger only on >+0.02 val F1
