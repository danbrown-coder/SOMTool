"""WhatsApp Business via Twilio — templated event reminders and RSVP replies.

Environment:
  TWILIO_ACCOUNT_SID=...
  TWILIO_AUTH_TOKEN=...
  TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
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
    slug="whatsapp",
    display_name="WhatsApp Business",
    authorize_url="",
    token_url="",
    scopes=[],
    client_id_env="TWILIO_ACCOUNT_SID",
    client_secret_env="TWILIO_AUTH_TOKEN",
    redirect_uri_env="",
    icon_emoji="Wa",
    category="messaging",
    description="Send event reminders and capture RSVPs over WhatsApp (via Twilio).",
    unlocks=[
        "24h and 1h reminders to opted-in guests",
        "Reply YES/NO → RSVP updated automatically",
        "Delivery + read receipts appear on the event dashboard",
    ],
    auth_style="api_key",
    api_key_env="TWILIO_AUTH_TOKEN",
    docs_url="https://www.twilio.com/docs/whatsapp",
    webhook_secret_env="TWILIO_AUTH_TOKEN",
    extra_env=["TWILIO_ACCOUNT_SID", "TWILIO_WHATSAPP_FROM"],
)
register_provider(SPEC)


def send_template(to_phone_e164: str, body: str) -> Optional[str]:
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    tok = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    wfrom = os.environ.get("TWILIO_WHATSAPP_FROM", "").strip()
    if not (sid and tok and wfrom and to_phone_e164):
        return None
    try:
        r = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            auth=(sid, tok),
            data={
                "From": wfrom,
                "To": f"whatsapp:{to_phone_e164}" if not to_phone_e164.startswith("whatsapp:") else to_phone_e164,
                "Body": body[:1000],
            },
            timeout=20,
        )
        r.raise_for_status()
        return (r.json() or {}).get("sid")
    except Exception as exc:
        logger.warning("WhatsApp send_template failed: %s", exc)
        return None
