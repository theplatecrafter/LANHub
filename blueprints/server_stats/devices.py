from flask import Blueprint, render_template, jsonify
import os, socket, subprocess, re, time, threading
from glob_vars import BASE_DIR, app_log, error_log
import socket_events.global_events as ge

devices_bp = Blueprint("devices", __name__)

# ── In-memory device registry ─────────────────────────────────────────────────
# { mac: { ip, mac, hostname, vendor, first_seen, last_seen, open_tabs } }
_device_registry: dict[str, dict] = {}
_registry_lock = threading.Lock()

# ── MAC → vendor prefix table (top 60 common vendors) ────────────────────────
OUI_TABLE = {
    "00:50:56": "VMware",          "00:0C:29": "VMware",
    "00:1A:11": "Google",          "F4:F5:D8": "Google",
    "B8:27:EB": "Raspberry Pi",    "DC:A6:32": "Raspberry Pi",
    "E4:5F:01": "Raspberry Pi",    "28:CD:C1": "Raspberry Pi",
    "00:17:F2": "Apple",           "00:1B:63": "Apple",
    "00:1C:B3": "Apple",           "00:1D:4F": "Apple",
    "00:1E:52": "Apple",           "00:1F:5B": "Apple",
    "00:21:E9": "Apple",           "00:22:41": "Apple",
    "00:23:12": "Apple",           "00:23:6C": "Apple",
    "00:24:36": "Apple",           "00:25:00": "Apple",
    "00:25:4B": "Apple",           "00:26:08": "Apple",
    "00:26:B0": "Apple",           "00:26:BB": "Apple",
    "3C:07:54": "Apple",           "A4:D1:8C": "Apple",
    "F0:DB:F8": "Apple",           "F8:1E:DF": "Apple",
    "00:1A:7D": "Intel",           "00:1B:21": "Intel",
    "00:1C:C0": "Intel",           "00:1D:E0": "Intel",
    "00:1E:64": "Intel",           "00:1E:67": "Intel",
    "00:21:6A": "Intel",           "00:21:D7": "Intel",
    "00:22:FB": "Intel",           "00:23:14": "Intel",
    "00:23:8B": "Intel",           "00:24:D7": "Intel",
    "00:15:5D": "Microsoft Hyper-V","00:03:FF": "Microsoft",
    "00:12:79": "Samsung",         "00:13:77": "Samsung",
    "00:15:99": "Samsung",         "00:16:32": "Samsung",
    "00:17:C9": "Samsung",         "00:1A:8A": "Samsung",
    "18:67:B0": "Amazon",          "FC:65:DE": "Amazon",
    "00:04:4B": "NVIDIA",          "00:19:94": "Cisco",
    "00:1A:A1": "Cisco",           "00:1B:D4": "Cisco",
    "18:9C:5D": "Cisco",           "E8:BA:70": "Cisco",
    "B0:7D:64": "Huawei",          "00:E0:FC": "Huawei",
    "54:89:98": "Huawei",
}


def _lookup_vendor(mac: str) -> str:
    prefix = mac.upper()[:8]
    return OUI_TABLE.get(prefix, "Unknown")


def _resolve_hostname(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ""


def _parse_arp_table() -> list[dict]:
    """Reads /proc/net/arp (Linux) and returns a list of {ip, mac, iface}."""
    results = []
    path = "/proc/net/arp"
    if not os.path.isfile(path):
        return results
    try:
        with open(path) as f:
            lines = f.readlines()[1:]   # skip header
        for line in lines:
            parts = line.split()
            if len(parts) < 6:
                continue
            ip, _, flags, mac, _, iface = parts[:6]
            # Flags 0x0 = incomplete (no device), skip
            if mac in ("00:00:00:00:00:00", "") or flags == "0x0":
                continue
            results.append({"ip": ip, "mac": mac.upper(), "iface": iface})
    except Exception as e:
        error_log.error(f"[devices] ARP parse error: {e}")
    return results


def _ping_sweep(subnet: str) -> None:
    """
    Sends a single ICMP ping to every host on the /24 subnet
    to populate the ARP table. Runs in a background thread.
    subnet example: "192.168.1"
    """
    try:
        subprocess.run(
            ["nmap", "-sn", "--min-parallelism", "50",
             "-T4", f"{subnet}.0/24"],
            capture_output=True, timeout=30
        )
    except FileNotFoundError:
        # nmap not installed — fall back to fping or plain ping broadcast
        try:
            subprocess.run(
                ["fping", "-a", "-q", "-g", f"{subnet}.0/24"],
                capture_output=True, timeout=30
            )
        except Exception:
            pass
    except Exception as e:
        app_log.warning(f"[devices] ping sweep failed: {e}")


def get_local_subnet() -> str:
    """Returns the first three octets of the server's LAN IP, e.g. '192.168.1'"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ".".join(ip.split(".")[:3])
    except Exception:
        return "192.168.1"


def refresh_devices(force_sweep: bool = False) -> list[dict]:
    """
    Reads ARP table, enriches with hostname + vendor,
    merges into registry, returns sorted list.
    """
    if force_sweep:
        subnet = get_local_subnet()
        threading.Thread(target=_ping_sweep, args=(subnet,), daemon=True).start()

    arp_entries = _parse_arp_table()
    now = time.time()

    # Build a mac→ip map from ARP
    current_macs = {}
    for entry in arp_entries:
        current_macs[entry["mac"]] = entry

    with _registry_lock:
        # Update or add devices seen in ARP table
        for mac, entry in current_macs.items():
            ip   = entry["ip"]
            iface = entry.get("iface", "")
            if mac in _device_registry:
                _device_registry[mac]["ip"]        = ip
                _device_registry[mac]["last_seen"] = now
                _device_registry[mac]["iface"]     = iface
            else:
                hostname = _resolve_hostname(ip)
                _device_registry[mac] = {
                    "ip":         ip,
                    "mac":        mac,
                    "hostname":   hostname,
                    "vendor":     _lookup_vendor(mac),
                    "iface":      iface,
                    "first_seen": now,
                    "last_seen":  now,
                    "active":     True,
                }

        # Mark devices not in current ARP as inactive (not removed — keeps history)
        for mac in _device_registry:
            _device_registry[mac]["active"] = mac in current_macs

        # Attach open-tab count from global_events
        presence = ge.page_presence   # { sid: path }
        # We can't map sid → IP easily, so just count total tabs per IP from
        # the route presence — annotate the "server" entry
        # For now just return devices; open_tabs annotation added below
        snapshot = list(_device_registry.values())

    # Sort: active first, then by last_seen desc
    snapshot.sort(key=lambda d: (not d["active"], -d["last_seen"]))

    return snapshot


# ── Routes ────────────────────────────────────────────────────────────────────
@devices_bp.route("/devices")
def devices():
    return render_template("devices.html")


@devices_bp.route("/api/devices")
def api_devices():
    device_list = refresh_devices(force_sweep=False)
    # Serialise timestamps
    for d in device_list:
        d["first_seen_str"] = _fmt_time(d["first_seen"])
        d["last_seen_str"]  = _fmt_time(d["last_seen"])
        d["ago"]            = _fmt_ago(d["last_seen"])
    return jsonify({"devices": device_list})


@devices_bp.route("/api/devices/scan", methods=["POST"])
def api_scan():
    """Trigger a fresh ping sweep then return updated device list."""
    device_list = refresh_devices(force_sweep=True)
    for d in device_list:
        d["first_seen_str"] = _fmt_time(d["first_seen"])
        d["last_seen_str"]  = _fmt_time(d["last_seen"])
        d["ago"]            = _fmt_ago(d["last_seen"])
    return jsonify({"devices": device_list, "scanning": True})


def _fmt_time(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _fmt_ago(ts: float) -> str:
    secs = int(time.time() - ts)
    if secs < 60:    return f"{secs}s ago"
    if secs < 3600:  return f"{secs//60}m ago"
    if secs < 86400: return f"{secs//3600}h ago"
    return f"{secs//86400}d ago"