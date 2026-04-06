"""
shared/game_session.py

Unified GameSessionManager for multiplayer game session tracking.
Eliminates duplicated session management logic across socket_events.
"""

from typing import Dict, Set, Optional, Any, Tuple


class GameSessionManager:
    """
    Manages game session lifecycle for a single game instance.
    
    Consolidates:
    - Session CRUD (create, read, update, delete)
    - Username validation and tracking
    - Online player counting
    - Session lookup utilities
    
    Usage:
        manager = GameSessionManager()
        is_valid, error = manager.validate_username(username, active_usernames)
        if is_valid:
            session = manager.add_session(sid, username, status="idle")
            # ... game logic ...
            manager.remove_session(sid)
    """
    
    def __init__(self, name: str = "game"):
        """
        Initialize a session manager.
        
        Args:
            name: Human-readable name for logging/debugging (e.g., "tetris", "chess")
        """
        self.name = name
        self.sessions: Dict[str, Dict[str, Any]] = {}
    
    def add_session(self, sid: str, username: str, **extras) -> Dict[str, Any]:
        """
        Create and register a new session.
        
        Args:
            sid: Socket.IO session ID
            username: Player's username
            **extras: Additional fields (status, room_id, etc.)
        
        Returns:
            The created session dict
        """
        session = {"username": username, **extras}
        self.sessions[sid] = session
        return session
    
    def remove_session(self, sid: str) -> Optional[Dict[str, Any]]:
        """
        Remove a session by ID.
        
        Args:
            sid: Socket.IO session ID
        
        Returns:
            The removed session dict, or None if not found
        """
        return self.sessions.pop(sid, None)
    
    def get_session(self, sid: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a session by ID.
        
        Args:
            sid: Socket.IO session ID
        
        Returns:
            The session dict, or None if not found
        """
        return self.sessions.get(sid)
    
    def exists(self, sid: str) -> bool:
        """Check if a session exists."""
        return sid in self.sessions
    
    def update_session(self, sid: str, updates: Dict[str, Any]) -> bool:
        """
        Update a session's fields.
        
        Args:
            sid: Socket.IO session ID
            updates: Dict of fields to update
        
        Returns:
            True if session existed and was updated, False otherwise
        """
        if sid not in self.sessions:
            return False
        self.sessions[sid].update(updates)
        return True
    
    def get_username(self, sid: str) -> Optional[str]:
        """Get a player's username from session ID."""
        session = self.sessions.get(sid)
        return session["username"] if session else None
    
    def get_active_usernames(self) -> Set[str]:
        """Get all currently active usernames."""
        return {session["username"] for session in self.sessions.values()}
    
    def get_online_count(self) -> int:
        """Get count of active sessions."""
        return len(self.sessions)
    
    def is_username_taken(self, username: str) -> bool:
        """Check if a username is already in use."""
        return any(
            session["username"].lower() == username.lower()
            for session in self.sessions.values()
        )
    
    def validate_username(
        self,
        username: str,
        max_length: int = 24,
        check_profanity_func=None,
        allow_taken: bool = False,
    ) -> Tuple[bool, str]:
        """
        Validate a username for this game.
        
        Args:
            username: Username to validate
            max_length: Maximum allowed length
            check_profanity_func: Function returning True if profanity detected
            allow_taken: If True, allow already-taken usernames
        
        Returns:
            (is_valid, error_message) tuple
        """
        if not username:
            return False, "Username cannot be empty."
        
        if len(username) > max_length:
            return False, f"Username too long (max {max_length} chars)."
        
        if check_profanity_func and check_profanity_func(username):
            return False, "Username contains disallowed words."
        
        if not allow_taken and self.is_username_taken(username):
            return False, "Username already taken."
        
        return True, ""
    
    def find_sessions_by_field(self, field: str, value: Any) -> list[str]:
        """
        Find all session IDs where a field matches a value.
        
        Args:
            field: Field name to search
            value: Value to match
        
        Returns:
            List of matching session IDs
        """
        return [
            sid for sid, session in self.sessions.items()
            if session.get(field) == value
        ]
    
    def find_sessions_by_predicate(self, predicate) -> list[str]:
        """
        Find session IDs matching a predicate function.
        
        Args:
            predicate: Function(session) -> bool
        
        Returns:
            List of matching session IDs
        """
        return [
            sid for sid, session in self.sessions.items()
            if predicate(session)
        ]
    
    def clear_all(self) -> int:
        """
        Clear all sessions.
        
        Returns:
            Count of cleared sessions
        """
        count = len(self.sessions)
        self.sessions.clear()
        return count
    
    # ── Dictionary-like interface for compatibility ─────────────────────────
    
    def __getitem__(self, sid: str) -> Dict[str, Any]:
        """Allow dictionary-style access: manager[sid]"""
        return self.sessions[sid]
    
    def __setitem__(self, sid: str, value: Dict[str, Any]) -> None:
        """Allow dictionary-style assignment: manager[sid] = {...}"""
        self.sessions[sid] = value
    
    def __contains__(self, sid: str) -> bool:
        """Allow membership testing: sid in manager"""
        return sid in self.sessions
    
    def items(self):
        """Allow iteration over (sid, session) pairs: for sid, info in manager.items()"""
        return self.sessions.items()
    
    def pop(self, sid: str, default=None):
        """Remove and return a session, with optional default if not found"""
        return self.sessions.pop(sid, default)
