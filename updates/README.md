# LANHub System-Level Updates

This directory contains system-level update scripts for LANHub. These scripts handle changes that go beyond simple dependency updates (e.g., Docker image builds, configuration migrations, system package installations).

## How It Works

When LANHub starts (or when an admin manually checks), the update system:

1. **Scans** the `updates/` directory for new versions
2. **Checks** the update manifest to see which have already been applied
3. **Executes** pending updates in version order (e.g., v1.1.0 before v1.2.0)
4. **Logs** success/failure to `logs/updates.log`
5. **Notifies** admin if a restart or manual action is needed

## Structure

Each version gets its own directory:

```
updates/
  v1.1.0/
    001_docker_lab_setup.sh     # Install Docker & build Lab image
    002_systemd_unit.sh         # Update systemd service file
  v1.2.0/
    001_migrate_config.sh       # Config schema migration
```

Updates within a version run sequentially (001, 002, etc.).

## Creating an Update Script

### File Naming
- Use three-digit prefixes: `001_`, `002_`, etc.
- Format: `NNN_description_of_change.sh`

### Script Header
Every update script **must** include metadata in its shell comment:

```bash
#!/bin/bash
# Update: Docker Lab Setup
# Version: 1.1.0
# Requires restart: no
# Requires sudo: yes
# Requires input: no (or yes with description)
# Description: Install Docker and build the lanhub-lab:latest image

set -e
```

### Exit Codes
- **0**: Success — apply next update
- **1**: Failure — stop and notify admin
- **2**: Already applied — skip silently

### Key Guidelines

1. **Idempotent**: Must be safe to run multiple times
   ```bash
   # ✓ Good: Check first, only apply if needed
   if ! docker image inspect lanhub-lab:latest >/dev/null 2>&1; then
       docker build -f Dockerfile.lab -t lanhub-lab:latest .
   fi
   
   # ✗ Bad: Will fail on second run
   docker build -f Dockerfile.lab -t lanhub-lab:latest .
   ```

2. **Fail gracefully**: Catch errors and return appropriate exit code
   ```bash
   if ! some_command; then
       echo "ERROR: Failed to do X" >&2
       exit 1
   fi
   ```

3. **Use sudo only when needed**: If `Requires sudo: yes`, the function will handle elevation
   ```bash
   # Script will be run with: sudo ./script.sh
   # So you can use sudo directly inside
   sudo systemctl restart something
   ```

4. **Interactive prompts**: If `Requires input: yes`, describe what the admin needs to do
   ```bash
   # ── Interactive Input ─────────────────────────────────────────────────────
   # This update needs to know your GitHub user for SSH key setup.
   if [ -z "$GITHUB_USER" ]; then
       read -p "GitHub username: " GITHUB_USER
   fi
   ```

5. **Logging**: Use echo for user feedback, stderr for errors
   ```bash
   echo "Building Docker image..."
   if ! docker build -f Dockerfile.lab -t lanhub-lab:latest .; then
       echo "ERROR: Docker build failed" >&2
       exit 1
   fi
   echo "✓ Docker image built"
   ```

## Triggering Updates

### Automatic (On Startup)
The app checks for pending updates when:
- Server starts (`app.py` initialization)
- Admin clicks "Check for Updates" in Admin Panel

### Manual (Command Line)
```bash
python3 functions/updates.py check
python3 functions/updates.py apply
```

## Rollback

If an update fails:
1. The system stops execution and logs the error
2. Previous successful updates are **not** rolled back (this is intentional — updates are expected to be reversible or safe)
3. Admin is notified and can investigate logs/updates.log
4. When fixed, the failed update can be re-applied without re-applying earlier ones

## Manifest File

Applied updates are tracked in `.lanhub_updates_manifest` (JSON):

```json
{
  "last_check": "2026-04-08T10:30:00Z",
  "applied": {
    "v1.1.0": ["001_docker_lab_setup", "002_systemd_unit"],
    "v1.2.0": ["001_migrate_config"]
  }
}
```

This prevents re-running the same update twice.

## Examples

### Example 1: Docker Image Build
See: `v1.1.0/001_docker_lab_setup.sh`

### Example 2: System Package Installation
```bash
#!/bin/bash
# Update: Install Additional Libraries
# Version: 1.1.0
# Requires restart: no
# Requires sudo: yes
# Requires input: no

set -e

# Check if already installed
if dpkg -l | grep -q "^ii  libsomething"; then
    exit 2  # Already applied
fi

echo "Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y libsomething-dev

echo "✓ System packages installed"
```

### Example 3: Configuration Migration
```bash
#!/bin/bash
# Update: Migrate config schema
# Version: 1.2.0
# Requires restart: yes
# Requires sudo: no
# Requires input: no

set -e

if [ ! -f "configvars.json" ]; then
    exit 2  # Already done or config not set up
fi

echo "Migrating configuration..."
./venv/bin/python3 << 'PYEOF'
import json

with open("configvars.json", "r") as f:
    cfg = json.load(f)

# Add new field with default value
cfg.setdefault("lab", {})["default_project_quota"] = 5

with open("configvars.json", "w") as f:
    json.dump(cfg, f, indent=2)

print("✓ Configuration migrated")
PYEOF
```

## Testing an Update Locally

```bash
# Add to a new version directory
mkdir -p updates/v1.99.0
cat > updates/v1.99.0/001_test.sh << 'EOF'
#!/bin/bash
# Update: Test Update
# Version: 1.99.0
# Requires restart: no
# Requires sudo: no
# Requires input: no

set -e
echo "This is a test update"
EOF

chmod +x updates/v1.99.0/001_test.sh

# Manually trigger (from project root)
python3 functions/updates.py apply
```

## Troubleshooting

**Q: An update failed. What do I do?**
- Check `logs/updates.log` for details
- Fix the underlying issue (e.g., install Docker)
- The update will auto-retry on next startup, or run `python3 functions/updates.py apply` manually

**Q: Can I roll back an update?**
- Not automatically. Each update is expected to be idempotent or reversible.
- If an update is broken, the soonest approach is to fix the script and re-run it.

**Q: How do I skip an update?**
- Removes its entry from `.lanhub_updates_manifest` json so it will re-run on next check
- Or manually edit `.lanhub_updates_manifest` and remove the update from the applied list

**Q: The update says it requires sudo but isn't asking for my password**
- If you're already root (via `sudo -i`), it won't re-ask
- Otherwise, the update system will sudo and handle password prompts

---

For questions or to propose a new update, see [DEVELOPER_GUIDE.md](../docs/DEVELOPER_GUIDE.md).
