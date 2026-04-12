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
    Response,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from models import (
    ContactRole, ContactStatus, EmailType, RegistrationType,
    new_id, normalize_phone,
)
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
import call_scheduler
import call_monitor
import outreach_queue
import ai_config as aic

load_dotenv()


def _seed_data_if_missing() -> None:
    """Copy seed files into data/ when missing or empty (first deploy)."""
    import shutil
    from pathlib import Path

    def _is_empty_json(path: Path) -> bool:
        try:
            content = path.read_text(encoding="utf-8").strip()
            return content in ("[]", "{}", "")
        except Exception:
            return False

    seed_dir = Path(__file__).resolve().parent / "seed_data"
    data_dir = Path(__file__).resolve().parent / "data"
    if not seed_dir.is_dir():
        return
    data_dir.mkdir(parents=True, exist_ok=True)
    for src in seed_dir.iterdir():
        if src.is_file():
            dest = data_dir / src.name
            if not dest.exists() or _is_empty_json(dest):
                shutil.copy2(src, dest)


_seed_data_if_missing()


def _merge_seed_contacts() -> None:
    """Enrich events that have empty contacts with contacts from seed data."""
    from pathlib import Path

    seed_file = Path(__file__).resolve().parent / "seed_data" / "events.json"
    data_file = Path(__file__).resolve().parent / "data" / "events.json"
    if not seed_file.exists() or not data_file.exists():
        return
    try:
        seed_events = json.loads(seed_file.read_text(encoding="utf-8"))
        data_events = json.loads(data_file.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(seed_events, list) or not isinstance(data_events, list):
        return

    seed_by_som_id: dict[str, dict] = {}
    seed_by_name: dict[str, dict] = {}
    for se in seed_events:
        sid = se.get("som_event_id", "")
        if sid:
            seed_by_som_id[sid] = se
        name = se.get("name", "").strip().lower()
        if name:
            seed_by_name[name] = se

    changed = False
    for de in data_events:
        if de.get("contacts"):
            continue
        match = None
        sid = de.get("som_event_id", "")
        if sid:
            match = seed_by_som_id.get(sid)
        if not match:
            name = de.get("name", "").strip().lower()
            if name:
                match = seed_by_name.get(name)
        if match and match.get("contacts"):
            de["contacts"] = match["contacts"]
            changed = True

    if changed:
        data_file.write_text(
            json.dumps(data_events, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


_merge_seed_contacts()

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

    filter_audience = request.args.get("audience", "")
    filter_status = request.args.get("status", "")
    search_q = request.args.get("q", "").strip().lower()

    if filter_audience:
        events = [e for e in events if e.audience_type == filter_audience]
    if filter_status == "upcoming":
        today = date.today().isoformat()
        events = [e for e in events if e.date >= today]
    elif filter_status == "past":
        today = date.today().isoformat()
        events = [e for e in events if e.date < today]
    elif filter_status == "has_contacts":
        events = [e for e in events if e.contacts]
    elif filter_status == "no_contacts":
        events = [e for e in events if not e.contacts]
    if search_q:
        events = [e for e in events if search_q in e.name.lower() or search_q in e.description.lower()]

    sort_by = request.args.get("sort", "date_desc")
    if sort_by == "date_asc":
        events.sort(key=lambda e: e.date)
    elif sort_by == "name_asc":
        events.sort(key=lambda e: e.name.lower())
    elif sort_by == "name_desc":
        events.sort(key=lambda e: e.name.lower(), reverse=True)
    elif sort_by == "contacts_desc":
        events.sort(key=lambda e: len(e.contacts), reverse=True)
    elif sort_by == "contacts_asc":
        events.sort(key=lambda e: len(e.contacts))
    else:
        events.sort(key=lambda e: e.date, reverse=True)

    all_audiences = sorted({e.audience_type for e in em.list_events_visible_to(g.current_user) if e.audience_type})
    roles = {e.id: em.get_event_share_role(g.current_user, e) or "viewer" for e in events}
    return render_template(
        "index.html", events=events, event_roles=roles,
        sort_by=sort_by, filter_audience=filter_audience,
        filter_status=filter_status, search_q=request.args.get("q", ""),
        all_audiences=all_audiences,
    )


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
    try:
        venue_cap = int(request.form.get("venue_capacity", 0) or 0)
    except (ValueError, TypeError):
        venue_cap = 0
    try:
        walkin_buf = int(request.form.get("walkin_buffer_pct", 15) or 15)
    except (ValueError, TypeError):
        walkin_buf = 15
    em.create_event(
        name, event_date, description, audience,
        owner_id=g.current_user.id,
        sender_name=request.form.get("sender_name", ""),
        sender_title=request.form.get("sender_title", ""),
        sender_email=request.form.get("sender_email", ""),
        venue_capacity=venue_cap,
        walkin_buffer_pct=walkin_buf,
    )
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
    try:
        venue_cap = int(request.form.get("venue_capacity", 0) or 0)
    except (ValueError, TypeError):
        venue_cap = 0
    try:
        walkin_buf = int(request.form.get("walkin_buffer_pct", 15) or 15)
    except (ValueError, TypeError):
        walkin_buf = 15
    em.update_event(
        event_id, name, event_date, description, audience,
        sender_name=request.form.get("sender_name", ""),
        sender_title=request.form.get("sender_title", ""),
        sender_email=request.form.get("sender_email", ""),
        venue_capacity=venue_cap,
        walkin_buffer_pct=walkin_buf,
    )
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

    eq = outreach_queue.get_queue_filtered(event_id=event_id)
    sched_metrics = {
        "planned": sum(1 for i in eq if i["status"] == "planned"),
        "approved": sum(1 for i in eq if i["status"] == "approved"),
        "sent": sum(1 for i in eq if i["status"] == "sent"),
        "total": len(eq),
    }
    from datetime import datetime as _dt
    _now = _dt.utcnow().isoformat()
    upcoming_actions = [
        i for i in eq
        if i.get("scheduled_at", "") >= _now and i["status"] in ("planned", "approved")
    ][:3]

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
        sched_metrics=sched_metrics,
        upcoming_actions=upcoming_actions,
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
    phone = normalize_phone(request.form.get("phone", ""))
    try:
        role_val = ContactRole(request.form.get("contact_role", "attendee"))
    except ValueError:
        role_val = ContactRole.ATTENDEE
    try:
        reg_type = RegistrationType(request.form.get("registration_type", "pre_registered"))
    except ValueError:
        reg_type = RegistrationType.PRE_REGISTERED
    em.add_contact(event_id, name, email, contact_role=role_val, phone=phone,
                   registration_type=reg_type)
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
            event=event,
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
            event=event, **ctx,
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


# ── Contact edit / delete ────────────────────────────────────


@app.post("/events/<event_id>/contacts/<contact_id>/delete")
@login_required
def delete_contact_route(event_id: str, contact_id: str):
    if not _require_event_edit(event_id)[0]:
        flash("Not allowed.", "info")
        return redirect(url_for("index"))
    if em.delete_contact(event_id, contact_id):
        flash("Contact removed.", "info")
    else:
        flash("Could not remove contact.", "info")
    return redirect(url_for("event_detail", event_id=event_id))


@app.post("/events/<event_id>/contacts/<contact_id>/edit")
@login_required
def edit_contact_route(event_id: str, contact_id: str):
    if not _require_event_edit(event_id)[0]:
        flash("Not allowed.", "info")
        return redirect(url_for("index"))
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    phone = normalize_phone(request.form.get("phone", ""))
    if em.update_contact_details(event_id, contact_id, name=name, email=email, phone=phone):
        flash("Contact updated.", "info")
    else:
        flash("Could not update contact.", "info")
    return redirect(url_for("event_detail", event_id=event_id))


# ── Walk-in Check-in ────────────────────────────────────────


@app.route("/events/<event_id>/walkin", methods=["GET", "POST"])
@login_required
def walkin_checkin(event_id: str):
    event = em.get_event(event_id)
    if not event:
        flash("Event not found.", "info")
        return redirect(url_for("index"))
    role = em.get_event_share_role(g.current_user, event)
    if not _role_ok(role, "editor"):
        flash("You do not have permission.", "info")
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        if not name or not email:
            flash("Name and email are required.", "info")
            return redirect(url_for("walkin_checkin", event_id=event_id))
        phone = normalize_phone(request.form.get("phone", ""))
        em.add_contact(
            event_id, name, email,
            contact_role=ContactRole.ATTENDEE,
            phone=phone,
            registration_type=RegistrationType.WALK_IN,
            status=ContactStatus.CONFIRMED,
            attended=True,
        )
        flash(f"{name} checked in!", "info")
        return redirect(url_for("walkin_checkin", event_id=event_id))

    metrics = em.compute_metrics(event)
    return render_template(
        "walkin_checkin.html",
        event=event,
        metrics=metrics,
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
    from email_generator import get_sender_identity
    s_name, _s_title, s_email = get_sender_identity(event)
    results = email_sender.send_batch(emails, reply_to=s_email, sender_name=s_name)
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
            call_monitor.log_call(
                call_id=result["call_id"], event_id=event_id,
                contact_id=c.id, contact_name=c.name, call_type="invite",
                listen_url=result.get("listen_url", ""),
                control_url=result.get("control_url", ""),
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
            call_monitor.log_call(
                call_id=result["call_id"], event_id=event_id,
                contact_id=c.id, contact_name=c.name, call_type="followup",
                listen_url=result.get("listen_url", ""),
                control_url=result.get("control_url", ""),
            )
    placed = sum(1 for r in results if r.get("ok"))
    flash(f"Placed {placed} follow-up call(s).", "info")
    return render_template(
        "call_results.html",
        event=event,
        results=results,
        call_type="Follow-Up",
    )


# ── Live calls & analytics routes ───────────────────────────


@app.route("/calls/live")
@login_required
def live_calls_page():
    call_monitor.sync_all_active()
    active = call_monitor.get_active_calls()
    recent = [e for e in call_monitor.load_call_log() if e.get("status") == "ended"][-20:]
    recent.reverse()
    return render_template("live_calls.html", active=active, recent=recent)


@app.post("/calls/<call_id>/delete")
@login_required
def delete_call_route(call_id: str):
    call_monitor.delete_call(call_id)
    flash("Call deleted.", "info")
    return redirect(url_for("live_calls_page"))


@app.route("/calls/<call_id>/stream")
@login_required
def call_stream(call_id: str):
    def generate():
        import time as t
        for _ in range(120):
            entry = call_monitor.sync_call_from_vapi(call_id)
            if not entry:
                entry = call_monitor.get_call_by_call_id(call_id)
            if entry:
                payload = json.dumps({
                    "status": entry.get("status", ""),
                    "transcript": entry.get("transcript", ""),
                    "summary": entry.get("summary", ""),
                    "duration": entry.get("duration_seconds", 0),
                    "ended_reason": entry.get("ended_reason", ""),
                })
                yield f"data: {payload}\n\n"
                if entry.get("status") == "ended":
                    break
            t.sleep(2)
        yield "data: {\"done\": true}\n\n"
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/calls/<call_id>/detail")
@login_required
def call_detail_page(call_id: str):
    call_monitor.sync_call_from_vapi(call_id)
    entry = call_monitor.get_call_by_call_id(call_id)
    if not entry:
        flash("Call not found.", "info")
        return redirect(url_for("live_calls_page"))
    if entry.get("status") == "ended" and not entry.get("ai_analysis"):
        call_monitor.analyze_call(call_id)
        entry = call_monitor.get_call_by_call_id(call_id)
    return render_template("call_detail.html", call=entry)


@app.route("/analytics")
@login_required
def analytics_page():
    call_metrics = call_monitor.compute_channel_metrics()
    all_analyses = call_monitor.get_all_analyses()
    events = em.load_events()
    total_contacts = sum(len(e.contacts) for e in events)
    total_emails = len(log.get_all_logs()) if hasattr(log, "get_all_logs") else 0
    email_stats = {"total_sent": total_emails}
    event_stats = []
    for ev in events:
        m = em.compute_metrics(ev)
        if m["total_invited"] > 0:
            event_stats.append({"name": ev.name, **m})
    event_stats.sort(key=lambda x: -x["rsvp_rate"])
    return render_template(
        "analytics.html",
        call_metrics=call_metrics,
        email_stats=email_stats,
        event_stats=event_stats[:15],
        total_contacts=total_contacts,
        recent_analyses=all_analyses[-10:],
    )


@app.route("/api/calls/<call_id>/status")
@login_required
def api_call_status(call_id: str):
    entry = call_monitor.sync_call_from_vapi(call_id)
    if not entry:
        entry = call_monitor.get_call_by_call_id(call_id)
    if not entry:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "status": entry.get("status"),
        "transcript": entry.get("transcript", ""),
        "listen_url": entry.get("listen_url", ""),
        "summary": entry.get("summary", ""),
        "duration": entry.get("duration_seconds", 0),
    })


# ── Outreach Schedule routes ─────────────────────────────────


@app.route("/outreach/schedule")
@login_required
def outreach_schedule_page():
    status_filter = request.args.get("status", "")
    type_filter = request.args.get("type", "")
    event_filter = request.args.get("event", "")
    items = outreach_queue.get_queue_filtered(
        status=status_filter, action_type=type_filter, event_id=event_filter,
    )
    all_items = outreach_queue.get_queue_filtered()
    events = em.load_events()
    event_map = {e.id: e.name for e in events}
    event_counts = {}
    for i in all_items:
        event_counts[i["event_id"]] = event_counts.get(i["event_id"], 0) + 1
    return render_template(
        "outreach_schedule.html",
        queue=items, event_map=event_map, events=events,
        status_filter=status_filter, type_filter=type_filter,
        event_filter=event_filter, event_counts=event_counts,
    )


def _schedule_redirect():
    """Return redirect to per-event or global schedule based on return_to param."""
    ret = request.form.get("return_to", "") or request.args.get("return_to", "")
    if ret.startswith("event:"):
        eid = ret[6:]
        return redirect(url_for("event_schedule_page", event_id=eid))
    return redirect(url_for("outreach_schedule_page"))


@app.post("/outreach/queue/<action_id>/approve")
@login_required
def approve_queue_action(action_id: str):
    outreach_queue.update_status(action_id, "approved")
    flash("Action approved.", "info")
    return _schedule_redirect()


@app.post("/outreach/queue/<action_id>/skip")
@login_required
def skip_queue_action(action_id: str):
    outreach_queue.update_status(action_id, "skipped")
    flash("Action skipped.", "info")
    return _schedule_redirect()


@app.post("/outreach/queue/<action_id>/delete")
@login_required
def delete_queue_action(action_id: str):
    outreach_queue.delete_action(action_id)
    flash("Action deleted.", "info")
    return _schedule_redirect()


@app.post("/outreach/queue/<action_id>/reschedule")
@login_required
def reschedule_queue_action(action_id: str):
    new_time = request.form.get("scheduled_at", "")
    if not new_time:
        flash("No time provided.", "info")
        return _schedule_redirect()
    if "T" not in new_time:
        new_time += "T10:00:00Z"
    elif not new_time.endswith("Z"):
        new_time += "Z"
    outreach_queue.reschedule(action_id, new_time)
    flash("Rescheduled and approved.", "info")
    return _schedule_redirect()


@app.post("/outreach/queue/<action_id>/regenerate")
@login_required
def regenerate_queue_action(action_id: str):
    action = outreach_queue.get_by_id(action_id)
    if not action:
        flash("Action not found.", "info")
        return redirect(url_for("outreach_schedule_page"))
    event = em.get_event(action["event_id"])
    if not event:
        flash("Event not found.", "info")
        return redirect(url_for("outreach_schedule_page"))
    contact = next((c for c in event.contacts if c.id == action["contact_id"]), None)
    if not contact:
        flash("Contact not found.", "info")
        return redirect(url_for("outreach_schedule_page"))
    ctx = _person_context_for_contact(contact)
    atype = action["action_type"]
    if atype == "email_initial":
        gen = generate_initial_email(
            event.name, event.date, event.description,
            event.audience_type, contact.name,
            contact_role=contact.contact_role.value, event=event, **ctx,
        )
    elif atype == "email_followup":
        gen = generate_followup_email(
            event.name, event.date, contact.name,
            contact_role=contact.contact_role.value, event=event, **ctx,
        )
    else:
        flash("Regeneration only supported for email actions.", "info")
        return redirect(url_for("outreach_schedule_page"))
    preview = f"Subject: {gen.subject}\n\n{gen.body}"
    outreach_queue.update_preview(action_id, preview)
    flash("Email regenerated with fresh AI content.", "info")
    return _schedule_redirect()


@app.post("/outreach/plan-all")
@login_required
def plan_all_outreach():
    cfg = aic.load_config()
    total = 0
    for event in em.load_events():
        targets = [
            c for c in event.contacts
            if c.status == ContactStatus.NOT_CONTACTED and _is_valid_email(c.email)
            and not outreach_queue.already_queued(event.id, c.id, "email_initial")
        ]
        if not targets:
            continue
        added = outreach_queue.plan_outreach_for_event(event, targets, cfg)
        for c in targets:
            _generate_preview_for_queued(event, c)
        total += added
    flash(f"Planned {total} outreach action(s) across all events.", "info")
    return redirect(url_for("outreach_schedule_page"))


def _generate_preview_for_queued(event, contact) -> None:
    """Fill in email preview for queued initial email actions that lack one."""
    items = outreach_queue.load_queue()
    changed = False
    for item in items:
        if (item["event_id"] == event.id and item["contact_id"] == contact.id
                and item["action_type"] == "email_initial" and not item.get("preview")):
            ctx = _person_context_for_contact(contact)
            gen = generate_initial_email(
                event.name, event.date, event.description,
                event.audience_type, contact.name,
                contact_role=contact.contact_role.value, event=event, **ctx,
            )
            item["preview"] = f"Subject: {gen.subject}\n\n{gen.body}"
            changed = True
    if changed:
        outreach_queue.save_queue(items)


@app.post("/outreach/approve-all")
@login_required
def approve_all_outreach():
    items = outreach_queue.load_queue()
    count = 0
    for item in items:
        if item["status"] == "planned":
            item["status"] = "approved"
            count += 1
    if count:
        outreach_queue.save_queue(items)
    flash(f"Approved {count} planned action(s).", "info")
    return redirect(url_for("outreach_schedule_page"))


# ── Per-Event Outreach Schedule ──────────────────────────────


@app.route("/events/<event_id>/schedule")
@login_required
def event_schedule_page(event_id: str):
    event = em.get_event(event_id)
    if not event:
        flash("Event not found.", "info")
        return redirect(url_for("index"))
    role = em.get_event_share_role(g.current_user, event)
    if not role:
        flash("You do not have access to this event.", "info")
        return redirect(url_for("index"))
    can_edit = _role_ok(role, "editor")
    status_filter = request.args.get("status", "")
    type_filter = request.args.get("type", "")
    items = outreach_queue.get_queue_filtered(
        status=status_filter, action_type=type_filter, event_id=event_id,
    )
    return render_template(
        "event_schedule.html",
        event=event,
        queue=items,
        status_filter=status_filter,
        type_filter=type_filter,
        can_edit=can_edit,
        event_role=role,
    )


@app.post("/events/<event_id>/schedule/plan")
@login_required
def plan_event_outreach(event_id: str):
    event = em.get_event(event_id)
    if not event:
        flash("Event not found.", "info")
        return redirect(url_for("index"))
    role = em.get_event_share_role(g.current_user, event)
    if not _role_ok(role, "editor"):
        flash("Not allowed.", "info")
        return redirect(url_for("index"))
    cfg = aic.load_config()
    targets = [
        c for c in event.contacts
        if c.status == ContactStatus.NOT_CONTACTED and _is_valid_email(c.email)
        and not outreach_queue.already_queued(event.id, c.id, "email_initial")
    ]
    added = 0
    if targets:
        added = outreach_queue.plan_outreach_for_event(event, targets, cfg)
        for c in targets:
            _generate_preview_for_queued(event, c)
    flash(f"Planned {added} outreach action(s) for {event.name}.", "info")
    return redirect(url_for("event_schedule_page", event_id=event_id))


@app.post("/events/<event_id>/schedule/approve-all")
@login_required
def approve_event_outreach(event_id: str):
    event = em.get_event(event_id)
    if not event:
        flash("Event not found.", "info")
        return redirect(url_for("index"))
    role = em.get_event_share_role(g.current_user, event)
    if not _role_ok(role, "editor"):
        flash("Not allowed.", "info")
        return redirect(url_for("index"))
    items = outreach_queue.load_queue()
    count = 0
    for item in items:
        if item["event_id"] == event_id and item["status"] == "planned":
            item["status"] = "approved"
            count += 1
    if count:
        outreach_queue.save_queue(items)
    flash(f"Approved {count} planned action(s) for {event.name}.", "info")
    return redirect(url_for("event_schedule_page", event_id=event_id))


# ── Calendar JSON API ────────────────────────────────────────


_CAL_COLORS = {
    ("email_initial", "planned"): {"bg": "#3b82f6", "border": "#2563eb", "text": "#fff"},
    ("email_initial", "approved"): {"bg": "#60a5fa", "border": "#3b82f6", "text": "#fff"},
    ("email_initial", "sent"): {"bg": "#93c5fd", "border": "#60a5fa", "text": "#1e3a5f"},
    ("email_followup", "planned"): {"bg": "#6366f1", "border": "#4f46e5", "text": "#fff"},
    ("email_followup", "approved"): {"bg": "#818cf8", "border": "#6366f1", "text": "#fff"},
    ("email_followup", "sent"): {"bg": "#a5b4fc", "border": "#818cf8", "text": "#312e81"},
    ("call_invite", "planned"): {"bg": "#f59e0b", "border": "#d97706", "text": "#fff"},
    ("call_invite", "approved"): {"bg": "#fbbf24", "border": "#f59e0b", "text": "#78350f"},
    ("call_invite", "sent"): {"bg": "#fcd34d", "border": "#fbbf24", "text": "#78350f"},
    ("call_followup", "planned"): {"bg": "#f97316", "border": "#ea580c", "text": "#fff"},
    ("call_followup", "approved"): {"bg": "#fb923c", "border": "#f97316", "text": "#fff"},
    ("call_followup", "sent"): {"bg": "#fdba74", "border": "#fb923c", "text": "#7c2d12"},
}
_CAL_SKIP = {"bg": "#ef4444", "border": "#dc2626", "text": "#fff"}
_CAL_FAIL = {"bg": "#9ca3af", "border": "#6b7280", "text": "#fff"}

_ACTION_LABELS = {
    "email_initial": "Email",
    "email_followup": "Follow-up",
    "call_invite": "Call",
    "call_followup": "Call F/U",
}


@app.route("/api/outreach-calendar")
@login_required
def api_outreach_calendar():
    event_id = request.args.get("event_id", "")
    status_filter = request.args.get("status", "")
    type_filter = request.args.get("type", "")
    items = outreach_queue.get_queue_filtered(
        status=status_filter, action_type=type_filter, event_id=event_id,
    )
    events = em.load_events()
    event_map = {e.id: e.name for e in events}

    cal_events = []
    for item in items:
        atype = item.get("action_type", "")
        status = item.get("status", "")
        colors = _CAL_COLORS.get((atype, status))
        if not colors:
            colors = _CAL_SKIP if status == "skipped" else _CAL_FAIL if status == "failed" else {"bg": "#6b7280", "border": "#4b5563", "text": "#fff"}

        label = _ACTION_LABELS.get(atype, atype.replace("_", " ").title())
        ev_name = event_map.get(item.get("event_id", ""), "")
        title = f"{label}: {item.get('contact_name', '?')}"
        if not event_id and ev_name:
            title = f"{ev_name}: {title}"

        cal_events.append({
            "id": item["id"],
            "title": title,
            "start": item.get("scheduled_at", ""),
            "backgroundColor": colors["bg"],
            "borderColor": colors["border"],
            "textColor": colors["text"],
            "extendedProps": {
                "action_type": atype,
                "status": status,
                "contact_name": item.get("contact_name", ""),
                "contact_email": item.get("contact_email", ""),
                "event_name": ev_name,
                "event_id": item.get("event_id", ""),
                "ai_reason": item.get("ai_reason", ""),
                "preview": item.get("preview", ""),
            },
        })
    return jsonify(cal_events)


# ── AI Settings routes ──────────────────────────────────────


@app.route("/outreach/ai-settings", methods=["GET", "POST"])
@login_required
def ai_settings_page():
    if request.method == "POST":
        cfg = aic.load_config()
        cfg["personality"] = request.form.get("personality", cfg["personality"])
        cfg["timing_rules"] = request.form.get("timing_rules", cfg["timing_rules"])
        cfg["email_rules"] = request.form.get("email_rules", cfg["email_rules"])
        cfg["call_rules"] = request.form.get("call_rules", cfg["call_rules"])
        cfg["auto_approve_emails"] = request.form.get("auto_approve_emails") == "on"
        cfg["auto_approve_calls"] = request.form.get("auto_approve_calls") == "on"
        cfg["followup_delay_days"] = int(request.form.get("followup_delay_days", 3) or 3)
        cfg["call_delay_after_email_days"] = int(request.form.get("call_delay_after_email_days", 2) or 2)
        cfg["blackout_hours_start"] = int(request.form.get("blackout_hours_start", 22) or 22)
        cfg["blackout_hours_end"] = int(request.form.get("blackout_hours_end", 8) or 8)
        cfg["max_emails_per_day"] = int(request.form.get("max_emails_per_day", 20) or 20)
        cfg["max_calls_per_day"] = int(request.form.get("max_calls_per_day", 10) or 10)
        cfg["sender_name"] = request.form.get("sender_name", cfg.get("sender_name", "")).strip()
        cfg["sender_title"] = request.form.get("sender_title", cfg.get("sender_title", "")).strip()
        cfg["sender_email"] = request.form.get("sender_email", cfg.get("sender_email", "")).strip()
        aic.save_config(cfg)
        flash("AI settings saved.", "info")
        return redirect(url_for("ai_settings_page"))
    cfg = aic.load_config()
    return render_template("ai_settings.html", cfg=cfg)


# ── Background web monitor & automation engine ──────────────
_monitor_state = {
    "running": False,
    "last_check": None,
    "checks_count": 0,
    "last_changes": 0,
    "interval_minutes": 0,
}


def _env_bool(key: str, default: str = "false") -> bool:
    return os.environ.get(key, default).strip().lower() in ("1", "true", "yes")


# ── Automation helpers ───────────────────────────────────────


def _auto_notify_for_changes(new_changes: list[dict]) -> None:
    if not _env_bool("AUTO_NOTIFY_ON_CHANGE"):
        return
    gmail_ok = bool(os.environ.get("GMAIL_ADDRESS") and os.environ.get("GMAIL_APP_PASSWORD"))
    for change in new_changes:
        eid = change.get("event_id", "")
        if not eid:
            continue
        events = em.load_events()
        event = next((e for e in events if e.som_event_id == eid), None)
        if not event or not event.contacts:
            continue
        for c in event.contacts:
            ctx = _person_context_for_contact(c)
            gen = generate_event_update_email(
                event.name, event.date,
                change.get("description", "Event updated"),
                c.name,
                contact_role=c.contact_role.value,
                company=ctx.get("company", ""),
                title=ctx.get("title", ""),
                notes=ctx.get("notes", ""),
            )
            log.log_outreach(
                event.id, c.id, c.name, EmailType.FOLLOW_UP,
                gen.body, subject=gen.subject,
            )
            if gmail_ok:
                from email_generator import get_sender_identity
                s_name, _s_title, s_email = get_sender_identity(event)
                email_sender.send_email(c.email, gen.subject, gen.body, reply_to=s_email, sender_name=s_name)


def _auto_import_new_events() -> int:
    """Auto-import SOM catalog entries that aren't yet app events. Returns count."""
    if not _env_bool("AUTO_IMPORT_EVENTS"):
        return 0
    catalog = scraper.load_som_events()
    events = em.load_events()
    existing_som_ids = {e.som_event_id for e in events if e.som_event_id}
    imported = 0
    for cat in catalog:
        cid = cat.get("id", "")
        if not cid or cid in existing_som_ids:
            continue
        if cat.get("status") == "past":
            continue
        event = em.create_event(
            name=cat.get("name", "SOM Event"),
            date=cat.get("date", ""),
            description=cat.get("description", ""),
            audience_type=cat.get("series", "SOM"),
            owner_id="system",
        )
        all_events = em.load_events()
        for i, e in enumerate(all_events):
            if e.id == event.id:
                e.som_event_id = cid
                all_events[i] = e
                break
        em.save_events(all_events)
        imported += 1
    return imported


def _auto_populate_contacts(event) -> int:
    """Auto-add contacts from People directory using AI recommendations."""
    if not _env_bool("AUTO_POPULATE_CONTACTS"):
        return 0
    max_contacts = int(os.environ.get("AUTO_CONTACTS_MAX", "20") or "20")
    if len(event.contacts) >= max_contacts:
        return 0

    people = pm.load_people()
    if not people:
        return 0

    summaries = [
        {"id": p.id, "name": p.name, "email": p.email,
         "company": p.company, "role": p.role, "tags": p.tags}
        for p in people
    ]
    try:
        ranked = recommend_people_for_event(
            event.name, event.date, event.description, event.audience_type, summaries
        )
    except Exception:
        ranked = []

    if not ranked:
        return 0

    limit = max_contacts - len(event.contacts)
    rows = []
    for rec in ranked[:limit]:
        pid = rec.get("id", "")
        p = pm.get_person(pid) if pid else None
        if p:
            rows.append((p.name, p.email))
            pm.append_event_to_person(pid, event.id)
    if rows:
        return em.add_contacts_bulk(event.id, rows)
    return 0


import re as _re

_EMAIL_RE = _re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
_PLACEHOLDER_PREFIXES = ("unknown@", "test@", "example@", "noreply@", "no-reply@", "placeholder@", "none@")


def _is_valid_email(addr: str) -> bool:
    if not addr or not _EMAIL_RE.match(addr.strip()):
        return False
    lower = addr.strip().lower()
    if any(lower.startswith(p) for p in _PLACEHOLDER_PREFIXES):
        return False
    if lower.endswith("@example.com") or lower.endswith("@test.com"):
        return False
    return True


def _auto_plan_outreach() -> int:
    """Plan outreach actions into the queue for contacts that need them."""
    if not _env_bool("AUTO_SEND_EMAILS"):
        return 0
    cfg = aic.load_config()
    planned = 0
    for event in em.load_events():
        targets = [
            c for c in event.contacts
            if c.status == ContactStatus.NOT_CONTACTED and _is_valid_email(c.email)
            and not outreach_queue.already_queued(event.id, c.id, "email_initial")
        ]
        if not targets:
            continue
        for c in targets:
            ctx = _person_context_for_contact(c)
            gen = generate_initial_email(
                event.name, event.date, event.description,
                event.audience_type, c.name,
                contact_role=c.contact_role.value, event=event, **ctx,
            )
            preview = f"Subject: {gen.subject}\n\n{gen.body}"
            auto_approve = cfg.get("auto_approve_emails", False)
            status = "approved" if auto_approve else "planned"
            now = datetime.now(timezone.utc)
            blackout_end = cfg.get("blackout_hours_end", 8)
            blackout_start = cfg.get("blackout_hours_start", 22)
            email_time = outreach_queue._next_good_slot(now, blackout_start, blackout_end)
            outreach_queue.add_action(
                event_id=event.id, contact_id=c.id,
                contact_name=c.name, contact_email=c.email,
                action_type="email_initial", scheduled_at=email_time,
                ai_reason="Initial outreach — auto-planned by automation pipeline",
                preview=preview, status=status,
            )
            planned += 1

            from datetime import timedelta
            followup_delay = cfg.get("followup_delay_days", 3)
            followup_time = outreach_queue._next_good_slot(
                datetime.fromisoformat(email_time.replace("Z", "+00:00")) + timedelta(days=followup_delay),
                blackout_start, blackout_end,
            )
            if not outreach_queue.already_queued(event.id, c.id, "email_followup"):
                outreach_queue.add_action(
                    event_id=event.id, contact_id=c.id,
                    contact_name=c.name, contact_email=c.email,
                    action_type="email_followup", scheduled_at=followup_time,
                    ai_reason=f"Follow-up {followup_delay} days after initial email",
                    preview="", status=status,
                )
                planned += 1

            call_delay = cfg.get("call_delay_after_email_days", 2)
            call_time = outreach_queue._next_good_slot(
                datetime.fromisoformat(email_time.replace("Z", "+00:00")) + timedelta(days=call_delay),
                blackout_start, blackout_end,
            )
            if not outreach_queue.already_queued(event.id, c.id, "call_invite"):
                call_status = "approved" if cfg.get("auto_approve_calls", False) else "planned"
                outreach_queue.add_action(
                    event_id=event.id, contact_id=c.id,
                    contact_name=c.name, contact_email=c.email,
                    action_type="call_invite", scheduled_at=call_time,
                    ai_reason=f"Phone follow-up {call_delay} days after email",
                    preview="", status=call_status,
                )
                planned += 1

    return planned


def _execute_approved_actions() -> int:
    """Execute approved queue actions whose scheduled time has passed."""
    cfg = aic.load_config()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    due = outreach_queue.get_due_approved(now_iso)
    executed = 0
    emails_today = 0
    calls_today = 0
    max_emails = cfg.get("max_emails_per_day", 20)
    max_calls = cfg.get("max_calls_per_day", 10)

    gmail_ok = bool(os.environ.get("GMAIL_ADDRESS") and os.environ.get("GMAIL_APP_PASSWORD"))

    for action in due:
        atype = action["action_type"]

        if atype in ("email_initial", "email_followup"):
            if not gmail_ok or emails_today >= max_emails:
                continue
            if not _is_valid_email(action.get("contact_email", "")):
                outreach_queue.update_status(action["id"], "failed")
                continue

            event = em.get_event(action["event_id"])
            if not event:
                outreach_queue.update_status(action["id"], "failed")
                continue

            contact = next((c for c in event.contacts if c.id == action["contact_id"]), None)
            if not contact:
                outreach_queue.update_status(action["id"], "failed")
                continue

            preview = action.get("preview", "")
            if preview and "\n\n" in preview:
                subj_line, body = preview.split("\n\n", 1)
                subject = subj_line.replace("Subject: ", "").strip()
            else:
                ctx = _person_context_for_contact(contact)
                if atype == "email_initial":
                    gen = generate_initial_email(
                        event.name, event.date, event.description,
                        event.audience_type, contact.name,
                        contact_role=contact.contact_role.value, event=event, **ctx,
                    )
                else:
                    gen = generate_followup_email(
                        event.name, event.date, contact.name,
                        contact_role=contact.contact_role.value, event=event, **ctx,
                    )
                subject, body = gen.subject, gen.body

            from email_generator import get_sender_identity
            s_name, _s_title, s_email = get_sender_identity(event)

            etype = EmailType.INITIAL if atype == "email_initial" else EmailType.FOLLOW_UP
            log.log_outreach(event.id, contact.id, contact.name, etype, body, subject=subject)
            email_sender.send_email(contact.email, subject, body, reply_to=s_email, sender_name=s_name)

            if atype == "email_initial":
                em.update_contact_status(event.id, contact.id, "contacted")

            outreach_queue.update_status(action["id"], "sent")
            emails_today += 1
            executed += 1

        elif atype in ("call_invite", "call_followup"):
            if calls_today >= max_calls:
                continue
            event = em.get_event(action["event_id"])
            if not event:
                outreach_queue.update_status(action["id"], "failed")
                continue
            contact = next((c for c in event.contacts if c.id == action["contact_id"]), None)
            if not contact:
                outreach_queue.update_status(action["id"], "failed")
                continue
            phone = _person_phone_for_contact(contact)
            if not phone:
                outreach_queue.update_status(action["id"], "failed")
                continue
            ctx = _person_context_for_contact(contact)
            bg_parts = []
            if ctx.get("company"):
                bg_parts.append(f"Works at {ctx['company']}")
            if ctx.get("title"):
                bg_parts.append(f"Title: {ctx['title']}")
            call_type = "invite" if atype == "call_invite" else "followup"
            call_fn = vapi_caller.call_invite if call_type == "invite" else vapi_caller.call_followup
            result = call_fn(
                phone=phone, recipient_name=contact.name,
                event_name=event.name, event_date=event.date,
                contact_role=contact.contact_role.value,
                company=ctx.get("company", ""),
                title=ctx.get("title", ""),
                background_notes=". ".join(bg_parts) if bg_parts else "",
            )
            if result.get("ok"):
                call_monitor.log_call(
                    call_id=result["call_id"], event_id=event.id,
                    contact_id=contact.id, contact_name=contact.name,
                    call_type=call_type,
                    listen_url=result.get("listen_url", ""),
                    control_url=result.get("control_url", ""),
                )
                log.log_outreach(
                    event.id, contact.id, contact.name,
                    EmailType.INITIAL if call_type == "invite" else EmailType.FOLLOW_UP,
                    f"[AI CALL — AUTO] Call placed to {phone}",
                    subject=f"AI Call: {event.name}",
                )
                outreach_queue.update_status(action["id"], "sent")
                calls_today += 1
                executed += 1
            else:
                outreach_queue.update_status(action["id"], "failed")

    return executed


def _auto_analyze_completed_calls() -> int:
    """Analyze completed calls that don't have analysis yet."""
    entries = call_monitor.load_call_log()
    analyzed = 0
    for entry in entries:
        if entry.get("status") != "ended":
            continue
        if entry.get("ai_analysis"):
            continue
        if not entry.get("transcript"):
            continue
        result = call_monitor.analyze_call(entry["call_id"])
        if result:
            outcome = result.get("outcome", "")
            if outcome in ("confirmed",) and entry.get("event_id") and entry.get("contact_id"):
                em.update_contact_status(entry["event_id"], entry["contact_id"], "confirmed")
            elif outcome in ("not_interested", "hung_up") and entry.get("event_id") and entry.get("contact_id"):
                em.update_contact_status(entry["event_id"], entry["contact_id"], "declined")
            analyzed += 1
    return analyzed


# ── Full automation pipeline ─────────────────────────────────


def _monitor_loop() -> None:
    """Background loop: scrape -> import -> contacts -> emails -> calls -> analyze."""
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

            _auto_import_new_events()

            for event in em.load_events():
                if not event.contacts:
                    try:
                        _auto_populate_contacts(event)
                    except Exception:
                        pass

            _auto_plan_outreach()
            _execute_approved_actions()

            call_monitor.sync_all_active()
            _auto_analyze_completed_calls()

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
