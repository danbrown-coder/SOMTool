"""Sentry + PostHog observability wiring.

Both providers are optional: if the relevant env var isn't set the helpers
no-op so dev/demo deploys aren't noisy. Call `init_sentry()` and
`init_posthog()` once at app startup before requests are served.
"""
from __future__ import annotations

import logging
import os
from typing import Any

_sentry_initialized = False
_posthog_client = None
logger = logging.getLogger(__name__)


def init_sentry() -> bool:
    """Initialize the Sentry SDK if SENTRY_DSN is configured. Returns True if active."""
    global _sentry_initialized
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn or _sentry_initialized:
        return _sentry_initialized
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        from sentry_sdk.integrations.threading import ThreadingIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=os.environ.get("SENTRY_ENVIRONMENT", "development"),
            integrations=[FlaskIntegration(), ThreadingIntegration()],
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            send_default_pii=False,
        )
        _sentry_initialized = True
        logger.info("Sentry initialized.")
    except ImportError:
        logger.warning("sentry-sdk not installed; Sentry disabled.")
    except Exception as exc:  # pragma: no cover
        logger.warning("Sentry init failed: %s", exc)
    return _sentry_initialized


def init_posthog():
    """Initialize the PostHog client if POSTHOG_API_KEY is configured."""
    global _posthog_client
    api_key = os.environ.get("POSTHOG_API_KEY", "").strip()
    if not api_key or _posthog_client is not None:
        return _posthog_client
    try:
        from posthog import Posthog

        host = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")
        _posthog_client = Posthog(
            project_api_key=api_key,
            host=host,
            disabled=False,
        )
        logger.info("PostHog initialized.")
    except ImportError:
        logger.warning("posthog not installed; PostHog disabled.")
    except Exception as exc:  # pragma: no cover
        logger.warning("PostHog init failed: %s", exc)
    return _posthog_client


def capture_exception(exc: BaseException | None = None) -> None:
    """Safe-to-call anywhere. No-op when Sentry isn't configured."""
    if not _sentry_initialized:
        return
    try:
        import sentry_sdk

        if exc is None:
            sentry_sdk.capture_exception()
        else:
            sentry_sdk.capture_exception(exc)
    except Exception:  # pragma: no cover
        pass


def track(event: str, distinct_id: str | None = None, properties: dict[str, Any] | None = None) -> None:
    """Fire a PostHog event. No-op if PostHog isn't configured.

    `distinct_id` should be the user id if available, otherwise a stable
    anonymous id (session, IP hash, etc.). Falls back to "anonymous".
    """
    if _posthog_client is None:
        return
    try:
        _posthog_client.capture(
            distinct_id=distinct_id or "anonymous",
            event=event,
            properties=properties or {},
        )
    except Exception:  # pragma: no cover
        pass


def identify(user_id: str, traits: dict[str, Any] | None = None) -> None:
    """Associate traits with a user in PostHog."""
    if _posthog_client is None or not user_id:
        return
    try:
        _posthog_client.identify(distinct_id=user_id, properties=traits or {})
    except Exception:  # pragma: no cover
        pass


def safe_background(fn):
    """Decorator: wrap a background thread target so unhandled errors reach Sentry
    rather than dying silently.
    """
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            logger.exception("Background task %s failed", fn.__name__)
            capture_exception(exc)
            raise

    return wrapper
