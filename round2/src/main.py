"""Entry point: python -m src.main --input logs.csv --state run1 [--no-laya]"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orchestrator import run  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--state", default="run_state")
    ap.add_argument("--kit", default="")
    ap.add_argument("--memory", default="auto", choices=["auto", "faiss", "tfidf"])
    ap.add_argument("--no-laya", action="store_true")
    a = ap.parse_args()
    kit = a.kit or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "..", "rogue-protocol")
    kit = os.path.normpath(kit)
    run(a.input, a.state, kit, memory_backend=a.memory, use_laya=not a.no_laya)
