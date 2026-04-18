"""Stripe Checkout for event registration fees (Phase 6a).

One-time payments collected from attendees (not the SaaS subscription
flow — that's `billing_saas.py`). Writes to the `payments` table and
upserts the contact on `checkout.session.completed`.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from db import get_session
from db_models import Contact as ContactRow
from db_models import Event as EventRow
from db_models import Payment
from models import ContactStatus, RegistrationType, new_id, utc_now_iso
from org_manager import current_org_id


def _stripe_configured() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY"))


def _stripe():
    import stripe
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    return stripe


def _base_url() -> str:
    return (os.environ.get("APP_BASE_URL") or "http://localhost:5000").rstrip("/")


def _event_after_deadline(event: EventRow) -> bool:
    if not event.registration_deadline:
        return False
    try:
        dl = datetime.fromisoformat(event.registration_deadline.replace("Z", "+00:00"))
        if dl.tzinfo is None:
            dl = dl.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= dl
    except ValueError:
        return False


def create_checkout_session(
    event_id: str,
    payer_email: str,
    payer_name: str = "",
) -> dict:
    """Create a Stripe Checkout session for an event registration.

    Adds the late fee as a second line item automatically when the event's
    registration_deadline has passed.
    """
    if not _stripe_configured():
        return {"ok": False, "error": "Stripe not configured"}
    with get_session() as sess:
        event = sess.get(EventRow, event_id)
        if event is None:
            return {"ok": False, "error": "Event not found"}
        if event.registration_fee_cents <= 0:
            return {"ok": False, "error": "This event has no registration fee."}

        base = _base_url()
        line_items = [{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"{event.name} — Registration",
                    "description": (event.description or "")[:500] or None,
                },
                "unit_amount": int(event.registration_fee_cents),
            },
            "quantity": 1,
        }]
        if _event_after_deadline(event) and event.late_fee and event.late_fee > 0:
            line_items.append({
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": "Late registration fee",
                        "description": (event.late_fee_note or "Late fee")[:500] or None,
                    },
                    "unit_amount": int(round(event.late_fee * 100)),
                },
                "quantity": 1,
            })

        stripe = _stripe()
        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                success_url=f"{base}/events/{event_id}/pay/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{base}/events/{event_id}/pay?cancelled=1",
                customer_email=payer_email or None,
                line_items=line_items,
                metadata={
                    "event_id": event_id,
                    "payer_name": payer_name or "",
                    "type": "registration",
                },
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300]}

        payment = Payment(
            id=new_id(),
            org_id=event.org_id,
            event_id=event_id,
            type="registration",
            amount_cents=sum(int(li["price_data"]["unit_amount"]) for li in line_items),
            currency="usd",
            status="pending",
            stripe_checkout_session_id=session.id,
            payer_email=payer_email or "",
            payer_name=payer_name or "",
            meta={"line_items": [li["price_data"]["product_data"]["name"] for li in line_items]},
        )
        sess.add(payment)
        return {"ok": True, "url": session.url, "session_id": session.id}


def handle_webhook_event(event: dict) -> None:
    """Handle a parsed Stripe webhook event for registration payments."""
    etype = event.get("type", "")
    data = (event.get("data", {}) or {}).get("object", {}) or {}

    if etype == "checkout.session.completed":
        _handle_checkout_completed(data)
    elif etype in ("payment_intent.succeeded", "payment_intent.payment_failed"):
        _handle_payment_intent(data)


def _handle_checkout_completed(session_obj: dict) -> None:
    session_id = session_obj.get("id") or ""
    metadata = session_obj.get("metadata") or {}
    event_id = metadata.get("event_id", "")
    if metadata.get("type") not in (None, "registration"):
        return  # not ours (probably a subscription)
    payer_email = session_obj.get("customer_details", {}).get("email") or session_obj.get("customer_email") or ""
    payer_name = session_obj.get("customer_details", {}).get("name") or metadata.get("payer_name", "")
    payment_intent = session_obj.get("payment_intent") or ""
    amount_total = int(session_obj.get("amount_total") or 0)

    with get_session() as sess:
        payment = (
            sess.query(Payment)
            .filter(Payment.stripe_checkout_session_id == session_id)
            .first()
        )
        if payment is None:
            event_row = sess.get(EventRow, event_id) if event_id else None
            payment = Payment(
                id=new_id(),
                org_id=(event_row.org_id if event_row else current_org_id()),
                event_id=event_id or None,
                type="registration",
                amount_cents=amount_total,
                currency=session_obj.get("currency", "usd") or "usd",
                status="paid",
                stripe_checkout_session_id=session_id,
                stripe_payment_intent_id=payment_intent,
                payer_email=payer_email or "",
                payer_name=payer_name or "",
                meta={},
            )
            sess.add(payment)
        else:
            payment.status = "paid"
            payment.stripe_payment_intent_id = payment_intent
            payment.amount_cents = amount_total or payment.amount_cents
            if payer_email:
                payment.payer_email = payer_email
            if payer_name:
                payment.payer_name = payer_name

        if event_id and payer_email:
            existing = (
                sess.query(ContactRow)
                .filter(ContactRow.event_id == event_id)
                .filter(ContactRow.email.ilike(payer_email.lower()))
                .first()
            )
            if existing is None:
                sess.add(ContactRow(
                    id=new_id(),
                    event_id=event_id,
                    name=payer_name or payer_email.split("@")[0],
                    email=payer_email,
                    status=ContactStatus.CONFIRMED.value,
                    attended=False,
                    contact_role="attendee",
                    phone="",
                    registration_type=RegistrationType.PRE_REGISTERED.value,
                    registered_at=utc_now_iso(),
                ))
                payment.contact_id = None  # new contact id is fresh; we could set it but not strictly needed
            else:
                existing.status = ContactStatus.CONFIRMED.value
                payment.contact_id = existing.id


def _handle_payment_intent(intent: dict) -> None:
    pi_id = intent.get("id") or ""
    if not pi_id:
        return
    status = intent.get("status") or "succeeded"
    with get_session() as sess:
        p = sess.query(Payment).filter(Payment.stripe_payment_intent_id == pi_id).first()
        if p is None:
            return
        if status == "succeeded":
            p.status = "paid"
        elif status in ("canceled", "requires_payment_method"):
            p.status = "failed"
