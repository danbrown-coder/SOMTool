"""HubSpot CRM — bi-directional `people` ↔ `contacts`.

Environment:
  HUBSPOT_CLIENT_ID=...
  HUBSPOT_CLIENT_SECRET=...
  HUBSPOT_REDIRECT_URI=...
  HUBSPOT_WEBHOOK_SECRET=...
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from integrations.oauth import ProviderSpec, get_valid_access_token
from integrations import register_provider
from integrations.webhooks import register_webhook, verify_hmac_sha256

logger = logging.getLogger(__name__)


SPEC = ProviderSpec(
    slug="hubspot",
    display_name="HubSpot",
    authorize_url="https://app.hubspot.com/oauth/authorize",
    token_url="https://api.hubapi.com/oauth/v1/token",
    scopes=["crm.objects.contacts.read", "crm.objects.contacts.write", "crm.schemas.contacts.read"],
    client_id_env="HUBSPOT_CLIENT_ID",
    client_secret_env="HUBSPOT_CLIENT_SECRET",
    redirect_uri_env="HUBSPOT_REDIRECT_URI",
    icon_emoji="HS",
    category="crm",
    description="Mirror your People directory with HubSpot contacts in both directions.",
    unlocks=[
        "People ↔ HubSpot contacts two-way sync",
        "Event attendance pushed as timeline events",
        "Property mapping (tags, company, role)",
    ],
    is_popular=True,
    auth_style="oauth2",
    docs_url="https://developers.hubspot.com/docs/api/overview",
    webhook_secret_env="HUBSPOT_WEBHOOK_SECRET",
)
register_provider(SPEC)


BASE = "https://api.hubapi.com"


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def upsert_contact(user_id: str, person) -> Optional[str]:
    tok = get_valid_access_token(user_id, SPEC.slug)
    if not tok or not person.email:
        return None
    body = {
        "properties": {
            "email": person.email,
            "firstname": (person.name or "").split(" ")[0],
            "lastname": " ".join((person.name or "").split(" ")[1:]),
            "company": person.company or "",
            "jobtitle": person.role or "",
            "phone": person.phone or "",
        }
    }
    try:
        r = requests.put(
            f"{BASE}/crm/v3/objects/contacts/{person.email}?idProperty=email",
            json=body, headers=_headers(tok), timeout=20,
        )
        if r.status_code == 404:
            r = requests.post(
                f"{BASE}/crm/v3/objects/contacts",
                json=body, headers=_headers(tok), timeout=20,
            )
        r.raise_for_status()
        return (r.json() or {}).get("id")
    except Exception as exc:
        logger.warning("HubSpot upsert_contact failed: %s", exc)
        return None


def list_contacts(user_id: str, limit: int = 100) -> list[dict]:
    tok = get_valid_access_token(user_id, SPEC.slug)
    if not tok:
        return []
    try:
        r = requests.get(
            f"{BASE}/crm/v3/objects/contacts?limit={limit}",
            headers=_headers(tok), timeout=20,
        )
        r.raise_for_status()
        return (r.json() or {}).get("results") or []
    except Exception as exc:
        logger.warning("HubSpot list_contacts failed: %s", exc)
        return []


_verify = verify_hmac_sha256(
    os.environ.get("HUBSPOT_WEBHOOK_SECRET", ""),
    header_name="X-HubSpot-Signature-v3",
)


def _handle(payload: dict) -> None:
    events = payload if isinstance(payload, list) else [payload]
    for e in events:
        logger.info("HubSpot webhook: %s", e.get("subscriptionType"))


register_webhook("hubspot", _verify, _handle)
