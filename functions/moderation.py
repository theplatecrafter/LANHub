"""functions/moderation.py - IP bans and user reports."""

import time
from .db import get_db


def is_ip_banned(ip: str) -> dict | None:
    """Returns the ban row if the IP is currently banned, else None."""
    now = time.time()
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        SELECT * FROM ip_bans
        WHERE ip = ?
          AND (expires_at IS NULL OR expires_at > ?)
    """,
        (ip, now),
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_bans() -> list[dict]:
    """Get all IP bans."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM ip_bans ORDER BY banned_at DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def ban_ip(
    ip: str, reason: str, banned_by: str, expires_at: float | None = None
) -> tuple[bool, str]:
    """Ban an IP address."""
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO ip_bans (ip, reason, banned_by, banned_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (ip, reason, banned_by, time.time(), expires_at),
        )
        conn.commit()
        conn.close()
        return True, ""
    except Exception as e:
        return False, "IP already banned." if "UNIQUE" in str(e) else str(e)


def unban_ip(ban_id: int) -> None:
    """Remove an IP ban."""
    conn = get_db()
    conn.execute("DELETE FROM ip_bans WHERE id = ?", (ban_id,))
    conn.commit()
    conn.close()


def update_ban(ban_id: int, reason: str, expires_at: float | None) -> None:
    """Update a ban's reason and expiration."""
    conn = get_db()
    conn.execute(
        "UPDATE ip_bans SET reason = ?, expires_at = ? WHERE id = ?",
        (reason, expires_at, ban_id),
    )
    conn.commit()
    conn.close()


def create_report(
    reporter_ip: str,
    reported_username: str,
    reported_ip: str,
    message_id: int | None,
    message_text: str,
    reason: str,
    source: str = "chat",
) -> int:
    """Create a user report."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO reports
            (reporter_ip, reported_username, reported_ip,
             message_id, message_text, reason, timestamp, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            reporter_ip,
            reported_username,
            reported_ip,
            message_id,
            message_text,
            reason,
            time.time(),
            source,
        ),
    )
    conn.commit()
    rid = c.lastrowid
    conn.close()
    return rid


def get_reports(status: str | None = None) -> list[dict]:
    """Get reports, optionally filtered by status."""
    conn = get_db()
    c = conn.cursor()
    if status:
        c.execute(
            "SELECT * FROM reports WHERE status = ? ORDER BY timestamp DESC", (status,)
        )
    else:
        c.execute("SELECT * FROM reports ORDER BY timestamp DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def update_report_status(report_id: int, status: str, reviewed_by: str) -> None:
    """Update a report's status."""
    conn = get_db()
    conn.execute(
        """
        UPDATE reports
        SET status = ?, reviewed_by = ?, reviewed_at = ?
        WHERE id = ?
    """,
        (status, reviewed_by, time.time(), report_id),
    )
    conn.commit()
    conn.close()
