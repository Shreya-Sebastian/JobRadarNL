"""robots.txt for the generic careers-page crawler.

The ATS adapters call public APIs that exist for this purpose, so robots.txt does not apply to them. The
JSON-LD adapter, however, fetches ordinary web pages from employers' and boards' own sites, and those sites
express their wishes in robots.txt. We honour Disallow rules and Crawl-delay (AcademicTransfer asks for
10 seconds between requests) by lowering the per-host rate limit. One fetch per host per process, cached.

Matching follows the Robots Exclusion Protocol as Google and Bing apply it: within the group for our agent
(or `*`), the most specific (longest) matching rule wins and Allow beats Disallow on a tie. Python's
urllib.robotparser takes the first matching rule instead, which reads Netflix's "Disallow: / Allow: /careers"
as a ban on the very pages the site's own sitemap advertises.
"""

from __future__ import annotations

import logging
import re
import threading
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

OUR_TOKEN = "nl-tech-job-radar"


class Rules:
    def __init__(self) -> None:
        self.rules: list[tuple[bool, str]] = []  # (allow, pattern)
        self.crawl_delay: float | None = None

    def add(self, allow: bool, pattern: str) -> None:
        self.rules.append((allow, pattern))

    @staticmethod
    def _matches(pattern: str, path: str) -> bool:
        if not pattern:
            return False
        anchored = pattern.endswith("$")
        if anchored:
            pattern = pattern[:-1]
        rx = ".*".join(re.escape(part) for part in pattern.split("*"))
        return re.match(rx + ("$" if anchored else ""), path) is not None

    def allowed(self, path: str) -> bool:
        best: tuple[int, bool] | None = None
        for allow, pattern in self.rules:
            if self._matches(pattern, path):
                score = (len(pattern), allow)  # longest wins; Allow wins a tie
                if best is None or score > best:
                    best = score
        return True if best is None else best[1]


def parse(text: str, agent_token: str = OUR_TOKEN) -> Rules:
    """Rules for our agent token if a group names it, else the `*` group; no group means everything allowed."""
    groups: dict[str, Rules] = {}
    current: list[str] = []
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if not last_was_agent:
                current = []
            current.append(value.lower())
            for a in current:
                groups.setdefault(a, Rules())
            last_was_agent = True
            continue
        last_was_agent = False
        if not current:
            continue
        for a in current:
            g = groups[a]
            if key == "allow":
                g.add(True, value)
            elif key == "disallow":
                if value:
                    g.add(False, value)
            elif key == "crawl-delay":
                try:
                    g.crawl_delay = max(g.crawl_delay or 0, float(value))
                except ValueError:
                    pass
            elif key == "request-rate":
                m = re.match(r"(\d+)\s*/\s*(\d+)([smh]?)", value)
                if m:
                    n, per, unit = int(m.group(1)), int(m.group(2)), m.group(3)
                    per *= {"m": 60, "h": 3600}.get(unit, 1)
                    if n:
                        g.crawl_delay = max(g.crawl_delay or 0, per / n)
    token = agent_token.lower()
    for name, g in groups.items():
        if name != "*" and name in token:
            return g
    return groups.get("*", Rules())


_cache: dict[str, Rules | None] = {}
_lock = threading.Lock()


def _load(host: str, scheme: str, client: httpx.Client) -> Rules | None:
    with _lock:
        if host in _cache:
            return _cache[host]
    rules: Rules | None
    try:
        resp = client.get(f"{scheme}://{host}/robots.txt")
        if resp.status_code >= 400 or "text" not in resp.headers.get("content-type", "text/plain"):
            rules = None  # no robots.txt: everything allowed
        else:
            rules = parse(resp.text)
    except Exception:
        rules = None
    with _lock:
        _cache[host] = rules
    if rules is not None and rules.crawl_delay:
        from radar.ratelimit import get_limiter

        limiter = get_limiter()
        wanted = 1.0 / float(rules.crawl_delay)
        if wanted < limiter.rate(host):
            limiter.limits[host] = wanted
            log.info("robots.txt for %s asks for %ss between requests; rate limited to %.2f/s",
                     host, rules.crawl_delay, wanted)
    return rules


def allowed(url: str, client: httpx.Client) -> bool:
    """True unless the host's robots.txt disallows this path for everyone (or for our agent)."""
    u = urlparse(url)
    if not u.netloc:
        return True
    rules = _load(u.netloc.lower(), u.scheme or "https", client)
    if rules is None:
        return True
    path = u.path or "/"
    if u.query:
        path += "?" + u.query
    return rules.allowed(path)


def reset() -> None:
    with _lock:
        _cache.clear()
