"""JSON-backed CRUD for events and contacts."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from models import (
    Contact, ContactRole, ContactStatus, Event, RegistrationType,
    new_id, utc_now_iso,
)

if TYPE_CHECKING:
    from models import User

DATA_DIR = Path(__file__).resolve().parent / "data"
EVENTS_FILE = DATA_DIR / "events.json"


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def migrate_legacy_event_ownership(admin_user_id: str) -> None:
    """Assign owner_id to events missing it (one-time migration)."""
    _ensure_data_dir()
    if not EVENTS_FILE.exists():
        return
    with open(EVENTS_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        return
    changed = False
    for item in raw:
        if isinstance(item, dict) and not item.get("owner_id"):
            item["owner_id"] = admin_user_id
            if "permissions" not in item:
                item["permissions"] = []
            changed = True
    if changed:
        with open(EVENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)


def load_events() -> list[Event]:
    _ensure_data_dir()
    if not EVENTS_FILE.exists():
        return []
    with open(EVENTS_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        return []
    return [Event.from_dict(item) for item in raw]


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
    visible = []
    for e in events:
        if get_event_share_role(user, e) is not None:
            visible.append(e)
    return visible


def save_events(events: list[Event]) -> None:
    _ensure_data_dir()
    payload = [e.to_dict() for e in events]
    with open(EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def get_event(event_id: str) -> Event | None:
    for e in load_events():
        if e.id == event_id:
            return e
    return None


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
    events = load_events()
    event = Event(
        id=new_id(),
        name=name.strip(),
        date=date.strip(),
        description=description.strip(),
        audience_type=audience_type.strip(),
        contacts=[],
        owner_id=owner_id.strip(),
        permissions=[],
        sender_name=sender_name.strip(),
        sender_title=sender_title.strip(),
        sender_email=sender_email.strip(),
        venue_capacity=venue_capacity,
        walkin_buffer_pct=walkin_buffer_pct,
        registration_deadline=registration_deadline.strip() if registration_deadline else "",
        late_fee=late_fee,
        late_fee_note=late_fee_note.strip() if late_fee_note else "",
        goal_registrations=kwargs.get("goal_registrations", 0),
        goal_attendance=kwargs.get("goal_attendance", 0),
        goal_sponsorship=kwargs.get("goal_sponsorship", 0.0),
        goal_budget=kwargs.get("goal_budget", 0.0),
        custom_goals=kwargs.get("custom_goals", []),
        planned_budget=kwargs.get("planned_budget", 0.0),
        actual_spend=kwargs.get("actual_spend", 0.0),
        sponsorship_revenue=kwargs.get("sponsorship_revenue", 0.0),
        expenses=kwargs.get("expenses", []),
        registration_pin=kwargs.get("registration_pin", ""),
    )
    events.append(event)
    save_events(events)
    return event


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
    events = load_events()
    for i, e in enumerate(events):
        if e.id == event_id:
            e.name = name.strip()
            e.date = date.strip()
            e.description = description.strip()
            e.audience_type = audience_type.strip()
            e.sender_name = sender_name.strip()
            e.sender_title = sender_title.strip()
            e.sender_email = sender_email.strip()
            e.venue_capacity = venue_capacity
            e.walkin_buffer_pct = walkin_buffer_pct
            e.registration_deadline = registration_deadline.strip() if registration_deadline else ""
            e.late_fee = late_fee
            e.late_fee_note = late_fee_note.strip() if late_fee_note else ""
            e.goal_registrations = kwargs.get("goal_registrations", e.goal_registrations)
            e.goal_attendance = kwargs.get("goal_attendance", e.goal_attendance)
            e.goal_sponsorship = kwargs.get("goal_sponsorship", e.goal_sponsorship)
            e.goal_budget = kwargs.get("goal_budget", e.goal_budget)
            e.custom_goals = kwargs.get("custom_goals", e.custom_goals)
            e.planned_budget = kwargs.get("planned_budget", e.planned_budget)
            e.actual_spend = kwargs.get("actual_spend", e.actual_spend)
            e.sponsorship_revenue = kwargs.get("sponsorship_revenue", e.sponsorship_revenue)
            e.expenses = kwargs.get("expenses", e.expenses)
            e.registration_pin = kwargs.get("registration_pin", e.registration_pin)
            events[i] = e
            save_events(events)
            return True
    return False


def delete_event(event_id: str) -> bool:
    events = load_events()
    filtered = [e for e in events if e.id != event_id]
    if len(filtered) == len(events):
        return False
    save_events(filtered)
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
    events = load_events()
    for i, e in enumerate(events):
        if e.id == event_id:
            contact = Contact(
                id=new_id(),
                name=name.strip(),
                email=email.strip(),
                status=status,
                attended=attended,
                contact_role=contact_role,
                phone=phone.strip(),
                registration_type=registration_type,
                registered_at=utc_now_iso(),
            )
            e.contacts.append(contact)
            events[i] = e
            save_events(events)
            return contact
    return None


def delete_contact(event_id: str, contact_id: str) -> bool:
    events = load_events()
    for i, e in enumerate(events):
        if e.id != event_id:
            continue
        before = len(e.contacts)
        e.contacts = [c for c in e.contacts if c.id != contact_id]
        if len(e.contacts) < before:
            events[i] = e
            save_events(events)
            return True
    return False


def update_contact_details(
    event_id: str, contact_id: str,
    name: str = "", email: str = "", phone: str = "",
) -> bool:
    events = load_events()
    for i, e in enumerate(events):
        if e.id != event_id:
            continue
        for j, c in enumerate(e.contacts):
            if c.id == contact_id:
                if name:
                    c.name = name.strip()
                if email:
                    c.email = email.strip()
                c.phone = phone.strip() if phone is not None else c.phone
                e.contacts[j] = c
                events[i] = e
                save_events(events)
                return True
    return False


def update_contact_status(event_id: str, contact_id: str, status: str) -> bool:
    try:
        new_status = ContactStatus(status)
    except ValueError:
        return False
    events = load_events()
    for i, e in enumerate(events):
        if e.id != event_id:
            continue
        for j, c in enumerate(e.contacts):
            if c.id == contact_id:
                c.status = new_status
                e.contacts[j] = c
                events[i] = e
                save_events(events)
                return True
    return False


def update_contact_role(event_id: str, contact_id: str, role: str) -> bool:
    try:
        new_role = ContactRole(role)
    except ValueError:
        return False
    events = load_events()
    for i, e in enumerate(events):
        if e.id != event_id:
            continue
        for j, c in enumerate(e.contacts):
            if c.id == contact_id:
                c.contact_role = new_role
                e.contacts[j] = c
                events[i] = e
                save_events(events)
                return True
    return False


def set_contact_attended(event_id: str, contact_id: str, attended: bool) -> bool:
    events = load_events()
    for i, e in enumerate(events):
        if e.id != event_id:
            continue
        for j, c in enumerate(e.contacts):
            if c.id == contact_id:
                c.attended = attended
                e.contacts[j] = c
                events[i] = e
                save_events(events)
                return True
    return False


def update_contacts_status_batch(
    event_id: str,
    contact_ids: list[str],
    status: ContactStatus,
) -> int:
    """Set status for multiple contacts. Returns count updated."""
    events = load_events()
    updated = 0
    for i, e in enumerate(events):
        if e.id != event_id:
            continue
        for j, c in enumerate(e.contacts):
            if c.id in contact_ids:
                c.status = status
                e.contacts[j] = c
                updated += 1
        events[i] = e
        break
    if updated:
        save_events(events)
    return updated


def set_event_permissions(event_id: str, permissions: list[dict[str, str]]) -> bool:
    events = load_events()
    for i, e in enumerate(events):
        if e.id == event_id:
            e.permissions = [
                {"user_id": p["user_id"], "role": p["role"].lower()}
                for p in permissions
                if p.get("role", "").lower() in ("editor", "viewer")
            ]
            events[i] = e
            save_events(events)
            return True
    return False


def add_event_share(event_id: str, user_id: str, role: str) -> bool:
    role = role.lower()
    if role not in ("editor", "viewer"):
        return False
    events = load_events()
    for i, e in enumerate(events):
        if e.id != event_id:
            continue
        if e.owner_id == user_id:
            return False
        perms = [p for p in e.permissions if p.get("user_id") != user_id]
        perms.append({"user_id": user_id, "role": role})
        e.permissions = perms
        events[i] = e
        save_events(events)
        return True
    return False


def remove_event_share(event_id: str, user_id: str) -> bool:
    events = load_events()
    for i, e in enumerate(events):
        if e.id != event_id:
            continue
        e.permissions = [p for p in e.permissions if p.get("user_id") != user_id]
        events[i] = e
        save_events(events)
        return True
    return False


def add_contacts_bulk(
    event_id: str,
    rows: list[tuple[str, str]],
    contact_role: ContactRole = ContactRole.ATTENDEE,
    registration_type: RegistrationType = RegistrationType.PRE_REGISTERED,
) -> int:
    """Add contacts (name, email) skipping duplicates by email. Returns count added."""
    now = utc_now_iso()
    events = load_events()
    added = 0
    for i, e in enumerate(events):
        if e.id != event_id:
            continue
        existing_emails = {c.email.lower() for c in e.contacts}
        for name, email in rows:
            em = email.strip().lower()
            if not em or em in existing_emails:
                continue
            e.contacts.append(
                Contact(
                    id=new_id(),
                    name=name.strip(),
                    email=email.strip(),
                    status=ContactStatus.NOT_CONTACTED,
                    attended=False,
                    contact_role=contact_role,
                    registration_type=registration_type,
                    registered_at=now,
                )
            )
            existing_emails.add(em)
            added += 1
        events[i] = e
        break
    if added:
        save_events(events)
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

    # --- Days until event ---
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

    # --- Size tier ---
    size_ref = event.venue_capacity if event.venue_capacity > 0 else len(event.contacts)
    if size_ref >= 100:
        size_tier = "large"
    elif size_ref >= 30:
        size_tier = "medium"
    else:
        size_tier = "small"

    # --- Urgency ---
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

    # --- Priority score (0-100, higher = more urgent) ---
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

    # --- Deadline status ---
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

    # --- Door status ---
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
