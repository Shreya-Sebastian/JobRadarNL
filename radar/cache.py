"""Response cache and data-version signalling.

API processes keep the live rows in memory. When a finalize job changes the data, it bumps a version key in
Redis; every API process notices on its next request and reloads. Heavy responses are cached in Redis under
the current version, so a new version simply starts a fresh namespace. Without Redis everything falls back
to process-local behaviour with a short TTL.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from radar.config import settings

_VERSION_KEY = "radar:data_version"
_local: dict[str, tuple[float, Any]] = {}
_local_lock = threading.Lock()
_local_version = str(int(time.time()))


def _redis():
    if not settings.redis_url:
        return None
    try:
        from radar.queue import get_redis

        r = get_redis()
        r.ping()
        return r
    except Exception:
        return None


_db_version_cache: tuple[float, str] = (0.0, "")


def _db_version() -> str:
    """Version stored in the database (the `meta` table), polled at most once every few seconds per process,
    so a finalize job in another process is noticed even without Redis."""
    global _db_version_cache
    at, v = _db_version_cache
    if time.monotonic() - at < 5:
        return v
    try:
        from radar.db import new_session
        from radar.models import Meta

        s = new_session()
        try:
            row = s.get(Meta, "data_version")
            v = row.value if row else "0"
        finally:
            s.close()
    except Exception:
        v = _local_version
    _db_version_cache = (time.monotonic(), v)
    return v


def data_version() -> str:
    r = _redis()
    if r is not None:
        v = r.get(_VERSION_KEY)
        if v:
            return v.decode()
    return _db_version()


def bump_data_version() -> str:
    global _local_version, _db_version_cache
    v = str(int(time.time() * 1000))
    r = _redis()
    if r is not None:
        r.set(_VERSION_KEY, v)
    try:
        from radar.db import new_session
        from radar.models import Meta

        s = new_session()
        try:
            row = s.get(Meta, "data_version")
            if row:
                row.value = v
            else:
                s.add(Meta(key="data_version", value=v))
            s.commit()
        finally:
            s.close()
    except Exception:
        pass
    _local_version = v
    _db_version_cache = (time.monotonic(), v)
    with _local_lock:
        _local.clear()
    return v


def cached(key: str, fn, ttl: int | None = None) -> Any:
    """Return fn() cached under key for the current data version."""
    ttl = ttl or settings.cache_ttl_seconds
    full = f"api:{data_version()}:{key}"
    r = _redis()
    if r is not None:
        hit = r.get(full)
        if hit is not None:
            return json.loads(hit)
        value = fn()
        r.setex(full, ttl, json.dumps(value, default=str))
        return value
    with _local_lock:
        entry = _local.get(full)
        if entry and entry[0] > time.monotonic():
            return entry[1]
    value = fn()
    with _local_lock:
        _local[full] = (time.monotonic() + ttl, value)
        if len(_local) > 2000:
            _local.clear()
    return value
