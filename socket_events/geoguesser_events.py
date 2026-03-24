# socket_events/geoguesser_events.py
"""
GeoGuesser multiplayer + singleplayer socket events.
"""
import uuid, time, threading, random, math, urllib.request, hashlib
import json as _json
from flask import request
from flask_socketio import emit
from socketio_instance import socketio
from glob_vars import app_log, error_log
import functions as f
import config


try:
    from streetview import search_panoramas as _search_panoramas
    _SV_OK = True
except ImportError:
    _search_panoramas = None
    _SV_OK = False
    error_log.warning("[geo] 'streetview' library not found. Run: pip install streetview")


class GeoNoCoverageError(Exception):
    """Raised when the region search finds no Street View coverage."""


geo_sessions: dict[str, dict] = {}
geo_rooms:    dict[str, dict] = {}


ROUND_ADVANCE_SECS   = int(getattr(config, "GEO_ROUND_ADVANCE_SECS",   9))
MAX_LOCATION_RETRIES = int(getattr(config, "GEO_MAX_LOCATION_RETRIES", 50))


_region_coverage_cache: dict[str, dict] = {}
# Each entry shape:
#   'cells'           : set() — cells confirmed to contain Street View coverage.
#                       Instantly counted as covered at any depth, no API call.
#   'dead_cells'      : set() — cells confirmed to be empty (no pano within radius).
#                       Instantly skipped at any depth, no API call.
#                       Together with 'cells', once every cell at a depth has been
#                       classified the whole depth costs zero API calls.
#   'used_panos'      : set() — pano IDs returned to clients this session.
#   'exhausted_cells' : set() — cells where every reachable pano has been shown.
#                       The quadtree skips these when picking termination candidates
#                       and subdivides them so the game never runs out of fresh locations.
# Entries are evicted the moment no active room or SP session references the region.
_CACHE_MAX_CELLS_PER_REGION  = int(getattr(config, "GEO_CACHE_MAX_CELLS",      500))
_CACHE_MAX_DEAD_PER_REGION   = int(getattr(config, "GEO_CACHE_MAX_DEAD",      1000))
_CACHE_MAX_USED_PANOS        = int(getattr(config, "GEO_CACHE_MAX_USED_PANOS", 300))




def _region_hash(polygons: list) -> str | None:
    if not polygons:
        return None
    rounded = [
        [[round(c, 5) for c in pt] for pt in poly]
        for poly in polygons
    ]
    blob = _json.dumps(rounded, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.md5(blob).hexdigest()




def _cache_ensure(region_key: str) -> dict:
    """Return (and lazily create) the cache entry for a region."""
    if region_key not in _region_coverage_cache:
        _region_coverage_cache[region_key] = {
            'cells': set(), 'dead_cells': set(),
            'used_panos': set(), 'exhausted_cells': set(),
        }
    return _region_coverage_cache[region_key]




def _cache_add(region_key: str, cell: tuple) -> None:
    """Record a cell as confirmed-covered.  Also removes it from dead/exhausted."""
    if region_key is None:
        return
    entry = _cache_ensure(region_key)
    if len(entry['cells']) < _CACHE_MAX_CELLS_PER_REGION:
        entry['cells'].add(cell)
    entry['dead_cells'].discard(cell)       # covered → no longer dead
    entry['exhausted_cells'].discard(cell)  # fresh coverage found → reset exhaustion
    app_log.debug(
        f"[geo cache] {region_key[:8]}: "
        f"{len(entry['cells'])} covered  {len(entry['dead_cells'])} dead  "
        f"{len(entry['exhausted_cells'])} exhausted  {len(entry['used_panos'])} used panos"
    )




def _cache_add_dead(region_key: str, cell: tuple) -> None:
    """Record that a cell has no Street View coverage within its search radius."""
    if region_key is None:
        return
    entry = _cache_ensure(region_key)
    if len(entry['dead_cells']) < _CACHE_MAX_DEAD_PER_REGION:
        entry['dead_cells'].add(cell)




def _cache_mark_used(region_key: str, pano_id: str) -> None:
    """Record that pano_id was shown so the selection step won't repeat it."""
    if region_key is None or not pano_id:
        return
    entry = _cache_ensure(region_key)
    if len(entry['used_panos']) < _CACHE_MAX_USED_PANOS:
        entry['used_panos'].add(pano_id)




def _cache_mark_exhausted(region_key: str, cell: tuple) -> None:
    """Record that all reachable panos inside a cell have been shown."""
    if region_key is None:
        return
    _cache_ensure(region_key)['exhausted_cells'].add(cell)
    app_log.debug(f"[geo cache] cell exhausted in {region_key[:8]}")




def _cache_remove_cell(region_key: str, cell: tuple) -> None:
    if region_key is None:
        return
    entry = _region_coverage_cache.get(region_key)
    if entry:
        entry['cells'].discard(cell)




def _cache_release(region_key: str) -> None:
    if region_key is None or region_key not in _region_coverage_cache:
        return
    for room in geo_rooms.values():
        if room.get("region_key") == region_key:
            app_log.debug(f"[geo cache] release skipped for {region_key[:8]} (held by room {room['id']})")
            return
    for sess in geo_sessions.values():
        if sess.get("sp_region_key") == region_key:
            app_log.debug(f"[geo cache] release skipped for {region_key[:8]} (held by SP session)")
            return
    del _region_coverage_cache[region_key]
    app_log.info(f"[geo cache] released region {region_key[:8]} — cache now holds {len(_region_coverage_cache)} region(s)")




_WORLD_CITIES = [
    (40.71,-74.01),(34.05,-118.24),(41.88,-87.63),(29.76,-95.37),(33.45,-112.07),
    (39.95,-75.17),(29.95,-90.07),(32.78,-96.80),(47.61,-122.33),(25.77,-80.19),
    (36.17,-86.78),(39.74,-104.98),(42.36,-71.06),(37.34,-121.89),(45.52,-122.68),
    (38.90,-77.04),(43.65,-79.38),(45.50,-73.57),(49.25,-123.12),(51.05,-114.08),
    (19.43,-99.13),(20.97,-89.62),(20.52,-103.36),(21.16,-101.69),(13.69,-89.19),
    (14.08,-87.21),(10.00,-84.02),(18.54,-72.34),(18.01,-76.79),(10.65,-61.52),
    (-23.55,-46.63),(-34.61,-58.38),(-12.05,-77.04),(-33.46,-70.65),(-16.50,-68.15),
    (-0.22,-78.51),(4.71,-74.07),(10.48,-66.88),(-3.73,-38.52),(-19.92,-43.94),
    (-30.03,-51.23),(-8.05,-34.88),(-15.78,-47.93),(-1.46,-48.50),(-25.43,-49.27),
    (5.83,-55.17),(-17.73,-63.23),(-25.29,-57.65),(51.51,-0.13),(48.85,2.35),
    (52.52,13.41),(40.42,-3.70),(41.90,12.50),(52.37,4.90),(59.91,10.75),
    (57.71,11.97),(55.68,12.57),(60.17,24.94),(59.44,24.75),(56.95,24.11),
    (54.69,25.28),(53.90,27.57),(50.45,30.52),(47.50,19.04),(50.08,14.44),
    (48.15,17.11),(44.80,20.46),(45.82,15.98),(46.05,14.51),(42.00,21.43),
    (41.33,19.82),(43.85,18.36),(37.98,23.73),(38.72,-9.14),(41.16,-8.63),
    (53.35,-6.26),(55.95,-3.19),(53.48,-2.24),(48.21,16.37),(47.37,8.54),
    (46.95,7.44),(45.75,4.85),(43.30,5.37),(44.84,-0.58),(47.22,-1.55),
    (48.58,7.75),(51.22,4.40),(50.85,4.35),(52.08,4.31),(30.06,31.25),
    (-26.20,28.04),(-33.93,18.42),(6.37,3.38),(-1.29,36.82),(-4.32,15.32),
    (14.69,-17.44),(12.37,-1.53),(9.05,7.49),(5.35,-4.00),(4.05,9.70),
    (3.87,11.52),(-18.91,47.54),(-25.97,32.59),(15.56,32.53),(11.59,43.15),
    (-4.04,39.67),(6.14,1.21),(5.56,-0.20),(-15.42,28.28),(-17.83,31.05),
    (24.69,46.72),(21.49,39.19),(36.82,10.17),(33.89,9.54),(31.63,-7.99),
    (34.02,-6.84),(36.74,3.06),(35.69,139.69),(31.23,121.47),(39.91,116.39),
    (22.54,114.06),(1.35,103.82),(3.15,101.73),(13.75,100.52),(21.03,105.85),
    (10.82,106.63),(17.97,102.60),(16.87,96.19),(23.73,90.40),(22.57,88.36),
    (19.08,72.88),(28.66,77.22),(12.97,77.59),(17.38,78.49),(13.09,80.27),
    (22.99,120.21),(25.05,121.53),(37.57,126.98),(35.17,129.07),(34.69,135.50),
    (35.02,135.76),(43.06,141.35),(26.21,50.59),(24.47,54.37),(25.20,55.27),
    (29.38,47.99),(23.61,58.59),(33.34,44.40),(33.51,36.29),(33.89,35.50),
    (31.97,35.95),(31.50,34.47),(32.08,34.78),(41.01,28.95),(39.93,32.86),
    (41.30,69.27),(42.87,74.60),(43.25,76.94),(47.90,106.90),(55.75,37.62),
    (59.95,30.32),(56.50,84.98),(54.99,73.37),(51.18,71.45),(-33.87,151.21),
    (-37.81,144.97),(-27.47,153.03),(-31.95,115.86),(-34.93,138.60),
    (-41.29,174.78),(-36.86,174.77),(-43.53,172.64),(35.69,51.42),(29.56,52.55),
    (36.30,59.60),(37.94,58.38),(38.56,68.77),
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




def _point_in_any_polygon(lat: float, lng: float, polygons: list) -> bool:
    return any(
        _point_in_polygon(lat, lng, poly)
        for poly in polygons
        if isinstance(poly, list) and len(poly) >= 3
    )




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




def _random_point_in_any_polygon(polygons: list):
    order = list(range(len(polygons)))
    random.shuffle(order)
    for i in order:
        pt = _random_polygon_point(polygons[i])
        if pt:
            return pt
    return None




def haversine_km(lat1, lng1, lat2, lng2) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + (
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    )
    return 2 * R * math.asin(math.sqrt(max(0.0, min(1.0, a))))




def _region_diagonal_km(polygons: list) -> float:
    all_lats = [p[0] for poly in polygons for p in poly]
    all_lngs = [p[1] for poly in polygons for p in poly]
    if not all_lats:
        return 0.0
    return haversine_km(min(all_lats), min(all_lngs), max(all_lats), max(all_lngs))




def geo_score(distance_km: float, polygons: list = None,
              region_is_world: bool = True) -> int:
    if region_is_world or not polygons:
        if distance_km < 0.025:
            return 5000
        return round(max(0, 5000 * math.exp(-distance_km / 2000)))
    else:
        factor   = float(getattr(config, "GEO_REGION_SCORE_DECAY_FACTOR", 0.5))
        diagonal = _region_diagonal_km(polygons)
        decay    = max(0.1, diagonal * factor)
        perfect  = max(0.001, diagonal * 0.0005)
        if distance_km < perfect:
            return 5000
        return round(max(0, 5000 * math.exp(-distance_km / decay)))




# ── Street View Metadata API ──────────────────────────────────────────────────


def _sv_metadata_check(lat: float, lng: float, radius_m: int, api_key: str):
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




# ── Cell geometry helpers ─────────────────────────────────────────────────────


def _cell_diagonal_km(lat_min: float, lat_max: float,
                       lng_min: float, lng_max: float) -> float:
    return haversine_km(lat_min, lng_min, lat_max, lng_max)




def _cell_center(lat_min: float, lat_max: float,
                  lng_min: float, lng_max: float) -> tuple:
    return ((lat_min + lat_max) / 2.0, (lng_min + lng_max) / 2.0)




def _cell_search_radius_m(diagonal_km: float, max_radius_m: int) -> int:
    return min(max_radius_m, max(100, int(diagonal_km * 500)))




def _cell_has_region_overlap(lat_min: float, lat_max: float,
                               lng_min: float, lng_max: float,
                               polygons: list) -> bool:
    c_lat = (lat_min + lat_max) / 2.0
    c_lng = (lng_min + lng_max) / 2.0
    probe_points = [
        (c_lat,   c_lng),
        (lat_min, lng_min), (lat_min, lng_max),
        (lat_max, lng_min), (lat_max, lng_max),
        (c_lat,   lng_min), (c_lat,   lng_max),
        (lat_min, c_lng),   (lat_max, c_lng),
    ]
    return any(
        _point_in_any_polygon(lat, lng, polygons)
        for lat, lng in probe_points
    )




def _subdivide_cell(lat_min: float, lat_max: float,
                     lng_min: float, lng_max: float,
                     n: int) -> list:
    lat_step = (lat_max - lat_min) / n
    lng_step = (lng_max - lng_min) / n
    cells = []
    for i in range(n):
        for j in range(n):
            cells.append((
                lat_min + i * lat_step,
                lat_min + (i + 1) * lat_step,
                lng_min + j * lng_step,
                lng_min + (j + 1) * lng_step,
            ))
    return cells




# ── Adaptive quadtree region search ──────────────────────────────────────────


def _find_pano_region(polygons: list, region_key: str,
                      api_key: str, on_timeout=None, status_cb=None):
    """
    Adaptive quadtree coverage search with per-region cell caching.


    The cache stores four sets per region (all held in RAM while the region is active):


      cells           — cells confirmed to contain Street View coverage.  Instantly
                        counted as covered at any depth — no API call ever again.
      dead_cells      — cells confirmed to be empty within their search radius.
                        Instantly skipped at any depth — no API call ever again.
                        Once every cell at a depth is classified (covered or dead),
                        that entire depth costs zero API calls.
      used_panos      — pano IDs returned to clients this session.  The selection
                        step goes deeper rather than repeat a pano.
      exhausted_cells — cells where every reachable pano has already been shown.
                        The quadtree bypasses these when choosing termination
                        candidates and subdivides them further, so the game never
                        runs out of geographically distinct locations.


    Returns (pano_id, pano_lat, pano_lng) or None.
    """
    def _status(msg):
        if status_cb:
            try:
                status_cb(msg)
            except Exception:
                pass


    initial_divs  = int(  getattr(config, "GEO_COVERAGE_INITIAL_DIVISIONS",  4))
    subdivide_by  = int(  getattr(config, "GEO_COVERAGE_SUBDIVIDE_BY",       3))
    min_cell_km   = float(getattr(config, "GEO_COVERAGE_MIN_CELL_KM",      3.0))
    max_depth     = int(  getattr(config, "GEO_COVERAGE_MAX_DEPTH",          6))
    timeout_s     = float(getattr(config, "GEO_COVERAGE_TIMEOUT_SECS",     30.0))
    max_radius_m  = int(  getattr(config, "GEO_COVERAGE_MAX_RADIUS_M",   50_000))


    # Load all four cache sets for this region
    cache_entry     = _region_coverage_cache.get(region_key) or {}
    known_cells     = cache_entry.get("cells",           set())
    dead_cells_snap = cache_entry.get("dead_cells",      set())
    used_panos      = cache_entry.get("used_panos",      set())
    exhausted_snap  = cache_entry.get("exhausted_cells", set())


    app_log.info(
        f"[geo] Quadtree search for {region_key[:8]} — "
        f"{len(known_cells)} covered, {len(dead_cells_snap)} dead, "
        f"{len(exhausted_snap)} exhausted, {len(used_panos)} used panos"
    )


    # ── Core helper: probe a random point inside a cell ───────────────────────
    def _try_cell(cell):
        lat_min, lat_max, lng_min, lng_max = cell
        q_lat    = random.uniform(lat_min, lat_max)
        q_lng    = random.uniform(lng_min, lng_max)
        diag     = _cell_diagonal_km(*cell)
        radius_m = _cell_search_radius_m(diag, max_radius_m)
        result   = _sv_metadata_check(q_lat, q_lng, radius_m, api_key)
        if not result:
            return None
        pano_id, pano_lat, pano_lng = result
        if _point_in_any_polygon(pano_lat, pano_lng, polygons):
            return pano_id, pano_lat, pano_lng
        return None


    # ── Quadtree (always from depth 0) ────────────────────────────────────────
    all_lats = [p[0] for poly in polygons for p in poly]
    all_lngs = [p[1] for poly in polygons for p in poly]
    bb_lat_min, bb_lat_max = min(all_lats), max(all_lats)
    bb_lng_min, bb_lng_max = min(all_lngs), max(all_lngs)


    start_time    = time.time()
    timeout_fired = False


    def _check_timeout():
        nonlocal timeout_fired
        if not timeout_fired and on_timeout and (time.time() - start_time) >= timeout_s:
            timeout_fired = True
            try:
                on_timeout()
            except Exception:
                pass


    initial_cells = _subdivide_cell(
        bb_lat_min, bb_lat_max, bb_lng_min, bb_lng_max, initial_divs,
    )
    live_cells = [c for c in initial_cells if _cell_has_region_overlap(*c, polygons)]


    _status(f"Scanning region — dividing into {len(live_cells)} search zones…")


    diag_km = _cell_diagonal_km(
        bb_lat_min, bb_lat_max, bb_lng_min, bb_lng_max
    ) / initial_divs


    app_log.info(
        f"[geo] Adaptive search start: {len(initial_cells)} coarse cells -> "
        f"{len(live_cells)} overlap region, cell diag ~= {diag_km:.1f} km"
    )


    covered_cells = []


    for depth in range(max_depth):
        _check_timeout()
        if not live_cells:
            app_log.info(f"[geo] Depth {depth}: no live cells, stopping.")
            break


        diag_km = _cell_diagonal_km(*live_cells[0]) if live_cells else 0.0
        app_log.info(
            f"[geo] Depth {depth}: probing {len(live_cells)} cells, "
            f"diag ~= {diag_km:.1f} km"
        )
        zone_km = round(diag_km)
        _status(
            f"Pass {depth + 1} — checking {len(live_cells)} zone{'s' if len(live_cells) != 1 else ''} "
            f"({zone_km} km across each)…"
        )


        newly_covered = []
        # Re-read all four sets so changes made during this run are immediately visible
        entry_now     = _region_coverage_cache.get(region_key) or {}
        cur_known     = entry_now.get("cells",           set())
        cur_dead      = entry_now.get("dead_cells",      set())
        cur_exhausted = entry_now.get("exhausted_cells", set())


        for cell in live_cells:
            lat_min, lat_max, lng_min, lng_max = cell


            if cell in cur_known:
                # Previously confirmed coverage — instant, no API call
                newly_covered.append(cell)
                continue


            if cell in cur_dead:
                # Previously confirmed empty — instant skip, no API call
                continue


            c_lat, c_lng = _cell_center(*cell)
            diag     = _cell_diagonal_km(*cell)
            radius_m = _cell_search_radius_m(diag, max_radius_m)


            _check_timeout()
            result = _sv_metadata_check(c_lat, c_lng, radius_m, api_key)
            if not result:
                # No pano within radius — record as dead so we never probe again
                _cache_add_dead(region_key, cell)
                continue


            pano_id, pano_lat, pano_lng = result
            if (lat_min <= pano_lat <= lat_max and
                    lng_min <= pano_lng <= lng_max and
                    _point_in_any_polygon(pano_lat, pano_lng, polygons)):
                newly_covered.append(cell)
                _cache_add(region_key, cell)
            # else: pano snapped outside cell/region boundary — don't classify either way


        app_log.info(
            f"[geo] Depth {depth}: {len(newly_covered)}/{len(live_cells)} cells covered"
        )


        if not newly_covered:
            app_log.info(f"[geo] Depth {depth}: zero coverage hits, stopping early.")
            _status("No coverage found in these zones, trying a different approach…")
            break


        avg_diag    = sum(_cell_diagonal_km(*c) for c in newly_covered) / len(newly_covered)
        at_min_size = (avg_diag <= min_cell_km or depth == max_depth - 1)


        if at_min_size:
            # Filter exhausted cells — we know all their panos have already been shown
            fresh = [c for c in newly_covered if c not in cur_exhausted]
            if fresh:
                covered_cells = fresh
                skipped = len(newly_covered) - len(fresh)
                app_log.info(
                    f"[geo] Terminating at depth {depth}: {len(covered_cells)} fresh cells "
                    f"({skipped} exhausted skipped), avg diag {avg_diag:.2f} km"
                )
                _status(
                    f"Found {len(covered_cells)} zone{'s' if len(covered_cells) != 1 else ''} "
                    f"with coverage — picking a location…"
                )
                break
            elif depth == max_depth - 1:
                # Absolute limit reached with all cells exhausted — reuse as last resort
                covered_cells = newly_covered
                app_log.info(f"[geo] Max depth reached with all cells exhausted — reusing.")
                break
            # All covered cells are exhausted but we can still go deeper —
            # fall through to subdivision so the tree grows finer


        # When choosing which cell to subdivide, prefer non-exhausted cells so the
        # tree grows into fresh territory rather than re-exploring known-used areas
        candidates          = [c for c in newly_covered if c not in cur_exhausted]
        chosen_to_subdivide = random.choice(candidates if candidates else newly_covered)
        sub                 = _subdivide_cell(*chosen_to_subdivide, subdivide_by)
        next_cells          = [s for s in sub if _cell_has_region_overlap(*s, polygons)]
        random.shuffle(next_cells)


        exhausted_label = "exhausted" if chosen_to_subdivide in cur_exhausted else "fresh"
        app_log.info(
            f"[geo] Depth {depth}: subdividing 1/{len(newly_covered)} covered cells "
            f"({exhausted_label}) -> {len(next_cells)} sub-cells after region filter"
        )
        _status(
            f"Zooming into a promising zone "
            f"({len(next_cells)} smaller areas to check)…"
        )


        live_cells    = next_cells
        covered_cells = newly_covered


    if not covered_cells:
        app_log.warning("[geo] Adaptive search: no covered cells found.")
        return None


    # ── Final selection: unique pano, go deeper on repeat, mark exhausted ─────
    def _pick_unique(cells, extra_depth=0):
        """
        Return a fresh pano from cells that hasn't been shown yet this session.


        On a repeat, subdivide those cells one level deeper and recurse.  Any cell
        whose sub-tree has no remaining fresh panos is marked exhausted so the main
        quadtree stops treating it as a valid termination candidate on future rounds
        and subdivides it further instead — ensuring the game never repeats itself
        as long as there are undiscovered panos anywhere in the region.
        """
        random.shuffle(cells)
        repeat_cells = []


        for cell in cells:
            hit = _try_cell(cell)
            if not hit:
                continue
            pano_id, pano_lat, pano_lng = hit
            if pano_id not in used_panos:
                _cache_mark_used(region_key, pano_id)
                app_log.info(
                    f"[geo] Fresh pano {pano_id} @ ({pano_lat:.4f},{pano_lng:.4f}) "
                    f"[extra_depth={extra_depth}]"
                )
                return pano_id, pano_lat, pano_lng
            repeat_cells.append(cell)


        if not repeat_cells:
            return None  # no panos found at all in these cells


        if extra_depth >= 3:
            # Hit extra-depth limit — mark all repeated cells exhausted, then accept repeat
            for cell in repeat_cells:
                _cache_mark_exhausted(region_key, cell)
            for cell in cells:
                hit = _try_cell(cell)
                if hit:
                    _cache_mark_used(region_key, hit[0])
                    app_log.info(f"[geo] Uniqueness depth limit — reusing pano {hit[0]}")
                    return hit
            return None


        # Subdivide repeated cells to search for geographically distinct panos
        _status("All nearby panos seen before — zooming in for a fresh location…")
        deeper_cells    = []
        no_sub_coverage = []  # cells whose sub-cells all came back dead


        for cell in repeat_cells:
            if _cell_diagonal_km(*cell) < 0.25:  # ~250 m → single-pano resolution
                _cache_mark_exhausted(region_key, cell)
                continue
            found_sub = False
            for sub_cell in _subdivide_cell(*cell, subdivide_by):
                if not _cell_has_region_overlap(*sub_cell, polygons):
                    continue
                c_lat, c_lng = _cell_center(*sub_cell)
                diag     = _cell_diagonal_km(*sub_cell)
                r        = _cell_search_radius_m(diag, max_radius_m)
                probe    = _sv_metadata_check(c_lat, c_lng, r, api_key)
                if probe:
                    p_id, p_lat, p_lng = probe
                    if _point_in_any_polygon(p_lat, p_lng, polygons):
                        deeper_cells.append(sub_cell)
                        _cache_add(region_key, sub_cell)
                        found_sub = True
                else:
                    _cache_add_dead(region_key, sub_cell)
            if not found_sub:
                no_sub_coverage.append(cell)


        # Cells whose entire sub-tree is dead are exhausted
        for cell in no_sub_coverage:
            _cache_mark_exhausted(region_key, cell)


        if deeper_cells:
            app_log.info(
                f"[geo] Uniqueness: {len(deeper_cells)} deeper cells found, "
                f"{len(no_sub_coverage)} cells marked exhausted "
                f"(extra_depth={extra_depth + 1})"
            )
            result = _pick_unique(deeper_cells, extra_depth + 1)
            if result:
                return result
            # Deeper search also found nothing fresh — mark original cells exhausted
            for cell in repeat_cells:
                _cache_mark_exhausted(region_key, cell)


        # No fresh pano reachable anywhere — accept a repeat as absolute last resort
        for cell in cells:
            hit = _try_cell(cell)
            if hit:
                _cache_mark_used(region_key, hit[0])
                app_log.info(f"[geo] No fresh panos reachable — reusing {hit[0]}")
                return hit
        return None


    result = _pick_unique(covered_cells)
    if result:
        return result


    app_log.warning("[geo] Final selection returned nothing.")
    return None




# ── Extract pano info from streetview library results ────────────────────────


def _extract_pano_info(result, default_lat, default_lng):
    if isinstance(result, dict):
        pano_id  = result.get("pano_id") or result.get("panoid") or result.get("id", "")
        pano_lat = float(result.get("lat", default_lat))
        pano_lng = float(result.get("lon", result.get("lng", default_lng)))
    else:
        pano_id  = str(getattr(result, "pano_id", "") or getattr(result, "panoid", ""))
        pano_lat = float(getattr(result, "lat", default_lat))
        pano_lng = float(getattr(result, "lon", getattr(result, "lng", default_lng)))
    return pano_id.strip(), pano_lat, pano_lng




# ── Master panorama finder ────────────────────────────────────────────────────


# FIX: added status_cb=None parameter so callers can pass it through
def _find_pano(polygons: list, region_is_world: bool,
               region_key: str = None, on_timeout=None,
               status_cb=None) -> tuple:
    if not _SV_OK:
        raise Exception(
            "The 'streetview' library is not installed. Run: pip install streetview"
        )


    if region_is_world or not polygons:
        while True:
            if random.random() < 0.85:
                base_lat, base_lng = random.choice(_WORLD_CITIES)
                jitter = random.uniform(0.05, 0.45)
                lat = max(-85.0, min(85.0,  base_lat + random.uniform(-jitter, jitter)))
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
            app_log.info(f"[geo] World pano {pano_id} @ ({pano_lat:.4f},{pano_lng:.4f})")
            return pano_id, pano_lat, pano_lng


    valid_polys = [p for p in polygons if isinstance(p, list) and len(p) >= 3]
    if not valid_polys:
        raise GeoNoCoverageError("Region polygon is empty or invalid.")


    api_key = getattr(config, "GOOGLE_MAPS_EMBED_KEY", "")


    if api_key:
        # FIX: status_cb is now forwarded from the parameter instead of a non-existent global
        result = _find_pano_region(
            valid_polys,
            region_key or _region_hash(valid_polys),
            api_key,
            on_timeout=on_timeout,
            status_cb=status_cb,
        )
        if result:
            return result
        raise GeoNoCoverageError("No Street View coverage found in the selected region.")


    else:
        app_log.warning("[geo] No API key -- using streetview library for region mode")
        max_retries = int(  getattr(config, "GEO_REGION_MAX_RETRIES",      50))
        spread      = float(getattr(config, "GEO_REGION_NEIGHBOR_SPREAD", 0.015))
        offsets = [(0, 0), (spread, 0), (-spread, 0), (0, spread), (0, -spread)]
        for attempt in range(max_retries):
            pt = _random_point_in_any_polygon(valid_polys)
            if pt is None:
                break
            base_lat, base_lng = pt
            for dlat, dlng in offsets:
                clat = max(-85.0, min(85.0,   base_lat + dlat))
                clng = max(-180.0, min(180.0, base_lng + dlng))
                try:
                    results = _search_panoramas(lat=clat, lon=clng)
                except Exception:
                    continue
                if not results:
                    continue
                pano_id, pano_lat, pano_lng = _extract_pano_info(results[0], clat, clng)
                if pano_id and _point_in_any_polygon(pano_lat, pano_lng, valid_polys):
                    app_log.info(
                        f"[geo] Region pano (no-key, attempt {attempt+1}): "
                        f"{pano_id} @ ({pano_lat:.4f},{pano_lng:.4f})"
                    )
                    return pano_id, pano_lat, pano_lng
        app_log.warning("[geo] Region no-key search exhausted.")
        raise GeoNoCoverageError("No Street View coverage found in the selected region.")




# ── Room helpers ──────────────────────────────────────────────────────────────


def _rn(room_id: str) -> str:
    return f"geo_{room_id}"




def _emit_lobby():
    public = [
        {
            "id":                      r["id"],
            "title":                   r["title"],
            "players":                 len(r["players"]),
            "rounds":                  r["rounds_total"],
            "time":                    r["round_time_limit"],
            "status":                  r["status"],
            "region_is_world":         r["region_is_world"],
            "region":                  r["region"],
            "region_label":            r["region_label"],
            "region_preset_usernames": r["region_preset_usernames"],
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
            "id":                      room["id"],
            "title":                   room["title"],
            "privacy":                 room["privacy"],
            "creator_sid":             room["creator_sid"],
            "players":                 [
                {"sid": p["sid"], "username": p["username"], "total_score": p["total_score"]}
                for p in room["players"]
            ],
            "status":                  room["status"],
            "rounds_total":            room["rounds_total"],
            "round_current":           room["round_current"],
            "time_limit":              room["round_time_limit"],
            "region_is_world":         room["region_is_world"],
            "region":                  room["region"],
            "region_label":            room["region_label"],
            "region_preset_usernames": room["region_preset_usernames"],
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
                old_key = room.get("region_key")
                del geo_rooms[room_id]
                if old_key:
                    _cache_release(old_key)
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
        old_sp_key = sess.get("sp_region_key")
        geo_sessions.pop(sid, None)
        if old_sp_key:
            _cache_release(old_sp_key)
    for rid, r in list(geo_rooms.items()):
        if r["privacy"] == "private" and r["status"] == "waiting":
            _emit_invite_candidates(rid)
    if not full_delete:
        _emit_lobby()




# ── Round lifecycle ───────────────────────────────────────────────────────────


def _prefetch_room_pano(room_id: str) -> None:
    room = geo_rooms.get(room_id)
    if not room or room.get("region_is_world"):
        return
    room["prefetched_pano"] = None
    polygons   = room.get("region", [])
    region_key = room.get("region_key")


    def _fetch():
        try:
            result = _find_pano(polygons, False, region_key=region_key)
            r = geo_rooms.get(room_id)
            if r:
                r["prefetched_pano"] = result
                app_log.info(f"[geo prefetch] room {room_id}: pano ready")
        except Exception as e:
            app_log.debug(f"[geo prefetch] room {room_id}: fetch failed: {e}")


    threading.Thread(target=_fetch, daemon=True).start()




def _prefetch_sp_pano(sid: str) -> None:
    sess = geo_sessions.get(sid)
    if not sess or sess.get("sp_region_is_world"):
        return
    polygons   = sess.get("sp_polygons", [])
    region_key = sess.get("sp_region_key")
    if not polygons or not region_key:
        return
    sess["sp_prefetched_pano"] = None


    def _fetch():
        try:
            result = _find_pano(polygons, False, region_key=region_key)
            s = geo_sessions.get(sid)
            if s and s.get("sp_region_key") == region_key:
                s["sp_prefetched_pano"] = result
                app_log.info(f"[geo prefetch] SP {sid[:8]}: pano ready")
        except Exception as e:
            app_log.debug(f"[geo prefetch] SP {sid[:8]}: fetch failed: {e}")


    threading.Thread(target=_fetch, daemon=True).start()




def _start_round(room_id: str):
    room = geo_rooms.get(room_id)
    if not room:
        return
    room["status"]        = "loading"
    room["round_guesses"] = {}
    _cancel_room_timer(room)
    socketio.emit("geo_loading", {"message": "Finding a location..."}, room=_rn(room_id))


    creator_sid      = room.get("creator_sid")
    is_region_search = not room["region_is_world"]
    region_key       = room.get("region_key")


    def on_timeout():
        socketio.emit(
            "geo_region_timeout",
            {"creator_sid": creator_sid},
            room=_rn(room_id),
        )


    def fetch_and_start():
        def _room_status(msg):
            socketio.emit("geo_search_status", {"message": msg}, room=_rn(room_id))


        prefetched = room.get("prefetched_pano")
        if prefetched:
            room["prefetched_pano"] = None
            pano_id, lat, lng = prefetched
            app_log.info(f"[geo] Room {room_id}: using prefetched pano {pano_id}")
        else:
            # FIX: removed the duplicate _find_pano call that existed after this block.
            # status_cb=_room_status is now passed in the single call here.
            try:
                pano_id, lat, lng = _find_pano(
                    room["region"],
                    room["region_is_world"],
                    region_key=region_key,
                    on_timeout=(on_timeout if is_region_search else None),
                    status_cb=_room_status,
                )
            except GeoNoCoverageError:
                room2 = geo_rooms.get(room_id)
                if room2:
                    room2["status"] = "waiting"
                    _emit_room(room_id)
                socketio.emit("geo_region_no_coverage", {}, room=_rn(room_id))
                return
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
                "round":                   room2["round_current"],
                "total_rounds":            room2["rounds_total"],
                "pano_id":                 pano_id,
                "round_secs":              room2["round_time_limit"],
                "region_label":            room2["region_label"],
                "region_preset_usernames": room2["region_preset_usernames"],
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
                polygons        = room.get("region", []),
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
            "round":                   room["round_current"],
            "correct_lat":             correct_lat,
            "correct_lng":             correct_lng,
            "results":                 results,
            "advance_secs":            ROUND_ADVANCE_SECS,
            "region_label":            room.get("region_label", ""),
            "region_preset_usernames": room.get("region_preset_usernames", []),
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
    if room["round_current"] < room["rounds_total"]:
        _prefetch_room_pano(room_id)
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


def _normalize_polygons(polygons: list) -> list:
    """Wrap all polygon longitudes into [-180, 180]."""
    normalized = []
    for poly in polygons:
        norm_poly = []
        for point in poly:
            lat = point[0]
            lng = point[1]
            # Wrap longitude into [-180, 180]
            lng = ((lng + 180) % 360) - 180
            norm_poly.append([lat, lng])
        normalized.append(norm_poly)
    return normalized

@socketio.on("geo_create_room")
def handle_create_room(data):
    sid = request.sid
    if sid not in geo_sessions:
        emit("geo_error", {"message": "Set a username first."}); return


    title                   = (data.get("title") or "").strip() or "My Room"
    privacy                 = data.get("privacy", "public")
    rounds                  = int(data.get("rounds", 5))
    time_limit              = int(data.get("time_limit", 90))
    polygons                = data.get("polygons") or []
    polygons = _normalize_polygons(polygons)
    region_is_world         = bool(data.get("region_is_world", True))
    region_label            = str(data.get("region_label", "Entire World"))[:120]
    region_preset_usernames = list(data.get("region_preset_usernames") or [])


    if f.check_profanity(title):
        emit("geo_error", {"message": "Room title contains disallowed words."}); return
    if privacy not in ("public", "private"):
        privacy = "public"
    rounds     = max(1, min(10, rounds))
    time_limit = max(15, min(300, time_limit))
    if not region_is_world and len(polygons) == 0:
        emit("geo_error", {"message": "Draw a region or select a preset first."}); return


    room_id    = uuid.uuid4().hex[:8]
    username   = geo_sessions[sid]["username"]
    region_key = _region_hash(polygons) if not region_is_world else None


    geo_rooms[room_id] = {
        "id":                      room_id,
        "title":                   title,
        "privacy":                 privacy,
        "creator_sid":             sid,
        "players":                 [{"sid": sid, "username": username, "total_score": 0}],
        "status":                  "waiting",
        "region":                  polygons,
        "region_is_world":         region_is_world,
        "region_key":              region_key,
        "region_label":            region_label,
        "region_preset_usernames": region_preset_usernames,
        "rounds_total":            rounds,
        "round_current":           1,
        "round_time_limit":        time_limit,
        "current_panoid":          None,
        "current_location":        None,
        "round_guesses":           {},
        "round_timer":             None,
        "round_start_time":        None,
        "prefetched_pano":         None,
    }
    geo_sessions[sid]["room_id"] = room_id
    socketio.server.enter_room(sid, _rn(room_id))
    emit("geo_room_created", {"room_id": room_id})
    _emit_room(room_id)
    _emit_lobby()
    app_log.info(
        f"[geo] {username!r} created room {room_id} "
        f"({rounds}r,{time_limit}s,world={region_is_world},{privacy}) "
        f"label={region_label!r} cache_key={region_key and region_key[:8]}"
    )




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
    polygons        = data.get("polygons") or []
    polygons = _normalize_polygons(polygons)
    region_is_world = bool(data.get("region_is_world", True))


    emit("geo_sp_loading", {"message": "Finding a location..."})


    sess       = geo_sessions.get(sid, {})
    old_sp_key = sess.get("sp_region_key")
    new_sp_key = _region_hash(polygons) if not region_is_world else None


    sess["sp_region_key"]      = new_sp_key
    sess["sp_polygons"]        = polygons
    sess["sp_region_is_world"] = region_is_world


    if new_sp_key and new_sp_key == old_sp_key:
        prefetched = sess.pop("sp_prefetched_pano", None)
        if prefetched:
            app_log.info(f"[geo] SP {sid[:8]}: using prefetched pano {prefetched[0]}")
            socketio.emit(
                "geo_sp_panorama",
                {"pano_id": prefetched[0], "correct_lat": prefetched[1], "correct_lng": prefetched[2]},
                to=sid,
            )
            return


    if old_sp_key and old_sp_key != new_sp_key:
        _cache_release(old_sp_key)


    def on_timeout():
        socketio.emit("geo_region_timeout", {}, to=sid)


    def fetch():
        def _sp_status(msg):
            socketio.emit("geo_search_status", {"message": msg}, to=sid)


        # FIX: removed the duplicate _find_pano call that existed after this block.
        # status_cb=_sp_status is now passed in the single call here, inside the try/except.
        try:
            pano_id, lat, lng = _find_pano(
                polygons,
                region_is_world,
                region_key=new_sp_key,
                on_timeout=(on_timeout if not region_is_world else None),
                status_cb=_sp_status,
            )
            socketio.emit(
                "geo_sp_panorama",
                {"pano_id": pano_id, "correct_lat": lat, "correct_lng": lng},
                to=sid,
            )
        except GeoNoCoverageError:
            socketio.emit("geo_region_no_coverage", {}, to=sid)
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
        polygons        = sess.get("sp_polygons", []),
        region_is_world = sess.get("sp_region_is_world", True),
    )
    emit("geo_sp_result", {
        "distance_km": round(dist, 2),
        "score":       score,
        "correct_lat": correct_lat,
        "correct_lng": correct_lng,
    })
    _prefetch_sp_pano(request.sid)




# ── Disconnect ────────────────────────────────────────────────────────────────


@socketio.on("disconnect")
def handle_geo_disconnect():
    _cleanup_player(request.sid, full_delete=True)
