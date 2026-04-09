"""Pytest configuration and shared fixtures."""

import pytest
import sys
import os
from typing import Dict

# Add parent directory to path so we can import LANHub modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dependencies import DI, mock_database


@pytest.fixture(autouse=True)
def reset_di(mock_db):
    """Reset DI container at start of each test (but after mock_db set up).

    This fixture depends on mock_db so it gets created AFTER mock_db.
    The mock_db fixture registers itself in DI before reset_di runs.
    """
    # mock_db has already registered in DI
    yield
    # Reset after test
    DI.reset()


@pytest.fixture
def mock_db():
    """Provide an in-memory SQLite database for testing.

    Usage:
        def test_something(mock_db):
            conn = mock_db
            c = conn.cursor()
            # Use database
    """
    conn = mock_database()

    # Create basic tables for testing
    c = conn.cursor()

    # Users table
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT,
            created_at REAL
        )
    """)

    # Messages table
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            text TEXT NOT NULL,
            sender_ip TEXT,
            sender_name TEXT,
            timestamp REAL
        )
    """)

    # Channels table
    c.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            password_hash TEXT,
            created_at REAL
        )
    """)

    # Admin users table
    c.execute("""
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'ADMIN',
            created_at REAL
        )
    """)

    # IP bans table
    c.execute("""
        CREATE TABLE IF NOT EXISTS ip_bans (
            id INTEGER PRIMARY KEY,
            ip TEXT UNIQUE NOT NULL,
            reason TEXT,
            until REAL,
            created_at REAL
        )
    """)

    # Uploads table
    c.execute("""
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY,
            stored_name TEXT UNIQUE NOT NULL,
            display_name TEXT,
            size_bytes INTEGER,
            uploader_ip TEXT,
            uploader_name TEXT,
            created_at REAL
        )
    """)

    # Feedback table
    c.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY,
            content TEXT NOT NULL,
            reporter_ip TEXT,
            created_at REAL
        )
    """)

    # Polls table
    c.execute("""
        CREATE TABLE IF NOT EXISTS polls (
            id INTEGER PRIMARY KEY,
            question TEXT NOT NULL,
            created_at REAL
        )
    """)

    # Reports table
    c.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY,
            content TEXT NOT NULL,
            reporter_ip TEXT,
            status TEXT DEFAULT 'open',
            created_at REAL
        )
    """)

    # Lab: lab_users table
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

    # Lab: projects table
    c.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id          INTEGER NOT NULL REFERENCES lab_users(id) ON DELETE CASCADE,
            slug              TEXT    NOT NULL UNIQUE,
            title             TEXT    NOT NULL,
            description       TEXT    DEFAULT '',
            visibility        TEXT    NOT NULL DEFAULT 'private',
            socket_path       TEXT    NOT NULL UNIQUE,
            git_url           TEXT    DEFAULT '',
            docker_container_id TEXT  DEFAULT NULL,
            is_always_on      INTEGER NOT NULL DEFAULT 0,
            created_at        REAL    NOT NULL,
            updated_at        REAL    NOT NULL,
            last_deployed_at  REAL    DEFAULT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_projects_slug  ON projects(slug)")

    # Lab: project_members table
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

    # Lab: comments table
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

    conn.commit()

    # Create a wrapper connection that prevents close() from closing the DB
    class NonClosingConnection:
        """Wrapper around SQLite connection that prevents close() from actually closing it."""
        def __init__(self, wrapped_conn):
            self._conn = wrapped_conn
        
        def __getattr__(self, name):
            return getattr(self._conn, name)
        
        def close(self):
            # Silently ignore close() calls
            pass

    wrapped_conn = NonClosingConnection(conn)

    # Create a get_db function that returns the wrapped connection
    def mock_get_db():
        return wrapped_conn

    # Register the mock in DI container
    DI.register("get_db", mock_get_db)

    yield conn
    conn.close()


@pytest.fixture
def mock_profanity():
    """Mock profanity checker that detects 'badword'.

    Usage:
        def test_something(mock_profanity):
            # check_profanity will return True only for 'badword'
    """

    def checker(text: str) -> bool:
        return "badword" in text.lower()

    DI.register("check_profanity", checker)
    return checker


@pytest.fixture
def mock_time(monkeypatch):
    """Mock time.time() to return consistent timestamps.

    Usage:
        def test_something(mock_time):
            # time.time() will return 1000000.0
    """
    import time

    current_time = 1000000.0

    def mock_time_func():
        return current_time

    monkeypatch.setattr("time.time", mock_time_func)
    return mock_time_func


@pytest.fixture
def sample_messages() -> list[Dict]:
    """Sample message data for testing.

    Usage:
        def test_something(sample_messages):
            for msg in sample_messages:
                print(msg['text'])
    """
    return [
        {
            "id": 1,
            "text": "Hello world",
            "sender_ip": "192.168.1.1",
            "sender_name": "alice",
            "timestamp": 1000000.0,
        },
        {
            "id": 2,
            "text": "Hi there",
            "sender_ip": "192.168.1.2",
            "sender_name": "bob",
            "timestamp": 1000001.0,
        },
    ]


@pytest.fixture
def sample_users() -> list[Dict]:
    """Sample user data for testing.

    Usage:
        def test_something(sample_users):
            for user in sample_users:
                print(user['username'])
    """
    return [
        {
            "id": 1,
            "username": "alice",
            "email": "alice@example.com",
            "created_at": 1000000.0,
        },
        {
            "id": 2,
            "username": "bob",
            "email": "bob@example.com",
            "created_at": 1000001.0,
        },
    ]


# pytest configuration
def pytest_configure(config):
    """Add custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests for individual functions")
    config.addinivalue_line("markers", "integration: Integration tests between modules")
    config.addinivalue_line("markers", "slow: Slow tests that take time to run")
    config.addinivalue_line("markers", "database: Tests that use database")
