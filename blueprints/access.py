# blueprints/access.py
"""
Site-wide access gate.

Three modes (set via SITE_MODE in configvars.json or admin panel):
  lan_only        — only LAN/local connections are allowed; public users see a blocked page
  public_password — everyone must enter the password (LAN and public)
  both_password   — LAN devices connect freely; public connections require the password
"""

import hmac
import hashlib
import ipaddress

from flask import (
    Blueprint, render_template, request,
    redirect, url_for, make_response
)
import config

access_bp  = Blueprint("access", __name__)
_COOKIE    = "lanhub_access"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_token(password: str) -> str:
    """HMAC-SHA256 of the password with the app secret key."""
    key = (getattr(config, "SECRET_KEY", "") or "fallback").encode()
    return hmac.new(key, password.encode(), hashlib.sha256).hexdigest()


def is_lan_request() -> bool:
    """
    Returns True if the connection appears to come from the local network.
    Cloudflare tunnel requests always carry a CF-Connecting-IP header —
    if that header is present the request is public even if remote_addr is 127.0.0.1.
    """
    if request.headers.get("CF-Connecting-IP"):
        return False   # came through Cloudflare tunnel → public
    try:
        addr = ipaddress.ip_address(request.remote_addr or "127.0.0.1")
        return addr.is_private or addr.is_loopback
    except ValueError:
        return False


def is_access_granted() -> bool:
    """Returns True if the visitor holds a valid access cookie."""
    password = getattr(config, "SITE_PASSWORD", "").strip()
    if not password:
        return True  # gate disabled
    token = request.cookies.get(_COOKIE, "")
    if not token:
        return False
    return hmac.compare_digest(token, _make_token(password))


def check_site_access():
    """
    before_request hook.
    Returns None to allow the request, or a Response to block/redirect it.
    """
    # Always allow static files, the access page itself, admin, and socket.io
    skip = ("/static", "/access", "/admin", "/socket.io")
    if any(request.path.startswith(p) for p in skip):
        return None

    mode     = getattr(config, "SITE_MODE", "lan_only").strip()
    password = getattr(config, "SITE_PASSWORD", "").strip()
    lan      = is_lan_request()

    if mode == "lan_only":
        if not lan:
            return render_template("access_blocked.html"), 403
        return None

    elif mode == "public_password":
        if not password:
            return None  # no password configured → open
        if not is_access_granted():
            return redirect(url_for("access.access_page",
                                    next=request.path))
        return None

    elif mode == "both_password":
        if lan:
            return None  # LAN users always free
        if not password:
            return None
        if not is_access_granted():
            return redirect(url_for("access.access_page",
                                    next=request.path))
        return None

    return None   # unknown mode → allow


# ── Routes ────────────────────────────────────────────────────────────────────

@access_bp.route("/access", methods=["GET", "POST"])
def access_page():
    if is_access_granted():
        return redirect(request.args.get("next") or url_for("index"))

    error = None
    if request.method == "POST":
        entered  = request.form.get("password", "").strip()
        expected = getattr(config, "SITE_PASSWORD", "").strip()

        if entered and entered == expected:
            days  = int(getattr(config, "SITE_ACCESS_COOKIE_DAYS", 30))
            token = _make_token(entered)
            dest  = request.args.get("next") or url_for("index")
            resp  = make_response(redirect(dest))
            resp.set_cookie(
                _COOKIE, token,
                max_age=days * 86400,
                httponly=True,
                samesite="Lax",
            )
            return resp
        error = "Incorrect password."

    return render_template("access.html", error=error)


@access_bp.route("/access/logout", methods=["POST"])
def access_logout():
    """Clears the access cookie (useful for testing or switching accounts)."""
    resp = make_response(redirect(url_for("access.access_page")))
    resp.delete_cookie(_COOKIE)
    return resp