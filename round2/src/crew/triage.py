"""Laya Triage Officer: structured risk assessment with deterministic fallback.

Laya (Router choice/score/noul) supplies urgency signals; the Round 1 classifier
keeps the genuine-fault verdict always. All Laya output is validated; any failure
falls back to the deterministic policy. Never disables mandatory actions.
"""
import re

CALM = re.compile(r"all is well|nothing to see|crew need not worry", re.IGNORECASE)
CRIT_WORDS = re.compile(
    r"breach|deadlock|stalled|falling|overflow|dropped|missing|fault|leak|rupture|offline",
    re.IGNORECASE)

STATUS_SCORE = {"CRIT": 3, "ERROR": 2, "WARN": 1, "OK": 0}


def deterministic_policy(row: dict, proba: float) -> dict:
    rationale = []
    score = STATUS_SCORE.get(str(row.get("status", "OK")), 0)
    rationale.append("status=%s base=%d" % (row.get("status"), score))
    msg = str(row.get("message", ""))
    if CALM.search(msg) and (score >= 2 or proba >= 0.6):
        score += 1
        rationale.append("calm text + alarming signal: contradiction +1")
    if "REDACTED" in msg:
        rationale.append("redacted reading noted (unverifiable value)")
    if CRIT_WORDS.search(msg) and str(row.get("status")) == "OK":
        score += 1
        rationale.append("critical wording under OK status +1")
    try:
        if float(row.get("delay_ms", 0)) > 1000:
            score += 1
            rationale.append("delay>1000ms +1")
    except (TypeError, ValueError):
        pass
    try:
        if int(row.get("retry_count", 0)) >= 2:
            rationale.append("retries>=2 noted")
    except (TypeError, ValueError):
        pass
    score = max(0, min(5, score))
    urgency = "critical" if score >= 4 else "high" if score == 3 else "medium" if score == 2 else "low"
    return {"urgency": urgency, "score": score, "escalate": score >= 4,
            "contradiction": any("contradiction" in r for r in rationale),
            "rationale": rationale, "source": "fallback"}


def laya_assess(message: str) -> dict | None:
    """Return validated Laya signals or None (fallback). Lazy import; no download
    forced here — Router() downloads a checkpoint on first predict; wrap everything."""
    try:
        from laya import Router
        router = Router()
        res = router.predict(message, {
            "urgency": {"type": "score", "instructions": "How urgent is this spacecraft log?",
                        "criteria": ["routine", "watch", "urgent"]},
            "escalate": {"type": "noul", "instructions": "Does this need human escalation?"},
            "contradiction": {"type": "noul", "instructions": "Does calm wording hide a real problem?"},
        })
        ans = res.get("answers", {})
        urg = ans.get("urgency", {})
        lvl = urg.get("score", 0)
        if not isinstance(lvl, (int, float)):
            return None
        return {"urgency_level": max(0, min(2, int(lvl))),
                "escalate": bool(ans.get("escalate", {}).get("noul", False)),
                "contradiction": bool(ans.get("contradiction", {}).get("noul", False))}
    except Exception:
        return None


def assess(row: dict, proba: float, use_laya: bool = True) -> dict:
    base = deterministic_policy(row, proba)
    if not use_laya:
        return base
    sig = laya_assess(str(row.get("message", "")))
    if sig is None:
        base["rationale"].append("laya unavailable/invalid -> fallback kept")
        return base
    score = max(0, min(5, base["score"] + sig["urgency_level"] - 1))
    urgency = "critical" if score >= 4 else "high" if score == 3 else "medium" if score == 2 else "low"
    return {"urgency": urgency, "score": score,
            "escalate": sig["escalate"] or score >= 4,
            "contradiction": sig["contradiction"] or base["contradiction"],
            "rationale": base["rationale"] + ["laya urgency+%d" % (sig["urgency_level"] - 1)],
            "source": "laya+rules"}
