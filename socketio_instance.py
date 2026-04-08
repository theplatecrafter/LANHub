# socketio_instance.py
from glob_vars import *
from flask_socketio import SocketIO

# Use gevent for async mode - enables WebSocket support for reverse proxying
socketio = SocketIO(cors_allowed_origins="*", async_mode='gevent')