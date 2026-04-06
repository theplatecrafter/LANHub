# blueprints/slither.py
from flask import Blueprint, render_template

slither_bp = Blueprint("slither", __name__)

@slither_bp.route("/slither")
def slither():
    return render_template("slither.html")