"""Mailchimp / Constant Contact — mirror People as an audience; ingest
unsubscribes back into `people.opt_out`.

Mailchimp API keys embed the datacenter (e.g. `abc-us21`). We extract `us21`
from the key to build the API base URL.

Environment:
  MAILCHIMP_API_KEY=abc123abc-us21
  MAILCHIMP_AUDIENCE_ID=...
  MAILCHIMP_WEBHOOK_SECRET=...
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Optional

import requests

from integrations.oauth import ProviderSpec
from integrations import register_provider
from integrations.webhooks import register_webhook

logger = logging.getLogger(__name__)


SPEC = ProviderSpec(
    slug="mailchimp",
    display_name="Mailchimp / Constant Contact",
    authorize_url="",
    token_url="",
    scopes=[],
    client_id_env="MAILCHIMP_API_KEY",
    client_secret_env="MAILCHIMP_API_KEY",
    redirect_uri_env="MAILCHIMP_API_KEY",
    icon_emoji="MC",
    category="crm",
    description="People list mirrored as a Mailchimp audience; unsubs flow back.",
    unlocks=[
        "One-way and two-way audience sync",
        "Unsubscribe events flip `people.opt_out` to true",
        "Per-event merge fields land in campaigns",
    ],
    is_popular=True,
    auth_style="api_key",
    api_key_env="MAILCHIMP_API_KEY",
    docs_url="https://mailchimp.com/developer/marketing/api/",
    webhook_secret_env="MAILCHIMP_WEBHOOK_SECRET",
    extra_env=["MAILCHIMP_AUDIENCE_ID"],
)
register_provider(SPEC)


def _base() -> str:
    key = os.environ.get("MAILCHIMP_API_KEY", "").strip()
    if not key or "-" not in key:
        return ""
    dc = key.split("-")[-1]
    return f"https://{dc}.api.mailchimp.com/3.0"


def _auth() -> Optional[tuple[str, str]]:
    key = os.environ.get("MAILCHIMP_API_KEY", "").strip()
    return ("anystring", key) if key else None


def _subscriber_hash(email: str) -> str:
    return hashlib.md5(email.strip().lower().encode()).hexdigest()


def upsert_member(email: str, first: str = "", last: str = "", tags: list[str] | None = None) -> Optional[str]:
    base = _base()
    aud = os.environ.get("MAILCHIMP_AUDIENCE_ID", "").strip()
    if not base or not aud or not email:
        return None
    try:
        r = requests.put(
            f"{base}/lists/{aud}/members/{_subscriber_hash(email)}",
            auth=_auth(),
            json={
                "email_address": email,
                "status_if_new": "subscribed",
                "merge_fields": {"FNAME": first, "LNAME": last},
                "tags": tags or [],
            },
            timeout=20,
        )
        r.raise_for_status()
        return (r.json() or {}).get("id")
    except Exception as exc:
        logger.warning("Mailchimp upsert_member failed: %s", exc)
        return None


def _handle(payload: dict) -> None:
    """Mailchimp posts form-encoded webhooks; their shape has
    type=unsubscribe|subscribe|upemail|profile|cleaned.
    """
    import people_manager as pm
    etype = payload.get("type", "")
    data = payload.get("data", {}) or {}
    email = data.get("email") or ""
    if etype == "unsubscribe" and email:
        person = pm.find_by_email(email)
        if person:
            try:
                pm.update_person(person.id, notes=(person.notes or "") + "\n[opted out via Mailchimp]")
            except Exception:
                pass


register_webhook("mailchimp", lambda h, p, r: True, _handle)
