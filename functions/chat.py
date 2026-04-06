"""functions/chat.py - Chat messages, channels, and related utilities."""

import time
from werkzeug.security import check_password_hash, generate_password_hash
from glob_vars import CHAT_RATE_WINDOW, CHAT_RATE_LIMIT
from .db import get_db

# In-memory rate tracker: { ip: [timestamp, ...] }
_rate_tracker: dict[str, list[float]] = {}


def is_rate_limited(ip: str) -> bool:
    """Sliding window rate limiter. Returns True if IP is over the limit."""
    now = time.time()
    timestamps = _rate_tracker.get(ip, [])
    timestamps = [t for t in timestamps if now - t < CHAT_RATE_WINDOW]
    if len(timestamps) >= CHAT_RATE_LIMIT:
        _rate_tracker[ip] = timestamps
        return True
    timestamps.append(now)
    _rate_tracker[ip] = timestamps
    return False


# ── Chat Messages ─────────────────────────────────────────────────────────────


def save_chat_message(
    username: str,
    ip: str,
    message: str,
    reply_to_id: int | None = None,
    msg_type: str = "text",
) -> dict:
    """Inserts a message and returns it as a dict (including reply info if any)."""
    now = time.time()
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO chat_messages (username, ip, message, timestamp, reply_to_id, msg_type) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (username, ip, message, now, reply_to_id, msg_type),
    )
    conn.commit()
    row_id = c.lastrowid

    # Fetch reply info so the broadcast payload is complete
    reply_username = None
    reply_message = None
    if reply_to_id:
        c.execute(
            "SELECT username, message FROM chat_messages WHERE id = ?", (reply_to_id,)
        )
        row = c.fetchone()
        if row:
            reply_username = row["username"]
            reply_message = row["message"]

    conn.close()
    return {
        "id": row_id,
        "username": username,
        "message": message,
        "timestamp": now,
        "edited": False,
        "reply_to_id": reply_to_id,
        "reply_username": reply_username,
        "reply_message": reply_message,
        "msg_type": msg_type,
    }


def get_recent_messages(limit: int) -> list[dict]:
    """Returns the most recent `limit` messages (oldest first), with reply info joined."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            m.id, m.username, m.message, m.timestamp, m.edited,
            m.reply_to_id, m.msg_type,
            r.username AS reply_username, r.message AS reply_message
        FROM chat_messages m
        LEFT JOIN chat_messages r ON m.reply_to_id = r.id
        ORDER BY m.id DESC LIMIT ?
    """,
        (limit,),
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    rows.reverse()  # oldest → newest
    return rows


def edit_message(msg_id: int, new_text: str) -> None:
    """Updates message text and marks it as edited."""
    conn = get_db()
    conn.execute(
        "UPDATE chat_messages SET message = ?, edited = 1 WHERE id = ?",
        (new_text, msg_id),
    )
    conn.commit()
    conn.close()


def delete_message(msg_id: int) -> None:
    """Hard-deletes a message from the DB."""
    conn = get_db()
    conn.execute("DELETE FROM chat_messages WHERE id = ?", (msg_id,))
    conn.commit()
    conn.close()


def get_messages_before(before_id: int, limit: int) -> list[dict]:
    """Returns `limit` messages older than `before_id`, oldest first."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            m.id, m.username, m.message, m.timestamp, m.edited,
            m.reply_to_id, m.msg_type,
            r.username AS reply_username, r.message AS reply_message
        FROM chat_messages m
        LEFT JOIN chat_messages r ON m.reply_to_id = r.id
        ORDER BY m.id DESC LIMIT ?
    """,
        (limit,),
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    rows.reverse()  # oldest → newest
    return rows


# ── Channels ──────────────────────────────────────────────────────────────────


def create_channel(
    title: str, description: str, tags: list[str], password: str, ip: str
) -> dict:
    """Create a new channel."""
    now = time.time()
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO channels (title, description, password_hash, created_by_ip, created_at)
        VALUES (?, ?, ?, ?, ?)
    """,
        (title, description, generate_password_hash(password), ip, now),
    )
    cid = c.lastrowid

    clean_tags = list({t.strip().lower() for t in tags if t.strip()})
    for tag in clean_tags:
        c.execute("INSERT INTO channel_tags (channel_id, tag) VALUES (?,?)", (cid, tag))

    conn.commit()
    conn.close()

    return {
        "id": cid,
        "title": title,
        "description": description,
        "tags": clean_tags,
        "created_at": now,
    }


def get_channel_by_id(channel_id: int) -> dict | None:
    """Get a channel by ID."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM channels WHERE id = ?", (channel_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    d = dict(row)
    c.execute(
        "SELECT tag FROM channel_tags WHERE channel_id = ? ORDER BY tag", (channel_id,)
    )
    d["tags"] = [r[0] for r in c.fetchall()]
    conn.close()
    return d


def search_channels(query: str = "", tag: str = "") -> list[dict]:
    """Search channels by title, description, or tag."""
    conn = get_db()
    c = conn.cursor()
    like = f"%{query}%"

    if tag:
        c.execute(
            """
            SELECT DISTINCT ch.id, ch.title, ch.description, ch.created_at
            FROM channels ch
            JOIN channel_tags ct ON ct.channel_id = ch.id
            WHERE ct.tag = ?
              AND (ch.title LIKE ? OR ch.description LIKE ? OR CAST(ch.id AS TEXT) = ?)
            ORDER BY ch.created_at DESC
        """,
            (tag.lower(), like, like, query),
        )
    else:
        c.execute(
            """
            SELECT id, title, description, created_at
            FROM channels
            WHERE title LIKE ? OR description LIKE ? OR CAST(id AS TEXT) = ?
            ORDER BY created_at DESC
        """,
            (like, like, query),
        )

    rows = []
    for row in c.fetchall():
        d = {"id": row[0], "title": row[1], "description": row[2], "created_at": row[3]}
        c2 = conn.cursor()
        c2.execute(
            "SELECT tag FROM channel_tags WHERE channel_id = ? ORDER BY tag", (d["id"],)
        )
        d["tags"] = [r[0] for r in c2.fetchall()]
        rows.append(d)

    conn.close()
    return rows


def channel_tag_suggestions(prefix: str, limit: int = 10) -> list[str]:
    """Get tag suggestions for channels."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        SELECT tag, COUNT(*) as cnt
        FROM channel_tags
        WHERE tag LIKE ?
        GROUP BY tag ORDER BY cnt DESC, tag ASC LIMIT ?
    """,
        (f"{prefix.lower()}%", limit),
    )
    tags = [r[0] for r in c.fetchall()]
    conn.close()
    return tags


def edit_channel(
    channel_id: int, title: str | None, description: str | None, tags: list[str] | None
) -> None:
    """Edit a channel's properties."""
    conn = get_db()
    c = conn.cursor()
    if title is not None:
        c.execute("UPDATE channels SET title = ? WHERE id = ?", (title, channel_id))
    if description is not None:
        c.execute(
            "UPDATE channels SET description = ? WHERE id = ?",
            (description, channel_id),
        )
    if tags is not None:
        c.execute("DELETE FROM channel_tags WHERE channel_id = ?", (channel_id,))
        clean = list({t.strip().lower() for t in tags if t.strip()})
        for tag in clean:
            c.execute(
                "INSERT INTO channel_tags (channel_id, tag) VALUES (?,?)",
                (channel_id, tag),
            )
    conn.commit()
    conn.close()


def delete_channel(channel_id: int) -> None:
    """Delete a channel."""
    conn = get_db()
    conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
    conn.commit()
    conn.close()


def verify_channel_password(channel_id: int, password: str) -> bool:
    """Verify a channel password."""
    ch = get_channel_by_id(channel_id)
    if not ch:
        return False
    return check_password_hash(ch["password_hash"], password)


# ── Channel Messages ──────────────────────────────────────────────────────────


def save_channel_message(
    channel_id: int,
    username: str,
    ip: str,
    message: str,
    reply_to_id: int | None = None,
    msg_type: str = "text",
) -> dict:
    """Save a message in a channel."""
    now = time.time()
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO channel_messages
            (channel_id, username, ip, message, timestamp, reply_to_id, msg_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (channel_id, username, ip, message, now, reply_to_id, msg_type),
    )
    conn.commit()
    mid = c.lastrowid

    reply_username = reply_message = None
    if reply_to_id:
        c.execute(
            "SELECT username, message FROM channel_messages WHERE id = ?",
            (reply_to_id,),
        )
        row = c.fetchone()
        if row:
            reply_username, reply_message = row[0], row[1]

    conn.close()
    return {
        "id": mid,
        "channel_id": channel_id,
        "username": username,
        "message": message,
        "timestamp": now,
        "edited": False,
        "reply_to_id": reply_to_id,
        "reply_username": reply_username,
        "reply_message": reply_message,
        "msg_type": msg_type,
    }


def get_channel_messages(channel_id: int, limit: int) -> list[dict]:
    """Get recent messages in a channel."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        SELECT m.id, m.username, m.message, m.timestamp, m.edited, m.msg_type,
               m.reply_to_id, r.username AS reply_username, r.message AS reply_message
        FROM channel_messages m
        LEFT JOIN channel_messages r ON m.reply_to_id = r.id
        WHERE m.channel_id = ?
        ORDER BY m.id DESC LIMIT ?
    """,
        (channel_id, limit),
    )
    rows = [
        dict(
            zip(
                [
                    "id",
                    "username",
                    "message",
                    "timestamp",
                    "edited",
                    "msg_type",
                    "reply_to_id",
                    "reply_username",
                    "reply_message",
                ],
                row,
            )
        )
        for row in c.fetchall()
    ]
    conn.close()
    rows.reverse()
    return rows


def get_channel_messages_before(
    channel_id: int, before_id: int, limit: int
) -> list[dict]:
    """Get channel messages before a certain ID."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        SELECT m.id, m.username, m.message, m.timestamp, m.edited, m.msg_type,
               m.reply_to_id, r.username AS reply_username, r.message AS reply_message
        FROM channel_messages m
        LEFT JOIN channel_messages r ON m.reply_to_id = r.id
        WHERE m.channel_id = ? AND m.id < ?
        ORDER BY m.id DESC LIMIT ?
    """,
        (channel_id, before_id, limit),
    )
    rows = [
        dict(
            zip(
                [
                    "id",
                    "username",
                    "message",
                    "timestamp",
                    "edited",
                    "msg_type",
                    "reply_to_id",
                    "reply_username",
                    "reply_message",
                ],
                row,
            )
        )
        for row in c.fetchall()
    ]
    conn.close()
    rows.reverse()
    return rows


def edit_channel_message(msg_id: int, new_text: str) -> None:
    """Edit a channel message."""
    conn = get_db()
    conn.execute(
        "UPDATE channel_messages SET message = ?, edited = 1 WHERE id = ?",
        (new_text, msg_id),
    )
    conn.commit()
    conn.close()


def delete_channel_message(msg_id: int) -> None:
    """Delete a channel message."""
    conn = get_db()
    conn.execute("DELETE FROM channel_messages WHERE id = ?", (msg_id,))
    conn.commit()
    conn.close()


def get_channel_online_count(channel_id: int, sessions: dict) -> int:
    """Count how many sids are currently in a given channel."""
    return sum(
        1 for info in sessions.values() if channel_id in info.get("channels", set())
    )
