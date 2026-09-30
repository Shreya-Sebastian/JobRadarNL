"""Alert e-mails: crawling has stalled, or the nightly quality check failed.

The freshness check runs in the worker's timetable thread, not as a queued job: when queued jobs themselves are
failing (as in the outage where every forked job lost its database connection), a job would never report it.
An alert is sent once, repeated at most every 12 hours while the problem lasts, and followed by an all-clear.
Alerts go to RADAR_ALERT_EMAIL; without it, they are only logged.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select

from radar.config import settings

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(hours=3)
# at least this share of the active sources should have been crawled in the last STALE_AFTER
MIN_CRAWLED_SHARE = 0.01
REPEAT_AFTER = timedelta(hours=12)
_STALE_KEY = "radar:alert:stale"
_STALE_SENT_KEY = "radar:alert:stale:sent"
_UNSET = object()


def alert(subject: str, text: str) -> bool:
    """E-mail the site owner. Returns whether an e-mail was sent."""
    log.error("alert: %s | %s", subject, text.replace("\n", " "))
    if not settings.alert_email:
        return False
    from radar import mailer

    try:
        mailer.send(settings.alert_email, f"[{settings.site_name}] {subject}", text)
        return True
    except Exception:
        log.exception("alert e-mail could not be sent")
        return False


def last_successful_crawl() -> datetime | None:
    from radar.db import new_session
    from radar.models import Source

    s = new_session()
    try:
        return s.scalar(select(func.max(Source.last_run_at)).where(Source.last_status == "ok"))
    finally:
        s.close()


def crawl_volume(now: datetime) -> tuple[int, int]:
    """(active sources, active sources crawled in the last STALE_AFTER)."""
    from radar.db import new_session
    from radar.models import Source

    s = new_session()
    try:
        active = s.scalar(select(func.count()).select_from(Source).where(Source.active.is_(True))) or 0
        recent = s.scalar(select(func.count()).select_from(Source).where(
            Source.active.is_(True), Source.last_run_at >= now - STALE_AFTER)) or 0
        return active, recent
    finally:
        s.close()


def check_freshness(redis, now: datetime | None = None, last=_UNSET, volume=_UNSET) -> str | None:
    """Alert when no source has been crawled successfully for STALE_AFTER, or when almost none were crawled in that
    time (jobs stuck in the queue while a few still get through); send an all-clear once it recovers.
    Returns 'stale', 'recovered' or None."""
    now = now or datetime.utcnow()
    last = last_successful_crawl() if last is _UNSET else last
    if last is None:
        return None  # an empty database (a fresh install): nothing to compare with
    active, recent = crawl_volume(now) if volume is _UNSET else volume
    too_few = active >= 100 and recent < max(5, int(active * MIN_CRAWLED_SHARE))
    if now - last >= STALE_AFTER or too_few:
        redis.set(_STALE_KEY, last.isoformat())
        if redis.set(_STALE_SENT_KEY, now.isoformat(), nx=True, ex=int(REPEAT_AFTER.total_seconds())):
            hours = (now - last).total_seconds() / 3600
            window = int(STALE_AFTER.total_seconds() // 3600)
            alert("crawling has stopped",
                  f"Only {recent} of {active} active sources were crawled in the last {window} hours; the last "
                  f"successful crawl was {hours:.1f} hours ago ({last:%Y-%m-%d %H:%M} UTC).\n\n"
                  f"Listings on {settings.site_url} are not being refreshed. Check the worker logs and the queue:\n"
                  "kubectl -n radar logs deploy/radar-radar-worker --tail=100")
        return "stale"
    if redis.get(_STALE_KEY):
        redis.delete(_STALE_KEY, _STALE_SENT_KEY)
        alert("crawling has recovered", f"Sources are being crawled again (last success: {last:%Y-%m-%d %H:%M} UTC).")
        return "recovered"
    return None


def report_quality(violations: list[str]) -> bool:
    """E-mail the nightly quality check's threshold violations, if any."""
    if not violations:
        return False
    return alert("data-quality check failed", "The nightly quality check found:\n\n- " + "\n- ".join(violations))
