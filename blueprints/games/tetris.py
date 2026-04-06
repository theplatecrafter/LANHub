from flask import Blueprint, render_template

tetris_bp = Blueprint("tetris", __name__)

@tetris_bp.route("/tetris")
def tetris():
    return render_template("tetris.html")