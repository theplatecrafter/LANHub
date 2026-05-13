#!/bin/bash
# Diagnostic script for LANHub restart loop issues
# This script checks common causes of service restart loops

echo "═══════════════════════════════════════════════════════════════"
echo "LANHub Restart Loop Diagnostic"
echo "═══════════════════════════════════════════════════════════════"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check 1: Python and venv
echo "[1] Checking Python Environment..."
if [ ! -d "venv" ]; then
    echo "  ❌ Virtual environment 'venv' not found!"
else
    echo "  ✓ Virtual environment exists"
    if [ ! -f "venv/bin/activate" ]; then
        echo "  ❌ venv/bin/activate not found - venv may be corrupted"
    else
        echo "  ✓ venv/bin/activate exists"
        # Try to activate and check Python
        source venv/bin/activate
        if ! python -c "import sys; print(f'Python {sys.version_info.major}.{sys.version_info.minor}')"; then
            echo "  ❌ Python executable failed in venv"
        else
            python -c "import sys; print(f'  ✓ Python ready: {sys.version_info.major}.{sys.version_info.minor}')"
        fi
    fi
fi
echo ""

# Check 2: Config file
echo "[2] Checking Configuration..."
if [ ! -f "configvars.json" ]; then
    echo "  ❌ configvars.json not found!"
else
    echo "  ✓ configvars.json exists"
    # Check for invalid tunnel URL
    TUNNEL_URL=$(python3 -c "import json; cfg=json.load(open('configvars.json')); print(cfg.get('access', {}).get('TUNNEL_URL', ''))")
    if [ -z "$TUNNEL_URL" ]; then
        echo "  ℹ No TUNNEL_URL configured (OK - will run on LAN only)"
    else
        echo "  Tunnel URL: $TUNNEL_URL"
        # Validate the URL
        if [[ "$TUNNEL_URL" =~ https://[a-z0-9]+-[a-z0-9-]+\.trycloudflare\.com ]]; then
            echo "  ✓ Tunnel URL format is valid"
        else
            echo "  ⚠ WARNING: Tunnel URL format may be invalid!"
            echo "  Expected pattern: https://[multiple-hyphens].trycloudflare.com"
            echo "  Examples of invalid URLs: https://api.trycloudflare.com"
        fi
    fi
fi
echo ""

# Check 3: Required files
echo "[3] Checking Required Files..."
REQUIRED_FILES=("app.py" "config.py" "glob_vars.py" "requirements.txt" "start.sh")
for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✓ $file"
    else
        echo "  ❌ $file MISSING"
    fi
done
echo ""

# Check 4: Try to import key modules
echo "[4] Checking Python Imports..."
source venv/bin/activate 2>/dev/null
python3 - << 'PYEOF'
import sys
modules_to_check = ['flask', 'gevent', 'socketio', 'sqlite3', 'json']
for mod in modules_to_check:
    try:
        __import__(mod)
        print(f"  ✓ {mod}")
    except ImportError as e:
        print(f"  ❌ {mod}: {e}")
PYEOF
echo ""

# Check 5: Database
echo "[5] Checking Database..."
if [ -f "app.db" ]; then
    echo "  ✓ app.db exists"
    python3 << 'PYEOF'
import sqlite3
try:
    conn = sqlite3.connect("app.db")
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
    result = c.fetchone()
    conn.close()
    if result:
        print("  ✓ Database is accessible and has tables")
    else:
        print("  ⚠ Database exists but appears empty")
except Exception as e:
    print(f"  ❌ Database error: {e}")
PYEOF
else
    echo "  ℹ app.db not found (will be created on first run)"
fi
echo ""

# Check 6: Port availability
echo "[6] Checking Port..."
PORT=$(python3 -c "
import json
try:
    with open('configvars.json') as f:
        print(json.load(f).get('general', {}).get('PORT', 5000))
except:
    print(5000)
")
echo "  Configured PORT: $PORT"
if netstat -tuln 2>/dev/null | grep -q ":$PORT "; then
    echo "  ⚠ WARNING: Port $PORT is already in use!"
else
    echo "  ✓ Port $PORT is available"
fi
echo ""

# Check 7: Service status (if running as service)
echo "[7] Checking Service Status..."
if systemctl is-active --quiet lanhub.service 2>/dev/null; then
    echo "  ✓ Service is active"
elif systemctl is-enabled --quiet lanhub.service 2>/dev/null; then
    echo "  ⚠ Service exists but is not active"
else
    echo "  ℹ Not running as systemd service (OK for dev mode)"
fi
echo ""

echo "═══════════════════════════════════════════════════════════════"
echo "Next Steps:"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "1. Check logs:"
echo "   sudo journalctl -u lanhub -n 50 --no-pager"
echo "   tail -50 logs/app.log"
echo "   tail -50 logs/error.log"
echo ""
echo "2. To use the fixed start.sh:"
echo "   cp start.sh start.sh.backup"
echo "   cp start.sh.fixed start.sh"
echo "   chmod +x start.sh"
echo ""
echo "3. To restart the service:"
echo "   sudo systemctl restart lanhub"
echo ""
echo "4. To manually test the app:"
echo "   cd $SCRIPT_DIR"
echo "   source venv/bin/activate"
echo "   python app.py"
echo ""
