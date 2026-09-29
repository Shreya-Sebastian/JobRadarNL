"""Job queue on Redis (RQ). One job per source, so workers scale horizontally and a slow board never
blocks the others. `radar schedule` enqueues, `radar worker` consumes, `radar finalize` post-processes."""

from __future__ import annotations

from functools import lru_cache

from radar.config import settings

CRAWL_QUEUE = "crawl"
MAINT_QUEUE = "maintenance"


@lru_cache(maxsize=1)
def get_redis():
    import redis

    if not settings.redis_url:
        raise RuntimeError("RADAR_REDIS_URL is not set; the queue needs Redis")
    return redis.Redis.from_url(settings.redis_url)


def get_queue(name: str = CRAWL_QUEUE):
    from rq import Queue

    return Queue(name, connection=get_redis(), default_timeout=1800)


def enqueue_crawl(source_id: int):
    """Enqueue a crawl for one source unless an identical job is already queued or running."""
    from rq.job import Job

    q = get_queue()
    job_id = f"crawl-{source_id}"
    try:
        existing = Job.fetch(job_id, connection=q.connection)
        if existing.get_status() in ("queued", "started", "deferred", "scheduled"):
            return None
    except Exception:
        pass
    return q.enqueue("radar.tasks.crawl_source", source_id, job_id=job_id, result_ttl=3600, failure_ttl=86400,
                     retry=_retry())


def _retry():
    from rq import Retry

    return Retry(max=2, interval=[60, 300])


def queue_depths() -> dict[str, int]:
    out = {}
    for name in (CRAWL_QUEUE, MAINT_QUEUE):
        try:
            out[name] = get_queue(name).count
        except Exception:
            out[name] = -1
    return out
