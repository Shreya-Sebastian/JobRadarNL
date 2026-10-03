"""The sector an employer works in: pharma, consultancy, government, banking and so on.

Three sources, in this order:
0. data/company_sectors.tsv: every employer on the radar when it was made, each read once (name, job titles, how
   it describes itself) and given a sector by hand. New employers are added when the table is next refreshed.
1. The employer lists the radar tracks (data/top100.yaml, data/seeds/top500.tsv, data/seeds/big_employers.tsv)
   give a sector for some 600 large employers; their many small categories map onto the sectors below. "Health"
   in those lists mixes hospitals and drug makers, so pharma is split off by name and text.
2. Every other employer is read from the opening of its own postings, where the employer describes itself ("wij
   zijn een adviesbureau", "a clinical-stage biotech company"): a sector needs at least two distinct signals and a
   clear lead over the next one, otherwise the employer is left as "other". Recruitment agencies are recognised by
   their source.

The result is stored per employer (table `employers`), refreshed nightly by the worker and by `radar sectors`.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

SECTORS = ["software", "consultancy", "hardware", "finance", "pharma", "health", "government", "education", "energy",
           "transport", "engineering", "industry", "retail", "telecom_media", "staffing", "other"]
LABELS = {
    "en": {"software": "Software & internet", "consultancy": "Consultancy & IT services",
           "hardware": "Semiconductors & hardware", "finance": "Banking, finance & insurance",
           "pharma": "Pharma & life sciences", "health": "Healthcare", "government": "Government & public sector",
           "education": "Education & research", "energy": "Energy & utilities", "transport": "Transport & logistics",
           "engineering": "Engineering & construction", "industry": "Industry & manufacturing",
           "retail": "Retail & consumer goods", "telecom_media": "Telecom & media",
           "staffing": "Recruitment agencies", "other": "Other"},
    "nl": {"software": "Software & internet", "consultancy": "Consultancy & IT-dienstverlening",
           "hardware": "Halfgeleiders & hardware", "finance": "Bank, financiën & verzekeringen",
           "pharma": "Farma & life sciences", "health": "Zorg", "government": "Overheid & publieke sector",
           "education": "Onderwijs & onderzoek", "energy": "Energie & nutsbedrijven",
           "transport": "Transport & logistiek",
           "engineering": "Ingenieursdiensten & bouw", "industry": "Industrie & productie",
           "retail": "Retail & consumentengoederen", "telecom_media": "Telecom & media",
           "staffing": "Werving & detachering", "other": "Overig"},
}

# the employer lists' own categories
_LIST_SECTOR = {
    "software": "software", "internet": "software", "bigtech": "software", "gaming": "software",
    "consulting": "consultancy", "semicon": "hardware", "hardware": "hardware", "hightech": "hardware",
    "finance": "finance", "health": "health", "government": "government", "education": "education",
    "university": "education", "research": "education", "energy": "energy", "transport": "transport",
    "logistics": "transport", "infra": "transport", "engineering": "engineering", "construction": "engineering",
    "chemicals": "industry", "industry": "industry", "food": "retail", "fmcg": "retail", "retail": "retail",
    "telecom": "telecom_media", "media": "telecom_media", "staffing": "staffing", "other": "other",
}

_PHARMA = re.compile(r"pharma|biotech|life sciences?|biopharma|geneesmiddel|medicines?|drug (?:discovery|development)|"
                     r"vaccin|therapeutics|clinical[- ]stage|diagnostics", re.I)

# how employers describe themselves, in Dutch and English
_TEXT = {k: re.compile(rx, re.I) for k, rx in {
    "pharma": _PHARMA.pattern + r"|\bmedtech\b|medical devices?",
    "health": r"ziekenhuis|hospital|zorginstelling|\bzorg(?:organisatie|verlener|aanbieder)|\bggz\b|umc\b|"
              r"medisch centrum|medical cent(?:er|re)|patiënten|patients|healthcare provider|verpleeg",
    "consultancy": r"adviesbureau|consultancy|consulting|consultants?\b|advisory|\bdetacher\w*|it[- ]dienstverle\w*|"
                   r"\bit services\b|system integrator|managed service provider|implementation partner|"
                   r"(?:microsoft|sap|salesforce|aws|google cloud) (?:gold )?partner|onze klanten|our clients",
    "finance": r"\bbank\b|banking|\bbanken\b|verzeker\w*|insurance|insurer|pensioen\w*|pension|asset manag\w*|"
               r"vermogensbeheer|fintech|payments?\b|trading firm|market maker|beleggings\w*|hypothe\w*|lending",
    "government": r"\bgemeente\b|ministerie|ministry|\brijks\w*|overheid|government|provincie|waterschap|"
                  r"publieke (?:sector|organisatie)|public sector|uitvoeringsorganisatie|defensie|politie|"
                  r"\bagentschap\b",
    "education": r"universiteit|university|hogeschool|\bonderwijs\w*|education|\bschool\b|research institute|"
                 r"onderzoeksinstituut|kennisinstelling|academic|\bphd\b",
    "energy": r"energie\w*|energy|netbeheerder|grid operator|elektriciteit|electricity|\bgas\b|renewables?|"
              r"wind ?(?:farm|park)|solar|duurzame energie|utilit(?:y|ies)|drinkwater|waterbedrijf",
    "transport": r"logisti\w*|transport\w*|airline|luchtvaart|aviation|airport|luchthaven|\bspoor\w*|railway|"
                 r"openbaar vervoer|public transport|shipping|haven|port of|supply chain|warehous\w*|parcel|pakket",
    "engineering": r"ingenieursbureau|engineering (?:firm|company|consultancy)|bouwbedrijf|construction|"
                   r"\binfra(?:structuur)?\b|bouw\w* en|aannemer|contractor|architectenbureau|civiele techniek",
    "industry": r"fabriek|factory|manufactur\w*|productiebedrijf|chemi\w*|machinebouw|maakindustrie|"
                r"production plants?|industrial company|food producer|voedingsmiddelen\w*",
    "retail": r"retail\w*|winkels?\b|webshop|e-?commerce|supermarkt|supermarket|consumer (?:brand|goods|products)|"
              r"fashion|merk(?:en)?\b|brands?\b|fmcg",
    "telecom_media": r"telecom\w*|mobile network|glasvezel|fibre|\bkabel\w*|broadcast\w*|omroep|media ?(?:company|"
                     r"bedrijf|organisatie)|uitgever\w*|publisher|krant|newspaper|news(?:room)?\b|streaming",
    "hardware": r"semiconductor|halfgeleider|chip\w*|lithograph\w*|photonic\w*|high[- ]tech (?:systems|company|"
                r"equipment)|hardware company|electronics manufacturer|machines? (?:for|that)",
    "software": r"\bsaas\b|software (?:company|bedrijf|product|platform)|scale-?up|start-?up|tech company|"
                r"techbedrijf|our (?:platform|app|product)|ons platform|app (?:used|gebruikt)|marketplace|"
                r"online platform",
}.items()}


_ABOUT_HEADER = re.compile(
    r"^(?:about us|about (?!the role|the job|the position|you\b|the team)[\w&.' -]{2,40}|company description|"
    r"who we are|our (?:company|story|mission)|the company|bedrijfsomschrijving|over ons|"
    r"over (?!de functie|de rol|jou)[\w&.' -]{2,40}|"
    r"wie zijn (?:wij|we)|onze missie|hier ga je werken|waar ga je werken|de organisatie|organisatie)$", re.I)
_SELF = re.compile(r"\b(?:wij zijn|we zijn|we are|we're|ons bedrijf|our company|is een|is a|is an|is the|"
                   r"zijn een|are a|are an|als (?:toonaangevend|grootste|internationaal)|"
                   r"as (?:a|the) (?:leading|global|world))\b", re.I)


def self_description(company: str, text: str, limit: int = 2000) -> str:
    """The parts of a posting where the employer describes itself: an "about us" section, the opening prose
    before the first header, and sentences such as "<company> is a ..." or "Wij zijn ..."."""
    from radar.extract.sections import _ROLE_CUE, _header

    kept: list[str] = []
    zone, seen_header = "intro", False
    name = (company or "").split()[0].lower() if company else ""
    for line in (text or "").splitlines():
        t = line.strip()
        if not t:
            continue
        h = _header(t)
        if h or _ABOUT_HEADER.match(t.strip("#*•-–: ").rstrip(":?! ")):
            seen_header = True
            zone = "about" if _ABOUT_HEADER.match(t.strip("#*•-–: ").rstrip(":?! ")) else "other"
            continue
        if zone == "about" or (zone == "intro" and not seen_header and not _ROLE_CUE.search(t)):
            kept.append(t)
        elif _SELF.search(t) and (not name or name in t.lower() or re.search(r"\b(?:wij|we|ons|our)\b", t, re.I)):
            kept.append(t)
        if sum(len(x) for x in kept) > limit:
            break
    return "\n".join(kept)[:limit]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


@lru_cache(maxsize=1)
def _known() -> list[tuple[str, str, str]]:
    """(name, match fragment, sector) from the employer lists. A fragment "=x" must equal the name."""
    from radar.config import settings

    out: list[tuple[str, str, str]] = []
    data = Path(settings.data_dir)
    try:
        import yaml

        for e in yaml.safe_load((data / "top100.yaml").read_text(encoding="utf-8")) or []:
            for m in e.get("match") or [e["name"]]:
                out.append((e["name"], str(m), _LIST_SECTOR.get(e.get("group") or "", "other")))
    except Exception:
        pass
    for fname, col in (("seeds/top500.tsv", 4), ("seeds/big_employers.tsv", 3)):
        try:
            for line in (data / fname).read_text(encoding="utf-8").splitlines():
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) > col:
                    for m in parts[1].split(","):
                        if m.strip():
                            out.append((parts[0], m.strip(), _LIST_SECTOR.get(parts[col].strip(), "other")))
        except Exception:
            continue
    return out


@lru_cache(maxsize=1)
def _curated() -> dict[str, str]:
    from radar.config import settings

    out: dict[str, str] = {}
    try:
        for line in (Path(settings.data_dir) / "company_sectors.tsv").read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                company, sector = line.split("\t")[:2]
                if sector in SECTORS:
                    out[company] = sector
    except FileNotFoundError:
        pass
    return out


def listed_sector(company: str) -> str | None:
    """The sector the employer lists give this employer, when one of them matches its name."""
    name = _norm(company)
    best: tuple[int, str] | None = None
    for _, frag, sector in _known():
        if frag.startswith("="):
            hit = name == _norm(frag[1:])
        else:
            f = _norm(frag)  # whole words only: "ing" must not match "consulting"
            hit = bool(f) and re.search(rf"(?:^| ){re.escape(f)}(?: |$)", name) is not None
        if hit and (best is None or len(frag) > best[0]):  # the longest (most specific) fragment wins
            best = (len(frag), sector)
    return best[1] if best else None


def text_sector(company: str, text: str) -> str | None:
    """The sector the employer's own words point to, or None when they do not say clearly enough."""
    blob = f"{company}\n{text or ''}"
    scores = Counter({k: len({m.group(0).lower() for m in rx.finditer(blob)}) for k, rx in _TEXT.items()})
    (best, n), *rest = scores.most_common(2) + [("", 0)]
    second = rest[0][1] if rest else 0
    return best if n >= 2 and n >= second + 1 and n >= 1.5 * second else None


def sector_for(company: str, intro: str, kind: str = "employer") -> tuple[str, str]:
    """(sector, how it was found) for one employer: the curated table, the lists, the agency flag, its own words."""
    curated = _curated().get(company)
    if curated:
        return curated, "curated"
    listed = listed_sector(company)
    if listed == "health" and _PHARMA.search(f"{company} {intro}"):
        return "pharma", "list+text"
    if listed:
        return listed, "list"
    if kind == "agency":
        return "staffing", "source"
    found = text_sector(company, intro)
    return (found, "text") if found else ("other", "none")


def refresh(session) -> dict[str, int]:
    """Recompute every live employer's sector from the lists and the opening of up to three of its postings."""
    from sqlalchemy import delete, func, select

    from radar.models import Employer, Posting, Source

    intros: dict[str, list[str]] = defaultdict(list)
    kinds: dict[str, str] = {}
    q = (select(Posting.company, func.substr(Posting.description, 1, 12000), Source.kind)
         .join(Source, Source.id == Posting.source_id)
         .where(Posting.closed_at.is_(None), Posting.duplicate_of.is_(None), Posting.is_tech.is_(True))
         .execution_options(yield_per=500))
    for company, text, kind in session.execute(q):
        if len(intros[company]) < 5:
            intros[company].append(self_description(company, text or ""))
        kinds.setdefault(company, kind or "employer")
    counts: Counter = Counter()
    rows = []
    for company, texts in intros.items():
        sector, how = sector_for(company, "\n".join(texts), kinds.get(company, "employer"))
        rows.append(Employer(company=company[:200], sector=sector, sector_source=how))
        counts[how] += 1
    session.execute(delete(Employer))
    session.add_all(rows)
    session.flush()
    counts["employers"] = len(rows)
    return dict(counts)


def load_map(session) -> dict[str, str]:
    from sqlalchemy import select

    from radar.models import Employer

    try:
        return dict(session.execute(select(Employer.company, Employer.sector)).all())
    except Exception:
        return {}
