"""Server-rendered employer pages: /companies and /company/<slug>.

The dashboard is a single page driven by hash routes, which search engines do not index. These plain HTML
pages exist so that "<employer> tech jobs" searches can land on the radar: one page per employer with live
tech postings, listing its open roles with links to the employer's own pages, plus a link into the
interactive view. They are rendered from the same in-memory rows as the API and cached like it.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path

from radar.config import settings
from radar.stats import Row

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
_SLUG_RX = re.compile(r"[^a-z0-9]+")
_EMPTY_ROW = "<tr><td colspan=\"6\" class=\"muted\">No open tech roles right now.</td></tr>"


def slugify(name: str) -> str:
    s = _SLUG_RX.sub("-", name.lower()).strip("-")
    return s or "company"


def live_tech(rows: list[Row]) -> list[Row]:
    return [r for r in rows if r.closed_at is None and r.ex.get("is_tech", True)]


# Employer pages with fewer live tech jobs than this are kept for visitors but marked noindex and left out of the
# sitemap: a page with one listing is thin content to a search engine
MIN_INDEXED_POSTINGS = 2


def companies(rows: list[Row]) -> list[tuple[str, str, int]]:
    """(name, slug, live tech postings) for every employer with at least one, most postings first.
    Spellings that share a slug ("SURF" and "Surf") are one employer with one page, shown under the most used
    spelling."""
    counts = Counter(r.company for r in rows)
    by_slug: dict[str, list[tuple[str, int]]] = {}
    for name, n in counts.items():
        by_slug.setdefault(slugify(name), []).append((name, n))
    out = []
    for slug, names in by_slug.items():
        names.sort(key=lambda t: (-t[1], t[0]))
        out.append((names[0][0], slug, sum(n for _, n in names)))
    out.sort(key=lambda t: (-t[2], t[0].lower()))
    return out


def find_company(rows: list[Row], slug: str) -> str | None:
    for name, s, _ in companies(rows):
        if s == slug:
            return name
    return None


def company_rows(rows: list[Row], slug: str) -> list[Row]:
    return [r for r in rows if slugify(r.company) == slug]


def _template(name: str) -> str:
    return (WEB_DIR / name).read_text(encoding="utf-8")


def _brand(html: str) -> str:
    return (html.replace("{{SITE_NAME}}", escape(settings.site_name))
                .replace("{{SITE_URL}}", settings.site_url.rstrip("/"))
                .replace("{{SITE_TAGLINE}}", escape(settings.site_tagline)))


def _age(r: Row) -> str:
    d = (datetime.utcnow() - (r.posted_at or r.first_seen)).days
    return "today" if d <= 0 else "yesterday" if d == 1 else f"{d}d ago"


def render_company(name: str, rows: list[Row]) -> str:
    slug = slugify(name)
    mine = sorted(company_rows(rows, slug), key=lambda r: r.posted_at or r.first_seen, reverse=True)
    base = settings.site_url.rstrip("/")
    cities = Counter(r.city for r in mine if r.city)
    skills = Counter(s for r in mine for s in r.skills)
    english = sum(1 for r in mine if r.ex.get("english_only"))
    visa = sum(1 for r in mine if r.ex.get("visa_sponsorship") is True)
    rows_html = "".join(
        f"<tr><td class=\"muted\">{_age(r)}</td>"
        f"<td><a href=\"{escape(r.url)}\" rel=\"noopener\">{escape(r.title)}</a></td>"
        f"<td>{escape(r.city or ('Remote' if r.remote else ''))}</td>"
        f"<td>{escape(r.ex.get('seniority') or '') if r.ex.get('seniority') != 'unknown' else ''}</td>"
        f"<td>{escape(', '.join(r.skills[:6]))}</td>"
        f"<td>{'EN' if r.ex.get('english_only') else 'NL'}</td></tr>"
        for r in mine
    )
    desc = (f"{len(mine)} open tech jobs at {name} in the Netherlands"
            + (f", in {', '.join(c for c, _ in cities.most_common(3))}" if cities else "")
            + (f". Most asked skills: {', '.join(s for s, _ in skills.most_common(5))}" if skills else "")
            + ". Read from the employer's own career site; every listing links to the original page.")
    ld = {
        "@context": "https://schema.org", "@type": "CollectionPage",
        "name": f"{name}: tech jobs in the Netherlands", "url": f"{base}/company/{slug}", "description": desc,
        "isPartOf": {"@type": "WebSite", "name": settings.site_name, "url": base},
        "about": {"@type": "Organization", "name": name},
        "mainEntity": {"@type": "ItemList", "numberOfItems": len(mine), "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "url": r.url, "name": r.title} for i, r in enumerate(mine[:50])
        ]},
    }
    html = _template("company.html")
    return _brand(html).replace("{{COMPANY}}", escape(name)) \
        .replace("{{SLUG}}", slug) \
        .replace("{{ROBOTS}}", "" if len(mine) >= MIN_INDEXED_POSTINGS
                 else '<meta name="robots" content="noindex, follow">') \
        .replace("{{COUNT}}", str(len(mine))) \
        .replace("{{CITIES}}", escape(", ".join(f"{c} ({n})" for c, n in cities.most_common(6))) or "–") \
        .replace("{{SKILLS}}", "".join(f"<span class=\"chip\">{escape(s)} <span class=\"muted\">{n}</span></span>"
                                      for s, n in skills.most_common(15)) or "–") \
        .replace("{{ENGLISH}}", str(english)).replace("{{VISA}}", str(visa)) \
        .replace("{{ROWS}}", rows_html or _EMPTY_ROW) \
        .replace("{{DESCRIPTION}}", escape(desc)) \
        .replace("{{JSONLD}}", json.dumps(ld, ensure_ascii=False)) \
        .replace("{{COMPANY_URLENC}}", escape(name).replace(" ", "%20"))


def render_companies(rows: list[Row]) -> str:
    items = companies(rows)
    base = settings.site_url.rstrip("/")
    lis = "".join(f"<li><a href=\"/company/{slug}\">{escape(name)}</a> <span class=\"muted\">{n}</span></li>"
                  for name, slug, n in items)
    desc = (f"{len(items)} employers with open tech jobs in the Netherlands, read from their own career sites. "
            f"{sum(n for _, _, n in items)} live postings.")
    ld = {"@context": "https://schema.org", "@type": "CollectionPage",
          "name": "Employers hiring for tech in the Netherlands", "url": f"{base}/companies", "description": desc,
          "isPartOf": {"@type": "WebSite", "name": settings.site_name, "url": base}}
    return _brand(_template("companies.html")).replace("{{COUNT}}", str(len(items))) \
        .replace("{{ITEMS}}", lis).replace("{{DESCRIPTION}}", escape(desc)) \
        .replace("{{JSONLD}}", json.dumps(ld, ensure_ascii=False))
