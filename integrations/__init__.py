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


CATEGORY_LABELS = dict(CATEGORIES)


def setup_status() -> list[dict]:
    """Return a per-provider setup checklist.

    Each row has::
        {
          "slug": str,
          "display_name": str,
          "category": str,
          "category_label": str,
          "auth_style": str,
          "configured": bool,
          "docs_url": str,
          "env_vars": [{"name": str, "set": bool, "required": bool}, ...],
        }

    Never returns env-var *values* — only whether each key is present. Admins
    see this via `GET /admin/setup`.
    """
    import os

    rows: list[dict] = []
    for spec in PROVIDERS.values():
        env_specs: list[tuple[str, bool]] = []  # (name, required)
        if spec.auth_style == "oauth2":
            for attr in ("client_id_env", "client_secret_env", "redirect_uri_env"):
                v = getattr(spec, attr, "") or ""
                if v:
                    env_specs.append((v, True))
        elif spec.auth_style == "api_key":
            if getattr(spec, "api_key_env", ""):
                env_specs.append((spec.api_key_env, True))
        else:
            # custom / bot_token / basic: client_id_env (if set) drives
            # configured(). Treat it as required; everything else optional.
            cid = getattr(spec, "client_id_env", "") or ""
            if cid:
                env_specs.append((cid, True))
        for extra in getattr(spec, "extra_env", []) or []:
            if extra and not any(e == extra for e, _ in env_specs):
                env_specs.append((extra, False))
        # Webhook secret, if any, is always optional (webhooks just won't verify).
        wh = getattr(spec, "webhook_secret_env", "") or ""
        if wh and not any(e == wh for e, _ in env_specs):
            env_specs.append((wh, False))

        env_vars = [
            {"name": name, "set": bool(os.environ.get(name, "").strip()), "required": required}
            for name, required in env_specs
        ]

        rows.append({
            "slug": spec.slug,
            "display_name": spec.display_name,
            "category": spec.category,
            "category_label": CATEGORY_LABELS.get(spec.category, spec.category.title()),
            "auth_style": spec.auth_style,
            "configured": spec.configured(),
            "docs_url": getattr(spec, "docs_url", ""),
            "env_vars": env_vars,
            "is_default": bool(getattr(spec, "is_default", False)),
        })

    # Default-layer (Google) first, then alphabetical by category + name.
    cat_order = {cat: i for i, (cat, _) in enumerate(CATEGORIES)}
    rows.sort(key=lambda r: (
        0 if r["is_default"] else 1,
        cat_order.get(r["category"], 99),
        r["display_name"].lower(),
    ))
    return rows


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
