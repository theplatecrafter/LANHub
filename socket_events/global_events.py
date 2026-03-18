"""
socket_events/global_events.py

Tracks which route each connected socket has open.
Used by the scheduler to report per-route presence counts.
"""

from socketio_instance import socketio
from flask import request

# { sid: "/route" }
page_presence: dict[str, str] = {}


@socketio.on("connect")
def on_connect():
    # Page is registered via page_open after connect
    pass


@socketio.on("page_open")
def on_page_open(data):
    route = (data.get("path") or "/").strip() or "/"
    page_presence[request.sid] = route


@socketio.on("disconnect")
def on_global_disconnect():
    page_presence.pop(request.sid, None)


def get_route_counts() -> dict[str, int]:
    """Returns {route: count} for all currently connected sockets."""
    counts: dict[str, int] = {}
    for route in page_presence.values():
        counts[route] = counts.get(route, 0) + 1
    return counts


def get_total_connections() -> int:
    return len(page_presence)


def get_unique_ips() -> int:
    """Count unique remote addresses — not directly accessible here,
    so we approximate from the presence dict size (1 tab = 1 connection)."""
    return len(page_presence)

@socketio.on("cmd_ping")
def on_cmd_ping(_data=None):
    pass  # ack is sent automatically by flask-socketio when handler returns