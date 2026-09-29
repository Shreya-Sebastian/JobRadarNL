"""Search landing pages: the searches people actually make, in the language they make them.

Dutch job seekers search "ICT vacatures Amsterdam", "data vacatures Utrecht", "traineeship ICT"; international
ones search "tech jobs Amsterdam", "English speaking jobs Netherlands", "visa sponsorship tech jobs". Each landing
page answers one of those with data only this radar has (live counts, skills asked for, how many need no Dutch,
visa mentions, stated salaries, the employers hiring) and the newest listings, each linking to the employer's own
page. Pages below a minimum number of postings are not generated, so no thin template pages exist; that is what
Google's 2026 scaled-content rules penalise in job aggregators.

Dutch pages live under /vacatures/, English ones under /jobs/, paired with hreflang.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path

from radar import stats
from radar.config import settings

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
MIN_POSTINGS = 8
MIN_POSTINGS_COMBO = 20

ROLES = {  # key: (role families, nl name, en name)
    "software-developer": ("backend,frontend,fullstack,mobile", "Software developer", "Software developer"),
    "data": ("data", "Data", "Data"),
    "ai-machine-learning": ("ml", "AI en machine learning", "AI and machine learning"),
    "cloud-devops": ("platform", "Cloud en DevOps", "Cloud and DevOps"),
    "cybersecurity": ("security", "Cybersecurity", "Cybersecurity"),
    "embedded-hardware": ("embedded", "Embedded en hardware", "Embedded and hardware"),
    "test-qa": ("qa", "Test en QA", "Test and QA"),
    "product-owner": ("product", "Product owner", "Product owner"),
    "it-support": ("it_support", "IT support en systeembeheer", "IT support"),
    "simulation": ("simulation", "Simulatie en computational", "Simulation and computational"),
}
THEMES = {  # key: (filter kwargs, nl slug, en slug, nl title, en title)
    "english": (
        {"language": "en"},
        "engelstalig",
        "english-speaking",
        "Engelstalige IT vacatures{in_nl}",
        "English-speaking tech jobs{in_en}",
    ),
    "visa": (
        {"sponsorship": True},
        "visumsponsoring",
        "visa-sponsorship",
        "IT vacatures met visumsponsoring{in_nl}",
        "Tech jobs with visa sponsorship{in_en}",
    ),
    "junior": (
        {"seniority": "junior,trainee", "experience": "none,1"},
        "junior-starter",
        "junior",
        "Junior IT vacatures en startersfuncties{in_nl}",
        "Junior and entry-level tech jobs{in_en}",
    ),
    "trainee": (
        {"seniority": "trainee"},
        "traineeship",
        "graduate-traineeship",
        "ICT traineeships en graduate programma's{in_nl}",
        "Tech traineeships and graduate programmes{in_en}",
    ),
    "intern": (
        {"seniority": "intern"},
        "stage",
        "internship",
        "ICT stages en afstudeerstages{in_nl}",
        "Tech internships{in_en}",
    ),
    "remote": ({"remote": "remote"}, "remote", "remote", "Remote IT vacatures{in_nl}", "Remote tech jobs{in_en}"),
}
CITY_NL = {"The Hague": "Den Haag", "'s-Hertogenbosch": "Den Bosch"}


def city_nl(c: str) -> str:
    return CITY_NL.get(c, c)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower().replace("'s-", "s-")).strip("-")


@dataclass
class Page:
    key: str
    nl_path: str
    en_path: str
    nl_title: str
    en_title: str
    filters: dict
    city: str | None = None
    role: str | None = None
    theme: str | None = None
    count: int = 0


def _filtered(rows: list[stats.Row], filters: dict, city: str | None) -> list[stats.Row]:
    kw = dict(filters)
    if city:
        kw["city"] = city
    return stats.Filters(**kw).apply(rows)


def build_pages(rows: list[stats.Row]) -> list[Page]:
    live = [r for r in rows if r.closed_at is None]
    cities = [c for c, n in Counter(r.city for r in live if r.city).most_common(14) if n >= MIN_POSTINGS]
    pages: list[Page] = []

    def add(page: Page, minimum: int) -> None:
        page.count = len(_filtered(live, page.filters, page.city))
        if page.count >= minimum:
            pages.append(page)

    for c in cities:
        add(
            Page(
                f"city:{c}",
                f"/vacatures/ict-{slug(city_nl(c))}",
                f"/jobs/tech-{slug(c)}",
                f"ICT vacatures {city_nl(c)}",
                f"Tech jobs in {c}",
                {},
                city=c,
            ),
            MIN_POSTINGS,
        )
    for key, (families, nl, en) in ROLES.items():
        add(
            Page(
                f"role:{key}",
                f"/vacatures/{key}",
                f"/jobs/{key}",
                f"{nl} vacatures",
                f"{en} jobs in the Netherlands",
                {"role": families},
                role=key,
            ),
            MIN_POSTINGS,
        )
        for c in cities[:8]:
            add(
                Page(
                    f"role:{key}:{c}",
                    f"/vacatures/{key}-{slug(city_nl(c))}",
                    f"/jobs/{key}-{slug(c)}",
                    f"{nl} vacatures {city_nl(c)}",
                    f"{en} jobs in {c}",
                    {"role": families},
                    city=c,
                    role=key,
                ),
                MIN_POSTINGS_COMBO,
            )
    for key, (filters, nl_slug, en_slug, nl_t, en_t) in THEMES.items():
        add(
            Page(
                f"theme:{key}",
                f"/vacatures/{nl_slug}",
                f"/jobs/{en_slug}",
                nl_t.format(in_nl=""),
                en_t.format(in_en=" in the Netherlands"),
                filters,
                theme=key,
            ),
            MIN_POSTINGS,
        )
        if key in ("english", "visa", "junior"):
            for c in cities[:6]:
                add(
                    Page(
                        f"theme:{key}:{c}",
                        f"/vacatures/{nl_slug}-{slug(city_nl(c))}",
                        f"/jobs/{en_slug}-{slug(c)}",
                        nl_t.format(in_nl=f" {city_nl(c)}"),
                        en_t.format(in_en=f" in {c}"),
                        filters,
                        city=c,
                        theme=key,
                    ),
                    MIN_POSTINGS_COMBO,
                )
    return pages


def find(pages: list[Page], path: str) -> tuple[Page, str] | None:
    path = path.rstrip("/")
    for p in pages:
        if p.nl_path == path:
            return p, "nl"
        if p.en_path == path:
            return p, "en"
    return None


_T = {
    "nl": {
        "open": "open vacatures",
        "employers": "werkgevers",
        "no_dutch": "zonder Nederlands",
        "visa": "noemen visumsponsoring",
        "entry": "voor starters",
        "updated": "bijgewerkt",
        "skills": "Meest gevraagde skills",
        "hiring": "Wie neemt aan",
        "cities": "Steden",
        "salary": "Vermeld salaris (bruto per jaar)",
        "median": "mediaan",
        "of": "van",
        "stated": "vacatures die een bedrag noemen",
        "newest": "Nieuwste vacatures",
        "related": "Ook bekijken",
        "interactive": "Open de interactieve weergave",
        "interactive_hint": "met filters, matchscore en grafieken",
        "lang_other": "English",
        "home": "Alle tech vacatures",
        "intro": "{n} open vacatures bij {m} werkgevers, rechtstreeks gelezen van hun eigen carrièresites en elke paar "
        "uur bijgewerkt. Elke vacature linkt naar de originele pagina van de werkgever.",
        "th": ["Functie", "Werkgever", "Plaats", "Niveau", "Taal", "Leeftijd"],
        "today": "vandaag",
        "days": "{d} d",
    },
    "en": {
        "open": "open roles",
        "employers": "employers",
        "no_dutch": "need no Dutch",
        "visa": "mention visa sponsorship",
        "entry": "entry level",
        "updated": "updated",
        "skills": "Most requested skills",
        "hiring": "Who is hiring",
        "cities": "Cities",
        "salary": "Stated salaries (gross per year)",
        "median": "median",
        "of": "of",
        "stated": "postings that state an amount",
        "newest": "Newest openings",
        "related": "See also",
        "interactive": "Open the interactive view",
        "interactive_hint": "with filters, match scores and charts",
        "lang_other": "Nederlands",
        "home": "All tech jobs",
        "intro": "{n} open roles at {m} employers, read directly from their own career sites and refreshed every few "
        "hours. Every listing links to the employer's original page.",
        "th": ["Role", "Employer", "City", "Level", "Language", "Age"],
        "today": "today",
        "days": "{d}d",
    },
}


def _entry(r: stats.Row) -> bool:
    return r.ex.get("seniority") in ("intern", "trainee", "junior") or r.experience in ("none", "1")


def render(page: Page, lang: str, rows: list[stats.Row], pages: list[Page]) -> str:
    from radar.pages import company_path, slugify

    T = _T[lang]
    base = settings.site_url.rstrip("/")
    mine = sorted(
        _filtered([r for r in rows if r.closed_at is None], page.filters, page.city),
        key=lambda r: r.posted_at or r.first_seen,
        reverse=True,
    )
    n = len(mine)
    employers = Counter(r.company for r in mine)
    skills = Counter(s for r in mine for s in r.skills)
    no_dutch = sum(1 for r in mine if r.ex.get("english_only"))
    visa = sum(1 for r in mine if r.ex.get("visa_sponsorship") is True)
    entry = sum(1 for r in mine if _entry(r))
    sal = stats.salary(mine)
    title = page.nl_title if lang == "nl" else page.en_title
    path = page.nl_path if lang == "nl" else page.en_path
    other = page.en_path if lang == "nl" else page.nl_path
    pct = lambda k: f"{round(100 * k / n)}%" if n else "0%"  # noqa: E731

    kpis = [
        (n, T["open"]),
        (len(employers), T["employers"]),
        (pct(no_dutch), T["no_dutch"]),
        (visa, T["visa"]),
        (entry, T["entry"]),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><b>{escape(str(v))}</b><span>{escape(label)}</span></div>' for v, label in kpis
    )
    skill_html = "".join(
        f'<span class="chip">{escape(s)} <span class="muted">{round(100 * c / n)}%</span></span>'
        for s, c in skills.most_common(12)
    )
    emp_html = "".join(
        f'<li><a href="{company_path(slugify(e), lang)}">{escape(e)}</a> <span class="muted">{c}</span></li>'
        for e, c in employers.most_common(10)
    )
    city_html = ""
    if not page.city:
        by_city = Counter(r.city for r in mine if r.city).most_common(8)
        links = {
            p.city: (p.nl_path if lang == "nl" else p.en_path)
            for p in pages
            if p.city and p.role == page.role and p.theme == page.theme
        }
        items = []
        for c, k in by_city:
            label = city_nl(c) if lang == "nl" else c
            href = links.get(c)
            items.append(
                f"<li>{f'<a href={chr(34)}{href}{chr(34)}>{escape(label)}</a>' if href else escape(label)} "
                f'<span class="muted">{k}</span></li>'
            )
        city_html = f'<div class="card"><h2>{T["cities"]}</h2><ul class="cols">{"".join(items)}</ul></div>'
    sal_html = ""
    if sal.get("n", 0) >= 10:
        sal_html = (
            f'<p class="small"><b>{T["salary"]}:</b> {T["median"]} €{sal["median"]:,} '
            f"(p25 €{sal['p25']:,}, p75 €{sal['p75']:,}), {sal['n']} {T['stated']}.</p>"
        ).replace(",", ".")

    def level(r: stats.Row) -> str:
        s = r.ex.get("seniority") or ""
        return "" if s == "unknown" else s

    def age(r: stats.Row) -> str:
        d = max(0, (datetime.utcnow() - (r.posted_at or r.first_seen)).days)
        return T["today"] if d == 0 else T["days"].format(d=d)

    rows_html = "".join(
        f'<tr><td><a href="{escape(r.url)}" rel="noopener">{escape(r.title)}</a></td>'
        f'<td><a href="{company_path(slugify(r.company), lang)}">{escape(r.company)}</a></td>'
        f"<td>{escape(city_nl(r.city) if lang == 'nl' and r.city else (r.city or ''))}</td>"
        f"<td>{escape(level(r))}</td><td>{'EN' if r.ex.get('english_only') else 'NL'}</td>"
        f'<td class="muted">{age(r)}</td></tr>'
        for r in mine[:50]
    )
    related = [
        p
        for p in pages
        if p is not page
        and (
            (page.city and p.city == page.city and not (p.role and p.theme))
            or (page.role and p.role == page.role)
            or (page.theme and p.theme == page.theme)
            or (not page.city and not p.city and not (p.role and p.city))
        )
    ]
    related = sorted(related, key=lambda p: -p.count)[:14]
    rel_html = "".join(
        f'<li><a href="{p.nl_path if lang == "nl" else p.en_path}">'
        f'{escape(p.nl_title if lang == "nl" else p.en_title)}</a> <span class="muted">{p.count}</span></li>'
        for p in related
    )
    top = ", ".join(s for s, _ in skills.most_common(4))
    if lang == "nl":
        desc = (
            f"{title}: {n} vacatures bij {len(employers)} werkgevers, rechtstreeks van hun eigen sites. "
            f"{pct(no_dutch)} zonder Nederlands{f', gevraagd: {top}' if top else ''}. Dagelijks bijgewerkt."
        )
    else:
        desc = (
            f"{title}: {n} open roles at {len(employers)} employers, straight from their own career sites. "
            f"{pct(no_dutch)} need no Dutch{f'; top skills {top}' if top else ''}. Updated daily."
        )
    ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "CollectionPage",
                "name": title,
                "url": base + path,
                "inLanguage": lang,
                "description": desc,
                "isPartOf": {"@type": "WebSite", "name": settings.site_name, "url": base},
                "mainEntity": {
                    "@type": "ItemList",
                    "numberOfItems": n,
                    "itemListElement": [
                        {"@type": "ListItem", "position": i + 1, "url": r.url, "name": r.title}
                        for i, r in enumerate(mine[:30])
                    ],
                },
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": 1,
                        "name": settings.site_name,
                        "item": base + ("/nl/" if lang == "nl" else "/"),
                    },
                    {"@type": "ListItem", "position": 2, "name": title, "item": base + path},
                ],
            },
        ],
    }
    html = (WEB_DIR / "landing.html").read_text(encoding="utf-8")
    reps = {
        "{{LANG}}": lang,
        "{{TITLE}}": escape(title),
        "{{COUNT}}": str(n),
        "{{SITE_NAME}}": escape(settings.site_name),
        "{{SITE_URL}}": base,
        "{{PATH}}": path,
        "{{NL_PATH}}": page.nl_path,
        "{{EN_PATH}}": page.en_path,
        "{{OTHER_PATH}}": other,
        "{{OTHER_LANG}}": T["lang_other"],
        "{{DESCRIPTION}}": escape(desc),
        "{{INTRO}}": escape(T["intro"].format(n=n, m=len(employers))),
        "{{KPIS}}": kpi_html,
        "{{SKILLS_H}}": T["skills"],
        "{{SKILLS}}": skill_html,
        "{{HIRING_H}}": T["hiring"],
        "{{EMPLOYERS}}": emp_html,
        "{{CITIES}}": city_html,
        "{{SALARY}}": sal_html,
        "{{NEWEST_H}}": T["newest"],
        "{{ROWS}}": rows_html,
        "{{TH}}": "".join(f"<th>{h}</th>" for h in T["th"]),
        "{{RELATED_H}}": T["related"],
        "{{RELATED}}": rel_html,
        "{{INTERACTIVE}}": T["interactive"],
        "{{INTERACTIVE_HINT}}": T["interactive_hint"],
        "{{HOME}}": ("/nl/" if lang == "nl" else "/"),
        "{{HOME_LABEL}}": T["home"],
        "{{UPDATED}}": f"{T['updated']} {datetime.utcnow():%Y-%m-%d}",
        "{{JSONLD}}": json.dumps(ld, ensure_ascii=False),
        "{{VERIFY}}": verification_meta(),
    }
    for k, v in reps.items():
        html = html.replace(k, v)
    return html


def verification_meta() -> str:
    token = settings.google_site_verification
    return f'<meta name="google-site-verification" content="{escape(token)}">' if token else ""


def popular_links(pages: list[Page], lang: str, limit: int = 18) -> str:
    """Footer links on the home page: helps visitors, and helps crawlers find the landing pages."""
    chosen = sorted(pages, key=lambda p: -p.count)[:limit]
    return " · ".join(
        f'<a href="{p.nl_path if lang == "nl" else p.en_path}">{escape(p.nl_title if lang == "nl" else p.en_title)}</a>'
        for p in chosen
    )
