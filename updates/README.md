# HansHub Update System

## Overview

The HansHub update system allows server administrators to apply incremental updates to a running deployment. The system tracks which updates have been applied and prevents duplicate execution.

## Files

- **`updates.json`** (Git-tracked): Master manifest of all available updates
  - Contains metadata for each update: version, description, path to script, created timestamp
  - Synced with the repository during `git pull`

- **`updated.json`** (Local/Git-ignored): Local tracking of applied updates
  - Records which updates have already been run on this server
  - Auto-created if missing
  - Updated after each successful update

- **`*.sh` files** (Git-tracked): Individual update scripts
  - Each script perform specific update tasks (dependencies, migrations, rebuilds, etc.)
  - Referenced from `updates.json`
  - Can request interactive input and sudo passwords

## Usage

Run the update process from the HansHub root directory:

```bash
bash update.sh
```

### What happens:

1. Activates the Python virtual environment
2. Pulls latest code from the repository
3. Creates `updated.json` if it doesn't exist
4. Compares available updates (from `updates.json`) against applied updates (from `updated.json`)
5. Displays all pending updates with descriptions
6. Prompts for confirmation: `Apply updates? (Y/n)`
7. Runs each pending update script in chronological order (sorted by `created_at`)
8. Allows scripts to request interactive input (user input, sudo password, etc.)
9. Records each successful update in `updated.json`
10. Stops on first failure and shows which updates were partially applied

## Creating New Updates

To add a new update:

### 1. Create the update script

Create a new file in the `updates/` directory, e.g., `updates/2.0-migration.sh`:

```bash
#!/bin/bash
set -e

source venv/bin/activate

# Your update logic here
pip install -r dependencies.txt
python -m upgrade_database

echo "✓ Update completed successfully"
```

### 2. Update `updates.json`

Add an entry to `updates/updates.json`:

```json
{
  "2.0 Migration": {
    "id": 1,
    "version": "2.0.0",
    "path": "updates/2.0-migration.sh",
    "description": "Database migration to v2.0 schema and dependency updates",
    "created_at": 1712800000,
    "tags": ["migration", "database"]
  }
}
```

**Important:**
- Use a unique `id` (increment from the last highest ID)
- Use a unique `created_at` timestamp (use `date +%s` to get current Unix timestamp)
- Keep `created_at` in chronological order (earlier updates should have earlier timestamps)

### 3. Commit to Git

```bash
git add updates/2.0-migration.sh updates/updates.json
git commit -m "Add v2.0 migration update"
git push
```

## Example Flow

**First run after new updates are available:**

```
===============================================================================
PENDING UPDATES

1. v1.1.0       Dependencies Update
   Description: Installs latest Python dependencies
   Path: updates/dependencies-1.1.sh
   Tags: dependencies, bugfix

2. v2.0.0       Database Migration
   Description: Migrates database to new schema
   Path: updates/2.0-migration.sh
   Tags: migration, database

===============================================================================
Apply updates? (Y/n): y

===============================================================================
Running updates...
===============================================================================

>>> Running: updates/dependencies-1.1.sh
-----------------------------------------------------------------------
Collecting updates...
Successfully installed new packages
✓ Update successful and recorded

>>> Running: updates/2.0-migration.sh
-----------------------------------------------------------------------
Starting database migration...
Migration completed successfully
✓ Update successful and recorded

===============================================================================
✓ All updates completed successfully!
===============================================================================
```

**Subsequent runs:**

```
✓ No pending updates.
```

## Error Handling

- If any update script exits with non-zero status, the update process stops
- Already-applied updates are recorded in `updated.json` and won't be re-run
- If an update fails partially, you can fix issues and rerun `update.sh` (it will skip already-applied updates)

## Variables Available in Scripts

Update scripts have access to:
- Python virtual environment (activated via `source venv/bin/activate`)
- All environment variables and project structure
- Ability to use `sudo` for privileged operations (will prompt if needed)

## Troubleshooting

**All updates already applied?**
- Check that available updates in `updates.json` are not in `updated.json.updates[]`
- Verify `updated.json` has correct `created_at` timestamps matching `updates.json`

**Script won't run?**
- Ensure script is executable: `chmod +x updates/your-script.sh`
- Check script syntax: `bash -n updates/your-script.sh`
- Verify it has proper shebang: `#!/bin/bash`

**Updates keeping track?**
- Check that `updated.json` is writable
- Verify it's git-ignored (in `.gitignore`)
- Don't manually edit `updated.json` after updates run
