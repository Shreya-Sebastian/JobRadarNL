from sqlalchemy import text

from radar import db


def test_a_forked_process_gets_its_own_connection_pool(fresh_db, monkeypatch):
    engine = db.get_engine()
    with engine.connect() as c:
        c.execute(text("select 1"))
    parent_pool = engine.pool
    real_pid = db.os.getpid()
    monkeypatch.setattr(db.os, "getpid", lambda: real_pid + 1)  # as seen from inside a forked RQ job
    assert db.get_engine() is engine and engine.pool is not parent_pool  # inherited connections dropped
    with db.session_scope() as s:
        assert s.execute(text("select 1")).scalar() == 1
    child_pool = engine.pool
    db.get_engine()
    assert engine.pool is child_pool  # same process again: the pool is kept
