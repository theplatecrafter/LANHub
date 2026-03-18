# socket_events/geoguesser_events.py
"""
GeoGuesser multiplayer + singleplayer socket events.

The server only resolves a pano_id from coordinates (a fast metadata call).
The client loads the panorama directly from Google via the Maps Embed API iframe —
no image is ever downloaded or cached by the server.

Requires: pip install streetview
"""
import uuid, time, threading, random, math
from flask import request
from flask_socketio import emit
from socketio_instance import socketio
from glob_vars import app_log, error_log
import functions as f

# ── Try importing streetview ───────────────────────────────────────────────────
try:
    from streetview import search_panoramas as _search_panoramas
    _SV_OK = True
except ImportError:
    _search_panoramas = None
    _SV_OK = False
    error_log.warning("[geo] 'streetview' library not found. Run: pip install streetview")

# ── In-memory state ───────────────────────────────────────────────────────────
geo_sessions: dict[str, dict] = {}   # sid → {username, room_id}
geo_rooms:    dict[str, dict] = {}   # room_id → room

ROUND_ADVANCE_SECS   = 9
MAX_LOCATION_RETRIES = 50


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _point_in_polygon(lat: float, lng: float, polygon: list) -> bool:
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        if (yi > lng) != (yj > lng):
            if lat < (xj - xi) * (lng - yi) / (yj - yi + 1e-12) + xi:
                inside = not inside
        j = i
    return inside


def _random_polygon_point(polygon: list):
    lats = [p[0] for p in polygon]
    lngs = [p[1] for p in polygon]
    mn_lat, mx_lat = min(lats), max(lats)
    mn_lng, mx_lng = min(lngs), max(lngs)
    for _ in range(2000):
        lat = random.uniform(mn_lat, mx_lat)
        lng = random.uniform(mn_lng, mx_lng)
        if _point_in_polygon(lat, lng, polygon):
            return lat, lng
    return None


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + (
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def geo_score(distance_km: float) -> int:
    if distance_km < 0.025:
        return 5000
    return round(max(0, 5000 * math.exp(-distance_km / 2000)))


# ── Panorama location lookup ───────────────────────────────────────────────────

def _extract_pano_info(result, default_lat: float, default_lng: float):
    if isinstance(result, dict):
        pano_id  = result.get("pano_id") or result.get("panoid") or result.get("id", "")
        pano_lat = float(result.get("lat", default_lat))
        pano_lng = float(result.get("lon", result.get("lng", default_lng)))
    else:
        pano_id  = str(getattr(result, "pano_id", "") or getattr(result, "panoid", ""))
        pano_lat = float(getattr(result, "lat", default_lat))
        pano_lng = float(getattr(result, "lon", getattr(result, "lng", default_lng)))
    return pano_id.strip(), pano_lat, pano_lng


def _find_pano(region: list, region_is_world: bool):
    """
    Find a random valid Street View pano_id inside the given region.
    Returns (pano_id, lat, lng).  This is purely a metadata lookup —
    no image is downloaded.
    """
    if not _SV_OK:
        raise Exception(
            "The 'streetview' library is not installed. "
            "Run: pip install streetview"
        )

    last_error = "No attempts made"

    for attempt in range(MAX_LOCATION_RETRIES):
        try:
            if region_is_world:
                lat = random.uniform(-55, 70)
                lng = random.uniform(-180, 180)
            else:
                pt = _random_polygon_point(region)
                if pt is None:
                    raise Exception(
                        "Could not generate a point inside the drawn polygon. "
                        "Try drawing a larger region."
                    )
                lat, lng = pt

            try:
                results = _search_panoramas(lat=lat, lon=lng)
            except Exception as e:
                last_error = f"search_panoramas() error at ({lat:.2f},{lng:.2f}): {e}"
                app_log.debug(f"[geo] Attempt {attempt+1}/{MAX_LOCATION_RETRIES}: {last_error}")
                continue

            if not results:
                last_error = f"No Street View coverage at ({lat:.2f},{lng:.2f})"
                app_log.debug(f"[geo] Attempt {attempt+1}/{MAX_LOCATION_RETRIES}: {last_error}")
                continue

            pano_id, pano_lat, pano_lng = _extract_pano_info(results[0], lat, lng)
            if not pano_id:
                last_error = f"Empty pano_id returned at ({lat:.2f},{lng:.2f})"
                continue

            app_log.info(f"[geo] Found pano {pano_id} at ({pano_lat:.4f},{pano_lng:.4f})")
            return pano_id, pano_lat, pano_lng

        except Exception as e:
            last_error = str(e)
            app_log.debug(f"[geo] Attempt {attempt+1}/{MAX_LOCATION_RETRIES}: {e}")
            continue

    raise Exception(
        f"Could not find a Street View panorama after {MAX_LOCATION_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


# ── Room helpers ──────────────────────────────────────────────────────────────

def _rn(room_id: str) -> str:
    return f"geo_{room_id}"


def _emit_lobby():
    public = [
        {
            "id":      r["id"],
            "title":   r["title"],
            "players": len(r["players"]),
            "rounds":  r["rounds_total"],
            "time":    r["round_time_limit"],
            "status":  r["status"],
        }
        for r in geo_rooms.values()
        if r["privacy"] == "public" and r["status"] == "waiting"
    ]
    for sid, sess in list(geo_sessions.items()):
        if not sess.get("room_id"):
            socketio.emit("geo_lobby", {"rooms": public, "my_sid": sid}, to=sid)


def _emit_room(room_id: str):
    room = geo_rooms.get(room_id)
    if not room:
        return
    socketio.emit(
        "geo_room_state",
        {
            "id":            room["id"],
            "title":         room["title"],
            "privacy":       room["privacy"],
            "creator_sid":   room["creator_sid"],
            "players":       [
                {"sid": p["sid"], "username": p["username"], "total_score": p["total_score"]}
                for p in room["players"]
            ],
            "status":        room["status"],
            "rounds_total":  room["rounds_total"],
            "round_current": room["round_current"],
            "time_limit":    room["round_time_limit"],
        },
        room=_rn(room_id),
    )
    if room["privacy"] == "private" and room["status"] == "waiting":
        _emit_invite_candidates(room_id)


def _emit_invite_candidates(room_id: str):
    room = geo_rooms.get(room_id)
    if not room or room["privacy"] != "private":
        return
    creator_sid  = room["creator_sid"]
    in_room_sids = {p["sid"] for p in room["players"]}
    candidates   = [
        sess["username"]
        for sid, sess in geo_sessions.items()
        if not sess.get("room_id") and sid not in in_room_sids
    ]
    socketio.emit("geo_invite_candidates", {"users": candidates}, to=creator_sid)


def _cancel_room_timer(room: dict):
    t = room.get("round_timer")
    if t:
        try:
            t.cancel()
        except Exception:
            pass
        room["round_timer"] = None


def _cleanup_player(sid: str, full_delete: bool = True):
    sess = geo_sessions.get(sid)
    if not sess:
        return

    room_id = sess.get("room_id")
    sess["room_id"] = None

    if room_id:
        room = geo_rooms.get(room_id)
        if room:
            room["players"] = [p for p in room["players"] if p["sid"] != sid]
            try:
                socketio.server.leave_room(sid, _rn(room_id))
            except Exception:
                pass
            if not room["players"]:
                _cancel_room_timer(room)
                del geo_rooms[room_id]
                _emit_lobby()
            else:
                if room["creator_sid"] == sid:
                    room["creator_sid"] = room["players"][0]["sid"]
                    socketio.emit("geo_you_are_creator", {}, to=room["creator_sid"])
                if room["status"] == "playing":
                    room["round_guesses"].pop(sid, None)
                    _check_all_guessed(room_id)
                _emit_room(room_id)
                _emit_lobby()

    if full_delete:
        geo_sessions.pop(sid, None)

    for rid, r in list(geo_rooms.items()):
        if r["privacy"] == "private" and r["status"] == "waiting":
            _emit_invite_candidates(rid)

    if not full_delete:
        _emit_lobby()


# ── Round lifecycle ───────────────────────────────────────────────────────────

def _start_round(room_id: str):
    room = geo_rooms.get(room_id)
    if not room:
        return

    room["status"]        = "loading"
    room["round_guesses"] = {}
    _cancel_room_timer(room)

    socketio.emit("geo_loading", {"message": "Finding a location…"}, room=_rn(room_id))

    def fetch_and_start():
        try:
            pano_id, lat, lng = _find_pano(room["region"], room["region_is_world"])
        except Exception as e:
            error_log.error(f"[geo] Room {room_id} pano lookup failed: {e}")
            socketio.emit("geo_fetch_error", {"message": str(e)}, room=_rn(room_id))
            room2 = geo_rooms.get(room_id)
            if room2:
                room2["status"] = "waiting"
                _emit_room(room_id)
            return

        room2 = geo_rooms.get(room_id)
        if not room2:
            return

        room2["current_panoid"]   = pano_id
        room2["current_location"] = [lat, lng]
        room2["status"]           = "playing"
        room2["round_start_time"] = time.time()

        socketio.emit(
            "geo_round_start",
            {
                "round":        room2["round_current"],
                "total_rounds": room2["rounds_total"],
                "pano_id":      pano_id,
                "round_secs":   room2["round_time_limit"],
            },
            room=_rn(room_id),
        )

        def on_timeout():
            r = geo_rooms.get(room_id)
            if r and r["status"] == "playing":
                _end_round(room_id)

        t = threading.Timer(room2["round_time_limit"], on_timeout)
        room2["round_timer"] = t
        t.daemon = True
        t.start()

    threading.Thread(target=fetch_and_start, daemon=True).start()


def _check_all_guessed(room_id: str):
    room = geo_rooms.get(room_id)
    if not room or room["status"] != "playing":
        return
    active = [p["sid"] for p in room["players"]]
    locked = sum(1 for g in room["round_guesses"].values() if g.get("locked"))
    if active and locked >= len(active):
        _cancel_room_timer(room)
        _end_round(room_id)


def _end_round(room_id: str):
    room = geo_rooms.get(room_id)
    if not room or room["status"] != "playing":
        return

    room["status"] = "round_end"
    _cancel_room_timer(room)

    correct_lat, correct_lng = room["current_location"]
    results = []

    for player in room["players"]:
        sid   = player["sid"]
        guess = room["round_guesses"].get(sid)
        if guess and guess.get("lat") is not None:
            dist  = haversine_km(guess["lat"], guess["lng"], correct_lat, correct_lng)
            score = geo_score(dist)
        else:
            dist  = None
            score = 0
        player["total_score"] += score
        results.append({
            "sid":         sid,
            "username":    player["username"],
            "guessed":     dist is not None,
            "guess_lat":   guess["lat"]  if guess else None,
            "guess_lng":   guess["lng"]  if guess else None,
            "distance_km": round(dist, 2) if dist is not None else None,
            "round_score": score,
            "total_score": player["total_score"],
        })

    results.sort(key=lambda x: -x["round_score"])

    socketio.emit(
        "geo_round_end",
        {
            "round":        room["round_current"],
            "correct_lat":  correct_lat,
            "correct_lng":  correct_lng,
            "results":      results,
            "advance_secs": ROUND_ADVANCE_SECS,
        },
        room=_rn(room_id),
    )

    def advance():
        r = geo_rooms.get(room_id)
        if not r:
            return
        if r["round_current"] >= r["rounds_total"]:
            _end_game(room_id)
        else:
            r["round_current"] += 1
            _start_round(room_id)

    t = threading.Timer(ROUND_ADVANCE_SECS, advance)
    t.daemon = True
    t.start()


def _end_game(room_id: str):
    room = geo_rooms.get(room_id)
    if not room:
        return
    room["status"] = "game_over"
    scores = sorted(
        [{"username": p["username"], "sid": p["sid"], "total_score": p["total_score"]}
         for p in room["players"]],
        key=lambda x: -x["total_score"],
    )
    socketio.emit("geo_game_over", {"scores": scores}, room=_rn(room_id))


# ── Socket handlers ───────────────────────────────────────────────────────────

@socketio.on("geo_set_username")
def handle_set_username(data):
    sid      = request.sid
    username = (data.get("username") or "").strip()
    if not username:
        emit("geo_username_ack", {"ok": False, "error": "Username required."}); return
    if len(username) > 24:
        emit("geo_username_ack", {"ok": False, "error": "Max 24 characters."}); return
    if f.check_profanity(username):
        emit("geo_username_ack", {"ok": False, "error": "Username contains disallowed words."}); return
    taken = {v["username"] for k, v in geo_sessions.items() if k != sid}
    if username in taken:
        emit("geo_username_ack", {"ok": False, "error": "Username already taken on this server."}); return
    existing = geo_sessions.get(sid)
    if existing:
        existing["username"] = username
    else:
        geo_sessions[sid] = {"username": username, "room_id": None}
    emit("geo_username_ack", {"ok": True, "username": username})
    _emit_lobby()
    for rid, r in geo_rooms.items():
        if r["privacy"] == "private" and r["status"] == "waiting":
            _emit_invite_candidates(rid)


@socketio.on("geo_get_lobby")
def handle_get_lobby(_=None):
    sid  = request.sid
    sess = geo_sessions.get(sid)
    if sess and sess.get("room_id") and sess["room_id"] not in geo_rooms:
        sess["room_id"] = None
    _emit_lobby()


@socketio.on("geo_create_room")
def handle_create_room(data):
    sid = request.sid
    if sid not in geo_sessions:
        emit("geo_error", {"message": "Set a username first."}); return

    title           = (data.get("title") or "").strip() or "My Room"
    privacy         = data.get("privacy", "public")
    rounds          = int(data.get("rounds", 5))
    time_limit      = int(data.get("time_limit", 90))
    region          = data.get("region") or []
    region_is_world = bool(data.get("region_is_world", True))

    if f.check_profanity(title):
        emit("geo_error", {"message": "Room title contains disallowed words."}); return
    if privacy not in ("public", "private"):
        privacy = "public"
    rounds     = max(1, min(10, rounds))
    time_limit = max(15, min(300, time_limit))
    if not region_is_world and len(region) < 3:
        emit("geo_error", {"message": "Draw a region on the map first."}); return

    room_id  = uuid.uuid4().hex[:8]
    username = geo_sessions[sid]["username"]

    geo_rooms[room_id] = {
        "id":              room_id,
        "title":           title,
        "privacy":         privacy,
        "creator_sid":     sid,
        "players":         [{"sid": sid, "username": username, "total_score": 0}],
        "status":          "waiting",
        "region":          region,
        "region_is_world": region_is_world,
        "rounds_total":    rounds,
        "round_current":   1,
        "round_time_limit":time_limit,
        "current_panoid":  None,
        "current_location":None,
        "round_guesses":   {},
        "round_timer":     None,
        "round_start_time":None,
    }
    geo_sessions[sid]["room_id"] = room_id
    socketio.server.enter_room(sid, _rn(room_id))
    emit("geo_room_created", {"room_id": room_id})
    _emit_room(room_id)
    _emit_lobby()
    app_log.info(f"[geo] {username!r} created room {room_id} ({rounds}r,{time_limit}s,world={region_is_world},{privacy})")


@socketio.on("geo_join_room")
def handle_join_room(data):
    sid     = request.sid
    room_id = data.get("room_id")
    if sid not in geo_sessions:
        emit("geo_error", {"message": "Set a username first."}); return
    room = geo_rooms.get(room_id)
    if not room:
        emit("geo_error", {"message": "Room not found."}); return
    if room["privacy"] == "private":
        emit("geo_error", {"message": "This room is private."}); return
    if room["status"] != "waiting":
        emit("geo_error", {"message": "This game has already started."}); return
    if any(p["sid"] == sid for p in room["players"]):
        emit("geo_joined_room", {"room_id": room_id}); return
    username = geo_sessions[sid]["username"]
    room["players"].append({"sid": sid, "username": username, "total_score": 0})
    geo_sessions[sid]["room_id"] = room_id
    socketio.server.enter_room(sid, _rn(room_id))
    socketio.emit("geo_player_joined", {"username": username}, room=_rn(room_id))
    emit("geo_joined_room", {"room_id": room_id})
    _emit_room(room_id)
    _emit_lobby()


@socketio.on("geo_join_room_by_invite")
def handle_join_by_invite(data):
    sid     = request.sid
    room_id = data.get("room_id")
    if sid not in geo_sessions:
        emit("geo_error", {"message": "Set a username first."}); return
    room = geo_rooms.get(room_id)
    if not room:
        emit("geo_error", {"message": "Room no longer exists."}); return
    if room["status"] != "waiting":
        emit("geo_error", {"message": "This game has already started."}); return
    if any(p["sid"] == sid for p in room["players"]):
        emit("geo_joined_room", {"room_id": room_id}); return
    username = geo_sessions[sid]["username"]
    room["players"].append({"sid": sid, "username": username, "total_score": 0})
    geo_sessions[sid]["room_id"] = room_id
    socketio.server.enter_room(sid, _rn(room_id))
    socketio.emit("geo_player_joined", {"username": username}, room=_rn(room_id))
    emit("geo_joined_room", {"room_id": room_id})
    _emit_room(room_id)
    _emit_lobby()


@socketio.on("geo_leave_room")
def handle_leave_room(_=None):
    _cleanup_player(request.sid, full_delete=False)


@socketio.on("geo_leave_route")
def handle_leave_route(_=None):
    _cleanup_player(request.sid, full_delete=True)


@socketio.on("geo_start_game")
def handle_start_game(_=None):
    sid     = request.sid
    room_id = geo_sessions.get(sid, {}).get("room_id")
    room    = geo_rooms.get(room_id)
    if not room:
        emit("geo_error", {"message": "Not in a room."}); return
    if room["creator_sid"] != sid:
        emit("geo_error", {"message": "Only the room creator can start the game."}); return
    if room["status"] != "waiting":
        emit("geo_error", {"message": "Game already started."}); return
    room["round_current"] = 1
    for p in room["players"]:
        p["total_score"] = 0
    _start_round(room_id)


@socketio.on("geo_submit_guess")
def handle_submit_guess(data):
    sid     = request.sid
    room_id = geo_sessions.get(sid, {}).get("room_id")
    room    = geo_rooms.get(room_id)
    if not room or room["status"] != "playing":
        return
    if not any(p["sid"] == sid for p in room["players"]):
        return
    lat    = data.get("lat")
    lng    = data.get("lng")
    locked = bool(data.get("locked", False))
    if lat is None or lng is None:
        return
    if room["round_guesses"].get(sid, {}).get("locked"):
        return
    room["round_guesses"][sid] = {"lat": lat, "lng": lng, "locked": locked}
    if locked:
        username     = geo_sessions[sid]["username"]
        locked_count = sum(1 for g in room["round_guesses"].values() if g.get("locked"))
        socketio.emit(
            "geo_guess_locked",
            {"username": username, "locked_count": locked_count, "total": len(room["players"])},
            room=_rn(room_id),
        )
        _check_all_guessed(room_id)


@socketio.on("geo_restart_room")
def handle_restart_room(_=None):
    sid     = request.sid
    room_id = geo_sessions.get(sid, {}).get("room_id")
    room    = geo_rooms.get(room_id)
    if not room:
        emit("geo_error", {"message": "Not in a room."}); return
    if room["creator_sid"] != sid:
        emit("geo_error", {"message": "Only the room creator can restart."}); return
    if room["status"] != "game_over":
        return
    room["status"]        = "waiting"
    room["round_current"] = 1
    for p in room["players"]:
        p["total_score"] = 0
    _emit_room(room_id)
    socketio.emit("geo_room_restarted", {}, room=_rn(room_id))


@socketio.on("geo_invite_user")
def handle_invite_user(data):
    sid     = request.sid
    room_id = geo_sessions.get(sid, {}).get("room_id")
    room    = geo_rooms.get(room_id)
    if not room or room["creator_sid"] != sid or room["privacy"] != "private":
        return
    target_username = (data.get("username") or "").strip()
    target_sid = next(
        (k for k, v in geo_sessions.items()
         if v["username"] == target_username and not v.get("room_id")),
        None
    )
    if not target_sid:
        emit("geo_error", {"message": f"{target_username!r} is no longer available."}); return
    socketio.emit(
        "geo_invited",
        {
            "room_id":       room_id,
            "room_title":    room["title"],
            "from_username": geo_sessions[sid]["username"],
        },
        to=target_sid,
    )


# ── Singleplayer ──────────────────────────────────────────────────────────────

@socketio.on("geo_sp_get_panorama")
def handle_sp_get_panorama(data):
    sid             = request.sid
    region          = data.get("region") or []
    region_is_world = bool(data.get("region_is_world", True))
    emit("geo_sp_loading", {"message": "Finding a location…"})

    def fetch():
        try:
            pano_id, lat, lng = _find_pano(region, region_is_world)
            socketio.emit(
                "geo_sp_panorama",
                {"pano_id": pano_id, "correct_lat": lat, "correct_lng": lng},
                to=sid,
            )
        except Exception as e:
            socketio.emit("geo_sp_error", {"message": str(e)}, to=sid)

    threading.Thread(target=fetch, daemon=True).start()


@socketio.on("geo_sp_submit_guess")
def handle_sp_submit_guess(data):
    lat         = data.get("lat")
    lng         = data.get("lng")
    correct_lat = data.get("correct_lat")
    correct_lng = data.get("correct_lng")
    if None in (lat, lng, correct_lat, correct_lng):
        emit("geo_error", {"message": "Invalid guess data."}); return
    dist  = haversine_km(lat, lng, correct_lat, correct_lng)
    score = geo_score(dist)
    emit("geo_sp_result", {
        "distance_km": round(dist, 2),
        "score":       score,
        "correct_lat": correct_lat,
        "correct_lng": correct_lng,
    })


# ── Disconnect ────────────────────────────────────────────────────────────────

@socketio.on("disconnect")
def handle_geo_disconnect():
    _cleanup_player(request.sid, full_delete=True)