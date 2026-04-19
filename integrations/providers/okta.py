"""Okta — OIDC SSO + SCIM 2.0 provisioning for orgs that want enterprise identity.

Environment:
  OKTA_CLIENT_ID=...
  OKTA_CLIENT_SECRET=...
  OKTA_REDIRECT_URI=...
  OKTA_DOMAIN=https://your-org.okta.com
  OKTA_SCIM_TOKEN=...              # bearer for /scim/v2 endpoints
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from integrations.oauth import ProviderSpec
from integrations import register_provider

logger = logging.getLogger(__name__)


SPEC = ProviderSpec(
    slug="okta",
    display_name="Okta (SSO + SCIM)",
    authorize_url="",  # resolved from OKTA_DOMAIN at runtime
    token_url="",
    scopes=["openid", "profile", "email", "offline_access", "groups"],
    client_id_env="OKTA_CLIENT_ID",
    client_secret_env="OKTA_CLIENT_SECRET",
    redirect_uri_env="OKTA_REDIRECT_URI",
    icon_emoji="Ok",
    category="identity",
    description="Enterprise SSO and auto-provisioning via Okta OIDC + SCIM 2.0.",
    unlocks=[
        "Sign in with Okta (OIDC) for the whole org",
        "SCIM auto-provision/deprovision of SOMTool users",
        "Group → role mapping for RBAC",
    ],
    auth_style="oauth2",
    docs_url="https://developer.okta.com/docs/",
)
register_provider(SPEC)


def _domain() -> Optional[str]:
    d = os.environ.get("OKTA_DOMAIN", "").strip().rstrip("/")
    return d or None


def oidc_discovery() -> Optional[dict]:
    d = _domain()
    if not d:
        return None
    try:
        r = requests.get(f"{d}/.well-known/openid-configuration", timeout=10)
        r.raise_for_status()
        return r.json() or {}
    except Exception as exc:
        logger.warning("Okta oidc_discovery failed: %s", exc)
        return None


def scim_list_users(limit: int = 100) -> list[dict]:
    d = _domain()
    tok = os.environ.get("OKTA_SCIM_TOKEN", "").strip()
    if not d or not tok:
        return []
    try:
        r = requests.get(
            f"{d}/scim/v2/Users",
            headers={"Authorization": f"Bearer {tok}", "Accept": "application/scim+json"},
            params={"count": str(limit)},
            timeout=20,
        )
        r.raise_for_status()
        return (r.json() or {}).get("Resources", [])
    except Exception as exc:
        logger.warning("Okta scim_list_users failed: %s", exc)
        return []


def scim_create_user(email: str, given_name: str, family_name: str, active: bool = True) -> Optional[str]:
    d = _domain()
    tok = os.environ.get("OKTA_SCIM_TOKEN", "").strip()
    if not d or not tok or not email:
        return None
    try:
        r = requests.post(
            f"{d}/scim/v2/Users",
            headers={
                "Authorization": f"Bearer {tok}",
                "Content-Type": "application/scim+json",
                "Accept": "application/scim+json",
            },
            json={
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
                "userName": email,
                "name": {"givenName": given_name, "familyName": family_name},
                "emails": [{"primary": True, "value": email, "type": "work"}],
                "active": active,
            },
            timeout=20,
        )
        r.raise_for_status()
        return (r.json() or {}).get("id")
    except Exception as exc:
        logger.warning("Okta scim_create_user failed: %s", exc)
        return None


def scim_set_active(user_id: str, active: bool) -> bool:
    d = _domain()
    tok = os.environ.get("OKTA_SCIM_TOKEN", "").strip()
    if not d or not tok or not user_id:
        return False
    try:
        r = requests.patch(
            f"{d}/scim/v2/Users/{user_id}",
            headers={
                "Authorization": f"Bearer {tok}",
                "Content-Type": "application/scim+json",
            },
            json={
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                "Operations": [{"op": "replace", "path": "active", "value": active}],
            },
            timeout=20,
        )
        return r.status_code < 300
    except Exception as exc:
        logger.warning("Okta scim_set_active failed: %s", exc)
        return False
