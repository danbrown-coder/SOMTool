"""User accounts and session helpers (JSON-backed)."""
from __future__ import annotations

import json
from pathlib import Path

from flask import session

from models import User, new_id, utc_now_iso

DATA_DIR = Path(__file__).resolve().parent / "data"
USERS_FILE = DATA_DIR / "users.json"


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_users() -> list[User]:
    _ensure_data_dir()
    if not USERS_FILE.exists():
        _seed_default_users()
    with open(USERS_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        return []
    return [User.from_dict(item) for item in raw]


def save_users(users: list[User]) -> None:
    _ensure_data_dir()
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump([u.to_dict() for u in users], f, indent=2, ensure_ascii=False)


def _seed_default_users() -> None:
    from werkzeug.security import generate_password_hash

    _ensure_data_dir()
    users = [
        User(
            id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
            username="admin",
            display_name="Dean (Admin)",
            email="dean@callutheran.edu",
            password_hash=generate_password_hash("admin123"),
            role="admin",
            created_at=utc_now_iso(),
        ),
        User(
            id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
            username="viewer",
            display_name="Demo Viewer",
            email="viewer@example.com",
            password_hash=generate_password_hash("viewer123"),
            role="user",
            created_at=utc_now_iso(),
        ),
    ]
    save_users(users)


def get_user_by_id(user_id: str) -> User | None:
    for u in load_users():
        if u.id == user_id:
            return u
    return None


def get_user_by_username(username: str) -> User | None:
    u = username.strip().lower()
    for user in load_users():
        if user.username.lower() == u:
            return user
    return None


def register_user(username: str, display_name: str, email: str, password: str) -> User | None:
    from werkzeug.security import generate_password_hash

    if get_user_by_username(username):
        return None
    user = User(
        id=new_id(),
        username=username.strip(),
        display_name=display_name.strip(),
        email=email.strip(),
        password_hash=generate_password_hash(password),
        role="user",
        created_at=utc_now_iso(),
    )
    users = load_users()
    users.append(user)
    save_users(users)
    return user


def verify_login(username: str, password: str) -> User | None:
    from werkzeug.security import check_password_hash

    user = get_user_by_username(username)
    if not user:
        return None
    if check_password_hash(user.password_hash, password):
        return user
    return None


def login_user(user: User) -> None:
    session["user_id"] = user.id
    session.permanent = True


def logout_user() -> None:
    session.pop("user_id", None)


def current_user_id() -> str | None:
    return session.get("user_id")


def get_first_admin_id() -> str | None:
    for u in load_users():
        if u.role == "admin":
            return u.id
    return None
