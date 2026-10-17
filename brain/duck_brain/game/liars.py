"""Liar's Duck: the rules of the bluffing card game (no I/O, easy to test).

Classic "Cheat", tuned to be quick: everyone gets a few cards, the required rank
climbs A, 2, 3 ... K, and each turn a player lays 1-4 cards face down claiming
they're all that rank. Anyone else may call QUACK! during the challenge window.
If any card isn't the claimed rank, the liar picks up the pile; if they were all
honest, the caller does. First to empty their hand (and survive a challenge on
that last play) wins.
"""

from __future__ import annotations

import random
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
RANK_NAMES = {"A": "ace", "J": "jack", "Q": "queen", "K": "king"}
SUITS = ["♠", "♥", "♦", "♣"]

POINTS = {"win": 5, "good_call": 2, "got_away": 1, "bad_call": -1}


def rank_word(rank: str, n: int = 1) -> str:
    word = RANK_NAMES.get(rank, rank)
    if n == 1:
        return f"one {word}"
    nums = {2: "two", 3: "three", 4: "four"}
    return f"{nums.get(n, n)} {word}{'es' if word == 'six' else 's'}"


@dataclass
class Card:
    id: int
    rank: str
    suit: str

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "rank": self.rank, "suit": self.suit}


@dataclass
class Player:
    id: str
    name: str
    token: str
    hand: list[Card] = field(default_factory=list)
    score: int = 0
    connected: bool = True


@dataclass
class Play:
    player_id: str
    cards: list[Card]
    rank: str
    at: float

    @property
    def honest(self) -> bool:
        return all(c.rank == self.rank for c in self.cards)


class GameError(ValueError):
    pass


class LiarsGame:
    """State machine: lobby -> turn -> challenge -> (reveal) -> turn ... -> over."""

    def __init__(self, hand_size: int = 7, challenge_s: float = 6.0, rng: Optional[random.Random] = None) -> None:
        self.hand_size = hand_size
        self.challenge_s = challenge_s
        self.rng = rng or random.Random()
        self.players: dict[str, Player] = {}
        self.order: list[str] = []
        self.phase = "lobby"
        self.turn_idx = 0
        self.rank_idx = 0
        self.pile: list[Card] = []
        self.last_play: Optional[Play] = None
        self.challenge_until = 0.0
        self.winner: Optional[str] = None
        self.round = 0

    # ------------------------------------------------------------ players

    def join(self, name: str) -> Player:
        name = " ".join(name.split())[:16] or "Duckling"
        taken = {p.name.lower() for p in self.players.values()}
        base, n = name, 2
        while name.lower() in taken:
            name, n = f"{base} {n}", n + 1
        if len(self.players) >= 8:
            raise GameError("table is full (8 players)")
        p = Player(id=secrets.token_hex(4), name=name, token=secrets.token_hex(12))
        self.players[p.id] = p
        if self.phase != "lobby":
            self.order.append(p.id)  # joins next round with an empty hand
        return p

    def by_token(self, token: str) -> Optional[Player]:
        return next((p for p in self.players.values() if p.token == token), None)

    def remove(self, player_id: str) -> None:
        p = self.players.pop(player_id, None)
        if p is None:
            return
        if player_id in self.order:
            idx = self.order.index(player_id)
            self.order.remove(player_id)
            if self.order and idx < self.turn_idx:
                self.turn_idx -= 1
            self.turn_idx %= max(1, len(self.order))
        self.pile.extend(p.hand)

    # ------------------------------------------------------------ flow

    @property
    def current(self) -> Optional[Player]:
        if self.phase not in ("turn",) or not self.order:
            return None
        return self.players.get(self.order[self.turn_idx % len(self.order)])

    @property
    def rank(self) -> str:
        return RANKS[self.rank_idx % len(RANKS)]

    def start(self) -> None:
        if len(self.players) < 2:
            raise GameError("need at least 2 players")
        deck = [Card(i, r, s) for i, (r, s) in enumerate((r, s) for r in RANKS for s in SUITS)]
        self.rng.shuffle(deck)
        self.order = list(self.players)
        self.rng.shuffle(self.order)
        per = min(self.hand_size, len(deck) // len(self.order))
        for p in self.players.values():
            p.hand = sorted((deck.pop() for _ in range(per)), key=lambda c: (RANKS.index(c.rank), c.suit))
        self.pile = []
        self.last_play = None
        self.turn_idx = 0
        self.rank_idx = 0
        self.winner = None
        self.round += 1
        self.phase = "turn"

    def play(self, player_id: str, card_ids: list[int], now: Optional[float] = None) -> Play:
        if self.phase != "turn":
            raise GameError("not time to play")
        cur = self.current
        if cur is None or cur.id != player_id:
            raise GameError("not your turn")
        ids = list(dict.fromkeys(card_ids))
        if not 1 <= len(ids) <= 4:
            raise GameError("play 1 to 4 cards")
        hand = {c.id: c for c in cur.hand}
        if any(i not in hand for i in ids):
            raise GameError("you don't have those cards")
        cards = [hand[i] for i in ids]
        cur.hand = [c for c in cur.hand if c.id not in ids]
        self.pile.extend(cards)
        now = time.monotonic() if now is None else now
        self.last_play = Play(cur.id, cards, self.rank, now)
        self.challenge_until = now + self.challenge_s
        self.phase = "challenge"
        return self.last_play

    def auto_play(self, now: Optional[float] = None) -> Play:
        """Timed out: play one card for them (an honest one if they have it)."""
        cur = self.current
        assert cur is not None and cur.hand
        honest = [c for c in cur.hand if c.rank == self.rank]
        return self.play(cur.id, [(honest or cur.hand)[0].id], now)

    def quack(self, caller_id: str, now: Optional[float] = None) -> dict[str, Any]:
        """Call the bluff. Returns the verdict; the loser has taken the pile."""
        if self.phase != "challenge" or self.last_play is None:
            raise GameError("nothing to call")
        now = time.monotonic() if now is None else now
        if now > self.challenge_until:
            raise GameError("too late")
        if caller_id == self.last_play.player_id:
            raise GameError("you can't call your own play")
        if caller_id not in self.players:
            raise GameError("not at the table")
        play = self.last_play
        liar = self.players[play.player_id]
        caller = self.players[caller_id]
        loser = caller if play.honest else liar
        loser.hand.extend(self.pile)
        loser.hand.sort(key=lambda c: (RANKS.index(c.rank), c.suit))
        picked = len(self.pile)
        self.pile = []
        if play.honest:
            caller.score += POINTS["bad_call"]
        else:
            caller.score += POINTS["good_call"]
        verdict = {
            "caller": caller.id, "player": liar.id, "honest": play.honest, "loser": loser.id,
            "picked_up": picked, "cards": [c.public() for c in play.cards], "rank": play.rank,
        }
        self.last_play = None
        self._after_play(play, challenged=True)
        return verdict

    def close_challenge(self, now: Optional[float] = None) -> Optional[dict[str, Any]]:
        """Window over with no QUACK: the play stands. Returns info about it."""
        if self.phase != "challenge" or self.last_play is None:
            return None
        now = time.monotonic() if now is None else now
        if now < self.challenge_until:
            return None
        play = self.last_play
        if not play.honest:
            self.players[play.player_id].score += POINTS["got_away"]
        self.last_play = None
        self._after_play(play, challenged=False)
        return {"player": play.player_id, "honest": play.honest}

    def _after_play(self, play: Play, challenged: bool) -> None:
        player = self.players.get(play.player_id)
        if player is not None and not player.hand:
            self.winner = player.id
            player.score += POINTS["win"]
            self.phase = "over"
            return
        self.turn_idx = (self.turn_idx + 1) % len(self.order)
        self.rank_idx += 1
        # skip anyone who has no cards (late joiners) without ending the game
        for _ in range(len(self.order)):
            cur = self.players.get(self.order[self.turn_idx])
            if cur and cur.hand:
                break
            self.turn_idx = (self.turn_idx + 1) % len(self.order)
        self.phase = "turn"

    # ------------------------------------------------------------ views

    def public(self) -> dict[str, Any]:
        cur = self.current
        lp = self.last_play
        return {
            "phase": self.phase,
            "round": self.round,
            "rank": self.rank,
            "turn": cur.id if cur else None,
            "pile": len(self.pile),
            "claim": ({"player": lp.player_id, "count": len(lp.cards), "rank": lp.rank,
                       "until": self.challenge_until} if lp else None),
            "winner": self.winner,
            "players": [
                {"id": pid, "name": self.players[pid].name, "cards": len(self.players[pid].hand),
                 "score": self.players[pid].score, "connected": self.players[pid].connected}
                for pid in (self.order if self.phase != "lobby" else list(self.players)) if pid in self.players
            ] + [
                {"id": p.id, "name": p.name, "cards": len(p.hand), "score": p.score, "connected": p.connected}
                for p in self.players.values() if self.phase != "lobby" and p.id not in self.order
            ],
        }

    def private(self, player_id: str) -> dict[str, Any]:
        p = self.players.get(player_id)
        return {"you": player_id, "hand": [c.public() for c in p.hand] if p else []}
