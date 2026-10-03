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
        "interactive": "Open the interactive view",
        "roles": "Open tech roles",
        "age": "Age", "t_title": "Title", "city": "City", "level": "Level", "skills_col": "Skills",
        "language": "Language", "all": "All employers", "overview": "Overview", "jobs": "Jobs", "market": "Market",
        "employers": "Employers", "empty": "No open tech roles right now.",
        "footer": "lists tech vacancies in the Netherlands read directly from employers' career sites.",
        "desc": "{n} open tech jobs at {c} in the Netherlands", "desc_in": ", in {x}",
        "desc_skills": ". Most asked skills: {x}",
        "desc_end": ". Read from the employer's own career site; every listing links to the original page.",
        "today": "today", "yesterday": "yesterday", "days": "{d}d ago",
    },
    "nl": {
        "title": "{c}: techvacatures in Nederland", "subtitle": "techvacatures in Nederland",
        "open": "open techvacatures", "nodutch": "zonder Nederlands", "visa": "noemen visumsponsoring",
        "employees": "medewerkers", "cities": "Steden", "skills": "Gevraagde skills",
        "interactive": "Open de interactieve weergave",
        "roles": "Open techvacatures",
        "age": "Leeftijd", "t_title": "Functie", "city": "Plaats", "level": "Niveau", "skills_col": "Skills",
        "language": "Taal", "all": "Alle werkgevers", "overview": "Overzicht", "jobs": "Vacatures",
        "market": "Markt", "employers": "Werkgevers",
        "empty": "Op dit moment geen open techvacatures.",
        "footer": "toont techvacatures in Nederland, rechtstreeks van de carrièresites van werkgevers.",
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
        f"<td><a href=\"{job_path(r.id, r.title, lang)}\">{escape(r.title)}</a></td>"
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
            {"@type": "ListItem", "position": i + 1, "url": base + job_path(r.id, r.title, lang), "name": r.title}
            for i, r in enumerate(mine[:50])
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
        .replace("{{SECTOR}}", escape(_sector_label(mine, lang))) \
        .replace("{{ROBOTS}}", "" if len(mine) >= MIN_INDEXED_POSTINGS
                 else '<meta name="robots" content="noindex, follow">') \
        .replace("{{COUNT}}", str(len(mine))) \
        .replace("{{EMPLOYEES_KPI}}", emp_kpi) \
        .replace("{{CITIES}}", escape(", ".join(f"{c} ({n})" for c, n in cities.most_common(6))) or "-") \
        .replace("{{SKILLS}}", "".join(f"<span class=\"chip\">{escape(s)} <span class=\"muted\">{n}</span></span>"
                                      for s, n in skills.most_common(15)) or "-") \
        .replace("{{ENGLISH}}", str(english)).replace("{{VISA}}", str(visa)) \
        .replace("{{ROWS}}", rows_html or f"<tr><td colspan=\"6\" class=\"muted\">{escape(t['empty'])}</td></tr>") \
        .replace("{{DESCRIPTION}}", escape(desc)) \
        .replace("{{JSONLD}}", json.dumps(ld, ensure_ascii=False)) \
        .replace("{{COMPANY_URLENC}}", escape(name).replace(" ", "%20"))


# ---------- one page per listing: /job/<id>/<slug> and /nl/vacature/<id>/<slug> ----------

def job_path(posting_id: int, title: str, lang: str = "en") -> str:
    return f"/nl/vacature/{posting_id}/{slugify(title)}" if lang == "nl" else f"/job/{posting_id}/{slugify(title)}"


_JOB_TEXT = {
    "en": {
        "overview": "Overview", "jobs": "Jobs", "market": "Market", "employers": "Employers",
        "back": "← All jobs", "apply": "View and apply on", "more_at": "More jobs at",
        "description": "Job description",
        "credit": "From {c}'s job posting, as published on {h}. The text belongs to {c}; read the original at {u}.",
        "closed": "This vacancy is no longer open.", "posted": "posted {d}", "remote": "Remote",
        "footer": "lists tech vacancies in the Netherlands read directly from employers' career sites.",
        "title": "{t} at {c}", "in": " in {x}",
        "no_text": "The employer's page has no description that could be read. See the original posting.",
        "level": {"intern": "Internship", "trainee": "Trainee / graduate programme", "junior": "Junior",
                  "medior": "Medior", "senior": "Senior", "lead": "Lead", "staff": "Staff / principal",
                  "manager": "Manager"},
        "years": "{n}+ years of experience", "years_text": "{n} years of experience",
        "one_year": "1 year of experience",
        "no_exp": "No experience asked",
        "degree": {"phd": "PhD", "msc": "Master's degree", "bsc": "Bachelor's degree", "hbo": "HBO degree",
                   "mbo": "MBO", "none": "No degree asked"},
        "english": "English, no Dutch required", "dutch": "Dutch required",
        "policy": {"remote": "Remote", "hybrid": "Hybrid", "onsite": "On-site"},
        "visa_yes": "Visa sponsorship mentioned", "visa_no": "No visa sponsorship",
        "enrol": "For enrolled students", "salary": "€{lo} – €{hi} a year", "salary_from": "from €{lo} a year",
        "skills": "Skills asked for", "nice": "Nice to have",
    },
    "nl": {
        "overview": "Overzicht", "jobs": "Vacatures", "market": "Markt", "employers": "Werkgevers",
        "back": "← Alle vacatures", "apply": "Bekijk en solliciteer op", "more_at": "Meer vacatures bij",
        "description": "Vacaturetekst",
        "credit": "Uit de vacature van {c}, zoals gepubliceerd op {h}. De tekst is van {c}; lees het origineel op {u}.",
        "closed": "Deze vacature is niet meer open.", "posted": "geplaatst {d}", "remote": "Op afstand",
        "footer": "toont techvacatures in Nederland, rechtstreeks van de carrièresites van werkgevers.",
        "title": "{t} bij {c}", "in": " in {x}",
        "no_text": "De pagina van de werkgever heeft geen leesbare vacaturetekst. Bekijk de originele vacature.",
        "level": {"intern": "Stage", "trainee": "Traineeship / starterprogramma", "junior": "Junior",
                  "medior": "Medior", "senior": "Senior", "lead": "Lead", "staff": "Staff / principal",
                  "manager": "Manager"},
        "years": "{n}+ jaar ervaring", "years_text": "{n} jaar ervaring", "one_year": "1 jaar ervaring",
        "no_exp": "Geen ervaring gevraagd",
        "degree": {"phd": "PhD", "msc": "Master", "bsc": "Bachelor", "hbo": "Hbo", "mbo": "Mbo",
                   "none": "Geen opleiding gevraagd"},
        "english": "Engels, geen Nederlands nodig", "dutch": "Nederlands vereist",
        "policy": {"remote": "Op afstand", "hybrid": "Hybride", "onsite": "Op locatie"},
        "visa_yes": "Visumsponsoring genoemd", "visa_no": "Geen visumsponsoring",
        "enrol": "Voor ingeschreven studenten", "salary": "€{lo} – €{hi} per jaar",
        "salary_from": "vanaf €{lo} per jaar",
        "skills": "Gevraagde skills", "nice": "Pluspunten",
    },
}


def _body(p) -> str:
    """The description as HTML: the employer's formatting when the source gave it (cleaned again here, so nothing
    stored can bypass the allowlist), else paragraphs, lists and headings made from the plain text."""
    from radar.htmlclean import clean_html, drop_leading, text_to_html

    body = clean_html(p.description_html) or text_to_html(p.description or "")
    return drop_leading(body, (p.title, p.company))


def render_job(p, lang: str = "en", sector: str | None = None) -> str:
    """The listing page: what the radar read from the posting, then the employer's own text with credit and links
    back to the original. `p` is a radar.models.Posting."""
    from urllib.parse import urlparse

    from radar.seo import city_nl
    from radar.stats import experience_band

    lang = "nl" if lang == "nl" else "en"
    t = _JOB_TEXT[lang]
    ex = p.extraction or {}
    base = settings.site_url.rstrip("/")
    host = urlparse(p.url).netloc.removeprefix("www.") or p.url
    sep = "." if lang == "nl" else ","

    def money(v):
        return f"{int(v):,}".replace(",", sep)

    city = (city_nl(p.city) if lang == "nl" else p.city) if p.city else (t["remote"] if p.remote else "")
    when = p.posted_at or p.first_seen
    meta = " · ".join(x for x in (
        f'<a href="{company_path(slugify(p.company), lang)}">{escape(p.company)}</a>',
        escape(city) if city else "",
        escape(t["posted"].format(d=when.strftime("%d-%m-%Y"))) if when else "",
    ) if x)

    facts = []
    if ex.get("seniority") in t["level"]:
        facts.append(t["level"][ex["seniority"]])
    years = ex.get("years_experience")
    label = ex.get("years_experience_text")
    if years and label:
        facts.append(t["one_year"] if label == "1" else t["years_text"].format(n=label.replace("-", "–")))
    elif years:
        facts.append(t["years"].format(n=years))
    elif experience_band(ex, p.title) == "none":
        facts.append(t["no_exp"])
    if ex.get("degree_required") in t["degree"]:
        facts.append(t["degree"][ex["degree_required"]])
    facts.append(t["english"] if ex.get("english_only") else t["dutch"] if ex.get("dutch_required") else "")
    facts.append(t["policy"].get(ex.get("remote_policy") or "", ""))
    if ex.get("visa_sponsorship") is True:
        facts.append(t["visa_yes"])
    elif ex.get("visa_sponsorship") is False:
        facts.append(t["visa_no"])
    if ex.get("enrollment_required") is True:
        facts.append(t["enrol"])
    lo, hi = ex.get("salary_min_eur"), ex.get("salary_max_eur")
    if lo and hi and hi > lo:
        facts.append(t["salary"].format(lo=money(lo), hi=money(hi)))
    elif lo:
        facts.append(t["salary_from"].format(lo=money(lo)))
    if sector and sector != "other":
        from radar.sectors import LABELS

        facts.insert(0, LABELS[lang][sector])
    from radar.positions import LABELS as POSITION_LABELS
    from radar.positions import position

    kind = position(p.title)
    if kind != "other":
        facts.insert(0, POSITION_LABELS[lang][kind])
    facts_html = "".join(f'<span class="chip">{escape(f)}</span>' for f in facts if f)

    req, nice = ex.get("skills_required") or [], ex.get("skills_nice") or []
    skills_html = ""
    if req:
        skills_html += f'<p class="small mb-1"><b>{t["skills"]}</b></p><div class="chips">' + "".join(
            f'<span class="chip have">{escape(s)}</span>' for s in req) + "</div>"
    if nice:
        skills_html += f'<p class="small mb-1"><b>{t["nice"]}</b></p><div class="chips">' + "".join(
            f'<span class="chip">{escape(s)}</span>' for s in nice) + "</div>"

    text = p.description or ""
    title = t["title"].format(t=p.title, c=p.company)
    summary = " ".join(text.split())
    desc = (title + (t["in"].format(x=city) if city else "") + ". " + summary)[:155].rstrip() + ("…" if summary else "")
    url_link = f'<a href="{escape(p.url)}" rel="noopener" target="_blank">{escape(host)}</a>'
    credit = escape(t["credit"]).replace("{c}", escape(p.company)).replace("{h}", escape(host)).replace("{u}", url_link)
    self_path = job_path(p.id, p.title, lang)
    closed = p.closed_at is not None

    # schema.org JobPosting, so the page can appear in Google's job search; left out once the vacancy is closed
    ld = ""
    if not closed and text:
        posting = {
            "@context": "https://schema.org", "@type": "JobPosting", "title": p.title,
            "description": _body(p), "datePosted": when.date().isoformat() if when else None,
            "hiringOrganization": {"@type": "Organization", "name": p.company},
            "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressCountry": "NL",
                                                          **({"addressLocality": p.city} if p.city else {})}},
            "url": base + self_path, "identifier": {"@type": "PropertyValue", "name": p.company,
                                                     "value": str(p.external_id)},
            "directApply": False,
        }
        if p.valid_through:
            posting["validThrough"] = p.valid_through.isoformat()
        if ex.get("remote_policy") == "remote" or p.remote:
            posting["jobLocationType"] = "TELECOMMUTE"
            posting["applicantLocationRequirements"] = {"@type": "Country", "name": "NL"}
        if lo:
            posting["baseSalary"] = {"@type": "MonetaryAmount", "currency": "EUR", "value": {
                "@type": "QuantitativeValue", "unitText": "YEAR", "minValue": lo, **({"maxValue": hi} if hi else {})}}
        posting = {k: v for k, v in posting.items() if v is not None}
        ld = ('<script type="application/ld+json">' + json.dumps(posting, ensure_ascii=False).replace("</", "<\\/")
              + "</script>")

    html = _template("job.html")
    for key, value in t.items():
        if isinstance(value, str):
            html = html.replace("{{L_" + key.upper() + "}}", escape(value))
    return _brand(html).replace("{{LANG}}", lang) \
        .replace("{{TITLE}}", escape(title)) \
        .replace("{{DESCRIPTION}}", escape(desc)) \
        .replace("{{SELF_PATH}}", self_path) \
        .replace("{{EN_PATH}}", job_path(p.id, p.title, "en")).replace("{{NL_PATH}}", job_path(p.id, p.title, "nl")) \
        .replace("{{EN_ON}}", " on" if lang == "en" else "").replace("{{NL_ON}}", " on" if lang == "nl" else "") \
        .replace("{{ROBOTS}}", '<meta name="robots" content="noindex, follow">' if closed else "") \
        .replace("{{JSONLD}}", ld) \
        .replace("{{HOME}}", "/nl/" if lang == "nl" else "/") \
        .replace("{{COMPANIES}}", "/companies") \
        .replace("{{CLOSED}}", f'<p class="card bad">{escape(t["closed"])}</p>' if closed else "") \
        .replace("{{JOB_TITLE}}", escape(p.title)) \
        .replace("{{META}}", meta) \
        .replace("{{FACTS}}", facts_html) \
        .replace("{{SKILLS}}", skills_html) \
        .replace("{{URL}}", escape(p.url)) \
        .replace("{{HOST}}", escape(host)) \
        .replace("{{COMPANY_PATH}}", company_path(slugify(p.company), lang)) \
        .replace("{{COMPANY}}", escape(p.company)) \
        .replace("{{CREDIT}}", credit) \
        .replace("{{TEXT}}", _body(p) or f'<p class="muted">{escape(t["no_text"])}</p>')


def _sector_label(rows: list[Row], lang: str) -> str:
    from radar.sectors import LABELS

    sector = next((r.sector for r in rows if r.sector and r.sector != "other"), None)
    return LABELS["nl" if lang == "nl" else "en"][sector] if sector else ""


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
