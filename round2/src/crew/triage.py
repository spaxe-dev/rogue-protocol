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


_ROUTER = None


def _router():
    global _ROUTER
    if _ROUTER is None:
        from laya import Router
        _ROUTER = Router(default="english", device="cpu")  # logs English; venue CPU-only
    return _ROUTER


PRIORITY_LEVELS = ("critical", "high", "medium", "low")
PRIORITY_SCORE = {"critical": 4, "high": 3, "medium": 2, "low": 1}

QUESTIONS = {
    # PRIORITY CLASSIFICATION of an already-confirmed fault (never fault detection).
    "priority": {"type": "choice",
                 "instructions": "What is the repair priority of this confirmed spacecraft fault?",
                 "criteria": {
                     "critical": "safety-critical failure needing immediate action",
                     "high": "serious fault needing prompt repair",
                     "medium": "degraded function, schedule normally",
                     "low": "minor anomaly, monitor"}},
    "escalate": {"type": "noul",
                 "instructions": "Does this need human escalation?"},
    "contradiction": {"type": "noul",
                      "instructions": "Does calm wording hide a real problem?"},
}


def build_priority_state(row: dict, proba: float) -> str:
    """Telemetry + fault context for the priority step (genuine faults only)."""
    return ("CONFIRMED FAULT (classifier p=%.2f). module=%s status=%s reading=%s "
            "delay_ms=%s retry_count=%s mode=%s message=%s" % (
                proba, row.get("module"), row.get("status"), row.get("reading"),
                row.get("delay_ms"), row.get("retry_count"), row.get("mode"),
                row.get("message", "")))


def laya_assess(message: str) -> dict | None:
    """Priority classification via Laya `choice`. Returns None on any failure
    or invalid/ambiguous output — caller falls back explicitly, never invents."""
    try:
        res = _router().predict(message, QUESTIONS, model="english")
        ans = res.get("answers", {})
        choice = ans.get("priority", {}).get("choice", "")
        if choice not in PRIORITY_LEVELS:
            return None
        return {"priority": choice,
                "escalate": float(ans.get("escalate", {}).get("noul", 0.0)) >= 0.5,
                "contradiction": float(ans.get("contradiction", {}).get("noul", 0.0)) >= 0.5}
    except Exception:
        return None


def assess(row: dict, proba: float, use_laya: bool = True) -> dict:
    """Round 1 owns the verdict. Laya classifies PRIORITY of genuine faults;
    invalid Laya output falls back explicitly to the deterministic policy."""
    base = deterministic_policy(row, proba)
    if not use_laya:
        return base
    try:
        sig = laya_assess(build_priority_state(row, proba))
    except Exception:
        sig = None
    if sig is None or sig.get("priority") not in PRIORITY_LEVELS:
        base["rationale"].append("laya priority invalid/unavailable -> deterministic fallback")
        return base
    score = PRIORITY_SCORE[sig["priority"]]
    if abs(score - base["score"]) > 1:
        base["rationale"].append(
            "laya=%s vs deterministic=%s disagree >1 level -> escalate" % (
                sig["priority"], base["urgency"]))
        return {"urgency": sig["priority"], "score": score, "escalate": True,
                "contradiction": sig["contradiction"],
                "rationale": base["rationale"] + ["priority source: laya choice"],
                "source": "laya+rules"}
    return {"urgency": sig["priority"], "score": score,
            "escalate": sig["escalate"] or score >= 4,
            "contradiction": sig["contradiction"] or base["contradiction"],
            "rationale": base["rationale"] + ["priority source: laya choice"],
            "source": "laya+rules"}
