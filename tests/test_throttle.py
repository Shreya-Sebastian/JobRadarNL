from fastapi.testclient import TestClient

from radar import throttle
from radar.api import app
from radar.config import settings

BROWSER = {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36"}


def test_scrapers_and_ai_crawlers_are_refused_search_engines_are_not(fresh_db):
    c = TestClient(app)
    for agent in ("GPTBot/1.2", "python-requests/2.32", "curl/8.5.0", "Scrapy/2.11", ""):
        assert c.get("/api/overview", headers={"user-agent": agent}).status_code == 403
    for agent in ("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
                  "LinkedInBot/1.0 (compatible; Mozilla/5.0; Apache-HttpClient +http://www.linkedin.com)",
                  BROWSER["user-agent"]):
        assert c.get("/api/overview", headers={"user-agent": agent}).status_code == 200
    # health checks and robots.txt stay reachable for everyone
    assert c.get("/healthz", headers={"user-agent": ""}).status_code == 200
    robots = c.get("/robots.txt", headers={"user-agent": "GPTBot/1.2"})
    assert robots.status_code == 200 and "User-agent: GPTBot" in robots.text


def test_requests_per_ip_are_limited(fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 5)
    monkeypatch.setattr(settings, "rate_limit_detail_per_minute", 2)
    throttle.reset()
    c = TestClient(app)
    me = {**BROWSER, "cf-connecting-ip": "203.0.113.7"}
    assert [c.get("/api/postings", headers=me).status_code for _ in range(3)] == [200, 200, 429]
    assert c.get("/api/postings", headers=me).headers["retry-after"] == "60"
    assert c.get("/api/overview", headers=me).status_code == 200  # the overall limit is higher
    assert c.get("/api/overview", headers=me).status_code == 429  # 6th request this minute
    other = {**BROWSER, "cf-connecting-ip": "198.51.100.2"}
    assert c.get("/api/postings", headers=other).status_code == 200
    assert c.get("/healthz", headers=me).status_code == 200
