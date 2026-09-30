"""Weekly discovery: find employers the radar does not read yet.

The regular crawl only re-reads known sources. Once a week this job looks for new ones, in small steps so it
never holds up the crawl for long on a small server:

1. boards: ask the Internet Archive's URL index for every board on a few platforms (three a week, in turn), probe
   the ones never checked before, and register those with postings in the Netherlands;
2. rechecks: probe again a few boards that had no Dutch postings months ago, since employers start hiring here;
3. sponsors: download the IND register of recognised sponsors and look up the employers that are new on it.

Every board or employer checked is stored in `discovery_candidates`, so the next run skips it.
Each step has a budget, and the whole run stops at a time limit.
"""

from __future__ import annotations

import html
import logging
import re
import time
from datetime import datetime, timedelta

import httpx
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from radar.config import settings
from radar.models import DiscoveryCandidate, Source

log = logging.getLogger(__name__)

IND_REGISTER_URL = "https://ind.nl/en/public-register-recognised-sponsors/public-register-work"
PLATFORMS_PER_WEEK = 3
RECHECK_AFTER_DAYS = 90
RETRY_FAILED_AFTER_DAYS = 7
_FAILED = ("error", "exception")
MAX_KEY = 300  # the archive index also holds junk "slugs" (long tokens); no real board name is this long
_ROW = re.compile(r'<th scope="row">(.*?)</th>\s*<td>\s*(\d{8})\s*</td>', re.S)


def parse_register(page: str) -> list[tuple[str, str]]:
    """(name, KvK number) for every row of the IND register page."""
    return [(html.unescape(re.sub(r"<[^>]+>", "", name)).strip(), kvk) for name, kvk in _ROW.findall(page)]


def fetch_register() -> list[tuple[str, str]]:
    with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": settings.user_agent}) as c:
        return parse_register(c.get(IND_REGISTER_URL).raise_for_status().text)


def platforms_this_week(today: datetime) -> list[str]:
    from radar.enumerate import PATTERNS

    names = sorted(PATTERNS)
    week = today.isocalendar()[1]
    start = (week * PLATFORMS_PER_WEEK) % len(names)
    return [names[(start + i) % len(names)] for i in range(PLATFORMS_PER_WEEK)]


def _sponsor_status(entry: dict) -> str:
    if entry.get("ats") or entry.get("jsonld") or entry.get("sitemap"):
        return "board"
    return "no_board" if entry.get("domain") else "no_domain"


def _record(session: Session, kind: str, key: str, status: str, nl: int = 0) -> None:
    row = session.get(DiscoveryCandidate, (kind, key))
    if row is None:
        session.add(DiscoveryCandidate(kind=kind, key=key, status=status, nl=nl, checked_at=datetime.utcnow()))
    else:
        row.status, row.nl, row.checked_at = status, nl, datetime.utcnow()


def _register_board(session: Session, ats: str, slug: str) -> bool:
    from radar.registry import _pretty, upsert_source

    _, new = upsert_source(session, _pretty(slug), ats, slug, discovered_by="weekly")
    return bool(new)


def run(session: Session, *, boards: int = 300, rechecks: int = 100, sponsors: int = 200,
        time_budget_s: int = 3600, today: datetime | None = None) -> dict:
    from radar.enumerate import _probe_one, enumerate_slugs

    today = today or datetime.utcnow()
    deadline = time.monotonic() + time_budget_s
    stats = {"platforms": [], "boards_probed": 0, "rechecked": 0, "sponsors_checked": 0, "sources_added": 0}
    seen = {tuple(r) for r in session.execute(select(DiscoveryCandidate.kind, DiscoveryCandidate.key))}
    have = {(a, s.lower()) for a, s in session.execute(select(Source.ats, Source.slug))}

    def probe(ats: str, slug: str) -> None:
        res = _probe_one(ats, slug)
        nl = int(res.get("nl") or 0)
        _record(session, ats, slug, res.get("status", "error"), nl)
        if res.get("status") == "ok" and nl > 0 and _register_board(session, ats, slug):
            stats["sources_added"] += 1
        session.commit()

    # 1. new boards on this week's platforms
    todo: list[tuple[str, str]] = []
    for ats in platforms_this_week(today):
        stats["platforms"].append(ats)
        try:
            slugs = enumerate_slugs(ats, timeout=300)
        except Exception as e:  # the archive is slow or down: try the next platform
            log.warning("weekly discovery: index lookup for %s failed: %s", ats, e)
            continue
        todo += [(ats, s) for s in slugs
                 if len(s) <= MAX_KEY and (ats, s) not in seen and (ats, s.lower()) not in have]
    for ats, slug in todo[:boards]:
        if time.monotonic() > deadline:
            break
        probe(ats, slug)
        stats["boards_probed"] += 1

    # 2. boards that had no Dutch postings a while ago, and checks that failed (rate limits, timeouts) last week
    c = DiscoveryCandidate
    stale = session.execute(
        select(c.kind, c.key)
        .where(c.kind != "sponsor", or_(
            and_(c.status == "ok", c.nl == 0, c.checked_at < today - timedelta(days=RECHECK_AFTER_DAYS)),
            and_(c.status.in_(_FAILED), c.checked_at < today - timedelta(days=RETRY_FAILED_AFTER_DAYS))))
        .order_by(c.checked_at).limit(rechecks)).all()
    for ats, slug in stale:
        if time.monotonic() > deadline:
            break
        probe(ats, slug)
        stats["rechecked"] += 1

    # 3. employers that are new on the IND register
    from radar import sponsors as sp

    try:
        register = fetch_register()
    except Exception as e:
        log.warning("weekly discovery: IND register download failed: %s", e)
        register = []
    covered = sp.covered_keys(session)
    new = [(n, k) for n, k in register
           if ("sponsor", k) not in seen and sp.name_key(n) and sp.name_key(n) not in covered]
    client = sp._client()
    try:
        for name, kvk in new[:sponsors]:
            if time.monotonic() > deadline:
                break
            try:
                entry = sp.process_one(name, client)
            except Exception as e:  # one broken site must not stop the run
                entry = {"name": name, "domain": None, "error": type(e).__name__}
            status = _sponsor_status(entry)
            _record(session, "sponsor", kvk, status)
            if status == "board":
                stats["sources_added"] += sp.register(session, entry)
            session.commit()
            stats["sponsors_checked"] += 1
    finally:
        client.close()
    stats["register_size"] = len(register)
    stats["sponsors_new_on_register"] = len(new)
    log.info("weekly discovery: %s", stats)
    return stats


def import_state(session: Session, probed: dict[str, dict[str, dict]], sponsor_state: dict[str, dict],
                 checked_at: datetime) -> int:
    """Load results of earlier discovery runs (the JSON state files) so the weekly job does not repeat them."""
    seen = {tuple(r) for r in session.execute(select(DiscoveryCandidate.kind, DiscoveryCandidate.key))}
    added = 0
    for ats, state in probed.items():
        for slug, res in state.items():
            # failed checks (mostly rate limits) were never really checked: leave them for the weekly job
            if (ats, slug) not in seen and res.get("status") not in _FAILED and len(slug) <= MAX_KEY:
                session.add(DiscoveryCandidate(kind=ats, key=slug, status=res.get("status", "error"),
                                               nl=int(res.get("nl") or 0), checked_at=checked_at))
                added += 1
    for kvk, entry in sponsor_state.items():
        if ("sponsor", kvk) not in seen:
            session.add(DiscoveryCandidate(kind="sponsor", key=kvk, checked_at=checked_at, nl=0,
                                           status=_sponsor_status(entry)))
            added += 1
    return added
