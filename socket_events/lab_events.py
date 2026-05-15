"""socket_events/lab_events.py - HansHub Lab real-time event handlers."""

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
    Emits progress events to keep user informed during deployment.
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
    project_room = f"project_{project['id']}"
    
    # Check resource capacity before deploying
    can_deploy, reason = lab.can_deploy_project(project)
    if not can_deploy:
        app_log.warning(f"[lab] Deployment rejected for {project['slug']}: {reason}")
        socketio.emit("lab_deployment_failed", {
            "message": f"Cannot deploy: {reason}"
        }, to=project_room)
        return
    
    # Emit progress: Stopping old container
    if project.get("docker_container_id"):
        socketio.emit("lab_deployment_progress", {
            "message": "Stopping previous container (this may take a few seconds)..."
        }, to=project_room)
        app_log.info(f"[lab] Stopping existing container {project['docker_container_id'][:12]}")
        lab.docker_container_stop(project["docker_container_id"])
        socketio.emit("lab_deployment_progress", {
            "message": "Previous container stopped successfully"
        }, to=project_room)
    
    # Emit progress: Starting new container
    socketio.emit("lab_deployment_progress", {
        "message": "Pulling Docker image and starting new container..."
    }, to=project_room)
    app_log.info(f"[lab] Starting new container for {project['slug']}")
    
    container_id = lab.docker_container_start(project)
    
    app_log.info(f"[lab] Container operation completed. Room: {project_room}, ContainerID: {container_id if container_id else 'None'}")
    
    if not container_id:
        app_log.error(f"[lab] Failed to start container for {project['slug']}")
        app_log.info(f"[lab] Emitting lab_deployment_failed to room {project_room}")
        socketio.emit("lab_deployment_failed", {
            "message": "Failed to start container. Check logs for details."
        }, to=project_room)
    else:
        # Emit progress: Container is running
        socketio.emit("lab_deployment_progress", {
            "message": "Container started successfully (ID: {})".format(container_id[:12])
        }, to=project_room)
        
        # Emit progress: Mounting filesystem
        socketio.emit("lab_deployment_progress", {
            "message": "Mounting project filesystem into container..."
        }, to=project_room)
        
        # Emit progress: Initializing code-server
        socketio.emit("lab_deployment_progress", {
            "message": "Initializing code-server IDE (this may take 10-15 seconds)..."
        }, to=project_room)
        
        # Emit progress: Waiting for socket
        socketio.emit("lab_deployment_progress", {
            "message": "Waiting for IDE to become ready..."
        }, to=project_room)
        
        app_log.info(f"[lab] Deployed project {project_id} ({project['slug']}) - container {container_id[:12]}")
        app_log.info(f"[lab] Emitting lab_deployment_success to room {project_room}")
        
        socketio.emit("lab_deployment_success", {
            "container_id": container_id[:12],
            "message": "Container started and IDE is ready!"
        }, to=project_room)
        
        app_log.info(f"[lab] Emitted lab_deployment_success to room {project_room} with container {container_id[:12]}")


@socketio.on("lab_stop_project")
def handle_stop_project(data):
    """
    Stop a project's Docker container.
    Emits status events to keep user informed during stopping.
    """
    sid = request.sid
    app_log.info(f"[lab] Stop requested for project_id={data.get('project_id')} from {sid}")
    
    # Check if user is authenticated
    if sid not in authenticated_users:
        app_log.error(f"[lab] Stop rejected - user not authenticated for {sid}")
        emit("error", {"message": "Not authenticated"})
        return
    
    user = authenticated_users[sid]
    project_id = data.get("project_id")
    
    project = lab.project_get_by_id(project_id)
    if not project:
        app_log.error(f"[lab] Stop rejected - project {project_id} not found")
        emit("error", {"message": "Project not found"})
        return
    
    if not lab.project_can_edit(project_id, user["id"]):
        app_log.error(f"[lab] Stop rejected - user {user['id']} cannot edit {project_id}")
        emit("error", {"message": "Access denied"})
        return
    
    # Check if container exists
    if not project.get("docker_container_id"):
        app_log.warning(f"[lab] Stop requested but no container for {project['slug']}")
        socketio.emit("lab_stop_failed", {
            "message": "Container not running"
        }, to=f"project_{project['id']}")
        return
    
    app_log.info(f"[lab] Stopping container {project['docker_container_id'][:12]} for {project['slug']}")
    project_room = f"project_{project['id']}"
    
    # Emit progress: Stopping container
    socketio.emit("lab_stop_progress", {
        "message": f"Stopping container {project['docker_container_id'][:12]}..."
    }, to=project_room)
    
    try:
        success = lab.docker_container_stop(project["docker_container_id"], project_id)
        
        if success:
            # Update database: Mark project as OFFLINE and clear container ID
            app_log.info(f"[lab] Updating project {project['slug']} status to OFFLINE")
            lab.project_update(project_id, {"status": "OFFLINE", "docker_container_id": None})
            
            # Emit success
            app_log.info(f"[lab] Container stopped successfully for {project['slug']}")
            socketio.emit("lab_stop_success", {
                "message": "Container stopped successfully"
            }, to=project_room)
        else:
            app_log.error(f"[lab] Failed to stop container for {project['slug']}")
            socketio.emit("lab_stop_failed", {
                "message": "Failed to stop container"
            }, to=project_room)
    except Exception as e:
        app_log.error(f"[lab] Error stopping container: {e}")
        socketio.emit("lab_stop_failed", {
            "message": f"Error stopping container: {str(e)}"
        }, to=project_room)


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
        emit("lab_logs", {"logs": "Container not running. Deploy the project first."})
        return
    
    app_log.info(f"[lab] Retrieving logs for container {project['docker_container_id'][:12]}")
    logs = lab.docker_container_get_logs(project["docker_container_id"], tail=tail)
    app_log.info(f"[lab] Logs retrieved successfully ({len(logs)} bytes)")
    emit("lab_logs", {"logs": logs})


# Secrets Management Events

@socketio.on("lab_set_secret")
def handle_lab_set_secret(data):
    """Store or update an environment secret for a lab project."""
    project_id = data.get("project_id")
    secret_key = data.get("secret_key")
    secret_value = data.get("secret_value")
    
    if not all([project_id, secret_key, secret_value]):
        emit("lab_error", {"error": "Missing required fields: project_id, secret_key, secret_value"})
        return
    
    try:
        lab.set_project_secret(project_id, secret_key, secret_value)
        app_log.info(f"[lab] Secret '{secret_key}' set for project {project_id}")
        emit("lab_secret_set", {"success": True, "secret_key": secret_key})
    except Exception as e:
        app_log.error(f"[lab] Error setting secret: {e}")
        emit("lab_error", {"error": str(e)})


@socketio.on("lab_delete_secret")
def handle_lab_delete_secret(data):
    """Delete an environment secret for a lab project."""
    project_id = data.get("project_id")
    secret_key = data.get("secret_key")
    
    if not all([project_id, secret_key]):
        emit("lab_error", {"error": "Missing required fields: project_id, secret_key"})
        return
    
    try:
        lab.delete_project_secret(project_id, secret_key)
        app_log.info(f"[lab] Secret '{secret_key}' deleted for project {project_id}")
        emit("lab_secret_deleted", {"success": True, "secret_key": secret_key})
    except Exception as e:
        app_log.error(f"[lab] Error deleting secret: {e}")
        emit("lab_error", {"error": str(e)})


@socketio.on("lab_get_secrets")
def handle_lab_get_secrets(data):
    """Retrieve the list of secret keys (not values) for a lab project."""
    project_id = data.get("project_id")
    
    if not project_id:
        emit("lab_error", {"error": "Missing required field: project_id"})
        return
    
    try:
        secret_keys = lab.get_project_secret_keys(project_id)
        app_log.info(f"[lab] Retrieved {len(secret_keys)} secret keys for project {project_id}")
        emit("lab_secrets", {"secret_keys": secret_keys})
    except Exception as e:
        app_log.error(f"[lab] Error retrieving secrets: {e}")
        emit("lab_error", {"error": str(e)})


# Project Cloning Events

@socketio.on("lab_clone_project")
def handle_lab_clone_project(data):
    """Clone a public project for the authenticated user."""
    sid = request.sid
    
    # Check if user is authenticated
    if sid not in authenticated_users:
        emit("lab_error", {"error": "Not authenticated"})
        return
    
    user = authenticated_users[sid]
    source_project_id = data.get("project_id")
    
    if not source_project_id:
        emit("lab_error", {"error": "Missing project_id"})
        return
    
    try:
        # Get source project to verify it's public
        source_project = lab.project_get_by_id(source_project_id)
        if not source_project:
            emit("lab_error", {"error": "Project not found"})
            return
        
        if source_project["visibility"] != "public":
            emit("lab_error", {"error": "Can only clone public projects"})
            return
        
        # Clone the project
        new_project = lab.project_clone(source_project_id, user["id"])
        if not new_project:
            emit("lab_error", {"error": "Failed to clone project"})
            return
        
        app_log.info(f"[lab] User {user['username']} cloned project {source_project_id}")
        emit("lab_project_cloned", {
            "success": True,
            "new_project": {
                "id": new_project["id"],
                "slug": new_project["slug"],
                "title": new_project["title"]
            }
        })
    except Exception as e:
        app_log.error(f"[lab] Error cloning project: {e}")
        emit("lab_error", {"error": str(e)})


# Project Starring Events

@socketio.on("lab_star_project")
def handle_lab_star_project(data):
    """Add a star to a project."""
    sid = request.sid
    
    # Check if user is authenticated
    if sid not in authenticated_users:
        emit("lab_error", {"error": "Not authenticated"})
        return
    
    user = authenticated_users[sid]
    project_id = data.get("project_id")
    
    if not project_id:
        emit("lab_error", {"error": "Missing project_id"})
        return
    
    try:
        # Check project exists and is public
        project = lab.project_get_by_id(project_id)
        if not project:
            emit("lab_error", {"error": "Project not found"})
            return
        
        if project["visibility"] != "public":
            emit("lab_error", {"error": "Can only star public projects"})
            return
        
        # Add star
        success = lab.project_add_star(project_id, user["id"])
        if not success:
            emit("lab_error", {"error": "Already starred or error occurred"})
            return
        
        # Get updated star count
        star_count = lab.project_get_star_count(project_id)
        app_log.info(f"[lab] User {user['username']} starred project {project_id}")
        emit("lab_project_starred", {
            "success": True,
            "project_id": project_id,
            "star_count": star_count
        })
    except Exception as e:
        app_log.error(f"[lab] Error starring project: {e}")
        emit("lab_error", {"error": str(e)})


@socketio.on("lab_unstar_project")
def handle_lab_unstar_project(data):
    """Remove a star from a project."""
    sid = request.sid
    
    # Check if user is authenticated
    if sid not in authenticated_users:
        emit("lab_error", {"error": "Not authenticated"})
        return
    
    user = authenticated_users[sid]
    project_id = data.get("project_id")
    
    if not project_id:
        emit("lab_error", {"error": "Missing project_id"})
        return
    
    try:
        # Remove star
        success = lab.project_remove_star(project_id, user["id"])
        if not success:
            emit("lab_error", {"error": "Not starred by user or error occurred"})
            return
        
        # Get updated star count
        star_count = lab.project_get_star_count(project_id)
        app_log.info(f"[lab] User {user['username']} unstarred project {project_id}")
        emit("lab_project_unstarred", {
            "success": True,
            "project_id": project_id,
            "star_count": star_count
        })
    except Exception as e:
        app_log.error(f"[lab] Error unstarring project: {e}")
        emit("lab_error", {"error": str(e)})


@socketio.on("lab_get_star_info")
def handle_lab_get_star_info(data):
    """Get star count and user's star status for a project."""
    sid = request.sid
    project_id = data.get("project_id")
    
    if not project_id:
        emit("lab_error", {"error": "Missing project_id"})
        return
    
    try:
        star_count = lab.project_get_star_count(project_id)
        user_has_starred = False
        
        if sid in authenticated_users:
            user = authenticated_users[sid]
            user_has_starred = lab.project_has_star(project_id, user["id"])
        
        emit("lab_star_info", {
            "project_id": project_id,
            "star_count": star_count,
            "user_has_starred": user_has_starred
        })
    except Exception as e:
        app_log.error(f"[lab] Error getting star info: {e}")
        emit("lab_error", {"error": str(e)})
