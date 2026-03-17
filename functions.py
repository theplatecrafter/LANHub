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
from better_profanity import profanity as _profanity_filter



#######################################################
# Profanity Filter
#######################################################
def check_profanity(message: str) -> bool:
    """Returns True if the message contains profanity."""
    return _profanity_filter.contains_profanity(message)


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
# In-memory rate tracker: { ip: [timestamp, ...] }
_rate_tracker: dict[str, list[float]] = {}
 
def is_rate_limited(ip: str) -> bool:
    """Sliding window rate limiter. Returns True if IP is over the limit."""
    now = time.time()
    timestamps = _rate_tracker.get(ip, [])
    timestamps = [t for t in timestamps if now - t < CHAT_RATE_WINDOW]
    if len(timestamps) >= CHAT_RATE_LIMIT:
        _rate_tracker[ip] = timestamps
        return True
    timestamps.append(now)
    _rate_tracker[ip] = timestamps
    return False
 
 
def save_chat_message(username: str, ip: str, message: str,
                      reply_to_id: int | None = None) -> dict:
    """Inserts a message and returns it as a dict (including reply info if any)."""
    now = time.time()
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO chat_messages (username, ip, message, timestamp, reply_to_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (username, ip, message, now, reply_to_id)
    )
    conn.commit()
    row_id = c.lastrowid
 
    # Fetch reply info so the broadcast payload is complete
    reply_username = None
    reply_message  = None
    if reply_to_id:
        c.execute("SELECT username, message FROM chat_messages WHERE id = ?", (reply_to_id,))
        row = c.fetchone()
        if row:
            reply_username = row["username"]
            reply_message  = row["message"]
 
    conn.close()
    return {
        "id":             row_id,
        "username":       username,
        "message":        message,
        "timestamp":      now,
        "edited":         False,
        "reply_to_id":    reply_to_id,
        "reply_username": reply_username,
        "reply_message":  reply_message,
    }
 
 
def get_recent_messages(limit: int) -> list[dict]:
    """Returns the most recent `limit` messages (oldest first), with reply info joined."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT
            m.id,
            m.username,
            m.message,
            m.timestamp,
            m.edited,
            m.reply_to_id,
            r.username  AS reply_username,
            r.message   AS reply_message
        FROM chat_messages m
        LEFT JOIN chat_messages r ON m.reply_to_id = r.id
        ORDER BY m.id DESC
        LIMIT ?
    """, (limit,))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    rows.reverse()   # oldest → newest
    return rows
 
 
def edit_message(msg_id: int, new_text: str) -> None:
    """Updates message text and marks it as edited."""
    conn = get_db()
    conn.execute(
        "UPDATE chat_messages SET message = ?, edited = 1 WHERE id = ?",
        (new_text, msg_id)
    )
    conn.commit()
    conn.close()
 
 
def delete_message(msg_id: int) -> None:
    """Hard-deletes a message from the DB."""
    conn = get_db()
    conn.execute("DELETE FROM chat_messages WHERE id = ?", (msg_id,))
    conn.commit()
    conn.close()
    

def get_messages_before(before_id: int, limit: int) -> list[dict]:
    """Returns `limit` messages older than `before_id`, oldest first."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT
            m.id,
            m.username,
            m.message,
            m.timestamp,
            m.edited,
            m.reply_to_id,
            r.username  AS reply_username,
            r.message   AS reply_message
        FROM chat_messages m
        LEFT JOIN chat_messages r ON m.reply_to_id = r.id
        WHERE m.id < ?
        ORDER BY m.id DESC
        LIMIT ?
    """, (before_id, limit))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    rows.reverse()   # oldest → newest
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
            <p>You must be connected to the <b>same LAN (or Wi-Fi)</b> as the server to access this page.</p>
            <p>Current Target: <a href="http://{ip}:{port}">http://{ip}:{port}</a></p>
        </div>

        <p style="font-size: 0.9em; color: #666; margin-top: 20px;">
            If you aren't redirected in 5 seconds, you are likely on the wrong network or the server is offline.
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


# Module-level: store last net reading for speed calculation
_last_net_io = None
_last_net_time = None
 
# App start time for uptime calculation
_app_start_time = time.time()
 
 
def get_disk_stats() -> dict:
    """Returns disk usage for the root filesystem."""
    usage = psutil.disk_usage('/')
    return {
        "total_gb":   round(usage.total  / (1024**3), 1),
        "used_gb":    round(usage.used   / (1024**3), 1),
        "free_gb":    round(usage.free   / (1024**3), 1),
        "percent":    usage.percent,
    }
 
 
def get_network_speed() -> dict:
    """Returns upload/download speed in KB/s by diffing two psutil readings."""
    global _last_net_io, _last_net_time
 
    now     = time.time()
    current = psutil.net_io_counters()
 
    if _last_net_io is None or _last_net_time is None:
        _last_net_io   = current
        _last_net_time = now
        return {"upload_kbps": 0.0, "download_kbps": 0.0,
                "bytes_sent": current.bytes_sent, "bytes_recv": current.bytes_recv}
 
    elapsed = now - _last_net_time
    if elapsed <= 0:
        elapsed = 0.001
 
    upload_kbps   = round((current.bytes_sent - _last_net_io.bytes_sent) / elapsed / 1024, 1)
    download_kbps = round((current.bytes_recv - _last_net_io.bytes_recv) / elapsed / 1024, 1)
 
    _last_net_io   = current
    _last_net_time = now
 
    return {
        "upload_kbps":   max(0.0, upload_kbps),
        "download_kbps": max(0.0, download_kbps),
        "bytes_sent":    current.bytes_sent,
        "bytes_recv":    current.bytes_recv,
    }
 
 
def get_gpu_stats() -> dict | None:
    """
    Returns GPU usage if a compatible GPU is found.
    Returns None silently if GPUtil is missing or broken.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode != 0:
            return None
        parts = [p.strip() for p in result.stdout.strip().split(",")]
        if len(parts) < 5:
            return None
        mem_used  = float(parts[2])
        mem_total = float(parts[3])
        return {
            "name":         parts[0],
            "load":         float(parts[1]),
            "mem_used_mb":  mem_used,
            "mem_total_mb": mem_total,
            "mem_percent":  round(mem_used / mem_total * 100, 1) if mem_total else 0,
            "temp":         float(parts[4]),
        }
    except Exception:
        return None
 
 
def get_uptime_seconds() -> int:
    """Seconds since the LANHub process started."""
    return int(time.time() - _app_start_time)
 
 
def get_cpu_temp() -> float | None:
    """Returns CPU temperature in °C on supported Linux systems."""
    try:
        temps = psutil.sensors_temperatures()
        for key in ("coretemp", "cpu_thermal", "k10temp", "acpitz"):
            if key in temps and temps[key]:
                return round(temps[key][0].current, 1)
    except Exception:
        pass
    return None
 
 
def get_full_server_stats(route_counts: dict, total_connections: int) -> dict:
    """
    Assembles the full stats payload emitted to /stats clients.
    Call this from the scheduler.
    """
    net_stats  = get_network_stats()   # existing function (ip, ssid, etc.)
    net_speed  = get_network_speed()
    disk       = get_disk_stats()
    gpu        = get_gpu_stats()
    cpu_temp   = get_cpu_temp()
    uptime     = get_uptime_seconds()
 
    mem = psutil.virtual_memory()
    cpu_per_core = psutil.cpu_percent(percpu=True)
 
    return {
        # CPU
        "cpu":            psutil.cpu_percent(),
        "cpu_per_core":   cpu_per_core,
        "cpu_count":      len(cpu_per_core),
        "cpu_temp":       cpu_temp,
 
        # RAM
        "ram":            mem.percent,
        "ram_used_gb":    round(mem.used   / (1024**3), 2),
        "ram_total_gb":   round(mem.total  / (1024**3), 2),
        "ram_avail_gb":   round(mem.available / (1024**3), 2),
 
        # Disk
        "disk":           disk,
 
        # GPU (None if unavailable)
        "gpu":            gpu,
 
        # Network identity
        "ssid":           net_stats["ssid"],
        "ip":             net_stats["ip_address"],
 
        # Network speed
        "upload_kbps":    net_speed["upload_kbps"],
        "download_kbps":  net_speed["download_kbps"],
        "bytes_sent":     net_speed["bytes_sent"],
        "bytes_recv":     net_speed["bytes_recv"],
 
        # Connections
        "total_connections": total_connections,
        "route_counts":      route_counts,
 
        # System
        "uptime":         uptime,
        "platform":       platform.system() + " " + platform.release(),
    }