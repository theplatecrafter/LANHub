# blueprints/scribble.py
from flask import Blueprint, render_template

scribble_bp = Blueprint("scribble", __name__)

@scribble_bp.route("/scribble")
def scribble():
    return render_template("scribble.html")