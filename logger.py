"""Append-only outreach log in JSON."""
from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path

from models import EmailType, OutreachLog, new_id, utc_now_iso


DATA_DIR = Path(__file__).resolve().parent / "data"
LOG_FILE = DATA_DIR / "outreach_log.json"
_lock = threading.Lock()


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_all_logs() -> list[OutreachLog]:
    _ensure_data_dir()
    if not LOG_FILE.exists():
        return []
    try:
        text = LOG_FILE.read_text(encoding="utf-8")
        raw = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        raw = _try_recover(text)
    if not isinstance(raw, list):
        return []
    return [OutreachLog.from_dict(item) for item in raw]


def _try_recover(text: str) -> list:
    """Attempt to recover valid JSON from a corrupted file."""
    for i in range(len(text) - 1, 0, -1):
        if text[i] == "]":
            try:
                return json.loads(text[: i + 1])
            except json.JSONDecodeError:
                continue
    return []


def _save_all_logs(logs: list[OutreachLog]) -> None:
    _ensure_data_dir()
    payload = [log.to_dict() for log in logs]
    data = json.dumps(payload, indent=2, ensure_ascii=False)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
    try:
        with open(tmp_fd, "w", encoding="utf-8") as f:
            f.write(data)
        Path(tmp_path).replace(LOG_FILE)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def log_outreach(
    event_id: str,
    contact_id: str,
    contact_name: str,
    email_type: EmailType,
    email_body: str,
    subject: str | None = None,
) -> OutreachLog:
    """Append a log entry. email_body may include subject line prefix for display."""
    with _lock:
        logs = _load_all_logs()
        body = email_body
        if subject:
            body = f"Subject: {subject}\n\n{email_body}"
        entry = OutreachLog(
            id=new_id(),
            event_id=event_id,
            contact_id=contact_id,
            contact_name=contact_name,
            email_type=email_type,
            email_body=body,
            timestamp=utc_now_iso(),
        )
        logs.append(entry)
        _save_all_logs(logs)
        return entry


def get_logs(event_id: str) -> list[OutreachLog]:
    return [log for log in _load_all_logs() if log.event_id == event_id]


def get_all_logs() -> list[OutreachLog]:
    return _load_all_logs()


def get_last_outreach(event_id: str, contact_id: str) -> dict | None:
    """Return the most recent log entry for a specific contact on an event."""
    matches = [
        l for l in _load_all_logs()
        if l.event_id == event_id and l.contact_id == contact_id
    ]
    if not matches:
        return None
    matches.sort(key=lambda x: x.timestamp, reverse=True)
    return matches[0].to_dict()
