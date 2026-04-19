"""Google OAuth provider + API client helpers.

Phase A of the integrations plan makes Google the product's default layer.
One consent grants seven scopes; each surface (Calendar/Meet, Gmail send-as,
Drive Picker, Sheets sync, Forms import, Contacts sync, Sign-in) is wired
directly into the SOMTool UI instead of sitting behind a Hub tile.
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


# ── Scope groups — user can grant the base set and opt into more later ──

SCOPE_IDENTITY = ["openid", "email", "profile"]
SCOPE_CALENDAR = ["https://www.googleapis.com/auth/calendar"]
SCOPE_GMAIL    = ["https://www.googleapis.com/auth/gmail.send"]
SCOPE_DRIVE    = ["https://www.googleapis.com/auth/drive.readonly"]
SCOPE_SHEETS   = ["https://www.googleapis.com/auth/spreadsheets"]
SCOPE_FORMS    = ["https://www.googleapis.com/auth/forms.responses.readonly"]
SCOPE_CONTACTS = ["https://www.googleapis.com/auth/contacts"]

GOOGLE_SCOPES = (
    SCOPE_IDENTITY
    + SCOPE_CALENDAR
    + SCOPE_GMAIL
    + SCOPE_DRIVE
    + SCOPE_SHEETS
    + SCOPE_FORMS
    + SCOPE_CONTACTS
)


SCOPE_GROUPS = {
    "calendar": SCOPE_CALENDAR,
    "gmail":    SCOPE_GMAIL,
    "drive":    SCOPE_DRIVE,
    "sheets":   SCOPE_SHEETS,
    "forms":    SCOPE_FORMS,
    "contacts": SCOPE_CONTACTS,
}


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
    display_name="Google Workspace",
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
    description="Sign in, sync Calendar+Meet, send as you from Gmail, import from Drive, two-way Sheets, Forms, and Contacts.",
    category="identity",
    unlocks=[
        "One-click Sign in with Google",
        "Calendar + Meet baked into the Outreach Calendar",
        "Send outreach as you (Gmail), Drive Picker, Sheets sync, Forms import, Contacts sync",
    ],
    is_default=True,
    auth_style="oauth2",
    docs_url="https://developers.google.com/identity/protocols/oauth2",
)


register_provider(SPEC)


# ── Scope-gap helpers (progressive consent) ──


def connection_for(user_id: str):
    from integrations import get_connection
    return get_connection(user_id, SPEC.slug)


def has_scope_group(user_id: str, group: str) -> bool:
    """Does this user have all scopes for `group` (calendar/gmail/...)?"""
    scopes = SCOPE_GROUPS.get(group)
    if not scopes:
        return False
    conn = connection_for(user_id)
    if conn is None:
        return False
    granted = set(conn.scopes or [])
    return all(s in granted for s in scopes)


def missing_scope_groups(user_id: str) -> list[str]:
    """Which scope groups (calendar/gmail/...) has the user *not* granted?"""
    return [g for g in SCOPE_GROUPS if not has_scope_group(user_id, g)]


def scope_group_granted_map(user_id: str) -> dict[str, bool]:
    return {g: has_scope_group(user_id, g) for g in SCOPE_GROUPS}


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


def _build_client(user_id: str, api: str, version: str):
    creds = _credentials_for(user_id)
    if creds is None:
        return None
    try:
        from googleapiclient.discovery import build
    except ImportError:
        return None
    return build(api, version, credentials=creds, cache_discovery=False)


def get_calendar_client(user_id: str):   return _build_client(user_id, "calendar", "v3")
def get_drive_client(user_id: str):      return _build_client(user_id, "drive", "v3")
def get_gmail_client(user_id: str):      return _build_client(user_id, "gmail", "v1")
def get_sheets_client(user_id: str):     return _build_client(user_id, "sheets", "v4")
def get_forms_client(user_id: str):      return _build_client(user_id, "forms", "v1")
def get_people_client(user_id: str):     return _build_client(user_id, "people", "v1")


# ── Gmail send-as ──────────────────────────────────────────


def send_gmail_as_user(
    user_id: str, to: str, subject: str, body: str,
    reply_to: str = "", sender_name: str = "",
) -> Optional[dict]:
    """Send via Gmail as the logged-in user. Returns a dict compatible with
    email_sender.send_email's contract, or None if the user has no Google
    connection (so the caller can fall back to Resend/SMTP).
    """
    if not user_id or not has_scope_group(user_id, "gmail"):
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


# ── Calendar + Meet sync (two-way) ─────────────────────────


def _event_to_gcal_body(event) -> dict:
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    event_date = (event.date or "").strip()
    body = {
        "summary": event.name or "Event",
        "description": event.description or "",
        "attendees": [
            {"email": c.email, "displayName": c.name or c.email}
            for c in getattr(event, "contacts", [])
            if c.email and getattr(c, "status", None) and (
                c.status.value if hasattr(c.status, "value") else str(c.status)
            ) == "confirmed"
        ],
        # Ask Google to auto-create a Meet link for us.
        "conferenceData": {
            "createRequest": {
                "requestId": f"somtool-{event.id}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    try:
        start = _dt.fromisoformat(event_date.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=_tz.utc)
        end = start + _td(hours=1)
        body["start"] = {"dateTime": start.isoformat()}
        body["end"] = {"dateTime": end.isoformat()}
    except ValueError:
        body["start"] = {"date": event_date[:10] or _dt.utcnow().date().isoformat()}
        body["end"] = {"date": event_date[:10] or _dt.utcnow().date().isoformat()}
    return body


def sync_event_to_calendar(user_id: str, event) -> Optional[str]:
    """Create (or update) a Google Calendar event matching a SOMTool event.
    Also auto-provisions a Meet link the first time.

    Returns the gcal event id. Persists `gcal_event_id` on the Event row and
    stashes the Meet URL in `meta.meet_url` via ExternalObject.
    """
    if not has_scope_group(user_id, "calendar"):
        return None
    client = get_calendar_client(user_id)
    if client is None:
        return None
    try:
        body = _event_to_gcal_body(event)
        existing_id = getattr(event, "gcal_event_id", None)
        if existing_id:
            result = (
                client.events()
                .update(
                    calendarId="primary",
                    eventId=existing_id,
                    body=body,
                    conferenceDataVersion=1,
                    sendUpdates="none",
                )
                .execute()
            )
        else:
            result = (
                client.events()
                .insert(
                    calendarId="primary",
                    body=body,
                    conferenceDataVersion=1,
                    sendUpdates="none",
                )
                .execute()
            )
        gcal_id = result.get("id")
        meet_url = ""
        for ep in (result.get("conferenceData", {}) or {}).get("entryPoints", []) or []:
            if ep.get("entryPointType") == "video":
                meet_url = ep.get("uri", "")
                break

        if gcal_id:
            from db import get_session
            from db_models import Event as EventRow
            with get_session() as sess:
                row = sess.get(EventRow, event.id)
                if row is not None:
                    row.gcal_event_id = gcal_id
            try:
                from integrations.sync import set_external_id
                from org_manager import current_org_id
                set_external_id(
                    org_id=current_org_id(),
                    entity_type="event",
                    entity_id=event.id,
                    provider="google",
                    external_id=gcal_id,
                    meta={"meet_url": meet_url, "html_link": result.get("htmlLink", "")},
                )
            except Exception:  # pragma: no cover
                pass
        return gcal_id
    except Exception as exc:
        logger.warning("Calendar sync failed: %s", exc)
        return None


def delete_event_from_calendar(user_id: str, gcal_event_id: str) -> bool:
    if not gcal_event_id or not has_scope_group(user_id, "calendar"):
        return False
    client = get_calendar_client(user_id)
    if client is None:
        return False
    try:
        client.events().delete(
            calendarId="primary", eventId=gcal_event_id, sendUpdates="none"
        ).execute()
        return True
    except Exception as exc:
        logger.warning("Calendar delete failed: %s", exc)
        return False


def list_user_calendar_events(user_id: str, time_min_iso: str, time_max_iso: str) -> list[dict]:
    """Return the raw GCal events in a window so the Outreach Calendar can
    overlay the user's real calendar alongside SOMTool events.
    """
    if not has_scope_group(user_id, "calendar"):
        return []
    client = get_calendar_client(user_id)
    if client is None:
        return []
    try:
        resp = (
            client.events()
            .list(
                calendarId="primary",
                timeMin=time_min_iso,
                timeMax=time_max_iso,
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
            )
            .execute()
        )
        return list(resp.get("items", []))
    except Exception as exc:
        logger.warning("Calendar list failed: %s", exc)
        return []


# ── Drive Picker ────────────────────────────────────────────


def download_drive_file(user_id: str, file_id: str) -> Optional[tuple[bytes, str, str]]:
    """Download a Drive file. Returns (bytes, filename, mime) or None."""
    if not has_scope_group(user_id, "drive"):
        return None
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


# ── Sheets two-way sync ────────────────────────────────────


def read_sheet_rows(user_id: str, spreadsheet_id: str, sheet_range: str = "A1:Z1000") -> list[list[str]]:
    """Read raw rows from a Google Sheet range."""
    if not has_scope_group(user_id, "sheets"):
        return []
    client = get_sheets_client(user_id)
    if client is None:
        return []
    try:
        resp = (
            client.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=sheet_range)
            .execute()
        )
        return resp.get("values", [])
    except Exception as exc:
        logger.warning("Sheet read failed: %s", exc)
        return []


def write_sheet_rows(
    user_id: str,
    spreadsheet_id: str,
    values: list[list],
    sheet_range: str = "A1",
) -> bool:
    """Overwrite a sheet range with `values`."""
    if not has_scope_group(user_id, "sheets"):
        return False
    client = get_sheets_client(user_id)
    if client is None:
        return False
    try:
        client.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=sheet_range,
            valueInputOption="RAW",
            body={"values": values},
        ).execute()
        return True
    except Exception as exc:
        logger.warning("Sheet write failed: %s", exc)
        return False


def export_people_to_sheet(user_id: str, spreadsheet_id: str, people: list) -> bool:
    """Push the SOMTool people list to a Google Sheet (one row per person)."""
    header = ["id", "name", "email", "company", "role", "phone", "linkedin_url", "tags", "source"]
    rows: list[list] = [header]
    for p in people:
        rows.append([
            getattr(p, "id", ""),
            getattr(p, "name", ""),
            getattr(p, "email", ""),
            getattr(p, "company", ""),
            getattr(p, "role", ""),
            getattr(p, "phone", ""),
            getattr(p, "linkedin_url", ""),
            ", ".join(getattr(p, "tags", []) or []),
            getattr(p, "source", ""),
        ])
    return write_sheet_rows(user_id, spreadsheet_id, rows, sheet_range="A1")


def import_people_from_sheet(user_id: str, spreadsheet_id: str) -> list[dict]:
    """Read a Sheet whose first row is a header; return list-of-dicts."""
    rows = read_sheet_rows(user_id, spreadsheet_id)
    if not rows:
        return []
    header = [str(c).strip().lower() for c in rows[0]]
    out: list[dict] = []
    for raw in rows[1:]:
        padded = list(raw) + [""] * (len(header) - len(raw))
        out.append({header[i]: padded[i] for i in range(len(header))})
    return out


# ── Forms import ───────────────────────────────────────────


def list_form_responses(user_id: str, form_id: str) -> list[dict]:
    """Return the responses for a Google Form in a flattened format."""
    if not has_scope_group(user_id, "forms"):
        return []
    client = get_forms_client(user_id)
    if client is None:
        return []
    try:
        form = client.forms().get(formId=form_id).execute()
        items = {
            i.get("itemId"): (i.get("title") or i.get("questionItem", {}).get("question", {}).get("questionId", ""))
            for i in form.get("items", [])
            if i.get("itemId")
        }
        resp = client.forms().responses().list(formId=form_id).execute()
        out: list[dict] = []
        for r in resp.get("responses", []) or []:
            flat: dict = {
                "_response_id": r.get("responseId"),
                "_submitted_at": r.get("lastSubmittedTime") or r.get("createTime"),
                "_respondent_email": r.get("respondentEmail", ""),
            }
            for item_id, answer in (r.get("answers") or {}).items():
                title = items.get(item_id) or item_id
                text_answers = (answer.get("textAnswers") or {}).get("answers") or []
                flat[title] = ", ".join(a.get("value", "") for a in text_answers)
            out.append(flat)
        return out
    except Exception as exc:
        logger.warning("Forms list failed: %s", exc)
        return []


# ── Contacts sync ──────────────────────────────────────────


def upsert_person_to_google_contacts(user_id: str, person) -> Optional[str]:
    """Mirror one SOMTool Person to the user's Google Contacts.
    Returns the Google resourceName, or None if unavailable.
    """
    if not has_scope_group(user_id, "contacts"):
        return None
    client = get_people_client(user_id)
    if client is None:
        return None
    try:
        body = {
            "names": [{"givenName": person.name or ""}] if person.name else [],
            "emailAddresses": [{"value": person.email}] if person.email else [],
            "phoneNumbers": [{"value": person.phone}] if person.phone else [],
            "organizations": [{"name": person.company, "title": person.role}] if person.company else [],
        }
        result = client.people().createContact(body=body).execute()
        return result.get("resourceName")
    except Exception as exc:
        logger.warning("People createContact failed: %s", exc)
        return None
