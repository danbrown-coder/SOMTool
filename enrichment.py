"""Apollo.io People enrichment (Phase 7).

Fills missing fields on a Person row (company, title, linkedin_url, phone).
Only updates fields that are currently empty so manual edits are preserved.
Gated behind the `pro` plan at the route layer.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import requests

from db import get_session
from db_models import Person as PersonRow

logger = logging.getLogger(__name__)

API_URL = "https://api.apollo.io/v1/people/match"


def apollo_configured() -> bool:
    return bool(os.environ.get("APOLLO_API_KEY"))


def _call_apollo(email: str) -> Optional[dict]:
    key = os.environ.get("APOLLO_API_KEY", "").strip()
    if not key or not email:
        return None
    try:
        resp = requests.post(
            API_URL,
            headers={"Cache-Control": "no-cache", "Content-Type": "application/json"},
            json={"api_key": key, "email": email, "reveal_personal_emails": False},
            timeout=20,
        )
        if resp.status_code != 200:
            logger.warning("Apollo returned %s: %s", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        return data.get("person") or data.get("matches", [{}])[0] if data.get("matches") else data.get("person")
    except Exception as exc:
        logger.warning("Apollo call failed: %s", exc)
        return None


def enrich_person(person_id: str) -> dict:
    """Enrich a single person. Returns {"ok": bool, "updated_fields": [..], "reason": "..."}"""
    with get_session() as sess:
        row = sess.get(PersonRow, person_id)
        if row is None:
            return {"ok": False, "reason": "not_found"}
        if not row.email:
            return {"ok": False, "reason": "no_email"}
    if not apollo_configured():
        return {"ok": False, "reason": "not_configured"}

    data = _call_apollo(row.email)
    if not data:
        return {"ok": False, "reason": "no_match"}

    updated: list[str] = []
    with get_session() as sess:
        row = sess.get(PersonRow, person_id)
        if row is None:
            return {"ok": False, "reason": "not_found"}
        # Only fill empty fields so we don't clobber user edits
        title = (data.get("title") or "").strip()
        if title and not row.role:
            row.role = title
            updated.append("role")
        org = data.get("organization") or {}
        company = (org.get("name") or "").strip()
        if company and not row.company:
            row.company = company
            updated.append("company")
        linkedin = (data.get("linkedin_url") or "").strip()
        if linkedin and not row.linkedin_url:
            row.linkedin_url = linkedin
            updated.append("linkedin_url")
        phone_numbers = data.get("phone_numbers") or []
        if phone_numbers and not row.phone:
            phone = (phone_numbers[0].get("sanitized_number") or phone_numbers[0].get("raw_number") or "").strip()
            if phone:
                row.phone = phone
                updated.append("phone")
        row.enriched_at = datetime.now(timezone.utc)
        row.enrichment_source = "apollo"
    return {"ok": True, "updated_fields": updated}


def enrich_missing_bulk(limit: int = 50) -> dict:
    """Enrich all people with at least one missing enrichable field. Cap at `limit`."""
    if not apollo_configured():
        return {"ok": False, "reason": "not_configured", "processed": 0, "updated": 0}
    with get_session() as sess:
        candidates = (
            sess.query(PersonRow.id)
            .filter(PersonRow.email != "")
            .filter(
                (PersonRow.company == "")
                | (PersonRow.role == "")
                | (PersonRow.linkedin_url == "")
            )
            .limit(limit)
            .all()
        )
    processed = 0
    updated = 0
    for (pid,) in candidates:
        result = enrich_person(pid)
        processed += 1
        if result.get("ok") and result.get("updated_fields"):
            updated += 1
    return {"ok": True, "processed": processed, "updated": updated}
