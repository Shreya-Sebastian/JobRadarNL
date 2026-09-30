"""Integrity checks on the stored postings.

link_check:   re-fetch a sample of original posting URLs and close the ones that are gone.
quality_report: shares of postings with empty text, unknown city, unknown seniority, missing dates, bad URLs,
              stale postings, partial sources; with thresholds so a nightly run can fail loudly.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from radar.config import settings
from radar.models import Posting, Source
from radar.ratelimit import throttle_request

log = logging.getLogger(__name__)

_GONE_TEXT = re.compile(
    r"no longer (?:available|accepting|open)|this (?:job|position|vacancy|posting|role) (?:has been|is) (?:filled|"
    r"closed|removed|expired)|position has been filled|job not found|vacancy not found|"
    r"applications? (?:are|is) (?:now )?closed|(?:we are|we're) no longer (?:recruiting|hiring) for|"
    r"this (?:job|vacancy|posting) (?:has )?expired|(?:the )?application (?:deadline|period) has (?:passed|ended)|"
    r"vacature is (?:gesloten|vervuld|verlopen|ingevuld|niet meer (?:beschikbaar|actief|open))|"
    r"deze vacature (?:bestaat niet|is niet meer|is inmiddels)|niet langer beschikbaar|"
    r"sollicitatietermijn is (?:verlopen|gesloten|voorbij)|de sluitingsdatum is verstreken|"
    r"reageren (?:op deze vacature )?is niet meer mogelijk|deze functie is (?:inmiddels )?(?:vervuld|ingevuld)|"
    r"stelle ist (?:bereits )?besetzt|nicht mehr verf.gbar",
    re.I,
)
_GONE_TITLE = re.compile(r"not found|404|no longer|expired|gesloten|niet gevonden|bestaat niet", re.I)


def _visible_text(html: str) -> str:
    """Page text without scripts and styles, so a '404' inside JavaScript cannot count as evidence."""
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", html)


def _check_url(url: str, title: str | None = None) -> str:
    """ok | gone | redirected | error"""
    try:
        with httpx.Client(
            timeout=20,
            follow_redirects=True,
            event_hooks={"request": [throttle_request]},
            headers={"User-Agent": settings.user_agent},
        ) as c:
            r = c.get(url)
    except Exception:
        return "error"
    if r.status_code in (404, 410):
        return "gone"
    if r.status_code >= 400:
        return "error"
    final = str(r.url)
    orig, fin = urlparse(url), urlparse(final)
    # redirected to a listing or homepage: the job page itself is gone
    if fin.netloc != orig.netloc or (
        fin.path.rstrip("/") in ("", "/jobs", "/careers", "/vacatures", "/en", "/nl")
        and orig.path.rstrip("/") not in ("", "/jobs", "/careers")
    ):
        return "redirected"
    if r.headers.get("content-type", "").startswith("text/html"):
        html = r.text or ""
        page_title = re.search(r"<title[^>]*>(.*?)</title>", html[:5000], re.I | re.S)
        visible = _visible_text(html[:60000])
        # the posting's own title on the page is the strongest sign that it is still live
        if title and len(title) >= 8 and title.lower()[:40] in visible.lower():
            return "ok"
        if page_title and _GONE_TITLE.search(page_title.group(1)):
            return "gone"
        if _GONE_TEXT.search(visible[:20000]):
            return "gone"
    return "ok"


def link_check(session: Session, sample: int | None = None, older_than_days: int = 21, workers: int = 8,
               cycle_days: int = 14) -> dict:
    """Open posting pages, oldest first (most likely to be stale), and close the ones that are gone.

    With sample=None the batch size follows the size of the radar, so that every live posting's page is opened
    about once per `cycle_days` when this runs nightly."""
    if sample is None:
        live = session.scalar(select(func.count()).select_from(Posting)
                              .where(Posting.closed_at.is_(None), Posting.duplicate_of.is_(None))) or 0
        sample = max(200, live // cycle_days)
    cutoff = datetime.utcnow() - timedelta(days=older_than_days)
    recheck = datetime.utcnow() - timedelta(days=7)
    age = func.coalesce(Posting.posted_at, Posting.first_seen)  # the board's posting date when it gives one
    q = (
        select(Posting)
        .where(Posting.closed_at.is_(None), Posting.duplicate_of.is_(None), age <= cutoff)
        .where((Posting.link_checked_at.is_(None)) | (Posting.link_checked_at <= recheck))
        .order_by(age)
        .limit(sample)
    )
    postings = list(session.scalars(q))
    results = {"checked": len(postings), "ok": 0, "gone": 0, "redirected": 0, "error": 0, "closed": 0,
               "sources_flagged": 0}
    verdicts: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_check_url, p.url, p.title): p for p in postings}
        for fut in as_completed(futures):
            p = futures[fut]
            status = fut.result()
            p.link_checked_at = datetime.utcnow()
            p.link_status = status
            results[status] += 1
            verdicts[p.id] = status
    # Per-source guard: when most of a board's checked links look dead while the board still lists the
    # postings, the URLs are wrong (or the site blocks us), not the vacancies. Flag the source, close nothing.
    by_source: dict[int, list[Posting]] = {}
    for p in postings:
        by_source.setdefault(p.source_id, []).append(p)
    for source_id, group in by_source.items():
        dead = [p for p in group if verdicts[p.id] in ("gone", "redirected")]
        if len(group) >= 3 and len(dead) / len(group) >= 0.5:
            src = session.get(Source, source_id)
            src.last_error = f"link check: {len(dead)} of {len(group)} checked URLs look dead; verify URL format"
            results["sources_flagged"] += 1
            continue
        for p in dead:
            p.closed_at = datetime.utcnow()
            results["closed"] += 1
    session.flush()
    return results


def verify_sources(session: Session, since_days: int = 3, min_share: float = 0.3, flag: bool = True,
                   discovered_by: tuple[str, ...] = ("discovery-guess",)) -> list[dict]:
    """Flag boards found by guessing a slug whose postings rarely name the employer they are filed under: the mark
    of a namesake (another company with the same short name) or a vendor demo tenant.

    Only guessed boards are checked. Plenty of genuine employers never name themselves in their own postings
    ("we connect conversations..."), so the mention test is weak evidence and is used only where the board's
    link to the employer is itself unproven. Boards the employer's website links to, sitemap sources and the
    sponsor-register pipeline (which never guesses) are trusted. Multi-employer boards are skipped. Nothing is
    deactivated; flagged sources are listed for a human to judge."""
    from radar.sponsors import clean_name, tokens

    since = datetime.utcnow() - timedelta(days=since_days)
    out = []
    for src in session.scalars(select(Source).where(Source.active.is_(True), Source.created_at >= since,
                                                    Source.discovered_by.in_(discovered_by))):
        if (src.kind or "employer") == "board":
            continue
        posts = session.execute(select(Posting.title, Posting.description)
                                .where(Posting.source_id == src.id, Posting.closed_at.is_(None))).all()
        if len(posts) < 3:
            continue
        toks = tokens(src.company) or [w for w in clean_name(src.company).lower().split() if len(w) >= 3]
        if not toks:
            continue
        rx = re.compile("|".join(re.escape(t) for t in toks), re.I)
        share = sum(1 for t, d in posts if rx.search(t or "") or rx.search((d or "")[:6000])) / len(posts)
        if share < min_share:
            out.append({"id": src.id, "company": src.company, "ats": src.ats, "slug": src.slug, "postings": len(posts),
                        "mention_share": round(share, 2)})
            if flag and not (src.last_error or "").startswith("unverified"):
                src.last_error = f"unverified: only {share:.0%} of postings name {src.company}; check the board"
    session.flush()
    return out


def quality_report(session: Session) -> dict:
    """Shares and counts that describe the health of the live data. One streaming pass over the live postings,
    reading only the length of each description, so it fits in memory on a small server."""
    stale = datetime.utcnow() - timedelta(days=90)
    week_ago = datetime.utcnow() - timedelta(days=7)
    month_ago = datetime.utcnow() - timedelta(days=30)
    half_year = datetime.utcnow() - timedelta(days=180)
    c = dict.fromkeys(("live", "tech", "empty", "no_city", "no_date", "bad_url", "stale", "unknown_seniority",
                       "no_skills", "confirmed", "checked", "old", "agency", "link_gone", "link_known"), 0)
    q = (select(Posting.url, Posting.city, func.length(Posting.description), Posting.posted_at, Posting.first_seen,
                Posting.is_tech, Posting.extraction, Posting.link_status, Posting.link_checked_at, Posting.last_seen,
                Source.kind)
         .join(Source, Source.id == Posting.source_id)
         .where(Posting.closed_at.is_(None), Posting.duplicate_of.is_(None))
         .execution_options(stream_results=True, yield_per=500))
    for row in session.execute(q):
        url, city, desc_len, posted, first_seen, is_tech, ex, link_status, checked_at, last_seen, kind = row
        c["live"] += 1
        c["empty"] += (desc_len or 0) < 200
        c["no_city"] += not city
        c["no_date"] += posted is None
        c["bad_url"] += not (url or "").startswith("http")
        c["stale"] += (posted or first_seen) < stale
        c["old"] += (posted or first_seen) < half_year
        c["confirmed"] += bool(last_seen and last_seen >= week_ago)
        c["checked"] += bool(checked_at and checked_at >= month_ago)
        c["agency"] += kind == "agency"
        if link_status:
            c["link_known"] += 1
            c["link_gone"] += link_status in ("gone", "redirected")
        if is_tech:
            ex = ex or {}
            c["tech"] += 1
            c["unknown_seniority"] += ex.get("seniority") in (None, "unknown")
            c["no_skills"] += not ex.get("skills_required") and not ex.get("skills_nice")
    n, nt = max(1, c["live"]), max(1, c["tech"])

    def share(count: int, base: int) -> float:
        return round(count / max(1, base), 4)

    report = {
        "live_postings": c["live"],
        "live_tech": c["tech"],
        "empty_description_share": share(c["empty"], n),
        "unknown_city_share": share(c["no_city"], n),
        "missing_posted_date_share": share(c["no_date"], n),
        "invalid_url_count": c["bad_url"],
        "stale_over_90_days_share": share(c["stale"], n),
        "tech_unknown_seniority_share": share(c["unknown_seniority"], nt),
        "tech_no_skills_share": share(c["no_skills"], nt),
        "confirmed_7d_share": share(c["confirmed"], n),
        "link_checked_30d_share": share(c["checked"], n),
        "open_over_180_days_share": share(c["old"], n),
        "agency_share": share(c["agency"], n),
        "sources_unverified": session.scalar(
            select(func.count()).select_from(Source)
            .where(Source.active.is_(True), Source.last_error.like("unverified%"))
        )
        or 0,
        "link_checked_gone_share": share(c["link_gone"], max(1, c["link_known"])),
        "sources_partial": session.scalar(
            select(func.count()).select_from(Source).where(Source.last_status == "partial")
        )
        or 0,
        "sources_failed": session.scalar(
            select(func.count())
            .select_from(Source)
            .where(Source.active.is_(True), Source.last_status.in_(["error", "exception"]))
        )
        or 0,
        "sources_stale_over_24h": session.scalar(
            select(func.count())
            .select_from(Source)
            .where(Source.active.is_(True), Source.last_run_at < datetime.utcnow() - timedelta(hours=24))
        )
        or 0,
    }
    return report


THRESHOLDS = {
    "empty_description_share": 0.10,
    "unknown_city_share": 0.35,
    "missing_posted_date_share": 0.30,
    "invalid_url_count": 0,
    # about 40% of live postings are over 90 days old: universities, government and large employers keep roles
    # open for months (the site marks them "long open"); a jump well above that means something broke
    "stale_over_90_days_share": 0.50,
    "tech_unknown_seniority_share": 0.50,
    "tech_no_skills_share": 0.35,
    "sources_partial": 25,
    "sources_failed": 60,
}


def violations(report: dict) -> list[str]:
    out = []
    for key, limit in THRESHOLDS.items():
        if report.get(key, 0) > limit:
            out.append(f"{key} = {report[key]} exceeds {limit}")
    return out
