"""JSON-backed feedback store for event attendee surveys."""
from __future__ import annotations

import json
from pathlib import Path

from models import new_id, utc_now_iso

DATA_DIR = Path(__file__).resolve().parent / "data"
FEEDBACK_FILE = DATA_DIR / "feedback.json"


def _ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not FEEDBACK_FILE.exists():
        FEEDBACK_FILE.write_text("[]", encoding="utf-8")


def load_feedback() -> list[dict]:
    _ensure()
    with open(FEEDBACK_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _save(items: list[dict]) -> None:
    _ensure()
    with open(FEEDBACK_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def save_feedback(
    event_id: str,
    respondent_name: str,
    respondent_email: str,
    rating: int,
    liked: str,
    improve: str,
    would_attend_again: bool,
) -> dict:
    items = load_feedback()
    entry = {
        "id": new_id(),
        "event_id": event_id,
        "respondent_name": respondent_name,
        "respondent_email": respondent_email,
        "rating": max(1, min(5, rating)),
        "liked": liked.strip(),
        "improve": improve.strip(),
        "would_attend_again": would_attend_again,
        "submitted_at": utc_now_iso(),
    }
    items.append(entry)
    _save(items)
    return entry


def get_feedback(event_id: str) -> list[dict]:
    return [f for f in load_feedback() if f["event_id"] == event_id]


def get_all_feedback() -> list[dict]:
    return load_feedback()


def compute_feedback_summary(event_id: str) -> dict:
    entries = get_feedback(event_id)
    count = len(entries)
    if count == 0:
        return {
            "count": 0, "avg_rating": 0, "would_return_pct": 0,
            "top_liked": [], "top_improve": [], "entries": [],
        }

    avg_rating = round(sum(e["rating"] for e in entries) / count, 1)
    would_return = sum(1 for e in entries if e.get("would_attend_again"))
    would_return_pct = round(would_return / count * 100)

    liked_items = [e["liked"] for e in entries if e.get("liked")]
    improve_items = [e["improve"] for e in entries if e.get("improve")]

    return {
        "count": count,
        "avg_rating": avg_rating,
        "would_return_pct": would_return_pct,
        "top_liked": liked_items[:5],
        "top_improve": improve_items[:5],
        "entries": sorted(entries, key=lambda x: x.get("submitted_at", ""), reverse=True)[:10],
    }
