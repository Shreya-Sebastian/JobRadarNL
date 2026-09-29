"""Server-rendered employer pages: /companies, /company/<slug> and the Dutch /nl/bedrijf/<slug>.

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


_TEXT = {
    "en": {
        "title": "{c}: tech jobs in the Netherlands", "subtitle": "tech jobs in the Netherlands",
        "open": "open tech roles", "nodutch": "need no Dutch", "visa": "mention visa sponsorship",
        "employees": "employees", "cities": "Cities", "skills": "Skills asked for",
        "interactive": "Open the interactive view", "interactive_hint": "match scores, filters and charts",
        "roles": "Open tech roles", "roles_hint": "newest first; each title links to the employer's own page",
        "age": "Age", "t_title": "Title", "city": "City", "level": "Level", "skills_col": "Skills",
        "language": "Language", "all": "All employers", "overview": "Overview", "jobs": "Jobs", "market": "Market",
        "employers": "Employers", "coverage": "Coverage", "empty": "No open tech roles right now.",
        "footnote": "Postings are read from {c}'s own career site and refreshed every few hours. Language shows EN "
                    "when no Dutch is required.",
        "footer": "lists tech vacancies in the Netherlands read directly from employers' career sites. Every "
                  "listing links to the original page.",
        "desc": "{n} open tech jobs at {c} in the Netherlands", "desc_in": ", in {x}",
        "desc_skills": ". Most asked skills: {x}",
        "desc_end": ". Read from the employer's own career site; every listing links to the original page.",
        "today": "today", "yesterday": "yesterday", "days": "{d}d ago",
    },
    "nl": {
        "title": "{c}: techvacatures in Nederland", "subtitle": "techvacatures in Nederland",
        "open": "open techvacatures", "nodutch": "zonder Nederlands", "visa": "noemen visumsponsoring",
        "employees": "medewerkers", "cities": "Steden", "skills": "Gevraagde skills",
        "interactive": "Open de interactieve weergave", "interactive_hint": "matchscores, filters en grafieken",
        "roles": "Open techvacatures", "roles_hint": "nieuwste eerst; elke titel linkt naar de pagina van de werkgever",
        "age": "Leeftijd", "t_title": "Functie", "city": "Plaats", "level": "Niveau", "skills_col": "Skills",
        "language": "Taal", "all": "Alle werkgevers", "overview": "Overzicht", "jobs": "Vacatures",
        "market": "Markt", "employers": "Werkgevers", "coverage": "Dekking",
        "empty": "Op dit moment geen open techvacatures.",
        "footnote": "Vacatures worden gelezen van de eigen carrièresite van {c} en elke paar uur ververst. Taal "
                    "toont EN als Nederlands niet vereist is.",
        "footer": "toont techvacatures in Nederland, rechtstreeks van de carrièresites van werkgevers. Elke "
                  "vacature linkt naar de originele pagina.",
        "desc": "{n} open techvacatures bij {c} in Nederland", "desc_in": ", in {x}",
        "desc_skills": ". Meest gevraagde skills: {x}",
        "desc_end": ". Rechtstreeks van de carrièresite van de werkgever; elke vacature linkt naar de "
                    "originele pagina.",
        "today": "vandaag", "yesterday": "gisteren", "days": "{d} dagen geleden",
    },
}
TAGLINE_NL = "Tech-, software-, data- en IT-vacatures in Nederland, rechtstreeks van de sites van werkgevers."


def company_path(slug: str, lang: str = "en") -> str:
    return f"/nl/bedrijf/{slug}" if lang == "nl" else f"/company/{slug}"


def _age(r: Row, lang: str = "en") -> str:
    t = _TEXT[lang]
    d = (datetime.utcnow() - (r.posted_at or r.first_seen)).days
    return t["today"] if d <= 0 else t["yesterday"] if d == 1 else t["days"].format(d=d)


def render_company(name: str, rows: list[Row], lang: str = "en") -> str:
    from radar.seo import city_nl

    t = _TEXT["nl" if lang == "nl" else "en"]
    slug = slugify(name)
    mine = sorted(company_rows(rows, slug), key=lambda r: r.posted_at or r.first_seen, reverse=True)
    base = settings.site_url.rstrip("/")

    def city(c):
        return city_nl(c) if lang == "nl" and c else c

    cities = Counter(city(r.city) for r in mine if r.city)
    skills = Counter(s for r in mine for s in r.skills)
    english = sum(1 for r in mine if r.ex.get("english_only"))
    visa = sum(1 for r in mine if r.ex.get("visa_sponsorship") is True)
    headcount = next((r.employees for r in mine if r.employees), None)
    rows_html = "".join(
        f"<tr><td class=\"muted\">{_age(r, lang)}</td>"
        f"<td><a href=\"{escape(r.url)}\" rel=\"noopener\">{escape(r.title)}</a></td>"
        f"<td>{escape(city(r.city) or ('Remote' if r.remote else ''))}</td>"
        f"<td>{escape(r.ex.get('seniority') or '') if r.ex.get('seniority') != 'unknown' else ''}</td>"
        f"<td>{escape(', '.join(r.skills[:6]))}</td>"
        f"<td>{'EN' if r.ex.get('english_only') else 'NL'}</td></tr>"
        for r in mine
    )
    desc = (t["desc"].format(n=len(mine), c=name)
            + (t["desc_in"].format(x=", ".join(c for c, _ in cities.most_common(3))) if cities else "")
            + (t["desc_skills"].format(x=", ".join(s for s, _ in skills.most_common(5))) if skills else "")
            + t["desc_end"])
    self_path = company_path(slug, lang)
    ld = {
        "@context": "https://schema.org", "@type": "CollectionPage", "inLanguage": lang,
        "name": t["title"].format(c=name), "url": base + self_path, "description": desc,
        "isPartOf": {"@type": "WebSite", "name": settings.site_name, "url": base},
        "about": {"@type": "Organization", "name": name,
                  **({"numberOfEmployees": {"@type": "QuantitativeValue", "value": headcount}} if headcount else {})},
        "mainEntity": {"@type": "ItemList", "numberOfItems": len(mine), "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "url": r.url, "name": r.title} for i, r in enumerate(mine[:50])
        ]},
    }
    sep = "." if lang == "nl" else ","
    emp_kpi = (f'<div class="kpi"><b>{f"{headcount:,}".replace(",", sep)}</b><span>{t["employees"]}</span></div>'
               if headcount else "")
    html = _template("company.html")
    for key, value in t.items():
        html = html.replace("{{L_" + key.upper() + "}}", escape(value.replace("{c}", name)))
    return _brand(html).replace("{{LANG}}", "nl" if lang == "nl" else "en") \
        .replace("{{TITLE}}", escape(t["title"].format(c=name))) \
        .replace("{{TAGLINE}}", escape(TAGLINE_NL if lang == "nl" else settings.site_tagline)) \
        .replace("{{HOME}}", "/nl/" if lang == "nl" else "/") \
        .replace("{{COMPANIES}}", "/companies") \
        .replace("{{SELF_PATH}}", self_path) \
        .replace("{{EN_PATH}}", company_path(slug, "en")).replace("{{NL_PATH}}", company_path(slug, "nl")) \
        .replace("{{EN_ON}}", " on" if lang != "nl" else "").replace("{{NL_ON}}", " on" if lang == "nl" else "") \
        .replace("{{COMPANY}}", escape(name)) \
        .replace("{{ROBOTS}}", "" if len(mine) >= MIN_INDEXED_POSTINGS
                 else '<meta name="robots" content="noindex, follow">') \
        .replace("{{COUNT}}", str(len(mine))) \
        .replace("{{EMPLOYEES_KPI}}", emp_kpi) \
        .replace("{{CITIES}}", escape(", ".join(f"{c} ({n})" for c, n in cities.most_common(6))) or "–") \
        .replace("{{SKILLS}}", "".join(f"<span class=\"chip\">{escape(s)} <span class=\"muted\">{n}</span></span>"
                                      for s, n in skills.most_common(15)) or "–") \
        .replace("{{ENGLISH}}", str(english)).replace("{{VISA}}", str(visa)) \
        .replace("{{ROWS}}", rows_html or f"<tr><td colspan=\"6\" class=\"muted\">{escape(t['empty'])}</td></tr>") \
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
