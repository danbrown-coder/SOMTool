"""Asana — ProjectTracker adapter.

Environment:
  ASANA_PAT=...
  ASANA_WORKSPACE_GID=...
  ASANA_PROJECT_GID=...   # optional default project for event tasks
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
    slug="asana",
    display_name="Asana",
    authorize_url="",
    token_url="",
    scopes=[],
    client_id_env="ASANA_PAT",
    client_secret_env="ASANA_PAT",
    redirect_uri_env="ASANA_PAT",
    icon_emoji="As",
    category="ops",
    description="Auto-create event-prep tasks in Asana.",
    unlocks=[
        "Template task list spawned per event",
        "Due dates anchored to event date",
        "Section/project routing by event type",
    ],
    auth_style="api_key",
    api_key_env="ASANA_PAT",
    docs_url="https://developers.asana.com/docs",
    extra_env=["ASANA_WORKSPACE_GID", "ASANA_PROJECT_GID"],
)
register_provider(SPEC)


def _headers() -> dict:
    tok = os.environ.get("ASANA_PAT", "").strip()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def create_task(name: str, notes: str = "", due_on: str = "") -> Optional[str]:
    h = _headers()
    project = os.environ.get("ASANA_PROJECT_GID", "").strip()
    workspace = os.environ.get("ASANA_WORKSPACE_GID", "").strip()
    if not h or not (project or workspace):
        return None
    body = {"data": {"name": name, "notes": notes, "due_on": due_on or None}}
    if project:
        body["data"]["projects"] = [project]
    elif workspace:
        body["data"]["workspace"] = workspace
    try:
        r = requests.post("https://app.asana.com/api/1.0/tasks", headers=h, json=body, timeout=20)
        r.raise_for_status()
        return ((r.json() or {}).get("data") or {}).get("gid")
    except Exception as exc:
        logger.warning("Asana create_task failed: %s", exc)
        return None
