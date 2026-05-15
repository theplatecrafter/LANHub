# HansHub Configuration Files

This directory contains configuration files and examples for HansHub development and deployment.

## Contents

- **pytest.ini** - Pytest configuration for testing
- **requirements-dev.txt** - Development dependencies (use: `pip install -r config/requirements-dev.txt`)
- **.pre-commit-config.yaml** - Pre-commit hook configuration (use: `pre-commit install -c config/.pre-commit-config.yaml`)
- **.bandit** - Bandit security scanning configuration
- **configvars.example.json** - Example configuration (copy to root as `configvars.json`)

## Setup Commands

```bash
# Install development dependencies
pip install -r config/requirements-dev.txt

# Setup pre-commit hooks
pre-commit install -c config/.pre-commit-config.yaml

# Create runtime configuration
cp config/configvars.example.json ../configvars.json
```

## Files

### pytest.ini
Configuration for pytest test runner. Referenced in `pytest` command.

### requirements-dev.txt
Development dependencies including:
- Testing: pytest, pytest-cov
- Code quality: black, isort, flake8, pylint, mypy
- Security: bandit, safety
- Automation: pre-commit

### .pre-commit-config.yaml
Defines pre-commit hooks for:
- Code formatting (Black, isort)
- Linting (Flake8, Pylint)
- Type checking (mypy)
- Security (Bandit)
- File checks (YAML, JSON, etc.)

### configvars.example.json
Template for runtime configuration. Copy to root and customize for your environment.
