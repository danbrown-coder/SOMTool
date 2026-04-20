"""Student Information System — authoritative roster adapter.

Supports three backends behind one adapter: Ellucian Banner, Jenzabar
PowerCampus, and Workday Student. The institution picks one via env:

  CAMPUS_SIS=banner|powercampus|workday
  CAMPUS_SIS_BASE_URL=...
  CAMPUS_SIS_USERNAME=...
  CAMPUS_SIS_PASSWORD=...
  CAMPUS_SIS_TENANT=...      # Workday
  CAMPUS_SIS_CLIENT_ID=...   # Workday OAuth
  CAMPUS_SIS_CLIENT_SECRET=...

Because most SIS integrations are campus-IT projects on private VPNs, this
module's job is to (a) provide a stable `list_students(filter=...)` surface
for the People importer and (b) isolate vendor-specific payload quirks so
switching institutions is a one-line env change.

The provider is hidden from the Hub when `CAMPUS_SIS` is empty.
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
    slug="sis",
    display_name="Student Information System (Banner / PowerCampus / Workday)",
    authorize_url="",
    token_url="",
    scopes=[],
    client_id_env="CAMPUS_SIS",
    client_secret_env="CAMPUS_SIS",
    redirect_uri_env="CAMPUS_SIS",
    icon_emoji="SIS",
    category="campus",
    description="Authoritative roster, major, and class year from your campus SIS.",
    unlocks=[
        "Authoritative name, major, class year onto every Person",
        "Feeds the Discover engine so invitations hit the right cohort",
        "Nightly delta sync; no CSV uploads ever again",
    ],
    auth_style="api_key",
    api_key_env="CAMPUS_SIS",
    docs_url="https://resources.ellucian.com/ethos",
    extra_env=[
        "CAMPUS_SIS_BASE_URL",
        "CAMPUS_SIS_USERNAME",
        "CAMPUS_SIS_PASSWORD",
        "CAMPUS_SIS_TENANT",
        "CAMPUS_SIS_CLIENT_ID",
        "CAMPUS_SIS_CLIENT_SECRET",
    ],
)
register_provider(SPEC)


def _backend() -> str:
    return (os.environ.get("CAMPUS_SIS") or "").strip().lower()


def _base() -> str:
    return (os.environ.get("CAMPUS_SIS_BASE_URL") or "").rstrip("/")


def list_students(*, major: str = "", class_year: str = "") -> list[dict]:
    """Return a normalized student list: [{name, email, major, class_year}]."""
    be = _backend()
    if be == "banner":
        return _list_banner(major, class_year)
    if be == "powercampus":
        return _list_powercampus(major, class_year)
    if be == "workday":
        return _list_workday(major, class_year)
    return []


# ── Backend-specific implementations (thin; schools usually customize) ──


def _auth_basic() -> tuple[str, str] | None:
    u, p = os.environ.get("CAMPUS_SIS_USERNAME", ""), os.environ.get("CAMPUS_SIS_PASSWORD", "")
    return (u, p) if u and p else None


def _list_banner(major: str, class_year: str) -> list[dict]:
    base = _base()
    if not base:
        return []
    try:
        r = requests.get(
            f"{base}/studentApi/v1/students",
            params={"major": major or None, "classYear": class_year or None},
            auth=_auth_basic(),
            timeout=30,
        )
        r.raise_for_status()
        rows = (r.json() or {}).get("students") or []
        return [
            {
                "name": f"{s.get('firstName','')} {s.get('lastName','')}".strip(),
                "email": s.get("email", ""),
                "major": s.get("primaryMajor", ""),
                "class_year": str(s.get("classYear", "")),
            }
            for s in rows
            if s.get("email")
        ]
    except Exception as exc:
        logger.warning("Banner list_students failed: %s", exc)
        return []


def _list_powercampus(major: str, class_year: str) -> list[dict]:
    base = _base()
    if not base:
        return []
    try:
        r = requests.get(
            f"{base}/api/Students",
            params={"programOfStudy": major or None, "classLevel": class_year or None},
            auth=_auth_basic(),
            timeout=30,
        )
        r.raise_for_status()
        rows = r.json() or []
        return [
            {
                "name": s.get("fullName") or f"{s.get('firstName','')} {s.get('lastName','')}".strip(),
                "email": s.get("emailAddress", ""),
                "major": s.get("programOfStudy", ""),
                "class_year": str(s.get("classLevel", "")),
            }
            for s in rows
            if s.get("emailAddress")
        ]
    except Exception as exc:
        logger.warning("PowerCampus list_students failed: %s", exc)
        return []


def _workday_token() -> Optional[str]:
    cid = os.environ.get("CAMPUS_SIS_CLIENT_ID", "")
    csec = os.environ.get("CAMPUS_SIS_CLIENT_SECRET", "")
    tenant = os.environ.get("CAMPUS_SIS_TENANT", "")
    base = _base()
    if not (cid and csec and tenant and base):
        return None
    try:
        r = requests.post(
            f"{base}/ccx/oauth2/{tenant}/token",
            data={"grant_type": "client_credentials"},
            auth=(cid, csec),
            timeout=15,
        )
        r.raise_for_status()
        return (r.json() or {}).get("access_token")
    except Exception as exc:
        logger.warning("Workday token failed: %s", exc)
        return None


def _list_workday(major: str, class_year: str) -> list[dict]:
    tok = _workday_token()
    base = _base()
    tenant = os.environ.get("CAMPUS_SIS_TENANT", "")
    if not tok or not base:
        return []
    try:
        r = requests.get(
            f"{base}/ccx/api/student/v2/{tenant}/students",
            params={"academic_level": class_year or None, "program": major or None},
            headers={"Authorization": f"Bearer {tok}"},
            timeout=30,
        )
        r.raise_for_status()
        rows = (r.json() or {}).get("data") or []
        return [
            {
                "name": s.get("preferred_name_for_institutional_purposes")
                        or s.get("legal_name") or "",
                "email": (s.get("primary_work_email") or s.get("primary_home_email") or ""),
                "major": (s.get("primary_program") or {}).get("descriptor", ""),
                "class_year": str(s.get("academic_level") or ""),
            }
            for s in rows
            if (s.get("primary_work_email") or s.get("primary_home_email"))
        ]
    except Exception as exc:
        logger.warning("Workday list_students failed: %s", exc)
        return []
