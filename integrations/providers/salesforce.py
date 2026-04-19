"""Salesforce — same CRM surface as HubSpot via a shared adapter pattern.

Salesforce uses OAuth2 with per-org instance URLs. The access-token response
includes an `instance_url` which we persist in the connection's `meta` so API
calls know which pod to hit.

Environment:
  SALESFORCE_CLIENT_ID=...
  SALESFORCE_CLIENT_SECRET=...
  SALESFORCE_REDIRECT_URI=...
  SALESFORCE_LOGIN_URL=https://login.salesforce.com   # or test.salesforce.com
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from integrations.oauth import ProviderSpec, get_valid_access_token
from integrations import register_provider, get_connection

logger = logging.getLogger(__name__)


LOGIN = (os.environ.get("SALESFORCE_LOGIN_URL") or "https://login.salesforce.com").rstrip("/")


SPEC = ProviderSpec(
    slug="salesforce",
    display_name="Salesforce",
    authorize_url=f"{LOGIN}/services/oauth2/authorize",
    token_url=f"{LOGIN}/services/oauth2/token",
    scopes=["api", "refresh_token", "offline_access"],
    client_id_env="SALESFORCE_CLIENT_ID",
    client_secret_env="SALESFORCE_CLIENT_SECRET",
    redirect_uri_env="SALESFORCE_REDIRECT_URI",
    icon_emoji="SF",
    category="crm",
    description="Mirror your People directory with Salesforce Contacts + Leads.",
    unlocks=[
        "People ↔ Salesforce Contact upsert",
        "Event attendance as Campaign Members",
        "Per-org instance-URL aware",
    ],
    auth_style="oauth2",
    docs_url="https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/intro_rest.htm",
)
register_provider(SPEC)


def _instance(user_id: str) -> Optional[str]:
    conn = get_connection(user_id, SPEC.slug)
    if conn is None:
        return None
    return (conn.meta or {}).get("instance_url") or ""


def upsert_contact(user_id: str, person) -> Optional[str]:
    tok = get_valid_access_token(user_id, SPEC.slug)
    inst = _instance(user_id)
    if not tok or not inst or not person.email:
        return None
    body = {
        "FirstName": (person.name or "").split(" ")[0],
        "LastName": " ".join((person.name or "").split(" ")[1:]) or (person.name or person.email),
        "Email": person.email,
        "Title": person.role or "",
        "Phone": person.phone or "",
    }
    try:
        r = requests.patch(
            f"{inst.rstrip('/')}/services/data/v60.0/sobjects/Contact/Email/{person.email}",
            json=body,
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            timeout=20,
        )
        if r.status_code in (200, 201, 204):
            return (r.json() or {}).get("id") if r.content else "upserted"
        r.raise_for_status()
        return None
    except Exception as exc:
        logger.warning("Salesforce upsert_contact failed: %s", exc)
        return None
