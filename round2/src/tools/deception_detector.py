"""NINE Deception Detector (Automation B): flags suspicious evidence, never declares intent."""
import re

CALM = re.compile(r"all is well|nothing to see|crew need not worry", re.IGNORECASE)


def detect(row, proba, seen_hashes):
    flags = []
    msg = str(row.get("message", ""))
    if CALM.search(msg) and (str(row.get("status")) in ("CRIT", "ERROR") or proba >= 0.6):
        flags.append("calm wording paired with alarming status/proba")
    if CALM.search(msg) and "REDACTED" in msg and proba >= 0.5:
        flags.append("reassurance + unverifiable redacted value")
    if str(row.get("status")) == "OK" and proba >= 0.7:
        flags.append("OK status but high fault probability")
    h = str(row.get("module")) + "|" + msg[:60]
    if h in seen_hashes:
        flags.append("near-repeat of earlier log text (possible recurrence)")
    seen_hashes.add(h)
    return flags
