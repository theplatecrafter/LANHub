# System Updates Infrastructure

This document describes LANHub's system-level update framework for managing infrastructure changes, Docker updates, and system-wide configurations.

## Overview

The system update framework automatically manages version updates and infrastructure changes without requiring manual intervention or deployment restarts.

**Key Features:**
- ✓ Automatic detection of pending updates on startup
- ✓ Non-blocking update execution (no password prompts)
- ✓ Real-time progress visualization with streaming output
- ✓ Persistent tracking to prevent re-running completed updates
- ✓ Admin panel integration for manual control
- ✓ Full logging and error reporting

## Architecture

### Update Detection
When LANHub starts, it scans the `updates/` directory for pending updates:
```
updates/
  v1.1.0/
    001_docker_lab_setup.sh      ← Update script with metadata
```

Each update has metadata in its header:
```bash
# Requires restart: no              # Will this require app restart?
# Requires sudo: yes                # Will this need elevated privileges?
# Requires input: no                # Will this prompt the user?
```

### Update Execution
1. **Detection**: `check_for_updates()` scans `updates/` and compares against `.lanhub_updates_manifest`
2. **Application**: `apply_pending_updates()` executes scripts with real-time output streaming
3. **Tracking**: `.lanhub_updates_manifest` (JSON file) records successful completions

### Update Lifecycle

```
App Startup
  ↓
Check for updates (scan updates/v*/*.sh)
  ↓
Compare against .lanhub_updates_manifest
  ↓
Found pending updates?
  ├─ YES → Auto-apply (unless LANHUB_SKIP_AUTO_UPDATES=1)
  │         └─ Execute scripts with progress logging
  │         └─ Update manifest if successful
  └─ NO  → Log "All up to date"
```

## Auto-Apply Behavior

**Default (Production)**: Auto-apply pending updates on startup
- Non-interactive execution
- Real-time output to app logs
- Graceful error handling with helpful messages

**Developer Override**: Skip auto-apply with environment variable
```bash
LANHUB_SKIP_AUTO_UPDATES=1 python3 app.py
```

## Write an Update Script

Create a new update in `updates/vX.Y.Z/`:

1. **Create directory**: `mkdir -p updates/v1.2.0/`
2. **Create script**: `updates/v1.2.0/001_feature_name.sh`
3. **Add metadata header**:
   ```bash
   #!/bin/bash
   # Update: Feature Name
   # Version: 1.2.0
   # Requires restart: no|yes
   # Requires sudo: yes|no
   # Requires input: yes|no
   # Description: What this update does...
   ```
4. **Make executable**: `chmod +x updates/v1.2.0/001_feature_name.sh`
5. **Test locally** before committing

### Update Script Best Practices

#### Progress Output
Use colored indicators for user feedback:
```bash
# Helper functions (match install.sh style)
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[UPDATE]${RESET} $*"; }
success() { echo -e "${GREEN}[✓]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $*"; }

# Use in your script:
info "Starting long operation..."
success "Operation completed successfully"
warn "Non-critical issue found"
```

#### Idempotency (Run Multiple Times Safely)
```bash
# Check if already done
if [ -f "/path/to/done.marker" ]; then
    success "Already completed"
    exit 0
fi

# Do work...

# Mark as done
touch "/path/to/done.marker"
success "Update completed"
```

#### Non-Interactive Sudo
Use `sudo -n` (no password prompt) or check for docker group membership:
```bash
run_docker() {
    # Try without sudo first (user in docker group)
    if docker "$@" 2>/dev/null; then
        return 0
    fi
    # Fall back to passwordless sudo
    if sudo -n docker "$@" 2>/dev/null; then
        return 0
    fi
    # If both fail, show the original error
    docker "$@"
    return $?
}
```

#### Download Progress
Show progress bars for downloads:
```bash
# Instead of: curl -sSL url -o file (silent)
# Use:        curl -f# url -o file    (progress bar)

echo "  Downloading..."
curl -f# "https://example.com/large-file" -o /tmp/file
if [ $? -eq 0 ]; then
    success "Download complete"
else
    error "Download failed"
fi
```

#### Real-Time Streaming
Pipe output line-by-line for immediate visibility:
```bash
# Instead of: long_command >output.log 2>&1 && show_result
# Use:        long_command 2>&1 | while read line; do echo "  $line"; done

docker build . 2>&1 | while IFS= read -r line; do
    if [[ "$line" =~ ^Step ]]; then
        echo -e "  ${GREEN}→${RESET} $line"
    else
        echo "    $line"
    fi
done
```

## Current Updates

### v1.1.0 — Docker Lab Setup
**Location**: `updates/v1.1.0/001_docker_lab_setup.sh`

**What it does**:
1. Checks if Docker is installed (installs if not)
2. Ensures Docker daemon is running
3. Verifies Docker is accessible (user in docker group or passwordless sudo)
4. Builds `lanhub-lab:latest` image for Lab feature

**Execution Time**: 2-5 minutes (depends on internet and hardware)

**Progress Indicators**:
- `→` Build step starting
- `✓` Build step completed
- `⋯` In progress
- `↓` Download in progress
- `✗` Error/failure

**Requirements**:
- `sudo -n` access (no password prompt) OR user in docker group
- ~5GB free disk space
- Internet connection for Docker image layers

## Admin Panel Integration

### Check Updates
**Route**: `GET /admin/server/system-updates`

Response:
```json
{
  "v1.1.0": ["001_docker_lab_setup"],
  "v1.2.0": ["001_new_feature"]
}
```

### Apply Updates
**Route**: `POST /admin/server/system-updates/apply`

Response: Real-time streaming of script output

**Access**: Admin panel → Server → 🔧 System Updates

## Logging

All update activity is logged to `logs/`:
```
[UPDATE] Found 1 pending system updates
[UPDATE] Applying pending system updates automatically...
  [UPDATE] → Step 1/10: ...
  [UPDATE] → Step 2/10: ...
[UPDATE] ✓ All system updates applied successfully
```

Users can monitor progress:
1. **Admin Panel**: Browse to Settings → System Updates (real-time)
2. **App Logs**: View through app's logging interface
3. **Terminal**: `tail -f logs/app.log | grep UPDATE`

## Troubleshooting

### Update Appears Multiple Times
Check `.lanhub_updates_manifest` — if an update isn't recorded, it will re-run.

```bash
cat .lanhub_updates_manifest
```

### Update Fails with "Permission denied"
The update script needs passwordless sudo. Fix with:

```bash
# Option A: Add user to docker group (if update involves Docker)
sudo usermod -aG docker $USER
# Then log out and back in

# Option B: Allow specific commands without password
sudo visudo
# Add: $USER ALL=(ALL) NOPASSWD: /usr/bin/docker, /usr/bin/systemctl
```

### Update Hangs or Takes Forever
Check for:
1. Network connectivity issues
2. System resource constraints (free disk space, RAM)
3. Log output (tail -f logs/) for stuck operations

To debug:
```bash
# Check if update process is still running
ps aux | grep "001_"

# Look for specific errors
grep -i "error\|fail" logs/app.log
```

### Skip Auto-Apply (For Testing)
```bash
# Start app without auto-applying updates
LANHUB_SKIP_AUTO_UPDATES=1 python3 app.py
```

Then apply manually via admin panel or CLI:
```bash
python3 functions/system_updates.py --apply
```

## CLI Interface

### Check for updates
```bash
python3 functions/system_updates.py --check
```

### Apply all pending updates
```bash
python3 functions/system_updates.py --apply
```

### Show update status
```bash
python3 functions/system_updates.py --status
```

## Implementation Details

### files/system_updates.py
Core module for update management:
- `check_for_updates()` - Scan and detect pending updates
- `apply_pending_updates(allow_interactive)` - Execute with progress
- `get_update_status()` - Return pending updates dict
- `_load_manifest()` / `_save_manifest()` - Tracking storage

### .lanhub_updates_manifest
JSON file tracking all applied updates:
```json
{
  "v1.1.0": ["001_docker_lab_setup"],
  "v1.2.0": ["001_new_feature"],
  "history": {
    "v1.1.0": {
      "001_docker_lab_setup": {
        "applied_at": "2024-01-15T10:30:45.123456",
        "status": "success"
      }
    }
  }
}
```

### Admin Panel Routes
- `GET /admin/server/system-updates` - List pending updates
- `POST /admin/server/system-updates/apply` - Apply all pending
- `GET /admin/server/system-updates-output` - Stream progress (SSE)

## Related Documentation

- [DEPLOYMENT.md](./DEPLOYMENT.md) - Production deployment guide
- [DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md) - Development setup
- [CONTRIBUTING.md](./CONTRIBUTING.md) - Contributing updates/features
