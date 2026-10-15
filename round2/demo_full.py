"""Live batch demo on the REAL test set: 3000 logs end-to-end + compact dashboard.
Run from round2/:  python demo_full.py [--state demo_full]   (~2-5 min, offline)"""
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

STATE = sys.argv[sys.argv.index("--state") + 1] if "--state" in sys.argv else "demo_full"
KIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rogue-protocol")

from orchestrator import run  # noqa: E402

t0 = time.time()
res = run(os.path.join(KIT, "test.csv"), STATE, KIT,
          memory_backend="faiss", use_laya=False)
dt = time.time() - t0

gen = [r for r in res if r.get("verdict") == 1]
print("logs=%d genuine=%d (%.1f%%) in %.0fs" % (len(res), len(gen), 100 * len(gen) / len(res), dt))
print("priority:", dict(Counter(r["risk"]["urgency"] for r in gen)))
print("specialist:", dict(Counter(r["routed_to"] for r in gen)))
print("schedule:", dict(Counter(r["schedule"].get("state") for r in gen)))
print("mail:", dict(Counter(r["notification"].get("status") for r in gen)))
print("duplicates suppressed:", sum(1 for r in gen if r.get("is_duplicate_of")))
print("review queue:", sum(1 for r in gen if r.get("status") == "needs_review"))
print("\nsample incidents:")
for r in gen[:3]:
    print("  %s p=%s pri=%s spec=%s sched=%s mail=%s" % (
        r["log_id"], r.get("proba"), r["risk"]["urgency"], r.get("routed_to"),
        r["schedule"].get("state"), r["notification"].get("status")))
print("\nartifacts: %s/{schedule.csv,outbox/,reports/,trace.jsonl,state/}" % STATE)
