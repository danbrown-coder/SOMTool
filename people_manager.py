"""Central People directory (DB-backed)."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select

from db import get_session
from db_models import Person as PersonRow
from models import Person, new_id, utc_now_iso
from org_manager import DEFAULT_ORG_ID, ensure_default_org


def _row_to_dto(row: PersonRow) -> Person:
    return Person(
        id=row.id,
        name=row.name,
        email=row.email,
        company=row.company or "",
        role=row.role or "",
        linkedin_url=row.linkedin_url or "",
        phone=row.phone or "",
        tags=list(row.tags or []),
        source=row.source or "",
        referred_by=row.referred_by or "",
        notes=row.notes or "",
        added_at=row.added_at or "",
        events_participated=list(row.events_participated or []),
    )


def _apply_dto_to_row(row: PersonRow, p: Person) -> None:
    row.name = p.name
    row.email = p.email
    row.company = p.company or ""
    row.role = p.role or ""
    row.linkedin_url = p.linkedin_url or ""
    row.phone = p.phone or ""
    row.tags = list(p.tags or [])
    row.source = p.source or ""
    row.referred_by = p.referred_by or ""
    row.notes = p.notes or ""
    row.added_at = p.added_at or ""
    row.events_participated = list(p.events_participated or [])


def load_people() -> list[Person]:
    ensure_default_org()
    with get_session() as sess:
        rows = sess.execute(
            select(PersonRow).where(PersonRow.org_id == DEFAULT_ORG_ID).order_by(PersonRow.name)
        ).scalars().all()
        return [_row_to_dto(r) for r in rows]


def save_people(people: list[Person]) -> None:
    """Upsert each provided Person (does not delete missing ones; use delete_person)."""
    ensure_default_org()
    with get_session() as sess:
        for p in people:
            row = sess.get(PersonRow, p.id)
            if row is None:
                row = PersonRow(id=p.id, org_id=DEFAULT_ORG_ID)
                sess.add(row)
            _apply_dto_to_row(row, p)


def get_person(person_id: str) -> Person | None:
    with get_session() as sess:
        row = sess.get(PersonRow, person_id)
        return _row_to_dto(row) if row else None


def find_by_email(email: str) -> Person | None:
    em = (email or "").strip().lower()
    if not em:
        return None
    with get_session() as sess:
        row = sess.query(PersonRow).filter(
            PersonRow.org_id == DEFAULT_ORG_ID,
            PersonRow.email.ilike(em),
        ).first()
        return _row_to_dto(row) if row else None


def add_person(
    name: str,
    email: str,
    company: str = "",
    role: str = "",
    linkedin_url: str = "",
    tags: list[str] | None = None,
    source: str = "manual",
    referred_by: str = "",
    notes: str = "",
) -> Person | None:
    if not (email or "").strip():
        return None
    if find_by_email(email):
        return None
    ensure_default_org()
    pid = new_id()
    with get_session() as sess:
        sess.add(PersonRow(
            id=pid,
            org_id=DEFAULT_ORG_ID,
            name=name.strip(),
            email=email.strip(),
            company=company.strip(),
            role=role.strip(),
            linkedin_url=linkedin_url.strip(),
            tags=list(tags or []),
            source=source,
            referred_by=referred_by,
            notes=notes.strip(),
            added_at=utc_now_iso(),
            events_participated=[],
        ))
    return get_person(pid)


def update_person(person_id: str, **kwargs) -> bool:
    # Accept: name, email, company, role, linkedin_url, phone, tags, source,
    # referred_by, notes, events_participated, enriched_at, enrichment_source
    with get_session() as sess:
        row = sess.get(PersonRow, person_id)
        if row is None:
            return False
        for k, v in kwargs.items():
            if v is None:
                continue
            if not hasattr(row, k):
                continue
            setattr(row, k, v)
        return True


def delete_person(person_id: str) -> bool:
    with get_session() as sess:
        row = sess.get(PersonRow, person_id)
        if row is None:
            return False
        sess.delete(row)
        return True


def append_event_to_person(person_id: str, event_id: str) -> None:
    with get_session() as sess:
        row = sess.get(PersonRow, person_id)
        if row is None:
            return
        events = list(row.events_participated or [])
        if event_id not in events:
            events.append(event_id)
            row.events_participated = events


def search_people(q: str, tag: str | None = None) -> list[Person]:
    people = load_people()
    if tag:
        tag_l = tag.lower()
        people = [p for p in people if any(t.lower() == tag_l for t in p.tags)]
    if not q.strip():
        return sorted(people, key=lambda x: x.name.lower())
    ql = q.lower()
    out = []
    for p in people:
        blob = " ".join(
            [p.name, p.email, p.company, p.role, " ".join(p.tags), p.notes]
        ).lower()
        if ql in blob:
            out.append(p)
    return sorted(out, key=lambda x: x.name.lower())


def import_people_rows(
    rows: list[dict[str, str]],
    default_tags: list[str] | None = None,
    skip_duplicates: bool = True,
) -> tuple[int, int]:
    """Returns (added, skipped). Each row: name, email, company?, role?, tags?"""
    added = 0
    skipped = 0
    tags_base = default_tags or []
    for row in rows:
        email = (row.get("email") or "").strip()
        name = (row.get("name") or "").strip()
        if not email or not name:
            skipped += 1
            continue
        if skip_duplicates and find_by_email(email):
            skipped += 1
            continue
        row_tags = list(tags_base)
        extra = row.get("tags") or ""
        if extra:
            row_tags.extend(t.strip() for t in re.split(r"[,;]", extra) if t.strip())
        add_person(
            name=name,
            email=email,
            company=row.get("company", "").strip(),
            role=row.get("role", "").strip(),
            tags=row_tags,
            source="csv_import",
        )
        added += 1
    return added, skipped


def all_tags() -> list[str]:
    seen: set[str] = set()
    for p in load_people():
        for t in p.tags:
            seen.add(t.lower())
    return sorted(seen)
