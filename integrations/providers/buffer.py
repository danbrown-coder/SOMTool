"""Buffer — multi-network post scheduling.

Environment:
  BUFFER_CLIENT_ID=...
  BUFFER_CLIENT_SECRET=...
  BUFFER_REDIRECT_URI=...
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from integrations.oauth import ProviderSpec, get_valid_access_token
from integrations import register_provider

logger = logging.getLogger(__name__)


SPEC = ProviderSpec(
    slug="buffer",
    display_name="Buffer",
    authorize_url="https://bufferapp.com/oauth2/authorize",
    token_url="https://api.bufferapp.com/1/oauth2/token.json",
    scopes=[],
    client_id_env="BUFFER_CLIENT_ID",
    client_secret_env="BUFFER_CLIENT_SECRET",
    redirect_uri_env="BUFFER_REDIRECT_URI",
    icon_emoji="Bf",
    category="social",
    description="Schedule event-promo posts across IG, LinkedIn, X from one dialog.",
    unlocks=[
        "Schedule a multi-network promo cadence per event",
        "Auto-swap event images from the Drive Picker",
        "Engagement stats surface on the event dashboard",
    ],
    is_popular=True,
    auth_style="oauth2",
    docs_url="https://buffer.com/developers/api",
)
register_provider(SPEC)


def create_update(user_id: str, profile_ids: list[str], text: str, scheduled_at: Optional[int] = None) -> Optional[str]:
    tok = get_valid_access_token(user_id, SPEC.slug)
    if not tok or not profile_ids:
        return None
    try:
        r = requests.post(
            "https://api.bufferapp.com/1/updates/create.json",
            data={
                "access_token": tok,
                "profile_ids[]": profile_ids,
                "text": text,
                "scheduled_at": scheduled_at,
            },
            timeout=20,
        )
        r.raise_for_status()
        ids = [u.get("id") for u in (r.json() or {}).get("updates", [])]
        return ids[0] if ids else None
    except Exception as exc:
        logger.warning("Buffer create_update failed: %s", exc)
        return None
