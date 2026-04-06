# LANHub Setup & Verification Checklist

**Complete checklist for LANHub development environment setup and verification**

---

## ✅ Installation Checklist

### Prerequisites
- [ ] Python 3.10 or higher installed (`python --version`)
- [ ] Git installed (`git --version`)
- [ ] Access to LANHub repository
- [ ] Text editor or IDE (VS Code recommended)

### Initial Setup
- [ ] Clone repository: `git clone <url>`
- [ ] Navigate to directory: `cd LANHub`
- [ ] Create virtual environment: `python -m venv venv`
- [ ] Activate virtual environment:
  - [ ] Linux/Mac: `source venv/bin/activate`
  - [ ] Windows: `venv\Scripts\activate`

### Install Dependencies
- [ ] Install production deps: `pip install -r dependencies.txt`
- [ ] Install dev deps: `pip install -r requirements-dev.txt`
- [ ] Verify installation: `pip list | grep -E "pytest|black|flask"`

### Setup Development Tools
- [ ] Install pre-commit hooks: `pre-commit install`
- [ ] Verify hooks: `pre-commit run --all-files`
- [ ] Check Black: `black --version`
- [ ] Check isort: `isort --version`
- [ ] Check Flake8: `flake8 --version`
- [ ] Check pytest: `pytest --version`
- [ ] Check mypy: `mypy --version`

---

## 🧪 Testing Verification

### Run Tests
- [ ] Run all tests: `pytest tests/ -v`
- [ ] All tests should PASS ✓
- [ ] No errors or failures

### Test Coverage
- [ ] Run with coverage: `pytest tests/ --cov=functions --cov=shared --cov-report=html`
- [ ] Open coverage report: `open htmlcov/index.html`
- [ ] Coverage meets targets (80%+ functions, 90%+ shared)

### Specific Test Files
- [ ] Database tests pass: `pytest tests/test_db.py -v`
- [ ] Validator tests pass: `pytest tests/test_validators.py -v`
- [ ] Admin tests pass: `pytest tests/test_admin.py -v`

---

## 🎨 Code Quality Verification

### Formatting
- [ ] Format code: `black .`
- [ ] Check formatting: `black --check .`
- [ ] Output shows "All done! ✓"

### Import Sorting
- [ ] Sort imports: `isort .`
- [ ] Check sorting: `isort --check-only .`
- [ ] No import errors

### Linting
- [ ] Run Flake8: `flake8 . --max-line-length=100`
- [ ] Number of errors should be 0 or minimal
- [ ] Review any reported issues

### Pylint Analysis
- [ ] Run Pylint: `pylint functions/ --exit-zero`
- [ ] Review output for critical issues
- [ ] Check docstring coverage

### Type Checking
- [ ] Run mypy: `mypy . --ignore-missing-imports`
- [ ] Review type errors
- [ ] Add type hints where needed

### Security Scanning
- [ ] Run Bandit: `bandit -r . -ll`
- [ ] Review security issues
- [ ] Address any high-priority findings

---

## 🔧 Pre-commit Hooks Verification

### Hook Installation
- [ ] Check hooks installed: `ls -la .git/hooks/pre-commit*`
- [ ] File should exist and be executable

### Manual Execution
- [ ] Run all hooks: `pre-commit run --all-files`
- [ ] All hooks should pass or be fixed
- [ ] Review output for any failures

### Specific Hooks
- [ ] Black hook: `pre-commit run black --all-files`
- [ ] isort hook: `pre-commit run isort --all-files`
- [ ] Flake8 hook: `pre-commit run flake8 --all-files`
- [ ] mypy hook: `pre-commit run mypy --all-files`
- [ ] Bandit hook: `pre-commit run bandit --all-files`

---

## 📚 Documentation Verification

### Files exist
- [ ] [QUICK_START.md](QUICK_START.md) exists and is readable
- [ ] [TESTING.md](TESTING.md) exists and is readable
- [ ] [CONTRIBUTING.md](CONTRIBUTING.md) exists and is readable
- [ ] [ARCHITECTURE.md](ARCHITECTURE.md) exists and is readable
- [ ] [DOCUMENTATION_SUMMARY.md](DOCUMENTATION_SUMMARY.md) exists and is readable
- [ ] [README_DEVELOP.md](README_DEVELOP.md) exists and is readable

### Documentation Content
- [ ] QUICK_START.md has setup instructions
- [ ] TESTING.md has testing guide
- [ ] CONTRIBUTING.md has code style guide
- [ ] ARCHITECTURE.md has system design
- [ ] All links work correctly

---

## ⚙️ Project Structure Verification

### Essential Files
- [ ] `app.py` exists (main application)
- [ ] `config.py` exists (configuration)
- [ ] `functions.py` exists (utilities)
- [ ] `dependencies.py` exists (DI container)
- [ ] `pytest.ini` exists (pytest config)

### Essential Directories
- [ ] `blueprints/` exists (feature modules)
- [ ] `socket_events/` exists (WebSocket handlers)
- [ ] `templates/` exists (HTML templates)
- [ ] `static/` exists (CSS/JS assets)
- [ ] `tests/` exists (test files)

### Configuration Files
- [ ] `.pre-commit-config.yaml` exists
- [ ] `.github/workflows/ci-cd.yml` exists
- [ ] `requirements-dev.txt` exists
- [ ] `dependencies.txt` exists
- [ ] `configvars.json` exists

---

## 🚀 First Commit Verification

### Before Committing
- [ ] Made changes to appropriate files
- [ ] Written tests for changes
- [ ] All tests pass: `pytest tests/ -v`
- [ ] Code formatted: `black .`
- [ ] Imports sorted: `isort .`
- [ ] No lint issues: `flake8 .`

### Making First Commit
- [ ] Stage changes: `git add .`
- [ ] Check status: `git status`
- [ ] Run pre-commit: `pre-commit run --all-files`
- [ ] All hooks pass
- [ ] Commit with message: `git commit -m "feat(module): description"`
- [ ] Message follows format from CONTRIBUTING.md

### Pushing Changes
- [ ] Create feature branch: `git checkout -b feature/name`
- [ ] Push branch: `git push origin feature/name`
- [ ] Create pull request on GitHub
- [ ] Use PR template from CONTRIBUTING.md

---

## 🐛 Troubleshooting Checklist

### Environment Issues
- [ ] Virtual environment active (prompt shows `(venv)`)
- [ ] Python version correct: `python --version`
- [ ] Pip pointing to venv: `which pip` or `where pip`
- [ ] All packages installed: `pip list`

### Test Issues
- [ ] Database file writable: `ls -la app.db`
- [ ] Test fixtures working: `pytest tests/conftest.py -v`
- [ ] DI container functional: `python -c "from dependencies import DI"`
- [ ] Database connection works: `pytest tests/test_db.py::TestDatabaseOperations::test_get_db_returns_connection -v`

### Formatting Issues
- [ ] Black finds issues: `black --check .`
- [ ] isort finds issues: `isort --check-only .`
- [ ] Run fixes: `black . && isort .`
- [ ] Verify fixed: `black --check . && isort --check-only .`

### Pre-commit Issues
- [ ] Hooks installed: `pre-commit install`
- [ ] Hooks up to date: `pre-commit autoupdate`
- [ ] Try skipping for one commit: `git commit --no-verify`
- [ ] Clean and reinstall: `pre-commit clean && pre-commit install`

### Import Issues
- [ ] Check Python path: `python -c "import sys; print(sys.path)"`
- [ ] Directory in path: `ls -la functions.py shared.py`
- [ ] Try direct import: `python -c "import functions as f"`
- [ ] Check __init__.py files: `ls -la tests/__init__.py`

---

## 📋 Daily Development Checklist

### Start of Day
- [ ] Activate virtual environment
- [ ] Pull latest changes: `git pull origin develop`
- [ ] Install any new dependencies: `pip install -r requirements-dev.txt`
- [ ] Run tests to verify setup: `pytest tests/`

### Before Each Commit
- [ ] Write tests for changes
- [ ] Run tests: `pytest tests/ -v`
- [ ] Format code: `black .`
- [ ] Sort imports: `isort .`
- [ ] Check style: `flake8 .`
- [ ] Type check: `mypy .`
- [ ] Verify hooks pass (automatic on commit)

### Before Creating PR
- [ ] All tests pass with coverage: `pytest tests/ --cov`
- [ ] Clean working directory: `git status` (should show unpushed)
- [ ] Follow commit message format
- [ ] Add tests for new features
- [ ] Update docs if needed
- [ ] Use PR template

### End of Day
- [ ] Commit work: `git commit -m "..."`
- [ ] Push branch: `git push origin feature/name`
- [ ] Update PR with progress notes
- [ ] Review for any failing CI/CD checks

---

## ✨ Advanced Verification

### Performance
- [ ] Tests run in < 5 seconds: `time pytest tests/`
- [ ] Formatting completes < 1 second: `time black .`
- [ ] No obvious performance issues in code

### Security
- [ ] No hardcoded credentials in code
- [ ] No secrets in commits: `git log -p | grep -i secret`
- [ ] Bandit scan passes: `bandit -r . -ll`
- [ ] Safety check passes: `safety check`

### Documentation
- [ ] Code has docstrings for public functions
- [ ] Complex logic has explanatory comments
- [ ] README updated if adding features
- [ ] Examples provided for new APIs

### Git Workflow
- [ ] On correct branch: `git branch`
- [ ] Tracking upstream: `git remote -v`
- [ ] No merge conflicts: `git status`
- [ ] Clean commit history: `git log --oneline -5`

---

## 🎯 Sign-Off

**I have verified:**
- [ ] All prerequisites installed
- [ ] Development environment set up
- [ ] Tests passing
- [ ] Code quality checks passing
- [ ] Pre-commit hooks working
- [ ] Documentation accessible
- [ ] Project structure correct
- [ ] Ready to develop

**Environment Status:** ✅ READY

**Next Step:** Read [QUICK_START.md](QUICK_START.md) or [CONTRIBUTING.md](CONTRIBUTING.md)

---

**Date Verified:** ________________
**Developer Name:** ________________
**Notes:** ________________________________________________________________

