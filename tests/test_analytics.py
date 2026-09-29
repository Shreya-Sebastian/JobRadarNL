from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from radar import analytics
from radar.config import settings
from radar.db import session_scope
from radar.models import DailyStat, PageView

CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/128.0 Safari/537.36")
IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
          "Version/17.0 Mobile/15E148 Safari/604.1")
GOOGLEBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"


def test_parse_agent():
    assert analytics.parse_agent(CHROME) == ("Chrome", "Windows", "desktop", False)
    assert analytics.parse_agent(IPHONE) == ("Safari", "iOS", "mobile", False)
    assert analytics.parse_agent(GOOGLEBOT)[0::3] == ("Googlebot", True)
    assert analytics.parse_agent("")[3] is True
    assert analytics.classify("/static/app.js") is None and analytics.classify("/api/version") is None
    assert analytics.classify("/vacatures/ict-utrecht") == "page" and analytics.classify("/sitemap.xml") == "crawl"


@pytest.fixture()
def client(fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "analytics_enabled", True)
    monkeypatch.setattr(settings, "admin_token", "secret-token")
    from radar.api import app

    with TestClient(app) as c:
        yield c


def _seed_posting():
    from radar.models import Posting, Source

    with session_scope() as s:
        src = Source(company="Acme", ats="lever", slug="acme")
        s.add(src)
        s.flush()
        p = Posting(source_id=src.id, external_id="1", title="Platform Engineer", company="Acme", url="https://x/1",
                    content_hash="h", dedup_key="d", first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
                    is_tech=True)
        s.add(p)
        s.flush()
        return p.id


def test_visits_are_recorded_anonymously_and_shown_to_the_admin(client):
    pid = _seed_posting()
    human = {"user-agent": CHROME, "cf-connecting-ip": "203.0.113.5", "cf-ipcountry": "NL",
             "referer": "https://www.google.com/search?q=tech+jobs"}
    client.get("/?utm_source=newsletter", headers=human)
    client.get("/api/postings?q=python&city=Utrecht", headers=human)
    client.get("/api/postings?q=python&city=Utrecht&page=2", headers=human)  # paging is not a new search
    client.post("/api/e", json={"e": "job_click", "d": str(pid), "p": "/#jobs"}, headers=human)
    client.post("/api/e", json={"e": "nav", "p": "/#market"}, headers=human)
    client.post("/api/e", json={"e": "not-an-event"}, headers=human)
    client.get("/", headers={"user-agent": IPHONE, "cf-connecting-ip": "198.51.100.7", "cf-ipcountry": "BE"})
    client.get("/robots.txt", headers={"user-agent": GOOGLEBOT, "cf-connecting-ip": "66.249.66.1"})
    client.get("/static/app.js", headers=human)  # assets are not counted
    assert analytics.flush() >= 6

    with session_scope() as s:
        rows = s.query(PageView).all()
        assert {r.event for r in rows} >= {"job_click", "nav", "search"} and "not-an-event" not in {r.event for r in rows}
        stored = " ".join(str(v) for r in rows for v in vars(r).values())
        assert "203.0.113.5" not in stored and "198.51.100.7" not in stored  # no IP addresses
        assert not any(r.path.startswith("/static") for r in rows)

    assert client.get("/api/admin/analytics").status_code == 401
    d = client.get("/api/admin/analytics", headers={"Authorization": "Bearer secret-token"}).json()
    k = d["kpi"]
    assert k["views_today"] == 3 and k["uniques_today"] == 2  # two page loads + one tab switch, two people
    assert k["job_clicks"] == 1 and k["searches"] == 1 and k["bounce_rate"] is not None
    assert {"key": "google.com", "hits": 1} in d["referrers"] and d["utm"][0]["key"] == "newsletter"
    assert {c["key"] for c in d["countries"]} == {"NL", "BE"}
    assert d["job_clicks_by_employer"] == [{"key": "Acme", "hits": 1}]
    assert d["searches"][0]["key"] == "q=python&city=Utrecht"
    assert all("Googlebot" != b["key"] for b in d["browsers"])  # bots hidden by default
    with_bots = client.get("/api/admin/analytics?bots=true", headers={"Authorization": "Bearer secret-token"}).json()
    assert {"key": "Googlebot", "hits": 1} in with_bots["bots"]
    page = client.get("/admin/analytics")
    assert page.status_code == 200 and "noindex" in page.headers["x-robots-tag"] and "{{" not in page.text


def test_admin_analytics_needs_the_token_configured(fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", None)
    from radar.api import app

    assert TestClient(app).get("/api/admin/analytics", headers={"Authorization": "Bearer x"}).status_code == 404


def test_visitor_hash_changes_every_day(fresh_db):
    a = analytics.visitor_id("203.0.113.5", CHROME, "2026-09-29")
    assert a == analytics.visitor_id("203.0.113.5", CHROME, "2026-09-29") and len(a) == 16
    assert analytics.visitor_id("203.0.113.5", CHROME, "2026-09-30") != a


def test_nightly_rollup_keeps_daily_totals_and_drops_old_rows(fresh_db):
    now = datetime(2026, 9, 30, 0, 10)
    with session_scope() as s:
        for i, (ts, bot, country) in enumerate([(now - timedelta(hours=5), False, "NL"),
                                                (now - timedelta(hours=4), False, "NL"),
                                                (now - timedelta(hours=3), True, "US"),
                                                (now - timedelta(days=100), False, "DE")]):
            s.add(PageView(ts=ts, kind="page", path="/", status=200, ms=5, bytes=100, bot=bot, country=country,
                           visitor=f"v{i % 2}"))
    with session_scope() as s:
        out = analytics.nightly(s, now=now)
        assert out["deleted"] == 1
        total = s.query(DailyStat).filter_by(day=(now - timedelta(days=1)).date(), dim="total").one()
        assert (total.hits, total.humans, total.uniques) == (3, 2, 2)
        assert s.query(DailyStat).filter_by(dim="country", key="NL").one().humans == 2
        at = analytics._all_time(s, [], datetime(2026, 9, 30))
        assert at["hits"] == 3 and at["humans"] == 2 and at["countries"] == 1
