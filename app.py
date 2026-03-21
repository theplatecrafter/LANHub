# app.py
from glob_vars import *
from init import initialize
initialize()

import os
from flask import Flask,render_template, session, redirect, url_for, request
from socketio_instance import socketio
import scheduler as sch
import sys
import signal
import datetime
import re as _re
import config as _config

app = Flask(__name__)
app.secret_key = _config.SECRET_KEY

# Blueprints
from blueprints.chat import chat_bp
from blueprints.stats import stats_bp
from blueprints.logs import logs_bp
from blueprints.devices import devices_bp
from blueprints.admin import admin_bp, check_ban
from blueprints.dropzone import dropzone_bp
from blueprints.channels import channels_bp
from blueprints.feedback import feedback_bp
from blueprints.polls import polls_bp
from blueprints.updates import updates_bp
from blueprints.chess import chess_bp
from blueprints.tetris import tetris_bp
from blueprints.uno import uno_bp
from blueprints.server_config import server_config_bp
from blueprints.slither import slither_bp
from blueprints.scribble import scribble_bp
from blueprints.geoguesser import geoguesser_bp
from blueprints.access import access_bp, check_site_access




# Socket event handlers
import socket_events.chat_events
import socket_events.global_events
import socket_events.console_events
import socket_events.channels_events
import socket_events.chess_events
import socket_events.tetris_events
import socket_events.uno_events
import socket_events.slither_events
import socket_events.scribble_events
import socket_events.geoguesser_events



socketio.init_app(app)
app.register_blueprint(chat_bp)
app.register_blueprint(stats_bp)
app.register_blueprint(logs_bp)
app.register_blueprint(devices_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(dropzone_bp)
app.before_request(check_site_access)
app.before_request(check_ban)
app.register_blueprint(channels_bp)
app.register_blueprint(feedback_bp)
app.register_blueprint(polls_bp)
app.register_blueprint(updates_bp)
app.register_blueprint(chess_bp)
app.register_blueprint(tetris_bp)
app.register_blueprint(uno_bp)
app.register_blueprint(server_config_bp)
app.register_blueprint(slither_bp)
app.register_blueprint(scribble_bp)
app.register_blueprint(geoguesser_bp)
app.register_blueprint(access_bp)


###########################################
# App Configs
###########################################
app.config["MAX_CONTENT_LENGTH"] = _config.DROPZONE_MAX_FILE_BYTES



###########################################
# Other Handlers
###########################################

@app.template_filter("timestamp_fmt")
def timestamp_fmt(ts):
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)

@app.errorhandler(413)
def too_large(e):
    from flask import jsonify
    return jsonify({"ok": False, "error": "File too large."}), 413

 
def _repo_url_to_pages(repo_url: str) -> str | None:
    """
    Convert a GitHub repo URL to its GitHub Pages URL.
 
    https://github.com/USER/REPO        →  https://USER.github.io/REPO/
    https://github.com/USER/REPO.git    →  https://USER.github.io/REPO/
    git@github.com:USER/REPO.git        →  https://USER.github.io/REPO/
 
    Returns None if the URL can't be parsed.
    """
    # HTTPS form
    m = _re.match(
        r'https?://github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?\s*$',
        repo_url.strip()
    )
    if m:
        return f"https://{m.group(1)}.github.io/{m.group(2)}/"
 
    # SSH form
    m = _re.match(
        r'git@github\.com:([^/\s]+)/([^/\s]+?)(?:\.git)?\s*$',
        repo_url.strip()
    )
    if m:
        return f"https://{m.group(1)}.github.io/{m.group(2)}/"
 
    return None
 
@app.context_processor
def inject_globals():
    import config as _config
    import re as _re
    def _repo_url_to_pages(url):
        m = _re.match(r'https?://github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?\s*$', url.strip())
        if m: return f"https://{m.group(1)}.github.io/{m.group(2)}/"
        m = _re.match(r'git@github\.com:([^/\s]+)/([^/\s]+?)(?:\.git)?\s*$', url.strip())
        if m: return f"https://{m.group(1)}.github.io/{m.group(2)}/"
        return None
    return {
        "share_url":       _repo_url_to_pages(getattr(_config, 'REPO_URL', '') or ''),
        "afk_idle_secs":   int(getattr(_config, 'AFK_IDLE_SECS',   300)),
         "afk_prompt_secs": int(getattr(_config, 'AFK_PROMPT_SECS',  60)),
    }


###########################################
# Routes
###########################################
@app.route("/")
def index():
    return render_template("root.html")


@app.route("/about")
def about():
    return render_template("about.html")


##########################################
# Graceful Shutdown Handler
##########################################
def graceful_shutdown(signum, frame):
    app_log.info(f"Received signal {signum}. Cleaning up...")
    
    if sch.scheduler.running:
        sch.scheduler.shutdown(wait=True)
        app_log.info("Scheduler shut down.")

    app_log.info("Server shutting down gracefully.")
    
    

    app_log.info("Cleanup complete. Exiting.")
    sys.exit(0)


signal.signal(signal.SIGINT, graceful_shutdown)
signal.signal(signal.SIGTERM, graceful_shutdown)

if __name__ == "__main__":
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        sch.start_scheduler()
    socketio.run(app, host="0.0.0.0",debug=True,port=_config.PORT,allow_unsafe_werkzeug=True)