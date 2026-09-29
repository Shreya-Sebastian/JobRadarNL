from datetime import datetime, timedelta

import httpx
import respx

from radar.adapters.base import RawPosting
from radar.crawler import ingest
from radar.db import session_scope
from radar.integrity import _check_url, link_check, quality_report, violations
from radar.models import Posting, Source


def _raw(ext, title="Backend Engineer", url=None):
    return RawPosting(external_id=ext, title=title, url=url or f"https://acme.nl/jobs/{ext}",
                      location="Amsterdam, Netherlands", description_text="Python and AWS. " * 20)


def test_partial_response_does_not_close_postings(fresh_db):
    with session_scope() as s:
        src = Source(company="Acme", ats="greenhouse", slug="acme")
        s.add(src)
        s.flush()
        ingest(s, src, [_raw(str(i)) for i in range(20)])
        src.last_nl_count = 20
        c = ingest(s, src, [_raw("1"), _raw("2")])          # 2 of 20: suspicious, keep everything open
        assert c["partial"] is True and c["closed"] == 0
        assert s.query(Posting).filter(Posting.closed_at.is_(None)).count() == 20
        c = ingest(s, src, [_raw(str(i)) for i in range(12)])  # 12 of 20: a normal shrink, close the rest
        assert c["partial"] is False and c["closed"] == 8


@respx.mock
def test_check_url_classifies_gone_redirected_ok():
    respx.get("https://acme.nl/jobs/1").mock(return_value=httpx.Response(200, text="<html>Backend Engineer</html>",
                                                                          headers={"content-type": "text/html"}))
    respx.get("https://acme.nl/jobs/2").mock(return_value=httpx.Response(404))
    respx.get("https://acme.nl/jobs/3").mock(return_value=httpx.Response(302, headers={"location": "https://acme.nl/careers"}))
    respx.get("https://acme.nl/careers").mock(return_value=httpx.Response(200, text="<html>all jobs</html>",
                                                                           headers={"content-type": "text/html"}))
    respx.get("https://acme.nl/jobs/4").mock(return_value=httpx.Response(200, headers={"content-type": "text/html"},
                                                                          text="<html>This position has been filled.</html>"))
    respx.get("https://acme.nl/jobs/5").mock(return_value=httpx.Response(200, headers={"content-type": "text/html"},
        text='<html><script>var e404 = "page not found";</script><h1>Senior Backend Engineer</h1></html>'))
    assert _check_url("https://acme.nl/jobs/1") == "ok"
    assert _check_url("https://acme.nl/jobs/2") == "gone"
    assert _check_url("https://acme.nl/jobs/3") == "redirected"
    assert _check_url("https://acme.nl/jobs/4") == "gone"
    assert _check_url("https://acme.nl/jobs/5", "Senior Backend Engineer") == "ok"  # '404' inside a script is not evidence


def test_link_check_flags_source_instead_of_closing_when_most_links_look_dead(fresh_db):
    with respx.mock:
        for i in range(4):
            respx.get(f"https://acme.nl/jobs/{i}").mock(return_value=httpx.Response(404))
        with session_scope() as s:
            src = Source(company="Acme", ats="greenhouse", slug="acme")
            s.add(src)
            s.flush()
            ingest(s, src, [_raw(str(i)) for i in range(4)])
            for p in s.query(Posting):
                p.first_seen = datetime.utcnow() - timedelta(days=40)
                p.posted_at = None
            s.flush()
            res = link_check(s, sample=10, older_than_days=21, workers=2)
            assert res["gone"] == 4 and res["closed"] == 0 and res["sources_flagged"] == 1
            assert "look dead" in s.get(Source, src.id).last_error


def test_test_boards_are_switched_off():
    from radar.registry import classify_source, looks_like_test_board

    assert looks_like_test_board("Acmecorp", "AcmeCorp091614")
    assert looks_like_test_board("Demo", "demo-company") and looks_like_test_board("X", "sandbox")
    assert not looks_like_test_board("Testronic", "testronic")  # a real company whose name starts with "test"
    assert looks_like_test_board("Test Company", "test-company")
    assert classify_source("Acmecorp", "acmecorp091614") == "test"
    assert classify_source("Adyen", "adyen") == "employer"


@respx.mock
def test_link_check_closes_gone_postings(fresh_db):
    respx.get("https://acme.nl/jobs/old").mock(return_value=httpx.Response(404))
    respx.get("https://acme.nl/jobs/fine").mock(return_value=httpx.Response(200, text="<html>ok</html>",
                                                                             headers={"content-type": "text/html"}))
    with session_scope() as s:
        src = Source(company="Acme", ats="greenhouse", slug="acme")
        s.add(src)
        s.flush()
        ingest(s, src, [_raw("old"), _raw("fine"), _raw("new")])
        for p in s.query(Posting).filter(Posting.external_id.in_(["old", "fine"])):
            p.first_seen = datetime.utcnow() - timedelta(days=40)
            p.posted_at = None
        s.flush()
        res = link_check(s, sample=10, older_than_days=21, workers=2)
        assert res["checked"] == 2 and res["gone"] == 1 and res["closed"] == 1
        assert s.query(Posting).filter_by(external_id="old").one().closed_at is not None
        assert s.query(Posting).filter_by(external_id="new").one().link_checked_at is None  # too recent


def test_quality_report_and_thresholds(fresh_db):
    with session_scope() as s:
        src = Source(company="Acme", ats="greenhouse", slug="acme")
        s.add(src)
        s.flush()
        ingest(s, src, [_raw("1"), RawPosting(external_id="2", title="Data Engineer", url="https://acme.nl/jobs/2",
                                                location="Netherlands", description_text="x")])
        rep = quality_report(s)
    assert rep["live_postings"] == 2 and rep["empty_description_share"] == 0.5 and rep["unknown_city_share"] == 0.5
    assert "empty_description_share = 0.5 exceeds 0.1" in violations(rep)
