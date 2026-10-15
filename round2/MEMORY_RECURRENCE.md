# Memory and recurrence handoff

## Memory contract

`memory.historian.open_memory(path, backend)` returns a store and backend name.
Both backends expose `add(log_id, text, metadata)`, `query(text, k=3, module=None)`,
`find_exact(fingerprint, module=None)`, `persisted()`, and `report()`. `docs.json` is the durable source of stable log IDs,
text, and metadata. FAISS stores a derived `index.faiss`; if the index is missing,
unreadable, or does not match the record count/dimension, it is rebuilt from the
persisted documents. TF-IDF reports its lexical search method accurately. Neither
backend claims neural semantic embeddings.

Insertion by an existing `log_id` is idempotent. Empty stores, blank queries, and
non-positive result limits return no hits. Malformed persisted JSON raises a
`ValueError` with its path so callers can distinguish corrupt state from no hits.
The orchestrator catches historian initialization, query, and persistence errors,
records the degraded operation in the run report, and continues mandatory actions.

## Recurrence helper

`tools.recurrence.analyze_recurrence(trace_rows, burst_threshold=3)` returns
fault counts grouped by module, explicit duplicate links, suppressed duplicate
IDs, repeat-offender IDs, similar-neighbor records without a duplicate link, and
module bursts. Unknown module values are grouped under `unknown`. A burst means
three or more genuine faults in one module **in this run**; it does not imply a
long-term reliability trend.

Only a persisted exact source-row fingerprint (excluding the assigned log ID) sets
`is_duplicate_of` and suppresses repeat notification/scheduling. Neighbor similarity
alone remains evidence and cannot suppress a distinct fault. This fingerprint is
deliberately strict; older memory records without one remain searchable but are not
eligible for duplicate suppression.

Generate a report from an existing trace:

```bash
cd round2
python -m src.tools.recurrence demo_run/trace.jsonl demo_run/reports/recurrence.md
```

The unit tests are in `tests/test_memory_recurrence.py`; run with `python -m pytest
tests/ -q` in an environment with the Round 2 dependencies installed.

## Artifacts and limits

Each orchestrator run writes `reports/recurrence.md` from that invocation's result
records, alongside `run_report.md`. The standalone command reads a JSONL trace and
writes the same style of report. Counts are labeled as this run; a cumulative trace
should not be interpreted as one batch unless that is intended.

FAISS is a deterministic hashed character-trigram index, not a learned semantic
embedding model. TF-IDF is lexical. Both backends return actual stable IDs and
metadata; neither implies that a repair succeeded.

## Verification record

- Base checkout: `95b959c` (`main` before these working-tree changes).
- Passed: `PYTHONPATH=/tmp/rogue_round2_pytest python -m pytest tests/ -q` —
  **22 passed**; Python syntax compilation; recurrence/report smoke check;
  `git diff --check`; end-to-end demo with five logs and two predicted faults.
- Demo evidence: exact duplicate `D4` linked to `D1`; only `D1` was scheduled and
  queued to the local outbox. Outputs were written under `/tmp`.
- Test dependencies were installed into `/tmp/rogue_round2_pytest`; the run used
  Python 3.14 with newer compatible package versions than the project's pins.
  Re-run in the team's pinned environment if exact environment parity is required.
- Added artifact: `reports/recurrence.md` per run; synthetic fixtures are explicitly
  constructed in `tests/test_memory_recurrence.py`.
