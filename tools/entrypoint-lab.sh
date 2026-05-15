#!/bin/bash
# HansHub Lab Container Entrypoint

# Get configuration from environment
CODER_PASSWORD="${CODER_PASSWORD:-hanshub}"
PROJECT_SOCKET="${PROJECT_SOCKET:-/tmp/sockets/project.sock}"
PROJECT_SLUG="${PROJECT_SLUG:-project}"

# Ensure directories exist with proper permissions
mkdir -p /tmp/sockets
mkdir -p /home/coder/project
chmod 777 /tmp/sockets

echo "[Lab] Starting code-server for project: $PROJECT_SLUG"
echo "[Lab] Unix socket: $PROJECT_SOCKET"

# Setup code-server config directory
mkdir -p ~/.config/code-server

# Create or update code-server config if needed
cat > ~/.config/code-server/config.yaml << 'CODECFG'
bind-addr: 127.0.0.1:8443
auth: none
disable-telemetry: true
CODECFG

# =====================================================================
# AUTOMATION BLOCK: Venv, Pip Install, and Background App
# =====================================================================
cd /home/coder/project

echo "[Lab] Setting up Python environment..."
# 1. Create venv if it doesn't exist
if [ ! -d "venv" ]; then
    echo "[Lab] Creating virtual environment..."
    python3 -m venv venv
fi

# 2. Install requirements using the EXPLICIT venv pip path
if [ -f "requirements.txt" ]; then
    echo "[Lab] Installing dependencies..."
    /home/coder/project/venv/bin/pip install -r requirements.txt
fi

# 3. Start the app in the background so "Open Page" works immediately
# We use the EXPLICIT absolute path to the venv python to guarantee it finds Flask!
# CRITICAL: Capture Flask PID so we can shut it down gracefully later
FLASK_PID=""
if [ -f "app.py" ]; then
    echo "[Lab] Starting application in background..."
    /home/coder/project/venv/bin/python3 -u -m flask run --host=0.0.0.0 --port=8000 --debug </dev/null > /home/coder/project/app.log 2>&1 &
    FLASK_PID=$!
    echo "[Lab] Flask app started (PID: $FLASK_PID)"
fi

# 4. Setup shell to auto-activate venv AND handle port overlapping
cat > ~/.bashrc << 'BASHCFG'
# Standard bash configurations
if [ -f /etc/bash.bashrc ]; then
    source /etc/bash.bashrc
fi
export HISTFILE=/home/coder/.bash_history
export HISTSIZE=5000
export HISTFILESIZE=10000

# Auto-navigate to project and activate venv
cd /home/coder/project
if [ -d "venv" ]; then
    source venv/bin/activate
fi

BASHCFG
# =====================================================================

# ═══════════════════════════════════════════════════════════════════════════════
# Start code-server IDE in foreground
# ═══════════════════════════════════════════════════════════════════════════════
code-server \
  --bind-addr 127.0.0.1:8443 \
  --auth none \
  --disable-telemetry \
  /home/coder/project &

CODESERVER_PID=$!
echo "[Lab] code-server started (PID: $CODESERVER_PID)"

# Give code-server time to start
for i in {1..30}; do
  if curl -s -f http://localhost:8443 > /dev/null 2>&1; then
    echo "[Lab] code-server is responding"
    break
  fi
  echo "[Lab] Waiting for code-server to start... ($i/30)"
  sleep 1
  if ! kill -0 $CODESERVER_PID 2>/dev/null; then
    echo "[Lab] ERROR: code-server process died"
    exit 1
  fi
done

# Start Unix socket proxy using socat
rm -f "$PROJECT_SOCKET" 2>/dev/null || true
socat UNIX-LISTEN:"$PROJECT_SOCKET",fork,mode=666 TCP:localhost:8443 &
PROXY_PID=$!
echo "[Lab] Unix socket proxy started (PID: $PROXY_PID, Socket: $PROJECT_SOCKET)"

# Wait for socket to be created
for i in {1..10}; do
  if [ -S "$PROJECT_SOCKET" ]; then
    echo "[Lab] Socket is ready"
    break
  fi
  sleep 0.1
done

# Function to cleanup on exit
cleanup() {
    echo "[Lab] Shutting down gracefully..."
    
    # Kill Flask app first (cleanest shutdown)
    if [ -n "$FLASK_PID" ] && kill -0 $FLASK_PID 2>/dev/null; then
        echo "[Lab] Stopping Flask app (PID: $FLASK_PID)..."
        kill -TERM $FLASK_PID 2>/dev/null || true
        # Give it 2 seconds to shut down gracefully
        sleep 2
        # Force kill if still running
        kill -9 $FLASK_PID 2>/dev/null || true
    fi
    
    # Kill socat proxy
    if [ -n "$PROXY_PID" ] && kill -0 $PROXY_PID 2>/dev/null; then
        echo "[Lab] Stopping socket proxy (PID: $PROXY_PID)..."
        kill -TERM $PROXY_PID 2>/dev/null || true
        sleep 1
        kill -9 $PROXY_PID 2>/dev/null || true
    fi
    
    # Kill code-server
    if [ -n "$CODESERVER_PID" ] && kill -0 $CODESERVER_PID 2>/dev/null; then
        echo "[Lab] Stopping code-server (PID: $CODESERVER_PID)..."
        kill -TERM $CODESERVER_PID 2>/dev/null || true
        sleep 2
        kill -9 $CODESERVER_PID 2>/dev/null || true
    fi
    
    # Wait for all children to exit
    echo "[Lab] Waiting for all processes to exit..."
    wait 2>/dev/null || true
    
    echo "[Lab] Shutdown complete."
}

trap cleanup EXIT INT TERM

# Keep the container running - wait for all background processes
echo "[Lab] Container ready. Waiting for processes..."
# Wait for all background jobs (code-server, Flask, etc.)
# When any signal is received, trap handler will gracefully shut them down
wait