"""SQLAlchemy ORM models for SOMTool.

These are the persistent backing store. [models.py](models.py) dataclasses
remain the DTOs exposed to templates and route handlers. The manager modules
translate between the two.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _jsontype():
    """JSON column type that works on both Postgres and SQLite."""
    return JSON().with_variant(JSON(), "sqlite")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(128))
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(128))
    plan: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    seats: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="user", nullable=False)
    google_sub: Mapped[Optional[str]] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    date: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    audience_type: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    som_event_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    sender_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    sender_title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    sender_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    venue_capacity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    walkin_buffer_pct: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    registration_deadline: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    late_fee: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    late_fee_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    goal_registrations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    goal_attendance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    goal_sponsorship: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    goal_budget: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    custom_goals: Mapped[list] = mapped_column(_jsontype(), default=list, nullable=False)
    planned_budget: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    actual_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    sponsorship_revenue: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    expenses: Mapped[list] = mapped_column(_jsontype(), default=list, nullable=False)
    registration_pin: Mapped[str] = mapped_column(String(16), default="", nullable=False)

    registration_fee_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stripe_product_id: Mapped[Optional[str]] = mapped_column(String(128))
    stripe_price_id: Mapped[Optional[str]] = mapped_column(String(128))
    gcal_event_id: Mapped[Optional[str]] = mapped_column(String(255))
    sms_reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", lazy="selectin", order_by="Contact.registered_at"
    )
    permissions: Mapped[list["EventShare"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", lazy="selectin"
    )


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="not_contacted", nullable=False)
    attended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    contact_role: Mapped[str] = mapped_column(String(32), default="attendee", nullable=False)
    phone: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    registration_type: Mapped[str] = mapped_column(String(32), default="pre_registered", nullable=False)
    registered_at: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    event: Mapped["Event"] = relationship(back_populates="contacts")


class EventShare(Base):
    __tablename__ = "event_shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), default="viewer", nullable=False)

    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_event_share_event_user"),)

    event: Mapped["Event"] = relationship(back_populates="permissions")


class Person(Base):
    __tablename__ = "people"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False, index=True)
    company: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    role: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    linkedin_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    tags: Mapped[list] = mapped_column(_jsontype(), default=list, nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    referred_by: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    added_at: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    events_participated: Mapped[list] = mapped_column(_jsontype(), default=list, nullable=False)
    enriched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    enrichment_source: Mapped[Optional[str]] = mapped_column(String(64))


class OutreachLog(Base):
    __tablename__ = "outreach_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    contact_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    email_type: Mapped[str] = mapped_column(String(32), default="initial", nullable=False)
    email_body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    timestamp: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)

    delivery_status: Mapped[Optional[str]] = mapped_column(String(32))
    provider: Mapped[Optional[str]] = mapped_column(String(32))
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(255))
    opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    bounced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class FeedbackEntry(Base):
    __tablename__ = "feedback_entries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    respondent_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    respondent_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    rating: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    liked: Mapped[str] = mapped_column(Text, default="", nullable=False)
    improve: Mapped[str] = mapped_column(Text, default="", nullable=False)
    would_attend_again: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    submitted_at: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)


class Connection(Base):
    """OAuth connections from users to third-party providers."""
    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    account_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(255))
    scopes: Mapped[list] = mapped_column(_jsontype(), default=list, nullable=False)
    access_token_enc: Mapped[str] = mapped_column(Text, default="", nullable=False)
    refresh_token_enc: Mapped[str] = mapped_column(Text, default="", nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(_jsontype(), default=dict, nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_connection_user_provider"),)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("events.id", ondelete="SET NULL"), index=True)
    contact_id: Mapped[Optional[str]] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(32), default="registration", nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="usd", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    stripe_checkout_session_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    stripe_payment_intent_id: Mapped[Optional[str]] = mapped_column(String(255))
    payer_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    payer_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    meta: Mapped[dict] = mapped_column(_jsontype(), default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    stripe_subscription_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    stripe_customer_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    plan: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    meta: Mapped[dict] = mapped_column(_jsontype(), default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class FileAsset(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_user_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    event_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("events.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(64), default="misc", nullable=False)
    s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    bucket: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    filename: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    mime: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    public_url: Mapped[Optional[str]] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class SMSLog(Base):
    __tablename__ = "sms_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("events.id", ondelete="SET NULL"), index=True)
    contact_id: Mapped[Optional[str]] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(16), default="outbound", nullable=False)
    to_number: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    from_number: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    twilio_sid: Mapped[Optional[str]] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
