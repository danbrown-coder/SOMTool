"""QuickBooks Online — push event P&L (payments + expenses) as journal entries.

Environment:
  QUICKBOOKS_CLIENT_ID=...
  QUICKBOOKS_CLIENT_SECRET=...
  QUICKBOOKS_REDIRECT_URI=...
  QUICKBOOKS_REALM_ID=...        # set on first connect; we also cache in meta
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
    slug="quickbooks",
    display_name="QuickBooks Online",
    authorize_url="https://appcenter.intuit.com/connect/oauth2",
    token_url="https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
    scopes=["com.intuit.quickbooks.accounting", "openid", "profile", "email"],
    client_id_env="QUICKBOOKS_CLIENT_ID",
    client_secret_env="QUICKBOOKS_CLIENT_SECRET",
    redirect_uri_env="QUICKBOOKS_REDIRECT_URI",
    icon_emoji="QB",
    category="ops",
    description="Push event revenue + expenses into QuickBooks as journal entries.",
    unlocks=[
        "Event registrations → QB sales receipts",
        "Event expenses → QB bills/expenses",
        "P&L per event right inside QB",
    ],
    auth_style="oauth2",
    docs_url="https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/",
)
register_provider(SPEC)


def _base(sandbox: bool = False) -> str:
    return "https://sandbox-quickbooks.api.intuit.com" if sandbox else "https://quickbooks.api.intuit.com"


def create_sales_receipt(user_id: str, amount_cents: int, customer_ref: str, memo: str) -> Optional[str]:
    tok = get_valid_access_token(user_id, SPEC.slug)
    realm = os.environ.get("QUICKBOOKS_REALM_ID", "").strip()
    if not tok or not realm:
        return None
    try:
        r = requests.post(
            f"{_base()}/v3/company/{realm}/salesreceipt",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json", "Accept": "application/json"},
            json={
                "Line": [{
                    "DetailType": "SalesItemLineDetail",
                    "Amount": amount_cents / 100.0,
                    "SalesItemLineDetail": {"ItemRef": {"value": "1"}},
                    "Description": memo,
                }],
                "CustomerRef": {"value": customer_ref or "1"},
                "PrivateNote": memo,
            },
            timeout=20,
        )
        r.raise_for_status()
        return ((r.json() or {}).get("SalesReceipt") or {}).get("Id")
    except Exception as exc:
        logger.warning("QuickBooks create_sales_receipt failed: %s", exc)
        return None
