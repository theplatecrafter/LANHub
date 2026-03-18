"""
socket_events/channels_events.py

Handles real-time events for the channels feature.
Each channel maps to a Socket.IO room named "channel_{id}".

Session structure:
  ch_sessions[sid] = {
      "username": str,
      "ip": str,
      "channels": set[int],   # channel IDs this sid has joined
  }

Message ownership (for edit/delete):
  ch_msg_ownership[msg_id] = sid
"""

from glob_vars import *
from socketio_instance import socketio
from flask_socketio import emit, join_room, leave_room
from flask import request
import functions as f

ch_sessions: dict[str, dict]    = {}
ch_msg_ownership: dict[int, str] = {}


def _room(channel_id: int) -> str:
    return f"channel_{channel_id}"


def _online(channel_id: int) -> int:
    return sum(
        1 for info in ch_sessions.values()
        if channel_id in info.get("channels", set())
    )


# ── Username (shared across all channels in this session) ──────────────────────
@socketio.on("ch_set_username")
def handle_ch_set_username(data):
    sid = request.sid
    ip  = request.remote_addr
    username = (data.get("username") or "").strip()

    if not username:
        emit("ch_username_ack", {"ok": False, "error": "Username cannot be empty."})
        return
    if len(username) > 24:
        emit("ch_username_ack", {"ok": False, "error": "Username too long (max 24 chars)."})
        return
    if f.check_profanity(username):
        emit("ch_username_ack", {"ok": False, "error": "Username contains disallowed words."})
        return

    # Check uniqueness across all channel sessions
    taken = {v["username"] for v in ch_sessions.values() if v.get("username")}
    if username in taken and ch_sessions.get(sid, {}).get("username") != username:
        emit("ch_username_ack", {"ok": False, "error": "Username already taken."})
        return

    if sid not in ch_sessions:
        ch_sessions[sid] = {"username": username, "ip": ip, "channels": set()}
    else:
        ch_sessions[sid]["username"] = username
        ch_sessions[sid]["ip"]       = ip

    emit("ch_username_ack", {"ok": True, "username": username})
    app_log.info(f"[channels] {username} ({ip}) set username")


# ── Join a channel ──────────────────────────────────────────────────────────────
@socketio.on("ch_join")
def handle_ch_join(data):
    sid = request.sid

    if sid not in ch_sessions or not ch_sessions[sid].get("username"):
        emit("ch_join_ack", {"ok": False, "error": "Set a username first."})
        return

    try:
        channel_id = int(data.get("channel_id"))
    except (TypeError, ValueError):
        emit("ch_join_ack", {"ok": False, "error": "Invalid channel ID."})
        return

    ch = f.get_channel_by_id(channel_id)
    if not ch:
        emit("ch_join_ack", {"ok": False, "error": "Channel not found."})
        return

    username = ch_sessions[sid]["username"]
    ch_sessions[sid]["channels"].add(channel_id)
    join_room(_room(channel_id))

    # Send history to just this client
    history = f.get_channel_messages(channel_id, CHAT_HISTORY_ON_JOIN)
    emit("ch_history", {
        "channel_id": channel_id,
        "messages":   history,
        "has_more":   len(history) == CHAT_HISTORY_ON_JOIN,
    })

    ch_safe = {k: v for k, v in ch.items() if k != "password_hash"}
    emit("ch_join_ack", {
        "ok":          True,
        "channel":     ch_safe,
        "online_count": _online(channel_id),
    })

    # Notify others
    emit("ch_user_joined", {
        "channel_id":   channel_id,
        "username":     username,
        "online_count": _online(channel_id),
    }, to=_room(channel_id), include_self=False)

    app_log.info(f"[channels] {username} joined channel #{channel_id} '{ch['title']}'")


# ── Leave a channel ─────────────────────────────────────────────────────────────
@socketio.on("ch_leave")
def handle_ch_leave(data):
    sid = request.sid
    try:
        channel_id = int(data.get("channel_id"))
    except (TypeError, ValueError):
        return

    _leave_channel(sid, channel_id)


def _leave_channel(sid: str, channel_id: int) -> None:
    info = ch_sessions.get(sid)
    if not info:
        return
    info["channels"].discard(channel_id)
    leave_room(_room(channel_id))

    username = info.get("username", "")
    socketio.emit("ch_user_left", {
        "channel_id":   channel_id,
        "username":     username,
        "online_count": _online(channel_id),
    }, to=_room(channel_id))

    app_log.info(f"[channels] {username} left channel #{channel_id}")


# ── Send message ────────────────────────────────────────────────────────────────
@socketio.on("ch_send_message")
def handle_ch_send(data):
    sid = request.sid
    ip  = request.remote_addr

    if sid not in ch_sessions or not ch_sessions[sid].get("username"):
        emit("ch_error", {"message": "Set a username first."})
        return

    try:
        channel_id = int(data.get("channel_id"))
    except (TypeError, ValueError):
        return

    if channel_id not in ch_sessions[sid]["channels"]:
        emit("ch_error", {"message": "Join the channel first."})
        return

    username    = ch_sessions[sid]["username"]
    message     = (data.get("message") or "").strip()
    reply_to_id = data.get("reply_to_id")

    if not message:
        return
    if len(message) > CHAT_MAX_CHARS:
        emit("ch_error", {"message": f"Message too long (max {CHAT_MAX_CHARS} chars)."})
        return
    if f.is_rate_limited(ip):
        emit("ch_error", {"message": f"Slow down — max {CHAT_RATE_LIMIT} messages per {CHAT_RATE_WINDOW}s."})
        return
    SKIP_PROFANITY = {"display", "youtube", "flip", "roll"}
    ALLOWED_TYPES  = {"text", "me", "display", "youtube", "flip", "roll"}
    msg_type = data.get("msg_type", "text")
    if msg_type not in ALLOWED_TYPES:
        msg_type = "text"

    if msg_type not in SKIP_PROFANITY and f.check_profanity(message):
        emit("ch_error", {"message": "Message contains disallowed words."})
        return

    msg = f.save_channel_message(channel_id, username, ip, message, reply_to_id, msg_type=msg_type)
    ch_msg_ownership[msg["id"]] = sid

    socketio.emit("ch_new_message", msg, to=_room(channel_id))
    access_log.info(f"[channels] #{channel_id} {username}: {message[:60]}")


# ── Edit message ────────────────────────────────────────────────────────────────
@socketio.on("ch_edit_message")
def handle_ch_edit(data):
    sid = request.sid
    if sid not in ch_sessions:
        return

    try:
        msg_id = int(data.get("id"))
    except (TypeError, ValueError):
        return

    new_text = (data.get("new_text") or "").strip()
    if ch_msg_ownership.get(msg_id) != sid:
        emit("ch_error", {"message": "You can only edit your own messages."})
        return
    if not new_text:
        emit("ch_error", {"message": "Message cannot be empty."})
        return
    if len(new_text) > CHAT_MAX_CHARS:
        emit("ch_error", {"message": f"Too long (max {CHAT_MAX_CHARS} chars)."})
        return
    if f.check_profanity(new_text):
        emit("ch_error", {"message": "Edited message contains disallowed words."})
        return

    channel_id = int(data.get("channel_id"))
    f.edit_channel_message(msg_id, new_text)
    socketio.emit("ch_message_edited", {
        "id": msg_id, "channel_id": channel_id, "new_text": new_text
    }, to=_room(channel_id))


# ── Delete message ──────────────────────────────────────────────────────────────
@socketio.on("ch_delete_message")
def handle_ch_delete(data):
    sid = request.sid
    if sid not in ch_sessions:
        return

    try:
        msg_id     = int(data.get("id"))
        channel_id = int(data.get("channel_id"))
    except (TypeError, ValueError):
        return

    if ch_msg_ownership.get(msg_id) != sid:
        emit("ch_error", {"message": "You can only delete your own messages."})
        return

    f.delete_channel_message(msg_id)
    ch_msg_ownership.pop(msg_id, None)
    socketio.emit("ch_message_deleted", {
        "id": msg_id, "channel_id": channel_id
    }, to=_room(channel_id))

@socketio.on("ch_report_message")
def handle_ch_report(data):
    sid = request.sid
    ip  = request.remote_addr
    if sid not in ch_sessions:
        return
    try:
        msg_id = int(data.get("id"))
    except (TypeError, ValueError):
        return

    reported_username = str(data.get("username", ""))[:64]
    message_text      = str(data.get("message",  ""))[:500]
    reason            = str(data.get("reason",   ""))[:300]

    # Try to find the reported user's IP from active channel sessions
    reported_ip = ""
    for info in ch_sessions.values():
        if info.get("username") == reported_username:
            reported_ip = info.get("ip", "")
            break

    rid = f.create_report(
        reporter_ip=ip,
        reported_username=reported_username,
        reported_ip=reported_ip,
        message_id=msg_id,
        message_text=message_text,
        reason=reason,
        source="channels",
    )
    app_log.info(f"[channels] Report #{rid}: {ip} reported msg #{msg_id} by '{reported_username}'")

# ── Load older messages ─────────────────────────────────────────────────────────
@socketio.on("ch_load_older")
def handle_ch_load_older(data):
    sid = request.sid
    if sid not in ch_sessions:
        return

    try:
        channel_id = int(data.get("channel_id"))
        before_id  = int(data.get("before_id"))
    except (TypeError, ValueError):
        return

    messages = f.get_channel_messages_before(channel_id, before_id, CHAT_HISTORY_ON_JOIN)
    emit("ch_older_messages", {
        "channel_id": channel_id,
        "messages":   messages,
        "has_more":   len(messages) == CHAT_HISTORY_ON_JOIN,
    })


# ── Disconnect ──────────────────────────────────────────────────────────────────
@socketio.on("disconnect")
def handle_disconnect_all():
    sid = request.sid

    # ── Chat cleanup ───────────────────────────────────────
    from socket_events.chat_events import _cleanup_chat
    _cleanup_chat(sid)

    # ── Console cleanup ────────────────────────────────────
    from socket_events.console_events import _cleanup as _cleanup_console
    _cleanup_console(sid)
    
    # ── Chess cleanup ──────────────────────────────────────
    from socket_events.chess_events import _cleanup_chess
    _cleanup_chess(sid)
    
    # Uno Cleanup
    from socket_events.uno_events import _cleanup_uno
    _cleanup_uno(sid)

    # ── Channels cleanup ───────────────────────────────────
    info = ch_sessions.pop(sid, None)
    if info:
        username = info.get("username", "")
        for channel_id in list(info.get("channels", set())):
            socketio.emit("ch_user_left", {
                "channel_id":   channel_id,
                "username":     username,
                "online_count": _online(channel_id),
            }, to=_room(channel_id))
        dead = [k for k, v in ch_msg_ownership.items() if v == sid]
        for k in dead:
            ch_msg_ownership.pop(k, None)
        if username:
            app_log.info(f"[channels] {username} disconnected.")