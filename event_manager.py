"""JSON-backed CRUD for events and contacts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from models import Contact, ContactRole, ContactStatus, Event, new_id

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
    )
    events.append(event)
    save_events(events)
    return event


def update_event(event_id: str, name: str, date: str, description: str, audience_type: str) -> bool:
    events = load_events()
    for i, e in enumerate(events):
        if e.id == event_id:
            e.name = name.strip()
            e.date = date.strip()
            e.description = description.strip()
            e.audience_type = audience_type.strip()
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
) -> Contact | None:
    events = load_events()
    for i, e in enumerate(events):
        if e.id == event_id:
            contact = Contact(
                id=new_id(),
                name=name.strip(),
                email=email.strip(),
                status=ContactStatus.NOT_CONTACTED,
                attended=False,
                contact_role=contact_role,
                phone=phone.strip(),
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
) -> int:
    """Add contacts (name, email) skipping duplicates by email. Returns count added."""
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
    """Counts and rates for dashboard."""
    contacts = event.contacts
    total = len(contacts)
    # RSVPs: responded or confirmed (they engaged with RSVP flow)
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
    return {
        "total_invited": total,
        "rsvp_count": rsvp_count,
        "confirmed": confirmed,
        "declined": declined,
        "attended": attended,
        "rsvp_rate": round(rsvp_rate, 1),
        "attendance_rate": round(attendance_rate, 1),
    }
