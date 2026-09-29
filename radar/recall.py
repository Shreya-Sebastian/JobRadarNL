"""Recall check against an independent sample: how many of Adzuna's IT postings for the Netherlands are on the radar?

Adzuna (https://developer.adzuna.com) is the one licensed aggregator with a free API for individuals. Its terms
allow personal research with acknowledgement, and a 14-day trial for validating coverage; using the data
"in aggregation (including but not limited to vacancy counts...)" for ongoing work or publishing needs written
consent. So by default this module writes a private report under data/recall/ and nothing reaches the public
site. `publish=True` stores the headline numbers in the meta table for the Coverage tab; only use it after
Adzuna has agreed in writing. Employer names of unmatched postings are reported for your own coverage
planning; the terms forbid contacting content providers through Adzuna data, so treat that list as a hint to
look up an employer's public career site, not as a call list.

Matching is deliberately conservative: an Adzuna posting counts as covered only when a live radar posting has
the same normalised employer name (or one name contains the other) and a title similar enough (SequenceMatcher
ratio >= 0.8 on normalised titles, or one normalised title contained in the other).
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.classify import tech_score
from radar.config import settings
from radar.models import Meta, Posting
from radar.normalize import norm_company, norm_title
from radar.registry import classify_source, load_source_kinds

log = logging.getLogger(__name__)

API = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
META_KEY = "recall_adzuna"
_STOP = {"the", "bv", "b.v.", "nv", "n.v.", "group", "groep", "nederland", "netherlands", "holland", "europe",
         "international", "global", "company", "&", "and", "en", "de", "het"}


@dataclass
class Sample:
    id: str
    title: str
    company: str
    location: str
    url: str
    created: str
    description: str = ""
    tech: bool = True
    agency: bool = False
    matched_id: int | None = None
    employer_known: bool = False


@dataclass
class Report:
    checked_at: str
    country: str
    pages: int
    sample: int
    sample_tech: int
    sample_tech_employer: int  # tech postings not placed by an agency
    matched: int
    matched_tech: int
    matched_tech_employer: int
    recall: float
    recall_tech: float
    recall_tech_employer: float
    employer_known_unmatched: int
    missing_employers: list[dict] = field(default_factory=list)
    source: str = "Adzuna (https://www.adzuna.nl)"

    def headline(self) -> dict:
        """Compact JSON (<200 chars) for the meta table."""
        return {"ts": self.checked_at[:10], "n": self.sample, "nt": self.sample_tech,
                "nte": self.sample_tech_employer, "r": round(self.recall, 3), "rt": round(self.recall_tech, 3),
                "rte": round(self.recall_tech_employer, 3)}


def _company_key(name: str) -> str:
    toks = [t for t in norm_company(name).lower().replace("-", " ").split() if t not in _STOP]
    return " ".join(toks)


def _company_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    return (len(a) >= 5 and a in b) or (len(b) >= 5 and b in a)


def _title_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b or (len(a) >= 12 and a in b) or (len(b) >= 12 and b in a):
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.8


def fetch_sample(pages: int, country: str = "nl", category: str = "it-jobs", per_page: int = 50,
                 client: httpx.Client | None = None, max_days_old: int | None = None) -> list[Sample]:
    """Pull `pages` pages of Adzuna results (50 per page, the API maximum). Stays under the free quota:
    25 calls/minute, 250/day; we pace at 20/minute."""
    if not (settings.adzuna_app_id and settings.adzuna_app_key):
        raise RuntimeError("set RADAR_ADZUNA_APP_ID and RADAR_ADZUNA_APP_KEY (free at https://developer.adzuna.com)")
    client = client or httpx.Client(timeout=settings.http_timeout,
                                    headers={"User-Agent": settings.user_agent, "Accept": "application/json"})
    out: list[Sample] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        params = {"app_id": settings.adzuna_app_id, "app_key": settings.adzuna_app_key,
                  "results_per_page": per_page, "category": category, "content-type": "application/json"}
        if max_days_old:
            params["max_days_old"] = max_days_old
        resp = client.get(API.format(country=country, page=page), params=params)
        if resp.status_code == 429:
            log.warning("adzuna rate limit hit on page %d; stopping", page)
            break
        resp.raise_for_status()
        results = resp.json().get("results") or []
        for r in results:
            sid = str(r.get("id") or "")
            if not sid or sid in seen:
                continue
            seen.add(sid)
            out.append(Sample(
                id=sid, title=r.get("title") or "", company=((r.get("company") or {}).get("display_name") or ""),
                location=((r.get("location") or {}).get("display_name") or ""), url=r.get("redirect_url") or "",
                created=r.get("created") or "", description=r.get("description") or "",
            ))
        if len(results) < per_page:
            break
        if page < pages:
            time.sleep(3.0)  # 20 calls/minute, under Adzuna's 25/minute default
    return out


def match_sample(session: Session, sample: list[Sample]) -> list[Sample]:
    """Mark each sample posting as matched / employer known / unknown against live, non-duplicate radar postings."""
    rows = session.execute(
        select(Posting.id, Posting.title, Posting.company)
        .where(Posting.closed_at.is_(None), Posting.duplicate_of.is_(None))
    ).all()
    by_company: dict[str, list[tuple[int, str]]] = {}
    for pid, title, company in rows:
        by_company.setdefault(_company_key(company), []).append((pid, norm_title(title)))
    keys = list(by_company)
    kinds = load_source_kinds()
    for s in sample:
        s.tech = tech_score(s.title, s.description) >= 0.5
        s.agency = classify_source(s.company, s.company.lower().replace(" ", ""), kinds) == "agency"
        ck = _company_key(s.company)
        candidates = [k for k in keys if _company_match(ck, k)]
        if not candidates:
            continue
        s.employer_known = True
        nt = norm_title(s.title)
        for k in candidates:
            for pid, t in by_company[k]:
                if _title_match(nt, t):
                    s.matched_id = pid
                    break
            if s.matched_id:
                break
    return sample


def build_report(sample: list[Sample], pages: int, country: str = "nl") -> Report:
    n = len(sample)
    tech = [s for s in sample if s.tech]
    tech_emp = [s for s in tech if not s.agency]
    m = sum(1 for s in sample if s.matched_id)
    mt = sum(1 for s in tech if s.matched_id)
    mte = sum(1 for s in tech_emp if s.matched_id)
    missing = Counter(s.company for s in tech_emp if not s.matched_id and not s.employer_known)
    return Report(
        checked_at=datetime.utcnow().isoformat(timespec="seconds"), country=country, pages=pages,
        sample=n, sample_tech=len(tech), sample_tech_employer=len(tech_emp),
        matched=m, matched_tech=mt, matched_tech_employer=mte,
        recall=m / n if n else 0.0, recall_tech=mt / len(tech) if tech else 0.0,
        recall_tech_employer=mte / len(tech_emp) if tech_emp else 0.0,
        employer_known_unmatched=sum(1 for s in tech_emp if s.employer_known and not s.matched_id),
        missing_employers=[{"company": c, "postings": k} for c, k in missing.most_common(40)],
    )


def write_report(report: Report, sample: list[Sample], out_dir: Path | None = None) -> Path:
    out_dir = out_dir or Path(settings.data_dir) / "recall"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"adzuna_{report.checked_at[:10]}.json"
    payload = asdict(report)
    payload["unmatched_tech_employer_postings"] = [
        {"title": s.title, "company": s.company, "location": s.location, "url": s.url,
         "employer_known": s.employer_known}
        for s in sample if s.tech and not s.agency and not s.matched_id
    ]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def publish(session: Session, report: Report) -> None:
    """Store the headline numbers for the Coverage tab. Only with Adzuna's written consent (see module doc)."""
    value = json.dumps(report.headline(), separators=(",", ":"))
    row = session.get(Meta, META_KEY)
    if row:
        row.value = value
    else:
        session.add(Meta(key=META_KEY, value=value))
    session.flush()


def published(session: Session) -> dict | None:
    row = session.get(Meta, META_KEY)
    if not row:
        return None
    try:
        h = json.loads(row.value)
    except ValueError:
        return None
    return {"checked_at": h.get("ts"), "sample": h.get("n"), "sample_tech": h.get("nt"),
            "sample_tech_employer": h.get("nte"), "recall": h.get("r"), "recall_tech": h.get("rt"),
            "recall_tech_employer": h.get("rte"), "source": "Adzuna"}


def run(session: Session, pages: int = 20, country: str = "nl", do_publish: bool = False,
        client: httpx.Client | None = None, max_days_old: int | None = None,
        out_dir: Path | None = None) -> tuple[Report, Path]:
    sample = fetch_sample(pages, country=country, client=client, max_days_old=max_days_old)
    match_sample(session, sample)
    report = build_report(sample, pages, country)
    path = write_report(report, sample, out_dir)
    if do_publish:
        publish(session, report)
    return report, path
