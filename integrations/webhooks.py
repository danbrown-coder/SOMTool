"""Unified webhook dispatcher.

A single Flask route `/webhooks/<provider>` lands here. Each provider can
register a verifier + handler pair; this module:

  - persists every inbound payload to `webhook_events` for audit
  - verifies signatures
  - dispatches to the provider's handler
  - catches and records failures for retry with exponential backoff

Providers register via `register_webhook(provider_slug, verifier, handler)`.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from db import get_session
from db_models import WebhookEventRow
from models import new_id

logger = logging.getLogger(__name__)

# (verifier, handler) tuples keyed by provider slug
_HANDLERS: dict[str, tuple[Callable[..., bool], Callable[..., Any]]] = {}


def register_webhook(
    provider: str,
    verifier: Callable[[dict, dict, bytes], bool],
    handler: Callable[[dict], Any],
) -> None:
    """Register a webhook for a provider.

    verifier(headers, parsed_json, raw_body) -> bool
    handler(parsed_json) -> any
    """
    _HANDLERS[provider] = (verifier, handler)


def has_handler(provider: str) -> bool:
    return provider in _HANDLERS


def dispatch(provider: str, headers: dict, parsed: dict, raw: bytes) -> tuple[int, dict]:
    """Dispatch a webhook. Returns (http_status, body_dict)."""
    verifier_handler = _HANDLERS.get(provider)
    if verifier_handler is None:
        _persist(provider, parsed, signature_ok=False, error="no handler registered")
        return 404, {"ok": False, "error": "unknown provider"}

    verifier, handler = verifier_handler
    try:
        ok_sig = bool(verifier(headers, parsed, raw))
    except Exception as exc:  # pragma: no cover — be forgiving
        logger.warning("webhook %s verifier crashed: %s", provider, exc)
        ok_sig = False

    event_id = _persist(
        provider,
        parsed,
        signature_ok=ok_sig,
        error="" if ok_sig else "signature verification failed",
    )
    if not ok_sig:
        return 401, {"ok": False, "error": "signature verification failed"}

    # Synchronous handler w/ short retry. Persistent DLQ is the
    # `webhook_events` row with processed=False + processing_error set.
    last_error: Optional[str] = None
    for attempt in range(3):
        try:
            handler(parsed)
            _mark_processed(event_id)
            return 200, {"ok": True}
        except Exception as exc:  # pragma: no cover
            last_error = str(exc)[:4000]
            logger.warning("webhook %s handler error (attempt %s): %s", provider, attempt + 1, exc)
            time.sleep(0.25 * (2 ** attempt))
    _mark_failed(event_id, last_error or "handler failed")
    return 500, {"ok": False, "error": last_error or "handler failed"}


# ── Internal persistence ──


def _persist(provider: str, payload: dict, *, signature_ok: bool, error: str = "") -> str:
    eid = new_id()
    try:
        with get_session() as sess:
            sess.add(
                WebhookEventRow(
                    id=eid,
                    provider=provider,
                    event_type=_guess_event_type(payload),
                    signature_ok=signature_ok,
                    processed=False,
                    processing_error=error or None,
                    payload=payload if isinstance(payload, dict) else {"raw": str(payload)[:8000]},
                )
            )
    except Exception as exc:  # pragma: no cover
        logger.exception("webhook persist failed: %s", exc)
    return eid


def _guess_event_type(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("type", "event", "event_type", "action", "kind"):
        v = payload.get(key)
        if isinstance(v, str):
            return v[:128]
    return ""


def _mark_processed(event_id: str) -> None:
    with get_session() as sess:
        row = sess.get(WebhookEventRow, event_id)
        if row is not None:
            row.processed = True
            row.processing_error = None


def _mark_failed(event_id: str, error: str) -> None:
    with get_session() as sess:
        row = sess.get(WebhookEventRow, event_id)
        if row is not None:
            row.processed = False
            row.processing_error = error[:4000]
            row.retries = (row.retries or 0) + 1


# ── Convenience verifiers ──


def verify_always_true(_headers: dict, _parsed: dict, _raw: bytes) -> bool:
    """Dev-only verifier. Swap for a real one in prod."""
    return True


def verify_hmac_sha256(secret: str, header_name: str, prefix: str = "") -> Callable:
    """Build a verifier that compares `sha256(body)` HMAC hex to the value
    at `header_name` (optionally stripping `prefix`).
    """
    import hmac
    import hashlib

    def _v(headers: dict, _parsed: dict, raw: bytes) -> bool:
        if not secret:
            return False
        got = headers.get(header_name) or headers.get(header_name.lower()) or ""
        if not got:
            return False
        if prefix and got.startswith(prefix):
            got = got[len(prefix):]
        mac = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(mac, got.strip())

    return _v
