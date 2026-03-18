# socket_events/slither_events.py
"""
Authoritative slither.io-style game server.

World: circular, radius scales with player count.
Snake: chain simulation — each segment follows the one ahead
       at a fixed distance, giving smooth organic movement.
Tick:  20 Hz background thread (daemon).
"""

import math
import time
import random
import threading

from socketio_instance import socketio
from flask import request
from glob_vars import app_log, error_log

# ── Constants ─────────────────────────────────────────────────
TICK_HZ        = 20
BASE_SPEED     = 3.5        # px / tick
BOOST_SPEED    = 7.0
BOOST_DRAIN    = 0.18       # segments lost per tick while boosting
SEGMENT_DIST   = 15         # px between segment centres
INIT_SEGS      = 22         # starting segment count
MIN_SEGS       = 10
MAX_SEGS       = 700
TURN_RATE      = 0.11       # max radians turned per tick
EAT_R          = 17         # food collection radius
KILL_R         = 11         # head-vs-body kill radius
BASE_WORLD_R   = 2200
WORLD_R_PER_P  = 160
MAX_WORLD_R    = 5500
FOOD_DENSITY   = 0.000032   # food = density × π × r²
MAX_FOOD       = 420
SEND_SEGS_CAP  = 140        # max segments sent per snake per tick

# ── State ─────────────────────────────────────────────────────
_players : dict = {}   # sid → player
_food    : dict = {}   # fid → food item
_fid     : int  = 0
_lock           = threading.Lock()
_running : bool = False

# ── Helpers ───────────────────────────────────────────────────

def _world_r() -> float:
    return min(BASE_WORLD_R + len(_players) * WORLD_R_PER_P, MAX_WORLD_R)


def _mk_food(x=None, y=None, color=None, size=None) -> dict:
    global _fid
    _fid += 1
    r = _world_r()
    if x is None:
        a    = random.uniform(0, 2 * math.pi)
        dist = random.uniform(0, r * 0.93)
        x, y = math.cos(a) * dist, math.sin(a) * dist
    palette = [
        '#ff4d6a','#00d4ff','#39d98a','#f5a623',
        '#a78bfa','#f472b6','#ffec5c','#ff6b35',
        '#7fdbff','#3ddc97','#ffd700','#c084fc',
    ]
    return {
        'id':    _fid,
        'x':     round(x, 2),
        'y':     round(y, 2),
        'color': color or random.choice(palette),
        'size':  round(size or random.uniform(6, 13), 1),
        'phase': round(random.uniform(0, 6.28), 2),
    }


def _spawn(sid: str, username: str, color: str):
    r      = _world_r() * 0.6
    ang    = random.uniform(0, 2 * math.pi)
    cx     = math.cos(ang) * random.uniform(0, r)
    cy     = math.sin(ang) * random.uniform(0, r)
    facing = random.uniform(0, 2 * math.pi)
    segs   = [
        [round(cx - math.cos(facing) * i * SEGMENT_DIST, 2),
         round(cy - math.sin(facing) * i * SEGMENT_DIST, 2)]
        for i in range(INIT_SEGS)
    ]
    _players[sid] = {
        'sid':      sid,
        'username': username,
        'color':    color,
        'segs':     segs,
        'angle':    facing,
        't_angle':  facing,
        'boosting': False,
        'alive':    True,
        'score':    0,
        'grow':     0.0,
    }


# ── Game tick ──────────────────────────────────────────────────

def _tick():
    global _fid
    with _lock:
        if not _players:
            return

        wr      = _world_r()
        wr2     = wr * wr
        pending_food : dict = {}
        dead         : set  = set()

        for sid, p in list(_players.items()):
            if not p['alive']:
                continue

            segs = p['segs']

            # ── Steer ─────────────────────────────────────────
            da = p['t_angle'] - p['angle']
            while da >  math.pi: da -= 2 * math.pi
            while da < -math.pi: da += 2 * math.pi
            p['angle'] += max(-TURN_RATE, min(TURN_RATE, da))

            # ── Move head ─────────────────────────────────────
            speed = BOOST_SPEED if p['boosting'] else BASE_SPEED
            hx    = segs[0][0] + math.cos(p['angle']) * speed
            hy    = segs[0][1] + math.sin(p['angle']) * speed

            # ── Boundary ──────────────────────────────────────
            if hx * hx + hy * hy >= wr2:
                dead.add(sid)
                continue

            # ── Propagate chain ───────────────────────────────
            segs[0][0], segs[0][1] = hx, hy
            for i in range(1, len(segs)):
                ax, ay = segs[i - 1]
                bx, by = segs[i]
                dx, dy = bx - ax, by - ay
                d2     = dx * dx + dy * dy
                if d2 > SEGMENT_DIST * SEGMENT_DIST:
                    inv = SEGMENT_DIST / math.sqrt(d2)
                    segs[i][0] = round(ax + dx * inv, 2)
                    segs[i][1] = round(ay + dy * inv, 2)

            # ── Boost drain ───────────────────────────────────
            if p['boosting']:
                if len(segs) > MIN_SEGS + 3:
                    p['grow'] -= BOOST_DRAIN
                    if p['grow'] <= -1.0:
                        p['grow'] += 1.0
                        tx, ty = segs[-1]
                        fi = _mk_food(
                            x=tx + random.uniform(-4, 4),
                            y=ty + random.uniform(-4, 4),
                            color=p['color'], size=7)
                        pending_food[fi['id']] = fi
                        if len(segs) > MIN_SEGS:
                            segs.pop()
                else:
                    p['boosting'] = False

            # ── Grow ──────────────────────────────────────────
            while p['grow'] >= 1.0 and len(segs) < MAX_SEGS:
                p['grow'] -= 1.0
                segs.append(list(segs[-1]))

            # ── Eat food ──────────────────────────────────────
            eaten = []
            for fid, f in _food.items():
                dx = hx - f['x']
                dy = hy - f['y']
                if dx * dx + dy * dy < (EAT_R + f['size'] * 0.4) ** 2:
                    p['grow']  += f['size'] * 0.25
                    p['score'] += max(1, int(f['size']))
                    eaten.append(fid)
            for fid in eaten:
                del _food[fid]

            # ── Collision vs other snakes ──────────────────────
            r2 = KILL_R * KILL_R
            for osid, op in _players.items():
                if osid == sid or not op['alive']:
                    continue
                for bx, by in op['segs']:
                    if (hx - bx) ** 2 + (hy - by) ** 2 < r2:
                        dead.add(sid)
                        break
                if sid in dead:
                    break

        # ── Deaths ────────────────────────────────────────────
        for sid in dead:
            p = _players.get(sid)
            if not p or not p['alive']:
                continue
            p['alive'] = False
            for i, (fx, fy) in enumerate(p['segs']):
                if i % 2 == 0:
                    fi = _mk_food(
                        x=fx + random.uniform(-6, 6),
                        y=fy + random.uniform(-6, 6),
                        color=p['color'],
                        size=random.uniform(8, 18))
                    pending_food[fi['id']] = fi
            socketio.emit('slither_died', {'score': p['score']}, to=sid)
            app_log.info(f"[slither] {p['username']!r} died (score {p['score']})")

        _food.update(pending_food)

        # ── Refill ambient food ────────────────────────────────
        target = min(int(math.pi * wr * wr * FOOD_DENSITY), MAX_FOOD)
        deficit = target - len(_food)
        if deficit > 0:
            for _ in range(min(deficit, 10)):
                fi = _mk_food()
                _food[fi['id']] = fi

        # ── Broadcast ─────────────────────────────────────────
        players_out = []
        for p in _players.values():
            if p['alive']:
                players_out.append({
                    'sid':      p['sid'],
                    'username': p['username'],
                    'color':    p['color'],
                    'segs':     p['segs'][:SEND_SEGS_CAP],
                    'boosting': p['boosting'],
                    'score':    p['score'],
                })

        socketio.emit('slither_state', {
            'players': players_out,
            'food':    list(_food.values()),
            'world_r': round(wr),
        })


# ── Game loop ──────────────────────────────────────────────────

def _start_loop():
    global _running
    if _running:
        return
    _running = True
    interval = 1.0 / TICK_HZ

    def _loop():
        while True:
            t0 = time.perf_counter()
            try:
                _tick()
            except Exception as exc:
                error_log.error(f"[slither] tick error: {exc}")
            gap = interval - (time.perf_counter() - t0)
            if gap > 0:
                time.sleep(gap)

    threading.Thread(target=_loop, daemon=True, name='slither-loop').start()
    app_log.info('[slither] game loop started')


# ── Public cleanup (called by global_events disconnect) ────────

def cleanup_sid(sid: str):
    with _lock:
        _players.pop(sid, None)


# ── Socket events ──────────────────────────────────────────────

@socketio.on('slither_join')
def on_join(data):
    sid      = request.sid
    username = str(data.get('username', 'Snake'))[:20].strip() or 'Snake'
    color    = str(data.get('color', '#00d4ff'))

    with _lock:
        _spawn(sid, username, color)
        socketio.emit('slither_init', {
            'food':    list(_food.values()),
            'world_r': round(_world_r()),
            'my_sid':  sid,
        }, to=sid)

    app_log.info(f"[slither] {username!r} joined ({sid})")
    _start_loop()


@socketio.on('slither_input')
def on_input(data):
    sid = request.sid
    with _lock:
        p = _players.get(sid)
        if p and p['alive']:
            try:
                p['t_angle']  = float(data['angle'])
                p['boosting'] = bool(data.get('boost', False))
            except (KeyError, TypeError, ValueError):
                pass


@socketio.on('slither_leave')
def on_leave(_data=None):
    sid = request.sid
    with _lock:
        _players.pop(sid, None)
    app_log.info(f"[slither] {sid} left")


@socketio.on('disconnect')
def on_dc():
    # Flask-SocketIO supports multiple disconnect handlers — this
    # runs alongside global_events.on_global_disconnect
    sid = request.sid
    with _lock:
        _players.pop(sid, None)