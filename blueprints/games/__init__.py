"""
blueprints/games/

Multiplayer game blueprints.
All game logic runs primarily client-side with real-time coordination via WebSockets.

Games:
- chess.py: Chess with AI opponent
- tetris.py: Multiplayer Tetris
- uno.py: Card game UNO
- slither.py: Snake game (Slither.io style)
- scribble.py: Drawing and guessing game
- geoguesser.py: Geography guessing game
"""

from .chess import chess_bp
from .tetris import tetris_bp
from .uno import uno_bp
from .slither import slither_bp
from .scribble import scribble_bp
from .geoguesser import geoguesser_bp

__all__ = [
    "chess_bp", "tetris_bp", "uno_bp",
    "slither_bp", "scribble_bp", "geoguesser_bp"
]
