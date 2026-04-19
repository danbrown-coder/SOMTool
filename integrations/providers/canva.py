"""Canva — generate event-branded flyers from templates via Connect API.

Environment:
  CANVA_CLIENT_ID=...
  CANVA_CLIENT_SECRET=...
  CANVA_REDIRECT_URI=...
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from integrations.oauth import ProviderSpec, get_valid_access_token
from integrations import register_provider

logger = logging.getLogger(__name__)


SPEC = ProviderSpec(
    slug="canva",
    display_name="Canva",
    authorize_url="https://www.canva.com/api/oauth/authorize",
    token_url="https://api.canva.com/rest/v1/oauth/token",
    scopes=["design:content:read", "design:meta:read", "asset:read", "asset:write"],
    client_id_env="CANVA_CLIENT_ID",
    client_secret_env="CANVA_CLIENT_SECRET",
    redirect_uri_env="CANVA_REDIRECT_URI",
    icon_emoji="Cv",
    category="social",
    description="Spin up event-branded flyers from Canva templates in one click.",
    unlocks=[
        "Generate event flyers from org templates",
        "Export PDF/PNG straight into Drive + Buffer",
    ],
    is_popular=True,
    auth_style="oauth2",
    docs_url="https://www.canva.dev/docs/connect/",
)
register_provider(SPEC)


def list_user_designs(user_id: str) -> list[dict]:
    tok = get_valid_access_token(user_id, SPEC.slug)
    if not tok:
        return []
    try:
        r = requests.get(
            "https://api.canva.com/rest/v1/designs",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=20,
        )
        r.raise_for_status()
        return (r.json() or {}).get("items", [])
    except Exception as exc:
        logger.warning("Canva list_user_designs failed: %s", exc)
        return []


def export_design(user_id: str, design_id: str, fmt: str = "png") -> Optional[str]:
    tok = get_valid_access_token(user_id, SPEC.slug)
    if not tok or not design_id:
        return None
    try:
        r = requests.post(
            f"https://api.canva.com/rest/v1/exports",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            json={"design_id": design_id, "format": {"type": fmt}},
            timeout=30,
        )
        r.raise_for_status()
        return ((r.json() or {}).get("job") or {}).get("id")
    except Exception as exc:
        logger.warning("Canva export_design failed: %s", exc)
        return None
