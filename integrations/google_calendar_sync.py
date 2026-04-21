"""Two-way Google Calendar sync for the outreach queue.

Each approved outreach action is mirrored to the queue-owner's primary
Google Calendar. The mapping between a SOMTool `action.id` and its Google
`event.id` lives in `external_objects` (entity_type="outreach_action",
provider="google"), alongside a `meta` dict containing the owning user_id,
htmlLink, Meet URL, and etag. A per-user push-notification channel
watches the same calendar and feeds webhook deltas back into the queue.

The hot path goes::

    queue route ─► push_outreach()/delete_outreach() ─► Google
    Google push ─► /gcal/webhook ─► pull_changes()   ─► queue

Loop prevention: after every write we stash the returned etag in meta;
when a webhook delta arrives we compare the incoming etag against it
and skip events we just pushed ourselves.
"""
from __future__ import annotations

import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from integrations.google import (
    SPEC as GOOGLE_SPEC,
    get_calendar_client,
    has_scope_group,
)
from integrations.sync import (
    delete_external_id,
    get_cursor,
    get_external_id,
    get_external_meta,
    log_sync,
    set_cursor,
    set_external_id,
)

logger = logging.getLogger(__name__)


ENTITY_TYPE = "outreach_action"
PROVIDER = "google"
RESOURCE_WATCH = "calendar_watch"
CALENDAR_ID = "primary"

# Watch channels live up to 7 days (Google limit is shorter for push
# notifications, usually 24h for events). Renew ~6h before expiry.
RENEW_WINDOW_SECONDS = 6 * 3600


# ── Internal helpers ──────────────────────────────────────


def _connection_id(user_id: str) -> Optional[str]:
    from integrations import get_connection
    conn = get_connection(user_id, GOOGLE_SPEC.slug)
    return conn.id if conn else None


def _webhook_url() -> str:
    return (os.environ.get("GCAL_WEBHOOK_URL") or "").strip()


def _color_for_status(status: str) -> Optional[str]:
    """Map queue status → Google Calendar color id (1..11).

    `sent` ⇒ Graphite (8), `skipped`/`failed` ⇒ Tomato (11),
    `approved` ⇒ Sage (10), otherwise leave default.
    """
    return {
        "sent":    "8",
        "skipped": "11",
        "failed":  "11",
        "approved": "10",
    }.get(status)


def _human_action(action_type: str) -> str:
    return {
        "email_initial":  "Intro email",
        "email_followup": "Follow-up email",
        "email_thankyou": "Thank-you email",
        "email_survey":   "Survey email",
        "call_invite":    "Invite call",
        "call_followup":  "Follow-up call",
    }.get(action_type, (action_type or "Outreach").replace("_", " ").title())


def _event_name(action: dict) -> str:
    from event_manager import get_event
    ev = get_event(action.get("event_id", ""))
    return ev.name if ev else ""


def _outreach_to_gcal_body(action: dict) -> dict:
    """Build the Google Calendar insert/update payload for a queue action."""
    title = _human_action(action.get("action_type", ""))
    contact = action.get("contact_name") or action.get("contact_email") or ""
    event_name = _event_name(action)
    summary = f"{title}" + (f", {contact}" if contact else "")
    if event_name:
        summary = f"{summary} — {event_name}"

    scheduled = action.get("scheduled_at") or ""
    try:
        start = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    except ValueError:
        start = datetime.now(timezone.utc) + timedelta(hours=1)
    end = start + timedelta(minutes=30)

    description_lines = [
        f"SOMTool outreach · action {action.get('id','')}",
        f"Event: {event_name or '—'}",
        f"Contact: {contact or '—'} <{action.get('contact_email','')}>",
        f"Type: {_human_action(action.get('action_type',''))}",
        f"Status: {action.get('status','planned')}",
    ]
    if action.get("ai_reason"):
        description_lines.append("")
        description_lines.append(f"Why: {action['ai_reason']}")
    if action.get("preview"):
        description_lines.append("")
        description_lines.append("Preview:")
        description_lines.append(action["preview"][:2000])

    body: dict = {
        "summary": summary,
        "description": "\n".join(description_lines),
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "source": {
            "title": "SOMTool outreach",
            "url": "",  # filled by caller if a base URL is known
        },
        "extendedProperties": {
            "private": {
                "somtool_action_id": action.get("id", ""),
                "somtool_event_id": action.get("event_id", ""),
                "somtool_action_type": action.get("action_type", ""),
            }
        },
    }

    color = _color_for_status(action.get("status", ""))
    if color:
        body["colorId"] = color

    email = (action.get("contact_email") or "").strip()
    if email and action.get("action_type", "").startswith("email") and action.get("status") == "approved":
        body["attendees"] = [{"email": email, "displayName": contact or email}]

    return body


# ── Public API ────────────────────────────────────────────


def push_outreach(user_id: str, action: dict) -> Optional[str]:
    """Mirror a queue action to Google Calendar.

    Creates the event if no mapping exists yet, otherwise patches the
    existing one. Returns the Google event id, or None if the user has
    no calendar scope / the push fails. Safe to call repeatedly --
    idempotent on (action.id, user_id).
    """
    if not user_id or not action or not has_scope_group(user_id, "calendar"):
        return None
    client = get_calendar_client(user_id)
    if client is None:
        return None

    conn_id = _connection_id(user_id) or ""
    try:
        body = _outreach_to_gcal_body(action)
        existing_id = get_external_id(ENTITY_TYPE, action.get("id", ""), PROVIDER)
        meta_prev = get_external_meta(ENTITY_TYPE, action.get("id", ""), PROVIDER)

        if existing_id:
            result = (
                client.events()
                .patch(
                    calendarId=CALENDAR_ID,
                    eventId=existing_id,
                    body=body,
                    sendUpdates="none",
                )
                .execute()
            )
        else:
            result = (
                client.events()
                .insert(
                    calendarId=CALENDAR_ID,
                    body=body,
                    sendUpdates="none",
                )
                .execute()
            )

        gcal_id = result.get("id")
        if not gcal_id:
            return None

        meta = dict(meta_prev or {})
        meta.update({
            "owner_user_id": user_id,
            "html_link": result.get("htmlLink", meta.get("html_link", "")),
            "etag": result.get("etag", ""),
            "last_pushed_at": datetime.now(timezone.utc).isoformat(),
        })
        for ep in (result.get("conferenceData", {}) or {}).get("entryPoints", []) or []:
            if ep.get("entryPointType") == "video":
                meta["meet_url"] = ep.get("uri", "")
                break

        from org_manager import current_org_id
        try:
            org_id = current_org_id()
        except Exception:  # pragma: no cover — called outside request context
            org_id = ""
        set_external_id(
            org_id=org_id,
            entity_type=ENTITY_TYPE,
            entity_id=action.get("id", ""),
            provider=PROVIDER,
            external_id=gcal_id,
            meta=meta,
        )
        log_sync(conn_id, PROVIDER, action="outreach.push", rows_affected=1,
                 detail=f"action={action.get('id','')} gcal={gcal_id}")
        return gcal_id
    except Exception as exc:
        logger.warning("Calendar push for action %s failed: %s", action.get("id"), exc)
        log_sync(conn_id, PROVIDER, action="outreach.push", status="error",
                 detail=f"action={action.get('id','')} err={exc}")
        return None


def delete_outreach(action_id: str, user_id: str | None = None) -> bool:
    """Delete the Google Calendar event that mirrors this action.

    Uses the stored owner_user_id when no `user_id` is passed so CLI/cron
    callers don't need a Flask request context.
    """
    if not action_id:
        return False
    gcal_id = get_external_id(ENTITY_TYPE, action_id, PROVIDER)
    meta = get_external_meta(ENTITY_TYPE, action_id, PROVIDER)
    owner = user_id or meta.get("owner_user_id") or ""
    if not gcal_id or not owner:
        delete_external_id(ENTITY_TYPE, action_id, PROVIDER)
        return False
    if not has_scope_group(owner, "calendar"):
        return False
    client = get_calendar_client(owner)
    if client is None:
        return False

    conn_id = _connection_id(owner) or ""
    try:
        client.events().delete(
            calendarId=CALENDAR_ID, eventId=gcal_id, sendUpdates="none"
        ).execute()
        log_sync(conn_id, PROVIDER, action="outreach.delete", rows_affected=1,
                 detail=f"action={action_id} gcal={gcal_id}")
    except Exception as exc:
        logger.warning("Calendar delete for action %s failed: %s", action_id, exc)
        log_sync(conn_id, PROVIDER, action="outreach.delete", status="error",
                 detail=f"action={action_id} err={exc}")
    delete_external_id(ENTITY_TYPE, action_id, PROVIDER)
    return True


# ── Push-notification channels (watch/stop/renew) ─────────


def start_watch(user_id: str) -> Optional[dict]:
    """Subscribe to push notifications on the user's primary calendar.

    No-op (returns None) when GCAL_WEBHOOK_URL is unset or the user
    hasn't granted calendar scope. Stores the resulting channel id,
    token, and expiration in provider_sync_state so renew can find it.
    """
    url = _webhook_url()
    if not url or not user_id or not has_scope_group(user_id, "calendar"):
        return None
    client = get_calendar_client(user_id)
    conn_id = _connection_id(user_id)
    if client is None or conn_id is None:
        return None

    channel_id = f"somtool-{user_id}-{int(time.time())}"
    token = secrets.token_urlsafe(24)
    try:
        resp = client.events().watch(
            calendarId=CALENDAR_ID,
            body={
                "id": channel_id,
                "type": "web_hook",
                "address": url,
                "token": token,
                "params": {"ttl": str(6 * 3600)},
            },
        ).execute()
        expires_ms = int(resp.get("expiration") or 0)
        meta = {
            "user_id": user_id,
            "channel_id": resp.get("id", channel_id),
            "resource_id": resp.get("resourceId", ""),
            "token": token,
            "expires_at_ms": expires_ms,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        # Preserve the nextSyncToken (if any) that earlier pulls stored.
        cursor = get_cursor(conn_id, RESOURCE_WATCH, CALENDAR_ID)
        set_cursor(conn_id, RESOURCE_WATCH, cursor=cursor, resource_id=CALENDAR_ID, meta=meta)
        log_sync(conn_id, PROVIDER, action="calendar.watch",
                 detail=f"channel={meta['channel_id']} exp={expires_ms}")
        return meta
    except Exception as exc:
        logger.warning("Calendar start_watch for user %s failed: %s", user_id, exc)
        log_sync(conn_id, PROVIDER, action="calendar.watch", status="error",
                 detail=str(exc))
        return None


def stop_watch(user_id: str) -> bool:
    """Cancel an active push-notification channel for a user (best-effort)."""
    if not user_id:
        return False
    conn_id = _connection_id(user_id)
    if conn_id is None:
        return False
    client = get_calendar_client(user_id)
    if client is None:
        return False
    from db import get_session
    from db_models import ProviderSyncState
    with get_session() as sess:
        row = (
            sess.query(ProviderSyncState)
            .filter(
                ProviderSyncState.connection_id == conn_id,
                ProviderSyncState.resource_type == RESOURCE_WATCH,
                ProviderSyncState.resource_id == CALENDAR_ID,
            )
            .first()
        )
        meta = dict(row.meta or {}) if row else {}
    channel_id = meta.get("channel_id")
    resource_id = meta.get("resource_id")
    if not channel_id or not resource_id:
        return False
    try:
        client.channels().stop(body={"id": channel_id, "resourceId": resource_id}).execute()
        log_sync(conn_id, PROVIDER, action="calendar.unwatch",
                 detail=f"channel={channel_id}")
        return True
    except Exception as exc:
        logger.warning("Calendar stop_watch for user %s failed: %s", user_id, exc)
        return False


def renew_expiring_watches() -> int:
    """Rebuild any watch channels that are within the renewal window.

    Intended to be called from the existing cron tick; cheap no-op when
    nothing needs renewing. Returns the number of channels renewed.
    """
    if not _webhook_url():
        return 0
    now_ms = int(time.time() * 1000)
    threshold_ms = now_ms + RENEW_WINDOW_SECONDS * 1000
    from db import get_session
    from db_models import ProviderSyncState
    with get_session() as sess:
        rows = (
            sess.query(ProviderSyncState)
            .filter(
                ProviderSyncState.resource_type == RESOURCE_WATCH,
                ProviderSyncState.resource_id == CALENDAR_ID,
            )
            .all()
        )
        candidates = []
        for r in rows:
            meta = dict(r.meta or {})
            expires = int(meta.get("expires_at_ms") or 0)
            user_id = meta.get("user_id") or ""
            if user_id and expires and expires <= threshold_ms:
                candidates.append(user_id)

    count = 0
    for user_id in candidates:
        try:
            stop_watch(user_id)
        except Exception:
            pass
        if start_watch(user_id):
            count += 1
    return count


# ── Inbound: webhook ──────────────────────────────────────


def channel_meta_for_token(token: str) -> Optional[dict]:
    """Look up the stored watch metadata for a channel token.

    Returns a dict with at least ``user_id`` and ``channel_id`` when the
    token matches, otherwise None. Used by the webhook to authenticate
    incoming pings.
    """
    if not token:
        return None
    from db import get_session
    from db_models import ProviderSyncState
    with get_session() as sess:
        rows = (
            sess.query(ProviderSyncState)
            .filter(
                ProviderSyncState.resource_type == RESOURCE_WATCH,
                ProviderSyncState.resource_id == CALENDAR_ID,
            )
            .all()
        )
        for r in rows:
            meta = dict(r.meta or {})
            if meta.get("token") == token:
                return {
                    "user_id": meta.get("user_id", ""),
                    "channel_id": meta.get("channel_id", ""),
                    "connection_id": r.connection_id,
                    "cursor": r.cursor or "",
                }
    return None


def pull_changes(user_id: str) -> int:
    """Fetch calendar deltas using the stored syncToken and reconcile the
    outreach queue.

    Returns the number of queue actions touched. Quietly advances the
    sync token on next run. Safe to call without a token -- first call
    does a broad window and stores the new token.
    """
    if not user_id or not has_scope_group(user_id, "calendar"):
        return 0
    client = get_calendar_client(user_id)
    conn_id = _connection_id(user_id)
    if client is None or conn_id is None:
        return 0

    import outreach_queue  # lazy — avoids circular import

    cursor = get_cursor(conn_id, RESOURCE_WATCH, CALENDAR_ID)
    touched = 0
    new_token = cursor
    try:
        params = {"calendarId": CALENDAR_ID, "singleEvents": True, "showDeleted": True}
        if cursor:
            params["syncToken"] = cursor
        else:
            params["timeMin"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            params["maxResults"] = 250
        page_token = None
        while True:
            if page_token:
                params["pageToken"] = page_token
            resp = client.events().list(**params).execute()
            for ev in resp.get("items", []) or []:
                touched += _reconcile_one(user_id, ev)
            page_token = resp.get("nextPageToken")
            new_token = resp.get("nextSyncToken") or new_token
            if not page_token:
                break
    except Exception as exc:
        msg = str(exc).lower()
        if "fullSyncRequired" in msg or "410" in msg:
            # Token expired; reset to force a full sync next time.
            new_token = ""
            logger.info("Calendar syncToken invalidated for %s, resetting", user_id)
        else:
            logger.warning("Calendar pull for user %s failed: %s", user_id, exc)
            log_sync(conn_id, PROVIDER, action="calendar.pull", status="error",
                     detail=str(exc))
            return 0

    # Preserve the existing watch meta; only refresh the token + timestamp.
    from db import get_session
    from db_models import ProviderSyncState
    with get_session() as sess:
        row = (
            sess.query(ProviderSyncState)
            .filter(
                ProviderSyncState.connection_id == conn_id,
                ProviderSyncState.resource_type == RESOURCE_WATCH,
                ProviderSyncState.resource_id == CALENDAR_ID,
            )
            .first()
        )
        meta = dict(row.meta or {}) if row else {"user_id": user_id}
    set_cursor(conn_id, RESOURCE_WATCH, cursor=new_token,
               resource_id=CALENDAR_ID, meta=meta)
    log_sync(conn_id, PROVIDER, action="calendar.pull", rows_affected=touched,
             detail=f"user={user_id}")
    return touched


def _reconcile_one(user_id: str, ev: dict) -> int:
    """Apply a single GCal event delta to the outreach queue. Returns 1 if
    the queue was mutated, else 0.
    """
    props = (ev.get("extendedProperties") or {}).get("private") or {}
    action_id = props.get("somtool_action_id") or ""
    if not action_id:
        return 0
    try:
        import outreach_queue
        from db import get_session
        from db_models import ExternalObject
    except Exception:
        return 0

    existing = outreach_queue.get_by_id(action_id)
    if not existing:
        return 0

    # Loop prevention: if the event's etag matches what we just pushed,
    # skip -- that change originated from us.
    with get_session() as sess:
        row = (
            sess.query(ExternalObject)
            .filter(
                ExternalObject.entity_type == ENTITY_TYPE,
                ExternalObject.entity_id == action_id,
                ExternalObject.provider == PROVIDER,
            )
            .first()
        )
        meta = dict(row.meta or {}) if row else {}
    if ev.get("etag") and ev.get("etag") == meta.get("etag"):
        return 0

    status = ev.get("status", "")
    changed = False
    if status == "cancelled":
        if existing.get("status") != "skipped":
            outreach_queue.update_status(action_id, "skipped")
            changed = True
        delete_external_id(ENTITY_TYPE, action_id, PROVIDER)
        return 1 if changed else 0

    start = ((ev.get("start") or {}).get("dateTime")
             or (ev.get("start") or {}).get("date") or "")
    if start:
        try:
            parsed = datetime.fromisoformat(start.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            new_iso = parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if new_iso != existing.get("scheduled_at"):
                outreach_queue.reschedule(action_id, new_iso)
                changed = True
        except ValueError:
            pass

    meta["etag"] = ev.get("etag", meta.get("etag", ""))
    meta["html_link"] = ev.get("htmlLink", meta.get("html_link", ""))
    meta["owner_user_id"] = user_id
    try:
        from org_manager import current_org_id
        org_id = current_org_id()
    except Exception:
        org_id = meta.get("org_id", "") or ""
    set_external_id(
        org_id=org_id,
        entity_type=ENTITY_TYPE,
        entity_id=action_id,
        provider=PROVIDER,
        external_id=ev.get("id", ""),
        meta=meta,
    )
    return 1 if changed else 0
