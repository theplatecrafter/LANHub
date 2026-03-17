from glob_vars import *
from socketio_instance import socketio
from flask_socketio import emit, join_room, leave_room
from flask import request
import functions as f

# In-memory session state
# { sid: { "username": str, "ip": str } }
active_sessions: dict[str, dict] = {}

def _get_active_usernames() -> set[str]:
    return {v["username"] for v in active_sessions.values()}


@socketio.on("join_chat")
def handle_join(data):
    sid = request.sid
    ip  = request.remote_addr
    username = (data.get("username") or "").strip()

    # --- Validate ---
    if not username:
        emit("join_ack", {"success": False, "error": "Username cannot be empty."})
        return
    if len(username) > 24:
        emit("join_ack", {"success": False, "error": "Username too long (max 24 chars)."})
        return
    if username in _get_active_usernames():
        emit("join_ack", {"success": False, "error": "Username already taken."})
        return

    # --- Register ---
    active_sessions[sid] = {"username": username, "ip": ip}
    join_room("chat")

    # --- Confirm to joining client ---
    emit("join_ack", {"success": True, "username": username})

    # --- Send history only to this client ---
    history = f.get_recent_messages(CHAT_HISTORY_ON_JOIN)
    emit("chat_history", {"messages": history})

    # --- Announce to everyone else ---
    emit("user_joined", {"username": username}, to="chat", include_self=False)
    app_log.info(f"[chat] {username} ({ip}) joined.")


@socketio.on("send_message")
def handle_message(data):
    sid = request.sid
    ip  = request.remote_addr

    if sid not in active_sessions:
        emit("error", {"message": "You must set a username before chatting."})
        return

    username = active_sessions[sid]["username"]
    message  = (data.get("message") or "").strip()

    # --- Validate ---
    if not message:
        return
    if len(message) > CHAT_MAX_CHARS:
        emit("error", {"message": f"Message too long (max {CHAT_MAX_CHARS} chars)."})
        return
    if f.is_rate_limited(ip):
        emit("error", {"message": f"Slow down — max {CHAT_RATE_LIMIT} messages per {CHAT_RATE_WINDOW}s."})
        return

    # --- Save + broadcast ---
    msg = f.save_chat_message(username, ip, message)
    socketio.emit("new_message", msg, to="chat")
    access_log.info(f"[chat] {username} ({ip}): {message}")


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    if sid in active_sessions:
        username = active_sessions.pop(sid)["username"]
        emit("user_left", {"username": username}, to="chat")
        app_log.info(f"[chat] {username} disconnected.")