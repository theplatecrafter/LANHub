from flask import Blueprint, render_template
from utils.scheduler import server_stats_cache

stats_bp = Blueprint("stats", __name__)

@stats_bp.route("/stats")
def stats():
    # Pass the latest cached snapshot so the page has data before
    # the first socket update arrives.
    return render_template("stats.html", initial=server_stats_cache)