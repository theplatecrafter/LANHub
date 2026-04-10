#!/bin/bash

source venv/bin/activate
git pull

# Initialize updated.json if it doesn't exist
UPDATED_JSON="updates/updated.json"
if [ ! -f "$UPDATED_JSON" ]; then
    mkdir -p updates
    cat > "$UPDATED_JSON" <<'EOF'
{
  "manifest": {
    "last_update": 0
  },
  "updates": []
}
EOF
fi

# All update logic (detection, prompting, execution) in Python
python3 << 'PYTHON_EOF'
import json
import subprocess
import sys
import os
import time

# Read JSON files
with open('updates/updates.json', 'r') as f:
    available_updates = json.load(f)

with open('updates/updated.json', 'r') as f:
    applied_updates = json.load(f)

# Build a set of applied update IDs for quick lookup
applied_ids = {update['id'] for update in applied_updates.get('updates', [])}

# Find pending updates and sort by created_at
pending = []
for update_name, update_data in available_updates.items():
    if update_data['id'] not in applied_ids:
        update_data['name'] = update_name  # Store the display name
        pending.append(update_data)

pending.sort(key=lambda x: x['created_at'])

if not pending:
    print("\n✓ No pending updates.")
    sys.exit(0)

# Display pending updates
print("\n" + "="*75)
print("PENDING UPDATES")
print("="*75 + "\n")

for i, update in enumerate(pending, 1):
    version_str = f"v{update['version']}"
    print(f"{i}. {version_str:12} {update['name']}")
    print(f"   Description: {update['description']}")
    print(f"   Path: {update['path']}")
    if update.get('tags'):
        print(f"   Tags: {', '.join(update['tags'])}")
    print()

# Prompt for confirmation - with proper handling of piped vs interactive input
print("="*75)
response = None
try:
    # Check if stdin is a TTY (interactive terminal)
    import sys
    is_tty = sys.stdin.isatty()
    
    if is_tty:
        # Interactive terminal - read from stdin
        response = input("Apply updates? (Y/n): ").strip().lower()
    else:
        # Piped input - read from /dev/tty for true interactivity
        # If /dev/tty is available, use it; otherwise use stdin (which has piped data)
        try:
            with open('/dev/tty', 'r') as tty:
                sys.stdout.write("Apply updates? (Y/n): ")
                sys.stdout.flush()
                response = tty.readline().strip().lower()
        except (FileNotFoundError, OSError):
            # No /dev/tty available - read from piped stdin
            response = input("Apply updates? (Y/n): ").strip().lower()
except (KeyboardInterrupt, EOFError):
    print("\n\nUpdates cancelled.")
    sys.exit(0)

if response not in ['y', 'yes', '']:
    print("Updates cancelled.")
    sys.exit(0)

# Run each update
print("\n" + "="*75)
print("Running updates...")
print("="*75 + "\n")

for update in pending:
    print(f"\n>>> Running: {update['path']}")
    print("-"*75)
    
    # Run the update script, allowing interactive input
    result = subprocess.run(['bash', update['path']])
    
    if result.returncode != 0:
        print(f"\n{'!'*75}")
        print(f"[ERROR] Update failed with return code {result.returncode}")
        print(f"Stopping update process. Partial updates have been recorded.")
        print(f"{'!'*75}")
        sys.exit(1)
    
    # Mark as applied
    applied_updates['updates'].append({
        'id': update['id'],
        'version': update['version'],
        'title': update.get('title', update['name']),
        'description': update['description'],
        'timestamp': update['created_at'],
        'tags': update.get('tags', [])
    })
    # last_update is the current timestamp (when update is actually applied)
    applied_updates['manifest']['last_update'] = int(time.time())
    
    # Write updates to file after each successful update
    with open('updates/updated.json', 'w') as f:
        json.dump(applied_updates, f, indent=2)
    
    print(f"✓ Update successful and recorded")

print("\n" + "="*75)
print("✓ All updates completed successfully!")
print("="*75 + "\n")

PYTHON_EOF


if [ -f ".service_name" ]; then
    SVC_NAME=$(cat .service_name)
else
    SVC_NAME="lanhub"
fi

echo "Restarting $SVC_NAME..."
if sudo systemctl daemon-reload && sudo systemctl restart "$SVC_NAME"; then
    echo "✓ $SVC_NAME restarted successfully."
else
    echo -e "\n${YELLOW}⚠️  Failed to restart $SVC_NAME automatically.${RESET}"
    echo -e "  This may be a development setup without a systemd service."
    echo -e "  Please restart the server manually to apply updates."
fi