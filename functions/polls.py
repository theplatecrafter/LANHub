"""functions/polls.py - Poll/voting system."""

import time
from .db import get_db


def poll_create(
    title: str,
    description: str,
    poll_type: str,
    options: list[str],
    tags: list[str],
    ip: str,
    is_dev: bool,
    created_by: str,
) -> dict:
    """Create a new poll."""
    now = time.time()
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO polls (title, description, poll_type, is_dev, created_by, ip, timestamp)
        VALUES (?,?,?,?,?,?,?)
    """,
        (title, description, poll_type, int(is_dev), created_by, ip, now),
    )
    pid = c.lastrowid

    for i, label in enumerate(options):
        c.execute(
            "INSERT INTO poll_options (poll_id, label, position) VALUES (?,?,?)",
            (pid, label.strip(), i),
        )

    clean = list({t.strip().lower() for t in tags if t.strip()})
    for tag in clean:
        c.execute("INSERT INTO poll_tags (poll_id, tag) VALUES (?,?)", (pid, tag))

    conn.commit()
    conn.close()
    return poll_get_by_id(pid, ip)


def _poll_attach(rows: list[dict], viewer_ip: str) -> list[dict]:
    """Attach options, votes, and viewer data to poll rows."""
    if not rows:
        return rows
    conn = get_db()
    c = conn.cursor()
    ids = [r["id"] for r in rows]
    ph = ",".join("?" * len(ids))

    # Options
    c.execute(
        f"SELECT id, poll_id, label, position FROM poll_options WHERE poll_id IN ({ph}) ORDER BY position",
        ids,
    )
    opts_map: dict[int, list] = {}
    for oid, pid, label, pos in c.fetchall():
        opts_map.setdefault(pid, []).append(
            {"id": oid, "label": label, "position": pos}
        )

    # Vote counts per option
    c.execute(
        f"SELECT option_id, COUNT(*) FROM poll_votes WHERE poll_id IN ({ph}) GROUP BY option_id",
        ids,
    )
    vote_map = {oid: cnt for oid, cnt in c.fetchall()}

    # Total votes per poll
    c.execute(
        f"SELECT poll_id, COUNT(DISTINCT ip) FROM poll_votes WHERE poll_id IN ({ph}) GROUP BY poll_id",
        ids,
    )
    total_map = {pid: cnt for pid, cnt in c.fetchall()}

    # What did viewer vote on each poll?
    c.execute(
        f"SELECT poll_id, option_id FROM poll_votes WHERE poll_id IN ({ph}) AND ip=?",
        ids + [viewer_ip],
    )
    viewer_votes: dict[int, set] = {}
    for pid, oid in c.fetchall():
        viewer_votes.setdefault(pid, set()).add(oid)

    # Tags
    c.execute(f"SELECT poll_id, tag FROM poll_tags WHERE poll_id IN ({ph})", ids)
    tag_map: dict[int, list] = {}
    for pid, tag in c.fetchall():
        tag_map.setdefault(pid, []).append(tag)

    conn.close()
    for r in rows:
        pid = r["id"]
        opts = opts_map.get(pid, [])
        voted = viewer_votes.get(pid, set())
        total = total_map.get(pid, 0)
        for o in opts:
            o["votes"] = vote_map.get(o["id"], 0)
            o["viewer_voted"] = o["id"] in voted
            o["pct"] = round(o["votes"] / total * 100) if total else 0
        r["options"] = opts
        r["total_votes"] = total
        r["viewer_voted"] = bool(voted)
        r["tags"] = tag_map.get(pid, [])
    return rows


def poll_search(query: str = "", tag: str = "", viewer_ip: str = "") -> list[dict]:
    """Search polls by title/description or tag."""
    conn = get_db()
    c = conn.cursor()
    clauses, params = [], []
    if query:
        clauses.append("(p.title LIKE ? OR p.description LIKE ?)")
        params += [f"%{query}%", f"%{query}%"]
    if tag:
        clauses.append(
            "EXISTS (SELECT 1 FROM poll_tags pt WHERE pt.poll_id=p.id AND pt.tag=?)"
        )
        params.append(tag.lower())
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    c.execute(
        f"""
        SELECT p.*,
               (SELECT COUNT(DISTINCT ip) FROM poll_votes v WHERE v.poll_id=p.id) AS total_votes
        FROM polls p
        {where}
        ORDER BY
            p.is_dev DESC,
            total_votes DESC,
            p.timestamp DESC
    """,
        params,
    )
    cols = [d[0] for d in c.description]
    rows = [dict(zip(cols, row)) for row in c.fetchall()]
    conn.close()
    return _poll_attach(rows, viewer_ip)


def poll_get_by_id(poll_id: int, viewer_ip: str = "") -> dict | None:
    """Get a poll by ID."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM polls WHERE id=?", (poll_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return _poll_attach([dict(row)], viewer_ip)[0]


def poll_vote(poll_id: int, option_ids: list[int], ip: str) -> dict:
    """
    Cast votes. For single-choice polls, clears previous vote first.
    Returns updated poll dict.
    """
    conn = get_db()
    c = conn.cursor()

    # Verify poll type
    c.execute("SELECT poll_type FROM polls WHERE id=?", (poll_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise ValueError("Poll not found.")
    poll_type = row[0]

    if poll_type == "single" and len(option_ids) > 1:
        option_ids = option_ids[:1]

    # Remove previous votes for this IP on this poll
    c.execute("DELETE FROM poll_votes WHERE poll_id=? AND ip=?", (poll_id, ip))

    now = time.time()
    for oid in option_ids:
        try:
            c.execute(
                "INSERT INTO poll_votes (poll_id, option_id, ip, timestamp) VALUES (?,?,?,?)",
                (poll_id, oid, ip, now),
            )
        except Exception:
            pass  # UNIQUE violation — skip

    conn.commit()
    conn.close()
    return poll_get_by_id(poll_id, ip)


def poll_tag_suggestions(prefix: str, limit: int = 8) -> list[str]:
    """Get tag suggestions for polls."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        SELECT tag, COUNT(*) cnt FROM poll_tags
        WHERE tag LIKE ? GROUP BY tag ORDER BY cnt DESC, tag ASC LIMIT ?
    """,
        (f"{prefix.lower()}%", limit),
    )
    tags = [r[0] for r in c.fetchall()]
    conn.close()
    return tags


def poll_delete(poll_id: int) -> None:
    """Delete a poll."""
    conn = get_db()
    conn.execute("DELETE FROM polls WHERE id=?", (poll_id,))
    conn.commit()
    conn.close()
