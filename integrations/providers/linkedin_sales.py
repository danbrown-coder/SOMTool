"""LinkedIn Sales Navigator — speaker/alum enrichment companion to Apollo.io.

Uses the LinkedIn marketing/sales OAuth. Requires a partner-approved app.

Environment:
  LINKEDIN_CLIENT_ID=...
  LINKEDIN_CLIENT_SECRET=...
  LINKEDIN_REDIRECT_URI=...
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from integrations.oauth import ProviderSpec, get_valid_access_token
from integrations import register_provider

logger = logging.getLogger(__name__)


SPEC = ProviderSpec(
    slug="linkedin_sales",
    display_name="LinkedIn Sales Navigator",
    authorize_url="https://www.linkedin.com/oauth/v2/authorization",
    token_url="https://www.linkedin.com/oauth/v2/accessToken",
    scopes=["r_liteprofile", "r_emailaddress", "r_basicprofile"],
    client_id_env="LINKEDIN_CLIENT_ID",
    client_secret_env="LINKEDIN_CLIENT_SECRET",
    redirect_uri_env="LINKEDIN_REDIRECT_URI",
    icon_emoji="Li",
    category="crm",
    description="Enrich speakers, alumni and attendees with LinkedIn data.",
    unlocks=[
        "Enrich People with LinkedIn profile/title/company",
        "Find warm paths to potential speakers from your network",
        "Recommended-people surface informed by shared connections",
    ],
    auth_style="oauth2",
    docs_url="https://learn.microsoft.com/en-us/linkedin/",
)
register_provider(SPEC)


def fetch_profile(user_id: str, urn: str) -> Optional[dict]:
    tok = get_valid_access_token(user_id, SPEC.slug)
    if not tok or not urn:
        return None
    try:
        r = requests.get(
            f"https://api.linkedin.com/v2/people/{urn}",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=20,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning("LinkedIn fetch_profile failed: %s", exc)
        return None
