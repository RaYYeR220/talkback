"""Stats Desk: every number the gallery may say, as an evidence-carrying Fact.

A Fact records its value, the window it covers, how many observations stand
behind it, and the ids of the events it was computed from, so any line on air
can be walked back to the events that justify it.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

import numpy as np

from talkback.models.xt import XTGrid
from talkback.schemas.models import Event, EventType, Fact, Outcome
from talkback.sim.fast import win_probability
from talkback.world.league import Club

EVIDENCE_CAP = 50
SPRINT_MS = 7.0
SPRINT_TICKS = 10
MOMENTUM_HALF_LIFE_MS = 180_000
WP_REFRESH_MS = 5 * 60_000
MAX_STEP_M = 1.2           # ignore teleports at restarts when integrating distance
DEF_ACTIONS = (EventType.tackle, EventType.interception, EventType.foul)

TEAM_METRICS = ("team.xg", "team.shots", "team.shots_on_target", "team.passes", "team.pass_completion",
                "team.ppda", "team.field_tilt", "team.possession", "team.momentum", "team.pressures",
                "team.win_probability")
PLAYER_METRICS = ("player.xg", "player.shots", "player.goals", "player.passes", "player.pass_completion",
                  "player.avg_pass_difficulty", "player.distance_km", "player.top_speed_kmh", "player.sprints",
                  "player.xt_added", "player.tackles_won", "player.pressures")
EVENT_METRICS = ("event.shot_speed_kmh", "event.pass_difficulty", "event.pass_distance_m")
UNITS = {"xg": "xG", "shots": "count", "shots_on_target": "count", "passes": "count", "pass_completion": "ratio",
         "ppda": "ratio", "field_tilt": "ratio", "possession": "ratio", "momentum": "xT", "pressures": "count",
         "win_probability": "probability", "goals": "count", "avg_pass_difficulty": "ratio", "distance_km": "km",
         "top_speed_kmh": "km/h", "sprints": "count", "xt_added": "xT", "tackles_won": "count",
         "shot_speed_kmh": "km/h", "pass_difficulty": "ratio", "pass_distance_m": "m"}

Result = tuple[float, int, list[str]]


def _ratio(num: int, den: int, evidence: list[str]) -> Result:
    if den == 0:
        return 0.0, 0, []
    return num / den, den, evidence


class StatsDesk:
    def __init__(self, match_id: str, home: Club, away: Club, xt: XTGrid):
        self.match_id = match_id
        self.home, self.away = home, away
        self.team_ids = (home.id, away.id)
        self.xt = xt
        self.events: list[Event] = []
        self.score = [0, 0]
        self.reds = [0, 0]
        self._wp: tuple[int, tuple[float, float, float]] | None = None
        self._now = 0
        # tracking accumulators
        self._ids: tuple[str, ...] | None = None
        self._prev: np.ndarray | None = None
        self._arr = {k: np.zeros(0) for k in ("dist", "top", "run", "sprints")}
        self._acc: dict[str, dict[str, float]] = {k: defaultdict(float) for k in ("dist", "top", "run", "sprints")}
        self._dist_marks: list[tuple[int, dict[str, float]]] = [(0, {})]

    # ----------------------------------------------------------------- ingest
    def ingest(self, event: Event) -> None:
        self.events.append(event)
        self._now = max(self._now, event.t)
        k = self._team_index(event.team_id)
        if event.type == EventType.goal and k is not None:
            self.score[k] += 1
            self._wp = None
        if event.type == EventType.card and event.outcome == Outcome.red and k is not None:
            self.reds[k] += 1
            self._wp = None

    def ingest_frame(self, frame) -> None:
        self._now = max(self._now, frame.t)
        ids = tuple(frame.ids)
        pos = np.asarray(frame.pos, float)
        speed = np.asarray(frame.speed, float)
        if ids != self._ids:
            self._flush()
            self._ids = ids
            for key in self._arr:
                self._arr[key] = np.array([self._acc[key][pid] for pid in ids], float)
            self._prev = pos.copy()
        step = np.minimum(np.linalg.norm(pos - self._prev, axis=1), MAX_STEP_M)
        a = self._arr
        a["dist"] += step
        a["top"] = np.maximum(a["top"], speed)
        fast = speed > SPRINT_MS
        a["sprints"] += (fast & (a["run"] == SPRINT_TICKS - 1)).astype(float)
        a["run"] = np.where(fast, a["run"] + 1, 0)
        self._prev = pos.copy()
        if frame.t - self._dist_marks[-1][0] >= 10_000:
            self._flush()
            self._dist_marks.append((frame.t, dict(self._acc["dist"])))

    def _flush(self) -> None:
        if self._ids is None:
            return
        for key, arr in self._arr.items():
            for pid, v in zip(self._ids, arr):
                self._acc[key][pid] = float(v)

    # ---------------------------------------------------------------- helpers
    def _team_index(self, team_id: str | None) -> int | None:
        if team_id is None:
            return None
        return self.team_ids.index(team_id) if team_id in self.team_ids else None

    def _attacking_right(self, team_id: str, period: int) -> bool:
        return (team_id == self.team_ids[0]) == (period == 1)

    def _xn(self, e: Event, team_id: str, x: float | None = None) -> float:
        x = e.x if x is None else x
        return x / 105 if self._attacking_right(team_id, e.period) else 1 - x / 105

    def _xt_gain(self, e: Event) -> float:
        ar = self._attacking_right(e.team_id, e.period)
        return self.xt.value(e.end_x, e.end_y, ar) - self.xt.value(e.x, e.y, ar)

    def _other(self, team_id: str) -> str:
        return self.team_ids[1] if team_id == self.team_ids[0] else self.team_ids[0]

    def _win_prob(self, now_t: int) -> tuple[float, float, float]:
        if self._wp is None or now_t - self._wp[0] >= WP_REFRESH_MS:
            minute = int(self.events[-1].qualifiers.get("minute", now_t // 60_000)) if self.events else 0
            p = win_probability(self.home, self.away, minute, (self.score[0], self.score[1]),
                                (self.reds[0], self.reds[1]), n=2000, seed=minute)
            self._wp = (now_t, p)
        return self._wp[1]

    # --------------------------------------------------------------- metrics
    def _team(self, metric: str, team: str, evs: list[Event], now_t: int) -> Result:
        mine = [e for e in evs if e.team_id == team]
        shots = [e for e in mine if e.type == EventType.shot]
        passes = [e for e in mine if e.type == EventType.pass_]
        if metric == "team.xg":
            return sum(float(e.qualifiers.get("xg", 0.0)) for e in shots), len(shots), [e.id for e in shots]
        if metric == "team.shots":
            return float(len(shots)), len(shots), [e.id for e in shots]
        if metric == "team.shots_on_target":
            on = [e for e in shots if e.outcome in (Outcome.goal, Outcome.saved)]
            return float(len(on)), len(shots), [e.id for e in on]
        if metric == "team.passes":
            return float(len(passes)), len(passes), [e.id for e in passes]
        if metric == "team.pass_completion":
            ok = [e for e in passes if e.outcome == Outcome.success]
            return _ratio(len(ok), len(passes), [e.id for e in passes])
        if metric == "team.ppda":
            opp = self._other(team)
            opp_passes = [e for e in evs if e.type == EventType.pass_ and e.team_id == opp and e.x is not None
                          and self._xn(e, opp) < 0.6]
            actions = [e for e in mine if e.type in DEF_ACTIONS and e.x is not None and self._xn(e, team) > 0.4]
            return _ratio(len(opp_passes), len(actions), [e.id for e in actions])
        if metric == "team.field_tilt":
            final = lambda t: [e for e in evs if e.type == EventType.pass_ and e.team_id == t and e.x is not None
                               and self._xn(e, t) > 2 / 3]
            a, b = final(team), final(self._other(team))
            return _ratio(len(a), len(a) + len(b), [e.id for e in a])
        if metric == "team.possession":
            all_passes = [e for e in evs if e.type == EventType.pass_]
            return _ratio(len(passes), len(all_passes), [e.id for e in passes])
        if metric == "team.momentum":
            moves = [e for e in mine if e.end_x is not None and e.x is not None and
                     ((e.type == EventType.pass_ and e.outcome == Outcome.success) or e.type == EventType.carry)]
            val = sum(self._xt_gain(e) * 0.5 ** ((now_t - e.t) / MOMENTUM_HALF_LIFE_MS) for e in moves)
            return float(val), len(moves), [e.id for e in moves]
        if metric == "team.pressures":
            pr = [e for e in mine if e.type == EventType.pressure]
            return float(len(pr)), len(pr), [e.id for e in pr]
        if metric == "team.win_probability":
            hw, dr, aw = self._win_prob(now_t)
            return (hw if team == self.team_ids[0] else aw), 2000, []
        raise KeyError(metric)

    def _player(self, metric: str, pid: str, evs: list[Event], window: tuple[int, int]) -> Result:
        mine = [e for e in evs if e.player_id == pid]
        shots = [e for e in mine if e.type == EventType.shot]
        passes = [e for e in mine if e.type == EventType.pass_]
        if metric == "player.xg":
            return sum(float(e.qualifiers.get("xg", 0.0)) for e in shots), len(shots), [e.id for e in shots]
        if metric == "player.shots":
            return float(len(shots)), len(shots), [e.id for e in shots]
        if metric == "player.goals":
            g = [e for e in mine if e.type == EventType.goal]
            return float(len(g)), len(g), [e.id for e in g]
        if metric == "player.passes":
            return float(len(passes)), len(passes), [e.id for e in passes]
        if metric == "player.pass_completion":
            ok = [e for e in passes if e.outcome == Outcome.success]
            return _ratio(len(ok), len(passes), [e.id for e in passes])
        if metric == "player.avg_pass_difficulty":
            q = [e for e in passes if "xpass" in e.qualifiers]
            if not q:
                return 0.0, 0, []
            return float(np.mean([1 - float(e.qualifiers["xpass"]) for e in q])), len(q), [e.id for e in q]
        if metric == "player.xt_added":
            moves = [e for e in mine if e.end_x is not None and e.x is not None and
                     ((e.type == EventType.pass_ and e.outcome == Outcome.success) or e.type == EventType.carry)]
            return float(sum(self._xt_gain(e) for e in moves)), len(moves), [e.id for e in moves]
        if metric == "player.tackles_won":
            t = [e for e in mine if e.type == EventType.tackle and e.outcome == Outcome.success]
            return float(len(t)), len(t), [e.id for e in t]
        if metric == "player.pressures":
            pr = [e for e in mine if e.type == EventType.pressure]
            return float(len(pr)), len(pr), [e.id for e in pr]
        self._flush()
        if metric == "player.distance_km":
            start = self._dist_at(window[0]).get(pid, 0.0)
            end = self._acc["dist"].get(pid, 0.0) if window[1] >= self._now else self._dist_at(window[1]).get(pid, 0.0)
            ticks = (min(window[1], self._now) - window[0]) // 100
            return (end - start) / 1000, int(max(0, ticks)), []
        if metric == "player.top_speed_kmh":
            return self._acc["top"].get(pid, 0.0) * 3.6, int(self._now // 100), []
        if metric == "player.sprints":
            return float(self._acc["sprints"].get(pid, 0.0)), int(self._now // 100), []
        raise KeyError(metric)

    def _dist_at(self, t: int) -> dict[str, float]:
        best = self._dist_marks[0][1]
        for mt, snap in self._dist_marks:
            if mt <= t:
                best = snap
            else:
                break
        return best

    def _event_level(self, metric: str, subject: str, evs: list[Event]) -> Result:
        if metric == "event.shot_speed_kmh":
            cand = [e for e in evs if e.type == EventType.shot and e.player_id == subject]
            if not cand:
                return 0.0, 0, []
            e = cand[-1]
            return float(e.qualifiers.get("shot_speed_ms", 0.0)) * 3.6, 1, [e.id]
        cand = [e for e in evs if e.type == EventType.pass_ and e.player_id == subject]
        if not cand:
            return 0.0, 0, []
        e = cand[-1]
        if metric == "event.pass_difficulty":
            return 1 - float(e.qualifiers.get("xpass", 1.0)), 1, [e.id]
        if metric == "event.pass_distance_m":
            return float(e.qualifiers.get("distance", 0.0)), 1, [e.id]
        raise KeyError(metric)

    def _compute(self, metric: str, subject: str, evs: list[Event], window: tuple[int, int]) -> Fact:
        if metric.startswith("team."):
            value, n, ev = self._team(metric, subject, evs, window[1])
        elif metric.startswith("player."):
            value, n, ev = self._player(metric, subject, evs, window)
        elif metric.startswith("event."):
            value, n, ev = self._event_level(metric, subject, evs)
        else:
            raise KeyError(metric)
        if not np.isfinite(value):
            value, n, ev = 0.0, 0, []
        return Fact(id=f"{self.match_id}:{metric}:{subject}:{window[1]}", match_id=self.match_id, metric=metric,
                    subject=subject, value=round(float(value), 6), unit=UNITS[metric.split(".", 1)[1]],
                    window=window, sample_size=int(n), evidence=ev[-EVIDENCE_CAP:], computed_at=window[1])

    # ------------------------------------------------------------------- API
    def fact(self, metric: str, subject: str) -> Fact | None:
        try:
            return self._compute(metric, subject, self.events, (0, self._now))
        except KeyError:
            return None

    def window_fact(self, metric: str, subject: str, start_t: int, end_t: int) -> Fact:
        evs = [e for e in self.events if start_t <= e.t <= end_t]
        return self._compute(metric, subject, evs, (start_t, end_t))

    def players(self) -> list[str]:
        seen = dict.fromkeys(e.player_id for e in self.events if e.player_id)
        self._flush()
        seen.update(dict.fromkeys(self._acc["dist"]))
        return [p for p in seen if p]

    def facts(self, now_t: int) -> list[Fact]:
        self._now = max(self._now, now_t)
        out = [self._compute(m, t, self.events, (0, now_t)) for t in self.team_ids for m in TEAM_METRICS]
        by_player: dict[str, list[Event]] = defaultdict(list)
        for e in self.events:
            if e.player_id:
                by_player[e.player_id].append(e)
        for pid in self.players():
            evs = by_player.get(pid, [])
            out.extend(self._compute(m, pid, evs, (0, now_t)) for m in PLAYER_METRICS)
        for metric, etype in (("event.shot_speed_kmh", EventType.shot), ("event.pass_difficulty", EventType.pass_),
                              ("event.pass_distance_m", EventType.pass_)):
            last = next((e for e in reversed(self.events) if e.type == etype and e.player_id), None)
            if last is not None:
                out.append(self._compute(metric, last.player_id, by_player[last.player_id], (0, now_t)))
        return out
