"""Ball-carrier decisions: score every option, pick one by softmax, execute it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from talkback.models.passing import pass_completion
from talkback.models.xg import PITCH_LENGTH, PITCH_WIDTH, goal_geometry, shot_xg
from talkback.schemas.models import EventType, Outcome

if TYPE_CHECKING:
    from talkback.sim.engine import MatchEngine

TEMPERATURE = 0.012
KEEP_VALUE = 0.03       # value of simply keeping the ball
SHOT_A = 0.065          # shot hazard scale: P(shoot) = SHOT_A * xG^SHOT_EXP per decision
SHOT_EXP = 0.2
CONE_FACTOR = 0.5
CARRY_BONUS = 0.002


def _seg_dist(a: np.ndarray, b: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Distance from each point p (o,2) to each segment a->b[j] (m,2): returns (m, o)."""
    ab = b - a
    ap = p - a
    denom = np.maximum((ab ** 2).sum(axis=1), 1e-9)
    t = np.clip((ap @ ab.T).T / denom[:, None], 0, 1)
    closest = a + t[..., None] * ab[:, None, :]
    return np.linalg.norm(p[None, :, :] - closest, axis=2)


def in_box(x: float, y: float, attacking_right: bool) -> bool:
    gx = x if attacking_right else PITCH_LENGTH - x
    return gx > PITCH_LENGTH - 16.5 and 13.84 < y < 54.16


def shot_quality(eng: "MatchEngine", i: int, pos: np.ndarray, pressure_m: float, header: bool,
                 set_piece: bool) -> float:
    k = eng.team_of(i)
    ar = eng.attacking_right(k)
    dist, ang = goal_geometry(pos[0], pos[1], ar)
    xg = shot_xg(dist, ang, pressure_m < 2.0, header, set_piece)
    blockers = cone_blockers(eng, k, pos, ar)
    return xg * CONE_FACTOR ** blockers * _beat_factor(eng, i)[1]


def cone_blockers(eng: "MatchEngine", k: int, pos: np.ndarray, attacking_right: bool) -> int:
    """Outfield defenders inside the triangle between the shot and the goal posts."""
    s = eng.s
    gx = PITCH_LENGTH if attacking_right else 0.0
    a, b, c = pos, np.array([gx, 34 - 3.66]), np.array([gx, 34 + 3.66])
    d = eng.team_idx(1 - k)[1:]
    if not len(d):
        return 0
    p = s.pos[d]

    def side(p1, p2, q):
        return (q[:, 0] - p2[0]) * (p1[1] - p2[1]) - (p1[0] - p2[0]) * (q[:, 1] - p2[1])

    d1, d2, d3 = side(a, b, p), side(b, c, p), side(c, a, p)
    neg = (d1 < 0) | (d2 < 0) | (d3 < 0)
    pos_ = (d1 > 0) | (d2 > 0) | (d3 > 0)
    return int((~(neg & pos_)).sum())


def _beat_factor(eng: "MatchEngine", i: int) -> tuple[float, float]:
    """(shot propensity, xG multiplier) for a player with an active scripted beat."""
    s = eng.s
    for b, done in zip(s.beats, s.beats_done):
        if not done and b.player_id == s.ids[i] and b.window_ms[0] <= s.t <= b.window_ms[1]:
            late = (s.t - b.window_ms[0]) / max(1, b.window_ms[1] - b.window_ms[0]) > 0.6
            return (14.0, 2.4) if late else (7.0, 1.8)
    return 1.0, 1.0


def _beat_targets(eng: "MatchEngine") -> set[str]:
    s = eng.s
    return {b.player_id for b, done in zip(s.beats, s.beats_done)
            if not done and b.window_ms[0] <= s.t <= b.window_ms[1]}


def decide(eng: "MatchEngine", i: int, forced: str | None = None) -> None:
    s = eng.s
    k = eng.team_of(i)
    ar = eng.attacking_right(k)
    mates = eng.team_idx(k)
    mates = mates[mates != i]
    opps = eng.team_idx(1 - k)
    p = s.pos[i].copy()
    opp_pos = s.pos[opps]
    press_d = float(np.min(np.linalg.norm(opp_pos - p, axis=1))) if len(opps) else 30.0
    st = eng.style(k)
    xn = p[0] / PITCH_LENGTH if ar else 1 - p[0] / PITCH_LENGTH
    yn = p[1] / PITCH_WIDTH
    passing = s.attrs[i, 1]
    xt = eng.xt

    def own(xs, ys):
        return xt.value_np(xs, ys, ar, eng.xt_arr)

    def theirs(xs, ys):
        return xt.value_np(xs, ys, not ar, eng.xt_arr)

    # shooting is a hazard on chance quality, so shot volume has one calibrated knob
    inside = 0.0 < p[0] < PITCH_LENGTH and 0.0 < p[1] < PITCH_WIDTH
    beat_on = _beat_factor(eng, i)[0] > 1.0
    if forced is None and (xn > 0.6 or (beat_on and xn > 0.55)) and inside and s.positions[i] != "GK":
        xg = shot_quality(eng, i, p, press_d, False, False)
        if xg > 0.015:
            p_shoot = min(0.85, SHOT_A * xg ** SHOT_EXP) * _beat_factor(eng, i)[0]
            if s.rng.random() < p_shoot and not eng.flip_active("shot", k):
                take_shot(eng, i, xg, header=False, set_piece=False, press_d=press_d)
                return

    kinds: list[str] = []
    evs: list[float] = []
    payload: list[tuple] = []

    if len(mates):
        mp = s.pos[mates]
        d = np.linalg.norm(mp - p, axis=1)
        lanes = _seg_dist(p, mp, opp_pos).min(axis=1) if len(opps) else np.full(len(mates), 10.0)
        lofted = d > 30
        comp = pass_completion(d, lanes, press_d, passing, lofted)
        ev = (comp * (own(mp[:, 0], mp[:, 1]) + KEEP_VALUE) - (1 - comp) * theirs(mp[:, 0], mp[:, 1])
              + (d > 25) * 0.006 * st["directness"] - (d < 6) * 0.004)
        beat_ids = _beat_targets(eng)
        if beat_ids:
            ev = ev + np.array([0.12 if s.ids[m] in beat_ids else 0.0 for m in mates])
        for j in range(len(mates)):
            kinds.append("pass")
            evs.append(float(ev[j]))
            payload.append((int(mates[j]), float(comp[j]), float(lanes[j]), bool(lofted[j]), float(d[j])))

    goal_dir = np.array([1.0 if ar else -1.0, 0.0])
    if len(opps):
        near = opp_pos[np.argmin(np.linalg.norm(opp_pos - p, axis=1))]
        away = p - near
        away = away / (np.linalg.norm(away) + 1e-9)
        direction = goal_dir * 0.75 + away * 0.25 + s.rng.normal(0, 0.15, 2)
    else:
        direction = goal_dir
    direction = direction / (np.linalg.norm(direction) + 1e-9)
    carry_to = np.clip(p + direction * s.rng.uniform(3, 6), [1, 1], [PITCH_LENGTH - 1, PITCH_WIDTH - 1])
    crowd = int((np.linalg.norm(opp_pos - carry_to, axis=1) < 3.0).sum()) if len(opps) else 0
    keep = max(0.25, (0.92 if press_d > 2 else 0.75) - 0.18 * crowd
               - (0.2 if in_box(carry_to[0], carry_to[1], ar) else 0.0))
    cx, cy = carry_to[0:1], carry_to[1:2]
    kinds.append("carry")
    evs.append(float(keep * (own(cx, cy)[0] + KEEP_VALUE) - (1 - keep) * theirs(cx, cy)[0] + CARRY_BONUS))
    payload.append((carry_to,))

    if xn > 0.75 and (yn < 0.22 or yn > 0.78):
        tx = PITCH_LENGTH - s.rng.uniform(6, 14) if ar else s.rng.uniform(6, 14)
        target = np.array([tx, s.rng.uniform(26, 42)])
        lane = float(np.min(np.linalg.norm(opp_pos - target, axis=1))) if len(opps) else 6.0
        comp_c = float(pass_completion(np.linalg.norm(target - p), lane, press_d, passing, True))
        kinds.append("cross")
        evs.append(comp_c * (own(target[0:1], target[1:2])[0] + KEEP_VALUE + 0.04)
                   - (1 - comp_c) * 0.01)
        payload.append((target, comp_c))

    if xn < 0.3 and press_d < 3.0:
        kinds.append("clearance")
        evs.append(0.5 * KEEP_VALUE - 0.004)
        payload.append(())

    if forced:
        choice = kinds.index(forced) if forced in kinds else int(np.argmax(evs))
    else:
        w = np.exp((np.array(evs) - max(evs)) / TEMPERATURE)
        choice = int(s.rng.choice(len(evs), p=w / w.sum()))
    execute(eng, i, kinds[choice], payload[choice], press_d)


def execute(eng: "MatchEngine", i: int, kind: str, pl: tuple, press_d: float) -> None:
    s = eng.s
    k = eng.team_of(i)
    p = s.pos[i].copy()
    if kind == "carry":
        s.carry_target = pl[0]
        s.carry_start = p
        s.carry_t0 = s.t
        return
    if kind == "pass":
        target, comp, lane, lofted, dist = pl
        _do_pass(eng, i, target, comp, lane, lofted, dist, press_d)
        return
    if kind == "shot":
        take_shot(eng, i, pl[0], header=False, set_piece=False, press_d=press_d)
        return
    if kind == "cross":
        target, comp = pl
        success = s.rng.random() < comp
        attackers = eng.team_idx(k)
        defenders = eng.team_idx(1 - k)
        if success:
            recv = int(attackers[np.argmin(np.linalg.norm(s.pos[attackers] - target, axis=1))])
            outcome = "header_chance" if s.rng.random() < 0.45 else "complete"
        else:
            recv = int(defenders[np.argmin(np.linalg.norm(s.pos[defenders] - target, axis=1))])
            outcome = "intercept"
        eng.emit(EventType.cross, k, i, x=p[0], y=p[1], end_x=target[0], end_y=target[1],
                 outcome=Outcome.success if success else Outcome.fail, xpass=comp, lofted=True)
        eng.start_flight("cross", i, target, s.rng.normal(17, 2.5), 3.0, recv if success else -1, outcome,
                         interceptor=-1 if success else recv)
        return
    if kind == "clearance":
        ar = eng.attacking_right(k)
        tx = p[0] + (1 if ar else -1) * s.rng.uniform(25, 45)
        end = np.array([np.clip(tx, 3, PITCH_LENGTH - 3), np.clip(p[1] + s.rng.normal(0, 12), 2, PITCH_WIDTH - 2)])
        eng.emit(EventType.clearance, k, i, x=p[0], y=p[1], end_x=end[0], end_y=end[1])
        eng.start_flight("clearance", i, end, s.rng.normal(20, 3), 6.0, -1, "loose")
        return
    raise ValueError(kind)


def _offside_line(eng: "MatchEngine", k: int) -> float:
    """Normalised x of the second-last defender of the team defending against k."""
    s = eng.s
    ar = eng.attacking_right(k)
    d = eng.team_idx(1 - k)
    xs = s.pos[d, 0] / PITCH_LENGTH if ar else 1 - s.pos[d, 0] / PITCH_LENGTH
    return float(np.sort(xs)[-2]) if len(xs) >= 2 else 1.0


def _do_pass(eng: "MatchEngine", i: int, target: int, comp: float, lane: float, lofted: bool,
             dist: float, press_d: float) -> None:
    s = eng.s
    k = eng.team_of(i)
    ar = eng.attacking_right(k)
    p = s.pos[i].copy()
    end = s.pos[target] + s.vel[target] * 0.6
    end = np.clip(end, [0.5, 0.5], [PITCH_LENGTH - 0.5, PITCH_WIDTH - 0.5])
    rx = end[0] / PITCH_LENGTH if ar else 1 - end[0] / PITCH_LENGTH
    px = p[0] / PITCH_LENGTH if ar else 1 - p[0] / PITCH_LENGTH
    if rx > 0.5 and rx > _offside_line(eng, k) and rx > px and s.rng.random() < 0.10:
        eng.emit(EventType.pass_, k, i, target, x=p[0], y=p[1], end_x=end[0], end_y=end[1],
                 outcome=Outcome.fail, xpass=comp, lofted=lofted, distance=dist, offside=True)
        eng.emit(EventType.offside, k, target, x=end[0], y=end[1], outcome=Outcome.none)
        from talkback.sim import setpieces
        setpieces.begin_restart(eng, "free_kick", 1 - k, end, delay_ms=8000)
        return
    success = s.rng.random() < comp
    if not success and eng.flip_active("interception", 1 - k):
        success = True
    speed = s.rng.normal(18 if lofted else 14, 3)
    speed = float(np.clip(speed, 8, 30))
    if success:
        eng.emit(EventType.pass_, k, i, target, x=p[0], y=p[1], end_x=end[0], end_y=end[1],
                 outcome=Outcome.success, xpass=comp, lofted=lofted, distance=dist, pass_speed_ms=speed,
                 pressure=press_d < 2.0)
        eng.start_flight("pass", i, end, speed, 3.5 if lofted else 0.2, target, "complete")
        return
    opps = eng.team_idx(1 - k)
    seg = _seg_dist(p, end[None, :], s.pos[opps])[0]
    j = int(np.argmin(seg))
    if seg[j] < 2.5 and s.rng.random() < 0.8:
        inter = int(opps[j])
        ab = end - p
        tpos = np.clip(np.dot(s.pos[inter] - p, ab) / max(np.dot(ab, ab), 1e-9), 0.15, 1.0)
        cut = p + ab * tpos
        eng.emit(EventType.pass_, k, i, target, x=p[0], y=p[1], end_x=end[0], end_y=end[1],
                 outcome=Outcome.fail, xpass=comp, lofted=lofted, distance=dist, pass_speed_ms=speed,
                 pressure=press_d < 2.0)
        eng.start_flight("pass", i, cut, speed, 0.5, -1, "intercept", interceptor=inter, intended=target)
        return
    backward = (end[0] - p[0]) * (1 if ar else -1) < 0
    overhit = end + (end - p) / (np.linalg.norm(end - p) + 1e-9) * s.rng.uniform(1, 4 if backward else 15)
    if backward:
        overhit[0] = float(np.clip(overhit[0], 2.0, PITCH_LENGTH - 2.0))
    if (end[1] < 12 or end[1] > PITCH_WIDTH - 12) and s.rng.random() < 0.65:
        overhit[1] = -1.0 if end[1] < 34 else PITCH_WIDTH + 1.0
    eng.emit(EventType.pass_, k, i, target, x=p[0], y=p[1], end_x=end[0], end_y=end[1],
             outcome=Outcome.fail, xpass=comp, lofted=lofted, distance=dist, pass_speed_ms=speed,
             pressure=press_d < 2.0)
    outside = not (0 < overhit[0] < PITCH_LENGTH and 0 < overhit[1] < PITCH_WIDTH)
    eng.start_flight("pass", i, overhit, speed, 0.5, -1, "out" if outside else "loose")


def take_shot(eng: "MatchEngine", i: int, xg: float, header: bool, set_piece: bool, press_d: float,
              penalty: bool = False) -> None:
    s = eng.s
    k = eng.team_of(i)
    ar = eng.attacking_right(k)
    p = s.pos[i].copy()
    xg = float(min(0.9 if not penalty else 0.76, xg))
    gx = PITCH_LENGTH if ar else 0.0
    gy = 34 + s.rng.uniform(-3.4, 3.4)
    dist = float(np.linalg.norm(np.array([gx, gy]) - p))
    speed = float(np.clip(s.rng.normal(24 + 6 * (1 - min(dist, 35) / 35), 3.5), 15, 37))
    if header:
        speed = float(np.clip(speed * 0.55, 9, 20))
    r = s.rng.random()
    keeper = eng.team_idx(1 - k)[0]
    keeping = s.attrs[keeper, 7]
    if r < xg:
        outcome, o = "goal", Outcome.goal
    elif not penalty and s.rng.random() < (0.4 if press_d < 2.0 else 0.18):
        outcome, o = "blocked", Outcome.blocked
    elif s.rng.random() < 0.26 * (0.7 + keeping / 200):
        outcome, o = "saved", Outcome.saved
    else:
        outcome, o = "off", Outcome.off_target
        gy = 34 + s.rng.choice([-1, 1]) * s.rng.uniform(4.2, 12)
    end = np.array([gx, gy])
    if outcome == "blocked":
        end = p + (end - p) * s.rng.uniform(0.1, 0.3)
    eng.emit(EventType.shot, k, i, x=p[0], y=p[1], end_x=end[0], end_y=end[1], outcome=o, xg=xg,
             shot_speed_ms=speed, body_part="head" if header else "foot", set_piece=set_piece,
             penalty=penalty, pressure=press_d < 2.0)
    eng.start_flight("shot", i, end, speed, 1.2 if not header else 0.5, -1, outcome, xg=xg)
    if outcome == "goal":
        for n, b in enumerate(s.beats):
            if b.player_id == s.ids[i] and b.window_ms[0] <= s.t <= b.window_ms[1] + 120_000:
                s.beats_done[n] = True
