"""Eventbrite — two-way event + attendee sync.

Eventbrite uses a personal OAuth token. Users paste theirs at connect time
(we model it as api_key) or run through OAuth2.

Environment:
  EVENTBRITE_CLIENT_ID=...
  EVENTBRITE_CLIENT_SECRET=...
  EVENTBRITE_REDIRECT_URI=...
  EVENTBRITE_WEBHOOK_TOKEN=...   # shared secret for /webhooks/eventbrite
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from integrations.oauth import ProviderSpec, get_valid_access_token
from integrations import register_provider
from integrations.webhooks import register_webhook

logger = logging.getLogger(__name__)


SPEC = ProviderSpec(
    slug="eventbrite",
    display_name="Eventbrite",
    authorize_url="https://www.eventbrite.com/oauth/authorize",
    token_url="https://www.eventbrite.com/oauth/token",
    scopes=[],
    client_id_env="EVENTBRITE_CLIENT_ID",
    client_secret_env="EVENTBRITE_CLIENT_SECRET",
    redirect_uri_env="EVENTBRITE_REDIRECT_URI",
    icon_emoji="EB",
    category="crm",
    description="Two-way event & attendee sync with Eventbrite.",
    unlocks=[
        "Mirror a SOMTool event to Eventbrite with a single click",
        "Pull attendee list back into People + Contacts",
        "Live order-created webhooks auto-register paid attendees",
    ],
    is_popular=True,
    auth_style="oauth2",
    docs_url="https://www.eventbrite.com/platform/api",
    webhook_secret_env="EVENTBRITE_WEBHOOK_TOKEN",
)
register_provider(SPEC)


BASE = "https://www.eventbriteapi.com/v3"


def _headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}


def create_event(user_id: str, event) -> Optional[str]:
    token = get_valid_access_token(user_id, SPEC.slug)
    if not token:
        return None
    try:
        r = requests.get(f"{BASE}/users/me/organizations/", headers=_headers(token), timeout=20)
        r.raise_for_status()
        org_id = (r.json().get("organizations") or [{}])[0].get("id")
        if not org_id:
            return None
        payload = {
            "event": {
                "name": {"html": event.name or "Event"},
                "description": {"html": event.description or ""},
                "start": {"timezone": "America/Los_Angeles", "utc": (event.date or "")[:19]},
                "end":   {"timezone": "America/Los_Angeles", "utc": (event.date or "")[:19]},
                "currency": "USD",
            }
        }
        r = requests.post(
            f"{BASE}/organizations/{org_id}/events/", headers=_headers(token), json=payload, timeout=20
        )
        r.raise_for_status()
        return r.json().get("id")
    except Exception as exc:
        logger.warning("Eventbrite create_event failed: %s", exc)
        return None


def list_attendees(user_id: str, eventbrite_event_id: str) -> list[dict]:
    token = get_valid_access_token(user_id, SPEC.slug)
    if not token:
        return []
    try:
        r = requests.get(
            f"{BASE}/events/{eventbrite_event_id}/attendees/",
            headers=_headers(token),
            timeout=20,
        )
        r.raise_for_status()
        out = []
        for a in (r.json() or {}).get("attendees") or []:
            profile = a.get("profile") or {}
            out.append({
                "name": profile.get("name") or "",
                "email": profile.get("email") or "",
                "ticket": (a.get("ticket_class_name") or ""),
                "order_id": a.get("order_id"),
            })
        return out
    except Exception as exc:
        logger.warning("Eventbrite list_attendees failed: %s", exc)
        return []


# ── Webhook ──


def _verify(headers: dict, _parsed: dict, _raw: bytes) -> bool:
    secret = os.environ.get("EVENTBRITE_WEBHOOK_TOKEN", "").strip()
    got = headers.get("X-Eventbrite-Signature") or headers.get("x-eventbrite-signature") or ""
    return bool(secret) and got == secret


def _handle(payload: dict) -> None:
    api_url = payload.get("api_url") or ""
    action = payload.get("config", {}).get("action", "")
    logger.info("Eventbrite webhook %s %s", action, api_url)
    # Downstream: parse order.placed / attendee.updated -> register into a local event.


register_webhook("eventbrite", _verify, _handle)
