# app.py
from glob_vars import *
from utils.init import initialize
initialize()

import os
from flask import Flask, render_template, session, redirect, url_for, request
from socketio_instance import socketio
import utils.scheduler as sch
import sys
import signal
import datetime
import re as _re
import config as _config
import threading
import jinja2 as _jinja2
import types as _types

app = Flask(__name__)
app.secret_key = _config.SECRET_KEY
import functions as _fns
_startup_stats = _fns.get_network_stats()
app.config["LAN_IP"]   = _startup_stats.get("ip_address", "")
app.config["LAN_PORT"] = int(_config.PORT)

LANG_NAMES = {
    "en": "English",
    "ja": "日本語",
}

# Blueprints
from blueprints.admin import *
from blueprints.communications import *
from blueprints.games import *
from blueprints.server_stats import *
from blueprints.tools import *



# Socket event handlers
import socket_events.chat_events
import socket_events.global_events
import socket_events.console_events
import socket_events.channels_events
import socket_events.chess_events
import socket_events.tetris_events
import socket_events.uno_events
import socket_events.slither_events
import socket_events.scribble_events
import socket_events.geoguesser_events
import socket_events.lab_events

socketio.init_app(app)

# ── Check and apply system-level updates on startup ──────────────────────────
# System updates are now non-blocking thanks to:
# - Scripts use sudo -n (no password prompt)
# - Docker group allows docker commands without sudo
# - Subprocess streaming doesn't buffer output
# Updates apply automatically on startup for production readiness
try:
    from functions.system_updates import check_for_updates, apply_pending_updates
    import logging
    import os
    update_logger = logging.getLogger("lanhub.updates")
    
    # Check for updates on every startup
    pending = check_for_updates()
    if pending:
        pending_count = sum(len(v) for v in pending.values())
        update_logger.info(f"Found {pending_count} pending system updates")
        
        # Auto-apply unless running with LANHUB_SKIP_AUTO_UPDATES=1 (for testing)
        if os.environ.get("LANHUB_SKIP_AUTO_UPDATES") != "1":
            update_logger.info("Applying pending system updates automatically...")
            result = apply_pending_updates(allow_interactive=False)
            if result.get("success"):
                update_logger.info("✓ All system updates applied successfully")
            else:
                update_logger.warning("⚠ Some system updates failed to apply. Check logs above.")
        else:
            update_logger.info("Updates can be applied via Admin Panel → Server → System Updates")
            update_logger.info("Or run: python3 functions/system_updates.py --apply")
except Exception as e:
    import logging
    logging.getLogger("lanhub.updates").warning(f"Could not check for system updates: {e}")

# ── Language-aware template lookup ────────────────────────────────────────────
# Jinja2 caches compiled templates by name. Without this patch, the first
# language to request "chat.html" wins the cache and everyone else gets that
# copy until restart. We wrap get_template() so "fr" requests look up
# "fr/chat.html" (a different cache key) and fall back to "chat.html" if the
# translated file doesn't exist yet. Flask's built-in loader already resolves
# paths like "fr/chat.html" relative to templates/ with no extra loader needed.

_orig_get_template = app.jinja_env.get_template.__func__

def _lang_get_template(env, name, parent=None, globals=None):
    lang = "en"
    try:
        from flask import has_request_context, request as _req
        if has_request_context():
            _l = _req.cookies.get("lanhub_lang", "en")
            if _l and _l.replace("-", "").replace("_", "").isalnum():
                lang = _l
    except Exception:
        pass

    if lang != "en":
        try:
            return _orig_get_template(env, f"{lang}/{name}", parent, globals)
        except _jinja2.TemplateNotFound:
            pass  # no translated version — fall through to English

    return _orig_get_template(env, name, parent, globals)

app.jinja_env.get_template = _types.MethodType(_lang_get_template, app.jinja_env)

# Add custom strftime filter for date formatting
import datetime
def strftime_filter(timestamp, fmt='%Y-%m-%d %H:%M'):
    """Convert Unix timestamp to formatted date string."""
    if timestamp is None:
        return None
    try:
        dt = datetime.datetime.fromtimestamp(timestamp)
        return dt.strftime(fmt)
    except (TypeError, ValueError, OSError):
        return str(timestamp)

app.jinja_env.filters['strftime'] = strftime_filter
# ─────────────────────────────────────────────────────────────────────────────

# WebSocket upgrade request handler (before normal routing)
# This handles WebSocket upgrade requests that Flask's routing layer would reject
@app.before_request
def handle_websocket_upgrade():
    """Handle WebSocket upgrade requests gracefully by hijacking them early."""
    from flask import request
    
    upgrade_header = request.headers.get('Upgrade', '').lower()
    connection_header = request.headers.get('Connection', '').lower()
    
    if 'upgrade' in connection_header and 'websocket' in upgrade_header:
        path_with_qs = request.path
        qs = request.query_string.decode('utf-8')
        if qs: path_with_qs += '?' + qs
            
        if request.path.startswith('/lab/project/'):
            import re, socket, gevent, gevent.select, os
            from glob_vars import app_log, BASE_DIR
            
            # 1. Parse slug and target path
            m = re.match(r'^/lab/project/([^/]+)/edit(.*)$', path_with_qs)
            if not m: return "Invalid Lab Path", 400
            slug = m.group(1)
            full_path = m.group(2) if m.group(2) else "/"
            
            # 2. Extract raw client socket
            client_sock = request.environ.get('werkzeug.socket')
            if not client_sock:
                wsgi_input = request.environ.get('wsgi.input')
                client_sock = getattr(wsgi_input, 'raw', wsgi_input)._sock
                
            # 3. Connect to Unix socket
            unix_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock_path = os.path.join(BASE_DIR, 'files/lab-sockets', f"{slug}.sock")
            try:
                unix_socket.connect(sock_path)
            except Exception as e:
                return "Container offline", 502
            
            # 4. Construct perfectly compliant Upgrade request
            req_lines = [f"{request.method} {full_path} HTTP/1.1"]
            
            headers_sent = []
            for k, v in request.headers.items():
                if k.lower() == 'sec-websocket-extensions':
                    continue # Prevent RSV1 compression crash
                req_lines.append(f"{k}: {v}")
                headers_sent.append(k.lower())
            
            # Reconstruct missing headers
            if 'sec-websocket-key' not in headers_sent and 'HTTP_SEC_WEBSOCKET_KEY' in request.environ:
                req_lines.append(f"Sec-WebSocket-Key: {request.environ['HTTP_SEC_WEBSOCKET_KEY']}")
            if 'sec-websocket-version' not in headers_sent and 'HTTP_SEC_WEBSOCKET_VERSION' in request.environ:
                req_lines.append(f"Sec-WebSocket-Version: {request.environ['HTTP_SEC_WEBSOCKET_VERSION']}")
            if 'upgrade' not in headers_sent: req_lines.append("Upgrade: websocket")
            if 'connection' not in headers_sent: req_lines.append("Connection: Upgrade")
                
            raw_req = "\r\n".join(req_lines) + "\r\n\r\n"
            unix_socket.sendall(raw_req.encode('utf-8'))
            
            # 5. Read backend response (Yielding to prevent block)
            handshake_response = b""
            while b"\r\n\r\n" not in handshake_response:
                gevent.select.select([unix_socket], [], [])
                chunk = unix_socket.recv(4096)
                if not chunk: break
                handshake_response += chunk
                
            app_log.info(f"[websocket] Backend response: {handshake_response.split(b'\r\n')}")
            
            header_end = handshake_response.find(b"\r\n\r\n") + 4
            backend_headers = handshake_response[:header_end]
            backend_payload = handshake_response[header_end:]
            
            # 6. Handle Double Handshake
            if 'wsgi.websocket' in request.environ or 'werkzeug.websocket' in request.environ:
                if backend_payload: client_sock.sendall(backend_payload)
            else:
                client_sock.sendall(handshake_response)
                
            # 7. Bidirectional Relay (Yielding to prevent event loop death)
            def forward(src, dst):
                try:
                    while True:
                        gevent.select.select([src], [], []) # CRITICAL: Yield to gevent hub!
                        data = src.recv(8192)
                        if not data: break
                        dst.sendall(data)
                except Exception:
                    pass
                    
            g1 = gevent.spawn(forward, client_sock, unix_socket)
            g2 = gevent.spawn(forward, unix_socket, client_sock)
            gevent.joinall([g1, g2])
            
            # 8. Close socket gracefully
            try: client_sock.close()
            except Exception: pass
            
            return "", 204
        else:
            return None

# ── CSP Header Override for Lab Routes ────────────────────────────────────────
# Code-server requires specific CSP headers to execute inline scripts and load external resources.
# This middleware allows permissive CSP for Lab editor paths only.
@app.after_request
def handle_lab_csp_headers(response):
    """Override CSP headers for Lab routes to allow code-server to function."""
    if request.path.startswith('/lab/project/'):
        # Allow code-server to execute inline scripts, load external resources (CDNs), and manage iframes
        response.headers['Content-Security-Policy'] = (
            "default-src * 'unsafe-inline' 'unsafe-eval'; "
            "frame-ancestors 'self'; "
            "script-src * 'unsafe-inline' 'unsafe-eval' blob:; "
            "style-src * 'unsafe-inline'; "
            "font-src * data:; "
        )
        # Remove X-Frame-Options to allow code-server to be framed by LANHub
        response.headers.pop('X-Frame-Options', None)
        app_log.debug(f"[lab] Applied permissive CSP headers for {request.path}")
    return response

app.register_blueprint(chat_bp)
app.register_blueprint(stats_bp)
app.register_blueprint(logs_bp)
app.register_blueprint(devices_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(dropzone_bp)
app.before_request(check_site_access)
app.before_request(check_ban)
app.register_blueprint(channels_bp)
app.register_blueprint(feedback_bp)
app.register_blueprint(polls_bp)
app.register_blueprint(updates_bp)
app.register_blueprint(chess_bp)
app.register_blueprint(tetris_bp)
app.register_blueprint(uno_bp)
app.register_blueprint(server_config_bp)
app.register_blueprint(slither_bp)
app.register_blueprint(scribble_bp)
app.register_blueprint(geoguesser_bp)
app.register_blueprint(access_bp)
app.register_blueprint(backup_bp)
app.register_blueprint(lab_bp)


###########################################
# App Configs
###########################################
app.config["MAX_CONTENT_LENGTH"] = _config.DROPZONE_MAX_FILE_BYTES


###########################################
# Other Handlers
###########################################

from flask import jsonify, make_response

@app.route("/set-language", methods=["POST"])
def set_language():
    """
    POST { "lang": "fr" }
    Sets a one-year cookie and returns JSON.
    The JS in base.html reloads the page after receiving { ok: true }.
    """
    data = request.get_json(silent=True) or {}
    lang = str(data.get("lang", "en"))
    # Sanitise: alphanumeric + hyphens/underscores only, max 10 chars
    if not lang.replace("-", "").replace("_", "").isalnum() or len(lang) > 10:
        lang = "en"
    resp = make_response(jsonify({"ok": True, "lang": lang}))
    resp.set_cookie(
        "lanhub_lang", lang,
        max_age=365 * 86400,
        httponly=False,   # JS reads this for auto-detect
        samesite="Lax",
    )
    return resp


@socketio.on("connect")
def _track_connect():
    pass


@app.template_filter("timestamp_fmt")
def timestamp_fmt(ts):
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


@app.errorhandler(413)
def too_large(e):
    from flask import jsonify
    return jsonify({"ok": False, "error": "File too large."}), 413


def _repo_url_to_pages(repo_url: str) -> str | None:
    """
    Convert a GitHub repo URL to its GitHub Pages URL.

    https://github.com/USER/REPO        →  https://USER.github.io/REPO/
    https://github.com/USER/REPO.git    →  https://USER.github.io/REPO/
    git@github.com:USER/REPO.git        →  https://USER.github.io/REPO/

    Returns None if the URL can't be parsed.
    """
    m = _re.match(
        r'https?://github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?\s*$',
        repo_url.strip()
    )
    if m:
        return f"https://{m.group(1)}.github.io/{m.group(2)}/"

    m = _re.match(
        r'git@github\.com:([^/\s]+)/([^/\s]+?)(?:\.git)?\s*$',
        repo_url.strip()
    )
    if m:
        return f"https://{m.group(1)}.github.io/{m.group(2)}/"

    return None


@app.context_processor
def inject_globals():
    import config as _config
    import re as _re

    def _repo_url_to_pages(url):
        m = _re.match(r'https?://github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?\s*$', url.strip())
        if m:
            return f"https://{m.group(1)}.github.io/{m.group(2)}/"
        m = _re.match(r'git@github\.com:([^/\s]+)/([^/\s]+?)(?:\.git)?\s*$', url.strip())
        if m:
            return f"https://{m.group(1)}.github.io/{m.group(2)}/"
        return None

    # Only expose languages that actually have a sub-folder in templates/
    templates_dir = os.path.join(BASE_DIR, "templates")
    available_langs = {"en": LANG_NAMES["en"]}
    try:
        for name in sorted(os.listdir(templates_dir)):
            if (os.path.isdir(os.path.join(templates_dir, name))
                    and name in LANG_NAMES):
                available_langs[name] = LANG_NAMES[name]
    except Exception:
        pass

    current_lang = request.cookies.get("lanhub_lang", "en")
    if current_lang not in available_langs:
        current_lang = "en"

    return {
        "share_url":       _repo_url_to_pages(getattr(_config, "REPO_URL", "") or ""),
        "afk_idle_secs":   int(getattr(_config, "AFK_IDLE_SECS",   300)),
        "afk_prompt_secs": int(getattr(_config, "AFK_PROMPT_SECS",  60)),
        "available_langs": available_langs,   # {code: display_name}
        "current_lang":    current_lang,
    }


###########################################
# Routes
###########################################
@app.route("/")
def index():
    return render_template("root.html")


@app.route("/about")
def about():
    return render_template("about.html")


##########################################
# Graceful Shutdown Handler
##########################################
def graceful_shutdown(signum, frame):
    app_log.info(f"[shutdown] Signal {signum} received — starting graceful shutdown...")

    # ── 1. Warn all connected clients ─────────────────────────────────────────
    try:
        socketio.emit("server_shutdown", {
            "message": "The server is shutting down. See you soon!"
        })
        app_log.info("[shutdown] Shutdown notice sent to all connected clients.")
    except Exception as e:
        app_log.warning(f"[shutdown] Could not notify clients: {e}")

    # ── 2. Stop the scheduler (no new jobs) ───────────────────────────────────
    try:
        if sch.scheduler.running:
            sch.scheduler.shutdown(wait=False)
            app_log.info("[shutdown] Scheduler stopped.")
    except Exception as e:
        app_log.warning(f"[shutdown] Scheduler shutdown error: {e}")

    # ── 3. Push offline page to GitHub redirector ─────────────────────────────
    try:
        app_log.info("[shutdown] Pushing offline page to GitHub redirector...")
        ok = sch.push_offline_page()
        if not ok:
            app_log.warning("[shutdown] Offline page push failed — friends may see a stale redirect.")
    except Exception as e:
        app_log.warning(f"[shutdown] Redirector offline push error: {e}")

    # ── 4. Kill cloudflared tunnel process ────────────────────────────────────
    CF_PID_FILE = "/tmp/lanhub_cf.pid"
    try:
        if os.path.exists(CF_PID_FILE):
            with open(CF_PID_FILE) as f:
                cf_pid = int(f.read().strip())
            os.kill(cf_pid, signal.SIGTERM)
            os.remove(CF_PID_FILE)
            app_log.info(f"[shutdown] cloudflared (pid={cf_pid}) terminated.")
    except ProcessLookupError:
        app_log.info("[shutdown] cloudflared process already gone.")
    except Exception as e:
        app_log.warning(f"[shutdown] Could not stop cloudflared: {e}")

    # ── 5. Close active game/chess/uno sessions ───────────────────────────────
    try:
        from socket_events.chess_events import active_games
        for gid, game in list(active_games.items()):
            if game.get("status") == "active":
                game["status"] = "ended"
                game["result"] = "1/2-1/2"
                game["result_reason"] = "Server shutdown"
        app_log.info(f"[shutdown] Closed {len(active_games)} active chess game(s).")
    except Exception as e:
        app_log.warning(f"[shutdown] Chess cleanup error: {e}")

    try:
        from socket_events.uno_events import rooms
        for rid, room in list(rooms.items()):
            if room.get("status") == "playing":
                room["status"] = "ended"
        app_log.info(f"[shutdown] Closed {len(rooms)} active UNO room(s).")
    except Exception as e:
        app_log.warning(f"[shutdown] UNO cleanup error: {e}")

    # ── 6. Flush all log handlers ─────────────────────────────────────────────
    try:
        for logger in [app_log, access_log, git_log, error_log]:
            for handler in logger.handlers:
                handler.flush()
        app_log.info("[shutdown] Log handlers flushed.")
    except Exception as e:
        pass  # best effort

    # ── 7. Brief pause to let socket messages and log writes finish ───────────
    import time
    time.sleep(1.5)

    app_log.info("[shutdown] Shutdown complete. Goodbye.")
    sys.exit(0)


signal.signal(signal.SIGINT, graceful_shutdown)
signal.signal(signal.SIGTERM, graceful_shutdown)

if __name__ == "__main__":
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        sch.start_scheduler()
    # Use gevent as WSGI server with WebSocket support for Lab reverse proxy
    socketio.run(app, host="0.0.0.0", debug=True, port=_config.PORT, allow_unsafe_werkzeug=True)