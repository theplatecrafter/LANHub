# init.py
from glob_vars import *

import os
import sqlite3
import subprocess
from git import Repo



###########################################
# Database
###########################################
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
 
    # Core table
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
 
    # Migration: add columns to existing DBs that predate them
    for col, definition in [
        ("reply_to_id", "INTEGER REFERENCES chat_messages(id)"),
        ("edited",      "INTEGER NOT NULL DEFAULT 0"),
    ]:
        try:
            c.execute(f"ALTER TABLE chat_messages ADD COLUMN {col} {definition}")
        except Exception:
            pass   # column already exists — that's fine
 
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