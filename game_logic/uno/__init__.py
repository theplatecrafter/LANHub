"""
game_logic/uno/

UNO game engine with extensible game-type architecture.
Supports multiple UNO variants through subclassing.
"""

from .uno_game import UnoGame, UNO_TYPES, COLORS, Card

__all__ = ["UnoGame", "UNO_TYPES", "COLORS", "Card"]
