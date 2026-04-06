"""Vapi AI voice calling integration."""
from __future__ import annotations

import os

import requests


def _vapi_configured() -> bool:
    return bool(os.environ.get("VAPI_API_KEY"))


def _call(
    assistant_id: str,
    phone_number_id: str,
    phone: str,
    variable_values: dict,
) -> dict:
    """Place an outbound call via Vapi API.

    Returns {"ok": True, "call_id": "...", "status": "..."} or {"ok": False, "error": "..."}.
    """
    api_key = os.environ.get("VAPI_API_KEY", "")
    if not api_key:
        return {"ok": False, "error": "VAPI_API_KEY not configured"}
    if not assistant_id:
        return {"ok": False, "error": "Assistant ID not configured"}
    if not phone:
        return {"ok": False, "error": "No phone number for this contact"}

    clean_phone = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not clean_phone.startswith("+"):
        clean_phone = "+1" + clean_phone

    payload = {
        "assistantId": assistant_id,
        "assistantOverrides": {
            "variableValues": variable_values,
        },
        "customer": {
            "number": clean_phone,
        },
    }
    if phone_number_id:
        payload["phoneNumberId"] = phone_number_id

    try:
        resp = requests.post(
            "https://api.vapi.ai/call/phone",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        data = resp.json() if resp.content else {}
        if resp.status_code in (200, 201):
            return {
                "ok": True,
                "call_id": data.get("id", ""),
                "status": data.get("status", "queued"),
            }
        error_msg = data.get("message") or data.get("error") or resp.text[:200]
        return {"ok": False, "error": f"Vapi {resp.status_code}: {error_msg}"}
    except requests.Timeout:
        return {"ok": False, "error": "Vapi API timeout"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def call_invite(
    phone: str,
    recipient_name: str,
    event_name: str,
    event_date: str,
    contact_role: str = "attendee",
    company: str = "",
    title: str = "",
    background_notes: str = "",
) -> dict:
    """Place an outbound invite call."""
    assistant_id = os.environ.get("VAPI_INVITE_ASSISTANT_ID", "")
    phone_number_id = os.environ.get("VAPI_INVITE_PHONE_ID", "")
    return _call(
        assistant_id=assistant_id,
        phone_number_id=phone_number_id,
        phone=phone,
        variable_values={
            "recipientName": recipient_name,
            "eventName": event_name,
            "eventDate": event_date,
            "contactRole": contact_role.replace("_", " "),
            "company": company or "their organization",
            "title": title or "professional",
            "backgroundNotes": background_notes or "No additional background available",
        },
    )


def call_followup(
    phone: str,
    recipient_name: str,
    event_name: str,
    event_date: str,
    contact_role: str = "attendee",
    company: str = "",
    title: str = "",
    background_notes: str = "",
) -> dict:
    """Place an outbound follow-up call."""
    assistant_id = os.environ.get("VAPI_FOLLOWUP_ASSISTANT_ID", "")
    phone_number_id = os.environ.get("VAPI_FOLLOWUP_PHONE_ID", "")
    return _call(
        assistant_id=assistant_id,
        phone_number_id=phone_number_id,
        phone=phone,
        variable_values={
            "recipientName": recipient_name,
            "eventName": event_name,
            "eventDate": event_date,
            "contactRole": contact_role.replace("_", " "),
            "company": company or "their organization",
            "title": title or "professional",
            "backgroundNotes": background_notes or "No additional background available",
        },
    )
