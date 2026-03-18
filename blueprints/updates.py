# blueprints/updates.py
from flask import Blueprint, render_template, request, jsonify, session
import functions as f
from glob_vars import app_log, error_log
import datetime

updates_bp = Blueprint("updates", __name__)


def _is_dev():
    return session.get("admin_role") == "DEV"

def _dev_name():
    return session.get("admin_name", "DEV")

def _fmt(row: dict) -> dict:
    row["date_str"] = datetime.datetime.fromtimestamp(row["timestamp"]).strftime("%B %d, %Y")
    row["time_str"] = datetime.datetime.fromtimestamp(row["timestamp"]).strftime("%H:%M")
    return row


@updates_bp.route("/updates")
def updates_page():
    return render_template("updates.html", is_dev=_is_dev())


@updates_bp.route("/api/updates")
def api_list():
    rows = [_fmt(r) for r in f.updates_get_all()]
    return jsonify({"updates": rows, "is_dev": _is_dev()})


@updates_bp.route("/api/updates/create", methods=["POST"])
def api_create():
    if not _is_dev():
        return jsonify({"ok": False, "error": "DEV access required."}), 403
    version     = request.form.get("version", "").strip()
    title       = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    if not version:
        return jsonify({"ok": False, "error": "Version is required."}), 400
    if not title:
        return jsonify({"ok": False, "error": "Title is required."}), 400
    if not description:
        return jsonify({"ok": False, "error": "Description is required."}), 400
    if f.check_profanity(title) or f.check_profanity(description):
        return jsonify({"ok": False, "error": "Content contains disallowed words."}), 400
    try:
        row = f.updates_create(version, title, description, _dev_name())
        app_log.info(f"[updates] DEV {_dev_name()} created update v{version}: {title!r}")
        return jsonify({"ok": True, "update": _fmt(row)})
    except Exception as e:
        error_log.error(f"[updates] create error: {e}")
        return jsonify({"ok": False, "error": "Server error."}), 500


@updates_bp.route("/api/updates/<int:update_id>/edit", methods=["POST"])
def api_edit(update_id):
    if not _is_dev():
        return jsonify({"ok": False, "error": "DEV access required."}), 403
    version     = request.form.get("version", "").strip()
    title       = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    if not version or not title or not description:
        return jsonify({"ok": False, "error": "All fields are required."}), 400
    if f.check_profanity(title) or f.check_profanity(description):
        return jsonify({"ok": False, "error": "Content contains disallowed words."}), 400
    f.updates_edit(update_id, version, title, description)
    row = f.updates_get_by_id(update_id)
    app_log.info(f"[updates] DEV {_dev_name()} edited update #{update_id}")
    return jsonify({"ok": True, "update": _fmt(row)})


@updates_bp.route("/api/updates/<int:update_id>/delete", methods=["POST"])
def api_delete(update_id):
    if not _is_dev():
        return jsonify({"ok": False, "error": "DEV access required."}), 403
    f.updates_delete(update_id)
    app_log.info(f"[updates] DEV {_dev_name()} deleted update #{update_id}")
    return jsonify({"ok": True})