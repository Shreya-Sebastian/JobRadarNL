import time
from datetime import datetime, timedelta

import httpx
import respx
from fastapi.testclient import TestClient

from radar import cache
from radar.db import session_scope
from radar.models import Posting, Source
from radar.ratelimit import LocalRateLimiter
from radar.tasks import crawl_source, due_sources, finalize


def test_local_rate_limiter_spaces_requests():
    lim = LocalRateLimiter({"default": 50, "slow.example": 10})
    t0 = time.monotonic()
    for _ in range(4):
        lim.acquire("slow.example")
    assert time.monotonic() - t0 >= 0.25  # 4 requests at 10 rps need >= 0.3 s minus first
    t0 = time.monotonic()
    for _ in range(4):
        lim.acquire("fast.example")
    assert time.monotonic() - t0 < 0.2


def test_cache_local_fallback_and_version_bump(fresh_db):
    calls = []
    v = cache.cached("k", lambda: calls.append(1) or {"n": len(calls)}, ttl=60)
    assert v == {"n": 1} and cache.cached("k", lambda: calls.append(1) or {"n": len(calls)}, ttl=60) == {"n": 1}
    bumped = cache.bump_data_version()
    assert cache.cached("k", lambda: calls.append(1) or {"n": len(calls)}, ttl=60) == {"n": 2}
    # the version is persisted in the database so other processes (the API) notice it without Redis
    from radar.models import Meta

    with session_scope() as s:
        assert s.get(Meta, "data_version").value == bumped
    cache._db_version_cache = (0.0, "")
    assert cache.data_version() == bumped


@respx.mock
def test_crawl_source_job_and_finalize(fresh_db):
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(200, json={"jobs": [
            {"id": 1, "title": "Data Engineer", "absolute_url": "https://b/1", "location": {"name": "Utrecht"},
             "content": "SQL and Airflow", "updated_at": "2026-09-20T10:00:00Z"},
            {"id": 2, "title": "Data Engineer", "absolute_url": "https://b/2", "location": {"name": "Berlin"},
             "content": "SQL", "updated_at": "2026-09-20T10:00:00Z"}]}))
    respx.get("https://boards-api.greenhouse.io/v1/boards/gone/jobs").mock(return_value=httpx.Response(404))
    with session_scope() as s:
        ok = Source(company="Acme", ats="greenhouse", slug="acme")
        gone = Source(company="Gone", ats="greenhouse", slug="gone")
        s.add_all([ok, gone])
        s.flush()
        ok_id, gone_id = ok.id, gone.id
    assert crawl_source(ok_id)["new"] == 1
    assert crawl_source(gone_id)["error"] == "not_found"
    with session_scope() as s:
        assert s.get(Source, ok_id).last_status == "ok" and s.get(Source, ok_id).last_nl_count == 1
        assert s.get(Source, gone_id).active is False
        assert s.query(Posting).count() == 1
    out = finalize()
    assert out["live"] == 1 and out["tech"] == 1


def test_due_sources_follow_cadence(fresh_db):
    now = datetime.utcnow()
    with session_scope() as s:
        s.add_all([
            Source(company="never", ats="lever", slug="a"),
            Source(company="hot", ats="lever", slug="b", last_run_at=now - timedelta(minutes=90), last_nl_count=50),
            Source(company="warm", ats="lever", slug="c", last_run_at=now - timedelta(minutes=90), last_nl_count=3),
            Source(company="cold", ats="lever", slug="d", last_run_at=now - timedelta(minutes=90), last_nl_count=0),
            Source(company="off", ats="lever", slug="e", active=False),
        ])
        s.flush()
        due = {s.get(Source, i).company for i in due_sources(s, now)}
    assert due == {"never", "hot"}


def test_health_and_metrics_endpoints(fresh_db):
    from radar.api import app

    c = TestClient(app)
    assert c.get("/readyz").status_code == 200
    c.get("/api/overview")
    body = c.get("/metrics").text
    assert "radar_api_requests_total" in body and '/api/overview' in body


def test_multi_tenant_platforms_share_one_rate_limit_bucket():
    from radar.ratelimit import host_key

    assert host_key("ampelmann.recruitee.com") == "recruitee.com"
    assert host_key("Acme.Teamtailor.com") == "teamtailor.com"
    assert host_key("philips.wd3.myworkdayjobs.com") == "myworkdayjobs.com"
    assert host_key("careers.ing.com") == "careers.ing.com"
