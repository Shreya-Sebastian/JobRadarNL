"""Feedback page: messages are stored and e-mailed; bots, empty messages and floods are turned away."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

H = {"X-Requested-With": "radar"}


def _client(monkeypatch):
    from radar import feedback
    from radar.api import app
    from radar.config import settings

    feedback._hits.clear()
    mails = []
    monkeypatch.setattr(settings, "alert_email", "owner@example.com")
    monkeypatch.setattr("radar.mailer.send", lambda to, subject, text, html=None, headers=None:
                        mails.append((to, subject, text, headers)))
    return TestClient(app), mails


def test_a_message_is_stored_and_forwarded(fresh_db, monkeypatch):
    from sqlalchemy import select

    from radar.db import session_scope
    from radar.models import Feedback

    client, mails = _client(monkeypatch)
    r = client.post("/api/feedback", headers=H, json={"kind": "listing", "message": "The ASML job is closed already",
                                                      "email": "Visitor@Example.com", "page": "/#jobs", "lang": "nl"})
    assert r.status_code == 200
    with session_scope() as s:
        row = s.scalar(select(Feedback))
        assert (row.kind, row.email, row.page, row.lang) == ("listing", "visitor@example.com", "/#jobs", "nl")
    to, subject, text, headers = mails[0]
    assert to == "owner@example.com" and "Wrong or missing listing" in subject and "ASML" in text
    assert headers == {"Reply-To": "visitor@example.com"}


def test_bots_short_messages_and_bad_addresses_are_turned_away(fresh_db, monkeypatch):
    from sqlalchemy import func, select

    from radar.db import session_scope
    from radar.models import Feedback

    client, mails = _client(monkeypatch)
    assert client.post("/api/feedback", headers=H, json={"message": "buy cheap pills", "website": "spam.example"}).json() == {"ok": True}
    assert client.post("/api/feedback", headers=H, json={"message": "hi"}).status_code == 422
    assert client.post("/api/feedback", headers=H, json={"message": "hello there", "email": "nope"}).status_code == 422
    assert client.post("/api/feedback", json={"message": "no header from another site"}).status_code == 403
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(Feedback)) == 0
    assert mails == []


def test_a_visitor_can_send_a_few_messages_an_hour(fresh_db, monkeypatch):
    from radar import feedback

    client, _ = _client(monkeypatch)
    codes = [client.post("/api/feedback", headers=H, json={"message": f"message number {i}"}).status_code
             for i in range(feedback.MAX_PER_HOUR + 1)]
    assert codes[:-1] == [200] * feedback.MAX_PER_HOUR and codes[-1] == 429


def test_feedback_is_deleted_after_a_year(fresh_db):
    from sqlalchemy import func, select

    from radar import feedback
    from radar.db import session_scope
    from radar.models import Feedback

    with session_scope() as s:
        s.add(Feedback(created_at=datetime.utcnow() - timedelta(days=400), kind="bug", message="old", lang="en"))
        s.add(Feedback(created_at=datetime.utcnow(), kind="bug", message="new", lang="en"))
    with session_scope() as s:
        assert feedback.cleanup(s) == 1
        assert s.scalar(select(func.count()).select_from(Feedback)) == 1


def test_the_page_and_the_footer_link(fresh_db):
    from radar.api import app

    client = TestClient(app)
    assert "feedback" in client.get("/feedback").text.lower() and client.get("/nl/feedback").status_code == 200
    assert 'href="/feedback"' in client.get("/").text and 'href="/nl/feedback"' in client.get("/nl/").text
