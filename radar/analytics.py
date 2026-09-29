"""Anonymous site analytics for the admin page (/admin/analytics).

What is recorded per request: time, path, status, response time, size, the referring domain, utm_source, the
country (from Cloudflare's CF-IPCountry header), browser, OS, device class and whether it is a bot. What is not:
the IP address, the full user agent, cookies, or anything from request bodies (pasted CV text never reaches here).

Unique visitors are counted with `visitor`, a hash of IP + user agent with a salt that is replaced every day and
never kept, so a person is one visitor per day but cannot be followed across days or recognised later. This is
the approach of cookieless analytics such as Plausible, and needs no consent banner.

Rows are buffered in memory and written in batches every few seconds, so a page view costs no database round
trip. Raw rows are kept 90 days (API calls 14 days); `rollup` keeps daily totals for the all-time figures.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import threading
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from radar.config import settings

log = logging.getLogger(__name__)

RAW_DAYS = 90
API_DAYS = 14
SESSION_GAP = timedelta(minutes=30)
EVENTS = {"nav", "job_click", "profile_save", "login_request", "gap", "import", "export", "star"}

# Paths that would only add noise: assets, health checks, polling, admin, the beacon itself
_SKIP = re.compile(r"^/(static/|metrics|healthz|readyz|favicon|api/version|api/admin|api/me|api/e$|admin/)")
_PAGE = re.compile(r"^/(|nl/?|vacatures/.+|jobs/.+|company/.+|companies|privacy|nl/privacy)$")
_CRAWL = {"/robots.txt", "/sitemap.xml"}

_BOTS = [
    ("Googlebot", r"googlebot|google-inspectiontool|googleother"), ("bingbot", r"bingbot|bingpreview"),
    ("GPTBot", r"gptbot"), ("ChatGPT", r"chatgpt-user|oai-searchbot"), ("ClaudeBot", r"claudebot|claude-user"),
    ("PerplexityBot", r"perplexity"), ("Applebot", r"applebot"), ("DuckDuckBot", r"duckduckbot"),
    ("YandexBot", r"yandex"), ("Baiduspider", r"baiduspider"), ("AhrefsBot", r"ahrefsbot"),
    ("SemrushBot", r"semrushbot"), ("MJ12bot", r"mj12bot"), ("DotBot", r"dotbot"), ("PetalBot", r"petalbot"),
    ("facebookexternalhit", r"facebookexternalhit|meta-externalagent"), ("LinkedInBot", r"linkedinbot"),
    ("Twitterbot", r"twitterbot"), ("Slackbot", r"slackbot"), ("WhatsApp", r"whatsapp"),
    ("Discordbot", r"discordbot"), ("Uptime monitor", r"uptimerobot|pingdom|statuscake|betteruptime"),
    ("curl", r"^curl/"), ("python", r"python-requests|python-httpx|aiohttp|urllib"), ("Go client", r"go-http-client"),
    ("Headless", r"headlesschrome|phantomjs|puppeteer|playwright"), ("Bot", r"bot\b|crawler|spider|scrape"),
]
_BOT_RX = [(name, re.compile(rx, re.I)) for name, rx in _BOTS]


def parse_agent(ua: str) -> tuple[str, str, str, bool]:
    """(browser, os, device, is_bot) from a user-agent string."""
    ua = ua or ""
    if not ua:
        return "Unknown", "Unknown", "unknown", True
    for name, rx in _BOT_RX:
        if rx.search(ua):
            return name, _os(ua), "bot", True
    if re.search(r"edg/|edga/|edgios/", ua, re.I):
        browser = "Edge"
    elif re.search(r"opr/|opera", ua, re.I):
        browser = "Opera"
    elif re.search(r"samsungbrowser", ua, re.I):
        browser = "Samsung Internet"
    elif re.search(r"firefox/|fxios/", ua, re.I):
        browser = "Firefox"
    elif re.search(r"chrome/|crios/", ua, re.I):
        browser = "Chrome"
    elif re.search(r"safari/", ua, re.I):
        browser = "Safari"
    else:
        browser = "Other"
    if re.search(r"ipad|tablet", ua, re.I):
        device = "tablet"
    elif re.search(r"mobi|iphone|android", ua, re.I):
        device = "mobile"
    else:
        device = "desktop"
    return browser, _os(ua), device, False


def _os(ua: str) -> str:
    for name, rx in (("iOS", r"iphone|ipad|ipod"), ("Android", r"android"), ("Windows", r"windows"),
                     ("macOS", r"mac os x|macintosh"), ("ChromeOS", r"cros"), ("Linux", r"linux")):
        if re.search(rx, ua, re.I):
            return name
    return "Other"


def classify(path: str) -> str | None:
    if _SKIP.match(path):
        return None
    if path in _CRAWL:
        return "crawl"
    if path.startswith("/api/"):
        return "api"
    if _PAGE.match(path):
        return "page"
    return "other"


def _referrer(header: str | None) -> str | None:
    if not header:
        return None
    host = (urlparse(header).hostname or "").lower().removeprefix("www.")
    own = (urlparse(settings.site_url).hostname or "").removeprefix("www.")
    if not host or host == own or host in ("localhost", "127.0.0.1"):
        return None
    return host[:120]


def client_ip(request) -> str:
    """The visitor's address as Cloudflare reports it (the connection itself comes from Cloudflare/Traefik)."""
    for h in ("cf-connecting-ip", "x-forwarded-for"):
        v = request.headers.get(h)
        if v:
            return v.split(",")[0].strip()
    return request.client.host if request.client else ""


# ---------- daily salt ----------
_salt: tuple[str, str] | None = None  # (day, salt)
_salt_lock = threading.Lock()


def _daily_salt(today: str) -> str:
    """Kept only in memory and in one row that is replaced every day, so yesterday's hashes cannot be recomputed."""
    global _salt
    with _salt_lock:
        if _salt and _salt[0] == today:
            return _salt[1]
        from radar.db import session_scope
        from radar.models import Meta

        with session_scope() as s:
            row = s.get(Meta, "analytics_salt")
            day, _, value = (row.value if row else "").partition(":")
            if day != today or not value:
                value = secrets.token_hex(16)
                if row is None:
                    s.add(Meta(key="analytics_salt", value=f"{today}:{value}"))
                else:
                    row.value = f"{today}:{value}"
        _salt = (today, value)
        return value


def visitor_id(ip: str, ua: str, today: str) -> str:
    return hashlib.sha256(f"{_daily_salt(today)}|{ip}|{ua}".encode()).hexdigest()[:16]


# ---------- recording ----------
_buffer: list[dict] = []
_buffer_lock = threading.Lock()
_flusher: threading.Thread | None = None


def _search_detail(query: str) -> str | None:
    """Filters of a job search (first page only, so paging is not counted as a new search)."""
    q = parse_qs(query)
    if q.get("page", ["1"])[0] not in ("", "1") or q.get("ids"):
        return None
    keep = ["q", "city", "role", "seniority", "skill", "language", "remote", "sponsorship", "english_only",
            "experience", "org_size"]
    parts = [f"{k}={q[k][0][:40]}" for k in keep if q.get(k) and q[k][0] not in ("", "false")]
    return "&".join(parts)[:200] if parts else None


def record(request, status: int, ms: float, size: int, event: str | None = None, detail: str | None = None,
           path: str | None = None) -> None:
    if not settings.analytics_enabled:
        return
    path = path or request.url.path
    kind = "event" if event else classify(path)
    if kind is None:
        return
    ua = request.headers.get("user-agent", "")
    browser, os_name, device, bot = parse_agent(ua)
    now = datetime.utcnow()
    if kind == "api" and path == "/api/postings" and request.method == "GET":
        detail = _search_detail(request.url.query)
        event = "search" if detail else None
    elif kind == "api" and path == "/api/gap":
        event = "gap"
    elif kind == "api" and path == "/api/auth/request":
        event = "login_request"
    utm = parse_qs(request.url.query).get("utm_source", [None])[0]
    row = {
        "ts": now, "kind": kind, "path": path[:300], "status": status, "ms": int(ms), "bytes": int(size or 0),
        # where a visit came from: only the page load counts, not the API calls that page makes afterwards
        "referrer": _referrer(request.headers.get("referer")) if kind == "page" else None,
        "utm_source": utm[:60] if utm else None, "country": (request.headers.get("cf-ipcountry") or "")[:2] or None,
        "browser": browser, "os": os_name, "device": device, "bot": bot,
        "visitor": visitor_id(client_ip(request), ua, now.date().isoformat()),
        "event": event, "detail": detail[:200] if detail else None,
    }
    with _buffer_lock:
        _buffer.append(row)
        if len(_buffer) > 5000:  # database away for a long time: drop the oldest rather than grow
            del _buffer[:1000]
    _ensure_flusher()


def buffer_size() -> int:
    return len(_buffer)


def flush() -> int:
    from radar.db import session_scope
    from radar.models import PageView

    with _buffer_lock:
        rows = _buffer[:]
        _buffer.clear()
    if not rows:
        return 0
    try:
        with session_scope() as s:
            s.bulk_insert_mappings(PageView, rows)
    except Exception:
        log.exception("analytics flush failed; %d rows dropped", len(rows))
        return 0
    return len(rows)


def _ensure_flusher() -> None:
    global _flusher
    if _flusher is not None and _flusher.is_alive():
        return

    def loop():
        while True:
            time.sleep(10)
            flush()

    _flusher = threading.Thread(target=loop, name="analytics-flush", daemon=True)
    _flusher.start()


# ---------- dashboard ----------
def _top(counter: Counter, n: int = 10) -> list[dict]:
    return [{"key": k, "hits": v} for k, v in counter.most_common(n) if k]


def _sessions(views: list) -> tuple[int, int, float]:
    """(sessions, bounced sessions, pages per session) from page views and SPA navigations of humans."""
    by_visitor: dict[str, list[datetime]] = defaultdict(list)
    for v in views:
        by_visitor[v.visitor].append(v.ts)
    sessions = bounced = pages = 0
    for times in by_visitor.values():
        times.sort()
        count = 1
        for prev, cur in zip(times, times[1:], strict=False):
            if cur - prev > SESSION_GAP:
                sessions += 1
                bounced += count == 1
                pages += count
                count = 1
            else:
                count += 1
        sessions += 1
        bounced += count == 1
        pages += count
    return sessions, bounced, (pages / sessions if sessions else 0.0)


def dashboard(session: Session, include_bots: bool = False, now: datetime | None = None) -> dict:
    from radar.models import PageView, Posting

    now = now or datetime.utcnow()
    day_start = datetime(now.year, now.month, now.day)
    since = now - timedelta(hours=24)
    cols = [PageView.ts, PageView.kind, PageView.path, PageView.status, PageView.ms, PageView.bytes,
            PageView.referrer, PageView.utm_source, PageView.country, PageView.browser, PageView.os, PageView.device,
            PageView.bot, PageView.visitor, PageView.event, PageView.detail]
    rows = session.execute(select(*cols).where(PageView.ts >= min(since, day_start)).order_by(PageView.ts)).all()
    rows += [_as_row(r) for r in list(_buffer)]  # not yet flushed
    h24 = [r for r in rows if r.ts >= since]
    today = [r for r in rows if r.ts >= day_start]
    shown = h24 if include_bots else [r for r in h24 if not r.bot]

    def is_view(r):
        return r.kind == "page" or r.event == "nav"

    views_today = [r for r in today if is_view(r) and (include_bots or not r.bot)]
    views_24 = [r for r in shown if is_view(r)]
    human_views = [r for r in h24 if is_view(r) and not r.bot]
    served = [r for r in h24 if r.kind != "event"]
    times = sorted(r.ms for r in served)
    sessions, bounced, pps = _sessions(human_views)
    bytes_24 = sum(r.bytes for r in served)
    visitors_24 = {r.visitor for r in served}

    timeline = [{"hour": (since + timedelta(hours=i + 1)).strftime("%H:00"), "humans": 0, "bots": 0} for i in range(24)]
    for r in h24:
        if is_view(r):
            idx = min(23, int((r.ts - since).total_seconds() // 3600))
            timeline[idx]["bots" if r.bot else "humans"] += 1

    consumers: dict[str, dict] = {}
    for r in served:
        key = r.browser if r.bot else f"visitor {r.visitor[:6]}"
        c = consumers.setdefault(key, {"who": key, "country": r.country, "requests": 0, "bytes": 0, "bot": r.bot})
        c["requests"] += 1
        c["bytes"] += r.bytes

    clicks = [r for r in shown if r.event == "job_click" and r.detail and r.detail.isdigit()]
    ids = {int(r.detail) for r in clicks}
    posting = {p.id: p for p in session.scalars(select(Posting).where(Posting.id.in_(ids)))} if ids else {}
    by_employer = Counter(posting[int(r.detail)].company for r in clicks if int(r.detail) in posting)
    by_job = Counter(f"{posting[int(r.detail)].title} · {posting[int(r.detail)].company}"
                     for r in clicks if int(r.detail) in posting)

    all_time = _all_time(session, today, day_start)
    return {
        "generated_at": now.isoformat(timespec="seconds") + "Z", "include_bots": include_bots,
        "kpi": {
            "views_today": len(views_today), "uniques_today": len({r.visitor for r in views_today}),
            "views_24h": len(views_24), "uniques_24h": len({r.visitor for r in views_24}),
            "human_views_24h": len(human_views),
            "bot_hits_24h": sum(1 for r in h24 if r.bot and r.kind != "event"),
            "bounce_rate": round(bounced / sessions, 3) if sessions else None, "pages_per_session": round(pps, 1),
            "avg_ms": round(sum(times) / len(times)) if times else 0,
            "p95_ms": times[int(len(times) * 0.95)] if times else 0,
            "bytes_today": sum(r.bytes for r in today if r.kind != "event"), "bytes_24h": bytes_24,
            "bytes_per_visitor": round(bytes_24 / len(visitors_24)) if visitors_24 else 0,
            "spa_navigations": sum(1 for r in shown if r.event == "nav"),
            "interactions": sum(1 for r in shown if r.kind == "event" or r.event),
            "crawler_fetches": sum(1 for r in h24 if r.kind == "crawl"),
            "job_clicks": len(clicks), "searches": sum(1 for r in shown if r.event == "search"),
            "buffered": buffer_size(),
        },
        "timeline": timeline,
        "top_pages": _top(Counter(r.path for r in views_24 if r.kind == "page")),
        "top_api": _top(Counter(r.path for r in shown if r.kind == "api")),
        "referrers": _top(Counter(r.referrer for r in shown if r.referrer)),
        "utm": _top(Counter(r.utm_source for r in shown if r.utm_source)),
        "countries": _top(Counter(r.country for r in shown if r.kind != "event" and r.country)),
        "os": _top(Counter(r.os for r in shown if r.kind != "event")),
        "browsers": _top(Counter(r.browser for r in h24 if r.kind != "event" and (include_bots or not r.bot))),
        "devices": _top(Counter(r.device for r in h24 if r.kind != "event")),
        "bots": _top(Counter(r.browser for r in h24 if r.bot and r.kind != "event")),
        "statuses": _top(Counter(str(r.status) for r in served if (include_bots or not r.bot))),
        "consumers": sorted(consumers.values(), key=lambda c: -c["bytes"])[:10],
        "job_clicks_by_employer": _top(by_employer),
        "job_clicks_by_job": _top(by_job),
        "searches": _top(Counter(r.detail for r in shown if r.event == "search" and r.detail), 15),
        "events": _top(Counter(r.event for r in shown if r.event and r.event not in ("nav", "search")), 12),
        "recent": [
            {"ts": r.ts.isoformat(timespec="seconds") + "Z", "path": r.path, "status": r.status, "ms": r.ms,
             "bytes": r.bytes, "referrer": r.referrer, "utm": r.utm_source, "country": r.country,
             "browser": r.browser, "device": r.device, "visitor": (r.visitor or "")[:6], "event": r.event}
            for r in reversed([r for r in h24 if r.kind in ("page", "event", "crawl")][-25:])
            if include_bots or not r.bot
        ][:20],
        "all_time": all_time,
    }


def _as_row(d: dict):
    from types import SimpleNamespace

    return SimpleNamespace(**d)


def _all_time(session: Session, today_rows: list, day_start: datetime) -> dict:
    from radar.models import DailyStat

    stats = session.execute(select(DailyStat.day, DailyStat.dim, DailyStat.key, DailyStat.hits, DailyStat.humans,
                                   DailyStat.uniques)).all()
    totals = [s for s in stats if s.dim == "total"]
    live = [r for r in today_rows if r.kind != "event"]
    hits = sum(s.hits for s in totals) + len(live)
    humans = sum(s.humans for s in totals) + sum(1 for r in live if not r.bot)
    uniques = sum(s.uniques for s in totals) + len({r.visitor for r in live if not r.bot})
    days = sorted({s.day for s in totals})
    since = days[0] if days else day_start.date()
    n_days = (day_start.date() - since).days + 1
    by = defaultdict(Counter)
    for s in stats:
        if s.dim != "total":
            by[s.dim][s.key] += s.humans
    for r in live:
        if not r.bot:
            if r.country:
                by["country"][r.country] += 1
            if r.referrer:
                by["referrer"][r.referrer] += 1
            if r.kind == "page":
                by["page"][r.path] += 1
    daily = {s.day: s for s in totals}
    last14 = []
    for i in range(13, -1, -1):
        d = day_start.date() - timedelta(days=i)
        if d == day_start.date():
            people = [r for r in live if not r.bot]
            last14.append({"day": d.isoformat(), "humans": len(people), "bots": len(live) - len(people),
                           "uniques": len({r.visitor for r in people})})
        else:
            s = daily.get(d)
            last14.append({"day": d.isoformat(), "humans": s.humans if s else 0,
                           "bots": (s.hits - s.humans) if s else 0, "uniques": s.uniques if s else 0})
    return {
        "hits": hits, "humans": humans, "bots": hits - humans, "uniques": uniques, "since": since.isoformat(),
        "days": n_days, "countries": len(by["country"]), "avg_daily_humans": round(humans / n_days) if n_days else 0,
        "daily": last14, "top_countries": _top(by["country"]), "top_referrers": _top(by["referrer"]),
        "top_pages": _top(by["page"]),
    }


# ---------- nightly ----------
def rollup(session: Session, day: date) -> int:
    """Store the totals of one finished day (idempotent: re-running replaces them)."""
    from radar.models import DailyStat, PageView

    start = datetime(day.year, day.month, day.day)
    rows = session.execute(select(PageView.kind, PageView.path, PageView.referrer, PageView.country, PageView.bot,
                                  PageView.visitor).where(PageView.ts >= start, PageView.ts < start + timedelta(days=1),
                                                          PageView.kind != "event")).all()
    session.execute(delete(DailyStat).where(DailyStat.day == day))
    if not rows:
        return 0
    humans = [r for r in rows if not r.bot]
    out = [DailyStat(day=day, dim="total", key="all", hits=len(rows), humans=len(humans),
                     uniques=len({r.visitor for r in humans}))]
    for dim, values in (("country", [r.country for r in humans]), ("referrer", [r.referrer for r in humans]),
                        ("page", [r.path for r in humans if r.kind == "page"])):
        for key, n in Counter(v for v in values if v).most_common(200):
            out.append(DailyStat(day=day, dim=dim, key=key[:200], hits=n, humans=n))
    session.add_all(out)
    return len(out)


def nightly(session: Session, now: datetime | None = None) -> dict:
    """Roll up the last two finished days, then drop raw rows past their retention."""
    from radar.models import PageView

    now = now or datetime.utcnow()
    today = now.date()
    rolled = sum(rollup(session, today - timedelta(days=i)) for i in (1, 2))
    old = session.execute(delete(PageView).where(PageView.ts < now - timedelta(days=RAW_DAYS))).rowcount
    old_api = session.execute(delete(PageView).where(PageView.kind == "api",
                                                     PageView.ts < now - timedelta(days=API_DAYS))).rowcount
    session.commit()
    first = session.scalar(select(func.min(PageView.ts)))
    return {"daily_rows": rolled, "deleted": (old or 0) + (old_api or 0), "oldest_raw": first and first.isoformat()}
