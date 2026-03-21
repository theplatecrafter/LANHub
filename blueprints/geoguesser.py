# blueprints/geoguesser.py
import datetime
from flask import Blueprint, render_template, request, jsonify, session
import config
import functions as f
from glob_vars import app_log, error_log, access_log

geoguesser_bp = Blueprint("geoguesser", __name__)

import urllib.request as _urllib_req
import json as _json_bp
import random as _random_bp
import math as _math_bp

def _quick_coverage_check(polygons: list, api_key: str, attempts: int = 6) -> bool:
    """
    Sample a handful of random points in the polygon set.
    Returns True if at least one has Street View coverage within 50km.
    Fast enough to run synchronously on preset creation.
    """
    if not polygons or not api_key:
        return True   # no key = skip check, let the game fail naturally

    all_lats = [p[0] for poly in polygons for p in poly]
    all_lngs = [p[1] for poly in polygons for p in poly]
    if not all_lats:
        return False

    mn_lat, mx_lat = min(all_lats), max(all_lats)
    mn_lng, mx_lng = min(all_lngs), max(all_lngs)

    for _ in range(attempts):
        lat = _random_bp.uniform(mn_lat, mx_lat)
        lng = _random_bp.uniform(mn_lng, mx_lng)
        url = (
            "https://maps.googleapis.com/maps/api/streetview/metadata"
            f"?location={lat},{lng}&radius=50000&source=outdoor&key={api_key}"
        )
        try:
            with _urllib_req.urlopen(url, timeout=5) as resp:
                data = _json_bp.loads(resp.read().decode())
            if data.get("status") == "OK":
                return True
        except Exception:
            continue
    return False

@geoguesser_bp.route("/geoguesser")
def geoguesser():
    return render_template(
        "geoguesser.html",
        google_maps_key      = getattr(config, "GOOGLE_MAPS_EMBED_KEY",    ""),
        geo_map_expanded_w   = int(getattr(config, "GEO_MAP_EXPANDED_WIDTH",  380)),
        geo_map_expanded_h   = int(getattr(config, "GEO_MAP_EXPANDED_HEIGHT", 280)),
    )


# ── Preset search (returns id/title/username/created_at only, no polygon data) ──
@geoguesser_bp.route("/api/geo/presets/search")
def api_preset_search():
    q      = request.args.get("q", "").strip()
    presets = f.geo_preset_search(q)
    for p in presets:
        p["created_str"] = datetime.datetime.fromtimestamp(
            p["created_at"]).strftime("%Y-%m-%d")
    return jsonify({"presets": presets})


# ── Fetch a single preset with full polygon data ──────────────────────────────
@geoguesser_bp.route("/api/geo/presets/<int:preset_id>")
def api_preset_get(preset_id):
    p = f.geo_preset_get_by_id(preset_id)
    if not p:
        return jsonify({"ok": False, "error": "Not found."}), 404
    p["created_str"] = datetime.datetime.fromtimestamp(
        p["created_at"]).strftime("%Y-%m-%d")
    return jsonify({"ok": True, "preset": p})


# ── Create a preset ───────────────────────────────────────────────────────────
@geoguesser_bp.route("/api/geo/presets/create", methods=["POST"])
def api_preset_create():
    data     = request.get_json(silent=True) or {}
    title    = str(data.get("title",    "")).strip()
    username = str(data.get("username", "")).strip()
    polygons = data.get("polygons", [])

    if not title:
        return jsonify({"ok": False, "error": "Title is required."}), 400
    if len(title) > 80:
        return jsonify({"ok": False, "error": "Title too long (max 80 chars)."}), 400
    if not username:
        return jsonify({"ok": False, "error": "Username is required."}), 400
    if len(username) > 32:
        return jsonify({"ok": False, "error": "Username too long."}), 400
    if f.check_profanity(title):
        return jsonify({"ok": False, "error": "Title contains disallowed words."}), 400
    if not isinstance(polygons, list) or len(polygons) == 0:
        return jsonify({"ok": False, "error": "No region data provided."}), 400

    # Validate structure: each polygon must have at least 3 points
    for poly in polygons:
        if not isinstance(poly, list) or len(poly) < 3:
            return jsonify({"ok": False, "error": "Each region must have at least 3 points."}), 400

    # ── Coverage check ────────────────────────────────────────
    api_key = getattr(config, "GOOGLE_MAPS_EMBED_KEY", "")
    if api_key:
        if not _quick_coverage_check(polygons, api_key):
            return jsonify({
                "ok":    False,
                "error": "No Street View panoramas found in this region. "
                         "Try drawing a larger or more populated area."
            }), 400
    # ─────────────────────────────────────────────────────────


    try:
        preset = f.geo_preset_create(title, username, polygons)
        access_log.info(
            f"[geo] {request.remote_addr} ({username}) created preset '{title}' "
            f"({len(polygons)} polygon(s))"
        )
        preset["created_str"] = datetime.datetime.fromtimestamp(
            preset["created_at"]).strftime("%Y-%m-%d")
        return jsonify({"ok": True, "preset": preset})
    except Exception as e:
        error_log.error(f"[geo] preset create error: {e}")
        return jsonify({"ok": False, "error": "Server error."}), 500


# ── Delete a preset (admin only) ──────────────────────────────────────────────
@geoguesser_bp.route("/api/geo/presets/<int:preset_id>/delete", methods=["POST"])
def api_preset_delete(preset_id):
    if session.get("admin_role") not in ("MOD", "DEV"):
        return jsonify({"ok": False, "error": "Admin access required."}), 403
    f.geo_preset_delete(preset_id)
    app_log.info(
        f"[geo] admin {session.get('admin_name')!r} deleted preset #{preset_id}"
    )
    return jsonify({"ok": True})