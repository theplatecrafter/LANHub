# socket_events/geoguesser_events.py
"""
GeoGuesser multiplayer + singleplayer socket events.

The server only resolves a pano_id from coordinates (a fast metadata call).
The client loads the panorama directly from Google via the Maps Embed API iframe —
no image is ever downloaded or cached by the server.

Requires: pip install streetview
"""
import uuid, time, threading, random, math, urllib.request
import json as _json
from flask import request
from flask_socketio import emit
from socketio_instance import socketio
from glob_vars import app_log, error_log
import functions as f
import config

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

_WORLD_CITIES = [
    # North America
    (40.71, -74.01), (34.05, -118.24), (41.88, -87.63), (29.76, -95.37),
    (33.45, -112.07), (39.95, -75.17), (29.95, -90.07), (32.78, -96.80),
    (47.61, -122.33), (25.77, -80.19), (36.17, -86.78), (39.74, -104.98),
    (42.36, -71.06), (37.34, -121.89), (45.52, -122.68), (38.90, -77.04),
    (43.65, -79.38), (45.50, -73.57), (49.25, -123.12), (51.05, -114.08),
    (19.43, -99.13), (20.97, -89.62), (20.52, -103.36), (21.16, -101.69),
    (15.50, -88.03), (13.69, -89.19), (14.08, -87.21), (10.00, -84.02),
    (18.54, -72.34), (18.01, -76.79), (10.65, -61.52), (17.25, -88.77),
    # South America
    (-23.55, -46.63), (-34.61, -58.38), (-12.05, -77.04), (-33.46, -70.65),
    (-16.50, -68.15), (-0.22, -78.51), (4.71, -74.07), (10.48, -66.88),
    (-3.73, -38.52), (-19.92, -43.94), (-30.03, -51.23), (-8.05, -34.88),
    (-15.78, -47.93), (-1.46, -48.50), (-25.43, -49.27), (-22.91, -43.17),
    (-27.60, -48.55), (-20.32, -40.34), (-3.10, -60.02), (5.83, -55.17),
    (-4.32, -15.32), (-17.73, -63.23), (-25.29, -57.65), (5.85, -55.20),
    # Europe
    (51.51, -0.13), (48.85, 2.35), (52.52, 13.41), (40.42, -3.70),
    (41.90, 12.50), (52.37, 4.90), (59.91, 10.75), (57.71, 11.97),
    (55.68, 12.57), (60.17, 24.94), (59.44, 24.75), (56.95, 24.11),
    (54.69, 25.28), (53.90, 27.57), (50.45, 30.52), (47.50, 19.04),
    (50.08, 14.44), (48.15, 17.11), (44.80, 20.46), (45.82, 15.98),
    (46.05, 14.51), (42.00, 21.43), (41.33, 19.82), (41.99, 21.43),
    (43.85, 18.36), (42.44, 19.26), (42.00, 21.43), (37.98, 23.73),
    (38.72, -9.14), (41.16, -8.63), (53.35, -6.26), (55.95, -3.19),
    (53.48, -2.24), (52.48, -1.90), (51.46, -3.18), (55.86, -4.25),
    (48.21, 16.37), (47.37, 8.54), (46.95, 7.44), (45.75, 4.85),
    (43.30, 5.37), (44.84, -0.58), (47.22, -1.55), (48.58, 7.75),
    (51.22, 4.40), (50.85, 4.35), (50.63, 5.57), (52.08, 4.31),
    # Africa
    (30.06, 31.25), (-26.20, 28.04), (-33.93, 18.42), (6.37, 3.38),
    (-1.29, 36.82), (-4.32, 15.32), (14.69, -17.44), (12.37, -1.53),
    (12.37, -1.53), (9.05, 7.49), (5.35, -4.00), (4.05, 9.70),
    (3.87, 11.52), (-18.91, 47.54), (-25.97, 32.59), (15.56, 32.53),
    (11.59, 43.15), (-4.04, 39.67), (-11.70, 27.47), (6.14, 1.21),
    (5.56, -0.20), (-15.42, 28.28), (-17.83, 31.05), (24.69, 46.72),
    (21.49, 39.19), (36.82, 10.17), (33.89, 9.54), (31.63, -7.99),
    (34.02, -6.84), (36.74, 3.06), (-8.84, 13.23), (18.08, 15.78),
    # Asia
    (35.69, 139.69), (31.23, 121.47), (39.91, 116.39), (22.54, 114.06),
    (1.35, 103.82), (3.15, 101.69), (13.75, 100.52), (21.03, 105.85),
    (10.82, 106.63), (11.56, 104.92), (12.37, 104.91), (17.97, 102.60),
    (16.87, 96.19), (23.73, 90.40), (22.57, 88.36), (19.08, 72.88),
    (28.66, 77.22), (12.97, 77.59), (17.38, 78.49), (13.09, 80.27),
    (22.99, 120.21), (25.05, 121.53), (37.57, 126.98), (35.17, 129.07),
    (34.69, 135.50), (35.02, 135.76), (43.06, 141.35), (26.21, 50.59),
    (24.47, 54.37), (25.20, 55.27), (29.38, 47.99), (23.61, 58.59),
    (33.34, 44.40), (33.51, 36.29), (33.89, 35.50), (31.97, 35.95),
    (31.50, 34.47), (32.08, 34.78), (41.01, 28.95), (39.93, 32.86),
    (37.05, 37.38), (37.88, 40.73), (38.46, 27.13), (36.90, 30.70),
    (41.30, 69.27), (42.87, 74.60), (43.25, 76.94), (47.90, 106.90),
    (55.75, 37.62), (59.95, 30.32), (56.50, 84.98), (54.99, 73.37),
    (51.18, 71.45), (43.12, 76.08),
    # Oceania
    (-33.87, 151.21), (-37.81, 144.97), (-27.47, 153.03), (-31.95, 115.86),
    (-34.93, 138.60), (-41.29, 174.78), (-36.86, 174.77), (-43.53, 172.64),
    (-17.73, 168.32), (-9.43, 160.05),
    # Middle East / Central Asia
    (35.69, 51.42), (35.33, 47.07), (29.56, 52.55), (29.61, 52.53),
    (36.30, 59.60), (37.94, 58.38), (38.56, 68.77), (37.95, 58.38),
]


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


def _region_diagonal_km(region: list) -> float:
    """Bounding-box diagonal of the polygon in km (≈ max in-region distance)."""
    lats = [p[0] for p in region]
    lngs = [p[1] for p in region]
    return haversine_km(min(lats), min(lngs), max(lats), max(lngs))
 
 
def geo_score(distance_km: float,
              region: list = None,
              region_is_world: bool = True) -> int:
    """
    Score a guess (0–5000).
 
    World mode / no region
        decay = 2000 km  (original formula, unchanged)
 
    Custom region
        decay = bbox_diagonal * GEO_REGION_SCORE_DECAY_FACTOR
        This scales the full 0–5000 range to the actual size of the region,
        so near-misses within a small area still produce meaningful spread.
    """
    if region_is_world or not region:
        # ── Original world-scale formula ──────────────────────────────────
        if distance_km < 0.025:
            return 5000
        return round(max(0, 5000 * math.exp(-distance_km / 2000)))
    else:
        # ── Region-scaled formula ──────────────────────────────────────────
        factor    = float(getattr(config, "GEO_REGION_SCORE_DECAY_FACTOR", 0.5))
        diagonal  = _region_diagonal_km(region)
        decay     = max(0.1, diagonal * factor)   # floor at 100 m
        perfect   = max(0.001, diagonal * 0.0005) # 0.05 % of diagonal
        if distance_km < perfect:
            return 5000
        return round(max(0, 5000 * math.exp(-distance_km / decay)))


# ── Street View Metadata API (official, free, reliable) ───────────────────────

def _sv_metadata_check(lat: float, lng: float, radius_m: int, api_key: str) -> "tuple | None":
    """
    Query the official Street View Static API metadata endpoint.
    Free to use (zero cost per call), supports radius, returns actual pano coords.

    Response shape: { "status": "OK"|"ZERO_RESULTS"|...,
                      "pano_id": "...",
                      "location": {"lat": ..., "lng": ...} }

    Returns (pano_id, pano_lat, pano_lng) on success, or None.
    pano_lat/pano_lng are the panorama's ACTUAL position, not the query point.
    """
    url = (
        "https://maps.googleapis.com/maps/api/streetview/metadata"
        f"?location={lat},{lng}&radius={radius_m}&source=outdoor&key={api_key}"
    )
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            data = _json.loads(resp.read().decode())
        if data.get("status") != "OK":
            return None
        pano_id  = data.get("pano_id", "")
        location = data.get("location", {})
        pano_lat = float(location.get("lat", lat))
        pano_lng = float(location.get("lng", lng))
        if not pano_id:
            return None
        return pano_id, pano_lat, pano_lng
    except Exception as e:
        app_log.debug(f"[geo] metadata check error ({lat:.3f},{lng:.3f}) r={radius_m}m: {e}")
        return None


def _generate_grid_candidates(region: list, grid_step: float) -> list:
    """
    Generate a uniformly shuffled list of (lat, lng) candidate points on a
    regular grid inside the polygon. Adaptively halves grid_step until at
    least 2 interior points are found. The centroid is included as a regular
    candidate (no special priority) so each round starts at a different point.
    """
    lats = [p[0] for p in region]
    lngs = [p[1] for p in region]
    mn_lat, mx_lat = min(lats), max(lats)
    mn_lng, mx_lng = min(lngs), max(lngs)
    c_lat = sum(lats) / len(lats)
    c_lng = sum(lngs) / len(lngs)
 
    step = grid_step
    candidates = []
    while step >= 0.001:
        candidates = []
        lat = mn_lat + step / 2
        while lat <= mx_lat + step / 2:
            lng = mn_lng + step / 2
            while lng <= mx_lng + step / 2:
                if _point_in_polygon(lat, lng, region):
                    candidates.append((lat, lng))
                lng += step
            lat += step
        if len(candidates) >= 2:
            break
        step /= 2
 
    # Add centroid as a regular candidate (not prioritised)
    centroid = (c_lat, c_lng)
    if centroid not in candidates:
        candidates.append(centroid)
 
    # Fully shuffle — every round starts at a different grid cell
    random.shuffle(candidates)
    return candidates


def _find_pano_region(region: list, api_key: str, on_timeout=None) -> "tuple | None":
    """
    Grid-based region search using the official Street View Metadata API.
 
    Grid step is computed dynamically from the polygon's bounding box so that
    small regions get a fine grid (good coverage + variety) and large regions
    get a coarser grid (fewer API calls). The step equals:
 
        min(shorter_bbox_dimension / GEO_REGION_GRID_DIVISIONS,
            GEO_REGION_GRID_STEP_MAX)
 
    Phase 1 — coarse grid at the computed step.
    Phase 2 — finer grid at half the step.
    Phase 3 — centroid with escalating radii (2 km → 10 km → 50 km).
 
    Each candidate has random jitter of ±step/2 so the same grid cell returns
    a different nearby pano each round. The returned pano coordinates are always
    verified with _point_in_polygon.
    """
    # ── Config ────────────────────────────────────────────────────────────────
    divisions = int(  getattr(config, "GEO_REGION_GRID_DIVISIONS",         8))
    max_step  = float(getattr(config, "GEO_REGION_GRID_STEP_MAX",        0.5))
    radius_m  = int(  getattr(config, "GEO_REGION_SEARCH_RADIUS_M",      500))
    timeout_s = float(getattr(config, "GEO_REGION_SEARCH_TIMEOUT_SECS",   15))
 
    # ── Derive step from bbox ─────────────────────────────────────────────────
    lats = [p[0] for p in region]
    lngs = [p[1] for p in region]
    mn_lat, mx_lat = min(lats), max(lats)
    mn_lng, mx_lng = min(lngs), max(lngs)
    c_lat = (mn_lat + mx_lat) / 2
    c_lng = (mn_lng + mx_lng) / 2
 
    short_dim = min(mx_lat - mn_lat, mx_lng - mn_lng)
    # Avoid division by zero for degenerate (point-like) polygons
    grid_step = max(0.001, min(short_dim / max(divisions, 1), max_step))
 
    app_log.info(
        f"[geo] Region bbox short={short_dim:.4f}° → "
        f"grid_step={grid_step:.4f}° (~{grid_step * 111:.1f} km)"
    )
 
    # ── Timeout machinery ─────────────────────────────────────────────────────
    start_time    = time.time()
    timeout_fired = False
 
    def _check_timeout():
        nonlocal timeout_fired
        if not timeout_fired and on_timeout and (time.time() - start_time) >= timeout_s:
            timeout_fired = True
            try:
                on_timeout()
                app_log.info("[geo] Region search timeout signal emitted to client")
            except Exception:
                pass
 
    def _try_candidates(candidates, phase_name, jitter):
        for base_lat, base_lng in candidates:
            lat = base_lat + random.uniform(-jitter, jitter)
            lng = base_lng + random.uniform(-jitter, jitter)
            lat = max(-85.0, min(85.0,  lat))
            lng = max(-180.0, min(180.0, lng))
 
            _check_timeout()
            result = _sv_metadata_check(lat, lng, radius_m, api_key)
            if not result:
                continue
            pano_id, pano_lat, pano_lng = result
            if _point_in_polygon(pano_lat, pano_lng, region):
                app_log.info(
                    f"[geo] Region pano ({phase_name}): {pano_id} "
                    f"@ ({pano_lat:.4f},{pano_lng:.4f})"
                )
                return pano_id, pano_lat, pano_lng
            app_log.debug(
                f"[geo] Pano {pano_id} at ({pano_lat:.3f},{pano_lng:.3f}) "
                f"outside polygon — skipping"
            )
        return None
 
    # Phase 1 — coarse grid
    c1 = _generate_grid_candidates(region, grid_step)
    app_log.info(f"[geo] Phase 1: {len(c1)} candidates, jitter=±{grid_step/2:.4f}°")
    r = _try_candidates(c1, "phase 1", jitter=grid_step / 2)
    if r:
        return r
 
    # Phase 2 — finer grid (half step)
    fine_step = grid_step / 2
    c2 = _generate_grid_candidates(region, fine_step)
    app_log.info(f"[geo] Phase 2: {len(c2)} candidates, step={fine_step:.4f}°")
    r = _try_candidates(c2, "phase 2", jitter=fine_step / 2)
    if r:
        return r
 
    # Phase 3 — centroid with escalating radii
    for big_r in (2_000, 10_000, 50_000):
        _check_timeout()
        result = _sv_metadata_check(c_lat, c_lng, big_r, api_key)
        if result:
            pano_id, pano_lat, pano_lng = result
            if _point_in_polygon(pano_lat, pano_lng, region):
                app_log.info(f"[geo] Region pano (centroid r={big_r}m): {pano_id}")
                return pano_id, pano_lat, pano_lng
 
    _check_timeout()
    return None


# ── Panorama location lookup (legacy — used for world mode + no-key fallback) ─

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


def _find_pano(region: list, region_is_world: bool, on_timeout=None) -> tuple:
    """
    Master panorama finder. Never raises (always returns something playable).

    World mode  — weighted city list (85 %) + pure random (15 %), infinite loop.
    Region mode — uses official Street View Metadata API when an API key is
                  configured (fast, systematic, free).  Falls back to the old
                  streetview-library neighbour-search when no key is present.
                  If the region genuinely has no coverage, silently falls back
                  to world mode so the game never crashes.
    """
    if not _SV_OK:
        raise Exception(
            "The 'streetview' library is not installed. "
            "Run: pip install streetview"
        )

    # ── World mode: infinite weighted loop ────────────────────────────────────
    if region_is_world:
        while True:
            if random.random() < 0.85:
                base_lat, base_lng = random.choice(_WORLD_CITIES)
                jitter = random.uniform(0.05, 0.45)
                lat = max(-85.0, min(85.0, base_lat + random.uniform(-jitter, jitter)))
                lng = max(-180.0, min(180.0, base_lng + random.uniform(-jitter, jitter)))
            else:
                lat = random.uniform(-55, 70)
                lng = random.uniform(-180, 180)

            try:
                results = _search_panoramas(lat=lat, lon=lng)
            except Exception as e:
                app_log.debug(f"[geo] search_panoramas error at ({lat:.2f},{lng:.2f}): {e}")
                continue

            if not results:
                continue

            pano_id, pano_lat, pano_lng = _extract_pano_info(results[0], lat, lng)
            if not pano_id:
                continue

            app_log.info(f"[geo] Found pano {pano_id} @ ({pano_lat:.4f},{pano_lng:.4f})")
            return pano_id, pano_lat, pano_lng

    # ── Region mode ───────────────────────────────────────────────────────────
    if not region or _random_polygon_point(region) is None:
        app_log.warning("[geo] Empty or degenerate polygon — falling back to world mode")
        return _find_pano([], True)

    api_key = getattr(config, "GOOGLE_MAPS_EMBED_KEY", "")

    if api_key:
        # ── Primary path: official Metadata API — systematic, fast, free ─────
        result = _find_pano_region(region, api_key, on_timeout=on_timeout)
        if result:
            return result
        app_log.warning("[geo] Region search exhausted — falling back to world mode")
        return _find_pano([], True)

    else:
        # ── Fallback path: streetview library with neighbour offsets ──────────
        # Used only when GOOGLE_MAPS_EMBED_KEY is not configured.
        app_log.warning(
            "[geo] No API key configured — using streetview library for region mode. "
            "Set GOOGLE_MAPS_EMBED_KEY in configvars for much faster region search."
        )
        max_retries = int(  getattr(config, "GEO_REGION_MAX_RETRIES",      50))
        spread      = float(getattr(config, "GEO_REGION_NEIGHBOR_SPREAD", 0.015))
        offsets = [
            (0.0,    0.0),
            ( spread, 0.0),
            (-spread, 0.0),
            (0.0,    spread),
            (0.0,   -spread),
        ]
        attempt = 0
        while True:
            attempt += 1
            pt = _random_polygon_point(region)
            if pt is None:
                break
            base_lat, base_lng = pt
            for dlat, dlng in offsets:
                clat = max(-85.0, min(85.0,  base_lat + dlat))
                clng = max(-180.0, min(180.0, base_lng + dlng))
                try:
                    results = _search_panoramas(lat=clat, lon=clng)
                except Exception as e:
                    app_log.debug(f"[geo] Region attempt {attempt}: {e}")
                    continue
                if not results:
                    continue
                pano_id, pano_lat, pano_lng = _extract_pano_info(results[0], clat, clng)
                if pano_id:
                    app_log.info(
                        f"[geo] Region pano (no-key, attempt {attempt}): "
                        f"{pano_id} @ ({pano_lat:.4f},{pano_lng:.4f})"
                    )
                    return pano_id, pano_lat, pano_lng
            if attempt >= max_retries:
                break
        app_log.warning("[geo] Region no-key search exhausted — falling back to world mode")
        return _find_pano([], True)


# ── Room helpers ──────────────────────────────────────────────────────────────

def _rn(room_id: str) -> str:
    return f"geo_{room_id}"


def _emit_lobby():
    public = [
        {
            "id":              r["id"],
            "title":           r["title"],
            "players":         len(r["players"]),
            "rounds":          r["rounds_total"],
            "time":            r["round_time_limit"],
            "status":          r["status"],
            "region_is_world": r["region_is_world"],
            "region":          r["region"],          # polygon points for preview
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
            "id":              room["id"],
            "title":           room["title"],
            "privacy":         room["privacy"],
            "creator_sid":     room["creator_sid"],
            "players":         [
                {"sid": p["sid"], "username": p["username"], "total_score": p["total_score"]}
                for p in room["players"]
            ],
            "status":          room["status"],
            "rounds_total":    room["rounds_total"],
            "round_current":   room["round_current"],
            "time_limit":      room["round_time_limit"],
            "region_is_world": room["region_is_world"],
            "region":          room["region"],
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

    # Capture creator_sid now (before the thread starts) for the timeout callback
    creator_sid      = room.get("creator_sid")
    is_region_search = not room["region_is_world"]

    def on_timeout():
        # Emitted to the whole room; frontend shows the "Change Region" button
        # only to the creator (checked via amCreator in JS).
        socketio.emit(
            "geo_region_timeout",
            {"creator_sid": creator_sid},
            room=_rn(room_id),
        )

    def fetch_and_start():
        try:
            pano_id, lat, lng = _find_pano(
                room["region"],
                room["region_is_world"],
                on_timeout=(on_timeout if is_region_search else None),
            )
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

        def on_round_timeout():
            r = geo_rooms.get(room_id)
            if r and r["status"] == "playing":
                _end_round(room_id)
 
        t = threading.Timer(room2["round_time_limit"], on_round_timeout)
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
            score = geo_score(
                dist,
                region          = room.get("region", []),
                region_is_world = room.get("region_is_world", True),
            )
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
    geo_sessions[sid]["sp_region"]          = region
    geo_sessions[sid]["sp_region_is_world"] = region_is_world

    def on_timeout():
        socketio.emit("geo_region_timeout", {}, to=sid)

    def fetch():
        try:
            pano_id, lat, lng = _find_pano(
                region,
                region_is_world,
                on_timeout=(on_timeout if not region_is_world else None),
            )
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
    dist = haversine_km(lat, lng, correct_lat, correct_lng)
    sess = geo_sessions.get(request.sid, {})
    score = geo_score(
        dist,
        region          = sess.get("sp_region", []),
        region_is_world = sess.get("sp_region_is_world", True),
    )
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