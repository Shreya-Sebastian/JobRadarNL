"""Generic adapter: read schema.org JobPosting JSON-LD from any careers page.

Google Jobs requires career pages to embed JobPosting structured data, so most career sites
carry machine-readable postings regardless of ATS. The slug is a careers URL (a listing page
or a sitemap). We read JobPosting objects on that page, then follow same-site links that look
like job pages, up to a cap.
"""

from __future__ import annotations

import copy
import html
import json
import re
import time
import zlib
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from radar import robots
from radar.adapters.base import Adapter, AdapterError, RawPosting, parse_dt

_JOB_LINK = re.compile(r"(job|jobs|career|careers|vacature|vacatures|vacancy|vacancies|position|opening)", re.I)


_APPLY_PAGE = re.compile(r"/(?:[a-z]{2}/)?(?:apply|solliciteer|solliciteren|application(?:-form)?)/?(?:\?.*)?$", re.I)
_NL_URL_CACHE: re.Pattern | None = None


def _nl_url() -> re.Pattern:
    """Compiled lazily: normalize imports adapters, so importing it at module load would be circular."""
    global _NL_URL_CACHE
    if _NL_URL_CACHE is None:
        from radar.normalize import NL_CITIES

        parts = list(NL_CITIES.values()) + [r"netherlands", r"nederland", r"[-_/]nl[-_/]", r"[-_/]nl$"]
        _NL_URL_CACHE = re.compile("|".join(parts), re.I)
    return _NL_URL_CACHE


def _is_sitemap(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(".xml") or "sitemap" in path


def _url_key(url: str) -> str:
    u = urlparse(url)
    return f"{u.netloc.lower()}{u.path.rstrip('/')}"


class JsonLdAdapter(Adapter):
    """Incremental: the crawler may set `known_urls` (page URL key -> external id of a live posting). Pages that
    are still listed in the sitemap are then not fetched again; their ids are reported in `still_listed` so the
    crawler keeps them open. About one in twenty known pages is refetched each crawl, so content changes are
    still picked up within a few weeks without re-reading 1,700 pages every hour."""

    ats = "jsonld"
    MAX_PAGES = 150
    MAX_SITEMAP_PAGES = 4000
    NL_PREFILTER_ABOVE = 2500
    REFRESH_EVERY = 20
    TIME_BUDGET_SECONDS = 900  # one oversized site must not stall a whole crawl run

    def __init__(self, client=None):
        super().__init__(client)
        self.known_urls: dict[str, str] = {}
        self.still_listed: set[str] = set()
        self.skipped = 0
        self.truncated = False

    def _skip_known(self, url: str, salt: int) -> bool:
        ext = self.known_urls.get(_url_key(url))
        if ext is None:
            return False
        if (zlib.crc32(url.encode("utf-8")) + salt) % self.REFRESH_EVERY == 0:
            return False  # due for a refresh this time
        self.still_listed.add(ext)
        self.skipped += 1
        return True

    def fetch(self, slug: str) -> list[RawPosting]:
        start = slug
        seen: set[str] = set()
        queue: list[str] = [start]
        found_all: list[RawPosting] = []
        base_host = urlparse(start).netloc
        limit = self.MAX_PAGES
        self.still_listed = set()
        self.skipped = 0
        salt = datetime.utcnow().timetuple().tm_yday

        if _is_sitemap(start):
            # A job sitemap lists every posting page directly: read them all, no link following needed.
            limit = self.MAX_SITEMAP_PAGES
            urls = self._sitemap_urls(start)
            if len(urls) > self.NL_PREFILTER_ABOVE:
                # A global employer's sitemap (Capgemini lists ~10k jobs worldwide): only fetch pages whose URL
                # names a Dutch city or the country. Postings without a location in the URL are missed, which
                # is the price of not fetching ten thousand pages per crawl.
                urls = [u for u in urls if _nl_url().search(u)]
            queue = [u for u in urls if not self._skip_known(u, salt)][:limit]
            if not queue and self.still_listed:
                return []  # everything still listed, nothing new to read

        deadline = time.monotonic() + self.TIME_BUDGET_SECONDS
        self.truncated = False
        while queue and len(seen) < limit:
            if time.monotonic() > deadline:
                # Out of time: pages not reached are not evidence that a posting is gone, so keep them open.
                self.truncated = True
                for u in queue:
                    ext = self.known_urls.get(_url_key(u))
                    if ext:
                        self.still_listed.add(ext)
                break
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            if url != start and not _is_sitemap(start) and self._skip_known(url, salt):
                continue
            if not robots.allowed(url, self.client):
                continue
            try:
                resp = self.client.get(url)
            except Exception:
                continue
            if resp.status_code >= 400 or "html" not in resp.headers.get("content-type", ""):
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            found = False
            for obj in _jobpostings(soup):
                p = _to_raw(obj, url)
                if p and len(p.text()) < 300:
                    # the structured data has no description (Thales, many SuccessFactors sites) though the page
                    # shows the vacancy: read the page's own text so the posting is classified on more than its title
                    text = _page_text(soup)
                    if len(text) > len(p.text()):
                        p.description_text, p.description_html = text, None
                if p:
                    found_all.append(p)
                    found = True
            if found and url != start:
                continue
            for a in soup.find_all("a", href=True):
                href = urljoin(url, a["href"]).split("#")[0]
                if urlparse(href).netloc != base_host or href in seen:
                    continue
                if _JOB_LINK.search(href) and href not in queue:
                    queue.append(href)
        if not seen and not self.still_listed:
            raise AdapterError(f"could not read {start}")
        return _unique_ids(found_all)

    def probe(self, slug: str) -> bool:
        try:
            resp = self.client.get(slug)
        except Exception:
            return False
        return resp.status_code == 200 and "JobPosting" in resp.text

    def _sitemap_urls(self, url: str, depth: int = 0) -> list[str]:
        try:
            resp = self.client.get(url)
        except Exception:
            return []
        if resp.status_code >= 400:
            return []
        # sitemap URLs are XML-escaped (&amp; in query strings, Netflix's Eightfold sitemap for one)
        locs = [html.unescape(u) for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", resp.text)]
        if locs and depth < 1 and all(u.lower().endswith(".xml") or "sitemap" in u.lower() for u in locs):
            # sitemap index: descend into the job-related child sitemaps
            children = [u for u in locs if _JOB_LINK.search(u)] or locs[:5]
            out: list[str] = []
            for child in children[:10]:
                out.extend(self._sitemap_urls(child, depth + 1))
            return out
        # application forms repeat the job's data and would show up as a second copy of every posting
        locs = [u for u in locs if not _APPLY_PAGE.search(u)]
        return [u for u in locs if _JOB_LINK.search(u)] or locs


def _page_text(soup: BeautifulSoup, limit: int = 20000) -> str:
    """The visible text of a vacancy page's main content, without menus, headers, footers, forms and scripts."""
    root = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article") or soup.body
    if root is None:
        return ""
    root = copy.copy(root)  # the caller still reads links from the original page
    for el in root.find_all(["script", "style", "noscript", "nav", "header", "footer", "form", "aside", "svg",
                             "iframe", "button"]):
        el.decompose()
    for el in root.find_all(attrs={"class": re.compile(r"cookie|consent|breadcrumb|share|related", re.I)}):
        el.decompose()
    lines = [ln.strip() for ln in root.get_text("\n").splitlines()]
    return "\n".join(ln for ln in lines if ln)[:limit]


def _unique_ids(raws: list[RawPosting]) -> list[RawPosting]:
    """One posting per id. Some sites put the same `identifier` on every posting (TNO uses its own name), which
    would collapse all their vacancies into one; when an id is shared by different pages, use the URL instead."""
    urls_per_id: dict[str, set[str]] = {}
    for r in raws:
        urls_per_id.setdefault(r.external_id, set()).add(r.url)
    out: dict[str, RawPosting] = {}
    for r in raws:
        if len(urls_per_id[r.external_id]) > 1:
            r.external_id = r.url
        out[r.external_id] = r
    return list(out.values())


def _lenient_json(text: str) -> list[Any]:
    """Parse a JSON-LD block the way browsers and Google tolerate it. strict=False accepts raw line breaks inside
    strings (TNO); raw_decode reads object after object and skips stray commas between or after them
    (Defensie ends its object with "},"). A strict parser silently drops those postings."""
    decoder = json.JSONDecoder(strict=False)
    out: list[Any] = []
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n,;":
            i += 1
        if i >= n:
            break
        try:
            obj, end = decoder.raw_decode(text, i)
        except ValueError:
            break
        out.append(obj)
        i = end
    return out


def _jobpostings(soup: BeautifulSoup) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        for data in _lenient_json(script.string or script.get_text() or ""):
            out.extend(_walk(data))
    if not out:
        out.extend(_microdata_jobpostings(soup))
    return out


def _microdata_jobpostings(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """schema.org microdata (itemscope/itemprop), which SAP SuccessFactors career sites use instead of JSON-LD.
    Returns dicts shaped like JSON-LD JobPosting objects so the same conversion applies."""
    out: list[dict[str, Any]] = []
    for scope in soup.find_all(attrs={"itemtype": re.compile(r"schema\.org/JobPosting", re.I)}):
        obj: dict[str, Any] = {"@type": "JobPosting"}
        for el in scope.find_all(attrs={"itemprop": True}):
            # skip properties that belong to a nested scope other than this posting (handled below)
            prop = el["itemprop"]
            if prop in ("jobLocation", "hiringOrganization", "address", "baseSalary"):
                continue
            value = el.get("content") or el.get("datetime") or (el.get("href") if el.name == "a" else None)
            if value is None:
                value = el.decode_contents() if prop == "description" else el.get_text(" ", strip=True)
            if prop not in obj:
                obj[prop] = value
        loc = scope.find(attrs={"itemprop": "jobLocation"})
        if loc is not None:
            addr = {}
            for key in ("addressLocality", "addressRegion", "addressCountry", "streetAddress"):
                node = loc.find(attrs={"itemprop": key})
                if node is not None:
                    addr[key] = node.get("content") or node.get_text(" ", strip=True)
            obj["jobLocation"] = {"@type": "Place", "address": addr}
        org = scope.find(attrs={"itemprop": "hiringOrganization"})
        if org is not None:
            name = org.find(attrs={"itemprop": "name"})
            obj["hiringOrganization"] = {"name": (name.get("content") or name.get_text(" ", strip=True))
                                         if name is not None else org.get("content") or org.get_text(" ", strip=True)}
        if obj.get("title") or obj.get("name"):
            out.append(obj)
    return out


def _walk(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        t = node.get("@type")
        types = t if isinstance(t, list) else [t]
        if "JobPosting" in types:
            found.append(node)
        for v in node.values():
            if isinstance(v, (dict, list)):
                found.extend(_walk(v))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk(item))
    return found


def _text(value: Any) -> str | None:
    """Address fields are usually strings, but some sites send a list ("addressRegion": ["Brabant"]) or a
    {"name": ...} object; reduce all of them to one string."""
    if isinstance(value, list):
        value = next((v for v in value if v), None)
    if isinstance(value, dict):
        value = value.get("name") or value.get("@value")
    return str(value).strip() or None if value else None


def _job_url(value: Any, page_url: str) -> str:
    """The posting's own link. A relative, schemeless or homepage-only `url` in the data (iquality.nl sends
    "www.iquality.nl") would send people to the front page, so the page the posting was found on wins then."""
    if not isinstance(value, str) or not value.strip():
        return page_url
    u = value.strip()
    if u.startswith("//"):
        u = "https:" + u
    elif not u.startswith("http"):
        u = urljoin(page_url, u) if u.startswith("/") else page_url
    return page_url if urlparse(u).path.strip("/") == "" else u


def _place_from_url(url: str) -> str | None:
    from urllib.parse import unquote

    from radar.normalize import detect_city

    words = re.sub(r"[-_/.%]+", " ", unquote(urlparse(url).path))
    city = detect_city(words)
    return f"{city}, Netherlands" if city else None


def _to_raw(obj: dict[str, Any], page_url: str) -> RawPosting | None:
    title = obj.get("title") or obj.get("name")
    if not title:
        return None
    url = _job_url(obj.get("url"), page_url)
    ident = obj.get("identifier")
    if isinstance(ident, dict):
        ident = ident.get("value") or ident.get("name")
    external_id = str(ident or url)
    locs = obj.get("jobLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
    cities, countries, loc_parts = [], [], []
    for loc in locs:
        if isinstance(loc, str):  # "jobLocation": ["Amsterdam"] (Philadelphia) instead of Place objects
            loc_parts.append(loc)
            continue
        addr = (loc or {}).get("address") or {}
        if isinstance(addr, str):
            loc_parts.append(addr)
            continue
        city = _text(addr.get("addressLocality"))
        country = addr.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        country = _text(country)
        if city:
            cities.append(city)
        if country:
            countries.append(country)
        # SuccessFactors puts "Utrecht, NL" in streetAddress and nothing else; keep it so city detection can work
        parts = (city, _text(addr.get("addressRegion")), country, _text(addr.get("streetAddress")))
        loc_parts.append(", ".join(p for p in parts if p))
    jlt = obj.get("jobLocationType") or ""
    country = countries[0] if countries else None
    if country and len(country) != 2:
        country = None
    org = obj.get("hiringOrganization") or {}
    org_name = org.get("name") if isinstance(org, dict) else (org if isinstance(org, str) else None)
    location = "; ".join(p for p in loc_parts if p) or None
    if location is None and not cities:
        # No location in the structured data (SuccessFactors pages often omit it): use a Dutch place named in the
        # page URL, e.g. ".../job/Rotterdam-Product-Owner-Data-Platforms-ZH-3072-AP/..."
        location = _place_from_url(page_url)
    return RawPosting(
        external_id=external_id,
        title=str(title),
        url=url,
        company=(str(org_name).strip()[:200] or None) if org_name else None,
        location=location,
        city=cities[0] if cities else None,
        country=country.upper() if country else None,
        remote=True if "TELECOMMUTE" in str(jlt).upper() else None,
        description_html=obj.get("description") or None,
        posted_at=parse_dt(obj.get("datePosted")),
        raw={
            "employment_type": obj.get("employmentType"),
            "valid_through": obj.get("validThrough"),
        },
    )
