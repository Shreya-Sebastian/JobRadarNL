"""Probe candidate company slugs across every ATS adapter and write the hits to data/probe_results.json.

Usage: python scripts/probe_slugs.py <file with one company name per line> [out.json]
Superseded for bulk use by `radar enumerate` + `radar probe-boards`; kept for probing a short list of names.
Each line of the candidates file is a company name; slugs are derived by lowercasing and
stripping non-alphanumerics, plus a few common variants.
"""

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from radar.adapters import ADAPTERS
from radar.config import settings

ATS_TO_PROBE = ["greenhouse", "lever", "ashby", "workable", "recruitee"]


def slug_variants(name: str) -> list[str]:
    base = re.sub(r"[^a-z0-9]", "", name.lower())
    variants = {base}
    if base.endswith("bv"):
        variants.add(base[:-2])
    variants.add(re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-"))
    return [v for v in variants if v]


def probe_one(ats: str, name: str, slug: str) -> dict | None:
    client = httpx.Client(timeout=15, headers={"User-Agent": settings.user_agent}, follow_redirects=True)
    adapter = ADAPTERS[ats](client)
    try:
        if not adapter.probe(slug):
            return None
        postings = adapter.fetch(slug)
    except Exception:
        return None
    finally:
        client.close()
    nl = sum(1 for p in postings if _looks_nl(p.location, p.country))
    return {"company": name, "ats": ats, "slug": slug, "total": len(postings), "nl": nl}


def _looks_nl(location: str | None, country: str | None) -> bool:
    if country and country.upper() == "NL":
        return True
    if not location:
        return False
    return bool(re.search(r"netherlands|nederland|amsterdam|rotterdam|utrecht|eindhoven|den haag|the hague|"
                          r"delft|leiden|groningen|nijmegen|tilburg|breda|arnhem|haarlem|hilversum|amersfoort|"
                          r"apeldoorn|enschede|maastricht|zwolle|veldhoven|\bNL\b", location, re.I))


def main() -> None:
    candidates = [line.strip() for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()]
    candidates = [c for c in candidates if c and not c.startswith("#")]
    jobs = [(ats, name, slug) for name in candidates for slug in slug_variants(name) for ats in ATS_TO_PROBE]
    hits: list[dict] = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(probe_one, *j): j for j in jobs}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                hits.append(res)
                print(f"HIT {res['ats']:<11} {res['slug']:<28} total={res['total']:<5} nl={res['nl']}")
    hits.sort(key=lambda h: (-h["nl"], -h["total"]))
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "data/probe_results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(hits, indent=2), encoding="utf-8")
    print(f"\n{len(hits)} hits from {len(jobs)} probes; NL postings found: {sum(h['nl'] for h in hits)}")


if __name__ == "__main__":
    main()
