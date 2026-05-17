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