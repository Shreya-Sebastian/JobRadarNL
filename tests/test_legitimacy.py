from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from radar.adapters.base import RawPosting
from radar.crawler import ingest
from radar.db import session_scope
from radar.models import Posting, Source


def _src(s, company="Acme Robotics", slug="acme"):
    src = Source(company=company, ats="greenhouse", slug=slug, url="https://acme.example", active=True,
                 discovered_by="discovery-guess")
    s.add(src)
    s.flush()
    return src


def _raw(ext, title, valid=None, desc="Python, Docker and Kubernetes at Acme Robotics."):
    return RawPosting(external_id=ext, title=title, location="Utrecht, Netherlands", url=f"https://acme.example/{ext}",
                      description_html=desc, raw={"valid_through": valid} if valid else {})


def test_expired_valid_through_closes_the_posting(fresh_db):
    past = (datetime.utcnow() - timedelta(days=3)).isoformat()
    future = (datetime.utcnow() + timedelta(days=30)).isoformat()
    with session_scope() as s:
        src = _src(s)
        ingest(s, src, [_raw("1", "Backend Engineer", future), _raw("2", "Data Engineer", future)])
        c = ingest(s, src, [_raw("1", "Backend Engineer", future), _raw("2", "Data Engineer", past)])
        assert c["expired"] == 1 and c["closed"] == 1
        live = {p.title for p in s.query(Posting).filter(Posting.closed_at.is_(None))}
        assert live == {"Backend Engineer"}
        assert s.query(Posting).filter_by(external_id="1").one().valid_through is not None


def test_expiry_ignored_when_a_source_marks_everything_expired(fresh_db):
    past = (datetime.utcnow() - timedelta(days=400)).isoformat()
    with session_scope() as s:
        src = _src(s)
        c = ingest(s, src, [_raw(str(i), f"Engineer {i}", past) for i in range(6)])
        assert c["new"] == 6 and c["expired"] == 0


def test_talent_pools_are_not_vacancies():
    from radar.classify import is_tech

    for t in ("Talentpool - UI/UX Designers", "Senior Software Engineer (Java) - Talent Pool",
              "Netwerkbeheerder (aanmelden talentpool)", "Future opportunities in Data Engineering"):
        assert not is_tech(t, "Python, Kubernetes, AWS, Docker, SQL"), t
    assert is_tech("Senior Software Engineer (Java)", "")


def test_closed_page_phrases():
    from radar.integrity import _GONE_TEXT

    for text in ("De sollicitatietermijn is verlopen.", "Applications are now closed for this role.",
                 "Deze vacature is niet meer actief", "Die Stelle ist bereits besetzt."):
        assert _GONE_TEXT.search(text), text
    assert not _GONE_TEXT.search("We are hiring engineers who want to close the gap between research and product.")


def test_confirmed_filter_and_trust_fields(fresh_db):
    with session_scope() as s:
        src = _src(s)
        ingest(s, src, [_raw("1", "Backend Engineer"), _raw("2", "Data Engineer")])
        old = s.query(Posting).filter_by(external_id="2").one()
        old.last_seen = datetime.utcnow() - timedelta(days=20)
    from radar.api import app

    client = TestClient(app)
    items = client.get("/api/postings", params={"confirmed_days": 7}).json()["items"]
    assert [i["title"] for i in items] == ["Backend Engineer"]
    assert items[0]["confirmed_at"] and items[0]["source_kind"] == "employer"


def test_verify_sources_flags_namesake_boards(fresh_db):
    from radar.integrity import verify_sources

    with session_scope() as s:
        good = _src(s, "Acme Robotics", "acme")
        ingest(s, good, [_raw(str(i), f"Engineer {i}") for i in range(4)])
        bad = _src(s, "Delta Precision", "delta")
        ingest(s, bad, [_raw(f"d{i}", f"Flight Attendant {i}", desc="Join our airline cabin crew.") for i in range(4)])
        flagged = verify_sources(s, since_days=1)
        assert [f["company"] for f in flagged] == ["Delta Precision"]
        assert s.get(Source, bad.id).last_error.startswith("unverified")


def test_job_links_never_point_at_a_homepage():
    from radar.adapters.jsonld import _job_url

    page = "https://www.iquality.nl/vacatures/devops-engineer"
    assert _job_url("www.iquality.nl", page) == page
    assert _job_url("https://www.iquality.nl/", page) == page
    assert _job_url("/vacatures/devops-engineer?ref=x", "https://www.iquality.nl/sitemap") == \
        "https://www.iquality.nl/vacatures/devops-engineer?ref=x"
    assert _job_url("https://jobs.example.com/j/123", page) == "https://jobs.example.com/j/123"



def test_linked_boards_are_not_second_guessed(fresh_db):
    from radar.integrity import verify_sources

    with session_scope() as s:
        linked = Source(company="Cmcom", ats="recruitee", slug="cmcom", url="https://cm.example", active=True,
                        discovered_by="discovery")
        s.add(linked)
        s.flush()
        ingest(s, linked, [_raw(f"c{i}", f"Engineer {i}", desc="We connect conversations and payments.")
                           for i in range(4)])
        assert verify_sources(s, since_days=1) == []


def test_test_postings_are_not_vacancies():
    from radar.classify import is_tech

    for t in ("AMC testvacature", "Test Template evaluatieformulieren", "Dummy Software Engineer", "DO NOT APPLY - Java"):
        assert not is_tech(t, "Python, Java, Docker, Kubernetes"), t
    assert is_tech("Test Automation Engineer", "")
