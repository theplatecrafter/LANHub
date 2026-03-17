from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, jsonify, flash
)
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import functions as f
from glob_vars import app_log, error_log, access_log

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# ── Role hierarchy ────────────────────────────────────────────────────────────
ROLE_LEVELS = {"MOD": 1, "DEV": 2}

def _current_role() -> str | None:
    return session.get("admin_role")

def _current_name() -> str | None:
    return session.get("admin_name")

def require_role(min_role: str):
    """Decorator — redirects to login if not authenticated at the required level."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = _current_role()
            if not role or ROLE_LEVELS.get(role, 0) < ROLE_LEVELS[min_role]:
                return redirect(url_for("admin.login", next=request.path))
            return fn(*args, **kwargs)
        return wrapper
    return decorator

# ── Auth routes ───────────────────────────────────────────────────────────────
@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        role     = request.form.get("role", "").upper()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if role not in ROLE_LEVELS:
            return render_template("admin_login.html", error="Invalid role selected.")

        admin = f.get_admin_by_username(username)

        if not admin:
            return render_template("admin_login.html",
                                   error="Invalid credentials.", selected_role=role)

        if admin["role"] != role:
            return render_template("admin_login.html",
                                   error="Role does not match account.", selected_role=role)

        if not check_password_hash(admin["password_hash"], password):
            return render_template("admin_login.html",
                                   error="Invalid credentials.", selected_role=role)

        session["admin_name"] = admin["username"]
        session["admin_role"] = admin["role"]
        access_log.info(f"[admin] {username!r} logged in as {role}")

        next_url = request.form.get("next") or url_for("index")
        return redirect(next_url)

    return render_template(
        "admin_login.html",
        error=None,
        selected_role=request.args.get("role", "MOD"),
        next=request.args.get("next", "/"),
    )


@admin_bp.route("/logout", methods=["POST"])
def logout():
    name = _current_name()
    session.pop("admin_name", None)
    session.pop("admin_role", None)
    app_log.info(f"[admin] {name!r} logged out")
    return redirect(url_for("index"))


# ── Admin Power Control (DEV only) ────────────────────────────────────────────
@admin_bp.route("/power", methods=["GET"])
@require_role("DEV")
def power():
    admins = f.get_all_admins()
    return render_template("admin_power.html", admins=admins)


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

    app_log.info(f"[admin] DEV {_current_name()!r} created admin {username!r} ({role})")
    return jsonify({"ok": True})


@admin_bp.route("/power/edit/<int:admin_id>", methods=["POST"])
@require_role("DEV")
def power_edit(admin_id):
    new_username = request.form.get("username", "").strip()
    new_password = request.form.get("password", "").strip()  # blank = don't change
    new_role     = request.form.get("role", "").upper()

    # Guard: can't demote or delete yourself
    target = f.get_admin_by_id(admin_id)
    if not target:
        return jsonify({"ok": False, "error": "Admin not found."}), 404
    if target["username"] == _current_name() and new_role != "DEV":
        return jsonify({"ok": False, "error": "Cannot change your own role."}), 400

    ok, err = f.edit_admin(admin_id, new_username or None,
                           new_password or None, new_role or None)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400

    app_log.info(f"[admin] DEV {_current_name()!r} edited admin id={admin_id}")
    return jsonify({"ok": True})


@admin_bp.route("/power/delete/<int:admin_id>", methods=["POST"])
@require_role("DEV")
def power_delete(admin_id):
    target = f.get_admin_by_id(admin_id)
    if not target:
        return jsonify({"ok": False, "error": "Admin not found."}), 404
    if target["username"] == _current_name():
        return jsonify({"ok": False, "error": "Cannot delete your own account."}), 400

    f.delete_admin(admin_id)
    app_log.info(f"[admin] DEV {_current_name()!r} deleted admin {target['username']!r}")
    return jsonify({"ok": True})


# ── API: current session info (used by root.html JS) ─────────────────────────
@admin_bp.route("/me")
def me():
    return jsonify({
        "logged_in": bool(_current_role()),
        "name":      _current_name(),
        "role":      _current_role(),
    })