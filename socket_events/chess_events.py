# socket_events/chess_events.py
import chess
import uuid
import time
import threading
import random

from flask import request
from flask_socketio import emit
from socketio_instance import socketio
from glob_vars import app_log, error_log
from game_logic.chess import get_bot_move
import functions as f

# ── In-memory state ────────────────────────────────────────────────────────────
chess_sessions: dict[str, dict] = {}   # sid → {username, game_id, in_queue}
active_games:   dict[str, dict] = {}   # game_id → GameState
random_queue:   list[str]       = []   # sids waiting for random match

TIME_CONTROLS = {
    "bullet":    {"time": 120,  "inc": 1},
    "blitz":     {"time": 300,  "inc": 3},
    "rapid":     {"time": 900,  "inc": 10},
    "classical": {"time": 1800, "inc": 0},
}

TC_LABELS = {
    "bullet": "2+1", "blitz": "5+3", "rapid": "15+10", "classical": "30+0"
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def _board_to_grid(board: chess.Board) -> list:
    """8×8 list, index[0]=rank8 .. index[7]=rank1. Uppercase=white, lowercase=black, None=empty."""
    grid = []
    for rank in range(7, -1, -1):
        row = []
        for file in range(8):
            p = board.piece_at(chess.square(file, rank))
            row.append(p.symbol() if p else None)
        grid.append(row)
    return grid


def _game_snapshot(game: dict, sid: str) -> dict:
    board = game["board"]
    if sid == game["white_sid"]:
        player_color = "white"
    elif sid == game["black_sid"]:
        player_color = "black"
    else:
        player_color = "spectator"

    # Legal moves for this player (UCI strings like "e2e4")
    legal = []
    if game["status"] == "active":
        is_white_turn = board.turn == chess.WHITE
        if (is_white_turn  and player_color == "white") or \
           (not is_white_turn and player_color == "black"):
            legal = [m.uci() for m in board.legal_moves]

    # Last move
    last_move = None
    if board.move_stack:
        m = board.peek()
        last_move = {"from": chess.square_name(m.from_square),
                     "to":   chess.square_name(m.to_square)}

    # SAN move history
    temp = chess.Board()
    history = []
    for mv in board.move_stack:
        history.append(temp.san(mv))
        temp.push(mv)

    # Live time (subtract elapsed on current turn)
    now = time.time()
    wt  = game["white_time"]
    bt  = game["black_time"]
    if game["status"] == "active" and game["last_move_ts"]:
        elapsed = now - game["last_move_ts"]
        if board.turn == chess.WHITE:
            wt = max(0.0, wt - elapsed)
        else:
            bt = max(0.0, bt - elapsed)

    return {
        "game_id":        game["id"],
        "board":          _board_to_grid(board),
        "turn":           "white" if board.turn == chess.WHITE else "black",
        "player_color":   player_color,
        "legal_moves":    legal,
        "last_move":      last_move,
        "white_time":     wt,
        "black_time":     bt,
        "white_username": game["white_username"],
        "black_username": game["black_username"],
        "in_check":       board.is_check(),
        "is_over":        game["status"] == "ended",
        "result":         game.get("result"),
        "result_reason":  game.get("result_reason"),
        "draw_offer_by":  game.get("draw_offer_by"),
        "can_claim_draw": board.can_claim_draw(),
        "move_history":   history,
        "tc_label":       game["tc_label"],
        "is_bot_game":    game["is_bot_game"],
    }


def _end_game(game_id: str, result: str, reason: str) -> None:
    game = active_games.get(game_id)
    if not game or game["status"] == "ended":
        return
    game["status"]        = "ended"
    game["result"]        = result
    game["result_reason"] = reason

    for sid in [game["white_sid"], game["black_sid"]]:
        if sid and sid in chess_sessions:
            chess_sessions[sid]["game_id"] = None
            socketio.emit("chess_game_over", {
                "result":         result,
                "reason":         reason,
                "white_username": game["white_username"],
                "black_username": game["black_username"],
            }, to=sid)
    app_log.info(f"[chess] Game {game_id} ended: {result} ({reason})")


def _check_outcome(board: chess.Board) -> tuple[str | None, str | None]:
    """Returns (result, reason) or (None, None) if game continues."""
    if not board.is_game_over():
        return None, None
    outcome = board.outcome()
    if not outcome:
        return "1/2-1/2", "Draw"
    winner = outcome.winner
    result = ("1-0" if winner == chess.WHITE else
              "0-1" if winner == chess.BLACK else "1/2-1/2")
    REASONS = {
        chess.Termination.CHECKMATE:              "Checkmate",
        chess.Termination.STALEMATE:              "Stalemate",
        chess.Termination.INSUFFICIENT_MATERIAL:  "Insufficient material",
        chess.Termination.SEVENTYFIVE_MOVES:      "75-move rule",
        chess.Termination.FIVEFOLD_REPETITION:    "Fivefold repetition",
        chess.Termination.FIFTY_MOVES:            "50-move rule",
        chess.Termination.THREEFOLD_REPETITION:   "Threefold repetition",
    }
    return result, REASONS.get(outcome.termination, "Game over")


def _emit_lobby() -> None:
    available = [
        {"sid": s, "username": v["username"]}
        for s, v in chess_sessions.items()
        if not v.get("game_id") and not v.get("in_queue")
    ]
    for sid in list(chess_sessions):
        socketio.emit("chess_lobby_state", {
            "available": available,
            "my_sid":    sid,
        }, to=sid)


def _start_pvp(sid1: str, sid2: str, tc_name: str) -> None:
    tc = TIME_CONTROLS.get(tc_name, TIME_CONTROLS["blitz"])
    white_sid, black_sid = (sid1, sid2) if random.random() < .5 else (sid2, sid1)
    game_id = str(uuid.uuid4())[:8]

    game = {
        "id":             game_id,
        "board":          chess.Board(),
        "white_sid":      white_sid,
        "black_sid":      black_sid,
        "white_username": chess_sessions[white_sid]["username"],
        "black_username": chess_sessions[black_sid]["username"],
        "is_bot_game":    False,
        "bot_color":      None,
        "bot_difficulty": None,
        "tc_label":       TC_LABELS.get(tc_name, tc_name),
        "time_control":   tc["time"],
        "increment":      tc["inc"],
        "white_time":     float(tc["time"]),
        "black_time":     float(tc["time"]),
        "last_move_ts":   time.time(),
        "status":         "active",
        "result":         None,
        "result_reason":  None,
        "draw_offer_by":  None,
        "move_count":     0,
    }
    active_games[game_id] = game
    for s in [white_sid, black_sid]:
        chess_sessions[s]["game_id"]  = game_id
        chess_sessions[s]["in_queue"] = False
        socketio.emit("chess_game_start", _game_snapshot(game, s), to=s)
    _schedule_time_check(game_id)
    _emit_lobby()
    app_log.info(f"[chess] PvP game {game_id}: {game['white_username']} vs {game['black_username']} ({tc_name})")


def _schedule_time_check(game_id: str) -> None:
    def loop():
        while True:
            time.sleep(1)
            game = active_games.get(game_id)
            if not game or game["status"] != "active":
                break
            now = time.time()
            if not game["last_move_ts"]:
                continue
            elapsed = now - game["last_move_ts"]
            board   = game["board"]
            if board.turn == chess.WHITE:
                if game["white_time"] - elapsed <= 0:
                    _end_game(game_id, "0-1", "White ran out of time")
                    break
            else:
                if game["black_time"] - elapsed <= 0:
                    _end_game(game_id, "1-0", "Black ran out of time")
                    break
    threading.Thread(target=loop, daemon=True).start()


def _bot_move_async(game_id: str, delay: float = 0.6) -> None:
    def run():
        time.sleep(delay)
        game = active_games.get(game_id)
        if not game or game["status"] != "active":
            return
        board  = game["board"]
        move   = get_bot_move(board, game["bot_difficulty"])
        if not move:
            return

        now = time.time()
        if game["last_move_ts"]:
            elapsed = now - game["last_move_ts"]
            if board.turn == chess.WHITE:
                game["white_time"] = max(0, game["white_time"] - elapsed + game["increment"])
            else:
                game["black_time"] = max(0, game["black_time"] - elapsed + game["increment"])
        game["last_move_ts"] = now

        board.push(move)
        game["move_count"] += 1

        result, reason = _check_outcome(board)
        if result:
            human = game["white_sid"] or game["black_sid"]
            if human:
                socketio.emit("chess_game_update", _game_snapshot(game, human), to=human)
            _end_game(game_id, result, reason)
            return

        human = game["white_sid"] if game["bot_color"] == chess.BLACK else game["black_sid"]
        if human:
            socketio.emit("chess_game_update", _game_snapshot(game, human), to=human)

    threading.Thread(target=run, daemon=True).start()


# ── Public cleanup (called by consolidated disconnect handler) ─────────────────
def _cleanup_chess(sid: str) -> None:
    if sid in random_queue:
        random_queue.remove(sid)
    sess = chess_sessions.pop(sid, None)
    if not sess:
        return
    game_id = sess.get("game_id")
    if game_id:
        game = active_games.get(game_id)
        if game and game["status"] == "active":
            if game["white_sid"] == sid:
                _end_game(game_id, "0-1", f"{game['white_username']} disconnected")
            elif game["black_sid"] == sid:
                _end_game(game_id, "1-0", f"{game['black_username']} disconnected")
    _emit_lobby()


# ── Socket handlers ────────────────────────────────────────────────────────────

@socketio.on("chess_leave_route")
def handle_chess_leave_route(_=None):
    """
    Fired by the client when navigating away from /chess.
    Frees the username immediately without waiting for socket disconnect.
    """
    _cleanup_chess(request.sid)

@socketio.on("chess_set_username")
def handle_chess_username(data):
    sid      = request.sid
    username = (data.get("username") or "").strip()
    if f.check_profanity(username):
       emit("chess_username_ack", {"ok": False,
            "error": "Username contains disallowed words."}); return
    if not username:
        emit("chess_username_ack", {"ok": False, "error": "Username cannot be empty."}); return
    if len(username) > 24:
        emit("chess_username_ack", {"ok": False, "error": "Username too long (max 24)."}); return
    taken = {v["username"] for v in chess_sessions.values()}
    if username in taken and chess_sessions.get(sid, {}).get("username") != username:
        emit("chess_username_ack", {"ok": False, "error": "Username already taken."}); return
    chess_sessions[sid] = {"username": username, "game_id": None, "in_queue": False}
    emit("chess_username_ack", {"ok": True, "username": username})
    _emit_lobby()


@socketio.on("chess_join_lobby")
def handle_join_lobby(_data=None):
    sid = request.sid
    if sid not in chess_sessions:
        emit("chess_error", {"message": "Set username first."}); return
    chess_sessions[sid]["game_id"]  = None
    chess_sessions[sid]["in_queue"] = False
    _emit_lobby()


@socketio.on("chess_start_bot")
def handle_start_bot(data):
    sid        = request.sid
    difficulty = data.get("difficulty", "medium")
    tc_name    = data.get("time_control", "blitz")
    pref_color = data.get("color", "random")

    if sid not in chess_sessions:
        emit("chess_error", {"message": "Set username first."}); return
    if difficulty not in ("easy", "medium", "hard"):
        difficulty = "medium"
    if tc_name not in TIME_CONTROLS:
        tc_name = "blitz"
    if pref_color == "random":
        pref_color = random.choice(["white", "black"])

    tc        = TIME_CONTROLS[tc_name]
    game_id   = str(uuid.uuid4())[:8]
    username  = chess_sessions[sid]["username"]
    is_white  = (pref_color == "white")
    bot_color = chess.BLACK if is_white else chess.WHITE

    game = {
        "id":             game_id,
        "board":          chess.Board(),
        "white_sid":      sid if is_white else None,
        "black_sid":      sid if not is_white else None,
        "white_username": username if is_white else f"Bot ({difficulty.capitalize()})",
        "black_username": f"Bot ({difficulty.capitalize()})" if is_white else username,
        "is_bot_game":    True,
        "bot_color":      bot_color,
        "bot_difficulty": difficulty,
        "tc_label":       TC_LABELS.get(tc_name, tc_name),
        "time_control":   tc["time"],
        "increment":      tc["inc"],
        "white_time":     float(tc["time"]),
        "black_time":     float(tc["time"]),
        "last_move_ts":   time.time(),
        "status":         "active",
        "result":         None,
        "result_reason":  None,
        "draw_offer_by":  None,
        "move_count":     0,
    }
    active_games[game_id]      = game
    chess_sessions[sid]["game_id"] = game_id
    emit("chess_game_start", _game_snapshot(game, sid))
    if not is_white:
        _bot_move_async(game_id, delay=1.0)
    else:
        _schedule_time_check(game_id)


@socketio.on("chess_challenge")
def handle_challenge(data):
    sid     = request.sid
    target  = data.get("target_sid")
    tc_name = data.get("time_control", "blitz")
    if sid not in chess_sessions:
        emit("chess_error", {"message": "Set username first."}); return
    if target not in chess_sessions or chess_sessions[target].get("game_id"):
        emit("chess_error", {"message": "Player no longer available."}); return
    socketio.emit("chess_challenged", {
        "challenger_sid":      sid,
        "challenger_username": chess_sessions[sid]["username"],
        "time_control":        tc_name,
        "tc_label":            TC_LABELS.get(tc_name, tc_name),
    }, to=target)
    emit("chess_challenge_sent", {"target": chess_sessions[target]["username"]})


@socketio.on("chess_challenge_response")
def handle_challenge_response(data):
    sid            = request.sid
    challenger_sid = data.get("challenger_sid")
    accept         = bool(data.get("accept"))
    tc_name        = data.get("time_control", "blitz")
    if not accept:
        if challenger_sid in chess_sessions:
            socketio.emit("chess_challenge_declined",
                          {"by": chess_sessions[sid]["username"]}, to=challenger_sid)
        return
    if challenger_sid not in chess_sessions or chess_sessions[challenger_sid].get("game_id"):
        emit("chess_error", {"message": "Challenger no longer available."}); return
    if chess_sessions[sid].get("game_id"):
        emit("chess_error", {"message": "You are already in a game."}); return
    _start_pvp(challenger_sid, sid, tc_name)


@socketio.on("chess_queue_random")
def handle_queue_random(data):
    sid     = request.sid
    tc_name = data.get("time_control", "blitz")
    if sid not in chess_sessions:
        emit("chess_error", {"message": "Set username first."}); return
    if chess_sessions[sid].get("game_id"):
        emit("chess_error", {"message": "Already in a game."}); return
    if sid in random_queue:
        return
    for waiting in random_queue[:]:
        if waiting != sid and waiting in chess_sessions and not chess_sessions[waiting].get("game_id"):
            random_queue.remove(waiting)
            chess_sessions[sid]["in_queue"] = False
            _start_pvp(waiting, sid, tc_name)
            return
    random_queue.append(sid)
    chess_sessions[sid]["in_queue"] = True
    emit("chess_queued", {"tc_label": TC_LABELS.get(tc_name, tc_name)})
    _emit_lobby()


@socketio.on("chess_cancel_queue")
def handle_cancel_queue(_data=None):
    sid = request.sid
    if sid in random_queue:
        random_queue.remove(sid)
    if sid in chess_sessions:
        chess_sessions[sid]["in_queue"] = False
    emit("chess_queue_cancelled")
    _emit_lobby()


@socketio.on("chess_move")
def handle_chess_move(data):
    sid     = request.sid
    game_id = data.get("game_id")
    from_sq = data.get("from", "")
    to_sq   = data.get("to", "")
    promo   = data.get("promotion", "q")

    game = active_games.get(game_id)
    if not game or game["status"] != "active":
        emit("chess_error", {"message": "Game not active."}); return

    board = game["board"]
    is_white_turn = (board.turn == chess.WHITE)
    if is_white_turn  and game["white_sid"] != sid:
        emit("chess_error", {"message": "Not your turn."}); return
    if not is_white_turn and game["black_sid"] != sid:
        emit("chess_error", {"message": "Not your turn."}); return

    try:
        uci = from_sq + to_sq
        piece = board.piece_at(chess.parse_square(from_sq))
        if piece and piece.piece_type == chess.PAWN:
            to_rank = int(to_sq[1])
            if (piece.color == chess.WHITE and to_rank == 8) or \
               (piece.color == chess.BLACK and to_rank == 1):
                uci += (promo if promo in "qrbn" else "q")
        move = chess.Move.from_uci(uci)
    except Exception:
        emit("chess_error", {"message": "Invalid move."}); return

    if move not in board.legal_moves:
        emit("chess_error", {"message": "Illegal move."}); return

    # Deduct time + add increment
    now = time.time()
    if game["last_move_ts"]:
        elapsed = now - game["last_move_ts"]
        if board.turn == chess.WHITE:
            game["white_time"] = max(0.0, game["white_time"] - elapsed + game["increment"])
            if game["white_time"] <= 0:
                _end_game(game_id, "0-1", "White ran out of time"); return
        else:
            game["black_time"] = max(0.0, game["black_time"] - elapsed + game["increment"])
            if game["black_time"] <= 0:
                _end_game(game_id, "1-0", "Black ran out of time"); return
    game["last_move_ts"]  = now
    game["draw_offer_by"] = None

    board.push(move)
    game["move_count"] += 1

    result, reason = _check_outcome(board)
    for s in [game["white_sid"], game["black_sid"]]:
        if s:
            socketio.emit("chess_game_update", _game_snapshot(game, s), to=s)
    if result:
        _end_game(game_id, result, reason); return

    if game["is_bot_game"]:
        _bot_move_async(game_id)


@socketio.on("chess_resign")
def handle_resign(data):
    sid     = request.sid
    game_id = data.get("game_id")
    game    = active_games.get(game_id)
    if not game or game["status"] != "active": return
    if game["white_sid"] == sid:
        _end_game(game_id, "0-1",  f"{game['white_username']} resigned")
    elif game["black_sid"] == sid:
        _end_game(game_id, "1-0", f"{game['black_username']} resigned")


@socketio.on("chess_offer_draw")
def handle_offer_draw(data):
    sid     = request.sid
    game_id = data.get("game_id")
    game    = active_games.get(game_id)
    if not game or game["status"] != "active" or game["is_bot_game"]: return
    if game["white_sid"] == sid:
        game["draw_offer_by"] = "white"; opp = game["black_sid"]
    elif game["black_sid"] == sid:
        game["draw_offer_by"] = "black"; opp = game["white_sid"]
    else: return
    if opp: socketio.emit("chess_draw_offered", {"by": game["draw_offer_by"]}, to=opp)


@socketio.on("chess_draw_response")
def handle_draw_response(data):
    sid     = request.sid
    game_id = data.get("game_id")
    accept  = bool(data.get("accept"))
    game    = active_games.get(game_id)
    if not game or game["status"] != "active": return
    if accept:
        _end_game(game_id, "1/2-1/2", "Draw by agreement")
    else:
        game["draw_offer_by"] = None
        offeror = game["black_sid"] if game["white_sid"] == sid else game["white_sid"]
        if offeror: socketio.emit("chess_draw_declined", {}, to=offeror)


@socketio.on("chess_claim_draw")
def handle_claim_draw(data):
    sid     = request.sid
    game_id = data.get("game_id")
    game    = active_games.get(game_id)
    if not game or game["status"] != "active": return
    if game["board"].can_claim_draw():
        _end_game(game_id, "1/2-1/2", "Draw claimed")