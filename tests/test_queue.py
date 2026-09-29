"""Queue round trip on an in-memory Redis: schedule -> worker (burst) -> finalize."""

import fakeredis
import httpx
import respx
from rq import SimpleWorker

from radar import queue as q
from radar.db import session_scope
from radar.models import Posting, Source
from radar.tasks import finalize, schedule


@respx.mock
def test_schedule_worker_finalize_round_trip(fresh_db, monkeypatch):
    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(q, "get_redis", lambda: fake)
    monkeypatch.setattr("radar.config.settings.redis_url", "redis://fake")
    respx.get("https://api.lever.co/v0/postings/acme").mock(return_value=httpx.Response(200, json=[
        {"id": "x1", "text": "Platform Engineer", "hostedUrl": "https://jobs.lever.co/acme/x1",
         "categories": {"location": "Amsterdam"}, "country": "NL", "descriptionPlain": "Kubernetes and Terraform.",
         "createdAt": 1700000000000}]))
    with session_scope() as s:
        s.add(Source(company="Acme", ats="lever", slug="acme"))

    out = schedule()
    assert out == {"due": 1, "queued": 1}
    assert q.get_queue().count == 1
    assert schedule()["queued"] == 0  # same job already queued: not duplicated

    worker = SimpleWorker([q.get_queue()], connection=fake)
    worker.work(burst=True, with_scheduler=False)
    with session_scope() as s:
        p = s.query(Posting).one()
        assert p.title == "Platform Engineer" and p.extraction["skills_required"] == ["Kubernetes", "Terraform"]
        assert s.query(Source).one().last_status == "ok"

    result = finalize()
    assert result["live"] == 1 and result["tech"] == 1
    assert fake.get("radar:data_version") is not None
