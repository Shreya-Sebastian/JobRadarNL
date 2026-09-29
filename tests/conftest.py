import pytest

from radar import db as radar_db


@pytest.fixture
def fresh_db(tmp_path):
    """A throwaway SQLite database bound to the global engine for the duration of the test."""
    url = f"sqlite:///{tmp_path / 'test.db'}"
    radar_db.init_db(url)
    from radar import cache
    from radar.stats import CACHE

    CACHE.invalidate()
    with cache._local_lock:
        cache._local.clear()  # response cache must not leak between test databases
    yield url
    radar_db._engine = None
    radar_db._SessionLocal = None


@pytest.fixture(autouse=True)
def _no_analytics(monkeypatch):
    """Page-view recording is off in tests unless a test turns it on (tests/test_analytics.py)."""
    from radar import analytics
    from radar.config import settings

    monkeypatch.setattr(settings, "analytics_enabled", False)
    analytics._buffer.clear()
    analytics._salt = None
    yield
    analytics._buffer.clear()
