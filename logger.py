"""Append-only outreach log (DB-backed)."""
from __future__ import annotations

from db import get_session
from db_models import OutreachLog as OutreachLogRow
from models import EmailType, OutreachLog, new_id, utc_now_iso


def _row_to_dto(row: OutreachLogRow) -> OutreachLog:
    return OutreachLog(
        id=row.id,
        event_id=row.event_id,
        contact_id=row.contact_id or "",
        contact_name=row.contact_name or "",
        email_type=EmailType(row.email_type) if row.email_type else EmailType.INITIAL,
        email_body=row.email_body or "",
        timestamp=row.timestamp or "",
    )


def log_outreach(
    event_id: str,
    contact_id: str,
    contact_name: str,
    email_type: EmailType,
    email_body: str,
    subject: str | None = None,
) -> OutreachLog:
    """Append a log entry. email_body may include subject line prefix for display."""
    body = email_body
    if subject:
        body = f"Subject: {subject}\n\n{email_body}"
    row = OutreachLogRow(
        id=new_id(),
        event_id=event_id,
        contact_id=contact_id or "",
        contact_name=contact_name or "",
        email_type=email_type.value if hasattr(email_type, "value") else str(email_type),
        email_body=body,
        timestamp=utc_now_iso(),
    )
    with get_session() as sess:
        sess.add(row)
        sess.flush()
        return _row_to_dto(row)


def get_logs(event_id: str) -> list[OutreachLog]:
    with get_session() as sess:
        rows = sess.query(OutreachLogRow).filter(
            OutreachLogRow.event_id == event_id
        ).order_by(OutreachLogRow.timestamp).all()
        return [_row_to_dto(r) for r in rows]


def get_all_logs() -> list[OutreachLog]:
    with get_session() as sess:
        rows = sess.query(OutreachLogRow).order_by(OutreachLogRow.timestamp).all()
        return [_row_to_dto(r) for r in rows]


def get_last_outreach(event_id: str, contact_id: str) -> dict | None:
    """Return the most recent log entry for a specific contact on an event."""
    with get_session() as sess:
        row = sess.query(OutreachLogRow).filter(
            OutreachLogRow.event_id == event_id,
            OutreachLogRow.contact_id == contact_id,
        ).order_by(OutreachLogRow.timestamp.desc()).first()
        return _row_to_dto(row).to_dict() if row else None


def update_delivery_status(
    log_id: str,
    delivery_status: str | None = None,
    provider: str | None = None,
    provider_message_id: str | None = None,
    opened_at=None,
    bounced_at=None,
) -> bool:
    """Used by Resend webhooks (Phase 2) to update delivery status."""
    with get_session() as sess:
        row = sess.get(OutreachLogRow, log_id)
        if row is None:
            return False
        if delivery_status is not None:
            row.delivery_status = delivery_status
        if provider is not None:
            row.provider = provider
        if provider_message_id is not None:
            row.provider_message_id = provider_message_id
        if opened_at is not None:
            row.opened_at = opened_at
        if bounced_at is not None:
            row.bounced_at = bounced_at
        return True


def find_by_provider_message_id(provider_message_id: str) -> OutreachLog | None:
    """Look up a log by the external provider's message id (for webhook matching)."""
    if not provider_message_id:
        return None
    with get_session() as sess:
        row = sess.query(OutreachLogRow).filter(
            OutreachLogRow.provider_message_id == provider_message_id
        ).first()
        return _row_to_dto(row) if row else None
