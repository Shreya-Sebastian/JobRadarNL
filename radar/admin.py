"""Admin-only "crawl now", for the site owner, never for visitors.

Disabled unless RADAR_ADMIN_TOKEN is set; requests must send `Authorization: Bearer <token>`. With Redis (the
production setup) a trigger only enqueues jobs for the existing workers, which keep their per-host rate limits.
Without Redis (a laptop) one crawl runs in a background thread at a time. A cool-down stops accidental repeat
clicks from hammering employers' sites; `force` overrides it.
"""

from __future__ import annotations

import hmac
import logging
import threading
import time
from datetime import datetime

from sqlalchemy import select

from radar.config import settings

log = logging.getLogger(__name__)

COOLDOWN_SECONDS = 600
_lock = threading.Lock()
_status: dict = {"running": False, "started_at": None, "finished_at": None, "scope": None, "sources": 0,
                 "queued": 0, "new": None, "error": None, "mode": None}
_last_start = 0.0


def enabled() -> bool:
    return bool(settings.admin_token)


def authorised(header: str | None) -> bool:
    if not enabled() or not header or not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[7:].strip().encode(), str(settings.admin_token).encode())


def status() -> dict:
    with _lock:
        out = dict(_status)
    left = COOLDOWN_SECONDS - (time.monotonic() - _last_start) if _last_start else 0
    out["cooldown_seconds_left"] = max(0, int(left))
    return out


def _source_ids(scope: str, company: str | None) -> list[int]:
    from radar.db import session_scope
    from radar.models import Source
    from radar.tasks import due_sources

    with session_scope() as s:
        if scope == "due":
            return list(due_sources(s))
        q = select(Source.id).where(Source.active.is_(True))
        if scope == "company":
            q = q.where(Source.company.ilike(f"%{company}%"))
        return [i for (i,) in s.execute(q)]


def _run_local(ids: list[int]) -> None:
    from radar.crawler import crawl
    from radar.tasks import finalize

    try:
        run = crawl(source_ids=ids)
        finalize()
        with _lock:
            _status.update(new=run.postings_new, finished_at=datetime.utcnow().isoformat(timespec="seconds"))
    except Exception as e:  # report, do not crash the API process
        log.exception("admin crawl failed")
        with _lock:
            _status.update(error=f"{type(e).__name__}: {e}"[:300], finished_at=datetime.utcnow().isoformat())
    finally:
        with _lock:
            _status["running"] = False


def trigger(scope: str, company: str | None = None, force: bool = False) -> tuple[int, dict]:
    """(http status, body). scope: due | all | company."""
    global _last_start
    if scope not in ("due", "all", "company") or (scope == "company" and not (company or "").strip()):
        return 400, {"error": "scope must be due, all, or company with a company name"}
    with _lock:
        if _status["running"]:
            return 409, {"error": "a crawl is already running", **_status}
        if not force and _last_start and time.monotonic() - _last_start < COOLDOWN_SECONDS:
            return 429, {"error": "cooling down; wait or send force=true",
                         "seconds_left": int(COOLDOWN_SECONDS - (time.monotonic() - _last_start))}
    ids = _source_ids(scope, (company or "").strip())
    if not ids:
        # never fall through to "crawl everything": crawl() treats an empty list as all sources
        return 404, {"error": "no active sources match", "scope": scope, "company": company}
    started = datetime.utcnow().isoformat(timespec="seconds")
    if settings.redis_url:
        from radar.queue import enqueue_crawl

        queued = sum(1 for i in ids if enqueue_crawl(i) is not None)
        with _lock:
            _last_start = time.monotonic()
            _status.update(running=False, started_at=started, finished_at=None, scope=scope, sources=len(ids),
                           queued=queued, new=None, error=None, mode="queue")
        return 202, status()
    with _lock:
        _last_start = time.monotonic()
        _status.update(running=True, started_at=started, finished_at=None, scope=scope, sources=len(ids),
                       queued=0, new=None, error=None, mode="local")
    threading.Thread(target=_run_local, args=(ids,), daemon=True, name="admin-crawl").start()
    return 202, status()
