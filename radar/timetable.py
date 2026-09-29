"""The periodic jobs, run from inside the queue worker instead of as Kubernetes CronJobs.

A CronJob starts a fresh Python process (and pod) for every run; on a small node that process arrives on top of
the API and a crawl and can push the machine into swap. Here a thread in the worker only *enqueues* each job on
the maintenance queue when its time slot comes up. The worker takes maintenance jobs before crawl jobs and runs
one job at a time in a forked child that frees its memory when it ends, so periodic work never overlaps a crawl.

Each slot is claimed in Redis with SET NX, so several worker replicas never enqueue the same run twice.
All times are UTC.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Entry:
    name: str  # task function in radar.tasks
    every_minutes: int | None = None  # interval job: runs when (minute of day - offset) % every == 0
    offset_minutes: int = 0
    daily_at: tuple[int, int] | None = None  # (hour, minute) for a nightly job
    timeout_seconds: int = 1800


# Same timings as the CronJobs in the Helm chart
TIMETABLE = [
    Entry("schedule", every_minutes=15),
    Entry("finalize", every_minutes=30, offset_minutes=5),
    Entry("linkcheck", daily_at=(3, 15), timeout_seconds=3600),
    Entry("qualitycheck", daily_at=(3, 45)),
]


def slot(entry: Entry, now: datetime) -> str | None:
    """The id of the run due at this minute, or None when nothing is due."""
    minute_of_day = now.hour * 60 + now.minute
    if entry.every_minutes:
        if (minute_of_day - entry.offset_minutes) % entry.every_minutes == 0:
            return f"{entry.name}:{now:%Y-%m-%dT%H:%M}"
        return None
    if entry.daily_at and (now.hour, now.minute) == entry.daily_at:
        return f"{entry.name}:{now:%Y-%m-%d}"
    return None


def tick(redis, now: datetime | None = None) -> list[str]:
    """Enqueue every job whose slot is due now and not yet claimed. Returns the names enqueued."""
    from radar.queue import MAINT_QUEUE, get_queue

    now = now or datetime.utcnow()
    done = []
    for entry in TIMETABLE:
        sid = slot(entry, now)
        if sid is None or not redis.set(f"radar:timetable:{sid}", 1, nx=True, ex=2 * 86400):
            continue
        get_queue(MAINT_QUEUE).enqueue(f"radar.tasks.{entry.name}", job_id=f"maint-{sid}".replace(":", "-"),
                                       job_timeout=entry.timeout_seconds, result_ttl=86400, failure_ttl=7 * 86400)
        done.append(entry.name)
    return done


def start(redis, interval_seconds: int = 20) -> threading.Thread:
    """Check the timetable a few times a minute in a daemon thread."""

    def loop():
        stop = threading.Event()
        while not stop.wait(interval_seconds):
            try:
                names = tick(redis)
                if names:
                    log.info("timetable enqueued %s", ", ".join(names))
            except Exception:  # Redis briefly away: try again on the next tick
                log.exception("timetable tick failed")

    t = threading.Thread(target=loop, name="timetable", daemon=True)
    t.start()
    return t
