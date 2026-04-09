#!/bin/bash
# Update: Docker Lab Setup
# Version: 1.1.0
# Requires restart: no
# Requires sudo: yes (but tries without first)
# Requires input: no
# Description: Install Docker (if not present) and build lanhub-lab:latest image for Lab feature

set -e

# Colors for output (match install.sh style)
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[UPDATE]${RESET} $*"; }
success() { echo -e "${GREEN}[✓]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$SCRIPT_DIR"

# Helper to run docker with or without sudo
run_docker() {
    # Try without sudo first (user may be in docker group)
    if docker "$@" 2>/dev/null; then
        return 0
    fi
    # If permission denied, try with sudo -n (no password prompt, non-interactive)
    if sudo -n docker "$@" 2>/dev/null; then
        return 0
    fi
    # Both failed - try sudo -n one more time and show the actual error
    sudo -n docker "$@"
    return $?
}

# ── Ensure files/lab directory exists ─────────────────────────────────────────
info "Ensuring files/lab directory exists..."
mkdir -p files/lab files/lab-sockets files/dropzone logs
chmod 755 files/lab files/lab-sockets files/dropzone logs 2>/dev/null || true
success "Directory structure ready."
echo ""

# ── Check if Docker image already exists ──────────────────────────────────────
# Try to check without sudo first (if user is in docker group)
if docker image inspect lanhub-lab:latest >/dev/null 2>&1; then
    success "Docker image lanhub-lab:latest already exists — skipping build."
    exit 0
fi

# If not in docker group, try with sudo -n
if sudo -n docker image inspect lanhub-lab:latest >/dev/null 2>&1; then
    success "Docker image lanhub-lab:latest already exists — skipping build."
    exit 0
fi

# ── Check if Docker is installed ──────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    info "Docker not found — installing..."
    if ! command -v curl &>/dev/null; then
        echo "ERROR: curl is required to install Docker, but not found" >&2
        exit 1
    fi
    
    # Download Docker install script (official method) with progress
    echo "  Downloading Docker installer..."
    if curl -f# https://get.docker.com -o /tmp/get-docker.sh; then
        echo "  Installing Docker..."
        if ! sudo -n sh /tmp/get-docker.sh >/dev/null 2>&1; then
            echo "ERROR: Docker installation failed (sudo -n failed or script errored)" >&2
            exit 1
        fi
        rm -f /tmp/get-docker.sh
        success "Docker installed successfully."
    else
        echo "ERROR: Failed to download Docker installer" >&2
        exit 1
    fi
    
    # Start Docker daemon
    if run_docker info >/dev/null 2>&1; then
        success "Docker daemon is running."
    else
        warn "Docker daemon not responding — trying to start..."
        if sudo -n systemctl start docker >/dev/null 2>&1; then
            success "Docker daemon started."
        else
            warn "Could not start Docker daemon. It may start on next boot."
        fi
    fi
else
    info "Docker is already installed."
fi

# ── Check if Docker is accessible ─────────────────────────────────────────────
if ! run_docker info >/dev/null 2>&1; then
    echo ""
    echo "ERROR: Cannot run docker commands." >&2
    echo ""
    echo "SOLUTION: Reconfigure sudo access for Docker:" >&2
    echo ""
    echo "  Option A: Add user to docker group (recommended for local dev)" >&2
    echo "    sudo usermod -aG docker \$USER" >&2
    echo "    (then log out and back in)" >&2
    echo ""
    echo "  Option B: Allow docker via sudo without password" >&2
    echo "    sudo visudo" >&2
    echo "    Add: \$USER ALL=(ALL) NOPASSWD: /usr/bin/docker" >&2
    echo ""
    exit 1
fi

# ── Check Dockerfile exists ───────────────────────────────────────────────────
if [ ! -f "Dockerfile.lab" ]; then
    echo "ERROR: Dockerfile.lab not found in project root" >&2
    exit 1
fi

# ── Build the Docker image ────────────────────────────────────────────────────
info "Building Docker image (this may take 2-5 minutes)..."
echo ""

# Record start time for logging
BUILD_START=$(date +%s)

# Build with real-time output showing progress (pipeline preserves exit code with set -o pipefail)
set +e
run_docker build -f Dockerfile.lab -t lanhub-lab:latest . 2>&1 | while IFS= read -r line; do
    # Show each build step with indentation and formatting
    if [[ "$line" =~ ^Step\ [0-9] ]]; then
        echo -e "  ${GREEN}→${RESET} $line"
    elif [[ "$line" =~ "Successfully tagged" ]]; then
        echo -e "  ${GREEN}✓${RESET} $line"
    elif [[ "$line" =~ "Step" ]]; then
        echo -e "  ${CYAN}⋯${RESET} $line"
    elif [[ "$line" =~ "Download" || "$line" =~ "download" ]]; then
        # Highlight download progress
        echo -e "  ${CYAN}↓${RESET} $line"
    elif [[ "$line" =~ "ERROR" || "$line" =~ "error" ]]; then
        echo -e "  ${RED}✗${RESET} $line"
    elif [[ ! "$line" =~ ^[[:space:]]*$ ]]; then
        # Show non-empty lines with lighter formatting
        echo "    $line"
    fi
done
BUILD_EXIT=$?
set -e

if [ $BUILD_EXIT -ne 0 ]; then
    echo ""
    echo "ERROR: Docker build failed." >&2
    exit 1
fi

echo ""
success "Docker image lanhub-lab:latest built successfully."
echo "Lab feature is now ready — users can create projects and deploy them."
