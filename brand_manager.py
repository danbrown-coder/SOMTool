"""Multi-tenant brand configuration.

Mirrors the pattern used in ai_config.py: a tiny JSON-file-backed store with
sensible defaults. One active tenant per deployment. A future multi-tenant
story (subdomain or user -> tenant) can replace `load_brand()` with a
per-request lookup without touching templates.

The `static/brand/<slug>/` folder holds each tenant's asset kit:
    logo.svg    small horizontal lockup for the sidebar / auth header
    mark.svg    square monogram (favicons, tiny callouts)
    brand.css   declares ONLY the --brand-* tokens (nothing else allowed)

Templates receive the active brand via the `brand` context variable injected
by a Flask context_processor in app.py.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "branding.json"
BRAND_STATIC_DIR = ROOT / "static" / "brand"

DEFAULTS: dict = {
    "slug": "callutheran",
    "name": "California Lutheran School of Management",
    "short_name": "Cal Lutheran SOM",
    "initials": "CL",
    "tagline": "Event Operating System",
}


def _brand_exists(slug: str) -> bool:
    if not slug:
        return False
    return (BRAND_STATIC_DIR / slug / "brand.css").is_file()


def load_brand() -> dict:
    """Return the active tenant brand config.

    Reads branding.json. Unknown or missing slugs fall back to "default"
    (the neutral slate-blue tenant) so a misconfigured deploy still renders.
    """
    result = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                result.update({k: v for k, v in stored.items() if isinstance(v, str)})
        except Exception:
            pass

    slug = result.get("slug", "").strip() or "default"
    if not _brand_exists(slug):
        slug = "default"
    result["slug"] = slug

    initials = (result.get("initials") or "").strip()
    if not initials:
        words = [w for w in (result.get("short_name") or result.get("name") or "").split() if w]
        initials = "".join(w[0] for w in words[:2]).upper() or "SO"
        result["initials"] = initials

    result["logo_url"] = f"/static/brand/{slug}/logo.svg"
    result["mark_url"] = f"/static/brand/{slug}/mark.svg"
    result["css_url"] = f"/static/brand/{slug}/brand.css"
    return result


def save_brand(cfg: dict) -> None:
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in (cfg or {}).items() if isinstance(v, str)})
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)


def available_brands() -> list[str]:
    """List slugs that have a shipped brand kit on disk."""
    if not BRAND_STATIC_DIR.is_dir():
        return []
    return sorted(p.name for p in BRAND_STATIC_DIR.iterdir() if p.is_dir() and (p / "brand.css").is_file())
