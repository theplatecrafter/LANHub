#!/bin/bash
set -e

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

# Use Python to handle JSON parsing and update logic
python3 << 'PYTHON_EOF'
import json
import subprocess
import sys

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

# Prompt for confirmation
print("="*75)
try:
    response = input("Apply updates? (Y/n): ").strip().lower()
except KeyboardInterrupt:
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
    applied_updates['manifest']['last_update'] = update['created_at']
    
    # Write updates to file after each successful update
    with open('updates/updated.json', 'w') as f:
        json.dump(applied_updates, f, indent=2)
    
    print(f"✓ Update successful and recorded")

print("\n" + "="*75)
print("✓ All updates completed successfully!")
print("="*75 + "\n")

PYTHON_EOF

