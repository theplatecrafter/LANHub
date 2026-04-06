# blueprints/uno.py
from flask import Blueprint, render_template
uno_bp = Blueprint("uno", __name__)

@uno_bp.route("/uno")
def uno():
    from game_logic.uno import UNO_TYPES
    types_for_template = [
        {'key': k, 'name': v['name'],
         'min': v['min_players'], 'max': v['max_players'],
         'desc': v['description']}
        for k, v in UNO_TYPES.items()
    ]
    return render_template("uno.html", uno_types=types_for_template)