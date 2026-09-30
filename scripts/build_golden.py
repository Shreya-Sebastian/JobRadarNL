"""Build data/golden/golden.jsonl from the reviewed candidates.

The candidates file holds rule-based pre-labels. The overrides below are the corrections made while
reading each posting; indices not listed keep their pre-labels, indices in DROP were too ambiguous to label.
Re-run after editing overrides: python scripts/build_golden.py
"""

import json
from pathlib import Path

SRC = Path("data/golden/candidates.jsonl")
DST = Path("data/golden/golden.jsonl")

DROP = {6, 14, 20, 29, 36, 38}


def rm(*skills):
    return {"_remove": list(skills)}


def add(*skills):
    return {"_add": list(skills)}


def add_nice(*skills):
    return {"_add_nice": list(skills)}


def _apply_skills(exp: dict, ov: dict) -> None:
    """Skill corrections: `_remove` drops wrong skills, `_add` / `_add_nice` add ones the text asks for."""
    for s in ov.get("_add", []):
        if s not in exp["skills_required"]:
            exp["skills_required"].append(s)
    for s in ov.get("_add_nice", []):
        if s not in exp.setdefault("skills_nice", []) and s not in exp["skills_required"]:
            exp["skills_nice"].append(s)


OVERRIDES: dict[int, dict] = {
    0: {"role_family": "it_support", "skills_required": ["AWS", "Azure", "Mendix/Low-code"]},
    # skills added to the taxonomy on 30 Sept 2026 (IT operations), checked against each posting's text
    1: add("Windows Server/AD", "Virtualization", "Endpoint Management"),  # Windows Server, Hyper-V, SCCM
    2: {"role_family": "it_support", **add("Networking")},  # "troubleshoot network issues (mainly Cisco)"
    4: {"seniority": "senior", "role_family": "product", "remote_policy": "onsite", "degree_required": "unknown"},
    10: {"remote_policy": "onsite", "skills_required": []},
    # "2 years" in this posting is a tenure perk (travel budget), not experience asked
    11: {"role_family": "security", "skills_required": [], "seniority": "unknown", "years_experience": None},
    12: rm("Product Management"),
    13: {"visa_sponsorship": False},
    15: {"remote_policy": "onsite", **rm("Product Management")},
    16: {"degree_required": "unknown", **rm("LLMs")},  # "LLMs" came from "clients include ... OpenAI"
    17: {"skills_required": ["Machine Learning", "NLP", "LLMs", "MLOps", "Data Science"],
         "skills_nice": ["Python", "SQL", "AWS", "Azure", "GCP"]},
    18: {"remote_policy": "onsite", **rm("Monitoring/Observability")},
    19: {**rm("UX/Design"), **add("Virtualization")},  # workloads on VMware
    22: rm("UX/Design", "LLMs"),  # "LLMs" came from "clients include ... OpenAI"
    23: rm("Statistics"),  # "statistical reporting" is a regulatory regime the team reports under, not a skill
    24: rm("Product Management"),
    25: rm("UX/Design"),
    26: {"seniority": "senior", "role_family": "product", "remote_policy": "onsite", "degree_required": "unknown"},
    28: {"skills_nice": ["DevOps"], **rm("DevOps")},
    30: {"role_family": "other", **rm("Monitoring/Observability")},  # the company blurb ("Sentry is ... application
    # monitoring"), not a requirement of the role
    32: {"degree_required": "bsc", **rm("UX/Design")},
    33: {"role_family": "it_support", **add("Windows Server/AD"),  # "Active Directory, Exchange, MDM"
         **add_nice("Endpoint Management", "ITIL/ITSM", "Virtualization")},  # Intune, ITIL, virtualization
    35: {"role_family": "other"},
    39: {"dutch_required": False, "english_only": True, "seniority": "senior", **add("Networking")},  # firewalls
}

# corrections to records added later (scripts/add_golden.py), by posting id
LATER: dict[int, dict] = {
    23411: add("Networking"),  # "working knowledge of ... networking"
    23412: add("ITIL/ITSM"),  # "ITSM tooling (e.g. ServiceNow)"
}


def main() -> None:
    rows = [json.loads(line) for line in SRC.read_text(encoding="utf-8").splitlines() if line.strip()]
    out = []
    for i, r in enumerate(rows):
        if i in DROP:
            continue
        exp = dict(r["expected"])
        ov = dict(OVERRIDES.get(i, {}))
        removals = ov.pop("_remove", [])
        exp.update(ov)
        exp["skills_required"] = [s for s in exp["skills_required"] if s not in removals]
        kept_nice = ov.get("skills_nice", [])
        exp["skills_nice"] = [s for s in exp.get("skills_nice", []) if s not in removals or s in kept_nice]
        _apply_skills(exp, ov)
        for k in ("_add", "_add_nice"):
            exp.pop(k, None)
        exp["english_only"] = not exp["dutch_required"]
        out.append({"id": r["id"], "company": r["company"], "title": r["title"], "description": r["description"],
                    "expected": exp})
    # records added later (scripts/add_golden.py) are not in the candidates file: keep them as they are
    mine = {o["id"] for o in out} | {r["id"] for r in rows}
    later = [json.loads(line) for line in DST.read_text(encoding="utf-8").splitlines()
             if line.strip() and json.loads(line)["id"] not in mine] if DST.exists() else []
    for r in later:
        _apply_skills(r["expected"], LATER.get(r["id"], {}))
    out += later
    DST.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in out) + "\n", encoding="utf-8")
    print(f"wrote {len(out)} golden postings to {DST} ({len(later)} kept from later batches)")


if __name__ == "__main__":
    main()
