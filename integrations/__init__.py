"""Integrations Hub — per-user OAuth connections to third-party providers.

Each provider is described by a `ProviderSpec` (see `oauth.py`). Providers
register themselves by importing and calling `register_provider(...)`.

Public surface:
    integrations.list_providers() -> dict[slug, ProviderSpec]
    integrations.get_provider(slug) -> ProviderSpec | None
    integrations.get_connection(user_id, slug) -> Connection | None
    integrations.disconnect(user_id, slug) -> bool
"""
from __future__ import annotations

from db import get_session
from db_models import Connection


PROVIDERS: dict = {}


def register_provider(spec) -> None:
    PROVIDERS[spec.slug] = spec


def list_providers() -> dict:
    return dict(PROVIDERS)


def get_provider(slug: str):
    return PROVIDERS.get(slug)


def get_connection(user_id: str, provider: str) -> Connection | None:
    with get_session() as sess:
        row = (
            sess.query(Connection)
            .filter(Connection.user_id == user_id, Connection.provider == provider)
            .first()
        )
        if row is not None:
            sess.expunge(row)
        return row


def list_user_connections(user_id: str) -> list[Connection]:
    with get_session() as sess:
        rows = sess.query(Connection).filter(Connection.user_id == user_id).all()
        for r in rows:
            sess.expunge(r)
        return rows


def disconnect(user_id: str, provider: str) -> bool:
    with get_session() as sess:
        rows = (
            sess.query(Connection)
            .filter(Connection.user_id == user_id, Connection.provider == provider)
            .all()
        )
        for r in rows:
            sess.delete(r)
        return bool(rows)


def has_scopes(user_id: str, provider: str, required: list[str]) -> bool:
    conn = get_connection(user_id, provider)
    if conn is None:
        return False
    granted = set(conn.scopes or [])
    return all(s in granted for s in required)


# Side-effect: import provider modules so they register. Keep at bottom
# to avoid circular imports.
from . import google  # noqa: E402,F401
