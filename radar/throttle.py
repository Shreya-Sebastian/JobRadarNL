"""Limits on how fast one visitor can fetch pages and API responses, and a refusal for bulk scrapers.

Every listing is public, so nothing stops a patient scraper from collecting it slowly; the point is that nobody can
pull the whole site in a few minutes or load the server doing it. Requests are counted per client IP in one-minute
windows (in Redis when configured, so all API replicas share the count), with a lower limit for the listing and
detail endpoints a scraper would page through. Known AI-training crawlers and plain HTTP libraries are refused
outright; search engines are not, and robots.txt tells the crawlers that honour it the same thing.
"""

from __future__ import annotations

import re
import threading
import time

from radar.config import settings

# AI-training and bulk crawlers, and HTTP libraries that no browser sends
BLOCKED_AGENTS = re.compile(
    r"GPTBot|ChatGPT-User|OAI-SearchBot|CCBot|ClaudeBot|Claude-Web|anthropic-ai|Google-Extended|Bytespider|"
    r"PerplexityBot|Amazonbot|meta-externalagent|FacebookBot|Applebot-Extended|cohere-ai|Diffbot|ImagesiftBot|"
    r"Omgili|Timpibot|Scrapy|python-requests|python-urllib|aiohttp|httpx|Go-http-client|okhttp|curl/|Wget|"
    r"libwww-perl|HeadlessChrome|PhantomJS",
    re.I,
)
AI_CRAWLERS = ("GPTBot", "ChatGPT-User", "OAI-SearchBot", "CCBot", "ClaudeBot", "anthropic-ai", "Google-Extended",
               "Bytespider", "PerplexityBot", "Amazonbot", "meta-externalagent", "Applebot-Extended", "cohere-ai",
               "Diffbot", "ImagesiftBot", "Omgili", "Timpibot")

_EXEMPT = ("/healthz", "/readyz", "/metrics", "/robots.txt", "/static/", "/favicon")
_DETAIL = re.compile(r"^/api/postings|^/(?:nl/)?(?:jobs|job|vacatures|vacature|company|bedrijf)/")

_local: dict[str, int] = {}
_local_lock = threading.Lock()
_redis = None
_redis_checked = False


def _client():
    global _redis, _redis_checked
    if not _redis_checked:
        _redis_checked = True
        if settings.redis_url:
            try:
                import redis

                _redis = redis.Redis.from_url(settings.redis_url, socket_timeout=1)
                _redis.ping()
            except Exception:
                _redis = None
    return _redis


def _count(key: str) -> int:
    r = _client()
    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.incr(key)
            pipe.expire(key, 120)
            return int(pipe.execute()[0])
        except Exception:
            pass  # Redis down: fall back to counting in this process
    with _local_lock:
        if len(_local) > 50_000:
            _local.clear()
        _local[key] = _local.get(key, 0) + 1
        return _local[key]


def check(path: str, ip: str, agent: str) -> tuple[int, str] | None:
    """None when the request may go ahead, else (status, reason)."""
    if path.startswith(_EXEMPT):
        return None
    if settings.block_scraper_agents and (not agent or BLOCKED_AGENTS.search(agent)):
        return 403, "automated access is not permitted, see /robots.txt"
    if settings.rate_limit_per_minute <= 0 or not ip:
        return None
    minute = int(time.time() // 60)
    if _count(f"rl:{minute}:{ip}") > settings.rate_limit_per_minute:
        return 429, "too many requests"
    if _DETAIL.match(path) and _count(f"rld:{minute}:{ip}") > settings.rate_limit_detail_per_minute:
        return 429, "too many requests"
    return None


def reset() -> None:
    global _redis, _redis_checked
    with _local_lock:
        _local.clear()
    _redis, _redis_checked = None, False
