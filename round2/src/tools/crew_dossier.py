"""Crew dossier generator: reports/crew_dossier.md straight from the registry."""
import json
import os

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def generate(registry_path=None, out_path=None):
    registry_path = registry_path or os.path.join(ROOT, "config", "crew.json")
    out_path = out_path or os.path.join(ROOT, "reports", "crew_dossier.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    crew = json.load(open(registry_path, encoding="utf-8"))["crew"]
    lines = ["# Aurora Crew Dossier", "",
             "Source of truth: `config/crew.json`. Generated, never hand-edited.", ""]
    for c in crew:
        lines += ["## %s %s (%s) — %s" % (c["avatar_emoji"], c["name"], c["callsign"], c["crew_id"]),
                  "- Rank: %s | Role: %s | Status: %s" % (c["rank"], c["role"], c["availability"]),
                  "- Specialties: %s" % ", ".join(c["specialties"]),
                  "- Personality: %s" % c["personality"],
                  "- Comms: %s" % c["communication_style"],
                  "- Tools: %s" % (", ".join(c["tools"]) or "(none — duty specialist)"),
                  "- In: %s" % ", ".join(c["input_contract"]),
                  "- Out: %s" % ", ".join(c["output_contract"]),
                  "- Escalates to: %s" % c["escalation_target"], ""]
    open(out_path, "w", encoding="utf-8").write("\n".join(lines))
    return out_path, len(crew)


if __name__ == "__main__":
    path, n = generate()
    print("dossier: %s (%d members)" % (path, n))
