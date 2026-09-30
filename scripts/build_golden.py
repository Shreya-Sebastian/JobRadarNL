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


OVERRIDES: dict[int, dict] = {
    0: {"role_family": "it_support", "skills_required": ["AWS", "Azure", "Mendix/Low-code"]},
    2: {"role_family": "it_support"},
    4: {"seniority": "senior", "role_family": "product", "remote_policy": "onsite", "degree_required": "unknown"},
    10: {"remote_policy": "onsite", "skills_required": []},
    # "2 years" in this posting is a tenure perk (travel budget), not experience asked
    11: {"role_family": "security", "skills_required": [], "seniority": "unknown", "years_experience": None},
    12: rm("Product Management"),
    13: {"visa_sponsorship": False},
    15: {"remote_policy": "onsite", **rm("Product Management")},
    16: {"degree_required": "unknown"},
    17: {"skills_required": ["Machine Learning", "NLP", "LLMs", "MLOps", "Data Science"],
         "skills_nice": ["Python", "SQL", "AWS", "Azure", "GCP"]},
    18: {"remote_policy": "onsite", **rm("Monitoring/Observability")},
    19: rm("UX/Design"),
    22: rm("UX/Design"),
    24: rm("Product Management"),
    25: rm("UX/Design"),
    26: {"seniority": "senior", "role_family": "product", "remote_policy": "onsite", "degree_required": "unknown"},
    28: {"skills_nice": ["DevOps"], **rm("DevOps")},
    30: {"role_family": "other"},
    32: {"degree_required": "bsc", **rm("UX/Design")},
    33: {"role_family": "it_support"},
    35: {"role_family": "other"},
    39: {"dutch_required": False, "english_only": True, "seniority": "senior"},
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
        exp["english_only"] = not exp["dutch_required"]
        out.append({"id": r["id"], "company": r["company"], "title": r["title"], "description": r["description"],
                    "expected": exp})
    # records added later (scripts/add_golden.py) are not in the candidates file: keep them as they are
    mine = {o["id"] for o in out} | {r["id"] for r in rows}
    later = [json.loads(line) for line in DST.read_text(encoding="utf-8").splitlines()
             if line.strip() and json.loads(line)["id"] not in mine] if DST.exists() else []
    out += later
    DST.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in out) + "\n", encoding="utf-8")
    print(f"wrote {len(out)} golden postings to {DST} ({len(later)} kept from later batches)")


if __name__ == "__main__":
    main()
