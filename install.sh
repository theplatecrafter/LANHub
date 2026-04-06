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

# ── Mode selection ────────────────────────────────────────────────────────────
echo "Installation mode:"
echo "  1) Server     — full setup with Cloudflare tunnel and systemd autostart"
echo "  2) Local only — server mode but no Cloudflare tunnel (LAN access only)"
echo "  3) Developer  — minimal setup for local development, no systemd or tunnel"
while true; do
    ask "Choose mode [1/2/3, default: 1]:"
    read -r INSTALL_MODE
    INSTALL_MODE="${INSTALL_MODE:-1}"
    case "$INSTALL_MODE" in
        1) INSTALL_MODE="server";    break ;;
        2) INSTALL_MODE="local";     break ;;
        3) INSTALL_MODE="dev";       break ;;
        *) warn "Please enter 1, 2, or 3." ;;
    esac
done
echo ""

# ── Step 1 — System packages ──────────────────────────────────────────────────
info "Installing system packages (git, python3, python3-venv, python3-pip, curl)..."
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

if [ ! -f "venv/bin/pip" ]; then
    error "venv exists but pip is missing. Delete the venv/ folder and re-run."
fi

info "Installing Python dependencies..."
./venv/bin/pip install -q -r dependencies.txt
success "Python dependencies installed."

# ── Step 3 — cloudflared ──────────────────────────────────────────────────────
if [ "$INSTALL_MODE" = "server" ]; then
    if ! command -v cloudflared &>/dev/null; then
        info "Installing cloudflared..."
        ARCH=$(dpkg --print-architecture 2>/dev/null || echo "amd64")
        CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}"
        if ! curl -sSL "$CF_URL" -o /tmp/cloudflared; then
            error "Failed to download cloudflared. Check your internet connection."
        fi
        chmod +x /tmp/cloudflared
        sudo mv /tmp/cloudflared /usr/local/bin/cloudflared
        success "cloudflared installed ($(cloudflared --version 2>&1 | head -1))."
    else
        success "cloudflared already installed ($(cloudflared --version 2>&1 | head -1))."
    fi
else
    info "Skipping cloudflared (not needed for ${INSTALL_MODE} mode)."
fi

# ── Step 4 — SSH key ──────────────────────────────────────────────────────────
if [ "$INSTALL_MODE" = "server" ]; then
    SSH_KEY="$HOME/.ssh/id_ed25519"
    mkdir -p "$HOME/.ssh"
    chmod 700 "$HOME/.ssh"

    if [ ! -f "$SSH_KEY" ]; then
        info "Generating SSH key for GitHub..."
        ask "Enter your email address (used for SSH key label):"
        read -r USER_EMAIL
        if [ -z "$USER_EMAIL" ]; then
            error "Email cannot be empty."
        fi
        ssh-keygen -t ed25519 -C "$USER_EMAIL" -f "$SSH_KEY" -N "" -q
        success "SSH key generated."
    else
        warn "SSH key already exists at $SSH_KEY — using it as-is."
    fi

    if [ ! -f "${SSH_KEY}.pub" ]; then
        error "Public key not found at ${SSH_KEY}.pub — something went wrong with key generation."
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
    echo -e "${YELLOW}$(cat "${SSH_KEY}.pub")${RESET}"
    echo ""
    ask "Press ENTER once you have done both steps..."
    read -r
else
    info "Skipping GitHub SSH setup (not needed for ${INSTALL_MODE} mode)."
fi

# ── Step 5 — Interactive config ───────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━ Configuration ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""

SKIP_CONFIG=false

if [ -f "configvars.json" ]; then
    warn "configvars.json already exists."
    ask "Overwrite it with a fresh configuration? [y/N]:"
    read -r OVERWRITE_CFG
    if [[ ! "$OVERWRITE_CFG" =~ ^[Yy]$ ]]; then
        warn "Keeping existing configvars.json — skipping configuration prompts."
        SKIP_CONFIG=true
    else
        if [ ! -f "config/configvars.example.json" ]; then
            error "config/configvars.example.json not found. Is the repo fully cloned?"
        fi
        cp config/configvars.example.json configvars.json
        info "configvars.json reset from example."
    fi
else
    if [ ! -f "config/configvars.example.json" ]; then
        error "config/configvars.example.json not found. Is the repo fully cloned?"
    fi
    cp config/configvars.example.json configvars.json
fi

if [ "$SKIP_CONFIG" = false ]; then

    # REPO_URL — only needed for server mode
    REPO_URL=""
    if [ "$INSTALL_MODE" = "server" ]; then
        while true; do
            ask "GitHub redirector repo URL (e.g. https://github.com/YOU/lanhub-redirect):"
            read -r REPO_URL
            if [ -z "$REPO_URL" ]; then
                warn "Repo URL cannot be empty. Try again."
            elif [[ ! "$REPO_URL" =~ ^https://github\.com/.+/.+ ]]; then
                warn "That doesn't look like a valid GitHub URL. Try again."
            else
                break
            fi
        done
    fi

    # PORT — must be a number between 1 and 65535
    while true; do
        ask "Port to run LANHub on [default: 5000]:"
        read -r PORT
        PORT="${PORT:-5000}"
        if [[ ! "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
            warn "Port must be a number between 1 and 65535. Try again."
        else
            break
        fi
    done

    # DEV username
    ask "DEV admin username [default: dev]:"
    read -r DEV_USER
    DEV_USER="${DEV_USER:-dev}"
    if [ -z "$DEV_USER" ]; then
        error "DEV username cannot be empty."
    fi

    # DEV password — must not be empty, confirmed
    while true; do
        ask "DEV admin password:"
        read -rs DEV_PASS
        echo ""
        if [ -z "$DEV_PASS" ]; then
            warn "Password cannot be empty. Try again."
            continue
        fi
        ask "Confirm DEV admin password:"
        read -rs DEV_PASS_CONFIRM
        echo ""
        if [ "$DEV_PASS" != "$DEV_PASS_CONFIRM" ]; then
            warn "Passwords do not match. Try again."
        else
            break
        fi
    done

    # Visibility mode — forced to lan_only for non-server modes
    if [ "$INSTALL_MODE" = "server" ]; then
        echo ""
        echo "Visibility mode:"
        echo "  1) lan_only          — LAN devices only, public connections blocked"
        echo "  2) public_password   — everyone must enter a password"
        echo "  3) both_password     — LAN free, public connections need a password"
        while true; do
            ask "Choose mode [1/2/3, default: 1]:"
            read -r MODE_CHOICE
            MODE_CHOICE="${MODE_CHOICE:-1}"
            case "$MODE_CHOICE" in
                1) SITE_MODE="lan_only";        break ;;
                2) SITE_MODE="public_password"; break ;;
                3) SITE_MODE="both_password";   break ;;
                *) warn "Please enter 1, 2, or 3." ;;
            esac
        done
    else
        SITE_MODE="lan_only"
        info "Visibility mode set to lan_only (${INSTALL_MODE} mode)."
    fi

    # Site password — only asked if not lan_only, confirmed
    SITE_PASSWORD=""
    if [ "$SITE_MODE" != "lan_only" ]; then
        while true; do
            ask "Access password for friends (leave blank to disable gate):"
            read -rs SITE_PASSWORD
            echo ""
            if [ -z "$SITE_PASSWORD" ]; then
                warn "No password set — the gate will be disabled. Continue? [Y/n]:"
                read -r CONFIRM_BLANK
                if [[ "$CONFIRM_BLANK" =~ ^[Nn]$ ]]; then
                    continue
                fi
                break
            fi
            ask "Confirm access password:"
            read -rs SITE_PASSWORD_CONFIRM
            echo ""
            if [ "$SITE_PASSWORD" != "$SITE_PASSWORD_CONFIRM" ]; then
                warn "Passwords do not match. Try again."
            else
                break
            fi
        done
    fi

    # Write config — pass values via environment variables into a quoted heredoc
    # so special characters in passwords/URLs never break the Python script.
    export _LANHUB_REPO_URL="$REPO_URL"
    export _LANHUB_PORT="$PORT"
    export _LANHUB_DEV_USER="$DEV_USER"
    export _LANHUB_DEV_PASS="$DEV_PASS"
    export _LANHUB_SITE_MODE="$SITE_MODE"
    export _LANHUB_SITE_PASSWORD="$SITE_PASSWORD"

    ./venv/bin/python3 - <<'PYEOF'
import json, os, sys

cfg_path = "configvars.json"
try:
    with open(cfg_path, "r") as f:
        cfg = json.load(f)
except Exception as e:
    print(f"ERROR reading configvars.json: {e}", file=sys.stderr)
    sys.exit(1)

cfg.setdefault("general", {})
if os.environ["_LANHUB_REPO_URL"]:
    cfg["general"]["REPO_URL"] = os.environ["_LANHUB_REPO_URL"]
cfg["general"]["PORT"] = int(os.environ["_LANHUB_PORT"])

cfg.setdefault("admin", {})
cfg["admin"]["INITIAL_DEV_USERNAME"] = os.environ["_LANHUB_DEV_USER"]
cfg["admin"]["INITIAL_DEV_PASSWORD"] = os.environ["_LANHUB_DEV_PASS"]
cfg["admin"]["SECRET_KEY"]           = "__generate__"

cfg.setdefault("access", {})
cfg["access"]["SITE_MODE"]     = os.environ["_LANHUB_SITE_MODE"]
cfg["access"]["SITE_PASSWORD"] = os.environ["_LANHUB_SITE_PASSWORD"]

try:
    with open(cfg_path, "w") as f:
        json.dump(cfg, f, indent=2)
except Exception as e:
    print(f"ERROR writing configvars.json: {e}", file=sys.stderr)
    sys.exit(1)

print("configvars.json written successfully.")
PYEOF

    # Clean up exported secrets immediately
    unset _LANHUB_REPO_URL _LANHUB_PORT _LANHUB_DEV_USER _LANHUB_DEV_PASS
    unset _LANHUB_SITE_MODE _LANHUB_SITE_PASSWORD

    success "Configuration saved."
fi

# ── Step 6 — Disable sleep ────────────────────────────────────────────────────
if [ "$INSTALL_MODE" != "dev" ]; then
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
else
    info "Skipping sleep disable (dev mode)."
fi

# ── Step 7 — Write start.sh ───────────────────────────────────────────────────
info "Writing start.sh..."

if [ "$INSTALL_MODE" = "server" ]; then
    cat > start.sh << 'STARTSH'
#!/bin/bash
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

echo "Starting Cloudflare tunnel on port $PORT..."
rm -f "$CF_LOG"
cloudflared tunnel --url http://localhost:$PORT --logfile "$CF_LOG" &
CF_PID=$!

TUNNEL_URL=""
for i in $(seq 1 30); do
    sleep 0.5
    TUNNEL_URL=$(grep -oP 'https://[a-z0-9\-]+\.trycloudflare\.com' "$CF_LOG" 2>/dev/null | head -1)
    if [ -n "$TUNNEL_URL" ]; then break; fi
done

echo "$CF_PID" > /tmp/lanhub_cf.pid

if [ -n "$TUNNEL_URL" ]; then
    echo "Tunnel URL: $TUNNEL_URL"
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
    echo "Could not detect tunnel URL — starting server without it"
    echo "You can paste the URL manually in Admin → Access Settings"
fi

trap "echo 'Shutting down...'; kill $CF_PID 2>/dev/null; exit 0" SIGINT SIGTERM

echo "Starting LANHub server..."
source venv/bin/activate
python app.py

kill $CF_PID 2>/dev/null
STARTSH

elif [ "$INSTALL_MODE" = "local" ]; then
    cat > start.sh << 'STARTSH'
#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT=$(python3 -c "
import json
try:
    with open('configvars.json') as f:
        print(json.load(f).get('general', {}).get('PORT', 5000))
except:
    print(5000)
")

echo "Starting LANHub on port $PORT (LAN only — no tunnel)..."
source venv/bin/activate
python app.py
STARTSH

else
    # Developer mode
    cat > start.sh << 'STARTSH'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT=$(python3 -c "
import json
try:
    with open('configvars.json') as f:
        print(json.load(f).get('general', {}).get('PORT', 5000))
except:
    print(5000)
")

echo ""
echo "LANHub — Developer Mode"
echo "Access at: http://localhost:$PORT"
echo "Press Ctrl+C to stop."
echo ""

source venv/bin/activate
python app.py
STARTSH

fi

chmod +x start.sh
success "start.sh written and made executable."

# ── Step 8 — systemd service ──────────────────────────────────────────────────
if [ "$INSTALL_MODE" = "dev" ]; then
    info "Skipping systemd service (dev mode — run './start.sh' manually)."
else
    CURRENT_USER=$(whoami)
    SERVICE_FILE="/etc/systemd/system/lanhub.service"
    SKIP_SERVICE=false

    if [ -f "$SERVICE_FILE" ]; then
        warn "A systemd service named 'lanhub' already exists."
        ask "Overwrite it? [y/N]:"
        read -r OVERWRITE_SVC
        if [[ ! "$OVERWRITE_SVC" =~ ^[Yy]$ ]]; then
            warn "Skipping service installation. Your existing service was left untouched."
            SKIP_SERVICE=true
        fi
    fi

    if [ "$SKIP_SERVICE" = false ]; then
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
    fi
fi

# ── Step 9 — Initial redirector push ─────────────────────────────────────────
if [ "$INSTALL_MODE" = "server" ]; then
    info "Running initial GitHub redirector push..."
    ./venv/bin/python3 - <<'PYEOF'
import sys
sys.path.insert(0, ".")

try:
    import config as _config
    import functions as f
except Exception as e:
    print(f"Import error: {e}")
    print("Skipping redirector push — it will run automatically on first start.")
    sys.exit(0)

try:
    stats = f.get_network_stats()
    ip    = stats.get("ip_address", "127.0.0.1")
    port  = int(getattr(_config, "PORT", 5000))

    if ip == "127.0.0.1":
        print("No network connection detected — skipping redirector push.")
        print("It will run automatically within 60s of first start.")
        sys.exit(0)

    ok = f.redirector_update(ip, port)
    if ok:
        print(f"Redirector push successful → http://{ip}:{port}")
    else:
        print("Redirector push failed — check logs/github_sync.log after first start.")
except Exception as e:
    print(f"Redirector push skipped ({e}) — it will retry automatically on first start.")
PYEOF
else
    info "Skipping redirector push (${INSTALL_MODE} mode)."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}━━━ Setup Complete ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""

if [ "$INSTALL_MODE" = "dev" ]; then
    echo -e "  ${BOLD}Developer mode — run the server manually:${RESET}"
    echo ""
    echo -e "  Start:        ${BOLD}./start.sh${RESET}"
    echo -e "  Or directly:  ${BOLD}source venv/bin/activate && python app.py${RESET}"
    echo ""
    echo -e "  Local access: ${BOLD}http://localhost:${PORT:-5000}${RESET}"
    echo -e "  Admin panel:  ${BOLD}http://localhost:${PORT:-5000}/admin${RESET}"
    echo ""
    echo -e "  ${YELLOW}No systemd service was created. The server does not start on boot.${RESET}"
    echo -e "  ${YELLOW}Use Admin → Server → Update to pull changes from your dev machine.${RESET}"
else
    echo -e "  Start the server:   ${BOLD}sudo systemctl start lanhub${RESET}"
    echo -e "  Check status:       ${BOLD}sudo systemctl status lanhub${RESET}"
    echo -e "  View logs:          ${BOLD}journalctl -u lanhub -f${RESET}"
    echo ""
    echo -e "  Local access:       ${BOLD}http://localhost:${PORT:-5000}${RESET}"
    echo -e "  Admin panel:        ${BOLD}http://localhost:${PORT:-5000}/admin${RESET}"
    if [ "$INSTALL_MODE" = "server" ] && [ -n "${REPO_URL:-}" ]; then
        PAGES_URL=$(echo "$REPO_URL" | sed 's|https://github.com/\([^/]*\)/\(.*\)|\1.github.io/\2|')
        echo ""
        echo -e "  Redirector URL:     ${BOLD}https://${PAGES_URL}/${RESET}"
        echo -e "  ${YELLOW}(share this link with friends — it always finds your server)${RESET}"
    fi
    if [ "$INSTALL_MODE" = "local" ]; then
        echo ""
        echo -e "  ${YELLOW}Local-only mode — no Cloudflare tunnel. Accessible on this network only.${RESET}"
    fi
fi
echo ""