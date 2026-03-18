# blueprints/geoguesser.py
from flask import Blueprint, render_template
import config

geoguesser_bp = Blueprint("geoguesser", __name__)


@geoguesser_bp.route("/geoguesser")
def geoguesser():
    api_key = getattr(config, "GOOGLE_MAPS_EMBED_KEY", "")
    return render_template("geoguesser.html", google_maps_key=api_key)