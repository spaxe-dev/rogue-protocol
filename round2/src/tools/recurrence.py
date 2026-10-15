"""Deterministic recurrence facts derived from persisted incident traces.

Similarity neighbors are evidence only. A repeat link is reported only when an
incident has an explicit ``is_duplicate_of`` stable log ID in its trace.
"""
import argparse
import json
import os
from collections import Counter


BURST_THRESHOLD = 3  # descriptive threshold within one processed run


def analyze_recurrence(trace_rows, burst_threshold=BURST_THRESHOLD, scope="this run"):
    """Summarize genuine faults and explicit duplicate links from trace entries.

    Returns counts by module, duplicate links (new ID -> prior ID), suppressed
    duplicate IDs, repeat-offender prior IDs, and per-run module bursts. Similar
    neighbor hits without an explicit duplicate link are listed separately.
    """
    incidents = []
    for entry in trace_rows:
        if not isinstance(entry, dict):
            continue
        incident = entry.get("incident", entry)
        if isinstance(incident, dict) and "verdict" in incident:
            incidents.append(incident)

    faults = [i for i in incidents if i.get("verdict") == 1]
    counts = Counter(str(i.get("predicted_module") or "unknown") for i in faults)
    links, similar = [], []
    for incident in faults:
        log_id = str(incident.get("log_id", "unknown"))
        prior_id = incident.get("is_duplicate_of")
        schedule = incident.get("schedule") or {}
        if prior_id:
            links.append({"log_id": log_id, "prior_log_id": str(prior_id),
                          "suppressed": schedule.get("state") == "skipped"})
        elif incident.get("neighbors"):
            similar.append({"log_id": log_id,
                            "neighbor_ids": [str(n["log_id"]) for n in incident["neighbors"]
                                             if isinstance(n, dict) and n.get("log_id")]})

    prior_counts = Counter(link["prior_log_id"] for link in links)
    return {
        "scope": scope,
        "burst_threshold": burst_threshold,
        "genuine_fault_count": len(faults),
        "faults_by_module": dict(sorted(counts.items())),
        "duplicate_links": links,
        "suppressed_duplicate_ids": [x["log_id"] for x in links if x["suppressed"]],
        "repeat_offenders": [{"log_id": lid, "repeat_count": count}
                             for lid, count in sorted(prior_counts.items())],
        "similar_without_duplicate_link": similar,
        "module_bursts": [{"module": module, "fault_count": count,
                           "threshold": burst_threshold}
                          for module, count in sorted(counts.items())
                          if count >= burst_threshold],
    }


def read_trace(path):
    """Read JSONL trace, skipping no malformed lines; line errors are explicit."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError("invalid trace JSON at %s:%d: %s" % (path, line_no, exc)) from exc
    return rows


def write_report(trace_path, output_path):
    """Write a compact Markdown recurrence report from actual trace records."""
    facts = analyze_recurrence(read_trace(trace_path), scope="trace records")
    render_report(facts, output_path)
    return facts


def render_report(facts, output_path):
    """Render already-collected incident facts without rereading old runs."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Recurrence radar\n\nScope: **%s**. Counts describe these records only.\n\n" %
                facts.get("scope", "provided records"))
        f.write("Genuine faults: **%d**\n\n" % facts["genuine_fault_count"])
        f.write("## Faults by module in this run\n\n")
        f.write("| Module | Genuine faults |\n|---|---:|\n")
        for module, count in facts["faults_by_module"].items():
            f.write("| %s | %d |\n" % (module, count))
        if not facts["faults_by_module"]:
            f.write("| None | 0 |\n")
        f.write("\n## Explicit repeat links\n\n")
        if facts["duplicate_links"]:
            for link in facts["duplicate_links"]:
                tag = "suppressed duplicate" if link["suppressed"] else "linked repeat"
                f.write("- `%s` → prior `%s` (%s)\n" %
                        (link["log_id"], link["prior_log_id"], tag))
        else:
            f.write("No explicit duplicate links recorded. Similarity alone is not a duplicate.\n")
        f.write("\n## Module bursts\n\n")
        f.write("Threshold: %d genuine faults in one module for this scope.\n\n" %
                facts.get("burst_threshold", BURST_THRESHOLD))
        for burst in facts["module_bursts"]:
            f.write("- %s: %d genuine faults in this run\n" %
                    (burst["module"], burst["fault_count"]))
        if not facts["module_bursts"]:
            f.write("No module reached the threshold in this run.\n")
        f.write("\nSimilar incidents without an explicit duplicate link are not treated as duplicates.\n")
    return output_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", help="input trace.jsonl")
    parser.add_argument("output", help="output recurrence markdown")
    args = parser.parse_args(argv)
    facts = write_report(args.trace, args.output)
    print("recurrence_report=%s faults=%d links=%d" % (
        args.output, facts["genuine_fault_count"], len(facts["duplicate_links"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
