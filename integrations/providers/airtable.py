"""Airtable — mirror `events` and `people` as linked tables (two-way).

Airtable uses a Personal Access Token from the user's account — api_key style.

Environment:
  AIRTABLE_PAT=...
  AIRTABLE_BASE_ID=app...
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
    slug="airtable",
    display_name="Airtable",
    authorize_url="",
    token_url="",
    scopes=[],
    client_id_env="AIRTABLE_PAT",
    client_secret_env="AIRTABLE_PAT",
    redirect_uri_env="AIRTABLE_PAT",
    icon_emoji="At",
    category="ops",
    description="Mirror events + people in an Airtable base for power users.",
    unlocks=[
        "People + events two-way mirror in your Airtable base",
        "Airtable views (kanban, gallery, timeline) for free",
        "Custom fields flow through as Airtable columns",
    ],
    is_popular=True,
    auth_style="api_key",
    api_key_env="AIRTABLE_PAT",
    docs_url="https://airtable.com/developers/web/api/introduction",
    extra_env=["AIRTABLE_BASE_ID"],
)
register_provider(SPEC)


def _headers() -> dict:
    tok = os.environ.get("AIRTABLE_PAT", "").strip()
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"} if tok else {}


def _base() -> str:
    return os.environ.get("AIRTABLE_BASE_ID", "").strip()


def upsert_row(table: str, fields: dict, merge_field: str = "Email") -> Optional[str]:
    base, h = _base(), _headers()
    if not (base and h and table):
        return None
    try:
        r = requests.patch(
            f"https://api.airtable.com/v0/{base}/{table}",
            json={"performUpsert": {"fieldsToMergeOn": [merge_field]}, "records": [{"fields": fields}]},
            headers=h,
            timeout=20,
        )
        r.raise_for_status()
        records = (r.json() or {}).get("records") or []
        return records[0].get("id") if records else None
    except Exception as exc:
        logger.warning("Airtable upsert_row failed: %s", exc)
        return None
