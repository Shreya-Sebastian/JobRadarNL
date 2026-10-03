import json
import re
from datetime import datetime

from fastapi.testclient import TestClient

from radar.adapters.base import RawPosting
from radar.crawler import ingest
from radar.db import session_scope
from radar.models import Posting, Source

BROWSER = {"user-agent": "Mozilla/5.0 Chrome/130", "accept": "text/html"}
TEXT = ("About the role\n\nYou build payment services in Java and Kotlin on AWS. <script>alert(1)</script>\n\n"
        "What we ask\nAt least 3 years of experience. You speak English; Dutch is not required.")


def _setup():
    with session_scope() as s:
        src = Source(company="Adyen", ats="greenhouse", slug="adyen")
        s.add(src)
        s.flush()
        ingest(s, src, [RawPosting(external_id="1", title="Senior Backend Engineer", url="https://careers.adyen.com/j/1",
                                   location="Amsterdam, Netherlands", description_text=TEXT,
                                   posted_at=datetime(2026, 9, 28)),
                        RawPosting(external_id="2", title="Office Manager", url="https://careers.adyen.com/j/2",
                                   location="Amsterdam, Netherlands", description_text="Run the office.")])
        tech = s.query(Posting).filter_by(external_id="1").one()
        other = s.query(Posting).filter_by(external_id="2").one()
        return tech.id, other.id


def test_job_page_shows_the_employers_text_with_credit_and_links_back(fresh_db):
    from radar.api import app

    pid, _ = _setup()
    c = TestClient(app)
    r = c.get(f"/job/{pid}/senior-backend-engineer", headers=BROWSER)
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    html = r.text
    assert "Senior Backend Engineer" in html and "You build payment services in Java" in html
    assert "From Adyen&#x27;s job posting, as published on careers.adyen.com" in html
    assert 'href="https://careers.adyen.com/j/1"' in html and "View and apply on" in html
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html  # employer text is escaped
    assert 'name="robots"' not in html  # open listings are indexable
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1)
                    .replace("<\\/", "</"))
    assert ld["@type"] == "JobPosting" and ld["hiringOrganization"]["name"] == "Adyen"
    assert ld["datePosted"] == "2026-09-28" and ld["directApply"] is False
    nl = c.get(f"/nl/vacature/{pid}/senior-backend-engineer", headers=BROWSER)
    assert nl.status_code == 200 and "Vacaturetekst" in nl.text and 'lang="nl"' in nl.text


def test_job_page_addresses(fresh_db):
    from radar.api import app

    pid, other = _setup()
    c = TestClient(app)
    moved = c.get(f"/job/{pid}/old-title", headers=BROWSER, follow_redirects=False)
    assert moved.status_code == 301 and moved.headers["location"] == f"/job/{pid}/senior-backend-engineer"
    assert c.get(f"/job/{other}/office-manager", headers=BROWSER).status_code == 404  # not a tech listing
    assert c.get("/job/999999/x", headers=BROWSER).status_code == 404
    with session_scope() as s:
        s.get(Posting, pid).closed_at = datetime.utcnow()
    closed = c.get(f"/job/{pid}/senior-backend-engineer", headers=BROWSER).text
    assert "no longer open" in closed and 'content="noindex, follow"' in closed and "JobPosting" not in closed


def test_sitemap_lists_job_pages(fresh_db):
    from radar.api import app

    pid, _ = _setup()
    sm = TestClient(app).get("/sitemap.xml").text
    assert f"/job/{pid}/senior-backend-engineer" in sm and f"/nl/vacature/{pid}/senior-backend-engineer" in sm


def test_job_page_keeps_the_employers_formatting(fresh_db):
    from radar.api import app

    with session_scope() as s:
        src = Source(company="Adyen", ats="greenhouse", slug="adyen")
        s.add(src)
        s.flush()
        ingest(s, src, [RawPosting(external_id="9", title="Data Engineer", url="https://careers.adyen.com/j/9",
                                   location="Amsterdam, Netherlands",
                                   description_html="<h2>What you do</h2><p>Build <b>Spark</b> pipelines in Python "
                                                    "and SQL on AWS.</p><ul><li>Kafka</li><li>Airflow</li></ul>")])
        p = s.query(Posting).filter_by(external_id="9").one()
        pid, stored = p.id, p.description_html
    assert stored == "<h3>What you do</h3><p>Build <strong>Spark</strong> pipelines in Python and SQL on AWS.</p>" \
                     "<ul><li>Kafka</li><li>Airflow</li></ul>"
    html = TestClient(app).get(f"/job/{pid}/data-engineer", headers=BROWSER).text
    assert "<h3>What you do</h3>" in html and "<ul><li>Kafka</li><li>Airflow</li></ul>" in html
