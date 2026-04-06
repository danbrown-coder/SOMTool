"""Web scraper for SOM events — fetches CLU pages, detects changes."""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field as dc_field, asdict
from pathlib import Path
from urllib.parse import urljoin

from models import new_id, utc_now_iso

DATA_DIR = Path(__file__).resolve().parent / "data"
EVENTS_FILE = DATA_DIR / "som_events.json"
STATE_FILE = DATA_DIR / "som_scrape_state.json"
CHANGES_FILE = DATA_DIR / "som_changes.json"

SOURCES = [
    {"url": "https://www.callutheran.edu/management/events/", "label": "SOM Events Main"},
    {"url": "https://www.callutheran.edu/management/events/spmg.html", "label": "Sports Management"},
    {"url": "https://www.callutheran.edu/management/events/ess.html", "label": "Entrepreneur Speaker Series"},
    {"url": "https://www.callutheran.edu/management/events/forward.html", "label": "Forward Together"},
    {"url": "https://www.callutheran.edu/management/events/banquet.html", "label": "Graduation Banquet"},
    {"url": "https://www.callutheran.edu/management/events/mppa-events.html", "label": "MPPA Events"},
    {"url": "https://www.callutheran.edu/management/events/deij.html", "label": "DEIJB in the Workplace"},
    {"url": "https://www.callutheran.edu/management/events/techtalk.html", "label": "TechTalk Series"},
    {"url": "https://www.callutheran.edu/management/events/pathways-and-possibilities.html", "label": "Pathways & Possibilities"},
    {"url": "https://www.callutheran.edu/centers/entrepreneurship/programs/new-venture-fair.html", "label": "New Venture Fair"},
    {"url": "https://clucerf.org/events/", "label": "CERF Events"},
    {"url": "https://www.executivetalent.net/", "label": "Executive Talent Mgmt Forum"},
    {"url": "https://www.callutheran.edu/management/events/sponsor.html", "label": "Sponsorship"},
    {"url": "https://www.callutheran.edu/management/prime/", "label": "PRME @ SOM"},
]

_DATE_PATTERN = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?,?\s*"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4}",
    re.IGNORECASE,
)

_REG_KEYWORDS = {"register", "rsvp", "sign up", "tickets", "registration"}


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── Storage helpers ──────────────────────────────────────────

def load_som_events() -> list[dict]:
    _ensure_data_dir()
    if not EVENTS_FILE.exists():
        return []
    with open(EVENTS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def save_som_events(events: list[dict]) -> None:
    _ensure_data_dir()
    with open(EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)


def load_scrape_state() -> dict:
    _ensure_data_dir()
    if not STATE_FILE.exists():
        return {}
    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_scrape_state(state: dict) -> None:
    _ensure_data_dir()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def load_changes() -> list[dict]:
    _ensure_data_dir()
    if not CHANGES_FILE.exists():
        return []
    with open(CHANGES_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def save_changes(changes: list[dict]) -> None:
    _ensure_data_dir()
    with open(CHANGES_FILE, "w", encoding="utf-8") as f:
        json.dump(changes, f, indent=2, ensure_ascii=False)


def pending_changes() -> list[dict]:
    return [c for c in load_changes() if not c.get("dismissed")]


def dismiss_change(change_id: str) -> bool:
    changes = load_changes()
    for c in changes:
        if c["id"] == change_id:
            c["dismissed"] = True
            save_changes(changes)
            return True
    return False


# ── Web fetching ─────────────────────────────────────────────

def _fetch(url: str, timeout: int = 12) -> str | None:
    try:
        import requests
        r = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "SOM-EventOS/1.0 (university demo)"},
        )
        r.raise_for_status()
        return r.text
    except Exception:
        return None


def _content_hash(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        text = BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
    except Exception:
        text = html
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _extract_dates(html: str) -> list[str]:
    try:
        from bs4 import BeautifulSoup
        text = BeautifulSoup(html, "html.parser").get_text()
    except Exception:
        text = html
    return _DATE_PATTERN.findall(text)


def _extract_registration_links(html: str, base_url: str) -> list[dict]:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return []
    links = []
    for a in soup.find_all("a", href=True):
        label = a.get_text(strip=True).lower()
        if any(kw in label for kw in _REG_KEYWORDS):
            href = a["href"]
            if not href.startswith("http"):
                href = urljoin(base_url, href)
            links.append({"text": a.get_text(strip=True), "url": href})
    return links


# ── Refresh logic ────────────────────────────────────────────

def refresh_from_web() -> tuple[int, list[dict]]:
    """Scrape all sources, detect changes. Returns (pages_checked, new_changes)."""
    old_state = load_scrape_state()
    new_state: dict = {}
    new_changes: list[dict] = []
    events = load_som_events()

    pages_checked = 0
    for src in SOURCES:
        url = src["url"]
        html = _fetch(url)
        if not html:
            if url in old_state:
                new_state[url] = old_state[url]
            continue
        pages_checked += 1
        h = _content_hash(html)
        dates = _extract_dates(html)
        reg_links = _extract_registration_links(html, url)

        entry = {
            "hash": h,
            "dates": dates,
            "registration_links": [r["url"] for r in reg_links],
            "last_scraped": utc_now_iso(),
            "label": src["label"],
        }
        new_state[url] = entry

        old_entry = old_state.get(url)
        if not old_entry:
            continue
        if old_entry.get("hash") == h:
            continue

        matching = [e for e in events if e.get("source_url") == url]
        event_label = matching[0]["name"] if matching else src["label"]
        event_id = matching[0]["id"] if matching else ""

        change: dict = {
            "id": new_id(),
            "event_id": event_id,
            "event_name": event_label,
            "source_url": url,
            "change_type": "content_updated",
            "description": f"Page content changed for {src['label']}",
            "detected_at": utc_now_iso(),
            "dismissed": False,
        }

        old_dates = set(old_entry.get("dates", []))
        new_dates = set(dates)
        added_dates = new_dates - old_dates
        if added_dates:
            change["change_type"] = "date_changed"
            change["description"] = f"New date(s) found: {', '.join(sorted(added_dates))}"

        old_reg = set(old_entry.get("registration_links", []))
        new_reg = set(r["url"] for r in reg_links)
        added_reg = new_reg - old_reg
        if added_reg:
            change["change_type"] = "registration_opened"
            change["description"] = f"New registration link detected on {src['label']}"

        new_changes.append(change)
        time.sleep(0.5)

    save_scrape_state(new_state)
    if new_changes:
        all_changes = load_changes()
        all_changes.extend(new_changes)
        save_changes(all_changes)

    return pages_checked, new_changes


def get_som_event(event_id: str) -> dict | None:
    for e in load_som_events():
        if e["id"] == event_id:
            return e
    return None
