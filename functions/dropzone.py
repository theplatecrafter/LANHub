"""functions/dropzone.py - File upload and storage management."""

import os
import time
import uuid as _uuid
import mimetypes as _mimetypes
from werkzeug.security import generate_password_hash
from glob_vars import (
    BASE_DIR,
    DROPZONE_RATE_WINDOW_HOURS,
    DROPZONE_MAX_FILE_BYTES,
    DROPZONE_RATE_LIMIT_BYTES,
    DROPZONE_MAX_STORAGE_BYTES,
    app_log,
)
from .db import get_db

# Define directory locally
DROPZONE_DIR = os.path.join(BASE_DIR, "files", "dropzone")
os.makedirs(DROPZONE_DIR, exist_ok=True)


def dropzone_total_used() -> int:
    """Returns total bytes of all stored uploads."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(size_bytes),0) FROM uploads")
    total = c.fetchone()[0]
    conn.close()
    return total


def dropzone_ip_used_in_window(ip: str) -> int:
    """Bytes uploaded by this IP within the rate window."""
    cutoff = time.time() - DROPZONE_RATE_WINDOW_HOURS * 3600
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT COALESCE(SUM(size_bytes),0) FROM uploads WHERE uploader_ip=? AND timestamp>?",
        (ip, cutoff),
    )
    total = c.fetchone()[0]
    conn.close()
    return total


def dropzone_evict_oldest(needed_bytes: int) -> None:
    """Delete the oldest uploads until `needed_bytes` of space is freed."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, stored_name, size_bytes FROM uploads ORDER BY timestamp ASC")
    rows = c.fetchall()
    freed = 0
    for row in rows:
        if freed >= needed_bytes:
            break
        rid, stored_name, size = row[0], row[1], row[2]
        path = os.path.join(DROPZONE_DIR, stored_name)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        c.execute("DELETE FROM uploads WHERE id=?", (rid,))
        freed += size
        app_log.info(f"[dropzone] evicted {stored_name} ({size} bytes)")
    conn.commit()
    conn.close()


def dropzone_save(
    file_storage,
    display_name: str,
    tags: list[str],
    uploader_ip: str,
    password: str | None,
) -> dict:
    """
    Saves an uploaded file, evicting old files if needed.
    Returns the upload row dict on success, raises ValueError on quota exceeded.
    """
    data = file_storage.read()
    size = len(data)

    if size > DROPZONE_MAX_FILE_BYTES:
        raise ValueError(
            f"File too large (max {DROPZONE_MAX_FILE_BYTES // (1024*1024)} MB)."
        )

    # Per-IP rate check
    ip_used = dropzone_ip_used_in_window(uploader_ip)
    if ip_used + size > DROPZONE_RATE_LIMIT_BYTES:
        remaining = max(0, DROPZONE_RATE_LIMIT_BYTES - ip_used)
        raise ValueError(
            f"Upload limit reached. You have {remaining // (1024*1024)} MB remaining "
            f"in the current {DROPZONE_RATE_WINDOW_HOURS}h window."
        )

    # Global storage: evict if needed
    total_used = dropzone_total_used()
    if total_used + size > DROPZONE_MAX_STORAGE_BYTES:
        needed = (total_used + size) - DROPZONE_MAX_STORAGE_BYTES
        dropzone_evict_oldest(needed)

    # Determine file extension + MIME
    original_name = file_storage.filename or "file"
    ext = os.path.splitext(original_name)[1].lower()
    mime = _mimetypes.guess_type(original_name)[0] or "application/octet-stream"

    # Save file with UUID name
    stored_name = _uuid.uuid4().hex + ext
    path = os.path.join(DROPZONE_DIR, stored_name)
    with open(path, "wb") as f:
        f.write(data)

    password_hash = generate_password_hash(password) if password else None
    now = time.time()

    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO uploads
            (stored_name, original_name, display_name, uploader_ip,
             password_hash, size_bytes, mime_type, timestamp)
        VALUES (?,?,?,?,?,?,?,?)
    """,
        (
            stored_name,
            original_name,
            display_name,
            uploader_ip,
            password_hash,
            size,
            mime,
            now,
        ),
    )
    upload_id = c.lastrowid

    # Save tags (normalise: lowercase, strip, deduplicate)
    clean_tags = list({t.strip().lower() for t in tags if t.strip()})
    for tag in clean_tags:
        c.execute(
            "INSERT INTO upload_tags (upload_id, tag) VALUES (?,?)", (upload_id, tag)
        )

    conn.commit()
    conn.close()

    return {
        "id": upload_id,
        "stored_name": stored_name,
        "original_name": original_name,
        "display_name": display_name,
        "size_bytes": size,
        "mime_type": mime,
        "timestamp": now,
        "tags": clean_tags,
        "protected": bool(password),
    }


def dropzone_search(query: str = "", tag: str = "") -> list[dict]:
    """
    Returns uploads matching `query` (display_name or original_name)
    and/or `tag`. Returns all if both are empty.
    """
    conn = get_db()
    c = conn.cursor()

    if tag:
        c.execute(
            """
            SELECT DISTINCT u.id, u.stored_name, u.original_name, u.display_name,
                   u.uploader_ip, u.password_hash, u.size_bytes, u.mime_type, u.timestamp
            FROM uploads u
            JOIN upload_tags t ON t.upload_id = u.id
            WHERE t.tag = ?
              AND (u.display_name LIKE ? OR u.original_name LIKE ?)
            ORDER BY u.timestamp DESC
        """,
            (tag.lower(), f"%{query}%", f"%{query}%"),
        )
    else:
        c.execute(
            """
            SELECT id, stored_name, original_name, display_name,
                   uploader_ip, password_hash, size_bytes, mime_type, timestamp
            FROM uploads
            WHERE display_name LIKE ? OR original_name LIKE ?
            ORDER BY timestamp DESC
        """,
            (f"%{query}%", f"%{query}%"),
        )

    rows = []
    for row in c.fetchall():
        d = dict(
            zip(
                [
                    "id",
                    "stored_name",
                    "original_name",
                    "display_name",
                    "uploader_ip",
                    "password_hash",
                    "size_bytes",
                    "mime_type",
                    "timestamp",
                ],
                row,
            )
        )
        # Fetch tags for each result
        c2 = conn.cursor()
        c2.execute(
            "SELECT tag FROM upload_tags WHERE upload_id=? ORDER BY tag", (d["id"],)
        )
        d["tags"] = [r[0] for r in c2.fetchall()]
        d["protected"] = bool(d["password_hash"])
        d.pop("password_hash")
        rows.append(d)

    conn.close()
    return rows


def dropzone_get_by_id(upload_id: int) -> dict | None:
    """Returns full upload row including password_hash."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM uploads WHERE id=?", (upload_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    d = dict(row)
    c.execute(
        "SELECT tag FROM upload_tags WHERE upload_id=? ORDER BY tag", (upload_id,)
    )
    d["tags"] = [r[0] for r in c.fetchall()]
    conn.close()
    return d


def dropzone_delete(upload_id: int) -> None:
    """Deletes an upload from disk and DB."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT stored_name FROM uploads WHERE id=?", (upload_id,))
    row = c.fetchone()
    if row:
        path = os.path.join(DROPZONE_DIR, row[0])
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        c.execute("DELETE FROM uploads WHERE id=?", (upload_id,))
        conn.commit()
    conn.close()


def dropzone_tag_suggestions(prefix: str, limit: int = 10) -> list[str]:
    """Returns existing tags starting with `prefix`, ordered by frequency."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        SELECT tag, COUNT(*) as cnt
        FROM upload_tags
        WHERE tag LIKE ?
        GROUP BY tag
        ORDER BY cnt DESC, tag ASC
        LIMIT ?
    """,
        (f"{prefix.lower()}%", limit),
    )
    tags = [r[0] for r in c.fetchall()]
    conn.close()
    return tags


def dropzone_stats() -> dict:
    """Get storage statistics."""
    used = dropzone_total_used()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM uploads")
    count = c.fetchone()[0]
    conn.close()
    return {
        "used_bytes": used,
        "max_bytes": DROPZONE_MAX_STORAGE_BYTES,
        "used_pct": (
            round(used / DROPZONE_MAX_STORAGE_BYTES * 100, 1)
            if DROPZONE_MAX_STORAGE_BYTES
            else 0
        ),
        "file_count": count,
    }
