"""NINE Deception Detector (Automation B): flags suspicious evidence, never
declares intent.

`detect()` returns human-readable flag strings (unchanged behaviour, reused by
the orchestrator). `score()` returns an explainable 0-3 score plus the named
rule ids that fired, so downstream reports can show *why* a line looked
suspicious. Rules are evidence, not proof: nothing here claims intent.
"""
import re

CALM = re.compile(r"all is well|nothing to see|crew need not worry", re.IGNORECASE)

# Named, inspectable rules (id -> human-readable description). The score is the
# count of rules that fire, so it is always explainable by the rule ids.
RULES = [
    ("calm_with_alarming_signal",
     "calm wording paired with alarming status/proba"),
    ("reassurance_plus_redacted",
     "reassurance + unverifiable redacted value"),
    ("ok_status_high_proba",
     "OK status but high fault probability"),
]
_RULE_TEXT = dict(RULES)


def score(row, proba):
    """Return (score 0-3, fired_rule_ids) from named rules. No intent claimed."""
    fired = []
    msg = str(row.get("message", ""))
    status = str(row.get("status"))
    if CALM.search(msg) and (status in ("CRIT", "ERROR") or proba >= 0.6):
        fired.append("calm_with_alarming_signal")
    if CALM.search(msg) and "REDACTED" in msg and proba >= 0.5:
        fired.append("reassurance_plus_redacted")
    if status == "OK" and proba >= 0.7:
        fired.append("ok_status_high_proba")
    return len(fired), fired


def explain(rule_ids):
    """Map rule ids to their descriptions for reports."""
    return [_RULE_TEXT.get(r, r) for r in rule_ids]


def detect(row, proba, seen_hashes):
    """Human-readable flags. Deception rules come from score(); recurrence is
    tracked separately here (it is evidence of repetition, not of deception)."""
    flags = [_RULE_TEXT[r] for r in score(row, proba)[1]]
    h = str(row.get("module")) + "|" + str(row.get("message", ""))[:60]
    if h in seen_hashes:
        flags.append("near-repeat of earlier log text (possible recurrence)")
    seen_hashes.add(h)
    return flags
