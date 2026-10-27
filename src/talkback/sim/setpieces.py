"""Restarts, ball-flight resolution, substitutions and injuries."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from talkback.models.xg import PITCH_LENGTH, PITCH_WIDTH, goal_geometry, shot_xg
from talkback.schemas.models import EventType, Outcome
from talkback.sim import decide

if TYPE_CHECKING:
    from talkback.sim.engine import Flight, MatchEngine

RESTART_EVENT = {
    "kickoff": EventType.kickoff, "throw_in": EventType.throw_in, "goal_kick": EventType.goal_kick,
    "corner": EventType.corner, "free_kick": EventType.free_kick, "penalty": EventType.penalty,
}


def _place(eng: "MatchEngine", kind: str, team: int, pos: np.ndarray) -> np.ndarray:
    ar = eng.attacking_right(team)
    x, y = float(pos[0]), float(pos[1])
    if kind == "kickoff":
        return np.array([52.5, 34.0])
    if kind == "throw_in":
        return np.array([np.clip(x, 1, PITCH_LENGTH - 1), 0.0 if y < 34 else PITCH_WIDTH])
    if kind == "corner":
        return np.array([PITCH_LENGTH if ar else 0.0, 0.0 if y < 34 else PITCH_WIDTH])
    if kind == "goal_kick":
        return np.array([5.5 if ar else PITCH_LENGTH - 5.5, 34 + eng.s.rng.uniform(-9, 9)])
    if kind == "penalty":
        return np.array([PITCH_LENGTH - 11 if ar else 11.0, 34.0])
    return np.array([np.clip(x, 1, PITCH_LENGTH - 1), np.clip(y, 1, PITCH_WIDTH - 1)])


def begin_restart(eng: "MatchEngine", kind: str, team: int, pos: np.ndarray, delay_ms: int) -> None:
    from talkback.sim.engine import Restart
    s = eng.s
    spot = _place(eng, kind, team, pos)
    s.restart = Restart(kind=kind, team=team, pos=spot, t_resume=s.t + delay_ms)
    s.owner = -1
    s.flight = None
    s.carry_target = None
    s.ball[:2] = spot
    s.ball[2] = 0.0
    eng.set_possession(team)


def tick_restart(eng: "MatchEngine") -> None:
    s = eng.s
    r = s.restart
    if s.t < r.t_resume:
        return
    s.restart = None
    team = eng.team_idx(r.team)
    if r.kind == "goal_kick":
        taker = int(team[0])
    elif r.kind == "penalty":
        outfield = [i for i in team if s.positions[i] != "GK"]
        taker = int(max(outfield, key=lambda i: s.attrs[i, 2]))
    else:
        cand = [i for i in team if s.positions[i] != "GK"] or list(team)
        taker = int(min(cand, key=lambda i: np.linalg.norm(s.pos[i] - r.pos)))
    s.pos[taker] = r.pos
    s.vel[taker] = 0
    eng.emit(RESTART_EVENT[r.kind], r.team, taker, x=r.pos[0], y=r.pos[1], outcome=Outcome.none)
    eng.give_ball(taker, delay_ms=0)
    s.ball[:2] = r.pos
    if r.kind == "penalty":
        decide.take_shot(eng, taker, 0.76, header=False, set_piece=True, press_d=10.0, penalty=True)
    elif r.kind == "corner":
        decide.decide(eng, taker, forced="cross")
    elif r.kind == "free_kick":
        dist, ang = goal_geometry(r.pos[0], r.pos[1], eng.attacking_right(r.team))
        if dist <= 30 and abs(r.pos[1] - 34) < 20 and s.rng.random() < 0.5:
            xg = shot_xg(dist, ang, False, False, True) * 0.6
            decide.take_shot(eng, taker, max(xg, 0.02), header=False, set_piece=True, press_d=9.0)
        else:
            decide.decide(eng, taker, forced="pass")
    else:
        decide.decide(eng, taker, forced="pass")


def _nearest(eng: "MatchEngine", idx: np.ndarray, point: np.ndarray) -> int:
    return int(idx[np.argmin(np.linalg.norm(eng.s.pos[idx] - point, axis=1))])


def _out_of_play(eng: "MatchEngine", f: "Flight") -> None:
    s = eng.s
    x, y = f.end
    last = s.last_touch_team
    if x <= 0 or x >= PITCH_LENGTH:
        goal_of = 1 if (x >= PITCH_LENGTH) == eng.attacking_right(0) else 0  # team whose goal line it is
        if last == goal_of:
            begin_restart(eng, "corner", 1 - goal_of, f.end, delay_ms=15_000)
        else:
            begin_restart(eng, "goal_kick", goal_of, f.end, delay_ms=10_000)
    else:
        begin_restart(eng, "throw_in", 1 - last, f.end, delay_ms=6_000)


def _loose(eng: "MatchEngine", f: "Flight") -> None:
    s = eng.s
    end = np.clip(f.end, [0.5, 0.5], [PITCH_LENGTH - 0.5, PITCH_WIDTH - 0.5])
    s.ball[:2] = end
    act = np.flatnonzero(s.active)
    i = _nearest(eng, act, end)
    s.pos[i] = s.pos[i] + (end - s.pos[i]) * 0.5
    if eng.team_of(i) != f.team:
        eng.emit(EventType.ball_recovery, eng.team_of(i), i, x=end[0], y=end[1])
    eng.give_ball(i, delay_ms=int(500 + 600 * s.rng.random()))


def resolve_flight(eng: "MatchEngine", f: "Flight") -> None:
    s = eng.s
    s.flight = None
    k = f.team
    if f.kind == "shot":
        if eng.flip_active("shot", k):
            eng.give_ball(f.passer, delay_ms=300)
            return
        _resolve_shot(eng, f)
        return
    if f.outcome == "complete":
        eng.give_ball(f.target)
    elif f.outcome == "header_chance":
        i = f.target
        s.pos[i] = f.end
        defenders = eng.team_idx(1 - k)
        press_d = float(np.min(np.linalg.norm(s.pos[defenders] - f.end, axis=1)))
        xg = decide.shot_quality(eng, i, f.end, press_d, header=True, set_piece=True)
        eng.give_ball(i, delay_ms=0)
        decide.take_shot(eng, i, max(xg, 0.02), header=True, set_piece=True, press_d=press_d)
    elif f.outcome == "intercept" and f.kind == "pass" and f.intended >= 0 and eng.flip_active("interception", 1 - k):
        eng.give_ball(f.intended)
    elif f.outcome == "intercept":
        o = f.interceptor
        if f.kind == "cross":
            if s.rng.random() < 0.18:
                eng.emit(EventType.clearance, 1 - k, o, x=f.end[0], y=f.end[1])
                begin_restart(eng, "corner", k, f.end, delay_ms=15_000)
                return
            eng.give_ball(o, delay_ms=0)
            decide.decide(eng, o, forced="clearance")
            return
        eng.emit(EventType.interception, 1 - k, o, x=f.end[0], y=f.end[1])
        own_line = 0.0 if eng.attacking_right(1 - k) else PITCH_LENGTH
        if abs(f.end[0] - own_line) < 20 and s.rng.random() < 0.15:
            begin_restart(eng, "corner", k, f.end, delay_ms=15_000)
            return
        eng.give_ball(o, delay_ms=int(300 + 500 * s.rng.random()))
    elif f.outcome == "out":
        _out_of_play(eng, f)
    else:
        if not (0 < f.end[0] < PITCH_LENGTH and 0 < f.end[1] < PITCH_WIDTH):
            _out_of_play(eng, f)
        else:
            _loose(eng, f)


def _resolve_shot(eng: "MatchEngine", f: "Flight") -> None:
    s = eng.s
    k = f.team
    shooter = f.passer
    defenders = eng.team_idx(1 - k)
    keeper = int(defenders[0])
    if f.outcome == "goal":
        s.score[k] += 1
        eng.emit(EventType.goal, k, shooter, x=f.end[0], y=f.end[1], outcome=Outcome.goal, xg=f.xg)
        s.owner = -1
        for kk in (0, 1):
            idx = np.arange(11) + 11 * kk
            from talkback.sim import shape
            act = idx[s.active[idx]]
            s.pos[act] = shape.kickoff_positions(s.slots[act], eng.attacking_right(kk))
        begin_restart(eng, "kickoff", 1 - k, np.array([52.5, 34.0]), delay_ms=40_000)
    elif f.outcome == "saved":
        eng.emit(EventType.save, 1 - k, keeper, shooter, x=f.end[0], y=f.end[1])
        if s.rng.random() < 0.3:
            begin_restart(eng, "corner", k, f.end + np.array([0, 1 if f.end[1] > 34 else -1]), delay_ms=15_000)
        else:
            eng.give_ball(keeper, delay_ms=2500)
    elif f.outcome == "blocked":
        blocker = _nearest(eng, defenders, f.end)
        eng.emit(EventType.block, 1 - k, blocker, shooter, x=f.end[0], y=f.end[1])
        if s.rng.random() < 0.4:
            begin_restart(eng, "corner", k, f.end, delay_ms=15_000)
        else:
            _loose(eng, f)
    else:
        begin_restart(eng, "goal_kick", 1 - k, f.end, delay_ms=10_000)


def scheduled_changes(eng: "MatchEngine") -> None:
    s = eng.s
    if s.t % 60_000:
        return
    m = eng.minute()
    for k in (0, 1):
        if s.injury_plan[k] is not None and m >= s.injury_plan[k]:
            s.injury_plan[k] = None
            out = _pick_off(eng, k, injured=True)
            if out is not None:
                eng.emit(EventType.injury, k, out, x=s.pos[out, 0], y=s.pos[out, 1], outcome=Outcome.none)
                if s.subs_made[k] < 5:
                    _substitute(eng, k, out)
        plan = s.sub_plan[k]
        if s.period == 2 and s.subs_made[k] < min(5, len(plan)) and m >= plan[min(s.subs_made[k], len(plan) - 1)]:
            out = _pick_off(eng, k, injured=False)
            if out is not None:
                _substitute(eng, k, out)


def _pick_off(eng: "MatchEngine", k: int, injured: bool) -> int | None:
    s = eng.s
    protected = {b.player_id for b, done in zip(s.beats, s.beats_done) if not done}
    cand = [int(i) for i in eng.team_idx(k) if s.positions[i] != "GK" and i != s.owner
            and s.ids[i] not in protected
            and (s.flight is None or i not in (s.flight.target, s.flight.passer))]
    if not cand:
        return None
    if injured:
        return int(cand[int(s.rng.integers(len(cand)))])
    return min(cand, key=lambda i: s.attrs[i, 5] - (s.t - s.on_since[i]) / 60_000 * 0.4 + s.rng.normal(0, 4))


def _substitute(eng: "MatchEngine", k: int, out: int) -> None:
    from talkback.sim.engine import ATTR_KEYS
    s = eng.s
    bench = s.bench[k]
    if not bench:
        return
    same = [p for p in bench if p.position == s.positions[out]]
    sub = (same or bench)[0]
    bench.remove(sub)
    old = out
    out_id = s.ids[old]
    s.ids[old] = sub.id
    s.roles[old] = sub.role
    s.positions[old] = sub.position
    s.attrs[old] = [getattr(sub.attrs, a) for a in ATTR_KEYS]
    s.on_since[old] = s.t
    s.subs_made[k] += 1
    eng.invalidate()
    eng.emit(EventType.substitution, k, old, x=s.pos[old, 0], y=s.pos[old, 1], outcome=Outcome.none,
             player_out=out_id)
