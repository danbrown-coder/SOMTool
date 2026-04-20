"""Per-event integration cards powering the event Settings tab.

`event_integrations(user_id, event)` returns a list of card descriptors that
[templates/partials/_event_integration_card.html](templates/partials/_event_integration_card.html)
renders. Each card knows:

    - slug / display_name / icon
    - state: "connected" | "server_not_configured" | "not_connected"
    - summary line shown when collapsed
    - actions: list of {"label", "url", "method", "primary"} dicts
    - external_link (optional): "View in Eventbrite →" style link

The helper is deliberately dependency-light: it never executes a provider call
synchronously — it just inspects env + connections + the event's stored
`external_objects` to decide which buttons to show. Actual provider calls happen
when the user clicks an action (routed through `app.event_integration_action`).
"""
from __future__ import annotations

import logging
import os
from typing import Any

from flask import url_for

from integrations import list_user_connections, get_provider

logger = logging.getLogger(__name__)


# ── Per-provider card builders ───────────────────────────────


def _ext_objects_for(event, provider: str) -> list[dict]:
    """Best-effort lookup of external_objects rows tied to this event+provider.
    Returns a list of detached plain dicts so the template can consume them
    after the session closes. Returns [] on any error.
    """
    try:
        from db import get_session
        from db_models import ExternalObject  # type: ignore
        with get_session() as sess:
            rows = (
                sess.query(ExternalObject)
                .filter(
                    ExternalObject.provider == provider,
                    ExternalObject.entity_type == "event",
                    ExternalObject.entity_id == event.id,
                )
                .all()
            )
            return [
                {
                    "external_id": r.external_id,
                    "external_url": (r.meta or {}).get("external_url") or "",
                }
                for r in rows
            ]
    except Exception:
        return []


def _connected_slugs(user_id: str) -> set[str]:
    try:
        return {c.provider for c in list_user_connections(user_id)}
    except Exception:
        return set()


def _server_configured(slug: str) -> bool:
    spec = get_provider(slug)
    return bool(spec and spec.configured())


def _action_url(event_id: str, provider: str, action: str) -> str:
    return url_for("event_integration_action", event_id=event_id, provider=provider, action=action)


# Descriptor for each provider: (title, icon, category label, default action, summary).
# Drives both connected- and empty-state rendering.
PROVIDER_CARDS: list[dict] = [
    {
        "slug": "eventbrite",
        "title": "Eventbrite",
        "icon_char": "EB",
        "category": "Ticketing",
        "unlocks": "Publish this event for ticketing and pull the attendee list back.",
        "connected_summary": "Publish to Eventbrite + auto-import RSVPs.",
        "primary_label": "Publish to Eventbrite",
        "action": "publish",
        "external_domain": "https://www.eventbrite.com",
    },
    {
        "slug": "luma",
        "title": "Luma",
        "icon_char": "L",
        "category": "Ticketing",
        "unlocks": "Create a Luma event and pull its guest list back.",
        "connected_summary": "Publish to Luma + sync guest list.",
        "primary_label": "Publish to Luma",
        "action": "publish",
        "external_domain": "https://lu.ma",
    },
    {
        "slug": "wallet",
        "title": "Apple / Google Wallet",
        "icon_char": "W",
        "category": "Ticketing",
        "unlocks": "Issue tappable wallet passes for confirmed RSVPs.",
        "connected_summary": "Issue wallet passes; QR check-in at the door.",
        "primary_label": "Issue wallet passes",
        "action": "issue_passes",
    },
    {
        "slug": "canvas",
        "title": "Canvas LMS",
        "icon_char": "C",
        "category": "Campus",
        "unlocks": "Post an announcement to a course feed.",
        "connected_summary": "Post an announcement to any of your courses.",
        "primary_label": "Post announcement…",
        "action": "post_announcement",
    },
    {
        "slug": "twentyfivelive",
        "title": "25Live / EMS",
        "icon_char": "25",
        "category": "Campus",
        "unlocks": "Check room availability without leaving the event form.",
        "connected_summary": "Check room availability for this event.",
        "primary_label": "Check availability",
        "action": "check_availability",
    },
    {
        "slug": "discord",
        "title": "Discord",
        "icon_char": "Dc",
        "category": "Messaging",
        "unlocks": "Post an event card to a server channel.",
        "connected_summary": "Drop an event card into a channel.",
        "primary_label": "Post event card",
        "action": "post_message",
    },
    {
        "slug": "whatsapp",
        "title": "WhatsApp Business",
        "icon_char": "Wa",
        "category": "Messaging",
        "unlocks": "Blast opted-in contacts with a 24h/1h reminder.",
        "connected_summary": "Blast WhatsApp reminders to opted-in contacts.",
        "primary_label": "Send reminders",
        "action": "blast_reminders",
    },
    {
        "slug": "hubspot",
        "title": "HubSpot",
        "icon_char": "HS",
        "category": "CRM",
        "unlocks": "Sync event attendees to HubSpot contacts + timeline.",
        "connected_summary": "Sync attendees → HubSpot contacts.",
        "primary_label": "Sync attendees",
        "action": "sync_attendees",
    },
    {
        "slug": "salesforce",
        "title": "Salesforce",
        "icon_char": "SF",
        "category": "CRM",
        "unlocks": "Upsert attendees as Salesforce contacts + campaign members.",
        "connected_summary": "Sync attendees → Salesforce.",
        "primary_label": "Sync attendees",
        "action": "sync_attendees",
    },
    {
        "slug": "mailchimp",
        "title": "Mailchimp",
        "icon_char": "MC",
        "category": "CRM",
        "unlocks": "Mirror attendees to your Mailchimp audience.",
        "connected_summary": "Mirror attendees → Mailchimp audience.",
        "primary_label": "Sync to audience",
        "action": "sync_audience",
    },
    {
        "slug": "notion",
        "title": "Notion",
        "icon_char": "N",
        "category": "Ops",
        "unlocks": "Spin up a run-of-show page with the SOMTool dashboard embedded.",
        "connected_summary": "Create a Notion run-of-show page.",
        "primary_label": "Create run-of-show",
        "action": "create_run_of_show",
    },
    {
        "slug": "airtable",
        "title": "Airtable",
        "icon_char": "At",
        "category": "Ops",
        "unlocks": "Mirror this event + its attendees to your Airtable base.",
        "connected_summary": "Mirror to Airtable base.",
        "primary_label": "Mirror to Airtable",
        "action": "mirror",
    },
    {
        "slug": "linear",
        "title": "Linear",
        "icon_char": "Ln",
        "category": "Ops",
        "unlocks": "Seed an event-prep issue checklist in Linear.",
        "connected_summary": "Seed an issue checklist in Linear.",
        "primary_label": "Seed issues",
        "action": "seed_issues",
    },
    {
        "slug": "asana",
        "title": "Asana",
        "icon_char": "As",
        "category": "Ops",
        "unlocks": "Seed an event-prep task list in Asana.",
        "connected_summary": "Seed an event-prep task list.",
        "primary_label": "Seed tasks",
        "action": "seed_tasks",
    },
    {
        "slug": "canva",
        "title": "Canva",
        "icon_char": "Cv",
        "category": "Promote",
        "unlocks": "Generate a flyer from an org template.",
        "connected_summary": "Generate an event flyer.",
        "primary_label": "Make flyer",
        "action": "make_flyer",
    },
    {
        "slug": "buffer",
        "title": "Buffer",
        "icon_char": "Bf",
        "category": "Promote",
        "unlocks": "Schedule a multi-network promo cadence.",
        "connected_summary": "Schedule a multi-network promo cadence.",
        "primary_label": "Schedule promo",
        "action": "schedule_promo",
    },
    {
        "slug": "meta_graph",
        "title": "Instagram + Facebook",
        "icon_char": "Me",
        "category": "Promote",
        "unlocks": "Post an event promo to an FB Page and IG Business profile.",
        "connected_summary": "Post promo to FB Page + IG Business.",
        "primary_label": "Post promo",
        "action": "post_promo",
    },
    {
        "slug": "linkedin_pages",
        "title": "LinkedIn Pages",
        "icon_char": "Li",
        "category": "Promote",
        "unlocks": "Publish an org-page post about this event.",
        "connected_summary": "Publish an org-page post.",
        "primary_label": "Publish post",
        "action": "post_linkedin",
    },
]


def event_integrations(user_id: str, event) -> list[dict]:
    """Build the per-event integration card list for the Settings tab.

    Returns cards in three buckets, ordered: connected first, then
    "configured-but-not-connected", then hidden-but-installed providers roll up
    into a single "more" footer card rendered by the template.
    """
    connected = _connected_slugs(user_id)
    cards: list[dict] = []

    for tpl in PROVIDER_CARDS:
        slug = tpl["slug"]
        spec = get_provider(slug)
        if spec is None:
            continue

        is_connected = slug in connected
        is_server_ok = spec.configured()

        if is_connected:
            state = "connected"
        elif not is_server_ok:
            state = "server_not_configured"
        else:
            state = "not_connected"

        # Lookup any external_objects row so we can flip the primary action to
        # "Open in X" once there's an external link.
        external_id = None
        external_url = None
        for row in _ext_objects_for(event, slug):
            external_url = row.get("external_url")
            external_id = row.get("external_id")
            if external_url:
                break

        card: dict = {
            "slug": slug,
            "title": tpl["title"],
            "icon_char": tpl["icon_char"],
            "category": tpl["category"],
            "unlocks": tpl["unlocks"],
            "summary": tpl["connected_summary"] if is_connected else tpl["unlocks"],
            "state": state,
            "docs_url": getattr(spec, "docs_url", ""),
            "connect_url": url_for("integration_connect", provider=slug) + "?next=" + url_for("event_detail", event_id=event.id, tab="settings"),
            "actions": [],
            "external_id": external_id,
            "external_url": external_url,
        }

        if is_connected:
            if external_url:
                card["actions"].append({
                    "label": "Open in " + tpl["title"].split(" ")[0],
                    "url": external_url,
                    "method": "GET",
                    "primary": True,
                    "external": True,
                })
                card["actions"].append({
                    "label": "Re-sync",
                    "url": _action_url(event.id, slug, tpl["action"]),
                    "method": "POST",
                    "primary": False,
                })
            else:
                card["actions"].append({
                    "label": tpl["primary_label"],
                    "url": _action_url(event.id, slug, tpl["action"]),
                    "method": "POST",
                    "primary": True,
                })
        cards.append(card)

    # Connected first → configured → not configured.
    order = {"connected": 0, "not_connected": 1, "server_not_configured": 2}
    cards.sort(key=lambda c: (order.get(c["state"], 9), c["title"].lower()))
    return cards


# ── Action dispatch ───────────────────────────────────────────


def run_action(user_id: str, event, provider: str, action: str, form: dict) -> tuple[bool, str]:
    """Execute the server-side effect for a card action.

    Returns `(ok, message)` where `message` is a short, human-readable status
    suitable for `flash()`.

    This intentionally delegates to the existing provider adapters — no new
    API logic lives in this module. Unknown provider/action combinations
    return a "coming soon" message rather than 500'ing.
    """
    # Every path below assumes the user has an active connection; the adapters
    # themselves re-check and return None if not. We keep the try/except wide
    # so a single broken provider can't take out the Settings tab.
    try:
        if provider == "eventbrite" and action == "publish":
            from integrations.providers import eventbrite as _eb
            ext_id = _eb.create_event(user_id, event)
            if ext_id:
                _record_external(event.id, provider, ext_id, external_url=f"https://www.eventbrite.com/myevent?eid={ext_id}")
                return True, "Published to Eventbrite."
            return False, "Eventbrite did not accept the event (check the console for details)."

        if provider == "luma" and action == "publish":
            from integrations.providers import luma as _lu
            ext_id = _lu.create_event(event.name, event.starts_at or event.date or "", event.ends_at or event.date or "", getattr(event, "description", "") or "")
            if ext_id:
                _record_external(event.id, provider, ext_id, external_url=f"https://lu.ma/{ext_id}")
                return True, "Published to Luma."
            return False, "Luma did not accept the event."

        if provider == "canvas" and action == "post_announcement":
            from integrations.providers import canvas as _cv
            client = _cv.CanvasClient.for_user(user_id)
            if client is None:
                return False, "Canvas is not connected."
            course_id = int(form.get("course_id") or 0)
            if not course_id:
                return False, "Pick a course first."
            res = client.post_announcement(course_id, event.name, getattr(event, "description", "") or event.name)
            return (True, "Announcement posted to Canvas.") if res else (False, "Canvas rejected the announcement.")

        if provider == "notion" and action == "create_run_of_show":
            from integrations.providers import notion as _no
            parent = form.get("parent_page_id") or ""
            if not parent:
                return False, "Paste a parent Notion page ID first."
            ext_id = _no.create_run_of_show(user_id, parent, event)
            if ext_id:
                _record_external(event.id, provider, ext_id, external_url=f"https://www.notion.so/{ext_id.replace('-', '')}")
                return True, "Run-of-show page created in Notion."
            return False, "Notion did not create the page."

        if provider == "airtable" and action == "mirror":
            from integrations.providers import airtable as _at
            fields = {"Name": event.name, "Date": event.date, "Audience": event.audience_type}
            ext_id = _at.upsert_row("Events", fields, merge_field="Name")
            return (True, "Mirrored to Airtable.") if ext_id else (False, "Airtable rejected the upsert.")

        if provider == "linear" and action == "seed_issues":
            from integrations.providers import linear as _ln
            ext_id = _ln.create_issue(f"Event prep: {event.name}", f"Auto-seeded by SOMTool for event {event.id}.")
            return (True, "Linear issue created.") if ext_id else (False, "Linear did not create the issue.")

        if provider == "asana" and action == "seed_tasks":
            from integrations.providers import asana as _as
            ext_id = _as.create_task(f"Event prep: {event.name}", due_on=event.date or "")
            return (True, "Asana task created.") if ext_id else (False, "Asana did not create the task.")

        if provider == "discord" and action == "post_message":
            from integrations.providers import discord as _dc
            channel_id = form.get("channel_id") or ""
            if not channel_id:
                return False, "Paste a channel ID."
            msg = f"**{event.name}** — {event.date or 'TBA'}"
            res = _dc.post_channel_message(channel_id, msg)
            return (True, "Posted to Discord channel.") if res else (False, "Discord post failed.")

        if provider == "whatsapp" and action == "blast_reminders":
            # Marked advisory — real implementation would page through opted-in contacts.
            return True, "Queued WhatsApp reminders (placeholder)."

        if provider == "hubspot" and action == "sync_attendees":
            from integrations.providers import hubspot as _hs
            synced = 0
            for c in getattr(event, "contacts", []) or []:
                if _hs.upsert_contact(user_id, c):
                    synced += 1
            return True, f"Synced {synced} attendee(s) to HubSpot."

        if provider == "salesforce" and action == "sync_attendees":
            from integrations.providers import salesforce as _sf
            synced = 0
            for c in getattr(event, "contacts", []) or []:
                if _sf.upsert_contact(user_id, c):
                    synced += 1
            return True, f"Synced {synced} attendee(s) to Salesforce."

        if provider == "wallet" and action == "issue_passes":
            if not (os.environ.get("APPLE_WALLET_PASS_TYPE_IDENTIFIER") or os.environ.get("GOOGLE_WALLET_ISSUER_ID")):
                return False, "Wallet pass signing isn't configured server-side."
            return True, "Wallet passes queued for confirmed RSVPs (placeholder)."

        if provider == "twentyfivelive" and action == "check_availability":
            return True, "Opened 25Live availability (placeholder)."

        return False, f"{provider} → {action} isn't wired up yet."
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("event_action %s/%s failed: %s", provider, action, exc)
        return False, f"{provider} raised an error: {exc}"


def _record_external(event_id: str, provider: str, external_id: str, external_url: str = "") -> None:
    """Persist an external_objects row so the card flips to 'Open in X' next time."""
    try:
        from db import get_session
        from db_models import ExternalObject  # type: ignore
        from org_manager import current_org_id
        org_id = current_org_id() or ""
        with get_session() as sess:
            row = (
                sess.query(ExternalObject)
                .filter(
                    ExternalObject.provider == provider,
                    ExternalObject.entity_type == "event",
                    ExternalObject.entity_id == event_id,
                )
                .first()
            )
            meta = {"external_url": external_url} if external_url else {}
            if row is None:
                row = ExternalObject(
                    org_id=org_id,
                    entity_type="event",
                    entity_id=event_id,
                    provider=provider,
                    external_id=external_id,
                    meta=meta,
                )
                sess.add(row)
            else:
                row.external_id = external_id
                merged = dict(row.meta or {})
                if external_url:
                    merged["external_url"] = external_url
                row.meta = merged
    except Exception as exc:
        logger.warning("Could not persist external_object for %s: %s", provider, exc)
