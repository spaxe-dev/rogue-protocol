# Kunal — Round 2 Memory and Recurrence Feature

## Goal

Round 2 asked us to build tooling around the existing Round 1 fault classifier.
My part extends the autonomous crew workflow with persistent incident memory and
recurrence reporting. The Round 1 model remains responsible for the binary fault
verdict. Memory retrieval and recurrence analysis add historical context; they do
not change the classifier's verdict.

The implementation is in `round2/`, alongside the existing Round 1 kit. It uses
local files and can run without a vector database service or model download.

## What happens to a log

The main entry point is `round2/src/orchestrator.py`.

1. The orchestrator loads `model.joblib` and `threshold.txt` through
   `round2/src/classifier.py` and gets a verdict and probability for each input log.
2. Non-faults are marked reviewed and do not enter the fault response workflow.
3. For a fault, the existing crew assesses urgency, resolves a specialist, diagnoses
   the issue, and proposes ticket, notification, and schedule actions.
4. Before specialist routing, the Historian searches earlier incidents. It returns
   up to three results with stable incident IDs, similarity scores, module, text
   excerpt, and stored metadata. Similarity is context for the engineer; it is not
   a verdict or proof of duplication.
5. The orchestrator writes the incident and response outcomes to the memory store.
6. After the batch, it creates a recurrence report for that invocation and adds a
   link to it in `reports/run_report.md`.

The existing safety gates and adapters remain responsible for notifications and
bookings. Notifications are local outbox files unless a real transport is added;
the recurrence work does not claim that a message was delivered or a repair was
completed.

## Persistent Historian

Implementation: `round2/src/memory/historian.py`.

### Backends

`open_memory(path, backend="auto")` prefers FAISS when installed and otherwise
uses TF-IDF. Both implementations share this interface:

- `add(log_id, text, metadata)` stores an incident. Re-adding an existing ID is
  idempotent.
- `query(text, k=3, module=None)` returns up to `k` ranked incidents, optionally
  filtered to a module. Empty stores, blank queries, and non-positive `k` return
  an empty list.
- `find_exact(fingerprint, module=None)` looks for an exact source-row fingerprint.
  It does not use vector similarity.
- `persisted()` reports whether the document store exists.
- `report()` returns the backend name, actual record count, persistence status, and
  a truthful description of the search method.

FAISS uses a deterministic, 512-dimensional hashed character-trigram vector and
`IndexFlatIP`; it does not use a neural embedding model. TF-IDF uses word unigrams
and bigrams, with a vocabulary capped at 5,000 features. Both are lexical similarity
methods, not semantic embedding search. Query results carry actual log IDs and
stored metadata; similarity scores are evidence only.

### Persistence and recovery

`docs.json` is the durable source of truth. Each document stores its `log_id`, text,
module and incident metadata such as verdict, assigned crew, priority, and the exact
row fingerprint. Writes use a temporary file followed by an atomic replace. FAISS
also persists a derived `index.faiss` file.

At startup, document records are checked for a stable ID, text, and duplicate IDs.
Malformed JSON or invalid records raise a path-specific `ValueError`. If the FAISS
index is missing, unreadable, or has a different vector count or dimension, it is
rebuilt from `docs.json`. The orchestrator catches initialization, query, and write
errors, records them in `run_report.md`, and continues the response workflow without
the failed memory operation. A memory error is kept distinct from a successful query
that simply found no relevant incidents.

## Conservative Duplicate Handling

Previously, the orchestrator treated a high similarity score as a duplicate and
could suppress follow-up actions. That is unsafe for distinct faults that happen to
use similar log wording.

The current flow computes a SHA-256 fingerprint of the input row after removing
only `log_id`. A prior incident is considered an exact duplicate only when the
fingerprint and module match. In that case the incident records `is_duplicate_of`,
and repeat notification and scheduling are skipped. Similar vector-search results
without an exact fingerprint remain neighbors and do not suppress actions. Older
memory records without fingerprints are still searchable but cannot trigger this
duplicate policy.

This strict comparison may miss repeats when any source field changes. That is
intentional: uncertain matches should be reviewed as similar incidents rather than
silently discarded as duplicates.

## Recurrence Radar

Implementation: `round2/src/tools/recurrence.py`, called by the orchestrator after
processing a batch.

`analyze_recurrence(trace_rows, burst_threshold=3)` returns structured facts:

- total genuine faults in the provided records;
- genuine-fault counts grouped by module, including missing modules as `unknown`;
- explicit links from a new incident ID to the prior stable ID;
- which linked incidents had notification or schedule actions suppressed;
- repeat counts grouped by the original incident ID;
- similar neighbors that have no explicit duplicate link;
- module bursts when at least three genuine faults occur in that module in the
  current orchestrator invocation.

The report uses descriptive language such as “faults in this run.” A short batch
does not support claims that a subsystem is inherently unreliable. Similarity-only
neighbors appear separately and are not counted as duplicate links.

Every orchestrator invocation writes:

- `reports/recurrence.md` — recurrence details for that invocation;
- `reports/run_report.md` — run summary, current memory backend and record count,
  any degraded memory operations, and a link to the recurrence report.

There is also a standalone report command for an existing JSONL trace. It labels its
scope as “trace records,” since a trace file can contain more than one invocation:

```bash
cd round2
python -m src.tools.recurrence demo_run/trace.jsonl demo_run/reports/recurrence.md
```

## Changed Files and Tests

- `round2/src/memory/historian.py` — persistence validation and recovery, exact
  fingerprint lookup, metadata in results, backend reports, and safer writes.
- `round2/src/tools/recurrence.py` — structured recurrence analysis, JSONL reader,
  Markdown renderer, and CLI.
- `round2/src/orchestrator.py` — exact-duplicate policy, degraded memory handling,
  per-invocation recurrence report generation, and run report status.
- `round2/tests/test_memory_recurrence.py` — restart retrieval, metadata retention,
  idempotent insertion, corrupt state diagnostics, empty queries, FAISS rebuild,
  explicit recurrence links, similarity-only neighbors, bursts, and report output.
- `round2/MEMORY_RECURRENCE.md` — concise interface and handoff notes.

The existing test suite is in `round2/tests/` and is intended to run with:

```bash
cd round2
python -m pytest tests/ -q
```

## Verification Status and Limitations

The workspace Python is 3.14. Required runtime/test packages were installed into
`/tmp/rogue_round2_pytest` so the repository and system Python stayed unchanged.
The full suite and classifier-backed demo then ran successfully. The following
checks passed:

- syntax compilation for the historian, recurrence tool, orchestrator, and new tests;
- `PYTHONPATH=/tmp/rogue_round2_pytest python -m pytest tests/ -q` — **22 passed**;
- full repository test discovery from the repo root — **26 passed**;
- end-to-end demo with `--no-laya` — five input logs processed, two faults classified,
  and exact duplicate `D4` linked to `D1`, with repeat notification and scheduling
  suppressed;
- recurrence report generation with sample JSONL;
- `git diff --check`.

The run used Python 3.14 with NumPy 2.5.4, pandas 3.0.6, SciPy 1.18.1,
scikit-learn 1.9.1, and FAISS 1.15.1 from the temporary target directory. The
project's pinned versions target a different Python environment, so the team should
also run its normal environment if exact environment parity is required. The code
is based on checkout `95b959c`.

## Round 1 Threshold Validator Mismatch

The repository currently contains conflicting Round 1 threshold records:

| Artifact | Threshold / expected result |
|---|---|
| `rogue-protocol/threshold.txt` | `0.48` |
| `rogue-protocol/metrics.md` | F1 `0.6713` at `0.48` |
| `rogue-protocol/explanation.md` | `0.54`, F1 `0.6832` |
| `rogue-protocol/validate_anubhav.py` | hard-requires `0.54` and F1 within `0.02` of `0.6832` |

I ran `submit_swayam.py` with the current threshold. It generated 3,000 binary
verdicts and the submission checker printed `TRANSMISSION VALID` (779 faults
flagged). The validation script also passed its malformed-row fault injection, but
exited with `REVISE` because `threshold.txt` contained `0.48` instead of its required
`0.54`. It reported validation F1 `0.6713` at `0.48`, which is within the validator's
`0.02` F1 tolerance from `0.6832`; the exact-threshold assertion is the failing
condition.

This is a configuration mismatch, not a CSV-format or malformed-input failure. Before
calling the Round 1 gate green, the team should choose one canonical model result and
update the threshold, metrics, explanation, and validator expectations together—or
restore `0.54` and regenerate the submission from that threshold. Do not treat the
valid CSV as evidence that the strict model-validation gate passed.
