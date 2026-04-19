"""Xero — alternative accounting backend.

Environment:
  XERO_CLIENT_ID=...
  XERO_CLIENT_SECRET=...
  XERO_REDIRECT_URI=...
  XERO_TENANT_ID=...
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from integrations.oauth import ProviderSpec, get_valid_access_token
from integrations import register_provider

logger = logging.getLogger(__name__)


SPEC = ProviderSpec(
    slug="xero",
    display_name="Xero",
    authorize_url="https://login.xero.com/identity/connect/authorize",
    token_url="https://identity.xero.com/connect/token",
    scopes=["offline_access", "accounting.transactions", "accounting.contacts"],
    client_id_env="XERO_CLIENT_ID",
    client_secret_env="XERO_CLIENT_SECRET",
    redirect_uri_env="XERO_REDIRECT_URI",
    icon_emoji="Xr",
    category="ops",
    description="Xero alternative to QuickBooks for international orgs.",
    unlocks=[
        "Event revenue → Xero invoices",
        "Event expenses → Xero bills",
        "P&L surfaces inside the event dashboard",
    ],
    auth_style="oauth2",
    docs_url="https://developer.xero.com/documentation/api/accounting/overview",
)
register_provider(SPEC)


def create_invoice(user_id: str, amount_cents: int, contact_name: str, description: str) -> Optional[str]:
    tok = get_valid_access_token(user_id, SPEC.slug)
    tenant = os.environ.get("XERO_TENANT_ID", "").strip()
    if not tok or not tenant:
        return None
    try:
        r = requests.post(
            "https://api.xero.com/api.xro/2.0/Invoices",
            headers={
                "Authorization": f"Bearer {tok}",
                "Xero-Tenant-Id": tenant,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={
                "Invoices": [{
                    "Type": "ACCREC",
                    "Contact": {"Name": contact_name or "SOMTool"},
                    "Status": "AUTHORISED",
                    "LineItems": [{
                        "Description": description,
                        "Quantity": 1,
                        "UnitAmount": amount_cents / 100.0,
                        "AccountCode": "200",
                    }],
                }]
            },
            timeout=20,
        )
        r.raise_for_status()
        return ((r.json() or {}).get("Invoices") or [{}])[0].get("InvoiceID")
    except Exception as exc:
        logger.warning("Xero create_invoice failed: %s", exc)
        return None
