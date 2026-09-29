"""Top-employer coverage tracker: which of the employers in data/top100.yaml the radar actually has."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from radar.config import settings
from radar.models import Posting, Source


@dataclass
class Entry:
    name: str
    match: list[str]
    platform: str
    group: str
    status: str = "missing"      # covered | registered | missing
    live_postings: int = 0
    via: str = ""


def load_tracker(path: str | Path | None = None) -> list[Entry]:
    path = Path(path) if path else Path(settings.data_dir) / "top100.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [Entry(e["name"], [str(m).lower() for m in e["match"]], e.get("platform", "unknown"),
                  e.get("group", "")) for e in data]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9. ]", "", (s or "").lower())


def _matches(needle: str, *texts: str) -> bool:
    needle = needle.lower()
    if needle.startswith("="):  # "=ns": the employer name must be exactly this
        return any(_norm(t).strip() == needle[1:].strip() for t in texts)
    # "imc " style entries, and any needle of four letters or fewer ("ns", "esa", "afm"), match whole words only,
    # so NS does not match "Nederlandse Spoorwegen"-less names like "Dienstverlening" or "ns ecure"
    quoted_word = needle.strip() != needle or len(needle.strip()) <= 4
    for t in texts:
        t = _norm(t)
        if quoted_word:
            if re.search(rf"\b{re.escape(needle.strip())}\b", t):
                return True
        elif needle in t or needle in t.replace(" ", ""):
            return True
    return False


def evaluate(session: Session, entries: list[Entry] | None = None) -> list[Entry]:
    entries = entries or load_tracker()
    sources = list(session.scalars(select(Source)))
    live_by_company = Counter()
    for company, n in session.execute(
        select(Posting.company, func.count()).where(Posting.closed_at.is_(None), Posting.duplicate_of.is_(None))
        .group_by(Posting.company)
    ):
        live_by_company[company] = n
    for e in entries:
        # postings first: a university on AcademicTransfer has no source of its own
        hits = [(c, n) for c, n in live_by_company.items() if any(_matches(m, c) for m in e.match)]
        if hits:
            c, n = max(hits, key=lambda t: t[1])
            e.status, e.live_postings, e.via = "covered", sum(n for _, n in hits), f"postings as '{c}'"
            continue
        srcs = [s for s in sources if any(_matches(m, s.company, s.slug) for m in e.match)]
        if srcs:
            s = max(srcs, key=lambda x: x.last_nl_count or 0)
            e.status, e.live_postings, e.via = "registered", s.last_nl_count or 0, f"{s.ats}/{s.slug[:40]}"
        else:
            e.status = "missing"
    return entries


def report(entries: list[Entry]) -> str:
    counts = Counter(e.status for e in entries)
    lines = [f"Top employers: {counts['covered']} covered, {counts['registered']} registered without live "
             f"postings, {counts['missing']} missing (of {len(entries)})", ""]
    for status in ("missing", "registered", "covered"):
        names = [e for e in entries if e.status == status]
        if not names:
            continue
        lines.append(f"## {status} ({len(names)})")
        for e in sorted(names, key=lambda e: (e.group, e.name)):
            extra = f" - {e.live_postings} live via {e.via}" if status != "missing" else f" - platform: {e.platform}"
            lines.append(f"- {e.name} [{e.group}]{extra}")
        lines.append("")
    return "\n".join(lines)
