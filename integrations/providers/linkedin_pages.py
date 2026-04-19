"""LinkedIn Pages — publish org-page updates (distinct from Sales Navigator).

Environment:
  LINKEDIN_PAGES_CLIENT_ID=...
  LINKEDIN_PAGES_CLIENT_SECRET=...
  LINKEDIN_PAGES_REDIRECT_URI=...
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from integrations.oauth import ProviderSpec, get_valid_access_token
from integrations import register_provider

logger = logging.getLogger(__name__)


SPEC = ProviderSpec(
    slug="linkedin_pages",
    display_name="LinkedIn Pages",
    authorize_url="https://www.linkedin.com/oauth/v2/authorization",
    token_url="https://www.linkedin.com/oauth/v2/accessToken",
    scopes=["w_organization_social", "r_organization_social", "rw_organization_admin"],
    client_id_env="LINKEDIN_PAGES_CLIENT_ID",
    client_secret_env="LINKEDIN_PAGES_CLIENT_SECRET",
    redirect_uri_env="LINKEDIN_PAGES_REDIRECT_URI",
    icon_emoji="Li",
    category="social",
    description="Post event announcements to your org's LinkedIn page.",
    unlocks=[
        "Publish text/article posts from the event dashboard",
        "Pull LinkedIn page engagement stats onto reports",
    ],
    auth_style="oauth2",
    docs_url="https://learn.microsoft.com/en-us/linkedin/marketing/",
)
register_provider(SPEC)


def publish_org_post(user_id: str, org_urn: str, text: str) -> Optional[str]:
    tok = get_valid_access_token(user_id, SPEC.slug)
    if not tok or not org_urn:
        return None
    try:
        r = requests.post(
            "https://api.linkedin.com/v2/ugcPosts",
            headers={
                "Authorization": f"Bearer {tok}",
                "X-Restli-Protocol-Version": "2.0.0",
                "Content-Type": "application/json",
            },
            json={
                "author": org_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": text},
                        "shareMediaCategory": "NONE",
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            },
            timeout=20,
        )
        r.raise_for_status()
        return (r.json() or {}).get("id")
    except Exception as exc:
        logger.warning("LinkedIn Pages publish_org_post failed: %s", exc)
        return None
