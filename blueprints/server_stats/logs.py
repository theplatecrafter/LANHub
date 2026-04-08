from flask import Blueprint, render_template, request, jsonify
import os
from glob_vars import BASE_DIR, error_log

logs_bp = Blueprint("logs", __name__)

LOG_DIR   = os.path.join(BASE_DIR, "logs")
CHUNK     = 100    # lines per load

# The tabs shown in the UI — label, filename
LOG_FILES = [
    ("App",        "app.log"),
    ("Access",     "access.log"),
    ("Error",      "error.log"),
    ("GitHub",     "github_sync.log"),
]


def _read_chunk(filename: str, offset: int) -> dict:
    """
    Reads CHUNK lines ending at (total - offset) from the file,
    i.e. works backwards from the newest line.

    offset=0  → last CHUNK lines (newest)
    offset=N  → the CHUNK lines before those
    """
    path = os.path.join(LOG_DIR, filename)
    if not os.path.isfile(path):
        return {"lines": [], "offset": 0, "total": 0, "has_more": False}

    try:
        with open(path, "r", errors="replace") as f:
            all_lines = f.readlines()
    except Exception as e:
        error_log.error(f"[logs] failed to read {filename}: {e}")
        return {"lines": [], "offset": 0, "total": 0, "has_more": False}

    total    = len(all_lines)
    end      = total - offset          # exclusive upper bound
    start    = max(0, end - CHUNK)     # inclusive lower bound
    chunk    = all_lines[start:end]

    return {
        "lines":    [l.rstrip("\n") for l in chunk],
        "offset":   offset + len(chunk),   # new offset for next request
        "total":    total,
        "has_more": start > 0,
    }


@logs_bp.route("/logs")
def logs():
    return render_template(
        "logs.html",
        log_files=LOG_FILES,
    )


@logs_bp.route("/api/logs/<filename>")
def api_logs(filename):
    # Security: only allow known filenames
    allowed = {lf for _, lf in LOG_FILES}
    if filename not in allowed:
        return jsonify({"error": "Not found"}), 404

    try:
        offset = int(request.args.get("offset", 0))
    except ValueError:
        offset = 0

    return jsonify(_read_chunk(filename, offset))