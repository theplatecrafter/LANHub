"""socket_events/lab_events.py - LANHub Lab real-time event handlers."""

from flask import request
from flask_socketio import emit, join_room, leave_room
from socketio_instance import socketio
from glob_vars import app_log
import functions as f
from functions import lab
import config as _config
import time


# ──────────────────────────────────────────────────────────────────────────────
# State
# ──────────────────────────────────────────────────────────────────────────────

# Track authenticated Lab users per session ID
authenticated_users: dict[str, dict] = {}  # sid -> user_info

# Track which users are viewing/editing which projects
project_viewers: dict[str, dict] = {}  # project_id -> {sid: {username, user_id}}

# Idle heartbeat tracking
heartbeats: dict[str, float] = {}  # sid -> last_heartbeat_time


# ──────────────────────────────────────────────────────────────────────────────
# Connection Lifecycle
# ──────────────────────────────────────────────────────────────────────────────

@socketio.on("lab_connect")
def handle_lab_connect(data):
    """
    Lab user connects to the Lab namespace.
    Validates authentication and sets up session.
    Reads credentials from HTTP cookies (sent with WebSocket handshake).
    """
    sid = request.sid
    
    # Read auth credentials from HTTP cookies (automatically sent with WebSocket)
    lab_username = request.cookies.get("lab_username")
    lab_token = request.cookies.get("lab_session_token")
    
    if not lab_username or not lab_token:
        emit("lab_auth_failed", {"error": "No session credentials. Please log in."})
        return
    
    # Verify auth
    user = lab.lab_user_verify_session(lab_username, lab_token)
    if not user:
        emit("lab_auth_failed", {"error": "Invalid or expired session. Please log in again."})
        return
    
    # Store in authenticated_users dictionary (persistent per session)
    authenticated_users[sid] = user
    heartbeats[sid] = time.time()
    
    emit("lab_auth_success", {
        "username": user["username"],
        "user_id": user["id"]
    })
    
    app_log.info(f"[lab] User {user['username']} connected via WebSocket")


@socketio.on("disconnect")
def handle_lab_disconnect():
    """Clean up when user disconnects."""
    sid = request.sid
    
    # Remove from authenticated users
    if sid in authenticated_users:
        del authenticated_users[sid]
    
    # Remove from all project viewers
    for project_id in list(project_viewers.keys()):
        if sid in project_viewers[project_id]:
            del project_viewers[project_id][sid]
    
    # Remove heartbeat
    if sid in heartbeats:
        del heartbeats[sid]


# ──────────────────────────────────────────────────────────────────────────────
# Project Viewing / Collaboration
# ──────────────────────────────────────────────────────────────────────────────

@socketio.on("lab_join_project")
def handle_join_project(data):
    """
    User joins a project view (starts watching it).
    Used to track active users for spontaneous project idle timeouts.
    """
    sid = request.sid
    
    # Check if user is authenticated
    if sid not in authenticated_users:
        app_log.error(f"[lab] Join rejected - user not authenticated for {sid}")
        emit("error", {"message": "Not authenticated"})
        return
    
    user = authenticated_users[sid]
    project_slug = data.get("slug")
    app_log.info(f"[lab] User {user['username']} ({sid}) attempting to join project {project_slug}")
    
    project = lab.project_get_by_slug(project_slug)
    if not project:
        app_log.error(f"[lab] Join rejected - project {project_slug} not found")
        emit("error", {"message": "Project not found"})
        return
    
    # Check permissions
    if project["visibility"] == "private":
        role = lab.project_member_get_role(project["id"], user["id"])
        if not role:
            app_log.error(f"[lab] Join rejected - user {user['id']} no access to {project_slug}")
            emit("error", {"message": "Access denied"})
            return
    
    # Join room
    project_room = f"project_{project['id']}"
    join_room(project_room)
    app_log.info(f"[lab] User {user['username']} joined room {project_room}")
    
    # Track viewer
    if project["id"] not in project_viewers:
        project_viewers[project["id"]] = {}
    
    project_viewers[project["id"]][sid] = {
        "username": user["username"],
        "user_id": user["id"],
        "joined_at": time.time()
    }
    
    # Record activity for spontaneous projects
    if not project["is_always_on"]:
        lab.project_record_activity(project["id"])
    
    # Notify others
    active_count = len(project_viewers[project["id"]])
    socketio.emit("lab_viewers_updated", {
        "project_id": project["id"],
        "active_count": active_count,
        "viewers": [
            {"username": v["username"]} 
            for v in project_viewers[project["id"]].values()
        ]
    }, to=project_room)
    
    app_log.info(f"[lab] {user['username']} successfully joined project {project_slug}")


@socketio.on("lab_leave_project")
def handle_leave_project(data):
    """User leaves a project view."""
    sid = request.sid
    project_id = data.get("project_id")
    
    if not hasattr(request, "lab_user"):
        return
    
    user = request.lab_user
    
    # Get project to use consistent room naming
    project = lab.project_get_by_id(project_id)
    if project:
        project_id_normalized = project['id']
    else:
        project_id_normalized = project_id
    
    if project_id in project_viewers and sid in project_viewers[project_id]:
        del project_viewers[project_id][sid]
        
        project_room = f"project_{project_id_normalized}"
        leave_room(project_room)
        
        if project_viewers[project_id]:
            active_count = len(project_viewers[project_id])
            socketio.emit("lab_viewers_updated", {
                "project_id": project_id,
                "active_count": active_count,
                "viewers": [
                    {"username": v["username"]} 
                    for v in project_viewers[project_id].values()
                ]
            }, to=project_room)
        else:
            del project_viewers[project_id]
    
    app_log.info(f"[lab] {user['username']} left project")


# ──────────────────────────────────────────────────────────────────────────────
# Heartbeat & Idle Management
# ──────────────────────────────────────────────────────────────────────────────

@socketio.on("lab_heartbeat")
def handle_heartbeat(data):
    """Record user activity (WebSocket heartbeat)."""
    sid = request.sid
    if sid in heartbeats:
        heartbeats[sid] = time.time()
    
    # Also record project activity if viewing one
    project_id = data.get("project_id")
    if project_id:
        lab.project_record_activity(project_id)


def check_idle_projects():
    """
    Scheduled task to check for idle projects and stop them.
    Called periodically by APScheduler.
    """
    lab.project_check_idle()
    app_log.debug("[lab] Checked idle projects")


# ──────────────────────────────────────────────────────────────────────────────
# Collaboration / Notifications
# ──────────────────────────────────────────────────────────────────────────────

@socketio.on("lab_send_notification")
def handle_send_notification(data):
    """
    Send a notification to project members.
    Used for deployment status, build output, etc.
    """
    if not hasattr(request, "lab_user"):
        emit("error", {"message": "Not authenticated"})
        return
    
    user = request.lab_user
    project_id = data.get("project_id")
    message = data.get("message")
    notification_type = data.get("type", "info")  # info, warning, error, success
    
    project = lab.project_get_by_id(project_id)
    if not project:
        emit("error", {"message": "Project not found"})
        return
    
    # Check permission (owner/contributor only)
    if not lab.project_can_edit(project_id, user["id"]):
        emit("error", {"message": "Access denied"})
        return
    
    project_room = f"project_{project['id']}"
    socketio.emit("lab_notification", {
        "message": message,
        "type": notification_type,
        "from_user": user["username"],
        "timestamp": time.time()
    }, to=project_room)


# ──────────────────────────────────────────────────────────────────────────────
# File & Code Sync (Collaborative Editing - Optional)
# ──────────────────────────────────────────────────────────────────────────────

@socketio.on("lab_file_changed")
def handle_file_changed(data):
    """
    Broadcast file change notifications to other editors of the same project.
    Full content sync is handled by code-server; this just notifies others.
    """
    if not hasattr(request, "lab_user"):
        return
    
    user = request.lab_user
    project_id = data.get("project_id")
    file_path = data.get("file_path")
    
    if not lab.project_can_edit(project_id, user["id"]):
        return
    
    project = lab.project_get_by_id(project_id)
    if not project:
        return
    
    project_room = f"project_{project['id']}"
    socketio.emit("lab_file_changed", {
        "file_path": file_path,
        "modified_by": user["username"],
        "timestamp": time.time()
    }, to=project_room, include_self=False)


# ──────────────────────────────────────────────────────────────────────────────
# Deployment & Container Lifecycle
# ──────────────────────────────────────────────────────────────────────────────

@socketio.on("lab_deploy_project")
def handle_deploy_project(data):
    """
    Start/restart a project's Docker container.
    """
    sid = request.sid
    app_log.info(f"[lab] Deploy requested for project_id={data.get('project_id')} from {sid}")
    
    # Check if user is authenticated
    if sid not in authenticated_users:
        app_log.error(f"[lab] Deploy rejected - user not authenticated for {sid}")
        emit("error", {"message": "Not authenticated"})
        return
    
    user = authenticated_users[sid]
    project_id = data.get("project_id")
    
    project = lab.project_get_by_id(project_id)
    if not project:
        app_log.error(f"[lab] Deploy rejected - project {project_id} not found")
        emit("error", {"message": "Project not found"})
        return
    
    if not lab.project_can_edit(project_id, user["id"]):
        app_log.error(f"[lab] Deploy rejected - user {user['id']} cannot edit {project_id}")
        emit("error", {"message": "Access denied"})
        return
    
    app_log.info(f"[lab] Deploy starting for {project['slug']} ({project_id})")
    
    # Check resource capacity before deploying
    can_deploy, reason = lab.can_deploy_project(project)
    if not can_deploy:
        project_room = f"project_{project['id']}"
        app_log.warning(f"[lab] Deployment rejected for {project['slug']}: {reason}")
        socketio.emit("lab_deployment_failed", {
            "message": f"Cannot deploy: {reason}"
        }, to=project_room)
        return
    
    # Stop existing container if running
    if project.get("docker_container_id"):
        app_log.info(f"[lab] Stopping existing container {project['docker_container_id'][:12]}")
        lab.docker_container_stop(project["docker_container_id"])
    
    # Start new container
    app_log.info(f"[lab] Starting new container for {project['slug']}")
    container_id = lab.docker_container_start(project)
    
    project_room = f"project_{project['id']}"
    app_log.info(f"[lab] Container operation completed. Room: {project_room}, ContainerID: {container_id if container_id else 'None'}")
    
    if not container_id:
        app_log.error(f"[lab] Failed to start container for {project['slug']}")
        app_log.info(f"[lab] Emitting lab_deployment_failed to room {project_room}")
        socketio.emit("lab_deployment_failed", {
            "message": "Failed to start container"
        }, to=project_room)
    else:
        app_log.info(f"[lab] Deployed project {project_id} ({project['slug']}) - container {container_id[:12]}")
        app_log.info(f"[lab] Emitting lab_deployment_success to room {project_room}")
        socketio.emit("lab_deployment_success", {
            "container_id": container_id[:12],
            "message": "Container started"
        }, to=project_room)
        
        app_log.info(f"[lab] Emitted lab_deployment_success to room {project_room} with container {container_id[:12]}")


@socketio.on("lab_get_logs")
def handle_get_logs(data):
    """Get Docker container logs."""
    sid = request.sid
    
    # Check if user is authenticated
    if sid not in authenticated_users:
        emit("error", {"message": "Not authenticated"})
        return
    
    user = authenticated_users[sid]
    project_id = data.get("project_id")
    tail = data.get("tail", 100)
    
    project = lab.project_get_by_id(project_id)
    if not project:
        emit("error", {"message": "Project not found"})
        return
    
    if not lab.project_can_edit(project_id, user["id"]):
        emit("error", {"message": "Access denied"})
        return
    
    if not project.get("docker_container_id"):
        emit("lab_logs", {"logs": "Container not running"})
        return
    
    logs = lab.docker_container_get_logs(project["docker_container_id"], tail=tail)
    emit("lab_logs", {"logs": logs})
