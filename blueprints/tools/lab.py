"""blueprints/tools/lab.py - LANHub Lab blueprint routes."""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, session, make_response
from functools import wraps
import config as _config
import functions as f
from functions import lab
from glob_vars import app_log
import threading
import time

lab_bp = Blueprint("tools_lab", __name__, url_prefix="/lab", template_folder="../../templates")


# ──────────────────────────────────────────────────────────────────────────────
# Authentication Helpers
# ──────────────────────────────────────────────────────────────────────────────

def require_lab_auth(f_view):
    """Decorator to require Lab authentication."""
    @wraps(f_view)
    def decorated_function(*args, **kwargs):
        lab_username = request.cookies.get("lab_username")
        lab_token = request.cookies.get("lab_session_token")
        
        if not lab_username or not lab_token:
            return redirect(url_for("tools_lab.login"))
        
        user = lab.lab_user_verify_session(lab_username, lab_token)
        if not user:
            return redirect(url_for("tools_lab.login"))
        
        # Store in request context
        request.lab_user = user
        return f_view(*args, **kwargs)
    
    return decorated_function


# ──────────────────────────────────────────────────────────────────────────────
# Public Routes
# ──────────────────────────────────────────────────────────────────────────────

@lab_bp.route("", methods=["GET"])
def index():
    """Lab public directory (all public projects)."""
    if not _config.LAB_ENABLED:
        return render_template("lab_disabled.html"), 503
    
    projects = lab.project_list_public()
    
    return render_template(
        "lab_index.html",
        projects=projects,
        is_authenticated=bool(request.cookies.get("lab_username"))
    )


@lab_bp.route("/login", methods=["GET", "POST"])
def login():
    """Lab user login."""
    if not _config.LAB_ENABLED:
        return render_template("lab_disabled.html"), 503
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        
        user = lab.lab_user_authenticate(username, password)
        if not user:
            return render_template("lab_login.html", error="Invalid credentials"), 401
        
        # Set authentication cookies
        response = make_response(redirect(url_for("tools_lab.dashboard")))
        response.set_cookie("lab_username", user["username"], max_age=86400*7)
        response.set_cookie("lab_session_token", user["session_token"], max_age=86400*7)
        return response
    
    return render_template("lab_login.html")


@lab_bp.route("/register", methods=["GET", "POST"])
def register():
    """Lab user registration."""
    if not _config.LAB_ENABLED:
        return render_template("lab_disabled.html"), 503
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        
        if not username or len(username) < 3:
            return render_template("lab_register.html", error="Username must be at least 3 characters"), 400
        
        if password != confirm_password:
            return render_template("lab_register.html", error="Passwords don't match"), 400
        
        if len(password) < 8:
            return render_template("lab_register.html", error="Password must be at least 8 characters"), 400
        
        user = lab.lab_user_create(username, password)
        if not user:
            return render_template("lab_register.html", error="Username already exists"), 409
        
        # Auto-login after registration by authenticating with the new credentials
        authenticated_user = lab.lab_user_authenticate(username, password)
        if not authenticated_user:
            # This shouldn't happen but handle gracefully
            return render_template("lab_register.html", error="Account created but login failed"), 500
        
        response = make_response(redirect(url_for("tools_lab.dashboard")))
        response.set_cookie("lab_username", authenticated_user["username"], max_age=86400*7)
        response.set_cookie("lab_session_token", authenticated_user["session_token"], max_age=86400*7)
        return response
    
    return render_template("lab_register.html")


@lab_bp.route("/logout", methods=["POST"])
def logout():
    """Log out a Lab user."""
    response = make_response(redirect(url_for("tools_lab.index")))
    response.delete_cookie("lab_username")
    response.delete_cookie("lab_session_token")
    return response


# ──────────────────────────────────────────────────────────────────────────────
# Authenticated Routes
# ──────────────────────────────────────────────────────────────────────────────

@lab_bp.route("/dashboard", methods=["GET"])
@require_lab_auth
def dashboard():
    """User's project management dashboard."""
    user = request.lab_user
    projects = lab.project_list_by_owner(user["id"])
    quota_used_mb = lab.lab_user_get_quota_used(user["id"]) / (1024**2)
    
    return render_template(
        "lab_dashboard.html",
        user=user,
        projects=projects,
        quota_used_mb=quota_used_mb,
        max_quota_mb=user["quota_mb"],
        max_projects=_config.LAB_MAX_PROJECTS_PER_USER
    )


@lab_bp.route("/new", methods=["GET", "POST"])
@require_lab_auth
def create_project():
    """Create a new project."""
    user = request.lab_user
    
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        project_type = request.form.get("type", "flask")
        visibility = request.form.get("visibility", "private")
        is_always_on = request.form.get("always_on") == "on"
        
        if not title or len(title) < 3:
            return render_template("lab_new.html", error="Title must be at least 3 characters"), 400
        
        if project_type not in lab.LAB_PROJECT_TYPES:
            return render_template("lab_new.html", error="Invalid project type"), 400
        
        project = lab.project_create(
            owner_id=user["id"],
            title=title,
            project_type=project_type,
            description=description,
            visibility=visibility,
            is_always_on=is_always_on
        )
        
        if not project:
            return render_template("lab_new.html", error="Failed to create project"), 500
        
        # Scaffold the project
        lab.project_scaffold(project)
        
        return redirect(url_for("tools_lab.project_view", slug=project["slug"]))
    
    return render_template(
        "lab_new.html",
        project_types=lab.LAB_PROJECT_TYPES,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Project Routes
# ──────────────────────────────────────────────────────────────────────────────

@lab_bp.route("/project/<slug>", methods=["GET"])
def project_view(slug):
    """View a project (public page with comments)."""
    if not _config.LAB_ENABLED:
        return render_template("lab_disabled.html"), 503
    
    project = lab.project_get_by_slug(slug)
    if not project:
        return render_template("lab_404.html"), 404
    
    # Check authentication by reading cookies
    lab_user = None
    lab_username = request.cookies.get("lab_username")
    lab_token = request.cookies.get("lab_session_token")
    if lab_username and lab_token:
        lab_user = lab.lab_user_verify_session(lab_username, lab_token)
    
    is_owner = lab_user and lab_user["id"] == project["owner_id"]
    
    # Check visibility
    if project["visibility"] == "private" and not is_owner:
        return render_template("lab_403.html"), 403
    
    owner = lab.lab_user_get_by_id(project["owner_id"])
    comments = lab.lab_comment_list(project["id"])
    members = lab.project_member_list(project["id"])
    
    return render_template(
        "lab_project.html",
        project=project,
        owner=owner,
        comments=comments,
        members=members,
        is_owner=is_owner,
        is_authenticated=bool(lab_user)
    )


@lab_bp.route("/project/<slug>/edit", methods=["GET"])
@require_lab_auth
def project_edit(slug):
    """Browser-based code editor (code-server)."""
    user = request.lab_user
    project = lab.project_get_by_slug(slug)
    
    if not project:
        return render_template("lab_404.html"), 404
    
    if not lab.project_can_edit(project["id"], user["id"]):
        return render_template("lab_403.html"), 403
    
    # Record activity for spontaneous projects
    if not project["is_always_on"]:
        lab.project_record_activity(project["id"])
    
    return render_template(
        "lab_editor.html",
        project=project,
        code_server_port=_config.LAB_CODE_SERVER_PORT
    )


@lab_bp.route("/project/<slug>/edit/", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "CONNECT"])
@lab_bp.route("/project/<slug>/edit/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "CONNECT"])
def project_proxy(slug, path=""):
    """Reverse proxy route to forward requests to project containers via Unix socket.
    
    This route strips the LANHub prefix (/lab/project/<slug>/edit/) and forwards
    the remainder to code-server, which serves from its root.
    
    Example:
      Browser: GET /lab/project/test/edit/stable-xxx/static/main.js
      Flask captures: path="stable-xxx/static/main.js"
      Proxy sends: GET /stable-xxx/static/main.js to socket
      code-server (running at /) serves the file
    """
    project = lab.project_get_by_slug(slug)
    if not project:
        return render_template("lab_404.html"), 404
    
    # Check if this is a WebSocket upgrade request
    connection_header = request.headers.get("Connection", "").lower()
    upgrade_header = request.headers.get("Upgrade", "").lower()
    
    # Strip the LANHub route prefix and send only the path to the socket
    # If path is empty (root request), send "/"
    # Otherwise send "/<path>" (which may contain version hashes like stable-xxx/...)
    full_path = f"/{path}" if path else "/"
    
    if request.query_string:
        full_path += f"?{request.query_string.decode()}"
    
    # Forward HTTP request through proxy (WebSocket requests are handled in app.py before_request)
    status, headers, body = lab.proxy_forward_request(
        slug,
        request.method,
        full_path,
        headers=dict(request.headers),
        body=request.get_data(),
        client_addr=request.remote_addr
    )
    
    response = make_response(body, status)
    for key, value in headers.items():
        # Skip headers that Flask will set or that we've already handled
        if key.lower() not in ["content-encoding", "content-length", "server", "date", "connection"]:
            response.headers[key] = value
    
    return response


@lab_bp.route("/project/<slug>/settings", methods=["GET", "POST"])
@require_lab_auth
def project_settings(slug):
    """Project settings (visibility, env vars, deletion)."""
    user = request.lab_user
    project = lab.project_get_by_slug(slug)
    
    if not project:
        return render_template("lab_404.html"), 404
    
    if project["owner_id"] != user["id"]:
        return render_template("lab_403.html"), 403
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "update_settings":
            title = request.form.get("title", "").strip()
            description = request.form.get("description", "").strip()
            visibility = request.form.get("visibility", "private")
            
            lab.project_update(project["id"], {
                "title": title,
                "description": description,
                "visibility": visibility
            })
            return jsonify({"success": True})
        
        elif action == "delete":
            lab.project_delete(project["id"])
            return redirect(url_for("tools_lab.dashboard"))
    
    return render_template(
        "lab_settings.html",
        project=project
    )


# ──────────────────────────────────────────────────────────────────────────────
# Comment Routes (via AJAX/JSON)
# ──────────────────────────────────────────────────────────────────────────────

@lab_bp.route("/api/project/<slug>/comments", methods=["POST"])
@require_lab_auth
def api_create_comment(slug):
    """Create a comment on a project."""
    user = request.lab_user
    project = lab.project_get_by_slug(slug)
    
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    data = request.get_json() or {}
    content = data.get("content", "").strip()
    parent_id = data.get("parent_id")
    
    if not content or len(content) < 1:
        return jsonify({"error": "Content required"}), 400
    
    comment = lab.lab_comment_create(
        project["id"],
        user["id"],
        content,
        parent_id=parent_id
    )
    
    if not comment:
        return jsonify({"error": "Failed to create comment"}), 500
    
    return jsonify(comment), 201


@lab_bp.route("/api/comment/<int:comment_id>", methods=["PUT"])
@require_lab_auth
def api_update_comment(comment_id):
    """Update a comment."""
    user = request.lab_user
    comment = lab.lab_comment_get_by_id(comment_id)
    
    if not comment or comment["user_id"] != user["id"]:
        return jsonify({"error": "Not authorized"}), 403
    
    data = request.get_json() or {}
    content = data.get("content", "").strip()
    
    if not content:
        return jsonify({"error": "Content required"}), 400
    
    success = lab.lab_comment_update(comment_id, content)
    return jsonify({"success": success})


@lab_bp.route("/api/comment/<int:comment_id>", methods=["DELETE"])
@require_lab_auth
def api_delete_comment(comment_id):
    """Delete a comment."""
    user = request.lab_user
    comment = lab.lab_comment_get_by_id(comment_id)
    
    if not comment or comment["user_id"] != user["id"]:
        return jsonify({"error": "Not authorized"}), 403
    
    success = lab.lab_comment_delete(comment_id)
    return jsonify({"success": success})
