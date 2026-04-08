"""
blueprints/communications/

User communication and collaboration blueprints.
- chat.py: Main chat interface
- channels.py: User-created channels
- updates.py: Polls and voting
- dropzone.py: File sharing
- feedback.py: Feature requests and bug reports
"""

from .chat import chat_bp
from .channels import channels_bp
from .dropzone import dropzone_bp
from .feedback import feedback_bp
from .updates import updates_bp

__all__ = ["chat_bp", "channels_bp", "dropzone_bp", "feedback_bp", "updates_bp"]
