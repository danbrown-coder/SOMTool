"""Canvas LMS — import course rosters into People, push event announcements
to a course feed.

Auth: Canvas is typically accessed via a long-lived **access token** minted by
the user from their Canvas profile page (`Account → Settings → New Access
Token`). That's an API-key style connection from SOMTool's perspective, so we
model it as a bot/api_key provider rather than a full 3-legged OAuth.

Environment:
  CANVAS_BASE_URL=https://callutheran.instructure.com
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

import requests

from integrations.oauth import ProviderSpec, decrypt
from integrations import register_provider, get_connection

logger = logging.getLogger(__name__)


SPEC = ProviderSpec(
    slug="canvas",
    display_name="Canvas LMS",
    authorize_url="",           # no OAuth — user pastes an access token
    token_url="",
    scopes=[],
    client_id_env="CANVAS_BASE_URL",      # reused as "presence" check
    client_secret_env="CANVAS_BASE_URL",
    redirect_uri_env="CANVAS_BASE_URL",
    icon_emoji="C",
    category="campus",
    description="Push event announcements to course feeds and import class rosters.",
    unlocks=[
        "Import a Canvas course roster straight into People",
        "Post event announcements to a course feed",
        "Auto-tag imported people by course + term",
    ],
    is_popular=True,
    auth_style="api_key",
    api_key_env="CANVAS_BASE_URL",  # presence indicates the provider is enabled
    docs_url="https://canvas.instructure.com/doc/api/",
)
register_provider(SPEC)


class CanvasClient:
    def __init__(self, base_url: str, access_token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {access_token}"

    @classmethod
    def for_user(cls, user_id: str) -> Optional["CanvasClient"]:
        import os
        base = os.environ.get("CANVAS_BASE_URL", "").strip()
        if not base:
            return None
        conn = get_connection(user_id, SPEC.slug)
        if conn is None or not conn.access_token_enc:
            return None
        try:
            token = decrypt(conn.access_token_enc)
        except Exception:
            return None
        return cls(base, token)

    def list_courses(self, enrollment_state: str = "active") -> list[dict]:
        try:
            r = self.session.get(
                f"{self.base_url}/api/v1/courses",
                params={"enrollment_state": enrollment_state, "per_page": 100},
                timeout=20,
            )
            r.raise_for_status()
            return r.json() or []
        except Exception as exc:
            logger.warning("Canvas list_courses failed: %s", exc)
            return []

    def list_enrollments(self, course_id: int, type_: str = "StudentEnrollment") -> list[dict]:
        out: list[dict] = []
        url: Optional[str] = f"{self.base_url}/api/v1/courses/{course_id}/users"
        params: dict = {"enrollment_type[]": type_, "per_page": 100, "include[]": "email"}
        try:
            while url:
                r = self.session.get(url, params=params, timeout=20)
                r.raise_for_status()
                out.extend(r.json() or [])
                # Pagination via Link header
                link = r.headers.get("Link", "")
                nxt = None
                for part in link.split(","):
                    if 'rel="next"' in part:
                        nxt = part.split(";")[0].strip(" <>")
                        break
                url = nxt
                params = {}
        except Exception as exc:
            logger.warning("Canvas list_enrollments failed: %s", exc)
        return out

    def post_announcement(self, course_id: int, title: str, message: str) -> Optional[dict]:
        try:
            r = self.session.post(
                f"{self.base_url}/api/v1/courses/{course_id}/discussion_topics",
                data={"title": title, "message": message, "is_announcement": True, "published": True},
                timeout=20,
            )
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            logger.warning("Canvas post_announcement failed: %s", exc)
            return None


def import_course_roster(user_id: str, course_id: int, tags: Iterable[str] = ()) -> int:
    """Import a Canvas course roster into the People directory; returns count added."""
    import people_manager as pm

    client = CanvasClient.for_user(user_id)
    if client is None:
        return 0
    added = 0
    for u in client.list_enrollments(course_id):
        email = u.get("login_id") or u.get("email") or ""
        name = u.get("name") or u.get("short_name") or email
        if not email or "@" not in email or pm.find_by_email(email):
            continue
        if pm.add_person(name=name, email=email, tags=list(tags), source=f"canvas:course_{course_id}"):
            added += 1
    return added
