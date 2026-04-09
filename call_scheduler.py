"""JSON-backed call schedule persistence."""
from __future__ import annotations

import json
from pathlib import Path

from models import new_id, utc_now_iso

DATA_DIR = Path(__file__).resolve().parent / "data"
SCHEDULE_FILE = DATA_DIR / "call_schedule.json"


def _ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_schedule() -> list[dict]:
    _ensure()
    if not SCHEDULE_FILE.exists():
        return []
    with open(SCHEDULE_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def save_schedule(items: list[dict]) -> None:
    _ensure()
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def add_scheduled_call(
    event_id: str,
    contact_id: str,
    contact_name: str,
    call_type: str,
    scheduled_at: str,
    suggested_by: str = "ai",
) -> dict:
    items = load_schedule()
    entry = {
        "id": new_id(),
        "event_id": event_id,
        "contact_id": contact_id,
        "contact_name": contact_name,
        "call_type": call_type,
        "scheduled_at": scheduled_at,
        "status": "pending",
        "suggested_by": suggested_by,
        "created_at": utc_now_iso(),
        "call_id": "",
        "result": "",
    }
    items.append(entry)
    save_schedule(items)
    return entry


def get_pending_due(now_iso: str) -> list[dict]:
    return [
        s for s in load_schedule()
        if s.get("status") == "pending" and s.get("scheduled_at", "z") <= now_iso
    ]


def update_status(schedule_id: str, status: str, call_id: str = "", result: str = "") -> bool:
    items = load_schedule()
    for item in items:
        if item["id"] == schedule_id:
            item["status"] = status
            if call_id:
                item["call_id"] = call_id
            if result:
                item["result"] = result
            save_schedule(items)
            return True
    return False


def already_scheduled(event_id: str, contact_id: str, call_type: str) -> bool:
    return any(
        s["event_id"] == event_id
        and s["contact_id"] == contact_id
        and s["call_type"] == call_type
        and s["status"] == "pending"
        for s in load_schedule()
    )


def get_schedule_for_event(event_id: str) -> list[dict]:
    return [s for s in load_schedule() if s["event_id"] == event_id]
