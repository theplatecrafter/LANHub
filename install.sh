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
echo "Requirements:"
echo "  • Python 3.8+"
echo "  • Optional: Docker (only needed for Lab feature with code-server)"
echo ""

# ── IMPORTANT: Check if running as root ────────────────────────────────────────
if [ "$EUID" -eq 0 ]; then
    error "Do NOT run this script with sudo!
    
Run it as your regular user:
  bash install.sh

The script will prompt for sudo when needed for system operations.
Running as root will cause file permission issues everywhere (Lab, Admin, etc)."
fi

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

# ── Step 4 — Create required directories ───────────────────────────────────────
info "Setting up required directories..."
mkdir -p files/lab files/lab-sockets files/dropzone logs
chmod 777 files/lab files/lab-sockets  # Must be writable by Docker container (coder user)
chmod 755 files/dropzone logs
success "Directories created and configured."

# ── Step 5 — Lab Feature Setup ─────────────────────────────────────────────────
echo ""
ask "Do you want to enable the Lab feature? (self-hosted web development environment)"
ask "This requires Docker and will build a specialized container image."
ask "Enable Lab? [Y/n, default: Y]:"
read -r ENABLE_LAB
ENABLE_LAB="${ENABLE_LAB:-y}"

if [[ "$ENABLE_LAB" =~ ^[Yy]$ ]]; then
    # ── Docker Check for Lab ──────────────────────────────────────────────────
    info "Checking Docker installation for Lab feature..."
    if ! command -v docker &>/dev/null; then
        warn "Docker is not installed."
        ask "Install Docker now? [Y/n, default: Y]:"
        read -r INSTALL_DOCKER
        INSTALL_DOCKER="${INSTALL_DOCKER:-y}"
        
        if [[ "$INSTALL_DOCKER" =~ ^[Yy]$ ]]; then
            info "Installing Docker..."
            if ! curl -fsSL https://get.docker.com | sudo sh >/dev/null 2>&1; then
                error "Failed to install Docker. Please install manually from: https://docs.docker.com/get-docker/"
            fi
            success "Docker installed successfully."
        else
            error "Docker is required for Lab feature. Please install from: https://docs.docker.com/get-docker/"
        fi
    fi
    success "Docker found ($(docker --version))."
    
    # ── Docker Group Setup ────────────────────────────────────────────────────
    # Ensure current user is in docker group for passwordless access
    if ! groups "$USER" | grep -q docker; then
        info "Adding $USER to docker group for passwordless access..."
        sudo usermod -aG docker "$USER"
        # Create newgrp activation script so docker commands work immediately
        if newgrp docker &>/dev/null; then
            success "User added to docker group (activated in current session)."
        else
            warn "User added to docker group but needs to log out and back in for changes to take effect."
        fi
    else
        success "User already in docker group."
    fi
    
    LAB_FEATURE_ENABLED=true
    info "Lab feature will be enabled."
else
    LAB_FEATURE_ENABLED=false
    warn "Lab feature will not be available."
    # Remove directories if they won't be used
    rm -rf files/lab files/lab-sockets
fi
echo ""

# ── Step 6 — Build Docker image for Lab feature ────────────────────────────────
if [ "$LAB_FEATURE_ENABLED" = true ]; then
    info "Building Docker image for Lab feature (lanhub-lab:latest)..."
    echo ""

# Build with real-time output showing progress
if docker build -f tools/Dockerfile.lab -t lanhub-lab:latest . 2>&1 | while IFS= read -r line; do
    # Show each build step with indentation and formatting
    if [[ "$line" =~ ^Step\ [0-9] ]]; then
        echo -e "  ${GREEN}→${RESET} $line"
    elif [[ "$line" =~ "Successfully tagged" ]]; then
        echo -e "  ${GREEN}✓${RESET} $line"
    elif [[ "$line" =~ "Step" ]]; then
        echo -e "  ${CYAN}⋯${RESET} $line"
    elif [[ "$line" =~ "ERROR" || "$line" =~ "error" ]]; then
        echo -e "  ${RED}✗${RESET} $line"
    elif [[ ! "$line" =~ ^[[:space:]]*$ ]]; then
        # Show non-empty lines with lighter formatting
        echo "    $line"
    fi
done; then
    echo ""
    success "Docker image built successfully."
    # Create .lab_enabled flag file to mark Lab feature as enabled
    touch .lab_enabled
    success "Lab feature initialized and enabled."
else
    echo ""
    error "Docker image build failed. Lab feature will not work without it."
    LAB_FEATURE_ENABLED=false
fi
else
    info "Lab feature disabled — skipping Docker image build."
fi

# ── Step 7 — cloudflared ──────────────────────────────────────────────────────
if [ "$INSTALL_MODE" = "server" ]; then
    if ! command -v cloudflared &>/dev/null || [ ! -s /usr/local/bin/cloudflared ]; then
        info "Installing cloudflared..."
        ARCH=$(dpkg --print-architecture 2>/dev/null || echo "amd64")
        CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}"
        echo "  Downloading cloudflared-linux-${ARCH} from GitHub..."
        
        # Clean up any old/corrupt versions
        rm -f /tmp/cloudflared /usr/local/bin/cloudflared
        
        # Download with better error handling
        if ! curl -fSL "$CF_URL" -o /tmp/cloudflared 2>&1 | grep -v "^  [0-9]"; then
            error "Failed to download cloudflared. Check your internet connection."
        fi
        
        # Validate the binary was actually downloaded
        if [ ! -s /tmp/cloudflared ]; then
            error "cloudflared download failed (file is empty). Check your internet connection."
        fi
        
        # Validate it's an ELF binary
        if ! file /tmp/cloudflared | grep -q "ELF"; then
            warn "Downloaded file doesn't look like a valid binary. Contents:"
            head -c 200 /tmp/cloudflared
            error "cloudflared download corrupted. Try again."
        fi
        
        chmod +x /tmp/cloudflared
        sudo mv /tmp/cloudflared /usr/local/bin/cloudflared
        success "cloudflared installed."
    else
        success "cloudflared already installed."
    fi
    
    # Verify cloudflared works
    if ! cloudflared --version &>/dev/null; then
        warn "cloudflared not responding. Attempting fresh install..."
        sudo rm -f /usr/local/bin/cloudflared
        
        # Fresh download attempt
        ARCH=$(dpkg --print-architecture 2>/dev/null || echo "amd64")
        CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}"
        echo "  Re-downloading cloudflared-linux-${ARCH}..."
        
        if curl -fSL "$CF_URL" -o /tmp/cloudflared 2>&1 | grep -v "^  [0-9]"; then
            if [ -s /tmp/cloudflared ] && file /tmp/cloudflared | grep -q "ELF"; then
                chmod +x /tmp/cloudflared
                sudo mv /tmp/cloudflared /usr/local/bin/cloudflared
                if cloudflared --version &>/dev/null; then
                    success "cloudflared reinstalled successfully ($(cloudflared --version 2>&1 | head -1))."
                else
                    warn "cloudflared installed but still not responding. You may need to reinstall it manually."
                fi
            else
                warn "cloudflared download failed again. Tunnel will not be available."
                warn "Manual install: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
            fi
        else
            warn "Could not download cloudflared. Tunnel will not be available."
            warn "Manual install: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
        fi
    else
        success "cloudflared verified working ($(cloudflared --version 2>&1 | head -1))."
    fi
else
    info "Skipping cloudflared (not needed for ${INSTALL_MODE} mode)."
fi

# ── Step 7 — SSH key ──────────────────────────────────────────────────────────
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
    
    # Add GitHub to known_hosts to avoid SSH host key verification issues
    info "Configuring SSH for GitHub..."
    if ! grep -q "github.com" "$HOME/.ssh/known_hosts" 2>/dev/null; then
        mkdir -p "$HOME/.ssh"
        ssh-keyscan -H github.com >> "$HOME/.ssh/known_hosts" 2>/dev/null
        chmod 600 "$HOME/.ssh/known_hosts"
        success "GitHub added to known_hosts."
    else
        success "GitHub already in known_hosts."
    fi

    # Configure git user (needed for any git operations)
    if [ -z "$(git config --global user.name 2>/dev/null)" ]; then
        info "Configuring git user..."
        git config --global user.name "LANHub Server"
        git config --global user.email "server@lanhub.local"
        success "Git user configured."
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

# ── Step 8 — Interactive config ───────────────────────────────────────────────
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

# ── Step 9 — Disable sleep ────────────────────────────────────────────────────
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

# ── Step 10 — Write start.sh ───────────────────────────────────────────────────
info "Writing start.sh..."

if [ "$INSTALL_MODE" = "server" ]; then
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

echo "Starting LANHub server on port $PORT (LAN access)..."
source venv/bin/activate
python app.py
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

# ── Step 11 — systemd service ───────────────────────────────────────────────────
if [ "$INSTALL_MODE" = "dev" ]; then
    info "Skipping systemd service (dev mode — run './start.sh' manually)."
else
    CURRENT_USER=$(whoami)
    SERVICE_NAME="lanhub"

    # Loop to ensure we get a unique or explicitly overwritten service name
    while true; do
        SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
        if [ -f "$SERVICE_FILE" ]; then
            warn "A systemd service named '${SERVICE_NAME}' already exists."
            ask "Do you want to (O)verwrite it, or (R)ename this new service? [O/r]:"
            read -r OVERWRITE_CHOICE
            if [[ "$OVERWRITE_CHOICE" =~ ^[Rr]$ ]]; then
                ask "Enter new service name (e.g., lanhub-dev, lanhub2):"
                read -r SERVICE_NAME
                # Loop back to check if the new name exists!
                continue
            else
                info "Overwriting ${SERVICE_NAME}.service..."
                break
            fi
        else
            break # Name is unique and safe to use
        fi
    done

    # CRITICAL: Record the service name so update scripts know what to restart
    echo "$SERVICE_NAME" > .service_name
    success "Service name recorded as '${SERVICE_NAME}'"

    info "Writing systemd service (${SERVICE_NAME}.service)..."
    sudo tee "$SERVICE_FILE" > /dev/null <<SERVICE
[Unit]
Description=LANHub Server (${SERVICE_NAME})
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
    sudo systemctl enable "$SERVICE_NAME"
    success "systemd service ($SERVICE_NAME) installed and enabled."
fi

# ── Step 12 — Nginx reverse proxy for Lab WebSocket support ──────────────────
if [ "$INSTALL_MODE" = "server" ] || [ "$INSTALL_MODE" = "local" ]; then
    info "Configuring Nginx as reverse proxy (minimal config for Lab WebSocket support)..."
    
    # Get LANHub port from config
    LANHUB_PORT=$(./venv/bin/python3 -c "
import json
try:
    with open('configvars.json') as f:
        print(json.load(f).get('general', {}).get('PORT', 5000))
except:
    print(5000)
" 2>/dev/null || echo "5000")
    
    # Get project directory
    PROJECT_DIR="$SCRIPT_DIR"
    SOCKET_DIR="${PROJECT_DIR}/files/lab-sockets"
    
    # Check if Lab feature is enabled (flag file exists)
    if [ -f "${PROJECT_DIR}/.lab_enabled" ]; then
        info "Lab feature enabled — setting up Nginx for WebSocket proxying..."
        
        # Check and install Nginx if needed
        if ! command -v nginx &>/dev/null; then
            info "Installing Nginx..."
            sudo apt-get install -y nginx > /dev/null 2>&1
            success "Nginx installed."
        else
            success "Nginx already installed."
        fi
        
        # Ensure Nginx directories exist
        sudo mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
        
        NGINX_CONF="/etc/nginx/sites-available/lanhub"
        
        # Create Nginx config with minimal setup - just for Lab WebSocket
        # Note: using unquoted heredoc delimiter to allow bash variable expansion
        sudo bash -c "cat > '$NGINX_CONF' << NGINXEOF
upstream lanhub_backend {
    server localhost:${LANHUB_PORT};
    keepalive 32;
}

# Map upgrade header
map \\\$http_upgrade \\\$connection_upgrade {
    default upgrade;
    '' close;
}

server {
    listen 80;
    server_name _;
    
    # Lab project routes - proxy to Unix socket for code-server
    location ~ ^/lab/project/(?<slug>[a-zA-Z0-9_-]+)/page(/.*)?$ {
        set \\\$socket_path ${SOCKET_DIR}/\\\$slug.sock;
        
        # Proxy to Unix socket (WebSocket upgrade + HTTP)
        proxy_pass http://unix:\\\$socket_path\\\$request_uri;
        
        proxy_http_version 1.1;
        proxy_set_header Host \\\$http_host;
        proxy_set_header Upgrade \\\$http_upgrade;
        proxy_set_header Connection \\\$connection_upgrade;
        proxy_set_header X-Real-IP \\\$remote_addr;
        proxy_set_header X-Forwarded-For \\\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\\$scheme;
        
        proxy_buffering off;
        proxy_connect_timeout 600s;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
    
    # All other traffic to LANHub Flask
    location / {
        proxy_pass http://lanhub_backend;
        proxy_http_version 1.1;
        proxy_set_header Host \\\$http_host;
        proxy_set_header X-Real-IP \\\$remote_addr;
        proxy_set_header X-Forwarded-For \\\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\\$scheme;
        proxy_buffering off;
    }
}
NGINXEOF
"
        
        # Enable site
        if [ ! -L /etc/nginx/sites-enabled/lanhub ]; then
            sudo ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/lanhub
        fi
        
        # Test and reload — show full error output if it fails
        if NGINX_TEST_OUTPUT=$(sudo nginx -t 2>&1); then
            sudo systemctl restart nginx
            success "Nginx configured for Lab WebSocket proxying."
        else
            warn "Nginx configuration test failed:"
            echo "$NGINX_TEST_OUTPUT" | sed 's/^/  /'
            warn "Lab WebSocket may not work. Fix the config and run: sudo nginx -t"
        fi
    else
        info "Lab feature not enabled — skipping Nginx setup."
    fi
else
    info "Skipping Nginx setup (${INSTALL_MODE} mode)."
fi

# ── Step 11 — Initial redirector push ─────────────────────────────────────────
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

# ── Start Nginx for Lab WebSocket support ─────────────────────────────────────
if [ "$INSTALL_MODE" != "dev" ] && [ -f "${PROJECT_DIR}/.lab_enabled" ] 2>/dev/null; then
    info "Starting Nginx for Lab WebSocket proxying..."
    
    # Unmask Nginx if it's masked
    sudo systemctl unmask nginx 2>/dev/null
    
    if sudo systemctl enable nginx >/dev/null 2>&1; then
        success "Nginx enabled on boot."
    fi
    
    if sudo systemctl restart nginx >/dev/null 2>&1; then
        success "Nginx started and ready for Lab WebSocket connections."
    else
        warn "Failed to start Nginx. Lab routes may not work. Run: sudo systemctl unmask nginx && sudo systemctl start nginx"
    fi
fi

# ── Initialize updates tracking ───────────────────────────────────────────────
info "Initializing update tracking system..."

./venv/bin/python3 - <<'UPDATESPY'
import json
import sys
import time

try:
    # Read all available updates from updates.json
    with open('updates/updates.json', 'r') as f:
        available_updates = json.load(f)
    
    # Convert to updated.json format: mark all as already installed
    # This ensures a fresh install won't try to re-run all past updates
    installed_updates = []
    max_timestamp = 0
    
    for update_name, update_data in available_updates.items():
        installed_updates.append({
            'id': update_data['id'],
            'version': update_data['version'],
            'title': update_name,
            'description': update_data['description'],
            'timestamp': update_data['created_at'],
            'tags': update_data.get('tags', [])
        })
    
    # Create updated.json with all updates marked as installed
    # Note: last_update is the current timestamp (when installation happens), not when updates were created
    current_time = int(time.time())
    updated_data = {
        'manifest': {
            'last_update': current_time
        },
        'updates': installed_updates
    }
    
    # Write to updates/updated.json
    with open('updates/updated.json', 'w') as f:
        json.dump(updated_data, f, indent=2)
    
    print(f"Updated tracking initialized with {len(installed_updates)} updates pre-marked as installed.")
    
except Exception as e:
    print(f"ERROR initializing update tracking: {e}", file=sys.stderr)
    sys.exit(1)

UPDATESPY

success "Update tracking initialized."

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
    # Fetch the chosen service name for the printout
    SVC_NAME=$(cat .service_name 2>/dev/null || echo "lanhub")
    
    echo -e "  Start the server:   ${BOLD}sudo systemctl start ${SVC_NAME}${RESET}"
    echo -e "  Check status:       ${BOLD}sudo systemctl status ${SVC_NAME}${RESET}"
    echo -e "  View logs:          ${BOLD}journalctl -u ${SVC_NAME} -f${RESET}"
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