from flask import Blueprint, render_template


developer_playground_bp = Blueprint("developer_playground", __name__)


@developer_playground_bp.route("/developer_playground")
def developer_playground_index():
    return render_template(
        "developer_playground.html",
        projects=[
            {
                "title": "Sound Visualizer",
                "description": "Upload a local audio file and explore a reactive audio visualizer with waveform, FFT bands, and animated particles.",
                "slug": "sound-visualizer",
                "icon": "🎵",
                "label": "Audio",
            }
        ],
    )


@developer_playground_bp.route("/developer_playground/sound-visualizer")
def developer_playground_sound_visualizer():
    return render_template("sound_visualizer.html")
