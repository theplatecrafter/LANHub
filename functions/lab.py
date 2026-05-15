"""
functions/lab.py - HansHub Lab feature business logic.

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
import subprocess
from typing import Optional, Dict, List, Tuple
from werkzeug.security import generate_password_hash, check_password_hash
from glob_vars import DB_PATH, BASE_DIR, app_log, error_log
from functions.db import get_db, db_insert, db_get_row, db_update_row, db_delete_row, db_query
import config as _config

try:
    from gevent import spawn, joinall
except ImportError:
    # Fallback if gevent not available (shouldn't happen in HansHub)
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

# Docker image name - must match tools/Dockerfile.lab
LAB_DOCKER_IMAGE = "hanshub-lab:latest"

# Password for code-server (internal security layer; users authenticate at HansHub level)
LAB_CODE_SERVER_PASSWORD = ""

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
    description: str = "",
    visibility: str = "private",
    is_always_on: bool = False
) -> Optional[Dict]:
    """
    Create a new project.
    
    Args:
        owner_id: Lab user ID
        title: Project title
        description: Project description
        visibility: 'private' or 'public'
        is_always_on: If True, project starts on HansHub boot
    
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
        
        # Initialize git repository (get owner name for git config)
        owner = lab_user_get_by_id(owner_id)
        if owner:
            git_init_repo(slug, owner['username'])
            # Initial commit will be created after scaffolding
        
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
        import shutil
        
        # Remove working tree directory
        project_dir = os.path.join(resolve_lab_path(LAB_PROJECTS_DIR), project["slug"])
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)
            app_log.info(f"[lab] Removed project directory: {project_dir}")
        
        # Remove bare repository (origin remote)
        bare_repo_dir = os.path.join(resolve_lab_path(LAB_PROJECTS_DIR), f"{project['slug']}.git")
        if os.path.exists(bare_repo_dir):
            shutil.rmtree(bare_repo_dir)
            app_log.info(f"[lab] Removed bare repository: {bare_repo_dir}")
        
        # Clean up socket
        if os.path.exists(project["socket_path"]):
            os.remove(project["socket_path"])
            app_log.info(f"[lab] Removed socket: {project['socket_path']}")
        
        app_log.info(f"[lab] Deleted project {project_id} ({project['slug']})")
        return True
    except Exception as e:
        error_log.error(f"[lab] Failed to delete project {project_id}: {e}")
        return False


def project_clone(source_project_id: int, new_owner_id: int) -> Optional[Dict]:
    """
    Clone an existing project and assign it to a new owner.
    
    Creates a new project with:
    - Same title (with " (Clone)" suffix)
    - Same description
    - Private visibility (cloned projects start private)
    - New slug (auto-generated)
    - New directories and sockets
    - Copies all project files from source
    
    Args:
        source_project_id: Project ID to clone from
        new_owner_id: User ID of the new owner
    
    Returns:
        New project dict on success, None on failure
    """
    try:
        from slugify import slugify
        import shutil
        
        # Get source project
        source_project = project_get_by_id(source_project_id)
        if not source_project:
            error_log.error(f"[lab] Source project {source_project_id} not found")
            return None
        
        # Check new owner exists
        new_owner = lab_user_get_by_id(new_owner_id)
        if not new_owner:
            error_log.error(f"[lab] New owner {new_owner_id} not found")
            return None
        
        # Check new owner hasn't exceeded max projects
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM projects WHERE owner_id = ?", (new_owner_id,))
        count = c.fetchone()[0]
        conn.close()
        
        if count >= _config.LAB_MAX_PROJECTS_PER_USER:
            error_log.error(f"[lab] User {new_owner_id} has reached max projects limit")
            return None
        
        # Generate new title and slug
        new_title = f"{source_project['title']} (Clone)"
        new_slug = slugify(new_title)
        
        # Ensure slug is unique
        while project_get_by_slug(new_slug):
            new_slug = f"{new_slug}-{uuid.uuid4().hex[:4]}"
        
        # Socket path for new project
        new_socket_path = os.path.join(resolve_lab_path(LAB_SOCKET_DIR), f"{new_slug}.sock")
        
        now = time.time()
        
        # Create new project
        new_project_id = db_insert("projects", {
            "owner_id": new_owner_id,
            "slug": new_slug,
            "title": new_title,
            "description": source_project["description"],
            "visibility": "private",  # Clone always starts as private
            "socket_path": new_socket_path,
            "is_always_on": source_project["is_always_on"],
            "created_at": now,
            "updated_at": now
        })
        
        # Add owner as project member
        db_insert("project_members", {
            "project_id": new_project_id,
            "user_id": new_owner_id,
            "role": "owner",
            "added_at": now
        })
        
        # Copy project files from source directory
        source_dir = os.path.join(resolve_lab_path(LAB_PROJECTS_DIR), source_project["slug"])
        new_dir = os.path.join(resolve_lab_path(LAB_PROJECTS_DIR), new_slug)
        
        try:
            if os.path.exists(source_dir):
                shutil.copytree(source_dir, new_dir)
                app_log.info(f"[lab] Copied project files from {source_project['slug']} to {new_slug}")
            else:
                # Create empty project directory
                os.makedirs(new_dir, mode=0o755, exist_ok=True)
                app_log.info(f"[lab] Created empty project directory for {new_slug}")
        except Exception as e:
            error_log.error(f"[lab] Failed to copy project files: {e}")
            # Don't fail entirely, project can be created without files
        
        app_log.info(f"[lab] Cloned project {source_project_id} to {new_project_id} for user {new_owner_id}")
        return project_get_by_id(new_project_id)
    
    except Exception as e:
        error_log.error(f"[lab] Failed to clone project: {e}")
        return None

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
# Project Invitations & Collaboration
# ──────────────────────────────────────────────────────────────────────────────

def project_invite_send(project_id: int, inviter_id: int, invitee_username: str, role: str = "contributor") -> Optional[Dict]:
    """
    Send a collaboration invitation to another Lab user.
    
    Args:
        project_id: Project ID
        inviter_id: User ID of the person sending the invite
        invitee_username: Username of the person being invited
        role: Role to grant if accepted (contributor or viewer)
    
    Returns:
        Invitation dict on success, None on failure
    """
    try:
        # Find invitee by username
        invitee = lab_user_get_by_username(invitee_username)
        if not invitee:
            return None
        
        project = project_get_by_id(project_id)
        if not project:
            return None
        
        # Check if inviter is project owner
        inviter_role = project_member_get_role(project_id, inviter_id)
        if inviter_role != "owner":
            return None
        
        # Check if invitee is already a member
        existing_role = project_member_get_role(project_id, invitee["id"])
        if existing_role:
            return None  # Already a member
        
        # Check for existing pending invitation
        cols, rows = db_query(
            "SELECT * FROM project_invitations WHERE project_id = ? AND invitee_id = ? AND status = 'pending'",
            [project_id, invitee["id"]]
        )
        if rows:
            return None  # Invitation already pending
        
        # Create invitation
        invite_id = db_insert("project_invitations", {
            "project_id": project_id,
            "inviter_id": inviter_id,
            "invitee_id": invitee["id"],
            "role": role,
            "status": "pending",
            "created_at": time.time()
        })
        
        app_log.info(f"[lab] Created invitation for {invitee_username} to {project['slug']}")
        
        return {
            "id": invite_id,
            "project_id": project_id,
            "inviter_id": inviter_id,
            "invitee_id": invitee["id"],
            "invitee_username": invitee["username"],
            "role": role,
            "status": "pending",
            "created_at": time.time()
        }
    except Exception as e:
        error_log.error(f"[lab] Failed to send invitation: {e}")
        return None


def project_invite_accept(invitation_id: int, user_id: int) -> bool:
    """Accept a collaboration invitation and become a project member."""
    try:
        # Get invitation
        cols, rows = db_query(
            "SELECT * FROM project_invitations WHERE id = ? AND invitee_id = ? AND status = 'pending'",
            [invitation_id, user_id]
        )
        
        if not rows:
            return False
        
        invitation = rows[0]
        project_id = invitation[1]  # project_id from columns
        role = invitation[4]  # role from columns
        
        # Add user to project
        if not project_member_add(project_id, user_id, role):
            return False
        
        # Mark invitation as accepted
        db_update_row("project_invitations", invitation_id, {
            "status": "accepted",
            "responded_at": time.time()
        })
        
        app_log.info(f"[lab] User {user_id} accepted invitation {invitation_id}")
        return True
    except Exception as e:
        error_log.error(f"[lab] Failed to accept invitation: {e}")
        return False


def project_invite_reject(invitation_id: int, user_id: int) -> bool:
    """Reject a collaboration invitation."""
    try:
        # Get invitation
        cols, rows = db_query(
            "SELECT * FROM project_invitations WHERE id = ? AND invitee_id = ? AND status = 'pending'",
            [invitation_id, user_id]
        )
        
        if not rows:
            return False
        
        # Mark invitation as rejected
        db_update_row("project_invitations", invitation_id, {
            "status": "rejected",
            "responded_at": time.time()
        })
        
        app_log.info(f"[lab] User {user_id} rejected invitation {invitation_id}")
        return True
    except Exception as e:
        error_log.error(f"[lab] Failed to reject invitation: {e}")
        return False


def project_invitations_list_pending_received(user_id: int) -> List[Dict]:
    """List pending invitations received by a user."""
    cols, rows = db_query(
        """
        SELECT pi.*, p.title, p.slug, lu.username as inviter_username
        FROM project_invitations pi
        JOIN projects p ON pi.project_id = p.id
        JOIN lab_users lu ON pi.inviter_id = lu.id
        WHERE pi.invitee_id = ? AND pi.status = 'pending'
        ORDER BY pi.created_at DESC
        """,
        [user_id]
    )
    return rows


def project_invitations_list_sent(project_id: int) -> List[Dict]:
    """List all invitations sent for a project (pending and answered)."""
    cols, rows = db_query(
        """
        SELECT pi.*, lu.username as invitee_username
        FROM project_invitations pi
        JOIN lab_users lu ON pi.invitee_id = lu.id
        WHERE pi.project_id = ?
        ORDER BY pi.created_at DESC
        """,
        [project_id]
    )
    return rows


def lab_user_get_by_username(username: str) -> Optional[Dict]:
    """Get a Lab user by username."""
    cols, rows = db_query(
        "SELECT * FROM lab_users WHERE username = ?",
        [username]
    )
    return rows[0] if rows else None


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


def comment_add_like(comment_id: int, user_id: int) -> bool:
    """Add a like to a comment by a user."""
    try:
        db_insert("comment_likes", {
            "comment_id": comment_id,
            "user_id": user_id,
            "created_at": time.time()
        })
        return True
    except Exception as e:
        # Likely duplicate entry
        return False


def comment_remove_like(comment_id: int, user_id: int) -> bool:
    """Remove a like from a comment by a user."""
    try:
        c = get_db().cursor()
        c.execute("DELETE FROM comment_likes WHERE comment_id = ? AND user_id = ?", 
                  (comment_id, user_id))
        return c.rowcount > 0
    except Exception:
        return False


def comment_has_like(comment_id: int, user_id: int) -> bool:
    """Check if a user has liked a comment."""
    try:
        cols, rows = db_query(
            "SELECT 1 FROM comment_likes WHERE comment_id = ? AND user_id = ?",
            [comment_id, user_id]
        )
        return len(rows) > 0
    except Exception:
        return False


def comment_get_like_count(comment_id: int) -> int:
    """Get the number of likes for a comment."""
    try:
        cols, rows = db_query(
            "SELECT COUNT(*) as count FROM comment_likes WHERE comment_id = ?",
            [comment_id]
        )
        return rows[0]["count"] if rows else 0
    except Exception:
        return 0


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
    col, row = get_lab_running_projects()
    return len(row) * _config.LAB_DOCKER_MEMORY_MB


def calculate_total_cpu_usage() -> int:
    """Calculate total CPU shares allocated to running Lab containers."""
    col, row = get_lab_running_projects()
    return len(row) * _config.LAB_DOCKER_CPU_SHARES


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
        lab_dir = resolve_lab_path(LAB_PROJECTS_DIR)
        
        # Create directories with proper permissions
        # Use 0o777 so container user (coder:1000) can write to mounted volumes
        os.makedirs(project_dir, mode=0o777, exist_ok=True)
        os.makedirs(socket_dir, mode=0o777, exist_ok=True)
        
        # Prepare volumes and mounts
        # Mount both the project directory (for code-server) and the parent lab directory
        # (so git commands can access the bare repo at ../projectslug.git)
        git_repo_dir = os.path.join(resolve_lab_path(LAB_PROJECTS_DIR), f"{project['slug']}.git")
        volumes = {
            project_dir: {"bind": "/home/coder/project", "mode": "rw"},
            lab_dir: {"bind": "/home/coder/lab", "mode": "rw"},
            git_repo_dir: {"bind": "/home/coder/project.git", "mode": "rw"},
            socket_dir: {"bind": "/tmp/sockets", "mode": "rw"}
        }
        
        # Container environment
        # Use /tmp/sockets inside container since that's where socket_dir is mounted
        container_socket_path = f"/tmp/sockets/{project['slug']}.sock"
        environment = {
            "CODER_PASSWORD": LAB_CODE_SERVER_PASSWORD or "hanshub",
            "PROJECT_SOCKET": container_socket_path,
            "PROJECT_SLUG": project["slug"]
        }
        
        # Load project secrets and inject as environment variables
        project_secrets = get_project_secrets_for_deployment(project["id"])
        environment.update(project_secrets)
        
        app_log.info(f"[lab] Injecting {len(project_secrets)} secrets for project {project['slug']}")
        
        # Start container (NO PORT MAPPING - Unix socket only)
        container = client.containers.run(
            LAB_DOCKER_IMAGE,
            name=f"lab-{project['slug']}",
            volumes=volumes,
            environment=environment,
            mem_limit=f"{_config.LAB_DOCKER_MEMORY_MB}m",
            cpu_shares=_config.LAB_DOCKER_CPU_SHARES,
            network_mode="bridge",
            dns=["8.8.8.8", "1.1.1.1"],  # Explicit DNS for reliable package manager access
            detach=True,
            restart_policy={"Name": "no"},
            user="1000:1000"  # Run as coder user (see tools/Dockerfile.lab)
        )
        
        # Wait for socket file to be created and set permissions
        import time
        socket_path = os.path.join(socket_dir, f"{project['slug']}.sock")
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


def docker_container_get_ip(container_id: str) -> Optional[str]:
    """
    Get the IP address of a running Docker container.
    
    Returns:
        The container's IP address on the bridge network, or None if not found.
    """
    try:
        import docker
        client = docker.from_env()
        container = client.containers.get(container_id)
        
        # Force SDK to refresh container attributes from Docker daemon
        # This ensures IP address is up-to-date, especially on cold boots
        container.reload()
        
        # Try to get the IP from the default bridge network
        if (container.attrs and 
            "NetworkSettings" in container.attrs and 
            "Networks" in container.attrs["NetworkSettings"]):
            networks = container.attrs["NetworkSettings"]["Networks"]
            # Try 'bridge' first, then fall back to first available network
            if "bridge" in networks and networks["bridge"].get("IPAddress"):
                return networks["bridge"]["IPAddress"]
            else:
                # Get first network with an IP
                for network_name, network_info in networks.items():
                    if network_info.get("IPAddress"):
                        return network_info["IPAddress"]
        
        return None
    except Exception as e:
        error_log.warning(f"[lab] Failed to get container IP for {container_id[:12]}: {e}")
        return None


def sync_all_container_states():
    """
    Syncs the database 'status' with Docker reality.
    Forces Always-On projects to boot up if they are missing.
    """
    import docker
    import time
    try:
        client = docker.from_env()
    except Exception as e:
        app_log.error(f"[lab] Docker connection failed: {e}")
        return

    # Fetch all projects using your existing db_query helper
    cols, results = db_query("SELECT * FROM projects")
    if not results:
        return

    for project in results:
        # project is already a dict because of how your db_query works
        slug = project['slug']
        project_id = project['id']
        is_always_on = project.get('is_always_on', 0)
        container_name = f"lab-{slug}"
        
        is_running = False
        try:
            container = client.containers.get(container_name)
            if container.status == "running":
                is_running = True
        except:
            is_running = False

        if is_running:
            # If Docker says it's running, ensure DB matches
            db_update_row("projects", project_id, {"status": "RUNNING"})
        else:
            if is_always_on == 1:
                app_log.info(f"[lab] Always-on project '{slug}' is offline. Starting...")
                try:
                    # Use your actual function from lab.py
                    docker_container_start(project)
                    db_update_row("projects", project_id, {"status": "RUNNING"})
                except Exception as e:
                    app_log.error(f"[lab] Auto-start failed for {slug}: {e}")
                    db_update_row("projects", project_id, {"status": "OFFLINE"})
            else:
                # Spontaneous project that is not running
                db_update_row("projects", project_id, {"status": "OFFLINE"})

    app_log.info("[lab] Startup status synchronization complete.")

# ──────────────────────────────────────────────────────────────────────────────
# Project Scaffolding
# ──────────────────────────────────────────────────────────────────────────────

def project_scaffold(project: Dict) -> bool:
    """
    Initialize a project directory with the universal Flask template.
    
    Unified Dual-Process Architecture: All projects get the same Flask+HTML template.
    The container runs both the app (port 8000) and IDE (port 8443) simultaneously.
    
    Returns:
        True on success, False on failure
    """
    try:
        project_dir = os.path.join(resolve_lab_path(LAB_PROJECTS_DIR), project["slug"])
        os.makedirs(project_dir, mode=0o755, exist_ok=True)
        
        # Universal Template: All projects use Flask for consistency
        # Users can modify app.py to add their own logic, frameworks, etc.
        _scaffold_universal_app(project_dir)
        
        # Generate .gitignore to prevent repo bloat
        _scaffold_gitignore(project_dir)
        
        # Setup Python virtual environment
        _setup_python_venv(project_dir)
        _scaffold_vscode_settings(project_dir)
        
        # Create initial git commit after scaffolding
        git_create_initial_commit(project["slug"])
        
        app_log.info(f"[lab] Scaffolded project {project['slug']} (universal)")
        return True
    
    except Exception as e:
        error_log.error(f"[lab] Failed to scaffold project {project['slug']}: {e}")
        return False


def _scaffold_universal_app(project_dir: str):
    """
    Create the universal Flask application template.
    
    All projects start with the same Flask structure:
    - app.py: Flask app serving index.html on port 8000
    - requirements.txt: Flask, python-dotenv dependencies
    - templates/index.html: Basic starting HTML
    - Static files support for CSS, JS, images
    
    Users modify these files to build their project.
    """
    os.makedirs(project_dir, exist_ok=True)
    
    # Create app.py with graceful shutdown and basic Flask app
    app_py = """
import signal
import sys
from flask import Flask, render_template, send_from_directory
import os

app = Flask(__name__)

def graceful_shutdown(signum, frame):
    \"\"\"Handle SIGINT/SIGTERM for graceful shutdown.\"\"\"
    print('[Server] Shutting down gracefully...', file=sys.stderr)
    sys.exit(0)

signal.signal(signal.SIGINT, graceful_shutdown)
signal.signal(signal.SIGTERM, graceful_shutdown)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
"""
    
    requirements_txt = """Flask==2.3.3
Werkzeug==2.3.7
python-dotenv==1.0.0
watchdog==4.0.0
"""
    
    # Create templates directory and HTML
    templates_dir = os.path.join(project_dir, "templates")
    os.makedirs(templates_dir, exist_ok=True)
    
    index_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>My HansHub Project</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        
        .container {
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            padding: 40px;
            max-width: 600px;
            text-align: center;
        }
        
        h1 {
            color: #333;
            margin-bottom: 15px;
            font-size: 2em;
        }
        
        .subtitle {
            color: #666;
            font-size: 1.1em;
            margin-bottom: 30px;
            line-height: 1.6;
        }
        
        .features {
            text-align: left;
            margin: 30px 0;
            padding: 20px;
            background: #f5f7fa;
            border-radius: 8px;
        }
        
        .features li {
            margin: 10px 0;
            color: #555;
            list-style-position: inside;
        }
        
        .cta {
            margin-top: 30px;
        }
        
        .cta a {
            display: inline-block;
            background: #667eea;
            color: white;
            padding: 12px 30px;
            border-radius: 6px;
            text-decoration: none;
            font-weight: 600;
            transition: background 0.3s;
        }
        
        .cta a:hover {
            background: #764ba2;
        }
        
        .info {
            margin-top: 20px;
            font-size: 0.9em;
            color: #999;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 Welcome to your HansHub Project!</h1>
        <p class="subtitle">
            Your Flask app is now running and ready to customize. Edit the files in VS Code to get started.
        </p>
        
        <div class="features">
            <strong>What you can do:</strong>
            <ul>
                <li>Edit <code>templates/index.html</code> to customize this page</li>
                <li>Add static files (CSS, JS, images) in the <code>static/</code> directory</li>
                <li>Modify <code>app.py</code> to create routes and add backend logic</li>
                <li>Install Python packages with <code>pip install &lt;package&gt;</code></li>
                <li>Commit your changes to the built-in Git repository</li>
            </ul>
        </div>
        
        <div class="info">
            ✨ Your app is running on port 8000. Changes to Python code will auto-reload.
        </div>
    </div>
</body>
</html>
"""
    
    with open(os.path.join(project_dir, "app.py"), "w") as f:
        f.write(app_py.strip())
    
    with open(os.path.join(project_dir, "requirements.txt"), "w") as f:
        f.write(requirements_txt.strip())
    
    with open(os.path.join(templates_dir, "index.html"), "w") as f:
        f.write(index_html.strip())
    
    # Create static directory for CSS, JS, images
    static_dir = os.path.join(project_dir, "static")
    os.makedirs(static_dir, exist_ok=True)
    
    # Create a basic CSS file
    css_content = """/* Add your custom styles here */
body {
    font-family: sans-serif;
}
"""
    with open(os.path.join(static_dir, "style.css"), "w") as f:
        f.write(css_content.strip())
    
    # Create .vscode/settings.json to exclude venv and caches from file watcher
    # This prevents IDE hangs and excessive CPU usage from monitoring massive directories
    vscode_dir = os.path.join(project_dir, ".vscode")
    os.makedirs(vscode_dir, exist_ok=True)
    
    vscode_settings = {
        "files.watcherExclude": {
            "**/venv/**": True,
            "**/__pycache__/**": True,
            "**/.git/objects/**": True,
            "**/.git/hooks/**": True,
            "**/.git/logs/**": True,
            "**/node_modules/**": True,
            "**/*.pyc": True
        }
    }
    
    import json
    with open(os.path.join(vscode_dir, "settings.json"), "w") as f:
        json.dump(vscode_settings, f, indent=2)
    
    app_log.info(f"[lab] Created universal app template at {project_dir}")
    
    app_py = """
import signal
import sys
from flask import Flask, render_template

app = Flask(__name__)

def graceful_shutdown(signum, frame):
    \"\"\"Handle SIGINT/SIGTERM for graceful shutdown.\"\"\"
    print('\\n[Server] Shutting down gracefully...', file=sys.stderr)
    sys.exit(0)

signal.signal(signal.SIGINT, graceful_shutdown)
signal.signal(signal.SIGTERM, graceful_shutdown)

@app.route('/')
def index():
    return render_template('index.html')
    

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
"""
    
    requirements_txt = """Flask==2.3.3
Werkzeug==2.3.7
python-dotenv==1.0.0
watchdog==4.0.0
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
    """Create FastAPI starter template with graceful shutdown."""
    os.makedirs(project_dir, exist_ok=True)
    
    app_py = """
import signal
import sys
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="HansHub FastAPI App")

def graceful_shutdown(signum, frame):
    \"\"\"Handle SIGINT/SIGTERM for graceful shutdown.\"\"\"
    print('\\n[Server] Shutting down gracefully...', file=sys.stderr)
    sys.exit(0)

signal.signal(signal.SIGINT, graceful_shutdown)
signal.signal(signal.SIGTERM, graceful_shutdown)

@app.get("/", response_class=HTMLResponse)
def read_root():
    return '''
    <!DOCTYPE html>
    <html>
        <head>
            <title>FastAPI App</title>
        </head>
        <body>
            <h1>Welcome to FastAPI!</h1>
            <p>Edit app.py to customize.</p>
        </body>
    </html>
    '''

if __name__ == '__main__':
    import uvicorn
    print('[Server] Starting FastAPI app on 0.0.0.0:8000')
    uvicorn.run(app, host='0.0.0.0', port=8000)
"""
    
    requirements_txt = """fastapi==0.103.1
uvicorn==0.23.2
python-dotenv==1.0.0
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
import os
import signal
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler

class ShutdownHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stderr.write("[%s] %s\\n" % (self.log_date_time_string(), format % args))

def graceful_shutdown(signum, frame):
    print('\\n[Server] Shutting down gracefully...', file=sys.stderr)
    sys.exit(0)

signal.signal(signal.SIGINT, graceful_shutdown)
signal.signal(signal.SIGTERM, graceful_shutdown)

os.chdir(os.path.dirname(__file__))
httpd = HTTPServer(('0.0.0.0', 8000), ShutdownHandler)
print('[Server] Starting HTTP server on http://0.0.0.0:8000')
try:
    httpd.serve_forever()
except KeyboardInterrupt:
    print('\\n[Server] Shutting down gracefully...', file=sys.stderr)
""".strip())


def _scaffold_blank_python(project_dir: str):
    """Create blank Python starter template."""
    os.makedirs(project_dir, exist_ok=True)
    
    with open(os.path.join(project_dir, "main.py"), "w") as f:
        f.write("""
import signal
import sys

def graceful_shutdown(signum, frame):
    \"\"\"Handle SIGINT/SIGTERM for graceful shutdown.\"\"\"
    print('\\n[App] Shutting down gracefully...', file=sys.stderr)
    sys.exit(0)

signal.signal(signal.SIGINT, graceful_shutdown)
signal.signal(signal.SIGTERM, graceful_shutdown)

def hello():
    return "Hello, HansHub Lab!"

if __name__ == '__main__':
    print(hello())
""".strip())
    
    with open(os.path.join(project_dir, "requirements.txt"), "w") as f:
        f.write("""python-dotenv==1.0.0
""".strip())


def _scaffold_nodejs_express(project_dir: str):
    """Create Node.js Express starter template."""
    os.makedirs(project_dir, exist_ok=True)
    
    package_json = {
        "name": "hanshub-app",
        "version": "1.0.0",
        "description": "HansHub Node.js project",
        "main": "app.js",
        "scripts": {
            "start": "node app.js",
            "dev": "nodemon app.js"
        },
        "dependencies": {
            "express": "^4.18.2",
            "dotenv": "^16.3.1"
        }
    }
    
    with open(os.path.join(project_dir, "package.json"), "w") as f:
        json.dump(package_json, f, indent=2)
    
    app_js = """
const express = require('express');
const app = express();

// Graceful shutdown handlers
process.on('SIGINT', () => {
    console.error('\\n[Server] Shutting down gracefully...');
    process.exit(0);
});

process.on('SIGTERM', () => {
    console.error('[Server] Shutting down gracefully...');
    process.exit(0);
});

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

const server = app.listen(8000, '0.0.0.0', () => {
    console.log('[Server] Starting Express app on http://0.0.0.0:8000');
});

server.on('error', (err) => {
    console.error('[Server] Error:', err);
});
"""
    
    with open(os.path.join(project_dir, "app.js"), "w") as f:
        f.write(app_js.strip())


def _setup_python_venv(project_dir: str):
    """
    Prepare Python project for virtual environment creation.
    
    NOTE: The actual venv creation happens INSIDE the container via entrypoint-lab.sh
    This is necessary because venv with compiled packages must be created in the target OS,
    not on the host. This function just ensures requirements.txt exists.
    """
    requirements_file = os.path.join(project_dir, "requirements.txt")
    if os.path.exists(requirements_file):
        app_log.info(f"[lab] requirements.txt exists - venv will be created in container: {requirements_file}")
    else:
        error_log.warning(f"[lab] requirements.txt not found for {project_dir}")


def _scaffold_vscode_settings(project_dir: str):
    """
    Create .vscode/settings.json to configure VS Code for the project.
    
    This forces code-server to use the project's virtual environment,
    sets up the PATH so terminal commands use venv, and enables better 
    Python language support.
    """
    vscode_dir = os.path.join(project_dir, ".vscode")
    os.makedirs(vscode_dir, exist_ok=True)
    
    settings = {
        "python.defaultInterpreterPath": "/home/coder/project/venv/bin/python",
        "terminal.integrated.env.linux": {
            "PATH": "/home/coder/project/venv/bin:${env:PATH}"
        },
        "python.formatting.provider": "black",
        "python.linting.enabled": True,
        "python.linting.pylintEnabled": False,
        "[python]": {
            "editor.defaultFormatter": "ms-python.python",
            "editor.formatOnSave": True
        }
    }
    
    settings_file = os.path.join(vscode_dir, "settings.json")
    try:
        with open(settings_file, "w") as f:
            json.dump(settings, f, indent=2)
        app_log.info(f"[lab] Created VS Code settings at {settings_file}")
    except Exception as e:
        error_log.error(f"[lab] Failed to create VS Code settings: {e}")


def _scaffold_gitignore(project_dir: str):
    """
    Create a .gitignore file to exclude common files that shouldn't be committed.
    
    This prevents venv, dependencies, cache files, and OS files from bloating the repository.
    """
    gitignore_path = os.path.join(project_dir, ".gitignore")
    
    gitignore_content = """# Virtual Environment
venv/
env/
ENV/
.venv/

# Environment variables
.env
.env.local

# Python cache and compiled files
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
*.egg-info/
dist/
build/

# IDE and Editor
.vscode/
.idea/
*.swp
*.swo
*~

# OS files
.DS_Store
Thumbs.db
.project
.pydevproject

# Node modules (if applicable)
node_modules/
npm-debug.log

# Logs
*.log
logs/

# Coverage and testing
.coverage
htmlcov/
.pytest_cache/

# Database files
*.db
*.sqlite
*.sqlite3
"""
    
    try:
        with open(gitignore_path, "w") as f:
            f.write(gitignore_content.strip())
        app_log.info(f"[lab] Created .gitignore at {gitignore_path}")
    except Exception as e:
        error_log.error(f"[lab] Failed to create .gitignore: {e}")


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
    Always-on projects are EXEMPT from this check.
    """
    now = time.time()
    idle_threshold = _config.LAB_IDLE_TIMEOUT_MINS * 60
    
    projects_to_stop = []
    
    for project_id, last_activity in list(project_idle_timers.items()):
        # Check if the time has passed the threshold
        if (now - last_activity) > idle_threshold:
            # CRITICAL FIX: Get project details to check Always-On status
            project = project_get_by_id(project_id)
            
            # Only stop it if it is NOT an always-on project
            if project and project.get("is_always_on") == 0:
                projects_to_stop.append(project_id)
            else:
                # If it IS always-on, just remove it from the idle timer 
                # so we stop checking it, or update its timer to 'now'
                if project_id in project_idle_timers:
                    del project_idle_timers[project_id]

    for project_id in projects_to_stop:
        project = project_get_by_id(project_id)
        if project and project.get("docker_container_id"):
            app_log.info(f"[lab] Stopping idle spontaneous project {project_id}")
            docker_container_stop(project["docker_container_id"], project_id)
            
            db_update_row("projects", project_id, {
                "docker_container_id": None, 
                "status": "OFFLINE"
            })
            
            if project_id in project_idle_timers:
                del project_idle_timers[project_id]


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


# ──────────────────────────────────────────────────────────────────────────────
# Environment Secrets Management
# ──────────────────────────────────────────────────────────────────────────────

def set_project_secret(project_id: int, secret_key: str, secret_value: str) -> bool:
    """
    Store or update an environment secret for a project.
    
    Secrets are encrypted and stored in the database. They can be injected as
    environment variables when the project's Docker container starts.
    
    Args:
        project_id: Project ID
        secret_key: Secret key/name (e.g., 'API_KEY', 'DB_PASSWORD')
        secret_value: Secret value (stored encrypted)
    
    Returns:
        True on success, False on failure
    """
    try:
        if not secret_key or not secret_value:
            error_log.error("[lab] Secret key and value cannot be empty")
            return False
        
        # Check if project exists
        project = project_get_by_id(project_id)
        if not project:
            error_log.error(f"[lab] Project {project_id} not found")
            return False
        
        # Check if secret already exists (update) or new (insert)
        conn = get_db()
        c = conn.cursor()
        
        try:
            c.execute(
                "SELECT id FROM project_secrets WHERE project_id = ? AND secret_key = ?",
                (project_id, secret_key)
            )
            existing = c.fetchone()
            
            if existing:
                # Update existing secret
                db_update_row("project_secrets", existing[0], {
                    "secret_value": secret_value,
                    "updated_at": time.time()
                })
                app_log.info(f"[lab] Updated secret '{secret_key}' for project {project_id}")
            else:
                # Insert new secret
                db_insert("project_secrets", {
                    "project_id": project_id,
                    "secret_key": secret_key,
                    "secret_value": secret_value,
                    "created_at": time.time(),
                    "updated_at": time.time()
                })
                app_log.info(f"[lab] Created secret '{secret_key}' for project {project_id}")
            
            return True
        finally:
            conn.close()
    
    except Exception as e:
        error_log.error(f"[lab] Failed to set secret for project {project_id}: {e}")
        return False


def delete_project_secret(project_id: int, secret_key: str) -> bool:
    """
    Delete an environment secret for a project.
    
    Args:
        project_id: Project ID
        secret_key: Secret key to delete
    
    Returns:
        True on success, False if secret not found or error
    """
    try:
        conn = get_db()
        c = conn.cursor()
        
        try:
            c.execute(
                "SELECT id FROM project_secrets WHERE project_id = ? AND secret_key = ?",
                (project_id, secret_key)
            )
            secret_id = c.fetchone()
            
            if not secret_id:
                error_log.warning(f"[lab] Secret '{secret_key}' not found for project {project_id}")
                return False
            
            db_delete_row("project_secrets", secret_id[0])
            app_log.info(f"[lab] Deleted secret '{secret_key}' for project {project_id}")
            return True
        finally:
            conn.close()
    
    except Exception as e:
        error_log.error(f"[lab] Failed to delete secret for project {project_id}: {e}")
        return False


def get_project_secret_keys(project_id: int) -> List[str]:
    """
    Get all secret keys (not values) for a project.
    
    This returns only the key names, not the actual secret values (for security).
    Secret values should only be loaded into environment variables when the
    container is actually deployed.
    
    Args:
        project_id: Project ID
    
    Returns:
        List of secret key names, empty list if none or error
    """
    try:
        conn = get_db()
        c = conn.cursor()
        
        try:
            c.execute(
                "SELECT secret_key FROM project_secrets WHERE project_id = ? ORDER BY created_at ASC",
                (project_id,)
            )
            rows = c.fetchall()
            keys = [row[0] for row in rows]
            return keys
        finally:
            conn.close()
    
    except Exception as e:
        error_log.error(f"[lab] Failed to get secrets for project {project_id}: {e}")
        return []


def get_project_secrets_for_deployment(project_id: int) -> Dict[str, str]:
    """
    Get all secrets for a project as a dict for Docker environment injection.
    
    This is called only at deployment time and returns the actual secret values.
    Should be used with caution and never logged or exposed to the client.
    
    Args:
        project_id: Project ID
    
    Returns:
        Dict of secret_key -> secret_value, empty dict if none or error
    """
    try:
        conn = get_db()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        try:
            c.execute(
                "SELECT secret_key, secret_value FROM project_secrets WHERE project_id = ?",
                (project_id,)
            )
            rows = c.fetchall()
            secrets = {row["secret_key"]: row["secret_value"] for row in rows}
            return secrets
        finally:
            conn.close()
    
    except Exception as e:
        error_log.error(f"[lab] Failed to get secrets for deployment {project_id}: {e}")
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# Project Starring & Ratings
# ──────────────────────────────────────────────────────────────────────────────

def project_add_star(project_id: int, user_id: int) -> bool:
    """
    Add a star to a project by a user.
    
    Args:
        project_id: Project ID
        user_id: User ID
    
    Returns:
        True on success (created new star), False if already starred or error
    """
    try:
        db_insert("project_stars", {
            "project_id": project_id,
            "user_id": user_id,
            "created_at": time.time()
        })
        app_log.info(f"[lab] User {user_id} starred project {project_id}")
        return True
    except sqlite3.IntegrityError:
        # Already starred by this user
        return False
    except Exception as e:
        error_log.error(f"[lab] Failed to add star: {e}")
        return False


def project_remove_star(project_id: int, user_id: int) -> bool:
    """
    Remove a star from a project by a user.
    
    Args:
        project_id: Project ID
        user_id: User ID
    
    Returns:
        True on success, False if not starred or error
    """
    try:
        conn = get_db()
        c = conn.cursor()
        
        try:
            c.execute(
                "DELETE FROM project_stars WHERE project_id = ? AND user_id = ?",
                (project_id, user_id)
            )
            conn.commit()
            
            if c.rowcount > 0:
                app_log.info(f"[lab] User {user_id} unstarred project {project_id}")
                return True
            return False
        finally:
            conn.close()
    
    except Exception as e:
        error_log.error(f"[lab] Failed to remove star: {e}")
        return False


def project_get_star_count(project_id: int) -> int:
    """
    Get the number of stars for a project.
    
    Args:
        project_id: Project ID
    
    Returns:
        Number of stars, 0 if none or error
    """
    try:
        conn = get_db()
        c = conn.cursor()
        
        try:
            c.execute(
                "SELECT COUNT(*) FROM project_stars WHERE project_id = ?",
                (project_id,)
            )
            count = c.fetchone()[0]
            return count
        finally:
            conn.close()
    
    except Exception as e:
        error_log.error(f"[lab] Failed to get star count: {e}")
        return 0


def project_has_star(project_id: int, user_id: int) -> bool:
    """
    Check if a user has starred a project.
    
    Args:
        project_id: Project ID
        user_id: User ID
    
    Returns:
        True if starred, False otherwise or error
    """
    try:
        conn = get_db()
        c = conn.cursor()
        
        try:
            c.execute(
                "SELECT 1 FROM project_stars WHERE project_id = ? AND user_id = ?",
                (project_id, user_id)
            )
            return c.fetchone() is not None
        finally:
            conn.close()
    
    except Exception as e:
        error_log.error(f"[lab] Failed to check star: {e}")
        return False


def project_list_public_sorted(sort_by: str = "recent", search_query: str = "") -> List[Dict]:
    """
    List all public projects with optional sorting and search filtering.
    
    Args:
        sort_by: Sort order - 'recent' (default), 'stars' (most starred)
        search_query: Optional search string to filter by name, description, owner, or contributors
    
    Returns:
        List of project dicts, sorted and filtered as requested
    """
    try:
        search_filter = ""
        if search_query:
            search_query = f"%{search_query}%"
            search_filter = """
                AND (
                    p.title LIKE ? 
                    OR p.description LIKE ?
                    OR u.username LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM project_members pm
                        JOIN lab_users lu ON pm.user_id = lu.id
                        WHERE pm.project_id = p.id AND lu.username LIKE ?
                    )
                )
            """
        
        if sort_by == "stars":
            query = f"""
                SELECT p.id, p.owner_id, p.slug, p.title, p.description, 
                       p.visibility, p.socket_path, p.git_url, p.docker_container_id, 
                       p.is_always_on, p.created_at, p.updated_at, p.last_deployed_at,
                       COUNT(ps.id) as star_count, 
                       COALESCE(u.username, 'Unknown') as owner_username
                FROM projects p
                LEFT JOIN project_stars ps ON p.id = ps.project_id
                LEFT JOIN lab_users u ON p.owner_id = u.id
                WHERE p.visibility = 'public'
                {search_filter}
                GROUP BY p.id
                ORDER BY star_count DESC, p.created_at DESC
            """
            if search_query:
                cols, rows = db_query(query, (search_query, search_query, search_query, search_query))
            else:
                cols, rows = db_query(query)
        else:
            # Default to 'recent'
            query = f"""
                SELECT p.id, p.owner_id, p.slug, p.title, p.description, 
                       p.visibility, p.socket_path, p.git_url, p.docker_container_id, 
                       p.is_always_on, p.created_at, p.updated_at, p.last_deployed_at,
                       0 as star_count, 
                       COALESCE(u.username, 'Unknown') as owner_username
                FROM projects p
                LEFT JOIN lab_users u ON p.owner_id = u.id
                WHERE p.visibility = 'public'
                {search_filter}
                ORDER BY p.created_at DESC
            """
            if search_query:
                cols, rows = db_query(query, (search_query, search_query, search_query, search_query))
            else:
                cols, rows = db_query(query)
        
        return rows if rows else []
    
    except Exception as e:
        error_log.error(f"[lab] Failed to list public projects: {e}")
        return []


# ═════════════════════════════════════════════════════════════════════════════
# Git Integration - Wrap Git Commands for Multi-Contributor Collaboration
# ═════════════════════════════════════════════════════════════════════════════

def _get_git_dir(project_slug: str) -> str:
    """Get the git directory path for a project."""
    project_dir = os.path.join(resolve_lab_path(LAB_PROJECTS_DIR), project_slug)
    return os.path.join(project_dir, '.git')


def _get_project_dir(project_slug: str) -> str:
    """Get the project directory path."""
    return os.path.join(resolve_lab_path(LAB_PROJECTS_DIR), project_slug)


def git_init_repo(project_slug: str, author_name: str) -> bool:
    """Initialize a git repository for a new project with isolation and local origin."""
    try:
        project_dir = _get_project_dir(project_slug)
        git_dir = _get_git_dir(project_slug)
        
        # Bare repository path (acts as "origin" remote on the server)
        bare_repo_dir = os.path.join(resolve_lab_path(LAB_PROJECTS_DIR), f"{project_slug}.git")
        
        # Make sure project dir exists
        os.makedirs(project_dir, exist_ok=True)
        
        # Create bare repository (acts as origin)
        if not os.path.exists(bare_repo_dir):
            # Create the bare repo directory first
            os.makedirs(bare_repo_dir, exist_ok=True)
            
            result = subprocess.run(
                ['git', 'init', '--bare', '--initial-branch=main'],
                cwd=bare_repo_dir,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                error_log.error(f"[lab] Failed to create bare repo: {result.stderr}")
                return False
            app_log.info(f"[lab] Created bare git repo at {bare_repo_dir}")
        
        # Initialize working tree repo with explicit git directory
        result = subprocess.run(
            ['git', 'init', '--initial-branch=main'],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode != 0:
            error_log.error(f"[lab] Git init failed: {result.stderr}")
            return False
        
        # Verify .git directory was created
        if not os.path.exists(git_dir):
            error_log.error(f"[lab] Git directory not created at {git_dir}")
            return False
        
        # Use --git-dir and --work-tree to explicitly set repo location (prevents parent search)
        subprocess.run(
            ['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'config', 'user.name', author_name],
            cwd=project_dir,
            capture_output=True,
            check=True
        )
        
        email = f"{author_name.lower().replace(' ', '.')}@hanshub.local"
        subprocess.run(
            ['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'config', 'user.email', email],
            cwd=project_dir,
            capture_output=True,
            check=True
        )
        
        # Configure the bare repo as "origin" remote (local push destination)
        # Use container-specific path so it works inside docker container
        container_bare_path = "/home/coder/project.git"
        subprocess.run(
            ['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'remote', 'add', 'origin', container_bare_path],
            cwd=project_dir,
            capture_output=True,
            check=True
        )
        
        app_log.info(f"[lab] Initialized git repo for project: {project_slug} at {git_dir}")
        app_log.info(f"[lab] Configured local origin remote at {bare_repo_dir}")
        return True
    except Exception as e:
        error_log.error(f"[lab] Failed to init git repo: {e}")
        return False


def git_create_initial_commit(project_slug: str, initial_file: str = "README.md") -> bool:
    """Create initial commit in git repository and push to local origin."""
    try:
        project_dir = _get_project_dir(project_slug)
        git_dir = _get_git_dir(project_slug)
        
        # Verify git repo exists
        if not os.path.exists(git_dir):
            error_log.error(f"[lab] Git repo not found at {git_dir}")
            return False
        
        # Create initial file if it doesn't exist
        readme_path = os.path.join(project_dir, initial_file)
        if not os.path.exists(readme_path):
            with open(readme_path, 'w') as f:
                f.write(f"# {project_slug}\n\nProject initialized by HansHub.\n")
        
        # Add all files using explicit git repo
        subprocess.run(
            ['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'add', '.'],
            cwd=project_dir,
            capture_output=True,
            check=True
        )
        
        # Create commit using explicit git repo
        subprocess.run(
            ['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'commit', '-m', 'Initial commit'],
            cwd=project_dir,
            capture_output=True,
            check=True
        )
        
        # Push initial commit to local origin remote
        # This allows code-server to track remote/origin branch
        subprocess.run(
            ['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'push', '-u', 'origin', 'main'],
            cwd=project_dir,
            capture_output=True,
            check=False  # Don't fail if push doesn't work (might happen if bare repo not ready)
        )
        
        return True
    except Exception as e:
        error_log.error(f"[lab] Failed to create initial commit: {e}")
        return False
        return False


def git_get_branches(project_slug: str) -> List[Dict]:
    """Get all git branches for a project."""
    try:
        project_dir = _get_project_dir(project_slug)
        git_dir = _get_git_dir(project_slug)
        
        # Get all branches with metadata - use explicit git dir to prevent parent search
        result = subprocess.run(
            ['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'branch', '-v', '--format=%(refname:short)|%(objectname:short)|%(committerdate:iso8601-strict)'],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=True
        )
        
        branches = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split('|')
            if len(parts) >= 3:
                branches.append({
                    'name': parts[0],
                    'commit': parts[1],
                    'date': parts[2],
                    'is_default': parts[0] == 'main'
                })
        
        return branches
    except Exception as e:
        error_log.error(f"[lab] Failed to get branches: {e}")
        return []


def git_create_branch(project_slug: str, branch_name: str, from_commit: str = None) -> bool:
    """Create a new branch from a commit hash (or HEAD if not specified)."""
    try:
        project_dir = _get_project_dir(project_slug)
        git_dir = _get_git_dir(project_slug)
        
        if from_commit:
            subprocess.run(['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'checkout', '-b', branch_name, from_commit], cwd=project_dir, check=True, capture_output=True)
        else:
            subprocess.run(['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'checkout', '-b', branch_name], cwd=project_dir, check=True, capture_output=True)
        
        # Switch back to main after creating
        subprocess.run(['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'checkout', 'main'], cwd=project_dir, check=True, capture_output=True)
        
        return True
    except Exception as e:
        error_log.error(f"[lab] Failed to create branch: {e}")
        return False


def git_get_commit_log(project_slug: str, branch: str = 'main', limit: int = 50) -> List[Dict]:
    """Get commit history for a branch."""
    try:
        project_dir = _get_project_dir(project_slug)
        git_dir = _get_git_dir(project_slug)
        
        # Get commits with full info - use explicit git dir to prevent parent search
        result = subprocess.run(
            ['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'log', f'{branch}', '--format=%H|%an|%ae|%s|%aI|%b', f'-n{limit}'],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=True
        )
        
        commits = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split('|', 5)
            if len(parts) >= 4:
                commits.append({
                    'hash': parts[0][:7],  # Short hash
                    'author': parts[1],
                    'email': parts[2],
                    'message': parts[3],
                    'date': parts[4],
                    'body': parts[5] if len(parts) > 5 else ''
                })
        
        return commits
    except Exception as e:
        error_log.error(f"[lab] Failed to get commit log: {e}")
        return []


def git_get_diff_stat(project_slug: str, commit1: str, commit2: str) -> Dict:
    """Get statistics of changes between two commits."""
    try:
        project_dir = _get_project_dir(project_slug)
        git_dir = _get_git_dir(project_slug)
        
        # Get files changed - use explicit git dir
        result = subprocess.run(
            ['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'diff', '--name-status', commit1, commit2],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=True
        )
        
        changes = {'created': [], 'modified': [], 'deleted': []}
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            status, filepath = line.split('\t', 1)
            if status == 'A':
                changes['created'].append(filepath)
            elif status == 'M':
                changes['modified'].append(filepath)
            elif status == 'D':
                changes['deleted'].append(filepath)
        
        return changes
    except Exception as e:
        error_log.error(f"[lab] Failed to get diff stat: {e}")
        return {'created': [], 'modified': [], 'deleted': []}


def git_merge_branch(project_slug: str, source_branch: str, target_branch: str = 'main') -> Dict:
    """Attempt to merge source branch into target branch. Returns merge status."""
    try:
        project_dir = _get_project_dir(project_slug)
        git_dir = _get_git_dir(project_slug)
        
        # Checkout target branch using explicit git dir
        subprocess.run(['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'checkout', target_branch], cwd=project_dir, check=True, capture_output=True)
        
        # Attempt merge
        result = subprocess.run(
            ['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'merge', source_branch, '--no-edit'],
            cwd=project_dir,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return {'success': True, 'message': f'Successfully merged {source_branch} into {target_branch}'}
        else:
            # Merge conflict detected
            conflicts = git_get_conflicted_files(project_slug)
            return {
                'success': False,
                'conflicts': conflicts,
                'merge_in_progress': True,
                'error': 'Merge conflict detected. Please resolve conflicts.'
            }
    except Exception as e:
        error_log.error(f"[lab] Failed to merge branches: {e}")
        return {'success': False, 'error': str(e)}


def git_get_conflicted_files(project_slug: str) -> List[str]:
    """Get list of files with merge conflicts."""
    try:
        project_dir = _get_project_dir(project_slug)
        git_dir = _get_git_dir(project_slug)
        
        result = subprocess.run(
            ['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'diff', '--name-only', '--diff-filter=U'],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=True
        )
        
        return [f for f in result.stdout.strip().split('\n') if f]
    except Exception as e:
        error_log.error(f"[lab] Failed to get conflicted files: {e}")
        return []


def git_get_file_content(project_slug: str, file_path: str, commit_hash: str = None) -> Optional[str]:
    """Get file content at a specific commit (or working directory if no commit specified)."""
    try:
        project_dir = _get_project_dir(project_slug)
        git_dir = _get_git_dir(project_slug)
        
        if commit_hash:
            # Get from specific commit using explicit git dir
            result = subprocess.run(
                ['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'show', f'{commit_hash}:{file_path}'],
                cwd=project_dir,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout
        else:
            # Get from working directory
            full_path = os.path.join(project_dir, file_path)
            if os.path.exists(full_path):
                with open(full_path, 'r') as f:
                    return f.read()
            return None
    except Exception as e:
        error_log.error(f"[lab] Failed to get file content: {e}")
        return None


def git_resolve_conflict(project_slug: str, file_path: str, resolved_content: str) -> bool:
    """Resolve a merge conflict by writing resolved content and marking as resolved."""
    try:
        project_dir = _get_project_dir(project_slug)
        git_dir = _get_git_dir(project_slug)
        full_path = os.path.join(project_dir, file_path)
        
        # Write resolved content
        with open(full_path, 'w') as f:
            f.write(resolved_content)
        
        # Stage the file using explicit git dir
        subprocess.run(['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'add', file_path], cwd=project_dir, check=True, capture_output=True)
        
        return True
    except Exception as e:
        error_log.error(f"[lab] Failed to resolve conflict: {e}")
        return False


def git_abort_merge(project_slug: str) -> bool:
    """Abort an ongoing merge operation."""
    try:
        project_dir = _get_project_dir(project_slug)
        git_dir = _get_git_dir(project_slug)
        
        subprocess.run(['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'merge', '--abort'], cwd=project_dir, check=True, capture_output=True)
        
        return True
    except Exception as e:
        error_log.error(f"[lab] Failed to abort merge: {e}")
        return False


def git_complete_merge(project_slug: str, merge_message: str = "Merge branch") -> bool:
    """Complete a merge after resolving all conflicts."""
    try:
        project_dir = _get_project_dir(project_slug)
        git_dir = _get_git_dir(project_slug)
        
        # Check if merge is in progress
        merge_head = os.path.join(git_dir, 'MERGE_HEAD')
        if not os.path.exists(merge_head):
            return False
        
        # Commit the merge using explicit git dir
        subprocess.run(
            ['git', f'--git-dir={git_dir}', f'--work-tree={project_dir}', 'commit', '--no-edit', '-m', merge_message],
            cwd=project_dir,
            check=True,
            capture_output=True
        )
        
        return True
    except Exception as e:
        error_log.error(f"[lab] Failed to complete merge: {e}")
        return False
