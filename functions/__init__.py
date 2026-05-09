"""functions/__init__.py - Unified module exports for backward compatibility.

This module re-exports all functions from domain-specific submodules,
allowing existing code to continue using:
    from functions import function_name
    import functions as f
"""

# Profanity
from .profanity import check_profanity

# Database
from .db import (
    get_db,
    db_get_tables,
    db_get_schema,
    db_query,
    db_get_row,
    db_insert,
    db_update_row,
    db_delete_row,
)

# Dropzone (File uploads)
from .dropzone import (
    dropzone_save,
    dropzone_search,
    dropzone_delete,
    dropzone_total_used,
    dropzone_ip_used_in_window,
    dropzone_evict_oldest,
    dropzone_get_by_id,
    dropzone_tag_suggestions,
    dropzone_stats,
)

# Moderation
from .moderation import (
    is_ip_banned,
    get_all_bans,
    ban_ip,
    unban_ip,
    update_ban,
    create_report,
    get_reports,
    update_report_status,
)

# Admin users
from .admin import (
    get_admin_by_username,
    get_admin_by_id,
    get_all_admins,
    create_admin,
    edit_admin,
    delete_admin,
)

# Chat (Messages and channels)
from .chat import (
    is_rate_limited,
    save_chat_message,
    get_recent_messages,
    edit_message,
    delete_message,
    get_messages_before,
    create_channel,
    get_channel_by_id,
    search_channels,
    channel_tag_suggestions,
    edit_channel,
    delete_channel,
    verify_channel_password,
    save_channel_message,
    get_channel_messages,
    get_channel_messages_before,
    edit_channel_message,
    delete_channel_message,
    get_channel_online_count,
)

# Server monitoring
from .server import (
    get_server_stats,
    get_wifi_ssid,
    get_network_stats,
    get_public_ip,
    get_disk_stats,
    get_network_speed,
    get_gpu_stats,
    get_uptime_seconds,
    get_cpu_temp,
    get_full_server_stats,
)

# Redirector
from .redirector import redirector_update

# Feedback
from .feedback import (
    feedback_create,
    _feedback_attach,
    feedback_search,
    feedback_get_by_id,
    feedback_toggle_star,
    feedback_add_reply,
    feedback_get_replies,
    feedback_resolve,
    feedback_tag_suggestions,
)

# Polls
from .polls import (
    poll_create,
    _poll_attach,
    poll_search,
    poll_get_by_id,
    poll_vote,
    poll_tag_suggestions,
    poll_delete,
)

# Updates
from .updates import (
    updates_get_all,
    updates_get_by_id,
    updates_create,
    updates_edit,
    updates_delete,
)

# Geoguesser
from .geoguesser import (
    geo_preset_create,
    geo_preset_search,
    geo_preset_get_by_id,
    geo_preset_delete,
)

# Owner's Playground
from .owner_playground import (
    measure_coherency,
    random_image,
    ndarray_to_png,
)

__all__ = [
    # Profanity
    "check_profanity",
    # Database
    "get_db",
    "db_get_tables",
    "db_get_schema",
    "db_query",
    "db_get_row",
    "db_insert",
    "db_update_row",
    "db_delete_row",
    # Dropzone
    "dropzone_save",
    "dropzone_search",
    "dropzone_delete",
    "dropzone_total_used",
    "dropzone_ip_used_in_window",
    "dropzone_evict_oldest",
    "dropzone_get_by_id",
    "dropzone_tag_suggestions",
    "dropzone_stats",
    # Moderation
    "is_ip_banned",
    "get_all_bans",
    "ban_ip",
    "unban_ip",
    "update_ban",
    "create_report",
    "get_reports",
    "update_report_status",
    # Admin
    "get_admin_by_username",
    "get_admin_by_id",
    "get_all_admins",
    "create_admin",
    "edit_admin",
    "delete_admin",
    # Chat
    "is_rate_limited",
    "save_chat_message",
    "get_recent_messages",
    "edit_message",
    "delete_message",
    "get_messages_before",
    "create_channel",
    "get_channel_by_id",
    "search_channels",
    "channel_tag_suggestions",
    "edit_channel",
    "delete_channel",
    "verify_channel_password",
    "save_channel_message",
    "get_channel_messages",
    "get_channel_messages_before",
    "edit_channel_message",
    "delete_channel_message",
    "get_channel_online_count",
    # Server
    "get_server_stats",
    "get_wifi_ssid",
    "get_network_stats",
    "get_public_ip",
    "get_disk_stats",
    "get_network_speed",
    "get_gpu_stats",
    "get_uptime_seconds",
    "get_cpu_temp",
    "get_full_server_stats",
    # Redirector
    "redirector_update",
    # Feedback
    "feedback_create",
    "_feedback_attach",
    "feedback_search",
    "feedback_get_by_id",
    "feedback_toggle_star",
    "feedback_add_reply",
    "feedback_get_replies",
    "feedback_resolve",
    "feedback_tag_suggestions",
    # Polls
    "poll_create",
    "_poll_attach",
    "poll_search",
    "poll_get_by_id",
    "poll_vote",
    "poll_tag_suggestions",
    "poll_delete",
    # Updates
    "updates_get_all",
    "updates_get_by_id",
    "updates_create",
    "updates_edit",
    "updates_delete",
    # Geoguesser
    "geo_preset_create",
    "geo_preset_search",
    "geo_preset_get_by_id",
    "geo_preset_delete",
    # Owner's Playground
    "measure_coherency",
    "random_image",
    "ndarray_to_png",
]

