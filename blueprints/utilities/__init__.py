"""
blueprints/utilities/

Utility and feature blueprints.
- access.py: IP allowlist/blocklist management
- devices.py: Connected devices information
- dropzone.py: File upload and download (The Dropzone)
- stats.py: Server statistics and monitoring
- updates.py: Version updates and changelog
- server_config.py: Server settings configuration
"""

from .access import access_bp, check_site_access
from .devices import devices_bp
from .dropzone import dropzone_bp
from .stats import stats_bp
from .updates import updates_bp
from .server_config import server_config_bp

__all__ = [
    "access_bp", "check_site_access", "devices_bp", "dropzone_bp",
    "stats_bp", "updates_bp", "server_config_bp"
]
