# 🛰️ LANHub

A self-hosted hub for your local network (or friends over the internet) featuring chat, file sharing, games, polls, and more.

---

## Table of Contents

1. [Features](#features)
2. [Requirements](#requirements)
3. [Setup](#setup)
   - [Step 1 — Prepare the Server](#step-1--prepare-the-server)
   - [Step 2 — Deploy LANHub](#step-2--deploy-lanhub)
   - [Step 3 — Configure](#step-3--configure)
   - [Step 4 — Create the systemd Service](#step-4--create-the-systemd-service)
   - [Step 5 — GitHub Pages Redirector](#step-5--github-pages-redirector)
   - [Step 6 — Public Access & Cloudflare Tunnel](#step-6--public-access--cloudflare-tunnel)
4. [Access Modes](#access-modes)
5. [Server Management](#server-management)
6. [SSH Remote Access](#ssh-remote-access)
7. [Viewing Logs](#viewing-logs)

---

## Features

- 💬 **Chat** — global chat with replies, reactions, and rate limiting
- 📢 **Channels** — password-protected persistent chat rooms
- 📁 **Dropzone** — file sharing with quotas and optional password protection
- 📊 **Polls** — create and vote on polls
- 📝 **Feedback** — bug reports and feature requests
- 🔄 **Updates** — post changelogs and announcements
- 📈 **Stats** — live CPU, RAM, disk, GPU, and network monitoring
- 🎮 **Games** — Chess, Tetris, UNO (5 variants), Slither.io, Scribble.io, GeoGuesser
- 🔧 **Admin Panel** — ban management, reports, DB inspector, live terminal, config editor
- 🌐 **Public Access** — optional Cloudflare tunnel with password gate for friends

---

## Requirements

- Linux-based OS (Ubuntu Desktop 22.04/24.04 recommended for campus/dorm use)
- Python 3.10+
- Git
- A GitHub account (for the redirector)

---

## Setup

### Step 1 — Prepare the Server

**Disable sleep/hibernation** so the server stays on 24/7:

```bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

To undo this later:
```bash
sudo systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

**Optional — save RAM by switching to CLI mode** (no desktop GUI):
```bash
sudo systemctl set-default multi-user.target
sudo reboot
```

To switch back to GUI:
```bash
sudo systemctl set-default graphical.target
sudo reboot
```

---

### Step 2 — Deploy LANHub

Install Git if needed:
```bash
sudo apt install git
```

Clone the repository:
```bash
git clone https://github.com/theplatecrafter/LANHub
cd LANHub
```

Install Python and venv tools:
```bash
sudo apt install python3 python3-venv python3-pip
```

Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:
```bash
pip install -r dependencies.txt
```

---

### Step 3 — Configure

Copy the example config:
```bash
cp configvars.example.json configvars.json
nano configvars.json
```

Key fields to set:

| Field | Location | Description |
|---|---|---|
| `REPO_URL` | `general` | URL of your GitHub redirector repository |
| `PORT` | `general` | Port to run on (default `5000`) |
| `INITIAL_DEV_USERNAME` | `admin` | Username for the first DEV account |
| `INITIAL_DEV_PASSWORD` | `admin` | Password for the first DEV account |
| `SITE_MODE` | `access` | Visibility mode (see [Access Modes](#access-modes)) |
| `SITE_PASSWORD` | `access` | Shared password for friends (leave blank to disable) |
| `TUNNEL_URL` | `access` | Auto-filled by `start.sh` — leave blank for now |

> **Note:** `SECRET_KEY` in the `admin` section is auto-generated on first run. Leave it as `"__generate__"`.

---

### Step 4 — Create the systemd Service

This makes LANHub start automatically on boot.

Create the service file:
```bash
sudo nano /etc/systemd/system/lanhub.service
```

Paste the following (replace `<username>` and `<path>` with your own values):
```ini
[Unit]
Description=LANHub Server
After=network.target

[Service]
User=<username>
WorkingDirectory=/home/<username>/<path>/LANHub
ExecStart=/bin/bash /home/<username>/<path>/LANHub/start.sh
Restart=always
RestartSec=5
Environment="PYTHONUNBUFFERED=1"
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Save and exit, then enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable lanhub
sudo systemctl start lanhub
sudo systemctl status lanhub
```

> **Tip:** `start.sh` launches the Cloudflare tunnel first, then starts the Flask app.
> See [Step 6](#step-6--public-access--cloudflare-tunnel) for setup.
> If you are LAN-only and don't need the tunnel, you can change `ExecStart` to point
> directly to `python app.py` instead.

---

### Step 5 — GitHub Pages Redirector

The redirector is a GitHub Pages site that always points to your server's current
address. Friends bookmark this one link and it always finds your server even if
your IP or tunnel URL changes.

**5.1 — Generate an SSH key on the server:**
```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
```
Press Enter at all prompts to use defaults.

**5.2 — Copy the public key:**
```bash
cat ~/.ssh/id_ed25519.pub
```

**5.3 — Add it to GitHub:**
Go to **GitHub → Account Settings → SSH and GPG keys → New SSH key**, paste the key, and save.

**5.4 — Create a new GitHub repository:**
- Name it anything you like (e.g. `lanhub-redirect`)
- Add a `README.md` file so the `main` branch is created
- Go to **Settings → Pages → Source → Deploy from branch → main / root** and save

**5.5 — Set `REPO_URL` in configvars.json:**
```json
"REPO_URL": "https://github.com/YOUR_USERNAME/lanhub-redirect"
```

**5.6 — Test the push:**
```bash
cd /home/<username>/<path>/LANHub
python app.py
```

On first run the app will clone the redirector repo and attempt a push.
Check the log for success:
```bash
tail -f logs/github_sync.log
```

If you see an authentication error:
```bash
cd lanhub-redirect
git remote set-url origin git@github.com:YOUR_USERNAME/lanhub-redirect.git
git push
cd ..
```

Then restart the app — subsequent pushes will use SSH automatically.

---

### Step 6 — Public Access & Cloudflare Tunnel

This step lets friends outside your local network connect to LANHub securely
over HTTPS, with no router or port forwarding required.

**6.1 — Install cloudflared:**
```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
     -o cloudflared
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/
cloudflared --version
```

**6.2 — Make start.sh executable:**
```bash
chmod +x start.sh
```

**6.3 — Test it:**
```bash
./start.sh
```

You should see output like:
```
🚀 Starting Cloudflare tunnel...
✅ Tunnel URL: https://abc-xyz-123.trycloudflare.com
configvars.json updated with tunnel URL
🌐 Starting LANHub server...
```

Within about 60 seconds the GitHub Pages redirector will be updated with the
new tunnel URL automatically.

**6.4 — Set an access password (optional but recommended):**

Log into the admin panel at `http://localhost:5000/admin`, go to
**Access Settings**, and fill in:
- **Visibility Mode** — choose one (see [Access Modes](#access-modes))
- **Access Password** — the shared password you give to friends
- **Remember-me Duration** — how many days before friends need to re-enter it

**6.5 — Share with friends:**

Give your friends the GitHub Pages URL:
```
https://YOUR_USERNAME.github.io/lanhub-redirect/
```

They visit that link → get redirected to the tunnel → enter the password → done.
The link never changes even when the tunnel URL rotates on restart.

---

## Access Modes

Controlled from **Admin Panel → Access Settings** (or directly in `configvars.json`).

| Mode | `SITE_MODE` value | Description |
|---|---|---|
| 🏠 LAN Only | `lan_only` | Only devices on the same network can connect. Public connections receive a 403 blocked page. |
| 🔑 Public with Password | `public_password` | Everyone (LAN and public) must enter the shared password. |
| 🔑 LAN Free + Public Password | `both_password` | LAN devices connect freely. Public/tunnel connections require the password. |

> Changing the password in the admin panel **immediately** invalidates all existing
> friend sessions — they will need to re-enter the new password.

---

## Server Management

**Start:**
```bash
sudo systemctl start lanhub
```

**Stop:**
```bash
sudo systemctl stop lanhub
```

**Restart:**
```bash
sudo systemctl restart lanhub
```

**Check status:**
```bash
sudo systemctl status lanhub
```

**Update LANHub** (from the admin panel):
Go to **Admin → Server → Update** — this runs `git pull`, merges any new config
keys, and installs updated dependencies automatically.

Or manually from the terminal:
```bash
sudo systemctl stop lanhub
git pull
sudo systemctl daemon-reload
sudo systemctl start lanhub
```

---

## SSH Remote Access

Access your server's terminal from another computer on the same network.

**On the server — install and enable SSH:**
```bash
sudo apt update
sudo apt install openssh-server
sudo systemctl enable ssh
sudo systemctl start ssh
```

**Find the server's LAN IP:**
```bash
ip a
```

**Connect from another computer:**
```bash
ssh your_username@SERVER_LAN_IP
```

---

## Viewing Logs

All logs are in the `logs/` folder. Use `tail -f` to follow them live.

| Log | Command | Contents |
|---|---|---|
| App | `tail -f logs/app.log` | General app events |
| Access | `tail -f logs/access.log` | User activity (messages, uploads, etc.) |
| Errors | `tail -f logs/error.log` | Errors and exceptions |
| GitHub Sync | `tail -f logs/github_sync.log` | Redirector push results |
| Full journal | `journalctl -u lanhub -f` | Everything including stdout |