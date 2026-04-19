"""Hootsuite — alternative to Buffer for post scheduling.

Environment:
  HOOTSUITE_CLIENT_ID=...
  HOOTSUITE_CLIENT_SECRET=...
  HOOTSUITE_REDIRECT_URI=...
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from integrations.oauth import ProviderSpec, get_valid_access_token
from integrations import register_provider

logger = logging.getLogger(__name__)


SPEC = ProviderSpec(
    slug="hootsuite",
    display_name="Hootsuite",
    authorize_url="https://platform.hootsuite.com/oauth2/auth",
    token_url="https://platform.hootsuite.com/oauth2/token",
    scopes=["offline"],
    client_id_env="HOOTSUITE_CLIENT_ID",
    client_secret_env="HOOTSUITE_CLIENT_SECRET",
    redirect_uri_env="HOOTSUITE_REDIRECT_URI",
    icon_emoji="Hs",
    category="social",
    description="Enterprise social scheduler — pick either Hootsuite or Buffer per org.",
    unlocks=[
        "Schedule multi-network promo cadences per event",
        "Mirror SOMTool events as Hootsuite campaigns",
    ],
    auth_style="oauth2",
    docs_url="https://developer.hootsuite.com/docs",
)
register_provider(SPEC)


def schedule_message(user_id: str, social_profile_ids: list[str], text: str, send_time_iso: str) -> Optional[str]:
    tok = get_valid_access_token(user_id, SPEC.slug)
    if not tok or not social_profile_ids:
        return None
    try:
        r = requests.post(
            "https://platform.hootsuite.com/v1/messages",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            json={
                "text": text,
                "scheduledSendTime": send_time_iso,
                "socialProfileIds": social_profile_ids,
            },
            timeout=20,
        )
        r.raise_for_status()
        data = (r.json() or {}).get("data") or []
        return data[0].get("id") if data else None
    except Exception as exc:
        logger.warning("Hootsuite schedule_message failed: %s", exc)
        return None
