#!/bin/bash
# install.sh — LANHub one-shot setup script
# Run this once after cloning the repo.
# Usage: bash install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[LANHub]${RESET} $*"; }
success() { echo -e "${GREEN}[✓]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $*"; }
error()   { echo -e "${RED}[✗]${RESET} $*"; exit 1; }
ask()     { echo -e "${BOLD}$*${RESET}"; }

echo ""
echo -e "${BOLD}🛰️  LANHub Setup${RESET}"
echo "────────────────────────────────────────"
echo ""

# ── Step 1 — System packages ──────────────────────────────────────────────────
info "Installing system packages (git, python3, python3-venv, python3-pip)..."
sudo apt-get update -qq
sudo apt-get install -y git python3 python3-venv python3-pip curl
success "System packages ready."

# ── Step 2 — Python venv ──────────────────────────────────────────────────────
if [ ! -d "venv" ]; then
    info "Creating virtual environment..."
    python3 -m venv venv
    success "Virtual environment created."
else
    success "Virtual environment already exists."
fi

info "Installing Python dependencies..."
./venv/bin/pip install -q -r dependencies.txt
success "Python dependencies installed."

# ── Step 3 — cloudflared ──────────────────────────────────────────────────────
if ! command -v cloudflared &>/dev/null; then
    info "Installing cloudflared..."
    ARCH=$(dpkg --print-architecture 2>/dev/null || echo "amd64")
    curl -sSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}" \
         -o /tmp/cloudflared
    chmod +x /tmp/cloudflared
    sudo mv /tmp/cloudflared /usr/local/bin/cloudflared
    success "cloudflared installed ($(cloudflared --version 2>&1 | head -1))."
else
    success "cloudflared already installed."
fi

# ── Step 4 — SSH key ──────────────────────────────────────────────────────────
SSH_KEY="$HOME/.ssh/id_ed25519"
if [ ! -f "$SSH_KEY" ]; then
    info "Generating SSH key for GitHub..."
    ask "Enter your email address (used for SSH key label):"
    read -r USER_EMAIL
    ssh-keygen -t ed25519 -C "$USER_EMAIL" -f "$SSH_KEY" -N "" -q
    success "SSH key generated."
else
    success "SSH key already exists."
fi

echo ""
echo -e "${BOLD}━━━ GitHub Setup Required ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo "Before continuing, do these two things in your browser:"
echo ""
echo -e "  ${BOLD}1. Create a new GitHub repository${RESET} (e.g. 'lanhub-redirect')"
echo "     → Go to https://github.com/new"
echo "     → Add a README.md so the main branch is created"
echo "     → Go to Settings → Pages → Source → Deploy from branch → main / root → Save"
echo ""
echo -e "  ${BOLD}2. Add your SSH key to GitHub${RESET}"
echo "     → Go to https://github.com/settings/ssh/new"
echo "     → Paste the key below as the key contents:"
echo ""
echo -e "${YELLOW}$(cat "$SSH_KEY.pub")${RESET}"
echo ""
ask "Press ENTER once you have done both steps..."
read -r

# ── Step 5 — Interactive config ───────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━ Configuration ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""

# Copy example config if needed
if [ ! -f "configvars.json" ]; then
    cp configvars.example.json configvars.json
fi

ask "GitHub redirector repo URL (e.g. https://github.com/YOU/lanhub-redirect):"
read -r REPO_URL

ask "Port to run LANHub on [default: 5000]:"
read -r PORT
PORT="${PORT:-5000}"

ask "DEV admin username [default: dev]:"
read -r DEV_USER
DEV_USER="${DEV_USER:-dev}"

ask "DEV admin password:"
read -rs DEV_PASS
echo ""
if [ -z "$DEV_PASS" ]; then
    error "DEV password cannot be empty."
fi

echo ""
echo "Visibility mode:"
echo "  1) lan_only          — LAN devices only, public connections blocked"
echo "  2) public_password   — everyone must enter a password"
echo "  3) both_password     — LAN free, public connections need a password"
ask "Choose mode [1/2/3, default: 1]:"
read -r MODE_CHOICE
case "$MODE_CHOICE" in
    2) SITE_MODE="public_password" ;;
    3) SITE_MODE="both_password" ;;
    *) SITE_MODE="lan_only" ;;
esac

SITE_PASSWORD=""
if [ "$SITE_MODE" != "lan_only" ]; then
    ask "Access password for friends (leave blank to disable gate):"
    read -rs SITE_PASSWORD
    echo ""
fi

# Write config using Python to handle JSON safely
./venv/bin/python3 - <<PYEOF
import json

with open("configvars.json", "r") as f:
    cfg = json.load(f)

cfg.setdefault("general", {})
cfg["general"]["REPO_URL"] = "$REPO_URL"
cfg["general"]["PORT"]     = $PORT

cfg.setdefault("admin", {})
cfg["admin"]["INITIAL_DEV_USERNAME"] = "$DEV_USER"
cfg["admin"]["INITIAL_DEV_PASSWORD"] = "$DEV_PASS"
cfg["admin"]["SECRET_KEY"]           = "__generate__"

cfg.setdefault("access", {})
cfg["access"]["SITE_MODE"]     = "$SITE_MODE"
cfg["access"]["SITE_PASSWORD"] = "$SITE_PASSWORD"

with open("configvars.json", "w") as f:
    json.dump(cfg, f, indent=2)

print("configvars.json written.")
PYEOF

success "Configuration saved."

# ── Step 6 — Disable sleep ────────────────────────────────────────────────────
echo ""
ask "Disable system sleep/hibernation? Recommended for a server [Y/n]:"
read -r DISABLE_SLEEP
if [[ "$DISABLE_SLEEP" =~ ^[Nn]$ ]]; then
    warn "Skipping sleep disable."
else
    sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target \
         > /dev/null 2>&1
    success "Sleep and hibernation disabled."
fi

# ── Step 7 — Make scripts executable ─────────────────────────────────────────
chmod +x start.sh
success "start.sh is executable."

# ── Step 8 — systemd service ──────────────────────────────────────────────────
CURRENT_USER=$(whoami)
SERVICE_FILE="/etc/systemd/system/lanhub.service"

info "Writing systemd service..."
sudo tee "$SERVICE_FILE" > /dev/null <<SERVICE
[Unit]
Description=LANHub Server
After=network.target

[Service]
User=${CURRENT_USER}
WorkingDirectory=${SCRIPT_DIR}
ExecStart=/bin/bash ${SCRIPT_DIR}/start.sh
Restart=always
RestartSec=5
Environment="PYTHONUNBUFFERED=1"
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

sudo systemctl daemon-reload
sudo systemctl enable lanhub
success "systemd service installed and enabled."

# ── Step 9 — Initial redirector push ─────────────────────────────────────────
info "Running initial GitHub redirector push..."
source venv/bin/activate

./venv/bin/python3 - <<PYEOF
import sys
sys.path.insert(0, ".")
from glob_vars import *
import functions as f
import config as _config

stats = f.get_network_stats()
ip    = stats.get("ip_address", "127.0.0.1")
port  = int(getattr(_config, "PORT", 5000))
ok    = f.redirector_update(ip, port)
if ok:
    print("Redirector push successful.")
else:
    print("Redirector push failed — check logs/github_sync.log after first start.")
PYEOF

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}━━━ Setup Complete ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo -e "  Start the server:   ${BOLD}sudo systemctl start lanhub${RESET}"
echo -e "  Check status:       ${BOLD}sudo systemctl status lanhub${RESET}"
echo -e "  View logs:          ${BOLD}journalctl -u lanhub -f${RESET}"
echo ""
echo -e "  Local access:       ${BOLD}http://localhost:${PORT}${RESET}"
echo -e "  Admin panel:        ${BOLD}http://localhost:${PORT}/admin${RESET}"
echo ""
if [ -n "$REPO_URL" ]; then
    # Derive GitHub Pages URL from repo URL
    PAGES_URL=$(echo "$REPO_URL" | sed 's|https://github.com/\([^/]*\)/\(.*\)|\1.github.io/\2|')
    echo -e "  Redirector URL:     ${BOLD}https://${PAGES_URL}/${RESET}"
    echo -e "  ${YELLOW}(share this link with friends — it always finds your server)${RESET}"
fi
echo ""