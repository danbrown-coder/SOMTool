"""Send emails via Gmail SMTP."""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def _gmail_configured() -> bool:
    return bool(os.environ.get("GMAIL_ADDRESS") and os.environ.get("GMAIL_APP_PASSWORD"))


def send_email(to: str, subject: str, body: str, reply_to: str = "", sender_name: str = "") -> dict:
    """Send a single email via Gmail SMTP.

    Returns {"ok": True} on success or {"ok": False, "error": "..."} on failure.
    """
    sender = os.environ.get("GMAIL_ADDRESS", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not sender or not password:
        return {"ok": False, "error": "Gmail credentials not configured"}

    msg = MIMEMultipart("alternative")
    if sender_name:
        msg["From"] = f"{sender_name} <{sender}>"
    else:
        msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to

    msg.attach(MIMEText(body, "plain", "utf-8"))

    html_body = body.replace("\n", "<br>")
    html = f"""\
<html><body style="font-family:Inter,Arial,sans-serif;font-size:14px;color:#1a1a1a;line-height:1.6;">
{html_body}
</body></html>"""
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        return {"ok": True}
    except smtplib.SMTPAuthenticationError:
        return {"ok": False, "error": "Gmail authentication failed — check App Password"}
    except smtplib.SMTPRecipientsRefused:
        return {"ok": False, "error": f"Recipient rejected: {to}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def send_batch(emails: list[dict], reply_to: str = "", sender_name: str = "") -> list[dict]:
    """Send a batch of emails. Each dict needs: recipient_email, subject, body.

    Returns list of results with recipient info + ok/error.
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
        result = send_email(to, subject, body, reply_to=reply_to, sender_name=sender_name)
        result["recipient_name"] = name
        result["recipient_email"] = to
        results.append(result)
    return results
