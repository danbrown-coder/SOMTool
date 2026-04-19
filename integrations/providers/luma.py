"""Luma (lu.ma) — a second ticketing/event backend with the same SOMTool
shape as Eventbrite.

Environment:
  LUMA_API_KEY=...
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from integrations.oauth import ProviderSpec
from integrations import register_provider

logger = logging.getLogger(__name__)


SPEC = ProviderSpec(
    slug="luma",
    display_name="Luma",
    authorize_url="",
    token_url="",
    scopes=[],
    client_id_env="LUMA_API_KEY",
    client_secret_env="LUMA_API_KEY",
    redirect_uri_env="LUMA_API_KEY",
    icon_emoji="L",
    category="crm",
    description="Create + sync Luma events and pull attendees.",
    unlocks=[
        "Publish a Luma event from SOMTool in one click",
        "Pull guest list + RSVP status into `contacts`",
        "Luma check-in events flip `contact.status` to attended",
    ],
    auth_style="api_key",
    api_key_env="LUMA_API_KEY",
    docs_url="https://docs.lu.ma/reference/getting-started-with-your-api",
)
register_provider(SPEC)


BASE = "https://api.lu.ma/public/v1"


def _headers() -> dict:
    k = os.environ.get("LUMA_API_KEY", "").strip()
    return {"x-luma-api-key": k, "Content-Type": "application/json"} if k else {}


def create_event(name: str, start_iso: str, end_iso: str, description: str = "") -> Optional[str]:
    if not _headers():
        return None
    try:
        r = requests.post(
            f"{BASE}/event/create",
            json={"name": name, "start_at": start_iso, "end_at": end_iso, "description_md": description},
            headers=_headers(),
            timeout=20,
        )
        r.raise_for_status()
        return (r.json() or {}).get("event", {}).get("api_id")
    except Exception as exc:
        logger.warning("Luma create_event failed: %s", exc)
        return None


def list_guests(luma_event_id: str) -> list[dict]:
    if not _headers() or not luma_event_id:
        return []
    try:
        r = requests.get(
            f"{BASE}/event/get-guests",
            params={"event_api_id": luma_event_id, "pagination_limit": 100},
            headers=_headers(),
            timeout=20,
        )
        r.raise_for_status()
        entries = (r.json() or {}).get("entries") or []
        return [
            {
                "name": (e.get("guest") or {}).get("name", ""),
                "email": (e.get("guest") or {}).get("email", ""),
                "status": (e.get("guest") or {}).get("approval_status", ""),
                "checked_in": bool((e.get("guest") or {}).get("checked_in_at")),
            }
            for e in entries
        ]
    except Exception as exc:
        logger.warning("Luma list_guests failed: %s", exc)
        return []
