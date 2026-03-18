# blueprints/geoguesser.py
from flask import Blueprint, render_template
import config
 
geoguesser_bp = Blueprint("geoguesser", __name__)
 
 
@geoguesser_bp.route("/geoguesser")
def geoguesser():
    return render_template(
        "geoguesser.html",
        google_maps_key      = getattr(config, "GOOGLE_MAPS_EMBED_KEY",   ""),
        geo_map_expanded_w   = int(getattr(config, "GEO_MAP_EXPANDED_WIDTH",  380)),
        geo_map_expanded_h   = int(getattr(config, "GEO_MAP_EXPANDED_HEIGHT", 280)),
    )