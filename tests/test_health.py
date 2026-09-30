"""Alerts: one e-mail when crawling stalls, no repeats while it lasts, an all-clear when it recovers."""

from datetime import datetime, timedelta

import fakeredis

from radar import health


def test_stalled_crawling_alerts_once_then_gives_an_all_clear(monkeypatch):
    sent = []
    monkeypatch.setattr(health, "alert", lambda subject, text: sent.append(subject) or True)
    r = fakeredis.FakeRedis()
    now = datetime(2026, 10, 1, 12, 0)

    assert health.check_freshness(r, now, last=now - timedelta(minutes=40)) is None
    assert sent == []
    assert health.check_freshness(r, now, last=now - timedelta(hours=4)) == "stale"
    assert health.check_freshness(r, now + timedelta(minutes=15), last=now - timedelta(hours=4)) == "stale"
    assert sent == ["crawling has stopped"]  # not repeated every quarter of an hour
    assert health.check_freshness(r, now + timedelta(hours=1), last=now + timedelta(minutes=50)) == "recovered"
    assert sent == ["crawling has stopped", "crawling has recovered"]
    assert health.check_freshness(r, now + timedelta(hours=2), last=now + timedelta(hours=2)) is None


def test_an_empty_database_is_not_an_outage(monkeypatch):
    monkeypatch.setattr(health, "alert", lambda *a: (_ for _ in ()).throw(AssertionError("no alert expected")))
    assert health.check_freshness(fakeredis.FakeRedis(), datetime(2026, 10, 1), last=None) is None


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
