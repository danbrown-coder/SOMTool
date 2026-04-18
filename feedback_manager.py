"""DB-backed feedback store for event attendee surveys."""
from __future__ import annotations

from db import get_session
from db_models import FeedbackEntry as FeedbackRow
from models import new_id, utc_now_iso


def _row_to_dict(row: FeedbackRow) -> dict:
    return {
        "id": row.id,
        "event_id": row.event_id,
        "respondent_name": row.respondent_name,
        "respondent_email": row.respondent_email,
        "rating": row.rating,
        "liked": row.liked,
        "improve": row.improve,
        "would_attend_again": row.would_attend_again,
        "submitted_at": row.submitted_at,
    }


def load_feedback() -> list[dict]:
    with get_session() as sess:
        rows = sess.query(FeedbackRow).order_by(FeedbackRow.submitted_at.desc()).all()
        return [_row_to_dict(r) for r in rows]


def save_feedback(
    event_id: str,
    respondent_name: str,
    respondent_email: str,
    rating: int,
    liked: str,
    improve: str,
    would_attend_again: bool,
) -> dict:
    entry = FeedbackRow(
        id=new_id(),
        event_id=event_id,
        respondent_name=respondent_name,
        respondent_email=respondent_email,
        rating=max(1, min(5, int(rating or 0))),
        liked=(liked or "").strip(),
        improve=(improve or "").strip(),
        would_attend_again=bool(would_attend_again),
        submitted_at=utc_now_iso(),
    )
    with get_session() as sess:
        sess.add(entry)
        sess.flush()
        return _row_to_dict(entry)


def get_feedback(event_id: str) -> list[dict]:
    with get_session() as sess:
        rows = sess.query(FeedbackRow).filter(
            FeedbackRow.event_id == event_id
        ).order_by(FeedbackRow.submitted_at.desc()).all()
        return [_row_to_dict(r) for r in rows]


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
