# LANHub Developer Guide

**Complete documentation for the reorganized LANHub codebase (Phase 1-4)**

> Last Updated: April 2026  
> Status: Phase 4 - Final Documentation  
> Audience: Developers adding features or maintaining the codebase

---

## Table of Contents

1. [Repository Architecture](#repository-architecture)
2. [Directory Structure](#directory-structure)
3. [Core Python Modules](#core-python-modules)
4. [Framework & Technologies](#framework--technologies)
5. [How to Add a New Feature](#how-to-add-a-new-feature)
6. [Common Development Tasks](#common-development-tasks)
7. [Database Operations](#database-operations)
8. [Socket Events & Real-time Communication](#socket-events--real-time-communication)
9. [Configuration Management](#configuration-management)
10. [Debugging & Troubleshooting](#debugging--troubleshooting)

---

## Repository Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Client (Web UI)                      │
│              (HTML/CSS/JS - templates/)                 │
└──────────────────────┬──────────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        │                             │
   REST API                      WebSocket
   (HTTP requests)               (Socket.io)
        │                             │
```

```
┌────────────────────────────────────────────────────────────┐
│                  Flask + Flask-SocketIO                    │  
│                     (app.py)                               │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  ┌─────────────────────────────────────────────────────┐  │
│  │              Blueprints (Routes)                    │  │
│  │  ├── blueprints/admin/     (admin routes)          │  │
│  │  ├── blueprints/chat/      (messaging routes)      │  │
│  │  ├── blueprints/games/     (game routes)           │  │
│  │  └── blueprints/utilities/ (utility routes)        │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌─────────────────────────────────────────────────────┐  │
│  │          Socket Event Handlers                      │  │
│  │          (socket_events/)                           │  │
│  │  ├── chat_events.py                                │  │
│  │  ├── chess_events.py                               │  │
│  │  └── ... (other game events)                       │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌─────────────────────────────────────────────────────┐  │
│  │         Core Business Logic                         │  │
│  │  ├── functions/ (87 functions in 12 modules)       │  │
│  │  ├── shared/    (shared utilities)                 │  │
│  │  ├── game_logic/ (chess AI, uno engine)            │  │
│  │  └── utils/    (database, scheduler)               │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                            │
└────────────────────────────────────────────────────────────┘
        │
        └──► SQLite Database (app.db)
```

### Request Flow Example

```
User clicks "Send Message" button
  │
  ├─► JavaScript sends WebSocket event: emit('send_chat', {message: "Hi!"})
  │
  ├─► Socket handler receives: handle_send_chat() in socket_events/chat_events.py
  │
  ├─► Business logic: functions.save_chat_message() stores message in database
  │
  ├─► Response: emit('chat_message', {id: 123, text: "Hi!", timestamp: ...})
  │
  └─► Client updates UI with new message
```

---

## Directory Structure

### Complete Layout

```
LANHub/
├── app.py                          ★ Main Flask application
├── socketio_instance.py            ★ Socket.io configuration
├── config.py                       ★ Configuration management
├── glob_vars.py                    ★ Global variables & logging
│
├── blueprints/                     ● Route handlers (organized by feature)
│   ├── __init__.py
│   ├── admin/                      - Admin, backup, logs
│   │   ├── __init__.py
│   │   ├── admin.py                - Admin user management
│   │   ├── auth_utils.py           - Shared auth utilities
│   │   ├── backup.py               - Database backup
│   │   ├── logs.py                 - System logs viewing
│   │   ├── bans.py                 - IP ban management
│   │   ├── console.py              - Admin console
│   │   ├── config.py               - Server configuration
│   │   ├── db.py                   - Database management
│   │   ├── power.py                - Server control (restart, etc)
│   │   ├── reports.py              - User report management
│   │   └── server.py               - Server info page
│   │
│   ├── chat/                       - Chat & messaging
│   │   ├── __init__.py
│   │   ├── chat.py                 - Direct messages
│   │   ├── channels.py             - Chat channels
│   │   ├── feedback.py             - User feedback system
│   │   ├── polls.py                - Voting/polls feature
│   │   └── access.py               - Access control
│   │
│   ├── games/                      - Game routes
│   │   ├── __init__.py
│   │   ├── chess.py                - Chess game
│   │   ├── tetris.py               - Tetris game
│   │   ├── uno.py                  - UNO card game
│   │   ├── slither.py              - Slither snake game
│   │   ├── scribble.py             - Scribble drawing game
│   │   └── geoguesser.py           - Geoguesser game
│   │
│   └── utilities/                  - Utility routes
│       ├── __init__.py
│       ├── access.py               - Site access/login
│       ├── devices.py              - Device management
│       ├── dropzone.py             - File upload
│       ├── stats.py                - Server statistics
│       ├── updates.py              - Version history
│       └── server_config.py        - Server configuration UI
│
├── socket_events/                  ● WebSocket event handlers
│   ├── __init__.py
│   ├── chat_events.py              - Chat message events
│   ├── chess_events.py             - Chess game events
│   ├── uno_events.py               - UNO game events
│   ├── tetris_events.py            - Tetris game events
│   ├── slither_events.py           - Slither game events
│   ├── scribble_events.py          - Scribble game events
│   ├── geoguesser_events.py        - Geoguesser game events
│   ├── channels_events.py          - Channel events
│   ├── console_events.py           - Admin console events
│   └── global_events.py            - Connection, handshake, etc
│
├── functions/                      ● Business logic (87 functions, 12 modules)
│   ├── __init__.py                 - Master re-exports
│   ├── db.py                       - Database operations ⭐
│   ├── chat.py                     - Chat & messaging logic
│   ├── admin.py                    - Admin user management
│   ├── moderation.py               - IP bans & reports
│   ├── server.py                   - System monitoring
│   ├── dropzone.py                 - File upload handling
│   ├── feedback.py                 - User feedback logic
│   ├── polls.py                    - Poll/voting logic
│   ├── updates.py                  - Version tracking
│   ├── geoguesser.py               - Geoguesser presets
│   ├── profanity.py                - Content filtering
│   └── redirector.py               - GitHub redirector
│
├── shared/                         ● Reusable utilities
│   ├── __init__.py
│   ├── game_session.py             - Session management ⭐
│   ├── validators.py               - Input validation ⭐
│   └── config_helper.py            - Configuration helpers
│
├── game_logic/                     ● Game engines
│   ├── chess/
│   │   ├── __init__.py
│   │   └── chess_ai.py             - Chess AI (negamax + alpha-beta)
│   └── uno/
│       ├── __init__.py
│       └── uno_game.py             - UNO engine
│
├── utils/                          ● Utilities & background tasks
│   ├── __init__.py
│   ├── init.py                     - Database & app initialization
│   ├── scheduler.py                - Background job scheduler
│   └── write_update.py             - Update management
│
├── templates/                      ● HTML templates (Jinja2)
│   ├── base.html                   - Base template
│   ├── root.html                   - Home page
│   ├── about.html                  - About page
│   ├── chat.html, channels.html    - Chat templates
│   ├── [game].html                 - Game templates
│   ├── admin-*.html                - Admin pages
│   └── ja/                         - Japanese translations
│
├── static/                         ● Static assets
│   ├── js/
│   │   └── commands.js             - Client-side commands
│   └── themes/
│       └── *.css                   - Theme stylesheets
│
├── files/
│   └── dropzone/                   - Uploaded user files
│
├── logs/                           - Application logs
│   ├── access.log                  - HTTP access log
│   ├── app.log                     - Application events
│   ├── error.log                   - Error logs
│   └── github.log                  - GitHub sync logs
│
├── configvars.json                 ★ Configuration (DO NOT commit)
├── configvars.example.json         ★ Configuration template
├── app.db                          - SQLite database
├── main_update.json                - Global update history
│
├── DEVELOPER_GUIDE.md              (this file)
├── REFACTORING_PHASE3.md           - Phase 3 details
├── REFACTORING_NOTES.md            - Phase 1-2 details
├── ORGANIZATION.md                 - Repository organization
├── README.md                       - Project overview
│
└── venv/                           - Python virtual environment
```

**Legend:**
- `★` = Entry point or critical file
- `●` = Feature category
- `⭐` = Most commonly used in development

---

## Core Python Modules

### 1. functions/db.py ⭐ — Database Operations

**Purpose:** All low-level database operations

**Key Functions:**

```python
def get_db() -> sqlite3.Connection
    """Get SQLite connection with Row factory."""
    Returns: Connection object with row_factory=sqlite3.Row
    Usage:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM messages")
        rows = c.fetchall()
        conn.close()

def db_query(sql: str, params: list = []) -> list[tuple]
    """Execute SELECT query and return results."""
    Returns: List of Row objects
    Usage:
        rows = db_query("SELECT * FROM users WHERE id=?", [user_id])
        for row in rows:
            print(row["username"])

def db_get_row(table: str, id: int) -> dict | None
    """Get single row by ID."""
    Returns: Dict or None if not found
    Usage:
        user = db_get_row("users", 123)
        if user:
            print(user["username"])

def db_insert(table: str, data: dict) -> int
    """Insert row and return last insert ID."""
    Returns: ID of inserted row
    Usage:
        user_id = db_insert("users", {
            "username": "john",
            "password_hash": hash,
            "created_at": time.time()
        })

def db_update_row(table: str, id: int, data: dict) -> None
    """Update row by ID."""
    Usage:
        db_update_row("users", user_id, {
            "last_seen": time.time(),
            "is_active": True
        })

def db_delete_row(table: str, id: int) -> None
    """Delete row by ID."""
    Usage:
        db_delete_row("messages", message_id)

def db_get_tables() -> list[str]
    """List all table names."""
    Returns: List of table names
    Usage:
        tables = db_get_tables()  # ['users', 'messages', 'channels', ...]

def db_get_schema(table: str) -> list[dict]
    """Get table schema (column info)."""
    Returns: List of dicts with column information
    Usage:
        schema = db_get_schema("messages")
        for col in schema:
            print(f"{col['name']}: {col['type']}")
```

**Common Patterns:**

```python
# Pattern 1: Insert and get ID
import functions as f
user_id = f.db_insert("users", {"username": "alice"})

# Pattern 2: Query multiple rows
messages = f.db_query("SELECT * FROM messages WHERE user_id=? ORDER BY timestamp DESC LIMIT 10", [user_id])

# Pattern 3: Update existing row
f.db_update_row("users", user_id, {"last_seen": time.time()})

# Pattern 4: Get single row by ID
user = f.db_get_row("users", user_id)

# Pattern 5: Delete row
f.db_delete_row("messages", message_id)
```

---

### 2. functions/chat.py — Messaging & Channels

**Purpose:** Direct messages, chat channels, rate limiting

**Key Functions:**

```python
def save_chat_message(text: str, sender_ip: str, sender_name: str = "") -> dict
    """Save direct message."""
    Returns: Message dict with id, text, sender_name, timestamp
    Usage:
        msg = f.save_chat_message(
            "Hello!",
            sender_ip="192.168.1.1",
            sender_name="Alice"
        )
        print(msg["id"])  # Message ID in database

def get_recent_messages(limit: int = 50) -> list[dict]
    """Get recent direct messages."""
    Returns: List of message dicts
    Usage:
        messages = f.get_recent_messages(limit=100)
        for msg in messages:
            print(f"{msg['sender_name']}: {msg['text']}")

def is_rate_limited(ip: str, limit: int = 5, window_seconds: int = 10) -> bool
    """Check if IP has exceeded message rate limit."""
    Returns: True if rate limited
    Usage:
        if f.is_rate_limited(request.remote_addr):
            return jsonify({"error": "Rate limited"}), 429

def create_channel(name: str, description: str, password: str = "", is_dev: bool = False) -> dict
    """Create new chat channel."""
    Returns: Channel dict
    Usage:
        channel = f.create_channel(
            name="general",
            description="General discussion",
            password="",  # "" = no password
            is_dev=True
        )

def search_channels(query: str = "", tag: str = "") -> list[dict]
    """Search channels by name/description or tag."""
    Usage:
        channels = f.search_channels(query="game")
        for ch in channels:
            print(ch["name"], ch["member_count"])

def save_channel_message(channel_id: int, text: str, sender_ip: str, sender_name: str = "") -> dict
    """Post message to channel."""
    Usage:
        msg = f.save_channel_message(
            channel_id=1,
            text="Hello channel!",
            sender_ip="192.168.1.1",
            sender_name="Bob"
        )

def get_channel_messages(channel_id: int, limit: int = 50) -> list[dict]
    """Get messages from channel."""
    Usage:
        messages = f.get_channel_messages(channel_id=1, limit=100)

def delete_message(message_id: int) -> None
    """Delete message."""
    Usage:
        f.delete_message(message_id)

def verify_channel_password(channel_id: int, password: str) -> bool
    """Check channel password."""
    Returns: True if password matches or channel has no password
    Usage:
        if f.verify_channel_password(channel_id, user_password):
            # User can join
```

**Common Pattern - Chat Handler:**

```python
# In socket_events/chat_events.py
import functions as f
from shared import GameSessionManager

chat_sessions = GameSessionManager(name="chat")

@socketio.on('send_message')
def handle_send_message(data):
    text = data.get('text', '').strip()
    sender_ip = request.remote_addr
    sender_name = chat_sessions[request.sid].get('username', 'Anonymous')
    
    # Check rate limit
    if f.is_rate_limited(sender_ip):
        emit('error', {'message': 'Rate limited'})
        return
    
    # Check profanity
    if f.check_profanity(text):
        emit('error', {'message': 'Message contains disallowed content'})
        return
    
    # Save message
    msg = f.save_chat_message(text, sender_ip, sender_name)
    
    # Broadcast to all connected clients
    emit('new_message', msg, broadcast=True)
```

---

### 3. shared/game_session.py ⭐ — Session Management

**Purpose:** Unified session tracking for all games

**Class: GameSessionManager**

```python
class GameSessionManager(dict):
    """Dict-like object for managing game sessions."""
    
    def __init__(self, name: str = "default"):
        """Initialize session manager."""
        self.name = name
        self.session_data = {}
    
    def __getitem__(self, session_id: str) -> dict:
        """Get session: sessions[sid] returns {"username": "Alice", ...}"""
        return self.session_data.get(session_id, {})
    
    def __setitem__(self, session_id: str, value: dict) -> None:
        """Set session: sessions[sid] = {"username": "Alice"}"""
        self.session_data[session_id] = value
    
    def __contains__(self, session_id: str) -> bool:
        """Check if session exists: sid in sessions"""
        return session_id in self.session_data
    
    def pop(self, session_id: str, default=None):
        """Remove session: sessions.pop(sid)"""
        return self.session_data.pop(session_id, default)
    
    def items():
        """Get all sessions: for sid, data in sessions.items()"""
        return self.session_data.items()
    
    def get_active_usernames(self) -> set[str]:
        """Get set of all active usernames."""
        return {v.get("username") for v in self.session_data.values()}
    
    def get_online_count(self) -> int:
        """Get number of active sessions."""
        return len(self.session_data)
```

**Usage Example:**

```python
from shared import GameSessionManager

# Create session manager for a game
chess_sessions = GameSessionManager(name="chess")

# Store session data when user joins
chess_sessions[request.sid] = {
    "username": "alice",
    "color": "white",
    "elo": 1600,
    "join_time": time.time()
}

# Check if session exists
if request.sid in chess_sessions:
    player_data = chess_sessions[request.sid]
    print(player_data["username"])

# Get all active usernames
players = chess_sessions.get_active_usernames()
print(f"Players: {players}")

# Get online count
print(f"Online: {chess_sessions.get_online_count()}")

# Remove session when user leaves
chess_sessions.pop(request.sid)

# Iterate all sessions
for sid, player_data in chess_sessions.items():
    print(f"{sid}: {player_data['username']}")
```

---

### 4. shared/validators.py — Input Validation

**Purpose:** Consistent validation across all games

**Key Functions:**

```python
def validate_username(
    username: str,
    max_length: int = 24,
    taken_usernames: set[str] = set(),
    check_profanity_func = None
) -> tuple[bool, str]:
    """Validate username."""
    Returns: (is_valid, error_message)
    
    Checks:
    - Not empty
    - Not exceeding max_length
    - Not in taken_usernames set
    - No profanity (if check_profanity_func provided)
    
    Usage:
        from shared import validate_username
        import functions as f
        
        is_valid, error = validate_username(
            username="alice",
            max_length=24,
            taken_usernames={"bob", "charlie"},
            check_profanity_func=f.check_profanity
        )
        
        if not is_valid:
            emit('error', {'message': error})
            return  # "Username is already taken" or similar
        
        # Username is valid, continue

def validate_message(
    message: str,
    max_chars: int = 500,
    check_profanity_func = None
) -> tuple[bool, str]:
    """Validate message."""
    Returns: (is_valid, error_message)
    
    Checks:
    - Not empty
    - Not exceeding max_chars
    - No profanity (if check_profanity_func provided)
    
    Usage:
        is_valid, error = validate_message(
            message="Hello world!",
            max_chars=500,
            check_profanity_func=f.check_profanity
        )

def validate_email(email: str) -> tuple[bool, str]:
    """Validate email format."""
    Returns: (is_valid, error_message)
    
    Checks:
    - Valid email format
    - Contains @
    - Contains domain

def validate_ip_address(ip: str) -> bool:
    """Check if valid IP address."""
    Returns: True if valid IPv4
    
    Usage:
        if validate_ip_address(request.remote_addr):
            # Valid IP
```

**Common Pattern:**

```python
from shared import validate_username, validate_message
import functions as f

@socketio.on('join_game')
def handle_join(data):
    username = data.get('username', '').strip()
    
    # Validate username
    is_valid, error = validate_username(
        username,
        max_length=24,
        taken_usernames=game_sessions.get_active_usernames(),
        check_profanity_func=f.check_profanity
    )
    
    if not is_valid:
        emit('join_ack', {'success': False, 'error': error})
        return
    
    # Username valid - store session
    game_sessions[request.sid] = {'username': username}
    emit('join_ack', {'success': True})
```

---

### 5. functions/admin.py — Admin User Management

**Purpose:** Admin account management

**Key Functions:**

```python
def get_all_admins() -> list[dict]:
    """Get all admin accounts."""
    Returns: List of admin dicts (without password hashes)
    Usage:
        admins = f.get_all_admins()
        for admin in admins:
            print(admin["username"], admin["role"])

def get_admin_by_username(username: str) -> dict | None:
    """Get admin by username."""
    Returns: Admin dict or None
    Usage:
        admin = f.get_admin_by_username("dev")
        if admin and admin["role"] == "DEV":
            # User is DEV admin

def create_admin(username: str, password: str, role: str = "ADMIN") -> dict:
    """Create new admin account."""
    Returns: New admin dict
    Roles: "ADMIN", "DEV"
    Usage:
        admin = f.create_admin("alice", "password123", role="ADMIN")

def edit_admin(admin_id: int, data: dict) -> dict | None:
    """Update admin account."""
    Usage:
        f.edit_admin(admin_id, {"role": "DEV"})

def delete_admin(admin_id: int) -> None:
    """Delete admin account."""
    Usage:
        f.delete_admin(admin_id)
```

---

### 6. functions/server.py — System Monitoring

**Purpose:** Collect server statistics and system information

**Key Functions:**

```python
def get_server_stats() -> dict:
    """Get CPU, RAM, disk usage."""
    Returns: {
        "cpu": 45.2,        # Percentage
        "ram": 2048,        # MB
        "ram_max": 8192,    # MB
        "disk": 512,        # GB used
        "disk_max": 1000    # GB total
    }
    Usage:
        stats = f.get_server_stats()
        print(f"CPU: {stats['cpu']}%")

def get_full_server_stats() -> dict:
    """Get comprehensive server statistics."""
    Returns: Full dict with all metrics
    Usage:
        full_stats = f.get_full_server_stats()
        # Includes: cpu, ram, disk, network, uptime, gpu, wifi_ssid

def get_uptime_seconds() -> int:
    """Get server uptime since boot."""
    Returns: Seconds
    Usage:
        uptime = f.get_uptime_seconds()
        hours = uptime // 3600

def get_public_ip() -> str:
    """Get external IP address."""
    Returns: String like "203.0.113.42"
    Usage:
        ip = f.get_public_ip()

def get_network_stats() -> dict:
    """Get network interface statistics."""
    Returns: Dict with network info
    Usage:
        net = f.get_network_stats()

def get_disk_stats() -> dict:
    """Get detailed disk statistics."""
    Returns: Dict with disk info
    Usage:
        disk = f.get_disk_stats()
```

---

### 7. functions/moderation.py — Bans & Reports

**Purpose:** IP banning and user report management

**Key Functions:**

```python
def is_ip_banned(ip: str) -> bool:
    """Check if IP is currently banned."""
    Returns: True if banned
    Usage:
        if f.is_ip_banned(request.remote_addr):
            return "Access denied", 403

def get_all_bans() -> list[dict]:
    """Get all active IP bans."""
    Returns: List of ban dicts
    Usage:
        bans = f.get_all_bans()
        for ban in bans:
            print(ban["ip"], ban["reason"], ban["until"])

def ban_ip(ip: str, reason: str, duration_seconds: int) -> dict:
    """Issue new IP ban."""
    Returns: Ban dict
    Usage:
        ban = f.ban_ip(
            ip="192.168.1.1",
            reason="Spam",
            duration_seconds=3600  # 1 hour
        )

def unban_ip(ban_id: int) -> None:
    """Remove IP ban."""
    Usage:
        f.unban_ip(ban_id)

def create_report(content: str, reporter_ip: str, report_type: str = "other") -> dict:
    """File user report."""
    Returns: Report dict
    Types: "spam", "abuse", "bug", "other"
    Usage:
        report = f.create_report(
            content="User X is spamming",
            reporter_ip=request.remote_addr,
            report_type="spam"
        )

def get_reports(status: str = None) -> list[dict]:
    """Get user reports."""
    Statuses: "open", "reviewed", "resolved"
    Usage:
        open_reports = f.get_reports(status="open")

def update_report_status(report_id: int, status: str) -> None:
    """Update report status."""
    Usage:
        f.update_report_status(report_id, "resolved")
```

---

### 8. functions/dropzone.py — File Uploads

**Purpose:** File upload, storage, and quota management

**Key Functions:**

```python
def dropzone_save(
    file_storage,
    display_name: str,
    tags: list[str],
    uploader_ip: str,
    uploader_name: str = ""
) -> dict:
    """Save uploaded file to storage."""
    Returns: Upload dict with id, name, size, url
    Enforces:
    - Max file size per file
    - Max upload rate per IP per time window
    - Max total storage quota
    Usage:
        upload = f.dropzone_save(
            request.files['file'],
            display_name="my_image.jpg",
            tags=["photo", "vacation"],
            uploader_ip=request.remote_addr,
            uploader_name=request.form.get('name', '')
        )
        if upload:
            print(f"File saved: {upload['url']}")

def dropzone_get_by_id(upload_id: int) -> dict | None:
    """Get upload info by ID."""
    Usage:
        upload = f.dropzone_get_by_id(123)

def dropzone_search(query: str = "", tag: str = "") -> list[dict]:
    """Search uploads by name or tag."""
    Usage:
        files = f.dropzone_search(query="photo")

def dropzone_delete(upload_id: int) -> None:
    """Delete uploaded file."""
    Usage:
        f.dropzone_delete(123)

def dropzone_total_used() -> int:
    """Get total storage used in bytes."""
    Usage:
        used = f.dropzone_total_used()
        print(f"Used: {used / (1024**2):.1f} MB")

def dropzone_stats() -> dict:
    """Get detailed storage statistics."""
    Returns: Dict with usage, limits, percentages
    Usage:
        stats = f.dropzone_stats()
        print(f"Storage: {stats['used_pct']}% full")
```

---

## Framework & Technologies

### Flask & Flask-SocketIO

**Flask** - HTTP web framework for REST API endpoints

```python
# In blueprints/
@chat_bp.route("/api/messages")
def get_messages():
    return jsonify({"messages": f.get_recent_messages()})

@chat_bp.route("/api/messages", methods=["POST"])
def send_message():
    text = request.form.get('text')
    msg = f.save_chat_message(text, request.remote_addr)
    return jsonify({"ok": True, "message": msg})
```

**Flask-SocketIO** - Bi-directional WebSocket communication

```python
# In socket_events/
from socketio_instance import socketio

@socketio.on('connect')
def handle_connect():
    print(f"Client {request.sid} connected")

@socketio.on('send_message')
def handle_send(data):
    msg = f.save_chat_message(data['text'], request.remote_addr)
    emit('new_message', msg, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client {request.sid} disconnected")
```

### SQLite3 Database

**Connection & Queries:**

```python
import sqlite3

# Get connection (from functions.db)
conn = f.get_db()
c = conn.cursor()

# Read
c.execute("SELECT * FROM messages WHERE id=?", (msg_id,))
row = c.fetchone()
print(dict(row))  # Row acts like dict due to row_factory

# Write
c.execute("INSERT INTO messages (text, timestamp) VALUES (?,?)", 
          ("Hello", time.time()))
conn.commit()

# Close when done
conn.close()
```

**Table Format:**

All tables are accessed through functions.db, or via direct query. Common tables:

- `users` - User accounts
- `messages` - Direct messages
- `channels` - Chat channels
- `channel_messages` - Channel posts
- `uploads` - File uploads
- `admin_users` - Admin accounts
- `ip_bans` - IP ban records
- `user_reports` - User reports
- `feedback` - User feedback
- `polls` - Poll records
- `updates` - Version history

---

## How to Add a New Feature

### Step 1: Plan the Feature

**Example: Create a "Favorites" feature for messages**

```
Feature: Users can star/favorite messages
Database change: Add 'favorites' table
API changes:
  - POST /api/favorites/{message_id} - Add to favorites
  - DELETE /api/favorites/{message_id} - Remove from favorites
  - GET /api/favorites - Get user's favorites
Socket events:
  - favorite_message - Add to favorites
  - unfavorite_message - Remove from favorites
  - favorites_updated - Broadcast when favorites change
```

### Step 2: Create Database Migration

Add table to `utils/init.py`:

```python
# In initialize() function
c.execute("""
    CREATE TABLE IF NOT EXISTS message_favorites (
        id INTEGER PRIMARY KEY,
        message_id INTEGER NOT NULL,
        user_ip TEXT NOT NULL,
        timestamp REAL,
        FOREIGN KEY(message_id) REFERENCES messages(id),
        UNIQUE(message_id, user_ip)
    )
""")
```

### Step 3: Add Business Logic

Create new domain module or add to existing `functions/chat.py`:

```python
# In functions/chat.py (add these functions)

def add_to_favorites(message_id: int, user_ip: str) -> bool:
    """Add message to user's favorites."""
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO message_favorites (message_id, user_ip, timestamp)
            VALUES (?, ?, ?)
        """, (message_id, user_ip, time.time()))
        conn.commit()
        conn.close()
        return True
    except:
        conn.close()
        return False

def remove_from_favorites(message_id: int, user_ip: str) -> None:
    """Remove message from user's favorites."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        DELETE FROM message_favorites
        WHERE message_id=? AND user_ip=?
    """, (message_id, user_ip))
    conn.commit()
    conn.close()

def get_user_favorites(user_ip: str, limit: int = 50) -> list[dict]:
    """Get user's favorite messages."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT m.* FROM messages m
        INNER JOIN message_favorites mf ON m.id = mf.message_id
        WHERE mf.user_ip = ?
        ORDER BY mf.timestamp DESC
        LIMIT ?
    """, (user_ip, limit))
    cols = [d[0] for d in c.description]
    rows = [dict(zip(cols, row)) for row in c.fetchall()]
    conn.close()
    return rows

def is_user_favorite(message_id: int, user_ip: str) -> bool:
    """Check if message is in user's favorites."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT 1 FROM message_favorites
        WHERE message_id=? AND user_ip=?
    """, (message_id, user_ip))
    result = c.fetchone() is not None
    conn.close()
    return result
```

### Step 4: Create REST Endpoints

Add to `blueprints/chat/chat.py`:

```python
@chat_bp.route("/api/favorites", methods=["GET"])
def get_favorites():
    """Get current user's favorite messages."""
    favorites = f.get_user_favorites(request.remote_addr)
    return jsonify({"favorites": favorites})

@chat_bp.route("/api/messages/<int:message_id>/favorite", methods=["POST"])
def favorite_message(message_id):
    """Add message to favorites."""
    success = f.add_to_favorites(message_id, request.remote_addr)
    if not success:
        return jsonify({"ok": False, "error": "Already in favorites"}), 400
    return jsonify({"ok": True})

@chat_bp.route("/api/messages/<int:message_id>/favorite", methods=["DELETE"])
def unfavorite_message(message_id):
    """Remove message from favorites."""
    f.remove_from_favorites(message_id, request.remote_addr)
    return jsonify({"ok": True})
```

### Step 5: Add Socket Event Handlers

Add to `socket_events/chat_events.py`:

```python
@socketio.on('favorite_message')
def handle_favorite(data):
    """Add message to favorites."""
    message_id = data.get('message_id')
    user_ip = request.remote_addr
    
    success = f.add_to_favorites(message_id, user_ip)
    if success:
        emit('favorite_added', {
            'message_id': message_id
        }, broadcast=True)
    else:
        emit('error', {'message': 'Failed to favorite'})

@socketio.on('unfavorite_message')
def handle_unfavorite(data):
    """Remove message from favorites."""
    message_id = data.get('message_id')
    user_ip = request.remote_addr
    
    f.remove_from_favorites(message_id, user_ip)
    emit('favorite_removed', {
        'message_id': message_id
    }, broadcast=True)
```

### Step 6: Update Frontend (JavaScript)

Add to `static/js/commands.js` or game JavaScript:

```javascript
// Add to favorites
function favoriteMessage(messageId) {
    socket.emit('favorite_message', {
        message_id: messageId
    });
}

// Remove from favorites
function unfavoriteMessage(messageId) {
    socket.emit('unfavorite_message', {
        message_id: messageId
    });
}

// Listen for updates
socket.on('favorite_added', (data) => {
    document.getElementById(`msg-${data.message_id}`)
        .classList.add('favorited');
});

socket.on('favorite_removed', (data) => {
    document.getElementById(`msg-${data.message_id}`)
        .classList.remove('favorited');
});
```

### Step 7: Update HTML Template

In `templates/chat.html`:

```html
<div class="message" id="msg-{{ msg.id }}">
    <p>{{ msg.text }}</p>
    <button onclick="favoriteMessage({{ msg.id }})">
        ★ Favorite
    </button>
</div>

<style>
.message.favorited button {
    color: gold;
}
</style>
```

### Step 8: Test

```bash
# Start app
python3 app.py

# Test REST API
curl http://localhost:5000/api/favorites

# Test via browser console
socket.emit('favorite_message', {message_id: 1})
```

---

## Common Development Tasks

### Task 1: Add a New Game

**Files to Create:**
1. `blueprints/games/[game].py` - Game route
2. `socket_events/[game]_events.py` - Game WebSocket handlers
3. `templates/[game].html` - Game UI
4. `game_logic/[game]_logic.py` - Optional: Game engine (if complex)

**Minimal Example - Simple Dice Game:**

`blueprints/games/dice.py`:
```python
from flask import Blueprint, render_template

dice_bp = Blueprint("dice", __name__)

@dice_bp.route("/dice")
def dice_page():
    return render_template("dice.html")
```

`socket_events/dice_events.py`:
```python
from socketio_instance import socketio
from shared import GameSessionManager
import random

dice_sessions = GameSessionManager(name="dice")

@socketio.on('join_dice')
def handle_join(data):
    username = data.get('username', 'Player')
    dice_sessions[request.sid] = {'username': username, 'score': 0}
    emit('joined', {'players': len(dice_sessions)}, broadcast=True)

@socketio.on('roll_dice')
def handle_roll():
    roll = random.randint(1, 6)
    session = dice_sessions[request.sid]
    session['score'] += roll
    emit('rolled', {'roll': roll, 'total': session['score']}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    dice_sessions.pop(request.sid)
    emit('player_left', {}, broadcast=True)
```

`app.py`:
```python
from blueprints.games.dice import dice_bp
app.register_blueprint(dice_bp)
```

---

### Task 2: Add Admin Feature

Admin features go in `blueprints/admin/[feature].py`

**Example: Node management feature**

`blueprints/admin/nodes.py`:
```python
from flask import Blueprint, render_template, request, jsonify, session
import functions as f
from glob_vars import app_log

nodes_bp = Blueprint("admin_nodes", __name__, url_prefix="/admin")

def _check_admin():
    if session.get("admin_role") != "DEV":
        return False
    return True

@nodes_bp.route("/nodes")
def nodes_page():
    if not _check_admin():
        return "Unauthorized", 403
    return render_template("admin_nodes.html")

@nodes_bp.route("/api/admin/nodes", methods=["GET"])
def get_nodes():
    if not _check_admin():
        return {"error": "Unauthorized"}, 403
    
    nodes = f.db_query("SELECT * FROM nodes")
    return jsonify({"nodes": nodes})

@nodes_bp.route("/api/admin/nodes", methods=["POST"])
def add_node():
    if not _check_admin():
        return {"error": "Unauthorized"}, 403
    
    data = {
        "name": request.form.get("name"),
        "address": request.form.get("address"),
        "port": request.form.get("port"),
        "active": True,
        "created_by": session.get("admin_name")
    }
    node_id = f.db_insert("nodes", data)
    app_log.info(f"Admin {session.get('admin_name')} added node {data['name']}")
    return jsonify({"ok": True, "id": node_id})
```

---

### Task 3: Query the Database

```python
import functions as f

# Get all rows
users = f.db_query("SELECT * FROM users")
for user in users:
    print(user["username"])

# Get single row
user = f.db_get_row("users", user_id)

# Check if exists
if user:
    print(f"Found: {user['username']}")

# Custom query
messages = f.db_query("""
    SELECT m.*, u.username 
    FROM messages m
    JOIN users u ON m.user_id = u.id
    WHERE m.channel_id = ?
    ORDER BY m.timestamp DESC
    LIMIT 10
""", [channel_id])

# Insert
user_id = f.db_insert("users", {
    "username": "alice",
    "email": "alice@example.com",
    "created": time.time()
})

# Update
f.db_update_row("users", user_id, {
    "email": "newalice@example.com",
    "last_seen": time.time()
})

# Delete
f.db_delete_row("users", user_id)
```

---

### Task 4: Add Configuration Option

Configuration is in `configvars.json` and loaded via `config.py`.

**Add new setting:**

1. Add to `configvars.example.json`:
```json
{
  "features": {
    "ENABLE_FAVORITES": true,
    "MAX_FAVORITES_PER_USER": 100
  }
}
```

2. Use in code:
```python
from config import ENABLE_FAVORITES, MAX_FAVORITES_PER_USER

if ENABLE_FAVORITES:
    # Feature is enabled
    max_favs = MAX_FAVORITES_PER_USER
```

To reload config file after editing:
```python
import config
config.reload()  # Re-reads configvars.json
```

---

### Task 5: Log Events

```python
from glob_vars import app_log, error_log, access_log

# Log info
app_log.info(f"User {username} joined chat")

# Log error
try:
    risky_operation()
except Exception as e:
    error_log.error(f"Operation failed: {e}")

# Log access
access_log.info(f"GET /api/messages from {request.remote_addr}")
```

Logs are in `logs/` directory:
- `app.log` - Application events
- `error.log` - Errors
- `access.log` - HTTP access
- `github.log` - GitHub sync

---

## Database Operations

### Common Queries

```python
import functions as f
import time

# Get messages in date range
messages = f.db_query("""
    SELECT * FROM messages
    WHERE timestamp BETWEEN ? AND ?
    ORDER BY timestamp DESC
""", [start_time, end_time])

# Count items
count_result = f.db_query("SELECT COUNT(*) as cnt FROM messages")
total = count_result[0]['cnt']

# Aggregate
stats = f.db_query("""
    SELECT COUNT(*) as total, SUM(size_bytes) as total_size
    FROM uploads
""")

# Join tables
recent_with_author = f.db_query("""
    SELECT m.*, u.username, u.id as user_id
    FROM messages m
    LEFT JOIN users u ON m.user_id = u.id
    ORDER BY m.timestamp DESC
    LIMIT 20
""")

# Group by
by_user = f.db_query("""
    SELECT user_id, COUNT(*) as msg_count
    FROM messages
    GROUP BY user_id
    ORDER BY msg_count DESC
""")

# Conditional update
f.db_query("""
    UPDATE messages
    SET is_edited = 1, edited_at = ?
    WHERE id = ? AND user_id = ?
""", [time.time(), msg_id, user_id])
```

### Performance Tips

```python
# ✅ GOOD: Use parameterized queries (prevents SQL injection)
f.db_query("SELECT * FROM users WHERE id = ?", [user_id])

# ❌ BAD: String interpolation (unsafe)
f.db_query(f"SELECT * FROM users WHERE id = {user_id}")

# ✅ GOOD: Use LIMIT to prevent huge result sets
f.db_query("SELECT * FROM messages LIMIT 100")

# ❌ BAD: SELECT without LIMIT (can crash app)
f.db_query("SELECT * FROM messages")  # Could be millions!

# ✅ GOOD: Index frequently-queried columns
# (Handled by utils/init.py in CREATE TABLE)

# ✅ GOOD: Close connections
conn = f.get_db()
try:
    # Use connection
finally:
    conn.close()  # Always close!
```

---

## Socket Events & Real-time Communication

### Socket Event Patterns

**Pattern 1: Request-Response**

```python
# Client (JavaScript)
socket.emit('get_user_profile', {user_id: 123})

# Server (Python)
@socketio.on('get_user_profile')
def handle_get_profile(data):
    user = f.db_get_row("users", data['user_id'])
    emit('user_profile', {'user': user})

# Client receives response
socket.on('user_profile', (data) => {
    console.log(data.user.username)
})
```

**Pattern 2: Broadcast**

```python
# Server broadcasts to all connected clients
emit('game_updated', {'state': game_state}, broadcast=True)

# Or to room
emit('game_updated', {'state': game_state}, to=room_id)
```

**Pattern 3: Session Tracking**

```python
from shared import GameSessionManager

game_sessions = GameSessionManager(name="chess")

@socketio.on('join_game')
def handle_join(data):
    game_sessions[request.sid] = {
        'username': data['username'],
        'game_id': data['game_id'],
        'joined_at': time.time()
    }
    emit('game_state', get_game_state(), to=request.sid)
    emit('player_joined', broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    player = game_sessions.pop(request.sid)
    if player:
        emit('player_left', {'username': player['username']}, broadcast=True)
```

---

## Configuration Management

### Adding App-Wide Settings

Settings are in `configvars.json` structured by section:

```json
{
  "general": {
    "PORT": 5000,
    "REPO_URL": "https://github.com/myrepo"
  },
  "features": {
    "ENABLE_FAVORITES": true
  },
  "limits": {
    "MAX_MESSAGE_LENGTH": 500,
    "RATE_LIMIT_MESSAGES": 5
  },
  "admin": {
    "SECRET_KEY": "...",
    "INITIAL_DEV_USERNAME": "dev"
  }
}
```

Access in code:

```python
from config import PORT, ENABLE_FAVORITES, MAX_MESSAGE_LENGTH

if ENABLE_FAVORITES:
    # Feature enabled
    
app.run(port=PORT)
```

Admin UI to change settings: `blueprints/admin/server_config.py`

---

## Debugging & Troubleshooting

### Enable Debug Mode

```python
# In app.py
app.run(debug=True)  # Will auto-reload on file changes
```

### Check Logs

```bash
# View application logs
tail -f logs/app.log

# View errors
tail -f logs/error.log

# View HTTP access
tail -f logs/access.log

# Search logs
grep "ERROR" logs/error.log
grep "user_id=123" logs/app.log
```

### Test Database Connection

```python
python3 << 'EOF'
import functions as f

# Get connection
conn = f.get_db()

# List tables
tables = f.db_get_tables()
print(f"Tables: {tables}")

# Get table count
for table in tables:
    count = f.db_query(f"SELECT COUNT(*) as cnt FROM {table}")
    print(f"{table}: {count[0]['cnt']} rows")

conn.close()
EOF
```

### Test Socket Connection

In browser console:

```javascript
// Connect
socket.on('connect', () => {
    console.log('Connected:', socket.id)
})

// Send test event
socket.emit('test', {message: 'Hello'})

// Listen for response
socket.on('test_response', (data) => {
    console.log('Response:', data)
})

// Check if connected
console.log('Connected:', socket.connected)
```

### Common Issues

**App won't start:**
```bash
# Check if port is in use
lsof -i :5000

# Check Python syntax
python3 -m py_compile app.py

# Check imports
python3 -c "from app import app"
```

**Database locked:**
```bash
# SQLite file locked?
lsof app.db

# Solution: Kill process or restart app
pkill -f "python.*app.py"
```

**Socket events not firing:**
```python
# Check if namespace registered
@socketio.on('event_name')
def handler():
    print("Event received!")  # Add print to debug
    
# Check client-side
socket.emit('event_name', {..})  # Is this firing?
console.log('Emitted event')
```

---

## Summary Checklist

When adding a new feature:

- [ ] Plan feature (user stories, mockups)
- [ ] Add database table (if needed)
- [ ] Create business logic functions (`functions/[domain].py`)
- [ ] Create REST endpoints (`blueprints/[category]/[feature].py`)
- [ ] Add Socket event handlers (`socket_events/[feature]_events.py`)
- [ ] Create/update HTML template (`templates/[feature].html`)
- [ ] Add JavaScript handlers (`static/js/` or template)
- [ ] Add tests (manual testing in browser)
- [ ] Document in code comments
- [ ] Update this guide if pattern changes
- [ ] Commit with clear message

---

## Getting Help

- **Python errors**: Check `logs/error.log`
- **Socket issues**: Browser console (`F12` → Console)
- **Database questions**: See `functions/db.py` docstrings
- **Module API**: Check corresponding `functions/[module].py`
- **Flask routing**: Flask documentation + `blueprints/` examples
- **Socket.io events**: Socket.io documentation + `socket_events/` examples

---

## Next Resources

- `ORGANIZATION.md` - Repository structure guide
- `REFACTORING_PHASE3.md` - Details on functions.py split
- `REFACTORING_NOTES.md` - Phases 1-2 changes
- `README.md` - Project overview
- Function docstrings - Run `help(functions.function_name)` or read source
- Configuration - Edit `configvars.json` and reload with `config.reload()`

**Happy coding!**
