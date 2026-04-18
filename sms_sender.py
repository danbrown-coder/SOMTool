"""SMS sender using Twilio. Also logs every send to the `sms_logs` table."""
from __future__ import annotations

import os

from db import get_session
from db_models import SMSLog
from models import new_id, normalize_phone
from org_manager import current_org_id


def _twilio_configured() -> bool:
    return bool(
        os.environ.get("TWILIO_ACCOUNT_SID")
        and os.environ.get("TWILIO_AUTH_TOKEN")
        and os.environ.get("TWILIO_FROM_NUMBER")
    )


def _client():
    try:
        from twilio.rest import Client
    except ImportError:
        return None
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        return None
    return Client(sid, token)


def send_sms(
    to: str,
    body: str,
    event_id: str | None = None,
    contact_id: str | None = None,
    org_id: str | None = None,
) -> dict:
    """Send a single SMS via Twilio and write an sms_logs row.

    Returns {"ok": True, "sid": "..."} or {"ok": False, "error": "..."}
    """
    to_norm = normalize_phone(to)
    from_number = os.environ.get("TWILIO_FROM_NUMBER", "")
    org = org_id or current_org_id()
    log = SMSLog(
        id=new_id(),
        org_id=org,
        event_id=event_id,
        contact_id=contact_id,
        direction="outbound",
        to_number=to_norm,
        from_number=from_number,
        body=body or "",
        status="queued",
    )

    if not to_norm or "+" not in to_norm:
        log.status = "failed"
        log.error = "Invalid destination number"
        with get_session() as sess:
            sess.add(log)
        return {"ok": False, "error": log.error}

    if not _twilio_configured():
        log.status = "failed"
        log.error = "Twilio not configured"
        with get_session() as sess:
            sess.add(log)
        return {"ok": False, "error": log.error}

    client = _client()
    if client is None:
        log.status = "failed"
        log.error = "Twilio SDK unavailable"
        with get_session() as sess:
            sess.add(log)
        return {"ok": False, "error": log.error}

    try:
        msg = client.messages.create(body=body or "", from_=from_number, to=to_norm)
        log.twilio_sid = msg.sid
        log.status = msg.status or "sent"
        with get_session() as sess:
            sess.add(log)
        return {"ok": True, "sid": msg.sid, "status": log.status}
    except Exception as exc:
        log.status = "failed"
        log.error = str(exc)[:500]
        with get_session() as sess:
            sess.add(log)
        return {"ok": False, "error": log.error}


def send_batch(items: list[dict]) -> list[dict]:
    """Each item: to, body, event_id?, contact_id?"""
    results = []
    for it in items:
        r = send_sms(
            to=it.get("to", ""),
            body=it.get("body", ""),
            event_id=it.get("event_id"),
            contact_id=it.get("contact_id"),
        )
        r["to"] = it.get("to", "")
        results.append(r)
    return results


def find_contact_by_phone(phone: str) -> tuple[str, str] | None:
    """Find (event_id, contact_id) for an inbound number. Best-effort lookup
    against the most recent outbound SMS to that number. Returns None if no match.
    """
    norm = normalize_phone(phone)
    if not norm:
        return None
    with get_session() as sess:
        row = (
            sess.query(SMSLog)
            .filter(SMSLog.to_number == norm, SMSLog.direction == "outbound")
            .order_by(SMSLog.created_at.desc())
            .first()
        )
        if row is None or not row.event_id or not row.contact_id:
            return None
        return row.event_id, row.contact_id
