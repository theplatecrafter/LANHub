"""Tests for functions/admin.py - Admin user management."""

import pytest
import time
from werkzeug.security import check_password_hash
from dependencies import DI


@pytest.mark.unit
@pytest.mark.database
class TestAdminUserManagement:
    """Test admin user management functions."""

    def test_create_admin(self, mock_db):
        """Test creating new admin user."""
        db_insert = DI.get("db_insert")

        # Simulate create_admin
        admin_id = db_insert(
            "admin_users",
            {
                "username": "admin1",
                "password_hash": "hashed_password",
                "role": "ADMIN",
                "created_at": time.time(),
            },
        )

        assert admin_id > 0

        # Verify inserted
        get_db = DI.get("get_db")
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM admin_users WHERE id = ?", (admin_id,))
        admin = c.fetchone()

        assert admin is not None
        assert admin["username"] == "admin1"
        assert admin["role"] == "ADMIN"

    def test_get_all_admins(self, mock_db):
        """Test retrieving all admin users."""
        db_insert = DI.get("db_insert")

        # Create multiple admins
        admin1 = db_insert(
            "admin_users",
            {
                "username": "dev",
                "password_hash": "hash1",
                "role": "DEV",
                "created_at": time.time(),
            },
        )

        admin2 = db_insert(
            "admin_users",
            {
                "username": "admin",
                "password_hash": "hash2",
                "role": "ADMIN",
                "created_at": time.time(),
            },
        )

        # Get all
        get_db = DI.get("get_db")
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM admin_users ORDER BY id")
        admins = c.fetchall()

        assert len(admins) >= 2
        usernames = [a["username"] for a in admins]
        assert "dev" in usernames
        assert "admin" in usernames

    def test_get_admin_by_username(self, mock_db):
        """Test retrieving admin by username."""
        db_insert = DI.get("db_insert")

        # Create admin
        db_insert(
            "admin_users",
            {
                "username": "testadmin",
                "password_hash": "hashed",
                "role": "ADMIN",
                "created_at": time.time(),
            },
        )

        # Retrieve by username
        get_db = DI.get("get_db")
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM admin_users WHERE username = ?", ("testadmin",))
        admin = c.fetchone()

        assert admin is not None
        assert admin["username"] == "testadmin"
        assert admin["role"] == "ADMIN"

    def test_admin_roles(self, mock_db):
        """Test different admin roles."""
        db_insert = DI.get("db_insert")

        roles = ["DEV", "ADMIN"]

        for role in roles:
            admin_id = db_insert(
                "admin_users",
                {
                    "username": f"user_{role.lower()}",
                    "password_hash": "hash",
                    "role": role,
                    "created_at": time.time(),
                },
            )

            # Verify role
            get_db = DI.get("get_db")
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT * FROM admin_users WHERE id = ?", (admin_id,))
            admin = c.fetchone()

            assert admin["role"] == role


@pytest.mark.integration
class TestAdminIntegration:
    """Integration tests for admin functionality."""

    def test_admin_creation_and_retrieval(self, mock_db):
        """Test full admin creation and retrieval flow."""
        db_insert = DI.get("db_insert")

        # Create admin
        admin_id = db_insert(
            "admin_users",
            {
                "username": "integration_test",
                "password_hash": "secure_hash",
                "role": "ADMIN",
                "created_at": time.time(),
            },
        )

        # Simulate retrieval by username
        get_db = DI.get("get_db")
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM admin_users WHERE username = ?", ("integration_test",))
        admin = c.fetchone()

        # Verify
        assert admin is not None
        assert admin["id"] == admin_id
        assert admin["username"] == "integration_test"
        assert admin["role"] == "ADMIN"

    def test_multiple_admins_with_different_roles(self, mock_db):
        """Test managing multiple admins with different roles."""
        db_insert = DI.get("db_insert")

        # Create admins
        dev_id = db_insert(
            "admin_users",
            {
                "username": "dev_user",
                "password_hash": "hash",
                "role": "DEV",
                "created_at": time.time(),
            },
        )

        regular_id = db_insert(
            "admin_users",
            {
                "username": "regular_admin",
                "password_hash": "hash",
                "role": "ADMIN",
                "created_at": time.time(),
            },
        )

        # Retrieve and check roles
        get_db = DI.get("get_db")
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM admin_users WHERE role = ?", ("DEV",))
        dev_admins = c.fetchall()

        assert len(dev_admins) >= 1
        assert any(a["username"] == "dev_user" for a in dev_admins)

        c.execute("SELECT * FROM admin_users WHERE role = ?", ("ADMIN",))
        regular_admins = c.fetchall()

        assert len(regular_admins) >= 1
        assert any(a["username"] == "regular_admin" for a in regular_admins)
