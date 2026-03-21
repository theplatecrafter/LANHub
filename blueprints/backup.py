# blueprints/backup.py
"""
Backup / Restore / Danger Zone — DEV only.

Endpoints:
  GET  /admin/backup                 — page
  GET  /admin/backup/export          — download zip
  POST /admin/backup/import          — upload + restore zip
  POST /admin/danger/reset-db        — wipe and reinitialise database
  POST /admin/danger/wipe-files      — delete all dropzone uploads
  POST /admin/danger/clear-logs      — truncate all log files
  POST /admin/danger/rotate-key      — generate new SECRET_KEY (boots everyone)
  POST /admin/danger/purge-bans      — delete all IP bans
  POST /admin/danger/purge-chat      — delete all chat + channel messages
  POST /admin/danger/nuke            — stop systemd, delete entire project
"""

import os
import io
import glob
import shutil
import signal
import zipfile
import secrets
import datetime
import threading
import subprocess

from flask import (
    Blueprint, render_template, request,
    jsonify, send_file, session
)

from blueprints.admin import require_role
from glob_vars import BASE_DIR, app_log, error_log
import config as _config
import functions as f

backup_bp = Blueprint("backup", __name__, url_prefix="/admin")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _dev_name() -> str:
    return session.get("admin_name", "DEV")


def _zip_dir(zf: zipfile.ZipFile, folder: str, arcname: str) -> None:
    """Recursively add a directory to a zip, skipping .pyc and __pycache__."""
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for file in files:
            if file.endswith(".pyc"):
                continue
            full = os.path.join(root, file)
            rel  = os.path.relpath(full, folder)
            zf.write(full, os.path.join(arcname, rel))


# ── Page ──────────────────────────────────────────────────────────────────────

@backup_bp.route("/backup")
@require_role("DEV")
def backup_page():
    # Gather sizes for display
    def _size(path: str) -> int:
        if os.path.isfile(path):
            return os.path.getsize(path)
        total = 0
        for r, _, files in os.walk(path):
            for f_ in files:
                try:
                    total += os.path.getsize(os.path.join(r, f_))
                except OSError:
                    pass
        return total

    def _fmt(b: int) -> str:
        if b >= 1 << 30: return f"{b/(1<<30):.1f} GB"
        if b >= 1 << 20: return f"{b/(1<<20):.1f} MB"
        if b >= 1 << 10: return f"{b/(1<<10):.1f} KB"
        return f"{b} B"

    items = [
        ("Database",         os.path.join(BASE_DIR, "app.db"),          "app.db"),
        ("Configuration",    os.path.join(BASE_DIR, "configvars.json"), "configvars.json"),
        ("Uploaded files",   os.path.join(BASE_DIR, "files"),           "files/"),
        ("Logs",             os.path.join(BASE_DIR, "logs"),            "logs/"),
        ("Redirector repo",  os.path.join(BASE_DIR, "redirector_repo"), "redirector_repo/"),
    ]

    manifest = [
        {"label": label, "path": arcname,
         "size": _fmt(_size(full)), "exists": os.path.exists(full)}
        for label, full, arcname in items
    ]

    return render_template("admin_backup.html", manifest=manifest)


# ── Export ────────────────────────────────────────────────────────────────────

@backup_bp.route("/backup/export")
@require_role("DEV")
def backup_export():
    buf = io.BytesIO()
    ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Single files
        for filename in ("app.db", "configvars.json"):
            full = os.path.join(BASE_DIR, filename)
            if os.path.isfile(full):
                zf.write(full, filename)

        # Directories
        for dirname in ("files", "logs", "redirector_repo"):
            full = os.path.join(BASE_DIR, dirname)
            if os.path.isdir(full):
                _zip_dir(zf, full, dirname)

        # Manifest so we can validate on import
        zf.writestr(
            "lanhub_backup.json",
            f'{{"version": 1, "timestamp": "{ts}", "host": "{os.uname().nodename}"}}'
        )

    buf.seek(0)
    app_log.info(f"[backup] {_dev_name()!r} exported server backup ({ts})")
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"lanhub_backup_{ts}.zip",
    )


# ── Import ────────────────────────────────────────────────────────────────────

@backup_bp.route("/backup/import", methods=["POST"])
@require_role("DEV")
def backup_import():
    file = request.files.get("backup_zip")
    if not file:
        return jsonify({"ok": False, "error": "No file uploaded."}), 400

    try:
        data = file.read()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()

            # Validate: must contain the manifest
            if "lanhub_backup.json" not in names:
                return jsonify({
                    "ok":    False,
                    "error": "This does not look like a valid LANHub backup "
                             "(missing lanhub_backup.json)."
                }), 400

            # Restore files — overwrite in place
            restored = []

            for filename in ("app.db", "configvars.json"):
                if filename in names:
                    dest = os.path.join(BASE_DIR, filename)
                    with zf.open(filename) as src, open(dest, "wb") as dst:
                        dst.write(src.read())
                    restored.append(filename)

            for dirname in ("files", "logs"):
                prefix = dirname + "/"
                entries = [n for n in names if n.startswith(prefix)]
                if entries:
                    dest_root = os.path.join(BASE_DIR, dirname)
                    os.makedirs(dest_root, exist_ok=True)
                    for entry in entries:
                        dest = os.path.join(BASE_DIR, entry)
                        if entry.endswith("/"):
                            os.makedirs(dest, exist_ok=True)
                        else:
                            os.makedirs(os.path.dirname(dest), exist_ok=True)
                            with zf.open(entry) as src, open(dest, "wb") as dst:
                                dst.write(src.read())
                    restored.append(prefix)

        _config.reload()
        app_log.info(
            f"[backup] {_dev_name()!r} restored backup — files: {restored}. "
            "Restart recommended."
        )
        return jsonify({
            "ok":      True,
            "message": f"Restored: {', '.join(restored)}. "
                       "Restart the server for all changes to take effect.",
        })

    except zipfile.BadZipFile:
        return jsonify({"ok": False, "error": "File is not a valid zip archive."}), 400
    except Exception as e:
        error_log.error(f"[backup] import error: {e}")
        return jsonify({"ok": False, "error": f"Restore failed: {e}"}), 500


# ── Danger Zone ───────────────────────────────────────────────────────────────

@backup_bp.route("/danger/reset-db", methods=["POST"])
@require_role("DEV")
def danger_reset_db():
    try:
        db_path = os.path.join(BASE_DIR, "app.db")
        if os.path.isfile(db_path):
            os.remove(db_path)
        from init import init_db
        init_db()
        app_log.info(f"[danger] {_dev_name()!r} reset the database.")
        return jsonify({"ok": True, "message": "Database wiped and reinitialised."})
    except Exception as e:
        error_log.error(f"[danger] reset-db error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@backup_bp.route("/danger/wipe-files", methods=["POST"])
@require_role("DEV")
def danger_wipe_files():
    try:
        dropzone_dir = os.path.join(BASE_DIR, "files", "dropzone")
        if os.path.isdir(dropzone_dir):
            shutil.rmtree(dropzone_dir)
            os.makedirs(dropzone_dir, exist_ok=True)

        # Clear upload records from DB
        conn = f.get_db()
        conn.execute("DELETE FROM upload_tags")
        conn.execute("DELETE FROM uploads")
        conn.commit()
        conn.close()

        app_log.info(f"[danger] {_dev_name()!r} wiped all uploaded files.")
        return jsonify({"ok": True, "message": "All uploaded files deleted."})
    except Exception as e:
        error_log.error(f"[danger] wipe-files error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@backup_bp.route("/danger/clear-logs", methods=["POST"])
@require_role("DEV")
def danger_clear_logs():
    try:
        log_dir = os.path.join(BASE_DIR, "logs")
        cleared = []
        for log_file in glob.glob(os.path.join(log_dir, "*.log")):
            open(log_file, "w").close()
            cleared.append(os.path.basename(log_file))
        app_log.info(f"[danger] {_dev_name()!r} cleared all logs.")
        return jsonify({"ok": True, "message": f"Cleared: {', '.join(cleared)}"})
    except Exception as e:
        error_log.error(f"[danger] clear-logs error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@backup_bp.route("/danger/rotate-key", methods=["POST"])
@require_role("DEV")
def danger_rotate_key():
    try:
        new_key = secrets.token_hex(32)
        data    = _config.load_json()
        data.setdefault("admin", {})["SECRET_KEY"] = new_key
        _config.save_json(data)
        _config.reload()
        app_log.info(
            f"[danger] {_dev_name()!r} rotated SECRET_KEY. "
            "All sessions (including this one) are now invalid."
        )
        return jsonify({
            "ok":      True,
            "message": "Secret key rotated. All sessions have been invalidated — "
                       "everyone including you will need to log in again.",
        })
    except Exception as e:
        error_log.error(f"[danger] rotate-key error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@backup_bp.route("/danger/purge-bans", methods=["POST"])
@require_role("DEV")
def danger_purge_bans():
    try:
        conn = f.get_db()
        conn.execute("DELETE FROM ip_bans")
        conn.commit()
        conn.close()
        app_log.info(f"[danger] {_dev_name()!r} purged all IP bans.")
        return jsonify({"ok": True, "message": "All IP bans removed."})
    except Exception as e:
        error_log.error(f"[danger] purge-bans error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@backup_bp.route("/danger/purge-chat", methods=["POST"])
@require_role("DEV")
def danger_purge_chat():
    try:
        conn = f.get_db()
        conn.execute("DELETE FROM chat_messages")
        conn.execute("DELETE FROM channel_messages")
        conn.commit()
        conn.close()
        app_log.info(f"[danger] {_dev_name()!r} purged all chat history.")
        return jsonify({"ok": True, "message": "All chat and channel messages deleted."})
    except Exception as e:
        error_log.error(f"[danger] purge-chat error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@backup_bp.route("/danger/nuke", methods=["POST"])
@require_role("DEV")
def danger_nuke():
    """
    Complete server removal:
      1. Stop + disable the lanhub systemd service
      2. Delete the service file
      3. Delete the entire project directory

    Runs in a background thread after a short delay so the HTTP
    response can reach the browser before the process dies.
    """
    confirm = request.form.get("confirm_phrase", "").strip()
    if confirm != "DELETE LANHUB FOREVER":
        return jsonify({
            "ok":    False,
            "error": 'You must type "DELETE LANHUB FOREVER" exactly to confirm.',
        }), 400

    app_log.info(
        f"[danger] {_dev_name()!r} initiated FULL SERVER NUKE. "
        "Shutting down in 3 seconds..."
    )

    def _nuke():
        import time
        time.sleep(3)

        # Stop + disable systemd service
        for cmd in [
            ["sudo", "systemctl", "stop",    "lanhub"],
            ["sudo", "systemctl", "disable", "lanhub"],
        ]:
            try:
                subprocess.run(cmd, timeout=10)
            except Exception:
                pass

        # Remove service file
        service = "/etc/systemd/system/lanhub.service"
        try:
            subprocess.run(["sudo", "rm", "-f", service], timeout=5)
            subprocess.run(["sudo", "systemctl", "daemon-reload"], timeout=10)
        except Exception:
            pass

        # Kill cloudflared
        pid_file = "/tmp/lanhub_cf.pid"
        try:
            if os.path.isfile(pid_file):
                with open(pid_file) as fh:
                    cf_pid = int(fh.read().strip())
                os.kill(cf_pid, signal.SIGTERM)
        except Exception:
            pass

        # Delete the project directory
        try:
            shutil.rmtree(BASE_DIR)
        except Exception as e:
            pass  # if we can't delete ourselves at least the service is gone

        # Kill this process
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_nuke, daemon=True).start()

    return jsonify({
        "ok":      True,
        "message": "Nuke initiated. The server will stop in ~3 seconds and "
                   "remove itself completely.",
    })