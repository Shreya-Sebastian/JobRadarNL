"""Alerts: one e-mail when crawling stalls, no repeats while it lasts, an all-clear when it recovers."""

from datetime import datetime, timedelta

import fakeredis

from radar import health

OK = (2700, 400)  # active sources, crawled in the last three hours


def test_stalled_crawling_alerts_once_then_gives_an_all_clear(monkeypatch):
    sent = []
    monkeypatch.setattr(health, "alert", lambda subject, text: sent.append(subject) or True)
    r = fakeredis.FakeRedis()
    now = datetime(2026, 10, 1, 12, 0)

    assert health.check_freshness(r, now, last=now - timedelta(minutes=40), volume=OK) is None
    assert sent == []
    assert health.check_freshness(r, now, last=now - timedelta(hours=4), volume=OK) == "stale"
    assert health.check_freshness(r, now + timedelta(minutes=15), last=now - timedelta(hours=4), volume=OK) == "stale"
    assert sent == ["crawling has stopped"]  # not repeated every quarter of an hour
    assert health.check_freshness(r, now + timedelta(hours=1), last=now + timedelta(minutes=50), volume=OK) == "recovered"
    assert sent == ["crawling has stopped", "crawling has recovered"]
    assert health.check_freshness(r, now + timedelta(hours=2), last=now + timedelta(hours=2), volume=OK) is None


def test_an_empty_database_is_not_an_outage(monkeypatch):
    monkeypatch.setattr(health, "alert", lambda *a: (_ for _ in ()).throw(AssertionError("no alert expected")))
    assert health.check_freshness(fakeredis.FakeRedis(), datetime(2026, 10, 1), last=None, volume=OK) is None


def test_quality_violations_are_e_mailed(monkeypatch):
    from radar.config import settings

    mails = []
    monkeypatch.setattr(settings, "alert_email", "owner@example.com")
    monkeypatch.setattr("radar.mailer.send", lambda to, subject, text, *a, **k: mails.append((to, subject, text)))
    assert health.report_quality([]) is False and mails == []
    assert health.report_quality(["tech_no_skills_share = 0.41 exceeds 0.35"]) is True
    to, subject, text = mails[0]
    assert to == "owner@example.com" and "quality check failed" in subject and "tech_no_skills_share" in text
    monkeypatch.setattr(settings, "alert_email", None)
    assert health.report_quality(["x"]) is False  # without an address, alerts are only logged


def test_a_trickle_of_crawls_is_still_a_stall(monkeypatch):
    # 30 Sept 2026: retried jobs stuck in the queue blocked 2,569 sources while three still got crawled, so the
    # last successful crawl looked recent
    sent = []
    monkeypatch.setattr(health, "alert", lambda subject, text: sent.append(text) or True)
    now = datetime(2026, 9, 30, 14, 30)
    assert health.check_freshness(fakeredis.FakeRedis(), now, last=now - timedelta(minutes=20), volume=(2700, 3)) == "stale"
    assert "Only 3 of 2700" in sent[0]
    assert health.check_freshness(fakeredis.FakeRedis(), now, last=now - timedelta(minutes=20), volume=(40, 1)) is None


def test_a_retry_that_never_ran_does_not_block_its_source(monkeypatch):
    from datetime import UTC

    from rq.job import Job

    from radar import queue as q

    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(q, "get_redis", lambda: fake)
    monkeypatch.setattr("radar.config.settings.redis_url", "redis://fake")
    job = Job.create("radar.tasks.crawl_source", args=(7,), id="crawl-7", connection=fake)
    job.set_status("scheduled")
    job.ended_at = datetime.now(UTC) - timedelta(hours=20)
    job.save()
    assert q.enqueue_crawl(7) is not None  # the stale retry is replaced by a fresh job
    assert q.enqueue_crawl(7) is None  # and that one is not queued twice
