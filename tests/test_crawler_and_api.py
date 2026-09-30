from datetime import datetime

from fastapi.testclient import TestClient

from radar.adapters.base import RawPosting
from radar.crawler import ingest, mark_duplicates
from radar.db import session_scope
from radar.models import Posting, Source


def _raw(ext, title, loc="Amsterdam, Netherlands", desc="Python, AWS and Docker. 3 years experience."):
    return RawPosting(external_id=ext, title=title, url=f"https://x/{ext}", location=loc, description_text=desc)


def _source(session, company="Acme", ats="greenhouse", slug="acme"):
    s = Source(company=company, ats=ats, slug=slug)
    session.add(s)
    session.flush()
    return s


def test_ingest_lifecycle_new_update_close_reopen(fresh_db):
    with session_scope() as s:
        src = _source(s)
        c = ingest(s, src, [_raw("1", "Backend Engineer"), _raw("2", "Recruiter"), _raw("3", "Engineer", "Berlin")])
        assert c == {"new": 2, "updated": 0, "closed": 0, "seen": 2, "foreign": 1, "partial": False, "expired": 0}
        p1 = s.query(Posting).filter_by(external_id="1").one()
        assert p1.is_tech and p1.extraction["skills_required"] == ["Python", "AWS", "Docker"]
        assert not s.query(Posting).filter_by(external_id="2").one().is_tech
        assert s.query(Posting).filter_by(external_id="3").count() == 0  # Berlin filtered out

        c = ingest(s, src, [_raw("1", "Backend Engineer", desc="Now Rust and Kubernetes.")])
        assert c["updated"] == 1 and c["closed"] == 1
        p1 = s.query(Posting).filter_by(external_id="1").one()
        assert p1.extraction["skills_required"] == ["Rust", "Kubernetes"]
        assert s.query(Posting).filter_by(external_id="2").one().closed_at is not None

        c = ingest(s, src, [_raw("1", "Backend Engineer", desc="Now Rust and Kubernetes."), _raw("2", "Recruiter")])
        assert c["new"] == 0 and c["closed"] == 0
        assert s.query(Posting).filter_by(external_id="2").one().closed_at is None  # reopened


def test_duplicates_across_sources_prefer_ats(fresh_db):
    with session_scope() as s:
        ats = _source(s, "Acme", "greenhouse", "acme")
        generic = _source(s, "Acme", "jsonld", "https://acme.nl/careers")
        ingest(s, generic, [_raw("g1", "Data Engineer")])
        ingest(s, ats, [_raw("a1", "Data Engineer (m/f/d)")])
        assert mark_duplicates(s) == 1
        dup = s.query(Posting).filter_by(external_id="g1").one()
        canonical = s.query(Posting).filter_by(external_id="a1").one()
        assert dup.duplicate_of == canonical.id and canonical.duplicate_of is None


def test_duplicates_same_source_identical_text_and_same_url(fresh_db):
    with session_scope() as s:
        src = _source(s)
        def raw(ext, url, desc):
            return RawPosting(external_id=ext, title="Backend Engineer", url=url, location="Amsterdam, Netherlands",
                              description_text=desc)

        ingest(s, src, [
            raw("a", "https://x/backend-engineer", "Python and AWS."),
            raw("b", "https://x/backend-engineer-2", "Python and AWS."),      # repost counter: duplicate
            raw("c", "https://x/backend-engineer-3", "Rust and Kubernetes."),  # same title, other text: keep
            raw("d", "https://x/backend-engineer-hoorn", "Python and AWS."),   # same text, other slug: keep
            raw("e", "https://x/backend-engineer-4", "Python and AWS."),      # twin of a even though a != canonical
        ])
        other = _source(s, "Acme", "jsonld", "https://acme.nl/careers")
        ingest(s, other, [RawPosting(external_id="z", title="Rust Person", url="https://x/backend-engineer-3?utm=1",
                                     location="Amsterdam", description_text="whatever")])  # same URL as c
        assert mark_duplicates(s) == 3
        by = lambda ext: s.query(Posting).filter_by(external_id=ext).one()  # noqa: E731
        assert by("b").duplicate_of == by("a").id and by("e").duplicate_of == by("a").id
        assert by("c").duplicate_of is None and by("d").duplicate_of is None
        assert by("z").duplicate_of == by("c").id


def test_source_kinds_label_and_deactivate_aggregators(fresh_db):
    from radar.registry import apply_source_kinds, classify_source, upsert_source

    assert classify_source("Jobgether", "jobgether") == "aggregator"
    assert classify_source("Friday Recruitment", "fridayrecruitment") == "agency"
    assert classify_source("Adyen", "adyen") == "employer"
    with session_scope() as s:
        agg, _ = upsert_source(s, "Jobgether", "lever", "jobgether")
        assert agg.active is False and agg.kind == "aggregator"
        emp = _source(s, "Acme")
        emp2 = Source(company="Acme", ats="lever", slug="copycat", active=True)  # same employer, other board
        s.add(emp2)
        s.flush()
        ingest(s, emp, [_raw("1", "Backend Engineer")])
        emp2.kind = "aggregator"
        emp2.active = True
        ingest(s, emp2, [_raw("9", "Backend Engineer")])
        counts = apply_source_kinds(s)
        assert counts["postings_closed"] == 0  # copycat is not in the yaml, so its kind is reset to employer
        emp2.kind = "aggregator"
        assert mark_duplicates(s) == 1
        assert s.query(Posting).filter_by(external_id="9").one().duplicate_of is not None  # employer copy wins


def test_api_endpoints(fresh_db):
    with session_scope() as s:
        src = _source(s)
        ingest(s, src, [
            _raw("1", "Senior Backend Engineer", desc="Python, AWS, Docker and Kubernetes. Visa sponsorship offered."),
            _raw("2", "Junior Data Scientist", "Utrecht",
                 "Je werkt met Python en SQL aan onze data. Je spreekt vloeiend Nederlands en werkt in een team in Utrecht."),
            _raw("3", "Office Manager"),
        ])
    from radar.api import app

    client = TestClient(app)
    assert client.get("/healthz").json() == {"ok": True}
    home = client.get("/").text
    assert "{{" not in home and "<h1>Tech Jobs Radar</h1>" in home and "TechJobsNL" in home
    assert '"@type": "WebSite"' in home
    assert "Sitemap:" in client.get("/robots.txt").text and "<urlset" in client.get("/sitemap.xml").text
    ov = client.get("/api/overview").json()
    assert ov["live_tech_postings"] == 2 and ov["live_postings"] == 3
    sk = client.get("/api/skills").json()
    assert sk["n"] == 2 and sk["skills"][0]["skill"] == "Python" and sk["skills"][0]["count"] == 2
    assert client.get("/api/skills", params={"english_only": "true"}).json()["n"] == 1
    assert client.get("/api/skills", params={"language": "en"}).json()["n"] == 1
    assert client.get("/api/skills", params={"language": "nl"}).json()["n"] == 1   # the Dutch-required one
    assert client.get("/api/skills", params={"language": "any"}).json()["n"] == 2
    assert client.get("/api/skills", params={"sponsorship": "true"}).json()["n"] == 1
    # experience bands: neither posting states years; the junior one is entry level ("none"), the senior one is
    # "unspecified" and must never appear under "none"
    assert client.get("/api/skills", params={"experience": "none"}).json()["n"] == 1
    assert client.get("/api/postings", params={"experience": "none"}).json()["items"][0]["title"] == "Junior Data Scientist"
    assert client.get("/api/skills", params={"experience": "unspecified"}).json()["n"] == 1
    assert client.get("/api/skills", params={"experience": "none,unspecified"}).json()["n"] == 2
    assert client.get("/api/skills", params={"experience": "2-3"}).json()["n"] == 0
    bd = {i["key"]: i["count"] for i in client.get("/api/breakdown/experience").json()["items"]}
    assert bd == {"none": 1, "unspecified": 1}
    assert client.get("/api/breakdown/city").json()["items"][0]["key"] in {"Amsterdam", "Utrecht"}
    assert client.get("/api/breakdown/bogus").status_code == 400
    posts = client.get("/api/postings", params={"seniority": "junior"}).json()
    assert posts["total"] == 1 and posts["items"][0]["title"] == "Junior Data Scientist"
    assert posts["items"][0]["age_days"] == 0
    assert client.get("/api/sources").json()["sources"][0]["kind"] == "employer"
    co = client.get("/api/cooccurrence", params={"top": 10}).json()
    assert any(n["id"] == "Python" for n in co["nodes"])
    gap = client.post("/api/gap", json={"cv_text": "I know Python and pandas, plus some SQL."}).json()
    assert "Python" in gap["cv_skills"]
    assert gap["missing"][0]["skill"] in {"AWS", "Docker", "Kubernetes"}
    assert gap["matches"][0]["title"] == "Junior Data Scientist"
    assert client.get("/api/sources").json()["sources"][0]["slug"] == "acme"
    # multi-value and personalisation filters
    assert client.get("/api/postings", params={"seniority": "junior,senior"}).json()["total"] == 2
    assert client.get("/api/postings", params={"city": "utrecht,remote"}).json()["total"] == 1
    assert client.get("/api/postings", params={"exclude_companies": "acme"}).json()["total"] == 0
    assert client.get("/api/postings", params={"skills_any": "Kubernetes,Nope"}).json()["total"] == 1
    ranked = client.get("/api/postings", params={"sort": "match", "skills_have": "sql,python"}).json()["items"]
    assert ranked[0]["title"] == "Junior Data Scientist" and ranked[0]["matched"] == ["Python", "SQL"]
    assert client.get("/api/skills/canonical", params={"names": "LLM,ml,k8s,nope"}).json() == {
        "LLM": "LLMs", "ml": "Machine Learning", "k8s": "Kubernetes", "nope": None}
    gap = client.post("/api/gap", json={"skills": ["python", "ML"]}).json()
    assert gap["cv_skills"] == ["Machine Learning", "Python"]
    first_id = ranked[0]["id"]
    assert client.get("/api/postings", params={"ids": str(first_id)}).json()["total"] == 1
    cov = client.get("/api/coverage").json()
    assert "tracker" in cov and cov["summary"]["missing"] >= 1 and cov["sources_by_kind"]["employer"] == 1


def test_company_pages_and_sitemap(fresh_db):
    with session_scope() as s:
        src = _source(s, company="Acme Robotics B.V.", slug="acme-robotics")
        ingest(s, src, [_raw("1", "Senior Backend Engineer"), _raw("2", "Office Manager"),
                        _raw("3", "Data Engineer")])
        # one listing under another spelling of the same employer, one lone listing elsewhere
        ingest(s, _source(s, company="ACME Robotics", slug="acme-2"), [_raw("4", "Frontend Developer")])
        ingest(s, _source(s, company="Tiny Labs", slug="tiny"), [_raw("5", "Python Developer")])
    from radar.api import app
    from radar.pages import slugify

    assert slugify("Acme Robotics B.V.") == "acme-robotics-b-v"
    client = TestClient(app)
    page = client.get("/company/acme-robotics")  # norm_company drops the B.V. suffix
    assert page.status_code == 200
    assert "Senior Backend Engineer" in page.text and "Office Manager" not in page.text  # tech only
    assert "Frontend Developer" in page.text  # both spellings on one page
    assert 'rel="canonical" href="https://techjobsradar.nl/company/acme-robotics"' in page.text
    assert '"@type": "CollectionPage"' in page.text and "{{" not in page.text and "noindex" not in page.text
    assert 'content="noindex, follow"' in client.get("/company/tiny-labs").text  # one listing: thin page
    assert client.get("/company/nobody").status_code == 404
    idx = client.get("/companies").text
    assert "Acme Robotics" in idx and idx.count('href="/company/acme-robotics"') == 1
    sm = client.get("/sitemap.xml").text
    assert "/companies</loc>" in sm and sm.count("/company/acme-robotics</loc>") == 1
    assert "/company/tiny-labs</loc>" not in sm and "<lastmod>20" in sm and "changefreq" not in sm
    robots = client.get("/robots.txt").text
    assert "Disallow: /api/\n" not in robots and "Disallow: /api/me" in robots and "Disallow: /auth/" in robots
    assert client.get("/api/overview").headers["x-robots-tag"] == "noindex"


def test_experience_band_never_leaks_experienced_roles_into_none():
    from radar.stats import experience_band

    assert experience_band({"years_experience": None, "seniority": "senior"}, "Senior Engineer") == "unspecified"
    assert experience_band({"years_experience": None, "seniority": "unknown"}, "Graduate Software Engineer") == "none"
    assert experience_band({"years_experience": None, "seniority": "junior"}, "Data Analyst") == "none"
    assert experience_band({"years_experience": 1, "seniority": "junior"}, "Junior Developer") == "1"
    assert experience_band({"years_experience": 5, "seniority": "medior"}, "Developer") == "4-5"
    assert experience_band({"years_experience": 8, "seniority": "senior"}, "Developer") == "6+"


def test_all_remote_policies_ticked_means_any(fresh_db):
    with session_scope() as s:
        src = _source(s)
        ingest(s, src, [_raw("1", "Backend Engineer", desc="Python. Hybrid working."),
                        _raw("2", "Data Engineer", desc="Python. No word about where you work.")])
    from radar.api import app

    client = TestClient(app)
    assert client.get("/api/skills", params={"remote": "hybrid"}).json()["n"] == 1
    assert client.get("/api/skills", params={"remote": "remote,hybrid,onsite"}).json()["n"] == 2


def test_enrollment_filter_keeps_internships_that_do_not_ask(fresh_db):
    with session_scope() as s:
        src = _source(s)
        ingest(s, src, [
            _raw("1", "Internship Software Engineering", desc="Python. You are currently enrolled at a Dutch university."),
            _raw("2", "Internship Data Engineering", desc="Python and SQL. Recent graduates are welcome."),
            _raw("3", "Stage Backend Development", desc="Python. Je werkt in Utrecht aan onze API."),
            _raw("4", "Senior Backend Engineer", desc="Python and Kubernetes. 6 years experience."),
        ])
    from radar.api import app

    client = TestClient(app)
    titles = lambda **kw: sorted(i["title"] for i in client.get("/api/postings", params=kw).json()["items"])  # noqa: E731
    assert titles(enrollment="open") == ["Internship Data Engineering", "Senior Backend Engineer", "Stage Backend Development"]
    assert titles(enrollment="required") == ["Internship Software Engineering"]
    assert titles(enrollment="stated_open") == ["Internship Data Engineering"]
    assert titles(enrollment="open", seniority="intern") == ["Internship Data Engineering", "Stage Backend Development"]
    item = next(i for i in client.get("/api/postings").json()["items"] if i["title"] == "Internship Software Engineering")
    assert item["enrollment_required"] is True


def test_dutch_and_english_copies_of_one_vacancy_are_shown_once(fresh_db):
    from radar.adapters.base import RawPosting
    from radar.crawler import mark_duplicates
    from radar.models import Posting

    def raw(ext, title, url, desc):
        return RawPosting(external_id=ext, title=title, location="Delft, Netherlands", url=url,
                          description_html=desc, posted_at=datetime(2026, 9, 14))
    with session_scope() as s:
        src = _source(s, company="TNO", ats="jsonld", slug="https://www.tno.example/en/sitemap.xml")
        ingest(s, src, [
            raw("en1", "Systems Engineer Defence", "https://www.tno.example/en/careers/vacancies/1/",
                "Python and C++. 40 hours, salary EUR 4.200 - 6.100, ref 2026-117."),
            raw("nl1", "Systems Engineer Defensie", "https://www.tno.example/nl/werken-bij/vacatures/1/",
                "Python en C++. 40 uur, salaris EUR 4.200 - 6.100, ref 2026-117."),
            raw("en2", "Quantum Scientist", "https://www.tno.example/en/careers/vacancies/2/",
                "Python and physics. 36 hours, salary EUR 3.900 - 5.800."),
        ])
        mark_duplicates(s)
        live = {p.title for p in s.query(Posting).filter(Posting.duplicate_of.is_(None))}
    assert live == {"Systems Engineer Defence", "Quantum Scientist"}


def test_changed_id_for_the_same_page_keeps_the_posting(fresh_db):
    from radar.models import Posting

    with session_scope() as s:
        src = _source(s)
        ingest(s, src, [_raw("TNO", "Systems Engineer")])
        first = s.query(Posting).one()
        first_id, first_seen, url = first.id, first.first_seen, first.url
        # next crawl: the site's identifier is gone, the adapter uses the page URL as id
        r = _raw("x", "Systems Engineer")
        r.external_id, r.url = url, url
        counters = ingest(s, src, [r])
        assert counters["new"] == 0 and counters["closed"] == 0
        p = s.query(Posting).one()
        assert p.id == first_id and p.external_id == url and p.first_seen == first_seen and p.closed_at is None


def test_dutch_only_option_excludes_postings_that_also_need_english(fresh_db):
    with session_scope() as s:
        src = _source(s)
        ingest(s, src, [
            _raw("1", "Data Engineer", desc="Python en SQL. Je spreekt vloeiend Nederlands. Wij werken in Utrecht."),
            _raw("2", "Cloud Engineer", desc="Python en AWS. Je spreekt vloeiend Nederlands en Engels."),
            _raw("3", "Backend Engineer", desc="Python, AWS and Docker. English is our working language."),
        ])
    from radar.api import app

    client = TestClient(app)
    titles = lambda **kw: sorted(i["title"] for i in client.get("/api/postings", params=kw).json()["items"])  # noqa: E731
    assert titles(language="nl") == ["Data Engineer"]
    assert titles(language="en") == ["Backend Engineer"]
    assert titles() == ["Backend Engineer", "Cloud Engineer", "Data Engineer"]


def test_organisation_size_filter_and_sort(fresh_db):
    with session_scope() as s:
        big = _source(s, company="Bigcorp", slug="bigcorp")
        ingest(s, big, [_raw(str(i), f"Backend Engineer {i}") for i in range(12)])
        small = _source(s, company="Tinyco", ats="lever", slug="tinyco")
        ingest(s, small, [_raw("t1", "Data Engineer")])
    from radar.api import app

    client = TestClient(app)
    assert client.get("/api/postings", params={"org_size": "small"}).json()["total"] == 1
    assert client.get("/api/postings", params={"org_size": "medium"}).json()["total"] == 12
    first = lambda sort: client.get("/api/postings", params={"sort": sort, "size": 1}).json()["items"][0]  # noqa: E731
    assert first("size_small")["company"] == "Tinyco" and first("size_small")["org_size"] == "small"
    assert first("size_large")["company"] == "Bigcorp" and first("size_large")["org_roles"] == 12


def test_search_landing_pages_bilingual_and_in_sitemap(fresh_db):
    with session_scope() as s:
        src = _source(s, company="Acme Robotics", slug="acme")
        ingest(s, src, [_raw(str(i), f"Data Engineer {i}", desc="Python, SQL and Spark. English is our working language.")
                        for i in range(10)])
    from radar.api import app

    client = TestClient(app)
    nl = client.get("/vacatures/ict-amsterdam")
    en = client.get("/jobs/tech-amsterdam")
    assert nl.status_code == 200 and en.status_code == 200
    assert "<title>ICT vacatures Amsterdam (10)" in nl.text and 'lang="nl"' in nl.text
    assert "<title>Tech jobs in Amsterdam (10)" in en.text and 'hreflang="nl" href="https://techjobsradar.nl/vacatures/ict-amsterdam"' in en.text
    assert "Data Engineer 0" in en.text and "{{" not in en.text
    assert client.get("/jobs/english-speaking").status_code == 200
    assert client.get("/jobs/tech-groningen").status_code == 404  # no postings there: no thin page
    home_nl = client.get("/nl/").text
    assert 'lang="nl"' in home_nl and "ICT en tech vacatures in Nederland" in home_nl and "/vacatures/ict-amsterdam" in home_nl
    sm = client.get("/sitemap.xml").text
    assert "/vacatures/ict-amsterdam</loc>" in sm and "/jobs/english-speaking</loc>" in sm and "/nl/</loc>" in sm


def test_unprefixed_english_pages_pair_with_nl_pages(fresh_db):
    from radar.adapters.base import RawPosting
    from radar.crawler import mark_duplicates
    from radar.models import Posting

    def raw(ext, url):
        return RawPosting(external_id=ext, title="Lead Engineer", location="Eindhoven, Netherlands", url=url,
                          description_html="Embedded C++ and Python. 40 hours, ref 137.",
                          posted_at=datetime(2026, 9, 20))
    with session_scope() as s:
        src = _source(s, company="Madison People", ats="jsonld", slug="https://madisonpeople.example/sitemap.xml")
        ingest(s, src, [raw("a", "https://madisonpeople.example/jobs/lead-engineer/"),
                        raw("b", "https://madisonpeople.example/nl/jobs/lead-engineer-137/")])
        mark_duplicates(s)
        assert s.query(Posting).filter(Posting.duplicate_of.is_(None)).count() == 1


def test_one_vacancy_listed_per_city_becomes_one_listing_with_its_cities(fresh_db):
    from radar.adapters.base import RawPosting
    from radar.crawler import mark_duplicates
    from radar.models import Posting

    text = ("Als DevOps Engineer in {city} bouw je CI/CD-pipelines met Kubernetes en Terraform voor onze klanten. "
            "Je werkt in een agile team met developers en beheerders.")

    def raw(ext, city, day=20):
        return RawPosting(external_id=ext, title="DevOps Engineer", location=f"{city}, Netherlands",
                          url=f"https://agency.example/jobs/devops-engineer-{ext}", posted_at=datetime(2026, 9, day),
                          description_html=text.format(city=city))
    with session_scope() as s:
        src = _source(s, company="Agency", ats="jsonld", slug="https://agency.example/sitemap.xml")
        ingest(s, src, [raw("1", "Zwolle"), raw("2", "Emmen"), raw("3", "Assen", 22),
                        raw("4", "Groningen", day=1)])  # the same ad posted again 19 days earlier: still one job
        mark_duplicates(s)
        shown = s.query(Posting).filter(Posting.duplicate_of.is_(None)).all()
        assert len(shown) == 1
        merged = shown[0]
        assert sorted([merged.city, *merged.also_in]) == ["Assen", "Emmen", "Groningen", "Zwolle"]

    from radar.api import app
    client = TestClient(app)
    hit = client.get("/api/postings", params={"city": "Emmen"}).json()["items"]
    assert len(hit) == 1 and "Emmen" in hit[0]["also_in"]  # found through one of its other cities


def test_language_copies_of_one_page_are_one_listing(fresh_db):
    from radar.adapters.base import RawPosting
    from radar.crawler import mark_duplicates
    from radar.models import Posting

    def raw(prefix, title):
        return RawPosting(external_id=prefix or "root", title=title, location="Rotterdam, Netherlands",
                          url=f"https://marlink.example{prefix}/job/339", posted_at=datetime(2026, 9, 29),
                          description_html=f"{title}: you run our network security products in Python and Go.")
    with session_scope() as s:
        src = _source(s, company="Marlink", ats="jsonld", slug="https://marlink.example/sitemap.xml")
        ingest(s, src, [raw("", "Head of Security Products"), raw("/fr", "Responsable produits sécurité"),
                        raw("/br", "Chefe de produtos"), raw("/en-gb", "Head of Security Products")])
        mark_duplicates(s)
        shown = s.query(Posting).filter(Posting.duplicate_of.is_(None)).all()
        assert len(shown) == 1 and shown[0].url.endswith("/en-gb/job/339")  # the English copy is kept


def test_security_guard_at_a_datacenter_is_not_a_tech_job():
    from radar.classify import is_tech

    assert not is_tech("Beveiliger datacenter", "")
    assert is_tech("Datacenter Engineer", "")


def test_dutch_employer_pages(fresh_db):
    with session_scope() as s:
        src = _source(s, company="Acme Robotics B.V.", slug="acme-robotics")
        ingest(s, src, [_raw("1", "Senior Backend Engineer"), _raw("3", "Data Engineer")])
    from radar.api import app

    client = TestClient(app)
    nl = client.get("/nl/bedrijf/acme-robotics")
    assert nl.status_code == 200 and '<html lang="nl">' in nl.text and "techvacatures in Nederland" in nl.text
    assert 'rel="canonical" href="https://techjobsradar.nl/nl/bedrijf/acme-robotics"' in nl.text
    assert 'hreflang="en" href="https://techjobsradar.nl/company/acme-robotics"' in nl.text
    en = client.get("/company/acme-robotics").text
    assert 'hreflang="nl" href="https://techjobsradar.nl/nl/bedrijf/acme-robotics"' in en and "{{" not in en
    assert "/nl/bedrijf/acme-robotics</loc>" in client.get("/sitemap.xml").text



def test_same_vacancy_under_two_paths_is_one_listing_but_different_titles_stay(fresh_db):
    from radar.adapters.base import RawPosting
    from radar.crawler import mark_duplicates
    from radar.models import Posting

    text = "Je bouwt met ons team aan de frontend van onze applicaties in React en TypeScript, in een agile team."
    boiler = "Nijwald is een detacheerder in Twente met mooie klanten in de maakindustrie en de hightech sector."

    def raw(ext, title, url, desc):
        return RawPosting(external_id=ext, title=title, location="Zwolle, Netherlands", url=url,
                          description_html=desc, posted_at=datetime(2026, 9, 25))
    with session_scope() as s:
        src = _source(s, company="Politie", ats="jsonld", slug="https://kombijde.example/sitemap.xml")
        ingest(s, src, [raw("a", "DevOps frontend developer", "https://kombijde.example/vacatures/devops-_1338704.html", text),
                        raw("b", "DevOps frontend developer", "https://kombijde.example/vacature/devops-_1338704.html", text)])
        agency = _source(s, company="Nijwald", ats="jsonld", slug="https://nijwald.example/sitemap.xml")
        ingest(s, agency, [raw("c", "Project Engineer", "https://nijwald.example/vacature/project-engineer/2484", boiler),
                           raw("d", "Sales Engineer", "https://nijwald.example/vacature/sales-engineer/2485", boiler)])
        mark_duplicates(s)
        shown = s.query(Posting).filter(Posting.duplicate_of.is_(None)).all()
        assert sorted(p.company for p in shown) == ["Nijwald", "Nijwald", "Politie"]


def test_a_posting_date_in_the_future_is_dropped():
    from radar.normalize import _plausible_posted

    assert _plausible_posted(datetime(2484, 9, 29)) is None
    assert _plausible_posted(datetime(2026, 9, 25)) == datetime(2026, 9, 25)


def test_city_in_the_title_does_not_split_one_vacancy(fresh_db):
    from radar.adapters.base import RawPosting
    from radar.crawler import mark_duplicates
    from radar.models import Posting

    text = "You build AI products with Python and PyTorch for our clients, in a small agile team of engineers."
    with session_scope() as s:
        src = _source(s, company="Linden IT", ats="jsonld", slug="https://linden.example/sitemap.xml")
        ingest(s, src, [RawPosting(external_id=c, title=f"Medior / Senior AI Engineer {c}", location=f"{c}, Netherlands",
                                   url=f"https://linden.example/vacatures/ai-engineer-{c.lower()}",
                                   description_html=text, posted_at=datetime(2026, 9, 10))
                        for c in ("Hilversum", "Amsterdam")])
        mark_duplicates(s)
        shown = s.query(Posting).filter(Posting.duplicate_of.is_(None)).all()
        assert len(shown) == 1 and len(shown[0].also_in) == 1
