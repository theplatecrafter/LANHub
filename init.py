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
    for col, defn in [
        ("reply_to_id", "INTEGER REFERENCES chat_messages(id)"),
        ("edited",      "INTEGER NOT NULL DEFAULT 0"),
    ]:
        try:
            c.execute(f"ALTER TABLE chat_messages ADD COLUMN {col} {defn}")
        except Exception:
            pass
 
    # ── admins ───────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL,
            role          TEXT    NOT NULL CHECK(role IN ('MOD','DEV'))
        )
    """)
 
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