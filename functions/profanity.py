"""functions/profanity.py - Profanity filtering."""

from better_profanity import profanity as _profanity_filter


def check_profanity(message: str) -> bool:
    """Returns True if the message contains profanity."""
    return _profanity_filter.contains_profanity(message)
