"""Organization (workspace) layer.

Currently single-tenant: we auto-seed a single `default` Organization and
every tenant-scoped row carries its id. When multi-tenant is turned on,
swap `current_org_id()` for a per-request lookup.
"""
from __future__ import annotations

from db import get_session
from db_models import Organization
from models import new_id

DEFAULT_ORG_ID = "org_default_000000000000000000"
DEFAULT_ORG_SLUG = "default"
DEFAULT_ORG_NAME = "Cal Lutheran SOM"


def ensure_default_org() -> str:
    """Create the default Organization row if it doesn't exist. Returns its id."""
    with get_session() as sess:
        org = sess.get(Organization, DEFAULT_ORG_ID)
        if org is None:
            org = Organization(
                id=DEFAULT_ORG_ID,
                name=DEFAULT_ORG_NAME,
                slug=DEFAULT_ORG_SLUG,
                plan="free",
            )
            sess.add(org)
        return DEFAULT_ORG_ID


def current_org_id() -> str:
    """Return the caller's active Organization id.

    Single-tenant today: always the default org. In multi-tenant mode this
    will pull from the Flask session / request context.
    """
    return DEFAULT_ORG_ID


def get_org(org_id: str) -> Organization | None:
    with get_session() as sess:
        org = sess.get(Organization, org_id)
        if org is not None:
            sess.expunge(org)
        return org


def set_org_plan(org_id: str, plan: str, stripe_customer_id: str | None = None,
                 stripe_subscription_id: str | None = None) -> None:
    with get_session() as sess:
        org = sess.get(Organization, org_id)
        if org is None:
            return
        org.plan = plan
        if stripe_customer_id is not None:
            org.stripe_customer_id = stripe_customer_id
        if stripe_subscription_id is not None:
            org.stripe_subscription_id = stripe_subscription_id
