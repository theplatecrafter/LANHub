"""
blueprints/admin/auth_utils.py

Authentication and authorization utilities for admin blueprint.
Separated to avoid circular imports.
"""

from flask import redirect, url_for, request, session
from functools import wraps


# Role level hierarchy
ROLE_LEVELS = {"MOD": 1, "DEV": 2}


# ── Helpers ───────────────────────────────────────────────────────────────────
def _role() -> str | None:
    """Get the current session's admin role."""
    return session.get("admin_role")


def _name() -> str | None:
    """Get the current session's admin name."""
    return session.get("admin_name")


def require_role(min_role: str):
    """
    Decorator to require a minimum admin role for a route.
    
    Args:
        min_role: Required role ('MOD' or 'DEV')
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not _role() or ROLE_LEVELS.get(_role(), 0) < ROLE_LEVELS[min_role]:
                return redirect(url_for("admin.login", next=request.path))
            return fn(*args, **kwargs)
        return wrapper
    return decorator
