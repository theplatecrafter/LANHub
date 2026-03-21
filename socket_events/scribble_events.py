# socket_events/scribble_events.py
"""
Scribble.io clone — authoritative server.
All tunable constants are read from configvars.json via config module.
"""

import random
import threading
import time
import uuid

from flask import request
from flask_socketio import join_room as sio_join, leave_room as sio_leave

from socketio_instance import socketio
from glob_vars import app_log, error_log
import config
import functions as f


# ── Config accessor ───────────────────────────────────────────

def _cfg():
    return {
        'MAX_PLAYERS':    int(  getattr(config, 'SCRIBBLE_MAX_PLAYERS',   15)),
        'MIN_START':      int(  getattr(config, 'SCRIBBLE_MIN_START',      2)),
        'ROUND_SECS':     int(  getattr(config, 'SCRIBBLE_ROUND_SECS',    80)),
        'CHOOSE_SECS':    int(  getattr(config, 'SCRIBBLE_CHOOSE_SECS',   15)),
        'ROUNDEND_SECS':  int(  getattr(config, 'SCRIBBLE_ROUNDEND_SECS',  6)),
        'GAMEEND_SECS':   int(  getattr(config, 'SCRIBBLE_GAMEEND_SECS',  10)),
        'NUM_ROUNDS':     int(  getattr(config, 'SCRIBBLE_NUM_ROUNDS',     3)),
        'HINT_INTERVAL':  int(  getattr(config, 'SCRIBBLE_HINT_INTERVAL', 22)),
        'WORD_CHOICES':   int(  getattr(config, 'SCRIBBLE_WORD_CHOICES',   3)),
    }


# ── Word list ─────────────────────────────────────────────────
WORDS = [
    "apple","banana","elephant","rainbow","guitar","bicycle","mountain",
    "umbrella","dolphin","telescope","volcano","lighthouse","sandwich","castle",
    "submarine","tornado","penguin","cactus","snowflake","compass","hammock",
    "backpack","butterfly","waterfall","pyramid","rocket","igloo","scissors",
    "crown","anchor","trophy","lantern","magnifying glass","parachute","windmill",
    "bridge","caterpillar","skyscraper","mushroom","treasure","ghost","wizard",
    "dragon","spaceship","mermaid","pirate","robot","ninja","superhero",
    "blizzard","earthquake","hurricane","avalanche",
    "pizza","hamburger","sushi","taco","waffle","pretzel","donut",
    "popcorn","ice cream","cupcake","smoothie","lemonade","pancake","spaghetti",
    "lion","tiger","giraffe","crocodile","kangaroo","flamingo","octopus",
    "porcupine","armadillo","platypus","chameleon","jellyfish","starfish",
    "rhinoceros","chimpanzee","parrot","peacock","toucan",
    "basketball","football","tennis","volleyball","skateboard",
    "surfboard","snowboard","bowling","archery","fencing","gymnastics",
    "piano","trumpet","violin","saxophone","drumset","harp","accordion",
    "camping","fishing","hiking","kayaking","rock climbing","scuba diving",
    "fireworks","carnival","circus","rollercoaster","ferris wheel","merry-go-round",
    "sunset","aurora","eclipse","meteor","black hole","satellite",
    "library","museum","hospital","factory","stadium","airport",
    "toolbox","wrench","hammer","screwdriver","drill","ladder","blueprint",
    "ring","necklace","bracelet","earring","mirror","perfume",
    "thunder","lightning","fog","hail","drizzle","monsoon",
    "chess","checkers","dominoes","jigsaw puzzle","rubiks cube","yo-yo","kite",
    "candle","campfire","bonfire","flashlight","spotlight",
    "map","compass","hourglass","binoculars","microscope","thermometer",
    "clock","calendar","alarm","stopwatch","sundial","metronome",
    "backpack","suitcase","briefcase","purse","wallet","keychain","glasses",
    "snowman","scarecrow","totem pole","gargoyle","statue","fountain","arch",
    "sleeping bag","tent","canteen",
    "palette","paintbrush","easel","sculpture","pottery","origami","mosaic",
    "detective","fingerprint","handcuffs","badge","wanted poster",
    "witch","cauldron","broomstick","magic wand","crystal ball","spell book",
    "treasure map","chest","steering wheel","sailboat",
    "hotdog","cotton candy","funnel cake","candy apple",
    "whirlpool","quicksand","trapdoor","maze","labyrinth",
]

def _pick_words(n: int) -> list[str]:
    return random.sample(WORDS, min(n, len(WORDS)))


# ── Room management ───────────────────────────────────────────
_rooms    : dict[str, dict] = {}
_sid_room : dict[str, str]  = {}
_lock = threading.Lock()


def _new_room() -> dict:
    rid = str(uuid.uuid4())[:8]
    room = {
        'id':           rid,
        'players':      {},
        'state':        'waiting',
        'round':        0,
        'turn':         0,
        'turn_order':   [],
        'drawer':       None,
        'word':         None,
        'word_masked':  None,
        'canvas':       [],
        'chat':         [],
        'timer_end':    0,
        'hints_given':  0,
        '_timer':       None,
        '_round_timer': None,
    }
    _rooms[rid] = room
    app_log.info(f"[scribble] created room {rid}")
    return room


def _find_or_create_room(c: dict) -> dict:
    for r in list(_rooms.values()):
        if r['state'] != 'game_end' and len(r['players']) < c['MAX_PLAYERS']:
            return r
    return _new_room()


def _cancel_timer(room: dict):
    t = room.get('_timer')
    if t and t.is_alive():
        t.cancel()
    room['_timer'] = None


def _sched(room: dict, secs: float, fn):
    _cancel_timer(room)
    t = threading.Timer(secs, fn)
    t.daemon = True
    t.start()
    room['_timer'] = t


def _broadcast(room: dict, event: str, data: dict):
    socketio.emit(event, data, room=room['id'])


# ── Mask / hint ───────────────────────────────────────────────

def _mask(word: str) -> str:
    return ' '.join('_' * len(w) for w in word.split())


def _hint(word: str, n: int) -> str:
    letters  = [(i, c) for i, c in enumerate(word) if c not in (' ', '-')]
    revealed = set(random.sample([i for i, _ in letters], min(n, len(letters))))
    return ''.join(
        c if (c in (' ', '-') or i in revealed) else '_'
        for i, c in enumerate(word)
    )


# ── Game flow ─────────────────────────────────────────────────

def _room_state_payload(room: dict, sid: str | None = None) -> dict:
    players = []
    for s, p in room['players'].items():
        players.append({
            'sid':       s,
            'name':      p['name'],
            'score':     p['score'],
            'guessed':   p['guessed'],
            'is_drawer': s == room['drawer'],
        })
    players.sort(key=lambda p: -p['score'])

    word_display = None
    if room['state'] == 'drawing':
        word_display = room['word'] if sid == room['drawer'] else room['word_masked']
    elif room['state'] == 'round_end':
        word_display = room['word']

    return {
        'room_id':      room['id'],
        'state':        room['state'],
        'players':      players,
        'drawer_sid':   room['drawer'],
        'drawer_name':  room['players'][room['drawer']]['name']
                        if room['drawer'] and room['drawer'] in room['players'] else None,
        'word_display': word_display,
        'word_len':     len(room['word']) if room['word'] else 0,
        'round':        room['round'],
        'total_rounds': _cfg()['NUM_ROUNDS'],
        'timer_end':    room['timer_end'],
        'chat':         room['chat'][-40:],
        'num_players':  len(room['players']),
        'turn':         room['turn'],
        'total_turns':  len(room['turn_order']) * _cfg()['NUM_ROUNDS']
                        if room['turn_order'] else 0,
    }


def _push_state(room: dict):
    for sid in list(room['players']):
        socketio.emit('scr_state', _room_state_payload(room, sid), to=sid)


def _start_choosing(room: dict):
    c = _cfg()
    if room['state'] == 'game_end':
        return
    room['state']       = 'choosing'
    room['canvas']      = []
    room['hints_given'] = 0

    for p in room['players'].values():
        p['guessed'] = False

    turn_idx   = room['turn'] % len(room['turn_order'])
    drawer_sid = room['turn_order'][turn_idx]

    attempts = 0
    while drawer_sid not in room['players']:
        room['turn'] += 1
        attempts     += 1
        if attempts >= len(room['turn_order']):
            _end_game(room)
            return
        turn_idx   = room['turn'] % len(room['turn_order'])
        drawer_sid = room['turn_order'][turn_idx]

    room['drawer']    = drawer_sid
    room['word']      = None
    room['timer_end'] = time.time() + c['CHOOSE_SECS']

    words = _pick_words(c['WORD_CHOICES'])
    socketio.emit('scr_choose_word', {'words': words, 'secs': c['CHOOSE_SECS']}, to=drawer_sid)

    for sid in room['players']:
        socketio.emit('scr_state', _room_state_payload(room, sid), to=sid)

    _broadcast(room, 'scr_chat_msg', {
        'sys':  True,
        'text': f"🎨  {room['players'][drawer_sid]['name']} is choosing a word…",
    })

    def _auto_pick():
        with _lock:
            r = _rooms.get(room['id'])
            if r and r['state'] == 'choosing' and r['drawer'] == drawer_sid:
                _start_drawing(r, random.choice(words))

    _sched(room, c['CHOOSE_SECS'], _auto_pick)


def _start_drawing(room: dict, word: str):
    c = _cfg()
    room['state']       = 'drawing'
    room['word']        = word
    room['word_masked'] = _mask(word)
    room['hints_given'] = 0
    room['timer_end']   = time.time() + c['ROUND_SECS']

    _broadcast(room, 'scr_canvas_clear', {})
    _push_state(room)

    drawer_name = room['players'].get(room['drawer'], {}).get('name', '?')
    _broadcast(room, 'scr_chat_msg', {
        'sys':  True,
        'text': f"✏️  {drawer_name} is drawing!  ({len(word)} letters)",
    })

    def _give_hint(n):
        def _fn():
            with _lock:
                r = _rooms.get(room['id'])
                if not r or r['state'] != 'drawing' or r['word'] != word:
                    return
                r['hints_given'] = n
                r['word_masked'] = _hint(word, n)
                for sid in r['players']:
                    if sid != r['drawer']:
                        socketio.emit('scr_hint', {'masked': r['word_masked']}, to=sid)
                max_hints = max(1, len(word.replace(' ', '')) // 3)
                if n < max_hints:
                    _sched(r, _cfg()['HINT_INTERVAL'], _give_hint(n + 1))
        return _fn

    _sched(room, c['HINT_INTERVAL'], _give_hint(1))

    rt = room.get('_round_timer')
    if rt and rt.is_alive():
        rt.cancel()

    def _round_expire():
        with _lock:
            r = _rooms.get(room['id'])
            if r and r['state'] == 'drawing' and r['word'] == word:
                _end_round(r)

    t = threading.Timer(c['ROUND_SECS'], _round_expire)
    t.daemon = True
    t.start()
    room['_round_timer'] = t


def _end_round(room: dict):
    c = _cfg()
    _cancel_timer(room)
    rt = room.get('_round_timer')
    if rt and rt.is_alive():
        rt.cancel()
    room['_round_timer'] = None
    room['state'] = 'round_end'

    correct_count = sum(1 for p in room['players'].values() if p['guessed'])
    drawer = room['players'].get(room['drawer'])
    if drawer:
        drawer['score'] += correct_count * 40

    _broadcast(room, 'scr_chat_msg', {
        'sys':  True,
        'text': f"⏱  Time's up! The word was: {room['word']}",
    })
    _push_state(room)

    def _next():
        with _lock:
            r = _rooms.get(room['id'])
            if not r:
                return
            r['turn'] += 1
            total = len(r['turn_order']) * _cfg()['NUM_ROUNDS']
            if r['turn'] >= total:
                _end_game(r)
            else:
                r['round'] = r['turn'] // len(r['turn_order'])
                _start_choosing(r)

    _sched(room, c['ROUNDEND_SECS'], _next)


def _end_game(room: dict):
    c = _cfg()
    _cancel_timer(room)
    room['state']     = 'game_end'
    room['timer_end'] = time.time() + c['GAMEEND_SECS']
    _push_state(room)
    _broadcast(room, 'scr_chat_msg', {'sys': True, 'text': '🏆  Game over! Final scores:'})

    def _reset():
        with _lock:
            r = _rooms.get(room['id'])
            if not r:
                return
            if len(r['players']) >= _cfg()['MIN_START']:
                for p in r['players'].values():
                    p['score'] = 0; p['guessed'] = False
                r['turn']       = 0
                r['round']      = 0
                r['turn_order'] = list(r['players'].keys())
                random.shuffle(r['turn_order'])
                r['state'] = 'waiting'
                _start_choosing(r)
            else:
                r['state'] = 'waiting'
                r['turn']  = 0
                r['round'] = 0
                _push_state(r)

    _sched(room, c['GAMEEND_SECS'], _reset)


def _maybe_start(room: dict):
    c = _cfg()
    if room['state'] == 'waiting' and len(room['players']) >= c['MIN_START']:
        room['turn']       = 0
        room['round']      = 0
        room['turn_order'] = list(room['players'].keys())
        random.shuffle(room['turn_order'])
        _broadcast(room, 'scr_chat_msg', {'sys': True, 'text': '🚀  Enough players — game starting!'})
        _start_choosing(room)


def _try_all_guessed(room: dict):
    non_drawers = [s for s in room['players'] if s != room['drawer']]
    if non_drawers and all(room['players'][s]['guessed'] for s in non_drawers):
        _end_round(room)


def _close_guess(guess: str, word: str) -> bool:
    if abs(len(guess) - len(word)) > 2:
        return False
    if len(guess) == len(word):
        return sum(a != b for a, b in zip(guess, word)) == 1
    return False


# ── Socket events ──────────────────────────────────────────────

# NEW helper — insert just above on_join
def _cleanup_player(sid: str) -> None:
    """Remove a player from their room, handle drawer disconnect, clean up empty rooms."""
    rid  = _sid_room.pop(sid, None)
    room = _rooms.get(rid) if rid else None
    if not room:
        return

    pname = room['players'].pop(sid, {}).get('name', '?')
    # Remove from turn order immediately so they never get picked as drawer
    room['turn_order'] = [s for s in room['turn_order'] if s in room['players']]

    try:
        sio_leave(rid)
    except Exception:
        pass

    if not room['players']:
        _cancel_timer(room)
        rt = room.get('_round_timer')
        if rt and rt.is_alive():
            rt.cancel()
        del _rooms[rid]
        app_log.info(f"[scribble] room {rid} deleted (empty after {pname!r} left)")
        return

    _broadcast(room, 'scr_chat_msg', {'sys': True, 'text': f"👋  {pname} left."})
    _push_state(room)   # immediately update everyone's player list

    c = _cfg()
    if room['drawer'] == sid:
        _cancel_timer(room)
        rt = room.get('_round_timer')
        if rt and rt.is_alive():
            rt.cancel()
        _broadcast(room, 'scr_chat_msg',
                   {'sys': True, 'text': '🎨  Drawer disconnected — skipping turn.'})
        if len(room['players']) >= c['MIN_START']:
            room['turn'] += 1
            if room['turn_order']:
                _start_choosing(room)
            else:
                room['state'] = 'waiting'
                _push_state(room)
        else:
            room['state'] = 'waiting'
            _push_state(room)
    else:
        if room['state'] == 'drawing':
            _try_all_guessed(room)
        # If below min players mid-game, pause back to waiting
        if len(room['players']) < c['MIN_START'] and room['state'] in ('drawing', 'choosing'):
            _cancel_timer(room)
            rt = room.get('_round_timer')
            if rt and rt.is_alive():
                rt.cancel()
            _broadcast(room, 'scr_chat_msg',
                       {'sys': True, 'text': '⏸  Not enough players — pausing game.'})
            room['state'] = 'waiting'
            _push_state(room)

@socketio.on('scribble_join')
def on_join(data):
    sid      = request.sid
    username = str(data.get('username', 'Player'))[:20].strip() or 'Player'
    if f.check_profanity(username):
       socketio.emit('scr_username_err',
                     {'error': 'Username contains disallowed words.'}, to=sid)
       return
    c        = _cfg()

    with _lock:
        if sid in _sid_room:
            return
        room = _find_or_create_room(c)
        rid  = room['id']
        room['players'][sid] = {'name': username, 'score': 0, 'guessed': False}
        _sid_room[sid] = rid
        sio_join(rid)

        app_log.info(f"[scribble] {username!r} joined room {rid} ({len(room['players'])}/{c['MAX_PLAYERS']})")

        if room['canvas']:
            socketio.emit('scr_canvas_replay', {'events': room['canvas']}, to=sid)

        # Add to turn order if a game is already in progress
        # (they'll be eligible to draw from the next turn onwards)
        if room['state'] in ('drawing', 'choosing', 'round_end') \
                and sid not in room['turn_order']:
            room['turn_order'].append(sid)

        _broadcast(room, 'scr_chat_msg', {
            'sys':  True,
            'text': f"👤  {username} joined ({len(room['players'])}/{c['MAX_PLAYERS']})",
        })

        # Broadcast to ALL players so the new player appears in everyone's sidebar
        _push_state(room)

        # Resume a paused game if we now have enough players again
        if room['state'] == 'waiting' and len(room['players']) >= c['MIN_START']:
            _broadcast(room, 'scr_chat_msg',
                       {'sys': True, 'text': '🚀  Enough players — game starting!'})
            room['turn']       = 0
            room['round']      = 0
            room['turn_order'] = list(room['players'].keys())
            random.shuffle(room['turn_order'])
            _start_choosing(room)
        elif room['state'] == 'waiting':
            pass   # still waiting, _push_state above already told everyone
        # If mid-game, nothing else needed — player is now in the list and turn_order

@socketio.on('scribble_draw')
def on_draw(data):
    sid = request.sid
    with _lock:
        rid  = _sid_room.get(sid)
        room = _rooms.get(rid) if rid else None
        if not room or room['state'] != 'drawing' or room['drawer'] != sid:
            return
        event = {
            'type':   'stroke',
            'color':  str(data.get('color', '#000'))[:9],
            'size':   max(1, min(80, int(data.get('size', 5)))),
            'points': [[round(float(x), 2), round(float(y), 2)]
                       for x, y in (data.get('points') or [])[:500]],
        }
        room['canvas'].append(event)
        _broadcast(room, 'scr_canvas_stroke', event)


@socketio.on('scribble_fill')
def on_fill(data):
    sid = request.sid
    with _lock:
        rid  = _sid_room.get(sid)
        room = _rooms.get(rid) if rid else None
        if not room or room['state'] != 'drawing' or room['drawer'] != sid:
            return
        event = {
            'type':  'fill',
            'x':     round(float(data.get('x', 0)), 2),
            'y':     round(float(data.get('y', 0)), 2),
            'color': str(data.get('color', '#fff'))[:9],
        }
        room['canvas'].append(event)
        _broadcast(room, 'scr_canvas_fill', event)


@socketio.on('scribble_undo')
def on_undo(_data=None):
    sid = request.sid
    with _lock:
        rid  = _sid_room.get(sid)
        room = _rooms.get(rid) if rid else None
        if not room or room['state'] != 'drawing' or room['drawer'] != sid:
            return
        if room['canvas']:
            room['canvas'].pop()
        _broadcast(room, 'scr_canvas_replay', {'events': room['canvas']})


@socketio.on('scribble_clear_canvas')
def on_clear_canvas(_data=None):
    sid = request.sid
    with _lock:
        rid  = _sid_room.get(sid)
        room = _rooms.get(rid) if rid else None
        if not room or room['state'] != 'drawing' or room['drawer'] != sid:
            return
        room['canvas'] = []
        _broadcast(room, 'scr_canvas_clear', {})


@socketio.on('scribble_choose')
def on_choose(data):
    sid  = request.sid
    word = str(data.get('word', '')).strip().lower()
    with _lock:
        rid  = _sid_room.get(sid)
        room = _rooms.get(rid) if rid else None
        if not room or room['state'] != 'choosing' or room['drawer'] != sid:
            return
        if word not in [w.lower() for w in WORDS]:
            return
        _cancel_timer(room)
        _start_drawing(room, word)


@socketio.on('scribble_guess')
def on_guess(data):
    sid  = request.sid
    text = str(data.get('text', '')).strip()
    if not text:
        return

    with _lock:
        rid    = _sid_room.get(sid)
        room   = _rooms.get(rid) if rid else None
        if not room:
            return
        player = room['players'].get(sid)
        if not player:
            return
        c = _cfg()

        if sid == room['drawer']:
            msg = {'sid': sid, 'name': player['name'], 'text': text, 'sys': False, 'correct': False}
            room['chat'].append(msg)
            _broadcast(room, 'scr_chat_msg', msg)
            return

        if player['guessed']:
            msg = {'sid': sid, 'name': player['name'], 'text': '...', 'sys': False, 'correct': False}
            room['chat'].append(msg)
            _broadcast(room, 'scr_chat_msg', msg)
            return

        if room['state'] == 'drawing' and room['word']:
            if text.lower() == room['word'].lower():
                player['guessed'] = True
                elapsed = c['ROUND_SECS'] - max(0, room['timer_end'] - time.time())
                pts     = max(50, 500 - int(elapsed / c['ROUND_SECS'] * 450))
                first   = sum(1 for p in room['players'].values() if p['guessed']) == 1
                if first:
                    pts += 100
                player['score'] += pts
                socketio.emit('scr_correct', {'pts': pts}, to=sid)
                msg = {'sys': True, 'text': f"✅  {player['name']} guessed correctly! (+{pts})", 'correct': True}
                room['chat'].append(msg)
                _broadcast(room, 'scr_chat_msg', msg)
                _push_state(room)
                _try_all_guessed(room)
                return

            if _close_guess(text.lower(), room['word'].lower()):
                socketio.emit('scr_chat_msg', {
                    'sys': True, 'text': f"🔥  {player['name']} is very close!",
                }, to=sid)

        display = text
        if room['state'] == 'drawing' and room['word']:
            if room['word'].lower() in text.lower():
                display = '⬛' * len(text)

        msg = {'sid': sid, 'name': player['name'], 'text': display, 'sys': False, 'correct': False}
        room['chat'].append(msg)
        _broadcast(room, 'scr_chat_msg', msg)


@socketio.on('disconnect')
def on_dc():
    with _lock:
        _cleanup_player(request.sid)

@socketio.on('scribble_leave_route')
def on_leave_route(_=None):
    """Fired by the client on pagehide/beforeunload — same cleanup as disconnect."""
    with _lock:
        _cleanup_player(request.sid)