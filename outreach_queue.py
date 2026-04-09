"""JSON-backed outreach action queue: plan, approve, skip, reschedule, execute."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from models import new_id, utc_now_iso

DATA_DIR = Path(__file__).resolve().parent / "data"
QUEUE_FILE = DATA_DIR / "outreach_queue.json"


def _ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_queue() -> list[dict]:
    _ensure()
    if not QUEUE_FILE.exists():
        return []
    with open(QUEUE_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def save_queue(items: list[dict]) -> None:
    _ensure()
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def add_action(
    event_id: str,
    contact_id: str,
    contact_name: str,
    contact_email: str,
    action_type: str,
    scheduled_at: str,
    ai_reason: str = "",
    preview: str = "",
    status: str = "planned",
) -> dict:
    items = load_queue()
    entry = {
        "id": new_id(),
        "event_id": event_id,
        "contact_id": contact_id,
        "contact_name": contact_name,
        "contact_email": contact_email,
        "action_type": action_type,
        "scheduled_at": scheduled_at,
        "status": status,
        "ai_reason": ai_reason,
        "preview": preview,
        "created_at": utc_now_iso(),
        "executed_at": None,
    }
    items.append(entry)
    save_queue(items)
    return entry


def get_by_id(action_id: str) -> dict | None:
    for item in load_queue():
        if item["id"] == action_id:
            return item
    return None


def already_queued(event_id: str, contact_id: str, action_type: str) -> bool:
    return any(
        q["event_id"] == event_id
        and q["contact_id"] == contact_id
        and q["action_type"] == action_type
        and q["status"] in ("planned", "approved")
        for q in load_queue()
    )


def update_status(action_id: str, status: str) -> bool:
    items = load_queue()
    for item in items:
        if item["id"] == action_id:
            item["status"] = status
            if status == "sent":
                item["executed_at"] = utc_now_iso()
            save_queue(items)
            return True
    return False


def reschedule(action_id: str, new_time: str) -> bool:
    items = load_queue()
    for item in items:
        if item["id"] == action_id:
            item["scheduled_at"] = new_time
            item["status"] = "approved"
            save_queue(items)
            return True
    return False


def update_preview(action_id: str, preview: str) -> bool:
    items = load_queue()
    for item in items:
        if item["id"] == action_id:
            item["preview"] = preview
            save_queue(items)
            return True
    return False


def delete_action(action_id: str) -> bool:
    items = load_queue()
    before = len(items)
    items = [i for i in items if i["id"] != action_id]
    if len(items) < before:
        save_queue(items)
        return True
    return False


def get_due_approved(now_iso: str | None = None) -> list[dict]:
    if now_iso is None:
        now_iso = utc_now_iso()
    return [
        q for q in load_queue()
        if q["status"] == "approved" and q.get("scheduled_at", "z") <= now_iso
    ]


def get_queue_filtered(
    status: str = "",
    action_type: str = "",
    event_id: str = "",
) -> list[dict]:
    items = load_queue()
    if status:
        items = [i for i in items if i["status"] == status]
    if action_type:
        items = [i for i in items if i["action_type"] == action_type]
    if event_id:
        items = [i for i in items if i["event_id"] == event_id]
    items.sort(key=lambda x: x.get("scheduled_at", ""))
    return items


def plan_outreach_for_event(event, contacts, ai_config: dict | None = None) -> int:
    """Use AI to generate a schedule of outreach actions for an event's contacts.

    Returns the number of new actions added to the queue.
    """
    cfg = ai_config or {}
    auto_approve_emails = cfg.get("auto_approve_emails", False)
    auto_approve_calls = cfg.get("auto_approve_calls", False)
    followup_delay = cfg.get("followup_delay_days", 3)
    call_delay = cfg.get("call_delay_after_email_days", 2)
    blackout_start = cfg.get("blackout_hours_start", 22)
    blackout_end = cfg.get("blackout_hours_end", 8)
    timing_rules = cfg.get("timing_rules", "")

    now = datetime.now(timezone.utc)
    added = 0

    ai_schedule = _ai_suggest_schedule(event, contacts, cfg)

    for c in contacts:
        if already_queued(event.id, c.id, "email_initial"):
            continue

        suggestion = ai_schedule.get(c.id, {})
        email_time = suggestion.get("email_time") or _next_good_slot(
            now, blackout_start, blackout_end
        )
        email_reason = suggestion.get("email_reason", "Initial outreach before event")
        email_status = "approved" if auto_approve_emails else "planned"

        add_action(
            event_id=event.id,
            contact_id=c.id,
            contact_name=c.name,
            contact_email=c.email,
            action_type="email_initial",
            scheduled_at=email_time,
            ai_reason=email_reason,
            preview="",
            status=email_status,
        )
        added += 1

        followup_time = suggestion.get("followup_time") or _next_good_slot(
            datetime.fromisoformat(email_time.replace("Z", "+00:00")) + timedelta(days=followup_delay),
            blackout_start, blackout_end,
        )
        if not already_queued(event.id, c.id, "email_followup"):
            add_action(
                event_id=event.id,
                contact_id=c.id,
                contact_name=c.name,
                contact_email=c.email,
                action_type="email_followup",
                scheduled_at=followup_time,
                ai_reason=suggestion.get("followup_reason", f"Follow-up {followup_delay} days after initial email"),
                preview="",
                status=email_status,
            )
            added += 1

        call_time = suggestion.get("call_time") or _next_good_slot(
            datetime.fromisoformat(email_time.replace("Z", "+00:00")) + timedelta(days=call_delay),
            blackout_start, blackout_end,
        )
        if not already_queued(event.id, c.id, "call_invite"):
            call_status = "approved" if auto_approve_calls else "planned"
            add_action(
                event_id=event.id,
                contact_id=c.id,
                contact_name=c.name,
                contact_email=c.email,
                action_type="call_invite",
                scheduled_at=call_time,
                ai_reason=suggestion.get("call_reason", f"Phone follow-up {call_delay} days after email"),
                preview="",
                status=call_status,
            )
            added += 1

    return added


def _next_good_slot(
    base: datetime, blackout_start: int = 22, blackout_end: int = 8
) -> str:
    t = base
    if t.hour >= blackout_start or t.hour < blackout_end:
        if t.hour >= blackout_start:
            t = t + timedelta(days=1)
        t = t.replace(hour=blackout_end, minute=30, second=0, microsecond=0)
    if t.weekday() == 5:
        t += timedelta(days=2)
    elif t.weekday() == 6:
        t += timedelta(days=1)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ai_suggest_schedule(event, contacts, cfg: dict) -> dict:
    """Ask OpenAI to suggest optimal outreach times for each contact.

    Returns {contact_id: {email_time, followup_time, call_time, email_reason, ...}}.
    Falls back to empty dict on failure (caller uses defaults).
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key or not contacts:
        return {}

    timing_rules = cfg.get("timing_rules", "")
    personality = cfg.get("personality", "")

    contact_lines = []
    for c in contacts[:30]:
        contact_lines.append(f"- id={c.id} | {c.name} | {c.email} | role={c.contact_role.value}")
    contacts_block = "\n".join(contact_lines)

    now = datetime.now(timezone.utc)
    prompt = (
        f"You are scheduling outreach for an event.\n\n"
        f"Event: {event.name}\nDate: {event.date}\n"
        f"Description: {event.description[:500]}\n"
        f"Today: {now.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"Timing rules from admin: {timing_rules or 'None specified'}\n\n"
        f"Contacts to schedule:\n{contacts_block}\n\n"
        "For each contact, suggest optimal times for:\n"
        "1. Initial email\n"
        "2. Follow-up email (if no reply)\n"
        "3. Phone call (if still no reply)\n\n"
        "Consider:\n"
        "- Spread outreach across days (don't send all at once)\n"
        "- Business hours only\n"
        "- Earlier outreach for contacts with important roles (speaker, sponsor)\n"
        "- Time zone awareness\n\n"
        "Return ONLY valid JSON object: {\"<contact_id>\": {\"email_time\": \"ISO\", "
        "\"email_reason\": \"why this time\", \"followup_time\": \"ISO\", "
        "\"followup_reason\": \"...\", \"call_time\": \"ISO\", \"call_reason\": \"...\"}} "
        "All times in UTC ISO 8601 format."
    )

    try:
        from openai import OpenAI
        import re
        client = OpenAI(api_key=api_key)
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            timeout=30,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}
