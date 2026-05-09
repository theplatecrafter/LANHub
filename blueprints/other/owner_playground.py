"""
owner_playground.py

The owner/developer playground for LANHub.
A space for the owner to experiment with new features and ideas.
"""

from flask import Blueprint, render_template, jsonify, send_from_directory
from functions.owner_playground import get_task_manager
import os
from glob_vars import BASE_DIR

bp = Blueprint('owner_playground', __name__, url_prefix='/owner_playground')

OWNER_PLAYGROUND_FILES_DIR = os.path.join(BASE_DIR, 'files/owner_playground')


@bp.route('/')
def playground():
    """Render the owner playground page."""
    return render_template('owner_playground.html')


@bp.route('/sound-visualizer')
def sound_visualizer():
    """Render the 3D audio visualizer."""
    return render_template('OP_sound_visualizer.html')


@bp.route('/coherent-image-finder')
def coherent_image_finder():
    """Render the coherent image finder page."""
    return render_template('OP_Coherent_Images.html')


# ─── REST API Endpoints for Task Management ─────────────────────────────────

@bp.route('/api/tasks/stats', methods=['GET'])
def get_task_stats():
    """Get statistics for all playground tasks."""
    manager = get_task_manager()
    stats = manager.get_stats()
    return jsonify(stats)


@bp.route('/api/tasks/<task_name>/toggle', methods=['POST'])
def toggle_task(task_name):
    """Enable or disable a specific task."""
    manager = get_task_manager()
    
    with manager.lock:
        if task_name not in manager.tasks:
            return jsonify({"error": f"Task '{task_name}' not found"}), 404
        
        task = manager.tasks[task_name]
        task.enabled = not task.enabled
        
        return jsonify({
            "task": task_name,
            "enabled": task.enabled
        })


@bp.route('/api/images', methods=['GET'])
def list_images():
    """List all generated coherent images."""
    image_dir = os.path.join(OWNER_PLAYGROUND_FILES_DIR, 'Coherent_Images')
    
    if not os.path.exists(image_dir):
        return jsonify({"images": []})
    
    images = []
    for filename in sorted(os.listdir(image_dir)):
        if filename.endswith('.png'):
            images.append({
                "filename": filename,
                "url": f"/owner_playground/images/Coherent_Images/{filename}",
                "path": os.path.join(image_dir, filename)
            })
    
    # Return in reverse order (newest first)
    return jsonify({"images": images[::-1]})


@bp.route('/images/<path:subdir>/<filename>', methods=['GET'])
def serve_image(subdir, filename):
    """Serve a generated image file."""
    image_dir = os.path.join(OWNER_PLAYGROUND_FILES_DIR, subdir)
    return send_from_directory(image_dir, filename)