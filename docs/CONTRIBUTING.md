# Contributing to LANHub

**Guidelines for contributing to the LANHub project**

> Last Updated: April 2026

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Development Setup](#development-setup)
3. [Code Style](#code-style)
4. [Testing](#testing)
5. [Commit Guidelines](#commit-guidelines)
6. [Pull Requests](#pull-requests)
7. [Reporting Issues](#reporting-issues)
8. [Review Process](#review-process)

---

## Getting Started

### Prerequisites

- Python 3.10+
- Git
- Virtual environment (venv/virtualenv)

### Fork & Clone

```bash
# Fork the repo on GitHub
# Clone your fork
git clone https://github.com/YOUR_USERNAME/LANHub.git
cd LANHub

# Add upstream remote
git remote add upstream https://github.com/ORIGINAL_OWNER/LANHub.git
```

### Branches

**Main branch**: `main` (stable, production-ready)
**Development branch**: `develop` (staging, merges to main)
**Feature branches**: `feature/feature-name` (off develop)
**Bug fixes**: `fix/bug-name` (off develop)
**Hotfixes**: `hotfix/issue-name` (off main)

---

## Development Setup

### 1. Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Install Dependencies

```bash
# Production dependencies
pip install -r dependencies.txt

# Development dependencies
pip install -r config/requirements-dev.txt
```

### 3. Setup Pre-commit Hooks

```bash
pre-commit install -c config/.pre-commit-config.yaml
```

### 4. Verify Installation

```bash
# Run tests
pytest tests/

# Check code quality
black --check .
```

---

## Code Style

### Python Style Guide

Follow PEP 8 and these conventions:

#### Naming

```python
# Constants (UPPER_CASE)
MAX_MESSAGE_LENGTH = 500
DEFAULT_TIMEOUT = 30

# Classes (PascalCase)
class MessageValidator:
    pass

# Functions/Methods (snake_case)
def validate_message(text):
    pass

# Variables (snake_case)
message_count = 0
user_dict = {}

# Private (leading underscore)
def _internal_helper():
    pass
```

#### Code Organization

```python
"""Module docstring - describes file purpose."""

# Standard library imports
import json
import time
from typing import Dict, List

# Third-party imports
import requests
import flask

# Local imports
from shared.validators import validate_email
from dependencies import DI

# Constants
MAX_LENGTH = 500

# Module-level docstring
VALID_ROLES = ['admin', 'user', 'guest']


class MyClass:
    """Class docstring."""
    
    def __init__(self):
        """Initialize the class."""
        pass
    
    def public_method(self):
        """Public method."""
        pass
    
    def _private_method(self):
        """Private method - not part of public API."""
        pass


def module_function():
    """Function at module level."""
    pass
```

### Automatic Formatting

```bash
# Format code with Black
black .

# Sort imports with isort
isort .

# Do both
black . && isort .
```

### Comments & Docstrings

```python
def save_user(name: str, email: str) -> int:
    """Save user to database.
    
    Args:
        name: User's full name
        email: User's email address
    
    Returns:
        User ID if successful, -1 on error
    
    Raises:
        ValueError: If email is invalid
    """
    # This is a regular comment - explain WHY, not WHAT
    if not email or '@' not in email:
        raise ValueError("Invalid email")
    
    # Insert user
    user_id = DI.get('db_insert')('users', {
        'name': name,
        'email': email
    })
    return user_id
```

### Type Hints

```python
from typing import Dict, List, Optional, Tuple

def process_data(
    items: List[str],
    options: Optional[Dict[str, int]] = None
) -> Tuple[bool, str]:
    """Process items with optional config."""
    if options is None:
        options = {}
    # ...
    return True, "Success"

# Class attributes
class User:
    name: str
    age: int
    email: Optional[str] = None
```

---

## Testing

### Writing Tests

See [TESTING.md](https://github.com/theplatecrafter/LANHub/blob/main/docs/TESTING.md) for detailed testing guide.

**Quick summary:**
```python
import pytest
from dependencies import DI

@pytest.mark.unit
class TestMyFeature:
    """Test group for related tests."""
    
    def test_success_case(self, mock_db):
        """Test successful operation."""
        assert True
    
    def test_error_case(self, mock_db):
        """Test error handling."""
        with pytest.raises(ValueError):
            raise ValueError("Expected error")
```

### Run Tests

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=functions --cov=shared --cov-report=html

# Run specific test
pytest tests/test_db.py::TestDatabaseOperations::test_something
```

### Coverage Requirements

- Aim for 80%+ coverage on new code
- Always write tests before fixing bugs (TDD)
- Test both happy path and error cases

---

## Commit Guidelines

### Commit Messages

Follow standard format:

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Code style (formatting, semicolons, etc.)
- `refactor`: Code refactoring
- `perf`: Performance improvement
- `test`: Adding or updating tests
- `chore`: Build, dependencies, configuration

### Examples

```bash
# Good commit messages
git commit -m "feat(chat): add message encryption"
git commit -m "fix(auth): prevent SQL injection in login"
git commit -m "docs(README): update installation instructions"
git commit -m "test(validators): add email validation tests"
git commit -m "refactor(functions): extract message validation"
```

### Detailed Commit

```bash
git commit -m "feat(chat): add message encryption

- Implement AES-256 encryption for messages
- Add encryption key rotation
- Update message model with encrypted_text field
- Add tests for encryption/decryption

Closes #123"
```

### Writing Commit Messages

1. **Subject line** (50 characters max)
   - Imperative mood: "add" not "added"
   - Don't end with period
   - Example: "fix: resolve race condition in chat"

2. **Body** (72 characters per line)
   - Explain WHAT and WHY, not HOW
   - Separated from subject by blank line
   - Bullet points are okay
   - Example:
     ```
     Implement message rate limiting to prevent spam attacks.
     
     - Check message rate per IP/user
     - Return 429 Too Many Requests if limit exceeded
     - Make limit configurable via environment variable
     ```

3. **Footer** (for issues)
   - Reference GitHub issues
   - Example: `Closes #123` or `Fixes #456`

---

## Pull Requests

### Before Creating PR

1. **Update from upstream**
   ```bash
   git fetch upstream
   git rebase upstream/develop  # Or main if hotfix
   ```

2. **Run tests**
   ```bash
   pytest tests/ --cov
   ```

3. **Check code quality**
   ```bash
   black --check .
   flake8 .
   pylint functions/
   mypy .
   ```

4. **Fix issues**
   ```bash
   black .
   isort .
   ```

### Creating PR

1. **Push to your fork**
   ```bash
   git push origin feature/my-feature
   ```

2. **Create PR on GitHub**
   - Base branch: `develop` (or `main` for hotfix)
   - Title: Clear, descriptive title
   - Description: What, why, how

### PR Description Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation

## Related Issues
Fixes #123

## Testing
Describe testing done:
- [ ] Unit tests added
- [ ] Integration tests passed
- [ ] Manual testing completed

## Checklist
- [ ] Code follows style guidelines
- [ ] Tests pass locally
- [ ] No new warnings from linters
- [ ] Documentation updated
- [ ] Pre-commit hooks pass
```

### PR Review Process

1. **Changes requested** → Update code and push
2. **Approved** → Maintainer merges
3. **CI/CD checks** → Must pass before merge

---

## Reporting Issues

### Issue Title

Be specific and descriptive:
- ❌ Bad: "It doesn't work"
- ✅ Good: "Chat messages fail to send with TypeError when user has special characters in name"

### Issue Description

Use template:

```markdown
## Description
Brief description of the issue

## Steps to Reproduce
1. Do this
2. Then do this
3. Issue occurs

## Expected Behavior
What should happen

## Actual Behavior
What actually happens

## Environment
- OS: macOS/Windows/Linux
- Python version: 3.10
- Browser: Chrome 90

## Logs/Error Messages
```
Error traceback here
```

## Possible Solution
(Optional) Any ideas for fixing this?
```

### Issue Labels

- `bug` - Something broken
- `enhancement` - Feature request
- `documentation` - Docs improvement
- `good first issue` - Easy for newcomers
- `help wanted` - Need assistance

---

## Review Process

### Code Review Checklist

Reviewers check:

1. **Functionality**
   - Does it do what it claims?
   - Edge cases handled?
   - No obvious bugs?

2. **Code Quality**
   - Follows style guide?
   - Well-documented?
   - DRY principle applied?

3. **Tests**
   - Tests added/updated?
   - Coverage adequate?
   - Tests passing?

4. **Performance**
   - Any performance regressions?
   - Database queries optimized?

5. **Security**
   - Any security vulnerabilities?
   - Input validation present?
   - SQL injection aware?

### Addressing Feedback

1. Read feedback carefully
2. Make changes
3. Push commits to same branch
4. Respond to comments
5. Mark as "Ready for review"

---

## Dependencies

### Adding Dependencies

**From PyPI:**
```bash
pip install new_package
pip freeze | grep new_package >> requirements.txt
```

### Update Requirements

```bash
# Generate complete requirements
pip freeze > requirements.txt

# Or manually edit and test
pip install -r requirements.txt
```

### Development Dependencies

Located in `requirements-dev.txt`:
- pytest
- pytest-cov
- black
- isort
- flake8
- pylint
- mypy
- bandit
- pre-commit

---

## Documentation

### Writing Docs

1. **Markdown format** (.md files)
2. **Clear headings** - Use # ## ### format
3. **Code examples** - Include working examples
4. **Links** - Use relative paths for internal links

### Update These Files

- `README.md` - Overview and setup
- `ARCHITECTURE.md` - System design
- `TESTING.md` - Test guide
- `CONTRIBUTING.md` - This file
- API docs in docstrings

---

## Questions?

- Open a GitHub issue with `question` label
- Check existing documentation
- Look at similar implementations in codebase

---

## Also See

- [TESTING.md](https://github.com/theplatecrafter/LANHub/blob/main/docs/TESTING.md) - Testing guide
- [ARCHITECTURE.md](https://github.com/theplatecrafter/LANHub/blob/main/docs/ARCHITECTURE.md) - Project structure
- [README.md](https://github.com/theplatecrafter/LANHub/blob/main/docs/README.md) - Project overview

---

**Thank you for contributing to LANHub!** 🎉
