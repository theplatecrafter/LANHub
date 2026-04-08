# blueprints/feedback.py
from flask import Blueprint, render_template, request, jsonify, session
import functions as f
from glob_vars import app_log, error_log, access_log

feedback_bp = Blueprint("feedback", __name__)


def _is_dev():
    return session.get("admin_role") == "DEV"

def _dev_name():
    return session.get("admin_name", "DEV")


# ── Page ──────────────────────────────────────────────────────────────────────
@feedback_bp.route("/feedback")
def feedback_page():
    return render_template("feedback.html")


# ── Create ────────────────────────────────────────────────────────────────────
@feedback_bp.route("/api/feedback/create", methods=["POST"])
def api_create():
    ip          = request.remote_addr
    type_       = request.form.get("type", "").strip()
    title       = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    username    = request.form.get("username", "").strip()
    tags_raw    = request.form.get("tags", "")

    if type_ not in ("bug", "feature", "other"):
        return jsonify({"ok": False, "error": "Invalid type."}), 400
    if not title:
        return jsonify({"ok": False, "error": "Title is required."}), 400
    if len(title) > 120:
        return jsonify({"ok": False, "error": "Title too long (max 120 chars)."}), 400
    if not username:
        return jsonify({"ok": False, "error": "Username is required."}), 400
    if len(username) > 32:
        return jsonify({"ok": False, "error": "Username too long (max 32 chars)."}), 400

    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    for field, val in [("title", title), ("description", description), ("username", username)]:
        if val and f.check_profanity(val):
            return jsonify({"ok": False, "error": f"{field.capitalize()} contains disallowed words."}), 400
    for tag in tags:
        if f.check_profanity(tag):
            return jsonify({"ok": False, "error": f"Tag '{tag}' contains disallowed words."}), 400

    try:
        item = f.feedback_create(type_, title, description, username, ip, tags)
        access_log.info(f"[feedback] {ip} ({username}) created #{item['id']} [{type_}] {title!r}")
        return jsonify({"ok": True, "item": item})
    except Exception as e:
        error_log.error(f"[feedback] create error: {e}")
        return jsonify({"ok": False, "error": "Server error."}), 500


# ── Search ────────────────────────────────────────────────────────────────────
@feedback_bp.route("/api/feedback/search")
def api_search():
    ip    = request.remote_addr
    query = request.args.get("q", "").strip()
    type_ = request.args.get("type", "").strip()
    tag   = request.args.get("tag", "").strip()
    results = f.feedback_search(query, type_, tag, viewer_ip=ip)
    import datetime
    for r in results:
        r["time_str"] = datetime.datetime.fromtimestamp(r["timestamp"]).strftime("%Y-%m-%d %H:%M")
    return jsonify({"results": results})


# ── Star (toggle) ─────────────────────────────────────────────────────────────
@feedback_bp.route("/api/feedback/<int:fb_id>/star", methods=["POST"])
def api_star(fb_id):
    ip = request.remote_addr
    result = f.feedback_toggle_star(fb_id, ip)
    return jsonify({"ok": True, **result})


# ── Replies ───────────────────────────────────────────────────────────────────
@feedback_bp.route("/api/feedback/<int:fb_id>/replies")
def api_replies(fb_id):
    import datetime
    replies = f.feedback_get_replies(fb_id)
    for r in replies:
        r["time_str"] = datetime.datetime.fromtimestamp(r["timestamp"]).strftime("%Y-%m-%d %H:%M")
    return jsonify({"replies": replies})


@feedback_bp.route("/api/feedback/<int:fb_id>/reply", methods=["POST"])
def api_reply(fb_id):
    ip       = request.remote_addr
    username = request.form.get("username", "").strip()
    content  = request.form.get("content", "").strip()

    if not username:
        return jsonify({"ok": False, "error": "Username is required."}), 400
    if not content:
        return jsonify({"ok": False, "error": "Reply cannot be empty."}), 400
    if len(content) > 1000:
        return jsonify({"ok": False, "error": "Reply too long (max 1000 chars)."}), 400
    if f.check_profanity(content) or f.check_profanity(username):
        return jsonify({"ok": False, "error": "Content contains disallowed words."}), 400

    # DEV status: real admin session OR the POST includes the DEV token from their session
    is_dev = _is_dev()
    # If a normal user is replying, ignore any is_dev claim from form
    reply = f.feedback_add_reply(fb_id, username, ip, content, is_dev)

    import datetime
    reply["time_str"] = datetime.datetime.fromtimestamp(reply["timestamp"]).strftime("%Y-%m-%d %H:%M")
    access_log.info(f"[feedback] {ip} ({username}) replied to #{fb_id}" + (" [DEV]" if is_dev else ""))
    return jsonify({"ok": True, "reply": reply})


# ── Resolve (DEV only) ────────────────────────────────────────────────────────
@feedback_bp.route("/api/feedback/<int:fb_id>/resolve", methods=["POST"])
def api_resolve(fb_id):
    if not _is_dev():
        return jsonify({"ok": False, "error": "DEV access required."}), 403
    note = request.form.get("note", "").strip()
    f.feedback_resolve(fb_id, _dev_name(), note)
    app_log.info(f"[feedback] DEV {_dev_name()} resolved #{fb_id}")
    return jsonify({"ok": True})


# ── Tag suggestions ───────────────────────────────────────────────────────────
@feedback_bp.route("/api/feedback/tags")
def api_tags():
    prefix = request.args.get("q", "").strip()
    return jsonify({"tags": f.feedback_tag_suggestions(prefix)})