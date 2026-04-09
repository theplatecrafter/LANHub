#!/bin/bash
# LANHub Lab Container Entrypoint

# Get configuration from environment
CODER_PASSWORD="${CODER_PASSWORD:-lanhub}"
PROJECT_SOCKET="${PROJECT_SOCKET:-/tmp/sockets/project.sock}"
PROJECT_SLUG="${PROJECT_SLUG:-project}"
LAB_MODE="${LAB_MODE:-development}" # Can be "development" or "production"

# Ensure directories exist with proper permissions
mkdir -p /tmp/sockets
mkdir -p /home/coder/project
chmod 777 /tmp/sockets

echo "[Lab] Starting container for project: $PROJECT_SLUG"
echo "[Lab] Mode: $LAB_MODE"
echo "[Lab] Unix socket: $PROJECT_SOCKET"

cd /home/coder/project

# =====================================================================
# STANDARD SETUP: Venv and Pip Install
# =====================================================================
echo "[Lab] Setting up Python environment..."
if [ ! -d "venv" ]; then
    echo "[Lab] Creating virtual environment..."
    python3 -m venv venv
fi

if [ -f "requirements.txt" ]; then
    echo "[Lab] Installing dependencies..."
    /home/coder/project/venv/bin/pip install -r requirements.txt
fi

# Setup shell to auto-activate venv for terminals
cat > ~/.bashrc << 'BASHCFG'
if [ -f /etc/bash.bashrc ]; then
    source /etc/bash.bashrc
fi
export HISTFILE=/home/coder/.bash_history
export HISTSIZE=5000
export HISTFILESIZE=10000

cd /home/coder/project
if [ -d "venv" ]; then
    source venv/bin/activate
fi
BASHCFG


# =====================================================================
# MODE SWITCH: Production (App) vs Development (VS Code)
# =====================================================================

PROXY_PORT=""

if [ "$LAB_MODE" = "production" ]; then
    # --- PRODUCTION MODE (Always-On) ---
    echo "[Lab] Booting in PRODUCTION mode. Starting background app..."
    
    if [ -f "app.py" ]; then
        /home/coder/project/venv/bin/python3 -u -m flask run --host=0.0.0.0 --port=8000 > /home/coder/project/app.log 2>&1 &
        MAIN_PID=$!
        echo "[Lab] Flask app started (PID: $MAIN_PID)"
        PROXY_PORT=8000 # Proxy the socket directly to the Flask app!
    else
        echo "[Lab] ERROR: No app.py found for production mode!"
        exit 1
    fi

else
    # --- DEVELOPMENT MODE (Spontaneous) ---
    echo "[Lab] Booting in DEVELOPMENT mode. Starting code-server..."
    
    mkdir -p ~/.config/code-server
    cat > ~/.config/code-server/config.yaml << 'CODECFG'
bind-addr: 127.0.0.1:8443
auth: none
disable-telemetry: true
CODECFG

    code-server --bind-addr 127.0.0.1:8443 --auth none --disable-telemetry /home/coder/project &
    MAIN_PID=$!
    echo "[Lab] code-server started (PID: $MAIN_PID)"
    PROXY_PORT=8443 # Proxy the socket to VS Code!
    
    # Wait for code-server to wake up
    for i in {1..30}; do
      if curl -s -f http://localhost:8443 > /dev/null 2>&1; then
        break
      fi
      sleep 1
    done
fi

# =====================================================================
# START SOCKET PROXY
# =====================================================================
rm -f "$PROJECT_SOCKET" 2>/dev/null || true
socat UNIX-LISTEN:"$PROJECT_SOCKET",fork,mode=666 TCP:localhost:$PROXY_PORT &
PROXY_PID=$!
echo "[Lab] Unix socket proxy started (PID: $PROXY_PID, routing to port $PROXY_PORT)"

# Wait for socket to be created
for i in {1..10}; do
  if [ -S "$PROJECT_SOCKET" ]; then
    echo "[Lab] Socket is ready"
    break
  fi
  sleep 0.1
done

# =====================================================================
# GRACEFUL SHUTDOWN
# =====================================================================
cleanup() {
    echo "[Lab] Shutting down gracefully..."
    if [ -n "$MAIN_PID" ] && kill -0 $MAIN_PID 2>/dev/null; then
        kill -TERM $MAIN_PID 2>/dev/null || true
        sleep 2
        kill -9 $MAIN_PID 2>/dev/null || true
    fi
    if [ -n "$PROXY_PID" ] && kill -0 $PROXY_PID 2>/dev/null; then
        kill -TERM $PROXY_PID 2>/dev/null || true
        sleep 1
        kill -9 $PROXY_PID 2>/dev/null || true
    fi
    exit 0
}

trap cleanup EXIT INT TERM

echo "[Lab] Container ready. Waiting for processes..."
wait