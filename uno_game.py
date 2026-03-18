# uno_game.py
"""
Complete UNO engine. No external dependencies.
Supports: all standard cards, draw-stacking, 2-player reverse = skip.
Bot difficulties: easy (random), medium (prefer action cards), hard (strategic).
"""
import random
from typing import Optional

COLORS = ['red', 'green', 'blue', 'yellow']

UNO_TYPES = {
    'classic': {
        'name':        'Classic UNO',
        'min_players': 2,
        'max_players': 10,
        'description': 'Standard UNO rules — first to empty hand wins.',
    }
}


class Card:
    __slots__ = ('color', 'value', 'chosen_color')

    def __init__(self, color: str, value: str):
        self.color         = color
        self.value         = value
        self.chosen_color: Optional[str] = None

    def effective_color(self) -> str:
        return self.chosen_color or self.color

    def can_play_on(self, top: 'Card') -> bool:
        if self.color == 'wild':
            return True
        tc = top.effective_color()
        if self.color == tc:
            return True
        if tc != 'wild' and self.value == top.value:
            return True
        return False

    def to_dict(self) -> dict:
        return {'color': self.color, 'value': self.value,
                'chosen_color': self.chosen_color}

    def reset(self):
        self.chosen_color = None


def make_deck() -> list:
    deck = []
    for c in COLORS:
        deck.append(Card(c, '0'))
        for v in ['1','2','3','4','5','6','7','8','9','skip','reverse','draw2']:
            deck.append(Card(c, v))
            deck.append(Card(c, v))
    for _ in range(4):
        deck.append(Card('wild', 'wild'))
        deck.append(Card('wild', 'wild4'))
    random.shuffle(deck)
    return deck


def bot_choose_card(hand: list, top: Card, difficulty: str,
                    pending_draw: int = 0) -> Optional[int]:
    if pending_draw > 0:
        playable = [i for i, c in enumerate(hand)
                    if c.value in ('draw2', 'wild4') and c.can_play_on(top)]
    else:
        playable = [i for i, c in enumerate(hand) if c.can_play_on(top)]
    if not playable:
        return None
    if difficulty == 'easy':
        return random.choice(playable)

    def score(idx):
        c = hand[idx]
        if difficulty == 'medium':
            if c.value == 'wild4':   return 9
            if c.value == 'draw2':   return 8
            if c.value in ('skip','reverse'): return 7
            if c.value == 'wild':    return 4
            return int(c.value) if c.value.isdigit() else 1
        # hard
        if c.value == 'wild4':   return 10
        if c.value == 'draw2':   return 9
        if c.value == 'skip':    return 8
        if c.value == 'reverse': return 7
        if c.value == 'wild':    return 5
        return int(c.value) if c.value.isdigit() else 1

    return max(playable, key=score)


def bot_choose_color(hand: list) -> str:
    counts = {c: 0 for c in COLORS}
    for card in hand:
        if card.color in counts:
            counts[card.color] += 1
    return max(counts, key=counts.get)


class UnoGame:
    def __init__(self, players_data: list):
        """
        players_data: list of dicts:
          sid, id, username, is_bot, difficulty (for bots)
        """
        self.players = [dict(p) for p in players_data]
        random.shuffle(self.players)
        for p in self.players:
            p['hand']     = []
            p['finished'] = False
            p['rank']     = None

        self.deck          = make_deck()
        self.discard       = []
        self.direction     = 1
        self.turn_order    = list(range(len(self.players)))
        self.turn_pos      = 0
        self.pending_draw  = 0
        self.waiting_for_color = False
        self.status        = 'playing'
        self.winner_rank   = 0

        for p in self.players:
            p['hand'] = [self.deck.pop() for _ in range(7)]

        # First card — must not be wild
        while True:
            card = self.deck.pop()
            if card.color != 'wild':
                self.discard.append(card)
                break
            self.deck.insert(0, card)

        self._handle_first_card()

    # ── Turn helpers ──────────────────────────────────────────

    def active_count(self) -> int:
        return sum(1 for p in self.players if not p['finished'])

    def _advance(self):
        n = len(self.turn_order)
        if not n:
            return
        new = (self.turn_pos + self.direction) % n
        if new < 0:
            new += n
        for _ in range(n + 1):
            if not self.players[self.turn_order[new]]['finished']:
                break
            new = (new + self.direction) % n
            if new < 0:
                new += n
        self.turn_pos = new

    def cur_idx(self) -> int:
        return self.turn_order[self.turn_pos]

    def current_player(self) -> dict:
        return self.players[self.cur_idx()]

    def top_card(self) -> Optional[Card]:
        return self.discard[-1] if self.discard else None

    def player_idx_by_sid(self, sid: str) -> int:
        for i, p in enumerate(self.players):
            if not p.get('is_bot') and p.get('sid') == sid:
                return i
        return -1

    def _handle_first_card(self):
        top = self.top_card()
        if not top:
            return
        if top.value == 'skip':
            self._advance()
        elif top.value == 'reverse':
            self.direction = -1
            if self.active_count() == 2:
                self._advance()
        elif top.value == 'draw2':
            self.pending_draw += 2

    def _refill(self):
        if len(self.deck) < 4 and len(self.discard) > 1:
            top = self.discard.pop()
            for c in self.discard:
                c.reset()
            random.shuffle(self.discard)
            self.deck.extend(self.discard)
            self.discard = [top]

    def _draw_n(self, n: int) -> list:
        self._refill()
        drawn = []
        for _ in range(n):
            if self.deck:
                drawn.append(self.deck.pop())
        return drawn

    # ── Game actions ──────────────────────────────────────────

    def play_card(self, player_all_idx: int, card_hand_idx: int,
                  chosen_color: str = None) -> dict:
        p = self.players[player_all_idx]
        if player_all_idx != self.cur_idx():
            return {'ok': False, 'error': 'Not your turn.'}
        if p['finished']:
            return {'ok': False, 'error': 'You have finished.'}

        hand = p['hand']
        if card_hand_idx >= len(hand):
            return {'ok': False, 'error': 'Invalid card.'}

        card = hand[card_hand_idx]
        top  = self.top_card()

        if self.pending_draw > 0 and card.value not in ('draw2', 'wild4'):
            return {'ok': False, 'error': f'Stack a draw card or draw {self.pending_draw}.'}

        if not card.can_play_on(top):
            return {'ok': False, 'error': 'That card cannot be played here.'}

        hand.pop(card_hand_idx)

        # Wild — need color choice
        if card.color == 'wild':
            if chosen_color and chosen_color in COLORS:
                card.chosen_color = chosen_color
            else:
                self.discard.append(card)
                self.waiting_for_color = True
                return {'ok': True, 'needs_color': True, 'card': card.to_dict()}

        self.discard.append(card)

        # Win condition
        if not hand:
            self.winner_rank += 1
            p['finished'] = True
            p['rank']     = self.winner_rank
            remaining = self.active_count()
            if remaining <= 1:
                for p2 in self.players:
                    if not p2['finished']:
                        self.winner_rank += 1
                        p2['finished'] = True
                        p2['rank']     = self.winner_rank
                self.status = 'finished'
                return {'ok': True, 'event': 'game_over', 'card': card.to_dict()}
            n = remaining
            self.turn_pos = self.turn_pos % n
            self._advance()
            return {'ok': True, 'event': 'player_won', 'card': card.to_dict(),
                    'rank': p['rank'], 'username': p['username']}

        self._apply_effects(card)
        return {'ok': True, 'event': 'played', 'card': card.to_dict()}

    def _apply_effects(self, card: Card):
        if card.value == 'skip':
            self._advance()
            self._advance()
        elif card.value == 'reverse':
            self.direction *= -1
            if self.active_count() == 2:
                self._advance(); self._advance()
            else:
                self._advance()
        elif card.value in ('draw2', 'wild4'):
            self.pending_draw += 4 if card.value == 'wild4' else 2
            self._advance()
        else:
            self._advance()

    def choose_color(self, player_all_idx: int, color: str) -> dict:
        if player_all_idx != self.cur_idx():
            return {'ok': False, 'error': 'Not your turn.'}
        if not self.waiting_for_color:
            return {'ok': False, 'error': 'No color choice needed.'}
        if color not in COLORS:
            return {'ok': False, 'error': 'Invalid color.'}
        self.top_card().chosen_color = color
        self.waiting_for_color = False
        self._apply_effects(self.top_card())
        return {'ok': True}

    def draw_action(self, player_all_idx: int) -> dict:
        if player_all_idx != self.cur_idx():
            return {'ok': False, 'error': 'Not your turn.'}
        count = self.pending_draw if self.pending_draw > 0 else 1
        drawn = self._draw_n(count)
        self.players[player_all_idx]['hand'].extend(drawn)
        self.pending_draw = 0
        self._advance()
        return {'ok': True, 'drawn': [c.to_dict() for c in drawn], 'count': count}

    # ── State snapshot ────────────────────────────────────────

    def snapshot(self, viewer_sid: str = None,
                 viewer_is_spectator: bool = False) -> dict:
        ci  = self.cur_idx()
        cur = self.current_player()

        players_out = []
        for i, p in enumerate(self.players):
            hand     = p['hand']
            is_me    = (not p.get('is_bot') and p.get('sid') == viewer_sid)
            see_hand = is_me or viewer_is_spectator

            players_out.append({
                'idx':        i,
                'sid':        p.get('sid'),
                'id':         p.get('id', p.get('sid', str(i))),
                'username':   p['username'],
                'is_bot':     p.get('is_bot', False),
                'finished':   p['finished'],
                'rank':       p.get('rank'),
                'hand':       ([c.to_dict() for c in hand] if see_hand and hand
                               else (len(hand) if hand is not None else 0)),
                'hand_count': len(hand) if hand is not None else 0,
                'has_uno':    (len(hand) == 1) if (hand and not p['finished']) else False,
                'is_current': i == ci,
            })

        top = self.top_card()
        return {
            'players':           players_out,
            'top_card':          top.to_dict() if top else None,
            'deck_count':        len(self.deck),
            'direction':         self.direction,
            'current_player_idx':ci,
            'current_username':  cur['username'] if cur else None,
            'current_sid':       (cur.get('sid') if cur and not cur.get('is_bot') else None),
            'current_is_bot':    (cur.get('is_bot', False) if cur else False),
            'waiting_for_color': self.waiting_for_color,
            'pending_draw':      self.pending_draw,
            'status':            self.status,
        }