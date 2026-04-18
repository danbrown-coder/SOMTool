"""Google OAuth provider + API client helpers.

Phase 4 wires up the OAuth flow. Phase 5 uses the helpers here to:
  - sync events to Google Calendar
  - send emails via Gmail as the logged-in user
  - import files from Google Drive
"""
from __future__ import annotations

import base64
import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests

from integrations.oauth import ProviderSpec
from integrations import register_provider

logger = logging.getLogger(__name__)


GOOGLE_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _fetch_userinfo(access_token: str) -> dict:
    try:
        resp = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("Google userinfo lookup failed: %s", exc)
        return {}


SPEC = ProviderSpec(
    slug="google",
    display_name="Google (Calendar / Gmail / Drive)",
    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    scopes=GOOGLE_SCOPES,
    client_id_env="GOOGLE_CLIENT_ID",
    client_secret_env="GOOGLE_CLIENT_SECRET",
    redirect_uri_env="GOOGLE_REDIRECT_URI",
    extra_auth_params={
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    },
    account_info_fn=_fetch_userinfo,
    icon_emoji="G",
    description="Sync events to your Google Calendar, send emails as you via Gmail, and import CSV/flyer files from Drive.",
)


register_provider(SPEC)


# ── API helpers ─────────────────────────────────────────────


def _access_token_for(user_id: str) -> Optional[str]:
    from integrations.oauth import get_valid_access_token
    return get_valid_access_token(user_id, SPEC.slug)


def _credentials_for(user_id: str):
    """Build a google.oauth2.credentials.Credentials for discovery-based clients."""
    try:
        from google.oauth2.credentials import Credentials
    except ImportError:
        return None
    access = _access_token_for(user_id)
    if not access:
        return None
    from integrations.oauth import get_decrypted_refresh_token
    refresh = get_decrypted_refresh_token(user_id, SPEC.slug)
    return Credentials(
        token=access,
        refresh_token=refresh,
        token_uri=SPEC.token_url,
        client_id=SPEC.client_id(),
        client_secret=SPEC.client_secret(),
        scopes=SPEC.scopes,
    )


def get_calendar_client(user_id: str):
    creds = _credentials_for(user_id)
    if creds is None:
        return None
    try:
        from googleapiclient.discovery import build
    except ImportError:
        return None
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def get_drive_client(user_id: str):
    creds = _credentials_for(user_id)
    if creds is None:
        return None
    try:
        from googleapiclient.discovery import build
    except ImportError:
        return None
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def get_gmail_client(user_id: str):
    creds = _credentials_for(user_id)
    if creds is None:
        return None
    try:
        from googleapiclient.discovery import build
    except ImportError:
        return None
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


# ── Phase 5 feature: Gmail send-as ──────────────────────────


def send_gmail_as_user(
    user_id: str, to: str, subject: str, body: str,
    reply_to: str = "", sender_name: str = "",
) -> Optional[dict]:
    """Send via Gmail as the logged-in user. Returns a dict compatible with
    email_sender.send_email's contract, or None if the user has no Google
    connection (so the caller can fall back to Resend/SMTP).
    """
    if not user_id:
        return None
    client = get_gmail_client(user_id)
    if client is None:
        return None
    try:
        from integrations import get_connection
        conn = get_connection(user_id, SPEC.slug)
        from_email = (conn.account_email if conn else "") or "me"

        msg = MIMEMultipart("alternative")
        msg["To"] = to
        msg["Subject"] = subject
        if sender_name and from_email and "@" in from_email:
            msg["From"] = f"{sender_name} <{from_email}>"
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.attach(MIMEText(body, "plain", "utf-8"))
        html_body = body.replace("\n", "<br>")
        msg.attach(MIMEText(
            f'<div style="font-family:Inter,Arial,sans-serif;font-size:14px;line-height:1.6;">{html_body}</div>',
            "html", "utf-8",
        ))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        result = client.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {
            "ok": True,
            "provider": "gmail_oauth",
            "provider_message_id": result.get("id"),
        }
    except Exception as exc:
        logger.warning("Gmail send-as failed: %s", exc)
        return {"ok": False, "provider": "gmail_oauth", "error": str(exc)[:200]}


# ── Phase 5 feature: Calendar sync ──────────────────────────


def sync_event_to_calendar(user_id: str, event) -> Optional[str]:
    """Create (or update) a Google Calendar event matching a SOMTool event.

    Returns the gcal event id. Persists `gcal_event_id` on the Event row.
    """
    client = get_calendar_client(user_id)
    if client is None:
        return None
    try:
        from datetime import datetime as _dt, timezone as _tz
        event_date = (event.date or "").strip()
        if not event_date:
            return None
        try:
            start = _dt.fromisoformat(event_date.replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=_tz.utc)
            end = start.replace(hour=(start.hour + 1) % 24)
            has_time = True
        except ValueError:
            start = None
            end = None
            has_time = False

        body = {
            "summary": event.name or "Event",
            "description": event.description or "",
            "attendees": [
                {"email": c.email, "displayName": c.name or c.email}
                for c in getattr(event, "contacts", [])
                if c.email and c.status and c.status.value == "confirmed"
            ],
        }
        if has_time:
            body["start"] = {"dateTime": start.isoformat()}
            body["end"] = {"dateTime": end.isoformat()}
        else:
            body["start"] = {"date": event_date[:10]}
            body["end"] = {"date": event_date[:10]}

        existing_id = getattr(event, "gcal_event_id", None)
        if existing_id:
            result = client.events().update(calendarId="primary", eventId=existing_id, body=body).execute()
        else:
            result = client.events().insert(calendarId="primary", body=body, sendUpdates="none").execute()
        gcal_id = result.get("id")

        if gcal_id:
            from db import get_session
            from db_models import Event as EventRow
            with get_session() as sess:
                row = sess.get(EventRow, event.id)
                if row is not None:
                    row.gcal_event_id = gcal_id
        return gcal_id
    except Exception as exc:
        logger.warning("Calendar sync failed: %s", exc)
        return None


# ── Phase 5 feature: Drive file import ──────────────────────


def download_drive_file(user_id: str, file_id: str) -> Optional[tuple[bytes, str, str]]:
    """Download a Drive file. Returns (bytes, filename, mime) or None."""
    client = get_drive_client(user_id)
    if client is None:
        return None
    try:
        meta = client.files().get(fileId=file_id, fields="id,name,mimeType").execute()
        name = meta.get("name", file_id)
        mime = meta.get("mimeType", "application/octet-stream")

        if mime.startswith("application/vnd.google-apps"):
            export_mime = {
                "application/vnd.google-apps.spreadsheet": "text/csv",
                "application/vnd.google-apps.document": "text/plain",
            }.get(mime, "application/pdf")
            data = client.files().export(fileId=file_id, mimeType=export_mime).execute()
            return data, name, export_mime

        data = client.files().get_media(fileId=file_id).execute()
        return data, name, mime
    except Exception as exc:
        logger.warning("Drive download failed: %s", exc)
        return None
