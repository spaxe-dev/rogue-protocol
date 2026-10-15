# ROGUE PROTOCOL — Round 2 Team Plan
**Revision:** post-`de3b07a` Laya fixes and `95b959c` crew-registry implementation  
**Operating mode:** deadline-driven implementation; protect the working end-to-end pipeline.

## Mission
Ship a reliable autonomous spacecraft-maintenance workflow that demonstrates:
1. Round 1 binary fault classification remains authoritative.
2. Triage can use Laya when available and deterministic policy otherwise.
3. Crew routing uses the validated `round2/config/crew.json` registry.
4. AEGIS validates every notification and booking action.
5. Incidents are stored and retrieved through persistent FAISS memory.
6. Required notifications and `schedule.csv` entries are produced honestly and idempotently.
7. Traceable artifacts make the entire decision process visible to judges.

## Current verified baseline (reported by the team)
- Commit `de3b07a`: corrected Laya `noul` probability thresholds, English routing, and singleton CPU Router; deterministic policy unchanged.
- Commit `95b959c`: crew registry, AEGIS safety gate, delegation trace, per-member activity logs, generated crew dossier, `--roster` and `--status` CLI options.
- Reported status: clean tree, 15/15 tests green, one live-Laya test deselected because the 421 MB checkpoint is not cached.
- FAISS demo was rerun: D1 booked and mailed; D4 duplicate-suppressed.
- Treat these as the starting baseline, but verify in the current checkout before relying on them.

## Workstream ownership

| Owner | Primary workstream | Owns | Must avoid |
|---|---|---|---|
| Aadit | Laya + triage | `src/crew/triage.py`, Laya-specific tests and triage evidence | Editing orchestrator/memory internals unless coordinated |
| Kunal | Historian + recurrence intelligence | `src/memory/historian.py`, recurrence helper/report contribution, isolated memory tests | Editing triage or orchestrator without agreement |
| Anubhav | Validation + schedule audit | New schedule auditor and validation tests; test fixtures | Rewriting AEGIS or changing schemas without agreement |
| Swayam | Orchestration + judge-visible reports | `src/orchestrator.py`, report generators, communications integration | Rewriting Laya/memory implementation; avoid unrelated UI |

## Shared contracts
- `round2/config/crew.json` is the single crew-registry source of truth. Do not reintroduce the deleted flat `crew.json`.
- `src/schemas.py` is the shared incident contract. Do not add fields casually; announce and document any required schema change.
- AEGIS remains the deterministic gate before notifications and bookings.
- Keep existing CLI commands and artifact paths working.
- Fault/non-fault decisions remain owned by the Round 1 classifier. Laya may inform urgency, escalation, and contradiction assessment, but cannot independently convert a non-fault into a genuine fault.
- No external service is mandatory for the core workflow. Live integrations must be feature-flagged and clearly distinguish real success from local preview/queue behavior.
- Do not claim a notification was delivered, a Jira issue was created, or a physical repair was performed without confirmation from the relevant adapter.

## Shared working protocol
1. Before editing, inspect the current branch, `git status`, recent commits, current files, and tests.
2. Read this plan and your assigned role document before substantial changes.
3. Do not reset, overwrite, or discard another teammate's work.
4. Work in your owned files. If a shared file must change, tell the team what and why before editing.
5. Make small commits with explicit messages. Do not commit secrets, model weights, caches, or generated bulky artifacts.
6. Run targeted tests, then the complete test suite from `round2/`.
7. Report completion with commit hash, files changed, tests run/results, artifact paths, and remaining risks.

## Feature priority
### P0 — protect
- Classifier integration and fault/non-fault behavior.
- Specialist routing from the validated roster.
- AEGIS safety checks.
- Notification artifact/adapter.
- Persistent memory and retrieval.
- Valid `schedule.csv` append.
- Idempotency and working end-to-end command.

### P1 — implement if P0 stays green
- `reports/HANDOVER.md` shift-handover digest.
- Recurrence radar: repeat offenders, same-module bursts, duplicate links.
- `reports/TIMELINE.md` causal workflow replay.
- Clear deception/contradiction scoring based only on existing evidence.
- Schedule audit report and crew workload balancing.

### P2 — only if time remains
- Threshold sweep report.
- Batched low-priority alert digest.
- Jira adapter/queue, only behind a disabled-by-default feature flag and only if core remains green.
- No dashboard, no heavy new dependencies, no broad refactor.

## Definition of done
- Full offline test suite passes.
- The end-to-end demo command succeeds from a clean working tree.
- Notification, trace, memory, schedule, dossier, and report artifacts are inspectable.
- Live Laya behavior is separately verified if the checkpoint is available; otherwise fallback is tested and accurately reported.
- Final commit is clean, and the team can explain the exact demo sequence without claiming unverified behavior.
