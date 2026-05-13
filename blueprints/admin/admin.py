from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash
import subprocess, os, time
import functions as f
from glob_vars import app_log, error_log, access_log, BASE_DIR
import sys
import config
import threading

from .auth_utils import _role, _name, require_role, ROLE_LEVELS

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ── IP ban enforcement — call this from app.py before_request ─────────────────
def check_ban():
    """Call as: app.before_request(check_ban)"""
    # Skip admin routes so banned admins can still log in
    if request.path.startswith("/admin"):
        return None
    ban = f.is_ip_banned(request.remote_addr)
    if ban:
        reason = ban.get("reason") or "No reason given."
        return render_template("banned.html", reason=reason), 403
    return None


# ── Auth ──────────────────────────────────────────────────────────────────────
@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        role     = request.form.get("role", "").upper()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if role not in ROLE_LEVELS:
            return render_template("admin_login.html", error="Invalid role.",
                                   selected_role=role, next="/")

        admin = f.get_admin_by_username(username)
        if not admin or admin["role"] != role or \
                not check_password_hash(admin["password_hash"], password):
            return render_template("admin_login.html", error="Invalid credentials.",
                                   selected_role=role,
                                   next=request.form.get("next", "/"))

        session["admin_name"] = admin["username"]
        session["admin_role"] = admin["role"]
        access_log.info(f"[admin] {username!r} logged in as {role}")
        return redirect(request.form.get("next") or url_for("index"))

    return render_template("admin_login.html", error=None,
                           selected_role=request.args.get("role", "MOD"),
                           next=request.args.get("next", "/"))


@admin_bp.route("/logout", methods=["POST"])
def logout():
    app_log.info(f"[admin] {_name()!r} logged out")
    session.pop("admin_name", None)
    session.pop("admin_role", None)
    return redirect(url_for("index"))


@admin_bp.route("/me")
def me():
    return jsonify({"logged_in": bool(_role()), "name": _name(), "role": _role()})


# ── IP Ban Manager ────────────────────────────────────────────────────────────
@admin_bp.route("/bans")
@require_role("MOD")
def bans():
    return render_template("admin_bans.html", bans=f.get_all_bans())


@admin_bp.route("/bans/add", methods=["POST"])
@require_role("MOD")
def bans_add():
    ip        = request.form.get("ip", "").strip()
    reason    = request.form.get("reason", "").strip()
    duration  = request.form.get("duration", "permanent")

    if not ip:
        return jsonify({"ok": False, "error": "IP is required."}), 400

    expires_at = None
    if duration != "permanent":
        try:
            hours = float(duration)
            expires_at = time.time() + hours * 3600
        except ValueError:
            return jsonify({"ok": False, "error": "Invalid duration."}), 400

    ok, err = f.ban_ip(ip, reason, _name(), expires_at)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400

    app_log.info(f"[admin] {_name()!r} banned {ip!r} — {reason!r}")
    return jsonify({"ok": True})


@admin_bp.route("/bans/unban/<int:ban_id>", methods=["POST"])
@require_role("MOD")
def bans_unban(ban_id):
    f.unban_ip(ban_id)
    app_log.info(f"[admin] {_name()!r} unbanned id={ban_id}")
    return jsonify({"ok": True})


@admin_bp.route("/bans/edit/<int:ban_id>", methods=["POST"])
@require_role("MOD")
def bans_edit(ban_id):
    reason   = request.form.get("reason", "").strip()
    duration = request.form.get("duration", "permanent")
    expires_at = None
    if duration != "permanent":
        try:
            expires_at = time.time() + float(duration) * 3600
        except ValueError:
            return jsonify({"ok": False, "error": "Invalid duration."}), 400
    f.update_ban(ban_id, reason, expires_at)
    return jsonify({"ok": True})


# ── Report Queue ──────────────────────────────────────────────────────────────
@admin_bp.route("/reports")
@require_role("MOD")
def reports():
    status = request.args.get("status", "pending")
    source = request.args.get("source", "")
    return render_template("admin_reports.html",
                           reports=f.get_reports(status if status != "all" else None),
                           current_status=status,
                           current_source=source)


@admin_bp.route("/reports/<int:report_id>/action", methods=["POST"])
@require_role("MOD")
def reports_action(report_id):
    action = request.form.get("action", "")
    if action not in ("reviewed", "dismissed"):
        return jsonify({"ok": False, "error": "Invalid action."}), 400

    f.update_report_status(report_id, action, _name())

    # If action is "ban", also ban the reported IP
    if request.form.get("ban") == "1":
        report = next((r for r in f.get_reports() if r["id"] == report_id), None)
        if report and report.get("reported_ip"):
            f.ban_ip(report["reported_ip"],
                     f"Report #{report_id}: {report.get('reason','')}",
                     _name())
            app_log.info(f"[admin] {_name()!r} banned {report['reported_ip']!r} via report #{report_id}")

    app_log.info(f"[admin] {_name()!r} marked report #{report_id} as {action!r}")
    return jsonify({"ok": True})


# ── DB Inspector (DEV only) ───────────────────────────────────────────────────
@admin_bp.route("/db")
@require_role("DEV")
def db_inspector():
    tables = f.db_get_tables()
    return render_template("admin_db.html", tables=tables)


@admin_bp.route("/db/schema/<table>")
@require_role("DEV")
def db_schema(table):
    allowed = set(f.db_get_tables())
    if table not in allowed:
        return jsonify({"error": "Table not found."}), 404
    return jsonify({"schema": f.db_get_schema(table)})


@admin_bp.route("/db/browse/<table>")
@require_role("DEV")
def db_browse(table):
    allowed = set(f.db_get_tables())
    if table not in allowed:
        return jsonify({"error": "Table not found."}), 404
    try:
        limit  = min(int(request.args.get("limit", 100)), 500)
        offset = max(int(request.args.get("offset", 0)), 0)
        cols, rows = f.db_query(f"SELECT * FROM {table} LIMIT {limit} OFFSET {offset}")
        return jsonify({"columns": cols, "rows": rows,
                        "offset": offset, "limit": limit})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@admin_bp.route("/db/query", methods=["POST"])
@require_role("DEV")
def db_query_run():
    sql = request.form.get("sql", "").strip()
    if not sql:
        return jsonify({"error": "No SQL provided."}), 400
    try:
        cols, rows = f.db_query(sql)
        app_log.info(f"[admin] {_name()!r} ran DB query: {sql[:120]}")
        return jsonify({"columns": cols, "rows": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@admin_bp.route("/db/row/<table>/<int:rowid>")
@require_role("DEV")
def db_get_row(table, rowid):
    allowed = set(f.db_get_tables())
    if table not in allowed:
        return jsonify({"error": "Table not found."}), 404
    try:
        result = f.db_get_row(table, rowid)
        if not result:
            return jsonify({"error": "Row not found."}), 404
        cols, row = result
        return jsonify({"columns": cols, "row": row})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
 
 
@admin_bp.route("/db/insert/<table>", methods=["POST"])
@require_role("DEV")
def db_insert_row(table):
    allowed = set(f.db_get_tables())
    if table not in allowed:
        return jsonify({"ok": False, "error": "Table not found."}), 404
    data = request.get_json(silent=True) or {}
    row_data = data.get("row", {})
    if not row_data:
        return jsonify({"ok": False, "error": "No data provided."}), 400
    try:
        new_id = f.db_insert(table, row_data)
        app_log.info(f"[admin] {_name()!r} inserted row into {table!r} (rowid={new_id})")
        return jsonify({"ok": True, "rowid": new_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
 
 
@admin_bp.route("/db/update/<table>/<int:rowid>", methods=["POST"])
@require_role("DEV")
def db_update_row(table, rowid):
    allowed = set(f.db_get_tables())
    if table not in allowed:
        return jsonify({"ok": False, "error": "Table not found."}), 404
    data = request.get_json(silent=True) or {}
    row_data = data.get("row", {})
    if not row_data:
        return jsonify({"ok": False, "error": "No data provided."}), 400
    try:
        f.db_update_row(table, rowid, row_data)
        app_log.info(f"[admin] {_name()!r} updated row rowid={rowid} in {table!r}")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
 
 
@admin_bp.route("/db/delete/<table>/<int:rowid>", methods=["POST"])
@require_role("DEV")
def db_delete_row(table, rowid):
    allowed = set(f.db_get_tables())
    if table not in allowed:
        return jsonify({"ok": False, "error": "Table not found."}), 404
    try:
        f.db_delete_row(table, rowid)
        app_log.info(f"[admin] {_name()!r} deleted row rowid={rowid} from {table!r}")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ── Admin Power Control (DEV only) ────────────────────────────────────────────
@admin_bp.route("/power")
@require_role("DEV")
def power():
    return render_template("admin_power.html", admins=f.get_all_admins())


@admin_bp.route("/power/create", methods=["POST"])
@require_role("DEV")
def power_create():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role     = request.form.get("role", "").upper()
    if not username or not password or role not in ROLE_LEVELS:
        return jsonify({"ok": False, "error": "Missing or invalid fields."}), 400
    ok, err = f.create_admin(username, password, role)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    app_log.info(f"[admin] {_name()!r} created admin {username!r} ({role})")
    return jsonify({"ok": True})


@admin_bp.route("/power/edit/<int:admin_id>", methods=["POST"])
@require_role("DEV")
def power_edit(admin_id):
    new_username = request.form.get("username", "").strip()
    new_password = request.form.get("password", "").strip()
    new_role     = request.form.get("role", "").upper()
    target = f.get_admin_by_id(admin_id)
    if not target:
        return jsonify({"ok": False, "error": "Admin not found."}), 404
    if target["username"] == _name() and new_role != "DEV":
        return jsonify({"ok": False, "error": "Cannot change your own role."}), 400
    ok, err = f.edit_admin(admin_id, new_username or None,
                           new_password or None, new_role or None)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    app_log.info(f"[admin] {_name()!r} edited admin id={admin_id}")
    return jsonify({"ok": True})


@admin_bp.route("/power/delete/<int:admin_id>", methods=["POST"])
@require_role("DEV")
def power_delete(admin_id):
    target = f.get_admin_by_id(admin_id)
    if not target:
        return jsonify({"ok": False, "error": "Admin not found."}), 404
    if target["username"] == _name():
        return jsonify({"ok": False, "error": "Cannot delete your own account."}), 400
    f.delete_admin(admin_id)
    app_log.info(f"[admin] {_name()!r} deleted admin {target['username']!r}")
    return jsonify({"ok": True})

# ── Admin Console (DEV only) ───────────────────────────────────────────────
@admin_bp.route("/console")
@require_role("DEV")
def console():
    return render_template("admin_console.html")

@admin_bp.route("/is_dev_session")
def is_dev_session():
    """Public endpoint — returns whether the current session is DEV. Used by feedback page."""
    from flask import jsonify
    return jsonify({"is_dev": _role() == "DEV"})



# ── Access / Visibility settings (DEV+) ──────────────────────────────────────
@admin_bp.route("/access")
@require_role("DEV")
def access():
    return render_template(
        "admin_access.html",
        current_mode     = getattr(config, "SITE_MODE",                 "lan_only"),
        current_password = getattr(config, "SITE_PASSWORD",             ""),
        cookie_days      = int(getattr(config, "SITE_ACCESS_COOKIE_DAYS", 30)),
    )


@admin_bp.route("/access/save", methods=["POST"])
@require_role("DEV")
def access_settings_save():
    import config as _config

    mode       = request.form.get("mode",       "lan_only").strip()
    password   = request.form.get("password",   "").strip()
    try:
        cookie_days = max(1, min(365, int(request.form.get("cookie_days", 30))))
    except ValueError:
        cookie_days = 30

    if mode not in ("lan_only", "public_password", "both_password"):
        return jsonify({"ok": False, "error": "Invalid mode."}), 400

    data = _config.load_json()
    data.setdefault("access", {})
    data["access"]["SITE_MODE"]                = mode
    data["access"]["SITE_PASSWORD"]            = password
    data["access"]["SITE_ACCESS_COOKIE_DAYS"]  = cookie_days
    _config.save_json(data)
    _config.reload()

    app_log.info(
        f"[admin] {_name()!r} updated access settings: "
        f"mode={mode!r} password={'(set)' if password else '(none)'}"
    )

    return jsonify({"ok": True})