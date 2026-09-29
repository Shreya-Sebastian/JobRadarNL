from datetime import datetime

import fakeredis

from radar import queue as q
from radar import timetable


def test_slots_match_the_cronjob_times():
    by = {e.name: e for e in timetable.TIMETABLE}
    assert timetable.slot(by["schedule"], datetime(2026, 9, 29, 20, 15)) == "schedule:2026-09-29T20:15"
    assert timetable.slot(by["schedule"], datetime(2026, 9, 29, 20, 16)) is None
    assert timetable.slot(by["finalize"], datetime(2026, 9, 29, 20, 35)) is not None
    assert timetable.slot(by["finalize"], datetime(2026, 9, 29, 20, 30)) is None
    assert timetable.slot(by["linkcheck"], datetime(2026, 9, 29, 3, 15)) == "linkcheck:2026-09-29"
    assert timetable.slot(by["qualitycheck"], datetime(2026, 9, 29, 3, 15)) is None


def test_tick_enqueues_each_slot_once_across_workers(monkeypatch):
    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(q, "get_redis", lambda: fake)
    monkeypatch.setattr("radar.config.settings.redis_url", "redis://fake")
    at = datetime(2026, 9, 29, 3, 15)  # schedule (every 15 min) and linkcheck (03:15) are both due
    assert sorted(timetable.tick(fake, at)) == ["linkcheck", "schedule"]
    assert timetable.tick(fake, at) == []  # a second worker ticking in the same minute adds nothing
    maint = q.get_queue(q.MAINT_QUEUE)
    assert maint.count == 2 and q.get_queue(q.CRAWL_QUEUE).count == 0
    assert {j.func_name for j in maint.jobs} == {"radar.tasks.schedule", "radar.tasks.linkcheck"}
    assert timetable.tick(fake, datetime(2026, 9, 29, 3, 16)) == []
