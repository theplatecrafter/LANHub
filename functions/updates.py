"""functions/updates.py - Version/update management."""

import time
from .db import get_db


def updates_get_all() -> list[dict]:
    """Get all updates."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM updates ORDER BY timestamp DESC")
    cols = [d[0] for d in c.description]
    rows = [dict(zip(cols, row)) for row in c.fetchall()]
    conn.close()
    return rows


def updates_get_by_id(update_id: int) -> dict | None:
    """Get a specific update."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM updates WHERE id=?", (update_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    cols = [d[0] for d in c.description]
    return dict(zip(cols, row))


def updates_create(title: str, description: str, version: str) -> dict:
    """Create a new update entry."""
    now = time.time()
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO updates (title, description, version, timestamp)
        VALUES (?, ?, ?, ?)
    """,
        (title, description, version, now),
    )
    uid = c.lastrowid
    conn.commit()
    conn.close()
    return updates_get_by_id(uid)


def updates_edit(
    update_id: int, title: str, description: str, version: str
) -> dict | None:
    """Edit an update entry."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        UPDATE updates
        SET title=?, description=?, version=?
        WHERE id=?
    """,
        (title, description, version, update_id),
    )
    conn.commit()
    conn.close()
    return updates_get_by_id(update_id)


def updates_delete(update_id: int) -> None:
    """Delete an update entry."""
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM updates WHERE id=?", (update_id,))
    conn.commit()
    conn.close()
