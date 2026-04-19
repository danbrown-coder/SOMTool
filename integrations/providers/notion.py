"""Notion — per-event run-of-show page, with SOMTool dashboard embedded.

Environment:
  NOTION_CLIENT_ID=...
  NOTION_CLIENT_SECRET=...
  NOTION_REDIRECT_URI=...
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from integrations.oauth import ProviderSpec, get_valid_access_token
from integrations import register_provider

logger = logging.getLogger(__name__)


SPEC = ProviderSpec(
    slug="notion",
    display_name="Notion",
    authorize_url="https://api.notion.com/v1/oauth/authorize",
    token_url="https://api.notion.com/v1/oauth/token",
    scopes=[],
    client_id_env="NOTION_CLIENT_ID",
    client_secret_env="NOTION_CLIENT_SECRET",
    redirect_uri_env="NOTION_REDIRECT_URI",
    extra_auth_params={"owner": "user"},
    icon_emoji="N",
    category="ops",
    description="Per-event run-of-show page; embed SOMTool dashboard inline.",
    unlocks=[
        "Auto-create a run-of-show Notion page per SOMTool event",
        "Embed the attendance dashboard via Notion embed block",
        "One-click 'open run-of-show' on the event detail page",
    ],
    is_popular=True,
    auth_style="oauth2",
    docs_url="https://developers.notion.com/",
)
register_provider(SPEC)


BASE = "https://api.notion.com/v1"


def _headers(tok: str) -> dict:
    return {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


def create_run_of_show(user_id: str, parent_page_id: str, event) -> Optional[str]:
    tok = get_valid_access_token(user_id, SPEC.slug)
    if not tok:
        return None
    try:
        r = requests.post(
            f"{BASE}/pages",
            headers=_headers(tok),
            json={
                "parent": {"page_id": parent_page_id},
                "properties": {
                    "title": {"title": [{"text": {"content": f"Run of show — {event.name}"}}]}
                },
                "children": [
                    {"object": "block", "type": "heading_2",
                     "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Agenda"}}]}},
                    {"object": "block", "type": "paragraph",
                     "paragraph": {"rich_text": [{"type": "text", "text": {"content": event.description or ""}}]}},
                ],
            },
            timeout=20,
        )
        r.raise_for_status()
        return (r.json() or {}).get("id")
    except Exception as exc:
        logger.warning("Notion create_run_of_show failed: %s", exc)
        return None
