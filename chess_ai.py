# chess_ai.py
"""
Simple negamax + alpha-beta bot engine.
No external binaries required.
Difficulty:
  easy   → random legal move
  medium → depth 2 alpha-beta
  hard   → depth 3 alpha-beta with MVV-LVA move ordering
"""
import chess
import random

PIECE_VALUES = {
    chess.PAWN:   100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK:   500,
    chess.QUEEN:  900,
    chess.KING:   20000,
}

# Piece-square tables indexed [0]=a8..[63]=h1  (row0=rank8, row7=rank1)
_PAWN = [
     0,  0,  0,  0,  0,  0,  0,  0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
     5,  5, 10, 25, 25, 10,  5,  5,
     0,  0,  0, 20, 20,  0,  0,  0,
     5, -5,-10,  0,  0,-10, -5,  5,
     5, 10, 10,-20,-20, 10, 10,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
]
_KNIGHT = [
   -50,-40,-30,-30,-30,-30,-40,-50,
   -40,-20,  0,  0,  0,  0,-20,-40,
   -30,  0, 10, 15, 15, 10,  0,-30,
   -30,  5, 15, 20, 20, 15,  5,-30,
   -30,  0, 15, 20, 20, 15,  0,-30,
   -30,  5, 10, 15, 15, 10,  5,-30,
   -40,-20,  0,  5,  5,  0,-20,-40,
   -50,-40,-30,-30,-30,-30,-40,-50,
]
_BISHOP = [
   -20,-10,-10,-10,-10,-10,-10,-20,
   -10,  0,  0,  0,  0,  0,  0,-10,
   -10,  0,  5, 10, 10,  5,  0,-10,
   -10,  5,  5, 10, 10,  5,  5,-10,
   -10,  0, 10, 10, 10, 10,  0,-10,
   -10, 10, 10, 10, 10, 10, 10,-10,
   -10,  5,  0,  0,  0,  0,  5,-10,
   -20,-10,-10,-10,-10,-10,-10,-20,
]
_ROOK = [
     0,  0,  0,  0,  0,  0,  0,  0,
     5, 10, 10, 10, 10, 10, 10,  5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
     0,  0,  0,  5,  5,  0,  0,  0,
]
_QUEEN = [
   -20,-10,-10, -5, -5,-10,-10,-20,
   -10,  0,  0,  0,  0,  0,  0,-10,
   -10,  0,  5,  5,  5,  5,  0,-10,
    -5,  0,  5,  5,  5,  5,  0, -5,
     0,  0,  5,  5,  5,  5,  0, -5,
   -10,  5,  5,  5,  5,  5,  0,-10,
   -10,  0,  5,  0,  0,  0,  0,-10,
   -20,-10,-10, -5, -5,-10,-10,-20,
]
_KING_MID = [
   -30,-40,-40,-50,-50,-40,-40,-30,
   -30,-40,-40,-50,-50,-40,-40,-30,
   -30,-40,-40,-50,-50,-40,-40,-30,
   -30,-40,-40,-50,-50,-40,-40,-30,
   -20,-30,-30,-40,-40,-30,-30,-20,
   -10,-20,-20,-20,-20,-20,-20,-10,
    20, 20,  0,  0,  0,  0, 20, 20,
    20, 30, 10,  0,  0, 10, 30, 20,
]

_PST = {
    chess.PAWN:   _PAWN,
    chess.KNIGHT: _KNIGHT,
    chess.BISHOP: _BISHOP,
    chess.ROOK:   _ROOK,
    chess.QUEEN:  _QUEEN,
    chess.KING:   _KING_MID,
}


def _pst(piece_type: int, square: int, color: bool) -> int:
    tbl  = _PST.get(piece_type, [0]*64)
    rank = chess.square_rank(square)   # 0=rank1 .. 7=rank8
    file = chess.square_file(square)
    idx  = (7 - rank) * 8 + file if color == chess.WHITE else rank * 8 + file
    return tbl[idx]


def _evaluate(board: chess.Board) -> int:
    """Score from white's perspective (positive = white ahead)."""
    if board.is_checkmate():
        return -100_000 if board.turn == chess.WHITE else 100_000
    if board.is_stalemate() or board.is_insufficient_material():
        return 0
    score = 0
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p:
            v = PIECE_VALUES[p.piece_type] + _pst(p.piece_type, sq, p.color)
            score += v if p.color == chess.WHITE else -v
    return score


def _negamax(board: chess.Board, depth: int, alpha: float, beta: float, color: int) -> int:
    if depth == 0 or board.is_game_over():
        return color * _evaluate(board)
    best = -float("inf")
    moves = sorted(board.legal_moves,
                   key=lambda m: (board.is_capture(m), bool(m.promotion)),
                   reverse=True)
    for move in moves:
        board.push(move)
        val = -_negamax(board, depth - 1, -beta, -alpha, -color)
        board.pop()
        best  = max(best, val)
        alpha = max(alpha, val)
        if alpha >= beta:
            break
    return best


def get_bot_move(board: chess.Board, difficulty: str) -> chess.Move | None:
    moves = list(board.legal_moves)
    if not moves:
        return None
    if difficulty == "easy":
        return random.choice(moves)

    depth = 2 if difficulty == "medium" else 3
    color = 1 if board.turn == chess.WHITE else -1

    moves.sort(key=lambda m: (board.is_capture(m), bool(m.promotion)), reverse=True)

    best_move  = moves[0]
    best_score = -float("inf")
    alpha, beta = -float("inf"), float("inf")

    for move in moves:
        board.push(move)
        score = -_negamax(board, depth - 1, -beta, -alpha, -color)
        board.pop()
        if score > best_score:
            best_score = score
            best_move  = move
        alpha = max(alpha, score)

    return best_move