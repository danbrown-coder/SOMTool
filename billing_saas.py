"""Stripe Subscriptions for SaaS plans (Phase 6b).

Plans:
    free      — default, no payment required
    pro       — STRIPE_PRICE_PRO
    campus    — STRIPE_PRICE_CAMPUS

The Organization row holds the active plan. Feature-gating happens via the
`require_plan` decorator declared in this module.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from functools import wraps
from typing import Optional

from flask import flash, g, redirect, url_for

from db import get_session
from db_models import Organization, Subscription
from models import new_id
from org_manager import current_org_id


PLAN_TIERS = {"free": 0, "pro": 1, "campus": 2}


PLAN_PRICE_ENVS = {
    "pro": "STRIPE_PRICE_PRO",
    "campus": "STRIPE_PRICE_CAMPUS",
}


def _stripe():
    import stripe
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    return stripe


def _stripe_configured() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY"))


def _base_url() -> str:
    return (os.environ.get("APP_BASE_URL") or "http://localhost:5000").rstrip("/")


def plan_price_id(plan: str) -> str:
    env = PLAN_PRICE_ENVS.get(plan)
    if not env:
        return ""
    return os.environ.get(env, "").strip()


def current_plan(org_id: str | None = None) -> str:
    org_id = org_id or current_org_id()
    with get_session() as sess:
        org = sess.get(Organization, org_id)
        return (org.plan if org and org.plan else "free") or "free"


def has_plan_at_least(required: str, org_id: str | None = None) -> bool:
    cur = current_plan(org_id)
    return PLAN_TIERS.get(cur, 0) >= PLAN_TIERS.get(required, 99)


def require_plan(required_plan: str):
    """Route decorator. Redirect to /settings/billing if the org's plan is too low."""
    def deco(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if has_plan_at_least(required_plan):
                return view(*args, **kwargs)
            flash(f"Upgrade to the {required_plan} plan to use this feature.", "info")
            return redirect(url_for("billing_settings"))
        return wrapped
    return deco


# ── Checkout for upgrading the org's plan ───────────────────


def create_subscription_checkout(org_id: str, plan: str, customer_email: str) -> dict:
    if not _stripe_configured():
        return {"ok": False, "error": "Stripe not configured"}
    price_id = plan_price_id(plan)
    if not price_id:
        return {"ok": False, "error": f"No price configured for plan '{plan}'"}

    stripe = _stripe()
    base = _base_url()

    with get_session() as sess:
        org = sess.get(Organization, org_id)
        if org is None:
            return {"ok": False, "error": "Organization not found"}
        customer_id = org.stripe_customer_id
        if not customer_id:
            cust = stripe.Customer.create(email=customer_email or None, name=org.name or None, metadata={"org_id": org_id})
            customer_id = cust.id
            org.stripe_customer_id = customer_id

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{base}/settings/billing?upgraded=1",
            cancel_url=f"{base}/settings/billing?cancelled=1",
            metadata={"org_id": org_id, "plan": plan, "type": "saas"},
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}
    return {"ok": True, "url": session.url}


def create_billing_portal_url(org_id: str) -> Optional[str]:
    if not _stripe_configured():
        return None
    with get_session() as sess:
        org = sess.get(Organization, org_id)
        if org is None or not org.stripe_customer_id:
            return None
        customer_id = org.stripe_customer_id
    try:
        stripe = _stripe()
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{_base_url()}/settings/billing",
        )
        return session.url
    except Exception:
        return None


# ── Webhook handler ─────────────────────────────────────────


def handle_webhook_event(event: dict) -> None:
    etype = event.get("type", "")
    data = (event.get("data", {}) or {}).get("object", {}) or {}

    if etype == "checkout.session.completed" and (data.get("mode") == "subscription" or (data.get("metadata") or {}).get("type") == "saas"):
        _handle_checkout_subscription_completed(data)
    elif etype in (
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        _handle_subscription_change(data)


def _plan_from_price_id(price_id: str) -> str:
    for plan, env in PLAN_PRICE_ENVS.items():
        if price_id and os.environ.get(env, "") == price_id:
            return plan
    return "pro"  # sensible default


def _handle_checkout_subscription_completed(session_obj: dict) -> None:
    metadata = session_obj.get("metadata") or {}
    org_id = metadata.get("org_id", "")
    plan = metadata.get("plan", "")
    customer_id = session_obj.get("customer") or ""
    sub_id = session_obj.get("subscription") or ""
    if not org_id:
        return
    with get_session() as sess:
        org = sess.get(Organization, org_id)
        if org is None:
            return
        if plan:
            org.plan = plan
        if customer_id:
            org.stripe_customer_id = customer_id
        if sub_id:
            org.stripe_subscription_id = sub_id


def _handle_subscription_change(sub_obj: dict) -> None:
    sub_id = sub_obj.get("id") or ""
    customer_id = sub_obj.get("customer") or ""
    status = sub_obj.get("status") or "active"
    cancel_at_period_end = bool(sub_obj.get("cancel_at_period_end"))
    items = ((sub_obj.get("items") or {}).get("data") or [])
    price_id = (items[0].get("price", {}).get("id") if items else "") or ""
    plan = _plan_from_price_id(price_id)
    period_end = sub_obj.get("current_period_end")
    cpe = None
    if period_end:
        try:
            cpe = datetime.fromtimestamp(int(period_end), tz=timezone.utc)
        except (ValueError, TypeError):
            cpe = None

    if not sub_id or not customer_id:
        return

    with get_session() as sess:
        org = sess.query(Organization).filter(Organization.stripe_customer_id == customer_id).first()
        if org is None:
            return

        existing = sess.query(Subscription).filter(Subscription.stripe_subscription_id == sub_id).first()
        if existing is None:
            existing = Subscription(
                id=new_id(),
                org_id=org.id,
                stripe_subscription_id=sub_id,
                stripe_customer_id=customer_id,
                status=status,
                plan=plan,
                current_period_end=cpe,
                cancel_at_period_end=cancel_at_period_end,
                meta={},
            )
            sess.add(existing)
        else:
            existing.status = status
            existing.plan = plan
            existing.current_period_end = cpe
            existing.cancel_at_period_end = cancel_at_period_end
            existing.updated_at = datetime.now(timezone.utc)

        if status in ("active", "trialing"):
            org.plan = plan
            org.stripe_subscription_id = sub_id
        elif status in ("canceled", "incomplete_expired", "unpaid", "past_due"):
            org.plan = "free"
