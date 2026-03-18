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
from configvars import SECRET_KEY
import datetime

app = Flask(__name__)
app.secret_key = SECRET_KEY

# Blueprints
from blueprints.chat import chat_bp
from blueprints.stats import stats_bp
from blueprints.logs import logs_bp
from blueprints.devices import devices_bp
from blueprints.admin import admin_bp, check_ban
from blueprints.dropzone import dropzone_bp
from blueprints.channels import channels_bp




# Socket event handlers
import socket_events.chat_events
import socket_events.global_events
import socket_events.console_events
import socket_events.channels_events


socketio.init_app(app)
app.register_blueprint(chat_bp)
app.register_blueprint(stats_bp)
app.register_blueprint(logs_bp)
app.register_blueprint(devices_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(dropzone_bp)
app.before_request(check_ban)
app.register_blueprint(channels_bp)


###########################################
# App Configs
###########################################
app.config["MAX_CONTENT_LENGTH"] = DROPZONE_MAX_FILE_BYTES



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

###########################################
# Routes
###########################################
@app.route("/")
def index():
    return render_template("root.html")



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
    socketio.run(app, host="0.0.0.0",debug=True,port=PORT,allow_unsafe_werkzeug=True)