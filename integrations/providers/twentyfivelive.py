"""25Live / EMS — campus room booking autocomplete + availability overlay
inside the event form.

Auth: service-account / basic-auth against the institution's 25Live or EMS
deployment. We model it as an api_key-style provider where the credentials
live in env.

Environment:
  25LIVE_BASE_URL=https://25live.collegenet.com/your-school
  25LIVE_USERNAME=...
  25LIVE_PASSWORD=...
  25LIVE_API_TOKEN=...   # optional, if the institution uses bearer tokens

This adapter exposes two primary actions used by the event form:

  search_rooms(query)  -> list of {"id","name","capacity"}
  is_available(room_id, start_iso, end_iso) -> bool
  reserve(room_id, event_name, start_iso, end_iso, organizer_email) -> external_id | None
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
    slug="twentyfivelive",
    display_name="25Live / EMS",
    authorize_url="",
    token_url="",
    scopes=[],
    client_id_env="25LIVE_BASE_URL",
    client_secret_env="25LIVE_BASE_URL",
    redirect_uri_env="25LIVE_BASE_URL",
    icon_emoji="25",
    category="campus",
    description="Room autocomplete and bookings inside the SOMTool event form.",
    unlocks=[
        "Search rooms by capacity as you type",
        "Live availability overlay on the event form",
        "Auto-reserve the room at event creation",
    ],
    is_popular=True,
    auth_style="api_key",
    api_key_env="25LIVE_API_TOKEN",
    docs_url="https://knowledge25.collegenet.com/display/WSR25/",
)
register_provider(SPEC)


def _base() -> str:
    return (os.environ.get("25LIVE_BASE_URL") or "").rstrip("/")


def _auth() -> tuple[str, str] | None:
    user = os.environ.get("25LIVE_USERNAME", "")
    pw = os.environ.get("25LIVE_PASSWORD", "")
    return (user, pw) if user and pw else None


def _token_header() -> dict:
    tok = os.environ.get("25LIVE_API_TOKEN", "").strip()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def search_rooms(query: str, limit: int = 20) -> list[dict]:
    base = _base()
    if not base:
        return []
    try:
        r = requests.get(
            f"{base}/25live/data/spaces.json",
            params={"query": query, "count": limit},
            auth=_auth(),
            headers=_token_header(),
            timeout=15,
        )
        r.raise_for_status()
        data = r.json() or {}
        spaces = (data.get("spaces") or {}).get("space") or []
        return [
            {"id": s.get("space_id"), "name": s.get("formal_name") or s.get("space_name"),
             "capacity": int(s.get("max_capacity") or 0)}
            for s in spaces
        ]
    except Exception as exc:
        logger.warning("25Live search_rooms failed: %s", exc)
        return []


def is_available(room_id: int, start_iso: str, end_iso: str) -> bool:
    base = _base()
    if not base or not room_id:
        return False
    try:
        r = requests.get(
            f"{base}/25live/data/spaces/{room_id}/availability.json",
            params={"start_dt": start_iso, "end_dt": end_iso},
            auth=_auth(),
            headers=_token_header(),
            timeout=15,
        )
        r.raise_for_status()
        body = r.json() or {}
        # 25Live returns zero conflicting reservations when free.
        return (body.get("reservations") or {}).get("reservation") in (None, [])
    except Exception as exc:
        logger.warning("25Live availability failed: %s", exc)
        return False


def reserve(
    room_id: int, event_name: str, start_iso: str, end_iso: str, organizer_email: str
) -> Optional[str]:
    base = _base()
    if not base or not room_id:
        return None
    try:
        r = requests.post(
            f"{base}/25live/data/events.json",
            auth=_auth(),
            headers=_token_header(),
            json={
                "event_name": event_name,
                "space_id": room_id,
                "start_dt": start_iso,
                "end_dt": end_iso,
                "contact_email": organizer_email,
            },
            timeout=20,
        )
        r.raise_for_status()
        data = r.json() or {}
        return str(((data.get("event") or {}).get("event_id") or "") or None)
    except Exception as exc:
        logger.warning("25Live reserve failed: %s", exc)
        return None
