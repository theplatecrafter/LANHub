"""
shared/validators.py

Centralized validation functions for usernames, messages, and common inputs.
Eliminates repeated validation logic across socket_events handlers.
"""

from typing import Tuple


def validate_username(
    username: str,
    max_length: int = 24,
    taken_usernames: set[str] | None = None,
    check_profanity_func=None,
) -> Tuple[bool, str]:
    """
    Validate a username with standard checks.
    
    Args:
        username: The username to validate
        max_length: Maximum allowed username length (default 24)
        taken_usernames: Set of already-taken usernames to check against
        check_profanity_func: Function that returns True if profanity detected
    
    Returns:
        (is_valid, error_message) tuple
    """
    if not username:
        return False, "Username cannot be empty."
    
    if len(username) > max_length:
        return False, f"Username too long (max {max_length} chars)."
    
    if check_profanity_func and check_profanity_func(username):
        return False, "Username contains disallowed words."
    
    if taken_usernames and username in taken_usernames:
        return False, "Username already taken."
    
    return True, ""


def validate_message(
    message: str,
    max_chars: int,
    check_profanity_func=None,
    skip_profanity: bool = False,
) -> Tuple[bool, str]:
    """
    Validate a message with standard checks.
    
    Args:
        message: The message text to validate
        max_chars: Maximum allowed message length
        check_profanity_func: Function that returns True if profanity detected
        skip_profanity: Skip profanity check if True
    
    Returns:
        (is_valid, error_message) tuple
    """
    if not message or not message.strip():
        return False, "Message cannot be empty."
    
    if len(message) > max_chars:
        return False, f"Message too long (max {max_chars} chars)."
    
    if not skip_profanity and check_profanity_func and check_profanity_func(message):
        return False, "Message contains disallowed words."
    
    return True, ""


def validate_channel_password(
    password: str,
    min_length: int = 1,
    max_length: int = 255,
) -> Tuple[bool, str]:
    """
    Validate a channel password.
    
    Args:
        password: The password to validate
        min_length: Minimum allowed length
        max_length: Maximum allowed length
    
    Returns:
        (is_valid, error_message) tuple
    """
    if not password:
        return False, "Password cannot be empty."
    
    if len(password) < min_length:
        return False, f"Password too short (min {min_length} chars)."
    
    if len(password) > max_length:
        return False, f"Password too long (max {max_length} chars)."
    
    return True, ""


def validate_channel_title(
    title: str,
    max_length: int = 255,
    check_profanity_func=None,
) -> Tuple[bool, str]:
    """
    Validate a channel title.
    
    Args:
        title: The title to validate
        max_length: Maximum allowed length
        check_profanity_func: Function that returns True if profanity detected
    
    Returns:
        (is_valid, error_message) tuple
    """
    if not title or not title.strip():
        return False, "Title cannot be empty."
    
    if len(title) > max_length:
        return False, f"Title too long (max {max_length} chars)."
    
    if check_profanity_func and check_profanity_func(title):
        return False, "Title contains disallowed words."
    
    return True, ""
