# socket_events/geoguesser_events.py
"""
GeoGuesser multiplayer + singleplayer socket events.

Region format (v2):
  region: List[List[List[float]]]  — list of polygons, each polygon = [[lat,lng], ...]
  region_is_world: bool
  region_label: str                — display name ("Entire World", "Custom Region", preset title, etc.)
  region_preset_usernames: List[str] — creator usernames for presets

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

try:
    from streetview import search_panoramas as _search_panoramas
    _SV_OK = True
except ImportError:
    _search_panoramas = None
    _SV_OK = False
    error_log.warning("[geo] 'streetview' library not found. Run: pip install streetview")

# ── In-memory state ───────────────────────────────────────────────────────────
geo_sessions: dict[str, dict] = {}
geo_rooms:    dict[str, dict] = {}

ROUND_ADVANCE_SECS   = 9
MAX_LOCATION_RETRIES = 50

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
    (22.54,114.06),(1.35,103.82),(3.15,101.69),(13.75,100.52),(21.03,105.85),
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
    """Returns True if (lat,lng) is inside any polygon in the list."""
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
    """Pick a random interior point from any polygon, trying each in random order."""
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
    """Bounding-box diagonal across ALL polygons combined."""
    all_lats = [p[0] for poly in polygons for p in poly]
    all_lngs = [p[1] for poly in polygons for p in poly]
    if not all_lats:
        return 0.0
    return haversine_km(min(all_lats), min(all_lngs), max(all_lats), max(all_lngs))


def geo_score(distance_km: float, polygons: list = None,
              region_is_world: bool = True) -> int:
    """
    Score 0–5000. World mode: exponential decay over 2000 km.
    Region mode: decay scaled to bbox diagonal × GEO_REGION_SCORE_DECAY_FACTOR.
    polygons: List[List[List[float]]] — list of polygons.
    """
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
    """
    Query the official (free) Street View Static metadata endpoint.
    Returns (pano_id, pano_lat, pano_lng) or None.
    pano_lat/pano_lng are the ACTUAL panorama coordinates, not the query point.
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
 
 
# ── Cell geometry helpers ─────────────────────────────────────────────────────
 
def _cell_diagonal_km(lat_min: float, lat_max: float,
                       lng_min: float, lng_max: float) -> float:
    """Haversine distance from SW corner to NE corner of a cell."""
    return haversine_km(lat_min, lng_min, lat_max, lng_max)
 
 
def _cell_center(lat_min: float, lat_max: float,
                  lng_min: float, lng_max: float) -> tuple:
    return ((lat_min + lat_max) / 2.0, (lng_min + lng_max) / 2.0)
 
 
def _cell_search_radius_m(diagonal_km: float, max_radius_m: int) -> int:
    """
    Search radius = half the cell diagonal (so the search circle
    circumscribes the cell), capped at max_radius_m.
    """
    return min(max_radius_m, max(100, int(diagonal_km * 500)))
 
 
def _cell_has_region_overlap(lat_min: float, lat_max: float,
                               lng_min: float, lng_max: float,
                               polygons: list) -> bool:
    """
    Fast pre-filter: returns True if the cell plausibly overlaps the region.
    Checks the center + 4 corners + 4 edge midpoints against all polygons.
    This catches thin corridors that miss the center-only test.
    """
    c_lat = (lat_min + lat_max) / 2.0
    c_lng = (lng_min + lng_max) / 2.0
    probe_points = [
        (c_lat,   c_lng),                          # center
        (lat_min, lng_min),                         # SW
        (lat_min, lng_max),                         # SE
        (lat_max, lng_min),                         # NW
        (lat_max, lng_max),                         # NE
        (c_lat,   lng_min),                         # W edge mid
        (c_lat,   lng_max),                         # E edge mid
        (lat_min, c_lng),                           # S edge mid
        (lat_max, c_lng),                           # N edge mid
    ]
    return any(
        _point_in_any_polygon(lat, lng, polygons)
        for lat, lng in probe_points
    )
 
 
def _subdivide_cell(lat_min: float, lat_max: float,
                     lng_min: float, lng_max: float,
                     n: int) -> list:
    """
    Divide a cell into n×n sub-cells.
    Returns a list of (lat_min, lat_max, lng_min, lng_max) tuples.
    """
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
 
def _find_pano_region(polygons: list, api_key: str, on_timeout=None):
    """
    Adaptive quadtree coverage search.
 
    Algorithm
    ---------
    1. Cover the combined bounding box of all polygons with an initial
       coarse grid of GEO_COVERAGE_INITIAL_DIVISIONS × GEO_COVERAGE_INITIAL_DIVISIONS
       cells. Keep only cells that overlap the region (9-point probe).
 
    2. For each surviving cell, query the Street View Metadata API with a
       search radius equal to half the cell's diagonal. If the returned
       panorama lands INSIDE the cell AND INSIDE the region polygon, the
       cell is marked "covered".
 
    3. Take all covered cells from step 2, subdivide each one into
       GEO_COVERAGE_SUBDIVIDE_BY × GEO_COVERAGE_SUBDIVIDE_BY sub-cells,
       and repeat step 2 on those sub-cells.
 
    4. Repeat until the cell diagonal ≤ GEO_COVERAGE_MIN_CELL_KM  OR
       the iteration count reaches GEO_COVERAGE_MAX_DEPTH.
 
    5. From the finest-level covered cells, pick one UNIFORMLY AT RANDOM
       (so dense city clusters are not over-represented) and do a final
       tight-radius query to return the definitive pano ID.
 
    The double containment check (cell bounds + polygon bounds) is what
    prevents panoramas from leaking outside the drawn region.
 
    Returns (pano_id, pano_lat, pano_lng) or None.
    """
    # ── Config ────────────────────────────────────────────────────────────────
    initial_divs  = int(  getattr(config, "GEO_COVERAGE_INITIAL_DIVISIONS",  4))
    subdivide_by  = int(  getattr(config, "GEO_COVERAGE_SUBDIVIDE_BY",       3))
    min_cell_km   = float(getattr(config, "GEO_COVERAGE_MIN_CELL_KM",      3.0))
    max_depth     = int(  getattr(config, "GEO_COVERAGE_MAX_DEPTH",          6))
    timeout_s     = float(getattr(config, "GEO_COVERAGE_TIMEOUT_SECS",     30.0))
    max_radius_m  = int(  getattr(config, "GEO_COVERAGE_MAX_RADIUS_M",   50_000))
 
    # ── Combined bounding box ─────────────────────────────────────────────────
    all_lats = [p[0] for poly in polygons for p in poly]
    all_lngs = [p[1] for poly in polygons for p in poly]
    bb_lat_min, bb_lat_max = min(all_lats), max(all_lats)
    bb_lng_min, bb_lng_max = min(all_lngs), max(all_lngs)
 
    # ── Timeout machinery ─────────────────────────────────────────────────────
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
 
    # ── Step 1: initial coarse grid ───────────────────────────────────────────
    initial_cells = _subdivide_cell(
        bb_lat_min, bb_lat_max,
        bb_lng_min, bb_lng_max,
        initial_divs,
    )
 
    # Pre-filter: discard cells that don't overlap the region at all
    live_cells = [
        c for c in initial_cells
        if _cell_has_region_overlap(*c, polygons)
    ]
 
    diag_km = _cell_diagonal_km(
        bb_lat_min, bb_lat_max, bb_lng_min, bb_lng_max
    ) / initial_divs
 
    app_log.info(
        f"[geo] Adaptive search start: {len(initial_cells)} coarse cells → "
        f"{len(live_cells)} overlap region, cell diag ≈ {diag_km:.1f} km"
    )
 
    # ── Steps 2–4: iterative coverage probing ─────────────────────────────────
    covered_cells = []   # finest-level cells with confirmed coverage
 
    for depth in range(max_depth):
        _check_timeout()
        if not live_cells:
            app_log.info(f"[geo] Depth {depth}: no live cells remaining, stopping.")
            break
 
        diag_km = _cell_diagonal_km(*live_cells[0], ) if live_cells else 0.0
 
        app_log.info(
            f"[geo] Depth {depth}: probing {len(live_cells)} cells, "
            f"diag ≈ {diag_km:.1f} km"
        )
 
        newly_covered = []
 
        for cell in live_cells:
            lat_min, lat_max, lng_min, lng_max = cell
            c_lat, c_lng = _cell_center(*cell)
            diag = _cell_diagonal_km(*cell)
            radius_m = _cell_search_radius_m(diag, max_radius_m)
 
            _check_timeout()
            result = _sv_metadata_check(c_lat, c_lng, radius_m, api_key)
            if not result:
                continue
 
            pano_id, pano_lat, pano_lng = result
 
            # Double containment: pano must be inside THIS cell AND inside region
            pano_in_cell   = (lat_min <= pano_lat <= lat_max and
                               lng_min <= pano_lng <= lng_max)
            pano_in_region = _point_in_any_polygon(pano_lat, pano_lng, polygons)
 
            if pano_in_cell and pano_in_region:
                newly_covered.append(cell)
 
        app_log.info(
            f"[geo] Depth {depth}: {len(newly_covered)}/{len(live_cells)} cells covered"
        )
 
        if not newly_covered:
            # No coverage found at this level — stop, don't go deeper
            app_log.info(f"[geo] Depth {depth}: zero coverage hits, stopping early.")
            break
 
        # Check termination condition
        avg_diag = sum(_cell_diagonal_km(*c) for c in newly_covered) / len(newly_covered)
        if avg_diag <= min_cell_km or depth == max_depth - 1:
            # We've reached sufficient resolution — these are our final candidates
            covered_cells = newly_covered
            app_log.info(
                f"[geo] Terminating at depth {depth}: avg diag {avg_diag:.2f} km, "
                f"{len(covered_cells)} candidate cells"
            )
            break
 
        # Subdivide covered cells for next iteration
        next_cells = []
        for cell in newly_covered:
            sub = _subdivide_cell(*cell, subdivide_by)
            # Pre-filter sub-cells against region
            next_cells.extend(
                s for s in sub
                if _cell_has_region_overlap(*s, polygons)
            )
        # Shuffle so we don't systematically prefer SW cells
        random.shuffle(next_cells)
        live_cells    = next_cells
        covered_cells = newly_covered   # keep as fallback in case depth terminates
 
    # ── Step 5: uniform random selection ─────────────────────────────────────
    if not covered_cells:
        app_log.warning("[geo] Adaptive search: no covered cells found.")
        return None
 
    # Pick uniformly at random — avoids density bias toward city clusters
    chosen = random.choice(covered_cells)
    c_lat, c_lng = _cell_center(*chosen)
    diag    = _cell_diagonal_km(*chosen)
    # Final query: tight radius = half the smallest cell diagonal
    radius_m = _cell_search_radius_m(diag, max_radius_m)
 
    result = _sv_metadata_check(c_lat, c_lng, radius_m, api_key)
    if result:
        pano_id, pano_lat, pano_lng = result
        # Final containment check
        lat_min, lat_max, lng_min, lng_max = chosen
        if (lat_min <= pano_lat <= lat_max and
                lng_min <= pano_lng <= lng_max and
                _point_in_any_polygon(pano_lat, pano_lng, polygons)):
            app_log.info(
                f"[geo] Adaptive final pano: {pano_id} "
                f"@ ({pano_lat:.4f},{pano_lng:.4f}), "
                f"cell diag {diag:.2f} km"
            )
            return pano_id, pano_lat, pano_lng
 
    # Fallback: iterate remaining covered cells until we get a clean hit
    random.shuffle(covered_cells)
    for cell in covered_cells:
        c_lat, c_lng = _cell_center(*cell)
        diag     = _cell_diagonal_km(*cell)
        radius_m = _cell_search_radius_m(diag, max_radius_m)
        result   = _sv_metadata_check(c_lat, c_lng, radius_m, api_key)
        if not result:
            continue
        pano_id, pano_lat, pano_lng = result
        lat_min, lat_max, lng_min, lng_max = cell
        if (lat_min <= pano_lat <= lat_max and
                lng_min <= pano_lng <= lng_max and
                _point_in_any_polygon(pano_lat, pano_lng, polygons)):
            app_log.info(
                f"[geo] Adaptive fallback pano: {pano_id} "
                f"@ ({pano_lat:.4f},{pano_lng:.4f})"
            )
            return pano_id, pano_lat, pano_lng
 
    app_log.warning("[geo] Adaptive search: all covered cells re-queried with no clean hit.")
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
 
def _find_pano(polygons: list, region_is_world: bool, on_timeout=None) -> tuple:
    """
    Master panorama finder.
    polygons: List[List[List[float]]] — array of polygons (empty for world mode).
    Returns (pano_id, pano_lat, pano_lng). Never raises — falls back to world mode.
    """
    if not _SV_OK:
        raise Exception(
            "The 'streetview' library is not installed. Run: pip install streetview"
        )
 
    # ── World mode ────────────────────────────────────────────────────────────
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
 
    # ── Region mode ───────────────────────────────────────────────────────────
    valid_polys = [p for p in polygons if isinstance(p, list) and len(p) >= 3]
    if not valid_polys:
        app_log.warning("[geo] Empty/degenerate polygons — falling back to world mode")
        return _find_pano([], True)
 
    api_key = getattr(config, "GOOGLE_MAPS_EMBED_KEY", "")
 
    if api_key:
        result = _find_pano_region(valid_polys, api_key, on_timeout=on_timeout)
        if result:
            return result
        app_log.warning("[geo] Region search exhausted — falling back to world mode")
        return _find_pano([], True)
 
    else:
        # ── No-key fallback: streetview library with random interior points ──
        app_log.warning("[geo] No API key — using streetview library for region mode")
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
        app_log.warning("[geo] Region no-key search exhausted — falling back to world mode")
        return _find_pano([], True)

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

    creator_sid      = room.get("creator_sid")
    is_region_search = not room["region_is_world"]

    def on_timeout():
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

    title                   = (data.get("title") or "").strip() or "My Room"
    privacy                 = data.get("privacy", "public")
    rounds                  = int(data.get("rounds", 5))
    time_limit              = int(data.get("time_limit", 90))
    polygons                = data.get("polygons") or []          # List[List[List[float]]]
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

    room_id  = uuid.uuid4().hex[:8]
    username = geo_sessions[sid]["username"]

    geo_rooms[room_id] = {
        "id":                      room_id,
        "title":                   title,
        "privacy":                 privacy,
        "creator_sid":             sid,
        "players":                 [{"sid": sid, "username": username, "total_score": 0}],
        "status":                  "waiting",
        "region":                  polygons,
        "region_is_world":         region_is_world,
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
    }
    geo_sessions[sid]["room_id"] = room_id
    socketio.server.enter_room(sid, _rn(room_id))
    emit("geo_room_created", {"room_id": room_id})
    _emit_room(room_id)
    _emit_lobby()
    app_log.info(
        f"[geo] {username!r} created room {room_id} "
        f"({rounds}r,{time_limit}s,world={region_is_world},{privacy}) "
        f"label={region_label!r}"
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
    polygons        = data.get("polygons") or []     # List[List[List[float]]]
    region_is_world = bool(data.get("region_is_world", True))

    emit("geo_sp_loading", {"message": "Finding a location…"})
    geo_sessions[sid]["sp_polygons"]        = polygons
    geo_sessions[sid]["sp_region_is_world"] = region_is_world

    def on_timeout():
        socketio.emit("geo_region_timeout", {}, to=sid)

    def fetch():
        try:
            pano_id, lat, lng = _find_pano(
                polygons,
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
        polygons        = sess.get("sp_polygons", []),
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