#!/bin/bash
# start.sh — starts LANHub + Cloudflare tunnel, auto-updates configvars.json

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CF_LOG="/tmp/cloudflared_lanhub.log"

PORT=$(python3 -c "
import json
try:
    with open('configvars.json') as f:
        print(json.load(f).get('general', {}).get('PORT', 5000))
except:
    print(5000)
")

echo "🚀 Starting Cloudflare tunnel..."
rm -f "$CF_LOG"
cloudflared tunnel --url http://localhost:$PORT --logfile "$CF_LOG" &
CF_PID=$!

# Wait up to 15 seconds for the tunnel URL to appear in the log
TUNNEL_URL=""
for i in $(seq 1 30); do
    sleep 0.5
    TUNNEL_URL=$(grep -oP 'https://[a-z0-9\-]+\.trycloudflare\.com' "$CF_LOG" 2>/dev/null | head -1)
    if [ -n "$TUNNEL_URL" ]; then
        break
    fi
done

echo "$CF_PID" > /tmp/lanhub_cf.pid

if [ -n "$TUNNEL_URL" ]; then
    echo "✅ Tunnel URL: $TUNNEL_URL"
    # Patch configvars.json with the new tunnel URL
    python3 - <<PYEOF
import json
with open("configvars.json", "r") as f:
    cfg = json.load(f)
cfg.setdefault("access", {})["TUNNEL_URL"] = "$TUNNEL_URL"
with open("configvars.json", "w") as f:
    json.dump(cfg, f, indent=2)
print("configvars.json updated with tunnel URL")
PYEOF
else
    echo "⚠️  Could not detect tunnel URL — starting server without it"
    echo "    You can paste the URL manually in Admin → Access Settings"
fi

# Trap Ctrl+C to kill cloudflared too
trap "echo 'Shutting down...'; kill $CF_PID 2>/dev/null; exit 0" SIGINT SIGTERM

echo "🌐 Starting LANHub server..."
source venv/bin/activate
python app.py

# Cleanup
kill $CF_PID 2>/dev/null