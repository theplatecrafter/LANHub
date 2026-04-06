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

    conn.commit()

    # Create a get_db function that returns the same connection
    def mock_get_db():
        return conn

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
