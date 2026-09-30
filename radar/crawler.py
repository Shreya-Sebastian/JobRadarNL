"""Crawl every active source, upsert postings, track lifecycle, dedup across sources.

Prototype concurrency: a thread pool with a per-domain delay. Production moves the same
adapter calls behind a queue (SQS/Redis) with horizontally scaled workers.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.adapters import get_adapter
from radar.adapters.base import AdapterError, RawPosting, SourceNotFound
from radar.classify import is_tech, tech_score
from radar.config import allowed_countries, settings
from radar.db import new_session
from radar.extract import get_extractor
from radar.models import CrawlRun, Posting, Source
from radar.normalize import normalize

log = logging.getLogger(__name__)

_ATS_PRIORITY = {"greenhouse": 0, "lever": 0, "ashby": 0, "workable": 0, "recruitee": 0, "jsonld": 5}


class _DomainThrottle:
    def __init__(self, delay: float):
        self.delay = delay
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, domain: str) -> None:
        with self._lock:
            last = self._last.get(domain, 0.0)
            now = time.monotonic()
            sleep_for = max(0.0, last + self.delay - now)
            self._last[domain] = max(now, last + self.delay)
        if sleep_for > 0:
            time.sleep(sleep_for)


def _domain_for(source: Source) -> str:
    """Key for the crawler's own pacing. Boards on one multi-tenant platform share a key (recruitee.com), because
    the platform rate-limits by IP across all its customers' subdomains."""
    if source.ats == "jsonld":
        from radar.ratelimit import host_key

        return host_key(urlparse(source.slug).netloc)
    return source.ats


def known_urls_for(session: Session, source: Source) -> dict[str, str]:
    """Page-URL key -> external id of every live posting of a JSON-LD source, for incremental sitemap crawls."""
    if source.ats != "jsonld":
        return {}
    from radar.adapters.jsonld import _url_key

    rows = session.execute(select(Posting.url, Posting.external_id)
                           .where(Posting.source_id == source.id, Posting.closed_at.is_(None))).all()
    return {_url_key(url): ext for url, ext in rows}


def fetch_source(source: Source, throttle: _DomainThrottle,
                 known: dict[str, str] | None = None) -> tuple[Source, list[RawPosting] | None, str | None]:
    throttle.wait(_domain_for(source))
    adapter = get_adapter(source.ats)
    if known and hasattr(adapter, "known_urls"):
        adapter.known_urls = known
    try:
        postings = adapter.fetch(source.slug)
        for ext in getattr(adapter, "still_listed", None) or ():
            postings.append(RawPosting(external_id=ext, title="", url="", raw={"still_listed": True}))
        return source, postings, None
    except SourceNotFound:
        return source, None, "not_found"
    except AdapterError as e:
        return source, None, f"error: {e}"[:500]
    except Exception as e:  # network errors etc.
        return source, None, f"exception: {type(e).__name__}: {e}"[:500]


def ingest(session: Session, source: Source, raws: list[RawPosting], extractor_name: str = "rules") -> dict:
    """Upsert one source's postings. Returns counters."""
    now = datetime.utcnow()
    extract, version = get_extractor(extractor_name)
    existing = {
        p.external_id: p
        for p in session.scalars(select(Posting).where(Posting.source_id == source.id))
    }
    by_url = {p.url: p for p in existing.values() if p.url}
    seen_ids: set[str] = set()
    new = updated = skipped_foreign = expired = 0
    keep = allowed_countries()
    # An employer's own expiry date (validThrough) in the past means the vacancy is over, even while the page is
    # still listed. Guard: when nearly every posting of a source looks expired, the field is a broken template
    # value, not information, and is ignored for that source.
    from radar.normalize import _valid_through

    dated = [v for v in (_valid_through(r) for r in raws if not r.raw.get("still_listed")) if v is not None]
    trust_expiry = not (len(dated) >= 5 and sum(1 for v in dated if v < now) / len(dated) > 0.8)
    for raw in raws:
        if raw.raw.get("still_listed"):
            # an incremental crawl confirmed this page is still in the sitemap without re-reading it
            p = existing.get(raw.external_id)
            if p is not None:
                seen_ids.add(raw.external_id)
                p.last_seen = now
                if p.closed_at is not None:
                    p.closed_at = None
            continue
        if not raw.external_id or not raw.title:
            continue
        # A job board (AcademicTransfer, werkenvoornederland) hosts many employers: attribute the posting to the
        # hiring organisation it names; an employer's own board is always attributed to that employer.
        company = raw.company if (source.kind == "board" and raw.company) else source.company
        fields = normalize(raw, company)
        country = fields["country"]
        if keep is not None:
            if country not in keep:
                skipped_foreign += 1
                continue
        elif not country or country == "XX":
            skipped_foreign += 1
            continue
        if trust_expiry and fields.get("valid_through") and fields["valid_through"] < now:
            expired += 1
            continue  # not seen: an existing copy is closed below like any posting that disappeared
        seen_ids.add(fields["external_id"])
        p = existing.get(fields["external_id"])
        if p is None and fields["url"]:
            # Same page under a new id (a site started or stopped sending a usable identifier): keep the posting
            # and its history instead of closing it and creating a "new" one.
            old = by_url.get(fields["url"])
            if old is not None and old.external_id not in seen_ids:
                existing.pop(old.external_id, None)
                old.external_id = fields["external_id"]
                existing[old.external_id] = old
                p = old
        if p is None:
            p = Posting(source_id=source.id, **fields)
            p.is_tech = is_tech(p.title, p.description)
            p.tech_score = tech_score(p.title, p.description)
            if p.is_tech:
                p.extraction = extract(p.title, p.description).model_dump()
                p.extractor_version = version
                p.extracted_hash = p.content_hash
            p.first_seen = now
            p.last_seen = now
            session.add(p)
            existing[p.external_id] = p
            new += 1
        else:
            p.last_seen = now
            if p.closed_at is not None:
                p.closed_at = None  # reopened
            if p.content_hash != fields["content_hash"]:
                for k, v in fields.items():
                    setattr(p, k, v)
                p.is_tech = is_tech(p.title, p.description)
                p.tech_score = tech_score(p.title, p.description)
                if p.is_tech:
                    p.extraction = extract(p.title, p.description).model_dump()
                    p.extractor_version = version
                    p.extracted_hash = p.content_hash
                updated += 1
    # Completeness guard: a board that suddenly returns far fewer postings than last time is more likely a
    # partial or broken response than a mass closure. Keep its postings open and flag it instead.
    previous = source.last_nl_count or 0
    partial = previous >= 10 and len(seen_ids) < 0.5 * previous
    closed = 0
    if partial:
        source.last_error = f"partial: saw {len(seen_ids)} postings, previously {previous}; not closing"
        log.warning("%s/%s: %s", source.ats, source.slug, source.last_error)
    else:
        for ext_id, p in existing.items():
            if ext_id not in seen_ids and p.closed_at is None:
                p.closed_at = now
                closed += 1
    session.flush()
    return {"new": new, "updated": updated, "closed": closed, "seen": len(seen_ids), "foreign": skipped_foreign,
            "partial": partial, "expired": expired}


def mark_duplicates(session: Session) -> int:
    """Link duplicate open postings to one canonical copy so the dashboard shows each job once.

    A posting is a duplicate of an earlier one when any of these hold:
      1. same dedup key (company + normalised title + city) on a different source (aggregator or second ATS),
      2. same dedup key on the same source with identical text and a URL that differs only by a repost
         counter ("...-2", "...-3"): the board really lists it twice,
      3. same original URL (ignoring query strings),
      4. the Dutch and English copy of one vacancy on a bilingual career site (see radar/bilingual.py); the
         English copy is kept as canonical,
      5. the same vacancy under several addresses: same board, employer and title and the same text apart from city
         names, whatever the URL (/vacatures/ and /vacature/, /eu/ and /us/, one page per city, a reposted ad);
         the canonical copy lists any other cities in `also_in`. Different titles with the same text are kept
         apart, since that is often an agency's boilerplate around different jobs,
      6. the same page in another language: the URL differs only by a language segment (/fr/, /es/, /en-gb/).
    Same title on the same board with different text, or identical text under a different URL slug (often a
    different location encoded in the slug), is kept: that is usually a separate requisition."""
    rows = session.execute(
        select(Posting.id, Posting.dedup_key, Posting.source_id, Posting.first_seen, Posting.content_hash,
               Posting.url, Source.ats, Source.kind, Posting.company, Posting.title, Posting.city, Posting.posted_at,
               Posting.also_in, Posting.duplicate_of)
        .join(Source, Source.id == Posting.source_id)
        .where(Posting.closed_at.is_(None))
    ).all()
    _kind_rank = {"employer": 0, "board": 0, "agency": 1, "aggregator": 2}
    canonical_of: dict[int, int] = {}

    def root(pid: int) -> int:
        while pid in canonical_of:
            pid = canonical_of[pid]
        return pid

    def sort_members(members: list) -> list:
        # employer copy beats agency beats aggregator; then the ATS copy; then the oldest
        return sorted(members, key=lambda r: (_kind_rank.get(r.kind or "employer", 0), _ATS_PRIORITY.get(r.ats, 3),
                                              r.first_seen, r.id))

    def mark(dup, canonical) -> None:
        if dup.id != canonical.id and dup.id not in canonical_of and root(canonical.id) != dup.id:
            canonical_of[dup.id] = root(canonical.id)

    from radar.normalize import dedup_key

    by_key: dict[str, list] = {}
    by_url: dict[str, list] = {}
    twins: dict[tuple, list] = {}
    for r in rows:
        # computed from the current employer, title and city: the stored key dates from the first crawl and goes
        # stale when a city is corrected later
        key = dedup_key(r.company or "", r.title or "", r.city)
        by_key.setdefault(key, []).append(r)
        by_url.setdefault(_url_stem(r.url, strip_counter=False), []).append(r)
        twins.setdefault((r.source_id, key, r.content_hash, _url_stem(r.url, strip_counter=True)), []).append(r)
    # 1. same job on another source
    for members in by_key.values():
        if len(members) > 1:
            members = sort_members(members)
            for dup in members[1:]:
                if dup.source_id != members[0].source_id:
                    mark(dup, members[0])
    # 2. identical twins on one board
    for members in twins.values():
        if len(members) > 1:
            members = sort_members(members)
            for dup in members[1:]:
                mark(dup, members[0])
    # 3. same original URL
    for members in by_url.values():
        if len(members) > 1:
            members = sort_members(members)
            for dup in members[1:]:
                mark(dup, members[0])
    # 4. Dutch and English copies of one vacancy on a bilingual site
    by_id = {r.id: r for r in rows}
    for n_id, e_id in _bilingual_pairs(session):
        if n_id in by_id and e_id in by_id:
            mark(by_id[n_id], by_id[e_id])
    # 5. one vacancy, one page per city
    also_in: dict[int, set[str]] = {}
    for group in _per_city_groups(session, rows):
        # only copies no earlier rule has merged, so every city listed is one that is really folded in here
        group = sorted((r for r in group if r.id not in canonical_of),  # employer copy, then English, then oldest
                       key=lambda r: (_kind_rank.get(r.kind or "employer", 0), _ATS_PRIORITY.get(r.ats, 3),
                                      _lang_rank(r.url), r.first_seen, r.id))
        if len(group) < 2:
            continue
        keep = group[0]
        for dup in group[1:]:
            mark(dup, keep)
        cities = {r.city for r in group[1:] if r.city and r.city != keep.city}
        if cities:
            also_in.setdefault(root(keep.id), set()).update(cities)
    # 6. the same page in other languages
    by_lang: dict[tuple, list] = {}
    for r in rows:
        by_lang.setdefault((r.source_id, _lang_stem(r.url)), []).append(r)
    for members in by_lang.values():
        if len(members) > 1 and any(_lang_rank(r.url) != 1 for r in members):
            members = sorted(members, key=lambda r: (_lang_rank(r.url), r.first_seen, r.id))
            for dup in members[1:]:
                mark(dup, members[0])

    changes = []
    for r in rows:
        target = root(r.id) if r.id in canonical_of else None
        cities = (sorted(also_in.get(r.id, ())) or None) if target is None else None
        if r.duplicate_of != target or (r.also_in or None) != cities:
            changes.append({"pid": r.id, "dup": target, "cities": cities})
    # plain UPDATEs in batches: loading each changed posting (description and all) would need hundreds of MB on
    # a first run, more than a small worker has
    from sqlalchemy import bindparam, update

    stmt = update(Posting).where(Posting.id == bindparam("pid")) \
        .values(duplicate_of=bindparam("dup"), also_in=bindparam("cities", type_=Posting.also_in.type))
    for i in range(0, len(changes), 1000):
        session.connection().execute(stmt, changes[i:i + 1000])
    session.expire_all()
    return len(changes)


_LANGS = {"en", "nl", "de", "fr", "es", "it", "pt", "pl", "el", "sv", "da", "fi", "no", "nb", "cs", "hu", "ro", "tr",
          "ja", "zh", "ko", "ru", "uk", "bg", "hr", "sk", "sl", "lt", "lv", "et", "ar", "he", "th", "vi", "id",
          # country codes that sites use as language segments (/br/ for Brazilian Portuguese, /cn/, /jp/)
          "br", "cn", "jp", "kr", "se", "dk", "cz", "gr", "ua", "gb", "us", "be", "at", "ch"}


def _lang_segment(seg: str) -> str | None:
    m = re.fullmatch(r"([a-z]{2})(?:[-_][a-z]{2})?", seg.lower())
    return m.group(1) if m and m.group(1) in _LANGS else None


def _lang_stem(url: str) -> str:
    """The URL without its language segment (only the first two path segments count, so an id like /ai/ deeper
    in the path is left alone): /job/339, /fr/job/339 and /en-gb/job/339 share one stem."""
    u = urlparse(url)
    segs = [s for s in u.path.split("/") if s]
    kept = [s for i, s in enumerate(segs) if not (i < 2 and _lang_segment(s))]
    return f"{u.netloc.lower().removeprefix('www.')}/{'/'.join(kept)}"


def _lang_rank(url: str) -> int:
    """English first, then no language segment, then Dutch, then the rest."""
    segs = [s for s in urlparse(url).path.split("/") if s][:2]
    langs = [lang for lang in (_lang_segment(s) for s in segs) if lang]
    lang = langs[0] if langs else None
    return {"en": 0, None: 1, "nl": 2}.get(lang, 3)


def _per_city_groups(session: Session, rows: list) -> list[list]:
    """Groups of postings that are one vacancy under several addresses (rule 5)."""
    from radar.normalize import norm_company

    candidates: dict[tuple, list] = {}
    for r in rows:
        key = (r.source_id, norm_company(r.company or "").lower(), _title_without_city(r.title or "", r.city))
        candidates.setdefault(key, []).append(r)
    candidates = {k: v for k, v in candidates.items() if len(v) > 1}
    ids = [r.id for v in candidates.values() for r in v]
    text: dict[int, str] = {}
    for i in range(0, len(ids), 500):  # only the candidates' descriptions, never the whole table
        chunk = ids[i:i + 500]
        text.update(session.execute(select(Posting.id, Posting.description).where(Posting.id.in_(chunk))).all())
    groups = []
    for members in candidates.values():
        cities = {c.lower() for r in members for c in (r.city, *(r.also_in or [])) if c}
        by_sig: dict[str, list] = {}
        for r in members:
            by_sig.setdefault(_text_signature(text.get(r.id) or "", cities), []).append(r)
        # one board, one title, one text: one vacancy to a job seeker, whether it was posted twice, under two
        # paths or once per city
        groups.extend(same for sig, same in by_sig.items() if sig and len(same) > 1)
    return groups


def _title_without_city(title: str, city: str | None) -> str:
    """The normalised title without the posting's own city, so "AI Engineer Hilversum" and "AI Engineer Amsterdam"
    (same text on the same board) compare equal."""
    from radar.normalize import norm_title
    from radar.seo import city_nl

    t = norm_title(title)
    for name in {city, city_nl(city)} - {None, ""} if city else ():
        n = norm_title(name)
        if n:
            t = re.sub(rf"\b(?:in |te |- )?{re.escape(n)}\b", " ", t)
    return " ".join(t.split()) or norm_title(title)


def _text_signature(description: str, cities: set[str]) -> str:
    """The description with city names, numbers and spacing removed, so per-city copies compare equal."""
    import hashlib

    t = description.lower()
    for c in sorted(cities, key=len, reverse=True):
        t = t.replace(c, " ")
    t = re.sub(r"[\d\W_]+", " ", t).strip()
    return hashlib.sha1(t[:6000].encode()).hexdigest() if len(t) >= 80 else ""


def _bilingual_pairs(session: Session) -> list[tuple[int, int]]:
    """Pairs only from sources whose postings live under both /nl/ and /en/ paths, so the cost stays small."""
    from radar.bilingual import pair, path_language

    rows = session.execute(
        select(Posting.id, Posting.source_id, Posting.url, Posting.title, Posting.company, Posting.city,
               Posting.posted_at, Posting.first_seen)
        .where(Posting.closed_at.is_(None))
    ).all()
    # which sources publish in both languages, from the URLs alone; texts are loaded for those sources only
    langs: dict[int, set[str]] = {}
    for r in rows:
        langs.setdefault(r.source_id, set()).add(path_language(r.url) or "none")
    bilingual = {sid for sid, seen in langs.items() if {"nl", "en"} <= seen or {"nl", "none"} <= seen}
    ids = [r.id for r in rows if r.source_id in bilingual]
    text: dict[int, str] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        text.update(session.execute(select(Posting.id, Posting.description).where(Posting.id.in_(chunk))).all())
    per_source: dict[int, list[dict]] = {}
    for r in rows:
        if r.source_id not in bilingual:
            continue
        lang = path_language(r.url)
        day = (r.posted_at or r.first_seen)
        per_source.setdefault(r.source_id, []).append(
            {"id": r.id, "url": r.url, "title": r.title, "company": r.company, "city": r.city, "lang": lang,
             "day": day.date().isoformat() if day else None, "description": text.get(r.id) or ""})
    out: list[tuple[int, int]] = []
    for sid, posts in per_source.items():
        seen = langs[sid]
        if "nl" in seen and "en" not in seen and "none" in seen:
            # Sites that publish English without a prefix next to /nl/ pages (madisonpeople.com/jobs/... and
            # /nl/jobs/...): the unprefixed pages are the English copies
            for p in posts:
                if p["lang"] is None:
                    p["lang_hint"] = "en"
        if {"nl", "en"} <= seen or any(p.get("lang_hint") for p in posts):
            out.extend(pair(posts))
    return out


_COUNTER_RX = re.compile(r"[-_ ]?\(?\d{1,3}\)?$")


def _url_stem(url: str, strip_counter: bool) -> str:
    stem = url.split("?")[0].split("#")[0].rstrip("/").lower()
    if strip_counter:
        stem = _COUNTER_RX.sub("", stem)
    return stem


def crawl(source_ids: list[int] | None = None, ats: str | None = None, limit: int | None = None,
          extractor_name: str | None = None) -> CrawlRun:
    extractor_name = extractor_name or settings.extractor
    session = new_session()
    run = CrawlRun()
    session.add(run)
    session.commit()
    q = select(Source).where(Source.active.is_(True))
    if source_ids:
        q = q.where(Source.id.in_(source_ids))
    if ats:
        q = q.where(Source.ats == ats)
    sources = list(session.scalars(q))
    if limit:
        sources = sources[:limit]
    run.sources_total = len(sources)
    throttle = _DomainThrottle(settings.per_domain_delay)
    log.info("crawling %d sources", len(sources))

    with ThreadPoolExecutor(max_workers=settings.max_workers) as pool:
        futures = [pool.submit(fetch_source, s, throttle, known_urls_for(session, s)) for s in sources]
        for fut in as_completed(futures):
            source, raws, error = fut.result()
            src = session.get(Source, source.id)
            src.last_run_at = datetime.utcnow()
            if error is not None:
                src.last_status = error.split(":")[0]
                src.last_error = error
                src.consecutive_failures += 1
                run.sources_failed += 1
                if error == "not_found" or src.consecutive_failures >= 5:
                    src.active = False
                log.warning("%s/%s failed: %s", src.ats, src.slug, error)
                session.commit()
                continue
            counters = ingest(session, src, raws, extractor_name)
            src.last_status = "partial" if counters.get("partial") else "ok"
            if src.first_success_at is None:
                src.first_success_at = datetime.utcnow()
            if not counters.get("partial"):
                src.last_error = None
                src.last_nl_count = counters["seen"]  # a partial response must not lower the baseline
            src.consecutive_failures = 0
            src.last_count = len(raws)
            run.sources_ok += 1
            run.postings_seen += counters["seen"]
            run.postings_new += counters["new"]
            run.postings_closed += counters["closed"]
            session.commit()
            log.info("%s/%s: total=%d nl=%d new=%d closed=%d", src.ats, src.slug, len(raws),
                     counters["seen"], counters["new"], counters["closed"])
    dups = mark_duplicates(session)
    run.finished_at = datetime.utcnow()
    run.notes = f"duplicates marked: {dups}"
    session.commit()
    session.close()
    return run
