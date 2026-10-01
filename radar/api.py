from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from radar import auth, feedback, stats
from radar.cache import cached
from radar.config import settings
from radar.db import get_engine, init_db, new_session
from radar.metrics import API_REQUESTS, API_SECONDS, QUEUE_DEPTH
from radar.models import CrawlRun, Source

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield
    from radar import analytics

    analytics.flush()  # page views still in the buffer at shutdown


app = FastAPI(title=settings.site_name, version="0.2.0", lifespan=lifespan, description=settings.site_tagline)
app.include_router(auth.router)
app.include_router(feedback.router)
_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["GET", "POST"], allow_headers=["*"])


@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api/"):
        response.headers["X-Robots-Tag"] = "noindex"  # fetched to render pages, never a search result itself
    if response.headers.get("content-type", "").startswith("text/html") and "cache-control" not in response.headers:
        # pages name the current app.js/app.css versions: a browser must check for a new page, or it keeps running
        # the previous release's script after a deploy
        response.headers["Cache-Control"] = "no-cache"
    try:
        from radar import analytics

        analytics.record(request, response.status_code, (time.perf_counter() - t0) * 1000,
                         int(response.headers.get("content-length") or 0))
    except Exception:  # statistics must never break a response
        pass
    if path.startswith("/api/") or path in ("/", "/healthz", "/readyz"):
        # collapse dynamic segments so label cardinality stays small
        label = "/api/breakdown/*" if path.startswith("/api/breakdown/") else path
        API_REQUESTS.labels(label, str(response.status_code)).inc()
        API_SECONDS.labels(label).observe(time.perf_counter() - t0)
    return response


@app.middleware("http")
async def _throttle_middleware(request: Request, call_next):
    # added after the metrics middleware, so it runs first and refused requests cost nothing further
    from starlette.concurrency import run_in_threadpool

    from radar import analytics, throttle

    refused = await run_in_threadpool(throttle.check, request.url.path, analytics.client_ip(request),
                                      request.headers.get("user-agent", ""))
    if refused:
        status, reason = refused
        return Response(reason + "\n", status_code=status, media_type="text/plain",
                        headers={"Retry-After": "60"} if status == 429 else None)
    return await call_next(request)


_NOT_FOUND = {
    "en": ("Page not found", "This page does not exist, or the vacancy has been taken down.", "/", "Back to the jobs"),
    "nl": ("Pagina niet gevonden", "Deze pagina bestaat niet, of de vacature is offline gehaald.", "/nl/",
           "Terug naar de vacatures"),
}


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    from fastapi.exception_handlers import http_exception_handler

    path = request.url.path
    if exc.status_code != 404 or path.startswith("/api/") or "text/html" not in request.headers.get("accept", ""):
        return await http_exception_handler(request, exc)  # API clients keep the JSON error
    from html import escape

    lang = "nl" if path.startswith("/nl/") or path == "/nl" else "en"
    title, text, home, back = _NOT_FOUND[lang]
    page = (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
            f'<title>{escape(title)} · {escape(settings.site_name)}</title>'
            '<link rel="stylesheet" href="/static/app.css?v=3"></head><body>'
            f'<main class="wrap" style="padding-top:4rem;padding-bottom:4rem"><h1>{escape(title)}</h1>'
            f'<p class="muted">{escape(text)}</p>'
            f'<p><a class="btn primary" href="{home}">{escape(back)}</a></p></main></body></html>')
    return Response(page, status_code=404, media_type="text/html")


def db() -> Iterator[Session]:
    s = new_session()
    try:
        yield s
    finally:
        s.close()


def filters(
    role: str | None = None,
    seniority: str | None = None,
    city: str | None = None,
    company: str | None = None,
    english_only: bool | None = None,
    sponsorship: bool | None = None,
    remote: str | None = None,
    days: int | None = Query(None, ge=1, le=365),
    q: str | None = None,
    skill: str | None = None,
    include_closed: bool = False,
    exclude_agencies: bool = False,
    exclude_companies: str | None = None,
    since: str | None = None,
    skills_any: str | None = None,
    ids: str | None = None,
    language: str | None = None,
    experience: str | None = None,
    enrollment: str | None = None,
    org_size: str | None = None,
    confirmed_days: int | None = Query(None, ge=1, le=90),
    degree: str | None = None,
    employees: str | None = None,
) -> stats.Filters:
    return stats.Filters(role, seniority, city, company, english_only, sponsorship, remote, days, q, skill,
                         include_closed, exclude_agencies, exclude_companies, since, skills_any, ids, language,
                         experience, enrollment, org_size, confirmed_days, degree, employees)


def _rows(session: Session, f: stats.Filters) -> list[stats.Row]:
    return f.apply(stats.CACHE.rows(session))


def _key(request: Request) -> str:
    return f"{request.url.path}?{request.url.query}"


@app.get("/api/overview")
def overview(request: Request, session: Session = Depends(db)):
    return cached(_key(request), lambda: stats.overview(session), ttl=60)


@app.get("/api/skills")
def skills(request: Request, top: int = Query(40, le=200), f: stats.Filters = Depends(filters),
           session: Session = Depends(db)):
    def compute():
        rows = _rows(session, f)
        return {"n": len(rows), "skills": stats.skill_counts(rows, top)}

    return cached(_key(request), compute)


@app.get("/api/cooccurrence")
def cooccurrence(request: Request, top: int = Query(30, le=80), f: stats.Filters = Depends(filters),
                 session: Session = Depends(db)):
    def compute():
        rows = _rows(session, f)
        return {"n": len(rows), **stats.cooccurrence(rows, top)}

    return cached(_key(request), compute)


@app.get("/api/breakdown/{key}")
def breakdown(request: Request, key: str, top: int = Query(20, le=100), f: stats.Filters = Depends(filters),
              session: Session = Depends(db)):
    allowed = {"city", "company", "ats", "seniority", "role_family", "remote_policy", "degree_required",
               "posting_language", "experience", "org_size", "degree", "employees"}
    if key not in allowed:
        raise HTTPException(400, f"key must be one of {sorted(allowed)}")

    def compute():
        rows = _rows(session, f)
        return {"n": len(rows), "items": stats.breakdown(rows, key, top)}

    return cached(_key(request), compute)


@app.get("/api/trends")
def trends(request: Request, skills: str | None = None, weeks: int = Query(12, le=52),
           f: stats.Filters = Depends(filters), session: Session = Depends(db)):
    def compute():
        f.include_closed = True
        rows = _rows(session, f)
        wanted = [s.strip() for s in skills.split(",")] if skills else None
        return stats.trends(rows, wanted, weeks)

    return cached(_key(request), compute)


@app.get("/api/salary")
def salary(request: Request, f: stats.Filters = Depends(filters), session: Session = Depends(db)):
    return cached(_key(request), lambda: stats.salary(_rows(session, f)))


@app.get("/api/postings")
def postings(request: Request, page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
             sort: str = "newest", skills_have: str | None = None, f: stats.Filters = Depends(filters),
             session: Session = Depends(db)):
    from radar.taxonomy import canonicalise

    have = set(canonicalise((skills_have or "").split(",")))
    return cached(_key(request), lambda: stats.posting_dicts(_rows(session, f), page, size, sort, have))


@app.get("/api/skills/canonical")
def canonical_skills(names: str):
    """Map typed skill names to the tracked canonical names: LLM -> LLMs, ml -> Machine Learning, k8s -> Kubernetes."""
    from radar.taxonomy import canonical_skill

    return {n.strip(): canonical_skill(n) for n in names.split(",") if n.strip()}


@app.get("/api/coverage")
def coverage(request: Request, session: Session = Depends(db)):
    """Top-employer tracker and source counts by kind, for the Coverage tab."""
    from collections import Counter

    from radar.recall import published
    from radar.tracker import evaluate

    def compute():
        entries = evaluate(session)
        by_kind = Counter()
        healthy = Counter()
        for s in session.scalars(select(Source)):
            by_kind[s.kind or "employer"] += 1
            if s.last_status == "ok":
                healthy[s.kind or "employer"] += 1
        return {
            "tracker": [{"name": e.name, "group": e.group, "status": e.status, "platform": e.platform,
                         "live_postings": e.live_postings} for e in entries],
            "summary": {k: sum(1 for e in entries if e.status == k) for k in ("covered", "registered", "missing")},
            "sources_by_kind": dict(by_kind),
            "healthy_by_kind": dict(healthy),
            "recall": published(session),
        }

    return cached(_key(request), compute, ttl=600)


@app.get("/api/filters")
def filter_options(request: Request, session: Session = Depends(db)):
    def compute():
        rows = [r for r in stats.CACHE.rows(session) if r.closed_at is None]
        return {
            "cities": [d["key"] for d in stats.breakdown(rows, "city", 40)],
            "companies": [d["key"] for d in stats.breakdown(rows, "company", 300)],
            "roles": [d["key"] for d in stats.breakdown(rows, "role_family", 20)],
            "seniorities": [d["key"] for d in stats.breakdown(rows, "seniority", 10)],
            "skills": [d["skill"] for d in stats.skill_counts(rows, 120)],
        }

    return cached(_key(request), compute)


@app.get("/api/sources")
def sources(session: Session = Depends(db)):
    items = []
    for s in session.scalars(select(Source).order_by(Source.ats, Source.company)):
        items.append({
            "id": s.id, "company": s.company, "ats": s.ats, "slug": s.slug, "active": s.active,
            "status": s.last_status, "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
            "total": s.last_count, "nl": s.last_nl_count, "failures": s.consecutive_failures,
            "discovered_by": s.discovered_by, "kind": s.kind, "note": s.last_error,
        })
    runs = [
        {"id": r.id, "started_at": r.started_at.isoformat(), "finished_at": r.finished_at.isoformat()
         if r.finished_at else None, "sources_ok": r.sources_ok, "sources_failed": r.sources_failed,
         "seen": r.postings_seen, "new": r.postings_new, "closed": r.postings_closed}
        for r in session.scalars(select(CrawlRun).order_by(CrawlRun.id.desc()).limit(20))
    ]
    return {"sources": items, "runs": runs}


class GapRequest(BaseModel):
    cv_text: str | None = Field(default=None, max_length=50_000)
    skills: list[str] | None = Field(default=None, max_length=200)
    role: str | None = None
    seniority: str | None = None
    city: str | None = None
    english_only: bool | None = None
    language: str | None = None
    exclude_agencies: bool = False
    days: int | None = 90


@app.post("/api/gap")
def gap(req: GapRequest, session: Session = Depends(db)):
    if not (req.cv_text and len(req.cv_text.strip()) >= 20) and not req.skills:
        raise HTTPException(422, "provide cv_text (20+ characters) or a skills list")
    f = stats.Filters(role=req.role, seniority=req.seniority, city=req.city, english_only=req.english_only,
                      days=req.days, exclude_agencies=req.exclude_agencies, language=req.language)
    rows = _rows(session, f)
    return stats.gap_analysis(rows, req.cv_text, req.skills)


@app.get("/api/version")
def version(session: Session = Depends(db)):
    """Cheap freshness check for the page: it polls this and offers a reload when a crawl has finished."""
    from radar.cache import data_version

    last = session.scalar(select(CrawlRun.finished_at).where(CrawlRun.finished_at.is_not(None))
                          .order_by(CrawlRun.finished_at.desc()).limit(1))
    return {"version": data_version(), "last_crawl_at": last.isoformat() if last else None}


class AdminCrawl(BaseModel):
    scope: str = "due"  # due | all | company
    company: str | None = None
    force: bool = False


def _admin(request: Request) -> None:
    from radar import admin

    if not admin.enabled():
        raise HTTPException(404, "not found")
    if not admin.authorised(request.headers.get("authorization")):
        raise HTTPException(401, "admin token required")


@app.post("/api/admin/crawl", include_in_schema=False)
def admin_crawl(body: AdminCrawl, request: Request):
    from fastapi.responses import JSONResponse

    from radar import admin

    _admin(request)
    code, payload = admin.trigger(body.scope, body.company, body.force)
    return JSONResponse(payload, status_code=code)


class Beacon(BaseModel):
    e: str = Field(max_length=30)
    d: str | None = Field(default=None, max_length=200)
    p: str | None = Field(default=None, max_length=300)


@app.post("/api/e", include_in_schema=False, status_code=204)
def beacon(body: Beacon, request: Request):
    """Events the server cannot see itself: tab switches inside the page, clicks through to a job, saves."""
    from radar import analytics

    if body.e in analytics.EVENTS:
        analytics.record(request, 204, 0, 0, event=body.e, detail=body.d, path=(body.p or "/")[:300])
    return Response(status_code=204)


@app.get("/api/admin/analytics", include_in_schema=False)
def admin_analytics(request: Request, bots: bool = False, session: Session = Depends(db)):
    from radar import analytics

    _admin(request)
    return {**analytics.dashboard(session, include_bots=bots), "this_browser_excluded": analytics.excluded(request)}


@app.post("/api/admin/analytics/exclude", include_in_schema=False)
def admin_analytics_exclude(request: Request, session: Session = Depends(db)):
    """Stop counting this browser (a cookie in the admin's own browser only) and forget its visits of today."""
    from radar import analytics

    _admin(request)
    forgotten = analytics.forget_today(session, analytics.request_visitor(request))
    resp = Response(content=f'{{"excluded": true, "forgotten": {forgotten}}}', media_type="application/json")
    local = request.url.hostname in {"localhost", "127.0.0.1", "::1", "testserver"}
    resp.set_cookie(analytics.IGNORE_COOKIE, "1", max_age=400 * 86400, httponly=True, samesite="lax",
                    secure=not local, path="/")
    return resp


@app.delete("/api/admin/analytics/exclude", include_in_schema=False)
def admin_analytics_include(request: Request):
    from radar import analytics

    _admin(request)
    resp = Response(content='{"excluded": false}', media_type="application/json")
    resp.delete_cookie(analytics.IGNORE_COOKIE, path="/")
    return resp


@app.get("/api/admin/status", include_in_schema=False)
def admin_status(request: Request):
    from radar import admin

    _admin(request)
    return admin.status()


@app.get("/healthz")
def healthz():
    """Liveness: the process is up."""
    return {"ok": True}


@app.get("/readyz")
def readyz():
    """Readiness: the database answers. Kubernetes stops routing to a replica that fails this."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(503, f"database unavailable: {type(e).__name__}") from e
    return {"ok": True}


@app.get("/metrics", include_in_schema=False)
def metrics():
    if settings.redis_url:
        from radar.queue import queue_depths

        for name, depth in queue_depths().items():
            QUEUE_DEPTH.labels(name).set(depth)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/robots.txt", include_in_schema=False)
def robots():
    # The dashboard builds its content from /api/, so search engines may fetch it to render the page; the API
    # responses themselves carry X-Robots-Tag: noindex. Accounts, login links and admin stay out, and AI-training
    # crawlers are asked to stay away altogether (radar/throttle.py refuses them too).
    from radar.throttle import AI_CRAWLERS

    ai = "".join(f"User-agent: {a}\n" for a in AI_CRAWLERS) + "Disallow: /\n\n"
    return Response(ai + "User-agent: *\nAllow: /\nDisallow: /api/admin/\nDisallow: /api/me\nDisallow: /api/auth/\n"
                    f"Disallow: /auth/\nDisallow: /admin/\nSitemap: {settings.site_url.rstrip('/')}/sitemap.xml\n",
                    media_type="text/plain")


def _live_tech_rows(session: Session) -> list[stats.Row]:
    return stats.Filters().apply(stats.CACHE.rows(session))


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap(session: Session = Depends(db)):
    from xml.sax.saxutils import escape as xml_escape

    from radar import pages

    base = settings.site_url.rstrip("/")

    def lastmod(rows) -> str | None:
        # when the newest listing on the page appeared: search engines re-crawl pages whose date moved
        newest = max((r.first_seen for r in rows), default=None)
        return newest.date().isoformat() if newest else None

    def compute():
        from radar import seo

        tech = _live_tech_rows(session)
        rows, landing_pages = _pages_objects(session)
        live = [r for r in rows if r.closed_at is None]
        home = lastmod(tech)
        urls = [(f"{base}/", home), (f"{base}/nl/", home), (f"{base}/companies", home)]
        for lp in landing_pages:
            day = lastmod(seo._filtered(live, lp.filters, lp.city))
            urls += [(base + lp.nl_path, day), (base + lp.en_path, day)]
        for _, slug, n in pages.companies(tech):
            if n >= pages.MIN_INDEXED_POSTINGS:
                day = lastmod(pages.company_rows(tech, slug))
                urls += [(f"{base}/company/{slug}", day), (f"{base}/nl/bedrijf/{slug}", day)]
        body = "".join(f"<url><loc>{xml_escape(u)}</loc>" + (f"<lastmod>{d}</lastmod>" if d else "") + "</url>"
                       for u, d in urls)
        return (f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"{body}</urlset>")

    return Response(cached("sitemap.xml", compute, ttl=3600), media_type="application/xml")


@app.get("/companies", include_in_schema=False)
def companies_page(session: Session = Depends(db)):
    from radar import pages

    return Response(cached("page:companies", lambda: pages.render_companies(_live_tech_rows(session)), ttl=3600),
                    media_type="text/html")


@app.get("/nl/bedrijf/{slug}", include_in_schema=False)
def company_page_nl(slug: str, session: Session = Depends(db)):
    return company_page(slug, session, lang="nl")


@app.get("/company/{slug}", include_in_schema=False)
def company_page(slug: str, session: Session = Depends(db), lang: str = "en"):
    from radar import pages

    rows = _live_tech_rows(session)
    name = pages.find_company(rows, slug)
    if name is None:
        raise HTTPException(404, "no employer with live tech postings under that name")
    return Response(cached(f"page:company:{lang}:{slug}", lambda: pages.render_company(name, rows, lang), ttl=3600),
                    media_type="text/html")


def _seo_pages(session: Session):
    from radar import seo

    rows = stats.CACHE.rows(session)
    return rows, cached("seo:pages", lambda: [p.__dict__ for p in seo.build_pages(rows)], ttl=600)


def _pages_objects(session: Session):
    from radar import seo

    rows, dicts = _seo_pages(session)
    return rows, [seo.Page(**d) for d in dicts]


def _source_link(lang: str = "en", sentence: bool = False) -> str:
    """A link to the public source repository, or nothing while RADAR_SOURCE_URL is unset (a private repository
    would only give visitors a 404)."""
    if not settings.source_url:
        return ""
    from html import escape

    url = escape(settings.source_url)
    if sentence:
        return (f' De broncode staat openbaar op <a href="{url}" rel="noopener">GitHub</a>.' if lang == "nl"
                else f' The source code is public on <a href="{url}" rel="noopener">GitHub</a>.')
    label = "Broncode op GitHub" if lang == "nl" else "Source code on GitHub"
    return f' · <a href="{url}" rel="noopener">{label}</a>'


def _render_index(session: Session | None = None, lang: str = "en") -> str:
    """index.html with branding, a localised title and description carrying the live count, hreflang, and a
    footer of popular search pages. Renaming the site is one env var."""
    import json as _json

    from radar import seo

    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    aliases = [a.strip() for a in settings.site_aliases.split(",") if a.strip()]
    n, m, links = 0, 0, ""
    if session is not None:
        rows, pages = _pages_objects(session)
        live = [r for r in rows if r.closed_at is None]
        n, m = len(live), len({r.company for r in live})
        links = seo.popular_links(pages, lang)
    count = f"{n:,}".replace(",", "." if lang == "nl" else ",") if n else ""
    if lang == "nl":
        title = f"{settings.site_name}: {count + ' ' if count else ''}ICT en tech vacatures in Nederland"
        desc = (f"{count + ' ' if count else ''}actuele IT- en ICT-vacatures van {m or 'honderden'} werkgevers, "
                "rechtstreeks van hun eigen carrièresites: developer, data, AI, cloud en security. Filter op "
                "Engelstalig, visumsponsoring, junior, traineeship en stad.")
    else:
        title = f"{settings.site_name}: {count + ' ' if count else ''}tech jobs in the Netherlands"
        desc = (f"{count + ' ' if count else ''}live IT and tech jobs from {m or 'hundreds of'} Dutch employers' own "
                "career sites: software, data, AI, cloud, security. Filter on English-speaking, visa sponsorship, "
                "junior, traineeship and city.")
    ld = {
        "@context": "https://schema.org", "@type": "WebSite", "name": settings.site_name,
        "alternateName": aliases, "url": settings.site_url, "description": settings.site_tagline,
        "inLanguage": ["en", "nl"],
    }
    return (html.replace("{{SITE_NAME}}", settings.site_name)
                .replace("{{SITE_URL}}", settings.site_url.rstrip("/"))
                .replace("{{SITE_TAGLINE}}", settings.site_tagline)
                .replace("{{SITE_ALIASES}}", ", ".join(aliases))
                .replace("{{SITE_JSONLD}}", _json.dumps(ld))
                .replace("{{HTML_LANG}}", lang)
                .replace("{{HOME_PATH}}", "/nl/" if lang == "nl" else "/")
                .replace("{{PAGE_TITLE}}", title)
                .replace("{{META_DESCRIPTION}}", desc)
                .replace("{{VERIFY}}", seo.verification_meta())
                .replace("{{SOURCE_LINK}}", _source_link(lang))
                .replace("{{PRIVACY_PATH}}", "/nl/privacy" if lang == "nl" else "/privacy")
                .replace("{{FEEDBACK_PATH}}", "/nl/feedback" if lang == "nl" else "/feedback")
                .replace("{{SEO_LINKS}}", links))


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index(session: Session = Depends(db)):
        stats.CACHE.rows(session)  # the title carries the live count: cache the page per load of the rows
        return Response(cached(f"page:index:en:{stats.CACHE.loads}", lambda: _render_index(session, "en"), ttl=300),
                        media_type="text/html")

    @app.get("/nl/", include_in_schema=False)
    @app.get("/nl", include_in_schema=False)
    def index_nl(session: Session = Depends(db)):
        stats.CACHE.rows(session)
        return Response(cached(f"page:index:nl:{stats.CACHE.loads}", lambda: _render_index(session, "nl"), ttl=300),
                        media_type="text/html")

    @app.get("/login", include_in_schema=False)
    @app.get("/nl/inloggen", include_in_schema=False)
    def login_page(request: Request):
        lang = "nl" if request.url.path.startswith("/nl") else "en"
        html = (WEB_DIR / "login.html").read_text(encoding="utf-8")
        return Response(html.replace("{{HTML_LANG}}", lang).replace("{{SITE_NAME}}", settings.site_name),
                        media_type="text/html", headers={"X-Robots-Tag": "noindex"})

    @app.get("/feedback", include_in_schema=False)
    @app.get("/nl/feedback", include_in_schema=False)
    def feedback_page(request: Request):
        lang = "nl" if request.url.path.startswith("/nl") else "en"
        html = (WEB_DIR / "feedback.html").read_text(encoding="utf-8")
        return Response(html.replace("{{HTML_LANG}}", lang).replace("{{SITE_NAME}}", settings.site_name),
                        media_type="text/html", headers={"X-Robots-Tag": "noindex"})

    @app.get("/admin/analytics", include_in_schema=False)
    def analytics_page():
        return Response((WEB_DIR / "analytics.html").read_text(encoding="utf-8")
                        .replace("{{SITE_NAME}}", settings.site_name), media_type="text/html",
                        headers={"X-Robots-Tag": "noindex", "Cache-Control": "no-store"})

    @app.get("/privacy", include_in_schema=False)
    @app.get("/nl/privacy", include_in_schema=False)
    def privacy(request: Request):
        lang = "nl" if request.url.path.startswith("/nl") else "en"
        html = (WEB_DIR / "privacy.html").read_text(encoding="utf-8")
        return Response(html.replace("{{HTML_LANG}}", lang).replace("{{SITE_NAME}}", settings.site_name)
                        .replace("{{SOURCE_EN}}", _source_link("en", sentence=True))
                        .replace("{{SOURCE_NL}}", _source_link("nl", sentence=True)), media_type="text/html")

    @app.get("/vacatures/{slug}", include_in_schema=False)
    @app.get("/jobs/{slug}", include_in_schema=False)
    def landing(slug: str, request: Request, session: Session = Depends(db)):
        from radar import seo

        rows, pages = _pages_objects(session)
        hit = seo.find(pages, request.url.path)
        if hit is None:
            raise HTTPException(404, "no page for this search yet")
        page, lang = hit
        body = cached(f"page:landing:{request.url.path}", lambda: seo.render(page, lang, rows, pages), ttl=600)
        return Response(body, media_type="text/html")
