"""One-shot migration from data/*.json into the Postgres/SQLite database.

Idempotent: re-running skips rows that already exist by primary key.

Usage:
    python -m scripts.migrate_json_to_db
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root is on sys.path when run as `python scripts/migrate_json_to_db.py`
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import get_session, init_db  # noqa: E402
from db_models import (  # noqa: E402
    Contact as ContactRow,
    Event as EventRow,
    EventShare as EventShareRow,
    FeedbackEntry as FeedbackRow,
    OutreachLog as OutreachLogRow,
    Person as PersonRow,
    User as UserRow,
)
from models import utc_now_iso  # noqa: E402
from org_manager import DEFAULT_ORG_ID, ensure_default_org  # noqa: E402


DATA_DIR = ROOT / "data"


def _load_json(name: str):
    path = DATA_DIR / name
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        print(f"  ! {name} is corrupt ({exc}); skipping.")
        return None


def migrate_users() -> int:
    raw = _load_json("users.json")
    if not isinstance(raw, list):
        return 0
    added = 0
    with get_session() as sess:
        for item in raw:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            if sess.get(UserRow, item["id"]) is not None:
                continue
            sess.add(UserRow(
                id=item["id"],
                org_id=DEFAULT_ORG_ID,
                username=item.get("username", ""),
                display_name=item.get("display_name", item.get("username", "")),
                email=item.get("email", ""),
                password_hash=item.get("password_hash", ""),
                role=item.get("role", "user"),
            ))
            added += 1
    return added


def migrate_people() -> int:
    raw = _load_json("people.json")
    if not isinstance(raw, list):
        return 0
    added = 0
    with get_session() as sess:
        for item in raw:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            if sess.get(PersonRow, item["id"]) is not None:
                continue
            sess.add(PersonRow(
                id=item["id"],
                org_id=DEFAULT_ORG_ID,
                name=item.get("name", ""),
                email=item.get("email", ""),
                company=item.get("company", ""),
                role=item.get("role", ""),
                linkedin_url=item.get("linkedin_url", ""),
                phone=item.get("phone", ""),
                tags=list(item.get("tags", []) or []),
                source=item.get("source", ""),
                referred_by=item.get("referred_by", ""),
                notes=item.get("notes", ""),
                added_at=item.get("added_at", ""),
                events_participated=list(item.get("events_participated", []) or []),
            ))
            added += 1
    return added


def migrate_events() -> tuple[int, int, int]:
    raw = _load_json("events.json")
    if not isinstance(raw, list):
        return 0, 0, 0
    events_added = 0
    contacts_added = 0
    shares_added = 0
    with get_session() as sess:
        for item in raw:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            existing = sess.get(EventRow, item["id"])
            if existing is not None:
                continue
            erow = EventRow(
                id=item["id"],
                org_id=DEFAULT_ORG_ID,
                name=item.get("name", ""),
                date=item.get("date", ""),
                description=item.get("description", ""),
                audience_type=item.get("audience_type", ""),
                som_event_id=item.get("som_event_id", ""),
                owner_id=item.get("owner_id", ""),
                sender_name=item.get("sender_name", ""),
                sender_title=item.get("sender_title", ""),
                sender_email=item.get("sender_email", ""),
                venue_capacity=int(item.get("venue_capacity", 0) or 0),
                walkin_buffer_pct=int(item.get("walkin_buffer_pct", 15) or 15),
                registration_deadline=item.get("registration_deadline", ""),
                late_fee=float(item.get("late_fee", 0.0) or 0.0),
                late_fee_note=item.get("late_fee_note", ""),
                goal_registrations=int(item.get("goal_registrations", 0) or 0),
                goal_attendance=int(item.get("goal_attendance", 0) or 0),
                goal_sponsorship=float(item.get("goal_sponsorship", 0.0) or 0.0),
                goal_budget=float(item.get("goal_budget", 0.0) or 0.0),
                custom_goals=list(item.get("custom_goals", []) or []),
                planned_budget=float(item.get("planned_budget", 0.0) or 0.0),
                actual_spend=float(item.get("actual_spend", 0.0) or 0.0),
                sponsorship_revenue=float(item.get("sponsorship_revenue", 0.0) or 0.0),
                expenses=list(item.get("expenses", []) or []),
                registration_pin=item.get("registration_pin", ""),
            )
            sess.add(erow)
            events_added += 1

            for c in item.get("contacts", []) or []:
                if not isinstance(c, dict) or not c.get("id"):
                    continue
                sess.add(ContactRow(
                    id=c["id"],
                    event_id=item["id"],
                    name=c.get("name", ""),
                    email=c.get("email", ""),
                    status=c.get("status", "not_contacted"),
                    attended=bool(c.get("attended", False)),
                    contact_role=c.get("contact_role", "attendee"),
                    phone=c.get("phone", ""),
                    registration_type=c.get("registration_type", "pre_registered"),
                    registered_at=c.get("registered_at", ""),
                ))
                contacts_added += 1

            for p in item.get("permissions", []) or []:
                if not isinstance(p, dict) or not p.get("user_id"):
                    continue
                sess.add(EventShareRow(
                    event_id=item["id"],
                    user_id=p["user_id"],
                    role=(p.get("role") or "viewer").lower(),
                ))
                shares_added += 1
    return events_added, contacts_added, shares_added


def migrate_outreach_logs() -> tuple[int, int]:
    raw = _load_json("outreach_log.json")
    if not isinstance(raw, list):
        return 0, 0
    added = 0
    skipped_orphans = 0
    with get_session() as sess:
        valid_event_ids = {r[0] for r in sess.query(EventRow.id).all()}
        for item in raw:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            event_id = item.get("event_id", "")
            if event_id not in valid_event_ids:
                skipped_orphans += 1
                continue
            if sess.get(OutreachLogRow, item["id"]) is not None:
                continue
            sess.add(OutreachLogRow(
                id=item["id"],
                event_id=event_id,
                contact_id=item.get("contact_id", ""),
                contact_name=item.get("contact_name", ""),
                email_type=item.get("email_type", "initial"),
                email_body=item.get("email_body", ""),
                timestamp=item.get("timestamp", ""),
            ))
            added += 1
    return added, skipped_orphans


def migrate_feedback() -> tuple[int, int]:
    raw = _load_json("feedback.json")
    if not isinstance(raw, list):
        return 0, 0
    added = 0
    skipped_orphans = 0
    with get_session() as sess:
        valid_event_ids = {r[0] for r in sess.query(EventRow.id).all()}
        for item in raw:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            event_id = item.get("event_id", "")
            if event_id not in valid_event_ids:
                skipped_orphans += 1
                continue
            if sess.get(FeedbackRow, item["id"]) is not None:
                continue
            sess.add(FeedbackRow(
                id=item["id"],
                event_id=event_id,
                respondent_name=item.get("respondent_name", ""),
                respondent_email=item.get("respondent_email", ""),
                rating=int(item.get("rating", 5) or 5),
                liked=item.get("liked", ""),
                improve=item.get("improve", ""),
                would_attend_again=bool(item.get("would_attend_again", True)),
                submitted_at=item.get("submitted_at", utc_now_iso()),
            ))
            added += 1
    return added, skipped_orphans


def run() -> None:
    print("Initializing database schema...")
    init_db()
    ensure_default_org()
    print(f"Default organization: {DEFAULT_ORG_ID}")

    print("\nMigrating users...")
    print(f"  +{migrate_users()} users")
    print("Migrating people...")
    print(f"  +{migrate_people()} people")
    print("Migrating events + contacts + shares...")
    ev, ct, sh = migrate_events()
    print(f"  +{ev} events, +{ct} contacts, +{sh} shares")
    print("Migrating outreach logs...")
    ol_added, ol_orphans = migrate_outreach_logs()
    print(f"  +{ol_added} log entries ({ol_orphans} orphans skipped)")
    print("Migrating feedback...")
    fb_added, fb_orphans = migrate_feedback()
    print(f"  +{fb_added} feedback entries ({fb_orphans} orphans skipped)")
    print("\nDone.")


if __name__ == "__main__":
    run()
