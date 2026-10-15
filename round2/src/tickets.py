"""Escalation tickets: Jira provider behind a single provider interface.

INTEGRATION GUIDE (docs snippet)
--------------------------------
Purpose: file (or queue) a Jira issue when an escalation event fires, without
ever breaking the offline/demo workflow.

Escalation events (written by the escalation workstream) land in
``<run_state>/state/escalations.jsonl`` as::

    {"incident_id": ..., "log_id": ..., "type": ..., "reason": ..., "ts": ...}

where ``type`` is ``"disagreement"`` (Laya-vs-deterministic priority split) or
``"ack-timeout"``. Shared contracts: ``incident_id == log_id``; a ticket
request is ``{incident_id, log_id, escalation_type, priority, summary,
description_md}``; a ticket result is ``{provider, key, url|None, status,
detail}`` with ``status`` in ``created|queued|failed``.

Orchestrator hook (one line, call from ``orchestrator.py`` scope)::

    from tickets import ticket_escalation; result = ticket_escalation(state_dir, incident, escalation)

``incident`` is the incident dict (keys: ``log_id, verdict, proba,
risk{urgency,score,rationale,source}, routed_to, neighbors[{log_id,score}],
notification{status}, schedule{state}``); ``escalation`` is the escalation
event (``type`` or ``escalation_type`` plus optional ``reason``).
If forensics artifacts exist (``<run_state>/state/incidents/{log_id}.json``
plus a sibling Markdown report) they are reused inline; otherwise the
description is built from the incident dict alone.

Environment (see ``.env.example`` — names only, never commit values)::

    JIRA_ENABLED      != "1" (default/unset) => DRY-RUN: append to
                        <run_state>/state/jira_queue.jsonl, return queued.
    JIRA_BASE_URL     e.g. https://your-domain.atlassian.net
    JIRA_EMAIL        Atlassian account email (Basic-auth username)
    JIRA_API_TOKEN    Atlassian API token (Basic-auth password)
    JIRA_PROJECT_KEY  Jira project key the issue is filed under

Behavior: missing credentials (even with ``JIRA_ENABLED=1``) => queued, never
created. Live creation uses ``POST {base}/rest/api/3/issue`` with fields
project key, summary, ADF description, ``issuetype: Task``, and priority mapped
critical->Highest / high->High / medium->Medium / low->Low. Priority names are
Jira defaults — confirm against your project via
``GET /rest/api/3/priority`` or ``/rest/api/3/issue/createmeta`` if creation
rejects the priority. Network/rate-limit errors (HTTP 429 / 5xx / URLError)
=> a pending event is appended to ``<run_state>/state/jira_pending.jsonl``
for retry and the result is ``failed`` with the reason; failures are NOT
cached in the idempotency map so a later retry can succeed. Idempotency key
``f"{incident_id}:{escalation_type}"`` persists in
``<run_state>/state/jira_map.json``; reprocessing returns the stored result
with a replay note and creates no duplicate (remote or queued).

Attachment limitation: ``attach_report()`` attempts the Jira Cloud
``POST /rest/api/3/issue/{key}/attachments`` endpoint, which requires
multipart/form-data with header ``X-Atlassian-Token: no-check``. Some proxies
or permission schemes reject this; when the call fails this module falls back
to inlining the forensics report excerpt into the issue description, which is
also what dry-run/offline mode always does. A successful remote attach is
never assumed — the result reports exactly what the adapter confirmed.

Only stdlib is used (urllib); no new dependencies. Linear can be added later
by subclassing ``TicketProvider`` (it needs GraphQL, hence Jira-first).
"""

import base64
import glob
import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timezone

PROVIDER_NAME = "jira"
ISSUE_TYPE = "Task"

# Jira default priority names. Confirm via /rest/api/3/priority or createmeta.
PRIORITY_MAP = {
    "critical": "Highest",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}

QUEUE_FILE = "jira_queue.jsonl"
MAP_FILE = "jira_map.json"
PENDING_FILE = "jira_pending.jsonl"


class JiraError(Exception):
    """Transport/config failure from the Jira adapter."""

    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


class TicketProvider(ABC):
    """Single provider interface; Linear can subclass this later."""

    provider = "unknown"

    @abstractmethod
    def create_issue(self, request):
        """Create a remote issue. Returns a ticket-result dict."""
        raise NotImplementedError

    def attach_file(self, issue_key, path):
        """Best-effort file attach. Returns True/False; optional."""
        return False


class JiraProvider(TicketProvider):
    """Jira Cloud REST provider (JSON over urllib, Basic auth)."""

    provider = PROVIDER_NAME

    def __init__(self, base_url, email, api_token, project_key, timeout=15):
        if not (base_url and email and api_token and project_key):
            raise JiraError("JiraProvider needs base_url, email, api_token, "
                            "project_key", retryable=False)
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key
        self.timeout = timeout
        creds = ("%s:%s" % (email, api_token)).encode("utf-8")
        self._auth = "Basic " + base64.b64encode(creds).decode("ascii")

    def _post_json(self, path, payload):
        url = self.base_url + path
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "Accept": "application/json",
                     "Authorization": self._auth})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8") or "{}"
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8")[:500]
            except Exception:
                detail = ""
            retryable = e.code == 429 or 500 <= e.code < 600
            raise JiraError("Jira HTTP %s: %s %s"
                            % (e.code, e.msg, detail), retryable=retryable)
        except urllib.error.URLError as e:
            raise JiraError("Jira network error: %s" % e, retryable=True)

    def create_issue(self, request):
        priority = PRIORITY_MAP.get(str(request.get("priority", "medium")).lower(),
                                    "Medium")
        summary = str(request.get("summary", "Escalation"))[:255]
        payload = {
            "fields": {
                "project": {"key": self.project_key},
                "summary": summary,
                "description": md_to_adf(str(request.get("description_md", ""))),
                "issuetype": {"name": ISSUE_TYPE},
                "priority": {"name": priority},
                "labels": [str(request.get("incident_id", "unknown")),
                           str(request.get("escalation_type", "unknown"))],
            }
        }
        body = self._post_json("/rest/api/3/issue", payload)
        key = body.get("key")
        if not key:
            raise JiraError("Jira response missing issue key: %s"
                            % json.dumps(body)[:300], retryable=False)
        return {"provider": PROVIDER_NAME, "key": key,
                "url": "%s/browse/%s" % (self.base_url, key),
                "status": "created",
                "detail": "Jira issue %s created in project %s (priority %s)"
                          % (key, self.project_key, priority)}

    def search_by_label(self, label):
        """Find issues carrying our incident label. Used to reconcile timeouts."""
        import urllib.parse
        jql = "labels = %s" % label
        url = "%s/rest/api/3/search?%s" % (
            self.base_url, urllib.parse.urlencode(
                {"jql": jql, "fields": "key,summary", "maxResults": 5}))
        req = urllib.request.Request(
            url, method="GET",
            headers={"Accept": "application/json",
                     "Authorization": self._auth})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            raise JiraError("Jira search HTTP %s" % e.code,
                            retryable=e.code == 429 or 500 <= e.code < 600)
        except urllib.error.URLError as e:
            raise JiraError("Jira network error: %s" % e, retryable=True)
        out = []
        for issue in body.get("issues", []) or []:
            out.append({"key": issue.get("key"),
                        "url": "%s/browse/%s" % (self.base_url, issue.get("key")),
                        "summary": ((issue.get("fields") or {}).get("summary", ""))})
        return out

    def attach_file(self, issue_key, path):
        """Try multipart attach; False on any failure (caller inlines)."""
        try:
            with open(path, "rb") as f:
                blob = f.read()
            boundary = "----rogueprotocol边界x7"
            name = os.path.basename(path)
            head = ("--%s\r\nContent-Disposition: form-data; name=\"file\"; "
                    "filename=\"%s\"\r\nContent-Type: application/octet-stream"
                    "\r\n\r\n" % (boundary, name)).encode("utf-8")
            tail = ("\r\n--%s--\r\n" % boundary).encode("utf-8")
            req = urllib.request.Request(
                "%s/rest/api/3/issue/%s/attachments" % (self.base_url, issue_key),
                data=head + blob + tail, method="POST",
                headers={"Authorization": self._auth,
                         "X-Atlassian-Token": "no-check",
                         "Content-Type": "multipart/form-data; boundary=%s"
                                         % boundary})
            with urllib.request.urlopen(req, timeout=self.timeout):
                return True
        except Exception:
            return False
        return False


# --------------------------------------------------------------------------
# paths / persistence helpers
# --------------------------------------------------------------------------

def _state_path(state_dir, filename):
    """Map a run-state dir to its inner state/ file (tolerates state/ itself)."""
    norm = os.path.normpath(state_dir)
    if os.path.basename(norm) == "state":
        path = os.path.join(norm, filename)
    else:
        path = os.path.join(norm, "state", filename)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


def _load_map(state_dir):
    path = _state_path(state_dir, MAP_FILE)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (ValueError, OSError):
            return {}
    return {}


def _save_map(state_dir, mapping):
    with open(_state_path(state_dir, MAP_FILE), "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, sort_keys=True)


def _append_jsonl(state_dir, filename, record):
    with open(_state_path(state_dir, filename), "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# description builder
# --------------------------------------------------------------------------

def _load_forensics(state_dir, log_id):
    """Reuse forensics artifacts if present: (extra_fields, report_excerpt)."""
    if not state_dir or not log_id:
        return {}, ""
    fields, excerpt = {}, ""
    candidates = []
    norm = os.path.normpath(state_dir)
    if os.path.basename(norm) == "state":
        candidates.append(os.path.join(norm, "incidents", str(log_id) + ".json"))
    else:
        candidates.append(os.path.join(norm, "state", "incidents",
                                       str(log_id) + ".json"))
        candidates.append(os.path.join(norm, "incidents", str(log_id) + ".json"))
    for cand in candidates:
        if os.path.exists(cand):
            try:
                with open(cand, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    fields = data
                for md in glob.glob(os.path.splitext(cand)[0] + "*.md"):
                    try:
                        with open(md, encoding="utf-8") as f:
                            excerpt = f.read()[:2000]
                        break
                    except OSError:
                        continue
                break
            except (ValueError, OSError):
                continue
    return fields, excerpt


def build_description_md(incident, escalation_type, reason="", state_dir=None):
    """Build the Markdown issue body from the incident dict (+ forensics)."""
    incident = dict(incident or {})
    log_id = str(incident.get("log_id", "unknown"))
    if state_dir:
        forensics, report_excerpt = _load_forensics(state_dir, log_id)
        for k, v in forensics.items():
            if isinstance(v, dict) and isinstance(incident.get(k), dict):
                merged = dict(v)
                merged.update(incident[k])
                incident[k] = merged
            else:
                incident.setdefault(k, v)
    else:
        forensics, report_excerpt = {}, ""
    risk = incident.get("risk") or {}
    urgency = str(risk.get("urgency", "medium"))
    score = risk.get("score", "?")
    source = str(risk.get("source", "fallback"))
    rationale = risk.get("rationale") or []
    raw = incident.get("raw") or {}
    neighbors = incident.get("neighbors") or []
    notification = incident.get("notification") or {}
    schedule = incident.get("schedule") or {}
    repair = incident.get("repair") or {}
    verdict = incident.get("verdict", "?")
    proba = incident.get("proba", "?")
    try:
        proba_s = "p=%.3f" % float(proba)
    except (TypeError, ValueError):
        proba_s = "p=%s" % proba
    routed_to = incident.get("routed_to", "review_queue")
    module = incident.get("predicted_module", raw.get("module", "unknown"))

    if str(escalation_type) == "disagreement":
        disagreement = ("Laya-vs-deterministic priority split: triage source "
                        "'%s' (urgency %s, score %s/5) disagrees with the "
                        "deterministic policy. %s"
                        % (source, urgency, score, reason or "See rationale."))
    elif str(escalation_type) == "ack-timeout":
        disagreement = ("Acknowledgement timeout: no ack observed for the "
                        "notification below within the expected window. %s"
                        % (reason or "See notification/ack state."))
    else:
        disagreement = ("Escalation '%s'. %s"
                        % (escalation_type, reason or "See rationale."))

    tele_keys = ["module", "mode", "node", "status", "reading",
                 "delay_ms", "retry_count", "timestamp", "message"]
    tele_lines = ["- %s: %s" % (k, raw.get(k, "?")) for k in tele_keys
                  if k in raw or True]
    if not raw:
        tele_lines = ["- no raw telemetry captured (message/module unknown)"]

    if neighbors:
        neighbor_lines = ["- %s (score %s)" % (n.get("log_id", "?"),
                                               n.get("score", "?"))
                          for n in neighbors]
    else:
        neighbor_lines = ["- none retrieved"]

    notif_state = "suppressed" if notification.get("status") == "suppressed" \
        else str(notification.get("status", "unknown"))
    if str(escalation_type) == "ack-timeout":
        ack_state = "not acknowledged (timeout)"
    elif notif_state in ("sent", "queued"):
        ack_state = "pending — confirm crew ack"
    else:
        ack_state = "no ack expected (%s)" % notif_state
    sched_state = str(schedule.get("state", "unknown"))

    unresolved = []
    if notif_state != "sent":
        unresolved.append("notification %s (ack: %s) — confirm delivery/ack"
                          % (notif_state, ack_state))
    if sched_state != "done":
        unresolved.append("schedule %s (%s) — confirm booking"
                          % (sched_state, schedule.get("reason", "no reason")))
    if risk.get("escalate"):
        unresolved.append("triage escalate flag set — needs human review")
    if risk.get("contradiction"):
        unresolved.append("contradiction flag set — verify calm wording "
                          "against readings")
    if incident.get("is_duplicate_of"):
        unresolved.append("possible duplicate of %s — confirm dedup decision"
                          % incident.get("is_duplicate_of"))
    if not unresolved:
        unresolved.append("none — all actions completed (ticket is audit trace)")

    lines = [
        "# Escalation ticket: %s [%s]" % (log_id, escalation_type),
        "",
        "## 1. Identity",
        "- incident_id: %s" % log_id,
        "- log_id: %s" % log_id,
        "- escalation_type: %s" % escalation_type,
        "- priority: %s" % urgency,
        "- routed_to: %s" % routed_to,
        "- module: %s" % module,
        "",
        "## 2. Verdict (Round 1 classifier is authoritative)",
        "- verdict: %s%s" % (verdict,
                             " (GENUINE FAULT)" if verdict == 1 else
                             " (NON-FAULT)" if verdict == 0 else ""),
        "- fault probability: %s" % proba_s,
        "- predicted module: %s" % module,
        "",
        "## 3. Priority assessment — deterministic vs Laya",
        "- triage source: %s" % source,
        "- urgency: %s (score %s/5)" % (urgency, score),
        "- escalate flag: %s; contradiction flag: %s"
        % (risk.get("escalate", False), risk.get("contradiction", False)),
        "- rationale:",
    ]
    lines += ["  - %s" % r for r in rationale] or ["  - (no rationale recorded)"]
    lines += ["- disagreement: %s" % disagreement,
              "",
              "## 4. Telemetry",
              ] + tele_lines + [
              "",
              "## 5. Similar past incidents (neighbors)",
              ] + neighbor_lines + [
              "",
              "## 6. Actions, notification/ack, schedule",
              "- routed_to: %s" % routed_to,
              "- repair job: %s" % (repair.get("job", "(none proposed)")
                                    if isinstance(repair, dict) else repair),
              "- notification channel: %s; status: %s; path: %s"
              % (notification.get("channel", "?"), notif_state,
                 notification.get("path", "")),
              "- ack: %s" % ack_state,
              "- schedule state: %s; row: %s; reason: %s"
              % (sched_state, schedule.get("row", ""),
                 schedule.get("reason", "")),
              "",
              "## 7. Unresolved items",
              ] + ["- %s" % u for u in unresolved]
    if report_excerpt:
        lines += ["",
                  "## 8. Forensics report (reused artifact, excerpt)",
                  report_excerpt]
    elif forensics:
        lines += ["",
                  "## 8. Forensics (reused artifact)",
                  "- state/incidents/%s.json reused for fields above" % log_id]
    return "\n".join(lines) + "\n"


def md_to_adf(md):
    """Minimal Markdown -> Jira ADF (headings, bullets, paragraphs)."""
    content = []
    for line in str(md).splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("### "):
            level, text = 3, s[4:]
        elif s.startswith("## "):
            level, text = 2, s[3:]
        elif s.startswith("# "):
            level, text = 1, s[2:]
        else:
            level, text = 0, s
        if text.startswith("- ") and level == 0:
            text = text[2:]
            content.append({"type": "bulletList", "content": [{
                "type": "listItem", "content": [{
                    "type": "paragraph", "content": [
                        {"type": "text", "text": text}]}]}]})
        elif level:
            content.append({"type": "heading",
                            "attrs": {"level": level},
                            "content": [{"type": "text", "text": text}]})
        else:
            content.append({"type": "paragraph",
                            "content": [{"type": "text", "text": text}]})
    if not content:
        content = [{"type": "paragraph",
                    "content": [{"type": "text", "text": "(empty)"}]}]
    return {"type": "doc", "version": 1, "content": content}


# --------------------------------------------------------------------------
# request / entry points
# --------------------------------------------------------------------------

def build_ticket_request(incident, escalation_type, reason="", state_dir=None):
    """Assemble the shared-contract ticket request dict."""
    incident = incident or {}
    log_id = str(incident.get("log_id", "unknown"))
    risk = incident.get("risk") or {}
    priority = str(risk.get("urgency", "medium")).lower()
    if priority not in PRIORITY_MAP:
        priority = "medium"
    summary = "[%s] %s escalation %s (routed %s)" % (
        priority.upper(), escalation_type, log_id,
        incident.get("routed_to", "review_queue"))
    return {"incident_id": log_id,
            "log_id": log_id,
            "escalation_type": str(escalation_type),
            "priority": priority,
            "summary": summary[:255],
            "description_md": build_description_md(
                incident, escalation_type, reason, state_dir)}


def _load_dotenv():
    """Load round2/.env (KEY=VALUE lines, stdlib only) without overriding real env."""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", ".env"),
                 os.path.join(os.getcwd(), ".env")):
        try:
            with open(os.path.normpath(cand), encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())
        except OSError:
            continue


def provider_from_env():
    """Return (provider|None, reason). Enabled only when JIRA_ENABLED=1."""
    _load_dotenv()
    if os.environ.get("JIRA_ENABLED") != "1":
        return None, "dry-run (JIRA_ENABLED != 1)"
    base = os.environ.get("JIRA_BASE_URL", "").strip()
    email = os.environ.get("JIRA_EMAIL", "").strip()
    token = os.environ.get("JIRA_API_TOKEN", "")
    project = os.environ.get("JIRA_PROJECT_KEY", "").strip()
    missing = [k for k, v in (("JIRA_BASE_URL", base), ("JIRA_EMAIL", email),
                              ("JIRA_API_TOKEN", token),
                              ("JIRA_PROJECT_KEY", project)) if not v]
    if missing:
        return None, "missing credentials: %s" % ", ".join(missing)
    try:
        return (JiraProvider(base, email, token, project),
                "live (JIRA_ENABLED=1)")
    except JiraError as e:
        return None, str(e)


def create_ticket(request, state_dir, provider=None):
    """File or queue one ticket. Returns a ticket-result dict.

    Idempotent on ``incident_id:escalation_type``; dry-run queues when the
    provider is unavailable; transport failures append a pending retry event.
    """
    request = dict(request or {})
    incident_id = str(request.get("incident_id")
                      or request.get("log_id", "unknown"))
    escalation_type = str(request.get("escalation_type", "unknown"))
    idem = "%s:%s" % (incident_id, escalation_type)

    mapping = _load_map(state_dir)
    if idem in mapping:
        replay = dict(mapping[idem])
        replay["detail"] = "%s [idempotent replay: no duplicate created]" \
            % replay.get("detail", "")
        return replay

    if provider is None:
        provider, why = provider_from_env()
        if provider is None:
            _append_jsonl(state_dir, QUEUE_FILE,
                          {"idempotency_key": idem, "request": request,
                           "ts": _utcnow(), "reason": why})
            result = {"provider": PROVIDER_NAME, "key": None, "url": None,
                      "status": "queued",
                      "detail": "queued locally, never claimed as created "
                                "(%s); set JIRA_ENABLED=1 with credentials "
                                "to create remotely" % why}
            mapping[idem] = result
            _save_map(state_dir, mapping)
            return result

    try:
        result = provider.create_issue(request)
    except JiraError as e:
        _append_jsonl(state_dir, PENDING_FILE,
                      {"idempotency_key": idem, "request": request,
                       "ts": _utcnow(), "error": str(e),
                       "retryable": bool(e.retryable)})
        return {"provider": getattr(provider, "provider", PROVIDER_NAME),
                "key": None, "url": None, "status": "failed",
                "detail": "not created (%s); pending retry event recorded"
                          % e}
    except Exception as e:  # defensive: never crash the pipeline
        return {"provider": getattr(provider, "provider", PROVIDER_NAME),
                "key": None, "url": None, "status": "failed",
                "detail": "not created (unexpected %s: %s)"
                          % (type(e).__name__, e)}
    mapping[idem] = result
    _save_map(state_dir, mapping)
    return result


def reconcile(state_dir, request, provider):
    """After a possible-timeout: adopt an already-created issue instead of
    duplicating. Returns a ticket-result or None (nothing found -> retry)."""
    request = dict(request or {})
    label = str(request.get("incident_id") or request.get("log_id", "unknown"))
    try:
        hits = provider.search_by_label(label)
    except JiraError:
        return None
    if not hits:
        return None
    hit = hits[0]
    result = {"provider": getattr(provider, "provider", PROVIDER_NAME),
              "key": hit["key"], "url": hit["url"], "status": "created",
              "detail": "reconciled: %s already exists, adopted (no duplicate)"
                        % hit["key"]}
    mapping = _load_map(state_dir)
    idem = "%s:%s" % (label, request.get("escalation_type", "unknown"))
    mapping[idem] = result
    _save_map(state_dir, mapping)
    return result


def retry_pending(state_dir, provider=None):
    """Retry queued/pending events: reconcile-first, then recreate. Returns list."""
    if provider is None:
        provider, _ = provider_from_env()
        if provider is None:
            return []
    outcomes = []
    pend_path = _state_path(state_dir, PENDING_FILE)
    try:
        pending = [json.loads(l) for l in open(pend_path, encoding="utf-8")
                   if l.strip()]
    except (OSError, ValueError):
        pending = []
    remaining = []
    for ev in pending:
        req = ev.get("request", {})
        if not ev.get("retryable", False):
            remaining.append(ev)
            outcomes.append({"idempotency_key": ev.get("idempotency_key"),
                             "status": "failed",
                             "detail": "not retryable, left pending"})
            continue
        adopted = reconcile(state_dir, req, provider)
        if adopted:
            outcomes.append(adopted)
            continue
        try:
            outcomes.append(create_ticket(req, state_dir, provider))
        except Exception as e:  # defensive
            remaining.append(ev)
            outcomes.append({"status": "failed", "detail": str(e)[:200]})
    with open(pend_path, "w", encoding="utf-8") as f:
        for ev in remaining:
            f.write(json.dumps(ev) + "\n")
    return outcomes


def ticket_escalation(state_dir, incident, escalation, provider=None):
    """Orchestrator hook: ticket one escalation event. See module docstring."""
    escalation = escalation or {}
    incident = incident or {}
    esc_type = str(escalation.get("escalation_type")
                   or escalation.get("type", "unknown"))
    reason = str(escalation.get("reason", ""))
    request = build_ticket_request(incident, esc_type, reason, state_dir)
    # escalation wins for identity (incident_id == log_id by contract).
    for k in ("incident_id", "log_id"):
        if escalation.get(k):
            request[k] = str(escalation[k])
    return create_ticket(request, state_dir, provider)


def attach_report(provider, issue_key, report_path):
    """Best-effort attach; False means the caller keeps the inlined excerpt."""
    try:
        return bool(provider.attach_file(issue_key, report_path))
    except Exception:
        return False
