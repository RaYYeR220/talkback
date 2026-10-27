"""Seeded engine snapshots used by the rollout tests."""

from __future__ import annotations

from functools import lru_cache, partial

from talkback.schemas.models import EventType, Outcome
from talkback.sim.engine import MatchEngine, simulate_match
from talkback.world.league import generate_league

FIXTURE = "FX1"
SEED = 3


@lru_cache(maxsize=1)
def clubs():
    lg = generate_league(7)
    return lg.club("C03"), lg.club("C11")


def factory():
    h, a = clubs()
    return partial(MatchEngine, FIXTURE, h, a, SEED)


@lru_cache(maxsize=1)
def final_third_snapshot():
    """Snapshot taken while a final-third pass is in flight and about to be intercepted."""
    h, a = clubs()
    events, _ = simulate_match(FIXTURE, h, a, seed=SEED, frames=False)
    target = None
    for prev, ev in zip(events, events[1:]):
        if (ev.type == EventType.interception and prev.type == EventType.pass_
                and prev.outcome == Outcome.fail and prev.x is not None):
            attacking_right = (prev.team_id == h.id) == (prev.period == 1)
            xn = prev.x / 105 if attacking_right else 1 - prev.x / 105
            en = prev.end_x / 105 if attacking_right else 1 - prev.end_x / 105
            if xn > 0.6 and en > 0.75 and en > xn:
                target = prev
                break
    assert target is not None
    eng = MatchEngine(FIXTURE, h, a, SEED)
    while eng.t < target.t + 100:
        eng.step()
    return eng.snapshot(), target.team_id, ev.team_id
