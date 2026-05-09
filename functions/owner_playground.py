"""A set of functions for Divinecode's fun little playground features"""

import numpy as np
from skimage import io, measure
import os
import threading
import time
import logging
from glob_vars import *

OWNER_PLAYGROUND_FILES_DIR = os.path.join(BASE_DIR, 'files/owner_playground')
logger = logging.getLogger(__name__)

# ─── Image Coherency Functions ──────────────────────────────────────────────

def measure_coherency(image_array: np.ndarray) -> float:
    """Measure image coherency using Shannon entropy.
    
    High Entropy (~8.0) = High Noise/Low Meaning
    Low Entropy (<5.0) = High Structure/High Meaning
    """
    img = image_array.astype(np.float32) / 255.0  # Normalize to [0, 1]
    img_8bit = (img * 255).astype(np.uint8)
    entropy = measure.shannon_entropy(img_8bit)
    return entropy


def random_image(width: int, height: int) -> np.ndarray:
    """Generate a random noise image of given dimensions."""
    return np.random.rand(height, width) * 255


def ndarray_to_png(array: np.ndarray, subdirectory: str = "Coherent_Images") -> str:
    """Save a numpy array as a PNG image. Returns the filepath."""
    subdir_path = os.path.join(OWNER_PLAYGROUND_FILES_DIR, subdirectory)
    os.makedirs(subdir_path, exist_ok=True)
    
    # Get next filename
    existing = os.listdir(subdir_path) if os.path.exists(subdir_path) else []
    filename = f"image_{len(existing) + 1}.png"
    filepath = os.path.join(subdir_path, filename)
    
    io.imsave(filepath, array.astype(np.uint8))
    return filepath


# ─── Background Task System ─────────────────────────────────────────────────

class OwnerPlaygroundTask:
    """Base class for playground tasks."""
    
    def __init__(self, name: str, task_type: str = "continuous"):
        """
        Args:
            name: Task identifier
            task_type: "continuous" (runs in loop) or "spontaneous" (on-demand)
        """
        self.name = name
        self.task_type = task_type
        self.enabled = True
        self.interval = 1.0  # Default interval in seconds (for continuous tasks)
        self.stats = {"runs": 0, "errors": 0}
    
    def run(self):
        """Execute the task. Override in subclass."""
        raise NotImplementedError
    
    def on_error(self, error: Exception):
        """Handle errors. Override if custom error handling needed."""
        logger.error(f"Task '{self.name}' failed: {error}")
        self.stats["errors"] += 1


class CoherentImageFinderTask(OwnerPlaygroundTask):
    """Continuously generates images and saves coherent ones."""
    
    def __init__(self, width: int = 256, height: int = 256, entropy_threshold: float = 5.0, interval: float = 2.0):
        super().__init__("coherent_image_finder", task_type="continuous")
        self.width = width
        self.height = height
        self.entropy_threshold = entropy_threshold
        self.interval = interval  # Seconds between generations
    
    def run(self):
        """Generate image, measure coherency, save if threshold met."""
        try:
            img = random_image(self.width, self.height)
            entropy = measure_coherency(img)
            
            if entropy < self.entropy_threshold:
                filepath = ndarray_to_png(img, "Coherent_Images")
                logger.info(f"✓ Coherent image found! Entropy: {entropy:.2f} → {filepath}")
            
            self.stats["runs"] += 1
            return {"entropy": entropy, "saved": entropy < self.entropy_threshold}
        except Exception as e:
            self.on_error(e)


class PlaygroundTaskManager:
    """Manages continuous and spontaneous playground tasks."""
    
    def __init__(self):
        self.tasks = {}  # name -> OwnerPlaygroundTask
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self.app = None
    
    def register_task(self, task: OwnerPlaygroundTask):
        """Register a task (continuous or spontaneous)."""
        with self.lock:
            self.tasks[task.name] = task
            logger.info(f"Registered {task.task_type} task: {task.name}")
    
    def start(self, app=None):
        """Start the background task manager."""
        if self.running:
            logger.warning("Task manager already running")
            return
        
        self.running = True
        self.app = app
        
        self.thread = threading.Thread(daemon=True, target=self._loop)
        self.thread.start()
        logger.info("Owner Playground task manager started")
    
    def stop(self):
        """Stop the background task manager."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Owner Playground task manager stopped")
    
    def _loop(self):
        """Main background loop for continuous tasks."""
        # Push Flask app context if available
        app_context = None
        if self.app:
            app_context = self.app.app_context()
            app_context.push()
        
        try:
            continuous_tasks = [t for t in self.tasks.values() if t.task_type == "continuous"]
            task_timers = {t.name: 0 for t in continuous_tasks}
            
            while self.running:
                current_time = time.time()
                
                for task in continuous_tasks:
                    if not task.enabled:
                        continue
                    
                    # Check if task is ready to run
                    if current_time - task_timers[task.name] >= task.interval:
                        try:
                            task.run()
                            task_timers[task.name] = current_time
                        except Exception as e:
                            task.on_error(e)
                
                time.sleep(0.1)  # Small sleep to avoid busy-waiting
        
        except Exception as e:
            logger.error(f"Task manager loop error: {e}")
        finally:
            if app_context:
                app_context.pop()
    
    def trigger_task(self, task_name: str) -> dict:
        """Manually trigger a spontaneous task. Returns result."""
        with self.lock:
            if task_name not in self.tasks:
                return {"error": f"Task '{task_name}' not found"}
            
            task = self.tasks[task_name]
            if task.task_type != "spontaneous":
                return {"error": f"Task '{task_name}' is not spontaneous"}
            
            try:
                result = task.run()
                return {"success": True, "result": result}
            except Exception as e:
                task.on_error(e)
                return {"error": str(e)}
    
    def get_stats(self) -> dict:
        """Get statistics for all tasks."""
        with self.lock:
            return {name: {"enabled": t.enabled, "type": t.task_type, "stats": t.stats} 
                    for name, t in self.tasks.items()}


# Global task manager instance
_task_manager = PlaygroundTaskManager()


def init_playground_tasks(app):
    """Initialize and start playground tasks. Call from app startup."""
    # Register tasks
    _task_manager.register_task(
        CoherentImageFinderTask(
            width=128, 
            height=128, 
            entropy_threshold=6,  # Looking for low-entropy (coherent) images
            interval=1.0  # Check every 1 second
        )
    )
    
    # Start the manager
    _task_manager.start(app)


def get_task_manager():
    """Get the global task manager instance."""
    return _task_manager
    