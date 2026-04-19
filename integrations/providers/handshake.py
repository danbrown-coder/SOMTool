"""Handshake — career-event two-way sync.

Handshake's public API is partner-gated; the adapter provides a thin wrapper
around their events + employer endpoints. Auth is OAuth2 client-credentials.

Environment:
  HANDSHAKE_CLIENT_ID=...
  HANDSHAKE_CLIENT_SECRET=...
  HANDSHAKE_INSTITUTION_ID=...
  HANDSHAKE_BASE_URL=https://app.joinhandshake.com
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
    slug="handshake",
    display_name="Handshake",
    authorize_url="https://app.joinhandshake.com/oauth/authorize",
    token_url="https://app.joinhandshake.com/oauth/token",
    scopes=["events.read", "events.write"],
    client_id_env="HANDSHAKE_CLIENT_ID",
    client_secret_env="HANDSHAKE_CLIENT_SECRET",
    redirect_uri_env="HANDSHAKE_REDIRECT_URI",
    icon_emoji="H",
    category="campus",
    description="Career-event two-way sync with Handshake.",
    unlocks=[
        "Mirror Handshake career events into SOMTool",
        "Push SOMTool-created career events to Handshake",
        "Pull RSVP + check-in counts back for post-event analytics",
    ],
    auth_style="oauth2",
    docs_url="https://joinhandshake-support.com/hc/en-us/articles/218693318-Handshake-API-Documentation",
)
register_provider(SPEC)


def _base() -> str:
    return (os.environ.get("HANDSHAKE_BASE_URL") or "https://app.joinhandshake.com").rstrip("/")


class HandshakeClient:
    def __init__(self, access_token: str):
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {access_token}"

    @classmethod
    def for_user(cls, user_id: str) -> Optional["HandshakeClient"]:
        from integrations.oauth import get_valid_access_token
        tok = get_valid_access_token(user_id, SPEC.slug)
        return cls(tok) if tok else None

    def list_events(self) -> list[dict]:
        inst = os.environ.get("HANDSHAKE_INSTITUTION_ID", "")
        try:
            r = self.s.get(
                f"{_base()}/api/v1/institutions/{inst}/career_events",
                timeout=20,
            )
            r.raise_for_status()
            return (r.json() or {}).get("events", [])
        except Exception as exc:
            logger.warning("Handshake list_events failed: %s", exc)
            return []

    def create_event(self, *, name: str, start_iso: str, end_iso: str, description: str = "") -> Optional[str]:
        inst = os.environ.get("HANDSHAKE_INSTITUTION_ID", "")
        try:
            r = self.s.post(
                f"{_base()}/api/v1/institutions/{inst}/career_events",
                json={
                    "name": name, "start_time": start_iso, "end_time": end_iso,
                    "description": description,
                },
                timeout=20,
            )
            r.raise_for_status()
            return str(((r.json() or {}).get("event") or {}).get("id") or "") or None
        except Exception as exc:
            logger.warning("Handshake create_event failed: %s", exc)
            return None
