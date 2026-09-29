from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from radar import alerts, auth, mailer
from radar.adapters.base import RawPosting
from radar.crawler import ingest
from radar.db import session_scope
from radar.models import Source, User, UserData

H = {"X-Requested-With": "radar"}


def _jobs():
    with session_scope() as s:
        src = Source(company="Acme", ats="greenhouse", slug="acme")
        s.add(src)
        s.flush()
        ingest(s, src, [
            RawPosting(external_id="1", title="Backend Developer", url="https://acme.example/1",
                       location="Utrecht, Netherlands", description_text="Python and SQL backend work."),
            RawPosting(external_id="2", title="Frontend Developer", url="https://acme.example/2",
                       location="Rotterdam, Netherlands", description_text="React and TypeScript."),
        ])


def _user(s, frequency="daily", cities=("Utrecht",), lang="en"):
    u = User(email="ada@example.org", alerts=frequency, lang=lang,
             alerts_sent_at=datetime.utcnow() - timedelta(days=2))
    s.add(u)
    s.flush()
    s.add(UserData(user_id=u.id, profile={"cities": list(cities), "skills": ["Python"]}, saved=[]))
    return u


def test_daily_alert_lists_matching_new_jobs_with_one_click_unsubscribe(fresh_db):
    mailer.OUTBOX.clear()
    _jobs()
    with session_scope() as s:
        _user(s)
    with session_scope() as s:
        assert alerts.run(s) == {"due": 1, "sent": 1, "empty": 0, "failed": 0}
    msg = mailer.OUTBOX[-1]
    body = msg.get_body(("plain",)).get_content()
    assert msg["Subject"] == "1 new tech job for you" and "Backend Developer" in body and "Frontend" not in body
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click" and "/alerts/unsubscribe?" in msg["List-Unsubscribe"]
    with session_scope() as s:  # sent: not due again until tomorrow
        assert alerts.run(s)["due"] == 0

    url = msg["List-Unsubscribe"].strip("<>")
    q = parse_qs(urlparse(url).query)
    from radar.api import app

    client = TestClient(app)
    assert client.get("/alerts/unsubscribe", params={"u": q["u"][0], "t": "wrong"}).status_code == 400
    assert client.post("/alerts/unsubscribe", params={"u": q["u"][0], "t": q["t"][0]}).status_code == 200
    with session_scope() as s:
        assert s.query(User).one().alerts == "off"


def test_no_mail_when_nothing_new_matches_and_dutch_alerts(fresh_db):
    mailer.OUTBOX.clear()
    _jobs()
    with session_scope() as s:
        _user(s, cities=("Groningen",))
    with session_scope() as s:
        assert alerts.run(s)["empty"] == 1 and not mailer.OUTBOX
    with session_scope() as s:
        u = s.query(User).one()
        u.alerts_sent_at, u.lang = datetime.utcnow() - timedelta(days=2), "nl"
        s.query(UserData).one().profile = {"cities": ["Rotterdam"]}
    with session_scope() as s:
        alerts.run(s)
    assert mailer.OUTBOX[-1]["Subject"] == "1 nieuwe techvacature voor jou"


def test_alert_setting_via_the_api(fresh_db):
    mailer.OUTBOX.clear()
    auth._ip_hits.clear()
    from radar.api import app

    with TestClient(app) as client:
        assert client.get("/api/me/alerts").status_code == 401
        client.post("/api/auth/request", json={"email": "bo@example.org"}, headers=H)
        link = next(w for w in mailer.OUTBOX[-1].get_body(("plain",)).get_content().split() if "token=" in w)
        client.get("/auth/verify?token=" + parse_qs(urlparse(link).query)["token"][0], follow_redirects=False)
        assert client.put("/api/me/alerts", json={"frequency": "weekly"}).status_code == 403  # header required
        assert client.put("/api/me/alerts", json={"frequency": "hourly"}, headers=H).status_code == 422
        assert client.put("/api/me/alerts", json={"frequency": "weekly", "lang": "nl"}, headers=H).json() == \
            {"frequency": "weekly"}
        assert client.get("/api/me/alerts").json() == {"frequency": "weekly"}
        assert client.get("/api/me/export").json()["job_alerts"] == "weekly"
        with session_scope() as s:
            u = s.query(User).one()
            assert u.lang == "nl" and u.alerts_sent_at is not None  # starts from now, not the backlog
