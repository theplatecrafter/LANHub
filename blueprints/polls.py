# blueprints/polls.py
from flask import Blueprint, render_template, request, jsonify, session
import functions as f
from glob_vars import app_log, error_log, access_log

polls_bp = Blueprint("polls", __name__)


def _is_dev():
    return session.get("admin_role") == "DEV"

def _dev_name():
    return session.get("admin_name", "DEV")


@polls_bp.route("/polls")
def polls_page():
    return render_template("polls.html")


@polls_bp.route("/api/polls/create", methods=["POST"])
def api_create():
    ip          = request.remote_addr
    title       = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    poll_type   = request.form.get("poll_type", "single").strip()
    tags_raw    = request.form.get("tags", "")
    options_raw = request.form.getlist("options")  # list of option labels

    if poll_type not in ("single", "multi"):
        poll_type = "single"
    if not title:
        return jsonify({"ok": False, "error": "Title is required."}), 400
    if len(title) > 120:
        return jsonify({"ok": False, "error": "Title too long (max 120 chars)."}), 400

    options = [o.strip() for o in options_raw if o.strip()]
    if len(options) < 2:
        return jsonify({"ok": False, "error": "At least 2 options are required."}), 400
    if len(options) > 20:
        return jsonify({"ok": False, "error": "Max 20 options allowed."}), 400

    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    for field, val in [("title", title), ("description", description)]:
        if val and f.check_profanity(val):
            return jsonify({"ok": False, "error": f"{field.capitalize()} contains disallowed words."}), 400
    for opt in options:
        if f.check_profanity(opt):
            return jsonify({"ok": False, "error": f"Option '{opt}' contains disallowed words."}), 400
    for tag in tags:
        if f.check_profanity(tag):
            return jsonify({"ok": False, "error": f"Tag '{tag}' contains disallowed words."}), 400

    is_dev     = _is_dev()
    created_by = _dev_name() if is_dev else ""

    try:
        poll = f.poll_create(title, description, poll_type, options, tags, ip, is_dev, created_by)
        access_log.info(f"[polls] {ip} created poll #{poll['id']} {'[DEV] ' if is_dev else ''}{title!r}")
        return jsonify({"ok": True, "poll": poll})
    except Exception as e:
        error_log.error(f"[polls] create error: {e}")
        return jsonify({"ok": False, "error": "Server error."}), 500


@polls_bp.route("/api/polls/search")
def api_search():
    ip    = request.remote_addr
    query = request.args.get("q", "").strip()
    tag   = request.args.get("tag", "").strip()
    results = f.poll_search(query, tag, viewer_ip=ip)
    import datetime
    for r in results:
        r["time_str"] = datetime.datetime.fromtimestamp(r["timestamp"]).strftime("%Y-%m-%d %H:%M")
    return jsonify({"results": results})


@polls_bp.route("/api/polls/<int:poll_id>/vote", methods=["POST"])
def api_vote(poll_id):
    ip         = request.remote_addr
    option_ids = request.form.getlist("option_ids", type=int)
    if not option_ids:
        return jsonify({"ok": False, "error": "Select at least one option."}), 400
    try:
        poll = f.poll_vote(poll_id, option_ids, ip)
        return jsonify({"ok": True, "poll": poll})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except Exception as e:
        error_log.error(f"[polls] vote error: {e}")
        return jsonify({"ok": False, "error": "Server error."}), 500


@polls_bp.route("/api/polls/<int:poll_id>")
def api_get(poll_id):
    ip   = request.remote_addr
    poll = f.poll_get_by_id(poll_id, ip)
    if not poll:
        return jsonify({"ok": False, "error": "Not found."}), 404
    import datetime
    poll["time_str"] = datetime.datetime.fromtimestamp(poll["timestamp"]).strftime("%Y-%m-%d %H:%M")
    return jsonify({"ok": True, "poll": poll})


@polls_bp.route("/api/polls/<int:poll_id>/delete", methods=["POST"])
def api_delete(poll_id):
    if not _is_dev():
        return jsonify({"ok": False, "error": "DEV access required."}), 403
    f.poll_delete(poll_id)
    app_log.info(f"[polls] DEV {_dev_name()} deleted poll #{poll_id}")
    return jsonify({"ok": True})


@polls_bp.route("/api/polls/tags")
def api_tags():
    prefix = request.args.get("q", "").strip()
    return jsonify({"tags": f.poll_tag_suggestions(prefix)})