"""Dependency Injection Container for LANHub

Provides a centralized dependency injection system for easier testing and decoupling.
Allows functions to be mocked in tests while maintaining production code structure.

Usage:
    # In production
    from dependencies import DI
    
    # In tests
    from dependencies import DI
    DI.reset()
    DI.register('get_db', mock_get_db)
"""

from typing import Callable, Any, Dict
import sqlite3


class DependencyContainer:
    """Simple dependency injection container."""
    
    def __init__(self):
        """Initialize empty container."""
        self._services: Dict[str, Any] = {}
        self._factories: Dict[str, Callable] = {}
        self._reset_to_defaults()
    
    def _reset_to_defaults(self):
        """Reset to production implementations."""
        # Import here to avoid circular imports
        import functions as f
        import sqlite3
        from glob_vars import DB_PATH
        
        self._services = {
            # Don't register get_db itself - use factory instead to avoid recursion
            'db_query': f.db_query,
            'db_get_row': f.db_get_row,
            'db_insert': f.db_insert,
            'db_update_row': f.db_update_row,
            'db_delete_row': f.db_delete_row,
            'check_profanity': f.check_profanity,
            'save_chat_message': f.save_chat_message,
            'get_recent_messages': f.get_recent_messages,
            'is_rate_limited': f.is_rate_limited,
            'create_channel': f.create_channel,
            'search_channels': f.search_channels,
            'save_channel_message': f.save_channel_message,
            'is_ip_banned': f.is_ip_banned,
            'ban_ip': f.ban_ip,
            'create_report': f.create_report,
            'get_all_admins': f.get_all_admins,
            'create_admin': f.create_admin,
            'get_server_stats': f.get_server_stats,
            'get_full_server_stats': f.get_full_server_stats,
            'dropzone_save': f.dropzone_save,
            'dropzone_search': f.dropzone_search,
            'dropzone_total_used': f.dropzone_total_used,
            'feedback_create': f.feedback_create,
            'poll_create': f.poll_create,
            'poll_vote': f.poll_vote,
            'updates_create': f.updates_create,
            'geo_preset_create': f.geo_preset_create,
        }
        
        # Register database connection factory
        def db_connection_factory():
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            return conn
        
        self._factories['DB_CONNECTION_FACTORY'] = db_connection_factory
    
    def register(self, name: str, implementation: Any) -> None:
        """Register a service or mock.
        
        Args:
            name: Service name (e.g., 'get_db', 'save_chat_message')
            implementation: Function, class, or value to use
        
        Usage:
            DI.register('get_db', mock_get_db)
            DI.register('check_profanity', lambda msg: False)
        """
        self._services[name] = implementation
    
    def register_factory(self, name: str, factory: Callable) -> None:
        """Register a factory function that creates instances.
        
        Args:
            name: Service name
            factory: Callable that returns a new instance each time
        
        Usage:
            DI.register_factory('get_db', lambda: sqlite3.connect(':memory:'))
        """
        self._factories[name] = factory
    
    def get(self, name: str) -> Any:
        """Get a service implementation.
        
        Args:
            name: Service name
        
        Returns:
            The registered service or mock
        
        Raises:
            KeyError: If service not found
        
        Usage:
            get_db = DI.get('get_db')
            conn = get_db()
        """
        # Check factory first (creates new instance each time)
        if name in self._factories:
            return self._factories[name]()
        
        # Then check registered services
        if name in self._services:
            return self._services[name]
        
        raise KeyError(f"Service '{name}' not registered in DI container")
    
    def reset(self) -> None:
        """Reset all services to production implementations.
        
        Useful in tests to ensure clean state between test runs.
        
        Usage:
            def test_something():
                DI.reset()  # Start with production code
                DI.register('get_db', mock_db)  # Override one service
        """
        self._services.clear()
        self._factories.clear()
        self._reset_to_defaults()
    
    def has(self, name: str) -> bool:
        """Check if a service is registered.
        
        Returns:
            True if service exists
        
        Usage:
            if DI.has('get_db'):
                # Service is available
        """
        return name in self._services or name in self._factories
    
    def clear(self) -> None:
        """Clear all services (useful for testing)."""
        self._services.clear()
        self._factories.clear()


# Global container instance
DI = DependencyContainer()


# Helper functions for common patterns

def with_di(service_name: str):
    """Decorator to inject a dependency into a function.
    
    Usage:
        @with_di('get_db')
        def my_function(get_db):
            conn = get_db()
            # Use connection
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            service = DI.get(service_name)
            return func(service, *args, **kwargs)
        return wrapper
    return decorator


def mock_database(data: Dict[str, list] = None) -> sqlite3.Connection:
    """Create an in-memory SQLite database for testing.
    
    Args:
        data: Optional dict mapping table names to list of dicts
    
    Returns:
        In-memory SQLite connection
    
    Usage:
        @pytest.fixture
        def db():
            conn = mock_database({
                'users': [{'id': 1, 'username': 'alice'}]
            })
            yield conn
            conn.close()
    """
    import json
    
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if data:
        for table, rows in data.items():
            if rows:
                # Get columns from first row
                columns = list(rows[0].keys())
                col_def = ', '.join([f'{col} TEXT' for col in columns])
                c.execute(f"CREATE TABLE {table} ({col_def})")
                
                # Insert rows
                placeholders = ', '.join(['?' for _ in columns])
                for row in rows:
                    values = tuple(row.get(col, '') for col in columns)
                    c.execute(f"INSERT INTO {table} VALUES ({placeholders})", values)
        
        conn.commit()
    
    return conn
