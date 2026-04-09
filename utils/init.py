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
    
    # ── polls ─────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS polls (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT    NOT NULL,
            description TEXT    DEFAULT '',
            poll_type   TEXT    NOT NULL DEFAULT 'single'
                            CHECK(poll_type IN ('single','multi')),
            is_dev      INTEGER NOT NULL DEFAULT 0,
            created_by  TEXT    NOT NULL DEFAULT '',
            ip          TEXT    NOT NULL,
            timestamp   REAL    NOT NULL
        )
    """)

    # ── poll_options ──────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS poll_options (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            poll_id  INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
            label    TEXT    NOT NULL,
            position INTEGER NOT NULL DEFAULT 0
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_poll_opts_poll ON poll_options(poll_id)")

    # ── poll_tags ─────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS poll_tags (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            poll_id  INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
            tag      TEXT    NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_poll_tags_poll ON poll_tags(poll_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_poll_tags_tag  ON poll_tags(tag)")

    # ── poll_votes ────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS poll_votes (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            poll_id   INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
            option_id INTEGER NOT NULL REFERENCES poll_options(id) ON DELETE CASCADE,
            ip        TEXT    NOT NULL,
            timestamp REAL    NOT NULL,
            UNIQUE(poll_id, option_id, ip)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_poll_votes_poll ON poll_votes(poll_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_poll_votes_ip   ON poll_votes(poll_id, ip)")
    
    # ── updates ───────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS updates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            version     TEXT    NOT NULL,
            title       TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            created_by  TEXT    NOT NULL,
            timestamp   REAL    NOT NULL
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS geo_presets (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT    NOT NULL,
            username   TEXT    NOT NULL,
            region     TEXT    NOT NULL,  -- JSON: List[List[List[float]]] (array of polygons)
            created_at REAL    NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_geo_presets_title ON geo_presets(title)")
    
    # ── Lab: lab_users ────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS lab_users (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            username          TEXT    NOT NULL UNIQUE,
            password_hash     TEXT    NOT NULL,
            quota_mb          INTEGER NOT NULL DEFAULT 500,
            is_admin          INTEGER NOT NULL DEFAULT 0,
            session_token     TEXT    UNIQUE,
            created_at        REAL    NOT NULL,
            last_login_at     REAL    DEFAULT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_lab_users_username ON lab_users(username)")
    
    # ── Lab: projects ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id          INTEGER NOT NULL REFERENCES lab_users(id) ON DELETE CASCADE,
            slug              TEXT    NOT NULL UNIQUE,
            title             TEXT    NOT NULL,
            description       TEXT    DEFAULT '',
            visibility        TEXT    NOT NULL DEFAULT 'private',  -- 'private', 'public'
            socket_path       TEXT    NOT NULL UNIQUE,
            git_url           TEXT    DEFAULT '',
            docker_container_id TEXT  DEFAULT NULL,
            is_always_on      INTEGER NOT NULL DEFAULT 0,
            created_at        REAL    NOT NULL,
            updated_at        REAL    NOT NULL,
            last_deployed_at  REAL    DEFAULT NULL,
            status            TEXT    NOT NULL DEFAULT 'OFFLINE'
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_projects_slug  ON projects(slug)")
    
    # ── Lab: project_members ──────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS project_members (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            user_id      INTEGER NOT NULL REFERENCES lab_users(id) ON DELETE CASCADE,
            role         TEXT    NOT NULL CHECK(role IN ('owner', 'contributor', 'viewer')),
            added_at     REAL    NOT NULL,
            UNIQUE(project_id, user_id)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_project_members_project ON project_members(project_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_project_members_user    ON project_members(user_id)")
    
    # ── Lab: comments ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS lab_comments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            user_id       INTEGER NOT NULL REFERENCES lab_users(id) ON DELETE CASCADE,
            parent_id     INTEGER REFERENCES lab_comments(id) ON DELETE CASCADE,
            content       TEXT    NOT NULL,
            created_at    REAL    NOT NULL,
            updated_at    REAL    NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_lab_comments_project ON lab_comments(project_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_lab_comments_user    ON lab_comments(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_lab_comments_parent  ON lab_comments(parent_id)")
    
    # ── Lab: comment_likes ────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS comment_likes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            comment_id   INTEGER NOT NULL REFERENCES lab_comments(id) ON DELETE CASCADE,
            user_id      INTEGER NOT NULL REFERENCES lab_users(id) ON DELETE CASCADE,
            created_at   REAL    NOT NULL,
            UNIQUE(comment_id, user_id)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_comment_likes_comment ON comment_likes(comment_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_comment_likes_user    ON comment_likes(user_id)")
    
    # ── Lab: project_invitations ──────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS project_invitations (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            inviter_id   INTEGER NOT NULL REFERENCES lab_users(id) ON DELETE CASCADE,
            invitee_id   INTEGER NOT NULL REFERENCES lab_users(id) ON DELETE CASCADE,
            role         TEXT    NOT NULL CHECK(role IN ('owner', 'contributor', 'viewer')),
            status       TEXT    NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'rejected')),
            created_at   REAL    NOT NULL,
            responded_at REAL    DEFAULT NULL,
            UNIQUE(project_id, invitee_id, status)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_project_invitations_project ON project_invitations(project_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_project_invitations_invitee ON project_invitations(invitee_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_project_invitations_status ON project_invitations(status)")
    
    # ── Lab: project_secrets ──────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS project_secrets (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            secret_key   TEXT    NOT NULL,
            secret_value TEXT    NOT NULL,
            created_at   REAL    NOT NULL,
            updated_at   REAL    NOT NULL,
            UNIQUE(project_id, secret_key)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_project_secrets_project ON project_secrets(project_id)")
    
    # ── Lab: project_stars ────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS project_stars (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            user_id      INTEGER NOT NULL REFERENCES lab_users(id) ON DELETE CASCADE,
            created_at   REAL    NOT NULL,
            UNIQUE(project_id, user_id)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_project_stars_project ON project_stars(project_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_project_stars_user ON project_stars(user_id)")
 
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
    
    # Lab: projects table gets external_port column (for direct code-server access)
    try:
        c.execute("ALTER TABLE projects ADD COLUMN external_port INTEGER DEFAULT NULL")
    except Exception:
        pass
 
    # ── Migration: Remove project_type column (no longer used with unified template) ──
    try:
        # Check if project_type column exists
        c.execute("PRAGMA table_info(projects)")
        columns = [col[1] for col in c.fetchall()]
        if 'project_type' in columns:
            # SQLite 3.35.0+ supports DROP COLUMN
            c.execute("ALTER TABLE projects DROP COLUMN project_type")
            app_log.info("[init] Dropped obsolete project_type column from projects table")
    except Exception as e:
        # If drop fails (older SQLite), log but don't fail - the column just won't be used
        app_log.warning(f"[init] Could not drop project_type column (may be on older SQLite): {e}")
 
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
            # Switch remote to SSH so pushes work without credentials
            _switch_remote_to_ssh()
        except Exception as e:
            git_log.error(f"Error cloning repo: {e}")
    else:
        git_log.info("Redirector repo already exists.")
        # Ensure remote is SSH even on existing repos
        _switch_remote_to_ssh()


def _switch_remote_to_ssh():
    """Convert the redirector remote URL from HTTPS to SSH."""
    import re
    try:
        repo = Repo(REDIRECTOR_PATH)
        current_url = repo.remotes.origin.url
        # Convert https://github.com/USER/REPO to git@github.com:USER/REPO.git
        m = re.match(r'https?://github\.com/([^/]+)/([^/\s]+?)(?:\.git)?\s*$', current_url)
        if m:
            ssh_url = f"git@github.com:{m.group(1)}/{m.group(2)}.git"
            repo.remotes.origin.set_url(ssh_url)
            git_log.info(f"Remote switched to SSH: {ssh_url}")
        else:
            git_log.info(f"Remote already SSH or unrecognised format: {current_url}")
    except Exception as e:
        git_log.error(f"Failed to switch remote to SSH: {e}")





#########################################################
def initialize():
    create_directories()
    ensure_redirector_exists()
    init_db()