"""Round 2 shared incident contracts (pydantic v2)."""
from typing import Literal
from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low"]
Status = Literal["auto", "needs_review", "reviewed", "auto_needs_review"]
ActionState = Literal["pending", "done", "skipped", "failed", "degraded"]


class RiskAssessment(BaseModel):
    urgency: Severity = "low"
    score: int = Field(default=0, ge=0, le=5)
    escalate: bool = False
    contradiction: bool = False
    rationale: list[str] = Field(default_factory=list)
    source: Literal["laya", "fallback", "laya+rules"] = "fallback"


class RepairProposal(BaseModel):
    crew_id: str
    job: str
    start: str  # ISO datetime
    end: str


class NotificationStatus(BaseModel):
    channel: str = "local-outbox"
    status: Literal["queued", "sent", "failed", "suppressed"] = "queued"
    path: str = ""


class ScheduleStatus(BaseModel):
    state: ActionState = "pending"
    row: str = ""
    reason: str = ""


class Incident(BaseModel):
    log_id: str
    raw: dict = Field(default_factory=dict)
    proba: float = 0.0
    verdict: Literal[0, 1] = 0
    predicted_module: str = "unknown"
    risk: RiskAssessment = Field(default_factory=RiskAssessment)
    routed_to: str = "review_queue"
    status: Status = "needs_review"
    neighbors: list[dict] = Field(default_factory=list)
    is_duplicate_of: str | None = None
    repair: RepairProposal | None = None
    notification: NotificationStatus = Field(default_factory=NotificationStatus)
    schedule: ScheduleStatus = Field(default_factory=ScheduleStatus)
    deception_flags: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
