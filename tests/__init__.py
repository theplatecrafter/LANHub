"""LANHub test suite.

This package contains comprehensive tests for all core modules.

Test Structure:
- test_db.py: Database operations
- test_validators.py: Input validation
- test_admin.py: Admin user management
- test_chat.py: Chat and messaging
- conftest.py: Pytest fixtures and configuration

Running Tests:
    # Run all tests
    pytest tests/

    # Run with coverage
    pytest tests/ --cov=functions --cov=shared

    # Run specific test file
    pytest tests/test_db.py

    # Run specific test class
    pytest tests/test_db.py::TestDatabaseOperations

    # Run specific test function
    pytest tests/test_db.py::TestDatabaseOperations::test_get_db_returns_connection

    # Run with markers
    pytest tests/ -m unit  # Only unit tests
    pytest tests/ -m integration  # Only integration tests
    pytest tests/ -m "not slow"  # Skip slow tests

Fixtures Available:
- mock_db: In-memory SQLite database
- mock_profanity: Profanity checker (detects 'badword')
- mock_time: Fixed timestamp
- sample_messages: Sample message data
- sample_users: Sample user data
- reset_di: Reset dependency injection container

Example Test:
    def test_example(mock_db):
        \"\"\"Test with mocked database.\"\"\"
        from dependencies import DI

        db_insert = DI.get('db_insert')
        user_id = db_insert('users', {'username': 'test'})

        assert user_id > 0
"""
