# socket_events/uno_events.py
import uuid, time, threading, random
from flask import request
from flask_socketio import emit
from socketio_instance import socketio
from glob_vars import app_log, error_log
from uno_game import UnoGame, UNO_TYPES, COLORS
import functions as f
import config


# ── State ──────────────────────────────────────────────────────────────────────
uno_sessions: dict[str, dict] = {}
rooms:        dict[str, dict] = {}

_BOT_NAMES = ['HAL', 'DEEP', 'NOVA', 'ARIA', 'ZETA', 'ORION', 'FLUX', 'ECHO']

# ── Lobby / room emitters ──────────────────────────────────────────────────────

def _rn(room_id): return f'uno_{room_id}'

def _total_players(room) -> int:
    return len(room['players']) + len(room['bots'])

def _available_players():
    return [{'sid': s, 'username': v['username']}
            for s, v in uno_sessions.items() if not v.get('room_id')]

def _emit_lobby():
    public = [{
        'id':        r['id'],
        'title':     r['title'],
        'uno_type':  r['uno_type'],
        'type_name': UNO_TYPES[r['uno_type']]['name'],
        'players':   _total_players(r),
        'max':       r['max_players'],
        'status':    r['status'],
    } for r in rooms.values() if r['privacy'] == 'public' and r['status'] == 'waiting']

    avail = _available_players()
    for sid, sess in uno_sessions.items():
        if not sess.get('room_id'):
            socketio.emit('uno_lobby', {'rooms': public, 'available': avail,
                                        'my_sid': sid}, to=sid)
    for room in rooms.values():
        if room['status'] == 'waiting' and room['privacy'] == 'private':
            creator_sid = room['creator_sid']
            if creator_sid in uno_sessions:
                socketio.emit('uno_available_update', {'available': avail},
                              to=creator_sid)

def _emit_room(room_id: str):
    room = rooms.get(room_id)
    if not room:
        return
    avail = _available_players()
    base = {
        'id':          room['id'],
        'title':       room['title'],
        'uno_type':    room['uno_type'],
        'type_name':   UNO_TYPES[room['uno_type']]['name'],
        'privacy':     room['privacy'],
        'creator_sid': room['creator_sid'],
        'players':     room['players'],
        'bots':        room['bots'],
        'status':      room['status'],
        'min_players': room['min_players'],
        'max_players': room['max_players'],
        'can_start':   (_total_players(room) >= room['min_players']
                        and room['status'] == 'waiting'),
        'is_full':     _total_players(room) >= room['max_players'],
        'available':   avail,
    }
    for p in room['players']:
        socketio.emit('uno_room_state', {**base, 'my_sid': p['sid'],
                       'is_creator': p['sid'] == room['creator_sid']}, to=p['sid'])
    for s in room['spectators']:
        socketio.emit('uno_room_state', {**base, 'my_sid': s['sid'],
                       'is_creator': False}, to=s['sid'])

def _broadcast_game(room_id: str):
    room = rooms.get(room_id)
    if not room or not room.get('game'):
        return
    game = room['game']
    for p in room['players']:
        socketio.emit('uno_game_state',
                      game.snapshot(viewer_sid=p['sid'], viewer_is_spectator=False),
                      to=p['sid'])
    for s in room['spectators']:
        socketio.emit('uno_game_state',
                      game.snapshot(viewer_sid=s['sid'], viewer_is_spectator=True),
                      to=s['sid'])

# ── Result handling ────────────────────────────────────────────────────────────
#
# Every game action (play_card, draw_action, choose_color, resolve_player_action)
# produces a result dict.  Route it through _process_result so no path can
# accidentally miss a game-over, mercy knockout, or bot schedule.

def _process_result(room_id: str, game: UnoGame, result: dict):
    if not result.get('ok'):
        return

    # Single mercy knockout (draw_action, roulette)
    mercy = result.get('mercy')
    if mercy and mercy.get('knocked_out'):
        _handle_mercy_knockout(room_id, game, mercy['username'])
        if game.status == 'finished':
            _broadcast_game(room_id)
            _handle_game_result(room_id, 'game_over', {})
            return

    # Multiple mercy knockouts (0 card rotation, or any future multi-knockout effect)
    for m in result.get('mercy_knockouts', []):
        if m.get('knocked_out'):
            _handle_mercy_knockout(room_id, game, m['username'])
    if result.get('mercy_knockouts') and game.status == 'finished':
        _broadcast_game(room_id)
        _handle_game_result(room_id, 'game_over', {})
        return

    ev = result.get('event')
    if ev == 'game_over':
        _handle_game_result(room_id, 'game_over', result)
        return
    elif ev == 'player_won':
        _handle_game_result(room_id, 'player_won', result)

    if game.status == 'playing':
        nxt = game.current_player()
        if nxt and nxt.get('is_bot'):
            _schedule_bot(room_id)


def _handle_mercy_knockout(room_id: str, game: UnoGame, username: str):
    """
    Move a mercy-knocked player to spectator mode, exactly like a normal win
    except they get 'uno_you_mercy_knocked' instead of 'uno_you_won'.
    """
    room = rooms.get(room_id)
    if not room:
        return

    knocked_sid = next(
        (p['sid'] for p in room['players'] if p['username'] == username),
        None
    )

    # Announce to the table
    socketio.emit('uno_mercy_knocked', {'username': username}, room=_rn(room_id))

    if knocked_sid:
        room['players']   = [p for p in room['players']   if p['sid'] != knocked_sid]
        room['spectators'].append({'sid': knocked_sid, 'username': username})
        if knocked_sid in uno_sessions:
            uno_sessions[knocked_sid]['room_id'] = room_id  # still in room
        socketio.emit('uno_you_mercy_knocked', {}, to=knocked_sid)


def _handle_game_result(room_id: str, event: str, extra: dict = None):
    room = rooms.get(room_id)
    if not room:
        return
    game = room['game']

    if event == 'player_won':
        username = extra.get('username')
        won_sid  = next((p['sid'] for p in room['players']
                         if p['username'] == username), None)
        if won_sid:
            room['players']   = [p for p in room['players'] if p['sid'] != won_sid]
            room['spectators'].append({'sid': won_sid, 'username': username})
            if won_sid in uno_sessions:
                uno_sessions[won_sid]['room_id'] = room_id
            socketio.emit('uno_you_won', {'rank': extra.get('rank')}, to=won_sid)
        _broadcast_game(room_id)

    elif event == 'game_over':
        room['status']         = 'post_game'
        room['ready_continue'] = set()
        rankings = sorted(game.players,
                  key=lambda p: p.get('rank') if isinstance(p.get('rank'), int) else 999)

        payload  = {
            'rankings':    [{'username': p['username'], 'rank': p.get('rank'),
                             'is_bot': p.get('is_bot', False),
                             'mercy_knocked': p.get('mercy_knocked', False)}
                            for p in rankings],
            'creator_sid': room['creator_sid'],
        }
        all_sids = [p['sid'] for p in room['players'] + room['spectators'] if p['sid']]
        for sid in all_sids:
            socketio.emit('uno_game_over',
                          {**payload, 'is_creator': sid == room['creator_sid']},
                          to=sid)
        _emit_lobby()

# ── Bot runner ─────────────────────────────────────────────────────────────────

def _schedule_bot(room_id: str, delay: float = None):
    if delay is None:
        room = rooms.get(room_id)
        if room and all(p.get('is_bot', False)
                        for p in room.get('players', [])):
            delay = float(getattr(config, 'UNO_BOT_ONLY_DELAY', 0.18))
        else:
            delay = float(getattr(config, 'UNO_BOT_THINK_DELAY', 1.3))

    def run():
        time.sleep(delay)
        room = rooms.get(room_id)
        if not room or room['status'] != 'playing':
            return
        game = room.get('game')
        if not game or game.status != 'playing':
            return
        cur = game.current_player()
        if not cur or not cur.get('is_bot'):
            return
        _do_bot_turn(room_id, game)
    threading.Thread(target=run, daemon=True).start()



def _do_bot_turn(room_id: str, game: UnoGame):
    cur_idx = game.cur_idx()
    cur     = game.players[cur_idx]

    # ── Pending player action (swap target, roulette colour, etc.) ────────────
    # get_pending_player_action() is a hook — works for any game type without
    # any changes to this function.
    pending = game.get_pending_player_action()
    if pending is not None:
        if pending['player_idx'] == cur_idx and cur.get('is_bot'):
            data   = game.bot_resolve_pending_action(cur_idx, cur, pending['type'])
            result = game.resolve_player_action(cur_idx, pending['type'], data)
            _broadcast_game(room_id)
            _process_result(room_id, game, result)
        # Always return here — human must resolve, or bot just did
        return

    # ── Normal turn ───────────────────────────────────────────────────────────
    if game.waiting_for_color:
        color  = game.bot_pick_color(cur['hand'])
        result = game.choose_color(cur_idx, color)
    else:
        top = game.top_card()
        ci  = game.bot_pick_card(cur['hand'], top,
                                  cur.get('difficulty', 'medium'),
                                  game.pending_draw)
        if ci is None:
            result = game.draw_action(cur_idx)
        else:
            card   = cur['hand'][ci]
            cc     = game.bot_pick_color(cur['hand']) if card.color == 'wild' else None
            result = game.play_card(cur_idx, ci, cc)

    if not result.get('ok'):
        result = game.draw_action(cur_idx)

    _broadcast_game(room_id)
    _process_result(room_id, game, result)

# ── Player cleanup ─────────────────────────────────────────────────────────────

def _cleanup_uno(sid: str):
    sess = uno_sessions.pop(sid, None)
    if not sess:
        return
    room_id = sess.get('room_id')
    if not room_id:
        _emit_lobby(); return
    room = rooms.get(room_id)
    if not room:
        return

    if room['status'] == 'waiting':
        room['players'] = [p for p in room['players'] if p['sid'] != sid]
        if room['creator_sid'] == sid:
            if room['players']:
                room['creator_sid'] = room['players'][0]['sid']
                socketio.emit('uno_you_are_creator', {}, to=room['creator_sid'])
            else:
                del rooms[room_id]
                _emit_lobby(); return
        _emit_room(room_id); _emit_lobby()

    elif room['status'] == 'playing':
        game = room.get('game')
        if game:
            p_idx = game.player_idx_by_sid(sid)
            if p_idx >= 0:
                pdata = game.players[p_idx]
                pdata['is_bot']     = True
                pdata['difficulty'] = 'medium'
                pdata['sid']        = None
                pdata['id']         = f'bot_{uuid.uuid4().hex[:6]}'
                app_log.info(f"[uno] {pdata['username']} replaced by bot in {room_id}")
                socketio.emit('uno_player_left', {'username': pdata['username']},
                              room=_rn(room_id))
                _broadcast_game(room_id)
                if game.cur_idx() == p_idx:
                    _schedule_bot(room_id, delay=1.0)
        room['players'] = [p for p in room['players'] if p['sid'] != sid]

# ── Socket handlers ────────────────────────────────────────────────────────────

@socketio.on('uno_continue_game')
def handle_continue_game(_=None):
    sid     = request.sid
    room_id = uno_sessions.get(sid, {}).get('room_id')
    room    = rooms.get(room_id)
    if not room or room['status'] != 'post_game':
        emit('uno_error', {'message': 'No post-game room to continue.'}); return
    if room['creator_sid'] != sid:
        emit('uno_error', {'message': 'Only the room creator can continue.'}); return

    for s in room['spectators']:
        if s['sid'] and s['sid'] in uno_sessions:
            room['players'].append({'sid': s['sid'], 'username': s['username']})
    room['spectators']      = []
    room['status']          = 'waiting'
    room['game']            = None
    room['ready_continue']  = set()
    for p in room['players']:
        if p['sid'] and p['sid'] in uno_sessions:
            uno_sessions[p['sid']]['room_id'] = room_id

    socketio.emit('uno_return_to_room', {'room_id': room_id}, room=_rn(room_id))
    _emit_room(room_id); _emit_lobby()
    app_log.info(f"[uno] Room {room_id} continued by {uno_sessions[sid]['username']!r}")


@socketio.on('uno_leave_postgame')
def handle_leave_postgame(_=None):
    sid     = request.sid
    room_id = uno_sessions.get(sid, {}).get('room_id')
    room    = rooms.get(room_id)
    if not room or room['status'] != 'post_game':
        return

    room['players']    = [p for p in room['players']    if p['sid'] != sid]
    room['spectators'] = [p for p in room['spectators'] if p['sid'] != sid]
    if sid in uno_sessions:
        uno_sessions[sid]['room_id'] = None
    emit('uno_left_room')

    if room['creator_sid'] == sid:
        human_players = [p for p in room['players'] if p['sid']]
        if human_players:
            room['creator_sid'] = human_players[0]['sid']
            socketio.emit('uno_you_are_creator', {}, to=room['creator_sid'])
            socketio.emit('uno_now_creator',     {}, to=room['creator_sid'])
        else:
            del rooms[room_id]
            _emit_lobby(); return
    _emit_lobby()


@socketio.on('uno_set_username')
def handle_set_username(data):
    sid      = request.sid
    username = (data.get('username') or '').strip()
    if not username:
        emit('uno_username_ack', {'ok': False, 'error': 'Username cannot be empty.'}); return
    if len(username) > 24:
        emit('uno_username_ack', {'ok': False, 'error': 'Max 24 chars.'}); return
    taken = {v['username'] for v in uno_sessions.values()}
    if username in taken and uno_sessions.get(sid, {}).get('username') != username:
        emit('uno_username_ack', {'ok': False, 'error': 'Username already taken.'}); return
    uno_sessions[sid] = {'username': username, 'room_id': None}
    emit('uno_username_ack', {'ok': True, 'username': username})
    _emit_lobby()


@socketio.on('uno_get_lobby')
def handle_get_lobby(_=None):
    sid = request.sid
    if sid in uno_sessions:
        uno_sessions[sid]['room_id'] = None
    _emit_lobby()


@socketio.on('uno_create_room')
def handle_create_room(data):
    sid = request.sid
    if sid not in uno_sessions:
        emit('uno_error', {'message': 'Set username first.'}); return
    title    = (data.get('title') or '').strip() or 'My Room'
    if f.check_profanity(title):
        emit('uno_error', {'message': 'Room title contains disallowed words.'}); return
    uno_type = data.get('uno_type', 'classic')
    privacy  = data.get('privacy', 'public')
    if uno_type not in UNO_TYPES:
        uno_type = 'classic'
    if privacy not in ('public', 'private'):
        privacy = 'public'

    info    = UNO_TYPES[uno_type]
    room_id = uuid.uuid4().hex[:8]
    rooms[room_id] = {
        'id':          room_id,
        'title':       title,
        'uno_type':    uno_type,
        'privacy':     privacy,
        'creator_sid': sid,
        'players':     [{'sid': sid, 'username': uno_sessions[sid]['username']}],
        'bots':        [],
        'spectators':  [],
        'status':      'waiting',
        'game':        None,
        'min_players': info['min_players'],
        'max_players': info['max_players'],
    }
    uno_sessions[sid]['room_id'] = room_id
    socketio.server.enter_room(sid, _rn(room_id))
    emit('uno_room_created', {'room_id': room_id})
    _emit_room(room_id); _emit_lobby()


@socketio.on('uno_join_room')
def handle_join_room(data):
    sid     = request.sid
    room_id = data.get('room_id')
    if sid not in uno_sessions:
        emit('uno_error', {'message': 'Set username first.'}); return
    room = rooms.get(room_id)
    if not room:
        emit('uno_error', {'message': 'Room not found.'}); return
    if room['privacy'] == 'private':
        emit('uno_error', {'message': 'This room is private.'}); return
    if room['status'] != 'waiting':
        emit('uno_error', {'message': 'Game already started.'}); return
    if _total_players(room) >= room['max_players']:
        emit('uno_error', {'message': 'Room is full.'}); return
    if any(p['sid'] == sid for p in room['players']):
        emit('uno_joined_room', {'room_id': room_id}); return
    username = uno_sessions[sid]['username']
    room['players'].append({'sid': sid, 'username': username})
    uno_sessions[sid]['room_id'] = room_id
    socketio.server.enter_room(sid, _rn(room_id))
    socketio.emit('uno_player_joined', {'username': username}, room=_rn(room_id))
    emit('uno_joined_room', {'room_id': room_id})
    _emit_room(room_id); _emit_lobby()


@socketio.on('uno_invite')
def handle_invite(data):
    sid     = request.sid
    room_id = uno_sessions.get(sid, {}).get('room_id')
    target  = data.get('target_sid')
    room    = rooms.get(room_id)
    if not room or room['creator_sid'] != sid or room['status'] != 'waiting':
        emit('uno_error', {'message': 'Cannot invite now.'}); return
    if _total_players(room) >= room['max_players']:
        emit('uno_error', {'message': 'Room is full.'}); return
    if target not in uno_sessions or uno_sessions[target].get('room_id'):
        emit('uno_error', {'message': 'Player not available.'}); return
    socketio.emit('uno_invited', {
        'room_id':          room_id,
        'room_title':       room['title'],
        'creator_username': uno_sessions[sid]['username'],
        'uno_type':         room['uno_type'],
        'type_name':        UNO_TYPES[room['uno_type']]['name'],
    }, to=target)
    emit('uno_invite_sent', {'to': uno_sessions[target]['username']})


@socketio.on('uno_invite_response')
def handle_invite_response(data):
    sid     = request.sid
    room_id = data.get('room_id')
    if not data.get('accept'):
        return
    room = rooms.get(room_id)
    if not room or room['status'] != 'waiting':
        emit('uno_error', {'message': 'Room no longer available.'}); return
    if _total_players(room) >= room['max_players']:
        emit('uno_error', {'message': 'Room is full.'}); return
    if sid not in uno_sessions or uno_sessions[sid].get('room_id'):
        emit('uno_error', {'message': 'You are already in a room.'}); return
    username = uno_sessions[sid]['username']
    room['players'].append({'sid': sid, 'username': username})
    uno_sessions[sid]['room_id'] = room_id
    socketio.server.enter_room(sid, _rn(room_id))
    socketio.emit('uno_player_joined', {'username': username}, room=_rn(room_id))
    emit('uno_joined_room', {'room_id': room_id})
    _emit_room(room_id); _emit_lobby()


@socketio.on('uno_add_bot')
def handle_add_bot(data):
    sid     = request.sid
    room_id = uno_sessions.get(sid, {}).get('room_id')
    room    = rooms.get(room_id)
    if not room or room['creator_sid'] != sid or room['status'] != 'waiting':
        emit('uno_error', {'message': 'Cannot add bot now.'}); return
    if _total_players(room) >= room['max_players']:
        emit('uno_error', {'message': 'Room is full.'}); return
    diff = data.get('difficulty', 'medium')
    if diff not in ('easy', 'medium', 'hard'):
        diff = 'medium'
    used  = {b['username'] for b in room['bots']}
    cands = [n for n in _BOT_NAMES if f'Bot {n}' not in used]
    name  = f'Bot {random.choice(cands) if cands else uuid.uuid4().hex[:4]}'
    room['bots'].append({'id': f'bot_{uuid.uuid4().hex[:6]}',
                         'username': name, 'difficulty': diff})
    _emit_room(room_id)


@socketio.on('uno_remove_bot')
def handle_remove_bot(data):
    sid     = request.sid
    room_id = uno_sessions.get(sid, {}).get('room_id')
    room    = rooms.get(room_id)
    if not room or room['creator_sid'] != sid:
        return
    room['bots'] = [b for b in room['bots'] if b['id'] != data.get('bot_id')]
    _emit_room(room_id)


@socketio.on('uno_kick')
def handle_kick(data):
    sid     = request.sid
    room_id = uno_sessions.get(sid, {}).get('room_id')
    room    = rooms.get(room_id)
    if not room or room['creator_sid'] != sid or room['status'] != 'waiting':
        return
    target = data.get('target_sid')
    if target == sid:
        return
    room['players'] = [p for p in room['players'] if p['sid'] != target]
    if target in uno_sessions:
        uno_sessions[target]['room_id'] = None
    socketio.emit('uno_kicked', {}, to=target)
    socketio.server.leave_room(target, _rn(room_id))
    _emit_room(room_id); _emit_lobby()


@socketio.on('uno_leave_room')
def handle_leave_room(_=None):
    sid      = request.sid
    username = uno_sessions.get(sid, {}).get('username')
    _cleanup_uno(sid)
    if username:
        uno_sessions[sid] = {'username': username, 'room_id': None}
    emit('uno_left_room'); _emit_lobby()


@socketio.on('uno_start_game')
def handle_start_game(_=None):
    sid     = request.sid
    room_id = uno_sessions.get(sid, {}).get('room_id')
    room    = rooms.get(room_id)
    if not room or room['creator_sid'] != sid or room['status'] != 'waiting':
        emit('uno_error', {'message': 'Cannot start game now.'}); return
    if _total_players(room) < room['min_players']:
        emit('uno_error', {'message': f'Need at least {room["min_players"]} players.'}); return

    players_data = [
        {'sid': p['sid'], 'id': p['sid'], 'username': p['username'],
         'is_bot': False, 'difficulty': None}
        for p in room['players']
    ] + [
        {'sid': None, 'id': b['id'], 'username': b['username'],
         'is_bot': True, 'difficulty': b['difficulty']}
        for b in room['bots']
    ]

    game_class   = UNO_TYPES[room['uno_type']]['game_class']
    room['game'] = game_class(players_data)
    room['status'] = 'playing'

    socketio.emit('uno_game_started', {'room_id': room_id}, room=_rn(room_id))
    _broadcast_game(room_id)
    _emit_lobby()

    _first = room['game'].current_player()
    if _first and _first.get('is_bot'):
        _schedule_bot(room_id)

    app_log.info(f"[uno] Room {room_id} started ({_total_players(room)} players, "
                 f"type={room['uno_type']})")


@socketio.on('uno_play_card')
def handle_play_card(data):
    sid     = request.sid
    room_id = uno_sessions.get(sid, {}).get('room_id')
    room    = rooms.get(room_id)
    if not room or room['status'] != 'playing' or not room['game']:
        emit('uno_error', {'message': 'No active game.'}); return
    game       = room['game']
    player_idx = game.player_idx_by_sid(sid)
    if player_idx < 0:
        emit('uno_error', {'message': 'You are not a player.'}); return
    card_idx = data.get('card_idx')
    if card_idx is None:
        emit('uno_error', {'message': 'No card index given.'}); return

    result = game.play_card(player_idx, int(card_idx), data.get('chosen_color'))
    if not result.get('ok'):
        emit('uno_error', {'message': result['error']}); return

    _broadcast_game(room_id)
    _process_result(room_id, game, result)


@socketio.on('uno_draw_card')
def handle_draw_card(_=None):
    sid     = request.sid
    room_id = uno_sessions.get(sid, {}).get('room_id')
    room    = rooms.get(room_id)
    if not room or room['status'] != 'playing' or not room['game']:
        return
    game       = room['game']
    player_idx = game.player_idx_by_sid(sid)
    if player_idx < 0:
        return

    result = game.draw_action(player_idx)
    if not result.get('ok'):
        emit('uno_error', {'message': result['error']}); return

    _broadcast_game(room_id)
    _process_result(room_id, game, result)

    # No Mercy: if the player drew until they found a playable card their turn
    # is NOT over — the updated hand is already broadcast, just let them play.
    # _process_result will have scheduled the bot if found_playable and the
    # current player is a bot.


@socketio.on('uno_choose_color')
def handle_choose_color(data):
    sid     = request.sid
    room_id = uno_sessions.get(sid, {}).get('room_id')
    room    = rooms.get(room_id)
    if not room or not room['game']:
        return
    game       = room['game']
    player_idx = game.player_idx_by_sid(sid)
    if player_idx < 0:
        return
    result = game.choose_color(player_idx, data.get('color', 'red'))
    if not result.get('ok'):
        emit('uno_error', {'message': result['error']}); return
    _broadcast_game(room_id)
    _process_result(room_id, game, result)


@socketio.on('uno_player_action')
def handle_player_action(data):
    """
    Generic handler for any pending player action (swap target, roulette colour,
    or any future game-type-specific choice).

    Client sends: { action_type: 'swap_target', data: { target_idx: N } }
                  { action_type: 'roulette_color', data: { color: 'red' } }
    """
    sid     = request.sid
    room_id = uno_sessions.get(sid, {}).get('room_id')
    room    = rooms.get(room_id)
    if not room or not room['game']:
        return
    game       = room['game']
    player_idx = game.player_idx_by_sid(sid)
    if player_idx < 0:
        return

    action_type = data.get('action_type', '')
    action_data = data.get('data', {})

    result = game.resolve_player_action(player_idx, action_type, action_data)
    if not result.get('ok'):
        emit('uno_error', {'message': result['error']}); return

    _broadcast_game(room_id)
    _process_result(room_id, game, result)

@socketio.on('uno_get_rules')
def handle_get_rules(data):
    """Return rules + card descriptions for a given game type."""
    uno_type   = data.get('uno_type', 'classic')
    info       = UNO_TYPES.get(uno_type)
    if not info:
        emit('uno_rules', {'rules': [], 'card_descriptions': {}, 'name': ''}); return
    game_class = info['game_class']
    # Instantiate a minimal dummy just to call the hooks
    # (hooks don't use self state so this is safe)
    dummy      = object.__new__(game_class)
    dummy.__class__ = game_class
    emit('uno_rules', {
        'name':              info['name'],
        'rules':             game_class.rules_html(dummy),
        'card_descriptions': game_class.card_descriptions(dummy),
    })

@socketio.on('uno_leave_route')
def handle_leave_route(_=None):
    _cleanup_uno(request.sid)

@socketio.on('disconnect')
def _uno_disconnect_shim():
    _cleanup_uno(request.sid)