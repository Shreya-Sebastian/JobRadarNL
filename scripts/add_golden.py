"""Append reviewed postings to data/golden/golden.jsonl.

Usage: python scripts/add_golden.py
Each entry below names a posting id in the local database and the fields that were verified by reading the
posting; the other fields keep the rules-v4 output (the same pre-label-and-correct procedure the first 34
records used). `_remove` drops skills that were wrong. Batch 2 (27 Sept 2026) covers the employers added that
day: ING, Politie, Nike, Fugro, Nexperia, Amazon, so the golden set also exercises their page formats.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from radar.db import init_db, session_scope  # noqa: E402
from radar.extract.rules import extract_rules  # noqa: E402
from radar.models import Posting  # noqa: E402

DST = Path("data/golden/golden.jsonl")


def rm(*skills: str) -> dict:
    return {"_remove": list(skills)}


# posting id -> verified corrections (fields not listed keep the rules output)
BATCH_2: dict[int, dict] = {
    23743: {"seniority": "senior", "years_experience": 5, "english_only": True, "dutch_required": False},
    23744: {"seniority": "intern", "remote_policy": "hybrid", "english_only": True, "dutch_required": False},
    23643: {"seniority": "lead", "dutch_required": True, "english_only": False, "degree_required": "bsc",
            "salary_min_eur": 63396, "salary_max_eur": 89076, **rm("REST APIs", "Monitoring/Observability")},
    23645: {"years_experience": 3, "remote_policy": "hybrid", "dutch_required": True, "english_only": False,
            "degree_required": "bsc", "salary_min_eur": 44808, "salary_max_eur": 70584, **rm("DevOps")},
    23411: {"seniority": "senior", "years_experience": 7, "english_only": True, "dutch_required": False},
    23412: {"years_experience": 2, "degree_required": "bsc", "english_only": True, "dutch_required": False},
    23379: {"seniority": "senior", "years_experience": 8, "remote_policy": "hybrid", "salary_min_eur": 73200,
            "salary_max_eur": 92400, "english_only": True, "dutch_required": False, **rm("Ruby")},
    23380: {"seniority": "senior", "years_experience": 7, "degree_required": "bsc", "english_only": True,
            "dutch_required": False, "role_family": "qa"},
    23370: {"seniority": "intern", "degree_required": "bsc", "english_only": True, "dutch_required": False},
    23371: {"seniority": "staff", "degree_required": "bsc", "english_only": True, "dutch_required": False},
    23322: {"seniority": "junior", "years_experience": 1, "degree_required": "bsc", "dutch_required": True,
            "english_only": False},
    23323: {"seniority": "junior", "degree_required": "bsc", "dutch_required": True, "english_only": False},
}


def main() -> None:
    init_db()
    existing = {json.loads(line)["id"] for line in DST.read_text(encoding="utf-8").splitlines() if line.strip()}
    added = 0
    with session_scope() as s, DST.open("a", encoding="utf-8") as out:
        for pid, fixes in BATCH_2.items():
            if pid in existing:
                continue
            p = s.scalar(select(Posting).where(Posting.id == pid))
            if p is None:
                print("missing posting", pid)
                continue
            expected = extract_rules(p.title, p.description).model_dump()
            remove = set(fixes.pop("_remove", []))
            expected.update(fixes)
            expected["skills_required"] = [x for x in expected["skills_required"] if x not in remove]
            expected["skills_nice"] = [x for x in expected["skills_nice"] if x not in remove]
            out.write(json.dumps({"id": pid, "company": p.company, "title": p.title, "description": p.description,
                                  "expected": expected}, ensure_ascii=False) + "\n")
            added += 1
    print(f"added {added}; golden set now {len(existing) + added} records")


if __name__ == "__main__":
    main()
