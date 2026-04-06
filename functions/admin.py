"""functions/admin.py - Admin user management."""

from werkzeug.security import generate_password_hash
from .db import get_db


def get_admin_by_username(username: str) -> dict | None:
    """Get admin by username."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM admins WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_admin_by_id(admin_id: int) -> dict | None:
    """Get admin by ID."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM admins WHERE id = ?", (admin_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_admins() -> list[dict]:
    """Get all admins."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, username, role FROM admins ORDER BY role DESC, username")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def create_admin(username: str, password: str, role: str) -> tuple[bool, str]:
    """Create a new admin. Returns (success, message)."""
    if not username or not password:
        return False, "Username and password are required."
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO admins (username, password_hash, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), role),
        )
        conn.commit()
        conn.close()
        return True, ""
    except Exception as e:
        return False, "Username already exists." if "UNIQUE" in str(e) else str(e)


def edit_admin(
    admin_id: int,
    new_username: str | None,
    new_password: str | None,
    new_role: str | None,
) -> tuple[bool, str]:
    """Edit an admin's properties."""
    conn = get_db()
    c = conn.cursor()
    try:
        if new_username:
            c.execute(
                "UPDATE admins SET username = ? WHERE id = ?", (new_username, admin_id)
            )
        if new_password:
            c.execute(
                "UPDATE admins SET password_hash = ? WHERE id = ?",
                (generate_password_hash(new_password), admin_id),
            )
        if new_role:
            c.execute("UPDATE admins SET role = ? WHERE id = ?", (new_role, admin_id))
        conn.commit()
        return True, ""
    except Exception as e:
        return False, "Username already exists." if "UNIQUE" in str(e) else str(e)
    finally:
        conn.close()


def delete_admin(admin_id: int) -> None:
    """Delete an admin."""
    conn = get_db()
    conn.execute("DELETE FROM admins WHERE id = ?", (admin_id,))
    conn.commit()
    conn.close()
