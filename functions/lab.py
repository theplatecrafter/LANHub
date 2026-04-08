"""
functions/lab.py - LANHub Lab feature business logic.

Handles:
- Lab user management (registration, authentication)
- Project CRUD operations
- Project collaboration (members, comments)
- Docker container orchestration
- Project lifecycle (always-on vs spontaneous)
"""

import sqlite3
import secrets
import time
import os
import uuid
import json
import socket
from typing import Optional, Dict, List, Tuple
from werkzeug.security import generate_password_hash, check_password_hash
from glob_vars import DB_PATH, BASE_DIR, app_log, error_log
from functions.db import get_db, db_insert, db_get_row, db_update_row, db_delete_row, db_query
import config as _config

try:
    from gevent import spawn, joinall
except ImportError:
    # Fallback if gevent not available (shouldn't happen in LANHub)
    def spawn(func, *args):
        import threading
        t = threading.Thread(target=func, args=args)
        t.daemon = True
        t.start()
        return t
    def joinall(*args):
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Lab Infrastructure Constants (DO NOT CHANGE - baked into system design)
# ──────────────────────────────────────────────────────────────────────────────

# Unix socket directory for Flask↔Container IPC (relative to project root, resolved at runtime)
LAB_SOCKET_DIR = "files/lab-sockets"

# Project storage directory (relative to project root, resolved at runtime)
LAB_PROJECTS_DIR = "files/lab"

# Docker image name - must match Dockerfile.lab
LAB_DOCKER_IMAGE = "lanhub-lab:latest"

# Password for code-server (internal security layer; users authenticate at LANHub level)
LAB_CODE_SERVER_PASSWORD = ""

# Available project templates (each requires scaffolding functions in this module)
LAB_PROJECT_TYPES = ["flask", "static_html", "blank_python", "fastapi", "nodejs_express"]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def resolve_lab_path(config_path: str) -> str:
    """
    Resolve a Lab config path to an absolute path.
    If the path is relative, it's resolved against BASE_DIR.
    If the path is absolute, it's returned as-is.
    """
    if os.path.isabs(config_path):
        return config_path
    return os.path.join(BASE_DIR, config_path)


# ──────────────────────────────────────────────────────────────────────────────
# Lab User Management
# ──────────────────────────────────────────────────────────────────────────────

def lab_user_create(username: str, password: str, quota_mb: int = None) -> Optional[Dict]:
    """
    Create a new Lab user account.
    
    Args:
        username: Lab username
        password: Plain text password (will be hashed)
        quota_mb: Storage quota in MB (defaults to config)
    
    Returns:
        User dict or None if creation failed (e.g., username exists)
    """
    if quota_mb is None:
        quota_mb = _config.LAB_DEFAULT_QUOTA_MB
    
    if not username or len(username) < 3:
        return None
    
    try:
        user_id = db_insert("lab_users", {
            "username": username,
            "password_hash": generate_password_hash(password),
            "quota_mb": quota_mb,
            "is_admin": 0,
            "created_at": time.time()
        })
        app_log.info(f"[lab] Created Lab user: {username} (id={user_id})")
        return lab_user_get_by_id(user_id)
    except ValueError:
        # Username already exists or other insert error
        return None


def lab_user_authenticate(username: str, password: str) -> Optional[Dict]:
    """
    Authenticate a Lab user and return their session.
    
    Returns:
        User dict with session_token, or None if auth failed
    """
    conn = get_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    try:
        c.execute("SELECT * FROM lab_users WHERE username = ?", (username,))
        row = c.fetchone()
        if not row:
            return None
        
        user = dict(row)
        if not check_password_hash(user["password_hash"], password):
            return None
        
        # Generate session token
        session_token = secrets.token_urlsafe(32)
        db_update_row("lab_users", user["id"], {
            "session_token": session_token,
            "last_login_at": time.time()
        })
        
        user["session_token"] = session_token
        app_log.info(f"[lab] User authenticated: {username}")
        return user
    finally:
        conn.close()


def lab_user_get_by_id(user_id: int) -> Optional[Dict]:
    """Get Lab user by ID."""
    cols, row = db_get_row("lab_users", user_id)
    return dict(row) if row else None


def lab_user_get_by_username(username: str) -> Optional[Dict]:
    """Get Lab user by username."""
    conn = get_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    try:
        c.execute("SELECT * FROM lab_users WHERE username = ?", (username,))
        row = c.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def lab_user_verify_session(username: str, session_token: str) -> Optional[Dict]:
    """Verify a Lab user's session token."""
    user = lab_user_get_by_username(username)
    if user and user.get("session_token") == session_token:
        return user
    return None


def lab_user_get_quota_used(user_id: int) -> int:
    """Get total storage used by a user's projects in bytes.
    
    Currently returns 0 as actual disk usage tracking would require
    monitoring the Docker container filesystems, which is complex.
    This is a placeholder for future implementation.
    """
    # TODO: Implement actual disk usage tracking from Docker containers
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Project Management
# ──────────────────────────────────────────────────────────────────────────────

def project_create(
    owner_id: int,
    title: str,
    project_type: str,
    description: str = "",
    visibility: str = "private",
    is_always_on: bool = False
) -> Optional[Dict]:
    """
    Create a new project.
    
    Args:
        owner_id: Lab user ID
        title: Project title
        project_type: One of ['flask', 'static_html', 'blank_python', 'fastapi', 'nodejs_express']
        description: Project description
        visibility: 'private' or 'public'
        is_always_on: If True, project starts on LANHub boot
    
    Returns:
        Project dict or None if creation failed
    """
    from slugify import slugify
    
    # Check user hasn't exceeded max projects
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM projects WHERE owner_id = ?", (owner_id,))
    count = c.fetchone()[0]
    conn.close()
    
    if count >= _config.LAB_MAX_PROJECTS_PER_USER:
        return None
    
    # Generate slug from title
    slug = slugify(title)
    if not slug:
        slug = f"project-{uuid.uuid4().hex[:8]}"
    
    # Ensure slug is unique
    while project_get_by_slug(slug):
        slug = f"{slug}-{uuid.uuid4().hex[:4]}"
    
    # Socket path for inter-process communication
    socket_path = os.path.join(resolve_lab_path(LAB_SOCKET_DIR), f"{slug}.sock")
    
    now = time.time()
    
    try:
        project_id = db_insert("projects", {
            "owner_id": owner_id,
            "slug": slug,
            "title": title,
            "description": description,
            "project_type": project_type,
            "visibility": visibility,
            "socket_path": socket_path,
            "is_always_on": 1 if is_always_on else 0,
            "created_at": now,
            "updated_at": now
        })
        
        # Add owner as project member with 'owner' role
        db_insert("project_members", {
            "project_id": project_id,
            "user_id": owner_id,
            "role": "owner",
            "added_at": now
        })
        
        app_log.info(f"[lab] Created project: {slug} (id={project_id}, owner_id={owner_id})")
        return project_get_by_id(project_id)
    except sqlite3.IntegrityError as e:
        error_log.error(f"[lab] Failed to create project: {e}")
        return None


def project_get_by_id(project_id: int) -> Optional[Dict]:
    """Get project by ID."""
    cols, row = db_get_row("projects", project_id)
    return dict(row) if row else None


def project_get_by_slug(slug: str) -> Optional[Dict]:
    """Get project by slug."""
    conn = get_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    try:
        c.execute("SELECT * FROM projects WHERE slug = ?", (slug,))
        row = c.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def project_list_by_owner(owner_id: int) -> List[Dict]:
    """List all projects owned by a user."""
    cols, rows = db_query(
        "SELECT * FROM projects WHERE owner_id = ? ORDER BY created_at DESC",
        [owner_id]
    )
    return rows


def project_list_public() -> List[Dict]:
    """List all public projects."""
    cols, rows = db_query(
        "SELECT * FROM projects WHERE visibility = 'public' ORDER BY created_at DESC"
    )
    return rows


def project_update(project_id: int, updates: Dict) -> bool:
    """Update project fields."""
    updates["updated_at"] = time.time()
    try:
        db_update_row("projects", project_id, updates)
        return True
    except Exception as e:
        error_log.error(f"[lab] Failed to update project {project_id}: {e}")
        return False


def project_delete(project_id: int) -> bool:
    """Delete a project (and all associated data)."""
    try:
        project = project_get_by_id(project_id)
        if not project:
            return False
        
        # Stop container if running
        if project.get("docker_container_id"):
            docker_container_stop(project["docker_container_id"], project_id)
        
        # Delete from DB (cascades to members, comments)
        db_delete_row("projects", project_id)
        
        # Clean up filesystem
        project_dir = os.path.join(resolve_lab_path(LAB_PROJECTS_DIR), project["slug"])
        if os.path.exists(project_dir):
            import shutil
            shutil.rmtree(project_dir)
        
        # Clean up socket
        if os.path.exists(project["socket_path"]):
            os.remove(project["socket_path"])
        
        app_log.info(f"[lab] Deleted project {project_id}")
        return True
    except Exception as e:
        error_log.error(f"[lab] Failed to delete project {project_id}: {e}")
        return False
# ──────────────────────────────────────────────────────────────────────────────
# Project Members & Collaboration
# ──────────────────────────────────────────────────────────────────────────────

def project_member_add(project_id: int, user_id: int, role: str = "contributor") -> bool:
    """Add a user to a project."""
    try:
        db_insert("project_members", {
            "project_id": project_id,
            "user_id": user_id,
            "role": role,
            "added_at": time.time()
        })
        return True
    except sqlite3.IntegrityError:
        return False


def project_member_remove(project_id: int, user_id: int) -> bool:
    """Remove a user from a project."""
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute(
            "DELETE FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, user_id)
        )
        conn.commit()
        return True
    finally:
        conn.close()


def project_member_list(project_id: int) -> List[Dict]:
    """List all members of a project."""
    cols, rows = db_query(
        """
        SELECT pm.*, lu.username FROM project_members pm
        JOIN lab_users lu ON pm.user_id = lu.id
        WHERE pm.project_id = ?
        """,
        [project_id]
    )
    return rows


def project_member_get_role(project_id: int, user_id: int) -> Optional[str]:
    """Get a user's role in a project."""
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute(
            "SELECT role FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, user_id)
        )
        row = c.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def project_can_edit(project_id: int, user_id: int) -> bool:
    """Check if user can edit a project."""
    role = project_member_get_role(project_id, user_id)
    return role in ["owner", "contributor"]


# ──────────────────────────────────────────────────────────────────────────────
# Project Comments
# ──────────────────────────────────────────────────────────────────────────────

def lab_comment_create(
    project_id: int,
    user_id: int,
    content: str,
    parent_id: int = None
) -> Optional[Dict]:
    """Create a new comment (or reply)."""
    try:
        comment_id = db_insert("lab_comments", {
            "project_id": project_id,
            "user_id": user_id,
            "parent_id": parent_id,
            "content": content,
            "created_at": time.time(),
            "updated_at": time.time()
        })
        return lab_comment_get_by_id(comment_id)
    except Exception as e:
        error_log.error(f"[lab] Failed to create comment: {e}")
        return None


def lab_comment_get_by_id(comment_id: int) -> Optional[Dict]:
    """Get comment by ID."""
    cols, row = db_get_row("lab_comments", comment_id)
    return dict(row) if row else None


def lab_comment_list(project_id: int, parent_id: int = None) -> List[Dict]:
    """List comments (with optional parent_id filter for replies)."""
    if parent_id is None:
        cols, rows = db_query(
            """
            SELECT lc.*, lu.username FROM lab_comments lc
            JOIN lab_users lu ON lc.user_id = lu.id
            WHERE lc.project_id = ? AND lc.parent_id IS NULL
            ORDER BY lc.created_at DESC
            """,
            [project_id]
        )
    else:
        cols, rows = db_query(
            """
            SELECT lc.*, lu.username FROM lab_comments lc
            JOIN lab_users lu ON lc.user_id = lu.id
            WHERE lc.project_id = ? AND lc.parent_id = ?
            ORDER BY lc.created_at ASC
            """,
            [project_id, parent_id]
        )
    return rows


def lab_comment_update(comment_id: int, content: str) -> bool:
    """Update comment content."""
    try:
        db_update_row("lab_comments", comment_id, {
            "content": content,
            "updated_at": time.time()
        })
        return True
    except Exception:
        return False


def lab_comment_delete(comment_id: int) -> bool:
    """Delete a comment (cascades to replies)."""
    try:
        db_delete_row("lab_comments", comment_id)
        return True
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Resource Capacity Checks
# ──────────────────────────────────────────────────────────────────────────────

def get_lab_running_projects() -> List[Dict]:
    """Get all projects with active Docker containers."""
    try:
        rows = db_query("SELECT * FROM projects WHERE docker_container_id IS NOT NULL")
        return rows if rows else []
    except Exception as e:
        error_log.error(f"[lab] Error querying running projects: {e}")
        return []


def calculate_total_memory_usage() -> int:
    """Calculate total memory allocated to running Lab containers in MB."""
    running = get_lab_running_projects()
    return len(running) * _config.LAB_DOCKER_MEMORY_MB


def calculate_total_cpu_usage() -> int:
    """Calculate total CPU shares allocated to running Lab containers."""
    running = get_lab_running_projects()
    return len(running) * _config.LAB_DOCKER_CPU_SHARES


def calculate_total_storage_usage() -> int:
    """Calculate total storage used by all Lab projects in MB."""
    try:
        lab_dir = resolve_lab_path(LAB_PROJECTS_DIR)
        if not os.path.exists(lab_dir):
            return 0
        
        total_bytes = 0
        for dirpath, dirnames, filenames in os.walk(lab_dir):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total_bytes += os.path.getsize(filepath)
                except OSError:
                    pass  # File may have been deleted
        
        return total_bytes // (1024 * 1024)  # Convert to MB
    except Exception as e:
        error_log.error(f"[lab] Error calculating storage usage: {e}")
        return 0


def can_deploy_project(project: Dict) -> Tuple[bool, str]:
    """
    Check if a project can be deployed given system resource caps.
    
    Returns:
        (can_deploy: bool, reason: str)
    """
    # Get current usage
    current_memory = calculate_total_memory_usage()
    current_cpu = calculate_total_cpu_usage()
    current_storage = calculate_total_storage_usage()
    
    # Get project storage usage
    try:
        project_dir = resolve_lab_path(os.path.join(LAB_PROJECTS_DIR, project["slug"]))
        project_storage = 0
        if os.path.exists(project_dir):
            for dirpath, dirnames, filenames in os.walk(project_dir):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    try:
                        project_storage += os.path.getsize(filepath)
                    except OSError:
                        pass
        project_storage = project_storage // (1024 * 1024)  # Convert to MB
    except Exception as e:
        error_log.error(f"[lab] Error calculating project storage: {e}")
        project_storage = 0
    
    # Check memory cap
    if current_memory + _config.LAB_DOCKER_MEMORY_MB > _config.LAB_TOTAL_MEMORY_MB:
        available = _config.LAB_TOTAL_MEMORY_MB - current_memory
        return (False, f"Insufficient memory. Available: {available}MB, needed: {_config.LAB_DOCKER_MEMORY_MB}MB")
    
    # Check CPU cap
    if current_cpu + _config.LAB_DOCKER_CPU_SHARES > _config.LAB_TOTAL_CPU_SHARES:
        return (False, "CPU quota exceeded. Too many projects running.")
    
    # Check storage cap
    if current_storage + project_storage > _config.LAB_TOTAL_STORAGE_MB:
        available = _config.LAB_TOTAL_STORAGE_MB - current_storage
        return (False, f"Insufficient storage. Available: {available}MB, used by project: {project_storage}MB")
    
    return (True, "")


# ──────────────────────────────────────────────────────────────────────────────
# Docker Container Operations
# ──────────────────────────────────────────────────────────────────────────────

def docker_container_start(project: Dict) -> Optional[str]:
    """
    Start a Docker container for a project.
    
    Returns:
        Container ID on success, None on failure
    """
    try:
        import docker
    except ImportError:
        error_log.error("[lab] Docker SDK not installed. Install with: pip install docker")
        return None
    
    try:
        client = docker.from_env()
        
        # Force-remove any existing container with this name to avoid "409 Conflict"
        container_name = f"lab-{project['slug']}"
        try:
            existing = client.containers.get(container_name)
            app_log.info(f"[lab] Found existing container {container_name}, force-removing...")
            existing.remove(force=True)
            app_log.info(f"[lab] Removed existing container {container_name}")
        except Exception as e:
            # Container doesn't exist or already removed, that's fine
            app_log.debug(f"[lab] No existing container to remove: {e}")
        
        # Resolve paths (relative paths resolved against BASE_DIR)
        project_dir = os.path.join(resolve_lab_path(LAB_PROJECTS_DIR), project["slug"])
        socket_dir = resolve_lab_path(LAB_SOCKET_DIR)
        
        # Create directories with proper permissions
        os.makedirs(project_dir, mode=0o755, exist_ok=True)
        os.makedirs(socket_dir, mode=0o755, exist_ok=True)
        
        # Prepare volumes and mounts
        volumes = {
            project_dir: {"bind": "/home/coder/project", "mode": "rw"},
            socket_dir: {"bind": "/tmp/sockets", "mode": "rw"}
        }
        
        # Container environment
        # Use /tmp/sockets inside container since that's where socket_dir is mounted
        container_socket_path = f"/tmp/sockets/{project['slug']}.sock"
        environment = {
            "CODER_PASSWORD": LAB_CODE_SERVER_PASSWORD or "lanhub",
            "PROJECT_SOCKET": container_socket_path,
            "PROJECT_SLUG": project["slug"],
            "PROJECT_TYPE": project["project_type"]
        }
        
        # Start container (NO PORT MAPPING - Unix socket only)
        container = client.containers.run(
            LAB_DOCKER_IMAGE,
            name=f"lab-{project['slug']}",
            volumes=volumes,
            environment=environment,
            mem_limit=f"{_config.LAB_DOCKER_MEMORY_MB}m",
            cpu_shares=_config.LAB_DOCKER_CPU_SHARES,
            network_mode="bridge",
            detach=True,
            restart_policy={"Name": "no"},
            user="1000:1000"  # Run as coder user (see Dockerfile.lab)
        )
        
        # Wait for socket file to be created and set permissions
        import time
        socket_path = f"{socket_dir}{project['slug']}.sock"
        for attempt in range(30):  # Wait up to 30 seconds
            if os.path.exists(socket_path):
                # Socket created, set permissions so Flask can access it
                try:
                    os.chmod(socket_path, 0o666)
                    app_log.info(f"[lab] Socket permissions set: {socket_path}")
                except Exception as e:
                    app_log.warning(f"[lab] Failed to set socket permissions: {e}")
                break
            if attempt < 29:
                time.sleep(1)
        
        # Update project with container ID (no external port needed)
        db_update_row("projects", project["id"], {
            "docker_container_id": container.id,
            "last_deployed_at": time.time()
        })
        
        app_log.info(f"[lab] Started container for project {project['slug']}: {container.id[:12]}")
        
        return container.id
    
    except Exception as e:
        error_log.error(f"[lab] Failed to start container for {project['slug']}: {e}")
        return None


def docker_container_stop(container_id: str, project_id: Optional[int] = None) -> bool:
    """Stop and remove a Docker container."""
    try:
        import docker
        client = docker.from_env()
        container = client.containers.get(container_id)
        container.stop(timeout=10)
        container.remove()
        app_log.info(f"[lab] Stopped container {container_id[:12]}")
        
        return True
    except Exception as e:
        error_log.warning(f"[lab] Failed to stop container {container_id[:12]}: {e}")
        return False


def docker_container_get_logs(container_id: str, tail: int = 100) -> str:
    """Get container logs (last N lines)."""
    try:
        import docker
        client = docker.from_env()
        container = client.containers.get(container_id)
        logs = container.logs(tail=tail).decode("utf-8")
        return logs
    except Exception as e:
        return f"Error retrieving logs: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# Project Scaffolding
# ──────────────────────────────────────────────────────────────────────────────

def project_scaffold(project: Dict) -> bool:
    """
    Initialize a project directory with a starter template.
    
    Returns:
        True on success, False on failure
    """
    try:
        project_dir = os.path.join(resolve_lab_path(LAB_PROJECTS_DIR), project["slug"])
        os.makedirs(project_dir, mode=0o755, exist_ok=True)
        
        project_type = project["project_type"]
        
        # Scaffold based on project type
        if project_type == "flask":
            _scaffold_flask(project_dir)
        elif project_type == "static_html":
            _scaffold_static_html(project_dir)
        elif project_type == "blank_python":
            _scaffold_blank_python(project_dir)
        elif project_type == "fastapi":
            _scaffold_fastapi(project_dir)
        elif project_type == "nodejs_express":
            _scaffold_nodejs_express(project_dir)
        
        # Setup virtual environment for Python projects
        if project_type in ["flask", "blank_python", "fastapi"]:
            _setup_python_venv(project_dir)
        
        app_log.info(f"[lab] Scaffolded project {project['slug']} ({project_type})")
        return True
    
    except Exception as e:
        error_log.error(f"[lab] Failed to scaffold project {project['slug']}: {e}")
        return False


def _scaffold_flask(project_dir: str):
    """Create Flask starter template."""
    os.makedirs(project_dir, exist_ok=True)
    
    app_py = """
from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8000, debug=False)
"""
    
    requirements_txt = """Flask==2.3.3
Werkzeug==2.3.7
"""
    
    with open(os.path.join(project_dir, "app.py"), "w") as f:
        f.write(app_py.strip())
    
    with open(os.path.join(project_dir, "requirements.txt"), "w") as f:
        f.write(requirements_txt.strip())
    
    # Create templates directory and HTML
    templates_dir = os.path.join(project_dir, "templates")
    os.makedirs(templates_dir, exist_ok=True)
    
    index_html = """<!DOCTYPE html>
<html>
<head>
    <title>Flask App</title>
</head>
<body>
    <h1>Welcome to your Flask App!</h1>
    <p>Edit this in the editor and refresh.</p>
</body>
</html>
"""
    
    with open(os.path.join(templates_dir, "index.html"), "w") as f:
        f.write(index_html.strip())


def _scaffold_fastapi(project_dir: str):
    """Create FastAPI starter template."""
    os.makedirs(project_dir, exist_ok=True)
    
    app_py = """
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
def read_root():
    return '''
    <html>
        <head>
            <title>FastAPI App</title>
        </head>
        <body>
            <h1>Welcome to FastAPI!</h1>
        </body>
    </html>
    '''

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000)
"""
    
    requirements_txt = """fastapi==0.103.1
uvicorn==0.23.2
"""
    
    with open(os.path.join(project_dir, "app.py"), "w") as f:
        f.write(app_py.strip())
    
    with open(os.path.join(project_dir, "requirements.txt"), "w") as f:
        f.write(requirements_txt.strip())


def _scaffold_static_html(project_dir: str):
    """Create static HTML starter template."""
    os.makedirs(project_dir, exist_ok=True)
    
    with open(os.path.join(project_dir, "index.html"), "w") as f:
        f.write("""<!DOCTYPE html>
<html>
<head>
    <title>My Website</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; }
        h1 { color: #333; }
    </style>
</head>
<body>
    <h1>Welcome to my website!</h1>
    <p>Edit index.html to customize.</p>
</body>
</html>
""")
    
    with open(os.path.join(project_dir, "server.py"), "w") as f:
        f.write("""
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os

os.chdir(os.path.dirname(__file__))
httpd = HTTPServer(('127.0.0.1', 8000), SimpleHTTPRequestHandler)
print('Server running on http://127.0.0.1:8000')
httpd.serve_forever()
""".strip())


def _scaffold_blank_python(project_dir: str):
    """Create blank Python starter template."""
    os.makedirs(project_dir, exist_ok=True)
    
    with open(os.path.join(project_dir, "main.py"), "w") as f:
        f.write("""
# Your Python project starts here!

def hello():
    return "Hello, LANHub Lab!"

if __name__ == '__main__':
    print(hello())
""".strip())
    
    with open(os.path.join(project_dir, "requirements.txt"), "w") as f:
        f.write("")  # Empty, user can add deps


def _scaffold_nodejs_express(project_dir: str):
    """Create Node.js Express starter template."""
    os.makedirs(project_dir, exist_ok=True)
    
    package_json = {
        "name": "lanhub-app",
        "version": "1.0.0",
        "description": "LANHub Node.js project",
        "main": "app.js",
        "scripts": {
            "start": "node app.js",
            "dev": "nodemon app.js"
        },
        "dependencies": {
            "express": "^4.18.2"
        }
    }
    
    with open(os.path.join(project_dir, "package.json"), "w") as f:
        json.dump(package_json, f, indent=2)
    
    app_js = """
const express = require('express');
const app = express();

app.get('/', (req, res) => {
    res.send(`
        <html>
        <head><title>Express App</title></head>
        <body>
            <h1>Welcome to Express!</h1>
            <p>Edit app.js to customize.</p>
        </body>
        </html>
    `);
});

app.listen(8000, '127.0.0.1', () => {
    console.log('Server running on http://127.0.0.1:8000');
});
"""
    
    with open(os.path.join(project_dir, "app.js"), "w") as f:
        f.write(app_js.strip())


def _setup_python_venv(project_dir: str):
    """Create and initialize a Python virtual environment."""
    import subprocess
    
    venv_dir = os.path.join(project_dir, "venv")
    try:
        subprocess.run(
            ["/usr/bin/python3", "-m", "venv", venv_dir],
            check=True,
            cwd=project_dir,
            capture_output=True
        )
        app_log.info(f"[lab] Created venv at {venv_dir}")
    except subprocess.CalledProcessError as e:
        error_log.error(f"[lab] Failed to create venv: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Project Heartbeat & Idle Timeout
# ──────────────────────────────────────────────────────────────────────────────

project_idle_timers: Dict[int, float] = {}  # project_id -> last_activity_time


def project_record_activity(project_id: int):
    """Record that a user is viewing/using a project."""
    project_idle_timers[project_id] = time.time()


def project_check_idle():
    """
    Check for idle projects and stop them.
    Called by the scheduler periodically.
    """
    now = time.time()
    idle_threshold = _config.LAB_IDLE_TIMEOUT_MINS * 60
    
    projects_to_stop = []
    
    for project_id, last_activity in list(project_idle_timers.items()):
        if (now - last_activity) > idle_threshold:
            projects_to_stop.append(project_id)
    
    for project_id in projects_to_stop:
        project = project_get_by_id(project_id)
        if project and project.get("docker_container_id"):
            docker_container_stop(project["docker_container_id"], project_id)
            db_update_row("projects", project_id, {"docker_container_id": None})
            del project_idle_timers[project_id]
            app_log.info(f"[lab] Stopped idle project {project_id}")


from datetime import datetime
import threading
import uuid

# Global dict to keep WebSocket proxy connections alive
# Maps connection_id -> socket object
websocket_proxy_sockets = {}
websocket_proxy_lock = threading.Lock()

# ──────────────────────────────────────────────────────────────────────────────
# Reverse Proxy & Socket Forwarding
# ──────────────────────────────────────────────────────────────────────────────

def proxy_forward_request(
    project_slug: str,
    method: str,
    path: str,
    headers: Dict = None,
    body: bytes = None,
    timeout: int = 30,
    client_addr: str = "127.0.0.1"
) -> Tuple[int, Dict, bytes]:
    """
    Forward HTTP requests to a project's Docker container via Unix socket.
    Uses raw socket communication for reliable request/response handling.
    
    NOTE: WebSocket upgrade requests are handled in app.py's before_request hook
    and never reach this function.
    
    Returns:
        (status_code, response_headers, response_body)
    """
    import socket
    
    try:
        project = project_get_by_slug(project_slug)
        if not project:
            return (404, {}, b"Project not found")
        
        app_log.info(f"[lab] Found project: {project_slug}")
        
        socket_path = project.get("socket_path")
        if not socket_path:
            app_log.error(f"[lab] Project {project_slug} has no socket_path")
            return (502, {}, b"Bad Gateway: Project has no socket path")
        
        # Ensure container is running
        if not project.get("docker_container_id"):
            # Auto-start if spontaneous
            app_log.info(f"[lab] No container_id found for {project_slug}. is_always_on={project.get('is_always_on')}")
            if not project.get("is_always_on"):
                app_log.info(f"[lab] Starting container for {project_slug}")
                docker_container_start(project)
            else:
                return (503, {}, b"Container not running")
        else:
            # Check if container actually exists
            try:
                import docker
                client = docker.from_env()
                client.containers.get(project["docker_container_id"])
                app_log.info(f"[lab] Container {project['docker_container_id'][:12]} exists, using it")
            except Exception as e:
                app_log.info(f"[lab] Container {project['docker_container_id'][:12]} not found: {e}, starting new one")
                db_update_row("projects", project["id"], {"docker_container_id": None})
                docker_container_start(project)
        
        # Build HTTP request
        if headers is None:
            headers = {}
        
        # ─────────────────────────────────────────────────────────────────────────
        # HTTP HANDLING: Forward request/response through Unix socket
        # ─────────────────────────────────────────────────────────────────────────
        
        # Filter headers for HTTP request
        allowed_headers = {
            "content-type",
            "content-length",
            "user-agent",
            "referer",
            "accept",
            "accept-language",
            "accept-encoding",
            "cookie",
            "authorization"
        }
        
        filtered_headers = {}
        for key, value in headers.items():
            if key.lower() in allowed_headers:
                filtered_headers[key.lower()] = value
        
        # Override with required values
        filtered_headers["host"] = "localhost:8443"
        filtered_headers["accept-encoding"] = "identity"  # No compression
        filtered_headers["connection"] = "close"  # Single request
        filtered_headers["x-forwarded-for"] = client_addr
        filtered_headers["x-forwarded-proto"] = "http"
        filtered_headers["x-real-ip"] = client_addr
        
        # Set Content-Length if there's a body
        if body:
            filtered_headers["content-length"] = str(len(body))
        else:
            filtered_headers.pop("content-length", None)
        
        # Build request
        request_line = f"{method} {path} HTTP/1.1\r\n"
        header_lines = request_line
        for key, value in filtered_headers.items():
            header_lines += f"{key}: {value}\r\n"
        header_lines += "\r\n"
        
        request_bytes = header_lines.encode() + (body or b"")
        
        app_log.info(f"[lab] HTTP Request: {method} {path}")
        
        # Connect and send
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        
        # Ensure socket path exists
        import time
        for attempt in range(3):
            if os.path.exists(socket_path):
                break
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
        
        try:
            sock.connect(socket_path)
            sock.sendall(request_bytes)
            
            # Read response
            response = b""
            sock.settimeout(timeout)
            while True:
                chunk = sock.recv(32768)
                if not chunk:
                    break
                response += chunk
            
            sock.close()
            
            # Parse response
            if b"\r\n\r\n" not in response:
                return (502, {}, b"Bad Gateway: Invalid response")
            
            header_end = response.find(b"\r\n\r\n")
            header_bytes = response[:header_end]
            body = response[header_end + 4:]
            
            # Parse status line and headers
            header_str = header_bytes.decode('utf-8', errors='ignore')
            lines = header_str.split('\r\n')
            status_code = int(lines[0].split()[1])
            
            # Parse response headers
            response_headers = {}
            is_chunked = False
            for line in lines[1:]:
                if ':' not in line:
                    continue
                key, value = line.split(':', 1)
                key_lower = key.strip().lower()
                value_clean = value.strip()
                response_headers[key.strip()] = value_clean
                
                if key_lower == 'transfer-encoding' and 'chunked' in value_clean.lower():
                    is_chunked = True
            
            # Dechunk if needed
            if is_chunked:
                dechunked = b""
                pos = 0
                while pos < len(body):
                    line_end = body.find(b'\r\n', pos)
                    if line_end == -1:
                        break
                    
                    chunk_size_str = body[pos:line_end].decode('utf-8', errors='ignore').strip()
                    if not chunk_size_str:
                        pos = line_end + 2
                        continue
                    
                    try:
                        chunk_size = int(chunk_size_str.split(';')[0], 16)
                    except ValueError:
                        break
                    
                    if chunk_size == 0:
                        break
                    
                    chunk_start = line_end + 2
                    chunk_end = chunk_start + chunk_size
                    if chunk_end > len(body):
                        break
                    
                    dechunked += body[chunk_start:chunk_end]
                    pos = chunk_end + 2
                
                body = dechunked
                response_headers.pop('Transfer-Encoding', None)
                response_headers.pop('Content-Encoding', None)
                response_headers['Content-Length'] = str(len(body))
            
            app_log.info(f"[lab] HTTP Response: {status_code}, body_size={len(body)}")
            return (status_code, response_headers, body)
            
        except Exception as e:
            app_log.error(f"[lab] HTTP request error: {e}")
            return (502, {}, f"Bad Gateway: {str(e)}".encode())
        finally:
            try:
                sock.close()
            except:
                pass
    
    except Exception as e:
        error_log.error(f"[lab] Proxy forward failed: {e}")
        import traceback
        error_log.error(traceback.format_exc())
        return (502, {}, f"Bad Gateway: {str(e)}".encode())



