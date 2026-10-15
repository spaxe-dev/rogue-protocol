"""Entry point: python -m src.main --input logs.csv --state run1 [--no-laya]
Prints:    python -m src.main --roster | --status <state_dir>"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orchestrator import run  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def show_roster():
    for c in json.load(open(os.path.join(ROOT, "config", "crew.json"),
                            encoding="utf-8"))["crew"]:
        print("%-22s %-6s %-24s %s [%s]" % (
            c["name"], c["callsign"], c["role"],
            c["availability"], ",".join(c["tools"]) or "no-tools"))


def show_status(state_dir):
    seen = {}
    sp = os.path.join(state_dir, "state", "seen.json")
    if os.path.exists(sp):
        seen = json.load(open(sp, encoding="utf-8"))
    acts = {}
    for p in glob.glob(os.path.join(state_dir, "state", "activity", "*.jsonl")):
        cid = os.path.basename(p)[:-6]
        acts[cid] = sum(1 for _ in open(p, encoding="utf-8"))
    print("logs=%d" % len(seen))
    for cid in ["NOVA", "LYRA", "ECHO", "ATLAS", "AEGIS", "ORBIT", "PULSE"]:
        print("  %-5s actions=%d" % (cid, acts.get(cid, 0)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="")
    ap.add_argument("--state", default="run_state")
    ap.add_argument("--kit", default="")
    ap.add_argument("--memory", default="auto", choices=["auto", "faiss", "tfidf"])
    ap.add_argument("--no-laya", action="store_true")
    ap.add_argument("--roster", action="store_true")
    ap.add_argument("--status", default="")
    a = ap.parse_args(argv)
    if a.roster:
        show_roster()
        return 0
    if a.status:
        show_status(a.status)
        return 0
    if not a.input:
        ap.error("--input is required (or use --roster / --status)")
    kit = a.kit or os.path.normpath(os.path.join(ROOT, "..", "rogue-protocol"))
    results = run(a.input, a.state, kit, memory_backend=a.memory, use_laya=not a.no_laya)
    failed = [r.get("log_id") for r in results
              if (r.get("schedule") or {}).get("state") == "failed"
              or (r.get("notification") or {}).get("status") == "failed"]
    if failed:
        print("run: %d failure(s) (%s); see reports/HANDOVER.md section 7"
              % (len(failed), ",".join(failed)))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
