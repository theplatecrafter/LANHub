# --- General settings ---
import os


REPO_URL = "https://github.com/YOUR_USERNAME/YOUR_REDIRECTOR_REPO"
PORT = 5000
# --- Chat settings ---
CHAT_MAX_CHARS       = 500   # max characters per message
CHAT_RATE_LIMIT      = 5     # max messages per window
CHAT_RATE_WINDOW     = 10    # seconds for rate window
CHAT_HISTORY_ON_JOIN = 50    # recent messages sent on connect
# --- Admin settings ---
INITIAL_DEV_USERNAME = "dev"
INITIAL_DEV_PASSWORD = "password"
SECRET_KEY = os.urandom(24)
# --- Drop Zone settings ---
DROPZONE_MAX_STORAGE_BYTES  = 5 * 1024 * 1024 * 1024   #total server storage
DROPZONE_MAX_FILE_BYTES     = 1 * 1024  * 1024 * 1024   #per single file
DROPZONE_RATE_WINDOW_HOURS  = 2                    # rolling window for per-IP limit
DROPZONE_RATE_LIMIT_BYTES   = 2*1024 * 1024 * 1024   # per IP per window
 