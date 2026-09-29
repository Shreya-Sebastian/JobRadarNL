"""Pair the Dutch and English copies of one vacancy on bilingual career sites.

Some employers (TNO, many universities and ministries) publish every vacancy twice: once under /nl/ and once
under /en/, with a translated title and a different URL. The regular duplicate rules key on employer + title +
city, so a translated title slips through and the dashboard shows the job twice.

Within one source, a Dutch-path and an English-path posting are the same job when they were posted on the same
day in the same city and either their titles are near-identical after removing language-specific prefixes
("Stage |" vs "Internship |") or they share most of their numbers (salary, hours, dates, reference numbers)
and their titles still look alike. Pairing is one-to-one and greedy on the combined score, so two different
Dutch jobs can never both collapse onto one English job.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_LANG_PATH = re.compile(r"^https?://[^/]+/(en|nl|en-[a-z]{2}|nl-[a-z]{2})(?:/|$)", re.I)
_PREFIX = re.compile(r"^(?:stage|internship|afstudeerstage|graduation internship|vacature|vacancy)\s*[|:–-]\s*",
                     re.I)
_NUM = re.compile(r"\d[\d.,]*\d|\d{2,}")
# common Dutch-English title cognates, so "Defensie" and "Defence" count as the same word
_COGNATES = {"defensie": "defence", "onderzoeker": "researcher", "medewerker": "employee", "stage": "internship",
             "afdeling": "department", "coördinator": "coordinator", "coordinator": "coordinator",
             "ingenieur": "engineer", "netwerk": "network", "militaire": "military", "energie": "energy",
             "materialentransitie": "materials transition", "divisie": "division", "februari": "february"}


def path_language(url: str) -> str | None:
    m = _LANG_PATH.match(url or "")
    return m.group(1).lower()[:2] if m else None


def _norm_title(title: str) -> str:
    t = _PREFIX.sub("", (title or "").lower()).replace("&amp;", "&")
    words = re.findall(r"[a-z0-9àáäéèëïíóöüú]+", t)
    return " ".join(_COGNATES.get(w, w) for w in words)


def _numbers(text: str) -> set[str]:
    return set(_NUM.findall(text or ""))


def score(nl: dict, en: dict) -> float:
    """0..1 similarity of two postings already known to share source, date and city."""
    title = SequenceMatcher(None, _norm_title(nl["title"]), _norm_title(en["title"])).ratio()
    a, b = _numbers(nl["description"]), _numbers(en["description"])
    nums = len(a & b) / len(a | b) if (a or b) else 0.0
    if title < 0.45 and nums < 0.9:
        return 0.0
    return 0.6 * title + 0.4 * nums


def pair(postings: list[dict], threshold: float = 0.55, lone_threshold: float = 0.45) -> list[tuple[int, int]]:
    """(dutch_id, english_id) pairs among one source's postings. Each posting dict needs id, url, title,
    description, day (date string), city and company (a board such as AcademicTransfer hosts many employers)."""
    nl = [p for p in postings if path_language(p["url"]) == "nl"]
    en = [p for p in postings if (path_language(p["url"]) or p.get("lang_hint")) == "en"]
    if not nl or not en:
        return []
    scored: list[tuple[float, int, int]] = []
    for n in nl:
        for e in en:
            if (n["day"] and n["day"] == e["day"] and (n["city"] or "") == (e["city"] or "")
                    and n.get("company") == e.get("company")):
                s = score(n, e)
                if s >= lone_threshold:
                    scored.append((s, n["id"], e["id"]))
    # a Dutch and an English posting that are each other's only plausible match that day and city need less
    # evidence: fully translated titles ("Scheepskwetsbaarheid" / "Ship Vulnerability") score lower
    per_nl: dict[int, int] = {}
    per_en: dict[int, int] = {}
    for _, n_id, e_id in scored:
        per_nl[n_id] = per_nl.get(n_id, 0) + 1
        per_en[e_id] = per_en.get(e_id, 0) + 1
    candidates = [c for c in scored if c[0] >= threshold or (per_nl[c[1]] == 1 and per_en[c[2]] == 1)]
    candidates.sort(reverse=True)
    used_nl: set[int] = set()
    used_en: set[int] = set()
    out: list[tuple[int, int]] = []
    for _, n_id, e_id in candidates:
        if n_id in used_nl or e_id in used_en:
            continue
        used_nl.add(n_id)
        used_en.add(e_id)
        out.append((n_id, e_id))
    return out
