# config.py
"""
Single source of truth for LANHub configuration.

Loads configvars.json and exposes every value as a module-level name,
so all existing  `from config import X`  and  `from config import *`
patterns work identically to the old configvars.py approach.

Usage (anywhere in the codebase):
    from config import PORT, SECRET_KEY   # explicit
    from config import *                  # wildcard (glob_vars style)
    import config; config.reload()        # hot-reload after a save
"""

import json
import os
import secrets as _secrets

_BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
_CONFIG_DIR = os.path.join(_BASE_DIR, "config")
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
    
def merge_with_example() -> dict:
    """
    After a git pull, synchronise configvars.json with configvars.example.json.

    Rules:
      - Admin section is NEVER touched (existing values kept as-is, no keys
        added or removed from it).
      - For every other section:
          * New keys in the example  → added with the example's default value.
          * Keys removed from example → removed from the live config.
          * Keys present in both     → live value is kept unchanged.
          * New sections in example  → added wholesale with example defaults.
          * Sections removed from example → removed from live config.

    Returns a dict describing what changed:
      { "added": [...], "removed": [...], "unchanged": [...] }
    """
    import os
    example_path = os.path.join(_CONFIG_DIR, "configvars.example.json")
    with open(example_path, "r") as fh:
        example = json.load(fh)

    current = load_json()
    admin_section = current.get(ADMIN_SECTION, {})

    added   = []
    removed = []

    merged = {}

    # 1. Walk every section in the example (this defines the authoritative shape)
    for section, example_keys in example.items():
        if section == ADMIN_SECTION:
            # Keep the live admin section completely intact
            merged[ADMIN_SECTION] = admin_section
            continue

        current_section = current.get(section, {})
        merged_section  = {}

        for key, default_val in example_keys.items():
            if key in current_section:
                merged_section[key] = current_section[key]   # keep live value
            else:
                merged_section[key] = default_val            # new key → use default
                added.append(f"{section}.{key}")

        # Detect removed keys (exist in live but not in example)
        for key in current_section:
            if key not in example_keys:
                removed.append(f"{section}.{key}")
                # (simply not copying it over is the removal)

        merged[section] = merged_section

    # 2. Detect removed sections (exist in live but not in example, excluding admin)
    for section in current:
        if section not in example and section != ADMIN_SECTION:
            removed.append(f"{section}.*")
            # (not copied into merged = removed)

    # 3. Ensure admin is always present (even if example doesn't have it)
    if ADMIN_SECTION not in merged:
        merged[ADMIN_SECTION] = admin_section

    save_json(merged)
    reload()

    return {"added": added, "removed": removed}


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