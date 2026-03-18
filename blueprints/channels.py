from flask import Blueprint, render_template, request, jsonify
from werkzeug.security import check_password_hash
import functions as f
from glob_vars import app_log, error_log, access_log
from configvars import CHAT_MAX_CHARS, CHAT_RATE_LIMIT, CHAT_RATE_WINDOW, CHAT_HISTORY_ON_JOIN

channels_bp = Blueprint("channels", __name__)


@channels_bp.route("/channels")
def channels():
    return render_template("channels.html",
                           MAX_CHARS=CHAT_MAX_CHARS,
                           HISTORY=CHAT_HISTORY_ON_JOIN)


# ── Create ────────────────────────────────────────────────────────────────────
@channels_bp.route("/api/channels/create", methods=["POST"])
def api_create():
    title       = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    tags_raw    = request.form.get("tags", "")
    password    = request.form.get("password", "").strip()
    ip          = request.remote_addr

    if not title:
        return jsonify({"ok": False, "error": "Title is required."}), 400
    if len(title) > 60:
        return jsonify({"ok": False, "error": "Title too long (max 60 chars)."}), 400
    if not password:
        return jsonify({"ok": False, "error": "Password is required to manage this channel."}), 400

    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    if f.check_profanity(title):
        return jsonify({"ok": False, "error": "Title contains disallowed words."}), 400
    if description and f.check_profanity(description):
        return jsonify({"ok": False, "error": "Description contains disallowed words."}), 400
    for tag in tags:
        if f.check_profanity(tag):
            return jsonify({"ok": False, "error": f"Tag '{tag}' contains disallowed words."}), 400

    try:
        channel = f.create_channel(title, description, tags, password, ip)
        access_log.info(f"[channels] {ip} created channel #{channel['id']} '{title}'")
        return jsonify({"ok": True, "channel": channel})
    except Exception as e:
        error_log.error(f"[channels] create error: {e}")
        return jsonify({"ok": False, "error": "Server error."}), 500


# ── Search ────────────────────────────────────────────────────────────────────
@channels_bp.route("/api/channels/search")
def api_search():
    query = request.args.get("q", "").strip()
    tag   = request.args.get("tag", "").strip()
    results = f.search_channels(query, tag)
    import time, datetime
    for r in results:
        r["created_str"] = datetime.datetime.fromtimestamp(r["created_at"]).strftime("%Y-%m-%d %H:%M")
    return jsonify({"results": results})


# ── Tag autocomplete ──────────────────────────────────────────────────────────
@channels_bp.route("/api/channels/tags")
def api_tags():
    prefix = request.args.get("q", "").strip()
    return jsonify({"tags": f.channel_tag_suggestions(prefix)})


# ── Get single channel (for joining) ─────────────────────────────────────────
@channels_bp.route("/api/channels/<int:channel_id>")
def api_get(channel_id):
    ch = f.get_channel_by_id(channel_id)
    if not ch:
        return jsonify({"ok": False, "error": "Channel not found."}), 404
    ch.pop("password_hash", None)
    import datetime
    ch["created_str"] = datetime.datetime.fromtimestamp(ch["created_at"]).strftime("%Y-%m-%d %H:%M")
    return jsonify({"ok": True, "channel": ch})


# ── Edit ──────────────────────────────────────────────────────────────────────
@channels_bp.route("/api/channels/<int:channel_id>/edit", methods=["POST"])
def api_edit(channel_id):
    ch = f.get_channel_by_id(channel_id)
    if not ch:
        return jsonify({"ok": False, "error": "Channel not found."}), 404

    password = request.form.get("password", "").strip()
    if not check_password_hash(ch["password_hash"], password):
        return jsonify({"ok": False, "error": "Incorrect channel password."}), 403

    title       = request.form.get("title", "").strip() or None
    description = request.form.get("description", None)
    tags_raw    = request.form.get("tags", None)
    tags        = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw is not None else None

    f.edit_channel(channel_id, title, description, tags)
    app_log.info(f"[channels] {request.remote_addr} edited channel #{channel_id}")
    return jsonify({"ok": True})


# ── Delete ────────────────────────────────────────────────────────────────────
@channels_bp.route("/api/channels/<int:channel_id>/delete", methods=["POST"])
def api_delete(channel_id):
    ch = f.get_channel_by_id(channel_id)
    if not ch:
        return jsonify({"ok": False, "error": "Channel not found."}), 404

    password = request.form.get("password", "").strip()
    if not check_password_hash(ch["password_hash"], password):
        return jsonify({"ok": False, "error": "Incorrect channel password."}), 403

    f.delete_channel(channel_id)
    app_log.info(f"[channels] {request.remote_addr} deleted channel #{channel_id} '{ch['title']}'")
    return jsonify({"ok": True})