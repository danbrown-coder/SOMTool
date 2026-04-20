"""Runtime-editable environment store for the Integrations Hub.

Admins can paste OAuth client IDs / secrets / API keys into the in-app
"Set up keys" drawer. This module owns ``.env.local`` (gitignored, sits
next to ``.env``) and mirrors every write into ``os.environ`` so that
``ProviderSpec.configured()`` flips the moment a key is saved — no restart
required.

Public surface
--------------
- ``load()`` -- hydrate ``os.environ`` from ``.env.local`` at boot.
- ``get(name)`` / ``get_many(names)`` -- read current values.
- ``set_many(updates)`` -- atomic write of the delta to disk + process.
- ``mask(value)`` -- safe display string for the UI.
- ``provider_fields(spec)`` -- shaped list describing every env the drawer
  should render for a given ``ProviderSpec``.
- ``core_fields()`` -- the same shape for the global "core layer".

We never log secret values. Any debug line that might touch a value runs
through :func:`mask`.
"""
from __future__ import annotations

import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Iterable, Optional


# ── Constants ──────────────────────────────────────────────

_WRITE_LOCK = threading.Lock()


def _env_path() -> Path:
    """Location of ``.env.local``. Matches the repo root next to ``.env``."""
    return Path(__file__).resolve().parent.parent / ".env.local"


# Core-layer env vars surfaced on /admin/setup outside any provider tile.
CORE_FIELDS: list[dict] = [
    {
        "name": "GOOGLE_CLIENT_ID",
        "label": "Google OAuth Client ID",
        "required": True,
        "help": "From console.cloud.google.com -> APIs & Services -> Credentials -> OAuth 2.0 Client IDs.",
        "secret": False,
    },
    {
        "name": "GOOGLE_CLIENT_SECRET",
        "label": "Google OAuth Client Secret",
        "required": True,
        "help": "Shown once when you create the OAuth client. Re-generate in the Google console if you lose it.",
        "secret": True,
    },
    {
        "name": "GOOGLE_REDIRECT_URI",
        "label": "Google Redirect URI",
        "required": True,
        "help": "Must exactly match the Authorized redirect URI in your Google OAuth client.",
        "secret": False,
    },
    {
        "name": "INTEGRATIONS_ENCRYPTION_KEY",
        "label": "Integrations Encryption Key (Fernet)",
        "required": True,
        "help": "32-byte Fernet key used to encrypt stored OAuth tokens. Use the generate button if you don't have one.",
        "secret": True,
    },
    {
        "name": "APP_BASE_URL",
        "label": "Public App Base URL",
        "required": False,
        "help": "e.g. https://events.myschool.edu -- used for webhook signatures and wallet passes.",
        "secret": False,
    },
    {
        "name": "FLASK_SECRET_KEY",
        "label": "Flask Session Secret",
        "required": False,
        "help": "Signs browser sessions. Leaving this unset falls back to a development default.",
        "secret": True,
    },
]


# ── File parsing ───────────────────────────────────────────

_LINE_RE = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*=(.*)$")


def _parse_file(path: Path) -> tuple[list[str], dict[str, int]]:
    """Return (lines, index).

    ``lines`` is the raw file preserving comments/blanks so writes keep the
    user's original formatting. ``index`` maps ``KEY -> line number`` for
    the LAST occurrence of each key (matches dotenv override semantics).
    """
    lines: list[str] = []
    index: dict[str, int] = {}
    if not path.exists():
        return lines, index
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return lines, index
    for i, line in enumerate(raw.splitlines()):
        lines.append(line)
        m = _LINE_RE.match(line)
        if m:
            key = m.group(1)
            index[key] = i
    return lines, index


def _decode_value(raw: str) -> str:
    """Mirror python-dotenv's value decoding: strip an inline ``#`` comment
    when the value is unquoted, honor surrounding double/single quotes, and
    unescape ``\\n`` / ``\\r`` / ``\\t`` / ``\\"`` inside double quotes.
    """
    raw = raw.strip()
    if not raw:
        return ""
    if raw[0] == '"' and raw.endswith('"') and len(raw) >= 2:
        inner = raw[1:-1]
        return (
            inner.replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
            .replace("\\\"", "\"")
            .replace("\\\\", "\\")
        )
    if raw[0] == "'" and raw.endswith("'") and len(raw) >= 2:
        return raw[1:-1]
    if "#" in raw:
        raw = raw.split("#", 1)[0].rstrip()
    return raw


def _encode_value(value: str) -> str:
    """Quote the value if it needs quoting. Kept permissive so pasted
    secrets round-trip cleanly even when they contain ``=`` or ``#``.
    """
    if value == "":
        return ""
    special = any(c in value for c in (" ", "\t", "#", "\"", "'", "=", "\n", "\r"))
    if not special:
        return value
    escaped = (
        value.replace("\\", "\\\\")
        .replace("\"", "\\\"")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f"\"{escaped}\""


# ── Public reads ───────────────────────────────────────────


def get(name: str) -> str:
    """Return the current value of ``name`` from ``os.environ`` (stripped)."""
    return (os.environ.get(name) or "").strip()


def get_many(names: Iterable[str]) -> dict[str, str]:
    return {n: get(n) for n in names}


def mask(value: str) -> str:
    """Safe display string -- preserves enough to be recognizable without
    leaking the secret. ``sk_live_abcd1234EF`` -> ``sk_l••••••••34EF``.
    """
    if not value:
        return ""
    if len(value) <= 8:
        return "\u2022" * len(value)
    return f"{value[:4]}{'\u2022' * 8}{value[-4:]}"


# ── Public writes ──────────────────────────────────────────


def load(override: bool = True) -> None:
    """Merge ``.env.local`` into ``os.environ``.

    Called from ``app.py`` once after ``dotenv.load_dotenv()`` so runtime
    edits win over the baseline ``.env``.
    """
    path = _env_path()
    if not path.exists():
        return
    lines, _ = _parse_file(path)
    for line in lines:
        m = _LINE_RE.match(line)
        if not m:
            continue
        key = m.group(1)
        val = _decode_value(m.group(2))
        if override or key not in os.environ:
            os.environ[key] = val


def set_many(updates: dict[str, str]) -> None:
    """Persist ``updates`` atomically to ``.env.local`` and mirror them
    into ``os.environ``.

    - Empty-string value removes the key (from both file and process).
    - Existing lines are updated in place; new keys are appended.
    - Comments, blank lines, and unrelated keys are preserved verbatim.
    - Uses a temp file + atomic rename so an interrupted write cannot
      corrupt the file.
    - If the key is ``INTEGRATIONS_ENCRYPTION_KEY`` the cached Fernet
      instance is invalidated so the new key takes effect immediately.
    """
    if not updates:
        return

    path = _env_path()
    with _WRITE_LOCK:
        lines, index = _parse_file(path)

        for key, raw_value in updates.items():
            if not re.match(r"^[A-Z_][A-Z0-9_]*$", key):
                # defensive -- route validates too, but this is the last gate
                continue
            value = "" if raw_value is None else str(raw_value)
            if value == "":
                if key in index:
                    lines[index[key]] = None  # type: ignore[assignment]
                    del index[key]
                os.environ.pop(key, None)
                continue
            encoded = f"{key}={_encode_value(value)}"
            if key in index:
                lines[index[key]] = encoded
            else:
                lines.append(encoded)
                index[key] = len(lines) - 1
            os.environ[key] = value

        cleaned = [l for l in lines if l is not None]
        body = "\n".join(cleaned)
        if body and not body.endswith("\n"):
            body += "\n"

        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".env.local.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(body)
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        try:
            os.chmod(str(path), 0o600)
        except OSError:
            # Windows / non-POSIX filesystems silently ignore -- not fatal.
            pass

    # Fernet cache must be invalidated when the encryption key rotates.
    if "INTEGRATIONS_ENCRYPTION_KEY" in updates:
        try:
            import integrations.oauth as _oauth_mod
            _oauth_mod._fernet = None  # type: ignore[attr-defined]
        except Exception:
            pass


# ── Provider field shaping ─────────────────────────────────


def _add(seen: set, out: list, name: str, **extra) -> None:
    if not name or name in seen:
        return
    seen.add(name)
    out.append({"name": name, "value": get(name), "masked": mask(get(name)), **extra})


def provider_fields(spec) -> list[dict]:
    """Return the ordered list of env-var descriptors to render in the
    drawer for ``spec``. Each descriptor::

        {
          "name": "EVENTBRITE_CLIENT_ID",
          "label": "Client ID",
          "required": True,
          "secret": False,
          "value": "...",      # raw current value (admins only)
          "masked": "abcd\u2022\u2022\u20221234",
        }
    """
    seen: set[str] = set()
    out: list[dict] = []
    style = getattr(spec, "auth_style", "oauth2")

    if style == "oauth2":
        _add(seen, out, getattr(spec, "client_id_env", ""), label="Client ID", required=True, secret=False)
        _add(seen, out, getattr(spec, "client_secret_env", ""), label="Client Secret", required=True, secret=True)
        _add(seen, out, getattr(spec, "redirect_uri_env", ""), label="Redirect URI", required=True, secret=False)
    elif style == "api_key":
        _add(seen, out, getattr(spec, "api_key_env", ""), label="API Key", required=True, secret=True)
    elif style in ("bot_token", "basic", "custom"):
        _add(seen, out, getattr(spec, "client_id_env", ""), label="Access Token" if style == "bot_token" else "Client ID / Account", required=True, secret=(style != "oauth2"))
        _add(seen, out, getattr(spec, "client_secret_env", ""), label="Secret", required=False, secret=True)

    for name in getattr(spec, "extra_env", []) or []:
        _add(seen, out, name, label=_pretty_label(name), required=False, secret=_guess_secret(name))

    wh = getattr(spec, "webhook_secret_env", "") or ""
    if wh:
        _add(seen, out, wh, label="Webhook Secret", required=False, secret=True)

    return out


def core_fields() -> list[dict]:
    """Shape the core-layer env vars the same way as provider fields so
    the ``/admin/setup`` page can reuse the drawer UI.
    """
    out: list[dict] = []
    for f in CORE_FIELDS:
        val = get(f["name"])
        out.append({
            "name": f["name"],
            "label": f["label"],
            "required": f["required"],
            "secret": f["secret"],
            "help": f["help"],
            "value": val,
            "masked": mask(val),
        })
    return out


def _pretty_label(name: str) -> str:
    parts = name.split("_")
    if parts and parts[0] in (
        "EVENTBRITE", "HUBSPOT", "LUMA", "CANVAS", "NOTION", "AIRTABLE",
        "LINEAR", "ASANA", "TRELLO", "CLICKUP", "QUICKBOOKS", "XERO",
        "SALESFORCE", "DISCORD", "WHATSAPP", "MAILCHIMP", "BUFFER",
        "HOOTSUITE", "CANVA", "META", "LINKEDIN", "OKTA", "TWILIO",
        "QUALTRICS", "HANDSHAKE", "ENGAGE", "SIS", "CAMPUS", "APPLE",
        "GOOGLE",
    ):
        parts = parts[1:]
    label = " ".join(p.capitalize() for p in parts if p)
    return label or name


_SECRETISH = ("SECRET", "TOKEN", "KEY", "PASSWORD", "PASS")


def _guess_secret(name: str) -> bool:
    upper = name.upper()
    return any(s in upper for s in _SECRETISH)
