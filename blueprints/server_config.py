# blueprints/server_config.py
"""
Server Configuration panel — DEV only.
Reads / writes all non-admin variables in configvars.py.
When REPO_URL changes, automatically:
  1. Deletes redirector_repo/
  2. Clones the new repo
  3. Switches the git remote to SSH
  4. Pushes a fresh redirect HTML
"""

import os
import re
import shutil
import importlib.util

from flask import Blueprint, render_template, request, jsonify, session
from git import Repo as GitRepo

from blueprints.admin import require_role
from glob_vars import app_log, error_log, git_log, BASE_DIR, REDIRECTOR_PATH
import functions as f

server_config_bp = Blueprint("server_config", __name__, url_prefix="/admin")

# ── Constants ─────────────────────────────────────────────────────────────────

CONFIGVARS_PATH = os.path.join(BASE_DIR, "configvars.py")

# Variables that live under "admin settings" — never shown or touched
ADMIN_VARS = {"INITIAL_DEV_USERNAME", "INITIAL_DEV_PASSWORD", "SECRET_KEY"}

# Metadata for every editable variable
#   type  : "str" | "int" | "bytes"
#   unit  : display hint shown next to the input
#   desc  : one-line explanation shown under the field
VAR_META = {
    "REPO_URL": {
        "label": "Redirector Repo URL",
        "type":  "str",
        "unit":  None,
        "desc":  "GitHub repository used for the IP-redirector GitHub Pages site.",
    },
    "PORT": {
        "label": "Server Port",
        "type":  "int",
        "unit":  None,
        "desc":  "Port the LANHub Flask server listens on. Requires restart.",
    },
    "CHAT_MAX_CHARS": {
        "label": "Max Message Length",
        "type":  "int",
        "unit":  "chars",
        "desc":  "Maximum characters allowed per chat message.",
    },
    "CHAT_RATE_LIMIT": {
        "label": "Chat Rate Limit",
        "type":  "int",
        "unit":  "msgs",
        "desc":  "Maximum messages a user can send within the rate window.",
    },
    "CHAT_RATE_WINDOW": {
        "label": "Chat Rate Window",
        "type":  "int",
        "unit":  "sec",
        "desc":  "Sliding window (seconds) used for the chat rate limiter.",
    },
    "CHAT_HISTORY_ON_JOIN": {
        "label": "History On Join",
        "type":  "int",
        "unit":  "msgs",
        "desc":  "Number of recent messages sent to a user when they connect to chat.",
    },
    "DROPZONE_MAX_STORAGE_BYTES": {
        "label": "Max Total Storage",
        "type":  "bytes",
        "unit":  "bytes",
        "desc":  "Total storage cap for all Dropzone uploads combined.",
    },
    "DROPZONE_MAX_FILE_BYTES": {
        "label": "Max Single File Size",
        "type":  "bytes",
        "unit":  "bytes",
        "desc":  "Maximum size for any single uploaded file.",
    },
    "DROPZONE_RATE_WINDOW_HOURS": {
        "label": "Upload Rate Window",
        "type":  "int",
        "unit":  "hours",
        "desc":  "Rolling time window (hours) used for the per-IP upload rate limit.",
    },
    "DROPZONE_RATE_LIMIT_BYTES": {
        "label": "Per-IP Upload Limit",
        "type":  "bytes",
        "unit":  "bytes",
        "desc":  "Maximum bytes a single IP may upload within the rate window.",
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_configvars() -> dict:
    """
    Dynamically import configvars.py and return {key: value} for all
    variables listed in VAR_META.
    """
    spec = importlib.util.spec_from_file_location("_configvars_live", CONFIGVARS_PATH)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {key: getattr(mod, key, None) for key in VAR_META}


def _write_configvar(key: str, python_literal: str) -> None:
    """
    Replace the line `KEY = <anything>` in configvars.py with
    `KEY = <python_literal>`.  Raises ValueError if the key isn't found.
    """
    with open(CONFIGVARS_PATH, "r") as fh:
        content = fh.read()

    pattern = rf'^{re.escape(key)}\s*=.*$'
    replacement = f'{key} = {python_literal}'
    new_content, n = re.subn(pattern, replacement, content, flags=re.MULTILINE)

    if n == 0:
        raise ValueError(f"Variable '{key}' not found in configvars.py")

    with open(CONFIGVARS_PATH, "w") as fh:
        fh.write(new_content)


def _https_to_ssh(url: str) -> str:
    """
    Convert  https://github.com/USER/REPO[.git]
    →        git@github.com:USER/REPO.git
    Returns the original string unchanged if it doesn't match.
    """
    m = re.match(
        r'https://github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?\s*$',
        url.strip()
    )
    if m:
        return f"git@github.com:{m.group(1)}/{m.group(2)}.git"
    return url  # already SSH or unknown host — leave alone


def _reinit_redirector(new_repo_url: str) -> tuple[bool, str]:
    """
    Full redirector re-initialisation when REPO_URL changes:
      1. Delete old redirector_repo/
      2. Clone the new repo (HTTPS is fine for cloning)
      3. Switch the remote to SSH so future pushes don't need a password
      4. Push a fresh redirect HTML for the current IP
    Returns (success, message).
    """
    try:
        # 1 — wipe old clone
        if os.path.exists(REDIRECTOR_PATH):
            shutil.rmtree(REDIRECTOR_PATH)
            git_log.info("[config] Deleted old redirector_repo.")

        # 2 — fresh clone
        git_log.info(f"[config] Cloning {new_repo_url} …")
        GitRepo.clone_from(new_repo_url, REDIRECTOR_PATH)
        git_log.info("[config] Clone complete.")

        # 3 — switch remote to SSH
        ssh_url = _https_to_ssh(new_repo_url)
        repo = GitRepo(REDIRECTOR_PATH)
        repo.remotes.origin.set_url(ssh_url)
        git_log.info(f"[config] Remote switched to SSH: {ssh_url}")

        # 4 — push redirect HTML for current IP
        stats      = f.get_network_stats()
        current_ip = stats.get("ip_address", "127.0.0.1")

        # Read PORT from the freshly-written configvars so we use the new value
        fresh = _load_configvars()
        port  = int(fresh.get("PORT") or 5000)

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


# ── Routes ────────────────────────────────────────────────────────────────────

@server_config_bp.route("/config")
@require_role("DEV")
def server_config():
    current = _load_configvars()
    return render_template("admin_config.html", vars=current, meta=VAR_META)


@server_config_bp.route("/config/save", methods=["POST"])
@require_role("DEV")
def server_config_save():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"ok": False, "error": "No data received."}), 400

    # Snapshot old REPO_URL before any writes
    old_vars     = _load_configvars()
    old_repo_url = str(old_vars.get("REPO_URL") or "").strip()

    errors = []
    for key, raw_val in data.items():
        if key not in VAR_META or key in ADMIN_VARS:
            continue
        meta = VAR_META[key]
        try:
            if meta["type"] == "str":
                # Write as a quoted string literal
                escaped = str(raw_val).replace("\\", "\\\\").replace('"', '\\"')
                _write_configvar(key, f'"{escaped}"')
            else:
                # "int" and "bytes" — both stored as plain integers
                _write_configvar(key, str(int(raw_val)))
        except Exception as exc:
            errors.append(f"{key}: {exc}")

    if errors:
        return jsonify({"ok": False, "error": "; ".join(errors)}), 400

    app_log.info(
        f"[config] {session.get('admin_name')!r} saved server configuration."
    )

    # If REPO_URL changed — reinitialise the redirector
    new_repo_url     = str(data.get("REPO_URL") or "").strip()
    redirector_msg   = None
    redirector_ok    = True

    if new_repo_url and new_repo_url != old_repo_url:
        redirector_ok, redirector_msg = _reinit_redirector(new_repo_url)

    return jsonify({
        "ok":             True,
        "redirector_ok":  redirector_ok,
        "redirector_msg": redirector_msg,
    })