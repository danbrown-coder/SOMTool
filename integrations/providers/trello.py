"""Trello — ProjectTracker adapter.

Environment:
  TRELLO_API_KEY=...
  TRELLO_TOKEN=...
  TRELLO_LIST_ID=...
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
    slug="trello",
    display_name="Trello",
    authorize_url="",
    token_url="",
    scopes=[],
    client_id_env="TRELLO_API_KEY",
    client_secret_env="TRELLO_API_KEY",
    redirect_uri_env="TRELLO_API_KEY",
    icon_emoji="Tr",
    category="ops",
    description="Auto-create Trello cards for event prep.",
    unlocks=[
        "Event-prep cards spawned in your board of choice",
        "Due dates anchored to the event date",
        "Card ↔ SOMTool task sync",
    ],
    auth_style="api_key",
    api_key_env="TRELLO_API_KEY",
    docs_url="https://developer.atlassian.com/cloud/trello/rest/",
)
register_provider(SPEC)


def create_card(name: str, desc: str = "", due: str = "") -> Optional[str]:
    key = os.environ.get("TRELLO_API_KEY", "").strip()
    tok = os.environ.get("TRELLO_TOKEN", "").strip()
    lid = os.environ.get("TRELLO_LIST_ID", "").strip()
    if not (key and tok and lid):
        return None
    try:
        r = requests.post(
            "https://api.trello.com/1/cards",
            params={"key": key, "token": tok, "idList": lid, "name": name, "desc": desc, "due": due or None},
            timeout=20,
        )
        r.raise_for_status()
        return (r.json() or {}).get("id")
    except Exception as exc:
        logger.warning("Trello create_card failed: %s", exc)
        return None
