# socket_events/slither_events.py
"""
Authoritative slither.io-style game server.
All tunable constants are read from configvars.json via config module.
"""

import math
import random
import threading
import time

from socketio_instance import socketio
from flask import request
from glob_vars import app_log, error_log
import config


# ── Config accessors (re-read each tick / call so live edits take effect) ─────

def _cfg():
    """Return a snapshot of slither config values from the live config module."""
    return {
        'TICK_HZ':       float(getattr(config, 'SLITHER_TICK_HZ',        20)),
        'BASE_SPEED':    float(getattr(config, 'SLITHER_BASE_SPEED',      3.5)),
        'BOOST_SPEED':   float(getattr(config, 'SLITHER_BOOST_SPEED',     7.0)),
        'BOOST_DRAIN':   float(getattr(config, 'SLITHER_BOOST_DRAIN',     0.18)),
        'SEG_DIST':      float(getattr(config, 'SLITHER_SEGMENT_DIST',    15)),
        'INIT_SEGS':     int(  getattr(config, 'SLITHER_INIT_SEGS',       22)),
        'MIN_SEGS':      int(  getattr(config, 'SLITHER_MIN_SEGS',        10)),
        'MAX_SEGS':      int(  getattr(config, 'SLITHER_MAX_SEGS',        700)),
        'TURN_RATE':     float(getattr(config, 'SLITHER_TURN_RATE',       0.11)),
        'EAT_R':         float(getattr(config, 'SLITHER_EAT_RADIUS',      17)),
        'KILL_R':        float(getattr(config, 'SLITHER_KILL_RADIUS',     11)),
        'BASE_WORLD_R':  float(getattr(config, 'SLITHER_BASE_WORLD_R',    2200)),
        'WORLD_R_PP':    float(getattr(config, 'SLITHER_WORLD_R_PER_PLAYER', 160)),
        'MAX_WORLD_R':   float(getattr(config, 'SLITHER_MAX_WORLD_R',     5500)),
        'FOOD_DENSITY':  float(getattr(config, 'SLITHER_FOOD_DENSITY',    0.000032)),
        'MAX_FOOD':      int(  getattr(config, 'SLITHER_MAX_FOOD',        420)),
        'SEGS_CAP':      int(  getattr(config, 'SLITHER_SEND_SEGS_CAP',   140)),
    }


# ── State ─────────────────────────────────────────────────────
_players : dict = {}
_food    : dict = {}
_fid     : int  = 0
_lock           = threading.Lock()
_running : bool = False


# ── Helpers ───────────────────────────────────────────────────

def _world_r(c: dict) -> float:
    return min(c['BASE_WORLD_R'] + len(_players) * c['WORLD_R_PP'], c['MAX_WORLD_R'])


def _mk_food(c: dict, x=None, y=None, color=None, size=None) -> dict:
    global _fid
    _fid += 1
    wr = _world_r(c)
    if x is None:
        a    = random.uniform(0, 2 * math.pi)
        dist = random.uniform(0, wr * 0.93)
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


def _spawn(sid: str, username: str, color: str, c: dict):
    r      = _world_r(c) * 0.6
    ang    = random.uniform(0, 2 * math.pi)
    cx     = math.cos(ang) * random.uniform(0, r)
    cy     = math.sin(ang) * random.uniform(0, r)
    facing = random.uniform(0, 2 * math.pi)
    segs   = [
        [round(cx - math.cos(facing) * i * c['SEG_DIST'], 2),
         round(cy - math.sin(facing) * i * c['SEG_DIST'], 2)]
        for i in range(c['INIT_SEGS'])
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


# ── Game tick ─────────────────────────────────────────────────

def _tick():
    global _fid
    c = _cfg()  # read config snapshot once per tick

    with _lock:
        if not _players:
            return

        wr      = _world_r(c)
        wr2     = wr * wr
        pending : dict = {}
        dead    : set  = set()

        for sid, p in list(_players.items()):
            if not p['alive']:
                continue

            segs = p['segs']

            # Steer
            da = p['t_angle'] - p['angle']
            while da >  math.pi: da -= 2 * math.pi
            while da < -math.pi: da += 2 * math.pi
            p['angle'] += max(-c['TURN_RATE'], min(c['TURN_RATE'], da))

            # Move head
            speed = c['BOOST_SPEED'] if p['boosting'] else c['BASE_SPEED']
            hx    = segs[0][0] + math.cos(p['angle']) * speed
            hy    = segs[0][1] + math.sin(p['angle']) * speed

            # Boundary
            if hx * hx + hy * hy >= wr2:
                dead.add(sid)
                continue

            # Propagate chain
            segs[0][0], segs[0][1] = hx, hy
            for i in range(1, len(segs)):
                ax, ay = segs[i - 1]
                bx, by = segs[i]
                dx, dy = bx - ax, by - ay
                d2     = dx * dx + dy * dy
                if d2 > c['SEG_DIST'] ** 2:
                    inv = c['SEG_DIST'] / math.sqrt(d2)
                    segs[i][0] = round(ax + dx * inv, 2)
                    segs[i][1] = round(ay + dy * inv, 2)

            # Boost drain
            if p['boosting']:
                if len(segs) > c['MIN_SEGS'] + 3:
                    p['grow'] -= c['BOOST_DRAIN']
                    if p['grow'] <= -1.0:
                        p['grow'] += 1.0
                        tx, ty = segs[-1]
                        fi = _mk_food(c, x=tx + random.uniform(-4,4),
                                         y=ty + random.uniform(-4,4),
                                         color=p['color'], size=7)
                        pending[fi['id']] = fi
                        if len(segs) > c['MIN_SEGS']:
                            segs.pop()
                else:
                    p['boosting'] = False

            # Grow
            while p['grow'] >= 1.0 and len(segs) < c['MAX_SEGS']:
                p['grow'] -= 1.0
                segs.append(list(segs[-1]))

            # Eat food
            eaten = []
            eat_r2 = (c['EAT_R']) ** 2
            for fid, f in _food.items():
                dx = hx - f['x']; dy = hy - f['y']
                if dx*dx + dy*dy < (c['EAT_R'] + f['size'] * 0.4) ** 2:
                    p['grow']  += f['size'] * 0.25
                    p['score'] += max(1, int(f['size']))
                    eaten.append(fid)
            for fid in eaten:
                del _food[fid]

            # Collision
            r2 = c['KILL_R'] ** 2
            for osid, op in _players.items():
                if osid == sid or not op['alive']:
                    continue
                for bx, by in op['segs']:
                    if (hx - bx) ** 2 + (hy - by) ** 2 < r2:
                        dead.add(sid)
                        break
                if sid in dead:
                    break

        # Deaths
        for sid in dead:
            p = _players.get(sid)
            if not p or not p['alive']:
                continue
            p['alive'] = False
            for i, (fx, fy) in enumerate(p['segs']):
                if i % 2 == 0:
                    fi = _mk_food(c,
                        x=fx + random.uniform(-6, 6),
                        y=fy + random.uniform(-6, 6),
                        color=p['color'],
                        size=random.uniform(8, 18))
                    pending[fi['id']] = fi
            socketio.emit('slither_died', {'score': p['score']}, to=sid)
            app_log.info(f"[slither] {p['username']!r} died (score {p['score']})")

        _food.update(pending)

        # Refill food
        target  = min(int(math.pi * wr * wr * c['FOOD_DENSITY']), c['MAX_FOOD'])
        deficit = target - len(_food)
        if deficit > 0:
            for _ in range(min(deficit, 10)):
                fi = _mk_food(c)
                _food[fi['id']] = fi

        # Broadcast
        players_out = [
            {
                'sid':      p['sid'],
                'username': p['username'],
                'color':    p['color'],
                'segs':     p['segs'][:c['SEGS_CAP']],
                'boosting': p['boosting'],
                'score':    p['score'],
            }
            for p in _players.values() if p['alive']
        ]

        socketio.emit('slither_state', {
            'players': players_out,
            'food':    list(_food.values()),
            'world_r': round(wr),
        })


# ── Game loop ─────────────────────────────────────────────────

def _start_loop():
    global _running
    if _running:
        return
    _running = True

    def _loop():
        while True:
            c   = _cfg()
            t0  = time.perf_counter()
            try:
                _tick()
            except Exception as exc:
                error_log.error(f"[slither] tick error: {exc}")
            gap = (1.0 / max(1, c['TICK_HZ'])) - (time.perf_counter() - t0)
            if gap > 0:
                time.sleep(gap)

    threading.Thread(target=_loop, daemon=True, name='slither-loop').start()
    app_log.info('[slither] game loop started')


# ── Socket events ──────────────────────────────────────────────

@socketio.on('slither_join')
def on_join(data):
    sid      = request.sid
    username = str(data.get('username', 'Snake'))[:20].strip() or 'Snake'
    color    = str(data.get('color', '#00d4ff'))
    c        = _cfg()

    with _lock:
        _spawn(sid, username, color, c)
        socketio.emit('slither_init', {
            'food':    list(_food.values()),
            'world_r': round(_world_r(c)),
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
    sid = request.sid
    with _lock:
        _players.pop(sid, None)