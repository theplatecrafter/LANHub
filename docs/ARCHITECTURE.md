# HansHub Architecture

**System design, module organization, and technical overview**

> Last Updated: April 2026  
> Version: 2.0  
> Tech Stack: Flask, Socket.IO, SQLite3, Python 3.10+

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Module Structure](#module-structure)
4. [Data Flow](#data-flow)
5. [Database Design](#database-design)
6. [WebSocket Architecture](#websocket-architecture)
7. [Configuration System](#configuration-system)
8. [Dependency Injection](#dependency-injection)
9. [Design Patterns](#design-patterns)
10. [Deployment](#deployment)

---

## System Overview

HansHub is a Flask-based web application serving local area network games and utilities. It provides:

- **Real-time Communication**: WebSocket-based messaging and game events
- **Multi-Game Platform**: Chat, chess, Uno, Tetris, Slither, Scribble, Geoguesser
- **User Management**: Authentication, permissions, admin controls
- **Content Safety**: Profanity filtering, message validation
- **System Monitoring**: Logging, statistics, device tracking
- **Admin Dashboard**: User management, server config, backups

### Key Characteristics

- **Single-page Application**: Frontend compiled with Jinja2 templates
- **Real-time Updates**: Socket.IO for instant communication
- **Modular Design**: Blueprints for each feature
- **Event-driven**: Socket events for user interactions
- **Configurable**: Environment-based configuration
- **Extensible**: Easy to add new games/features

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Web Browser (Client)                     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  HTML/CSS/JavaScript (in templates/ static/)         │   │
│  │  Handles UI rendering and user interactions          │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────┬──────────────────────────────┬─────────────────┘
              │ (HTTP)                       │ (WebSocket)
              │                              │
┌─────────────▼──────────────────────────────▼─────────────────┐
│                     Flask Application                         │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ app.py - Main Flask application & Socket.IO setup       │ │
│ │ socketio_instance.py - Shared Socket.IO instance        │ │
│ └──────────────────────────────────────────────────────────┘ │
│                                                               │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ Blueprints (routes/ & business logic)                   │ │
│ │  ├─ access.py (authentication)                          │ │
│ │  ├─ admin.py (admin dashboard)                          │ │
│ │  ├─ chat.py (messaging)                                 │ │
│ │  ├─ chess.py, uno.py, tetris.py, etc. (games)          │ │
│ │  └─ ... (other features)                                │ │
│ └──────────────────────────────────────────────────────────┘ │
│                                                               │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ Socket Events (socket_events/)                           │ │
│ │  ├─ chat_events.py                                       │ │
│ │  ├─ chess_events.py                                      │ │
│ │  └─ ... (other event handlers)                           │ │
│ └──────────────────────────────────────────────────────────┘ │
│                                                               │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ Core Modules                                             │ │
│ │  ├─ functions.py (utility functions)                    │ │
│ │  ├─ shared.py (shared validators/helpers)               │ │
│ │  ├─ config.py (configuration management)                │ │
│ │  ├─ dependencies.py (DI container)                       │ │
│ │  ├─ glob_vars.py (global state)                         │ │
│ │  └─ scheduler.py (background tasks)                      │ │
│ └──────────────────────────────────────────────────────────┘ │
│                                                               │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ Templates & Static Assets                                │ │
│ │  ├─ templates/ (Jinja2 HTML templates)                  │ │
│ │  ├─ static/js/ (JavaScript)                             │ │
│ │  └─ static/themes/ (CSS themes)                         │ │
│ └──────────────────────────────────────────────────────────┘ │
└─────────────┬──────────────────────────┬────────────────────┘
              │ (SQL)                    │
              │                          │
┌─────────────▼──────────────────────────▼─────────────────────┐
│                       SQLite3 Database                         │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Tables:                                                   │ │
│  │  ├─ users (usernames, IP addresses, settings)           │ │
│  │  ├─ messages (chat messages, timestamps)                │ │
│  │  ├─ games (game states)                                 │ │
│  │  ├─ statistics (player stats)                           │ │
│  │  ├─ admin_logs (audit trail)                            │ │
│  │  └─ ... (other tables)                                  │ │
│  └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## Module Structure

### Root Level Files

```
HansHub/
├── app.py                  # Flask app initialization & main routes
├── socketio_instance.py    # Shared Socket.IO instance
├── functions.py            # Utility functions (DB, validation, etc.)
├── shared.py              # Shared validators & helpers
├── config.py              # Configuration management
├── dependencies.py        # Dependency injection container
├── glob_vars.py           # Global state variables
├── scheduler.py           # Background task scheduler
├── chess_ai.py            # Chess AI engine
├── uno_game.py            # Uno game logic
└── configvars.json        # Runtime configuration
```

### blueprints/ - Feature Modules

Each blueprint is a self-contained feature with:
- Route handlers
- Business logic
- Integration with Socket events

```
blueprints/
├── __init__.py            # Blueprint registration
├── access.py              # Authentication & access control
├── admin.py               # Admin dashboard & controls
├── backup.py              # Database backups
├── chat.py                # Chat messaging
├── chess.py               # Chess game
├── devices.py             # Device tracking
├── dropzone.py            # File upload handling
├── feedback.py            # User feedback
├── geoguesser.py          # Geoguesser game
├── logs.py                # Log viewing
├── polls.py               # Polling system
├── scribble.py            # Drawing game
├── slither.py             # Slither game
├── stats.py               # User statistics
├── tetris.py              # Tetris game
├── uno.py                 # Uno game
├── updates.py             # Update management
└── server_config.py       # Server configuration
```

### socket_events/ - Real-time handlers

WebSocket event handlers for real-time communication:

```
socket_events/
├── __init__.py
├── chat_events.py         # Chat message events
├── chess_events.py        # Chess move events
├── console_events.py      # Admin console events
├── geoguesser_events.py   # Geoguesser guess events
├── global_events.py       # Connection/disconnect events
├── scribble_events.py     # Drawing events
├── slither_events.py      # Slither game events
├── tetris_events.py       # Tetris events
└── uno_events.py          # Uno card events
```

### templates/ - UI Templates

Jinja2 templates for page rendering:

```
templates/
├── base.html              # Base template (header, navigation)
├── root.html              # Home/index page
├── chat.html              # Chat interface
├── chess.html             # Chess game
├── uno.html               # Uno game
├── ... (other game pages)
├── admin_*.html           # Admin pages
└── ja/ (Japanese translations)
```

### static/ - Frontend Assets

```
static/
├── js/
│   └── commands.js        # JavaScript utilities
└── themes/                # CSS theme files
    ├── dark.css
    ├── matrix.css
    ├── neon-tokyo.css
    └── ... (12+ themes)
```

### tests/ - Test Suite

```
tests/
├── __init__.py
├── conftest.py            # Pytest config & fixtures
├── test_db.py             # Database tests
├── test_validators.py     # Validation tests
├── test_admin.py          # Admin function tests
└── test_*.py              # Feature-specific tests
```

---

## Data Flow

### User Connection Flow

```
1. User visits HansHub URL
   ↓
2. Browser requests HTML (HTTP GET)
   ↓
3. Flask serves base.html template
   ↓
4. Browser loads JavaScript & CSS
   ↓
5. JavaScript initiates Socket.IO connection
   ↓
6. Server socket_events.py handles 'connect' event
   ↓
7. User joins global & feature-specific rooms
   ↓
8. Real-time communication ready
```

### Message Send Flow

```
1. User types message in chat.html
   ↓
2. JavaScript captures input & validates locally
   ↓
3. Emits 'send_message' WebSocket event
   ↓
4. socket_events.chat_events.py receives event
   ↓
5. Functions.py validates message (length, profanity)
   ↓
6. Database insertion via DI container (db_insert)
   ↓
7. Message broadcast to all connected clients
   ↓
8. Chat.html updates DOM with new message
```

### Game Move Flow (e.g., Chess)

```
1. User clicks piece in chess.html
   ↓
2. JavaScript validates move locally
   ↓
3. Emits 'make_move' event with position
   ↓
4. socket_events.chess_events.py validates server-side
   ↓
5. chess_ai.py calculates new board state
   ↓
6. Broadcasts updated state to both players
   ↓
7. chess.html updates board display
```

---

## Database Design

### Users Table

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    ip_address TEXT,
    last_seen TIMESTAMP,
    is_banned BOOLEAN DEFAULT 0,
    is_admin BOOLEAN DEFAULT 0,
    created_at TIMESTAMP,
    settings TEXT  -- JSON
);
```

### Messages Table

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    sender_name TEXT NOT NULL,
    sender_ip TEXT,
    text TEXT NOT NULL,
    timestamp TIMESTAMP,
    is_edited BOOLEAN DEFAULT 0,
    edited_at TIMESTAMP
);
```

### Game States Table

```sql
CREATE TABLE game_states (
    id INTEGER PRIMARY KEY,
    game_type TEXT NOT NULL,  -- 'chess', 'uno', etc.
    player1_name TEXT,
    player2_name TEXT,
    state TEXT,  -- JSON
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    finished_at TIMESTAMP
);
```

### Statistics Table

```sql
CREATE TABLE statistics (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    game_type TEXT NOT NULL,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    draws INTEGER DEFAULT 0,
    plays INTEGER DEFAULT 0
);
```

---

## WebSocket Architecture

### Socket.IO Setup

Located in `socketio_instance.py`:

```python
socketio = SocketIO(
    cors_allowed_origins="*",
    message_queue="redis://localhost:6379",  # Optional
    async_mode='threading'
)
```

### Event Rooms

Users automatically join:
- **'global'** - All connected users
- **'chat'** - Chat feature users
- **'game_{game_type}'** - Game-specific room
- **'admin'** - Admin notifications

### Event Handling Pattern

```python
@socketio.on('event_name')
def handle_event(data):
    # Validate input
    if not validate_input(data):
        emit('error', {'message': 'Invalid input'})
        return
    
    # Process
    result = process_event(data)
    
    # Broadcast to room
    emit('event_response', result, room='room_name')
```

---

## Configuration System

### Sources (in order of precedence)

1. **Environment Variables** (highest priority)
   ```bash
   HANSHUB_PORT=5000
   HANSHUB_DEBUG=true
   ```

2. **configvars.json** (runtime config)
   ```json
   {
     "server_name": "My LAN",
     "max_players": 10,
     "features": ["chat", "chess", "uno"]
   }
   ```

3. **config.py** (hardcoded defaults)
   ```python
   DEBUG = False
   TESTING = False
   ```

### Adding Configuration

1. Define in `config.py`:
   ```python
   NEW_SETTING = os.getenv('HANSHUB_NEW_SETTING', 'default_value')
   ```

2. Use in code:
   ```python
   from config import NEW_SETTING
   ```

3. Override via environment:
   ```bash
   export LANHU_NEW_SETTING='custom_value'
   ```

---

## Dependency Injection

### Why Use DI?

- Testable: Easy to mock dependencies
- Decoupled: Functions don't depend on database directly
- Flexible: Switch implementations without changing code
- Clear: Explicit dependencies

### DI Container

Located in `dependencies.py`:

```python
class DI:
    @staticmethod
    def get(name):
        """Get production implementation."""
        
    @staticmethod
    def register(name, impl):
        """Register mock for testing."""
        
    @staticmethod
    def reset():
        """Reset to production."""
```

### Registered Services

```
├─ get_db()           - Database connection
├─ db_query()         - Execute SELECT
├─ db_insert()        - Execute INSERT
├─ db_delete()        - Execute DELETE  
├─ check_profanity()  - Profanity filter
└─ validate_message() - Message validation
```

### Example Usage

```python
from dependencies import DI

def save_message(text):
    # Get service from DI
    db_insert = DI.get('db_insert')
    check_profanity = DI.get('check_profanity')
    
    # Use services
    if check_profanity(text):
        raise ValueError("Message contains profanity")
    
    msg_id = db_insert('messages', {...})
    return msg_id
```

---

## Design Patterns

### 1. Blueprint Pattern

Each feature is a Flask Blueprint:

```python
# blueprints/chat.py
from flask import Blueprint

chat_bp = Blueprint('chat', __name__, url_prefix='/chat')

@chat_bp.route('/')
def chat_page():
    return render_template('chat.html')
```

**Benefits:**
- Modular organization
- Easy to enable/disable features
- Clear separation of concerns

### 2. Event-Driven Architecture

WebSocket events for real-time updates:

```python
@socketio.on('send_message')
def on_send_message(data):
    # Process and broadcast
    socketio.emit('message_received', result)
```

**Benefits:**
- Instant updates without polling
- Scalable to many users
- Decoupled components

### 3. Service Layer

Business logic separated from routes:

```python
# Route handler
@app.route('/api/users')
def get_users():
    return users_service.get_all()

# Service
class UsersService:
    def get_all(self):
        return DI.get('db_query')("SELECT * FROM users")
```

**Benefits:**
- Reusable across routes and events
- Easier testing
- Clear responsibility

### 4. Template Inheritance

HTML templates inherit from base:

```html
<!-- templates/chat.html -->
{% extends "base.html" %}
{% block content %}
    <!-- Chat-specific HTML -->
{% endblock %}
```

**Benefits:**
- DRY: No duplicate header/footer
- Consistent UI
- Easy theme switching

---

## Deployment

### Development

```bash
# Install dependencies
pip install -r dependencies.txt
pip install -r requirements-dev.txt

# Setup pre-commit hooks
pre-commit install

# Run with Flask development server
python app.py

# Or use built-in script
./start.sh
```

### Production

```bash
# Set environment
export FLASK_ENV=production
export LANHU_DEBUG=false

# Use production WSGI server
gunicorn --workers 4 --bind 0.0.0.0:5000 \
  --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker \
  app:app

# Or use provided scripts
./start.sh
```

### Docker (Optional)

```dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
CMD ["python", "app.py"]
```

---

## Growth & Scalability

### Current Limits

- Single process (threading not multi-process)
- SQLite (not suited for concurrent heavy writes)
- In-memory message queue (no persistence)

### Scaling Steps

1. **Switch Database**
   - SQLite → PostgreSQL
   - Update db_query/db_insert implementations

2. **Add Redis**
   - Message queue for Socket.IO
   - Session storage
   - Cache for frequently accessed data

3. **Multi-Process**
   - Use Gunicorn with multiple workers
   - Share session via Redis

4. **Load Balancing**
   - Nginx reverse proxy
   - Sticky sessions for WebSocket

5. **Database Optimization**
   - Indexes on frequently queried columns
   - Archive old messages
   - Query optimization

---

## Key Technologies

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Backend** | Flask | Web framework |
| **Real-time** | Socket.IO | WebSocket communication |
| **Database** | SQLite3 | Data storage |
| **Frontend** | Jinja2 | Template rendering |
| **Language** | Python 3.10+ | Primary language |
| **Testing** | pytest | Test framework |
| **Formatting** | Black, isort | Code quality |

---

## Contributing to Architecture

See [CONTRIBUTING.md](CONTRIBUTING.md) for:
- Code style guidelines
- How to add new features
- PR process
- Testing requirements

---

**Last updated: April 2026**

For questions about architecture, open an issue or check the code comments.
