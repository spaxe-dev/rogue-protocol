# metrics (val, n=1000)
- winner: hgb-svd64-leaves15+flags
- threshold: 0.54
- F1 tuned: 0.6832 | F1 @0.5: 0.6698
- confusion @thr: tp=138 fn=71 fp=57 tn=734
- floor LogReg: thr=0.54 F1=0.6022
- HGB: thr=0.54 F1=0.6832
- LGBM sparse: tuned thr=0.50 F1=0.6462 (@0.5=0.6462)
- train time: 7.7s, seed=42
- rule: promote challenger only on >+0.02 val F1
