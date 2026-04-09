"""Data models for SOM Event Operating System."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid


def normalize_phone(raw: str) -> str:
    """Accept any phone format and normalize to +1XXXXXXXXXX (US) or +<digits>."""
    if not raw:
        return ""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    if raw.strip().startswith("+"):
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return "+" + digits


class ContactStatus(str, Enum):
    NOT_CONTACTED = "not_contacted"
    CONTACTED = "contacted"
    RESPONDED = "responded"
    CONFIRMED = "confirmed"
    DECLINED = "declined"


class EmailType(str, Enum):
    INITIAL = "initial"
    FOLLOW_UP = "follow_up"


class ContactRole(str, Enum):
    SPEAKER = "speaker"
    PANELIST = "panelist"
    MODERATOR = "moderator"
    JUDGE = "judge"
    SPONSOR = "sponsor"
    FACULTY = "faculty"
    ORGANIZER = "organizer"
    STAFF = "staff"
    ATTENDEE = "attendee"


class EventShareRole(str, Enum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


@dataclass
class User:
    id: str
    username: str
    display_name: str
    email: str
    password_hash: str
    role: str = "user"  # "admin" or "user"
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "email": self.email,
            "password_hash": self.password_hash,
            "role": self.role,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> User:
        return cls(
            id=d["id"],
            username=d["username"],
            display_name=d.get("display_name", d["username"]),
            email=d.get("email", ""),
            password_hash=d["password_hash"],
            role=d.get("role", "user"),
            created_at=d.get("created_at", ""),
        )


@dataclass
class Person:
    id: str
    name: str
    email: str
    company: str = ""
    role: str = ""
    linkedin_url: str = ""
    phone: str = ""
    tags: list[str] = field(default_factory=list)
    source: str = ""
    referred_by: str = ""
    notes: str = ""
    added_at: str = ""
    events_participated: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "company": self.company,
            "role": self.role,
            "linkedin_url": self.linkedin_url,
            "phone": self.phone,
            "tags": self.tags,
            "source": self.source,
            "referred_by": self.referred_by,
            "notes": self.notes,
            "added_at": self.added_at,
            "events_participated": self.events_participated,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Person:
        return cls(
            id=d["id"],
            name=d["name"],
            email=d.get("email", ""),
            company=d.get("company", ""),
            role=d.get("role", ""),
            linkedin_url=d.get("linkedin_url", ""),
            phone=d.get("phone", ""),
            tags=list(d.get("tags", [])),
            source=d.get("source", ""),
            referred_by=d.get("referred_by", ""),
            notes=d.get("notes", ""),
            added_at=d.get("added_at", ""),
            events_participated=list(d.get("events_participated", [])),
        )


@dataclass
class Contact:
    id: str
    name: str
    email: str
    status: ContactStatus = ContactStatus.NOT_CONTACTED
    attended: bool = False
    contact_role: ContactRole = ContactRole.ATTENDEE
    phone: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "status": self.status.value,
            "attended": self.attended,
            "contact_role": self.contact_role.value,
            "phone": self.phone,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Contact:
        return cls(
            id=d["id"],
            name=d["name"],
            email=d["email"],
            status=ContactStatus(d.get("status", "not_contacted")),
            attended=bool(d.get("attended", False)),
            contact_role=ContactRole(d.get("contact_role", "attendee")),
            phone=d.get("phone", ""),
        )


@dataclass
class Event:
    id: str
    name: str
    date: str
    description: str
    audience_type: str
    contacts: list[Contact] = field(default_factory=list)
    som_event_id: str = ""
    owner_id: str = ""
    permissions: list[dict[str, str]] = field(default_factory=list)
    sender_name: str = ""
    sender_title: str = ""
    sender_email: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {
            "id": self.id,
            "name": self.name,
            "date": self.date,
            "description": self.description,
            "audience_type": self.audience_type,
            "contacts": [c.to_dict() for c in self.contacts],
            "owner_id": self.owner_id,
            "permissions": self.permissions,
        }
        if self.som_event_id:
            d["som_event_id"] = self.som_event_id
        if self.sender_name:
            d["sender_name"] = self.sender_name
        if self.sender_title:
            d["sender_title"] = self.sender_title
        if self.sender_email:
            d["sender_email"] = self.sender_email
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Event:
        contacts = [Contact.from_dict(c) for c in d.get("contacts", [])]
        perms = d.get("permissions") or []
        if not isinstance(perms, list):
            perms = []
        return cls(
            id=d["id"],
            name=d["name"],
            date=d["date"],
            description=d.get("description", ""),
            audience_type=d.get("audience_type", ""),
            contacts=contacts,
            som_event_id=d.get("som_event_id", ""),
            owner_id=d.get("owner_id", ""),
            permissions=[p for p in perms if isinstance(p, dict) and "user_id" in p and "role" in p],
            sender_name=d.get("sender_name", ""),
            sender_title=d.get("sender_title", ""),
            sender_email=d.get("sender_email", ""),
        )


@dataclass
class OutreachLog:
    id: str
    event_id: str
    contact_id: str
    contact_name: str
    email_type: EmailType
    email_body: str
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_id": self.event_id,
            "contact_id": self.contact_id,
            "contact_name": self.contact_name,
            "email_type": self.email_type.value,
            "email_body": self.email_body,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OutreachLog:
        return cls(
            id=d["id"],
            event_id=d["event_id"],
            contact_id=d["contact_id"],
            contact_name=d["contact_name"],
            email_type=EmailType(d.get("email_type", "initial")),
            email_body=d.get("email_body", ""),
            timestamp=d.get("timestamp", ""),
        )


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
