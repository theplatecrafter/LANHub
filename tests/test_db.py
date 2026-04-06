"""Tests for functions/db.py - Database operations."""

import pytest
import sqlite3
import time
from dependencies import DI


@pytest.mark.unit
@pytest.mark.database
class TestDatabaseOperations:
    """Test database core operations."""

    def test_get_db_returns_connection(self, mock_db):
        """Test that get_db returns a valid connection."""
        get_db = DI.get("get_db")
        conn = get_db()

        assert isinstance(conn, sqlite3.Connection)
        assert conn.row_factory == sqlite3.Row

    def test_db_insert_and_query(self, mock_db):
        """Test inserting and querying data."""
        db_insert = DI.get("db_insert")
        db_query = DI.get("db_query")

        # Insert user
        user_id = db_insert(
            "users",
            {
                "username": "testuser",
                "email": "test@example.com",
                "created_at": time.time(),
            },
        )

        assert user_id > 0

        # Query user
        results = db_query("SELECT * FROM users WHERE id = ?", [user_id])
        assert len(results) == 1
        assert results[0]["username"] == "testuser"

    def test_db_update_row(self, mock_db):
        """Test updating a row."""
        db_insert = DI.get("db_insert")
        db_update_row = DI.get("db_update_row")
        db_query = DI.get("db_query")

        # Insert user
        user_id = db_insert(
            "users",
            {
                "username": "oldname",
                "email": "old@example.com",
                "created_at": time.time(),
            },
        )

        # Update user
        db_update_row("users", user_id, {"email": "new@example.com"})

        # Verify update
        results = db_query("SELECT * FROM users WHERE id = ?", [user_id])
        assert results[0]["email"] == "new@example.com"
        assert results[0]["username"] == "oldname"  # Unchanged

    def test_db_delete_row(self, mock_db):
        """Test deleting a row."""
        db_insert = DI.get("db_insert")
        db_delete_row = DI.get("db_delete_row")
        db_query = DI.get("db_query")

        # Insert user
        user_id = db_insert(
            "users",
            {
                "username": "tobeDeleted",
                "email": "delete@example.com",
                "created_at": time.time(),
            },
        )

        # Delete user
        db_delete_row("users", user_id)

        # Verify deletion
        results = db_query("SELECT * FROM users WHERE id = ?", [user_id])
        assert len(results) == 0

    def test_db_query_with_parameters(self, mock_db):
        """Test parameterized queries to prevent SQL injection."""
        db_insert = DI.get("db_insert")
        db_query = DI.get("db_query")

        # Insert multiple users
        db_insert(
            "users", {"username": "alice", "email": "a@ex.com", "created_at": 1000.0}
        )
        db_insert(
            "users", {"username": "bob", "email": "b@ex.com", "created_at": 2000.0}
        )

        # Query with parameters (safe from SQL injection)
        results = db_query("SELECT * FROM users WHERE username = ?", ["alice"])

        assert len(results) == 1
        assert results[0]["username"] == "alice"

    def test_db_get_row(self, mock_db):
        """Test getting single row by ID."""
        db_insert = DI.get("db_insert")
        db_get_row = DI.get("db_get_row")

        # Insert user
        user_id = db_insert(
            "users",
            {"username": "test", "email": "test@ex.com", "created_at": time.time()},
        )

        # Get row
        row = db_get_row("users", user_id)

        assert row is not None
        assert row["username"] == "test"
        assert row["id"] == user_id

    def test_db_get_row_nonexistent(self, mock_db):
        """Test getting non-existent row returns None or empty."""
        db_get_row = DI.get("db_get_row")

        # Try to get non-existent row
        row = db_get_row("users", 99999)

        # Should return None or empty dict
        assert row is None or len(row) == 0

    def test_multiple_operations_transaction(self, mock_db):
        """Test multiple database operations."""
        db_insert = DI.get("db_insert")
        db_query = DI.get("db_query")

        # Insert multiple records
        for i in range(5):
            db_insert(
                "users",
                {
                    "username": f"user{i}",
                    "email": f"user{i}@ex.com",
                    "created_at": time.time(),
                },
            )

        # Verify all inserted
        results = db_query("SELECT COUNT(*) as cnt FROM users")
        assert results[0]["cnt"] == 5


@pytest.mark.integration
class TestDatabaseIntegration:
    """Integration tests for database with other functions."""

    def test_insert_and_retrieve_message(self, mock_db):
        """Test inserting and retrieving a message."""
        db_insert = DI.get("db_insert")
        db_query = DI.get("db_query")

        # Insert message
        msg_id = db_insert(
            "messages",
            {
                "text": "Hello world",
                "sender_ip": "192.168.1.1",
                "sender_name": "alice",
                "timestamp": time.time(),
            },
        )

        # Retrieve message
        results = db_query(
            "SELECT * FROM messages WHERE id = ? ORDER BY timestamp DESC", [msg_id]
        )

        assert len(results) == 1
        assert results[0]["text"] == "Hello world"
        assert results[0]["sender_name"] == "alice"
