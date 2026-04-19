"""Integrations Hub — per-user OAuth connections to third-party providers.

Each provider is described by a `ProviderSpec` (see `oauth.py`). Providers
register themselves by importing and calling `register_provider(...)`.

Public surface:
    integrations.list_providers()         -> dict[slug, ProviderSpec]
    integrations.get_provider(slug)       -> ProviderSpec | None
    integrations.providers_by_category()  -> dict[category, list[ProviderSpec]]
    integrations.get_connection(...)      -> Connection | None
    integrations.disconnect(...)          -> bool
    integrations.has_scopes(...)          -> bool
    integrations.missing_scopes(...)      -> list[str]
"""
from __future__ import annotations

from db import get_session
from db_models import Connection


PROVIDERS: dict = {}


CATEGORIES: list[tuple[str, str]] = [
    ("popular", "Popular"),
    ("campus", "Campus"),
    ("crm", "CRM & Marketing"),
    ("ops", "Ops & Productivity"),
    ("social", "Social & Promo"),
    ("messaging", "Messaging"),
    ("identity", "Identity"),
    ("other", "Other"),
]


def register_provider(spec) -> None:
    PROVIDERS[spec.slug] = spec


def list_providers() -> dict:
    return dict(PROVIDERS)


def get_provider(slug: str):
    return PROVIDERS.get(slug)


def providers_by_category() -> dict:
    """Return {category_slug: [ProviderSpec, ...]} with stable ordering.

    The Popular list is synthesized from any provider flagged `is_popular=True`.
    Default-layer providers (is_default=True, e.g. Google) are omitted since
    they're embedded and shouldn't appear as Hub tiles.
    """
    buckets: dict[str, list] = {cat: [] for cat, _ in CATEGORIES}
    for spec in PROVIDERS.values():
        if getattr(spec, "is_default", False):
            continue
        cat = getattr(spec, "category", "other") or "other"
        buckets.setdefault(cat, []).append(spec)
        if getattr(spec, "is_popular", False):
            buckets["popular"].append(spec)
    for cat in buckets:
        buckets[cat].sort(key=lambda s: s.display_name.lower())
    return buckets


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


def missing_scopes(user_id: str, provider: str, required: list[str]) -> list[str]:
    """Return the subset of `required` scopes NOT granted for this user+provider.
    Returns the full `required` list if no connection exists.
    """
    conn = get_connection(user_id, provider)
    if conn is None:
        return list(required)
    granted = set(conn.scopes or [])
    return [s for s in required if s not in granted]


# Side-effect: import provider modules so they register. Keep at bottom
# to avoid circular imports.
from . import google  # noqa: E402,F401

# Third-party provider pack (Phases C-I). Each module self-registers with
# `register_provider(...)`. Import failures are swallowed so a missing optional
# dependency for one provider never crashes the whole app.
def _autoload_providers() -> None:
    import importlib

    names = [
        # Messaging
        "integrations.providers.discord",
        "integrations.providers.whatsapp",
        # Campus
        "integrations.providers.canvas",
        "integrations.providers.twentyfivelive",
        "integrations.providers.handshake",
        "integrations.providers.sis",
        "integrations.providers.qualtrics",
        "integrations.providers.engage",
        # Registration & ticketing
        "integrations.providers.eventbrite",
        "integrations.providers.luma",
        "integrations.providers.wallet",
        # CRM & Marketing
        "integrations.providers.hubspot",
        "integrations.providers.salesforce",
        "integrations.providers.mailchimp",
        "integrations.providers.linkedin_sales",
        # Ops & Productivity
        "integrations.providers.notion",
        "integrations.providers.airtable",
        "integrations.providers.linear",
        "integrations.providers.asana",
        "integrations.providers.trello",
        "integrations.providers.clickup",
        "integrations.providers.quickbooks",
        "integrations.providers.xero",
        # Social & Promo
        "integrations.providers.buffer",
        "integrations.providers.hootsuite",
        "integrations.providers.canva",
        "integrations.providers.meta",
        "integrations.providers.linkedin_pages",
        # Identity
        "integrations.providers.okta",
    ]
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as exc:  # pragma: no cover
            import logging
            logging.getLogger(__name__).warning("provider %s failed to load: %s", name, exc)


_autoload_providers()
