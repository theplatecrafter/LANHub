"""
blueprints/admin/

Admin control panel blueprints.
- admin.py: Main admin dashboard
- backup.py: Database export/backup
- logs.py: System activity logs
"""

from .admin import admin_bp, check_ban
from .backup import backup_bp
from .logs import logs_bp
from .auth_utils import require_role

__all__ = ["admin_bp", "backup_bp", "logs_bp", "check_ban", "require_role"]
