"""Automated ATS discovery: given a company website, find its careers page and detect the ATS behind it.

This is the coverage multiplier. Adding a company means adding a domain; the discovery job
turns it into a working source (or records that no machine-readable board was found).
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from radar.adapters import get_adapter
from radar.config import settings
from radar.registry import upsert_source

log = logging.getLogger(__name__)

# ATS detection patterns, in priority order. Each yields (ats, slug).
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"boards(?:-api)?\.greenhouse\.io/(?:v1/boards/)?([a-z0-9_-]+)", re.I)),
    ("greenhouse", re.compile(r"job-boards\.greenhouse\.io/([a-z0-9_-]+)", re.I)),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board(?:/js)?\?for=([a-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([a-z0-9_-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_-]+)", re.I)),
    ("ashby", re.compile(r"api\.ashbyhq\.com/posting-api/job-board/([a-z0-9_-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/(?:api/v1/widget/accounts/)?([a-z0-9_-]+)", re.I)),
    ("recruitee", re.compile(r"https?://([a-z0-9-]+)\.recruitee\.com", re.I)),
    ("teamtailor", re.compile(r"https?://([a-z0-9-]+)\.teamtailor\.com", re.I)),
    ("workday", re.compile(r"https?://([a-z0-9-]+\.wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)")),
    ("personio", re.compile(r"https?://([a-z0-9-]+)\.jobs\.personio\.(?:de|com)", re.I)),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)")),
    # not Homerun's own hosts (static., cdn., feed., app., www.), which appear in every Homerun page's markup
    ("homerun", re.compile(r"https?://(?!(?:static|cdn|feed|app|www|api)\.)([a-z0-9-]+)\.homerun\.co", re.I)),
]
_WORKABLE_SKIP = {"api", "j", "jobs", "widget"}
# Subdomains of ATS vendors that are assets or shared infrastructure, never a company board.
_SLUG_SKIP = {
    "recruitee": {"careers-analytics", "api", "career", "careers", "app", "cdn", "static", "assets", "www"},
    "teamtailor": {"www", "app", "tt", "api", "cdn", "static", "assets", "images", "attachments"},
    "homerun": {"cdn", "static", "feed", "www", "app", "api", "assets"},
    "personio": {"www", "app", "api", "cdn"},
    "greenhouse": {"www", "boards", "app", "api"},
    "lever": {"www", "api"},
    "ashby": {"www", "api"},
}
_CAREERS_LINK = re.compile(
    r"career|careers|jobs|job\b|vacature|vacatures|werken[- ]bij|work[- ]with[- ]us|join[- ]us|join[- ]the[- ]team|"
    r"open[- ]positions|opportunities|werkenbij|recruitment|we'?re hiring|hiring",
    re.I,
)
# homerun is handled separately, through its sitemap (see register_discovery)
_HAS_ADAPTER = {"greenhouse", "lever", "ashby", "workable", "recruitee", "teamtailor", "personio", "workday",
                "smartrecruiters"}
_GUESS_ATS = ["greenhouse", "lever", "ashby", "recruitee", "teamtailor", "personio", "workable"]


def guess_slugs(domain: str) -> list[str]:
    host = urlparse(domain if domain.startswith("http") else f"https://{domain}").netloc.replace("www.", "")
    base = host.split(".")[0].lower()
    guesses = [base, base.replace("-", ""), base.replace("-", "_")]
    return list(dict.fromkeys(g for g in guesses if len(g) >= 2))


def probe_guesses(domain: str) -> list[tuple[str, str]]:
    """When a careers page embeds its ATS via JavaScript, static detection finds nothing.
    Fall back to trying the company name as a slug on every ATS with a public API."""
    found: list[tuple[str, str]] = []
    for slug in guess_slugs(domain):
        for ats in _GUESS_ATS:
            try:
                adapter = get_adapter(ats)
                if adapter.probe(slug) and adapter.fetch(slug):
                    found.append((ats, slug))
                    return found
            except Exception:
                continue
    return found


def _client() -> httpx.Client:
    return httpx.Client(timeout=settings.http_timeout, follow_redirects=True,
                        headers={"User-Agent": settings.user_agent, "Accept": "text/html,*/*;q=0.8"})


def detect_ats(html: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for ats, rx in _PATTERNS:
        for m in rx.finditer(html):
            slug = m.group(1)
            if ats == "workable" and slug.lower() in _WORKABLE_SKIP:
                continue
            if slug.lower() in _SLUG_SKIP.get(ats, set()):
                continue
            if ats == "workday":
                slug = f"{m.group(1)}/{m.group(2)}"
            pair = (ats, slug)
            if pair not in found:
                found.append(pair)
    return found


def find_careers_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    host = urlparse(base_url).netloc.replace("www.", "")
    scored: list[tuple[int, str]] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        text = " ".join(a.get_text(" ", strip=True).split())
        h = urlparse(href)
        score = 0
        if _CAREERS_LINK.search(text):
            score += 2
        if _CAREERS_LINK.search(h.path + " " + h.netloc):
            score += 2
        if any(v in h.netloc for v in ("greenhouse", "lever.co", "ashbyhq", "workable", "recruitee", "teamtailor",
                                        "myworkdayjobs", "personio", "smartrecruiters", "homerun")):
            score += 3
        if score and (host in h.netloc or _CAREERS_LINK.search(h.netloc) or score >= 3):
            scored.append((score, href))
    scored.sort(key=lambda t: -t[0])
    out: list[str] = []
    for _, href in scored:
        if href not in out:
            out.append(href)
    return out[:5]


def discover_domain(domain: str, client: httpx.Client | None = None, guess: bool = True) -> dict:
    """Return {'domain', 'careers_url', 'candidates': [(ats, slug)], 'jsonld': bool}. With guess=False no ATS slugs
    are guessed from the domain name: only boards the site itself links to count."""
    own = client is None
    client = client or _client()
    result = {"domain": domain, "careers_url": None, "candidates": [], "jsonld": False, "guessed": False}
    try:
        url = domain if domain.startswith("http") else f"https://{domain}"
        try:
            resp = client.get(url)
        except Exception:
            resp = client.get(url.replace("https://", "https://www."))
        if resp.status_code >= 400:
            return result
        home = resp.text
        result["candidates"] = detect_ats(home)
        for link in find_careers_links(home, str(resp.url)):
            try:
                r2 = client.get(link)
            except Exception:
                continue
            if r2.status_code >= 400:
                continue
            html = r2.text
            for pair in detect_ats(html):
                if pair not in result["candidates"]:
                    result["candidates"].append(pair)
            for pair in detect_ats(str(r2.url)):
                if pair not in result["candidates"]:
                    result["candidates"].append(pair)
            if not result["careers_url"]:
                result["careers_url"] = str(r2.url)
            if "JobPosting" in html:
                result["jsonld"] = True
                result["careers_url"] = str(r2.url)
            if result["candidates"]:
                break
        if guess and not result["candidates"] and not result["jsonld"]:
            result["candidates"] = probe_guesses(domain)
            result["guessed"] = bool(result["candidates"])
    finally:
        if own:
            client.close()
    return result


def homerun_sitemap(slug: str) -> str:
    return f"https://{slug}.homerun.co/sitemap.xml"


def register_discovery(session: Session, company: str, res: dict) -> int:
    """Verify candidates with the adapter probe and add working sources. Returns number added."""
    added = 0
    for ats, slug in res["candidates"]:
        if ats in _HAS_ADAPTER:
            try:
                ok = get_adapter(ats).probe(slug)
            except Exception:
                ok = False
            if not ok:
                continue
            # a board the employer's own site links to is trusted; a guessed slug may be a namesake and is
            # recorded as such, so `radar verify-sources` reviews it
            how = "discovery-guess" if res.get("guessed") else "discovery"
            _, new = upsert_source(session, company, ats, slug, res.get("careers_url"), discovered_by=how)
            added += int(new)
            return added
        if ats == "homerun":
            # Homerun career sites list every job in a sitemap and each job page carries JobPosting data, so the
            # generic JSON-LD adapter reads them
            _, new = upsert_source(session, company, "jsonld", homerun_sitemap(slug), res.get("careers_url"),
                                   discovered_by="discovery")
            added += int(new)
            return added
        # ATS known but no adapter yet: record inactive so the adapter backlog is visible.
        src, new = upsert_source(session, company, ats, slug, res.get("careers_url"), discovered_by="discovery")
        if new:
            src.active = False
            src.last_status = "no_adapter"
    if res.get("jsonld") and res.get("careers_url"):
        _, new = upsert_source(session, company, "jsonld", res["careers_url"], res["careers_url"],
                               discovered_by="discovery")
        added += int(new)
    return added


def discover_many(session: Session, domains: list[str], workers: int = 8) -> int:
    added = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(discover_domain, d): d for d in domains}
        for fut in as_completed(futures):
            d = futures[fut]
            try:
                res = fut.result()
            except Exception as e:
                log.warning("discovery failed for %s: %s", d, e)
                continue
            company = _company_from_domain(d)
            n = register_discovery(session, company, res)
            session.commit()
            added += n
            log.info("%s -> %s jsonld=%s added=%d", d, res["candidates"], res["jsonld"], n)
    return added


def _company_from_domain(domain: str) -> str:
    host = urlparse(domain if domain.startswith("http") else f"https://{domain}").netloc
    host = host.replace("www.", "")
    name = host.split(".")[0]
    return name[:1].upper() + name[1:]
