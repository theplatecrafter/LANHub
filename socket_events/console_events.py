"""
socket_events/console_events.py

Spawns a real PTY shell for each authenticated DEV socket session.
Each connected socket gets its own isolated bash process.

NOTE: Shell operations are run in background threads to avoid blocking
the main gevent event loop. Socket.IO emits are dispatched through a queue
to avoid thread-safety issues with gevent.
"""

import os
import pty
import fcntl
import struct
import termios
import threading
import signal
import queue
import select

import gevent
from flask import request
from flask_socketio import emit
from socketio_instance import socketio
from glob_vars import app_log, error_log


# { sid: { "pid": int, "fd": int, "queue": queue.Queue } }
_console_sessions: dict[str, dict] = {}
_session_lock = threading.Lock()


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


def _read_pty(fd: int, sid: str, msg_queue: queue.Queue) -> None:
    """
    Background thread: reads PTY output cooperatively.
    Uses select() to yield control back to the gevent web server so it doesn't freeze.
    """
    try:
        # 1. Make the PTY file descriptor non-blocking
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        while True:
            # 2. Cooperatively yield to gevent until there is text to read
            # This is the magic line that prevents the server from freezing!
            select.select([fd], [], [])

            try:
                data = os.read(fd, 4096)
                if not data:
                    break
                msg_queue.put(("output", data.decode("utf-8", errors="replace")))
            except BlockingIOError:
                # Occurs if select wakes up but no data is ready; just loop again
                gevent.sleep(0.01)
            except OSError:
                # Linux raises OSError(EIO) when the PTY slave is destroyed (shell exits)
                break
            except Exception as e:
                error_log.error(f"[console] read error for sid={sid}: {e}")
                break

        msg_queue.put(("exit", None))
    finally:
        _cleanup(sid)


def _cleanup(sid: str) -> None:
    with _session_lock:
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


def _emit_queue_messages(sid: str, msg_queue: queue.Queue) -> None:
    """
    Gevent greenlet: reads messages from the background thread's queue
    and emits them via socket.IO to the client. This runs in the gevent
    event loop context, avoiding thread-safety issues.
    """
    while True:
        try:
            msg_type, data = msg_queue.get(timeout=60)
            if msg_type == "output":
                socketio.emit("console_output", {"data": data}, to=sid)
            elif msg_type == "exit":
                socketio.emit("console_exit", {}, to=sid)
                break
        except queue.Empty:
            # Session timeout - check if it still exists
            with _session_lock:
                if sid not in _console_sessions:
                    break
        except Exception as e:
            error_log.error(f"[console] emit error for sid={sid}: {e}")
            break


# ── Socket events ──────────────────────────────────────────────────────────────

@socketio.on("console_start")
def handle_console_start(data):
    """Start a new shell session in a background thread with queue-based socket emit."""
    sid = request.sid

    if not _is_dev():
        emit("console_output", {
            "data": "\r\n\x1b[31mAccess denied — DEV role required.\x1b[0m\r\n"
        })
        return

    cols = max(10, int(data.get("cols", 80)))
    rows = max(2,  int(data.get("rows", 24)))
    
    # CRITICAL: Reserve the session BEFORE starting background thread
    # This prevents race condition where two console_start events spawn duplicate shells
    with _session_lock:
        if sid in _console_sessions:
            # Shell already running or being started
            emit("console_ready", {})
            return
        # Reserve this session with a queue for thread-safe socket emit
        msg_queue = queue.Queue()
        _console_sessions[sid] = {"reserved": True, "queue": msg_queue}
    
    # Start gevent greenlet to read from queue and emit socket events
    # This runs in the gevent event loop, avoiding thread-safety issues
    gevent.spawn(_emit_queue_messages, sid, msg_queue)
    
    # Start PTY in background thread to avoid blocking gevent reactor
    t = threading.Thread(
        target=_start_shell_in_background,
        args=(sid, cols, rows, msg_queue),
        daemon=True
    )
    t.start()


def _start_shell_in_background(sid: str, cols: int, rows: int, msg_queue: queue.Queue) -> None:
    """Start shell in background thread to avoid blocking gevent reactor."""
    try:
        # Try to fork a PTY
        try:
            pid, fd = pty.fork()
        except AttributeError:
            # pty.fork() not available on this system (e.g., Windows)
            error_log.warning(f"[console] pty.fork() not available")
            msg_queue.put(("output", "\r\n\x1b[33mInteractive shell not available on this system.\x1b[0m\r\n"))
            msg_queue.put(("exit", None))
            return
        except Exception as e:
            error_log.error(f"[console] pty.fork() failed: {e}")
            msg_queue.put(("output", f"\r\n\x1b[31mFailed to start shell: {e}\x1b[0m\r\n"))
            msg_queue.put(("exit", None))
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
                try:
                    os.execvpe("/bin/sh", ["/bin/sh"], env)
                except Exception:
                    os._exit(1)
            # execvpe never returns normally

        # ── Parent ─────────────────────────────────────────────
        try:
            _resize_pty(fd, cols, rows)
        except Exception as e:
            error_log.warning(f"[console] pty resize failed: {e}")

        # Update the reserved entry with actual session data
        with _session_lock:
            _console_sessions[sid].update({"pid": pid, "fd": fd, "reserved": False})
        
        app_log.info(
            f"[console] {_get_admin_name()!r} opened shell "
            f"(pid={pid}, sid={sid}, {cols}x{rows})"
        )
        
        # Start read thread (will put messages in queue)
        t = threading.Thread(target=_read_pty, args=(fd, sid, msg_queue), daemon=True)
        t.start()
        
        # Notify client that shell is ready (emit via socket.io)
        socketio.emit("console_ready", {}, to=sid)
    
    except Exception as e:
        error_log.error(f"[console] Unexpected error in _start_shell_in_background: {e}")
        msg_queue.put(("output", f"\r\n\x1b[31mUnexpected error: {e}\x1b[0m\r\n"))
        msg_queue.put(("exit", None))


@socketio.on("console_input")
def handle_console_input(data):
    sid  = request.sid
    if not _is_dev():
        return
    
    with _session_lock:
        info = _console_sessions.get(sid)
    # Don't process if session is still being reserved or doesn't exist
    if not info or info.get("reserved"):
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
    if not _is_dev():
        return
    
    with _session_lock:
        info = _console_sessions.get(sid)
    # Don't process if session is still being reserved or doesn't exist
    if not info or info.get("reserved"):
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
