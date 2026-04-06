"""Central People directory (JSON-backed)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from models import Person, new_id, utc_now_iso

DATA_DIR = Path(__file__).resolve().parent / "data"
PEOPLE_FILE = DATA_DIR / "people.json"


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_people() -> list[Person]:
    _ensure_data_dir()
    if not PEOPLE_FILE.exists():
        return []
    with open(PEOPLE_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        return []
    return [Person.from_dict(p) for p in raw]


def save_people(people: list[Person]) -> None:
    _ensure_data_dir()
    with open(PEOPLE_FILE, "w", encoding="utf-8") as f:
        json.dump([p.to_dict() for p in people], f, indent=2, ensure_ascii=False)


def get_person(person_id: str) -> Person | None:
    for p in load_people():
        if p.id == person_id:
            return p
    return None


def find_by_email(email: str) -> Person | None:
    em = email.strip().lower()
    for p in load_people():
        if p.email.lower() == em:
            return p
    return None


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
    if not email.strip():
        return None
    if find_by_email(email):
        return None
    person = Person(
        id=new_id(),
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
    )
    people = load_people()
    people.append(person)
    save_people(people)
    return person


def update_person(person_id: str, **kwargs) -> bool:
    people = load_people()
    for i, p in enumerate(people):
        if p.id != person_id:
            continue
        for k, v in kwargs.items():
            if hasattr(p, k) and v is not None:
                setattr(p, k, v)
        people[i] = p
        save_people(people)
        return True
    return False


def delete_person(person_id: str) -> bool:
    people = load_people()
    filtered = [p for p in people if p.id != person_id]
    if len(filtered) == len(people):
        return False
    save_people(filtered)
    return True


def append_event_to_person(person_id: str, event_id: str) -> None:
    people = load_people()
    for i, p in enumerate(people):
        if p.id == person_id:
            if event_id not in p.events_participated:
                p.events_participated.append(event_id)
            people[i] = p
            save_people(people)
            return


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
