# init.py
from glob_vars import *

import os
import sqlite3
import subprocess
from git import Repo
from werkzeug.security import generate_password_hash




###########################################
# Database
###########################################
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
 
    # ── chat_messages ────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT    NOT NULL,
            ip           TEXT    NOT NULL,
            message      TEXT    NOT NULL,
            timestamp    REAL    NOT NULL,
            reply_to_id  INTEGER REFERENCES chat_messages(id),
            edited       INTEGER NOT NULL DEFAULT 0
        )
    """)
    # ── admins ───────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL,
            role          TEXT    NOT NULL CHECK(role IN ('MOD','DEV'))
        )
    """)
    
    # ── ip_bans ──────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS ip_bans (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ip         TEXT    NOT NULL UNIQUE,
            reason     TEXT    DEFAULT '',
            banned_by  TEXT    NOT NULL,
            banned_at  REAL    NOT NULL,
            expires_at REAL    DEFAULT NULL  -- NULL = permanent
        )
    """)
 
    # ── reports ──────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_ip        TEXT    NOT NULL,
            reported_username  TEXT    NOT NULL,
            reported_ip        TEXT    DEFAULT '',
            message_id         INTEGER DEFAULT NULL,
            message_text       TEXT    DEFAULT '',
            reason             TEXT    DEFAULT '',
            source TEXT NOT NULL DEFAULT 'chat',
            timestamp          REAL    NOT NULL,
            status             TEXT    NOT NULL DEFAULT 'pending'
                                   CHECK(status IN ('pending','reviewed','dismissed')),
            reviewed_by        TEXT    DEFAULT NULL,
            reviewed_at        REAL    DEFAULT NULL
        )
    """)
    
    # ── uploads ──────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS uploads (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            stored_name    TEXT    NOT NULL UNIQUE,   -- UUID filename on disk
            original_name  TEXT    NOT NULL,          -- original filename from user
            display_name   TEXT    NOT NULL,
            uploader_ip    TEXT    NOT NULL,
            password_hash  TEXT    DEFAULT NULL,      -- NULL = public
            size_bytes     INTEGER NOT NULL,
            mime_type      TEXT    DEFAULT '',
            timestamp      REAL    NOT NULL
        )
    """)
 
    # ── upload_tags ───────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS upload_tags (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_id  INTEGER NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
            tag        TEXT    NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_upload_tags_tag       ON upload_tags(tag)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_upload_tags_upload_id ON upload_tags(upload_id)")
    
    # ── channels ──────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            title         TEXT    NOT NULL,
            description   TEXT    DEFAULT '',
            password_hash TEXT    NOT NULL,
            created_by_ip TEXT    NOT NULL,
            created_at    REAL    NOT NULL
        )
    """)
 
    # ── channel_tags ──────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS channel_tags (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
            tag        TEXT    NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_channel_tags_channel ON channel_tags(channel_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_channel_tags_tag     ON channel_tags(tag)")
 
    # ── channel_messages ──────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS channel_messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id   INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
            username     TEXT    NOT NULL,
            ip           TEXT    NOT NULL,
            message      TEXT    NOT NULL,
            timestamp    REAL    NOT NULL,
            reply_to_id  INTEGER DEFAULT NULL REFERENCES channel_messages(id),
            edited       INTEGER NOT NULL DEFAULT 0
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_channel_msgs_channel ON channel_messages(channel_id)")
    
    # ── feedback ──────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            type          TEXT    NOT NULL CHECK(type IN ('bug','feature','other')),
            title         TEXT    NOT NULL,
            description   TEXT    DEFAULT '',
            username      TEXT    NOT NULL,
            ip            TEXT    NOT NULL,
            status        TEXT    NOT NULL DEFAULT 'open'
                              CHECK(status IN ('open','resolved')),
            resolved_by   TEXT    DEFAULT NULL,
            resolved_at   REAL    DEFAULT NULL,
            resolved_note TEXT    DEFAULT '',
            timestamp     REAL    NOT NULL
        )
    """)

    # ── feedback_tags ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS feedback_tags (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
            tag         TEXT    NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_fb_tags_fb  ON feedback_tags(feedback_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_fb_tags_tag ON feedback_tags(tag)")

    # ── feedback_stars ────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS feedback_stars (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
            ip          TEXT    NOT NULL,
            timestamp   REAL    NOT NULL,
            UNIQUE(feedback_id, ip)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_fb_stars_fb ON feedback_stars(feedback_id)")

    # ── feedback_replies ──────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS feedback_replies (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
            username    TEXT    NOT NULL,
            ip          TEXT    NOT NULL,
            content     TEXT    NOT NULL,
            is_dev      INTEGER NOT NULL DEFAULT 0,
            timestamp   REAL    NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_fb_replies_fb ON feedback_replies(feedback_id)")
 
    for col, defn in [
        ("reply_to_id", "INTEGER REFERENCES chat_messages(id)"),
        ("edited",      "INTEGER NOT NULL DEFAULT 0"),
        ("msg_type",    "TEXT NOT NULL DEFAULT 'text'"),
    ]:
        try:
            c.execute(f"ALTER TABLE chat_messages ADD COLUMN {col} {defn}")
        except Exception:
            pass

    # channel_messages gets msg_type too
    try:
        c.execute("ALTER TABLE channel_messages ADD COLUMN msg_type TEXT NOT NULL DEFAULT 'text'")
    except Exception:
        pass
 
    # Seed initial DEV account if no admins exist yet
    c.execute("SELECT COUNT(*) FROM admins")
    if c.fetchone()[0] == 0:
        from werkzeug.security import generate_password_hash
        c.execute(
            "INSERT INTO admins (username, password_hash, role) VALUES (?, ?, ?)",
            (
                INITIAL_DEV_USERNAME,
                generate_password_hash(INITIAL_DEV_PASSWORD),
                "DEV",
            )
        )
        app_log.info(f"[admin] Seeded initial DEV account: {INITIAL_DEV_USERNAME!r}")
 
    conn.commit()
    conn.close()
    app_log.info("Database initialized.")




###########################################
# GitHub Redirector Setup
###########################################
def create_directories():
    directories = ['files']
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            

def ensure_redirector_exists():
    if not os.path.exists(REDIRECTOR_PATH):
        git_log.info("Redirector repo not found. Cloning...")
        try:
            Repo.clone_from(REPO_URL, REDIRECTOR_PATH)
            git_log.info("Clone successful.")
        except Exception as e:
            git_log.error(f"Error cloning repo: {e}")
    else:
        git_log.info("Redirector repo already exists.")




#########################################################
def initialize():
    create_directories()
    ensure_redirector_exists()
    init_db()