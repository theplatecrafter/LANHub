"""WebSocket events for owner playground real-time updates."""

from socketio import emit
from functions.owner_playground import get_task_manager
import logging

logger = logging.getLogger(__name__)


def init_owner_playground_events(socketio):
    """Initialize owner playground socket event handlers."""
    
    @socketio.on('owner_playground:get_task_stats')
    def handle_get_task_stats():
        """Send task statistics to client."""
        try:
            manager = get_task_manager()
            stats = manager.get_stats()
            emit('owner_playground:task_stats', stats)
        except Exception as e:
            logger.error(f"Error getting task stats: {e}")
            emit('owner_playground:error', {"error": str(e)})
    
    @socketio.on('owner_playground:trigger_task')
    def handle_trigger_task(data):
        """Manually trigger a spontaneous task."""
        try:
            task_name = data.get('task_name')
            manager = get_task_manager()
            result = manager.trigger_task(task_name)
            emit('owner_playground:task_triggered', result)
        except Exception as e:
            logger.error(f"Error triggering task: {e}")
            emit('owner_playground:error', {"error": str(e)})
    
    @socketio.on('owner_playground:toggle_task')
    def handle_toggle_task(data):
        """Enable or disable a task."""
        try:
            task_name = data.get('task_name')
            manager = get_task_manager()
            
            with manager.lock:
                if task_name not in manager.tasks:
                    emit('owner_playground:error', {"error": f"Task '{task_name}' not found"})
                    return
                
                task = manager.tasks[task_name]
                task.enabled = not task.enabled
                
                emit('owner_playground:task_toggled', {
                    "task": task_name,
                    "enabled": task.enabled
                })
        except Exception as e:
            logger.error(f"Error toggling task: {e}")
            emit('owner_playground:error', {"error": str(e)})

