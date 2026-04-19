"""Discord — per-org bot plus slash commands for announcements and RSVPs.

Environment:
  DISCORD_CLIENT_ID=...
  DISCORD_CLIENT_SECRET=...
  DISCORD_REDIRECT_URI=...
  DISCORD_BOT_TOKEN=...           # bot-level token for channel posts
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
    slug="discord",
    display_name="Discord",
    authorize_url="https://discord.com/api/oauth2/authorize",
    token_url="https://discord.com/api/oauth2/token",
    scopes=["bot", "applications.commands", "identify", "guilds"],
    client_id_env="DISCORD_CLIENT_ID",
    client_secret_env="DISCORD_CLIENT_SECRET",
    redirect_uri_env="DISCORD_REDIRECT_URI",
    icon_emoji="Dc",
    category="messaging",
    description="Drop a SOMTool bot into your server for announcements and RSVPs.",
    unlocks=[
        "/rsvp slash command captures going/interested",
        "Event announcements posted to a channel of your choice",
        "Reminders DM'd to attendees 24h before start",
    ],
    is_popular=True,
    auth_style="oauth2",
    docs_url="https://discord.com/developers/docs/intro",
)
register_provider(SPEC)


def _bot_headers() -> Optional[dict]:
    tok = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not tok:
        return None
    return {"Authorization": f"Bot {tok}", "Content-Type": "application/json"}


def post_channel_message(channel_id: str, content: str) -> Optional[str]:
    h = _bot_headers()
    if not h or not channel_id:
        return None
    try:
        r = requests.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers=h,
            json={"content": content[:1900]},
            timeout=15,
        )
        r.raise_for_status()
        return (r.json() or {}).get("id")
    except Exception as exc:
        logger.warning("Discord post_channel_message failed: %s", exc)
        return None


def register_slash_commands(guild_id: str, application_id: str) -> bool:
    """Register the baseline SOMTool slash commands on a guild. Returns True on success."""
    h = _bot_headers()
    if not h or not guild_id or not application_id:
        return False
    commands = [
        {"name": "rsvp", "description": "RSVP to the current event",
         "options": [{"name": "status", "description": "going|interested|declined", "type": 3, "required": True}]},
        {"name": "events", "description": "Show upcoming SOMTool events"},
    ]
    try:
        ok = True
        for c in commands:
            r = requests.post(
                f"https://discord.com/api/v10/applications/{application_id}/guilds/{guild_id}/commands",
                headers=h,
                json=c,
                timeout=15,
            )
            ok = ok and r.status_code < 300
        return ok
    except Exception as exc:
        logger.warning("Discord register_slash_commands failed: %s", exc)
        return False
