# ROUND2_FEATURES — Laya setup + Jira integration + creative-feature shortlist

Background research for ROGUE PROTOCOL 2026 Round 2 autonomous spacecraft-crew project.
Repo state verified on disk 2026-10-15 (repo root `D:\Projects\rogue-protocol\rogue-protocol\`,
`round2/` system as described in the task brief: `src/main.py`, `src/orchestrator.py`,
`src/schemas.py`, `src/classifier.py` thr 0.54, `src/crew/{triage,engineer,logistics,communications}.py`,
`src/memory/historian.py`, `src/tools/deception_detector.py`, `crew.json`, `demo_logs.csv`,
`tests/test_round2.py`). Local env confirmed: `laya 0.4.7` installed (Apache-2.0 license,
deps `huggingface_hub numpy safetensors torch transformers`), no checkpoint cached.

Citation convention: every external factual claim names its primary source URL plus what the
source says. Claims about our own code cite the local file (verified on disk).

---

## 1. LAYA SETUP brief (assignee: Aadit)

Primary sources: Laya repo README <https://github.com/NandhaKishorM/laya>,
PyPI page <https://pypi.org/project/laya/>, docs site <https://nandhakishorm.github.io/laya/>,
local `pip show laya` + installed `laya` 0.4.7 package source (`Router.__init__`/`predict`
signatures, `laya.presets`).

### 1.1 Install (exact)

- `python -m pip install laya` — README "Installation" says exactly this (PyPI page repeats it).
- **Python ≥ 3.10 required.** README "Installation details" says the floor is set by
  `huggingface_hub` 1.x, `transformers` 5.x and `torch` 2.14, which all require 3.10.
  Our env (Python 3.10.11, torch 2.14 present) satisfies this — confirmed by successful
  `import laya`, version 0.4.7, in this environment.
- No other mandatory deps: `pip show laya` lists
  `huggingface_hub, numpy, safetensors, torch, transformers`. CPU-only torch is fine;
  README says to install a CPU/GPU-specific torch build *before* Laya if needed.
- **License: Apache-2.0.** README carries the Apache-2.0 badge and a `LICENSE` file;
  `pip show laya` reports `License: Apache-2.0`. Safe to bundle/ship in contest code.

### 1.2 Router: lazy vs preload (this is the key cost decision)

- `Router()` is **lazy**: "the first prediction downloads only the selected checkpoint,
  then reuses the Hugging Face cache" (README "Model setup and troubleshooting").
  Construction alone downloads nothing — our `triage.py` comment ("no download forced
  here") is correct.
- `Router(preload=True)` "loads all three up front" (README quickstart); default keeps
  up to two checkpoints resident (`max_loaded=2`, LRU eviction; `max_loaded=1` reloads on
  every language switch, ~7–10 s). Verified against installed source:
  `Router.__init__(..., max_loaded: int = 2, ..., preload: bool = False, ...)`.
- First-use download **requires Hugging Face hub access**; README says the CLI "needs
  network access to the Hugging Face hub the first time; if a checkpoint cannot be
  downloaded, the CLI says so instead of crashing."
- Fully-offline option (README "Running from this checkout"): point the Router at local
  dirs — `Router(models={"english": "models/laya", ...}, preload=True)` — and set
  `HF_HUB_CACHE` to relocate the cache. Without a cached checkpoint and without network,
  `predict()` raises; our adapter must keep catching that (it does).

### 1.3 The three checkpoints + sizes

README checkpoint table (rows verified on both README and PyPI page):

| checkpoint | HF repo | encoder | params | context | use |
|---|---|---|---|---|---|
| `laya` | `convaiinnovations/laya` | ModernBERT-large | ~421M | 512 | English |
| `laya-multilingual` | `convaiinnovations/laya-multilingual` | mmBERT-base | ~322M | 1024 (up to 8,192 w/ `max_len=8192`) | 100+ languages, ~2x faster |
| `laya-typed-decisions` | `convaiinnovations/laya-typed-decisions` | ModernBERT-large | ~421M | 1024 | typed-decision workflows |

- Disk: `setup_laya.sh` fetches all three under `models/`, "~2.3 GB" (README).
  Per-checkpoint download size varies with weight precision/files (README troubleshooting).
- Speed reference (README, T4): single forward pass ~33 ms, 1 question ~32.8–39.5 ms GPU;
  CPU ~110–113 ms/question (english, 28-thread CPU). Venue is CPU-only: budget ~0.5 s per
  `predict()` of 3 questions after warm-up; batch via `Router.predict_batch` if needed.

### 1.4 Question schema (choice / score / noul) — exact semantics

- Input: any state (`str`, `dict`, or `list`) + a dict of typed questions:
  `choice` = pick one label, `score` = ordinal levels, `noul` = yes/no statement check
  (README "Minimal example (30 seconds)").
- Each `result["answers"][qid]` holds: `choice` = selected label, **`score` = the
  expected ordinal level** (integer index into `criteria`), **`noul` = P(true), a float
  0.0–1.0**; `confidence` is a separate field; `probabilities` exists for choice/score;
  `result["routing"]` names the checkpoint used (`routing.model`, e.g. `'english'`).
- ⚠️ **Correction to our adapter:** `src/crew/triage.py:62-67` reads
  `ans["escalate"]["noul"]` as a boolean via `bool(...)`. The real API returns a
  **probability float**, so `bool()` thresholds at >0.0 (any nonzero P(true) escalates).
  Threshold explicitly at `>= 0.5`. Same for `contradiction`.
- ⚠️ **Routing caveat for our data:** since 0.4.0 the default route for short Latin text
  carrying no language signal is `multilingual` (verified: installed
  `Router.__init__` has `default: str = 'multilingual'`; README "Supplying Your Own
  Language Detection" + quickstart). README benchmarks: English checkpoint scores 0.820
  on English vs 0.710 multilingual; break-even ~62% English traffic. **Our logs are all
  English → pin `model="english"` per call or build `Router(default="english")`.**
- ⚠️ **Perf bug in our adapter:** `laya_assess` constructs `Router()` **per log line**
  (`src/crew/triage.py:53`). Checkpoint build costs seconds; do it once (module-level
  singleton, or `preload=True` + `device="cpu"` at orchestrator start, pass router in).

### 1.5 Offline behavior — what works, what breaks

- Works offline, no download: **routing-only** calls — `router.route(...)` /
  `route_batch`, and CLI `laya "..."` *without* `--predict` ("Routing alone never
  downloads a checkpoint, so it returns in milliseconds", README "Command line").
- Breaks offline (first use): any `predict()` / `--predict` when the routed checkpoint
  is not in the HF cache — needs hub access; failure surfaces as an exception/CLI
  diagnostic. Our `laya_assess` try/except → `None` → deterministic fallback already
  handles this correctly (`src/crew/triage.py:69,77-79`); keep that shape.
- Our `assess(..., use_laya=False)` path and `test_laya_or_fallback_recorded`
  (`tests/test_round2.py:65-68`, accepts `"laya+rules"` or `"fallback"`) already encode
  offline-pass behavior. Do not weaken this test.

### 1.6 Device selection

- Automatic order: **CUDA → MPS → XPU → CPU**; mixed precision on CUDA, fp32 on CPU/MPS;
  override with `device=` on `laya.load(...)` or `Router(...)` (README "Command line",
  tail). On the venue CPU box auto-selection lands on CPU anyway, but **pin
  `device="cpu"`** for determinism (kills any MPS/CUDA probe latency and documents intent).

### 1.7 CLI presets

- `laya "text" --preset triage` answers a ready-made set; presets named in README:
  **triage, email, guard, moderation, router**. `laya.presets` module confirmed installed
  with `triage_questions, email_questions, guard_questions, moderation_questions,
  router_questions`.
- ⚠️ The shipped `triage_questions()` is **customer-support flavored** (verified from
  installed source: `intent` refund/technical_help/billing_question/…,
  `is_urgent`, `frustration`, `refund_requested`, `churn_risk`) — **not** spacecraft
  triage. Do not adopt it; keep our custom 3-question set (§1.8).

### 1.8 Extras

- README "Installation": `laya[serve]` (HTTP server), `laya[mcp]` (MCP server),
  `laya[langchain]` (LangChain + LangGraph), `laya[llamaindex]`, `laya[crewai]`,
  `laya[onnx]`, `laya[fast]` (TileLang GPU path), `laya[structured]` (pydantic in
  `decide`). **None needed for Round 2** — plain `laya` + `Router` is the whole surface.
  Explicitly do not add serve/mcp/langchain deps (network-flaky, CPU-only venue).

### 1.9 Minimal code for OUR triage questions

Drop-in replacement body for `laya_assess` in `src/crew/triage.py` (fixes §1.4 issues):

```python
_router = None
def _router():
    global _router
    if _router is None:
        from laya import Router
        _router = Router(default="english", device="cpu")  # logs are English; venue is CPU-only
    return _router

QUESTIONS = {
    "urgency": {"type": "score",
                "instructions": "How urgent is this spacecraft log?",
                "criteria": ["routine", "watch", "urgent"]},
    "escalate": {"type": "noul",
                 "instructions": "Does this need human escalation?"},
    "contradiction": {"type": "noul",
                      "instructions": "Does calm wording hide a real problem?"},
}

def laya_assess(message: str) -> dict | None:
    try:
        res = _router().predict(message, QUESTIONS, model="english")
        ans = res.get("answers", {})
        lvl = ans.get("urgency", {}).get("score", 0)
        if not isinstance(lvl, (int, float)):
            return None
        return {"urgency_level": max(0, min(2, int(lvl))),           # score = ordinal level
                "escalate": float(ans.get("escalate", {}).get("noul", 0.0)) >= 0.5,  # noul = P(true)
                "contradiction": float(ans.get("contradiction", {}).get("noul", 0.0)) >= 0.5}
    except Exception:
        return None  # no cache / no network -> deterministic_policy fallback keeps pipeline green
```

### 1.10 How the existing adapter maps (file-by-file)

- `src/crew/triage.py:deterministic_policy` — unchanged; it is the offline guarantee and
  the `use_laya=False` test path. Laya only ever adds `urgency_level ∈ {0,1,2}` mapped to
  `+1/0/-1` on the base score (`:80`); genuine-fault verdict stays with `classifier.py`.
- `src/crew/triage.py:laya_assess` — apply the §1.9 patch (singleton, english pin,
  cpu pin, noul ≥ 0.5). ~15 lines changed.
- `src/orchestrator.py:65` — no change needed (`triage.assess` signature unchanged).
- `tests/test_round2.py:65-68` — still passes either way (accepts both sources).

### 1.11 Next actions (Laya)

1. (Aadit) Patch `src/crew/triage.py:laya_assess` per §1.9 (singleton Router,
   `default="english"` + `model="english"`, `device="cpu"`, noul `>= 0.5`); keep
   `deterministic_policy` byte-identical.
2. (Aadit) Attempt one checkpoint download in background (`Router(default="english",
   preload=True)` then a single `predict`); whether it succeeds or not, record the
   outcome (bytes, seconds, or error) in `ROUND2_RECON.md`. Never gate tests on it.
3. (Aadit) Re-run `pytest tests/ -q` from `round2/` after the patch (must stay 10 green,
   offline, with and without `--predict` availability).
4. (Aadit) Optional iff download succeeded: pre-warm timing note (ms/predict on this CPU)
   appended to `demo_run/reports/run_report.md` footer; skip if it failed.

---

## 2. JIRA INTEGRATION brief

Primary sources: Jira Cloud REST v3 "Create issue"
<https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/#api-rest-api-3-issue-post>,
"Basic auth for REST APIs"
<https://developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/>,
"Issue search" (JQL)
<https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/>,
"Atlassian Document Format" structure
<https://developer.atlassian.com/cloud/jira/platform/apis/document/structure/>.

### 2.1 Minimal issue-create call

- Endpoint: **`POST https://<your-site>.atlassian.net/rest/api/3/issue`**.
  Success → `201` with `{id, key, self}` (e.g. `ED-24` in the docs example).
  Required permissions: ***Browse projects* and *Create issues* project permissions**
  (docs "Create issue" section).
- Content is defined by `fields`. Which fields are settable comes from the
  **create-metadata endpoints** (`GET /rest/api/3/issue/createmeta...` — same docs page):
  always resolve real `project`/`issuetype`/`priority` ids against the target site,
  never hardcode them blindly. Minimal practical payload:

```json
{"fields": {
  "project": {"key": "AUR"},
  "summary": "[Aurora CRITICAL] Life-Support fault D1 (p=0.93)",
  "description": {"type": "doc", "version": 1, "content": [
    {"type": "paragraph", "content": [{"type": "text", "text": "NINE log D1 classified GENUINE FAULT (p=0.93), priority critical."}]},
    {"type": "paragraph", "content": [{"type": "text", "text": "Findings: O2 trend falling; reading 16.70 outside typical band."}]}
  ]},
  "issuetype": {"name": "Task"},
  "priority": {"name": "Highest"},
  "labels": ["aurora", "D1", "C-LIFE"]
}}
```

- **ADF is mandatory for rich text:** the docs state "`description`, `environment`, and
  any `textarea` type custom fields take Atlassian Document Format content", while
  "single line custom fields (`textfield`) accept a string". Minimal valid ADF doc is
  `{"version": 1, "type": "doc", "content": [...]}` with `paragraph`/`text` nodes
  (ADF structure doc). So: build description from our `findings` list as one paragraph
  per finding — a 10-line helper, no ADF library needed.
- **Priority mapping (ours → Jira):** `critical→Highest, high→High, medium→Medium,
  low→Low`. Priority is passed as `{"id": ...}` or `{"name": ...}` (docs example uses
  `"priority": {"id": "20000"}`); names/ids vary per site, so resolve once via
  createmeta (or `GET /rest/api/3/priority`) and store ids in config. Default unknown →
  `Medium`, never fail the pipeline on a bad priority value.
- Related endpoints for later (same docs): bulk create up to **50** issues via
  `POST /rest/api/3/issue/bulk`; search via **`POST /rest/api/3/search/jql`** with a
  `{"jql": "project = AUR AND labels = D1"}` body (the legacy `GET/POST /rest/api/3/search`
  endpoints are marked "currently being removed" — use `/search/jql` for any dedupe
  check). OAuth app scope needed for server-side apps is `write:jira-work` (classic).

### 2.2 Auth — what credentials/config the adapter needs

- **Basic auth with API token** (docs "Basic auth for REST APIs"): password auth is
  deprecated; use account **email + API token** (token minted at
  `id.atlassian.com/manage/api-tokens`), sent as `curl -u email:token` or an
  `Authorization: Basic <base64(email:token)>` header. The docs explicitly frame basic
  auth as right "for simple scripts and manual calls" — i.e. exactly our contest use —
  while production apps should use OAuth 2.0 (3LO)/Forge.
- Config surface (env vars, never committed):
  `JIRA_BASE_URL` (e.g. `https://<site>.atlassian.net`),
  `JIRA_EMAIL`, `JIRA_API_TOKEN`,
  `JIRA_PROJECT_KEY`, `JIRA_ISSUETYPE` (name or id, default `Task`),
  priority map (4 entries), `JIRA_ENABLED` (`0/1`, default `0`),
  `JIRA_TIMEOUT_S` (default 10). New file `round2/jira.env.example` documents them
  with dummy values.

### 2.3 OFFLINE-SAFE design (the only acceptable shape for this venue)

Non-negotiable: the local ledger stays the source of truth; Jira is a best-effort mirror.

- `src/crew/engineer.py:file_ticket` (writes `tickets.jsonl`) **stays first and
  unconditional** — no network inside it, ever.
- New `round2/src/tools/jira_adapter.py` (~80 lines, stdlib `urllib` only, no new deps):
  `build_payload(ticket_row)` (fields + ADF description + priority map + labels),
  `post_issue(payload, cfg, timeout)` (returns issue key or raises), all exceptions
  caught by the caller.
- Call site: `src/orchestrator.py` after `engineer.file_ticket` (~line 87): if
  `JIRA_ENABLED=1`, try post with a short timeout; on success append
  `{incident_id: key}` to `state/jira_map.json`; on **any** failure append the full
  payload to `state/jira_queue.jsonl` with `{ts, error}` and continue (ticket status in
  `tickets.jsonl` remains `open`; Jira outcome recorded only in `jira_map.json` /
  `jira_queue.jsonl`, never by mutating the ledger schema in ways tests depend on).
- New `round2/src/tools/sync_jira_queue.py` (~30 lines): replays `jira_queue.jsonl`,
  skips `incident_id`s already in `jira_map.json` (idempotent), moves successes to the
  map. Runnable as `python src/tools/sync_jira_queue.py <state_dir>`.
- Tests (offline, mocked transport): `round2/tests/test_jira_adapter.py` —
  payload-shape test (ADF doc validates: `type==doc`, `version==1`, findings present),
  priority-map test (4 urgencies), queue-on-failure test (unreachable host →
  `jira_queue.jsonl` row, no exception out of `run`), replay test (stub post → map
  updated, queue drained). Zero network in tests.

### 2.4 What CANNOT be demoed without real credentials/network (explicit)

- Real issue creation (no genuine `AUR-123` keys), live transitions/assignment,
  JQL search-back/dedupe against the site, attachment upload, per-site priority/
  issuetype id resolution (ids differ per instance — must show discovery via createmeta).
- What we demo instead (honest, offline): every ticket's **exact JSON payload that
  *would* be POSTed** logged to `state/jira_preview.jsonl` on every run
  (flag-independent), plus the queue+replay flow against a local stub. Judges see the
  wire format and the failure discipline; nothing is claimed as delivered.

### 2.5 Next actions (Jira)

1. Add `round2/src/tools/jira_adapter.py` (`build_payload` with ADF description builder
   + priority map + `post_issue` on stdlib `urllib`, short timeout, raises on any HTTP/
   network error).
2. Hook `src/orchestrator.py` (~line 87, after `file_ticket`): gate on `JIRA_ENABLED`,
   try post → `state/jira_map.json`, except → `state/jira_queue.jsonl`; always also
   append payload to `state/jira_preview.jsonl`.
3. Add `round2/src/tools/sync_jira_queue.py` (idempotent replay via `jira_map.json`).
4. Add `round2/jira.env.example` + `round2/tests/test_jira_adapter.py` (4 tests, mocked
   transport, no network); re-run full suite `pytest tests/ -q` from `round2/`.

---

## 3. CREATIVE FEATURE BRAINSTORM (ranked, contest-scored)

Scoring lens: judge-visible in artifacts (RECON assumption: judges inspect
`schedule.csv`, outbox mail, memory dir, `trace.jsonl`, reports — not live infra),
CPU-only, flaky network, ~2-hour total build budget. Every proposal reads artifacts we
already produce (`trace.jsonl`, `tickets.jsonl`, `dispatch_log.csv`, `schedule.csv`,
`memory_store/`, `outbox/`, `reports/`). Ordered by value-per-minute.

### KEEP 1 — Shift-handover digest (`HANDOVER.md`) ⭐ highest value/line

- **Judge SEES:** one page in `reports/HANDOVER.md`: open criticals/highs with owner +
  booking slot, items needing review (`auto_needs_review`/`needs_review`), suppressed
  duplicates, memory backend + counts. The "crew is operational" story in 30 seconds.
- **Sketch:** new `src/tools/handover.py:main(state_dir)` (~45 lines) reads
  `trace.jsonl` (incident verdict/risk/routed/schedule/notification) + `schedule.csv`
  + `tickets.jsonl`; writes markdown with 4 fixed sections. Call at end of
  `orchestrator.run` (~line 136, next to `run_report.md` write). 1 test: sections present
  for a 2-incident fixture.
- **Cost:** ~45 lines + test, ~30 min. **Risk:** near-zero (pure reader, no pipeline
  changes). **Verdict: KEEP — build first.**

### KEEP 2 — Timeline replay (`TIMELINE.md` from `trace.jsonl`)

- **Judge SEES:** chronological per-incident causal chain
  `log → verdict(p) → urgency → deception? → specialist → mail → booking → memory` —
  proves autonomy end-to-end without reading code.
- **Sketch:** new `src/tools/timeline.py` (~40 lines) streams `trace.jsonl` incident
  dicts into one line/block each in `reports/TIMELINE.md`; hook next to KEEP 1 in
  `orchestrator.py`. Pure reader. 1 test on fixture trace.
- **Cost:** ~40 lines, ~20 min. **Risk:** near-zero. **Verdict: KEEP.**

### KEEP 3 — Recurrence radar (burst + repeat-offender lines)

- **Judge SEES:** in `run_report.md` + `HANDOVER.md`: "Life-Support: 3 genuine in this
  run (burst)", and per-incident `repeat of <log_id>` links (we already emit
  `is_duplicate_of` at `orchestrator.py:72-74` and near-repeat flags in
  `deception_detector.py:17-18` — currently invisible in reports).
- **Sketch:** ~25 lines in `src/tools/handover.py` (shared helper `recurrence(trace)`):
  count genuine per module; list `is_duplicate_of` edges. Touch `orchestrator.py`
  report block (~lines 127-135) to print burst lines. 1 test: 3 same-module faults →
  burst line present.
- **Cost:** ~25 lines, ~20 min. **Risk:** low (report-only). **Verdict: KEEP.**

### KEEP 4 — NINE deception scoring panel

- **Judge SEES:** per-incident deception score 0–3 + named flags inside each
  `reports/brief_<id>.md`, plus a "top deception" table in `run_report.md`. Turns the
  existing hidden `deception_flags` list into a scored, demo-visible instrument.
- **Sketch:** ~20-line `score(row, proba, flags)` in `src/tools/deception_detector.py`
  (1 pt each: calm-wording contradiction, redacted+reassurance, OK-status/high-proba —
  the three rules already there, `:11-15`); thread score into
  `communications.send` findings header and `orchestrator.py` report lines. 1 test:
  CRIT+calm-text scores ≥ 1.
- **Cost:** ~20 lines + 2 small call-site edits, ~20 min. **Risk:** low (additive).
  **Verdict: KEEP.**

### KEEP 5 — Specialist workload balancer (overflow → generalist)

- **Judge SEES:** `schedule.csv` with no crew double-booked under burst load, plus a
  report line "C-LIFE saturated (2 bookings) → D7 overflow to C-GEN". Autonomy under
  load — a crew-level behavior, not a single-incident one.
- **Sketch:** in `src/crew/logistics.py` add `load(rows)` counts per crew; in
  `orchestrator.py` (~line 104-109) if chosen crew has ≥2 bookings, re-route proposal
  to `C-GEN` with trace note (roster fallback already sanctioned:
  `engineer.py:61` + test `test_unknown_specialist_never_invented`). Cap as constant
  `MAX_BOOKINGS_PER_CREW = 2`. 1 test: 3rd same-crew fault → `C-GEN`.
- **Cost:** ~30 lines + test, ~20 min. **Risk:** low-medium (touches routing; keep the
  cap constant and the re-route trace-logged). **Verdict: KEEP.**

### KEEP 6 — What-if threshold simulator (`tools/threshold_sweep.py`)

- **Judge SEES:** a console + `reports/threshold_sweep.md` table sweeping classifier
  threshold 0.30–0.80 on `demo_logs.csv`: #genuine, #critical/high, #bookings,
  #mails at each cut. Shows we understand the operating point (0.54) instead of
  inheriting it blindly.
- **Sketch:** standalone script (~50 lines) reusing `classifier.predict` probas once,
  then pure arithmetic over thresholds (no re-runs, no labels claimed — columns are
  counts/actions, plus a frank "needs labeled data for precision/recall" footer).
  No orchestrator changes. 1 test: monotonic non-increasing genuine-count.
- **Cost:** ~50 lines, ~15 min. **Risk:** near-zero (side script). **Verdict: KEEP
  (stretch — build after 1–5).**

### KEEP 7 — Alert-fatigue digest (batch the lows)

- **Judge SEES:** `dispatch_log.csv` with per-incident rows *plus* one
  `DIGEST-<module>.eml` replacing N low-priority mails; `HANDOVER.md` cites the digest.
  Partially built already (suppression logic `orchestrator.py:90-94`, idempotent outbox
  `communications.py:25-27`) — this just batches what is currently suppressed into one
  visible digest mail per module.
- **Sketch:** ~35 lines in `src/crew/communications.py` (`send_digest(state_dir,
  module, incidents)`), called once at end of `run` for suppressed-low groups.
  1 test: 2 suppressed lows → 1 digest file.
- **Cost:** ~35 lines, ~15 min. **Risk:** low. **Verdict: KEEP if clock allows
  (first cut if over budget).**

### Explicit CUTs (with reasons)

- **Web dashboard / Streamlit / any UI.** CUT: RECON assumption is judges read
  artifacts; UI adds deps (likely absent), demo-time failure modes, and zero scoring
  weight. MD reports are the dashboard.
- **"Ask the historian" NL query.** CUT: no local LLM, network flaky; any demo would be
  keyword search wearing a costume. Our memory reports IDs+scores honestly instead.
- **Live Jira sync demo.** CUT live (§2.4); queued payload + replay is the honest
  offline version. Same for any cloud/service integration.
- **Calibration curve dashboard.** CUT: no labeled test data at demo time, so a
  reliability plot would be uncalibrated decoration; the sweep's count-table (§KEEP 6)
  with an explicit no-labels footer is the honest substitute.
- **Gantt-chart PNG of schedule.** CUT: `matplotlib` likely absent + new dep on a
  flaky network for marginal gain; ASCII timeline (§KEEP 2) carries the same info.
- **Contradiction spotlight as standalone.** CUT standalone — folded into KEEP 4
  (contradiction is one of the three scored points).
- **Embedding-based specialist matching (sentence-transformers).** CUT: package
  confirmed missing per RECON, download too heavy; rapidfuzz + memory-neighbor cascade
  (`engineer.py:38-61`) already covers it.

### Budget roll-up (2 h)

KEEP 1 (30) + KEEP 2 (20) + KEEP 3 (20) + KEEP 4 (20) + KEEP 5 (20) = 110 min core;
KEEP 6 (15, stretch) + KEEP 7 (15, first cut) = 140 min max. All costs are
report/reader-side except KEEP 5's small routing touch; existing 10 tests keep running
throughout (`pytest tests/ -q` from `round2/` after each item).

### Next actions (features, in order)

1. Add `round2/src/tools/handover.py` (KEEP 1 + KEEP 3 helper), hook at end of
   `src/orchestrator.py:run` next to `run_report.md`; add fixture test in
   `round2/tests/test_round2.py`.
2. Add `round2/src/tools/timeline.py` (KEEP 2), same hook point; extend report test.
3. Add `score()` to `src/tools/deception_detector.py` + surface in
   `src/crew/communications.py:send` and `src/orchestrator.py` report block (KEEP 4).
4. Add `load()` + `MAX_BOOKINGS_PER_CREW` to `src/crew/logistics.py`, re-route branch
   in `src/orchestrator.py:104-109` (KEEP 5); add overflow test.
5. (Stretch) Add `round2/src/tools/threshold_sweep.py` writing
   `reports/threshold_sweep.md` (KEEP 6).
6. (If clock) Add `send_digest` to `src/crew/communications.py` + end-of-run call
   (KEEP 7); re-run full suite.
