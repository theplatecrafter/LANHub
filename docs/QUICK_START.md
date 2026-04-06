# LANHub Quick Start Guide

**Get up and running with LANHub development in 5 minutes**

---

## ⚡ Quick Setup (5 minutes)

### 1. Clone & Enter Directory
```bash
git clone https://github.com/YOUR_USERNAME/LANHub.git
cd LANHub
```

### 2. Create Virtual Environment
```bash
python -m venv venv
source venv/bin/activate          # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r dependencies.txt
pip install -r config/requirements-dev.txt
```

### 4. Setup Pre-commit Hooks
```bash
pre-commit install -c config/.pre-commit-config.yaml
```

### 5. Run Tests
```bash
pytest tests/
```

✅ **Done!** You're ready to develop.

---

## 🚀 Common Commands

### Testing
```bash
pytest tests/                               # Run all tests
pytest tests/ -v                           # Verbose output
pytest tests/ --cov                        # With coverage
pytest tests/test_db.py                    # Specific test file
pytest tests/ -k "test_name"               # Run matching tests
pytest tests/ -x                           # Stop on first failure
pytest tests/ --pdb                        # Debug mode
```

### Code Quality
```bash
black .                                    # Format code
isort .                                    # Sort imports
flake8 .                                   # Linting
pylint functions/                          # Analysis
mypy .                                     # Type check
bandit -r .                                # Security scan
```

### All at Once
```bash
black . && isort . && flake8 . && pytest tests/
```

---

## 📁 Project Structure

```
LANHub/
├── blueprints/          # Flask blueprint modules
├── socket_events/       # WebSocket event handlers
├── static/              # Frontend assets (CSS, JS)
├── templates/           # HTML templates
├── files/               # Uploaded files storage
├── logs/                # Application logs
├── tests/               # Test files
├── app.py               # Main Flask app
├── functions.py         # Utility functions
├── config.py            # Configuration
├── scheduler.py         # Task scheduler
└── README.md, TESTING.md, CONTRIBUTING.md  # Docs
```

---

## 🧪 Writing Your First Test

Create `tests/test_example.py`:

```python
import pytest
from dependencies import DI

@pytest.mark.unit
def test_simple_function(mock_db):
    """Test a simple function."""
    # Setup
    from functions import some_function
    
    # Test
    result = some_function(args)
    
    # Verify
    assert result == expected_value
```

Run it:
```bash
pytest tests/test_example.py -v
```

---

## 📝 Making Changes

### 1. Create a Feature Branch
```bash
git checkout -b feature/my-feature
```

### 2. Make Changes & Write Tests
```bash
# Edit code
vim path/to/file.py

# Write tests
vim tests/test_something.py

# Run tests
pytest tests/
```

### 3. Format & Lint
```bash
black . && isort .
```

### 4. Commit
```bash
git add .
git commit -m "feat(module): description of change"
```

### 5. Push & Create PR
```bash
git push origin feature/my-feature
```

Then create a PR on GitHub.

---

## 🐛 Debugging

### Print Statements
```bash
pytest tests/ -s                          # Show print output
```

### Python Debugger
```bash
pytest tests/ --pdb                       # Drop into debugger on failure
pytest tests/ --trace                     # Drop into debugger at start
```

### Or use pdb in code:
```python
import pdb; pdb.set_trace()
```

---

## 📚 More Info

- **[TESTING.md](TESTING.md)** - Detailed testing guide
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Code style & PR process
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System design
- **[README.md](README.md)** - Project overview

---

## ❓ Troubleshooting

### `ModuleNotFoundError: No module named 'functions'`
```bash
# Make sure you're in the LANHub directory
cd /path/to/LANHub

# Reinstall dependencies
pip install -r dependencies.txt
```

### Pre-commit hooks failing
```bash
# Run Black & isort to fix most issues
black . && isort .

# Then try again
git commit -m "fix: resolve formatting issues"
```

### Tests not running
```bash
# Verify pytest is installed
pip install pytest

# Check test folder exists
ls -la tests/

# Run with absolute import path
python -m pytest tests/
```

### Database errors in tests
```bash
# Reset the test database
rm -f tests/test.db

# Run tests again
pytest tests/
```

---

## 💡 Tips

- **Before push**: Run `black . && isort . && pytest tests/`
- **Small commits**: Commit related changes together
- **Good messages**: Use `feat:`, `fix:`, `docs:` prefixes
- **Test first**: Write tests before/during development
- **Ask for help**: Open issues with clear examples
- **Keep learning**: Check existing code for patterns

---

## 🎉 You're Set!

Start with:
1. Pick an issue from GitHub (look for `good first issue`)
2. Create a branch: `git checkout -b feature/issue-name`
3. Write code + tests
4. Run: `black . && isort . && pytest tests/`
5. Push & create PR

Questions? Check the docs or open an issue!

**Happy coding! 🚀**
