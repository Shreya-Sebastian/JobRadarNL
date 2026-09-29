"""Find a career sitemap whose job pages carry schema.org JobPosting data.

Many large Dutch employers (TNO, ING, Politie, Unilever) run their own career site instead of a public
applicant-tracking board, but publish JobPosting structured data because Google for Jobs requires it. This
module does automatically what was first done by hand for TNO:

1. collect sitemaps from robots.txt and the usual places on the domain and its careers hosts
   (werkenbij.<domain>, careers.<domain>, jobs.<domain>, werkenbij<name>.nl);
2. follow sitemap indexes one level down, preferring children whose URL mentions jobs;
3. keep URLs that look like job detail pages (a job word in the path plus an id or a long slug);
4. fetch up to three of them and require JobPosting data on at least one.

The winning sitemap is registered as a `jsonld` source. robots.txt is honoured throughout.
"""

from __future__ import annotations

import html
import logging
import re
from urllib.parse import urlparse

import httpx

from radar import robots
from radar.config import settings

log = logging.getLogger(__name__)

_JOB_WORD = re.compile(r"/(?:jobs?|vacatures?|vacancies|vacancy|vacature|careers?/[a-z-]*jobs?|job-?offers?|"
                       r"werken-bij[^/]*/vacatures?|carriere/vacatures?|positions?|openings?)/", re.I)
_DETAIL = re.compile(r"(?:\d{3,}|[a-z0-9]+(?:[-_]+[a-z0-9]+){2,})(?:\.html?|\.aspx?)?/?(?:\?.*)?$", re.I)
_LISTING_TAIL = re.compile(r"/(?:jobs?|vacatures?|vacancies|search|zoeken|alle-vacatures|overview)/?$", re.I)
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


def _client() -> httpx.Client:
    return httpx.Client(timeout=min(settings.http_timeout, 20), follow_redirects=True,
                        headers={"User-Agent": settings.user_agent, "Accept": "text/html,application/xml,*/*;q=0.8"})


def candidate_hosts(domain: str) -> list[str]:
    d = re.sub(r"^https?://", "", domain).strip("/").lower()
    d = d[4:] if d.startswith("www.") else d
    name = d.split(".")[0]
    hosts = [f"www.{d}", d, f"werkenbij.{d}", f"careers.{d}", f"jobs.{d}", f"werkenbij{name}.nl",
             f"www.werkenbij{name}.nl", f"werkenbij-{name}.nl"]
    seen: list[str] = []
    for h in hosts:
        if h not in seen:
            seen.append(h)
    return seen


def careers_hosts(domain: str, client: httpx.Client) -> list[str]:
    """Hosts the homepage's careers / werken-bij links point to (kombijde.politie.nl, jobs.tno.nl, ...)."""
    from radar.discovery import find_careers_links

    d = re.sub(r"^https?://", "", domain).strip("/")
    for url in (f"https://www.{d}" if not d.startswith("www.") else f"https://{d}", f"https://{d}"):
        try:
            r = client.get(url)
        except Exception:
            continue
        if r.status_code >= 400:
            continue
        hosts: list[str] = []
        for link in find_careers_links(r.text, str(r.url)):
            h = urlparse(link).netloc.lower()
            if h and h not in hosts:
                hosts.append(h)
        return hosts[:4]
    return []


def _locs(client: httpx.Client, url: str) -> list[str]:
    try:
        if not robots.allowed(url, client):
            return []
        r = client.get(url)
    except Exception:
        return []
    if r.status_code >= 400 or "<loc" not in r.text[:200000]:
        return []
    return [html.unescape(u) for u in _LOC.findall(r.text)]


# Boards on these platforms are read through their own adapters; a sitemap on them would only duplicate that.
_ATS_HOSTS = ("myworkdayjobs.com", "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "recruitee.com",
              "teamtailor.com", "personio.de", "personio.com", "smartrecruiters.com")


def _on_ats(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host == h or host.endswith("." + h) for h in _ATS_HOSTS)


def _is_detail(url: str) -> bool:
    path = urlparse(url).path
    return bool(_JOB_WORD.search(path + "/")) and bool(_DETAIL.search(path)) and not _LISTING_TAIL.search(path)


def _has_jobposting(client: httpx.Client, url: str) -> bool:
    try:
        if not robots.allowed(url, client):
            return False
        r = client.get(url)
    except Exception:
        return False
    return r.status_code == 200 and ("JobPosting" in r.text)


def find_job_sitemap(domain: str, client: httpx.Client | None = None, max_sitemaps: int = 12) -> dict | None:
    """{'sitemap': url, 'jobs': n job-detail URLs, 'sample': url} for the best sitemap, or None."""
    own = client is None
    client = client or _client()
    try:
        sitemaps: list[str] = []
        # the host the homepage's careers link points to is the best bet, so it goes first
        hosts = careers_hosts(domain, client)
        hosts += [h for h in candidate_hosts(domain) if h not in hosts]
        for host in hosts:
            try:
                r = client.get(f"https://{host}/robots.txt")
                listed = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", r.text) if r.status_code < 400 else []
            except Exception:
                continue  # host does not exist
            for sm in listed or [f"https://{host}/sitemap.xml", f"https://{host}/sitemap_index.xml"]:
                if sm not in sitemaps:
                    sitemaps.append(sm)
        best: dict | None = None
        checked = 0
        for sm in sitemaps:
            if checked >= max_sitemaps:
                break
            locs = _locs(client, sm)
            checked += 1
            if not locs:
                continue
            groups: list[tuple[str, list[str]]] = []
            if all(u.lower().split("?")[0].endswith(".xml") or "sitemap" in u.lower() for u in locs[:5]):
                children = sorted(locs, key=lambda u: 0 if re.search(r"job|vacat|vacan|career|werken", u, re.I) else 1)
                for ch in children[:8]:
                    groups.append((ch, _locs(client, ch)))
                    checked += 1
            else:
                groups.append((sm, locs))
            for url, entries in groups:
                if _on_ats(url):
                    continue
                details = [u for u in entries if _is_detail(u)]
                if len(details) < 3 or (best and len(details) <= best["jobs"]):
                    continue
                sample = next((u for u in details[:3] if _has_jobposting(client, u)), None)
                if sample:
                    best = {"sitemap": url, "jobs": len(details), "sample": sample}
        if best is None:
            best = _listing_page(client, hosts, sitemaps)
        return best
    finally:
        if own:
            client.close()


_LISTING_HINT = re.compile(r"/(?:en/|nl/)?(?:vacancies|vacatures|jobs|job-openings|openings|alle-vacatures|"
                           r"careers/vacancies|werken-bij/vacatures|carriere/vacatures)/?$", re.I)


def _listing_page(client: httpx.Client, hosts: list[str], sitemaps: list[str]) -> dict | None:
    """Fallback for sites whose sitemap lists only the vacancy overview: find that overview page, follow its job
    links, and require JobPosting data on one of them. The source is the overview URL; the JSON-LD adapter
    follows same-site job links from there."""
    from urllib.parse import urljoin

    pages: list[str] = []
    for sm in sitemaps[:6]:
        pages += [u for u in _locs(client, sm) if _LISTING_HINT.search(urlparse(u).path)]
    for h in hosts[:3]:
        pages += [f"https://{h}/vacatures", f"https://{h}/en/vacancies", f"https://{h}/vacancies", f"https://{h}/jobs"]
    seen: set[str] = set()
    for page in pages:
        if page in seen or len(seen) >= 8:
            continue
        seen.add(page)
        try:
            if not robots.allowed(page, client):
                continue
            r = client.get(page)
        except Exception:
            continue
        if r.status_code >= 400:
            continue
        host = urlparse(str(r.url)).netloc
        links = {urljoin(str(r.url), h).split("#")[0] for h in re.findall(r'href="([^"]+)"', r.text)}
        details = [u for u in links if urlparse(u).netloc == host and _is_detail(u)]
        if len(details) < 3:
            continue
        sample = next((u for u in sorted(details)[:3] if _has_jobposting(client, u)), None)
        if sample:
            return {"sitemap": str(r.url), "jobs": len(details), "sample": sample, "listing": True}
    return None
