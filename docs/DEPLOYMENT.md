# LANHub Deployment Guide

**Production and staging deployment procedures for LANHub**

> Last Updated: April 2026

---

## Table of Contents

1. [Requirements](#requirements)
2. [Development Deployment](#development-deployment)
3. [Staging Deployment](#staging-deployment)
4. [Production Deployment](#production-deployment)
5. [Docker Deployment](#docker-deployment)
6. [Configuration](#configuration)
7. [Monitoring](#monitoring)
8. [Troubleshooting](#troubleshooting)
9. [Rollback Procedures](#rollback-procedures)

---

## Requirements

### System Requirements
- Python 3.10+
- SQLite3 or PostgreSQL
- Redis (optional, for caching/sessions)
- 1GB+ RAM minimum
- 500MB+ disk space

### Network Requirements
- Port 5000 (default Flask)
- Port 80/443 (production reverse proxy)
- Firewall rules for Socket.IO WebSocket

### Dependencies
- Flask and Flask-SocketIO
- python-socketio
- All packages in `dependencies.txt`

---

## Development Deployment

### Quick Start

```bash
# 1. Clone and setup
git clone https://github.com/your-org/LANHub.git
cd LANHub
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r dependencies.txt
pip install -r requirements-dev.txt

# 3. Setup configuration
cp configvars.example.json configvars.json
# Edit configvars.json with your settings

# 4. Run development server
python app.py
```

Access at `http://localhost:5000`

### Development Server

```bash
# With auto-reload
FLASK_ENV=development FLASK_APP=app.py flask run

# With debug mode
FLASK_DEBUG=True python app.py

# Custom port
python app.py --port 8000
```

### Database Setup (Development)

```bash
# SQLite (default, automatic)
# Database creates at app.db on first run

# Or use provided script
./install.sh
```

---

## Staging Deployment

### Environment Setup

```bash
# Create staging directory
mkdir -p /var/www/lanhub-staging
cd /var/www/lanhub-staging

# Clone with specific branch
git clone -b develop https://github.com/your-org/LANHub.git .

# Setup venv
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r dependencies.txt
```

### Configuration

```bash
# Copy and edit config
cp configvars.example.json configvars.json

# Set staging-specific values
{
  "DEBUG": false,
  "TESTING": false,
  "SERVER_NAME": "staging.lanhub.local",
  "DATABASE": "staging.db",
  "REDIS_URL": "redis://localhost:6379/1"
}
```

### Run Staging

```bash
# Using Gunicorn (production-like server)
gunicorn -w 4 -b 0.0.0.0:5001 app:app

# Or with systemd service (see below)
systemctl start lanhub-staging
```

---

## Production Deployment

### Pre-deployment Checklist

- [ ] All tests passing: `pytest tests/`
- [ ] Code formatted: `black --check .`
- [ ] Security scan: `bandit -r .`
- [ ] Dependencies secure: `safety check`
- [ ] Configuration file exists and valid
- [ ] Database backed up
- [ ] SSL certificates ready
- [ ] Reverse proxy configured (Nginx/Apache)

### Installation

```bash
# 1. Create production directory
mkdir -p /var/www/lanhub
cd /var/www/lanhub

# 2. Clone production branch
git clone -b main https://github.com/your-org/LANHub.git .

# 3. Setup environment
python3 -m venv venv
source venv/bin/activate
pip install -r dependencies.txt

# 4. Create non-root user
useradd -r -s /bin/bash lanhub
chown -R lanhub:lanhub /var/www/lanhub
```

### Configuration

```bash
# Setup production config
sudo -u lanhub cp configvars.example.json configvars.json

# Edit with production values
{
  "DEBUG": false,
  "TESTING": false,
  "SERVER_NAME": "games.example.com",
  "DATABASE": "/var/lib/lanhub/app.db",
  "SECRET_KEY": "your-secret-key-here",
  "REDIS_URL": "redis://localhost:6379/0",
  "MAX_PLAYERS": 50,
  "LOG_LEVEL": "INFO"
}
```

### Systemd Service

Create `/etc/systemd/system/lanhub.service`:

```ini
[Unit]
Description=LANHub Game Server
After=network.target redis.service

[Service]
Type=notify
User=lanhub
WorkingDirectory=/var/www/lanhub
Environment="PATH=/var/www/lanhub/venv/bin"
ExecStart=/var/www/lanhub/venv/bin/gunicorn \
  --workers 4 \
  --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker \
  --bind 127.0.0.1:5000 \
  --access-logfile /var/log/lanhub/access.log \
  --error-logfile /var/log/lanhub/error.log \
  app:app
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable lanhub
sudo systemctl start lanhub
sudo systemctl status lanhub
```

### Nginx Reverse Proxy

Create `/etc/nginx/sites-available/lanhub`:

```nginx
upstream lanhub {
    server 127.0.0.1:5000;
}

server {
    listen 80;
    server_name games.example.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name games.example.com;

    ssl_certificate /etc/letsencrypt/live/games.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/games.example.com/privkey.pem;

    client_max_body_size 100M;

    location / {
        proxy_pass http://lanhub;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /var/www/lanhub/static/;
        expires 30d;
    }
}
```

Enable site:

```bash
sudo ln -s /etc/nginx/sites-available/lanhub /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### SSL with Let's Encrypt

```bash
sudo certbot certonly --webroot -w /var/www/lanhub/static -d games.example.com
sudo systemctl restart nginx
```

---

## Docker Deployment

### Dockerfile

Create `Dockerfile`:

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create non-root user
RUN useradd -m -u 1000 lanhub && chown -R lanhub:lanhub /app
USER lanhub

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health').read()"

# Run application
CMD ["gunicorn", "--workers", "4", "--bind", "0.0.0.0:5000", "app:app"]
```

### Docker Compose

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  lanhub:
    build: .
    ports:
      - "5000:5000"
    environment:
      - FLASK_ENV=production
      - DATABASE=/data/app.db
      - REDIS_URL=redis://redis:6379/0
    volumes:
      - ./data:/data
      - ./configvars.json:/app/configvars.json
    depends_on:
      - redis
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped

volumes:
  redis_data:
```

Deploy:

```bash
docker-compose up -d
docker-compose logs -f lanhub
```

---

## Configuration

### Environment Variables

```bash
# Flask
FLASK_ENV=production
FLASK_DEBUG=false

# LANHub
LANHU_PORT=5000
LANHU_DEBUG=false
LANHU_DATABASE=/var/lib/lanhub/app.db

# Optional
REDIS_URL=redis://localhost:6379/0
LOG_LEVEL=INFO
SECRET_KEY=your-secret-key
```

### configvars.json

```json
{
  "server_name": "LANHub Game Server",
  "max_players": 100,
  "features": [
    "chat",
    "chess",
    "uno",
    "tetris",
    "slither",
    "scribble",
    "geoguesser"
  ],
  "message_limit": 500,
  "upload_limit_mb": 100,
  "session_timeout": 3600,
  "enable_profanity_filter": true
}
```

---

## Monitoring

### Health Check Endpoint

```bash
curl http://localhost:5000/health
```

### Log Files

```bash
# Systemd
sudo journalctl -u lanhub -f

# Gunicorn
tail -f /var/log/lanhub/access.log
tail -f /var/log/lanhub/error.log
```

### Metrics

Monitor:
- Active connections
- Message rate
- Game state changes
- Error rate
- CPU/Memory usage
- Disk space

### Uptime Monitoring

```bash
# Simple curl-based health check
while true; do
  curl -f http://localhost:5000/health || echo "DOWN"
  sleep 60
done
```

---

## Troubleshooting

### Port Already in Use

```bash
# Find process using port 5000
lsof -i :5000

# Kill process
kill -9 <PID>

# Use different port
python app.py --port 8000
```

### Database Locked

```bash
# Check for connections
sqlite3 app.db "pragma integrity_check;"

# Restart Flask application
systemctl restart lanhub
```

### WebSocket Connection Issues

```bash
# Check firewall allows WebSocket traffic
sudo ufw allow 5000/tcp

# Verify CORS settings in configvars.json
# Check reverse proxy WebSocket configuration
```

### Memory Issues

```bash
# Monitor memory usage
free -h
top -p $(pgrep -f gunicorn)

# Increase swap
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### High CPU Usage

```bash
# Check for infinite loops
strace -p <PID>

# Monitor with top
top -p <PID> -d 1

# Profile with cProfile
python -m cProfile -s cumtime app.py
```

---

## Rollback Procedures

### Quick Rollback

```bash
# If latest commit is broken
git revert HEAD
git push origin main

# Restart service
systemctl restart lanhub
```

### Database Rollback

```bash
# Backup current database
cp app.db app.db.backup

# Restore from backup
cp app.db.old app.db

# Restart service
systemctl restart lanhub
```

### Full Rollback

```bash
# Stop service
systemctl stop lanhub

# Checkout previous version
git checkout <previous-commit-hash>

# Restore database if needed
cp /backups/app.db.2024-01-15 app.db

# Start service
systemctl start lanhub

# Verify health
systemctl status lanhub
curl http://localhost:5000/health
```

### Backup Strategy

```bash
#!/bin/bash
# Daily backup script
BACKUP_DIR="/backups/lanhub"
DATE=$(date +%Y-%m-%d)

mkdir -p $BACKUP_DIR
cp /var/lib/lanhub/app.db $BACKUP_DIR/app.db.$DATE
tar -czf $BACKUP_DIR/config.$DATE.tar.gz /var/www/lanhub/configvars.json

# Keep last 30 days
find $BACKUP_DIR -mtime +30 -delete
```

Schedule in crontab:

```
0 2 * * * /usr/local/bin/backup-lanhub.sh
```

---

## Post-Deployment

### Verify Deployment

```bash
# Check service running
systemctl status lanhub

# Test endpoints
curl http://localhost:5000/health
curl http://localhost:5000/

# Check logs
journalctl -u lanhub -n 100

# Monitor for 5 minutes
watch -n 1 'systemctl show -p ActiveState --value lanhub'
```

### Performance Tuning

```bash
# Increase file descriptors
ulimit -n 65536

# Optimize Nginx
worker_processes auto;
worker_connections 4096;

# Enable gzip compression
gzip on;
gzip_types text/plain text/css application/json;
```

---

**Deployment complete! Monitor your LANHub instance.**
