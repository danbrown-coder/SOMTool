"""ClickUp — ProjectTracker adapter.

Environment:
  CLICKUP_API_TOKEN=...
  CLICKUP_LIST_ID=...
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
    slug="clickup",
    display_name="ClickUp",
    authorize_url="",
    token_url="",
    scopes=[],
    client_id_env="CLICKUP_API_TOKEN",
    client_secret_env="CLICKUP_API_TOKEN",
    redirect_uri_env="CLICKUP_API_TOKEN",
    icon_emoji="CU",
    category="ops",
    description="Auto-create event-prep tasks in ClickUp.",
    unlocks=[
        "Task list spawned per event",
        "Due dates relative to event date",
        "List selection per event type",
    ],
    auth_style="api_key",
    api_key_env="CLICKUP_API_TOKEN",
    docs_url="https://clickup.com/api",
)
register_provider(SPEC)


def create_task(name: str, description: str = "", due_ms: Optional[int] = None) -> Optional[str]:
    tok = os.environ.get("CLICKUP_API_TOKEN", "").strip()
    lid = os.environ.get("CLICKUP_LIST_ID", "").strip()
    if not (tok and lid):
        return None
    try:
        r = requests.post(
            f"https://api.clickup.com/api/v2/list/{lid}/task",
            headers={"Authorization": tok, "Content-Type": "application/json"},
            json={"name": name, "description": description, "due_date": due_ms},
            timeout=20,
        )
        r.raise_for_status()
        return (r.json() or {}).get("id")
    except Exception as exc:
        logger.warning("ClickUp create_task failed: %s", exc)
        return None
