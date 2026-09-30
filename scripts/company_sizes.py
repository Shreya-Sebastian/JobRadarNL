"""Look up employee counts for the employers on the radar and write data/company_sizes.tsv.

Sources, in order, all public:
  1. Wikidata "number of employees" (P1128), accepted only when the item's official website (P856) matches the
     employer's domain, or its label matches exactly and it is a Dutch organisation (P17 or P159 in NL);
  2. the "employees" field of the company infobox on Dutch or English Wikipedia, accepted only when the page's
     website field matches the employer's domain.
Employers without a confident match are left out, so the site shows "size unknown" rather than a guess.

    python scripts/company_sizes.py            # all employers with 2+ live tech postings, plus the top-500 list
    python scripts/company_sizes.py --limit 50
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from radar.normalize import norm_company  # noqa: E402

# Matches checked by hand and found wrong: the source counts something else than the employer's own staff
WRONG = {
    "Port of Rotterdam": "Wikidata counts all jobs in the port economy (~385,000); the port authority has ~1,300",
}
UA = {"User-Agent": "TechJobsRadar/1.0 (+https://techjobsradar.nl/privacy; contact@techjobsradar.nl)"}
WD = "https://www.wikidata.org/w/api.php"
NL = "Q55"
_INFOBOX_FIELDS = re.compile(r"^\s*\|\s*(?:werknemers|medewerkers|aantal[ _]werknemers|aantal[ _]medewerkers|"
                             r"num[ _]employees|employees)\s*=\s*(.+)$", re.I | re.M)
_WEBSITE_FIELDS = re.compile(r"^\s*\|\s*(?:website|homepage|url|web)\s*=\s*(.+)$", re.I | re.M)


def registrable(host: str) -> str:
    host = (host or "").lower().split(":")[0].removeprefix("www.")
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def site_domain(url: str) -> str:
    u = url if "//" in url else "https://" + url
    try:
        return registrable(urlparse(u).hostname or "")
    except ValueError:  # an infobox field holding an image or template instead of a URL
        return ""


def parse_count(text: str) -> int | None:
    """"3.600", "43,520 (2024)", "ca. 5000", "{{formatnum:12000}}", "± 1200 fte" -> int."""
    t = re.sub(r"<ref.*?(</ref>|/>)", " ", text, flags=re.S)
    t = re.sub(r"\{\{(?:formatnum|nts|nowrap|circa|c\.)\s*:?\|?\s*([^}|]+)[^}]*\}\}", r"\1", t, flags=re.I)
    m = re.search(r"(\d{1,3}(?:[.,\s]\d{3})+|\d+)", t)
    if not m:
        return None
    n = int(re.sub(r"[.,\s]", "", m.group(1)))
    return n if 1 <= n <= 3_000_000 else None


def employers(min_postings: int) -> dict[str, set[str]]:
    """Company name -> candidate domains (from the top-500 seed list and the sources' careers URLs)."""
    from sqlalchemy import func, select

    from radar.db import new_session
    from radar.models import Posting, Source

    s = new_session()
    out: dict[str, set[str]] = {}
    rows = s.execute(select(Posting.company, func.count()).where(Posting.closed_at.is_(None),
                                                                   Posting.duplicate_of.is_(None),
                                                                   Posting.is_tech.is_(True))
                     .group_by(Posting.company)).all()
    for name, n in rows:
        if n >= min_postings:
            out.setdefault(name, set())
    for name, url, slug in s.execute(select(Source.company, Source.url, Source.slug)):
        if name in out:
            for u in (url, slug):
                if u and "." in u and not any(a in u for a in ("greenhouse", "lever.co", "recruitee", "teamtailor",
                                                                "workday", "smartrecruiters", "ashby", "workable",
                                                                "personio", "homerun")):
                    d = site_domain(u)
                    if d:
                        out[name].add(re.sub(r"^(werkenbij|werkenvoor|careers?|jobs|vacatures)", "", d) or d)
                        out[name].add(d)
    seed = ROOT / "data/seeds/top500.tsv"
    for line in seed.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        cols = line.split("\t")
        name, domain = cols[0], cols[2] if len(cols) > 2 else ""
        key = next((k for k in out if norm_company(k).lower() == norm_company(name).lower()), name)
        out.setdefault(key, set())
        if domain:
            out[key].add(registrable(domain))
    return out


def wikidata(client: httpx.Client, name: str, domains: set[str]) -> tuple[int, str, str] | None:
    r = client.get(WD, params={"action": "wbsearchentities", "search": name, "language": "nl", "uselang": "nl",
                               "limit": 7, "format": "json", "type": "item"})
    ids = [x["id"] for x in r.json().get("search", [])]
    if not ids:
        return None
    ents = client.get(WD, params={"action": "wbgetentities", "ids": "|".join(ids), "props": "labels|aliases|claims",
                                  "languages": "nl|en", "format": "json"}).json().get("entities", {})
    want = norm_company(name).lower()
    for qid in ids:
        e = ents.get(qid, {})
        claims = e.get("claims", {})
        if "P1128" not in claims:
            continue
        sites = {site_domain(c["mainsnak"]["datavalue"]["value"]) for c in claims.get("P856", [])
                 if c.get("mainsnak", {}).get("datavalue")}
        names = {v["value"] for v in e.get("labels", {}).values()} | \
            {a["value"] for vs in e.get("aliases", {}).values() for a in vs}
        dutch = any(c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id") == NL
                    for p in ("P17",) for c in claims.get(p, []))
        exact = any(norm_company(n).lower() == want for n in names)
        if not ((domains and sites & domains) or (exact and dutch)):
            continue
        best = None
        for c in claims["P1128"]:
            try:
                amount = int(float(c["mainsnak"]["datavalue"]["value"]["amount"]))
            except (KeyError, ValueError, TypeError):
                continue
            year = (c.get("qualifiers", {}).get("P585", [{}])[0].get("datavalue", {}).get("value", {})
                    .get("time", "")[1:5])
            if best is None or year > best[1]:
                best = (amount, year)
        if best:
            return best[0], best[1], f"wikidata:{qid}"
    return None


def _lead(wikitext: str) -> str:
    """The opening sentences of an article, after the infobox."""
    body = re.sub(r"\{\{.*?\}\}", " ", wikitext[:20000], flags=re.S)
    return body.strip()[:800]


def wikipedia(client: httpx.Client, name: str, domains: set[str]) -> tuple[int, str, str] | None:
    if not domains:
        return None  # without a domain to check the page against, a namesake is too likely
    for lang in ("nl", "en"):
        api = f"https://{lang}.wikipedia.org/w/api.php"
        hits = client.get(api, params={"action": "query", "list": "search", "srsearch": name, "srlimit": 3,
                                       "format": "json"}).json().get("query", {}).get("search", [])
        for hit in hits:
            page = client.get(api, params={"action": "query", "prop": "revisions", "rvprop": "content",
                                           "rvslots": "main", "titles": hit["title"], "format": "json",
                                           "formatversion": 2}).json()
            try:
                text = page["query"]["pages"][0]["revisions"][0]["slots"]["main"]["content"]
            except (KeyError, IndexError):
                continue
            head = text[:8000]
            fields = _WEBSITE_FIELDS.findall(head)
            sites = {site_domain(m.strip(" []{}|")) for m in fields}
            sites |= {site_domain(u) for u in re.findall(r"https?://[^\s\]|}]+", " ".join(fields))}
            if not sites & domains:
                continue
            # the page must be about this name, not a parent company whose site matches ("ANSYS" -> "Synopsys")
            first = norm_company(name).lower().split()[0]
            if first not in hit["title"].lower() and name.lower() not in _lead(text).lower():
                continue
            m = _INFOBOX_FIELDS.search(head)
            n = parse_count(m.group(1)) if m else None
            if n:
                year = re.search(r"(20\d\d|19\d\d)", m.group(1))
                return n, year.group(1) if year else "", f"{lang}wiki:{hit['title']}"
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-postings", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=str(ROOT / "data/company_sizes.tsv"))
    ap.add_argument("--restart", action="store_true", help="forget earlier progress and look everything up again")
    args = ap.parse_args()
    todo = employers(args.min_postings)
    names = sorted(todo)[: args.limit or None]
    # progress is kept next to the output, so an interrupted run continues where it stopped
    partial = Path(args.out + ".partial")
    checked = Path(args.out + ".checked")
    if args.restart:
        partial.unlink(missing_ok=True)
        checked.unlink(missing_ok=True)
    done = set(checked.read_text(encoding="utf-8").splitlines()) if checked.exists() else set()
    left = [n for n in names if n not in done]
    print(f"{len(names)} employers, {len(names) - len(left)} already checked, {len(left)} to go", flush=True)
    with httpx.Client(timeout=20, headers=UA, follow_redirects=True) as client, \
            open(partial, "a", encoding="utf-8", newline="") as hits, open(checked, "a", encoding="utf-8") as seen:
        w = csv.writer(hits, delimiter="\t", lineterminator="\n")
        for i, name in enumerate(left, 1):
            try:
                hit = wikidata(client, name, todo[name]) or wikipedia(client, name, todo[name])
            except (httpx.HTTPError, ValueError) as e:
                print(f"  {name}: {e}", file=sys.stderr)
                continue  # not marked as checked: a rerun tries it again
            if hit and name in WRONG:
                hit = None
            if hit:
                w.writerow([name, *hit])
                hits.flush()
                print(f"[{i}/{len(left)}] {name}: {hit[0]:,} ({hit[2]})", flush=True)
            seen.write(name + "\n")
            seen.flush()
            time.sleep(0.2)
    with open(partial, encoding="utf-8") as f:
        found = {row[0]: row for row in csv.reader(f, delimiter="\t") if len(row) >= 4 and row[0] not in WRONG}
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["# company", "employees", "as_of", "source"])
        w.writerows(sorted(found.values()))
    print(f"{len(found)} of {len(names)} employers with an employee count -> {args.out}")


if __name__ == "__main__":
    main()
