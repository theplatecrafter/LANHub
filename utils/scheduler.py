# scheduler.py
from glob_vars import *
from apscheduler.schedulers.background import BackgroundScheduler
import functions as f
from socketio_instance import socketio
import socket_events.global_events as ge



server_stats_cache = {}
def update_stats():
    global server_stats_cache

    route_counts      = ge.get_route_counts()
    total_connections = ge.get_total_connections()

    full_stats = f.get_full_server_stats(route_counts, total_connections)
    server_stats_cache = full_stats

    # Emit to all connected clients in the default namespace
    # When emitting from a background job (not in a request context),
    # specify namespace='/' to broadcast to all clients
    socketio.emit("server_stats", full_stats, namespace='/')

def push_offline_page():
    """
    Pushes a 'server offline' page to the GitHub redirector.
    Called during graceful shutdown so friends see a clean message.
    """
    try:
        from git import Repo
        import datetime, os
        repo = Repo(REDIRECTOR_PATH)
        repo.remotes.origin.fetch()
        repo.git.reset('--hard', 'origin/main')
        repo.git.clean('-fd')

        offline_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>LANHub - Offline</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
               background: #0f1117; color: #e2e8f0; display: flex;
               align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
        .card { background: #1a1d27; border: 1px solid #2d3148; border-radius: 14px;
                padding: 2.5rem 2rem; max-width: 420px; width: 100%; text-align: center; }
        .icon { font-size: 2.5rem; margin-bottom: .6rem; }
        h1 { font-size: 1.4rem; color: #f87171; margin-bottom: .4rem; }
        p { color: #94a3b8; font-size: .9rem; line-height: 1.6; }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">🛰️</div>
        <h1>Server Offline</h1>
        <p>LANHub is currently offline.<br>Check back later.</p>
    </div>
</body>
</html>"""

        path = os.path.join(REDIRECTOR_PATH, "index.html")
        with open(path, "w") as fh:
            fh.write(offline_html)

        repo.index.add(["index.html"])
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        repo.index.commit(f"Server offline at {ts}")
        repo.remote("origin").push(force=True)
        git_log.info("[shutdown] Offline page pushed to redirector.")
        return True
    except Exception as e:
        git_log.error(f"[shutdown] Failed to push offline page: {e}")
        return False



#########################################################
# Lab Idle Timeout Management
##########################################################
def sch_lab_idle_check():
    """Periodically check for idle Lab projects and stop spontaneous ones."""
    try:
        from functions.lab import project_check_idle
        import os
        
        # Check if Lab feature is enabled
        lab_enabled_flag = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".lab_enabled")
        if not os.path.isfile(lab_enabled_flag):
            return
        
        project_check_idle()
    except Exception as e:
        app_log.error(f"[Lab] Idle timeout check failed: {e}")

#########################################################
# Schedulers
##########################################################
scheduler = BackgroundScheduler()
scheduler.add_job(update_stats, "interval", seconds=5, max_instances=1, coalesce=True,misfire_grace_time=5)
scheduler.add_job(sch_lab_idle_check, "interval", seconds=60, max_instances=1, coalesce=True)

def start_scheduler():
    update_stats()
    scheduler.start()