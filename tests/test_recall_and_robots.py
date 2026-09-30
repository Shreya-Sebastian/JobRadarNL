import httpx
import respx

from radar import robots
from radar.adapters.base import RawPosting
from radar.crawler import ingest
from radar.db import session_scope
from radar.models import Source


def _source(session, company="Acme", ats="greenhouse", slug="acme"):
    src = Source(company=company, ats=ats, slug=slug, url=f"https://{slug}.example", active=True)
    session.add(src)
    session.flush()
    return src


def _raw(ext, title, company=None, desc="Python, AWS and Docker. 3 years experience."):
    return RawPosting(external_id=ext, title=title, location="Amsterdam, Netherlands", url=f"https://x/{ext}",
                      description_html=desc, company=company)


def _adzuna(id_, title, company, desc="Python developer with Docker and Kubernetes experience."):
    return {"id": id_, "title": title, "company": {"display_name": company},
            "location": {"display_name": "Amsterdam, Noord-Holland"}, "redirect_url": f"https://adzuna/{id_}",
            "created": "2026-09-20T10:00:00Z", "description": desc, "category": {"tag": "it-jobs"}}


@respx.mock
def test_recall_matches_conservatively_and_stays_private(fresh_db, monkeypatch, tmp_path):
    from radar import recall
    from radar.config import settings

    monkeypatch.setattr(settings, "adzuna_app_id", "id")
    monkeypatch.setattr(settings, "adzuna_app_key", "key")
    with session_scope() as s:
        acme = _source(s)
        ingest(s, acme, [_raw("1", "Senior Backend Engineer"), _raw("2", "Data Scientist")])
        rand = _source(s, "Randstad", "lever", "randstad")
        ingest(s, rand, [_raw("3", "Java Developer")])

    respx.get("https://api.adzuna.com/v1/api/jobs/nl/search/1").mock(return_value=httpx.Response(200, json={
        "results": [
            _adzuna(1, "Senior Backend Engineer (m/f/d)", "Acme B.V."),        # matched: same employer, same title
            _adzuna(2, "Frontend Engineer", "Acme"),                            # employer known, title missing
            _adzuna(3, "Java Developer", "Randstad"),                           # matched, but an agency
            _adzuna(4, "Platform Engineer", "Globex"),                          # unknown employer
            _adzuna(5, "Platform Engineer", "Globex"),
            _adzuna(6, "Sales Manager Benelux", "Globex", "Drive revenue with our sales team."),  # not tech
        ]}))
    with session_scope() as s:
        report, path = recall.run(s, pages=1, out_dir=tmp_path)
        assert report.sample == 6 and report.sample_tech == 5 and report.sample_tech_employer == 4
        assert report.matched == 2 and report.matched_tech_employer == 1
        assert abs(report.recall_tech_employer - 0.25) < 1e-9
        assert report.employer_known_unmatched == 1
        assert report.missing_employers[0] == {"company": "Globex", "postings": 2}
        assert path.exists() and "Globex" in path.read_text(encoding="utf-8")
        assert recall.published(s) is None  # nothing on the site without --publish
        recall.publish(s, report)
        pub = recall.published(s)
        assert pub["sample_tech_employer"] == 4 and pub["recall_tech_employer"] == 0.25 and pub["source"] == "Adzuna"

    from fastapi.testclient import TestClient

    from radar.api import app

    cov = TestClient(app).get("/api/coverage").json()
    assert cov["recall"]["recall_tech_employer"] == 0.25


def test_recall_requires_keys(fresh_db, monkeypatch):
    import pytest

    from radar import recall
    from radar.config import settings

    monkeypatch.setattr(settings, "adzuna_app_id", None)
    with pytest.raises(RuntimeError, match="RADAR_ADZUNA_APP_ID"):
        recall.fetch_sample(1)


@respx.mock
def test_jsonld_adapter_honours_robots_disallow_and_crawl_delay():
    from radar.adapters.jsonld import JsonLdAdapter
    from radar.ratelimit import get_limiter

    robots.reset()
    respx.get("https://jobs.example/robots.txt").mock(return_value=httpx.Response(
        200, text="User-agent: *\nDisallow: /private/\nCrawl-delay: 10\n", headers={"content-type": "text/plain"}))
    job = ('<html><body><script type="application/ld+json">{"@type":"JobPosting","title":"Engineer",'
           '"url":"https://jobs.example/jobs/1","hiringOrganization":{"name":"Ex"},'
           '"jobLocation":{"address":{"addressLocality":"Utrecht","addressCountry":"NL"}},'
           '"description":"Python"}</script></body></html>')
    respx.get("https://jobs.example/jobs/1").mock(return_value=httpx.Response(200, text=job, headers={"content-type": "text/html"}))
    private = respx.get("https://jobs.example/private/jobs/2").mock(return_value=httpx.Response(200, text=job, headers={"content-type": "text/html"}))
    respx.get("https://jobs.example/sitemap.xml").mock(return_value=httpx.Response(200, text=(
        "<urlset><url><loc>https://jobs.example/jobs/1</loc></url>"
        "<url><loc>https://jobs.example/private/jobs/2</loc></url></urlset>"), headers={"content-type": "application/xml"}))

    limiter = get_limiter()
    limiter.limits.pop("jobs.example", None)
    client = httpx.Client()  # no throttle hook: the test only checks the limit was lowered
    postings = JsonLdAdapter(client).fetch("https://jobs.example/sitemap.xml")
    assert [p.title for p in postings] == ["Engineer"]
    assert not private.called
    assert abs(limiter.rate("jobs.example") - 0.1) < 1e-9
    robots.reset()
    limiter.limits.pop("jobs.example", None)


def test_robots_longest_match_precedence_and_delays():
    rules = robots.parse("User-agent: *\nDisallow: /\nAllow: /$\nAllow: /careers\nDisallow: /careers/private/\nCrawl-delay: 2\n")
    assert rules.allowed("/") and rules.allowed("/careers/job/1?x=1") and not rules.allowed("/careers/private/2")
    assert not rules.allowed("/admin") and rules.crawl_delay == 2
    # wildcard and anchor
    rules = robots.parse("User-agent: *\nDisallow: /*.pdf$\nDisallow: /search*\nRequest-rate: 10/1\n")
    assert not rules.allowed("/a/b.pdf") and rules.allowed("/a/b.pdf?x") and not rules.allowed("/search-jobs/")
    assert rules.crawl_delay == 0.1
    # our own token gets its own group; nothing for us means the star group
    rules = robots.parse("User-agent: TechJobsRadar\nDisallow: /jobs\n\nUser-agent: *\nAllow: /\n")
    assert not rules.allowed("/jobs/1")
    # the token robots.txt rules are matched on is the one the crawler sends
    from radar.config import settings

    assert settings.user_agent.lower().startswith(robots.OUR_TOKEN + "/")
    assert robots.parse("").allowed("/anything")
