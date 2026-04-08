# LANHub Lab Container Entrypoint
# Starts code-server and sets up Unix socket proxy
# NOTE: Code-server binds to 127.0.0.1:8443 (internal ONLY)
# Access is via Unix socket relay (socat), NOT direct port binding
# On deployment: Nginx proxies from port 80 to this socket
# On development: Flask proxies from port 5000 to this socket (with limitations)

# Get configuration from environment
CODER_PASSWORD="${CODER_PASSWORD:-lanhub}"
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

# Start code-server in background
# NOTE: Web UI is behind Flask auth layer, so we disable code-server auth for simplicity
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

# Start Unix socket proxy using socat (proven, battle-tested)
# socat creates a Unix socket that forwards bidirectionally to localhost:8443
# This is much more reliable than custom HTTP parsing
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
    echo "[Lab] Shutting down..."
    kill $CODESERVER_PID 2>/dev/null || true
    kill $PROXY_PID 2>/dev/null || true
    wait 2>/dev/null || true
}

trap cleanup EXIT INT TERM

# Keep the container running
echo "[Lab] Container ready. Waiting for processes..."
wait $CODESERVER_PID

