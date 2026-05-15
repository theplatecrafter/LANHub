#!/bin/bash
# WebSocket proxy starter for HansHub
# Listens on port 9000 and forwards to lab-sockets

SOCKET_DIR="/home/hans/project/HansHub/files/lab-sockets"

# Ensure socket directory exists
mkdir -p "$SOCKET_DIR"
chmod 777 "$SOCKET_DIR"

# Wait for test socket to be created (up to 30 seconds)
for i in {1..30}; do
    if [ -S "$SOCKET_DIR/test.sock" ]; then
        echo "✓ Found test socket at $SOCKET_DIR/test.sock"
        break
    fi
    echo "Waiting for test socket... ($i/30)"
    sleep 1
done

# For now, proxy statically to test.sock
# In production, this would dynamically create proxies for each active project
SOCKET_PATH="$SOCKET_DIR/test.sock"

if [ -S "$SOCKET_PATH" ]; then
    echo "Starting WebSocket proxy for $SOCKET_PATH on port 9000"
    exec /usr/bin/socat TCP-LISTEN:9000,reuseaddr,fork UNIX-CONNECT:"$SOCKET_PATH"
else
    echo "ERROR: Socket not found at $SOCKET_PATH"
    exit 1
fi
