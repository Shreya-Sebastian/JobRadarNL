"""Source registry: seed and update the `sources` table from probe results, YAML files or discovery."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.models import Source


def upsert_source(session: Session, company: str, ats: str, slug: str, url: str | None = None,
                  discovered_by: str = "seed", kind: str | None = None) -> tuple[Source, bool]:
    existing = session.scalar(select(Source).where(Source.ats == ats, Source.slug == slug))
    if existing:
        if url and not existing.url:
            existing.url = url
        if kind and existing.kind != kind:
            existing.kind = kind
        return existing, False
    kind = kind or classify_source(company, slug)
    off = kind in ("aggregator", "test")
    src = Source(company=company, ats=ats, slug=slug, url=url, discovered_by=discovered_by, kind=kind,
                 active=not off, last_status=kind if off else None)
    session.add(src)
    session.flush()
    return src, True


def seed_from_probe(session: Session, path: str | Path, min_total: int = 1) -> int:
    hits = json.loads(Path(path).read_text(encoding="utf-8"))
    created = 0
    for h in hits:
        if h.get("total", 0) < min_total:
            continue
        _, new = upsert_source(session, _pretty(h["company"]), h["ats"], h["slug"], discovered_by="probe")
        created += int(new)
    return created


def seed_from_yaml(session: Session, path: str | Path) -> int:
    """YAML format: a list of {company, ats, slug, url?} mappings."""
    entries = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    created = 0
    for e in entries:
        _, new = upsert_source(session, e["company"], e["ats"], str(e["slug"]), e.get("url"), discovered_by="seed",
                               kind=e.get("kind"))
        created += int(new)
    return created


def load_source_kinds(path: str | Path | None = None) -> dict[str, list[str]]:
    from radar.config import settings

    path = Path(path) if path else Path(settings.data_dir) / "source_kinds.yaml"
    if not path.exists():
        return {"aggregator": [], "agency": [], "board": [], "test": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {k: [str(v).lower() for v in data.get(k, [])] for k in ("aggregator", "agency", "board", "test")}


_TEST_SLUG = re.compile(
    r"^(acmecorp|acme-?corp|demo|sandbox|example|sample|dummy|playground)([-_]?\w*)?$"  # acmecorp091614, demo-x
    r"|^(test|testing)([-_]\w*)?$"                                                        # test, test-company
    r"|[-_](demo|sandbox|test|testing)$",                                                  # acme-sandbox
    re.I,
)


def looks_like_test_board(company: str, slug: str) -> bool:
    """Vendor demo tenants (SmartRecruiters' AcmeCorp091614) and sandbox boards are not employers."""
    return bool(_TEST_SLUG.search(slug) or _TEST_SLUG.search(company.replace(" ", "")))


def classify_source(company: str, slug: str, kinds: dict[str, list[str]] | None = None) -> str:
    """employer | agency | aggregator | board, from exact matches first, then substrings of slug or name.
    A board hosts many employers' own postings (universities on AcademicTransfer, ministries on
    werkenvoornederland); an aggregator re-posts jobs that exist elsewhere."""
    kinds = kinds or load_source_kinds()
    slug_l, name_l = slug.lower(), company.lower()
    for kind in ("board", "aggregator", "agency", "test"):
        if slug_l in kinds[kind] or name_l in kinds[kind]:
            return kind
    if looks_like_test_board(company, slug):
        return "test"
    for kind in ("board", "aggregator", "agency", "test"):
        for needle in kinds[kind]:
            if len(needle) >= 6 and (needle in slug_l or needle in name_l):
                return kind
    return "employer"


def apply_source_kinds(session: Session) -> dict[str, int]:
    """Label every source; deactivate aggregators and close their open postings."""
    from datetime import datetime

    from radar.models import Posting

    kinds = load_source_kinds()
    counts = {"employer": 0, "agency": 0, "aggregator": 0, "board": 0, "test": 0, "postings_closed": 0}
    for src in session.scalars(select(Source)):
        kind = classify_source(src.company, src.slug, kinds)
        if kind == "employer" and any((p.url or "").split("/")[2:3] == [h] for p in src.postings[:3]
                                      for h in ("test.com", "example.com", "localhost")):
            kind = "test"
        src.kind = kind
        counts[kind] += 1
        if kind in ("aggregator", "test") and src.active:
            src.active = False
            src.last_status = kind
            for p in session.scalars(select(Posting).where(Posting.source_id == src.id, Posting.closed_at.is_(None))):
                p.closed_at = datetime.utcnow()
                counts["postings_closed"] += 1
    session.flush()
    return counts


_PRETTY = {
    "imc": "IMC Trading", "asml": "ASML", "nxp": "NXP", "ing": "ING", "kpn": "KPN", "tno": "TNO", "n8n": "n8n",
    "abnamro": "ABN AMRO", "schubergphilis": "Schuberg Philis", "flowtraders": "Flow Traders",
    "remotecom": "Remote", "jetbrains": "JetBrains", "hellofresh": "HelloFresh", "grafanalabs": "Grafana Labs",
    "mongodb": "MongoDB", "uipath": "UiPath", "deepl": "DeepL", "vandebron": "Vandebron", "sqills": "Sqills",
    "nmbrs": "Nmbrs", "tomtom": "TomTom", "bunq": "bunq", "wetransfer": "WeTransfer", "gitlab": "GitLab",
    "justeattakeaway": "Just Eat Takeaway", "picnictechnologies": "Picnic", "bookingcom": "Booking.com",
    "messagebird": "Bird", "deptagency": "DEPT", "prodrivetechnologies": "Prodrive Technologies",
    "siouxtechnologies": "Sioux Technologies", "chargepoint": "ChargePoint", "bigquery": "BigQuery",
    "deloittenetherlands": "Deloitte", "soprasteria1": "Sopra Steria", "kpmgnederland": "KPMG",
    "xebiacareers": "Xebia", "accenture": "Accenture", "bjakcareer": "Bjak", "fridayrecruitment": "Friday Recruitment",
    "interstellargroup": "Interstellar Group", "vdkgroep": "VDK Groep", "urbansportsclub": "Urban Sports Club",
    "lighting": "Signify", "philips": "Philips", "shell": "Shell", "iodigital": "iO", "eurofins": "Eurofins",
    "sia": "Sia", "tsmg": "TSMG", "nn": "NN Group",
}


_NAME_NOISE = re.compile(
    r"^(careers?|jobs?|vacatures?|werkenbij|werken|recruitment|recruiting|talent|hiring|nederland|netherlands|"
    r"holland|benelux|europe|global|group|groep|bv|nv|inc|ltd|llc|gmbh|hq|external|internal|en|nl|com|org)$",
    re.I,
)
# suffixes safe to strip from a glued slug ("deloittenetherlands"); short ones like "en" or "nl" would maim names
_GLUED_SUFFIX = re.compile(
    r"(careers?|jobs?|vacatures?|werkenbij|recruitment|recruiting|talent|hiring|nederland|netherlands|holland|"
    r"benelux|europe|global|group|groep)$",
    re.I,
)
_KNOWN_WORDS = [
    "deloitte", "sopra", "steria", "kpmg", "xebia", "accenture", "capgemini", "philips", "rabobank", "heineken",
    "unilever", "booking", "coolblue", "picnic", "adyen", "mollie", "bunq", "signify", "vanderlande", "thermo",
    "fisher", "eurofins", "sweco", "conclusion", "centric", "schuberg", "philis", "datadog", "databricks", "elastic",
    "gitlab", "jetbrains", "mendix", "backbase", "catawiki", "fastned", "priva", "nedap", "topicus", "exact",
    "eneco", "vattenfall", "alliander", "randstad", "young", "capital", "ordina", "atos", "cognizant", "infosys",
    "wipro", "tcs", "microsoft", "google", "amazon", "oracle", "cisco", "shell", "asml", "nxp", "besi", "ampleon",
    "sioux", "prodrive", "lely", "vdl", "damen", "fugro", "thales", "canon", "kramp", "bol", "ahold", "jumbo",
    "wehkamp", "hema", "action", "rituals", "nike", "tesla", "uber", "netflix", "miro", "framer", "bynder",
    "channable", "sendcloud", "leaseweb", "transip", "trengo", "bitvavo", "optiver", "imc", "flow", "traders",
    "achmea", "aegon", "apg", "pggm", "asr", "knab", "triodos", "ing", "abn", "amro", "kpn", "odido", "ziggo",
    "vodafone", "tomtom", "just", "eat", "takeaway", "marktplaats", "zalando", "ns", "klm", "schiphol",
    "prorail", "tennet", "stedin", "essent", "dsm", "belastingdienst", "uwv", "duo", "politie", "tno", "surf",
]


def pretty_company(slug: str, name: str | None = None) -> str:
    """Turn a board slug such as 'deloittenetherlands', 'accenture.wd103/AccentureCareers' or
    'kpmg-nederland' into a display name. Used for employer boards; multi-employer boards attribute per posting."""
    key = slug.lower()
    if key in _PRETTY:
        return _PRETTY[key]
    if key.startswith("http"):                       # sitemap / careers-page sources keep their given name
        if name:
            return name.strip()
        host = re.sub(r"^https?://(www\.)?", "", key).split("/")[0]
        key = host.replace("careers.", "").replace("jobs.", "").replace("werkenbij.", "").split(".")[0]
    elif "/" in key and "." in key.split("/")[0]:     # workday: tenant.wdN/site -> tenant
        key = key.split("/")[0].split(".")[0]
    if key in _PRETTY:
        return _PRETTY[key]
    if name and " " in name.strip() and not re.fullmatch(r"[a-z0-9-]+", name.lower()):
        return name.strip()                          # already a real name with spacing/case
    base = re.sub(r"[-_.]+", " ", key).strip()
    base = re.sub(r"\d+$", "", base).strip()
    words = base.split()
    if len(words) == 1:                              # glued words: "deloittenetherlands" -> "deloitte netherlands"
        w = words[0]
        for _ in range(3):
            m = _GLUED_SUFFIX.search(w)
            if m and m.start() >= 3:
                w = w[: m.start()]
            else:
                break
        found = []
        rest = w
        for known in sorted(_KNOWN_WORDS, key=len, reverse=True):
            if rest.startswith(known) and len(rest) > len(known) + 2:
                found.append(known)
                rest = rest[len(known):]
        words = found + [rest] if found else [w]
    cleaned = [x for x in words if not _NAME_NOISE.fullmatch(x)] or words
    upper = {"asml", "nxp", "kpmg", "ing", "abn", "amro", "kpn", "imc", "vdl", "dsm", "apg", "pggm", "asr", "uwv",
             "duo", "tno", "surf", "ns", "klm", "hema", "tcs", "ibm", "sap", "cgi", "pwc", "ey", "nn"}
    return " ".join(x.upper() if x in upper else x[:1].upper() + x[1:] for x in cleaned)


def _pretty(slug_or_name: str) -> str:
    return pretty_company(slug_or_name)


def rename_employers(session: Session) -> int:
    """Recompute display names for employer sources and their postings, then apply the curated names
    (data/company_names.tsv) to every source and posting. Returns the number of sources and postings renamed."""
    from radar.models import Posting
    from radar.normalize import company_names

    renamed = 0
    for src in session.scalars(select(Source).where(Source.kind == "employer")):
        new = pretty_company(src.slug, src.company)
        if new and new != src.company:
            for p in session.scalars(select(Posting).where(Posting.source_id == src.id)):
                p.company = new
            src.company = new
            renamed += 1
    names = company_names()
    if names:
        for src in session.scalars(select(Source).where(Source.company.in_(list(names)))):
            src.company = names[src.company]
            renamed += 1
        for p in session.scalars(select(Posting).where(Posting.company.in_(list(names)))):
            p.company = names[p.company]
            renamed += 1
    session.flush()
    return renamed
