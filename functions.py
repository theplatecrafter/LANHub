# functions.py
from glob_vars import *

import sqlite3
import time
import psutil
import socket
import subprocess
import platform
from git import Repo
import datetime
import os
from better_profanity import profanity as _profanity_filter
from werkzeug.security import generate_password_hash, check_password_hash
import uuid as _uuid
import mimetypes as _mimetypes
import json as _json_mod



#######################################################
# Profanity Filter
#######################################################
def check_profanity(message: str) -> bool:
    """Returns True if the message contains profanity."""
    return _profanity_filter.contains_profanity(message)


#######################################################
# Database
#######################################################
def get_db():
    """Returns a sqlite3 connection. Caller is responsible for closing it."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts
    return conn


########################################################
# Drop Zone Functions
#########################################
 
DROPZONE_DIR = os.path.join(BASE_DIR, "files", "dropzone")
os.makedirs(DROPZONE_DIR, exist_ok=True)
 
 
# ─── Storage accounting ────────────────────────────────────────────────────────
 
def dropzone_total_used() -> int:
    """Returns total bytes of all stored uploads."""
    conn = get_db()
    c    = conn.cursor()
    c.execute("SELECT COALESCE(SUM(size_bytes),0) FROM uploads")
    total = c.fetchone()[0]
    conn.close()
    return total
 
 
def dropzone_ip_used_in_window(ip: str) -> int:
    """Bytes uploaded by this IP within the rate window."""
    cutoff = time.time() - DROPZONE_RATE_WINDOW_HOURS * 3600
    conn   = get_db()
    c      = conn.cursor()
    c.execute("SELECT COALESCE(SUM(size_bytes),0) FROM uploads WHERE uploader_ip=? AND timestamp>?",
              (ip, cutoff))
    total = c.fetchone()[0]
    conn.close()
    return total
 
 
def dropzone_evict_oldest(needed_bytes: int) -> None:
    """Delete the oldest uploads until `needed_bytes` of space is freed."""
    conn = get_db()
    c    = conn.cursor()
    c.execute("SELECT id, stored_name, size_bytes FROM uploads ORDER BY timestamp ASC")
    rows  = c.fetchall()
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
 
 
# ─── Upload ────────────────────────────────────────────────────────────────────
 
def dropzone_save(file_storage, display_name: str, tags: list[str],
                  uploader_ip: str, password: str | None) -> dict:
    """
    Saves an uploaded file, evicting old files if needed.
    Returns the upload row dict on success, raises ValueError on quota exceeded.
    """
    data  = file_storage.read()
    size  = len(data)
 
    if size > DROPZONE_MAX_FILE_BYTES:
        raise ValueError(f"File too large (max {DROPZONE_MAX_FILE_BYTES // (1024*1024)} MB).")
 
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
    ext  = os.path.splitext(original_name)[1].lower()
    mime = _mimetypes.guess_type(original_name)[0] or "application/octet-stream"
 
    # Save file with UUID name
    stored_name = _uuid.uuid4().hex + ext
    path        = os.path.join(DROPZONE_DIR, stored_name)
    with open(path, "wb") as f:
        f.write(data)
 
    password_hash = generate_password_hash(password) if password else None
    now           = time.time()
 
    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        INSERT INTO uploads
            (stored_name, original_name, display_name, uploader_ip,
             password_hash, size_bytes, mime_type, timestamp)
        VALUES (?,?,?,?,?,?,?,?)
    """, (stored_name, original_name, display_name, uploader_ip,
          password_hash, size, mime, now))
    upload_id = c.lastrowid
 
    # Save tags (normalise: lowercase, strip, deduplicate)
    clean_tags = list({t.strip().lower() for t in tags if t.strip()})
    for tag in clean_tags:
        c.execute("INSERT INTO upload_tags (upload_id, tag) VALUES (?,?)", (upload_id, tag))
 
    conn.commit()
    conn.close()
 
    return {
        "id":            upload_id,
        "stored_name":   stored_name,
        "original_name": original_name,
        "display_name":  display_name,
        "size_bytes":    size,
        "mime_type":     mime,
        "timestamp":     now,
        "tags":          clean_tags,
        "protected":     bool(password),
    }
 
 
# ─── Search ────────────────────────────────────────────────────────────────────
 
def dropzone_search(query: str = "", tag: str = "") -> list[dict]:
    """
    Returns uploads matching `query` (display_name or original_name)
    and/or `tag`. Returns all if both are empty.
    """
    conn = get_db()
    c    = conn.cursor()
 
    if tag:
        c.execute("""
            SELECT DISTINCT u.id, u.stored_name, u.original_name, u.display_name,
                   u.uploader_ip, u.password_hash, u.size_bytes, u.mime_type, u.timestamp
            FROM uploads u
            JOIN upload_tags t ON t.upload_id = u.id
            WHERE t.tag = ?
              AND (u.display_name LIKE ? OR u.original_name LIKE ?)
            ORDER BY u.timestamp DESC
        """, (tag.lower(), f"%{query}%", f"%{query}%"))
    else:
        c.execute("""
            SELECT id, stored_name, original_name, display_name,
                   uploader_ip, password_hash, size_bytes, mime_type, timestamp
            FROM uploads
            WHERE display_name LIKE ? OR original_name LIKE ?
            ORDER BY timestamp DESC
        """, (f"%{query}%", f"%{query}%"))
 
    rows = []
    for row in c.fetchall():
        d = dict(zip(
            ["id","stored_name","original_name","display_name",
             "uploader_ip","password_hash","size_bytes","mime_type","timestamp"],
            row
        ))
        # Fetch tags for each result
        c2 = conn.cursor()
        c2.execute("SELECT tag FROM upload_tags WHERE upload_id=? ORDER BY tag", (d["id"],))
        d["tags"]      = [r[0] for r in c2.fetchall()]
        d["protected"] = bool(d["password_hash"])
        d.pop("password_hash")
        rows.append(d)
 
    conn.close()
    return rows
 
 
def dropzone_get_by_id(upload_id: int) -> dict | None:
    """Returns full upload row including password_hash."""
    conn = get_db()
    c    = conn.cursor()
    c.execute("SELECT * FROM uploads WHERE id=?", (upload_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    d = dict(row)
    c.execute("SELECT tag FROM upload_tags WHERE upload_id=? ORDER BY tag", (upload_id,))
    d["tags"] = [r[0] for r in c.fetchall()]
    conn.close()
    return d
 
 
def dropzone_delete(upload_id: int) -> None:
    """Deletes an upload from disk and DB."""
    conn = get_db()
    c    = conn.cursor()
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
 
 
# ─── Tag autocomplete ──────────────────────────────────────────────────────────
 
def dropzone_tag_suggestions(prefix: str, limit: int = 10) -> list[str]:
    """Returns existing tags starting with `prefix`, ordered by frequency."""
    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        SELECT tag, COUNT(*) as cnt
        FROM upload_tags
        WHERE tag LIKE ?
        GROUP BY tag
        ORDER BY cnt DESC, tag ASC
        LIMIT ?
    """, (f"{prefix.lower()}%", limit))
    tags = [r[0] for r in c.fetchall()]
    conn.close()
    return tags
 
 
# ─── Storage stats ─────────────────────────────────────────────────────────────
 
def dropzone_stats() -> dict:
    used  = dropzone_total_used()
    conn  = get_db()
    c     = conn.cursor()
    c.execute("SELECT COUNT(*) FROM uploads")
    count = c.fetchone()[0]
    conn.close()
    return {
        "used_bytes":  used,
        "max_bytes":   DROPZONE_MAX_STORAGE_BYTES,
        "used_pct":    round(used / DROPZONE_MAX_STORAGE_BYTES * 100, 1) if DROPZONE_MAX_STORAGE_BYTES else 0,
        "file_count":  count,
    }


#########################################################
# IP Ban Helpers
#########################################################
 
def is_ip_banned(ip: str) -> dict | None:
    """Returns the ban row if the IP is currently banned, else None."""
    now  = time.time()
    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        SELECT * FROM ip_bans
        WHERE ip = ?
          AND (expires_at IS NULL OR expires_at > ?)
    """, (ip, now))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None
 
 
def get_all_bans() -> list[dict]:
    conn = get_db()
    c    = conn.cursor()
    c.execute("SELECT * FROM ip_bans ORDER BY banned_at DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows
 
 
def ban_ip(ip: str, reason: str, banned_by: str,
           expires_at: float | None = None) -> tuple[bool, str]:
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO ip_bans (ip, reason, banned_by, banned_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (ip, reason, banned_by, time.time(), expires_at)
        )
        conn.commit()
        conn.close()
        return True, ""
    except Exception as e:
        return False, "IP already banned." if "UNIQUE" in str(e) else str(e)
 
 
def unban_ip(ban_id: int) -> None:
    conn = get_db()
    conn.execute("DELETE FROM ip_bans WHERE id = ?", (ban_id,))
    conn.commit()
    conn.close()
 
 
def update_ban(ban_id: int, reason: str,
               expires_at: float | None) -> None:
    conn = get_db()
    conn.execute(
        "UPDATE ip_bans SET reason = ?, expires_at = ? WHERE id = ?",
        (reason, expires_at, ban_id)
    )
    conn.commit()
    conn.close()
 
 
###########################################################
# Report Helpers
############################################################
 
def create_report(reporter_ip: str, reported_username: str,
                  reported_ip: str, message_id: int | None,
                  message_text: str, reason: str,
                  source: str = "chat") -> int:   # ← add source param
    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        INSERT INTO reports
            (reporter_ip, reported_username, reported_ip,
             message_id, message_text, reason, timestamp, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (reporter_ip, reported_username, reported_ip,
          message_id, message_text, reason, time.time(), source))
    conn.commit()
    rid = c.lastrowid
    conn.close()
    return rid
 
 
def get_reports(status: str | None = None) -> list[dict]:
    conn = get_db()
    c    = conn.cursor()
    if status:
        c.execute("SELECT * FROM reports WHERE status = ? ORDER BY timestamp DESC", (status,))
    else:
        c.execute("SELECT * FROM reports ORDER BY timestamp DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows
 
 
def update_report_status(report_id: int, status: str,
                         reviewed_by: str) -> None:
    conn = get_db()
    conn.execute("""
        UPDATE reports
        SET status = ?, reviewed_by = ?, reviewed_at = ?
        WHERE id = ?
    """, (status, reviewed_by, time.time(), report_id))
    conn.commit()
    conn.close()
 
 
###########################################################
# DB Inspector Helpers
############################################################
 
def db_get_tables() -> list[str]:
    conn = get_db()
    c    = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows
 
 
def db_get_schema(table: str) -> list[dict]:
    conn = get_db()
    c    = conn.cursor()
    c.execute(f"PRAGMA table_info({table})")          # table name is safe — validated caller-side
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows
 
 
def db_query(sql: str) -> tuple[list[str], list[list]]:
    """
    Runs a read-only SQL statement and returns (columns, rows).
    Only SELECT statements are permitted.
    """
    sql_stripped = sql.strip().upper()
    if not sql_stripped.startswith("SELECT"):
        raise ValueError("Only SELECT statements are allowed.")
    conn = get_db()
    conn.row_factory = None   # plain tuples for JSON serialisation
    c = conn.cursor()
    c.execute(sql)
    columns = [d[0] for d in c.description] if c.description else []
    rows    = [list(r) for r in c.fetchmany(500)]   # cap at 500 rows
    conn.close()
    return columns, rows


def db_get_row(table: str, rowid: int) -> tuple[list[str], list] | None:
    """Fetch a single row by rowid. Returns (columns, row) or None."""
    conn = get_db()
    conn.row_factory = None
    c = conn.cursor()
    try:
        c.execute(f"SELECT rowid, * FROM {table} WHERE rowid = ?", (rowid,))
        row = c.fetchone()
        if not row:
            conn.close()
            return None
        cols = [d[0] for d in c.description]
        conn.close()
        return cols, list(row)
    except Exception as e:
        conn.close()
        raise ValueError(f"Cannot fetch row: {e}")
 
 
def db_insert(table: str, data: dict) -> int:
    """
    Insert a row. data = {col: value, ...} (do NOT include rowid).
    Returns the new rowid.
    """
    if not data:
        raise ValueError("No column data provided.")
    cols   = list(data.keys())
    vals   = [data[c] for c in cols]
    ph     = ", ".join("?" * len(cols))
    col_str = ", ".join(cols)
    conn   = get_db()
    try:
        c = conn.cursor()
        c.execute(f"INSERT INTO {table} ({col_str}) VALUES ({ph})", vals)
        conn.commit()
        new_id = c.lastrowid
        conn.close()
        return new_id
    except Exception as e:
        conn.close()
        raise ValueError(f"Insert failed: {e}")
 
 
def db_update_row(table: str, rowid: int, data: dict) -> None:
    """
    Update a row by rowid. data = {col: value, ...} for columns to change.
    Skips the rowid column itself if present in data.
    """
    data = {k: v for k, v in data.items() if k.lower() != "rowid"}
    if not data:
        raise ValueError("No columns to update.")
    set_clause = ", ".join(f"{col} = ?" for col in data)
    vals       = list(data.values()) + [rowid]
    conn       = get_db()
    try:
        conn.execute(f"UPDATE {table} SET {set_clause} WHERE rowid = ?", vals)
        conn.commit()
        conn.close()
    except Exception as e:
        conn.close()
        raise ValueError(f"Update failed: {e}")
 
 
def db_delete_row(table: str, rowid: int) -> None:
    """Delete a row by rowid."""
    conn = get_db()
    try:
        conn.execute(f"DELETE FROM {table} WHERE rowid = ?", (rowid,))
        conn.commit()
        conn.close()
    except Exception as e:
        conn.close()
        raise ValueError(f"Delete failed: {e}")


##############################################
# Admin Account Management
##############################################
 
def get_admin_by_username(username: str) -> dict | None:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM admins WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None
 
 
def get_admin_by_id(admin_id: int) -> dict | None:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM admins WHERE id = ?", (admin_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None
 
 
def get_all_admins() -> list[dict]:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, username, role FROM admins ORDER BY role DESC, username")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows
 
 
def create_admin(username: str, password: str, role: str) -> tuple[bool, str]:
    """Returns (True, '') on success or (False, error_message) on failure."""
    if not username or not password:
        return False, "Username and password are required."
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO admins (username, password_hash, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), role)
        )
        conn.commit()
        conn.close()
        return True, ""
    except Exception as e:
        return False, "Username already exists." if "UNIQUE" in str(e) else str(e)
 
 
def edit_admin(admin_id: int,
               new_username: str | None,
               new_password: str | None,
               new_role: str | None) -> tuple[bool, str]:
    conn = get_db()
    c = conn.cursor()
    try:
        if new_username:
            c.execute("UPDATE admins SET username = ? WHERE id = ?", (new_username, admin_id))
        if new_password:
            c.execute("UPDATE admins SET password_hash = ? WHERE id = ?",
                      (generate_password_hash(new_password), admin_id))
        if new_role:
            c.execute("UPDATE admins SET role = ? WHERE id = ?", (new_role, admin_id))
        conn.commit()
        return True, ""
    except Exception as e:
        return False, "Username already exists." if "UNIQUE" in str(e) else str(e)
    finally:
        conn.close()
 
 
def delete_admin(admin_id: int) -> None:
    conn = get_db()
    conn.execute("DELETE FROM admins WHERE id = ?", (admin_id,))
    conn.commit()
    conn.close()



#######################################################
# Chat Helpers
#######################################################
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
 
 
def save_chat_message(username: str, ip: str, message: str,
                      reply_to_id: int | None = None,
                      msg_type: str = "text") -> dict:
    """Inserts a message and returns it as a dict (including reply info if any)."""
    now = time.time()
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO chat_messages (username, ip, message, timestamp, reply_to_id, msg_type) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (username, ip, message, now, reply_to_id, msg_type)
    )
    conn.commit()
    row_id = c.lastrowid
 
    # Fetch reply info so the broadcast payload is complete
    reply_username = None
    reply_message  = None
    if reply_to_id:
        c.execute("SELECT username, message FROM chat_messages WHERE id = ?", (reply_to_id,))
        row = c.fetchone()
        if row:
            reply_username = row["username"]
            reply_message  = row["message"]
 
    conn.close()
    return {
        "id":             row_id,
        "username":       username,
        "message":        message,
        "timestamp":      now,
        "edited":         False,
        "reply_to_id":    reply_to_id,
        "reply_username": reply_username,
        "reply_message":  reply_message,
        "msg_type": msg_type,
    }
 
 
def get_recent_messages(limit: int) -> list[dict]:
    """Returns the most recent `limit` messages (oldest first), with reply info joined."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT
            m.id, m.username, m.message, m.timestamp, m.edited,
            m.reply_to_id, m.msg_type,
            r.username AS reply_username, r.message AS reply_message
        FROM chat_messages m
        LEFT JOIN chat_messages r ON m.reply_to_id = r.id
        ORDER BY m.id DESC LIMIT ?
    """, (limit,))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    rows.reverse()   # oldest → newest
    return rows
 
 
def edit_message(msg_id: int, new_text: str) -> None:
    """Updates message text and marks it as edited."""
    conn = get_db()
    conn.execute(
        "UPDATE chat_messages SET message = ?, edited = 1 WHERE id = ?",
        (new_text, msg_id)
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
    c.execute("""
        SELECT
            m.id, m.username, m.message, m.timestamp, m.edited,
            m.reply_to_id, m.msg_type,
            r.username AS reply_username, r.message AS reply_message
        FROM chat_messages m
        LEFT JOIN chat_messages r ON m.reply_to_id = r.id
        ORDER BY m.id DESC LIMIT ?
    """, (limit,))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    rows.reverse()   # oldest → newest
    return rows




#######################################################
# Github Static Redirector Page Functions
#######################################################

HTML_FILENAME = "index.html"

def redirector_update(ip,port=PORT):
    try:
        repo = Repo(REDIRECTOR_PATH)
        
        repo.remotes.origin.fetch()
        repo.git.reset('--hard', 'origin/main')
        repo.git.clean('-fd')
        
        # Using an f-string (note the f before the triple quotes)
        # Also, we use {{ }} for CSS brackets so Python doesn't get confused
        new_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LANHub Redirector</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; text-align: center; padding: 50px; background-color: #f4f4f9; color: #333; }}
        .card {{ max-width: 500px; margin: auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }}
        .error-box {{ display: none; color: #721c24; background-color: #f8d7da; border: 1px solid #f5c6cb; padding: 15px; border-radius: 8px; margin-top: 20px; }}
        .loading-spinner {{ border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; width: 30px; height: 30px; animation: spin 1s linear infinite; margin: 20px auto; }}
        @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
        a {{ color: #3498db; text-decoration: none; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>🛰️ LANHub Gateway</h2>
        
        <div id="checking">
            <p>Verifying connection to <b>{ip}</b>...</p>
            <div class="loading-spinner"></div>
        </div>

        <div id="error-msg" class="error-box">
            <h3>🚫 Connection Failed</h3>
            <p>You must be connected to the <b>same LAN (or Wi-Fi)</b> as the server to access this page.</p>
            <p>Current Target: <a href="http://{ip}:{port}">http://{ip}:{port}</a></p>
        </div>

        <p style="font-size: 0.9em; color: #666; margin-top: 20px;">
            If you aren't redirected in 5 seconds, you are likely on the wrong network or the server is offline.
        </p>
    </div>

    <script>
        const targetUrl = "http://{ip}:{port}";

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 4000);

        fetch(targetUrl + "/static/pixel.png", {{ mode: 'no-cors', signal: controller.signal }})
            .then(() => {{
                window.location.replace(targetUrl);
            }})
            .catch((err) => {{
                document.getElementById("checking").style.display = "none";
                document.getElementById("error-msg").style.display = "block";
                console.log("Connection failed: ", err);
            }});
    </script>
</body>
</html>"""

        file_path = os.path.join(REDIRECTOR_PATH, HTML_FILENAME)
        with open(file_path, "w") as f:
            f.write(new_html)

        repo.index.add([HTML_FILENAME])
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        repo.index.commit(f"Update redirect to {ip}:{port} at {timestamp}")
        
        origin = repo.remote(name='origin')
        origin.push(force=True) # Added force=True just in case history diverges again

        git_log.info(f"Successfully updated GitHub redirect to http://{ip}:{port}")
        return True

    except Exception as e:
        git_log.error(f"Failed to update GitHub: {e}")
        return False
    
########################################################
# Stats Functions
########################################################
def get_server_stats():
    return {
        "cpu": psutil.cpu_percent(),
        "ram": psutil.virtual_memory().percent
    }

def get_wifi_ssid():
    """Returns the name of the connected Wi-Fi network."""
    try: # dev purpose (for wsl)
        # We call netsh.exe (the Windows version) from inside WSL
        # we use 'powershell.exe' to make parsing easier
        cmd = ["powershell.exe", "-Command", "(Get-NetConnectionProfile | Where-Object {$_.InterfaceAlias -like '*Wi-Fi*'}).Name"]
        ssid = subprocess.check_output(cmd).decode("utf-8").strip()
        
        return ssid if ssid else "Ethernet/No Wi-Fi"
    except Exception:
        pass
    
    os_name = platform.system()
    try:
        if os_name == "Windows":
            results = subprocess.check_output(["netsh", "wlan", "show", "interfaces"]).decode("utf-8")
            for line in results.split("\n"):
                if "SSID" in line and "BSSID" not in line:
                    return line.split(":")[1].strip()
        elif os_name == "Darwin":  # macOS
            results = subprocess.check_output(["/System/Library/PrivateFrameworks/Apple80211.framework/Resources/airport", "-I"]).decode("utf-8")
            for line in results.split("\n"):
                if " SSID" in line:
                    return line.split(":")[1].strip()
        elif os_name == "Linux":
            return subprocess.check_output(["iwgetid", "-r"]).decode("utf-8").strip()
    except:
        return "Unknown/Wired"
    return "Not Connected"

def get_network_stats(flask_port=5000):
    # 1. Get the IP address used for the internet (skips loopback 'lo')
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't actually connect, just probes the routing table
        s.connect(('8.8.8.8', 80))
        ip_address = s.getsockname()[0]
    except Exception:
        ip_address = "127.0.0.1"
    finally:
        s.close()

    net_io = psutil.net_io_counters()
    public_ip = get_public_ip()

    return {
        "ssid": get_wifi_ssid(),
        "ip_address": ip_address,
        "public_ip":  public_ip,
        "flask_url": f"http://{ip_address}:{flask_port}",
        "bytes_sent": net_io.bytes_sent,
        "bytes_recv": net_io.bytes_recv
    }

def get_public_ip() -> str:
    """Fetches the server's public-facing IP via external lookup services."""
    import urllib.request as _ureq
    for url in [
        "https://api.ipify.org",
        "https://checkip.amazonaws.com",
        "https://icanhazip.com",
    ]:
        try:
            with _ureq.urlopen(url, timeout=5) as r:
                return r.read().decode().strip()
        except Exception:
            continue
    return ""

# Module-level: store last net reading for speed calculation
_last_net_io = None
_last_net_time = None
 
# App start time for uptime calculation
_app_start_time = time.time()
 
 
def get_disk_stats() -> dict:
    """Returns disk usage for the root filesystem."""
    usage = psutil.disk_usage('/')
    return {
        "total_gb":   round(usage.total  / (1024**3), 1),
        "used_gb":    round(usage.used   / (1024**3), 1),
        "free_gb":    round(usage.free   / (1024**3), 1),
        "percent":    usage.percent,
    }
 
 
def get_network_speed() -> dict:
    """Returns upload/download speed in KB/s by diffing two psutil readings."""
    global _last_net_io, _last_net_time
 
    now     = time.time()
    current = psutil.net_io_counters()
 
    if _last_net_io is None or _last_net_time is None:
        _last_net_io   = current
        _last_net_time = now
        return {"upload_kbps": 0.0, "download_kbps": 0.0,
                "bytes_sent": current.bytes_sent, "bytes_recv": current.bytes_recv}
 
    elapsed = now - _last_net_time
    if elapsed <= 0:
        elapsed = 0.001
 
    upload_kbps   = round((current.bytes_sent - _last_net_io.bytes_sent) / elapsed / 1024, 1)
    download_kbps = round((current.bytes_recv - _last_net_io.bytes_recv) / elapsed / 1024, 1)
 
    _last_net_io   = current
    _last_net_time = now
 
    return {
        "upload_kbps":   max(0.0, upload_kbps),
        "download_kbps": max(0.0, download_kbps),
        "bytes_sent":    current.bytes_sent,
        "bytes_recv":    current.bytes_recv,
    }
 
 
def get_gpu_stats() -> dict | None:
    """
    Returns GPU usage if a compatible GPU is found.
    Returns None silently if GPUtil is missing or broken.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode != 0:
            return None
        parts = [p.strip() for p in result.stdout.strip().split(",")]
        if len(parts) < 5:
            return None
        mem_used  = float(parts[2])
        mem_total = float(parts[3])
        return {
            "name":         parts[0],
            "load":         float(parts[1]),
            "mem_used_mb":  mem_used,
            "mem_total_mb": mem_total,
            "mem_percent":  round(mem_used / mem_total * 100, 1) if mem_total else 0,
            "temp":         float(parts[4]),
        }
    except Exception:
        return None
 
 
def get_uptime_seconds() -> int:
    """Seconds since the LANHub process started."""
    return int(time.time() - _app_start_time)
 
 
def get_cpu_temp() -> float | None:
    """Returns CPU temperature in °C on supported Linux systems."""
    try:
        temps = psutil.sensors_temperatures()
        for key in ("coretemp", "cpu_thermal", "k10temp", "acpitz"):
            if key in temps and temps[key]:
                return round(temps[key][0].current, 1)
    except Exception:
        pass
    return None
 
 
def get_full_server_stats(route_counts: dict, total_connections: int) -> dict:
    """
    Assembles the full stats payload emitted to /stats clients.
    Call this from the scheduler.
    """
    net_stats  = get_network_stats()   # existing function (ip, ssid, etc.)
    net_speed  = get_network_speed()
    disk       = get_disk_stats()
    gpu        = get_gpu_stats()
    cpu_temp   = get_cpu_temp()
    uptime     = get_uptime_seconds()
 
    mem = psutil.virtual_memory()
    cpu_per_core = psutil.cpu_percent(percpu=True)
 
    return {
        # CPU
        "cpu":            psutil.cpu_percent(),
        "cpu_per_core":   cpu_per_core,
        "cpu_count":      len(cpu_per_core),
        "cpu_temp":       cpu_temp,
 
        # RAM
        "ram":            mem.percent,
        "ram_used_gb":    round(mem.used   / (1024**3), 2),
        "ram_total_gb":   round(mem.total  / (1024**3), 2),
        "ram_avail_gb":   round(mem.available / (1024**3), 2),
 
        # Disk
        "disk":           disk,
 
        # GPU (None if unavailable)
        "gpu":            gpu,
 
        # Network identity
        "ssid":           net_stats["ssid"],
        "ip":             net_stats["ip_address"],
 
        # Network speed
        "upload_kbps":    net_speed["upload_kbps"],
        "download_kbps":  net_speed["download_kbps"],
        "bytes_sent":     net_speed["bytes_sent"],
        "bytes_recv":     net_speed["bytes_recv"],
 
        # Connections
        "total_connections": total_connections,
        "route_counts":      route_counts,
 
        # System
        "uptime":         uptime,
        "platform":       platform.system() + " " + platform.release(),
    }
    

#######################################################
# Channel Helpers
####################################################### 
def create_channel(title: str, description: str, tags: list[str],
                   password: str, ip: str) -> dict:
    now  = time.time()
    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        INSERT INTO channels (title, description, password_hash, created_by_ip, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (title, description, generate_password_hash(password), ip, now))
    cid = c.lastrowid
 
    clean_tags = list({t.strip().lower() for t in tags if t.strip()})
    for tag in clean_tags:
        c.execute("INSERT INTO channel_tags (channel_id, tag) VALUES (?,?)", (cid, tag))
 
    conn.commit()
    conn.close()
 
    return {
        "id":          cid,
        "title":       title,
        "description": description,
        "tags":        clean_tags,
        "created_at":  now,
    }
 
 
def get_channel_by_id(channel_id: int) -> dict | None:
    conn = get_db()
    c    = conn.cursor()
    c.execute("SELECT * FROM channels WHERE id = ?", (channel_id,))
    row  = c.fetchone()
    if not row:
        conn.close()
        return None
    d = dict(row)
    c.execute("SELECT tag FROM channel_tags WHERE channel_id = ? ORDER BY tag", (channel_id,))
    d["tags"] = [r[0] for r in c.fetchall()]
    conn.close()
    return d
 
 
def search_channels(query: str = "", tag: str = "") -> list[dict]:
    conn = get_db()
    c    = conn.cursor()
    like = f"%{query}%"
 
    if tag:
        c.execute("""
            SELECT DISTINCT ch.id, ch.title, ch.description, ch.created_at
            FROM channels ch
            JOIN channel_tags ct ON ct.channel_id = ch.id
            WHERE ct.tag = ?
              AND (ch.title LIKE ? OR ch.description LIKE ? OR CAST(ch.id AS TEXT) = ?)
            ORDER BY ch.created_at DESC
        """, (tag.lower(), like, like, query))
    else:
        c.execute("""
            SELECT id, title, description, created_at
            FROM channels
            WHERE title LIKE ? OR description LIKE ? OR CAST(id AS TEXT) = ?
            ORDER BY created_at DESC
        """, (like, like, query))
 
    rows = []
    for row in c.fetchall():
        d = {"id": row[0], "title": row[1], "description": row[2], "created_at": row[3]}
        c2 = conn.cursor()
        c2.execute("SELECT tag FROM channel_tags WHERE channel_id = ? ORDER BY tag", (d["id"],))
        d["tags"] = [r[0] for r in c2.fetchall()]
        rows.append(d)
 
    conn.close()
    return rows
 
 
def channel_tag_suggestions(prefix: str, limit: int = 10) -> list[str]:
    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        SELECT tag, COUNT(*) as cnt
        FROM channel_tags
        WHERE tag LIKE ?
        GROUP BY tag ORDER BY cnt DESC, tag ASC LIMIT ?
    """, (f"{prefix.lower()}%", limit))
    tags = [r[0] for r in c.fetchall()]
    conn.close()
    return tags
 
 
def edit_channel(channel_id: int, title: str | None, description: str | None,
                 tags: list[str] | None) -> None:
    conn = get_db()
    c    = conn.cursor()
    if title is not None:
        c.execute("UPDATE channels SET title = ? WHERE id = ?", (title, channel_id))
    if description is not None:
        c.execute("UPDATE channels SET description = ? WHERE id = ?", (description, channel_id))
    if tags is not None:
        c.execute("DELETE FROM channel_tags WHERE channel_id = ?", (channel_id,))
        clean = list({t.strip().lower() for t in tags if t.strip()})
        for tag in clean:
            c.execute("INSERT INTO channel_tags (channel_id, tag) VALUES (?,?)", (channel_id, tag))
    conn.commit()
    conn.close()
 
 
def delete_channel(channel_id: int) -> None:
    conn = get_db()
    conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
    conn.commit()
    conn.close()
 
 
def verify_channel_password(channel_id: int, password: str) -> bool:
    ch = get_channel_by_id(channel_id)
    if not ch:
        return False
    return check_password_hash(ch["password_hash"], password)
 
 
# ── Channel message helpers ────────────────────────────────────────────────────
 
def save_channel_message(channel_id: int, username: str, ip: str,
                         message: str, reply_to_id: int | None = None,
                         msg_type: str = "text") -> dict:
    now  = time.time()
    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        INSERT INTO channel_messages
            (channel_id, username, ip, message, timestamp, reply_to_id, msg_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (channel_id, username, ip, message, now, reply_to_id, msg_type))
    conn.commit()
    mid = c.lastrowid
 
    reply_username = reply_message = None
    if reply_to_id:
        c.execute("SELECT username, message FROM channel_messages WHERE id = ?", (reply_to_id,))
        row = c.fetchone()
        if row:
            reply_username, reply_message = row[0], row[1]
 
    conn.close()
    return {
        "id":             mid,
        "channel_id":     channel_id,
        "username":       username,
        "message":        message,
        "timestamp":      now,
        "edited":         False,
        "reply_to_id":    reply_to_id,
        "reply_username": reply_username,
        "reply_message":  reply_message,
        "msg_type": msg_type,
    }
 
 
def get_channel_messages(channel_id: int, limit: int) -> list[dict]:
    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        SELECT m.id, m.username, m.message, m.timestamp, m.edited, m.msg_type,
               m.reply_to_id, r.username AS reply_username, r.message AS reply_message
        FROM channel_messages m
        LEFT JOIN channel_messages r ON m.reply_to_id = r.id
        WHERE m.channel_id = ?
        ORDER BY m.id DESC LIMIT ?
    """, (channel_id, limit))
    rows = [dict(zip(
        ["id","username","message","timestamp","edited","msg_type",
         "reply_to_id","reply_username","reply_message"],
        row
    )) for row in c.fetchall()]
    conn.close()
    rows.reverse()
    return rows
 
 
def get_channel_messages_before(channel_id: int, before_id: int, limit: int) -> list[dict]:
    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        SELECT m.id, m.username, m.message, m.timestamp, m.edited, m.msg_type,
               m.reply_to_id, r.username AS reply_username, r.message AS reply_message
        FROM channel_messages m
        LEFT JOIN channel_messages r ON m.reply_to_id = r.id
        WHERE m.channel_id = ? AND m.id < ?
        ORDER BY m.id DESC LIMIT ?
    """, (channel_id, before_id, limit))
    rows = [dict(zip(
        ["id","username","message","timestamp","edited","msg_type",
         "reply_to_id","reply_username","reply_message"],
        row
    )) for row in c.fetchall()]
    conn.close()
    rows.reverse()
    return rows
 
 
def edit_channel_message(msg_id: int, new_text: str) -> None:
    conn = get_db()
    conn.execute(
        "UPDATE channel_messages SET message = ?, edited = 1 WHERE id = ?",
        (new_text, msg_id)
    )
    conn.commit()
    conn.close()
 
 
def delete_channel_message(msg_id: int) -> None:
    conn = get_db()
    conn.execute("DELETE FROM channel_messages WHERE id = ?", (msg_id,))
    conn.commit()
    conn.close()
 
 
def get_channel_online_count(channel_id: int, sessions: dict) -> int:
    """Count how many sids are currently in a given channel."""
    return sum(
        1 for info in sessions.values()
        if channel_id in info.get("channels", set())
    )
 
 
 #######################################################
# Feedback Helpers
#######################################################

def feedback_create(type_: str, title: str, description: str,
                    username: str, ip: str, tags: list[str]) -> dict:
    now  = time.time()
    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        INSERT INTO feedback (type, title, description, username, ip, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (type_, title, description, username, ip, now))
    fid = c.lastrowid
    clean = list({t.strip().lower() for t in tags if t.strip()})
    for tag in clean:
        c.execute("INSERT INTO feedback_tags (feedback_id, tag) VALUES (?,?)", (fid, tag))
    conn.commit()
    conn.close()
    return feedback_get_by_id(fid, ip)


def _feedback_attach(rows: list[dict], viewer_ip: str) -> list[dict]:
    """Attach tags, star count, and viewer_starred to a list of feedback dicts."""
    if not rows:
        return rows
    conn = get_db()
    c    = conn.cursor()
    ids  = [r["id"] for r in rows]
    placeholders = ",".join("?" * len(ids))

    c.execute(f"SELECT feedback_id, tag FROM feedback_tags WHERE feedback_id IN ({placeholders})", ids)
    tag_map: dict[int, list] = {}
    for fb_id, tag in c.fetchall():
        tag_map.setdefault(fb_id, []).append(tag)

    c.execute(f"SELECT feedback_id, COUNT(*) FROM feedback_stars WHERE feedback_id IN ({placeholders}) GROUP BY feedback_id", ids)
    star_map = {fb_id: cnt for fb_id, cnt in c.fetchall()}

    c.execute(f"SELECT feedback_id FROM feedback_stars WHERE feedback_id IN ({placeholders}) AND ip = ?", ids + [viewer_ip])
    viewer_starred = {row[0] for row in c.fetchall()}

    c.execute(f"SELECT feedback_id, COUNT(*) FROM feedback_replies WHERE feedback_id IN ({placeholders}) GROUP BY feedback_id", ids)
    reply_map = {fb_id: cnt for fb_id, cnt in c.fetchall()}

    conn.close()
    for r in rows:
        r["tags"]           = tag_map.get(r["id"], [])
        r["stars"]          = star_map.get(r["id"], 0)
        r["viewer_starred"] = r["id"] in viewer_starred
        r["reply_count"]    = reply_map.get(r["id"], 0)
    return rows


def feedback_search(query: str = "", type_: str = "",
                    tag: str = "", viewer_ip: str = "") -> list[dict]:
    """Returns open first (by stars desc), then resolved (by stars desc)."""
    conn = get_db()
    c    = conn.cursor()
    clauses = []
    params  = []
    if query:
        clauses.append("(f.title LIKE ? OR f.description LIKE ? OR f.username LIKE ?)")
        params += [f"%{query}%", f"%{query}%", f"%{query}%"]
    if type_:
        clauses.append("f.type = ?")
        params.append(type_)
    if tag:
        clauses.append("EXISTS (SELECT 1 FROM feedback_tags ft WHERE ft.feedback_id=f.id AND ft.tag=?)")
        params.append(tag.lower())
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    c.execute(f"""
        SELECT f.*,
               (SELECT COUNT(*) FROM feedback_stars s WHERE s.feedback_id=f.id) AS stars
        FROM feedback f
        {where}
        ORDER BY
            CASE f.status WHEN 'open' THEN 0 ELSE 1 END ASC,
            stars DESC,
            f.timestamp DESC
    """, params)
    cols = [d[0] for d in c.description]
    rows = [dict(zip(cols, row)) for row in c.fetchall()]
    conn.close()
    return _feedback_attach(rows, viewer_ip)


def feedback_get_by_id(fb_id: int, viewer_ip: str = "") -> dict | None:
    conn = get_db()
    c    = conn.cursor()
    c.execute("SELECT * FROM feedback WHERE id=?", (fb_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return _feedback_attach([dict(row)], viewer_ip)[0]


def feedback_toggle_star(fb_id: int, ip: str) -> dict:
    """Toggles star; returns {starred: bool, stars: int}."""
    conn = get_db()
    c    = conn.cursor()
    c.execute("SELECT id FROM feedback_stars WHERE feedback_id=? AND ip=?", (fb_id, ip))
    existing = c.fetchone()
    if existing:
        c.execute("DELETE FROM feedback_stars WHERE feedback_id=? AND ip=?", (fb_id, ip))
        starred = False
    else:
        c.execute("INSERT INTO feedback_stars (feedback_id, ip, timestamp) VALUES (?,?,?)",
                  (fb_id, ip, time.time()))
        starred = True
    conn.commit()
    c.execute("SELECT COUNT(*) FROM feedback_stars WHERE feedback_id=?", (fb_id,))
    stars = c.fetchone()[0]
    conn.close()
    return {"starred": starred, "stars": stars}


def feedback_add_reply(fb_id: int, username: str, ip: str,
                       content: str, is_dev: bool) -> dict:
    now  = time.time()
    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        INSERT INTO feedback_replies (feedback_id, username, ip, content, is_dev, timestamp)
        VALUES (?,?,?,?,?,?)
    """, (fb_id, username, ip, content, int(is_dev), now))
    rid = c.lastrowid
    conn.commit()
    conn.close()
    return {"id": rid, "feedback_id": fb_id, "username": username,
            "content": content, "is_dev": is_dev, "timestamp": now}


def feedback_get_replies(fb_id: int) -> list[dict]:
    conn = get_db()
    c    = conn.cursor()
    c.execute("SELECT * FROM feedback_replies WHERE feedback_id=? ORDER BY timestamp ASC", (fb_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def feedback_resolve(fb_id: int, resolved_by: str, note: str) -> None:
    conn = get_db()
    conn.execute("""
        UPDATE feedback SET status='resolved', resolved_by=?, resolved_at=?, resolved_note=?
        WHERE id=?
    """, (resolved_by, time.time(), note, fb_id))
    conn.commit()
    conn.close()


def feedback_tag_suggestions(prefix: str, limit: int = 8) -> list[str]:
    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        SELECT tag, COUNT(*) cnt FROM feedback_tags
        WHERE tag LIKE ? GROUP BY tag ORDER BY cnt DESC, tag ASC LIMIT ?
    """, (f"{prefix.lower()}%", limit))
    tags = [r[0] for r in c.fetchall()]
    conn.close()
    return tags

#######################################################
# Poll Helpers
#######################################################

def poll_create(title: str, description: str, poll_type: str,
                options: list[str], tags: list[str],
                ip: str, is_dev: bool, created_by: str) -> dict:
    now  = time.time()
    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        INSERT INTO polls (title, description, poll_type, is_dev, created_by, ip, timestamp)
        VALUES (?,?,?,?,?,?,?)
    """, (title, description, poll_type, int(is_dev), created_by, ip, now))
    pid = c.lastrowid

    for i, label in enumerate(options):
        c.execute("INSERT INTO poll_options (poll_id, label, position) VALUES (?,?,?)",
                  (pid, label.strip(), i))

    clean = list({t.strip().lower() for t in tags if t.strip()})
    for tag in clean:
        c.execute("INSERT INTO poll_tags (poll_id, tag) VALUES (?,?)", (pid, tag))

    conn.commit()
    conn.close()
    return poll_get_by_id(pid, ip)


def _poll_attach(rows: list[dict], viewer_ip: str) -> list[dict]:
    if not rows:
        return rows
    conn = get_db()
    c    = conn.cursor()
    ids  = [r["id"] for r in rows]
    ph   = ",".join("?" * len(ids))

    # Options
    c.execute(f"SELECT id, poll_id, label, position FROM poll_options WHERE poll_id IN ({ph}) ORDER BY position", ids)
    opts_map: dict[int, list] = {}
    for oid, pid, label, pos in c.fetchall():
        opts_map.setdefault(pid, []).append({"id": oid, "label": label, "position": pos})

    # Vote counts per option
    c.execute(f"SELECT option_id, COUNT(*) FROM poll_votes WHERE poll_id IN ({ph}) GROUP BY option_id", ids)
    vote_map = {oid: cnt for oid, cnt in c.fetchall()}

    # Total votes per poll
    c.execute(f"SELECT poll_id, COUNT(DISTINCT ip) FROM poll_votes WHERE poll_id IN ({ph}) GROUP BY poll_id", ids)
    total_map = {pid: cnt for pid, cnt in c.fetchall()}

    # What did viewer vote on each poll?
    c.execute(f"SELECT poll_id, option_id FROM poll_votes WHERE poll_id IN ({ph}) AND ip=?", ids + [viewer_ip])
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
        pid   = r["id"]
        opts  = opts_map.get(pid, [])
        voted = viewer_votes.get(pid, set())
        total = total_map.get(pid, 0)
        for o in opts:
            o["votes"]          = vote_map.get(o["id"], 0)
            o["viewer_voted"]   = o["id"] in voted
            o["pct"]            = round(o["votes"] / total * 100) if total else 0
        r["options"]        = opts
        r["total_votes"]    = total
        r["viewer_voted"]   = bool(voted)
        r["tags"]           = tag_map.get(pid, [])
    return rows


def poll_search(query: str = "", tag: str = "", viewer_ip: str = "") -> list[dict]:
    conn = get_db()
    c    = conn.cursor()
    clauses, params = [], []
    if query:
        clauses.append("(p.title LIKE ? OR p.description LIKE ?)")
        params += [f"%{query}%", f"%{query}%"]
    if tag:
        clauses.append("EXISTS (SELECT 1 FROM poll_tags pt WHERE pt.poll_id=p.id AND pt.tag=?)")
        params.append(tag.lower())
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    c.execute(f"""
        SELECT p.*,
               (SELECT COUNT(DISTINCT ip) FROM poll_votes v WHERE v.poll_id=p.id) AS total_votes
        FROM polls p
        {where}
        ORDER BY
            p.is_dev DESC,
            total_votes DESC,
            p.timestamp DESC
    """, params)
    cols = [d[0] for d in c.description]
    rows = [dict(zip(cols, row)) for row in c.fetchall()]
    conn.close()
    return _poll_attach(rows, viewer_ip)


def poll_get_by_id(poll_id: int, viewer_ip: str = "") -> dict | None:
    conn = get_db()
    c    = conn.cursor()
    c.execute("SELECT * FROM polls WHERE id=?", (poll_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return _poll_attach([dict(row)], viewer_ip)[0]


def poll_vote(poll_id: int, option_ids: list[int], ip: str) -> dict:
    """
    Casts votes. For single-choice polls, clears previous vote first.
    Returns updated poll dict.
    """
    conn = get_db()
    c    = conn.cursor()

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
            c.execute("INSERT INTO poll_votes (poll_id, option_id, ip, timestamp) VALUES (?,?,?,?)",
                      (poll_id, oid, ip, now))
        except Exception:
            pass  # UNIQUE violation — skip

    conn.commit()
    conn.close()
    return poll_get_by_id(poll_id, ip)


def poll_tag_suggestions(prefix: str, limit: int = 8) -> list[str]:
    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        SELECT tag, COUNT(*) cnt FROM poll_tags
        WHERE tag LIKE ? GROUP BY tag ORDER BY cnt DESC, tag ASC LIMIT ?
    """, (f"{prefix.lower()}%", limit))
    tags = [r[0] for r in c.fetchall()]
    conn.close()
    return tags


def poll_delete(poll_id: int) -> None:
    conn = get_db()
    conn.execute("DELETE FROM polls WHERE id=?", (poll_id,))
    conn.commit()
    conn.close()
    
    
#######################################################
# Updates Helpers
#######################################################

def updates_get_all() -> list[dict]:
    conn = get_db()
    c    = conn.cursor()
    c.execute("SELECT * FROM updates ORDER BY timestamp DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def updates_get_by_id(update_id: int) -> dict | None:
    conn = get_db()
    c    = conn.cursor()
    c.execute("SELECT * FROM updates WHERE id=?", (update_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def updates_create(version: str, title: str, description: str, created_by: str) -> dict:
    now  = time.time()
    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        INSERT INTO updates (version, title, description, created_by, timestamp)
        VALUES (?,?,?,?,?)
    """, (version, title, description, created_by, now))
    uid = c.lastrowid
    conn.commit()
    conn.close()
    return updates_get_by_id(uid)


def updates_edit(update_id: int, version: str, title: str, description: str) -> None:
    conn = get_db()
    conn.execute("""
        UPDATE updates SET version=?, title=?, description=? WHERE id=?
    """, (version, title, description, update_id))
    conn.commit()
    conn.close()


def updates_delete(update_id: int) -> None:
    conn = get_db()
    conn.execute("DELETE FROM updates WHERE id=?", (update_id,))
    conn.commit()
    conn.close()
    


def geo_preset_create(title: str, username: str, polygons: list) -> dict:
    """
    Saves a new preset.
    polygons: List[List[List[float]]] — array of polygons, each polygon = [[lat,lng], ...]
    """
    now  = time.time()
    conn = get_db()
    c    = conn.cursor()
    c.execute(
        "INSERT INTO geo_presets (title, username, region, created_at) VALUES (?,?,?,?)",
        (title, username, _json_mod.dumps(polygons), now)
    )
    pid = c.lastrowid
    conn.commit()
    conn.close()
    return {"id": pid, "title": title, "username": username, "created_at": now}
 
 
def geo_preset_search(query: str = "", limit: int = 40) -> list[dict]:
    """Returns presets matching query (title search), newest first."""
    conn = get_db()
    c    = conn.cursor()
    if query:
        c.execute(
            "SELECT id, title, username, created_at FROM geo_presets "
            "WHERE title LIKE ? ORDER BY created_at DESC LIMIT ?",
            (f"%{query}%", limit)
        )
    else:
        c.execute(
            "SELECT id, title, username, created_at FROM geo_presets "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
    rows = [
        {"id": r[0], "title": r[1], "username": r[2], "created_at": r[3]}
        for r in c.fetchall()
    ]
    conn.close()
    return rows
 
 
def geo_preset_get_by_id(preset_id: int) -> dict | None:
    """Returns full preset including region polygon data."""
    conn = get_db()
    c    = conn.cursor()
    c.execute(
        "SELECT id, title, username, region, created_at FROM geo_presets WHERE id=?",
        (preset_id,)
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id":         row[0],
        "title":      row[1],
        "username":   row[2],
        "region":     _json_mod.loads(row[3]),   # List[List[List[float]]]
        "created_at": row[4],
    }
 
 
def geo_preset_delete(preset_id: int) -> None:
    conn = get_db()
    conn.execute("DELETE FROM geo_presets WHERE id=?", (preset_id,))
    conn.commit()
    conn.close()
