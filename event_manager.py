"""DB-backed CRUD for events and contacts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select

from db import get_session
from db_models import Contact as ContactRow
from db_models import Event as EventRow
from db_models import EventShare as EventShareRow
from models import (
    Contact, ContactRole, ContactStatus, Event, RegistrationType,
    new_id, utc_now_iso,
)
from org_manager import DEFAULT_ORG_ID, ensure_default_org

if TYPE_CHECKING:
    from models import User


def _contact_row_to_dto(row: ContactRow) -> Contact:
    return Contact(
        id=row.id,
        name=row.name,
        email=row.email,
        status=ContactStatus(row.status) if row.status else ContactStatus.NOT_CONTACTED,
        attended=row.attended,
        contact_role=ContactRole(row.contact_role) if row.contact_role else ContactRole.ATTENDEE,
        phone=row.phone,
        registration_type=RegistrationType(row.registration_type) if row.registration_type else RegistrationType.PRE_REGISTERED,
        registered_at=row.registered_at,
    )


def _event_row_to_dto(row: EventRow) -> Event:
    contacts = [_contact_row_to_dto(c) for c in sorted(row.contacts, key=lambda c: c.registered_at or "")]
    perms = [{"user_id": p.user_id, "role": p.role} for p in row.permissions]
    return Event(
        id=row.id,
        name=row.name,
        date=row.date,
        description=row.description,
        audience_type=row.audience_type,
        contacts=contacts,
        som_event_id=row.som_event_id or "",
        owner_id=row.owner_id or "",
        permissions=perms,
        sender_name=row.sender_name or "",
        sender_title=row.sender_title or "",
        sender_email=row.sender_email or "",
        venue_capacity=row.venue_capacity,
        walkin_buffer_pct=row.walkin_buffer_pct,
        registration_deadline=row.registration_deadline or "",
        late_fee=row.late_fee,
        late_fee_note=row.late_fee_note or "",
        goal_registrations=row.goal_registrations,
        goal_attendance=row.goal_attendance,
        goal_sponsorship=row.goal_sponsorship,
        goal_budget=row.goal_budget,
        custom_goals=list(row.custom_goals or []),
        planned_budget=row.planned_budget,
        actual_spend=row.actual_spend,
        sponsorship_revenue=row.sponsorship_revenue,
        expenses=list(row.expenses or []),
        registration_pin=row.registration_pin or "",
        gcal_event_id=row.gcal_event_id or "",
        registration_fee_cents=int(row.registration_fee_cents or 0),
        stripe_price_id=row.stripe_price_id or "",
    )


def _apply_event_dto_to_row(row: EventRow, e: Event) -> None:
    row.name = e.name
    row.date = e.date
    row.description = e.description
    row.audience_type = e.audience_type
    row.som_event_id = e.som_event_id or ""
    row.owner_id = e.owner_id or ""
    row.sender_name = e.sender_name or ""
    row.sender_title = e.sender_title or ""
    row.sender_email = e.sender_email or ""
    row.venue_capacity = int(e.venue_capacity or 0)
    row.walkin_buffer_pct = int(e.walkin_buffer_pct or 15)
    row.registration_deadline = e.registration_deadline or ""
    row.late_fee = float(e.late_fee or 0.0)
    row.late_fee_note = e.late_fee_note or ""
    row.goal_registrations = int(e.goal_registrations or 0)
    row.goal_attendance = int(e.goal_attendance or 0)
    row.goal_sponsorship = float(e.goal_sponsorship or 0.0)
    row.goal_budget = float(e.goal_budget or 0.0)
    row.custom_goals = list(e.custom_goals or [])
    row.planned_budget = float(e.planned_budget or 0.0)
    row.actual_spend = float(e.actual_spend or 0.0)
    row.sponsorship_revenue = float(e.sponsorship_revenue or 0.0)
    row.expenses = list(e.expenses or [])
    row.registration_pin = e.registration_pin or ""
    if getattr(e, "gcal_event_id", ""):
        row.gcal_event_id = e.gcal_event_id
    if getattr(e, "registration_fee_cents", 0):
        row.registration_fee_cents = int(e.registration_fee_cents)
    if getattr(e, "stripe_price_id", ""):
        row.stripe_price_id = e.stripe_price_id


def _apply_contact_dto_to_row(row: ContactRow, c: Contact) -> None:
    row.name = c.name
    row.email = c.email
    row.status = c.status.value if hasattr(c.status, "value") else str(c.status)
    row.attended = bool(c.attended)
    row.contact_role = c.contact_role.value if hasattr(c.contact_role, "value") else str(c.contact_role)
    row.phone = c.phone or ""
    row.registration_type = c.registration_type.value if hasattr(c.registration_type, "value") else str(c.registration_type)
    row.registered_at = c.registered_at or utc_now_iso()


def migrate_legacy_event_ownership(admin_user_id: str) -> None:
    """Assign owner_id to events missing it (one-time migration)."""
    ensure_default_org()
    with get_session() as sess:
        rows = sess.query(EventRow).filter((EventRow.owner_id == "") | (EventRow.owner_id.is_(None))).all()
        for r in rows:
            r.owner_id = admin_user_id


def load_events() -> list[Event]:
    ensure_default_org()
    with get_session() as sess:
        rows = sess.execute(
            select(EventRow).where(EventRow.org_id == DEFAULT_ORG_ID).order_by(EventRow.date)
        ).scalars().all()
        return [_event_row_to_dto(r) for r in rows]


def get_event_share_role(user: "User | None", event: Event) -> str | None:
    """Return 'owner', 'editor', or 'viewer', or None if no access."""
    if user is None:
        return None
    if user.role == "admin":
        return "owner"
    if event.owner_id == user.id:
        return "owner"
    for p in event.permissions:
        if p.get("user_id") == user.id:
            r = (p.get("role") or "viewer").lower()
            if r in ("editor", "viewer"):
                return r
    return None


def list_events_visible_to(user: "User | None") -> list[Event]:
    if user is None:
        return []
    events = load_events()
    if user.role == "admin":
        return events
    return [e for e in events if get_event_share_role(user, e) is not None]


def save_events(events: list[Event]) -> None:
    """Upsert each event in the list. Does not delete events absent from the list
    (callers that modify a subset should not lose the rest). For deletes use `delete_event`.
    """
    ensure_default_org()
    with get_session() as sess:
        for e in events:
            row = sess.get(EventRow, e.id)
            if row is None:
                row = EventRow(id=e.id, org_id=DEFAULT_ORG_ID)
                sess.add(row)
            _apply_event_dto_to_row(row, e)
            # Contacts: upsert keyed by id, delete rows not in the DTO list
            existing_by_id = {c.id: c for c in row.contacts}
            incoming_ids = {c.id for c in e.contacts}
            for c in e.contacts:
                crow = existing_by_id.get(c.id)
                if crow is None:
                    crow = ContactRow(id=c.id, event_id=e.id)
                    sess.add(crow)
                _apply_contact_dto_to_row(crow, c)
            for cid, crow in existing_by_id.items():
                if cid not in incoming_ids:
                    sess.delete(crow)
            # Permissions (event shares): same upsert logic keyed on user_id
            existing_perms = {p.user_id: p for p in row.permissions}
            incoming_users = {p.get("user_id") for p in e.permissions if p.get("user_id")}
            for p in e.permissions:
                uid = p.get("user_id")
                if not uid:
                    continue
                prow = existing_perms.get(uid)
                if prow is None:
                    prow = EventShareRow(event_id=e.id, user_id=uid, role=p.get("role") or "viewer")
                    sess.add(prow)
                else:
                    prow.role = p.get("role") or prow.role
            for uid, prow in existing_perms.items():
                if uid not in incoming_users:
                    sess.delete(prow)


def get_event(event_id: str) -> Event | None:
    with get_session() as sess:
        row = sess.get(EventRow, event_id)
        return _event_row_to_dto(row) if row else None


def create_event(
    name: str,
    date: str,
    description: str,
    audience_type: str,
    owner_id: str = "",
    sender_name: str = "",
    sender_title: str = "",
    sender_email: str = "",
    venue_capacity: int = 0,
    walkin_buffer_pct: int = 15,
    registration_deadline: str = "",
    late_fee: float = 0.0,
    late_fee_note: str = "",
    **kwargs,
) -> Event:
    ensure_default_org()
    eid = new_id()
    with get_session() as sess:
        row = EventRow(
            id=eid,
            org_id=DEFAULT_ORG_ID,
            name=name.strip(),
            date=date.strip(),
            description=description.strip(),
            audience_type=audience_type.strip(),
            owner_id=owner_id.strip(),
            sender_name=sender_name.strip(),
            sender_title=sender_title.strip(),
            sender_email=sender_email.strip(),
            venue_capacity=int(venue_capacity or 0),
            walkin_buffer_pct=int(walkin_buffer_pct or 15),
            registration_deadline=(registration_deadline or "").strip(),
            late_fee=float(late_fee or 0.0),
            late_fee_note=(late_fee_note or "").strip(),
            goal_registrations=int(kwargs.get("goal_registrations", 0) or 0),
            goal_attendance=int(kwargs.get("goal_attendance", 0) or 0),
            goal_sponsorship=float(kwargs.get("goal_sponsorship", 0.0) or 0.0),
            goal_budget=float(kwargs.get("goal_budget", 0.0) or 0.0),
            custom_goals=list(kwargs.get("custom_goals", []) or []),
            planned_budget=float(kwargs.get("planned_budget", 0.0) or 0.0),
            actual_spend=float(kwargs.get("actual_spend", 0.0) or 0.0),
            sponsorship_revenue=float(kwargs.get("sponsorship_revenue", 0.0) or 0.0),
            expenses=list(kwargs.get("expenses", []) or []),
            registration_pin=(kwargs.get("registration_pin", "") or ""),
        )
        sess.add(row)
    return get_event(eid)  # type: ignore[return-value]


def update_event(
    event_id: str,
    name: str,
    date: str,
    description: str,
    audience_type: str,
    sender_name: str = "",
    sender_title: str = "",
    sender_email: str = "",
    venue_capacity: int = 0,
    walkin_buffer_pct: int = 15,
    registration_deadline: str = "",
    late_fee: float = 0.0,
    late_fee_note: str = "",
    **kwargs,
) -> bool:
    with get_session() as sess:
        row = sess.get(EventRow, event_id)
        if row is None:
            return False
        row.name = name.strip()
        row.date = date.strip()
        row.description = description.strip()
        row.audience_type = audience_type.strip()
        row.sender_name = sender_name.strip()
        row.sender_title = sender_title.strip()
        row.sender_email = sender_email.strip()
        row.venue_capacity = int(venue_capacity or 0)
        row.walkin_buffer_pct = int(walkin_buffer_pct or 15)
        row.registration_deadline = (registration_deadline or "").strip()
        row.late_fee = float(late_fee or 0.0)
        row.late_fee_note = (late_fee_note or "").strip()
        if "goal_registrations" in kwargs:
            row.goal_registrations = int(kwargs["goal_registrations"] or 0)
        if "goal_attendance" in kwargs:
            row.goal_attendance = int(kwargs["goal_attendance"] or 0)
        if "goal_sponsorship" in kwargs:
            row.goal_sponsorship = float(kwargs["goal_sponsorship"] or 0.0)
        if "goal_budget" in kwargs:
            row.goal_budget = float(kwargs["goal_budget"] or 0.0)
        if "custom_goals" in kwargs:
            row.custom_goals = list(kwargs["custom_goals"] or [])
        if "planned_budget" in kwargs:
            row.planned_budget = float(kwargs["planned_budget"] or 0.0)
        if "actual_spend" in kwargs:
            row.actual_spend = float(kwargs["actual_spend"] or 0.0)
        if "sponsorship_revenue" in kwargs:
            row.sponsorship_revenue = float(kwargs["sponsorship_revenue"] or 0.0)
        if "expenses" in kwargs:
            row.expenses = list(kwargs["expenses"] or [])
        if "registration_pin" in kwargs:
            row.registration_pin = kwargs["registration_pin"] or ""
        if "registration_fee_cents" in kwargs:
            row.registration_fee_cents = int(kwargs["registration_fee_cents"] or 0)
        if "stripe_price_id" in kwargs:
            row.stripe_price_id = kwargs["stripe_price_id"] or ""
        return True


def set_gcal_event_id(event_id: str, gcal_event_id: str) -> bool:
    with get_session() as sess:
        row = sess.get(EventRow, event_id)
        if row is None:
            return False
        row.gcal_event_id = gcal_event_id or ""
        return True


def set_event_stripe(event_id: str, price_id: str, product_id: str | None = None) -> bool:
    with get_session() as sess:
        row = sess.get(EventRow, event_id)
        if row is None:
            return False
        row.stripe_price_id = price_id or ""
        if product_id is not None:
            row.stripe_product_id = product_id or None
        return True


def delete_event(event_id: str) -> bool:
    with get_session() as sess:
        row = sess.get(EventRow, event_id)
        if row is None:
            return False
        sess.delete(row)
        return True


def add_contact(
    event_id: str,
    name: str,
    email: str,
    contact_role: ContactRole = ContactRole.ATTENDEE,
    phone: str = "",
    registration_type: RegistrationType = RegistrationType.PRE_REGISTERED,
    status: ContactStatus = ContactStatus.NOT_CONTACTED,
    attended: bool = False,
) -> Contact | None:
    with get_session() as sess:
        event = sess.get(EventRow, event_id)
        if event is None:
            return None
        crow = ContactRow(
            id=new_id(),
            event_id=event_id,
            name=name.strip(),
            email=email.strip(),
            status=status.value if hasattr(status, "value") else str(status),
            attended=bool(attended),
            contact_role=contact_role.value if hasattr(contact_role, "value") else str(contact_role),
            phone=phone.strip(),
            registration_type=registration_type.value if hasattr(registration_type, "value") else str(registration_type),
            registered_at=utc_now_iso(),
        )
        sess.add(crow)
        sess.flush()
        return _contact_row_to_dto(crow)


def delete_contact(event_id: str, contact_id: str) -> bool:
    with get_session() as sess:
        row = sess.query(ContactRow).filter(
            ContactRow.event_id == event_id, ContactRow.id == contact_id
        ).first()
        if row is None:
            return False
        sess.delete(row)
        return True


def update_contact_details(
    event_id: str, contact_id: str,
    name: str = "", email: str = "", phone: str = "",
) -> bool:
    with get_session() as sess:
        row = sess.query(ContactRow).filter(
            ContactRow.event_id == event_id, ContactRow.id == contact_id
        ).first()
        if row is None:
            return False
        if name:
            row.name = name.strip()
        if email:
            row.email = email.strip()
        if phone is not None:
            row.phone = phone.strip()
        return True


def update_contact_status(event_id: str, contact_id: str, status: str) -> bool:
    try:
        new_status = ContactStatus(status)
    except ValueError:
        return False
    with get_session() as sess:
        row = sess.query(ContactRow).filter(
            ContactRow.event_id == event_id, ContactRow.id == contact_id
        ).first()
        if row is None:
            return False
        row.status = new_status.value
        return True


def update_contact_role(event_id: str, contact_id: str, role: str) -> bool:
    try:
        new_role = ContactRole(role)
    except ValueError:
        return False
    with get_session() as sess:
        row = sess.query(ContactRow).filter(
            ContactRow.event_id == event_id, ContactRow.id == contact_id
        ).first()
        if row is None:
            return False
        row.contact_role = new_role.value
        return True


def set_contact_attended(event_id: str, contact_id: str, attended: bool) -> bool:
    with get_session() as sess:
        row = sess.query(ContactRow).filter(
            ContactRow.event_id == event_id, ContactRow.id == contact_id
        ).first()
        if row is None:
            return False
        row.attended = bool(attended)
        return True


def update_contacts_status_batch(
    event_id: str,
    contact_ids: list[str],
    status: ContactStatus,
) -> int:
    """Set status for multiple contacts. Returns count updated."""
    if not contact_ids:
        return 0
    with get_session() as sess:
        rows = sess.query(ContactRow).filter(
            ContactRow.event_id == event_id, ContactRow.id.in_(contact_ids)
        ).all()
        for r in rows:
            r.status = status.value
        return len(rows)


def set_event_permissions(event_id: str, permissions: list[dict[str, str]]) -> bool:
    cleaned = [
        {"user_id": p["user_id"], "role": p["role"].lower()}
        for p in permissions
        if p.get("role", "").lower() in ("editor", "viewer") and p.get("user_id")
    ]
    with get_session() as sess:
        event = sess.get(EventRow, event_id)
        if event is None:
            return False
        sess.query(EventShareRow).filter(EventShareRow.event_id == event_id).delete()
        for p in cleaned:
            sess.add(EventShareRow(event_id=event_id, user_id=p["user_id"], role=p["role"]))
        return True


def add_event_share(event_id: str, user_id: str, role: str) -> bool:
    role = role.lower()
    if role not in ("editor", "viewer"):
        return False
    with get_session() as sess:
        event = sess.get(EventRow, event_id)
        if event is None:
            return False
        if event.owner_id == user_id:
            return False
        existing = sess.query(EventShareRow).filter(
            EventShareRow.event_id == event_id, EventShareRow.user_id == user_id
        ).first()
        if existing is not None:
            existing.role = role
        else:
            sess.add(EventShareRow(event_id=event_id, user_id=user_id, role=role))
        return True


def remove_event_share(event_id: str, user_id: str) -> bool:
    with get_session() as sess:
        rows = sess.query(EventShareRow).filter(
            EventShareRow.event_id == event_id, EventShareRow.user_id == user_id
        ).all()
        for r in rows:
            sess.delete(r)
        return True


def add_contacts_bulk(
    event_id: str,
    rows: list[tuple[str, str]],
    contact_role: ContactRole = ContactRole.ATTENDEE,
    registration_type: RegistrationType = RegistrationType.PRE_REGISTERED,
) -> int:
    """Add contacts (name, email) skipping duplicates by email. Returns count added."""
    now = utc_now_iso()
    with get_session() as sess:
        event = sess.get(EventRow, event_id)
        if event is None:
            return 0
        existing_emails = {c.email.lower() for c in event.contacts if c.email}
        added = 0
        for name, email in rows:
            em = (email or "").strip().lower()
            if not em or em in existing_emails:
                continue
            sess.add(
                ContactRow(
                    id=new_id(),
                    event_id=event_id,
                    name=(name or "").strip(),
                    email=email.strip(),
                    status=ContactStatus.NOT_CONTACTED.value,
                    attended=False,
                    contact_role=contact_role.value if hasattr(contact_role, "value") else str(contact_role),
                    registration_type=registration_type.value if hasattr(registration_type, "value") else str(registration_type),
                    registered_at=now,
                )
            )
            existing_emails.add(em)
            added += 1
        return added


def compute_metrics(event: Event) -> dict:
    """Counts and rates for dashboard, including capacity and walk-in stats."""
    contacts = event.contacts
    total = len(contacts)
    rsvp_count = sum(
        1
        for c in contacts
        if c.status in (ContactStatus.RESPONDED, ContactStatus.CONFIRMED)
    )
    confirmed = sum(1 for c in contacts if c.status == ContactStatus.CONFIRMED)
    declined = sum(1 for c in contacts if c.status == ContactStatus.DECLINED)
    attended = sum(1 for c in contacts if c.attended)
    rsvp_rate = (rsvp_count / total * 100) if total else 0.0
    attendance_rate = (attended / total * 100) if total else 0.0

    pre_registered_count = sum(
        1 for c in contacts
        if c.registration_type == RegistrationType.PRE_REGISTERED
    )
    day_of_count = sum(
        1 for c in contacts
        if c.registration_type == RegistrationType.DAY_OF
    )
    walkin_count = sum(
        1 for c in contacts
        if c.registration_type == RegistrationType.WALK_IN
    )

    cap = event.venue_capacity
    buf_pct = event.walkin_buffer_pct
    buffer_slots = int(cap * buf_pct / 100) if cap else 0
    planned_total = cap + buffer_slots if cap else 0
    buffer_used = walkin_count + day_of_count
    buffer_remaining = max(buffer_slots - buffer_used, 0) if cap else 0
    capacity_pct = round(confirmed / cap * 100, 1) if cap else 0.0

    now = datetime.now(timezone.utc)
    deadline_passed = False
    registration_open = True
    if event.registration_deadline:
        try:
            dl = datetime.fromisoformat(event.registration_deadline.replace("Z", "+00:00"))
            if dl.tzinfo is None:
                dl = dl.replace(tzinfo=timezone.utc)
            deadline_passed = now >= dl
        except ValueError:
            pass
    registration_open = not deadline_passed

    return {
        "total_invited": total,
        "rsvp_count": rsvp_count,
        "confirmed": confirmed,
        "declined": declined,
        "attended": attended,
        "rsvp_rate": round(rsvp_rate, 1),
        "attendance_rate": round(attendance_rate, 1),
        "pre_registered_count": pre_registered_count,
        "day_of_count": day_of_count,
        "walkin_count": walkin_count,
        "venue_capacity": cap,
        "walkin_buffer_pct": buf_pct,
        "buffer_slots": buffer_slots,
        "planned_total": planned_total,
        "buffer_used": buffer_used,
        "buffer_remaining": buffer_remaining,
        "capacity_pct": capacity_pct,
        "deadline_passed": deadline_passed,
        "registration_open": registration_open,
    }


def compute_priority(event: Event) -> dict:
    """Compute priority score, urgency, size tier, and door status for an event."""
    now = datetime.now(timezone.utc)

    days_until = None
    is_tba = True
    is_past = False
    try:
        event_dt = datetime.fromisoformat(event.date.replace("Z", "+00:00"))
        if event_dt.tzinfo is None:
            event_dt = event_dt.replace(tzinfo=timezone.utc)
        days_until = (event_dt - now).days
        is_tba = False
        is_past = days_until < 0
    except (ValueError, AttributeError):
        pass

    size_ref = event.venue_capacity if event.venue_capacity > 0 else len(event.contacts)
    if size_ref >= 100:
        size_tier = "large"
    elif size_ref >= 30:
        size_tier = "medium"
    else:
        size_tier = "small"

    if is_tba:
        urgency = "tba"
    elif is_past:
        urgency = "past"
    elif days_until <= 2:
        urgency = "critical"
    elif days_until <= 7:
        urgency = "high"
    elif days_until <= 21:
        urgency = "medium"
    else:
        urgency = "low"

    if is_tba:
        time_score = 5
    elif is_past:
        time_score = 0
    elif days_until <= 2:
        time_score = 100
    elif days_until <= 7:
        time_score = 80 - (days_until - 2) * 4
    elif days_until <= 21:
        time_score = 55 - (days_until - 7) * 2
    else:
        time_score = max(25 - (days_until - 21), 0)

    size_bonus = {"large": 15, "medium": 8, "small": 0}[size_tier]
    priority_score = min(time_score + size_bonus, 100)

    deadline_passed = False
    registration_open = True
    if event.registration_deadline:
        try:
            dl = datetime.fromisoformat(event.registration_deadline.replace("Z", "+00:00"))
            if dl.tzinfo is None:
                dl = dl.replace(tzinfo=timezone.utc)
            deadline_passed = now >= dl
        except ValueError:
            pass
    registration_open = not deadline_passed

    cap = event.venue_capacity
    confirmed = sum(1 for c in event.contacts if c.status == ContactStatus.CONFIRMED)
    buf_pct = event.walkin_buffer_pct
    buffer_slots = int(cap * buf_pct / 100) if cap else 0
    total_capacity = cap + buffer_slots if cap else 0
    spots_remaining = total_capacity - confirmed if cap else -1

    if cap == 0:
        door_status = "open"
    elif spots_remaining > buffer_slots * 0.3:
        door_status = "open"
    elif spots_remaining > 0:
        door_status = "limited"
    elif spots_remaining == 0:
        door_status = "full"
    else:
        door_status = "over_capacity"

    return {
        "days_until": days_until,
        "is_past": is_past,
        "is_tba": is_tba,
        "size_tier": size_tier,
        "urgency": urgency,
        "priority_score": priority_score,
        "deadline_passed": deadline_passed,
        "registration_open": registration_open,
        "door_status": door_status,
        "spots_remaining": spots_remaining,
    }
