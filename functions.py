# functions.py
from glob_vars import *

import sqlite3
import time
import psutil
import socket
import subprocess
import platform
from git import Repo
import datetime
import os


#######################################################
# Database
#######################################################
def get_db():
    """Returns a sqlite3 connection. Caller is responsible for closing it."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts
    return conn

#######################################################
# Chat Helpers
#######################################################
# In-memory rate tracker: { ip: [timestamp, timestamp, ...] }
_rate_tracker: dict[str, list[float]] = {}

def is_rate_limited(ip: str) -> bool:
    """Sliding window rate limiter. Returns True if the IP is over the limit."""
    now = time.time()
    timestamps = _rate_tracker.get(ip, [])
    timestamps = [t for t in timestamps if now - t < CHAT_RATE_WINDOW]
    if len(timestamps) >= CHAT_RATE_LIMIT:
        _rate_tracker[ip] = timestamps
        return True
    timestamps.append(now)
    _rate_tracker[ip] = timestamps
    return False

def save_chat_message(username: str, ip: str, message: str) -> dict:
    """Saves a message and returns the row as a dict."""
    now = time.time()
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO chat_messages (username, ip, message, timestamp) VALUES (?, ?, ?, ?)",
        (username, ip, message, now)
    )
    conn.commit()
    row_id = c.lastrowid
    conn.close()
    return {"id": row_id, "username": username, "message": message, "timestamp": now}

def get_recent_messages(limit: int) -> list[dict]:
    """Returns the most recent `limit` messages, oldest first."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT id, username, message, timestamp FROM chat_messages ORDER BY id DESC LIMIT ?",
        (limit,)
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    rows.reverse()  # oldest → newest
    return rows




#######################################################
# Github Static Redirector Page Functions
#######################################################

HTML_FILENAME = "index.html"

def redirector_update(ip,port=PORT):
    try:
        repo = Repo(REDIRECTOR_PATH)
        
        repo.remotes.origin.fetch()
        repo.git.reset('--hard', 'origin/main')
        repo.git.clean('-fd')
        
        # Using an f-string (note the f before the triple quotes)
        # Also, we use {{ }} for CSS brackets so Python doesn't get confused
        new_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LANHub Redirector</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; text-align: center; padding: 50px; background-color: #f4f4f9; color: #333; }}
        .card {{ max-width: 500px; margin: auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }}
        .error-box {{ display: none; color: #721c24; background-color: #f8d7da; border: 1px solid #f5c6cb; padding: 15px; border-radius: 8px; margin-top: 20px; }}
        .loading-spinner {{ border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; width: 30px; height: 30px; animation: spin 1s linear infinite; margin: 20px auto; }}
        @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
        a {{ color: #3498db; text-decoration: none; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>🛰️ LANHub Gateway</h2>
        
        <div id="checking">
            <p>Verifying connection to <b>{ip}</b>...</p>
            <div class="loading-spinner"></div>
        </div>

        <div id="error-msg" class="error-box">
            <h3>🚫 Connection Failed</h3>
            <p>You must be connected to the <b>same Wi-Fi</b> as the server to access this page.</p>
            <p>Or, the server is down/offline.</p>
            <p>Current Target: <a href="http://{ip}:{port}">http://{ip}:{port}</a></p>
        </div>

        <p style="font-size: 0.9em; color: #666; margin-top: 20px;">
            If you aren't redirected in 5 seconds, you are likely off-campus or on the wrong network.
        </p>
    </div>

    <script>
        const targetUrl = "http://{ip}:{port}";

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 4000);

        fetch(targetUrl + "/static/pixel.png", {{ mode: 'no-cors', signal: controller.signal }})
            .then(() => {{
                window.location.replace(targetUrl);
            }})
            .catch((err) => {{
                document.getElementById("checking").style.display = "none";
                document.getElementById("error-msg").style.display = "block";
                console.log("Connection failed: ", err);
            }});
    </script>
</body>
</html>"""

        file_path = os.path.join(REDIRECTOR_PATH, HTML_FILENAME)
        with open(file_path, "w") as f:
            f.write(new_html)

        repo.index.add([HTML_FILENAME])
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        repo.index.commit(f"Update redirect to {ip}:{port} at {timestamp}")
        
        origin = repo.remote(name='origin')
        origin.push(force=True) # Added force=True just in case history diverges again

        git_log.info(f"Successfully updated GitHub redirect to http://{ip}:{port}")
        return True

    except Exception as e:
        git_log.error(f"Failed to update GitHub: {e}")
        return False
    
########################################################
# Stats Functions
########################################################
def get_server_stats():
    return {
        "cpu": psutil.cpu_percent(),
        "ram": psutil.virtual_memory().percent
    }

def get_wifi_ssid():
    """Returns the name of the connected Wi-Fi network."""
    try: # dev purpose (for wsl)
        # We call netsh.exe (the Windows version) from inside WSL
        # we use 'powershell.exe' to make parsing easier
        cmd = ["powershell.exe", "-Command", "(Get-NetConnectionProfile | Where-Object {$_.InterfaceAlias -like '*Wi-Fi*'}).Name"]
        ssid = subprocess.check_output(cmd).decode("utf-8").strip()
        
        return ssid if ssid else "Ethernet/No Wi-Fi"
    except Exception:
        pass
    
    os_name = platform.system()
    try:
        if os_name == "Windows":
            results = subprocess.check_output(["netsh", "wlan", "show", "interfaces"]).decode("utf-8")
            for line in results.split("\n"):
                if "SSID" in line and "BSSID" not in line:
                    return line.split(":")[1].strip()
        elif os_name == "Darwin":  # macOS
            results = subprocess.check_output(["/System/Library/PrivateFrameworks/Apple80211.framework/Resources/airport", "-I"]).decode("utf-8")
            for line in results.split("\n"):
                if " SSID" in line:
                    return line.split(":")[1].strip()
        elif os_name == "Linux":
            return subprocess.check_output(["iwgetid", "-r"]).decode("utf-8").strip()
    except:
        return "Unknown/Wired"
    return "Not Connected"

def get_network_stats(flask_port=5000):
    # 1. Get the IP address used for the internet (skips loopback 'lo')
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't actually connect, just probes the routing table
        s.connect(('8.8.8.8', 80))
        ip_address = s.getsockname()[0]
    except Exception:
        ip_address = "127.0.0.1"
    finally:
        s.close()

    net_io = psutil.net_io_counters()

    return {
        "ssid": get_wifi_ssid(),
        "ip_address": ip_address,
        "flask_url": f"http://{ip_address}:{flask_port}",
        "bytes_sent": net_io.bytes_sent,
        "bytes_recv": net_io.bytes_recv
    }