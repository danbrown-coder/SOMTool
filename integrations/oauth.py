"""Generic OAuth2 authorization-code plumbing + encrypted token storage.

Providers declare a `ProviderSpec` with their specific URLs and scopes; this
module owns the code flow, state handling, encryption/decryption, and
refresh-token exchange. Each provider's API-client creation lives in its
own module (e.g. `integrations/google.py`).
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from urllib.parse import urlencode

from db import get_session
from db_models import Connection
from models import new_id


# ── Encryption ──────────────────────────────────────────────

_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    key = os.environ.get("INTEGRATIONS_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "INTEGRATIONS_ENCRYPTION_KEY is required. Generate one with:\n"
            "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError("cryptography package not installed") from exc
    _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt(value: str) -> str:
    if not value:
        return ""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value:
        return ""
    return _get_fernet().decrypt(value.encode()).decode()


# ── Provider spec ───────────────────────────────────────────


@dataclass
class ProviderSpec:
    slug: str
    display_name: str
    authorize_url: str
    token_url: str
    scopes: list[str]
    client_id_env: str
    client_secret_env: str
    redirect_uri_env: str
    extra_auth_params: dict = field(default_factory=dict)
    account_info_fn: Optional[Callable] = None  # takes access_token -> dict(email, id)
    icon_emoji: str = ""
    description: str = ""

    # ── Hub metadata (Phase B) ──
    category: str = "other"          # popular | campus | crm | ops | social | messaging | identity | other
    unlocks: list[str] = field(default_factory=list)    # 2-3 bullets of "what this unlocks"
    is_default: bool = False         # always-on, embedded rather than opt-in tile
    is_popular: bool = False         # float to the Popular tab
    auth_style: str = "oauth2"       # oauth2 | api_key | basic | bot_token | custom
    api_key_env: str = ""            # for api_key-style providers
    docs_url: str = ""
    webhook_secret_env: str = ""

    def client_id(self) -> str:
        return os.environ.get(self.client_id_env, "").strip()

    def client_secret(self) -> str:
        return os.environ.get(self.client_secret_env, "").strip()

    def redirect_uri(self) -> str:
        return os.environ.get(self.redirect_uri_env, "").strip()

    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "").strip() if self.api_key_env else ""

    def configured(self) -> bool:
        if self.auth_style == "api_key":
            return bool(self.api_key())
        if self.auth_style == "oauth2":
            return bool(self.client_id() and self.client_secret() and self.redirect_uri())
        # custom / bot_token / basic styles: provider decides via client_id_env presence
        return bool(os.environ.get(self.client_id_env, "").strip()) if self.client_id_env else False


# ── Flow ───────────────────────────────────────────────────


def build_authorize_url(spec: ProviderSpec, state: str) -> str:
    params = {
        "client_id": spec.client_id(),
        "redirect_uri": spec.redirect_uri(),
        "response_type": "code",
        "scope": " ".join(spec.scopes),
        "state": state,
    }
    params.update(spec.extra_auth_params or {})
    return f"{spec.authorize_url}?{urlencode(params)}"


def make_state() -> str:
    return secrets.token_urlsafe(32)


def exchange_code_for_tokens(spec: ProviderSpec, code: str) -> dict:
    """Exchange an authorization code for access + refresh tokens."""
    import requests

    resp = requests.post(
        spec.token_url,
        data={
            "code": code,
            "client_id": spec.client_id(),
            "client_secret": spec.client_secret(),
            "redirect_uri": spec.redirect_uri(),
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def refresh_access_token(spec: ProviderSpec, refresh_token: str) -> dict:
    import requests

    resp = requests.post(
        spec.token_url,
        data={
            "refresh_token": refresh_token,
            "client_id": spec.client_id(),
            "client_secret": spec.client_secret(),
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def store_connection(
    user_id: str,
    org_id: str | None,
    spec: ProviderSpec,
    token_response: dict,
    account_email: str = "",
    account_id: str = "",
) -> Connection:
    """Persist (or update) a Connection row from a fresh token response."""
    access_token = token_response.get("access_token", "")
    refresh_token = token_response.get("refresh_token", "")
    expires_in = token_response.get("expires_in")
    expires_at = None
    if expires_in:
        try:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        except (ValueError, TypeError):
            expires_at = None
    scopes = [s for s in (token_response.get("scope") or "").split() if s]
    if not scopes:
        scopes = list(spec.scopes)

    with get_session() as sess:
        row = (
            sess.query(Connection)
            .filter(Connection.user_id == user_id, Connection.provider == spec.slug)
            .first()
        )
        if row is None:
            row = Connection(
                id=new_id(),
                user_id=user_id,
                org_id=org_id,
                provider=spec.slug,
            )
            sess.add(row)
        row.account_email = account_email or row.account_email or ""
        row.account_id = account_id or row.account_id or None
        row.scopes = scopes
        row.access_token_enc = encrypt(access_token) if access_token else row.access_token_enc
        if refresh_token:
            row.refresh_token_enc = encrypt(refresh_token)
        row.expires_at = expires_at
        meta = dict(row.meta or {})
        if token_response.get("token_type"):
            meta["token_type"] = token_response["token_type"]
        row.meta = meta
        sess.flush()
        sess.expunge(row)
        return row


def get_valid_access_token(user_id: str, provider_slug: str) -> str | None:
    """Return a current access token for the user+provider, refreshing if needed.
    Returns None if no connection exists or refresh fails.
    """
    from integrations import get_connection, get_provider

    conn = get_connection(user_id, provider_slug)
    if conn is None:
        return None
    spec = get_provider(provider_slug)
    if spec is None:
        return None

    now = datetime.now(timezone.utc)
    needs_refresh = conn.expires_at is not None and conn.expires_at <= now + timedelta(seconds=60)

    if not needs_refresh and conn.access_token_enc:
        try:
            return decrypt(conn.access_token_enc)
        except Exception:
            needs_refresh = True

    if not conn.refresh_token_enc:
        return None
    try:
        refresh_token = decrypt(conn.refresh_token_enc)
        tok = refresh_access_token(spec, refresh_token)
    except Exception:
        return None
    store_connection(
        user_id=user_id,
        org_id=conn.org_id,
        spec=spec,
        token_response=tok,
        account_email=conn.account_email,
        account_id=conn.account_id or "",
    )
    return tok.get("access_token")


def get_decrypted_refresh_token(user_id: str, provider_slug: str) -> str | None:
    from integrations import get_connection

    conn = get_connection(user_id, provider_slug)
    if conn is None or not conn.refresh_token_enc:
        return None
    try:
        return decrypt(conn.refresh_token_enc)
    except Exception:
        return None
