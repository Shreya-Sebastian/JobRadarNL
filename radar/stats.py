"""Aggregations over live tech postings.

Prototype approach: load the live set into memory with a short TTL cache and aggregate in Python.
At tens of thousands of rows this is milliseconds; production replaces it with materialised views.
"""

from __future__ import annotations

import re
import statistics
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import combinations
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from radar.models import CrawlRun, Posting, Source
from radar.taxonomy import find_skills


@dataclass
class Row:
    id: int
    title: str
    company: str
    city: str | None
    remote: bool
    url: str
    posted_at: datetime | None
    first_seen: datetime
    closed_at: datetime | None
    ats: str
    ex: dict[str, Any] = field(default_factory=dict)
    kind: str = "employer"
    org_roles: int = 0  # open roles this organisation has on the radar, all fields (size estimate)
    last_seen: datetime | None = None  # last crawl at which the employer's own board still listed it
    link_checked_at: datetime | None = None
    link_status: str | None = None
    valid_through: datetime | None = None
    also_in: list[str] = field(default_factory=list)  # other cities of the same vacancy

    @property
    def confirmed_at(self) -> datetime | None:
        """Most recent evidence that the vacancy is live: listed on the employer's board, or its page checked."""
        times = [t for t in (self.last_seen, self.link_checked_at if self.link_status == "ok" else None) if t]
        return max(times) if times else None

    @property
    def org_size(self) -> str:
        return org_size_band(self.org_roles)

    @property
    def skills(self) -> list[str]:
        seen: dict[str, None] = {}
        for s in self.ex.get("skills_required", []) + self.ex.get("skills_nice", []):
            seen.setdefault(s, None)
        return list(seen)

    @property
    def experience(self) -> str:
        return experience_band(self.ex, self.title)


ORG_SIZE_BANDS = ("small", "medium", "large")


def org_size_band(open_roles: int) -> str:
    """Estimated from open roles, not headcount: under 10 = small team, 10-99 = mid-size, 100+ = large."""
    if open_roles >= 100:
        return "large"
    if open_roles >= 10:
        return "medium"
    return "small"


EXPERIENCE_BANDS = ("none", "1", "2-3", "4-5", "6+", "unspecified")
_EARLY_TITLE = re.compile(
    r"graduate|trainee|traineeship|internship|\bintern\b|\bstage\b|stagiair|afstudeer|werkstudent|working student|"
    r"young professional|starter|\bjunior\b",
    re.I,
)


def experience_band(ex: dict[str, Any], title: str = "") -> str:
    """Years of experience the posting asks for, in bands. "none" is reserved for entry-level roles (intern,
    junior, graduate, trainee, starter) that state no years at all; a senior posting that merely omits the
    number is "unspecified", so the "no experience asked" filter never leaks experienced roles."""
    years = ex.get("years_experience")
    if not years:
        if ex.get("seniority") in ("intern", "trainee", "junior") or _EARLY_TITLE.search(title or ""):
            return "none"
        return "unspecified"
    if years <= 1:
        return "1"
    if years <= 3:
        return "2-3"
    if years <= 5:
        return "4-5"
    return "6+"


def _csv(value: str | None) -> set[str]:
    return {v.strip().lower() for v in value.split(",") if v.strip()} if value else set()


@dataclass
class Filters:
    """Every field is optional; comma-separated values mean "any of". Used by the API and the profile."""

    role: str | None = None
    seniority: str | None = None
    city: str | None = None
    company: str | None = None
    english_only: bool | None = None
    sponsorship: bool | None = None
    remote: str | None = None
    days: int | None = None
    q: str | None = None
    skill: str | None = None
    include_closed: bool = False
    exclude_agencies: bool = False
    exclude_companies: str | None = None
    since: str | None = None  # ISO timestamp: only postings first seen after this
    skills_any: str | None = None  # posting mentions at least one of these skills
    ids: str | None = None  # explicit posting ids (saved jobs)
    language: str | None = None  # "nl": Dutch required or posted in Dutch; "en": no Dutch required; None: either
    experience: str | None = None  # comma list of EXPERIENCE_BANDS: years of experience the posting asks for
    enrollment: str | None = None  # "open": drop postings that require study enrolment; "required": only those
    org_size: str | None = None  # comma list of ORG_SIZE_BANDS
    confirmed_days: int | None = None  # only postings confirmed live within this many days

    def apply(self, rows: list[Row]) -> list[Row]:
        out = rows
        if not self.include_closed:
            out = [r for r in out if r.closed_at is None]
        if self.ids:
            wanted = {int(i) for i in self.ids.split(",") if i.strip().isdigit()}
            out = [r for r in out if r.id in wanted]
        if self.days:
            cutoff = datetime.utcnow() - timedelta(days=self.days)
            out = [r for r in out if r.first_seen >= cutoff]
        if self.since:
            try:
                cutoff = datetime.fromisoformat(self.since.replace("Z", ""))
                out = [r for r in out if r.first_seen > cutoff]
            except ValueError:
                pass
        roles = _csv(self.role)
        if roles:
            out = [r for r in out if (r.ex.get("role_family") or "") in roles]
        levels = _csv(self.seniority)
        if levels:
            out = [r for r in out if (r.ex.get("seniority") or "") in levels]
        bands = _csv(self.experience)
        if bands:
            out = [r for r in out if r.experience in bands]
        if self.confirmed_days:
            since = datetime.utcnow() - timedelta(days=self.confirmed_days)
            out = [r for r in out if r.confirmed_at and r.confirmed_at >= since]
        sizes = _csv(self.org_size)
        if sizes:
            out = [r for r in out if r.org_size in sizes]
        if self.enrollment == "open":
            out = [r for r in out if r.ex.get("enrollment_required") is not True]
        elif self.enrollment == "required":
            out = [r for r in out if r.ex.get("enrollment_required") is True]
        elif self.enrollment == "stated_open":
            out = [r for r in out if r.ex.get("enrollment_required") is False]
        cities = _csv(self.city)
        if cities:
            out = [r for r in out if (r.city or "").lower() in cities or ("remote" in cities and r.remote)
                   or any(c.lower() in cities for c in r.also_in)]
        if self.company:
            out = [r for r in out if r.company.lower() == self.company.lower()]
        excluded = _csv(self.exclude_companies)
        if excluded:
            out = [r for r in out if r.company.lower() not in excluded]
        if self.exclude_agencies:
            out = [r for r in out if r.kind != "agency"]
        if self.english_only or self.language == "en":
            out = [r for r in out if r.ex.get("english_only")]
        elif self.language == "nl":
            # Dutch only: Dutch is required and English is not, for people who work in Dutch
            out = [r for r in out if (r.ex.get("dutch_required") or r.ex.get("posting_language") == "nl")
                   and r.ex.get("english_required") is False]
        if self.sponsorship:
            out = [r for r in out if r.ex.get("visa_sponsorship") is True]
        remotes = _csv(self.remote)
        if remotes and {"remote", "hybrid", "onsite"} <= set(remotes):
            remotes = []  # every policy ticked means "any", including postings that do not state one
        if remotes:
            # The board's "remote" flag only counts when the posting text does not say hybrid or on-site.
            out = [
                r
                for r in out
                if (r.ex.get("remote_policy") or "") in remotes
                or (
                    "remote" in remotes
                    and r.remote
                    and (r.ex.get("remote_policy") or "unknown") in ("unknown", "remote")
                )
            ]
        if self.skill:
            out = [r for r in out if self.skill in r.skills]
        any_of = {s.strip() for s in (self.skills_any or "").split(",") if s.strip()}
        if any_of:
            out = [r for r in out if any_of & set(r.skills)]
        if self.q:
            rx = re.compile(re.escape(self.q), re.I)
            # title, employer, or an extracted skill ("simulation" finds CFD and FEA roles titled
            # "Mechanical Engineer")
            out = [r for r in out if rx.search(r.title) or rx.search(r.company) or any(rx.search(k) for k in r.skills)]
        return out


class _Cache:
    """Per-process copy of the live rows. Reloaded when the TTL expires or when a finalize job bumps the
    shared data version in Redis, so every API replica picks up a finished crawl within one request."""

    def __init__(self, ttl: float = 300.0):
        self.ttl = ttl
        self._rows: list[Row] | None = None
        self._at = 0.0
        self._version = ""
        self._lock = threading.Lock()

    def rows(self, session: Session) -> list[Row]:
        from radar.cache import data_version

        version = data_version()
        with self._lock:
            fresh = self._rows is not None and time.monotonic() - self._at < self.ttl and version == self._version
            if fresh:
                return self._rows
            if self._rows is None:
                # first request in this process: nothing to serve yet, load synchronously
                self._rows = load_rows(session)
                self._at = time.monotonic()
                self._version = version
                return self._rows
            if not self._refreshing:
                # serve the stale rows now; refresh in the background so no request pays the 2-second reload
                self._refreshing = True
                threading.Thread(target=self._refresh, args=(version,), daemon=True).start()
            return self._rows

    _refreshing = False

    def _refresh(self, version: str) -> None:
        from radar.db import new_session

        session = new_session()
        try:
            rows = load_rows(session)
            with self._lock:
                self._rows = rows
                self._at = time.monotonic()
                self._version = version
        finally:
            session.close()
            with self._lock:
                self._refreshing = False

    def invalidate(self) -> None:
        with self._lock:
            self._rows = None


CACHE = _Cache()


def load_rows(session: Session, include_closed_days: int = 90) -> list[Row]:
    """Tech, non-duplicate postings: all live ones plus those closed in the last N days (for trends)."""
    cutoff = datetime.utcnow() - timedelta(days=include_closed_days)
    stmt = (
        select(Posting, Source.ats, Source.kind)
        .join(Source, Source.id == Posting.source_id)
        .where(Posting.is_tech.is_(True), Posting.duplicate_of.is_(None))
        .where((Posting.closed_at.is_(None)) | (Posting.closed_at >= cutoff))
    )
    open_roles = dict(session.execute(
        select(Posting.company, func.count())
        .where(Posting.closed_at.is_(None), Posting.duplicate_of.is_(None))
        .group_by(Posting.company)
    ).all())
    rows: list[Row] = []
    for p, ats, kind in session.execute(stmt):
        rows.append(
            Row(
                p.id,
                p.title,
                p.company,
                p.city,
                p.remote,
                p.url,
                p.posted_at,
                p.first_seen,
                p.closed_at,
                ats,
                p.extraction or {},
                kind or "employer",
                open_roles.get(p.company, 0),
                p.last_seen,
                p.link_checked_at,
                p.link_status,
                p.valid_through,
                p.also_in or [],
            )
        )
    return rows


def overview(session: Session) -> dict[str, Any]:
    live = session.scalar(
        select(func.count()).select_from(Posting).where(Posting.closed_at.is_(None), Posting.duplicate_of.is_(None))
    )
    live_tech = session.scalar(
        select(func.count())
        .select_from(Posting)
        .where(Posting.closed_at.is_(None), Posting.duplicate_of.is_(None), Posting.is_tech.is_(True))
    )
    companies = session.scalar(
        select(func.count(func.distinct(Posting.company))).where(Posting.closed_at.is_(None), Posting.is_tech.is_(True))
    )
    sources_total = session.scalar(select(func.count()).select_from(Source))
    sources_active = session.scalar(select(func.count()).select_from(Source).where(Source.active.is_(True)))
    sources_ok = session.scalar(select(func.count()).select_from(Source).where(Source.last_status == "ok"))
    # the last *finished* crawl: while a crawl is running the newest run has no finish time yet
    last_run = session.scalar(select(CrawlRun).where(CrawlRun.finished_at.is_not(None))
                              .order_by(CrawlRun.finished_at.desc()).limit(1))
    # Freshness only makes sense for postings that appeared after we started watching their source:
    # a source's backlog is "seen" at its first crawl regardless of when it was posted.
    fresh_rows = session.execute(
        select(Posting.posted_at, Posting.first_seen, Source.first_success_at)
        .join(Source, Source.id == Posting.source_id)
        .where(
            Posting.posted_at.isnot(None),
            Source.first_success_at.isnot(None),
            Posting.first_seen >= datetime.utcnow() - timedelta(days=14),
        )
    ).all()
    fresh = [
        (first_seen - posted_at).total_seconds() / 3600
        for posted_at, first_seen, first_ok in fresh_rows
        if first_seen > first_ok + timedelta(minutes=10) and first_seen >= posted_at
    ]
    # "New" means published in the last week: the employer's own posting date where it gives one; otherwise first
    # seen, but only when that was after the source's first crawl (a new source's whole backlog is not "new").
    week = datetime.utcnow() - timedelta(days=7)
    new_7d = session.scalar(
        select(func.count())
        .select_from(Posting)
        .join(Source, Source.id == Posting.source_id)
        .where(Posting.is_tech.is_(True), Posting.closed_at.is_(None), Posting.duplicate_of.is_(None))
        .where(
            (Posting.posted_at >= week)
            | (Posting.posted_at.is_(None) & (Posting.first_seen >= week)
               & (Posting.first_seen > Source.first_success_at + timedelta(minutes=10)))
        )
    )
    closed_7d = session.scalar(
        select(func.count())
        .select_from(Posting)
        .where(Posting.is_tech.is_(True), Posting.closed_at >= datetime.utcnow() - timedelta(days=7))
    )
    return {
        "live_postings": live,
        "live_tech_postings": live_tech,
        "companies": companies,
        "sources_total": sources_total,
        "sources_active": sources_active,
        "sources_ok": sources_ok,
        "new_last_7d": new_7d,
        "closed_last_7d": closed_7d,
        "freshness_median_hours": round(statistics.median(fresh), 1) if fresh else None,
        "last_crawl_at": last_run.finished_at.isoformat() if last_run and last_run.finished_at else None,
    }


def skill_counts(rows: list[Row], top: int = 40) -> list[dict[str, Any]]:
    n = len(rows) or 1
    c: Counter[str] = Counter()
    req: Counter[str] = Counter()
    for r in rows:
        for s in r.skills:
            c[s] += 1
        for s in r.ex.get("skills_required", []):
            req[s] += 1
    return [{"skill": s, "count": k, "share": round(k / n, 4), "required": req[s]} for s, k in c.most_common(top)]


def cooccurrence(rows: list[Row], top: int = 30, min_pair: int = 3) -> dict[str, Any]:
    top_skills = [d["skill"] for d in skill_counts(rows, top)]
    idx = set(top_skills)
    pairs: Counter[tuple[str, str]] = Counter()
    counts: Counter[str] = Counter()
    for r in rows:
        sk = sorted(s for s in r.skills if s in idx)
        for s in sk:
            counts[s] += 1
        for a, b in combinations(sk, 2):
            pairs[(a, b)] += 1
    nodes = [{"id": s, "count": counts[s]} for s in top_skills if counts[s]]
    links = [
        {"source": a, "target": b, "weight": w, "lift": round(w * len(rows) / max(1, counts[a] * counts[b]), 2)}
        for (a, b), w in pairs.items()
        if w >= min_pair
    ]
    links.sort(key=lambda link: -link["weight"])
    return {"nodes": nodes, "links": links[:200]}


def breakdown(rows: list[Row], key: str, top: int = 20) -> list[dict[str, Any]]:
    c: Counter[str] = Counter()
    for r in rows:
        if key == "city":
            v = r.city or ("Remote" if r.remote else "Unknown")
        elif key == "company":
            v = r.company
        elif key == "experience":
            v = r.experience
        elif key == "org_size":
            v = r.org_size
        elif key == "ats":
            v = r.ats
        else:
            v = str(r.ex.get(key, "unknown"))
        c[v] += 1
    n = len(rows) or 1
    return [{"key": k, "count": v, "share": round(v / n, 4)} for k, v in c.most_common(top)]


def trends(rows: list[Row], skills: list[str] | None = None, weeks: int = 12) -> dict[str, Any]:
    """Postings first seen per ISO week, overall and per skill."""
    start = datetime.utcnow() - timedelta(weeks=weeks)
    buckets: dict[str, Counter[str]] = {}
    total: Counter[str] = Counter()
    for r in rows:
        if r.first_seen < start:
            continue
        wk = r.first_seen.strftime("%G-W%V")
        total[wk] += 1
        for s in r.skills:
            if skills is None or s in skills:
                buckets.setdefault(s, Counter())[wk] += 1
    weeks_sorted = sorted(total)
    if skills is None:
        # nothing followed: plot the five most-asked skills, not all ninety
        top = sorted(buckets, key=lambda s: -sum(buckets[s].values()))[:5]
        buckets = {s: buckets[s] for s in top}
    return {
        "weeks": weeks_sorted,
        "total": [total[w] for w in weeks_sorted],
        "series": {s: [c[w] for w in weeks_sorted] for s, c in buckets.items()},
    }


def salary(rows: list[Row]) -> dict[str, Any]:
    mids = []
    for r in rows:
        lo, hi = r.ex.get("salary_min_eur"), r.ex.get("salary_max_eur")
        if lo:
            mids.append((lo + hi) / 2 if hi else lo)
    if not mids:
        return {"n": 0}
    mids.sort()
    q = statistics.quantiles(mids, n=4) if len(mids) >= 4 else [mids[0], mids[len(mids) // 2], mids[-1]]
    return {
        "n": len(mids),
        "p25": round(q[0]),
        "median": round(q[1]),
        "p75": round(q[2]),
        "min": round(mids[0]),
        "max": round(mids[-1]),
    }


def match_score(r: Row, have: set[str]) -> float:
    sk = set(r.skills)
    if not sk or not have:
        return 0.0
    return len(sk & have) / max(len(sk), 3)


def posting_dicts(
    rows: list[Row], page: int = 1, size: int = 50, sort: str = "newest", have_skills: set[str] | None = None
) -> dict[str, Any]:
    have = have_skills or set()
    newest = sorted(rows, key=lambda r: r.posted_at or r.first_seen, reverse=True)
    if sort == "match" and have:
        rows = sorted(rows, key=lambda r: (match_score(r, have), r.posted_at or r.first_seen), reverse=True)
    elif sort == "size_small":
        rows = sorted(newest, key=lambda r: r.org_roles)  # stable: newest first within an organisation
    elif sort == "size_large":
        rows = sorted(newest, key=lambda r: -r.org_roles)
    else:
        rows = newest
    total = len(rows)
    start = (page - 1) * size
    items = [
        {
            "id": r.id,
            "title": r.title,
            "company": r.company,
            "city": r.city,
            "also_in": r.also_in,
            "remote": r.remote,
            "url": r.url,
            "posted_at": (r.posted_at or r.first_seen).date().isoformat(),
            "first_seen": r.first_seen.isoformat(),
            "closed": r.closed_at is not None,
            "role": r.ex.get("role_family"),
            "seniority": r.ex.get("seniority"),
            "years": r.ex.get("years_experience"),
            "experience": r.experience,
            "enrollment_required": r.ex.get("enrollment_required"),
            "skills": r.skills[:12],
            "english_only": r.ex.get("english_only"),
            "english_required": r.ex.get("english_required"),
            "visa": r.ex.get("visa_sponsorship"),
            "remote_policy": r.ex.get("remote_policy"),
            "salary_min": r.ex.get("salary_min_eur"),
            "salary_max": r.ex.get("salary_max_eur"),
            "ats": r.ats,
            "via_agency": r.kind == "agency",
            "org_size": r.org_size,
            "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
            "link_checked_at": r.link_checked_at.isoformat() if r.link_checked_at else None,
            "link_status": r.link_status,
            "valid_through": r.valid_through.date().isoformat() if r.valid_through else None,
            "source_kind": r.kind,
            "org_roles": r.org_roles,
            "age_days": max(0, (datetime.utcnow() - (r.posted_at or r.first_seen)).days),
            "match": round(match_score(r, have), 2) if have else None,
            "matched": sorted(set(r.skills) & have) if have else [],
            "missing": sorted(set(r.skills) - have)[:6] if have else [],
        }
        for r in rows[start : start + size]
    ]
    return {"total": total, "page": page, "size": size, "items": items}


def gap_analysis(
    rows: list[Row],
    cv_text: str | None = None,
    skills: list[str] | None = None,
    top_missing: int = 15,
    top_matches: int = 20,
) -> dict[str, Any]:
    """Compare the skills found in a CV (or an explicit skill list) with the skills demanded by the postings."""
    from radar.taxonomy import canonicalise

    have = set(find_skills(cv_text or "")) | set(canonicalise(skills))
    n = len(rows) or 1
    demand = Counter(s for r in rows for s in r.skills)
    missing = [{"skill": s, "count": c, "share": round(c / n, 4)} for s, c in demand.most_common() if s not in have][
        :top_missing
    ]
    scored = []
    for r in rows:
        sk = set(r.skills)
        if not sk:
            continue
        overlap = len(sk & have)
        scored.append((match_score(r, have), overlap, r))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    matches = [
        {
            "id": r.id,
            "title": r.title,
            "company": r.company,
            "city": r.city,
            "url": r.url,
            "match": round(score, 2),
            "matched": sorted(set(r.skills) & have),
            "missing": sorted(set(r.skills) - have),
        }
        for score, _, r in scored[:top_matches]
    ]
    covered = sum(demand[s] for s in have) / max(1, sum(demand.values()))
    return {
        "cv_skills": sorted(have),
        "demand_coverage": round(covered, 3),
        "postings_considered": len(rows),
        "missing": missing,
        "matches": matches,
    }
