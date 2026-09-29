"""Per-host request rate limiting, shared across every worker through Redis.

With one crawler process a local throttle is enough. With fifty worker pods hitting Workable at once, the
limit has to live somewhere they all see. Fixed one-second windows in Redis are simple and good enough:
INCR on `rl:{host}:{second}`; if the count exceeds the host's budget, sleep until the next second.
Without Redis the limiter degrades to a process-local version with the same interface.
"""

from __future__ import annotations

import threading
import time

import httpx

from radar.config import host_rate_limits, settings


class LocalRateLimiter:
    def __init__(self, limits: dict[str, float]):
        self.limits = limits
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def rate(self, host: str) -> float:
        return self.limits.get(host, self.limits["default"])

    def acquire(self, host: str) -> None:
        interval = 1.0 / max(self.rate(host), 0.01)
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next.get(host, 0.0))
            self._next[host] = start + interval
        delay = start - now
        if delay > 0:
            time.sleep(delay)


class RedisRateLimiter(LocalRateLimiter):
    def __init__(self, limits: dict[str, float], redis_client):
        super().__init__(limits)
        self.redis = redis_client

    def acquire(self, host: str) -> None:
        budget = max(1, int(round(self.rate(host))))
        if self.rate(host) < 1:
            # sub-1 rps: use a window of ceil(1/rate) seconds with a budget of one request
            window = int(round(1.0 / self.rate(host)))
            budget = 1
        else:
            window = 1
        while True:
            slot = int(time.time()) // window
            key = f"rl:{host}:{slot}"
            pipe = self.redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, window + 1)
            count, _ = pipe.execute()
            if count <= budget:
                return
            time.sleep(((slot + 1) * window) - time.time() + 0.01)


_limiter: LocalRateLimiter | None = None
_limiter_lock = threading.Lock()


def get_limiter() -> LocalRateLimiter:
    global _limiter
    with _limiter_lock:
        if _limiter is None:
            limits = host_rate_limits()
            if settings.redis_url:
                try:
                    import redis

                    client = redis.Redis.from_url(settings.redis_url, socket_timeout=2)
                    client.ping()
                    _limiter = RedisRateLimiter(limits, client)
                except Exception:
                    _limiter = LocalRateLimiter(limits)
            else:
                _limiter = LocalRateLimiter(limits)
        return _limiter


# Multi-tenant platforms rate-limit per IP across all their customer subdomains, so 900 Recruitee boards must
# share one budget rather than each getting the default one.
_SHARED_SUFFIXES = ("recruitee.com", "teamtailor.com", "jobs.personio.de", "jobs.personio.com", "myworkdayjobs.com",
                    "homerun.co")


def host_key(host: str) -> str:
    host = host.lower()
    for suffix in _SHARED_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            return suffix
    return host


def throttle_request(request: httpx.Request) -> None:
    """httpx event hook: block until this host has budget for one more request."""
    get_limiter().acquire(host_key(request.url.host))
