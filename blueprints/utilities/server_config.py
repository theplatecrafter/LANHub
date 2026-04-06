# blueprints/server_config.py
"""
Server Configuration panel — DEV only.

Reads / writes configvars.json generically:
  - Every section except "admin" is shown and editable.
  - No field metadata is hardcoded here; the UI renders whatever the JSON contains.
  - Type is inferred from the existing JSON value (int, float, bool, str).
  - When REPO_URL changes the redirector is fully re-initialised.
"""

import os
import re
import shutil

from flask import Blueprint, render_template, request, jsonify, session
from git import Repo as GitRepo

from blueprints.admin.auth_utils import require_role
from glob_vars import app_log, error_log, git_log, BASE_DIR, REDIRECTOR_PATH
import config
import functions as f

server_config_bp = Blueprint("server_config", __name__, url_prefix="/admin")


# ── Redirector helpers ────────────────────────────────────────────────────────

def _https_to_ssh(url: str) -> str:
    m = re.match(
        r'https?://github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?\s*$',
        url.strip()
    )
    if m:
        return f"git@github.com:{m.group(1)}/{m.group(2)}.git"
    return url


def _reinit_redirector(new_repo_url: str) -> tuple[bool, str]:
    try:
        if os.path.exists(REDIRECTOR_PATH):
            shutil.rmtree(REDIRECTOR_PATH)
            git_log.info("[config] Deleted old redirector_repo.")

        git_log.info(f"[config] Cloning {new_repo_url} …")
        GitRepo.clone_from(new_repo_url, REDIRECTOR_PATH)
        git_log.info("[config] Clone complete.")

        ssh_url = _https_to_ssh(new_repo_url)
        repo = GitRepo(REDIRECTOR_PATH)
        repo.remotes.origin.set_url(ssh_url)
        git_log.info(f"[config] Remote switched to SSH: {ssh_url}")

        stats      = f.get_network_stats()
        current_ip = stats.get("ip_address", "127.0.0.1")
        fresh_data = config.load_json()
        port       = int(fresh_data.get("general", {}).get("PORT", 5000))

        success = f.redirector_update(current_ip, port)
        msg = (
            "Redirector reinitialized and redirect HTML pushed successfully."
            if success
            else "Redirector cloned & SSH remote set, but push failed — check github_sync.log."
        )
        git_log.info(f"[config] {msg}")
        return success, msg

    except Exception as e:
        error_log.error(f"[config] Redirector reinit error: {e}")
        return False, f"Redirector reinit error: {e}"


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

    current  = config.load_json()
    old_repo = str(current.get("general", {}).get("REPO_URL", "")).strip()

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

    app_log.info(f"[config] {session.get('admin_name')!r} saved server configuration.")

    new_repo       = str(current.get("general", {}).get("REPO_URL", "")).strip()
    redirector_ok  = True
    redirector_msg = None

    if new_repo and new_repo != old_repo:
        redirector_ok, redirector_msg = _reinit_redirector(new_repo)

    return jsonify({
        "ok":             True,
        "redirector_ok":  redirector_ok,
        "redirector_msg": redirector_msg,
    })