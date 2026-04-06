"""functions/feedback.py - User feedback system."""

import time
from .db import get_db


def feedback_create(
    type_: str, title: str, description: str, username: str, ip: str, tags: list[str]
) -> dict:
    """Create new feedback."""
    now = time.time()
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO feedback (type, title, description, username, ip, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (type_, title, description, username, ip, now),
    )
    fid = c.lastrowid
    clean = list({t.strip().lower() for t in tags if t.strip()})
    for tag in clean:
        c.execute(
            "INSERT INTO feedback_tags (feedback_id, tag) VALUES (?,?)", (fid, tag)
        )
    conn.commit()
    conn.close()
    return feedback_get_by_id(fid, ip)


def _feedback_attach(rows: list[dict], viewer_ip: str) -> list[dict]:
    """Attach tags, star count, and viewer_starred to a list of feedback dicts."""
    if not rows:
        return rows
    conn = get_db()
    c = conn.cursor()
    ids = [r["id"] for r in rows]
    placeholders = ",".join("?" * len(ids))

    c.execute(
        f"SELECT feedback_id, tag FROM feedback_tags WHERE feedback_id IN ({placeholders})",
        ids,
    )
    tag_map: dict[int, list] = {}
    for fb_id, tag in c.fetchall():
        tag_map.setdefault(fb_id, []).append(tag)

    c.execute(
        f"SELECT feedback_id, COUNT(*) FROM feedback_stars WHERE feedback_id IN ({placeholders}) GROUP BY feedback_id",
        ids,
    )
    star_map = {fb_id: cnt for fb_id, cnt in c.fetchall()}

    c.execute(
        f"SELECT feedback_id FROM feedback_stars WHERE feedback_id IN ({placeholders}) AND ip = ?",
        ids + [viewer_ip],
    )
    viewer_starred = {row[0] for row in c.fetchall()}

    c.execute(
        f"SELECT feedback_id, COUNT(*) FROM feedback_replies WHERE feedback_id IN ({placeholders}) GROUP BY feedback_id",
        ids,
    )
    reply_map = {fb_id: cnt for fb_id, cnt in c.fetchall()}

    conn.close()
    for r in rows:
        r["tags"] = tag_map.get(r["id"], [])
        r["stars"] = star_map.get(r["id"], 0)
        r["viewer_starred"] = r["id"] in viewer_starred
        r["reply_count"] = reply_map.get(r["id"], 0)
    return rows


def feedback_search(
    query: str = "", type_: str = "", tag: str = "", viewer_ip: str = ""
) -> list[dict]:
    """Search feedback. Returns open first (by stars desc), then resolved."""
    conn = get_db()
    c = conn.cursor()
    clauses = []
    params = []
    if query:
        clauses.append("(f.title LIKE ? OR f.description LIKE ? OR f.username LIKE ?)")
        params += [f"%{query}%", f"%{query}%", f"%{query}%"]
    if type_:
        clauses.append("f.type = ?")
        params.append(type_)
    if tag:
        clauses.append(
            "EXISTS (SELECT 1 FROM feedback_tags ft WHERE ft.feedback_id=f.id AND ft.tag=?)"
        )
        params.append(tag.lower())
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    c.execute(
        f"""
        SELECT f.*,
               (SELECT COUNT(*) FROM feedback_stars s WHERE s.feedback_id=f.id) AS stars
        FROM feedback f
        {where}
        ORDER BY
            CASE f.status WHEN 'open' THEN 0 ELSE 1 END ASC,
            stars DESC,
            f.timestamp DESC
    """,
        params,
    )
    cols = [d[0] for d in c.description]
    rows = [dict(zip(cols, row)) for row in c.fetchall()]
    conn.close()
    return _feedback_attach(rows, viewer_ip)


def feedback_get_by_id(fb_id: int, viewer_ip: str = "") -> dict | None:
    """Get feedback by ID."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM feedback WHERE id=?", (fb_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return _feedback_attach([dict(row)], viewer_ip)[0]


def feedback_toggle_star(fb_id: int, ip: str) -> dict:
    """Toggle star on feedback. Returns {starred: bool, stars: int}."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM feedback_stars WHERE feedback_id=? AND ip=?", (fb_id, ip))
    existing = c.fetchone()
    if existing:
        c.execute(
            "DELETE FROM feedback_stars WHERE feedback_id=? AND ip=?", (fb_id, ip)
        )
        starred = False
    else:
        c.execute(
            "INSERT INTO feedback_stars (feedback_id, ip, timestamp) VALUES (?,?,?)",
            (fb_id, ip, time.time()),
        )
        starred = True
    conn.commit()
    c.execute("SELECT COUNT(*) FROM feedback_stars WHERE feedback_id=?", (fb_id,))
    stars = c.fetchone()[0]
    conn.close()
    return {"starred": starred, "stars": stars}


def feedback_add_reply(
    fb_id: int, username: str, ip: str, content: str, is_dev: bool
) -> dict:
    """Add a reply to feedback."""
    now = time.time()
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO feedback_replies (feedback_id, username, ip, content, is_dev, timestamp)
        VALUES (?,?,?,?,?,?)
    """,
        (fb_id, username, ip, content, int(is_dev), now),
    )
    rid = c.lastrowid
    conn.commit()
    conn.close()
    return {
        "id": rid,
        "feedback_id": fb_id,
        "username": username,
        "content": content,
        "is_dev": is_dev,
        "timestamp": now,
    }


def feedback_get_replies(fb_id: int) -> list[dict]:
    """Get all replies to feedback."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM feedback_replies WHERE feedback_id=? ORDER BY timestamp ASC",
        (fb_id,),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def feedback_resolve(fb_id: int, resolved_by: str, note: str) -> None:
    """Mark feedback as resolved."""
    conn = get_db()
    conn.execute(
        """
        UPDATE feedback SET status='resolved', resolved_by=?, resolved_at=?, resolved_note=?
        WHERE id=?
    """,
        (resolved_by, time.time(), note, fb_id),
    )
    conn.commit()
    conn.close()


def feedback_tag_suggestions(prefix: str, limit: int = 8) -> list[str]:
    """Get tag suggestions for feedback."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        SELECT tag, COUNT(*) cnt FROM feedback_tags
        WHERE tag LIKE ? GROUP BY tag ORDER BY cnt DESC, tag ASC LIMIT ?
    """,
        (f"{prefix.lower()}%", limit),
    )
    tags = [r[0] for r in c.fetchall()]
    conn.close()
    return tags
