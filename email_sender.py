"""Transactional email sender.

Primary: Resend API (https://resend.com). Selected via `EMAIL_PROVIDER=resend`.
Fallback: Gmail SMTP (legacy). Selected via `EMAIL_PROVIDER=gmail`.

The `send_email` signature is identical to the original Gmail-only version
so nothing upstream changes. When a user is logged in and has connected
their Google account (Phase 5), Gmail send-as takes precedence over both.
"""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import observability


def _provider() -> str:
    return (os.environ.get("EMAIL_PROVIDER") or "resend").strip().lower()


def _resend_configured() -> bool:
    return bool(os.environ.get("RESEND_API_KEY"))


def _gmail_configured() -> bool:
    return bool(os.environ.get("GMAIL_ADDRESS") and os.environ.get("GMAIL_APP_PASSWORD"))


def _build_html(body: str) -> str:
    html_body = body.replace("\n", "<br>")
    return f"""<html><body style="font-family:Inter,Arial,sans-serif;font-size:14px;color:#1a1a1a;line-height:1.6;">
{html_body}
</body></html>"""


def _send_via_gmail(to: str, subject: str, body: str, reply_to: str, sender_name: str) -> dict:
    sender = os.environ.get("GMAIL_ADDRESS", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not sender or not password:
        return {"ok": False, "error": "Gmail credentials not configured"}

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{sender_name} <{sender}>" if sender_name else sender
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.attach(MIMEText(body, "plain", "utf-8"))
    msg.attach(MIMEText(_build_html(body), "html", "utf-8"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        return {"ok": True, "provider": "gmail"}
    except smtplib.SMTPAuthenticationError:
        return {"ok": False, "error": "Gmail authentication failed — check App Password"}
    except smtplib.SMTPRecipientsRefused:
        return {"ok": False, "error": f"Recipient rejected: {to}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def _send_via_resend(to: str, subject: str, body: str, reply_to: str, sender_name: str) -> dict:
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_hdr = os.environ.get("RESEND_FROM", "").strip()
    if not api_key or not from_hdr:
        return {"ok": False, "error": "Resend not configured (RESEND_API_KEY / RESEND_FROM)"}

    # If a per-event sender name is provided and RESEND_FROM is a bare email,
    # prefix the display name.
    if sender_name and "<" not in from_hdr and "@" in from_hdr:
        from_hdr = f"{sender_name} <{from_hdr}>"

    try:
        import resend

        resend.api_key = api_key
        payload: dict = {
            "from": from_hdr,
            "to": [to],
            "subject": subject,
            "html": _build_html(body),
            "text": body,
        }
        rt = reply_to or os.environ.get("RESEND_REPLY_TO", "")
        if rt:
            payload["reply_to"] = rt
        result = resend.Emails.send(payload)  # raises on failure
        return {"ok": True, "provider": "resend", "provider_message_id": result.get("id")}
    except ImportError:
        return {"ok": False, "error": "resend package not installed"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def _send_via_user_gmail(
    user_id: str, to: str, subject: str, body: str, reply_to: str, sender_name: str
) -> Optional[dict]:
    """Phase 5: if the caller has a Google connection with gmail.send scope,
    send as them. Returns None if not applicable so the caller can fall back.
    """
    try:
        from integrations.google import send_gmail_as_user  # lazy import
    except ImportError:
        return None
    try:
        return send_gmail_as_user(
            user_id=user_id, to=to, subject=subject, body=body,
            reply_to=reply_to, sender_name=sender_name,
        )
    except Exception as exc:  # pragma: no cover
        observability.capture_exception(exc)
        return None


def send_email(
    to: str,
    subject: str,
    body: str,
    reply_to: str = "",
    sender_name: str = "",
    as_user_id: str | None = None,
) -> dict:
    """Send a single email.

    Priority:
      1. If `as_user_id` is given and that user has Gmail connected, send as them.
      2. Resend (default).
      3. Gmail SMTP fallback.

    Returns {"ok": True, "provider": "...", "provider_message_id": "..."} on success,
    else {"ok": False, "error": "..."}.
    """
    if as_user_id:
        via_user = _send_via_user_gmail(as_user_id, to, subject, body, reply_to, sender_name)
        if via_user is not None:
            return via_user

    provider = _provider()
    if provider == "gmail":
        return _send_via_gmail(to, subject, body, reply_to, sender_name)
    if _resend_configured():
        result = _send_via_resend(to, subject, body, reply_to, sender_name)
        if result.get("ok"):
            return result
        if _gmail_configured():
            fallback = _send_via_gmail(to, subject, body, reply_to, sender_name)
            if fallback.get("ok"):
                fallback["fallback_reason"] = result.get("error", "resend failed")
                return fallback
        return result
    if _gmail_configured():
        return _send_via_gmail(to, subject, body, reply_to, sender_name)
    return {"ok": False, "error": "No email provider configured"}


def send_batch(
    emails: list[dict],
    reply_to: str = "",
    sender_name: str = "",
    as_user_id: str | None = None,
) -> list[dict]:
    """Send a batch of emails. Each dict needs: recipient_email, subject, body.

    Returns a list of results with recipient info + ok/error.
    """
    results = []
    for em in emails:
        to = em.get("recipient_email", "")
        subject = em.get("subject", "")
        body = em.get("body", "")
        name = em.get("recipient_name", to)
        if not to or "@" not in to:
            results.append({"recipient_name": name, "recipient_email": to, "ok": False, "error": "Invalid email"})
            continue
        result = send_email(
            to, subject, body,
            reply_to=reply_to, sender_name=sender_name, as_user_id=as_user_id,
        )
        result["recipient_name"] = name
        result["recipient_email"] = to
        results.append(result)
    return results
