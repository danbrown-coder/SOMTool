"""Call monitoring: log persistence, Vapi polling, post-call AI analysis."""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

from models import new_id, utc_now_iso

DATA_DIR = Path(__file__).resolve().parent / "data"
CALL_LOG_FILE = DATA_DIR / "call_log.json"


def _ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_call_log() -> list[dict]:
    _ensure()
    if not CALL_LOG_FILE.exists():
        return []
    with open(CALL_LOG_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def save_call_log(entries: list[dict]) -> None:
    _ensure()
    with open(CALL_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def log_call(
    call_id: str,
    event_id: str,
    contact_id: str,
    contact_name: str,
    call_type: str,
    listen_url: str = "",
    control_url: str = "",
) -> dict:
    entries = load_call_log()
    entry = {
        "id": new_id(),
        "call_id": call_id,
        "event_id": event_id,
        "contact_id": contact_id,
        "contact_name": contact_name,
        "call_type": call_type,
        "placed_at": utc_now_iso(),
        "status": "queued",
        "listen_url": listen_url,
        "control_url": control_url,
        "transcript": "",
        "messages": [],
        "recording_url": "",
        "stereo_recording_url": "",
        "summary": "",
        "ended_reason": "",
        "duration_seconds": 0,
        "ai_analysis": None,
    }
    entries.append(entry)
    save_call_log(entries)
    return entry


def get_active_calls() -> list[dict]:
    return [
        e for e in load_call_log()
        if e.get("status") in ("queued", "ringing", "in-progress")
    ]


def get_call_by_call_id(call_id: str) -> dict | None:
    for e in load_call_log():
        if e.get("call_id") == call_id:
            return e
    return None


def get_calls_for_event(event_id: str) -> list[dict]:
    return [e for e in load_call_log() if e.get("event_id") == event_id]


def get_calls_for_contact(event_id: str, contact_id: str) -> list[dict]:
    return [
        e for e in load_call_log()
        if e.get("event_id") == event_id and e.get("contact_id") == contact_id
    ]


# ── Vapi polling ─────────────────────────────────────────────

def poll_vapi_call(call_id: str) -> dict | None:
    """Fetch current call data from Vapi API. Returns raw response dict or None."""
    api_key = os.environ.get("VAPI_API_KEY", "")
    if not api_key or not call_id:
        return None
    try:
        resp = requests.get(
            f"https://api.vapi.ai/call/{call_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def sync_call_from_vapi(call_id: str) -> dict | None:
    """Poll Vapi and update local call log entry. Returns updated entry or None."""
    vapi_data = poll_vapi_call(call_id)
    if not vapi_data:
        return None

    entries = load_call_log()
    for entry in entries:
        if entry.get("call_id") != call_id:
            continue

        entry["status"] = vapi_data.get("status", entry["status"])

        monitor = vapi_data.get("monitor", {})
        if monitor.get("listenUrl"):
            entry["listen_url"] = monitor["listenUrl"]
        if monitor.get("controlUrl"):
            entry["control_url"] = monitor["controlUrl"]

        artifact = vapi_data.get("artifact", {})
        if artifact.get("transcript"):
            entry["transcript"] = artifact["transcript"]
        if artifact.get("messages"):
            entry["messages"] = artifact["messages"]
        if artifact.get("recordingUrl"):
            entry["recording_url"] = artifact["recordingUrl"]
        if artifact.get("stereoRecordingUrl"):
            entry["stereo_recording_url"] = artifact["stereoRecordingUrl"]

        analysis = vapi_data.get("analysis", {})
        if analysis.get("summary"):
            entry["summary"] = analysis["summary"]

        entry["ended_reason"] = vapi_data.get("endedReason", "")

        started = vapi_data.get("startedAt", "")
        ended = vapi_data.get("endedAt", "")
        if started and ended:
            try:
                from datetime import datetime
                fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
                s = datetime.strptime(started, fmt)
                e = datetime.strptime(ended, fmt)
                entry["duration_seconds"] = round((e - s).total_seconds())
            except Exception:
                pass

        save_call_log(entries)
        return entry
    return None


def sync_all_active() -> int:
    """Poll all active calls. Returns number updated."""
    active = get_active_calls()
    updated = 0
    for entry in active:
        result = sync_call_from_vapi(entry["call_id"])
        if result:
            updated += 1
    return updated


# ── Post-call AI analysis ────────────────────────────────────

def analyze_call(call_id: str) -> dict | None:
    """Run OpenAI analysis on a completed call's transcript. Returns analysis dict."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return None

    entry = get_call_by_call_id(call_id)
    if not entry or not entry.get("transcript"):
        return None
    if entry.get("ai_analysis"):
        return entry["ai_analysis"]

    try:
        from openai import OpenAI
    except Exception:
        return None

    prompt = f"""Analyze this AI voice call transcript and return a JSON object with these fields:
- "sentiment_score": 1-10 (how positively the person responded)
- "engagement_level": "low", "medium", or "high"
- "outcome": one of "confirmed", "interested", "maybe_later", "not_interested", "voicemail", "no_answer", "hung_up"
- "key_objections": array of strings (concerns they raised, empty if none)
- "what_worked": array of strings (talking points that resonated)
- "what_didnt_work": array of strings (things that fell flat)
- "recommended_next_step": string (follow-up email, another call, different approach, etc.)
- "phrasing_notes": string (specific language insights)
- "contact_preference": "phone", "email", or "either"

Call type: {entry.get('call_type', 'invite')}
Contact: {entry.get('contact_name', 'Unknown')}
Summary: {entry.get('summary', 'N/A')}
Ended reason: {entry.get('ended_reason', 'N/A')}

Transcript:
{entry['transcript'][:8000]}

Return ONLY valid JSON, no markdown fences."""

    try:
        client = OpenAI(api_key=api_key)
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            timeout=30,
        )
        raw = resp.choices[0].message.content.strip()
        import re
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        analysis = json.loads(raw)
    except Exception:
        return None

    entries = load_call_log()
    for e in entries:
        if e.get("call_id") == call_id:
            e["ai_analysis"] = analysis
            break
    save_call_log(entries)
    return analysis


def get_all_analyses() -> list[dict]:
    """Return all call log entries that have AI analysis."""
    return [e for e in load_call_log() if e.get("ai_analysis")]


def compute_channel_metrics() -> dict:
    """Compute aggregate metrics for the analytics dashboard."""
    entries = load_call_log()
    analyzed = [e for e in entries if e.get("ai_analysis")]
    total_calls = len(entries)
    completed = [e for e in entries if e.get("status") == "ended"]

    sentiments = [e["ai_analysis"]["sentiment_score"] for e in analyzed
                  if isinstance(e.get("ai_analysis", {}).get("sentiment_score"), (int, float))]
    avg_sentiment = round(sum(sentiments) / len(sentiments), 1) if sentiments else 0

    outcomes: dict[str, int] = {}
    for e in analyzed:
        o = e["ai_analysis"].get("outcome", "unknown")
        outcomes[o] = outcomes.get(o, 0) + 1

    engagement: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
    for e in analyzed:
        lvl = e["ai_analysis"].get("engagement_level", "low")
        if lvl in engagement:
            engagement[lvl] += 1

    all_worked: list[str] = []
    all_didnt: list[str] = []
    for e in analyzed:
        all_worked.extend(e["ai_analysis"].get("what_worked", []))
        all_didnt.extend(e["ai_analysis"].get("what_didnt_work", []))

    return {
        "total_calls": total_calls,
        "completed_calls": len(completed),
        "analyzed_calls": len(analyzed),
        "avg_sentiment": avg_sentiment,
        "outcomes": outcomes,
        "engagement": engagement,
        "top_worked": _top_n(all_worked, 5),
        "top_didnt_work": _top_n(all_didnt, 5),
    }


def _top_n(items: list[str], n: int) -> list[str]:
    counts: dict[str, int] = {}
    for item in items:
        key = item.strip().lower()
        if key:
            counts[key] = counts.get(key, 0) + 1
    return [k for k, _ in sorted(counts.items(), key=lambda x: -x[1])[:n]]
