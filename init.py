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

    # --- Chat ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            username  TEXT    NOT NULL,
            ip        TEXT    NOT NULL,
            message   TEXT    NOT NULL,
            timestamp REAL    NOT NULL
        )
    """)

    # --- Stub tables for future features ---
    # c.execute("CREATE TABLE IF NOT EXISTS game_scores (...)")
    # c.execute("CREATE TABLE IF NOT EXISTS reports (...)")

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