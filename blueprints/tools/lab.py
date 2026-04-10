"""blueprints/tools/lab.py - LANHub Lab blueprint routes."""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, session, make_response
from functools import wraps
import config as _config
import functions as f
from functions import lab
from glob_vars import app_log, error_log
import threading
import time
import requests
import os

# Check if Lab feature is enabled
_LAB_ENABLED = os.path.isfile(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".lab_enabled"))

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
    if not _LAB_ENABLED:
        return render_template("lab_disabled.html"), 503
    
    # Get sort parameter from query string
    sort_by = request.args.get("sort", "recent")
    if sort_by not in ["recent", "stars"]:
        sort_by = "recent"
    
    # Get search parameter from query string
    search_query = request.args.get("search", "").strip()
    
    projects = lab.project_list_public_sorted(sort_by=sort_by, search_query=search_query)
    
    return render_template(
        "lab_index.html",
        projects=projects,
        is_authenticated=bool(request.cookies.get("lab_username")),
        sort_by=sort_by,
        search_query=search_query
    )


@lab_bp.route("/login", methods=["GET", "POST"])
def login():
    """Lab user login."""
    if not _LAB_ENABLED:
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
    if not _LAB_ENABLED:
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
        visibility = request.form.get("visibility", "private")
        is_always_on = request.form.get("always_on") == "on"
        
        if not title or len(title) < 3:
            return render_template("lab_new.html", error="Title must be at least 3 characters"), 400
        
        project = lab.project_create(
            owner_id=user["id"],
            title=title,
            description=description,
            visibility=visibility,
            is_always_on=is_always_on
        )
        
        if not project:
            return render_template("lab_new.html", error="Failed to create project"), 500
        
        # Scaffold the project
        lab.project_scaffold(project)
        
        return redirect(url_for("tools_lab.project_view", slug=project["slug"]))
    
    return render_template("lab_new.html")


# ──────────────────────────────────────────────────────────────────────────────
# Project Routes
# ──────────────────────────────────────────────────────────────────────────────

@lab_bp.route("/project/<slug>", methods=["GET"])
def project_view(slug):
    """View a project (public page with comments)."""
    if not _LAB_ENABLED:
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
    
    # Check visibility - allow owner, contributors, and public projects
    is_contributor = False
    if lab_user and project["visibility"] == "private":
        role = lab.project_member_get_role(project["id"], lab_user["id"])
        is_contributor = role in ["contributor", "viewer"]
    
    if project["visibility"] == "private" and not is_owner and not is_contributor:
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
        is_authenticated=bool(lab_user),
        current_user=lab_user
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


@lab_bp.route("/project/<slug>/preview", methods=["GET", "POST", "PUT", "DELETE"])
@lab_bp.route("/project/<slug>/preview/", methods=["GET", "POST", "PUT", "DELETE"])
@lab_bp.route("/project/<slug>/preview/<path:path>", methods=["GET", "POST", "PUT", "DELETE"])
def project_preview(slug, path=""):
    """
    Display a preview of the user's running application on port 8000.
    Auto-deploys brand new projects and wakes up sleeping spontaneous containers!
    """
    import docker
    import gevent
    
    # Check authentication
    lab_user = request.cookies.get("lab_username")
    lab_token = request.cookies.get("lab_session_token")
    user = None
    if lab_user and lab_token:
        user = lab.lab_user_verify_session(lab_user, lab_token)
    
    project = lab.project_get_by_slug(slug)
    if not project:
        return render_template("lab_404.html"), 404
    
    # Check permissions
    if project.get("visibility") == "private":
        if not user or not lab.project_can_edit(project["id"], user["id"]):
            return render_template("lab_403.html"), 403
    
    # Record activity
    if user:
        lab.project_record_activity(project["id"])
        
    try:
        client = docker.from_env()
        container_name = f"lab-{slug}"
        
        # 1. THE FIRST BOOT FIX: Try to find container, build it if missing!
        try:
            container = client.containers.get(container_name)
        except docker.errors.NotFound:
            app_log.info(f"[lab:preview] Container {slug} does not exist yet. Auto-deploying...")
            lab.docker_container_start(project)
            container = client.containers.get(container_name)

        # 2. WAKE UP FIX: If it exists but is sleeping, wake it up
        container.reload()
        if container.status != "running":
            app_log.info(f"[lab:preview] Container {slug} is asleep. Waking up...")
            container.start()
            
        # 3. IP RACE CONDITION FIX: Wait for the IP to be assigned
        container_ip = None
        for attempt in range(10):
            container.reload()
            container_ip = lab.docker_container_get_ip(container.id)
            if container_ip:
                break
            gevent.sleep(0.5)

        if not container_ip:
            return render_template("lab_error.html", error="IP Error", message="Failed to get container IP after wake up."), 502

        # 4. PROXY THE TRAFFIC
        target_url = f"http://{container_ip}:8000/{path}"
        if request.query_string:
            target_url += f"?{request.query_string.decode()}"
            
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers={key: value for (key, value) in request.headers if key != 'Host'},
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            timeout=10
        )
        
        result = make_response(resp.content, resp.status_code)
        for key, value in resp.raw.headers.items():
            if key.lower() not in ["content-encoding", "transfer-encoding", "connection", "server"]:
                result.headers[key] = value
        return result

    except Exception as e:
        error_str = str(e)
        
        # Catch all variations of the container booting up
        if "Connection refused" in error_str or "Max retries exceeded" in error_str or "Failed to connect" in error_str:
            
            # Note: We intentionally DO NOT log this to error_log because it is expected 
            # behavior while the container is running pip install!
            
            loading_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Starting {slug}...</title>
                <style>
                    body {{ font-family: system-ui, -apple-system, sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; background-color: #1e1e2e; color: #cdd6f4; }}
                    .spinner {{ width: 50px; height: 50px; border: 4px solid #313244; border-top-color: #89b4fa; border-radius: 50%; animation: spin 1s linear infinite; margin-bottom: 20px; }}
                    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
                    h1 {{ font-size: 1.8rem; margin-bottom: 0.5rem; color: #cdd6f4; }}
                    p {{ color: #a6adc8; margin-top: 0; }}
                    .terminal {{ margin-top: 2rem; font-family: monospace; background: #11111b; color: #a6e3a1; padding: 1rem 1.5rem; border-radius: 0.5rem; font-size: 0.9rem; border: 1px solid #313244; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }}
                </style>
                <script>
                    // Quietly ping the server every 2 seconds
                    setInterval(async () => {{
                        try {{
                            let response = await fetch(window.location.href, {{ method: 'HEAD' }});
                            if (response.status !== 502) {{
                                window.location.reload();
                            }}
                        }} catch (err) {{
                            // Keep waiting
                        }}
                    }}, 2000);
                </script>
            </head>
            <body>
                <div class="spinner"></div>
                <h1>Waking up '{slug}'</h1>
                <p>The container is starting and configuring its environment...</p>
                <div class="terminal">
                    > creating virtual environment...<br>
                    > installing dependencies...<br>
                    > starting app.py on port 8000...<br>
                    <span style="color: #f9e2af; animation: blink 1s infinite;">_</span>
                </div>
                <style>@keyframes blink {{ 50% {{ opacity: 0; }} }}</style>
            </body>
            </html>
            """
            return loading_html, 502
            
        # Fallback for completely unknown errors: NOW we log it, because it's a real issue
        error_log.error(f"[lab:preview] Proxy error for {slug}: {error_str}")
        return f"Could not connect to the application. Error: {error_str}", 502

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
# Team Member Management Routes (via AJAX/JSON)
# ──────────────────────────────────────────────────────────────────────────────

@lab_bp.route("/api/project/<slug>/members", methods=["GET"])
@require_lab_auth
def api_get_project_members(slug):
    """Get list of project members."""
    user = request.lab_user
    project = lab.project_get_by_slug(slug)
    
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    # Only owner can view members
    if project["owner_id"] != user["id"]:
        return jsonify({"error": "Access denied"}), 403
    
    members = lab.project_member_list(project["id"])
    return jsonify({"members": members}), 200


@lab_bp.route("/api/project/<slug>/members/add", methods=["POST"])
@require_lab_auth
def api_add_project_member(slug):
    """Add a member to a project."""
    user = request.lab_user
    project = lab.project_get_by_slug(slug)
    
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    # Only owner can add members
    if project["owner_id"] != user["id"]:
        return jsonify({"error": "Access denied"}), 403
    
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    role = data.get("role", "contributor")
    
    if not username:
        return jsonify({"error": "Username required"}), 400
    
    if role not in ["contributor", "viewer"]:
        return jsonify({"error": "Invalid role. Must be 'contributor' or 'viewer'"}), 400
    
    # Get user by username
    target_user = lab.lab_user_get_by_username(username)
    if not target_user:
        return jsonify({"error": f"User '{username}' not found"}), 404
    
    # Check if already a member
    existing_role = lab.project_member_get_role(project["id"], target_user["id"])
    if existing_role:
        return jsonify({"error": f"User '{username}' is already a member"}), 400
    
    # Add member
    success = lab.project_member_add(project["id"], target_user["id"], role)
    if not success:
        return jsonify({"error": "Failed to add member"}), 500
    
    members = lab.project_member_list(project["id"])
    return jsonify({"success": True, "members": members}), 200


@lab_bp.route("/api/project/<slug>/members/remove", methods=["POST"])
@require_lab_auth
def api_remove_project_member(slug):
    """Remove a member from a project."""
    user = request.lab_user
    project = lab.project_get_by_slug(slug)
    
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    # Only owner can remove members
    if project["owner_id"] != user["id"]:
        return jsonify({"error": "Access denied"}), 403
    
    data = request.get_json() or {}
    member_id = data.get("member_id")
    
    if not member_id:
        return jsonify({"error": "member_id required"}), 400
    
    # Prevent removing the owner
    if member_id == project["owner_id"]:
        return jsonify({"error": "Cannot remove the project owner"}), 400
    
    # Remove member
    success = lab.project_member_remove(project["id"], member_id)
    if not success:
        return jsonify({"error": "Failed to remove member"}), 500
    
    members = lab.project_member_list(project["id"])
    return jsonify({"success": True, "members": members}), 200


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


@lab_bp.route("/api/comment/<int:comment_id>/replies", methods=["GET"])
def api_get_comment_replies(comment_id):
    """Get all replies to a comment with like info."""
    comment = lab.lab_comment_get_by_id(comment_id)
    if not comment:
        return jsonify({"error": "Comment not found"}), 404
    
    replies = lab.lab_comment_list(comment["project_id"], parent_id=comment_id)
    
    # Enhance each reply with like count and user's like status
    current_user = None
    lab_username = request.cookies.get("lab_username")
    lab_token = request.cookies.get("lab_session_token")
    if lab_username and lab_token:
        current_user = lab.lab_user_verify_session(lab_username, lab_token)
    
    for reply in replies:
        reply["like_count"] = lab.comment_get_like_count(reply["id"])
        reply["user_liked"] = lab.comment_has_like(reply["id"], current_user["id"]) if current_user else False
    
    return jsonify({"replies": replies}), 200


@lab_bp.route("/api/comment/<int:comment_id>/like", methods=["POST"])
@require_lab_auth
def api_like_comment(comment_id):
    """Like a comment."""
    user = request.lab_user
    comment = lab.lab_comment_get_by_id(comment_id)
    
    if not comment:
        return jsonify({"error": "Comment not found"}), 404
    
    success = lab.comment_add_like(comment_id, user["id"])
    if not success:
        return jsonify({"error": "Already liked or error occurred"}), 400
    
    like_count = lab.comment_get_like_count(comment_id)
    return jsonify({"success": True, "like_count": like_count}), 200


@lab_bp.route("/api/comment/<int:comment_id>/unlike", methods=["POST"])
@require_lab_auth
def api_unlike_comment(comment_id):
    """Unlike a comment."""
    user = request.lab_user
    comment = lab.lab_comment_get_by_id(comment_id)
    
    if not comment:
        return jsonify({"error": "Comment not found"}), 404
    
    success = lab.comment_remove_like(comment_id, user["id"])
    if not success:
        return jsonify({"error": "Not liked or error occurred"}), 400
    
    like_count = lab.comment_get_like_count(comment_id)
    return jsonify({"success": True, "like_count": like_count}), 200


@lab_bp.route("/api/comment/<int:comment_id>/likes", methods=["GET"])
def api_get_comment_likes(comment_id):
    """Get like count and whether current user has liked the comment."""
    comment = lab.lab_comment_get_by_id(comment_id)
    
    if not comment:
        return jsonify({"error": "Comment not found"}), 404
    
    like_count = lab.comment_get_like_count(comment_id)
    user_liked = False
    
    # Check if user has liked if authenticated
    if hasattr(request, 'lab_user') and request.lab_user:
        user_liked = lab.comment_has_like(comment_id, request.lab_user["id"])
    
    return jsonify({"like_count": like_count, "user_liked": user_liked}), 200


# ═══════════════════════════════════════════════════════════════════════════
# Git Operations Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@lab_bp.route("/api/project/<slug>/git/branches", methods=["GET"])
def api_get_git_branches(slug):
    """Get all git branches for a project."""
    project = lab.project_get_by_slug(slug)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    branches = lab.git_get_branches(project["slug"])
    return jsonify({"branches": branches}), 200


@lab_bp.route("/api/project/<slug>/git/branches", methods=["POST"])
@require_lab_auth
def api_create_git_branch(slug):
    """Create a new git branch."""
    user = request.lab_user
    project = lab.project_get_by_slug(slug)
    
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    # Check authorization - owner or contributor only
    role = lab.project_member_get_role(project["id"], user["id"])
    if not (project["owner_id"] == user["id"] or role in ["contributor"]):
        return jsonify({"error": "Insufficient permissions"}), 403
    
    data = request.get_json() or {}
    branch_name = data.get('name', '').strip()
    from_commit = data.get('from_commit')
    
    if not branch_name:
        return jsonify({"error": "Branch name required"}), 400
    
    if lab.git_create_branch(project["slug"], branch_name, from_commit):
        return jsonify({"success": True, "branch": branch_name}), 201
    else:
        return jsonify({"error": "Failed to create branch"}), 400


@lab_bp.route("/api/project/<slug>/git/log", methods=["GET"])
def api_get_git_log(slug):
    """Get git commit history for a branch."""
    project = lab.project_get_by_slug(slug)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    branch = request.args.get('branch', 'main')
    limit = request.args.get('limit', 50, type=int)
    
    commits = lab.git_get_commit_log(project["slug"], branch, limit)
    return jsonify({"commits": commits}), 200


@lab_bp.route("/api/project/<slug>/git/merge", methods=["POST"])
@require_lab_auth
def api_merge_branches(slug):
    """Merge a branch into another branch."""
    user = request.lab_user
    project = lab.project_get_by_slug(slug)
    
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    # Check authorization
    role = lab.project_member_get_role(project["id"], user["id"])
    if not (project["owner_id"] == user["id"] or role in ["contributor"]):
        return jsonify({"error": "Insufficient permissions"}), 403
    
    data = request.get_json() or {}
    source_branch = data.get('source', '').strip()
    target_branch = data.get('target', 'main').strip()
    
    if not source_branch:
        return jsonify({"error": "Source branch required"}), 400
    
    result = lab.git_merge_branch(project["slug"], source_branch, target_branch)
    
    if result['success']:
        return jsonify(result), 200
    else:
        return jsonify(result), 409 if 'conflicts' in result else 400


@lab_bp.route("/api/project/<slug>/git/conflicts", methods=["GET"])
def api_get_conflicts(slug):
    """Get list of files with merge conflicts."""
    project = lab.project_get_by_slug(slug)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    conflicts = lab.git_get_conflicted_files(project["slug"])
    return jsonify({"conflicts": conflicts}), 200


@lab_bp.route("/api/project/<slug>/git/conflict/<path:file_path>", methods=["GET"])
def api_get_conflict_content(slug, file_path):
    """Get content of a file with merge conflicts."""
    project = lab.project_get_by_slug(slug)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    content = lab.git_get_file_content(project["slug"], file_path)
    if content is None:
        return jsonify({"error": "File not found"}), 404
    
    return jsonify({"content": content}), 200


@lab_bp.route("/api/project/<slug>/git/resolve", methods=["POST"])
@require_lab_auth
def api_resolve_conflict(slug):
    """Resolve a merge conflict."""
    user = request.lab_user
    project = lab.project_get_by_slug(slug)
    
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    # Check authorization
    role = lab.project_member_get_role(project["id"], user["id"])
    if not (project["owner_id"] == user["id"] or role in ["contributor"]):
        return jsonify({"error": "Insufficient permissions"}), 403
    
    data = request.get_json() or {}
    file_path = data.get('file', '').strip()
    resolved_content = data.get('content', '')
    
    if not file_path:
        return jsonify({"error": "File path required"}), 400
    
    if lab.git_resolve_conflict(project["slug"], file_path, resolved_content):
        return jsonify({"success": True}), 200
    else:
        return jsonify({"error": "Failed to resolve conflict"}), 400


@lab_bp.route("/api/project/<slug>/git/merge/complete", methods=["POST"])
@require_lab_auth
def api_complete_merge(slug):
    """Complete merge after resolving all conflicts."""
    user = request.lab_user
    project = lab.project_get_by_slug(slug)
    
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    # Check authorization
    role = lab.project_member_get_role(project["id"], user["id"])
    if not (project["owner_id"] == user["id"] or role in ["contributor"]):
        return jsonify({"error": "Insufficient permissions"}), 403
    
    data = request.get_json() or {}
    merge_message = data.get('message', 'Merge branch')
    
    if lab.git_complete_merge(project["slug"], merge_message):
        return jsonify({"success": True}), 200
    else:
        return jsonify({"error": "Failed to complete merge"}), 400


@lab_bp.route("/api/project/<slug>/git/merge/abort", methods=["POST"])
@require_lab_auth
def api_abort_merge(slug):
    """Abort an ongoing merge."""
    user = request.lab_user
    project = lab.project_get_by_slug(slug)
    
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    # Check authorization
    role = lab.project_member_get_role(project["id"], user["id"])
    if not (project["owner_id"] == user["id"] or role in ["contributor"]):
        return jsonify({"error": "Insufficient permissions"}), 403
    
    if lab.git_abort_merge(project["slug"]):
        return jsonify({"success": True}), 200
    else:
        return jsonify({"error": "Failed to abort merge"}), 400

