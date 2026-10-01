import httpx
import respx

from radar import robots
from radar.adapters.jsonld import JsonLdAdapter, _url_key
from radar.crawler import fetch_source, ingest, known_urls_for
from radar.db import session_scope
from radar.models import Posting, Source

# a realistic posting text: pages stored with only a line or two are read again on the next crawl
_TEXT = "You build data services in Python and SQL with a small team in Utrecht. " * 6


def _job(title, url, city="Utrecht"):
    ident = url.rsplit("/", 1)[-1]
    return ('<html><body><script type="application/ld+json">{"@type":"JobPosting","title":"' + title + '","url":"' + url
            + '","identifier":{"value":"' + ident + '"},"hiringOrganization":{"name":"Ex"},'
            '"jobLocation":{"address":{"addressLocality":"' + city + '","addressCountry":"NL"}},'
            '"description":"' + _TEXT + '"}</script></body></html>')


@respx.mock
def test_sitemap_crawl_is_incremental_and_keeps_still_listed_postings_open(fresh_db):
    robots.reset()
    html = {"content-type": "text/html"}
    respx.get("https://jobs.example/robots.txt").mock(return_value=httpx.Response(404))
    sitemap = respx.get("https://jobs.example/jobs/sitemap.xml")
    page1 = respx.get("https://jobs.example/jobs/1").mock(return_value=httpx.Response(200, text=_job("Engineer", "https://jobs.example/jobs/1"), headers=html))
    page2 = respx.get("https://jobs.example/jobs/2").mock(return_value=httpx.Response(200, text=_job("Analyst", "https://jobs.example/jobs/2"), headers=html))
    page3 = respx.get("https://jobs.example/jobs/3").mock(return_value=httpx.Response(200, text=_job("Tester", "https://jobs.example/jobs/3"), headers=html))

    def sm(urls):
        return httpx.Response(200, text="<urlset>" + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>",
                              headers={"content-type": "application/xml"})

    with session_scope() as s:
        src = Source(company="Ex", ats="jsonld", slug="https://jobs.example/jobs/sitemap.xml", url="https://jobs.example", active=True)
        s.add(src)
        s.flush()
        # first crawl: nothing known, both pages fetched
        sitemap.mock(return_value=sm(["https://jobs.example/jobs/1", "https://jobs.example/jobs/2"]))
        adapter = JsonLdAdapter(httpx.Client())
        raws = adapter.fetch(src.slug)
        assert len(raws) == 2 and page1.call_count == 1 and page2.call_count == 1
        counters = ingest(s, src, raws)
        assert counters["new"] == 2
        src.last_nl_count = 2

        # second crawl: page 1 still listed, page 2 gone, page 3 new -> only page 3 fetched
        sitemap.mock(return_value=sm(["https://jobs.example/jobs/1", "https://jobs.example/jobs/3"]))
        known = known_urls_for(s, src)
        assert known == {_url_key("https://jobs.example/jobs/1"): "1", _url_key("https://jobs.example/jobs/2"): "2"}
        adapter = JsonLdAdapter(httpx.Client())
        adapter.REFRESH_EVERY = 10**9  # never refresh in this test
        adapter.known_urls = known
        raws = adapter.fetch(src.slug)
        assert [r.external_id for r in raws] == ["3"] and adapter.still_listed == {"1"} and adapter.skipped == 1
        assert page1.call_count == 1 and page3.call_count == 1
        for ext in adapter.still_listed:
            from radar.adapters.base import RawPosting
            raws.append(RawPosting(external_id=ext, title="", url="", raw={"still_listed": True}))
        counters = ingest(s, src, raws)
        assert counters["new"] == 1 and counters["closed"] == 1 and counters["seen"] == 2
        open_ids = {p.external_id for p in s.scalars(__import__("sqlalchemy").select(Posting).where(Posting.closed_at.is_(None)))}
        assert open_ids == {"1", "3"}
    robots.reset()


def test_fetch_source_passes_known_urls_and_appends_still_listed(fresh_db, monkeypatch):
    from radar import crawler

    class FakeAdapter:
        def __init__(self):
            self.known_urls = {}
            self.still_listed = set()

        def fetch(self, slug):
            assert self.known_urls == {"k": "42"}
            self.still_listed = {"42"}
            return []

    monkeypatch.setattr(crawler, "get_adapter", lambda ats: FakeAdapter())
    src = Source(company="Ex", ats="jsonld", slug="https://x.example/sitemap.xml", url="https://x.example", active=True)
    _, raws, err = fetch_source(src, crawler._DomainThrottle(0), {"k": "42"})
    assert err is None and len(raws) == 1 and raws[0].external_id == "42" and raws[0].raw["still_listed"]


@respx.mock
def test_sitemap_urls_are_xml_unescaped():
    respx.get("https://x.example/sitemap.xml").mock(return_value=httpx.Response(200, headers={"content-type": "application/xml"},
        text="<urlset><url><loc>https://x.example/careers/job/1?domain=a&amp;microsite=b</loc></url></urlset>"))
    urls = JsonLdAdapter(httpx.Client())._sitemap_urls("https://x.example/sitemap.xml")
    assert urls == ["https://x.example/careers/job/1?domain=a&microsite=b"]


def test_jsonld_with_raw_newlines_in_strings_is_parsed():
    from bs4 import BeautifulSoup

    from radar.adapters.jsonld import _jobpostings

    page = ('<script type="application/ld+json">{"@type": "JobPosting", "title": "TNO Traineeship",\r\n'
            '"description": "\r\n  <p>About this position</p>\r\n"}</script>')
    objs = _jobpostings(BeautifulSoup(page, "lxml"))
    assert [o["title"] for o in objs] == ["TNO Traineeship"]


def test_shared_identifier_across_pages_falls_back_to_url():
    from radar.adapters.base import RawPosting
    from radar.adapters.jsonld import _unique_ids

    raws = [RawPosting(external_id="TNO", title="Traineeship", url="https://tno.example/v/1"),
            RawPosting(external_id="TNO", title="Scientist", url="https://tno.example/v/2"),
            RawPosting(external_id="R123", title="Engineer", url="https://tno.example/v/3"),
            RawPosting(external_id="R123", title="Engineer", url="https://tno.example/v/3")]
    out = _unique_ids(raws)
    assert sorted(r.external_id for r in out) == ["R123", "https://tno.example/v/1", "https://tno.example/v/2"]



def test_jsonld_with_trailing_comma_and_location_from_url():
    from bs4 import BeautifulSoup

    from radar.adapters.jsonld import _jobpostings, _to_raw

    page = '<script type="application/ld+json">\n {"@type": "JobPosting", "title": "Officier Engineer"},\n </script>'
    objs = _jobpostings(BeautifulSoup(page, "lxml"))
    assert [o["title"] for o in objs] == ["Officier Engineer"]
    raw = _to_raw({"@type": "JobPosting", "title": "Product Owner"},
                  "https://werkenbij.portofrotterdam.com/job/Rotterdam-Product-Owner-Data-Platforms-ZH-3072-AP/1367862157/")
    assert raw.location == "Rotterdam, Netherlands"



@respx.mock
def test_time_budget_keeps_unvisited_known_postings_open():
    robots.reset()
    respx.get("https://slow.example/robots.txt").mock(return_value=httpx.Response(404))
    urls = [f"https://slow.example/jobs/{i}" for i in range(5)]
    respx.get("https://slow.example/jobs/sitemap.xml").mock(return_value=httpx.Response(
        200, text="<urlset>" + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>",
        headers={"content-type": "application/xml"}))
    adapter = JsonLdAdapter(httpx.Client())
    adapter.TIME_BUDGET_SECONDS = -1  # already out of time
    adapter.REFRESH_EVERY = 1  # every known page is due for a refresh, so none are skipped up front
    adapter.known_urls = {_url_key(u): str(i) for i, u in enumerate(urls)}
    raws = adapter.fetch("https://slow.example/jobs/sitemap.xml")
    assert raws == [] and adapter.truncated and adapter.still_listed == {"0", "1", "2", "3", "4"}
    robots.reset()


def test_address_fields_given_as_lists_are_read():
    from radar.adapters.jsonld import _to_raw

    raw = _to_raw({"@type": "JobPosting", "title": "ICT-medewerker", "jobLocation": {"address": {
        "addressLocality": ["Rotterdam"], "addressRegion": ["Zuid-Holland"], "addressCountry": "NL"}}},
        "https://werkenbij.example.nl/vacature/1")
    assert raw.city == "Rotterdam" and raw.country == "NL" and "Zuid-Holland" in raw.location


def test_job_location_given_as_plain_strings():
    from radar.adapters.jsonld import _to_raw

    raw = _to_raw({"@type": "JobPosting", "title": "Applicatiebeheerder", "jobLocation": ["Amersfoort"]},
                  "https://www.werkenvoor.example.nl/vacatures/1")
    assert raw.location == "Amersfoort"



@respx.mock
def test_sitemap_skips_application_form_pages():
    respx.get("https://avy.example/sitemap.xml").mock(return_value=httpx.Response(200, headers={"content-type": "application/xml"},
        text="<urlset><url><loc>https://avy.example/drone-engineer</loc></url>"
             "<url><loc>https://avy.example/drone-engineer/en/apply</loc></url>"
             "<url><loc>https://avy.example/vacature/data-analist/solliciteren</loc></url></urlset>"))
    urls = JsonLdAdapter(httpx.Client())._sitemap_urls("https://avy.example/sitemap.xml")
    assert urls == ["https://avy.example/drone-engineer"]


def test_homerun_boards_become_sitemap_sources(fresh_db):
    from radar.discovery import register_discovery

    with session_scope() as s:
        added = register_discovery(s, "Avy", {"candidates": [("homerun", "avy")], "careers_url": None, "jsonld": False})
        src = s.query(Source).one()
        assert added == 1 and src.ats == "jsonld" and src.slug == "https://avy.homerun.co/sitemap.xml" and src.active


@respx.mock
def test_page_text_is_used_when_the_structured_data_has_no_description():
    robots.reset()
    respx.get("https://site.example/robots.txt").mock(return_value=httpx.Response(404))
    page = ('<html><body><nav>Home Jobs Contact</nav><main><h1>PCB Lay-Out Engineer</h1>'
            '<p>You design printed circuit boards for radar systems in Altium.</p>'
            '<script type="application/ld+json">{"@type":"JobPosting","title":"PCB Lay-Out Engineer",'
            '"jobLocation":{"address":{"addressLocality":"Hengelo","addressCountry":"NL"}}}</script>'
            '</main><footer>Cookie settings</footer></body></html>')
    respx.get("https://site.example/vacatures/pcb-engineer").mock(
        return_value=httpx.Response(200, text=page, headers={"content-type": "text/html"}))
    (raw,) = JsonLdAdapter(httpx.Client()).fetch("https://site.example/vacatures/pcb-engineer")
    assert "printed circuit boards" in raw.description_text
    assert "Home Jobs Contact" not in raw.description_text and "Cookie settings" not in raw.description_text
    robots.reset()


def test_a_response_without_text_keeps_the_stored_description(fresh_db):
    from radar.adapters.base import RawPosting

    full = "You build data services in Python and SQL with a small team in Utrecht. " * 6
    with session_scope() as s:
        src = Source(company="Ex", ats="smartrecruiters", slug="ex", url="https://ex", active=True)
        s.add(src)
        s.flush()
        raw = dict(external_id="1", title="Data Engineer", url="https://ex/1", location="Utrecht, Netherlands",
                   country="NL")
        ingest(s, src, [RawPosting(**raw, description_text=full)])
        ingest(s, src, [RawPosting(**raw, description_html=None)])  # the detail request failed this time
        assert s.query(Posting).one().description.startswith("You build data services")


@respx.mock
def test_smartrecruiters_skips_details_it_already_has():
    from radar.adapters.smartrecruiters import SmartRecruitersAdapter

    base = "https://api.smartrecruiters.com/v1/companies/ex/postings"
    respx.get(base).mock(return_value=httpx.Response(200, json={"totalFound": 2, "content": [
        {"id": "1", "name": "Data Engineer", "location": {"city": "Utrecht", "country": "nl"}},
        {"id": "2", "name": "ML Engineer", "location": {"city": "Delft", "country": "nl"}}]}))
    known = respx.get(f"{base}/1").mock(return_value=httpx.Response(200, json={}))
    new = respx.get(f"{base}/2").mock(return_value=httpx.Response(200, json={"jobAd": {"sections": {
        "jobDescription": {"title": "Role", "text": "<p>You train models in PyTorch.</p>"}}}}))
    adapter = SmartRecruitersAdapter(httpx.Client())
    adapter.known_urls = {"1": "1"}
    adapter.REFRESH_EVERY = 10**9  # no refresh due in this test
    raws = adapter.fetch("ex")
    assert [r.external_id for r in raws] == ["2"] and adapter.still_listed == {"1"}
    assert not known.called and new.called
