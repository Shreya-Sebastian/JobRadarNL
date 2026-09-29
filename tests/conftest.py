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
