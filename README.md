# 🛰️ LANHub

A self-hosted hub for your local network (or friends over the internet) featuring chat, file sharing, games, polls, and more.

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
- 🌐 **Public Access** — Cloudflare tunnel with password gate for remote friends

---

## Setup

### Before you start — two browser steps

These two things can't be automated because they require your GitHub account:

**1. Create the redirector repository**
- Go to [github.com/new](https://github.com/new) and create a new repo (e.g. `lanhub-redirect`)
- Add a `README.md` so the `main` branch is created
- Go to **Settings → Pages → Source → Deploy from branch → main / root → Save**

**2. Get your server's SSH key ready to paste**
- You will generate it in the next step — the installer will display it and pause for you to add it at [github.com/settings/ssh/new](https://github.com/settings/ssh/new)

That's it for browser work. Everything else is automated.

---

### Run the installer

Clone the repo and run the install script:

```bash
git clone https://github.com/theplatecrafter/LANHub
cd LANHub
bash install.sh
```

The installer will:
- Install system packages (`git`, `python3`, `python3-venv`, `python3-pip`)
- Create the Python virtual environment and install dependencies
- Install `cloudflared` for the public tunnel
- Generate an SSH key and display it for you to add to GitHub
- Ask a few questions (repo URL, port, admin credentials, access mode)
- Write `configvars.json` automatically
- Optionally disable sleep/hibernation so the server runs 24/7
- Write and enable the `systemd` service so LANHub starts on boot
- Do an initial push to your GitHub Pages redirector

---

### Start the server

```bash
sudo systemctl start lanhub
```

Done. The server is running and will restart automatically on reboot.

Verify it's working:
```bash
sudo systemctl status lanhub
```

---

## Access Modes

Controlled from **Admin Panel → Access Settings** at any time — no file editing needed.

| Mode | Description |
|---|---|
| 🏠 **LAN Only** | Only devices on the same network can connect. Public connections are blocked. |
| 🔑 **Public with Password** | Everyone (LAN and public) must enter the shared password. |
| 🔑 **LAN Free + Public Password** | LAN devices connect freely. Public/tunnel connections require the password. |

> Changing the password immediately invalidates all existing friend sessions — they will need to re-enter the new password.

---

## Sharing with Friends

Once running in a public mode, share your GitHub Pages redirector link:

```
https://YOUR_USERNAME.github.io/lanhub-redirect/
```

Friends visit that link → redirected to your server → enter the password → done.
The link never changes even when your IP or tunnel URL rotates on restart.

---

## Server Management

| Action | Command |
|---|---|
| Start | `sudo systemctl start lanhub` |
| Stop | `sudo systemctl stop lanhub` |
| Restart | `sudo systemctl restart lanhub` |
| Status | `sudo systemctl status lanhub` |
| Live logs | `journalctl -u lanhub -f` |

**Updating LANHub** — go to **Admin Panel → Server → Update** to pull the latest
version, merge config changes, and reinstall dependencies all in one click.

---

## Viewing Logs

| Log | Command |
|---|---|
| App events | `tail -f logs/app.log` |
| User activity | `tail -f logs/access.log` |
| Errors | `tail -f logs/error.log` |
| GitHub sync | `tail -f logs/github_sync.log` |
| Full journal | `journalctl -u lanhub -f` |

---

## SSH Remote Access

Access your server's terminal from another machine on the same network.

```bash
# On the server — one time setup:
sudo apt install openssh-server
sudo systemctl enable --now ssh

# From another computer:
ssh your_username@SERVER_LAN_IP
```