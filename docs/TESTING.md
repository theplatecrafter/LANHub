# LANHub Testing Guide

**Comprehensive guide to testing infrastructure, CI/CD, and code quality tools**

> Last Updated: April 2026  
> Testing Coverage: ~80% of core modules  
> CI/CD Status: ✅ Active

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Testing Infrastructure](#testing-infrastructure)
3. [Running Tests](#running-tests)
4. [Dependency Injection](#dependency-injection)
5. [Writing Tests](#writing-tests)
6. [Code Quality Tools](#code-quality-tools)
7. [Pre-commit Hooks](#pre-commit-hooks)
8. [CI/CD Pipeline](#cicd-pipeline)
9. [Coverage Reports](#coverage-reports)
10. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Setup Testing Environment

```bash
# Install development dependencies
pip install -r config/requirements-dev.txt

# Install pre-commit hooks
pre-commit install -c config/.pre-commit-config.yaml

# Run all tests
pytest tests/
```

### Run Tests with Coverage

```bash
pytest tests/ --cov=functions --cov=shared --cov-report=html
```

Open `htmlcov/index.html` to see coverage report.

---

## Testing Infrastructure

### Architecture

```
tests/
├── __init__.py              - Test package declaration
├── conftest.py              - Pytest configuration & fixtures
├── test_db.py              - Database operations tests
├── test_validators.py      - Input validation tests
├── test_admin.py           - Admin management tests
└── test_chat.py            - Chat functionality tests (future)
```

### Key Components

#### 1. Dependency Injection (dependencies.py)

Simple DI container for easy mocking:

```python
from dependencies import DI

# Get production implementation
get_db = DI.get('get_db')

# Or mock it in tests
DI.register('get_db', mock_database)
```

**Benefits:**
- Mock functions without modifying production code
- Test in isolation
- Easy integration testing
- Quick setup/teardown

#### 2. Test Fixtures (conftest.py)

Reusable test setups:

```python
@pytest.fixture
def mock_db():
    """In-memory SQLite database for testing."""
    conn = mock_database()
    yield conn
    conn.close()
```

#### 3. Test Files

- **test_db.py** - Database operations (14 tests)
- **test_validators.py** - Input validation (16 tests)
- **test_admin.py** - Admin functions (6 tests)

---

## Running Tests

### Basic Commands

```bash
# Run all tests
pytest tests/

# Run specific file
pytest tests/test_db.py

# Run specific test class
pytest tests/test_db.py::TestDatabaseOperations

# Run specific test
pytest tests/test_db.py::TestDatabaseOperations::test_get_db_returns_connection

# Run with verbose output
pytest tests/ -v

# Run only unit tests
pytest tests/ -m unit

# Run only integration tests
pytest tests/ -m integration

# Run excluding slow tests
pytest tests/ -m "not slow"
```

### With Coverage

```bash
# Show coverage in terminal
pytest tests/ --cov=functions --cov=shared

# Generate HTML coverage report
pytest tests/ --cov=functions --cov=shared --cov-report=html

# Show missing lines
pytest tests/ --cov=functions --cov-report=term-missing
```

### Parallel Execution

```bash
# Run tests in parallel (faster)
pytest tests/ -n auto

# Run 4 workers
pytest tests/ -n 4
```

---

## Dependency Injection

### Why Dependency Injection?

**Without DI (hard to test):**
```python
def save_message(text):
    conn = get_db()  # Can't mock this
    # Use database
```

**With DI (easy to test):**
```python
def save_message(text, get_db=None):
    if get_db is None:
        get_db = DI.get('get_db')
    # Use database
```

### Using DI in Tests

```python
from dependencies import DI, mock_database

def test_save_message():
    # Setup mock
    DI.register('get_db', mock_database)
    
    # Test your code
    result = save_message("Hello")
    
    # Verify
    assert result is not None
    
    # Cleanup (automatic with fixture)
    DI.reset()
```

### Registering Mocks

```python
# Register a function
DI.register('check_profanity', lambda msg: False)

# Register a factory (creates new instance each time)
DI.register_factory('get_db', lambda: mock_database())

# Get the mock
check = DI.get('check_profanity')
assert check("any text") == False

# Check if registered
if DI.has('get_db'):
    conn = DI.get('get_db')

# Reset to production
DI.reset()
```

---

## Writing Tests

### Test Structure

```python
import pytest
from dependencies import DI

@pytest.mark.unit
class TestFeature:
    """Test group for related functionality."""
    
    def test_happy_path(self, mock_db):
        """Test successful case.
        
        Naming convention:
        - test_<function>_<scenario>
        - Example: test_save_message_succeeds
        """
        # Arrange
        db_insert = DI.get('db_insert')
        
        # Act
        result = db_insert('users', {'username': 'test'})
        
        # Assert
        assert result > 0
    
    def test_edge_case(self, mock_db):
        """Test boundary condition."""
        # Similar structure
    
    def test_error_case(self, mock_db):
        """Test error handling."""
        with pytest.raises(ValueError):
            # Code that should raise
            pass
```

### Test Markers

```python
@pytest.mark.unit
def test_function():
    """Quick unit test."""
    pass

@pytest.mark.integration
def test_modules_together():
    """Test multiple modules."""
    pass

@pytest.mark.slow
def test_expensive_operation():
    """Slow test, skip in CI."""
    pass

@pytest.mark.database
def test_with_db(mock_db):
    """Test using database."""
    pass
```

### Available Fixtures

```python
def test_example(
    mock_db,                # In-memory database
    mock_profanity,        # Profanity checker mock
    mock_time,             # Fixed timestamp
    sample_messages,       # Test message data
    sample_users,          # Test user data
    reset_di               # Reset DI container
):
    # Use fixtures
    pass
```

### Example: Complete Test

```python
@pytest.mark.unit
@pytest.mark.database
class TestMessageValidation:
    """Test message validation."""
    
    def test_valid_message_saved(self, mock_db, sample_messages):
        """Test that valid message is saved to database."""
        # Arrange
        db_insert = DI.get('db_insert')
        message = sample_messages[0]
        
        # Act
        msg_id = db_insert('messages', message)
        
        # Assert
        assert msg_id > 0
    
    def test_empty_message_rejected(self, mock_db):
        """Test that empty message is rejected."""
        # Arrange
        from shared import validate_message
        
        # Act
        is_valid, error = validate_message("")
        
        # Assert
        assert is_valid is False
        assert len(error) > 0
    
    def test_profane_message_rejected(self, mock_db, mock_profanity):
        """Test that profane message is rejected."""
        # Arrange
        from shared import validate_message
        
        # Act
        is_valid, error = validate_message(
            "This is badword content",
            check_profanity_func=DI.get('check_profanity')
        )
        
        # Assert
        assert is_valid is False
        assert 'disallowed' in error.lower()
```

---

## Code Quality Tools

### Black (Code Formatting)

```bash
# Format code
black .

# Check formatting
black --check .

# Configure line length
black --line-length=100 .
```

### isort (Import Sorting)

```bash
# Sort imports
isort .

# Check import order
isort --check-only .

# Use Black profile
isort --profile=black .
```

### Flake8 (Style Guide Enforcement)

```bash
# Check code style
flake8 .

# Show statistics
flake8 . --statistics

# Only show critical errors
flake8 . --select=E9,F63,F7,F82
```

### Pylint (Code Analysis)

```bash
# Analyze code
pylint functions/*.py shared/*.py

# Output rating
pylint app.py --exit-zero

# Custom config
pylint --load-plugins=pylint_flask .
```

### mypy (Type Checking)

```bash
# Check types
mypy .

# Ignore missing imports
mypy . --ignore-missing-imports

# Show error codes
mypy . --show-error-codes
```

### Bandit (Security)

```bash
# Scan for security issues
bandit -r .

# JSON output
bandit -r . -f json

# Skip certain tests
bandit -r . --skip B101
```

---

## Pre-commit Hooks

### Setup

```bash
# Install pre-commit
pip install pre-commit

# Setup hooks
pre-commit install

# Uninstall hooks
pre-commit uninstall
```

### Included Hooks

1. **Black** - Format Python code
2. **isort** - Sort imports
3. **Pylint** - Lint Python code
4. **mypy** - Type checking
5. **Bandit** - Security scanning
6. **Pre-commit hooks** - File checks
   - Large files detection
   - End-of-file newlines
   - Trailing whitespace
   - YAML/JSON validation
   - Private key detection
   - Merge conflict detection

### Running Hooks Manually

```bash
# Run on all files
pre-commit run --all-files

# Run specific hook
pre-commit run black --all-files

# Run on staged changes
pre-commit run
```

---

## CI/CD Pipeline

### GitHub Actions Workflow

File: `.github/workflows/ci-cd.yml`

**Triggers:**
- Push to main/develop branches
- Pull requests to main/develop
- Daily at 2 AM UTC

**Jobs:**

1. **Lint** (Code Quality)
   - Black formatting check
   - isort import check
   - Flake8 style checking
   - Pylint analysis
   - Bandit security scan
   - Pre-commit hooks

2. **Test** (Unit & Integration)
   - Run pytest on Python 3.10, 3.11, 3.13
   - Generate coverage reports
   - Upload to Codecov

3. **Type Check** (mypy)
   - Static type analysis
   - Type hint validation

4. **Security** (Bandit & Safety)
   - Security issue scanning
   - Vulnerability checking

5. **Build** (Package Check)
   - Verify imports work
   - Check module availability

6. **Docs** (Documentation)
   - Verify .md files exist
   - Validate Markdown syntax

7. **Status** (Final Report)
   - Summary of all checks
   - Fail if critical checks fail

### View CI/CD Results

1. **GitHub Actions**: https://github.com/[owner]/LANHub/actions
2. **Badge in README**: Add to README.md:
   ```markdown
   ![CI/CD](https://github.com/[owner]/LANHub/workflows/CI%2FCD%20Pipeline/badge.svg)
   ```

---

## Coverage Reports

### Generate Coverage

```bash
# Terminal report
pytest tests/ --cov=functions --cov=shared --cov-report=term-missing

# HTML report
pytest tests/ --cov=functions --cov=shared --cov-report=html

# Coverage percentage
pytest tests/ --cov=functions --cov=shared --cov-report=term
```

### View HTML Report

```bash
# Open in browser
python -m http.server 8000 -d htmlcov
# Visit http://localhost:8000
```

### Coverage Goals

Current targets:
- **functions/** modules: 80%+
- **shared/** modules: 90%+
- **Overall**: 75%+

Track in CI/CD pipeline.

---

## Troubleshooting

### Test Failures

```bash
# Verbose output
pytest tests/ -vv

# Show print statements
pytest tests/ -s

# Stop on first failure
pytest tests/ -x

# Show local variables on failure
pytest tests/ -l

# Enter debugger on failure
pytest tests/ --pdb
```

### Database Issues

```python
# Check if database is properly mocked
from dependencies import DI, mock_database

db = mock_database()
c = db.cursor()
c.execute("SELECT 1")
print(c.fetchone())
```

### Import Errors

```bash
# Check Python path
python -c "import sys; print(sys.path)"

# Test imports
python -c "import functions as f; print(dir(f))"

# Check module structure
python -c "from tests.conftest import mock_db"
```

### Pre-commit Hook Issues

```bash
# Skip hooks for one commit
git commit --no-verify

# Clean and reinstall hooks
pre-commit clean
pre-commit install

# Debug specific hook
pre-commit run black --all-files -v
```

---

## Best Practices

### Writing Tests

1. ✅ One assertion per test (or related assertions)
2. ✅ Clear test names: `test_<function>_<scenario>`
3. ✅ Use fixtures for setup
4. ✅ Use markers (@pytest.mark.unit, etc.)
5. ✅ Test both happy path and error cases
6. ✅ Use DI for mocking

### Code Quality

1. ✅ Run pre-commit hooks before committing
2. ✅ Fix issues with `black .` and `isort .`
3. ✅ Aim for 80%+ test coverage
4. ✅ Add type hints to new code
5. ✅ Use meaningful variable names
6. ✅ Follow PEP 8 style guide

### CI/CD

1. ✅ Fix any failing CI/CD checks before merging
2. ✅ Review GitHub Actions logs
3. ✅ Keep tests fast (use unit tests)
4. ✅ Avoid flaky tests
5. ✅ Document complex test logic

---

## Example Complete Test

```python
"""Test user validation workflow."""

import pytest
import time
from dependencies import DI


@pytest.mark.unit
class TestUserCreationWorkflow:
    """Test creating and validating users."""
    
    def test_create_user_with_validation(self, mock_db):
        """Test complete user creation with validation."""
        # Setup
        from shared.validators import validate_username
        
        username = "alice"
        email = "alice@example.com"
        
        # Validate input
        is_valid, error = validate_username(username)
        assert is_valid, f"Validation failed: {error}"
        
        # Create in database
        db_insert = DI.get('db_insert')
        user_id = db_insert('users', {
            'username': username,
            'email': email,
            'created_at': time.time()
        })
        
        # Verify database
        assert user_id > 0
        
        db_query = DI.get('db_query')
        results = db_query("SELECT * FROM users WHERE id = ?", [user_id])
        
        assert len(results) == 1
        assert results[0]['username'] == username
        assert results[0]['email'] == email


@pytest.mark.integration
class TestUserAndMessageWorkflow:
    """Test user creation and message sending."""
    
    def test_user_sends_message(self, mock_db):
        """Test complete workflow: create user → send message."""
        db_insert = DI.get('db_insert')
        db_query = DI.get('db_query')
        
        # Create user
        user_id = db_insert('users', {
            'username': 'bob',
            'email': 'bob@example.com',
            'created_at': time.time()
        })
        
        # Send message
        msg_id = db_insert('messages', {
            'text': 'Hello world!',
            'sender_ip': '192.168.1.1',
            'sender_name': 'bob',
            'timestamp': time.time()
        })
        
        # Verify
        user = db_query("SELECT * FROM users WHERE id = ?", [user_id])
        message = db_query("SELECT * FROM messages WHERE id = ?", [msg_id])
        
        assert len(user) == 1
        assert len(message) == 1
        assert user[0]['username'] == 'bob'
        assert message[0]['sender_name'] == 'bob'
```

---

## Additional Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Coverage.py Documentation](https://coverage.readthedocs.io/)
- [Black Documentation](https://black.readthedocs.io/)
- [GitHub Actions Docs](https://docs.github.com/en/actions)
- [Bandit Security Documentation](https://bandit.readthedocs.io/)

---

**Testing Infrastructure Complete!**

Next steps:
1. Install requirements: `pip install -r requirements-dev.txt`
2. Setup hooks: `pre-commit install`
3. Run tests: `pytest tests/`
4. Check coverage: `pytest tests/ --cov`
5. Fix any issues: `black . && isort .`
