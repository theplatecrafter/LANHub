# blueprints/uno.py
from flask import Blueprint, render_template
uno_bp = Blueprint("uno", __name__)

@uno_bp.route("/uno")
def uno_page():
    return render_template("uno.html")