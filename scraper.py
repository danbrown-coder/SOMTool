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


def _extract_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)
    except Exception:
        return html


def _content_hash(html: str) -> str:
    text = _extract_text(html).replace("\n", " ")
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _compute_diff(old_text: str, new_text: str, max_lines: int = 20) -> tuple[list[str], list[str]]:
    import difflib
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, n=0, lineterm=""))
    added: list[str] = []
    removed: list[str] = []
    for line in diff:
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            text = line[1:].strip()
            if text and len(added) < max_lines:
                added.append(text)
        elif line.startswith("-"):
            text = line[1:].strip()
            if text and len(removed) < max_lines:
                removed.append(text)
    return added, removed


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


# ── AI event extraction ──────────────────────────────────────

_EVENT_SCHEMA_DESCRIPTION = """\
Return a JSON array of event objects found on this page. Each object must have:
- "id": a short slug like "som-series-name-YYYY" (lowercase, hyphens, no spaces)
- "series": which series/program this belongs to (e.g. "Sports Management", "CERF Events")
- "name": event title
- "date": "YYYY-MM-DD" or "TBA"
- "time": time range or "TBA"
- "location": venue or "TBA"
- "description": 1-3 sentence summary
- "speakers": array of "Name – Title, Organization" strings (empty array if none)
- "registration_url": URL or ""
- "registration_status": "open", "closed", or "tba"
- "cost": pricing info or "Free"
- "source_url": will be filled in by caller, leave as ""
- "status": "upcoming" if date is in the future or TBA, "past" if date has passed
- "contact": organizer contact info or ""
- "extra_details": any other notable details (1-3 sentences, or "")
- "last_updated": will be filled in by caller, leave as ""

If the page has NO identifiable events, return an empty array [].
Only return valid JSON, no markdown fences or commentary."""


def _extract_events_with_ai(
    html: str, source_url: str, label: str, existing: list[dict]
) -> list[dict] | None:
    """Use OpenAI to extract structured events from page HTML.

    Returns list of event dicts on success, None on failure/skip.
    """
    import os

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from openai import OpenAI
        from bs4 import BeautifulSoup
    except Exception:
        return None

    text = BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)
    if len(text) > 30_000:
        text = text[:30_000]

    existing_for_url = [e for e in existing if e.get("source_url") == source_url]
    existing_context = ""
    if existing_for_url:
        existing_context = (
            "\n\nExisting catalog entries for this page (update if details changed, "
            "keep IDs stable when updating):\n"
            + json.dumps(existing_for_url, indent=2, ensure_ascii=False)
        )

    try:
        client = OpenAI(api_key=api_key)
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": _EVENT_SCHEMA_DESCRIPTION,
                },
                {
                    "role": "user",
                    "content": (
                        f"Source: {label} ({source_url})\n"
                        f"Today's date: {__import__('datetime').date.today().isoformat()}\n\n"
                        f"Page text:\n{text}"
                        f"{existing_context}"
                    ),
                },
            ],
            temperature=0.1,
            timeout=30,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return None
        return parsed
    except Exception:
        return None


def _merge_ai_events(
    existing: list[dict], ai_events: list[dict], source_url: str
) -> bool:
    """Merge AI-extracted events into the catalog. Returns True if catalog changed."""
    changed = False
    now = utc_now_iso()
    existing_by_id = {e["id"]: e for e in existing}

    for ai_evt in ai_events:
        if not isinstance(ai_evt, dict) or not ai_evt.get("name"):
            continue
        ai_evt["source_url"] = source_url
        ai_evt["last_updated"] = now

        eid = ai_evt.get("id", "")
        matched = existing_by_id.get(eid)
        if not matched:
            for e in existing:
                if (
                    e.get("source_url") == source_url
                    and e.get("name", "").strip().lower()
                    == ai_evt.get("name", "").strip().lower()
                ):
                    matched = e
                    break

        if matched:
            for key in (
                "date", "time", "location", "description", "speakers",
                "registration_url", "registration_status", "cost",
                "status", "contact", "extra_details",
            ):
                new_val = ai_evt.get(key)
                if new_val is not None and new_val != matched.get(key):
                    matched[key] = new_val
                    changed = True
            matched["last_updated"] = now
        else:
            if not eid:
                slug = re.sub(r"[^a-z0-9]+", "-", ai_evt["name"].lower()).strip("-")
                ai_evt["id"] = f"som-{slug}"[:60]
            existing.append(ai_evt)
            changed = True

    return changed


# ── Refresh logic ────────────────────────────────────────────

def refresh_from_web() -> tuple[int, list[dict]]:
    """Scrape all sources, detect changes, AI-update catalog. Returns (pages_checked, new_changes)."""
    old_state = load_scrape_state()
    new_state: dict = {}
    new_changes: list[dict] = []
    events = load_som_events()
    catalog_changed = False

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

        current_text = _extract_text(html)[:5000]
        entry = {
            "hash": h,
            "dates": dates,
            "registration_links": [r["url"] for r in reg_links],
            "last_scraped": utc_now_iso(),
            "label": src["label"],
            "page_text": current_text,
        }
        new_state[url] = entry

        old_entry = old_state.get(url)
        if not old_entry:
            ai_events = _extract_events_with_ai(html, url, src["label"], events)
            if ai_events and _merge_ai_events(events, ai_events, url):
                catalog_changed = True
            continue
        if old_entry.get("hash") == h:
            continue

        ai_events = _extract_events_with_ai(html, url, src["label"], events)
        if ai_events and _merge_ai_events(events, ai_events, url):
            catalog_changed = True

        old_text = old_entry.get("page_text", "")
        diff_added, diff_removed = _compute_diff(old_text, current_text) if old_text else ([], [])

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
            "diff_added": diff_added,
            "diff_removed": diff_removed,
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
    if catalog_changed:
        save_som_events(events)
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
