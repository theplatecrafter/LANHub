from glob_vars import *


import sqlite3
import psutil
import socket
import subprocess
import platform
from git import Repo
import datetime
import os



#######################################################
# Github Static Redirector Page Functions
#######################################################

HTML_FILENAME = "index.html"

def redirector_update(ip, port=PORT):
    try:
        repo = Repo(REDIRECTOR_PATH)
        
        repo.remotes.origin.fetch()
        
        repo.git.reset('--hard', 'origin/main')
        
        new_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="1; url=http://{ip}:{port}">
    <script>window.location.replace("http://{ip}:{port}");</script>
    <title>Redirecting to LAN Server</title>
</head>
<body>
    <p>Server moved to: <b>http://{ip}:{port}</b></p>
    <p>Redirecting you now... If it fails, <a href="http://{ip}:{port}">click here</a>.</p>
</body>
</html>"""

        file_path = os.path.join(REDIRECTOR_PATH, HTML_FILENAME)
        with open(file_path, "w") as f:
            f.write(new_html)

        repo.index.add([HTML_FILENAME])
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        repo.index.commit(f"Update redirect to {ip}:{port} at {timestamp}")
        
        origin = repo.remote(name='origin')
        origin.push()

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