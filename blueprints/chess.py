# blueprints/chess.py
from flask import Blueprint, render_template
chess_bp = Blueprint("chess", __name__)

@chess_bp.route("/chess")
def chess_page():
    return render_template("chess.html")