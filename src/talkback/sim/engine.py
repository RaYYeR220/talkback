"""10 Hz agent-based match engine.

Players move toward shape targets under acceleration and speed limits; the
ball carrier picks an action from scored options; duels, set pieces, cards,
substitutions and game-state tactics run on the same clock. Every outcome
comes from the engine's own seeded generator, so a match is reproducible
from (fixture, seed), and a snapshot can be restored for counterfactuals.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Iterator, NamedTuple

import numpy as np

from talkback.models.xg import PITCH_LENGTH, PITCH_WIDTH
from talkback.models.xt import XTGrid, load_xt_grid
from talkback.schemas.models import Event, EventType, MatchState, Outcome, event_id, state_hash
from talkback.sim import decide, duels, setpieces, shape
from talkback.sim.fast import select_xi
from talkback.world.league import Club, Player, StyleVector
from talkback.world.storylines import ForcedBeat

TICK_MS = 100
DT = TICK_MS / 1000
ACCEL = 4.0
SPRINT_MS = 7.0
ATTR_KEYS = ("pace", "passing", "finishing", "tackling", "pressing", "stamina", "composure", "keeping")
A = {k: i for i, k in enumerate(ATTR_KEYS)}


class RawFrame(NamedTuple):
    match_id: str
    t: int
    ball: np.ndarray       # (3,)
    pos: np.ndarray        # (n_active, 2)
    speed: np.ndarray      # (n_active,)
    ids: tuple[str, ...]


@dataclass
class Flight:
    kind: str              # pass | cross | shot | clearance | throw
    start: np.ndarray
    end: np.ndarray
    t0: int
    t1: int
    peak: float
    team: int
    passer: int
    target: int
    outcome: str           # complete | intercept | out | loose | goal | saved | off | blocked | header_chance
    interceptor: int = -1
    possession_id: int = 0
    xg: float = 0.0
    intended: int = -1


@dataclass
class Restart:
    kind: str              # kickoff | throw_in | goal_kick | corner | free_kick | penalty
    team: int
    pos: np.ndarray
    t_resume: int


@dataclass
class EngineState:
    t: int
    period: int
    p1_end: int
    p2_start: int
    p2_end: int
    ids: list[str]
    roles: list[str]
    positions: list[str]
    active: np.ndarray
    pos: np.ndarray
    vel: np.ndarray
    attrs: np.ndarray
    slots: np.ndarray
    on_since: np.ndarray
    offsets: np.ndarray
    next_offset_t: int
    styles: np.ndarray            # (2, 5): press, line, directness, width, tempo
    tactic_flags: list[set]
    ball: np.ndarray
    owner: int
    flight: Flight | None
    restart: Restart | None
    possession_team: int
    possession_id: int
    last_touch_team: int
    next_decision_t: int
    carry_target: np.ndarray | None
    carry_start: np.ndarray | None
    carry_t0: int
    pressing: bool
    pressure_flagged: set
    tackle_cooldown: np.ndarray
    score: list[int]
    reds: list[int]
    yellows: dict
    last_foul: dict
    subs_made: list[int]
    sub_plan: list[list[int]]
    injury_plan: list[int | None]
    bench: list[list[Player]]
    beats: list[ForcedBeat]
    beats_done: list[bool]
    seq: int
    done: bool
    rng: np.random.Generator
    set_piece: str | None = None
    overrides: dict = field(default_factory=dict)

    def copy(self) -> "EngineState":
        return copy.deepcopy(self)


class MatchEngine:
    def __init__(self, fixture_id: str, home: Club, away: Club, seed: int,
                 beats: list[ForcedBeat] | None = None,
                 start_xi: tuple[list[str], list[str]] | None = None,
                 xt: XTGrid | None = None):
        self.fixture_id = fixture_id
        self.clubs = (home, away)
        self.club_ids = (home.id, away.id)
        self.xt = xt or load_xt_grid()
        self.xt_arr = self.xt.array()
        self._events: list[Event] = []
        rng = np.random.default_rng(seed)
        lineups, benches = [], []
        for k, club in enumerate(self.clubs):
            xi, bench = select_xi(club, rng)
            if start_xi is not None:
                wanted = start_xi[k]
                by_id = {p.id: p for p in club.squad}
                xi = [by_id[pid] for pid in wanted]
                bench = [p for p in sorted(club.squad, key=lambda p: -p.attrs.stamina)
                         if p.id not in set(wanted)][:7]
            xi = sorted(xi, key=lambda p: ("GK", "DF", "MF", "FW").index(p.position))
            lineups.append(xi)
            benches.append(bench)
        players = lineups[0] + lineups[1]
        slots = np.array(shape.SLOTS[home.formation] + shape.SLOTS[away.formation], float)
        attrs = np.array([[getattr(p.attrs, k) for k in ATTR_KEYS] for p in players], float)
        styles = np.array([[c.style.press, c.style.line, c.style.directness, c.style.width, c.style.tempo]
                           for c in self.clubs])
        s1 = int(rng.integers(1, 6))
        s2 = int(rng.integers(2, 8))
        p1_end = (45 + s1) * 60_000
        sub_plan = []
        injury_plan: list[int | None] = []
        for _ in range(2):
            n = int(rng.integers(3, 6))
            sub_plan.append(sorted(int(m) for m in rng.uniform(55, 85, size=n)))
            injury_plan.append(int(rng.uniform(10, 85)) if rng.random() < 0.05 else None)
        self.s = EngineState(
            t=0, period=1, p1_end=p1_end, p2_start=p1_end, p2_end=p1_end + (45 + s2) * 60_000,
            ids=[p.id for p in players], roles=[p.role for p in players],
            positions=[p.position for p in players], active=np.ones(22, bool),
            pos=np.zeros((22, 2)), vel=np.zeros((22, 2)), attrs=attrs, slots=slots,
            on_since=np.zeros(22), offsets=np.zeros((22, 2)), next_offset_t=0, styles=styles,
            tactic_flags=[set(), set()], ball=np.array([52.5, 34.0, 0.0]), owner=-1, flight=None,
            restart=None, possession_team=0, possession_id=0, last_touch_team=0, next_decision_t=0,
            carry_target=None, carry_start=None, carry_t0=0, pressing=False, pressure_flagged=set(),
            tackle_cooldown=np.zeros(22), score=[0, 0], reds=[0, 0], yellows={}, last_foul={},
            subs_made=[0, 0], sub_plan=sub_plan, injury_plan=injury_plan, bench=benches,
            beats=list(beats or []), beats_done=[not (rng.random() < b.prob) for b in (beats or [])],
            seq=0, done=False, rng=rng,
        )
        self._kickoff_positions()
        self.emit(EventType.period_start, None, None, outcome=Outcome.none)
        setpieces.begin_restart(self, "kickoff", 0, np.array([52.5, 34.0]), delay_ms=0)

    # ------------------------------------------------------------------ helpers
    @property
    def t(self) -> int:
        return self.s.t

    @property
    def done(self) -> bool:
        return self.s.done

    def team_of(self, i: int) -> int:
        return 0 if i < 11 else 1

    def team_idx(self, k: int) -> np.ndarray:
        cache = self.s.overrides.get("_idx")
        if cache is None:
            cache = [np.flatnonzero(self.s.active[:11]), np.flatnonzero(self.s.active[11:]) + 11]
            self.s.overrides["_idx"] = cache
        return cache[k]

    def invalidate(self) -> None:
        self.s.overrides.pop("_idx", None)
        self.s.overrides.pop("_shape", None)
        self.s.overrides.pop("_vmax", None)

    def attacking_right(self, k: int) -> bool:
        return (k == 0) == (self.s.period == 1)

    def minute(self) -> int:
        s = self.s
        if s.period == 1:
            return s.t // 60_000
        return 45 + (s.t - s.p2_start) // 60_000

    def max_speed_all(self) -> np.ndarray:
        s = self.s
        cache = s.overrides.get("_vmax")
        if cache is None or s.t - cache[0] >= 1000:
            cache = (s.t, self.max_speed(np.arange(22)))
            s.overrides["_vmax"] = cache
        return cache[1]

    def max_speed(self, idx: np.ndarray) -> np.ndarray:
        s = self.s
        pace = s.attrs[idx, A["pace"]]
        stamina = s.attrs[idx, A["stamina"]]
        played = (s.t - s.on_since[idx]) / 60_000
        fatigue = 0.12 * np.clip(played / 95, 0, 1) * np.clip(1.3 - stamina / 99, 0.3, 1.0)
        return (6.4 + 3.1 * pace / 99) * (1 - fatigue)

    def style(self, k: int) -> dict[str, float]:
        p, line, d, w, tempo = self.s.styles[k]
        return {"press": p, "line": line, "directness": d, "width": w, "tempo": tempo}

    def emit(self, etype: EventType, team: int | None, player: int | None, other: int | None = None,
             x: float | None = None, y: float | None = None, end_x: float | None = None,
             end_y: float | None = None, outcome: Outcome = Outcome.success, **q) -> Event:
        s = self.s
        s.seq += 1
        q["minute"] = self.minute()
        ev = Event(
            id=event_id(self.fixture_id, s.seq), match_id=self.fixture_id, seq=s.seq, t=s.t,
            period=s.period, type=etype, team_id=None if team is None else self.club_ids[team],
            player_id=None if player is None else s.ids[player],
            other_player_id=None if other is None else s.ids[other],
            x=None if x is None else round(float(x), 2), y=None if y is None else round(float(y), 2),
            end_x=None if end_x is None else round(float(end_x), 2),
            end_y=None if end_y is None else round(float(end_y), 2),
            outcome=outcome, possession_id=s.possession_id,
            qualifiers={k: (round(float(v), 4) if isinstance(v, (float, np.floating)) else
                            (bool(v) if isinstance(v, (bool, np.bool_)) else v)) for k, v in q.items()},
        )
        self._events.append(ev)
        return ev

    def set_possession(self, k: int) -> None:
        s = self.s
        if k != s.possession_team:
            s.possession_team = k
            s.possession_id += 1
        s.last_touch_team = k

    def give_ball(self, i: int, delay_ms: int | None = None) -> None:
        s = self.s
        s.owner = i
        s.flight = None
        s.carry_target = None
        s.pressure_flagged = set()
        self.set_possession(self.team_of(i))
        tempo = s.styles[self.team_of(i), 4]
        if delay_ms is None:
            delay_ms = int((2.2 + 2.2 * (1 - tempo)) * 1000 * s.rng.uniform(0.7, 1.3))
        s.next_decision_t = s.t + delay_ms
        k = self.team_of(i)
        s.pressing = bool(s.rng.random() < s.styles[1 - k, 0] * 0.35)

    def _kickoff_positions(self) -> None:
        s = self.s
        for k in (0, 1):
            idx = np.arange(11) + 11 * k
            s.pos[idx] = shape.kickoff_positions(s.slots[idx], self.attacking_right(k))
        s.vel[:] = 0

    # --------------------------------------------------------------- snapshots
    def snapshot(self) -> EngineState:
        return self.s.copy()

    def restore(self, state: EngineState) -> None:
        self.s = state.copy()
        self._events = []

    def override(self, tactics: dict[str, StyleVector] | None = None,
                 shift: dict[str, tuple[float, float]] | None = None,
                 flip_next_event: str | None = None, flip_team: str | None = None) -> None:
        s = self.s
        for club_id, sv in (tactics or {}).items():
            k = self.club_ids.index(club_id)
            s.styles[k] = [sv.press, sv.line, sv.directness, sv.width, sv.tempo]
            s.tactic_flags[k].add("locked")
        for pid, (dx, dy) in (shift or {}).items():
            i = s.ids.index(pid)
            s.overrides.setdefault("shift", {})[i] = (dx, dy)
        if flip_next_event:
            team = self.club_ids.index(flip_team) if flip_team else -1
            s.overrides["flip"] = {"type": flip_next_event, "until": s.t + 3000, "team": team}

    def state(self) -> MatchState:
        s = self.s
        return MatchState(
            match_id=self.fixture_id, t=s.t, period=s.period, home_goals=s.score[0], away_goals=s.score[1],
            home_red=s.reds[0], away_red=s.reds[1], possession_team=self.club_ids[s.possession_team],
            game_state_hash=state_hash(home_goals=s.score[0], away_goals=s.score[1], home_red=s.reds[0],
                                       away_red=s.reds[1], subs_count=sum(s.subs_made), period=s.period),
        )

    # -------------------------------------------------------------------- tick
    def step(self) -> tuple[RawFrame | None, list[Event]]:
        s = self.s
        if s.done:
            return None, []
        self._events = []
        s.t += TICK_MS
        self._clock()
        if not s.done:
            setpieces.scheduled_changes(self)
            self._tactics()
            if s.restart is not None:
                setpieces.tick_restart(self)
            elif s.flight is not None:
                self._tick_flight()
            elif s.owner >= 0:
                self._tick_carrier()
                if s.owner >= 0 and s.restart is None:
                    duels.tick(self)
            self._move()
        frame = self._frame()
        return frame, self._events

    def run(self) -> Iterator[tuple[RawFrame | None, list[Event]]]:
        while not self.s.done:
            yield self.step()

    def _frame(self) -> RawFrame:
        s = self.s
        act = s.active
        v = s.vel[act]
        speed = np.sqrt((v * v).sum(axis=1))
        return RawFrame(self.fixture_id, s.t, s.ball.copy(), s.pos[act].copy(), speed,
                        tuple(i for i, a in zip(s.ids, act) if a))

    def _clock(self) -> None:
        s = self.s
        if s.period == 1 and s.t >= s.p1_end and s.flight is None:
            self.emit(EventType.period_end, None, None, outcome=Outcome.none)
            s.period = 2
            s.p2_start = s.t
            s.p2_end = s.t + (s.p2_end - s.p1_end)
            s.owner = -1
            self._kickoff_positions()
            self.emit(EventType.period_start, None, None, outcome=Outcome.none)
            setpieces.begin_restart(self, "kickoff", 1, np.array([52.5, 34.0]), delay_ms=0)
        elif s.period == 2 and s.t >= s.p2_end and s.flight is None:
            self.emit(EventType.period_end, None, None, outcome=Outcome.none)
            s.done = True

    def _tactics(self) -> None:
        s = self.s
        if s.t % 60_000:
            return
        m = self.minute()
        for k in (0, 1):
            flags = s.tactic_flags[k]
            if "locked" in flags:
                continue
            diff = s.score[k] - s.score[1 - k]
            if m >= 60 and diff < 0 and "chasing" not in flags:
                s.styles[k, 0] = min(1.0, s.styles[k, 0] + 0.2)
                s.styles[k, 2] = min(1.0, s.styles[k, 2] + 0.15)
                s.styles[k, 1] = min(1.0, s.styles[k, 1] + 0.1)
                flags.add("chasing")
            if m >= 70 and diff > 0 and "sitting" not in flags:
                s.styles[k, 1] = max(0.0, s.styles[k, 1] - 0.15)
                flags.add("sitting")

    # ----------------------------------------------------------------- motion
    def _targets(self) -> np.ndarray:
        s = self.s
        if s.t >= s.next_offset_t:
            s.offsets = s.rng.normal(0, 1.8, size=(22, 2))
            s.next_offset_t = s.t + 3000
        cache = s.overrides.get("_shape")
        if cache is None or s.t - cache[0] >= 400:
            base = s.pos.copy()
            for k in (0, 1):
                idx = self.team_idx(k)
                st = s.styles[k]
                in_poss = (s.possession_team == k) and s.restart is None or (
                    s.restart is not None and s.restart.team == k)
                is_gk = np.array([s.positions[i] == "GK" for i in idx])
                base[idx] = shape.team_targets(s.slots[idx], is_gk, s.ball, self.attacking_right(k),
                                               in_poss, st[1], st[3], s.offsets[idx])
            cache = (s.t, base)
            s.overrides["_shape"] = cache
        tgt = cache[1].copy()
        for i, (dx, dy) in s.overrides.get("shift", {}).items():
            tgt[i] += (dx, dy)
        ball2 = s.ball[:2]
        if s.restart is None:
            if s.owner >= 0:
                k = 1 - self.team_of(s.owner)
                opp = self.team_idx(k)
                d = np.linalg.norm(s.pos[opp] - ball2, axis=1)
                order = opp[np.argsort(d)]
                n_press = 2 if s.pressing else 1
                own_goal = np.array([0.0 if self.attacking_right(k) else PITCH_LENGTH, 34.0])
                carrier_deep = (ball2[0] < 35) if self.attacking_right(k) else (ball2[0] > 70)
                for j, i in enumerate(order[:n_press]):
                    if s.pressing or j == 0:
                        gap = 0.8 if s.pressing else (1.6 if carrier_deep else 3.0)
                        v = own_goal - ball2
                        tgt[i] = ball2 + v / (np.linalg.norm(v) + 1e-9) * gap
                gk = opp[0] if s.positions[opp[0]] == "GK" else None
                if gk is not None:
                    goal = np.array([0.0 if self.attacking_right(k) else PITCH_LENGTH, 34.0])
                    off = ball2 - goal
                    dist_g = float(np.sqrt(off @ off))
                    if dist_g < 20:
                        tgt[gk] = goal + off / (dist_g + 1e-9) * min(6.0, 0.35 * dist_g)
                if s.carry_target is not None:
                    tgt[s.owner] = s.carry_target
                else:
                    tgt[s.owner] = s.pos[s.owner]
            elif s.flight is not None:
                f = s.flight
                if f.target >= 0:
                    tgt[f.target] = f.end
                if f.interceptor >= 0:
                    tgt[f.interceptor] = f.end
                for k in (0, 1):
                    idx = self.team_idx(k)
                    d = np.linalg.norm(s.pos[idx] - f.end, axis=1)
                    if f.kind in ("clearance", "loose"):
                        tgt[idx[np.argmin(d)]] = f.end
        np.minimum(np.maximum(tgt, -1.0), [PITCH_LENGTH + 1, PITCH_WIDTH + 1], out=tgt)
        return tgt

    def _move(self) -> None:
        s = self.s
        act = np.flatnonzero(s.active)
        tgt = self._targets()[act]
        pos = s.pos[act]
        vel = s.vel[act]
        delta = tgt - pos
        dist = np.sqrt((delta * delta).sum(axis=1))
        vmax = self.max_speed_all()[act]
        want = np.minimum(vmax, 0.42 * dist)
        urgent: list[int] = []
        if s.flight is not None:
            urgent += [s.flight.target, s.flight.interceptor]
        if s.owner >= 0 and s.restart is None:
            opp = self.team_idx(1 - self.team_of(s.owner))
            dd = s.pos[opp] - s.ball[:2]
            near = opp[np.argsort((dd * dd).sum(axis=1))[: (2 if s.pressing else 1)]]
            urgent += [int(x) for x in near]
        pos_in_act = {int(a): n for n, a in enumerate(act)}
        for u in urgent:
            n = pos_in_act.get(u)
            if n is not None:
                want[n] = vmax[n]
        if s.owner >= 0 and s.carry_target is not None:
            n = pos_in_act.get(s.owner)
            if n is not None:
                want[n] = min(vmax[n] * 0.78, want[n] + 3.0)
        desired = delta * (want / (dist + 1e-9))[:, None]
        dv = desired - vel
        dvn = np.sqrt((dv * dv).sum(axis=1))
        lim = ACCEL * DT
        scale = np.where(dvn > lim, lim / (dvn + 1e-9), 1.0)
        vel = vel + dv * scale[:, None]
        sp = np.sqrt((vel * vel).sum(axis=1))
        vel = vel * np.where(sp > vmax, vmax / (sp + 1e-9), 1.0)[:, None]
        s.vel[act] = vel
        newpos = pos + vel * DT
        np.minimum(np.maximum(newpos, -0.8), [PITCH_LENGTH + 0.8, PITCH_WIDTH + 0.8], out=newpos)
        s.pos[act] = newpos
        if s.owner >= 0 and s.flight is None and s.restart is None:
            v = s.vel[s.owner]
            n = float(np.sqrt(v @ v))
            s.ball[0], s.ball[1] = (s.pos[s.owner] + v / n * 0.5) if n > 0.3 else s.pos[s.owner]
            s.ball[2] = 0.0

    # ----------------------------------------------------------- ball carrier
    def _tick_carrier(self) -> None:
        s = self.s
        i = s.owner
        if s.carry_target is not None:
            done = np.linalg.norm(s.pos[i] - s.carry_target) < 0.8 or s.t - s.carry_t0 > 4000
            if done:
                self.emit(EventType.carry, self.team_of(i), i, x=s.carry_start[0], y=s.carry_start[1],
                          end_x=s.pos[i, 0], end_y=s.pos[i, 1])
                s.carry_target = None
                s.next_decision_t = s.t + int(200 + 300 * s.rng.random())
            return
        if s.t >= s.next_decision_t:
            decide.decide(self, i)

    def flip_active(self, kind: str, team: int) -> bool:
        """True (and consumed) if a Lab override reverses the next `kind` event committed by `team`."""
        s = self.s
        flip = s.overrides.get("flip")
        if flip and flip["type"] == kind and flip["team"] in (-1, team) and s.t <= flip["until"]:
            s.overrides.pop("flip", None)
            return True
        return False

    def start_flight(self, kind: str, passer: int, end: np.ndarray, speed: float, peak: float,
                     target: int, outcome: str, interceptor: int = -1, xg: float = 0.0,
                     intended: int = -1) -> Flight:
        s = self.s
        start = s.ball[:2].copy()
        dist = float(np.linalg.norm(end - start))
        dur = max(200, int(dist / max(speed, 1.0) * 1000))
        s.flight = Flight(kind=kind, start=start, end=np.array(end, float), t0=s.t, t1=s.t + dur, peak=peak,
                          team=self.team_of(passer), passer=passer, target=target, outcome=outcome,
                          interceptor=interceptor, possession_id=s.possession_id, xg=xg, intended=intended)
        s.owner = -1
        s.carry_target = None
        s.last_touch_team = self.team_of(passer)
        return s.flight

    def _tick_flight(self) -> None:
        s = self.s
        f = s.flight
        frac = min(1.0, (s.t - f.t0) / max(1, f.t1 - f.t0))
        s.ball[:2] = f.start + (f.end - f.start) * frac
        s.ball[2] = 4 * f.peak * frac * (1 - frac)
        if s.t >= f.t1:
            setpieces.resolve_flight(self, f)


def simulate_match(fixture_id: str, home: Club, away: Club, seed: int,
                   beats: list[ForcedBeat] | None = None,
                   start_xi: tuple[list[str], list[str]] | None = None,
                   frames: bool = True) -> tuple[list[Event], list[RawFrame]]:
    eng = MatchEngine(fixture_id, home, away, seed, beats=beats, start_xi=start_xi)
    events: list[Event] = list(eng._events)
    out_frames: list[RawFrame] = []
    while not eng.done:
        fr, evs = eng.step()
        events.extend(evs)
        if frames and fr is not None:
            out_frames.append(fr)
    return events, out_frames
