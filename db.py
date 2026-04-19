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


def _scalar_default_sql(col) -> str | None:
    """Render a column's Python-side scalar default as a dialect-safe SQL literal.

    Returns None for callable/sentinel defaults we don't know how to serialize;
    the caller simply omits DEFAULT in that case.
    """
    default = col.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    val = default.arg
    if isinstance(val, bool):
        if _is_sqlite:
            return "1" if val else "0"
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        return "'" + val.replace("'", "''") + "'"
    return None


def _backfill_missing_columns() -> None:
    """Add columns that exist in the ORM models but not in the live DB.

    SQLAlchemy's create_all() only creates missing tables; it never ALTERs
    existing ones. This helper closes that gap for additive migrations so
    feature branches that add new columns (e.g. users.is_active for SCIM)
    don't require hand-written migration scripts to deploy.

    Only handles ADD COLUMN. Type/constraint changes still need real migrations.
    """
    from sqlalchemy import inspect as sa_inspect
    import db_models  # noqa: F401

    insp = sa_inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                col_type_sql = col.type.compile(dialect=engine.dialect)
                parts = [f'"{col.name}"', col_type_sql]
                default_sql = _scalar_default_sql(col)
                if default_sql is not None:
                    parts.append(f"DEFAULT {default_sql}")
                if not col.nullable:
                    if default_sql is None:
                        parts.append("DEFAULT ''" if "CHAR" in col_type_sql.upper() or "TEXT" in col_type_sql.upper() else "DEFAULT 0")
                    parts.append("NOT NULL")
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN ' + " ".join(parts)
                conn.exec_driver_sql(ddl)


def init_db() -> None:
    """Create tables if absent, then backfill any new columns on existing tables.

    Imports db_models inside to avoid circular import at module load.
    """
    import db_models  # noqa: F401  (registers mappers on Base)

    Base.metadata.create_all(bind=engine)
    _backfill_missing_columns()


def is_sqlite() -> bool:
    return _is_sqlite
