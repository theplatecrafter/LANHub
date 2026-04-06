from flask import (
    Blueprint, render_template, request, jsonify,
    send_from_directory, abort, session
)
from werkzeug.security import check_password_hash
import os
import functions as f
from glob_vars import app_log, access_log, error_log, BASE_DIR
from config import (DROPZONE_MAX_STORAGE_BYTES, DROPZONE_MAX_FILE_BYTES,
                        DROPZONE_RATE_LIMIT_BYTES, DROPZONE_RATE_WINDOW_HOURS)

dropzone_bp = Blueprint("dropzone", __name__)

DROPZONE_DIR = os.path.join(BASE_DIR, "files", "dropzone")


# ── Page ──────────────────────────────────────────────────────────────────────
@dropzone_bp.route("/dropzone")
def dropzone():
    stats = f.dropzone_stats()
    return render_template("dropzone.html", stats=stats,
                           max_file_mb=DROPZONE_MAX_FILE_BYTES // (1024 * 1024),
                           rate_limit_mb=DROPZONE_RATE_LIMIT_BYTES // (1024 * 1024),
                           rate_window_h=DROPZONE_RATE_WINDOW_HOURS)


# ── Upload ─────────────────────────────────────────────────────────────────────
@dropzone_bp.route("/api/dropzone/upload", methods=["POST"])
def api_upload():
    ip           = request.remote_addr
    display_name = request.form.get("display_name", "").strip()
    tags_raw     = request.form.get("tags", "")
    password     = request.form.get("password", "").strip() or None
    file         = request.files.get("file")

    if not file or not file.filename:
        return jsonify({"ok": False, "error": "No file provided."}), 400
    if not display_name:
        return jsonify({"ok": False, "error": "Display name is required."}), 400

    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    if f.check_profanity(display_name):
        return jsonify({"ok": False, "error": "Display name contains disallowed words."}), 400
    for tag in tags:
        if f.check_profanity(tag):
            return jsonify({"ok": False, "error": f"Tag '{tag}' contains disallowed words."}), 400

    try:
        upload = f.dropzone_save(file, display_name, tags, ip, password)
        
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        error_log.error(f"[dropzone] upload error: {e}")
        return jsonify({"ok": False, "error": "Server error during upload."}), 500

    access_log.info(f"[dropzone] {ip} uploaded '{upload['original_name']}' "
                    f"({upload['size_bytes']} bytes) as '{display_name}'")
    return jsonify({"ok": True, "upload": upload})


# ── Search ─────────────────────────────────────────────────────────────────────
@dropzone_bp.route("/api/dropzone/search")
def api_search():
    query = request.args.get("q", "").strip()
    tag   = request.args.get("tag", "").strip()
    results = f.dropzone_search(query, tag)
    # Stamp each result with human-readable size / time
    for r in results:
        r["size_str"]  = _fmt_size(r["size_bytes"])
        r["time_str"]  = _fmt_time(r["timestamp"])
    return jsonify({"results": results})


# ── Tag autocomplete ───────────────────────────────────────────────────────────
@dropzone_bp.route("/api/dropzone/tags")
def api_tags():
    prefix = request.args.get("q", "").strip()
    return jsonify({"tags": f.dropzone_tag_suggestions(prefix)})


# ── Download ───────────────────────────────────────────────────────────────────
@dropzone_bp.route("/api/dropzone/download/<int:upload_id>", methods=["GET", "POST"])
def api_download(upload_id):
    upload = f.dropzone_get_by_id(upload_id)
    if not upload:
        abort(404)

    # Password check
    if upload.get("password_hash"):
        password = request.form.get("password") or request.args.get("password", "")
        if not password:
            # Return 401 so the frontend knows to show a password prompt
            return jsonify({"ok": False, "protected": True,
                            "error": "Password required."}), 401
        if not check_password_hash(upload["password_hash"], password):
            return jsonify({"ok": False, "protected": True,
                            "error": "Incorrect password."}), 403

    access_log.info(f"[dropzone] {request.remote_addr} downloaded '{upload['original_name']}'")
    return send_from_directory(
        DROPZONE_DIR,
        upload["stored_name"],
        as_attachment=True,
        download_name=upload["original_name"],
        mimetype=upload.get("mime_type") or "application/octet-stream",
    )


# ── Delete (admin only or uploader's IP) ──────────────────────────────────────
@dropzone_bp.route("/api/dropzone/delete/<int:upload_id>", methods=["POST"])
def api_delete(upload_id):
    upload = f.dropzone_get_by_id(upload_id)
    if not upload:
        return jsonify({"ok": False, "error": "Not found."}), 404

    ip       = request.remote_addr
    is_admin = bool(session.get("admin_role"))
    is_owner = upload["uploader_ip"] == ip

    if not is_admin and not is_owner:
        return jsonify({"ok": False, "error": "Not authorised."}), 403

    # If file is password-protected, require the password to delete
    if upload.get("password_hash") and not is_admin:
        password = request.form.get("password", "").strip()
        if not password:
            return jsonify({"ok": False, "protected": True,
                            "error": "Password required to delete this file."}), 401
        if not check_password_hash(upload["password_hash"], password):
            return jsonify({"ok": False, "protected": True,
                            "error": "Incorrect password."}), 403

    f.dropzone_delete(upload_id)
    app_log.info(f"[dropzone] {ip} deleted upload #{upload_id} '{upload['original_name']}'")
    return jsonify({"ok": True})


# ── Storage stats ──────────────────────────────────────────────────────────────
@dropzone_bp.route("/api/dropzone/stats")
def api_stats():
    stats = f.dropzone_stats()
    stats["used_str"] = _fmt_size(stats["used_bytes"])
    stats["max_str"]  = _fmt_size(stats["max_bytes"])
    ip_used = f.dropzone_ip_used_in_window(request.remote_addr)
    stats["ip_used_bytes"] = ip_used
    stats["ip_used_str"]   = _fmt_size(ip_used)
    stats["ip_limit_str"]  = _fmt_size(DROPZONE_RATE_LIMIT_BYTES)
    stats["ip_used_pct"]   = round(ip_used / DROPZONE_RATE_LIMIT_BYTES * 100, 1) \
                             if DROPZONE_RATE_LIMIT_BYTES else 0
    return jsonify(stats)


# ── Report upload ─────────────────────────────────────────────────────────────
@dropzone_bp.route("/api/dropzone/report/<int:upload_id>", methods=["POST"])
def api_report(upload_id):
    upload = f.dropzone_get_by_id(upload_id)
    if not upload:
        return jsonify({"ok": False, "error": "File not found."}), 404

    reason = request.form.get("reason", "").strip()
    ip     = request.remote_addr

    rid = f.create_report(
        reporter_ip       = ip,
        reported_username = upload["display_name"],
        reported_ip       = upload["uploader_ip"],
        message_id        = upload_id,
        message_text      = upload["original_name"],
        reason            = reason,
        source            = "dropzone",
    )
    access_log.info(f"[dropzone] {ip} reported upload #{upload_id} — {reason!r}")
    return jsonify({"ok": True, "report_id": rid})



# ── Helpers ────────────────────────────────────────────────────────────────────
def _fmt_size(b: int) -> str:
    if b >= 1 << 30: return f"{b/(1<<30):.1f} GB"
    if b >= 1 << 20: return f"{b/(1<<20):.1f} MB"
    if b >= 1 << 10: return f"{b/(1<<10):.1f} KB"
    return f"{b} B"

def _fmt_time(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")