# uno_game.py
"""
UNO engine — extensible game-type architecture.

Adding a new UNO type
─────────────────────
1. Subclass UnoGame and override only the hooks that differ:

   Core hooks (called by the base engine):
     build_deck()                     – return the shuffled deck
     starting_hand_size()             – cards dealt at start (default 7)
     card_can_play_on(card, top)      – is this card legal to play?
     draw_stack_values()              – set of values that may stack onto a draw chain
     apply_effects(card)              – side-effects; return dict if a win event occurred
     handle_first_card()              – react to the opening card

   "Waiting for player input" hooks (called by events file / bot runner):
     get_pending_player_action()      – return {type, player_idx} or None
     resolve_player_action(idx, type, data) – execute a pending action
     bot_resolve_pending_action(idx, player, type) – return data dict for bot auto-resolve

   Bot hooks:
     bot_pick_card(hand, top, difficulty, pending_draw) – card index or None
     bot_pick_color(hand)             – color string

   Snapshot/meta hooks:
     extra_snapshot_fields()          – dict merged into every snapshot
     card_descriptions()              – {value: description} for tooltip/rules popup
     rules_html()                     – list of rule strings for rules popup

2. Register in UNO_TYPES at the bottom with game_class=YourClass.
3. Done — events file, lobby, and bot runner need no changes.
"""
import random
from typing import Optional

COLORS = ['red', 'green', 'blue', 'yellow']

UNO_TYPES: dict = {}   # filled in at the bottom


# ── Card ──────────────────────────────────────────────────────────────────────

class Card:
    __slots__ = ('color', 'value', 'chosen_color')

    def __init__(self, color: str, value: str):
        self.color        = color
        self.value        = value
        self.chosen_color: Optional[str] = None

    def effective_color(self) -> str:
        return self.chosen_color or self.color

    def can_play_on_classic(self, top: 'Card') -> bool:
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


# ── Classic deck / bot helpers ────────────────────────────────────────────────

def _build_classic_deck() -> list:
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


def _classic_bot_pick_card(hand: list, top: Card, difficulty: str,
                            pending_draw: int = 0) -> Optional[int]:
    if pending_draw > 0:
        playable = [i for i, c in enumerate(hand)
                    if c.value in ('draw2', 'wild4') and c.can_play_on_classic(top)]
    else:
        playable = [i for i, c in enumerate(hand) if c.can_play_on_classic(top)]
    if not playable:
        return None
    if difficulty == 'easy':
        return random.choice(playable)

    def score(idx):
        c = hand[idx]
        if difficulty == 'medium':
            if c.value == 'wild4':             return 9
            if c.value == 'draw2':             return 8
            if c.value in ('skip', 'reverse'): return 7
            if c.value == 'wild':              return 4
            return int(c.value) if c.value.isdigit() else 1
        if c.value == 'wild4':             return 10
        if c.value == 'draw2':             return 9
        if c.value == 'skip':              return 8
        if c.value == 'reverse':           return 7
        if c.value == 'wild':              return 5
        return int(c.value) if c.value.isdigit() else 1

    return max(playable, key=score)


def _classic_bot_pick_color(hand: list) -> str:
    counts = {c: 0 for c in COLORS}
    for card in hand:
        if card.color in counts:
            counts[card.color] += 1
    return max(counts, key=counts.get)


# ── UnoGame base class ────────────────────────────────────────────────────────

class UnoGame:
    """
    Base UNO engine. Type-specific behaviour lives entirely in hook methods.
    Override only what differs in your subclass.
    """

    def __init__(self, players_data: list):
        # Subclasses that need extra instance state MUST initialise it
        # before calling super().__init__() because build_deck() and
        # handle_first_card() are called from here.
        self.players = [dict(p) for p in players_data]
        random.shuffle(self.players)
        for p in self.players:
            p['hand']     = []
            p['finished'] = False
            p['rank']     = None

        self.deck:               list = self.build_deck()
        self.discard:            list = []
        self.direction:           int = 1
        self.turn_order:         list = list(range(len(self.players)))
        self.turn_pos:            int = 0
        self.pending_draw:        int = 0
        self.waiting_for_color:  bool = False
        self.status:              str = 'playing'
        self.winner_rank:         int = 0
        self.must_play_drawn:    bool = False

        for p in self.players:
            p['hand'] = [self.deck.pop() for _ in range(self.starting_hand_size())]

        while True:
            card = self.deck.pop()
            if self._first_card_ok(card):
                self.discard.append(card)
                break
            self.deck.insert(0, card)

        self.handle_first_card()

    # ── Core hooks ────────────────────────────────────────────────────────────

    def starting_hand_size(self) -> int:
        return 7

    def build_deck(self) -> list:
        raise NotImplementedError

    def card_can_play_on(self, card: Card, top: Card) -> bool:
        return card.can_play_on_classic(top)

    def draw_stack_values(self) -> set:
        return {'draw2', 'wild4'}

    def apply_effects(self, card: Card) -> Optional[dict]:
        """
        Apply side-effects of card after it lands on the discard pile.
        Return None normally, or a win-event dict if the effect caused a win.
        """
        if card.value == 'skip':
            self._advance(); self._advance()
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
        return None
    
    def _first_card_ok(self, card: Card) -> bool:
        """Return True if this card is acceptable as the opening discard card."""
        return card.color != 'wild'

    def handle_first_card(self):
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

    # ── Pending player action hooks ───────────────────────────────────────────

    def get_pending_player_action(self) -> Optional[dict]:
        return None

    def resolve_player_action(self, player_idx: int,
                               action_type: str, data: dict) -> dict:
        return {'ok': False, 'error': f'Unknown action type: {action_type}'}

    def bot_resolve_pending_action(self, player_idx: int,
                                    player: dict, action_type: str) -> dict:
        return {}

    # ── Bot hooks ─────────────────────────────────────────────────────────────

    def bot_pick_card(self, hand: list, top: Card,
                      difficulty: str, pending_draw: int) -> Optional[int]:
        return _classic_bot_pick_card(hand, top, difficulty, pending_draw)
    
    def valid_colors(self) -> list:
        """Valid non-wild colours for the current game state. Override for multi-side games."""
        return COLORS

    def bot_pick_color(self, hand: list) -> str:
        return _classic_bot_pick_color(hand)

    # ── Snapshot / meta hooks ─────────────────────────────────────────────────

    def extra_snapshot_fields(self) -> dict:
        return {
            'stackable_values':  list(self.draw_stack_values()),
            'draw_values':       {},
            'card_descriptions': self.card_descriptions(),
            'rules':             self.rules_html(),
        }

    def card_descriptions(self) -> dict:
        return {}

    def rules_html(self) -> list:
        return []

    # ── Internal helpers ──────────────────────────────────────────────────────

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
        self.must_play_drawn = False

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
        return [self.deck.pop() for _ in range(min(n, len(self.deck)))]

    def _playable_indices(self, hand: list) -> list:
        top = self.top_card()
        if self.pending_draw > 0:
            return [i for i, c in enumerate(hand)
                    if c.value in self.draw_stack_values()
                    and self.card_can_play_on(c, top)]
        return [i for i, c in enumerate(hand) if self.card_can_play_on(c, top)]

    def _check_win(self, player_all_idx: int) -> Optional[dict]:
        p = self.players[player_all_idx]
        if p['hand']:
            return None
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
            return {'event': 'game_over'}
        self.turn_pos = self.turn_pos % remaining
        self._advance()
        return {'event': 'player_won', 'rank': p['rank'], 'username': p['username']}

    def _check_all_mercy(self) -> list:
        """Base: no mercy rule. Override in subclasses with hand-size knockout."""
        return []

    # ── Public game actions ───────────────────────────────────────────────────

    def play_card(self, player_all_idx: int, card_hand_idx: int,
                  chosen_color: str = None) -> dict:
        p = self.players[player_all_idx]
        if player_all_idx != self.cur_idx():
            return {'ok': False, 'error': 'Not your turn.'}
        if p['finished']:
            return {'ok': False, 'error': 'You have finished.'}
        self.must_play_drawn = False
        hand = p['hand']
        if card_hand_idx >= len(hand):
            return {'ok': False, 'error': 'Invalid card.'}

        card = hand[card_hand_idx]
        top  = self.top_card()

        if self.pending_draw > 0 and card.value not in self.draw_stack_values():
            return {'ok': False,
                    'error': f'Stack a draw card or draw {self.pending_draw}.'}
        if not self.card_can_play_on(card, top):
            return {'ok': False, 'error': 'That card cannot be played here.'}

        hand.pop(card_hand_idx)

        if card.color == 'wild':
            if chosen_color and chosen_color in self.valid_colors():
                card.chosen_color = chosen_color
            else:
                self.discard.append(card)
                self.waiting_for_color = True
                return {'ok': True, 'needs_color': True, 'card': card.to_dict()}

        self.discard.append(card)

        win = self._check_win(player_all_idx)
        if win:
            return {'ok': True, 'card': card.to_dict(), **win}

        effect = self.apply_effects(card)
        if effect:
            return {'ok': True, 'card': card.to_dict(), **effect}

        return {'ok': True, 'event': 'played', 'card': card.to_dict()}

    def choose_color(self, player_all_idx: int, color: str) -> dict:
        if player_all_idx != self.cur_idx():
            return {'ok': False, 'error': 'Not your turn.'}
        if not self.waiting_for_color:
            return {'ok': False, 'error': 'No color choice needed.'}
        if color not in self.valid_colors():
            return {'ok': False, 'error': 'Invalid color.'}
        self.top_card().chosen_color = color
        self.waiting_for_color = False
        effect = self.apply_effects(self.top_card())
        result = {'ok': True, 'event': 'played'}
        if effect:
            result.update(effect)
        return result

    def draw_action(self, player_all_idx: int) -> dict:
        if player_all_idx != self.cur_idx():
            return {'ok': False, 'error': 'Not your turn.'}
        count = self.pending_draw if self.pending_draw > 0 else 1
        drawn = self._draw_n(count)
        self.players[player_all_idx]['hand'].extend(drawn)
        self.pending_draw = 0
        self._advance()
        return {'ok': True, 'drawn': [c.to_dict() for c in drawn],
                'count': count, 'found_playable': False}

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self, viewer_sid: str = None,
                 viewer_is_spectator: bool = False) -> dict:
        ci  = self.cur_idx()
        cur = self.current_player()

        players_out = []
        for i, p in enumerate(self.players):
            hand  = p['hand']
            is_me = not p.get('is_bot') and p.get('sid') == viewer_sid
            see   = is_me or viewer_is_spectator
            players_out.append({
                'idx':           i,
                'sid':           p.get('sid'),
                'id':            p.get('id', p.get('sid', str(i))),
                'username':      p['username'],
                'is_bot':        p.get('is_bot', False),
                'finished':      p['finished'],
                'mercy_knocked': p.get('mercy_knocked', False),
                'rank':          p.get('rank'),
                'hand':          ([c.to_dict() for c in hand]
                                  if see and hand else len(hand) if hand else 0),
                'hand_count':    len(hand) if hand else 0,
                'has_uno':       len(hand) == 1 if (hand and not p['finished']) else False,
                'is_current':    i == ci,
            })

        top = self.top_card()
        base = {
            'players':            players_out,
            'top_card':           top.to_dict() if top else None,
            'deck_count':         len(self.deck),
            'direction':          self.direction,
            'current_player_idx': ci,
            'current_username':   cur['username'] if cur else None,
            'current_sid':        cur.get('sid') if cur and not cur.get('is_bot') else None,
            'current_is_bot':     cur.get('is_bot', False) if cur else False,
            'waiting_for_color':  self.waiting_for_color,
            'pending_draw':       self.pending_draw,
            'status':             self.status,
            'game_type':          self._game_type_key(),
            'must_play_drawn':    self.must_play_drawn,
        }
        base.update(self.extra_snapshot_fields())
        return base

    def _game_type_key(self) -> str:
        for key, info in UNO_TYPES.items():
            if info.get('game_class') and isinstance(self, info['game_class']):
                return key
        return 'unknown'


# ── Classic UNO ───────────────────────────────────────────────────────────────

class ClassicUnoGame(UnoGame):

    def build_deck(self) -> list:
        return _build_classic_deck()

    def card_descriptions(self) -> dict:
        return {
            'skip':    'Next player loses their turn.',
            'reverse': 'Reverses the direction of play.',
            'draw2':   'Next player draws 2 cards and loses their turn.',
            'wild':    'Change the colour of play to any colour.',
            'wild4':   'Change colour AND the next player draws 4 cards and loses their turn.',
        }

    def rules_html(self) -> list:
        return [
            'Match the top card by colour or number.',
            'If you have no playable card, draw one from the deck.',
            'Play a drawn card immediately if it is playable.',
            'First player to empty their hand wins.',
            'Shout "UNO!" when you are down to one card.',
            'Wild cards may be played at any time on your turn.',
            'Draw 4 may only be played if you have no other playable card.',
        ]


# ═══════════════════════════════════════════════════════════════════════════════
#  Show 'Em No Mercy
# ═══════════════════════════════════════════════════════════════════════════════

NO_MERCY_DRAW_VALUES = {
    'draw2':         2,
    'draw4':         4,
    'draw6':         6,
    'draw10':       10,
    'reverse_draw4': 4,
}

MERCY_HAND_LIMIT = 25
_NO_MERCY_NUMBER_VALUES = frozenset('0123456789')


def _build_no_mercy_deck() -> list:
    deck = []
    for c in COLORS:
        for v in list('0123456789'):
            deck.append(Card(c, v))
            deck.append(Card(c, v))
        for _ in range(3): deck.append(Card(c, 'skip'))
        for _ in range(2): deck.append(Card(c, 'skip_all'))
        for _ in range(3): deck.append(Card(c, 'reverse'))
        for _ in range(2): deck.append(Card(c, 'draw2'))
        for _ in range(2): deck.append(Card(c, 'draw4'))
        for _ in range(3): deck.append(Card(c, 'discard_all'))
    for _ in range(8): deck.append(Card('wild', 'reverse_draw4'))
    for _ in range(4): deck.append(Card('wild', 'draw6'))
    for _ in range(4): deck.append(Card('wild', 'draw10'))
    for _ in range(8): deck.append(Card('wild', 'color_roulette'))
    random.shuffle(deck)
    return deck


class ShowEmNoMercyGame(UnoGame):

    def __init__(self, players_data: list):
        self.waiting_for_swap_target:    bool         = False
        self.swap_source_idx:            Optional[int] = None
        self.waiting_for_roulette_color: bool         = False
        self.roulette_target_idx:        Optional[int] = None
        self.mercy_pile:                 list         = []
        super().__init__(players_data)

    def build_deck(self) -> list:
        return _build_no_mercy_deck()

    def handle_first_card(self):
        while self.discard and self.discard[-1].value not in _NO_MERCY_NUMBER_VALUES:
            card = self.discard.pop()
            self.deck.insert(random.randint(0, len(self.deck)), card)
            while self.deck:
                nc = self.deck.pop()
                if nc.color != 'wild':
                    self.discard.append(nc)
                    break
                self.deck.insert(0, nc)

    def draw_stack_values(self) -> set:
        return set(NO_MERCY_DRAW_VALUES.keys())

    def _get_draw_value(self, card: Card) -> int:
        return NO_MERCY_DRAW_VALUES.get(card.value, 0)

    def _playable_indices(self, hand: list) -> list:
        top = self.top_card()
        if self.pending_draw > 0:
            return [i for i, c in enumerate(hand)
                    if c.value in self.draw_stack_values()
                    and self._get_draw_value(c) >= self.pending_draw]
        return [i for i, c in enumerate(hand) if self.card_can_play_on(c, top)]

    def apply_effects(self, card: Card) -> Optional[dict]:
        if card.value == 'skip':
            self._advance(); self._advance()
        elif card.value == 'skip_all':
            pass
        elif card.value == 'reverse':
            self.direction *= -1
            if self.active_count() == 2:
                self._advance(); self._advance()
            else:
                self._advance()
        elif card.value == 'draw2':
            self.pending_draw += 2; self._advance()
        elif card.value == 'draw4':
            self.pending_draw += 4; self._advance()
        elif card.value == 'discard_all':
            cur_idx = self.cur_idx()
            player  = self.players[cur_idx]
            discarded = [c for c in player['hand'] if c.color == card.color]
            player['hand'] = [c for c in player['hand'] if c.color != card.color]
            self.discard.extend(discarded)
            win = self._check_win(cur_idx)
            if win:
                return win
            self._advance()
        elif card.value == 'draw6':
            self.pending_draw += 6; self._advance()
        elif card.value == 'draw10':
            self.pending_draw += 10; self._advance()
        elif card.value == 'reverse_draw4':
            self.direction *= -1
            self.pending_draw += 4
            if self.active_count() == 2:
                self._advance(); self._advance()
            else:
                self._advance()
        elif card.value == 'color_roulette':
            self._advance()
            self.waiting_for_roulette_color = True
            self.roulette_target_idx = self.cur_idx()
        elif card.value == '7':
            self.waiting_for_swap_target = True
            self.swap_source_idx = self.cur_idx()
        elif card.value == '0':
            active = [p for p in self.players if not p['finished']]
            if len(active) > 1:
                if self.direction == 1:
                    first = active[0]['hand']
                    for i in range(len(active) - 1):
                        active[i]['hand'] = active[i + 1]['hand']
                    active[-1]['hand'] = first
                else:
                    last = active[-1]['hand']
                    for i in range(len(active) - 1, 0, -1):
                        active[i]['hand'] = active[i - 1]['hand']
                    active[0]['hand'] = last
            self._advance()
            knockouts = self._check_all_mercy()
            if knockouts:
                event = 'game_over' if self.status == 'finished' else 'played'
                return {'event': event, 'mercy_knockouts': knockouts}
        else:
            self._advance()
        return None

    def get_pending_player_action(self) -> Optional[dict]:
        if self.waiting_for_swap_target:
            return {'type': 'swap_target', 'player_idx': self.swap_source_idx}
        if self.waiting_for_roulette_color:
            return {'type': 'roulette_color', 'player_idx': self.roulette_target_idx}
        return None

    def resolve_player_action(self, player_idx: int,
                               action_type: str, data: dict) -> dict:
        if action_type == 'swap_target':
            return self._resolve_swap_target(player_idx, data.get('target_idx', -1))
        if action_type == 'roulette_color':
            return self._resolve_roulette_color(player_idx, data.get('color', ''))
        return {'ok': False, 'error': f'Unknown action: {action_type}'}

    def bot_resolve_pending_action(self, player_idx: int,
                                    player: dict, action_type: str) -> dict:
        if action_type == 'swap_target':
            candidates = [i for i, p in enumerate(self.players)
                          if i != player_idx and not p['finished']]
            if not candidates:
                return {'target_idx': -1}
            if player.get('difficulty') == 'hard':
                target = max(candidates, key=lambda i: len(self.players[i]['hand']))
            else:
                target = random.choice(candidates)
            return {'target_idx': target}
        if action_type == 'roulette_color':
            return {'color': self.bot_pick_color(player['hand'])}
        return {}

    def _resolve_swap_target(self, source_idx: int, target_idx: int) -> dict:
        if not self.waiting_for_swap_target:
            return {'ok': False, 'error': 'No swap active.'}
        if source_idx != self.swap_source_idx:
            return {'ok': False, 'error': 'Not your choice.'}
        self.waiting_for_swap_target = False
        self.swap_source_idx = None
        if (target_idx < 0 or target_idx >= len(self.players)
                or target_idx == source_idx
                or self.players[target_idx]['finished']):
            self._advance()
            return {'ok': True, 'event': 'played',
                    'source_username': self.players[source_idx]['username'],
                    'target_username': None}
        src, tgt = self.players[source_idx], self.players[target_idx]
        src['hand'], tgt['hand'] = tgt['hand'], src['hand']
        self._advance()
        return {'ok': True, 'event': 'played',
                'source_username': src['username'],
                'target_username': tgt['username']}

    def _resolve_roulette_color(self, player_all_idx: int, color: str) -> dict:
        if not self.waiting_for_roulette_color:
            return {'ok': False, 'error': 'No roulette active.'}
        if player_all_idx != self.roulette_target_idx:
            return {'ok': False, 'error': 'Not your choice.'}
        if color not in COLORS:
            self.waiting_for_roulette_color = False
            self.roulette_target_idx = None
            self._advance()
            return {'ok': True, 'event': 'played', 'drawn': [], 'count': 0, 'mercy': None}
        top = self.top_card()
        if top and top.value == 'color_roulette':
            top.chosen_color = color
        drawn = []
        while True:
            self._refill()
            if not self.deck:
                break
            card = self.deck.pop()
            drawn.append(card)
            if card.color == color:
                break
        self.players[player_all_idx]['hand'].extend(drawn)
        self.waiting_for_roulette_color = False
        self.roulette_target_idx = None
        mercy = self._check_mercy(player_all_idx)
        self._advance()
        return {'ok': True, 'event': 'played',
                'drawn': [c.to_dict() for c in drawn],
                'count': len(drawn), 'mercy': mercy}

    def draw_action(self, player_all_idx: int) -> dict:
        if player_all_idx != self.cur_idx():
            return {'ok': False, 'error': 'Not your turn.'}
        if self.must_play_drawn:
            return {'ok': False, 'error': 'You must play the card you just drew.'}
        if self.pending_draw > 0:
            count = self.pending_draw
            drawn = self._draw_n(count)
            self.players[player_all_idx]['hand'].extend(drawn)
            self.pending_draw = 0
            mercy = self._check_mercy(player_all_idx)
            self._advance()
            return {'ok': True, 'drawn': [c.to_dict() for c in drawn],
                    'count': count, 'found_playable': False, 'mercy': mercy}
        top   = self.top_card()
        drawn = []
        found = False
        while True:
            self._refill()
            if not self.deck:
                break
            card = self.deck.pop()
            drawn.append(card)
            self.players[player_all_idx]['hand'].append(card)
            if self.card_can_play_on(card, top):
                found = True
                break
        mercy = self._check_mercy(player_all_idx)
        if mercy and mercy.get('knocked_out'):
            found = False
        if not found:
            self._advance()
        else:
            self.must_play_drawn = True
        return {'ok': True, 'drawn': [c.to_dict() for c in drawn],
                'count': len(drawn), 'found_playable': found, 'mercy': mercy}

    def _check_mercy(self, player_idx: int) -> Optional[dict]:
        player = self.players[player_idx]
        if player['finished'] or len(player['hand']) < MERCY_HAND_LIMIT:
            return None
        player['mercy_knocked'] = True
        player['rank'] = 'knocked_out'
        self.mercy_pile.extend(player['hand'])
        player['hand']     = []
        player['finished'] = True
        remaining = self.active_count()
        if remaining <= 1:
            for p in self.players:
                if not p['finished']:
                    self.winner_rank += 1
                    p['finished'] = True
                    p['rank']     = self.winner_rank
            self.status = 'finished'
        return {'knocked_out': True, 'username': player['username']}

    def _check_all_mercy(self) -> list:
        knockouts = []
        for i in range(len(self.players)):
            m = self._check_mercy(i)
            if m:
                knockouts.append(m)
        return knockouts

    def _refill(self):
        if len(self.deck) < 4 and len(self.discard) > 1:
            top = self.discard.pop()
            for c in self.discard:
                c.reset()
            all_back = self.discard + self.mercy_pile
            for c in self.mercy_pile:
                c.reset()
            random.shuffle(all_back)
            self.deck.extend(all_back)
            self.discard    = [top]
            self.mercy_pile = []

    def bot_pick_card(self, hand: list, top: Card,
                      difficulty: str, pending_draw: int) -> Optional[int]:
        playable = self._playable_indices(hand)
        if not playable:
            return None
        if difficulty == 'easy':
            return random.choice(playable)

        def score(idx: int) -> int:
            c = hand[idx]
            if c.value == 'draw10':         return 15
            if c.value == 'color_roulette': return 14
            if c.value == 'discard_all':    return 13
            if c.value == 'draw6':          return 12
            if c.value == 'reverse_draw4':  return 11
            if c.value == 'draw4':          return 10
            if c.value == 'skip_all':       return 9
            if c.value == 'draw2':          return 8
            if c.value == 'skip':           return 7
            if c.value == 'reverse':        return 6
            if c.value == '7' and difficulty == 'hard': return 10
            if c.value.isdigit():           return int(c.value)
            return 1

        return max(playable, key=score)

    def extra_snapshot_fields(self) -> dict:
        base = super().extra_snapshot_fields()
        base.update({
            'draw_values':                NO_MERCY_DRAW_VALUES,
            'waiting_for_swap_target':    self.waiting_for_swap_target,
            'swap_source_idx':            self.swap_source_idx,
            'waiting_for_roulette_color': self.waiting_for_roulette_color,
            'roulette_target_idx':        self.roulette_target_idx,
            'mercy_limit':                MERCY_HAND_LIMIT,
            'pending_action':             self.get_pending_player_action(),
            'must_play_drawn':            self.must_play_drawn,
        })
        return base

    def card_descriptions(self) -> dict:
        return {
            'skip':          'Next player loses their turn.',
            'skip_all':      'Everyone else is skipped — you get another turn.',
            'reverse':       'Reverses the direction of play.',
            'draw2':         'Next player draws 2 cards and loses their turn.',
            'draw4':         'Next player draws 4 cards and loses their turn.',
            'discard_all':   "Discard all cards in your hand that match this card's colour.",
            'reverse_draw4': 'Reverse direction AND next player draws 4. In 2-player, YOU draw 4.',
            'draw6':         'Change colour. Next player draws 6 cards and loses their turn.',
            'draw10':        'Change colour. Next player draws 10 cards and loses their turn.',
            'color_roulette':'Change colour. Next player picks a colour, then draws until they get it.',
            '7':             'Swap your entire hand with any other player of your choice.',
            '0':             'All players pass their hand to the next player in the current direction.',
        }

    def rules_html(self) -> list:
        return [
            'Match the top card by colour or number.',
            'If you have no playable card, draw cards until you get one you can play.',
            'Stacking: when a draw card targets you, play one of equal or greater value to pass it on.',
            'Mercy Rule: if you reach 25 cards you are knocked out. Your cards return to the deck.',
            'Playing a 7 lets you swap your hand with any other player.',
            'Playing a 0 rotates every hand in the direction of play.',
            'Skip All: you get an extra turn — everyone else is skipped.',
            'Discard All: discard every card in your hand matching this card\'s colour.',
            'Wild Color Roulette: next player picks a colour, then draws until they pull that colour.',
            'First player to empty their hand wins. Last player standing also wins (mercy rule).',
        ]


# ═══════════════════════════════════════════════════════════════════════════════
#  UNO Attack!
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Key differences from Classic
#  ─────────────────────────────
#  Deck         – 1-9 per colour (no 0), Hit 2, Discard All, Trade Hands,
#                 Wild, Wild All-Hit, Wild Hit-Fire (112 cards total)
#  Drawing      – press the Launcher instead of drawing from a pile;
#                 launcher fires 0 or 1-8 cards randomly (~50/50)
#  Hit 2        – next player MUST press launcher twice (no stacking)
#  Wild All-Hit – each OTHER player presses launcher once; human players
#                 press their own button, bots auto-resolve immediately
#  Wild Hit-Fire– next player keeps pressing until launcher fires (guaranteed
#                 to receive at least some cards)
#  Trade Hands  – trade your whole hand with a player of your choice;
#                 cannot go out on this card
#  No stacking  – draw cards are not stackable

def _build_attack_deck() -> list:
    deck = []
    for c in COLORS:
        for v in ['1','2','3','4','5','6','7','8','9']:
            deck.append(Card(c, v))
            deck.append(Card(c, v))
        for _ in range(2): deck.append(Card(c, 'hit2'))
        for _ in range(2): deck.append(Card(c, 'reverse'))
        for _ in range(2): deck.append(Card(c, 'skip'))
        deck.append(Card(c, 'discard_all'))
        deck.append(Card(c, 'trade_hands'))
    for _ in range(4): deck.append(Card('wild', 'wild'))
    for _ in range(2): deck.append(Card('wild', 'wild_all_hit'))
    for _ in range(2): deck.append(Card('wild', 'wild_hit_fire'))
    random.shuffle(deck)
    return deck


# How the launcher fires: ~50 % chance of nothing, otherwise 1-8 cards
# (heavily weighted toward 1-3 for dramatic tension without being oppressive).
_ATTACK_LAUNCH_WEIGHTS = [35, 28, 18, 10, 5, 2, 1, 1]


class AttackUnoGame(UnoGame):
    """
    UNO Attack! — launcher-based card drawing instead of a draw pile.
    """

    def __init__(self, players_data: list):
        # pending_hits   – forced launcher presses the current player owes (from Hit 2)
        # all_hit_queue  – human player indices still waiting to press for Wild All-Hit
        # hit_fire_target– player index that must press-until-fire (Wild Hit-Fire)
        # trade_source   – player index waiting to choose a trade partner
        # last_launch    – info sent to the frontend to drive the launch animation
        self.pending_hits:       int          = 0
        self.all_hit_queue:      list         = []
        self.hit_fire_target:    Optional[int] = None
        self.trade_source:       Optional[int] = None
        self.last_launch:        dict         = {}
        self._launch_seq:        int          = 0
        super().__init__(players_data)

    # ── Core hooks ────────────────────────────────────────────────────────────

    def build_deck(self) -> list:
        return _build_attack_deck()

    def draw_stack_values(self) -> set:
        return set()   # no stacking in UNO Attack

    def handle_first_card(self):
        """
        Special first-card rules for UNO Attack (see rulebook).
        Trade Hands → put it back, draw again.
        """
        top = self.top_card()
        if not top:
            return
        if top.value == 'trade_hands':
            card = self.discard.pop()
            self.deck.insert(random.randint(0, len(self.deck)), card)
            while self.deck:
                nc = self.deck.pop()
                if nc.color != 'wild':
                    self.discard.append(nc)
                    break
                self.deck.insert(0, nc)
            top = self.top_card()
            if not top:
                return

        if top.value == 'reverse':
            self.direction = -1
            if self.active_count() == 2:
                self._advance()
        elif top.value == 'skip':
            self._advance()
            self._advance()
        elif top.value == 'hit2':
            self.pending_hits = 2
        elif top.value == 'wild_all_hit':
            # Each player starting from the left of dealer presses once.
            # We model this as: set up the queue (dealer is player at turn_pos 0
            # before any advance, so all players are in the queue).
            self._setup_all_hit_queue(exclude_idx=None)
        elif top.value == 'wild_hit_fire':
            # Player to the left of dealer presses until fire.
            target = self.turn_order[self.turn_pos]
            player = self.players[target]
            if player.get('is_bot'):
                drawn = self._launch_until_fire()
                player['hand'].extend(drawn)
                self.last_launch = {
                    'seq':      getattr(self, '_launch_seq', 0) + 1,
                    'username': player['username'],
                    'count':    len(drawn),
                    'fired':    True,
                    'type':     'hit_fire',
                }
                self._launch_seq = self.last_launch['seq']
                self._advance()
            else:
                self.hit_fire_target = target

    # ── Launcher simulation ───────────────────────────────────────────────────

    def _single_launch(self) -> list:
        """One button press: ~50% chance nothing fires, otherwise 1-8 cards."""
        if random.random() < 0.5:
            return []
        count = random.choices(range(1, 9), weights=_ATTACK_LAUNCH_WEIGHTS)[0]
        return self._draw_n(count)

    def _launch_until_fire(self) -> list:
        """Keep pressing until at least one card fires (max 20 presses safety cap)."""
        total = []
        for _ in range(20):
            batch = self._single_launch()
            total.extend(batch)
            if batch:
                break
        return total

    def _bump_launch_seq(self) -> int:
        self._launch_seq = getattr(self, '_launch_seq', 0) + 1
        return self._launch_seq

    # ── Wild All-Hit helper ───────────────────────────────────────────────────

    def _setup_all_hit_queue(self, exclude_idx: Optional[int]):
        # Start from turn_pos (= player directly left of card player after _advance)
        # so the rules-correct first-presser goes first, not second.
        n     = len(self.players)
        start = self.turn_pos          # was: (self.turn_pos + self.direction) % n

        order = []
        pos   = start
        for _ in range(n):
            idx = self.turn_order[pos]
            if idx != exclude_idx and not self.players[idx]['finished']:
                order.append(idx)
            pos = (pos + self.direction) % n
            if pos < 0:
                pos += n

        # Auto-resolve bots immediately
        for idx in order:
            player = self.players[idx]
            if player.get('is_bot'):
                drawn = self._single_launch()
                player['hand'].extend(drawn)
                self.last_launch = {
                    'seq':      self._bump_launch_seq(),   # was: getattr(…, 0) + 1
                    'username': player['username'],
                    'count':    len(drawn),
                    'fired':    bool(drawn),
                    'type':     'all_hit',
                }
            else:
                self.all_hit_queue.append(idx)


    # ── apply_effects ─────────────────────────────────────────────────────────

    def apply_effects(self, card: Card) -> Optional[dict]:
        played_by = self.cur_idx()  # the player who just played (pre-advance)

        if card.value == 'reverse':
            self.direction *= -1
            if self.active_count() == 2:
                self._advance(); self._advance()
            else:
                self._advance()

        elif card.value == 'skip':
            self._advance(); self._advance()

        elif card.value == 'hit2':
            # Advance to next player; they owe 2 launcher presses
            self._advance()
            self.pending_hits = 2

        elif card.value == 'discard_all':
            player = self.players[played_by]
            discarded = [c for c in player['hand'] if c.color == card.color]
            player['hand'] = [c for c in player['hand'] if c.color != card.color]
            self.discard.extend(discarded)
            win = self._check_win(played_by)
            if win:
                return win
            self._advance()

        elif card.value == 'trade_hands':
            # Must trade; cannot win on this card (checked in play_card override)
            self.trade_source = played_by
            # Don't advance yet — wait for resolve_player_action

        elif card.value in ('wild', 'wild4'):
            self._advance()

        elif card.value == 'wild_all_hit':
            # Advance first so the next player is the starting point of the queue
            self._advance()
            self._setup_all_hit_queue(exclude_idx=played_by)
            # If queue is empty (all bots already done), game continues normally

        elif card.value == 'wild_hit_fire':
            # Advance to next player; they must press until fire
            self._advance()
            target = self.cur_idx()
            player = self.players[target]
            if player.get('is_bot'):
                # Auto-resolve for bots immediately
                drawn = self._launch_until_fire()
                player['hand'].extend(drawn)
                self.last_launch = {
                    'seq':      self._bump_launch_seq(),
                    'username': player['username'],
                    'count':    len(drawn),
                    'fired':    True,
                    'type':     'hit_fire',
                }
                self._advance()  # their turn is forfeited
            else:
                self.hit_fire_target = target
                # Don't advance yet — wait for resolve_player_action

        else:
            self._advance()

        return None

    # ── play_card override — block going out on Trade Hands ───────────────────

    def play_card(self, player_all_idx: int, card_hand_idx: int,
                  chosen_color: str = None) -> dict:
        if self.pending_hits > 0:
            return {'ok': False,
                    'error': f'You must press the launcher {self.pending_hits} time(s) first.'}
        p = self.players[player_all_idx]
        hand = p['hand']
        if (0 <= card_hand_idx < len(hand)
                and hand[card_hand_idx].value == 'trade_hands'
                and len(hand) == 1):
            return {'ok': False,
                    'error': 'You cannot go out on a Trade Hands card.'}
        return super().play_card(player_all_idx, card_hand_idx, chosen_color)

    # ── draw_action = press the launcher ──────────────────────────────────────

    def draw_action(self, player_all_idx: int) -> dict:
        if player_all_idx != self.cur_idx():
            return {'ok': False, 'error': 'Not your turn.'}

        if self.pending_hits > 0:
            # Forced presses from Hit 2 — press pending_hits times, take all cards
            all_drawn = []
            presses   = self.pending_hits
            for _ in range(presses):
                all_drawn.extend(self._single_launch())
            self.pending_hits = 0
            self.players[player_all_idx]['hand'].extend(all_drawn)
            self.last_launch = {
                'seq':      self._bump_launch_seq(),
                'username': self.players[player_all_idx]['username'],
                'count':    len(all_drawn),
                'fired':    bool(all_drawn),
                'type':     'hit2',
                'presses':  presses,
            }
            self._advance()
            return {'ok': True,
                    'drawn':         [c.to_dict() for c in all_drawn],
                    'count':         len(all_drawn),
                    'found_playable':False,
                    'launched':      True,
                    'fired':         bool(all_drawn)}

        # Normal press — one launch, turn ends regardless
        drawn = self._single_launch()
        self.players[player_all_idx]['hand'].extend(drawn)
        self.last_launch = {
            'seq':      self._bump_launch_seq(),
            'username': self.players[player_all_idx]['username'],
            'count':    len(drawn),
            'fired':    bool(drawn),
            'type':     'press',
        }
        self._advance()
        return {'ok': True,
                'drawn':         [c.to_dict() for c in drawn],
                'count':         len(drawn),
                'found_playable':False,
                'launched':      True,
                'fired':         bool(drawn)}

    # ── Pending player action hooks ───────────────────────────────────────────

    def get_pending_player_action(self) -> Optional[dict]:
        if self.all_hit_queue:
            return {'type': 'all_hit_press', 'player_idx': self.all_hit_queue[0]}
        if self.hit_fire_target is not None:
            return {'type': 'hit_fire_press', 'player_idx': self.hit_fire_target}
        if self.trade_source is not None:
            return {'type': 'trade_hands', 'player_idx': self.trade_source}
        return None

    def resolve_player_action(self, player_idx: int,
                               action_type: str, data: dict) -> dict:
        if action_type == 'all_hit_press':
            return self._resolve_all_hit_press(player_idx)
        if action_type == 'hit_fire_press':
            return self._resolve_hit_fire_press(player_idx)
        if action_type == 'trade_hands':
            return self._resolve_trade_hands(player_idx, data.get('target_idx', -1))
        return {'ok': False, 'error': f'Unknown action: {action_type}'}

    def bot_resolve_pending_action(self, player_idx: int,
                                    player: dict, action_type: str) -> dict:
        if action_type == 'all_hit_press':
            return {}   # no data needed
        if action_type == 'hit_fire_press':
            return {}
        if action_type == 'trade_hands':
            # Hard bots trade with whoever has the most cards;
            # others pick the player closest to winning (fewest cards)
            candidates = [i for i, p in enumerate(self.players)
                          if i != player_idx and not p['finished']]
            if not candidates:
                return {'target_idx': -1}
            if player.get('difficulty') == 'hard':
                target = max(candidates, key=lambda i: len(self.players[i]['hand']))
            else:
                target = min(candidates, key=lambda i: len(self.players[i]['hand']))
            return {'target_idx': target}
        return {}

    # ── Action implementations ────────────────────────────────────────────────

    def _resolve_all_hit_press(self, player_idx: int) -> dict:
        """The player presses once for Wild All-Hit."""
        if not self.all_hit_queue or self.all_hit_queue[0] != player_idx:
            return {'ok': False, 'error': 'Not your press.'}
        self.all_hit_queue.pop(0)
        drawn = self._single_launch()
        self.players[player_idx]['hand'].extend(drawn)
        self.last_launch = {
            'seq':      self._bump_launch_seq(),
            'username': self.players[player_idx]['username'],
            'count':    len(drawn),
            'fired':    bool(drawn),
            'type':     'all_hit',
        }
        # Game continues normally once all presses are done (no advance here —
        # cur_idx is already the next player after the Wild All-Hit was played)
        return {'ok': True, 'event': 'played',
                'drawn':   [c.to_dict() for c in drawn],
                'count':   len(drawn),
                'fired':   bool(drawn),
                'launched': True}

    def _resolve_hit_fire_press(self, player_idx: int) -> dict:
        """The targeted player presses until the launcher fires."""
        if self.hit_fire_target != player_idx:
            return {'ok': False, 'error': 'Not your press.'}
        drawn = self._launch_until_fire()
        self.players[player_idx]['hand'].extend(drawn)
        self.last_launch = {
            'seq':      self._bump_launch_seq(),
            'username': self.players[player_idx]['username'],
            'count':    len(drawn),
            'fired':    True,
            'type':     'hit_fire',
        }
        self.hit_fire_target = None
        self._advance()   # target's turn is forfeited
        return {'ok': True, 'event': 'played',
                'drawn':   [c.to_dict() for c in drawn],
                'count':   len(drawn),
                'fired':   True,
                'launched': True}

    def _resolve_trade_hands(self, source_idx: int, target_idx: int) -> dict:
        """Trade entire hand with chosen player."""
        if self.trade_source != source_idx:
            return {'ok': False, 'error': 'Not your trade.'}
        self.trade_source = None
        if (target_idx < 0 or target_idx >= len(self.players)
                or target_idx == source_idx
                or self.players[target_idx]['finished']):
            # No valid target — skip trade, advance
            self._advance()
            return {'ok': True, 'event': 'played',
                    'source_username': self.players[source_idx]['username'],
                    'target_username': None}
        src, tgt = self.players[source_idx], self.players[target_idx]
        src['hand'], tgt['hand'] = tgt['hand'], src['hand']
        self._advance()
        return {'ok': True, 'event': 'played',
                'source_username': src['username'],
                'target_username': tgt['username']}

    # ── Bot AI ────────────────────────────────────────────────────────────────

    def bot_pick_card(self, hand: list, top: Card,
                      difficulty: str, pending_draw: int) -> Optional[int]:
        if self.pending_hits > 0:
            return None   # must press launcher

        playable = [i for i, c in enumerate(hand)
                    if self.card_can_play_on(c, top)]
        if not playable:
            return None
        if difficulty == 'easy':
            return random.choice(playable)

        def score(idx: int) -> int:
            c = hand[idx]
            if c.value == 'wild_hit_fire': return 12
            if c.value == 'wild_all_hit':  return 11
            if c.value == 'wild':          return 10
            if c.value == 'hit2':          return 9
            if c.value == 'skip':          return 8
            if c.value == 'reverse':       return 7
            if c.value == 'discard_all':   return 6
            if c.value == 'trade_hands':
                # Only play if we have many cards
                return 5 if len(hand) > 5 else 1
            if c.value.isdigit():          return int(c.value)
            return 1

        return max(playable, key=score)

    # ── Extra snapshot fields ─────────────────────────────────────────────────

    def extra_snapshot_fields(self) -> dict:
        base = super().extra_snapshot_fields()
        base.update({
            'pending_action':    self.get_pending_player_action(),
            'pending_hits':      self.pending_hits,
            'all_hit_queue':     list(self.all_hit_queue),
            'last_launch':       dict(self.last_launch),
            'launcher_active':   bool(self.pending_hits or self.all_hit_queue
                                      or self.hit_fire_target is not None),
        })
        return base

    def card_descriptions(self) -> dict:
        return {
            'skip':          'Next player loses their turn.',
            'reverse':       'Reverses the direction of play.',
            'hit2':          'Next player must press the Launcher twice and take any cards that fly out.',
            'discard_all':   "Discard all cards in your hand that match this card's colour.",
            'trade_hands':   'Trade your entire hand with a player of your choice. Cannot go out on this card.',
            'wild':          'Change the colour of play to any colour.',
            'wild_all_hit':  'Change colour. Every OTHER player must press the Launcher once.',
            'wild_hit_fire': 'Change colour. The next player keeps pressing until the Launcher fires.',
        }

    def rules_html(self) -> list:
        return [
            'Match the top card by colour, number, or action.',
            'If you have no playable card, press the Launcher. If it fires, take the cards. Either way your turn ends.',
            'You may also choose NOT to play a card and press the Launcher instead (reneging).',
            'Hit 2: the next player must press the Launcher twice, taking any cards that come out.',
            'Wild All-Hit: name a colour, then every OTHER player must press the Launcher once.',
            'Wild Hit-Fire: name a colour, then the next player keeps pressing until the Launcher fires.',
            'Trade Hands: you MUST swap your whole hand with a player of your choice. You cannot go out on this card.',
            'Discard All: discard every card in your hand that matches this card\'s colour.',
            'No stacking — you cannot play a Hit 2 on top of another Hit 2.',
            'First player to empty their hand wins.',
        ]

# ═══════════════════════════════════════════════════════════════════════════════
#  UNO Flip
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Two-sided deck: Light (red/green/blue/yellow) and Dark (pink/teal/orange/purple).
#  Playing a FLIP card flips every card in every hand, the deck, and the discard.
#
#  Light-side specials  │  Dark-side specials
#  ─────────────────────┼─────────────────────────────────────────────────────
#  Draw One  (+1)       │  Draw Five    (+5)
#  Skip                 │  Skip Everyone  (all others skipped; you play again)
#  Flip                 │  Flip
#  Wild Draw 2  (+2★)   │  Wild Draw Color  (draw until chosen colour)
#
#  Restriction: Wild Draw 2 / Wild Draw Color may only be played when the player
#               has NO card whose colour matches the current discard colour.
#  No stacking.

FLIP_LIGHT_COLORS = ['red',  'green', 'blue',   'yellow']
FLIP_DARK_COLORS  = ['pink', 'teal',  'orange',  'purple']

_FLIP_COLOR_PAIRS = [
    ('red',    'pink'),
    ('green',  'teal'),
    ('blue',   'orange'),
    ('yellow', 'purple'),
]
# Light action value  →  dark action value for the same physical card
_FLIP_ACTION_PAIRS = [
    ('draw_one',  'draw_five'),
    ('reverse',   'reverse'),
    ('skip',      'skip_everyone'),
    ('flip',      'flip'),
]


class FlipCard:
    """
    A double-sided UNO Flip card.
    `color` and `value` always reflect whichever face is currently showing.
    Calling .flip() toggles the face in-place; the object identity is preserved
    so _flip_all_cards() can iterate over the lists without rebuilding them.
    """
    __slots__ = ('_lc', '_lv', '_dc', '_dv', '_dark', 'chosen_color')

    def __init__(self, light_color: str, light_value: str,
                 dark_color: str, dark_value: str, dark: bool = False):
        self._lc        = light_color
        self._lv        = light_value
        self._dc        = dark_color
        self._dv        = dark_value
        self._dark      = dark
        self.chosen_color: Optional[str] = None

    # ── Same public interface as Card ─────────────────────────────────────────

    @property
    def color(self) -> str:
        return self._dc if self._dark else self._lc

    @property
    def value(self) -> str:
        return self._dv if self._dark else self._lv

    def effective_color(self) -> str:
        return self.chosen_color or self.color

    def flip(self):
        self._dark = not self._dark
        self.chosen_color = None   # a chosen colour is side-specific; clear it

    def reset(self):
        self.chosen_color = None   # used by _refill; does NOT flip the card

    def can_play_on_classic(self, top) -> bool:
        return False  # not used; FlipUnoGame overrides card_can_play_on

    def to_dict(self) -> dict:
        return {
            'color':        self.color,
            'value':        self.value,
            'chosen_color': self.chosen_color,
            'dark_side':    self._dark,
        }


def _build_flip_deck() -> list:
    """112 double-sided cards: 4 colour pairs × 26 cards + 4 wild + 4 wild-draw."""
    deck = []
    for lc, dc in _FLIP_COLOR_PAIRS:
        # Numbers 1-9, two of each
        for v in '123456789':
            deck.append(FlipCard(lc, v, dc, v))
            deck.append(FlipCard(lc, v, dc, v))
        # Action pairs, two of each
        for lv, dv in _FLIP_ACTION_PAIRS:
            deck.append(FlipCard(lc, lv, dc, dv))
            deck.append(FlipCard(lc, lv, dc, dv))
    # Wild ↔ Wild  (4×)
    for _ in range(4):
        deck.append(FlipCard('wild', 'wild', 'wild', 'wild'))
    # Wild Draw 2 ↔ Wild Draw Color  (4×)
    for _ in range(4):
        deck.append(FlipCard('wild', 'wild_draw2', 'wild', 'wild_draw_color'))
    random.shuffle(deck)
    return deck


class FlipUnoGame(UnoGame):

    def __init__(self, players_data: list):
        self.dark_side:              bool          = False
        self.wdc_target:             Optional[int] = None   # wild-draw-color target
        self.wdc_color:              Optional[str] = None   # colour they must draw until
        super().__init__(players_data)

    # ── Core hooks ────────────────────────────────────────────────────────────

    def build_deck(self) -> list:
        return _build_flip_deck()

    def draw_stack_values(self) -> set:
        return set()  # No stacking in UNO Flip

    def valid_colors(self) -> list:
        return FLIP_DARK_COLORS if self.dark_side else FLIP_LIGHT_COLORS

    def card_can_play_on(self, card: FlipCard, top: FlipCard) -> bool:
        if card.color == 'wild':
            return True
        tc = top.effective_color()
        if card.color == tc:
            return True
        if card.value == top.value:   # same action or same number across colours
            return True
        return False

    def handle_first_card(self):
        top = self.top_card()
        if not top:
            return
        # Wild Draw 2 is returned to the deck; draw a replacement
        if top.value == 'wild_draw2':
            card = self.discard.pop()
            self.deck.insert(random.randint(0, len(self.deck)), card)
            while self.deck:
                nc = self.deck.pop()
                if nc.value != 'wild_draw2':
                    self.discard.append(nc)
                    break
                self.deck.insert(0, nc)
            top = self.top_card()
            if not top:
                return

        if top.value == 'reverse':
            self.direction = -1
            if self.active_count() == 2:
                self._advance()
        elif top.value == 'skip':
            self._advance()
            self._advance()
        elif top.value == 'draw_one':
            self.pending_draw += 1
        elif top.value == 'wild':
            self.waiting_for_color = True
        elif top.value == 'flip':
            self._flip_all_cards()
        # skip_everyone / draw_five / wild_draw_color are not light-side starting cards
        # under normal rules, but we handle them gracefully by doing nothing special.

    def apply_effects(self, card: FlipCard) -> Optional[dict]:
        if card.value == 'draw_one':
            self.pending_draw += 1
            self._advance()

        elif card.value == 'draw_five':
            self.pending_draw += 5
            self._advance()

        elif card.value == 'reverse':
            self.direction *= -1
            if self.active_count() == 2:
                self._advance()
                self._advance()
            else:
                self._advance()

        elif card.value == 'skip':
            self._advance()
            self._advance()

        elif card.value == 'skip_everyone':
            # All OTHER players are skipped; same player goes again — no advance.
            pass

        elif card.value == 'flip':
            self._flip_all_cards()
            self._advance()

        elif card.value == 'wild':
            self._advance()

        elif card.value == 'wild_draw2':
            self.pending_draw += 2
            self._advance()

        elif card.value == 'wild_draw_color':
            # Advance to the targeted player, then have them draw until the colour.
            self._advance()
            target = self.cur_idx()
            player = self.players[target]
            color  = card.chosen_color or self.valid_colors()[0]
            if player.get('is_bot'):
                # Auto-resolve immediately for bots
                drawn = self._draw_until_color(target, color)
                self._advance()   # forfeit their turn
            else:
                self.wdc_target = target
                self.wdc_color  = color

        else:
            self._advance()

        return None

    # ── Flip mechanic ─────────────────────────────────────────────────────────

    def _flip_all_cards(self):
        """
        Flip every card in the game to its other face, then move the just-played
        Flip card from the top of the discard to the bottom (per rulebook).
        """
        self.dark_side = not self.dark_side
        for p in self.players:
            for c in p['hand']:
                c.flip()
        for c in self.deck:
            c.flip()
        for c in self.discard:
            c.flip()
        # Move the flip card (now at top) to the bottom so the previous card shows
        if len(self.discard) > 1:
            self.discard.insert(0, self.discard.pop())

    # ── Wild Draw Color resolution ────────────────────────────────────────────

    def _draw_until_color(self, player_idx: int, color: str) -> list:
        """Draw cards for player_idx until one matches `color`. Returns drawn cards."""
        drawn = []
        while True:
            self._refill()
            if not self.deck:
                break
            c = self.deck.pop()
            drawn.append(c)
            self.players[player_idx]['hand'].append(c)
            if c.color == color:
                break
        return drawn

    def _resolve_wdc(self, player_idx: int) -> dict:
        color          = self.wdc_color
        self.wdc_target = None
        self.wdc_color  = None
        drawn = self._draw_until_color(player_idx, color)
        self._advance()
        return {'ok': True, 'event': 'played',
                'drawn': [c.to_dict() for c in drawn], 'count': len(drawn)}

    # ── Pending player action hooks ───────────────────────────────────────────

    def get_pending_player_action(self) -> Optional[dict]:
        if self.wdc_target is not None:
            return {'type':       'draw_until_color',
                    'player_idx': self.wdc_target,
                    'color':      self.wdc_color}
        return None

    def resolve_player_action(self, player_idx: int,
                               action_type: str, data: dict) -> dict:
        if action_type == 'draw_until_color':
            if self.wdc_target != player_idx:
                return {'ok': False, 'error': 'Not your draw.'}
            return self._resolve_wdc(player_idx)
        return {'ok': False, 'error': f'Unknown action: {action_type}'}

    def bot_resolve_pending_action(self, player_idx: int,
                                    player: dict, action_type: str) -> dict:
        return {}  # draw_until_color needs no data; resolved via draw_action / resolve

    # ── Public game-action overrides ──────────────────────────────────────────

    def play_card(self, player_all_idx: int, card_hand_idx: int,
                  chosen_color: str = None) -> dict:
        # Block if this player owes a draw-until-color
        if self.wdc_target == player_all_idx:
            return {'ok': False, 'error': 'You must draw cards first.'}

        # Enforce Wild Draw restriction: cannot play if you hold a matching-colour card
        p    = self.players[player_all_idx]
        hand = p['hand']
        if 0 <= card_hand_idx < len(hand):
            card = hand[card_hand_idx]
            top  = self.top_card()
            if card.value in ('wild_draw2', 'wild_draw_color') and top:
                tc = top.effective_color()
                if tc not in ('wild', None):
                    has_match = any(c.color == tc
                                    for i, c in enumerate(hand)
                                    if i != card_hand_idx)
                    if has_match:
                        cname = tc.capitalize()
                        return {'ok': False,
                                'error': f'Wild Draw may only be played when you '
                                         f'hold no {cname} cards.'}
        return super().play_card(player_all_idx, card_hand_idx, chosen_color)

    def draw_action(self, player_all_idx: int) -> dict:
        if player_all_idx != self.cur_idx():
            return {'ok': False, 'error': 'Not your turn.'}

        # Wild Draw Color: draw until the chosen colour
        if self.wdc_target == player_all_idx:
            return self._resolve_wdc(player_all_idx)

        # Forced draw (Draw One, Draw Five, Wild Draw 2)
        if self.pending_draw > 0:
            count = self.pending_draw
            drawn = self._draw_n(count)
            self.players[player_all_idx]['hand'].extend(drawn)
            self.pending_draw = 0
            self._advance()
            return {'ok': True, 'drawn': [c.to_dict() for c in drawn],
                    'count': count, 'found_playable': False}

        # Normal single draw; playable drawn card may be played immediately
        drawn = self._draw_n(1)
        self.players[player_all_idx]['hand'].extend(drawn)
        top = self.top_card()
        if drawn and top and self.card_can_play_on(drawn[0], top):
            self.must_play_drawn = True
            return {'ok': True, 'drawn': [c.to_dict() for c in drawn],
                    'count': 1, 'found_playable': True}
        self._advance()
        return {'ok': True, 'drawn': [c.to_dict() for c in drawn],
                'count': 1, 'found_playable': False}

    # ── Bot hooks ─────────────────────────────────────────────────────────────

    def bot_pick_card(self, hand: list, top: FlipCard,
                      difficulty: str, pending_draw: int) -> Optional[int]:
        # Must draw if wild-draw-colour is waiting for this player
        if self.wdc_target == self.cur_idx():
            return None

        tc         = top.effective_color()
        has_color  = tc not in ('wild', None) and any(
            c.color == tc for c in hand)

        playable = [i for i, c in enumerate(hand)
                    if self.card_can_play_on(c, top)]

        # Enforce Wild Draw restriction for bots too
        if has_color:
            playable = [i for i in playable
                        if hand[i].value not in ('wild_draw2', 'wild_draw_color')]

        if not playable:
            return None
        if difficulty == 'easy':
            return random.choice(playable)

        def score(idx: int) -> int:
            c = hand[idx]
            if c.value == 'wild_draw_color': return 14
            if c.value == 'wild_draw2':      return 13
            if c.value == 'wild':            return 12
            if c.value == 'draw_five':       return 11
            if c.value == 'skip_everyone':   return 10
            if c.value == 'draw_one':        return 9
            if c.value == 'skip':            return 8
            if c.value == 'reverse':         return 7
            # Flip: on hard, play flip when on dark side (penalising opponents)
            if c.value == 'flip':
                return 6 if (difficulty == 'hard' and self.dark_side) else 3
            if c.value.isdigit():            return int(c.value)
            return 1

        return max(playable, key=score)

    def bot_pick_color(self, hand: list) -> str:
        available = self.valid_colors()
        counts    = {c: 0 for c in available}
        for card in hand:
            if card.color in counts:
                counts[card.color] += 1
        return max(counts, key=counts.get)

    # ── Snapshot / meta hooks ─────────────────────────────────────────────────

    def extra_snapshot_fields(self) -> dict:
        base = super().extra_snapshot_fields()
        base.update({
            'dark_side':      self.dark_side,
            'current_colors': self.valid_colors(),
            'pending_action': self.get_pending_player_action(),
        })
        return base

    def card_descriptions(self) -> dict:
        return {
            'draw_one':        'Light Side — next player draws 1 card and loses their turn.',
            'draw_five':       'Dark Side — next player draws 5 cards and loses their turn.',
            'reverse':         'Reverses the direction of play.',
            'skip':            'Light Side — next player loses their turn.',
            'skip_everyone':   'Dark Side — ALL other players are skipped; you play again immediately.',
            'flip':            'Flips the entire game between the Light Side and the Dark Side!',
            'wild':            'Choose any colour to continue play.',
            'wild_draw2':      'Light Side — choose colour; next player draws 2 and loses their turn. Only playable when you hold no matching-colour cards.',
            'wild_draw_color': 'Dark Side — choose colour; next player draws cards until they pull that colour, then loses their turn. Only playable when you hold no matching-colour cards.',
        }

    def rules_html(self) -> list:
        return [
            'Starts on the Light Side (red/green/blue/yellow) — plays like Classic UNO.',
            'When a FLIP card is played, every hand, the deck, and the discard flip to their other face.',
            'Dark Side colours: pink, teal, orange, purple — with much harsher penalties.',
            'Draw One (Light): next player draws 1 card and loses their turn.',
            'Draw Five (Dark): next player draws 5 cards and loses their turn.',
            'Skip (Light): next player loses their turn.',
            'Skip Everyone (Dark): ALL other players are skipped; the card player goes again.',
            'Wild Draw 2 (Light): choose colour; next player draws 2, loses turn. Requires no matching-colour card in hand.',
            'Wild Draw Color (Dark): choose colour; next player draws until they get that colour, loses turn. Same restriction as Wild Draw 2.',
            'No stacking — you cannot play a draw card to pass the penalty on.',
            'If you cannot play, draw 1 card. If it is playable you may play it immediately.',
            'Shout "UNO!" when you are down to one card.',
        ]


# ═══════════════════════════════════════════════════════════════════════════════
#  UNO All Wild
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Every card is a Wild — no colour or number matching required.
#  Any card may be played on any other card at any time.
#
#  Card counts (112 total):
#    54 Wild  ·  14 Wild Reverse  ·  14 Wild Skip  ·  10 Wild Draw 2
#     6 Wild Draw 4  ·  6 Wild Double Skip
#     4 Wild Targeted Draw 2  ·  4 Wild Forced Swap

def _build_all_wild_deck() -> list:
    counts = [
        ('wild',     54),
        ('w_reverse', 14),
        ('w_skip',    14),
        ('w_draw2',   10),
        ('w_draw4',    6),
        ('w_dskip',    6),
        ('w_tdraw2',   4),
        ('w_fswap',    4),
    ]
    deck = [Card('wild', v) for v, n in counts for _ in range(n)]
    random.shuffle(deck)
    return deck


class AllWildUnoGame(UnoGame):
    """
    UNO All Wild — every card is a Wild, no matching required.
    Two unique cards require the player to choose a target:
      w_tdraw2  – targeted draw 2 (target draws 2, keeps their turn)
      w_fswap   – forced swap    (swap hands with chosen player)
    """
    
    def _first_card_ok(self, card: Card) -> bool:
        return True   # every card is a wild, so any card is fine as the opener


    def __init__(self, players_data: list):
        self._aw_pending_type: Optional[str] = None
        self._aw_source_idx:   Optional[int] = None
        super().__init__(players_data)

    # ── Core hooks ────────────────────────────────────────────────────────────

    def build_deck(self) -> list:
        return _build_all_wild_deck()

    def draw_stack_values(self) -> set:
        return set()   # no stacking in All Wild

    def card_can_play_on(self, card: Card, top: Card) -> bool:
        return True    # any card plays on any card

    def handle_first_card(self):
        # Per official rules: if the first flipped card is a Wild Action card,
        # ignore its action entirely — just start play normally.
        pass

    def play_card(self, player_all_idx: int, card_hand_idx: int,
                  chosen_color: str = None) -> dict:
        # Colours are irrelevant in All Wild — inject a dummy chosen_color so
        # the base class never pauses waiting for colour input.
        return super().play_card(player_all_idx, card_hand_idx, chosen_color or 'red')

    def apply_effects(self, card: Card) -> Optional[dict]:
        if card.value == 'wild':
            self._advance()

        elif card.value == 'w_reverse':
            self.direction *= -1
            if self.active_count() == 2:
                self._advance(); self._advance()   # acts like skip in 2-player
            else:
                self._advance()

        elif card.value == 'w_skip':
            self._advance(); self._advance()       # skip 1 player

        elif card.value == 'w_dskip':
            if self.active_count() == 2:
                # "Opponent misses 2 turns" = you play 3 times total.
                # 4 advances with 2 active players toggles back to self twice.
                for _ in range(4): self._advance()
            else:
                for _ in range(3): self._advance() # skip 2 players

        elif card.value == 'w_draw2':
            self.pending_draw += 2
            self._advance()

        elif card.value == 'w_draw4':
            self.pending_draw += 4
            self._advance()

        elif card.value == 'w_tdraw2':
            # Source player must choose a target; do NOT advance yet.
            self._aw_pending_type = 'targeted_draw2'
            self._aw_source_idx   = self.cur_idx()

        elif card.value == 'w_fswap':
            # Source player must choose a target; do NOT advance yet.
            self._aw_pending_type = 'forced_swap'
            self._aw_source_idx   = self.cur_idx()

        else:
            self._advance()

        return None

    # ── Pending player action hooks ───────────────────────────────────────────

    def get_pending_player_action(self) -> Optional[dict]:
        if self._aw_pending_type is not None:
            return {'type': self._aw_pending_type, 'player_idx': self._aw_source_idx}
        return None

    def resolve_player_action(self, player_idx: int,
                               action_type: str, data: dict) -> dict:
        if action_type == 'targeted_draw2':
            return self._resolve_targeted_draw2(player_idx, data.get('target_idx', -1))
        if action_type == 'forced_swap':
            return self._resolve_forced_swap(player_idx, data.get('target_idx', -1))
        return {'ok': False, 'error': f'Unknown action: {action_type}'}

    def _resolve_targeted_draw2(self, source_idx: int, target_idx: int) -> dict:
        if self._aw_source_idx != source_idx:
            return {'ok': False, 'error': 'Not your choice.'}
        self._aw_pending_type = None
        self._aw_source_idx   = None
        target_username = None
        if (0 <= target_idx < len(self.players)
                and target_idx != source_idx
                and not self.players[target_idx]['finished']):
            drawn = self._draw_n(2)
            self.players[target_idx]['hand'].extend(drawn)
            target_username = self.players[target_idx]['username']
        self._advance()
        return {'ok': True, 'event': 'played',
                'source_username': self.players[source_idx]['username'],
                'target_username': target_username}

    def _resolve_forced_swap(self, source_idx: int, target_idx: int) -> dict:
        if self._aw_source_idx != source_idx:
            return {'ok': False, 'error': 'Not your choice.'}
        self._aw_pending_type = None
        self._aw_source_idx   = None
        target_username = None
        if (0 <= target_idx < len(self.players)
                and target_idx != source_idx
                and not self.players[target_idx]['finished']):
            src, tgt            = self.players[source_idx], self.players[target_idx]
            src['hand'], tgt['hand'] = tgt['hand'], src['hand']
            target_username     = tgt['username']
        self._advance()
        return {'ok': True, 'event': 'played',
                'source_username': self.players[source_idx]['username'],
                'target_username': target_username}

    # ── Bot hooks ─────────────────────────────────────────────────────────────

    def bot_resolve_pending_action(self, player_idx: int,
                                    player: dict, action_type: str) -> dict:
        candidates = [i for i, p in enumerate(self.players)
                      if i != player_idx and not p['finished']]
        if not candidates:
            return {'target_idx': -1}
        diff = player.get('difficulty', 'medium')
        if action_type == 'targeted_draw2':
            # Hard: target the player closest to winning (fewest cards)
            target = (min(candidates, key=lambda i: len(self.players[i]['hand']))
                      if diff == 'hard' else random.choice(candidates))
        elif action_type == 'forced_swap':
            # Hard: swap with whoever has the fewest cards (if better than us)
            our_count = len(self.players[player_idx]['hand'])
            best      = min(candidates, key=lambda i: len(self.players[i]['hand']))
            target    = (best
                         if diff == 'hard' and len(self.players[best]['hand']) < our_count
                         else random.choice(candidates))
        else:
            return {}
        return {'target_idx': target}

    def bot_pick_card(self, hand: list, top: Card,
                      difficulty: str, pending_draw: int) -> Optional[int]:
        if pending_draw > 0 or not hand:
            return None   # must draw (no stacking)
        if difficulty == 'easy':
            return random.randint(0, len(hand) - 1)

        n = len(hand)
        def score(idx: int) -> int:
            v = hand[idx].value
            if v == 'w_fswap':   return 10 if n > 5 else 1
            if v == 'w_draw4':   return 9
            if v == 'w_tdraw2':  return 8
            if v == 'w_dskip':   return 7
            if v == 'w_draw2':   return 6
            if v == 'w_skip':    return 5
            if v == 'w_reverse': return 3
            return 2   # plain wild

        return max(range(n), key=score)

    def bot_pick_color(self, hand: list) -> str:
        return 'red'   # irrelevant but base method requires a return

    # ── Snapshot / meta hooks ─────────────────────────────────────────────────

    def extra_snapshot_fields(self) -> dict:
        base = super().extra_snapshot_fields()
        base.update({'pending_action': self.get_pending_player_action()})
        return base

    def card_descriptions(self) -> dict:
        return {
            'wild':     'No action — just a standard card. Play at any time.',
            'w_reverse':'Reverses the direction of play.',
            'w_skip':   'Next player misses their turn.',
            'w_dskip':  'The next 2 players miss their turns. In 2-player, your opponent misses 2 turns in a row.',
            'w_draw2':  'Next player draws 2 cards and loses their turn.',
            'w_draw4':  'Next player draws 4 cards and loses their turn.',
            'w_tdraw2': 'Choose any player — they draw 2 cards, but do NOT lose their turn.',
            'w_fswap':  'You MUST choose a player to swap your entire hand with.',
        }

    def rules_html(self) -> list:
        return [
            'Every card is a Wild — any card can be played on any other card, no matching needed!',
            'On your turn, simply play any card from your hand.',
            'You may also choose not to play — press Draw to take 1 card and end your turn.',
            'Wild Draw 2: the next player draws 2 cards and loses their turn.',
            'Wild Draw 4: the next player draws 4 cards and loses their turn.',
            'Wild Targeted Draw 2: choose ANY player (not just the next) — they draw 2 cards but keep their turn.',
            'Wild Double Skip: the next 2 players miss their turns. With 2 players, opponent misses 2 turns in a row.',
            'Wild Forced Swap: you MUST choose a player to swap hands with.',
            'Wild Reverse: reverses the direction of play.',
            'Wild Skip: the next player misses their turn.',
            'Shout "UNO!" when you are down to one card.',
            'First player to empty their hand wins.',
        ]

# ── UNO_TYPES registry ────────────────────────────────────────────────────────

UNO_TYPES['classic'] = {
    'name':        'UNO Classic',
    'min_players': 2,
    'max_players': 10,
    'description': 'Standard UNO rules — first to empty hand wins.',
    'game_class':  ClassicUnoGame,
}

UNO_TYPES['no_mercy'] = {
    'name':        "UNO Show 'Em No Mercy",
    'min_players': 2,
    'max_players': 6,
    'description': ('Brutal UNO: stacking draws, mercy knockout at 25 cards, '
                    'hand swaps, rotations, and devastating wild cards.'),
    'game_class':  ShowEmNoMercyGame,
}

UNO_TYPES['attack'] = {
    'name':        'UNO Attack!',
    'min_players': 2,
    'max_players': 10,
    'description': ('Press the Launcher instead of drawing! '
                    'The launcher randomly fires 0-8 cards — or nothing at all.'),
    'game_class':  AttackUnoGame,
}

UNO_TYPES['flip'] = {
    'name':        'UNO Flip',
    'min_players': 2,
    'max_players': 10,
    'description': ('Two-sided deck — play flips between the gentle Light Side and the '
                    'brutal Dark Side whenever a Flip card is played.'),
    'game_class':  FlipUnoGame,
}

UNO_TYPES['all_wild'] = {
    'name':        'UNO All Wild',
    'min_players': 2,
    'max_players': 10,
    'description': 'Every card is a Wild — no matching needed! Just play any card you want.',
    'game_class':  AllWildUnoGame,
}


# ── Compatibility shims ───────────────────────────────────────────────────────

def bot_choose_card(hand, top, difficulty, pending_draw=0):
    return _classic_bot_pick_card(hand, top, difficulty, pending_draw)

def bot_choose_color(hand):
    return _classic_bot_pick_color(hand)