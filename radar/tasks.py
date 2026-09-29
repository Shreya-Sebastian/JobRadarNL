"""Queue jobs: crawl one source; finalize a crawl cycle. Both are plain functions so they run the same way
from RQ workers, from the thread-pool `radar crawl`, and from tests."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import func, select

from radar.adapters import get_adapter
from radar.adapters.base import AdapterError, RawPosting, SourceNotFound
from radar.config import settings
from radar.crawler import ingest, known_urls_for, mark_duplicates
from radar.db import init_db, session_scope
from radar.metrics import FETCH_SECONDS, FETCHES, LIVE_POSTINGS, POSTINGS_CLOSED, POSTINGS_NEW, POSTINGS_SEEN, SOURCES
from radar.models import CrawlRun, Posting, Source

log = logging.getLogger(__name__)


def crawl_source(source_id: int, extractor_name: str | None = None) -> dict:
    init_db()
    extractor_name = extractor_name or settings.extractor
    with session_scope() as s:
        src = s.get(Source, source_id)
        if src is None or not src.active:
            return {"source_id": source_id, "skipped": True}
        ats, slug = src.ats, src.slug
        known = known_urls_for(s, src)
    t0 = time.monotonic()
    error = None
    raws = None
    try:
        adapter = get_adapter(ats)
        if known and hasattr(adapter, "known_urls"):
            adapter.known_urls = known
        raws = adapter.fetch(slug)
        for ext in getattr(adapter, "still_listed", None) or ():
            raws.append(RawPosting(external_id=ext, title="", url="", raw={"still_listed": True}))
    except SourceNotFound:
        error = "not_found"
    except AdapterError as e:
        error = f"error: {e}"[:500]
    except Exception as e:
        error = f"exception: {type(e).__name__}: {e}"[:500]
    FETCH_SECONDS.labels(ats).observe(time.monotonic() - t0)

    with session_scope() as s:
        src = s.get(Source, source_id)
        src.last_run_at = datetime.utcnow()
        if error is not None:
            src.last_status = error.split(":")[0]
            src.last_error = error
            src.consecutive_failures += 1
            if error == "not_found" or src.consecutive_failures >= 5:
                src.active = False
            FETCHES.labels(ats, src.last_status).inc()
            log.warning("%s/%s failed: %s", ats, slug, error)
            return {"source_id": source_id, "error": error}
        counters = ingest(s, src, raws, extractor_name)
        src.last_status = "partial" if counters.get("partial") else "ok"
        if not counters.get("partial"):
            src.last_error = None
            src.last_nl_count = counters["seen"]  # a partial response must not lower the baseline
        src.consecutive_failures = 0
        src.last_count = len(raws)
        if src.first_success_at is None:
            src.first_success_at = datetime.utcnow()
    FETCHES.labels(ats, "ok").inc()
    POSTINGS_NEW.labels(ats).inc(counters["new"])
    POSTINGS_CLOSED.labels(ats).inc(counters["closed"])
    POSTINGS_SEEN.labels(ats).inc(counters["seen"])
    log.info("%s/%s: total=%d in_scope=%d new=%d closed=%d", ats, slug, len(raws), counters["seen"],
             counters["new"], counters["closed"])
    return {"source_id": source_id, **counters}


def cadence_minutes(src: Source) -> int:
    if src.last_nl_count is None:
        return 0
    if src.ats == "jsonld":
        # page-by-page crawls of a sitemap are expensive: never more often than every 6 hours
        return max(settings.cadence_normal_minutes, 360)
    if src.last_nl_count >= 20:
        return settings.cadence_high_minutes
    if src.last_nl_count >= 1:
        return settings.cadence_normal_minutes
    return settings.cadence_low_minutes


def due_sources(session, now: datetime | None = None) -> list[int]:
    now = now or datetime.utcnow()
    ids = []
    for src in session.scalars(select(Source).where(Source.active.is_(True))):
        if src.last_run_at is None or now - src.last_run_at >= timedelta(minutes=cadence_minutes(src)):
            ids.append(src.id)
    return ids


def schedule() -> dict:
    """Enqueue every due source. Runs as a CronJob."""
    from radar.queue import enqueue_crawl

    init_db()
    with session_scope() as s:
        ids = due_sources(s)
        run = CrawlRun(sources_total=len(ids), notes="queued")
        s.add(run)
    queued = sum(1 for i in ids if enqueue_crawl(i) is not None)
    log.info("scheduled %d of %d due sources", queued, len(ids))
    return {"due": len(ids), "queued": queued}


def finalize() -> dict:
    """Dedup, refresh gauges and bump the data version so API processes reload. Runs as a CronJob."""
    init_db()
    with session_scope() as s:
        dups = mark_duplicates(s)
        live = s.scalar(select(func.count()).select_from(Posting).where(Posting.closed_at.is_(None),
                                                                        Posting.duplicate_of.is_(None)))
        tech = s.scalar(select(func.count()).select_from(Posting).where(
            Posting.closed_at.is_(None), Posting.duplicate_of.is_(None), Posting.is_tech.is_(True)))
        LIVE_POSTINGS.labels("all").set(live or 0)
        LIVE_POSTINGS.labels("tech").set(tech or 0)
        for status, n in s.execute(select(Source.last_status, func.count()).group_by(Source.last_status)):
            SOURCES.labels(status or "pending").set(n)
        run = s.scalar(select(CrawlRun).where(CrawlRun.finished_at.is_(None)).order_by(CrawlRun.id.desc()))
        if run is not None:
            run.finished_at = datetime.utcnow()
            run.sources_ok = s.scalar(select(func.count()).select_from(Source).where(
                Source.last_run_at >= run.started_at, Source.last_status == "ok")) or 0
            run.sources_failed = s.scalar(select(func.count()).select_from(Source).where(
                Source.last_run_at >= run.started_at, Source.last_status != "ok")) or 0
            run.postings_new = s.scalar(select(func.count()).select_from(Posting).where(
                Posting.first_seen >= run.started_at)) or 0
            run.postings_closed = s.scalar(select(func.count()).select_from(Posting).where(
                Posting.closed_at >= run.started_at)) or 0
            run.notes = f"duplicates marked: {dups}"
    from radar.cache import bump_data_version

    bump_data_version()
    log.info("finalize: live=%s tech=%s duplicates=%s", live, tech, dups)
    return {"live": live, "tech": tech, "duplicates_marked": dups}
