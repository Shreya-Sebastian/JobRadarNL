import httpx
import pytest
import respx

from radar.adapters import get_adapter
from radar.adapters.base import SourceNotFound
from radar.adapters.jsonld import JsonLdAdapter


@respx.mock
def test_greenhouse_parses_jobs():
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(200, json={"jobs": [{
            "id": 123, "title": "Backend Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
            "location": {"name": "Amsterdam, Netherlands"},
            "content": "&lt;p&gt;Python and &lt;b&gt;Kubernetes&lt;/b&gt;&lt;/p&gt;",
            "updated_at": "2026-09-20T10:00:00Z", "departments": [{"name": "Engineering"}]}]})
    )
    jobs = get_adapter("greenhouse").fetch("acme")
    assert len(jobs) == 1
    j = jobs[0]
    assert j.external_id == "123" and j.location == "Amsterdam, Netherlands"
    assert "Python and Kubernetes" in j.text()
    assert j.posted_at.year == 2026


@respx.mock
def test_greenhouse_404_is_source_not_found():
    respx.get("https://boards-api.greenhouse.io/v1/boards/nope/jobs").mock(return_value=httpx.Response(404))
    with pytest.raises(SourceNotFound):
        get_adapter("greenhouse").fetch("nope")


@respx.mock
def test_lever_parses_postings():
    respx.get("https://api.lever.co/v0/postings/acme").mock(
        return_value=httpx.Response(200, json=[{
            "id": "abc", "text": "Data Scientist", "hostedUrl": "https://jobs.lever.co/acme/abc",
            "categories": {"location": "Rotterdam", "team": "Data"}, "country": "NL",
            "descriptionPlain": "Build models.", "lists": [{"text": "Requirements", "content": "<li>Python</li>"}],
            "createdAt": 1700000000000, "workplaceType": "hybrid"}])
    )
    jobs = get_adapter("lever").fetch("acme")
    assert jobs[0].country == "NL" and jobs[0].title == "Data Scientist"
    assert "Python" in jobs[0].text() and "Build models" in jobs[0].text()


@respx.mock
def test_ashby_and_workable_and_recruitee():
    respx.get("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
        return_value=httpx.Response(200, json={"jobs": [{
            "id": "a1", "title": "Platform Engineer", "jobUrl": "https://jobs.ashbyhq.com/acme/a1",
            "location": "Utrecht", "secondaryLocations": [{"location": "Remote - Netherlands"}],
            "descriptionPlain": "Terraform and AWS", "publishedAt": "2026-09-01T00:00:00Z", "isRemote": False}]})
    )
    respx.get("https://apply.workable.com/api/v1/widget/accounts/acme").mock(
        return_value=httpx.Response(200, json={"jobs": [{
            "shortcode": "W1", "title": "QA Engineer", "url": "https://apply.workable.com/acme/j/W1",
            "country": "Netherlands", "city": "Eindhoven", "state": "Noord-Brabant", "telecommuting": "False",
            "locations": [{"country": "Netherlands", "countryCode": "NL", "city": "Eindhoven", "region": "Noord-Brabant"}],
            "description": "<p>Playwright</p>", "published_on": "2026-08-30"}]})
    )
    respx.get("https://acme.recruitee.com/api/offers/").mock(
        return_value=httpx.Response(200, json={"offers": [{
            "id": 9, "title": "Frontend Developer", "careers_url": "https://acme.recruitee.com/o/frontend",
            "location": "Groningen, Netherlands", "city": "Groningen", "country_code": "nl",
            "description": "<p>React</p>", "requirements": "<p>TypeScript</p>", "published_at": "2026-09-10",
            "status": "published"}]})
    )
    a = get_adapter("ashby").fetch("acme")[0]
    assert a.location == "Utrecht; Remote - Netherlands"
    w = get_adapter("workable").fetch("acme")[0]
    assert w.city == "Eindhoven" and w.country == "NL"
    r = get_adapter("recruitee").fetch("acme")[0]
    assert r.country == "NL" and "TypeScript" in r.text()


@respx.mock
def test_teamtailor_and_personio():
    respx.get("https://acme.teamtailor.com/jobs.json").mock(
        return_value=httpx.Response(200, json={"items": [{
            "id": "t1", "title": "Data Engineer", "url": "https://acme.teamtailor.com/jobs/1-data-engineer",
            "date_published": "2026-09-01T10:00:00+02:00", "content_html": "<p>Airflow and dbt</p>",
            "_jobposting": {"@type": "JobPosting", "title": "Data Engineer", "description": "<p>Airflow and dbt</p>",
                            "jobLocation": {"@type": "Place", "address": {"addressLocality": "Amsterdam",
                                                                          "addressCountry": "NL"}}}}]})
    )
    respx.get("https://acme.jobs.personio.de/xml").mock(
        return_value=httpx.Response(200, content=b"""<?xml version="1.0"?><workzag-jobs><position>
            <id>77</id><office>Eindhoven</office><name>Embedded Engineer</name>
            <jobDescriptions><jobDescription><name>Role</name><value><![CDATA[<p>C++ and RTOS</p>]]></value>
            </jobDescription></jobDescriptions><createdAt>2026-09-03T08:05:01+00:00</createdAt>
            <yearsOfExperience>2-5</yearsOfExperience></position></workzag-jobs>""")
    )
    t = get_adapter("teamtailor").fetch("acme")[0]
    assert t.external_id == "t1" and t.city == "Amsterdam" and t.country == "NL" and "dbt" in t.text()
    p = get_adapter("personio").fetch("acme")[0]
    assert p.external_id == "77" and p.location == "Eindhoven" and "C++ and RTOS" in p.text()
    assert p.posted_at.year == 2026 and p.raw["years"] == "2-5"


@respx.mock
def test_workday_filters_by_country_facet_and_fetches_details():
    api = "https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/careers"
    first = {"total": 2, "jobPostings": [
        {"title": "US job", "externalPath": "/job/US/us_1", "locationsText": "USA", "bulletFields": ["R1"]},
        {"title": "Software Engineer", "externalPath": "/job/Nijmegen/se_2", "locationsText": "Nijmegen",
         "bulletFields": ["R2"]}],
        "facets": [{"facetParameter": "Location_Country", "values": [
            {"descriptor": "United States of America", "id": "us"}, {"descriptor": "Netherlands", "id": "nl"}]}]}
    nl_page = {"total": 1, "jobPostings": [first["jobPostings"][1]], "facets": []}
    route = respx.post(f"{api}/jobs")
    route.side_effect = [httpx.Response(200, json=first), httpx.Response(200, json=nl_page)]
    respx.get(f"{api}/job/Nijmegen/se_2").mock(return_value=httpx.Response(200, json={"jobPostingInfo": {
        "jobDescription": "<p>C++ and Python</p>", "startDate": "2026-09-20",
        "country": {"descriptor": "Netherlands"}}}))
    jobs = get_adapter("workday").fetch("acme.wd3/careers")
    assert len(jobs) == 1 and jobs[0].external_id == "R2" and jobs[0].country == "NL"
    assert "C++ and Python" in jobs[0].text()
    assert jobs[0].url == "https://acme.wd3.myworkdayjobs.com/careers/job/Nijmegen/se_2"
    body = route.calls[1].request.content
    assert b'"Location_Country": ["nl"]' in body or b'"Location_Country":["nl"]' in body
    first["facets"][0]["values"][1]["count"] = 7
    route.side_effect = [httpx.Response(200, json=first)]
    assert get_adapter("workday").count_nl("acme.wd3/careers") == (7, 2)
    # Philips-style nested facets: locationMainGroup -> Country/Region -> Netherlands
    nested = {"total": 861, "jobPostings": [], "facets": [{"facetParameter": "locationMainGroup", "values": [
        {"descriptor": "Country/Region", "facetParameter": "locationHierarchy1",
         "values": [{"descriptor": "Netherlands", "id": "nl-id", "count": 53}]},
        {"descriptor": "City", "facetParameter": "locations",
         "values": [{"descriptor": "Netherlands - Remote Based", "id": "city-id", "count": 1}]}]}]}
    route.side_effect = [httpx.Response(200, json=nested)]
    assert get_adapter("workday").count_nl("acme.wd3/careers") == (53, 861)


@respx.mock
def test_smartrecruiters_pages_and_fetches_nl_details_only():
    base = "https://api.smartrecruiters.com/v1/companies/Acme/postings"
    respx.get(base).mock(return_value=httpx.Response(200, json={"totalFound": 2, "content": [
        {"id": "1", "name": "Data Engineer", "releasedDate": "2026-09-01T00:00:00.000Z",
         "location": {"city": "Amsterdam", "country": "nl"}, "ref": f"{base}/1"},
        {"id": "2", "name": "Data Engineer", "releasedDate": "2026-09-01T00:00:00.000Z",
         "location": {"city": "Berlin", "country": "de"}, "ref": f"{base}/2"}]}))
    respx.get(f"{base}/1").mock(return_value=httpx.Response(200, json={"jobAd": {"sections": {
        "jobDescription": {"title": "Job", "text": "<p>Spark and Airflow</p>"}}}}))
    jobs = get_adapter("smartrecruiters").fetch("Acme")
    assert len(jobs) == 2
    nl = [j for j in jobs if j.country == "NL"][0]
    assert "Spark and Airflow" in nl.text() and nl.url == "https://jobs.smartrecruiters.com/Acme/1"
    assert all(not str(c.request.url).endswith("/postings/2") for c in respx.calls)  # no detail fetch for Berlin


@respx.mock
def test_jsonld_adapter_reads_successfactors_microdata_and_prefilters_big_sitemaps():
    urls = [f"https://acme.com/job/Pune-Engineer-{i}/{i}/" for i in range(3000)] + \
           ["https://acme.com/job/Utrecht-Data-Engineer/99/"]
    sitemap = "<urlset>" + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>"
    page = """<html><body><div itemscope itemtype="http://schema.org/JobPosting">
      <h1 itemprop="title">Data Engineer</h1>
      <span itemprop="datePosted" content="2026-09-10">Sep 10</span>
      <div itemprop="hiringOrganization" itemscope itemtype="http://schema.org/Organization">
        <span itemprop="name">Acme Consulting</span></div>
      <div itemprop="jobLocation" itemscope itemtype="http://schema.org/Place">
        <div itemprop="address" itemscope itemtype="http://schema.org/PostalAddress">
          <span itemprop="streetAddress">Utrecht, NL</span></div></div>
      <div itemprop="description"><p>Spark and Airflow</p></div></div></body></html>"""
    respx.get("https://acme.com/sitemap.xml").mock(return_value=httpx.Response(200, text=sitemap,
                                                                                 headers={"content-type": "application/xml"}))
    respx.get("https://acme.com/job/Utrecht-Data-Engineer/99/").mock(
        return_value=httpx.Response(200, text=page, headers={"content-type": "text/html"}))
    jobs = JsonLdAdapter().fetch("https://acme.com/sitemap.xml")
    assert len(jobs) == 1                      # 3000 Pune pages were never requested
    assert len(respx.calls) == 2
    j = jobs[0]
    from radar.normalize import normalize

    n = normalize(j, "Acme")
    assert j.title == "Data Engineer" and n["city"] == "Utrecht" and n["country"] == "NL"
    assert j.company == "Acme Consulting" and "Spark and Airflow" in j.text() and j.posted_at.day == 10


@respx.mock
def test_jsonld_adapter_reads_jobposting_and_follows_links():
    listing = """<html><body><a href="/jobs/1">Engineer</a><a href="/about">About</a></body></html>"""
    job = """<html><head><script type="application/ld+json">{"@context":"https://schema.org",
      "@type":"JobPosting","title":"Embedded Software Engineer","datePosted":"2026-09-05",
      "description":"<p>C++ and RTOS</p>","url":"https://acme.nl/jobs/1",
      "hiringOrganization":{"@type":"Organization","name":"Acme"},
      "jobLocation":{"@type":"Place","address":{"addressLocality":"Delft","addressCountry":"NL"}}}
      </script></head><body>job</body></html>"""
    respx.get("https://acme.nl/careers").mock(return_value=httpx.Response(200, text=listing,
                                                                          headers={"content-type": "text/html"}))
    respx.get("https://acme.nl/jobs/1").mock(return_value=httpx.Response(200, text=job,
                                                                         headers={"content-type": "text/html"}))
    jobs = JsonLdAdapter().fetch("https://acme.nl/careers")
    assert len(jobs) == 1
    assert jobs[0].city == "Delft" and jobs[0].country == "NL"
    assert "C++ and RTOS" in jobs[0].text()
    assert all("/about" not in str(c.request.url) for c in respx.calls)


@respx.mock
def test_amazon_pages_by_country_and_maps_fields():
    from radar.adapters.amazon import AmazonAdapter

    route = respx.get("https://www.amazon.jobs/en/search.json").mock(side_effect=lambda req: httpx.Response(200, json={
        "hits": 2, "jobs": [] if "offset=100" in str(req.url) else [
            {"id_icims": "10561022", "title": "Software Development Engineer", "city": "Den Haag", "country_code": "NLD",
             "location": "NL, Den Haag", "job_path": "/en/jobs/10561022/sde", "posted_date": "September 27, 2026",
             "description": "<p>Build things.</p>", "basic_qualifications": "Java, AWS", "company_name": "Amazon Web Services EMEA SARL"},
            {"id_icims": "10561023", "title": "Area Manager", "city": "Rozenburg", "country_code": "NLD",
             "job_path": "/en/jobs/10561023/am", "posted_date": "2026-09-20", "description": "Run a site."},
        ]}))
    posts = AmazonAdapter(httpx.Client()).fetch("NLD")
    assert route.called and "country=NLD" in str(route.calls[0].request.url)
    assert [p.external_id for p in posts] == ["10561022", "10561023"]
    p = posts[0]
    assert p.url == "https://www.amazon.jobs/en/jobs/10561022/sde" and p.city == "Den Haag" and p.country == "NL"
    assert p.posted_at.year == 2026 and "Java, AWS" in p.text() and p.raw["company_name"].startswith("Amazon Web")



def test_workday_location_facet_fallback_selects_dutch_sites():
    from radar.adapters.workday import _find_nl_locations

    facets = [{"facetParameter": "jobFamilyGroup", "values": [{"id": "x", "descriptor": "Engineering"}]},
              {"facetParameter": "locationMainGroup", "values": [
                  {"facetParameter": "locations", "descriptor": "Locations", "values": [
                      {"id": "v1", "descriptor": "Veldhoven"}, {"id": "s1", "descriptor": "Shanghai, China"},
                      {"id": "d1", "descriptor": "Delft"}, {"id": "w1", "descriptor": "Wilton, CT"}]}]}]
    assert _find_nl_locations(facets) == ("locations", ["v1", "d1"])
