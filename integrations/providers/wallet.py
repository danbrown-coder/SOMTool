"""Apple Wallet + Google Wallet pass issuer for SOMTool tickets.

Issues tappable tickets at RSVP-confirm time and provides a QR that flips
`contact.status` to ATTENDED when scanned at the door.

Environment:
  # Apple Wallet (signed .pkpass)
  APPLE_WALLET_PASS_TYPE_IDENTIFIER=pass.org.example.somtool
  APPLE_WALLET_TEAM_ID=XXXXXXXXXX
  APPLE_WALLET_SIGNER_PEM_PATH=/etc/secrets/pass.pem
  APPLE_WALLET_WWDR_PEM_PATH=/etc/secrets/wwdr.pem

  # Google Wallet (REST API with a service account)
  GOOGLE_WALLET_ISSUER_ID=123456...
  GOOGLE_WALLET_SA_JSON=/etc/secrets/wallet-sa.json

Because full signing/PKCS7 is beyond this adapter's scope, the default path
returns a hosted `https://somtool/pass/<contact_id>` fallback URL that redirects
to whichever wallet the user's device supports. A real pkpass bundle can be
dropped in later.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from integrations.oauth import ProviderSpec
from integrations import register_provider

logger = logging.getLogger(__name__)


SPEC = ProviderSpec(
    slug="wallet",
    display_name="Apple / Google Wallet passes",
    authorize_url="",
    token_url="",
    scopes=[],
    client_id_env="APPLE_WALLET_PASS_TYPE_IDENTIFIER",
    client_secret_env="APPLE_WALLET_PASS_TYPE_IDENTIFIER",
    redirect_uri_env="APPLE_WALLET_PASS_TYPE_IDENTIFIER",
    icon_emoji="W",
    category="crm",
    description="Tappable tickets. QR check-in at the door.",
    unlocks=[
        "Auto-issue a wallet pass when an RSVP is confirmed",
        "QR scan at check-in flips contact.status to ATTENDED",
        "Push updates (room change, delay) land on the attendee's lock screen",
    ],
    is_popular=True,
    auth_style="api_key",
    api_key_env="APPLE_WALLET_PASS_TYPE_IDENTIFIER",
    docs_url="https://developer.apple.com/documentation/walletpasses",
)
register_provider(SPEC)


def build_pass_url(contact_id: str, event_id: str) -> str:
    """Return a hosted URL that streams the pkpass / Google Wallet JWT on tap."""
    base = os.environ.get("APP_BASE_URL", "").rstrip("/") or "http://localhost:5000"
    return f"{base}/pass/{contact_id}?event={event_id}"


def check_in_token(contact_id: str, event_id: str) -> str:
    """Deterministic short token embedded in the pass QR — used by the
    door-scan endpoint to flip ATTENDED.
    """
    import hashlib, hmac
    secret = (os.environ.get("FLASK_SECRET_KEY") or "somtool").encode()
    mac = hmac.new(secret, f"{event_id}:{contact_id}".encode(), hashlib.sha256).hexdigest()
    return mac[:16]


def verify_check_in_token(contact_id: str, event_id: str, token: str) -> bool:
    import hmac
    return hmac.compare_digest(check_in_token(contact_id, event_id), (token or "").strip().lower())


def build_google_wallet_jwt(contact_id: str, event_id: str) -> Optional[str]:
    """Return a signed JWT the browser redirects to `save-to-google-wallet`.
    Returns None if the service-account JSON isn't configured.
    """
    sa_path = os.environ.get("GOOGLE_WALLET_SA_JSON", "").strip()
    issuer = os.environ.get("GOOGLE_WALLET_ISSUER_ID", "").strip()
    if not sa_path or not issuer:
        return None
    try:
        import json, time
        from google.auth import jwt as gjwt

        with open(sa_path, "r", encoding="utf-8") as fh:
            sa = json.load(fh)
        payload = {
            "iss": sa.get("client_email"),
            "aud": "google",
            "typ": "savetowallet",
            "iat": int(time.time()),
            "payload": {
                "eventTicketObjects": [{
                    "id": f"{issuer}.somtool-{event_id}-{contact_id}",
                    "classId": f"{issuer}.somtool_class",
                    "state": "ACTIVE",
                }],
            },
        }
        creds = gjwt.Credentials.from_service_account_info(sa, audience="google")
        token = gjwt.encode(creds.signer, payload).decode()
        return token
    except Exception as exc:
        logger.warning("Google Wallet JWT failed: %s", exc)
        return None
