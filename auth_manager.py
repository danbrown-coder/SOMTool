"""User accounts and session helpers (DB-backed)."""
from __future__ import annotations

from flask import session

from db import get_session
from db_models import User as UserRow
from models import User, new_id, utc_now_iso
from org_manager import DEFAULT_ORG_ID, ensure_default_org


def _row_to_user(row: UserRow) -> User:
    return User(
        id=row.id,
        username=row.username,
        display_name=row.display_name or row.username,
        email=row.email or "",
        password_hash=row.password_hash or "",
        role=row.role or "user",
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


def _user_to_row_kwargs(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "email": u.email,
        "password_hash": u.password_hash,
        "role": u.role,
    }


def load_users() -> list[User]:
    ensure_default_org()
    with get_session() as sess:
        if sess.query(UserRow).count() == 0:
            _seed_default_users_in(sess)
        rows = sess.query(UserRow).order_by(UserRow.username).all()
        return [_row_to_user(r) for r in rows]


def save_users(users: list[User]) -> None:
    """Replace the users table with the given list. Used by admin tooling only."""
    ensure_default_org()
    with get_session() as sess:
        sess.query(UserRow).delete()
        for u in users:
            sess.add(UserRow(org_id=DEFAULT_ORG_ID, **_user_to_row_kwargs(u)))


def _seed_default_users_in(sess) -> None:
    from werkzeug.security import generate_password_hash

    defaults = [
        UserRow(
            id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
            org_id=DEFAULT_ORG_ID,
            username="admin",
            display_name="Dean (Admin)",
            email="dean@callutheran.edu",
            password_hash=generate_password_hash("admin123"),
            role="admin",
        ),
        UserRow(
            id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
            org_id=DEFAULT_ORG_ID,
            username="viewer",
            display_name="Demo Viewer",
            email="viewer@example.com",
            password_hash=generate_password_hash("viewer123"),
            role="user",
        ),
        UserRow(
            id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
            org_id=DEFAULT_ORG_ID,
            username="register",
            display_name="Registration Desk",
            email="register@local",
            password_hash=generate_password_hash("register123"),
            role="register_only",
        ),
    ]
    for row in defaults:
        sess.add(row)


def ensure_register_desk_user() -> None:
    """Add the registration-desk account on existing installs that predate it."""
    from werkzeug.security import generate_password_hash

    ensure_default_org()
    with get_session() as sess:
        existing = sess.query(UserRow).filter(
            UserRow.username.ilike("register")
        ).first()
        if existing is not None:
            return
        sess.add(
            UserRow(
                id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
                org_id=DEFAULT_ORG_ID,
                username="register",
                display_name="Registration Desk",
                email="register@local",
                password_hash=generate_password_hash("register123"),
                role="register_only",
            )
        )


def get_user_by_id(user_id: str) -> User | None:
    with get_session() as sess:
        row = sess.get(UserRow, user_id)
        return _row_to_user(row) if row else None


def get_user_by_username(username: str) -> User | None:
    u = (username or "").strip().lower()
    if not u:
        return None
    with get_session() as sess:
        row = sess.query(UserRow).filter(UserRow.username.ilike(u)).first()
        return _row_to_user(row) if row else None


def get_user_by_google_sub(google_sub: str) -> User | None:
    if not google_sub:
        return None
    with get_session() as sess:
        row = sess.query(UserRow).filter(UserRow.google_sub == google_sub).first()
        return _row_to_user(row) if row else None


def link_google_sub(user_id: str, google_sub: str) -> None:
    with get_session() as sess:
        row = sess.get(UserRow, user_id)
        if row is not None:
            row.google_sub = google_sub


def register_user(username: str, display_name: str, email: str, password: str) -> User | None:
    from werkzeug.security import generate_password_hash

    ensure_default_org()
    if get_user_by_username(username):
        return None
    row = UserRow(
        id=new_id(),
        org_id=DEFAULT_ORG_ID,
        username=username.strip(),
        display_name=display_name.strip(),
        email=email.strip(),
        password_hash=generate_password_hash(password),
        role="user",
    )
    with get_session() as sess:
        sess.add(row)
    return get_user_by_id(row.id)


def verify_login(username: str, password: str) -> User | None:
    from werkzeug.security import check_password_hash

    user = get_user_by_username(username)
    if not user:
        return None
    if check_password_hash(user.password_hash, password):
        return user
    return None


def login_user(user: User, remember: bool = False) -> None:
    session["user_id"] = user.id
    session.permanent = bool(remember)


def logout_user() -> None:
    session.pop("user_id", None)


def current_user_id() -> str | None:
    return session.get("user_id")


def get_first_admin_id() -> str | None:
    with get_session() as sess:
        row = sess.query(UserRow).filter(UserRow.role == "admin").order_by(UserRow.created_at).first()
        return row.id if row else None
