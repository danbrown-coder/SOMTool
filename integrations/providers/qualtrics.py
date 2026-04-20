"""Qualtrics — replace the built-in feedback form with a campus-standard
survey when connected. Responses flow back into `feedback_entries`.

Auth: API token (from the user's Qualtrics account). Data-center subdomain
is per-brand (e.g. `yul1.qualtrics.com`).

Environment:
  QUALTRICS_API_TOKEN=...
  QUALTRICS_DATA_CENTER=yul1   # e.g. "fra1", "syd1"
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
    slug="qualtrics",
    display_name="Qualtrics",
    authorize_url="",
    token_url="",
    scopes=[],
    client_id_env="QUALTRICS_API_TOKEN",
    client_secret_env="QUALTRICS_API_TOKEN",
    redirect_uri_env="QUALTRICS_API_TOKEN",
    icon_emoji="Q",
    category="campus",
    description="Replace the built-in feedback form with your campus Qualtrics survey.",
    unlocks=[
        "Link any Qualtrics survey to a SOMTool event",
        "Pull responses into `feedback_entries` automatically",
        "Use Qualtrics branching & logic without leaving SOMTool",
    ],
    auth_style="api_key",
    api_key_env="QUALTRICS_API_TOKEN",
    docs_url="https://api.qualtrics.com/",
    extra_env=["QUALTRICS_DATA_CENTER"],
)
register_provider(SPEC)


def _base() -> str:
    dc = os.environ.get("QUALTRICS_DATA_CENTER", "").strip()
    return f"https://{dc}.qualtrics.com/API/v3" if dc else ""


def _headers() -> dict:
    tok = os.environ.get("QUALTRICS_API_TOKEN", "").strip()
    return {"X-API-TOKEN": tok} if tok else {}


def list_surveys() -> list[dict]:
    base = _base()
    if not base or not _headers():
        return []
    try:
        r = requests.get(f"{base}/surveys", headers=_headers(), timeout=20)
        r.raise_for_status()
        return ((r.json() or {}).get("result") or {}).get("elements") or []
    except Exception as exc:
        logger.warning("Qualtrics list_surveys failed: %s", exc)
        return []


def start_response_export(survey_id: str) -> Optional[str]:
    base = _base()
    try:
        r = requests.post(
            f"{base}/surveys/{survey_id}/export-responses",
            json={"format": "json"},
            headers=_headers(),
            timeout=20,
        )
        r.raise_for_status()
        return ((r.json() or {}).get("result") or {}).get("progressId")
    except Exception as exc:
        logger.warning("Qualtrics start_export failed: %s", exc)
        return None


def public_survey_url(survey_id: str) -> str:
    """Public link SOMTool embeds on the event feedback page."""
    dc = os.environ.get("QUALTRICS_DATA_CENTER", "").strip()
    return f"https://{dc}.qualtrics.com/jfe/form/{survey_id}" if dc and survey_id else ""
