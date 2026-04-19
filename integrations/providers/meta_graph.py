"""Meta Graph — publish to Facebook Pages and Instagram Business profiles.

Environment:
  META_APP_ID=...
  META_APP_SECRET=...
  META_REDIRECT_URI=...
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from integrations.oauth import ProviderSpec, get_valid_access_token
from integrations import register_provider

logger = logging.getLogger(__name__)


SPEC = ProviderSpec(
    slug="meta_graph",
    display_name="Instagram + Facebook Pages",
    authorize_url="https://www.facebook.com/v20.0/dialog/oauth",
    token_url="https://graph.facebook.com/v20.0/oauth/access_token",
    scopes=[
        "pages_manage_posts",
        "pages_read_engagement",
        "pages_show_list",
        "instagram_basic",
        "instagram_content_publish",
    ],
    client_id_env="META_APP_ID",
    client_secret_env="META_APP_SECRET",
    redirect_uri_env="META_REDIRECT_URI",
    icon_emoji="Me",
    category="social",
    description="Post event promos to Facebook Pages and Instagram Business accounts.",
    unlocks=[
        "Publish to FB Page + IG Business feed from SOMTool",
        "Pull page/IG insights onto the event dashboard",
    ],
    is_popular=True,
    auth_style="oauth2",
    docs_url="https://developers.facebook.com/docs/graph-api/",
    webhook_secret_env="META_WEBHOOK_SECRET",
)
register_provider(SPEC)


def publish_page_post(user_id: str, page_id: str, page_access_token: str, message: str, link: Optional[str] = None) -> Optional[str]:
    if not page_access_token or not page_id:
        return None
    try:
        params = {"message": message, "access_token": page_access_token}
        if link:
            params["link"] = link
        r = requests.post(f"https://graph.facebook.com/v20.0/{page_id}/feed", data=params, timeout=20)
        r.raise_for_status()
        return (r.json() or {}).get("id")
    except Exception as exc:
        logger.warning("Meta publish_page_post failed: %s", exc)
        return None


def publish_ig_post(user_id: str, ig_user_id: str, page_access_token: str, image_url: str, caption: str) -> Optional[str]:
    if not page_access_token or not ig_user_id or not image_url:
        return None
    try:
        c = requests.post(
            f"https://graph.facebook.com/v20.0/{ig_user_id}/media",
            data={"image_url": image_url, "caption": caption, "access_token": page_access_token},
            timeout=20,
        )
        c.raise_for_status()
        container_id = (c.json() or {}).get("id")
        if not container_id:
            return None
        p = requests.post(
            f"https://graph.facebook.com/v20.0/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": page_access_token},
            timeout=20,
        )
        p.raise_for_status()
        return (p.json() or {}).get("id")
    except Exception as exc:
        logger.warning("Meta publish_ig_post failed: %s", exc)
        return None
