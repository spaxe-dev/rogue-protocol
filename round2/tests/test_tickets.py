"""Jira ticket adapter tests (offline, urllib mocked — no network)."""
import base64
import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import tickets  # noqa: E402


def make_incident(log_id="L1", urgency="critical"):
    return {
        "log_id": log_id, "verdict": 1, "proba": 0.93,
        "predicted_module": "Lab-Power", "routed_to": "C-PWR",
        "raw": {"module": "Lab-Power", "mode": "CRUISE", "node": "N4",
                "status": "CRIT", "reading": 11.5, "delay_ms": 1200,
                "retry_count": 2, "timestamp": "2187-03-14 21:29:53",
                "message": "NINE: seal breach suspected [Lab-Power 11.5 V]"},
        "risk": {"urgency": urgency, "score": 4, "escalate": True,
                 "contradiction": True,
                 "rationale": ["status=CRIT base=3",
                               "laya=critical vs deterministic=high "
                               "disagree >1 level -> escalate"],
                 "source": "laya+rules"},
        "neighbors": [{"log_id": "L0", "score": 0.88}],
        "notification": {"channel": "local-outbox", "status": "queued",
                         "path": "outbox/L1.eml"},
        "schedule": {"state": "done", "row": "L1,C-PWR", "reason": "booked"},
        "repair": {"crew_id": "C-PWR", "job": "Inspect seals",
                   "start": "2187-04-15T08:30:00+00:00",
                   "end": "2187-04-15T10:30:00+00:00"},
    }


def live_env(monkeypatch, tmp_path):
    monkeypatch.setenv("JIRA_ENABLED", "1")
    monkeypatch.setenv("JIRA_BASE_URL", "https://demo.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "bot@aurora.ship")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok123")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "AUR")
    return str(tmp_path / "run")


class FakeResponse:
    def __init__(self, payload, status=201):
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_success_creates_with_right_payload_and_idempotent(monkeypatch, tmp_path):
    state_dir = live_env(monkeypatch, tmp_path)
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["req"] = req
        seen["count"] = seen.get("count", 0) + 1
        return FakeResponse({"key": "AUR-123"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    esc = {"incident_id": "L1", "log_id": "L1", "type": "disagreement",
           "reason": "laya=critical vs deterministic=high"}
    res = tickets.ticket_escalation(state_dir, make_incident(), esc)
    assert res["status"] == "created" and res["key"] == "AUR-123"
    assert res["url"] == "https://demo.atlassian.net/browse/AUR-123"
    assert res["provider"] == "jira"

    req = seen["req"]
    assert req.full_url == "https://demo.atlassian.net/rest/api/3/issue"
    assert req.get_header("Authorization") == "Basic " + base64.b64encode(
        b"bot@aurora.ship:tok123").decode("ascii")
    payload = json.loads(req.data.decode("utf-8"))
    fields = payload["fields"]
    assert fields["project"] == {"key": "AUR"}
    assert fields["issuetype"] == {"name": "Task"}
    assert fields["priority"] == {"name": "Highest"}
    assert "L1" in fields["summary"]
    assert fields["description"]["type"] == "doc"

    # idempotent reprocess: same key, no second HTTP call, no queue line
    res2 = tickets.ticket_escalation(state_dir, make_incident(), esc)
    assert res2["key"] == "AUR-123" and seen["count"] == 1
    assert "replay" in res2["detail"]
    assert not os.path.exists(os.path.join(state_dir, "state",
                                           tickets.QUEUE_FILE))


def test_failure_queues_pending(monkeypatch, tmp_path):
    state_dir = live_env(monkeypatch, tmp_path)

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests",
                                     {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    res = tickets.ticket_escalation(state_dir, make_incident("L2", "high"),
                                    {"type": "ack-timeout",
                                     "reason": "no ack in window"})
    assert res["status"] == "failed" and res["key"] is None
    assert "429" in res["detail"]
    pending = read_jsonl(os.path.join(state_dir, "state", tickets.PENDING_FILE))
    assert len(pending) == 1
    assert pending[0]["idempotency_key"] == "L2:ack-timeout"
    assert pending[0]["retryable"] is True
    # failures are not cached: no map entry, retry may proceed
    map_path = os.path.join(state_dir, "state", tickets.MAP_FILE)
    assert not os.path.exists(map_path) or \
        "L2:ack-timeout" not in json.load(open(map_path))


def test_missing_creds_queued_not_created(monkeypatch, tmp_path):
    monkeypatch.setenv("JIRA_ENABLED", "1")
    for var in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN",
                "JIRA_PROJECT_KEY"):
        monkeypatch.delenv(var, raising=False)
    state_dir = str(tmp_path / "run")

    def fake_urlopen(req, timeout=None):  # pragma: no cover
        raise AssertionError("no network allowed")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    res = tickets.ticket_escalation(state_dir, make_incident(),
                                    {"type": "disagreement"})
    assert res["status"] == "queued" and res["key"] is None
    assert "missing credentials" in res["detail"]
    queued = read_jsonl(os.path.join(state_dir, "state", tickets.QUEUE_FILE))
    assert len(queued) == 1
    assert queued[0]["idempotency_key"] == "L1:disagreement"


def test_description_contains_all_required_sections():
    md = tickets.build_description_md(
        make_incident(), "disagreement", "laya=critical vs deterministic=high")
    low = md.lower()
    for token in ("l1", "verdict", "deterministic", "laya", "disagreement",
                  "telemetry", "neighbor", "0.88", "notification", "ack",
                  "schedule", "unresolved"):
        assert token in low, "missing section token: %s" % token


def test_dry_run_default_when_jira_enabled_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("JIRA_ENABLED", raising=False)
    state_dir = str(tmp_path / "run")

    def fake_urlopen(req, timeout=None):  # pragma: no cover
        raise AssertionError("no network allowed")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    res = tickets.ticket_escalation(state_dir, make_incident(),
                                    {"type": "disagreement"})
    assert res["status"] == "queued" and res["url"] is None
    assert "JIRA_ENABLED" in res["detail"]
    queued = read_jsonl(os.path.join(state_dir, "state", tickets.QUEUE_FILE))
    assert queued and queued[0]["request"]["incident_id"] == "L1"


def test_priority_mapping_defaults():
    assert tickets.PRIORITY_MAP == {"critical": "Highest", "high": "High",
                                    "medium": "Medium", "low": "Low"}
    req = tickets.build_ticket_request(make_incident("L9", "weird"), "x")
    assert req["priority"] == "medium"
