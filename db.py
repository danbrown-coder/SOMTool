"""SQLAlchemy engine, session, and base. Supports Postgres (prod) and SQLite (dev fallback)."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DATA_DIR = Path(__file__).resolve().parent / "data"


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        # Render/Heroku style URLs use postgres:// but SQLAlchemy wants postgresql://
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        # Prefer psycopg v3 driver if the user didn't pick one
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://") :]
        return url
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(DATA_DIR / 'somtool.db').as_posix()}"


DATABASE_URL = _database_url()
_is_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)


if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_conn, _):  # pragma: no cover
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


@contextmanager
def get_session() -> Iterator[Session]:
    """Context-managed session with automatic commit/rollback."""
    sess = SessionLocal()
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def init_db() -> None:
    """Create tables if absent. Safe to call multiple times.

    Imports db_models inside to avoid circular import at module load.
    """
    import db_models  # noqa: F401  (registers mappers on Base)

    Base.metadata.create_all(bind=engine)


def is_sqlite() -> bool:
    return _is_sqlite
