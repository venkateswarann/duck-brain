import random

import pytest

from duck_brain.game.liars import POINTS, GameError, LiarsGame


def setup(n=3, seed=1):
    g = LiarsGame(hand_size=7, challenge_s=6, rng=random.Random(seed))
    ps = [g.join(f"P{i}") for i in range(n)]
    g.start()
    return g, ps


def test_deal_and_turn_order():
    g, ps = setup()
    assert g.phase == "turn" and g.rank == "A"
    assert all(len(p.hand) == 7 for p in ps)
    with pytest.raises(GameError):
        other = next(p for p in ps if p.id != g.current.id)
        g.play(other.id, [other.hand[0].id])


def test_caught_liar_takes_pile():
    g, _ = setup()
    cur = g.current
    lie = next(c for c in cur.hand if c.rank != g.rank)
    g.play(cur.id, [lie.id], now=0)
    caller = next(p for pid, p in g.players.items() if pid != cur.id)
    v = g.quack(caller.id, now=1)
    assert v["honest"] is False and v["loser"] == cur.id
    assert len(cur.hand) == 7 and caller.score == POINTS["good_call"]
    assert g.phase == "turn" and g.rank == "2"


def test_honest_play_punishes_caller():
    g, _ = setup()
    cur = g.current
    cur.hand[0].rank = g.rank  # force an honest card
    g.play(cur.id, [cur.hand[0].id], now=0)
    caller = next(p for pid, p in g.players.items() if pid != cur.id)
    v = g.quack(caller.id, now=1)
    assert v["honest"] is True and v["loser"] == caller.id
    assert len(caller.hand) == 8 and caller.score == POINTS["bad_call"]


def test_unchallenged_lie_scores_and_late_quack_rejected():
    g, _ = setup()
    cur = g.current
    lie = next(c for c in cur.hand if c.rank != g.rank)
    g.play(cur.id, [lie.id], now=0)
    with pytest.raises(GameError):
        g.quack(next(pid for pid in g.players if pid != cur.id), now=7)
    assert g.close_challenge(now=7)["honest"] is False
    assert cur.score == POINTS["got_away"]


def test_last_card_wins():
    g, _ = setup(n=2)
    cur = g.current
    cur.hand = cur.hand[:1]
    g.play(cur.id, [cur.hand[0].id], now=0)
    g.close_challenge(now=7)
    assert g.phase == "over" and g.winner == cur.id and cur.score >= POINTS["win"]


def test_cannot_call_own_play_and_card_limits():
    g, _ = setup()
    cur = g.current
    with pytest.raises(GameError):
        g.play(cur.id, [c.id for c in cur.hand[:5]])
    g.play(cur.id, [cur.hand[0].id], now=0)
    with pytest.raises(GameError):
        g.quack(cur.id, now=1)
