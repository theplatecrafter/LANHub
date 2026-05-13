# blueprints/server_config.py
"""
Server Configuration panel — DEV only.

Reads / writes configvars.json generically:
  - Every section except "admin" is shown and editable.
  - No field metadata is hardcoded here; the UI renders whatever the JSON contains.
  - Type is inferred from the existing JSON value (int, float, bool, str).
"""

import os

from flask import Blueprint, render_template, request, jsonify, session

from blueprints.admin.auth_utils import require_role
from glob_vars import app_log
import config

server_config_bp = Blueprint("server_config", __name__, url_prefix="/admin")


# ── Type coercion ─────────────────────────────────────────────────────────────

def _coerce(raw, original):
    """Cast incoming value to match the Python type of the original."""
    if isinstance(original, bool):
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("true", "1", "yes", "on")
    if isinstance(original, int):
        return int(raw)
    if isinstance(original, float):
        return float(raw)
    return str(raw)


# ── Routes ────────────────────────────────────────────────────────────────────

@server_config_bp.route("/config")
@require_role("DEV")
def server_config():
    data   = config.load_json()
    public = {k: v for k, v in data.items() if k != config.ADMIN_SECTION}
    return render_template("admin_config.html", config_data=public)


@server_config_bp.route("/config/save", methods=["POST"])
@require_role("DEV")
def server_config_save():
    incoming = request.get_json(silent=True)
    if not incoming or not isinstance(incoming, dict):
        return jsonify({"ok": False, "error": "No data received."}), 400

    current = config.load_json()

    errors = []
    for section, kv in incoming.items():
        if section == config.ADMIN_SECTION:
            continue
        if not isinstance(kv, dict):
            continue
        if section not in current:
            current[section] = {}
        for key, raw in kv.items():
            original = current[section].get(key)
            try:
                current[section][key] = _coerce(raw, original)
            except Exception as exc:
                errors.append(f"{section}.{key}: {exc}")

    if errors:
        return jsonify({"ok": False, "error": "; ".join(errors)}), 400

    config.save_json(current)
    config.reload()

    app_log.info("[config] Server configuration saved.")

    return jsonify({"ok": True})
