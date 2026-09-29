from fastapi.testclient import TestClient

from radar import admin
from radar.config import settings


def _client():
    from radar.api import app

    return TestClient(app)


def test_version_endpoint(fresh_db):
    v = _client().get("/api/version").json()
    assert "version" in v and "last_crawl_at" in v


def test_admin_disabled_without_token(fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", None)
    c = _client()
    assert c.post("/api/admin/crawl", json={"scope": "due"}).status_code == 404
    assert c.get("/api/admin/status").status_code == 404


def test_admin_rejects_wrong_token_and_runs_with_the_right_one(fresh_db, monkeypatch):
    from radar.db import session_scope
    from radar.models import Source

    monkeypatch.setattr(settings, "admin_token", "s3cret")
    monkeypatch.setattr(settings, "redis_url", None)
    ran = []
    monkeypatch.setattr(admin, "_run_local", lambda ids: ran.append(ids) or admin._status.update(running=False))
    monkeypatch.setattr(admin, "_last_start", 0.0)
    admin._status.update(running=False)
    with session_scope() as s:
        s.add(Source(company="Acme", ats="greenhouse", slug="acme", url="https://acme.example", active=True))
    c = _client()
    assert c.post("/api/admin/crawl", json={"scope": "all"}).status_code == 401
    assert c.post("/api/admin/crawl", json={"scope": "all"}, headers={"Authorization": "Bearer nope"}).status_code == 401
    ok = {"Authorization": "Bearer s3cret"}
    r = c.post("/api/admin/crawl", json={"scope": "company", "company": "acme"}, headers=ok)
    assert r.status_code == 202 and r.json()["sources"] == 1
    import time
    for _ in range(50):
        if ran:
            break
        time.sleep(0.02)
    assert len(ran) == 1 and len(ran[0]) == 1
    # cool-down, then force
    assert c.post("/api/admin/crawl", json={"scope": "all"}, headers=ok).status_code == 429
    assert c.post("/api/admin/crawl", json={"scope": "all", "force": True}, headers=ok).status_code == 202
    # an unknown employer never falls through to crawling everything
    assert c.post("/api/admin/crawl", json={"scope": "company", "company": "nobody", "force": True},
                  headers=ok).status_code == 404
    assert c.get("/api/admin/status", headers=ok).json()["mode"] == "local"
