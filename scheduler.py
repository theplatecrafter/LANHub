from glob_vars import *

from apscheduler.schedulers.background import BackgroundScheduler
import functions as f
from socketio_instance import socketio



server_stats_cache = {}
def update_stats():
    global server_stats_cache
    server_stats_cache = f.get_server_stats()

    socketio.emit(
        "server_stats",
        server_stats_cache
    )


last_pushed_ip = None
def sch_redirector_update():
    global last_pushed_ip
    
    stats = f.get_network_stats()
    current_ip = stats.get("ip_address")
    server = stats.get("ssid", "Could Not Determine")
    
    if current_ip and current_ip != "127.0.0.1" and current_ip != last_pushed_ip:
        git_log.info(f"IP Change detected ({last_pushed_ip} -> {current_ip}). Updating GitHub...")
        success = f.redirector_update(current_ip,server, PORT)
        
        if success:
            last_pushed_ip = current_ip
            git_log.info(f"Successfully updated GitHub redirect to http://{current_ip}:{PORT}")
        else:
            git_log.warning("Failed to update GitHub redirect.")
    else:
        git_log.info("No IP change detected.")


#########################################################
# Schedulers
##########################################################
scheduler = BackgroundScheduler()
scheduler.add_job(update_stats, "interval", seconds=3)
scheduler.add_job(sch_redirector_update, "interval", seconds=60)

def start_scheduler():
    update_stats()
    sch_redirector_update()
    scheduler.start()