"""Linear — shared ProjectTracker adapter member.

Environment:
  LINEAR_API_KEY=lin_api_...
  LINEAR_TEAM_ID=...
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
    slug="linear",
    display_name="Linear",
    authorize_url="",
    token_url="",
    scopes=[],
    client_id_env="LINEAR_API_KEY",
    client_secret_env="LINEAR_API_KEY",
    redirect_uri_env="LINEAR_API_KEY",
    icon_emoji="Ln",
    category="ops",
    description="Auto-create a Linear issue checklist when a SOMTool event is scheduled.",
    unlocks=[
        "Event-prep issues auto-seeded per event",
        "Issue-status back-sync to event progress bar",
        "Slash-style shortcut: turn any SOMTool task into a Linear issue",
    ],
    auth_style="api_key",
    api_key_env="LINEAR_API_KEY",
    docs_url="https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
    extra_env=["LINEAR_TEAM_ID"],
)
register_provider(SPEC)


def _headers() -> dict:
    tok = os.environ.get("LINEAR_API_KEY", "").strip()
    return {"Authorization": tok, "Content-Type": "application/json"} if tok else {}


def create_issue(title: str, description: str = "") -> Optional[str]:
    team = os.environ.get("LINEAR_TEAM_ID", "").strip()
    h = _headers()
    if not (team and h):
        return None
    q = (
        "mutation($teamId:String!,$title:String!,$desc:String){"
        "issueCreate(input:{teamId:$teamId,title:$title,description:$desc}){issue{id identifier}}}"
    )
    try:
        r = requests.post(
            "https://api.linear.app/graphql",
            headers=h,
            json={"query": q, "variables": {"teamId": team, "title": title, "desc": description}},
            timeout=20,
        )
        r.raise_for_status()
        return (((r.json() or {}).get("data") or {}).get("issueCreate") or {}).get("issue", {}).get("id")
    except Exception as exc:
        logger.warning("Linear create_issue failed: %s", exc)
        return None
