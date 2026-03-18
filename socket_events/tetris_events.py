"""
socket_events/tetris_events.py

Handles multiplayer Tetris matchmaking and in-game relay.
All game logic runs client-side; the server only:
  - Maintains a lobby of available players
  - Queues players for random matching
  - Creates game rooms and forwards garbage / board snapshots
  - Announces game-over results
"""

import uuid
from flask import request
from flask_socketio import emit, join_room, leave_room
from socketio_instance import socketio
from glob_vars import app_log, error_log

# ── State ─────────────────────────────────────────────────────────────────────
# { sid: { username, status: 'idle'|'queue'|'ingame', room_id } }
tetris_sessions: dict[str, dict] = {}

# Random-match queue: list of sids
tetris_queue: list[str] = []

# { room_id: { players: [sid, sid], ready: set, started: bool } }
tetris_rooms: dict[str, dict] = {}


def _name(sid: str) -> str:
    return tetris_sessions.get(sid, {}).get("username", "?")


def _idle_players(exclude_sid: str) -> list[str]:
    return [
        info["username"]
        for s, info in tetris_sessions.items()
        if s != exclude_sid and info.get("status") == "idle"
    ]


# ── Register / unregister ─────────────────────────────────────────────────────
@socketio.on("tetris_login")
def handle_tetris_login(data):
    sid      = request.sid
    username = (data.get("username") or "").strip()[:24]

    if not username:
        emit("tetris_login_ack", {"ok": False, "error": "Username required."})
        return

    # Check uniqueness among active tetris sessions
    taken = {v["username"] for v in tetris_sessions.values()}
    if username in taken and tetris_sessions.get(sid, {}).get("username") != username:
        emit("tetris_login_ack", {"ok": False, "error": "Username taken."})
        return

    tetris_sessions[sid] = {"username": username, "status": "idle", "room_id": None}
    emit("tetris_login_ack", {"ok": True, "username": username})
    app_log.info(f"[tetris] {username} logged in")

    # Broadcast updated idle list to everyone in lobby
    _broadcast_lobby()


@socketio.on("tetris_logout")
def handle_tetris_logout(_data=None):
    _cleanup(request.sid)


# ── Get available players ─────────────────────────────────────────────────────
@socketio.on("tetris_get_lobby")
def handle_get_lobby(_data=None):
    emit("tetris_lobby", {"players": _idle_players(request.sid)})


# ── Random queue ──────────────────────────────────────────────────────────────
@socketio.on("tetris_queue_join")
def handle_queue_join(_data=None):
    sid = request.sid
    if sid not in tetris_sessions:
        return

    # Already in queue?
    if sid in tetris_queue:
        return

    tetris_queue.append(sid)
    tetris_sessions[sid]["status"] = "queue"
    emit("tetris_queue_status", {"status": "waiting", "position": tetris_queue.index(sid) + 1})
    app_log.info(f"[tetris] {_name(sid)} joined queue (queue size={len(tetris_queue)})")

    # Try to match
    if len(tetris_queue) >= 2:
        sid_a = tetris_queue.pop(0)
        sid_b = tetris_queue.pop(0)
        _create_room(sid_a, sid_b)


@socketio.on("tetris_queue_leave")
def handle_queue_leave(_data=None):
    sid = request.sid
    if sid in tetris_queue:
        tetris_queue.remove(sid)
    if sid in tetris_sessions:
        tetris_sessions[sid]["status"] = "idle"
    _broadcast_lobby()


# ── Direct challenge ──────────────────────────────────────────────────────────
@socketio.on("tetris_challenge")
def handle_challenge(data):
    sid      = request.sid
    target   = (data.get("target") or "").strip()
    target_sid = next(
        (s for s, info in tetris_sessions.items() if info["username"] == target),
        None
    )

    if not target_sid or tetris_sessions[target_sid]["status"] != "idle":
        emit("tetris_challenge_ack", {"ok": False, "error": f"{target} is not available."})
        return

    # Send challenge to target
    socketio.emit("tetris_incoming_challenge", {
        "from": _name(sid),
        "from_sid": sid,
    }, to=target_sid)

    emit("tetris_challenge_ack", {"ok": True, "target": target})
    app_log.info(f"[tetris] {_name(sid)} challenged {target}")


@socketio.on("tetris_challenge_response")
def handle_challenge_response(data):
    sid      = request.sid
    accept   = bool(data.get("accept"))
    from_sid = data.get("from_sid")

    if from_sid not in tetris_sessions:
        return

    if not accept:
        socketio.emit("tetris_challenge_declined", {
            "by": _name(sid)
        }, to=from_sid)
        return

    _create_room(from_sid, sid)


# ── In-game relay ─────────────────────────────────────────────────────────────
@socketio.on("tetris_ready")
def handle_ready(data):
    sid     = request.sid
    room_id = data.get("room_id")
    if room_id not in tetris_rooms:
        return

    room = tetris_rooms[room_id]
    room["ready"].add(sid)

    if len(room["ready"]) == 2 and not room["started"]:
        room["started"] = True
        socketio.emit("tetris_start", {"room_id": room_id}, to=room_id)
        app_log.info(f"[tetris] Room {room_id[:8]} started")


@socketio.on("tetris_garbage")
def handle_garbage(data):
    sid     = request.sid
    room_id = data.get("room_id")
    lines   = int(data.get("lines", 0))

    if room_id not in tetris_rooms or lines <= 0:
        return

    # Forward to opponent
    room = tetris_rooms[room_id]
    for p in room["players"]:
        if p != sid:
            socketio.emit("tetris_recv_garbage", {"lines": lines}, to=p)


@socketio.on("tetris_board_update")
def handle_board_update(data):
    sid     = request.sid
    room_id = data.get("room_id")
    board   = data.get("board")   # compact board representation

    if room_id not in tetris_rooms:
        return

    room = tetris_rooms[room_id]
    for p in room["players"]:
        if p != sid:
            socketio.emit("tetris_opponent_board", {"board": board}, to=p)


@socketio.on("tetris_game_over")
def handle_game_over(data):
    sid     = request.sid
    room_id = data.get("room_id")

    if room_id not in tetris_rooms:
        return

    room = tetris_rooms[room_id]
    loser = _name(sid)

    # Notify both players
    for p in room["players"]:
        won = (p != sid)
        socketio.emit("tetris_result", {
            "won":   won,
            "loser": loser,
        }, to=p)

    _teardown_room(room_id)
    app_log.info(f"[tetris] Room {room_id[:8]} over — {loser} lost")


# ── Helpers ───────────────────────────────────────────────────────────────────
def _create_room(sid_a: str, sid_b: str) -> str:
    room_id = uuid.uuid4().hex[:12]
    tetris_rooms[room_id] = {
        "players": [sid_a, sid_b],
        "ready":   set(),
        "started": False,
    }
    for sid in (sid_a, sid_b):
        tetris_sessions[sid]["status"]  = "ingame"
        tetris_sessions[sid]["room_id"] = room_id
        join_room(room_id, sid=sid)

    opponent_a = _name(sid_b)
    opponent_b = _name(sid_a)

    socketio.emit("tetris_matched", {
        "room_id":  room_id,
        "opponent": opponent_a,
    }, to=sid_a)
    socketio.emit("tetris_matched", {
        "room_id":  room_id,
        "opponent": opponent_b,
    }, to=sid_b)

    app_log.info(f"[tetris] Matched {_name(sid_a)} vs {_name(sid_b)} → room {room_id[:8]}")
    _broadcast_lobby()
    return room_id


def _teardown_room(room_id: str) -> None:
    room = tetris_rooms.pop(room_id, None)
    if not room:
        return
    for sid in room["players"]:
        if sid in tetris_sessions:
            tetris_sessions[sid]["status"]  = "idle"
            tetris_sessions[sid]["room_id"] = None
        try:
            leave_room(room_id, sid=sid)
        except Exception:
            pass
    _broadcast_lobby()


def _cleanup(sid: str) -> None:
    info = tetris_sessions.pop(sid, None)
    if not info:
        return

    if sid in tetris_queue:
        tetris_queue.remove(sid)

    room_id = info.get("room_id")
    if room_id and room_id in tetris_rooms:
        room = tetris_rooms[room_id]
        # Notify opponent that player disconnected
        for p in room["players"]:
            if p != sid:
                socketio.emit("tetris_opponent_disconnected", {}, to=p)
                if p in tetris_sessions:
                    tetris_sessions[p]["status"]  = "idle"
                    tetris_sessions[p]["room_id"] = None
        tetris_rooms.pop(room_id, None)

    _broadcast_lobby()
    app_log.info(f"[tetris] {info.get('username')} disconnected from tetris")


def _broadcast_lobby() -> None:
    """Push updated idle player list to all tetris clients."""
    for sid, info in tetris_sessions.items():
        others = _idle_players(sid)
        socketio.emit("tetris_lobby", {"players": others}, to=sid)


@socketio.on("disconnect")
def handle_tetris_disconnect():
    _cleanup(request.sid)