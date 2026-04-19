"""Student-org platform adapter (Engage / Presence / CampusGroups).

One provider, three backends behind a single `CAMPUS_ORG_PLATFORM` env var.
The choice depends on what each school runs:

  CAMPUS_ORG_PLATFORM=engage|presence|campusgroups
  CAMPUS_ORG_BASE_URL=...
  CAMPUS_ORG_API_KEY=...

Common surface: list a school's student-org events and mirror them into SOMTool.
"""
from __future__ import annotations

import logging
import os

import requests

from integrations.oauth import ProviderSpec
from integrations import register_provider

logger = logging.getLogger(__name__)


SPEC = ProviderSpec(
    slug="engage",
    display_name="Engage / Presence / CampusGroups",
    authorize_url="",
    token_url="",
    scopes=[],
    client_id_env="CAMPUS_ORG_PLATFORM",
    client_secret_env="CAMPUS_ORG_PLATFORM",
    redirect_uri_env="CAMPUS_ORG_PLATFORM",
    icon_emoji="E",
    category="campus",
    description="Pull student-org events from your campus org platform.",
    unlocks=[
        "Mirror student-org events into the Outreach Calendar",
        "Auto-suggest SOM events when org calendars clash",
        "Unified attendance view across orgs",
    ],
    auth_style="api_key",
    api_key_env="CAMPUS_ORG_API_KEY",
    docs_url="",
)
register_provider(SPEC)


def _base() -> str:
    return (os.environ.get("CAMPUS_ORG_BASE_URL") or "").rstrip("/")


def _headers() -> dict:
    tok = os.environ.get("CAMPUS_ORG_API_KEY", "").strip()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def list_events() -> list[dict]:
    """Normalized list of {title, starts_at, ends_at, location, url}."""
    platform = (os.environ.get("CAMPUS_ORG_PLATFORM") or "").strip().lower()
    base = _base()
    if not (platform and base):
        return []
    try:
        if platform == "engage":
            r = requests.get(f"{base}/engage/api/events", headers=_headers(), timeout=20)
        elif platform == "presence":
            r = requests.get(f"{base}/api/v2/events", headers=_headers(), timeout=20)
        else:  # campusgroups
            r = requests.get(f"{base}/api/events", headers=_headers(), timeout=20)
        r.raise_for_status()
        raw = r.json() or {}
        items = raw if isinstance(raw, list) else (raw.get("items") or raw.get("events") or [])
        out: list[dict] = []
        for e in items:
            out.append({
                "title": e.get("name") or e.get("title") or "",
                "starts_at": e.get("startsOn") or e.get("start_date") or e.get("startDateTime") or "",
                "ends_at": e.get("endsOn") or e.get("end_date") or e.get("endDateTime") or "",
                "location": e.get("location") or "",
                "url": e.get("url") or e.get("permalink") or "",
            })
        return out
    except Exception as exc:
        logger.warning("Engage list_events failed: %s", exc)
        return []
