"""
socket_events/console_events.py

Spawns a real PTY shell for each authenticated DEV socket session.
Each connected socket gets its own isolated bash process.
Cleaned up automatically on disconnect.
"""

import os
import pty
import fcntl
import struct
import termios
import threading
import signal

from flask import request
from flask_socketio import emit
from socketio_instance import socketio
from glob_vars import app_log, error_log


# { sid: { "pid": int, "fd": int } }
_console_sessions: dict[str, dict] = {}


def _is_dev() -> bool:
    """
    Safely check the Flask session for DEV role.
    Flask-SocketIO copies the HTTP session into the socket context,
    so flask.session is accessible here.
    """
    try:
        from flask import session
        return session.get("admin_role") == "DEV"
    except Exception:
        return False


def _get_admin_name() -> str:
    try:
        from flask import session
        return session.get("admin_name", "unknown")
    except Exception:
        return "unknown"


def _read_pty(fd: int, sid: str) -> None:
    """
    Background thread: reads PTY output and emits to the client.
    Exits when the PTY closes (shell exited).
    """
    while True:
        try:
            data = os.read(fd, 4096)
            if not data:
                break
            socketio.emit("console_output",
                          {"data": data.decode("utf-8", errors="replace")},
                          to=sid)
        except OSError:
            break
        except Exception as e:
            error_log.error(f"[console] read error for sid={sid}: {e}")
            break

    socketio.emit("console_exit", {}, to=sid)
    _cleanup(sid)


def _cleanup(sid: str) -> None:
    info = _console_sessions.pop(sid, None)
    if not info:
        return
    fd  = info.get("fd")
    pid = info.get("pid")
    try:
        if fd is not None:
            os.close(fd)
    except OSError:
        pass
    try:
        if pid is not None:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, os.WNOHANG)
    except (OSError, ChildProcessError):
        pass
    app_log.info(f"[console] cleaned up shell for sid={sid}")


def _resize_pty(fd: int, cols: int, rows: int) -> None:
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


# ── Socket events ──────────────────────────────────────────────────────────────

@socketio.on("console_start")
def handle_console_start(data):
    sid = request.sid

    if not _is_dev():
        emit("console_output", {
            "data": "\r\n\x1b[31mAccess denied — DEV role required.\x1b[0m\r\n"
        })
        return

    # If a shell is already running for this sid, just ack
    if sid in _console_sessions:
        emit("console_ready", {})
        return

    cols = max(10, int(data.get("cols", 80)))
    rows = max(2,  int(data.get("rows", 24)))

    try:
        pid, fd = pty.fork()
    except Exception as e:
        error_log.error(f"[console] pty.fork() failed: {e}")
        emit("console_output", {
            "data": f"\r\n\x1b[31mFailed to start shell: {e}\x1b[0m\r\n"
        })
        return

    if pid == 0:
        # ── Child: exec the user's default shell ──────────────
        env = os.environ.copy()
        env["TERM"]    = "xterm-256color"
        env["COLUMNS"] = str(cols)
        env["LINES"]   = str(rows)
        shell = env.get("SHELL", "/bin/bash")
        try:
            os.execvpe(shell, [shell], env)
        except Exception:
            os.execvpe("/bin/sh", ["/bin/sh"], env)
        # execvpe never returns normally

    # ── Parent ─────────────────────────────────────────────
    _resize_pty(fd, cols, rows)

    t = threading.Thread(target=_read_pty, args=(fd, sid), daemon=True)
    t.start()

    _console_sessions[sid] = {"pid": pid, "fd": fd, "thread": t}
    app_log.info(
        f"[console] {_get_admin_name()!r} opened shell "
        f"(pid={pid}, sid={sid}, {cols}x{rows})"
    )
    emit("console_ready", {})


@socketio.on("console_input")
def handle_console_input(data):
    sid  = request.sid
    info = _console_sessions.get(sid)
    if not info or not _is_dev():
        return
    text = data.get("data", "")
    if isinstance(text, str):
        text = text.encode("utf-8")
    try:
        os.write(info["fd"], text)
    except OSError as e:
        error_log.error(f"[console] write error for sid={sid}: {e}")


@socketio.on("console_resize")
def handle_console_resize(data):
    sid  = request.sid
    info = _console_sessions.get(sid)
    if not info or not _is_dev():
        return
    try:
        _resize_pty(info["fd"],
                    max(10, int(data.get("cols", 80))),
                    max(2,  int(data.get("rows", 24))))
    except Exception:
        pass


@socketio.on("console_stop")
def handle_console_stop(_data=None):
    sid = request.sid
    app_log.info(f"[console] {_get_admin_name()!r} stopped shell (sid={sid})")
    _cleanup(sid)
