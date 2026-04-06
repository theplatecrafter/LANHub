"""functions/server.py - Server monitoring and statistics."""

import time
import platform
import subprocess
import socket
import psutil
from glob_vars import app_log
from .db import get_db

# App start time for uptime calculation
_app_start_time = time.time()

# Module-level: store last net reading for speed calculation
_last_net_io = None
_last_net_time = None


def get_server_stats() -> dict:
    """Get basic server stats (CPU and RAM)."""
    return {"cpu": psutil.cpu_percent(), "ram": psutil.virtual_memory().percent}


def get_wifi_ssid() -> str:
    """Returns the name of the connected Wi-Fi network."""
    try:
        # Try Windows/WSL first
        cmd = [
            "powershell.exe",
            "-Command",
            "(Get-NetConnectionProfile | Where-Object {$_.InterfaceAlias -like '*Wi-Fi*'}).Name",
        ]
        ssid = subprocess.check_output(cmd, timeout=2).decode("utf-8").strip()
        return ssid if ssid else "Ethernet/No Wi-Fi"
    except Exception:
        pass

    os_name = platform.system()
    try:
        if os_name == "Windows":
            results = subprocess.check_output(
                ["netsh", "wlan", "show", "interfaces"], timeout=2
            ).decode("utf-8")
            for line in results.split("\n"):
                if "SSID" in line and "BSSID" not in line:
                    return line.split(":")[1].strip()
        elif os_name == "Darwin":  # macOS
            results = subprocess.check_output(
                [
                    "/System/Library/PrivateFrameworks/Apple80211.framework/Resources/airport",
                    "-I",
                ],
                timeout=2,
            ).decode("utf-8")
            for line in results.split("\n"):
                if " SSID" in line:
                    return line.split(":")[1].strip()
        elif os_name == "Linux":
            return (
                subprocess.check_output(["iwgetid", "-r"], timeout=2)
                .decode("utf-8")
                .strip()
            )
    except Exception:
        return "Unknown/Wired"
    return "Not Connected"


def get_network_stats(flask_port: int = 5000) -> dict:
    """Get network statistics and configuration."""
    # Get the IP address used for internet (skips loopback)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
    except Exception:
        ip_address = "127.0.0.1"
    finally:
        s.close()

    net_io = psutil.net_io_counters()
    public_ip = get_public_ip()

    return {
        "ssid": get_wifi_ssid(),
        "ip_address": ip_address,
        "public_ip": public_ip,
        "flask_url": f"http://{ip_address}:{flask_port}",
        "bytes_sent": net_io.bytes_sent,
        "bytes_recv": net_io.bytes_recv,
    }


def get_public_ip() -> str:
    """Fetches the server's public-facing IP via external lookup services."""
    import urllib.request as _ureq

    for url in [
        "https://api.ipify.org",
        "https://checkip.amazonaws.com",
        "https://icanhazip.com",
    ]:
        try:
            with _ureq.urlopen(url, timeout=5) as r:
                return r.read().decode().strip()
        except Exception:
            continue
    return ""


def get_disk_stats() -> dict:
    """Returns disk usage for the root filesystem."""
    usage = psutil.disk_usage("/")
    return {
        "total_gb": round(usage.total / (1024**3), 1),
        "used_gb": round(usage.used / (1024**3), 1),
        "free_gb": round(usage.free / (1024**3), 1),
        "percent": usage.percent,
    }


def get_network_speed() -> dict:
    """Returns upload/download speed in KB/s by diffing two psutil readings."""
    global _last_net_io, _last_net_time

    now = time.time()
    current = psutil.net_io_counters()

    if _last_net_io is None or _last_net_time is None:
        _last_net_io = current
        _last_net_time = now
        return {
            "upload_kbps": 0.0,
            "download_kbps": 0.0,
            "bytes_sent": current.bytes_sent,
            "bytes_recv": current.bytes_recv,
        }

    elapsed = now - _last_net_time
    if elapsed <= 0:
        elapsed = 0.001

    upload_kbps = round(
        (current.bytes_sent - _last_net_io.bytes_sent) / elapsed / 1024, 1
    )
    download_kbps = round(
        (current.bytes_recv - _last_net_io.bytes_recv) / elapsed / 1024, 1
    )

    _last_net_io = current
    _last_net_time = now

    return {
        "upload_kbps": max(0.0, upload_kbps),
        "download_kbps": max(0.0, download_kbps),
        "bytes_sent": current.bytes_sent,
        "bytes_recv": current.bytes_recv,
    }


def get_gpu_stats() -> dict | None:
    """Returns GPU usage if a compatible GPU is found. Returns None if unavailable."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return None
        parts = [p.strip() for p in result.stdout.strip().split(",")]
        if len(parts) < 5:
            return None
        mem_used = float(parts[2])
        mem_total = float(parts[3])
        return {
            "name": parts[0],
            "load": float(parts[1]),
            "mem_used_mb": mem_used,
            "mem_total_mb": mem_total,
            "mem_percent": round(mem_used / mem_total * 100, 1) if mem_total else 0,
            "temp": float(parts[4]),
        }
    except Exception:
        return None


def get_uptime_seconds() -> int:
    """Seconds since the LANHub process started."""
    return int(time.time() - _app_start_time)


def get_cpu_temp() -> float | None:
    """Returns CPU temperature in °C on supported systems."""
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
    net_stats = get_network_stats()
    net_speed = get_network_speed()
    disk = get_disk_stats()
    gpu = get_gpu_stats()
    cpu_temp = get_cpu_temp()
    uptime = get_uptime_seconds()

    mem = psutil.virtual_memory()
    cpu_per_core = psutil.cpu_percent(percpu=True)

    return {
        # CPU
        "cpu": psutil.cpu_percent(),
        "cpu_per_core": cpu_per_core,
        "cpu_count": len(cpu_per_core),
        "cpu_temp": cpu_temp,
        # RAM
        "ram": mem.percent,
        "ram_used_gb": round(mem.used / (1024**3), 2),
        "ram_total_gb": round(mem.total / (1024**3), 2),
        "ram_avail_gb": round(mem.available / (1024**3), 2),
        # Disk
        "disk": disk,
        # GPU (None if unavailable)
        "gpu": gpu,
        # Network identity
        "ssid": net_stats["ssid"],
        "ip": net_stats["ip_address"],
        # Network speed
        "upload_kbps": net_speed["upload_kbps"],
        "download_kbps": net_speed["download_kbps"],
        "bytes_sent": net_speed["bytes_sent"],
        "bytes_recv": net_speed["bytes_recv"],
        # Connections
        "total_connections": total_connections,
        "route_counts": route_counts,
        # System
        "uptime": uptime,
        "platform": platform.system() + " " + platform.release(),
    }
