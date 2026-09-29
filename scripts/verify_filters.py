"""Apply filter combinations through the API and check that every returned posting really satisfies them.

Two levels of checking per posting:
  1. consistency: the stored fields the filter is based on (city, seniority, skills, ...) match the filter;
  2. evidence: the raw location text and description support those fields (city name present in the
     location text, no "Dutch required" phrasing for english_only, the skill's alias present in the text, ...).

Usage: python scripts/verify_filters.py [base_url]
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select

from radar.db import init_db, session_scope
from radar.extract.rules import _DUTCH_NOT_REQ, _DUTCH_REQ, detect_language
from radar.models import Posting, Source
from radar.normalize import NL_CITIES
from radar.taxonomy import COMPILED

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

CASES = [
    {"name": "junior data roles in Amsterdam", "params": {"role": "data", "seniority": "junior", "city": "Amsterdam"}},
    {
        "name": "ML or backend, junior or medior, English only",
        "params": {"role": "ml,backend", "seniority": "junior,medior", "english_only": "true"},
    },
    {
        "name": "Kubernetes skill, hybrid or remote, no agencies",
        "params": {"skill": "Kubernetes", "remote": "hybrid,remote", "exclude_agencies": "true"},
    },
    {"name": "visa sponsorship mentioned, senior", "params": {"sponsorship": "true", "seniority": "senior"}},
    {
        "name": "Eindhoven or Delft, last 30 days, embedded or platform",
        "params": {"city": "Eindhoven,Delft", "days": "30", "role": "embedded,platform"},
    },
    {
        "name": "any of Python/SQL, intern, English only, hide Deloitte",
        "params": {
            "skills_any": "Python,SQL",
            "seniority": "intern",
            "english_only": "true",
            "exclude_companies": "Deloitte",
        },
    },
    {"name": "search 'devops', Utrecht or Remote", "params": {"q": "devops", "city": "Utrecht,Remote"}},
    {
        "name": "best match sort with skills",
        "params": {"sort": "match", "skills_have": "Python,Kubernetes,SQL", "seniority": "junior,medior"},
    },
]

CITY_RX = {city: re.compile(rx, re.I) for city, rx in NL_CITIES.items()}


def check(case: dict) -> dict:
    params = dict(case["params"], size=200)
    data = httpx.get(f"{BASE}/api/postings", params=params, timeout=60).json()
    items = data["items"]
    ids = [i["id"] for i in items]
    problems: list[str] = []
    evidence_fail: list[str] = []
    p = case["params"]
    with session_scope() as s:
        rows = {
            r.id: (r, src)
            for r, src in s.execute(
                select(Posting, Source).join(Source, Source.id == Posting.source_id).where(Posting.id.in_(ids))
            )
        }
        prev_match = 2.0
        for it in items:
            r, src = rows[it["id"]]
            ex = r.extraction or {}
            tag = f"#{r.id} {r.company} | {r.title[:50]}"
            if r.closed_at is not None or r.duplicate_of is not None or not r.is_tech:
                problems.append(f"{tag}: closed/duplicate/non-tech row returned")
            if "role" in p and ex.get("role_family") not in p["role"].split(","):
                problems.append(f"{tag}: role {ex.get('role_family')} not in {p['role']}")
            if "seniority" in p and ex.get("seniority") not in p["seniority"].split(","):
                problems.append(f"{tag}: seniority {ex.get('seniority')} not in {p['seniority']}")
            if "city" in p:
                wanted = [c.lower() for c in p["city"].split(",")]
                ok = (r.city or "").lower() in wanted or ("remote" in wanted and r.remote)
                if not ok:
                    problems.append(f"{tag}: city {r.city} remote={r.remote} not in {p['city']}")
                elif r.city and not CITY_RX[r.city].search(r.location_raw or ""):
                    evidence_fail.append(f"{tag}: city {r.city} but location text is {r.location_raw!r}")
            if p.get("english_only") == "true":
                if not ex.get("english_only"):
                    problems.append(f"{tag}: english_only flag false")
                text = r.description or ""
                if _DUTCH_REQ.search(text) and not _DUTCH_NOT_REQ.search(text):
                    evidence_fail.append(
                        f"{tag}: description contains a Dutch-required phrase: "
                        f"{_DUTCH_REQ.search(text).group(0)[:60]!r}"
                    )
                if detect_language(text) == "nl" and not _DUTCH_NOT_REQ.search(text):
                    evidence_fail.append(f"{tag}: posting is written in Dutch")
            if p.get("sponsorship") == "true":
                if ex.get("visa_sponsorship") is not True:
                    problems.append(f"{tag}: visa flag {ex.get('visa_sponsorship')}")
                elif not re.search(
                    r"visa|relocation|30%|highly skilled|kennismigrant|sponsor", r.description or "", re.I
                ):
                    evidence_fail.append(f"{tag}: visa=True but no sponsorship wording in text")
            if "remote" in p:
                wanted = p["remote"].split(",")
                if ex.get("remote_policy") not in wanted and not ("remote" in wanted and r.remote):
                    problems.append(f"{tag}: remote_policy {ex.get('remote_policy')} not in {p['remote']}")
            if p.get("exclude_agencies") == "true" and src.kind == "agency":
                problems.append(f"{tag}: agency source returned")
            if "exclude_companies" in p and r.company.lower() in [c.lower() for c in p["exclude_companies"].split(",")]:
                problems.append(f"{tag}: excluded company returned")
            if "days" in p and r.first_seen < datetime.utcnow() - timedelta(days=int(p["days"])):
                problems.append(f"{tag}: first_seen {r.first_seen} older than {p['days']} days")
            skills = list(ex.get("skills_required", [])) + list(ex.get("skills_nice", []))
            if "skill" in p:
                if p["skill"] not in skills:
                    problems.append(f"{tag}: skill {p['skill']} not in {skills}")
                elif not COMPILED[p["skill"]].search((r.title or "") + "\n" + (r.description or "")):
                    evidence_fail.append(f"{tag}: skill {p['skill']} not found in text")
            if "skills_any" in p and not set(p["skills_any"].split(",")) & set(skills):
                problems.append(f"{tag}: none of {p['skills_any']} in {skills}")
            if "q" in p:
                rx = re.compile(re.escape(p["q"]), re.I)
                if not (rx.search(r.title) or rx.search(r.company)):
                    problems.append(f"{tag}: query {p['q']!r} not in title or company")
            if p.get("sort") == "match":
                if it["match"] is None or it["match"] > prev_match + 1e-9:
                    problems.append(f"{tag}: match order broken ({it['match']} after {prev_match})")
                prev_match = it["match"]
                have = set(p["skills_have"].split(","))
                if set(it["matched"]) != (set(skills) & have):
                    problems.append(f"{tag}: matched {it['matched']} != {sorted(set(skills) & have)}")
    return {
        "name": case["name"],
        "params": case["params"],
        "total": data["total"],
        "checked": len(items),
        "problems": problems,
        "evidence_fail": evidence_fail,
    }


def main() -> None:
    init_db()
    all_ok = True
    for case in CASES:
        res = check(case)
        status = "OK" if not res["problems"] else "FAIL"
        all_ok &= status == "OK"
        print(
            f"[{status}] {res['name']}: total={res['total']} checked={res['checked']} "
            f"consistency_problems={len(res['problems'])} evidence_doubts={len(res['evidence_fail'])}"
        )
        for line in res["problems"][:8]:
            print("    !!", line)
        for line in res["evidence_fail"][:5]:
            print("    ??", line)
    print("\nALL CONSISTENT" if all_ok else "\nSOME FILTERS RETURNED ROWS THAT DO NOT SATISFY THEM")


if __name__ == "__main__":
    main()
