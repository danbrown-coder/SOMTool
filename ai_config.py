"""AI behavior configuration: personality, timing, rules, limits."""
from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
CONFIG_FILE = DATA_DIR / "ai_config.json"

DEFAULTS: dict = {
    "personality": (
        "Be casual and warm. You work at the Cal Lutheran School of Management. "
        "Reference the recipient's background when possible."
    ),
    "timing_rules": (
        "Prefer Tuesday-Thursday mornings (9-11am PT). "
        "Never schedule calls before 9am or after 5pm PT."
    ),
    "email_rules": (
        "Keep emails under 5 sentences. Be direct, not salesy. "
        "Vary your opening lines -- never start with 'I hope this finds you well'."
    ),
    "call_rules": (
        "Open with your name and reason for calling within 10 seconds. "
        "Be conversational, not scripted. If voicemail, leave a brief message."
    ),
    "auto_approve_emails": False,
    "auto_approve_calls": False,
    "followup_delay_days": 3,
    "call_delay_after_email_days": 2,
    "blackout_hours_start": 22,
    "blackout_hours_end": 8,
    "max_emails_per_day": 20,
    "max_calls_per_day": 10,
    "sender_name": "Alex",
    "sender_title": "Events Coordinator, School of Management",
    "sender_email": "",
}


def _ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    _ensure()
    result = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                result.update(stored)
        except Exception:
            pass
    return result


def save_config(cfg: dict) -> None:
    _ensure()
    merged = dict(DEFAULTS)
    merged.update(cfg)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
