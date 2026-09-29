import httpx
import respx

from radar import robots
from radar.sitemaps import _is_detail, find_job_sitemap

JOB = ('<html><script type="application/ld+json">{"@type":"JobPosting","title":"Engineer"}</script></html>')


def test_detail_url_heuristic():
    assert _is_detail("https://kombijde.politie.nl/vacature/bedrijfsarts-_1276051.html")
    assert _is_detail("https://www.werkenbijderdw.nl/vacatures/administratief-medewerker-arnhem-384796")
    assert _is_detail("https://jobs.example.nl/job/Utrecht-Data-Engineer/1360074055/")
    assert not _is_detail("https://careers.example.nl/en/vacancies")
    assert not _is_detail("https://www.example.nl/over-ons/nieuws/opening-nieuwe-vestiging")


@respx.mock
def test_finds_the_career_sitemap_on_the_homepage_careers_host():
    robots.reset()
    html = {"content-type": "text/html"}
    xml = {"content-type": "application/xml"}
    respx.get("https://www.acme.example/").mock(return_value=httpx.Response(
        200, text='<a href="https://werkenbij.acme.example/">Werken bij</a>', headers=html))
    respx.get("https://werkenbij.acme.example/robots.txt").mock(return_value=httpx.Response(
        200, text="User-agent: *\nSitemap: https://werkenbij.acme.example/sitemap.xml\n", headers={"content-type": "text/plain"}))
    jobs = [f"https://werkenbij.acme.example/vacatures/data-engineer-utrecht-{i}" for i in range(1000, 1005)]
    respx.get("https://werkenbij.acme.example/sitemap.xml").mock(return_value=httpx.Response(
        200, text="<urlset>" + "".join(f"<url><loc>{u}</loc></url>" for u in jobs + ["https://werkenbij.acme.example/over-ons"])
        + "</urlset>", headers=xml))
    for u in jobs:
        respx.get(u).mock(return_value=httpx.Response(200, text=JOB, headers=html))
    respx.route(host__regex=r".*").mock(return_value=httpx.Response(404))  # routes match in order: catch-all last
    res = find_job_sitemap("acme.example", httpx.Client())
    assert res["sitemap"] == "https://werkenbij.acme.example/sitemap.xml" and res["jobs"] == 5
    robots.reset()
