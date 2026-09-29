"""Find the job boards of employers on the IND public register of recognised sponsors.

The register (https://ind.nl, "public register regular labour and highly skilled migrants") lists about 13,000
employers allowed to hire knowledge migrants: a list heavily weighted towards tech, engineering and research,
and mostly companies too small for any "top employers" list. It gives a name and a KvK number, no website.

Pipeline, one employer at a time, resumable through a state file:
1. skip employers the radar already covers (normalised name match);
2. guess domains from the name (adyen.nl, adyen.com, ...) and accept one only when its homepage names the company
   in <title> or og:site_name, and is not a parked domain;
3. on the verified domain, detect an ATS board from the homepage and its careers links (no slug guessing: guesses
   produced namesake boards before), register it after the adapter's probe;
4. otherwise look for a career sitemap or vacancy overview with JobPosting data (radar.sitemaps).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.config import settings

log = logging.getLogger(__name__)

_LEGAL = re.compile(
    r"\b(b\.?\s?v\.?|n\.?\s?v\.?|v\.?o\.?f\.?|c\.?v\.?|ltd\.?|limited|gmbh|inc\.?|llc|s\.?a\.?|s\.?e\.?|plc|ag|"
    r"holding|holdings|stichting|coöperatie|cooperatie|u\.?a\.?|branch|filiaal|nederland|netherlands|the netherlands|"
    r"europe|benelux|international|group|groep)\b",
    re.I,
)
_STOP = {"the", "and", "en", "van", "de", "der", "het", "of", "for", "services", "service", "solutions", "systems",
         "technologies", "technology", "consulting", "company", "global", "management", "software", "digital"}
_PARKED = re.compile(r"domain (?:is )?for sale|buy this domain|this domain|parked|coming soon|under construction|"
                     r"website coming|domeinnaam|te koop|default web site page|index of /|welcome to nginx|it works",
                     re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_SITE_NAME = re.compile(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)', re.I)


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def clean_name(name: str) -> str:
    n = _ascii(name).replace('"', " ").replace("'", " ")
    n = re.sub(r"\(.*?\)", " ", n)
    n = _LEGAL.sub(" ", n)
    n = re.sub(r"[^A-Za-z0-9&@+ -]+", " ", n)
    return " ".join(n.split()).strip(" -&")


def name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", clean_name(name).lower())


def tokens(name: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", clean_name(name).lower()) if len(w) >= 4 and w not in _STOP]


def domain_candidates(name: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", clean_name(name).lower())
    if not words:
        return []
    joined, dashed, first = "".join(words), "-".join(words), words[0]
    labels = [joined, dashed] + ([first] if len(words) > 1 and len(first) >= 5 else [])
    out: list[str] = []
    for label in labels:
        if 2 <= len(label) <= 40:
            for tld in ("nl", "com", "eu", "io"):
                d = f"{label}.{tld}"
                if d not in out:
                    out.append(d)
    return out[:10]


def verify(name: str, domain: str, client: httpx.Client) -> str | None:
    """The final URL's host when the homepage clearly belongs to this employer, else None."""
    toks = tokens(name)
    key = name_key(name)
    for url in (f"https://www.{domain}", f"https://{domain}"):
        try:
            r = client.get(url)
        except Exception:
            continue
        if r.status_code >= 400 or "html" not in r.headers.get("content-type", "html"):
            continue
        head = r.text[:60000]
        title = " ".join((_TITLE.search(head).group(1) if _TITLE.search(head) else "").split())
        site = _SITE_NAME.search(head).group(1) if _SITE_NAME.search(head) else ""
        label = f"{title} {site}".lower()
        if not label.strip() or _PARKED.search(label) or _PARKED.search(head[:3000]):
            return None
        label_key = re.sub(r"[^a-z0-9]", "", _ascii(label))
        host = r.url.host.lower()
        # a domain built from the whole name (acmerobotics.nl) needs one distinctive word on the page; a domain
        # from the first word only (delta.com for "Delta Precision Engineering") needs two, against namesakes
        dom_label = re.sub(r"[^a-z0-9]", "", domain.split(".")[0])
        full = dom_label == key
        needed = 1 if full or len(toks) <= 1 else 2
        if toks and sum(1 for t in toks if t in _ascii(label)) >= needed:
            return host
        if not toks and key and key in label_key:
            return host
        return None
    return None


def resolve(name: str, client: httpx.Client) -> str | None:
    for d in domain_candidates(name):
        host = verify(name, d, client)
        if host:
            return host
    return None


def covered_keys(session: Session) -> set[str]:
    from radar.models import Posting, Source

    keys = {name_key(c) for (c,) in session.execute(select(Source.company))}
    keys |= {name_key(c) for (c,) in session.execute(select(Posting.company).distinct())}
    return {k for k in keys if k}


class State:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, dict] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self._lock = threading.Lock()

    def set(self, kvk: str, value: dict) -> None:
        with self._lock:
            self.data[kvk] = value

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)


def _client() -> httpx.Client:
    return httpx.Client(timeout=12, follow_redirects=True,
                        headers={"User-Agent": settings.user_agent, "Accept": "text/html,*/*;q=0.8"})


def process_one(name: str, client: httpx.Client) -> dict:
    """Resolve the domain, then look for an ATS board or a JobPosting sitemap. No database writes here."""
    from radar.discovery import discover_domain
    from radar.sitemaps import find_job_sitemap

    host = resolve(name, client)
    if not host:
        return {"name": name, "domain": None}
    res = discover_domain(host, client, guess=False)
    out = {"name": name, "domain": host, "ats": res["candidates"], "careers_url": res.get("careers_url"),
           "jsonld": res.get("jsonld")}
    if not res["candidates"]:
        sm = find_job_sitemap(host, client)
        if sm:
            out["sitemap"] = sm
    return out


def register(session: Session, entry: dict) -> int:
    """Create sources for one processed employer. Returns the number of new sources."""
    from radar.discovery import register_discovery
    from radar.registry import upsert_source

    company = clean_name(entry["name"]) or entry["name"]
    added = 0
    if entry.get("ats") or entry.get("jsonld"):
        res = {"candidates": [tuple(c) for c in entry.get("ats") or []], "careers_url": entry.get("careers_url"),
               "jsonld": entry.get("jsonld")}
        added += register_discovery(session, company, res)
    if not added and entry.get("sitemap"):
        sm = entry["sitemap"]
        _, new = upsert_source(session, company, "jsonld", sm["sitemap"], sm["sample"], discovered_by="ind-register")
        added += int(new)
    return added


def run(session: Session, register_path: Path, state_path: Path, workers: int = 16, limit: int | None = None,
        checkpoint: int = 100) -> dict:
    entries = []
    for line in register_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        name, kvk = line.split("\t")[:2]
        entries.append((name.strip(), kvk.strip()))
    state = State(state_path)
    have = covered_keys(session)
    todo = [(n, k) for n, k in entries if k not in state.data and name_key(n) not in have and name_key(n)]
    if limit:
        todo = todo[:limit]
    log.info("sponsor register: %d employers, %d already processed, %d to do", len(entries), len(state.data), len(todo))
    stats = {"processed": 0, "resolved": 0, "boards": 0, "sources_added": 0}
    local = threading.local()

    def work(item):
        if not hasattr(local, "client"):
            local.client = _client()
        name, kvk = item
        try:
            return kvk, process_one(name, local.client)
        except Exception as e:  # one broken site must not stop the run
            return kvk, {"name": name, "domain": None, "error": f"{type(e).__name__}: {e}"[:200]}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, it) for it in todo]
        for i, fut in enumerate(as_completed(futures), 1):
            kvk, entry = fut.result()
            state.set(kvk, entry)
            stats["processed"] += 1
            if entry.get("domain"):
                stats["resolved"] += 1
            if entry.get("ats") or entry.get("jsonld") or entry.get("sitemap"):
                stats["boards"] += 1
                try:
                    stats["sources_added"] += register(session, entry)
                    session.commit()
                except Exception as e:
                    session.rollback()
                    log.warning("register failed for %s: %s", entry.get("name"), e)
            if i % checkpoint == 0:
                state.save()
                log.info("sponsors: %d/%d processed, %d domains, %d with boards, %d sources added", i, len(todo),
                         stats["resolved"], stats["boards"], stats["sources_added"])
    state.save()
    return stats
