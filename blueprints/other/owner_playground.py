"""
owner_playground.py

The owner/developer playground for LANHub.
A space for the owner to experiment with new features and ideas.
"""

from flask import Blueprint, render_template

bp = Blueprint('owner_playground', __name__, url_prefix='/owner_playground')


@bp.route('/')
def playground():
    """Render the owner playground page."""
    return render_template('owner_playground.html')


@bp.route('/sound-visualizer')
def sound_visualizer():
    """Render the 3D audio visualizer."""
    return render_template('OP_sound_visualizer.html')
