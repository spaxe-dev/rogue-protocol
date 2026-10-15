# Rogue Protocol — Round 1

**SMLRA × Abhiyantriki 2026 · Recalibrate**

Ship time 2187-04-15, 03:12. The research vessel *Aurora* is three weeks from Earth. Its ship computer, **NINE**, writes every log line and raises every alarm. Six hours ago it stopped telling the truth.

NINE floods the crew with false alarms and hides real faults inside calm messages. You are the recalibration unit. You have NINE's logs, and the crew has hand-checked some of them. Train a model that looks at any log line and returns a verdict:

| Verdict | Meaning |
|---|---|
| **1** | True fault. Wake the crew. |
| **0** | Noise. NINE is lying. Ignore it. |

This folder is the whole kit. Run `starter_round1.ipynb` from top to bottom and you will have a valid `submission.csv`. That first file is weak on purpose. Improve it, check it, and upload again. **Your best upload counts.** The form closes at **12:10**. Scores are announced at **12:20**.

Until then, validation F1 is your scoreboard. Nobody sees the hidden test score before the announcement.

---

## What's in this folder

| File | What it is |
|---|---|
| `starter_round1.ipynb` | The round. Story, a weak starter model, and the cells that write your submission. |
| `train.csv` | 6,000 logs **with** the crew's verdict, `is_true_fault`. Learn from these. |
| `val.csv` | 1,000 more checked logs. Use these to test a model honestly. |
| `test.csv` | 3,000 logs **nobody has checked**. Your verdicts on these are what get scored. |
| `check_submission.py` | Format checker. Run it before every upload. |
| `requirements.txt` | Python packages this folder needs. |
| `submission.csv` | Created by the notebook. It is not in the zip until you run Act 5. |

Keep every file in this folder. The notebook and the checker load `train.csv`, `val.csv`, and `test.csv` from the folder you run them in.

---

## Set up

You need Python 3. Open a terminal **in this folder** and install the packages:

```powershell
pip install -r requirements.txt
jupyter notebook starter_round1.ipynb
```

`requirements.txt` installs pandas, numpy, scikit-learn, matplotlib, and Jupyter. LightGBM is listed as optional. The starter model does not need it. If you want it later:

```powershell
pip install lightgbm
```

HistGradientBoosting is already inside scikit-learn, so a tree model does not require an extra install.

If `jupyter` is not found, start it as a module:

```powershell
python -m jupyter notebook starter_round1.ipynb
```

Any notebook editor works (JupyterLab, VS Code) as long as two things are true: the kernel has the packages above, and the notebook's working directory is this folder.

---

## What a log contains

`train.csv` and `val.csv` have the label. `test.csv` has the same columns without `is_true_fault`.

| Column | Meaning |
|---|---|
| `log_id` | Unique id. Train starts at `L00001`, val at `L06001`, test at `L07001`. |
| `timestamp` | Ship time. |
| `module` | Which system: Antenna, Notice-Bus, Lab-Power, Life-Support. |
| `mode` | Ship mode: CRUISE, DOCKED, ALERT, MAINT. |
| `node` | Which computer node wrote the line. |
| `status` | OK / WARN / ERROR / CRIT. |
| `reading` | Sensor value. |
| `delay_ms` | How late the log arrived. |
| `retry_count` | Retries before the log was written. |
| `message` | Free text from NINE. |
| `is_true_fault` | The crew's verdict, 1 or 0. Train and val only. |

About one log in four is a real fault. A model that answers 0 to every row looks accurate and still fails the crew. The round is scored on **F1** of your 1/0 verdicts, which rewards catching real faults without crying wolf.

---

## Run the notebook

Open `starter_round1.ipynb` and run every cell from the top (**Shift + Enter**). The first code cell is the bridge console. Leave it as it is. Set `DRAMA = False` in that cell if you want to skip the typing animations on a re-run.

| Act | What you do | What you get |
|---|---|---|
| 0 | Run it. | The task: 1 is real, 0 is a lie. |
| 1 | Run it. | `train`, `val`, and `test` loaded, and a column guide. |
| 2 | The starter model lives here. | A logistic regression pipeline on `reading`, `delay_ms`, and `retry_count`. |
| 3 | Set `THRESHOLD`, then run it again after every new model. | Probabilities turned into 1/0 verdicts. The cell ships with `0.5`. |
| 4 | Run it. | Validation F1, faults caught, faults missed, and false alarms. |
| 5 | Run both cells. | `submission.csv`, then the format check. |
| Epilogue | Run it once. | A short guide for the next attempt. |

The model does not emit 1 or 0. It emits a probability. You choose the cut-off in Act 3: at or above it, the verdict is 1. The cell starts at 0.5. Set `THRESHOLD` yourself, then re-run Act 3 after you change Act 2.

### Change the model

Edit Act 2. If you keep a scikit-learn pipeline named `model` that accepts raw log rows, Acts 3, 4, and 5 keep working.

If you build your own feature table instead, replace `model.predict_proba(val)[:, 1]` in Act 3 and the matching line in Act 5 with your own probabilities for val and test.

Then:

1. Set `THRESHOLD` in Act 3, then re-run Act 3 and Act 4. Expect the hidden test to land within a few points of your val F1. It can come out higher or lower.
2. Val is 1,000 logs. F1 moves by about ±0.02 from chance alone. Keep a change when it helps by more than that.
3. Re-run Act 5 so `submission.csv` matches the model you just measured.

---

## Check the file

Act 5 writes `submission.csv` in this folder and runs the checker. Run it yourself any time, from this same folder:

```powershell
python check_submission.py submission.csv
```

From a notebook cell:

```python
from check_submission import check
check("submission.csv")
```

A good file prints `TRANSMISSION VALID` (or `[OK]` on a terminal that cannot show the check mark) and the number of verdicts flagged as 1.

The checker rejects the file when any of these are true:

- It is not a readable CSV.
- The columns are anything other than exactly `log_id,is_true_fault`, in that order.
- A `log_id` is repeated.
- Any id from `test.csv` is missing.
- Any id is not in `test.csv`.
- Any verdict is not exactly `1` or `0`. Probabilities are rejected.

The file Act 5 writes looks like this:

```
log_id,is_true_fault
L07001,1
L07002,0
```

One row per test log. 3,000 verdicts.

---

## What you hand in

Two things. Nothing else. No notebook, no code, no zip.

**1. The CSV**, through the upload form. The link is on the board.

- File name: your team id, exactly as assigned at check-in, for example `team07.csv`.
- The form closes at **12:10**. Upload a valid starter file early, then upload again as you improve. Your best upload counts, not your last one.

**2. A paper card**, at the card desk, also by **12:10**. You can swap the card until then.

Write on it:

- Team id, exactly as assigned (`team07`).
- What features you used.
- What model you used.
- What trick helped, and how you know.
- At **11:30** NINE asks one question out loud. Write the answer on the same card.

A missing card scores 0 of the card points. An invalid CSV scores **0 for the whole round**, card included. Run `check_submission.py` before you upload.

---

## How the round is scored

Round 1 is out of 100.

| Points | For |
|---|---|
| 10 | A valid file. |
| up to 80 | F1 on the hidden test. 0 points at the baseline announced at the start. 80 points for the best F1 in the room. Linear in between. Below that baseline is 0 of these 80. |
| up to 10 | The card. |

Your val F1 is the number to watch while you work. The hidden test is scored once, after 12:10.

---

## Before 12:10

- [ ] The notebook has been run top to bottom once, so a valid `submission.csv` exists.
- [ ] `THRESHOLD` in Act 3 is the cut-off for the model you are submitting.
- [ ] Act 4 has been re-run for that model.
- [ ] `python check_submission.py submission.csv` prints TRANSMISSION VALID.
- [ ] The file uploaded to the form is named `<team id>.csv`.
- [ ] The card is at the card desk, with the team id, the three lines, and NINE's answer.
