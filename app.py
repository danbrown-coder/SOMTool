"""SOM Event Operating System — Flask entry point."""
from __future__ import annotations

import json
import os
import secrets
import threading
import time as _time
from datetime import date, datetime, timezone
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from models import ContactRole, ContactStatus, EmailType, new_id
from email_generator import (
    discover_prospects_from_text,
    generate_event_update_email,
    generate_followup_email,
    generate_initial_email,
    generate_referral_request_email,
    recommend_people_for_event,
)
import auth_manager as auth
import discover as disc
import email_sender
import event_manager as em
import logger as log
import people_import
import people_manager as pm
import scraper
import vapi_caller

load_dotenv()

app = Flask(__name__)


def _person_context_for_contact(contact) -> dict:
    """Look up background info from People DB for a contact, by email."""
    person = pm.find_by_email(contact.email)
    if not person:
        return {}
    return {
        "company": person.company or "",
        "title": person.role or "",
        "linkedin_url": person.linkedin_url or "",
        "tags": person.tags or [],
        "notes": person.notes or "",
    }


def _person_phone_for_contact(contact) -> str:
    """Get phone from contact itself or from People DB."""
    if contact.phone:
        return contact.phone
    person = pm.find_by_email(contact.email)
    return person.phone if person else ""
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(16))

_LEGACY_MIGRATED = False


@app.before_request
def _migrate_legacy_once():
    global _LEGACY_MIGRATED
    if _LEGACY_MIGRATED:
        return
    admin_id = auth.get_first_admin_id()
    if admin_id:
        em.migrate_legacy_event_ownership(admin_id)
    _LEGACY_MIGRATED = True


@app.context_processor
def inject_user():
    uid = auth.current_user_id()
    user = auth.get_user_by_id(uid) if uid else None
    return dict(current_user=user)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        uid = auth.current_user_id()
        if not uid:
            return redirect(url_for("login", next=request.path))
        user = auth.get_user_by_id(uid)
        if not user:
            auth.logout_user()
            return redirect(url_for("login"))
        g.current_user = user
        return view(*args, **kwargs)

    return wrapped


def _event_ended(event_date_str: str) -> bool:
    try:
        d = date.fromisoformat(event_date_str.strip()[:10])
        return d < date.today()
    except ValueError:
        return False


def _role_ok(role: str | None, need: str) -> bool:
    if not role:
        return False
    order = {"viewer": 0, "editor": 1, "owner": 2}
    return order.get(role, -1) >= order.get(need, 99)


# ── Auth (public) ───────────────────────────────────────────


@app.route("/login", methods=["GET", "POST"])
def login():
    if auth.current_user_id():
        return redirect(url_for("index"))
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        user = auth.verify_login(u, p)
        if user:
            auth.login_user(user)
            nxt = request.form.get("next") or request.args.get("next") or url_for("index")
            if not (
                isinstance(nxt, str)
                and nxt.startswith("/")
                and not nxt.startswith("//")
            ):
                nxt = url_for("index")
            return redirect(nxt)
        flash("Invalid username or password.", "info")
    return render_template("login.html", hide_sidebar=True)


@app.route("/register", methods=["GET", "POST"])
def register():
    if auth.current_user_id():
        return redirect(url_for("index"))
    if request.method == "POST":
        user = auth.register_user(
            request.form.get("username", ""),
            request.form.get("display_name", ""),
            request.form.get("email", ""),
            request.form.get("password", ""),
        )
        if user:
            auth.login_user(user)
            flash("Account created.", "info")
            return redirect(url_for("index"))
        flash("Username taken or invalid fields.", "info")
    return render_template("register.html", hide_sidebar=True)


@app.post("/logout")
def logout_route():
    auth.logout_user()
    return redirect(url_for("login"))


# ── Events ───────────────────────────────────────────────────


@app.route("/")
@login_required
def index():
    events = em.list_events_visible_to(g.current_user)
    events.sort(key=lambda e: e.date, reverse=True)
    roles = {e.id: em.get_event_share_role(g.current_user, e) or "viewer" for e in events}
    return render_template("index.html", events=events, event_roles=roles)


@app.post("/events")
@login_required
def create_event_route():
    name = request.form.get("name", "")
    event_date = request.form.get("date", "")
    description = request.form.get("description", "")
    audience = request.form.get("audience_type", "")
    if not name or not event_date:
        flash("Name and date are required.", "info")
        return redirect(url_for("index"))
    em.create_event(name, event_date, description, audience, owner_id=g.current_user.id)
    flash("Event created.", "info")
    return redirect(url_for("index"))


@app.route("/events/<event_id>/edit")
@login_required
def edit_event_page(event_id: str):
    event = em.get_event(event_id)
    if not event:
        flash("Event not found.", "info")
        return redirect(url_for("index"))
    role = em.get_event_share_role(g.current_user, event)
    if not _role_ok(role, "editor"):
        flash("You do not have permission to edit this event.", "info")
        return redirect(url_for("index"))
    return render_template("edit_event.html", event=event)


@app.post("/events/<event_id>/edit")
@login_required
def edit_event_route(event_id: str):
    event = em.get_event(event_id)
    role = em.get_event_share_role(g.current_user, event) if event else None
    if not event or not _role_ok(role, "editor"):
        flash("Not allowed.", "info")
        return redirect(url_for("index"))
    name = request.form.get("name", "")
    event_date = request.form.get("date", "")
    description = request.form.get("description", "")
    audience = request.form.get("audience_type", "")
    if not name or not event_date:
        flash("Name and date are required.", "info")
        return redirect(url_for("edit_event_page", event_id=event_id))
    em.update_event(event_id, name, event_date, description, audience)
    flash("Event updated.", "info")
    return redirect(url_for("index"))


@app.post("/events/<event_id>/delete")
@login_required
def delete_event_route(event_id: str):
    event = em.get_event(event_id)
    role = em.get_event_share_role(g.current_user, event) if event else None
    if not event or role != "owner":
        flash("Only the owner can delete this event.", "info")
        return redirect(url_for("index"))
    if em.delete_event(event_id):
        flash("Event deleted.", "info")
    else:
        flash("Event not found.", "info")
    return redirect(url_for("index"))


@app.route("/events/<event_id>/share", methods=["GET", "POST"])
@login_required
def share_event_page(event_id: str):
    event = em.get_event(event_id)
    role = em.get_event_share_role(g.current_user, event) if event else None
    if not event or role != "owner":
        flash("Only the owner can manage sharing.", "info")
        return redirect(url_for("event_detail", event_id=event_id) if event else url_for("index"))
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "add":
            uname = request.form.get("username", "").strip()
            new_role = request.form.get("role", "viewer")
            target = auth.get_user_by_username(uname)
            if not target:
                flash("User not found.", "info")
            elif target.id == event.owner_id:
                flash("Owner already has access.", "info")
            elif em.add_event_share(event_id, target.id, new_role):
                flash(f"Shared with @{target.username} as {new_role}.", "info")
            else:
                flash("Could not add share.", "info")
        elif action == "remove":
            uid = request.form.get("user_id", "")
            em.remove_event_share(event_id, uid)
            flash("Access removed.", "info")
        elif action == "update":
            uid = request.form.get("user_id", "")
            new_role = request.form.get("role", "viewer")
            em.remove_event_share(event_id, uid)
            em.add_event_share(event_id, uid, new_role)
            flash("Role updated.", "info")
        return redirect(url_for("share_event_page", event_id=event_id))

    users_by_id = {u.id: u for u in auth.load_users()}
    shares = []
    owner_u = users_by_id.get(event.owner_id)
    shares.append(
        {
            "user": owner_u,
            "role": "owner",
            "is_owner": True,
            "user_id": event.owner_id,
        }
    )
    for p in event.permissions:
        uid = p.get("user_id", "")
        u = users_by_id.get(uid)
        if u:
            shares.append(
                {
                    "user": u,
                    "role": p.get("role", "viewer"),
                    "is_owner": False,
                    "user_id": uid,
                }
            )
    return render_template(
        "share_event.html",
        event=event,
        shares=shares,
        all_users=auth.load_users(),
    )


@app.route("/events/<event_id>")
@login_required
def event_detail(event_id: str):
    event = em.get_event(event_id)
    if not event:
        flash("Event not found.", "info")
        return redirect(url_for("index"))
    role = em.get_event_share_role(g.current_user, event)
    if not role:
        flash("You do not have access to this event.", "info")
        return redirect(url_for("index"))
    metrics = em.compute_metrics(event)
    statuses = list(ContactStatus)
    can_edit = _role_ok(role, "editor")
    can_owner = role == "owner"
    contact_roles = list(ContactRole)
    grouped_contacts: list[tuple[ContactRole, list]] = []
    for cr in ContactRole:
        group = [c for c in event.contacts if c.contact_role == cr]
        if group:
            grouped_contacts.append((cr, group))
    return render_template(
        "event_detail.html",
        event=event,
        metrics=metrics,
        statuses=statuses,
        contact_roles=contact_roles,
        grouped_contacts=grouped_contacts,
        event_role=role,
        can_edit=can_edit,
        can_owner=can_owner,
    )


def _require_event_edit(event_id: str):
    event = em.get_event(event_id)
    role = em.get_event_share_role(g.current_user, event) if event else None
    if not event or not _role_ok(role, "editor"):
        return None, None
    return event, role


@app.post("/events/<event_id>/contacts")
@login_required
def add_contact_route(event_id: str):
    event, _ = _require_event_edit(event_id)
    if not event:
        flash("Not allowed.", "info")
        return redirect(url_for("index"))
    name = request.form.get("name", "")
    email = request.form.get("email", "")
    if not name or not email:
        flash("Name and email are required.", "info")
        return redirect(url_for("event_detail", event_id=event_id))
    phone = request.form.get("phone", "").strip()
    try:
        role_val = ContactRole(request.form.get("contact_role", "attendee"))
    except ValueError:
        role_val = ContactRole.ATTENDEE
    em.add_contact(event_id, name, email, contact_role=role_val, phone=phone)
    flash("Contact added.", "info")
    return redirect(url_for("event_detail", event_id=event_id))


@app.post("/events/<event_id>/contacts/<contact_id>/status")
@login_required
def update_contact_status_route(event_id: str, contact_id: str):
    if not _require_event_edit(event_id)[0]:
        flash("Not allowed.", "info")
        return redirect(url_for("index"))
    status = request.form.get("status", "")
    if em.update_contact_status(event_id, contact_id, status):
        flash("Status updated.", "info")
    else:
        flash("Could not update status.", "info")
    return redirect(url_for("event_detail", event_id=event_id))


@app.post("/events/<event_id>/contacts/<contact_id>/role")
@login_required
def update_contact_role_route(event_id: str, contact_id: str):
    if not _require_event_edit(event_id)[0]:
        flash("Not allowed.", "info")
        return redirect(url_for("index"))
    role = request.form.get("contact_role", "")
    if em.update_contact_role(event_id, contact_id, role):
        flash("Role updated.", "info")
    else:
        flash("Could not update role.", "info")
    return redirect(url_for("event_detail", event_id=event_id))


@app.post("/events/<event_id>/contacts/<contact_id>/attended")
@login_required
def toggle_attended_route(event_id: str, contact_id: str):
    if not _require_event_edit(event_id)[0]:
        flash("Not allowed.", "info")
        return redirect(url_for("index"))
    raw = request.form.getlist("attended")
    attended = raw and raw[-1] == "1"
    if em.set_contact_attended(event_id, contact_id, attended):
        flash("Attendance updated.", "info")
    else:
        flash("Could not update attendance.", "info")
    return redirect(url_for("event_detail", event_id=event_id))


@app.post("/events/<event_id>/generate")
@login_required
def generate_emails_route(event_id: str):
    event, _ = _require_event_edit(event_id)
    if not event:
        flash("Not allowed.", "info")
        return redirect(url_for("index"))
    targets = [c for c in event.contacts if c.status == ContactStatus.NOT_CONTACTED]
    if not targets:
        flash("No contacts with status 'not contacted'.", "info")
        return redirect(url_for("event_detail", event_id=event_id))
    emails: list[dict] = []
    ids = []
    for c in targets:
        ctx = _person_context_for_contact(c)
        gen = generate_initial_email(
            event.name,
            event.date,
            event.description,
            event.audience_type,
            c.name,
            contact_role=c.contact_role.value,
            **ctx,
        )
        log.log_outreach(
            event_id,
            c.id,
            c.name,
            EmailType.INITIAL,
            gen.body,
            subject=gen.subject,
        )
        emails.append(
            {
                "recipient_name": c.name,
                "recipient_email": c.email,
                "subject": gen.subject,
                "body": gen.body,
                "contact_role": c.contact_role.value,
            }
        )
        ids.append(c.id)
    em.update_contacts_status_batch(event_id, ids, ContactStatus.CONTACTED)
    flash(f"Generated {len(emails)} outreach email(s).", "info")
    return render_template(
        "email_preview.html",
        event=event,
        emails=emails,
        title="Generated outreach emails",
    )


@app.post("/events/<event_id>/followup")
@login_required
def followup_emails_route(event_id: str):
    event, _ = _require_event_edit(event_id)
    if not event:
        flash("Not allowed.", "info")
        return redirect(url_for("index"))
    ended = _event_ended(event.date)
    targets = []
    for c in event.contacts:
        if c.status == ContactStatus.CONTACTED:
            targets.append(c)
        elif ended and c.status == ContactStatus.NOT_CONTACTED:
            targets.append(c)
    if not targets:
        flash("No contacts need a follow-up right now.", "info")
        return redirect(url_for("event_detail", event_id=event_id))
    emails: list[dict] = []
    for c in targets:
        ctx = _person_context_for_contact(c)
        gen = generate_followup_email(
            event.name, event.date, c.name, contact_role=c.contact_role.value,
            **ctx,
        )
        log.log_outreach(
            event_id,
            c.id,
            c.name,
            EmailType.FOLLOW_UP,
            gen.body,
            subject=gen.subject,
        )
        emails.append(
            {
                "recipient_name": c.name,
                "recipient_email": c.email,
                "subject": gen.subject,
                "body": gen.body,
                "contact_role": c.contact_role.value,
            }
        )
    flash(f"Generated {len(emails)} follow-up email(s).", "info")
    return render_template(
        "email_preview.html",
        event=event,
        emails=emails,
        title="Follow-up emails",
    )


@app.route("/events/<event_id>/logs")
@login_required
def event_logs(event_id: str):
    event = em.get_event(event_id)
    role = em.get_event_share_role(g.current_user, event) if event else None
    if not event or not role:
        flash("Event not found.", "info")
        return redirect(url_for("index"))
    logs = log.get_logs(event_id)
    return render_template(
        "logs.html",
        event=event,
        logs=logs,
        can_edit=_role_ok(role, "editor"),
    )


# ── Recommend / Discover / Referrals ────────────────────────


@app.route("/events/<event_id>/recommend", methods=["GET", "POST"])
@login_required
def recommend_people_route(event_id: str):
    event, _ = _require_event_edit(event_id)
    if not event:
        flash("Not allowed.", "info")
        return redirect(url_for("index"))

    selectable_roles = [
        r for r in ContactRole if r not in (ContactRole.STAFF, ContactRole.ORGANIZER)
    ]
    target_role = request.args.get("target_role", "") or request.form.get("target_role", "")

    people = pm.load_people()
    summaries = [
        {
            "id": p.id,
            "name": p.name,
            "email": p.email,
            "company": p.company,
            "role": p.role,
            "tags": p.tags,
        }
        for p in people
    ]

    if request.method == "POST" and request.form.get("action") == "add":
        ids = request.form.getlist("person_id")
        try:
            add_role = ContactRole(request.form.get("target_role", "attendee"))
        except ValueError:
            add_role = ContactRole.ATTENDEE
        rows = []
        for pid in ids:
            p = pm.get_person(pid)
            if p:
                rows.append((p.name, p.email))
                pm.append_event_to_person(pid, event_id)
        n = em.add_contacts_bulk(event_id, rows, contact_role=add_role)
        role_label = add_role.value.replace("_", " ").title()
        flash(f"Added {n} contact(s) as {role_label}.", "info")
        return redirect(url_for("event_detail", event_id=event_id))

    if not target_role:
        return render_template(
            "recommendations.html",
            event=event,
            recommendations=[],
            selectable_roles=selectable_roles,
            target_role="",
            picking_role=True,
        )

    recs = recommend_people_for_event(
        event.name,
        event.date,
        event.description,
        event.audience_type,
        summaries,
        target_role=target_role,
    )
    by_id = {p.id: p for p in people}
    display = []
    for r in recs:
        p = by_id.get(r["person_id"])
        if p:
            display.append({"person": p, "reason": r.get("reason", "")})
    return render_template(
        "recommendations.html",
        event=event,
        recommendations=display,
        selectable_roles=selectable_roles,
        target_role=target_role,
        picking_role=False,
    )


@app.route("/events/<event_id>/discover", methods=["GET", "POST"])
@login_required
def discover_route(event_id: str):
    event, _ = _require_event_edit(event_id)
    if not event:
        flash("Not allowed.", "info")
        return redirect(url_for("index"))

    selectable_roles = [
        r for r in ContactRole if r not in (ContactRole.STAFF, ContactRole.ORGANIZER)
    ]
    target_role = request.form.get("target_role", "") or request.args.get("target_role", "")

    queries = disc.clean_queries(
        disc.build_search_queries(event.name, event.description, event.audience_type, target_role)
    )
    prospects: list[dict] = []
    if request.method == "POST":
        action = request.form.get("action", "search")
        if action == "search":
            q = request.form.get("query", queries[0] if queries else event.name)
            snippets = disc.search_web_snippets(q)
            blob = "\n".join(f"{s['title']} | {s['url']} | {s['snippet']}" for s in snippets)
            prospects = discover_prospects_from_text(event.name, blob, target_role=target_role)
            for i, pr in enumerate(prospects):
                if not (pr.get("email") or "").strip():
                    pr["email"] = f"pending+{new_id()[:8]}@som.local"
            session["discover_last"] = json.dumps(prospects)
            session["discover_role"] = target_role
        elif action == "add":
            raw = session.get("discover_last", "[]")
            try:
                last = json.loads(raw)
            except json.JSONDecodeError:
                last = []
            saved_role = session.get("discover_role", "")
            role_tag = f"prospect-{saved_role}" if saved_role else "web_discovery"
            idxs = [int(x) for x in request.form.getlist("idx") if x.isdigit()]
            added = 0
            for i in idxs:
                if 0 <= i < len(last):
                    row = last[i]
                    name = row.get("name", "Prospect")
                    email = row.get("email") or f"unknown{i}@placeholder.local"
                    if pm.find_by_email(email):
                        continue
                    pm.add_person(
                        name=name,
                        email=email,
                        company=row.get("organization", ""),
                        role=row.get("note", "")[:80],
                        linkedin_url=row.get("url", ""),
                        tags=["web_discovery", role_tag],
                        source="web_discovery",
                        notes=row.get("note", ""),
                    )
                    added += 1
            flash(f"Added {added} prospect(s) to People.", "info")
            return redirect(url_for("people_page"))
        return render_template(
            "discover.html",
            event=event,
            queries=queries,
            prospects=prospects,
            selectable_roles=selectable_roles,
            target_role=target_role,
        )
    return render_template(
        "discover.html",
        event=event,
        queries=queries,
        prospects=[],
        selectable_roles=selectable_roles,
        target_role=target_role,
    )


@app.route("/events/<event_id>/request-referrals", methods=["GET", "POST"])
@login_required
def request_referrals_route(event_id: str):
    event, _ = _require_event_edit(event_id)
    if not event:
        flash("Not allowed.", "info")
        return redirect(url_for("index"))

    selectable_roles = [
        r for r in ContactRole if r not in (ContactRole.STAFF, ContactRole.ORGANIZER)
    ]

    if request.method == "GET":
        return render_template(
            "referral_picker.html",
            event=event,
            selectable_roles=selectable_roles,
        )

    target_role = request.form.get("target_role", "attendee")
    targets = [
        c
        for c in event.contacts
        if c.status in (ContactStatus.RESPONDED, ContactStatus.CONFIRMED)
    ]
    if not targets:
        flash("No responded or confirmed contacts to ask for referrals.", "info")
        return redirect(url_for("event_detail", event_id=event_id))
    emails: list[dict] = []
    for c in targets:
        ctx = _person_context_for_contact(c)
        gen = generate_referral_request_email(
            event.name,
            event.date,
            c.name,
            sender_role=c.contact_role.value,
            target_role=target_role,
            **ctx,
        )
        log.log_outreach(
            event_id,
            c.id,
            c.name,
            EmailType.FOLLOW_UP,
            gen.body,
            subject=gen.subject,
        )
        emails.append(
            {
                "recipient_name": c.name,
                "recipient_email": c.email,
                "subject": gen.subject,
                "body": gen.body,
                "contact_role": c.contact_role.value,
            }
        )
    role_label = target_role.replace("_", " ").title()
    flash(f"Generated {len(emails)} referral request(s) looking for {role_label}s.", "info")
    return render_template(
        "email_preview.html",
        event=event,
        emails=emails,
        title=f"Referral requests — looking for {role_label}s",
    )


# ── People ──────────────────────────────────────────────────


def _can_edit_people() -> bool:
    return g.current_user.role == "admin"


@app.route("/people")
@login_required
def people_page():
    q = request.args.get("q", "")
    tag = request.args.get("tag") or None
    people = pm.search_people(q, tag)
    tags = pm.all_tags()
    referrers = {p.id: p.name for p in pm.load_people()}
    return render_template(
        "people.html",
        people=people,
        all_tags=tags,
        q=q,
        tag_filter=tag or "",
        can_edit_people=_can_edit_people(),
        referrers=referrers,
    )


@app.post("/people/add")
@login_required
def people_add_route():
    if not _can_edit_people():
        flash("Only admins can add people.", "info")
        return redirect(url_for("people_page"))
    p = pm.add_person(
        request.form.get("name", ""),
        request.form.get("email", ""),
        company=request.form.get("company", ""),
        role=request.form.get("role", ""),
        tags=[t.strip() for t in request.form.get("tags", "").split(",") if t.strip()],
        source="manual",
    )
    flash("Person added." if p else "Could not add (duplicate email?).", "info")
    return redirect(url_for("people_page"))


@app.post("/people/<person_id>/delete")
@login_required
def people_delete_route(person_id: str):
    if not _can_edit_people():
        flash("Not allowed.", "info")
        return redirect(url_for("people_page"))
    if pm.delete_person(person_id):
        flash("Removed.", "info")
    return redirect(url_for("people_page"))


@app.route("/people/import", methods=["GET", "POST"])
@login_required
def import_people_page():
    if not _can_edit_people():
        flash("Only admins can import.", "info")
        return redirect(url_for("people_page"))
    if request.method == "POST":
        if request.form.get("step") == "confirm":
            raw = session.pop("import_preview_rows", None)
            tag = session.pop("import_default_tag", "")
            if not raw:
                flash("Session expired — upload again.", "info")
                return redirect(url_for("import_people_page"))
            rows = json.loads(raw)
            tags = [tag] if tag else []
            added, skipped = pm.import_people_rows(rows, default_tags=tags)
            flash(f"Imported {added} row(s), skipped {skipped}.", "info")
            return redirect(url_for("people_page"))
        f = request.files.get("file")
        if not f or not f.filename:
            flash("Choose a file.", "info")
            return redirect(url_for("import_people_page"))
        data = f.read()
        rows = people_import.parse_upload(f.filename, data)
        if not rows:
            flash("No valid rows found (need name + email columns).", "info")
            return redirect(url_for("import_people_page"))
        default_tag = request.form.get("default_tag", "").strip()
        session["import_preview_rows"] = json.dumps(rows[:500])
        session["import_default_tag"] = default_tag
        return render_template(
            "import_people.html",
            preview_rows=rows[:50],
            total=len(rows),
            default_tag=default_tag,
            step="preview",
        )
    return render_template("import_people.html", step="upload", preview_rows=[], total=0)


# ── SOM Events Feed ──────────────────────────────────────────


@app.route("/som-events")
@login_required
def som_events_page():
    events = scraper.load_som_events()
    today_str = date.today().isoformat()
    upcoming = sorted(
        [e for e in events if e.get("status") == "upcoming" and e.get("date", "") >= today_str],
        key=lambda e: e.get("date", "9999"),
    )
    other = [e for e in events if e not in upcoming]
    changes = scraper.pending_changes()
    return render_template(
        "som_events.html",
        upcoming=upcoming,
        other=other,
        changes=changes,
        sources=scraper.SOURCES,
        monitor=_monitor_state,
    )


@app.post("/som-events/refresh")
@login_required
def som_refresh():
    pages, new_changes = scraper.refresh_from_web()
    if new_changes:
        flash(f"Scanned {pages} pages — {len(new_changes)} change(s) detected!", "info")
    else:
        flash(f"Scanned {pages} pages — no changes detected.", "info")
    return redirect(url_for("som_events_page"))


@app.post("/som-events/<som_id>/import")
@login_required
def som_import_event(som_id: str):
    som_evt = scraper.get_som_event(som_id)
    if not som_evt:
        flash("SOM event not found.", "info")
        return redirect(url_for("som_events_page"))
    existing = [e for e in em.load_events() if e.som_event_id == som_id]
    if existing:
        flash("Already imported — opening event.", "info")
        return redirect(url_for("event_detail", event_id=existing[0].id))
    event = em.create_event(
        name=som_evt.get("name", "SOM Event"),
        date=som_evt.get("date", ""),
        description=som_evt.get("description", ""),
        audience_type=som_evt.get("series", "SOM"),
        owner_id=g.current_user.id,
    )
    all_events = em.load_events()
    for i, e in enumerate(all_events):
        if e.id == event.id:
            e.som_event_id = som_id
            all_events[i] = e
            break
    em.save_events(all_events)
    flash(f"Imported \"{som_evt['name']}\" -- add contacts to start outreach.", "info")
    return redirect(url_for("event_detail", event_id=event.id))


@app.post("/som-events/changes/<change_id>/dismiss")
@login_required
def som_dismiss_change(change_id: str):
    scraper.dismiss_change(change_id)
    return redirect(url_for("som_events_page"))


@app.post("/som-events/changes/<change_id>/notify")
@login_required
def som_notify_change(change_id: str):
    changes = scraper.load_changes()
    change = next((c for c in changes if c["id"] == change_id), None)
    if not change:
        flash("Change not found.", "info")
        return redirect(url_for("som_events_page"))
    som_event_id = change.get("event_id", "")
    linked_events = (
        [e for e in em.load_events() if e.som_event_id == som_event_id]
        if som_event_id
        else []
    )
    if not linked_events:
        flash("Import this SOM event first, then add contacts before notifying.", "info")
        return redirect(url_for("som_events_page"))
    event = linked_events[0]
    if not _role_ok(em.get_event_share_role(g.current_user, event), "editor"):
        flash("Not allowed.", "info")
        return redirect(url_for("som_events_page"))
    targets = [c for c in event.contacts if c.status != ContactStatus.DECLINED]
    if not targets:
        flash("No contacts to notify — add contacts to the imported event first.", "info")
        return redirect(url_for("event_detail", event_id=event.id))
    emails: list[dict] = []
    for c in targets:
        ctx = _person_context_for_contact(c)
        gen = generate_event_update_email(
            event.name,
            event.date,
            c.name,
            change.get("description", "Event information has been updated."),
            contact_role=c.contact_role.value,
            company=ctx.get("company", ""),
            title=ctx.get("title", ""),
            notes=ctx.get("notes", ""),
        )
        log.log_outreach(
            event.id,
            c.id,
            c.name,
            EmailType.FOLLOW_UP,
            gen.body,
            subject=gen.subject,
        )
        emails.append(
            {
                "recipient_name": c.name,
                "recipient_email": c.email,
                "subject": gen.subject,
                "body": gen.body,
                "contact_role": c.contact_role.value,
            }
        )
    scraper.dismiss_change(change_id)
    flash(f"Generated {len(emails)} update email(s) for '{event.name}'.", "info")
    return render_template(
        "email_preview.html",
        event=event,
        emails=emails,
        title=f"Update: {change.get('description', 'Event updated')}",
    )


# ── Send emails (SMTP) ─────────────────────────────────────
@app.post("/events/<event_id>/send-emails")
@login_required
def send_emails_route(event_id: str):
    event, _ = _require_event_edit(event_id)
    if not event:
        flash("Not allowed.", "info")
        return redirect(url_for("index"))
    raw = request.form.get("email_batch", "[]")
    try:
        emails = json.loads(raw)
    except json.JSONDecodeError:
        emails = []
    if not emails:
        flash("No emails to send.", "info")
        return redirect(url_for("event_detail", event_id=event_id))
    results = email_sender.send_batch(emails)
    sent = sum(1 for r in results if r.get("ok"))
    failed = len(results) - sent
    flash(f"Sent {sent} email(s), {failed} failed.", "info" if failed == 0 else "info")
    return render_template(
        "send_results.html",
        event=event,
        results=results,
        sent=sent,
        failed=failed,
    )


# ── Vapi AI Calls ──────────────────────────────────────────
@app.post("/events/<event_id>/call-invite")
@login_required
def call_invite_route(event_id: str):
    event, _ = _require_event_edit(event_id)
    if not event:
        flash("Not allowed.", "info")
        return redirect(url_for("index"))
    targets = [
        c for c in event.contacts
        if c.status == ContactStatus.NOT_CONTACTED and _person_phone_for_contact(c)
    ]
    if not targets:
        flash("No un-contacted contacts with phone numbers.", "info")
        return redirect(url_for("event_detail", event_id=event_id))
    results = []
    for c in targets:
        ctx = _person_context_for_contact(c)
        phone = _person_phone_for_contact(c)
        bg_parts = []
        if ctx.get("company"):
            bg_parts.append(f"Works at {ctx['company']}")
        if ctx.get("title"):
            bg_parts.append(f"Title: {ctx['title']}")
        if ctx.get("notes"):
            bg_parts.append(ctx["notes"][:200])
        result = vapi_caller.call_invite(
            phone=phone,
            recipient_name=c.name,
            event_name=event.name,
            event_date=event.date,
            contact_role=c.contact_role.value,
            company=ctx.get("company", ""),
            title=ctx.get("title", ""),
            background_notes=". ".join(bg_parts) if bg_parts else "",
        )
        result["recipient_name"] = c.name
        result["phone"] = phone
        result["contact_role"] = c.contact_role.value
        results.append(result)
        if result.get("ok"):
            log.log_outreach(
                event_id, c.id, c.name, EmailType.INITIAL,
                f"[AI CALL — INVITE] Call placed to {phone}",
                subject=f"AI Call Invite: {event.name}",
            )
    placed = sum(1 for r in results if r.get("ok"))
    flash(f"Placed {placed} invite call(s).", "info")
    return render_template(
        "call_results.html",
        event=event,
        results=results,
        call_type="Invite",
    )


@app.post("/events/<event_id>/call-followup")
@login_required
def call_followup_route(event_id: str):
    event, _ = _require_event_edit(event_id)
    if not event:
        flash("Not allowed.", "info")
        return redirect(url_for("index"))
    targets = [
        c for c in event.contacts
        if c.status == ContactStatus.CONTACTED and _person_phone_for_contact(c)
    ]
    if not targets:
        flash("No contacted (non-responded) contacts with phone numbers.", "info")
        return redirect(url_for("event_detail", event_id=event_id))
    results = []
    for c in targets:
        ctx = _person_context_for_contact(c)
        phone = _person_phone_for_contact(c)
        bg_parts = []
        if ctx.get("company"):
            bg_parts.append(f"Works at {ctx['company']}")
        if ctx.get("title"):
            bg_parts.append(f"Title: {ctx['title']}")
        if ctx.get("notes"):
            bg_parts.append(ctx["notes"][:200])
        result = vapi_caller.call_followup(
            phone=phone,
            recipient_name=c.name,
            event_name=event.name,
            event_date=event.date,
            contact_role=c.contact_role.value,
            company=ctx.get("company", ""),
            title=ctx.get("title", ""),
            background_notes=". ".join(bg_parts) if bg_parts else "",
        )
        result["recipient_name"] = c.name
        result["phone"] = phone
        result["contact_role"] = c.contact_role.value
        results.append(result)
        if result.get("ok"):
            log.log_outreach(
                event_id, c.id, c.name, EmailType.FOLLOW_UP,
                f"[AI CALL — FOLLOW-UP] Call placed to {phone}",
                subject=f"AI Call Follow-Up: {event.name}",
            )
    placed = sum(1 for r in results if r.get("ok"))
    flash(f"Placed {placed} follow-up call(s).", "info")
    return render_template(
        "call_results.html",
        event=event,
        results=results,
        call_type="Follow-Up",
    )


# ── Background web monitor ──────────────────────────────────
_monitor_state = {
    "running": False,
    "last_check": None,
    "checks_count": 0,
    "last_changes": 0,
    "interval_minutes": 0,
}


def _auto_notify_for_changes(new_changes: list[dict]) -> None:
    """Auto-generate and send update emails when changes are detected."""
    if os.environ.get("AUTO_NOTIFY_ON_CHANGE", "true").lower() != "true":
        return
    gmail_ok = bool(os.environ.get("GMAIL_ADDRESS") and os.environ.get("GMAIL_APP_PASSWORD"))
    for change in new_changes:
        event_id = change.get("event_id", "")
        if not event_id:
            continue
        events = em.load_events()
        event = next((e for e in events if e.id == event_id), None)
        if not event or not event.contacts:
            continue
        for c in event.contacts:
            ctx = _person_context_for_contact(c)
            gen = generate_event_update_email(
                event.name, event.date,
                change.get("description", "Event updated"),
                c.name,
                contact_role=c.contact_role.value,
                **ctx,
            )
            log.log_outreach(
                event_id, c.id, c.name, EmailType.FOLLOW_UP,
                gen.body, subject=gen.subject,
            )
            if gmail_ok:
                email_sender.send_email(c.email, gen.subject, gen.body)


def _monitor_loop() -> None:
    """Background loop that periodically scrapes and auto-notifies."""
    interval = int(os.environ.get("SCRAPE_INTERVAL_MINUTES", "10") or "0")
    if interval <= 0:
        return
    _monitor_state["running"] = True
    _monitor_state["interval_minutes"] = interval
    while _monitor_state["running"]:
        _time.sleep(interval * 60)
        if not _monitor_state["running"]:
            break
        try:
            _, new_changes = scraper.refresh_from_web()
            _monitor_state["last_check"] = datetime.now(timezone.utc).isoformat()
            _monitor_state["checks_count"] += 1
            _monitor_state["last_changes"] = len(new_changes)
            if new_changes:
                _auto_notify_for_changes(new_changes)
        except Exception:
            pass


def _start_monitor() -> None:
    interval = int(os.environ.get("SCRAPE_INTERVAL_MINUTES", "10") or "0")
    if interval <= 0:
        _monitor_state["running"] = False
        _monitor_state["interval_minutes"] = 0
        return
    _monitor_state["interval_minutes"] = interval
    t = threading.Thread(target=_monitor_loop, daemon=True)
    t.start()


_start_monitor()


if __name__ == "__main__":
    run_host = os.environ.get("FLASK_RUN_HOST", "127.0.0.1")
    run_port = int(os.environ.get("FLASK_RUN_PORT", "5000"))
    debug_env = os.environ.get("FLASK_DEBUG", "").strip().lower()
    if debug_env in ("1", "true", "yes"):
        debug = True
    elif debug_env in ("0", "false", "no"):
        debug = False
    else:
        # Werkzeug debugger is unsafe on a shared interface; default off for 0.0.0.0 / ::
        debug = run_host not in ("0.0.0.0", "::")
    app.run(debug=debug, host=run_host, port=run_port)
