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

app = Flask(__name__)

# Blueprints
from blueprints.chat import chat_bp
from blueprints.stats import stats_bp


# Socket event handlers
import socket_events.chat_events
import socket_events.global_events

app.secret_key = os.urandom(24)
socketio.init_app(app)
app.register_blueprint(chat_bp)
app.register_blueprint(stats_bp)


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