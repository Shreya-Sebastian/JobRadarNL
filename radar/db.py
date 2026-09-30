import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from radar.config import settings
from radar.models import Base

_engine = None
_SessionLocal = None
_engine_pid = None


def get_engine(url: str | None = None):
    global _engine, _SessionLocal, _engine_pid
    if _engine is not None and _engine_pid != os.getpid():
        # A forked child (every RQ job runs in one) must not use the parent's pooled connections: both processes
        # would talk over the same socket and the next job fails with "SSL error: unexpected eof". Forget the
        # inherited pool without closing it (closing would cut the parent's connections) and open fresh ones.
        _engine.dispose(close=False)
        _engine_pid = os.getpid()
    if _engine is None or url is not None:
        _engine_pid = os.getpid()
        url = url or settings.database_url
        connect_args = {"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=connect_args, future=True)
        if url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _):
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()

        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def init_db(url: str | None = None) -> None:
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine) -> None:
    """Prototype-grade forward migration: add columns that exist in the models but not in the database.
    Production uses Alembic; this keeps a local SQLite file usable across model changes."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}"
                conn.execute(text(ddl))


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def new_session() -> Session:
    get_engine()
    return _SessionLocal()
