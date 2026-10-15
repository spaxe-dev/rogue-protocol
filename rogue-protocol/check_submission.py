"""Check your verdicts before uploading.

In a terminal:   python check_submission.py submission.csv
In a notebook:   from check_submission import check; check("submission.csv")
"""
import sys
import pandas as pd


def say(text):
    """print(), with plain marks where the output can't show ✓/✗ (e.g. `!python ...` in Jupyter on Windows)."""
    enc = sys.stdout.encoding or "utf-8"
    try:
        text.encode(enc)
    except UnicodeEncodeError:
        text = text.replace("✓", "[OK]").replace("✗", "[X]").encode(enc, "replace").decode(enc)
    print(text)


def check(path="submission.csv"):
    """Print the verdict on a submission file and return True when it is valid."""
    test_ids = set(pd.read_csv("test.csv").log_id)
    try:
        sub = pd.read_csv(path)
    except Exception as e:
        say(f"✗ TRANSMISSION REJECTED\n  ✗ could not read {path} as a csv ({e.__class__.__name__})")
        return False
    problems = []
    if list(sub.columns) != ["log_id", "is_true_fault"]:
        problems.append(f"columns must be exactly log_id,is_true_fault (got {list(sub.columns)})")
    else:
        if sub.log_id.duplicated().any():
            problems.append(f"{sub.log_id.duplicated().sum()} duplicate log_ids")
        if missing := test_ids - set(sub.log_id):
            problems.append(f"{len(missing)} test log_ids missing")
        if extra := set(sub.log_id) - test_ids:
            problems.append(f"{len(extra)} log_ids not in test.csv")
        if not sub.is_true_fault.isin([0, 1]).all():
            problems.append("every verdict must be exactly 1 or 0 (no probabilities)")
    if problems:
        say("✗ TRANSMISSION REJECTED\n" + "\n".join("  ✗ " + p for p in problems))
    else:
        say(f"✓ TRANSMISSION VALID — {len(sub):,} verdicts, {int(sub.is_true_fault.sum())} flagged as true faults. Upload it.")
    return not problems


if __name__ == "__main__":
    sys.exit(0 if check(sys.argv[1] if len(sys.argv) > 1 else "submission.csv") else 1)
