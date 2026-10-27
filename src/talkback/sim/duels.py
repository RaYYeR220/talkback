"""Pressure, tackles, fouls and cards around the ball carrier."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from talkback.schemas.models import EventType, Outcome
from talkback.sim import setpieces
from talkback.sim.decide import in_box

if TYPE_CHECKING:
    from talkback.sim.engine import MatchEngine

PRESSURE_M = 2.0
TACKLE_M = 1.2
TACKLE_HAZARD = 0.22      # attempts per second at tackling 70
FOUL_P = 0.4
BOX_FOUL_FACTOR = 0.02
YELLOW_P = 0.19
SECOND_FOUL_YELLOW_P = 0.35
RED_P = 0.003


def tick(eng: "MatchEngine") -> None:
    s = eng.s
    i = s.owner
    k = eng.team_of(i)
    opps = eng.team_idx(1 - k)
    d = np.linalg.norm(s.pos[opps] - s.pos[i], axis=1)
    j = int(np.argmin(d)) if len(d) else -1
    if j >= 0 and d[j] < PRESSURE_M and not s.pressure_flagged:
        o = int(opps[j])
        s.pressure_flagged.add(o)
        eng.emit(EventType.pressure, 1 - k, o, i, x=s.pos[o, 0], y=s.pos[o, 1], outcome=Outcome.none)
    press = s.styles[1 - k, 0]
    for j in np.flatnonzero(d < TACKLE_M):
        o = int(opps[j])
        if s.t < s.tackle_cooldown[o]:
            continue
        rate = TACKLE_HAZARD * s.attrs[o, 3] / 70 * (0.7 + 0.6 * press)
        if _in_own_third(eng, o):
            rate *= 2.0
        if s.rng.random() < rate * 0.1:
            _tackle(eng, o, i)
            return


def _in_own_third(eng: "MatchEngine", o: int) -> bool:
    x = eng.s.pos[o, 0]
    return x < 35 if eng.attacking_right(eng.team_of(o)) else x > 70


def _tackle(eng: "MatchEngine", o: int, i: int) -> None:
    s = eng.s
    k = eng.team_of(i)
    x, y = s.pos[i]
    foul_p = FOUL_P * (BOX_FOUL_FACTOR if in_box(x, y, eng.attacking_right(k)) else 1.0)
    if s.rng.random() < foul_p:
        _foul(eng, o, i)
        return
    p_win = 0.45 + 0.002 * (s.attrs[o, 3] - s.attrs[i, 6]) + (0.1 if _in_own_third(eng, o) else 0.0)
    won = s.rng.random() < p_win
    if won and eng.flip_active("tackle", 1 - k):
        won = False
    if won:
        eng.emit(EventType.tackle, 1 - k, o, i, x=x, y=y, outcome=Outcome.success)
        if (y < 6 or y > 62) and s.rng.random() < 0.4:
            setpieces.begin_restart(eng, "throw_in", k, np.array([x, y]), delay_ms=6_000)
            return
        eng.give_ball(o, delay_ms=int(400 + 500 * s.rng.random()))
    else:
        eng.emit(EventType.tackle, 1 - k, o, i, x=x, y=y, outcome=Outcome.fail)
        eng.emit(EventType.dribble, k, i, o, x=x, y=y, outcome=Outcome.success)
        s.tackle_cooldown[o] = s.t + 1500


def _foul(eng: "MatchEngine", o: int, i: int) -> None:
    s = eng.s
    k = eng.team_of(i)
    x, y = s.pos[i]
    eng.emit(EventType.foul, 1 - k, o, i, x=x, y=y, outcome=Outcome.none)
    pid = s.ids[o]
    recent = s.t - s.last_foul.get(pid, -10**9) < 15 * 60_000
    s.last_foul[pid] = s.t
    r = s.rng.random()
    if r < RED_P:
        send_off(eng, o, "straight")
    elif r < RED_P + (SECOND_FOUL_YELLOW_P if recent else YELLOW_P):
        s.yellows[pid] = s.yellows.get(pid, 0) + 1
        if s.yellows[pid] >= 2:
            send_off(eng, o, "second_yellow")
        else:
            eng.emit(EventType.card, 1 - k, o, x=x, y=y, outcome=Outcome.yellow, card="yellow")
    if in_box(x, y, eng.attacking_right(k)):
        setpieces.begin_restart(eng, "penalty", k, np.array([x, y]), delay_ms=30_000)
    else:
        setpieces.begin_restart(eng, "free_kick", k, np.array([x, y]), delay_ms=12_000)


def send_off(eng: "MatchEngine", o: int, why: str) -> None:
    s = eng.s
    k = eng.team_of(o)
    eng.emit(EventType.card, k, o, x=s.pos[o, 0], y=s.pos[o, 1], outcome=Outcome.red, card=why)
    s.active[o] = False
    eng.invalidate()
    s.vel[o] = 0
    s.reds[k] += 1
