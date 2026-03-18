# config.py
"""
Single source of truth for LANHub configuration.

Loads configvars.json and exposes every value as a module-level name,
so all existing  `from config import X`  and  `from config import *`
patterns work identically to the old configvars.py approach.

Usage (anywhere in the codebase):
    from config import PORT, REPO_URL, SECRET_KEY   # explicit
    from config import *                             # wildcard (glob_vars style)
    import config; config.reload()                   # hot-reload after a save
"""

import json
import os
import secrets as _secrets

_BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
JSON_PATH  = os.path.join(_BASE_DIR, "configvars.json")

# Section key that is NEVER exposed to the UI or wildcard exports
ADMIN_SECTION = "admin"


# ── I/O helpers ──────────────────────────────────────────────────────────────

def load_json() -> dict:
    """Read and return the full configvars.json dict."""
    with open(JSON_PATH, "r") as fh:
        return json.load(fh)


def save_json(data: dict) -> None:
    """Atomically write the full configvars.json dict."""
    tmp = JSON_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, JSON_PATH)


# ── Flatten into module globals ───────────────────────────────────────────────

def _flatten(data: dict) -> None:
    """Inject every key from every section into this module's globals."""
    g = globals()
    for section, vals in data.items():
        if isinstance(vals, dict):
            for key, val in vals.items():
                g[key] = val


def reload() -> None:
    """Re-read the JSON and refresh all module-level names.
    Call this after programmatically writing configvars.json so that
    in-process code sees the new values without a restart.
    """
    _flatten(load_json())
    _ensure_secret_key()


def _ensure_secret_key() -> None:
    """Generate and persist SECRET_KEY if it is missing or still a placeholder."""
    g = globals()
    if not g.get("SECRET_KEY") or g["SECRET_KEY"] == "__generate__":
        key  = _secrets.token_hex(24)
        data = load_json()
        data.setdefault(ADMIN_SECTION, {})["SECRET_KEY"] = key
        save_json(data)
        g["SECRET_KEY"] = key


# ── Boot ──────────────────────────────────────────────────────────────────────

_flatten(load_json())
_ensure_secret_key()