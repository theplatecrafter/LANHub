# scheduler.py
from glob_vars import *
from apscheduler.schedulers.background import BackgroundScheduler
import functions as f
from socketio_instance import socketio
import socket_events.global_events as ge
import config



server_stats_cache = {}
def update_stats():
    global server_stats_cache

    route_counts      = ge.get_route_counts()
    total_connections = ge.get_total_connections()

    full_stats = f.get_full_server_stats(route_counts, total_connections)
    server_stats_cache = full_stats

    socketio.emit("server_stats", full_stats)

def _redirector_update_url(full_url: str) -> bool:
    """Push a full URL (e.g. https://xyz.trycloudflare.com) to the redirector."""
    try:
        from git import Repo
        import datetime, os
        repo = Repo(REDIRECTOR_PATH)
        repo.remotes.origin.fetch()
        repo.git.reset('--hard', 'origin/main')
        repo.git.clean('-fd')

        new_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LANHub Redirector</title>
    <style>
        body {{ font-family: sans-serif; text-align: center; padding: 50px; background: #f4f4f9; }}
        .card {{ max-width: 500px; margin: auto; background: white; padding: 30px;
                 border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }}
        .spinner {{ border: 4px solid #f3f3f3; border-top: 4px solid #3498db;
                    border-radius: 50%; width: 30px; height: 30px;
                    animation: spin 1s linear infinite; margin: 20px auto; }}
        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
        .error-box {{ display:none; color:#721c24; background:#f8d7da;
                      border:1px solid #f5c6cb; padding:15px; border-radius:8px; margin-top:20px; }}
        a {{ color: #3498db; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>🛰️ LANHub Gateway</h2>
        <div id="checking">
            <p>Connecting to server...</p>
            <div class="spinner"></div>
        </div>
        <div id="error-msg" class="error-box">
            <h3>🚫 Server Unreachable</h3>
            <p>The server may be offline or the link may have changed.</p>
            <p><a href="{full_url}">{full_url}</a></p>
        </div>
    </div>
    <script>
        const target = "{full_url}";
        fetch(target + "/static/pixel.png", {{ mode: 'no-cors', signal: AbortSignal.timeout(4000) }})
            .then(() => window.location.replace(target))
            .catch(() => {{
                document.getElementById("checking").style.display = "none";
                document.getElementById("error-msg").style.display = "block";
            }});
    </script>
</body>
</html>"""

        path = os.path.join(REDIRECTOR_PATH, "index.html")
        with open(path, "w") as fh:
            fh.write(new_html)

        repo.index.add(["index.html"])
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        repo.index.commit(f"Update redirect to {full_url} at {ts}")
        repo.remote("origin").push(force=True)
        git_log.info(f"Redirector updated to {full_url}")
        return True
    except Exception as e:
        git_log.error(f"_redirector_update_url failed: {e}")
        return False

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
    <title>LANHub — Offline</title>
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

last_pushed_ip = None
def sch_redirector_update():
    global last_pushed_ip

    # Prefer a manually-set tunnel URL (e.g. from Cloudflare)
    tunnel_url = getattr(config, "TUNNEL_URL", "").strip()

    if tunnel_url:
        current_target = tunnel_url
    else:
        stats      = f.get_network_stats()
        current_ip = stats.get("public_ip") or stats.get("ip_address")
        if not current_ip or current_ip == "127.0.0.1":
            git_log.info("No routable IP found, skipping redirector update.")
            return
        current_target = f"http://{current_ip}:{PORT}"

    if current_target and current_target != last_pushed_ip:
        git_log.info(f"Target changed ({last_pushed_ip} -> {current_target}). Updating GitHub...")
        # redirector_update expects an IP+port, so handle full URLs here
        if current_target.startswith("http"):
            success = _redirector_update_url(current_target)
        else:
            success = f.redirector_update(current_target, PORT)
        if success:
            last_pushed_ip = current_target
            git_log.info(f"Successfully updated GitHub redirect to {current_target}")
        else:
            git_log.warning("Failed to update GitHub redirect.")
    else:
        git_log.info("No target change detected.")


#########################################################
# Schedulers
##########################################################
scheduler = BackgroundScheduler()
scheduler.add_job(update_stats, "interval", seconds=5, max_instances=1, coalesce=True,misfire_grace_time=5)
scheduler.add_job(sch_redirector_update, "interval", seconds=60)

def start_scheduler():
    update_stats()
    sch_redirector_update()
    scheduler.start()