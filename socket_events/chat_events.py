from glob_vars import *
from socketio_instance import socketio
from flask_socketio import emit, join_room
from flask import request
import functions as f

active_sessions: dict[str, dict] = {}
message_ownership: dict[int, str] = {}


def _get_active_usernames() -> set[str]:
    return {v["username"] for v in active_sessions.values()}


def _online_count() -> int:
    return len(active_sessions)


@socketio.on("join_chat")
def handle_join(data):
    sid = request.sid
    ip  = request.remote_addr
    username = (data.get("username") or "").strip()

    if not username:
        emit("join_ack", {"success": False, "error": "Username cannot be empty."})
        return
    if len(username) > 24:
        emit("join_ack", {"success": False, "error": "Username too long (max 24 chars)."})
        return
    if f.check_profanity(username):
        emit("join_ack", {"success": False, "error": "Username contains disallowed words."})
        return
    if username in _get_active_usernames():
        emit("join_ack", {"success": False, "error": "Username already taken."})
        return

    active_sessions[sid] = {"username": username, "ip": ip}
    join_room("chat")

    emit("join_ack", {
        "success":      True,
        "username":     username,
        "online_count": _online_count(),
    })

    history = f.get_recent_messages(CHAT_HISTORY_ON_JOIN)
    emit("chat_history", {"messages": history})

    emit("user_joined", {
        "username":     username,
        "online_count": _online_count(),
    }, to="chat", include_self=False)

    app_log.info(f"[chat] {username} ({ip}) joined. Online: {_online_count()}")


@socketio.on("send_message")
def handle_message(data):
    sid = request.sid
    ip  = request.remote_addr

    if sid not in active_sessions:
        emit("error", {"message": "You must set a username before chatting."})
        return

    username    = active_sessions[sid]["username"]
    message     = (data.get("message") or "").strip()
    reply_to_id = data.get("reply_to_id")

    if not message:
        return
    if len(message) > CHAT_MAX_CHARS:
        emit("error", {"message": f"Message too long (max {CHAT_MAX_CHARS} chars)."})
        return
    if f.is_rate_limited(ip):
        emit("error", {"message": f"Slow down — max {CHAT_RATE_LIMIT} messages per {CHAT_RATE_WINDOW}s."})
        return
    if f.check_profanity(message):
        emit("error", {"message": "Message contains disallowed words."})
        return

    if reply_to_id is not None:
        try:
            reply_to_id = int(reply_to_id)
        except (TypeError, ValueError):
            reply_to_id = None

    msg = f.save_chat_message(username, ip, message, reply_to_id=reply_to_id)
    message_ownership[msg["id"]] = sid
    socketio.emit("new_message", msg, to="chat")
    access_log.info(f"[chat] {username} ({ip}): {message}")


@socketio.on("edit_message")
def handle_edit(data):
    sid = request.sid
    if sid not in active_sessions:
        emit("error", {"message": "Not in chat."})
        return
    try:
        msg_id = int(data.get("id"))
    except (TypeError, ValueError):
        emit("error", {"message": "Invalid message ID."})
        return

    new_text = (data.get("new_text") or "").strip()

    if message_ownership.get(msg_id) != sid:
        emit("error", {"message": "You can only edit your own messages from this session."})
        return
    if not new_text:
        emit("error", {"message": "Edited message cannot be empty."})
        return
    if len(new_text) > CHAT_MAX_CHARS:
        emit("error", {"message": f"Message too long (max {CHAT_MAX_CHARS} chars)."})
        return
    if f.check_profanity(new_text):
        emit("error", {"message": "Edited message contains disallowed words."})
        return

    f.edit_message(msg_id, new_text)
    socketio.emit("message_edited", {"id": msg_id, "new_text": new_text}, to="chat")


@socketio.on("delete_message")
def handle_delete(data):
    sid = request.sid
    if sid not in active_sessions:
        emit("error", {"message": "Not in chat."})
        return
    try:
        msg_id = int(data.get("id"))
    except (TypeError, ValueError):
        emit("error", {"message": "Invalid message ID."})
        return

    if message_ownership.get(msg_id) != sid:
        emit("error", {"message": "You can only delete your own messages from this session."})
        return

    f.delete_message(msg_id)
    message_ownership.pop(msg_id, None)
    socketio.emit("message_deleted", {"id": msg_id}, to="chat")


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    if sid in active_sessions:
        username = active_sessions.pop(sid)["username"]
        dead_ids = [k for k, v in message_ownership.items() if v == sid]
        for k in dead_ids:
            message_ownership.pop(k, None)
        emit("user_left", {
            "username":     username,
            "online_count": _online_count(),
        }, to="chat")
        app_log.info(f"[chat] {username} disconnected. Online: {_online_count()}")