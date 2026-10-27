"""Paired counterfactual rollouts: replay a moment with and without one change.

Rollout i of the baseline and of the counterfactual share the seed
`seed * 100003 + i` (common random numbers), so the difference between the two
arms is caused by the intervention, not by noise. Game-state tactics are frozen
in both arms for the short horizon.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import Annotated, Callable, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from talkback.schemas.models import EventType
from talkback.sim.engine import EngineState, MatchEngine
from talkback.world.league import StyleVector


class _IV(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FlipEvent(_IV):
    type: Literal["flip_event"] = "flip_event"
    event_type: Literal["interception", "tackle", "shot"]
    team_id: str

    def describe(self) -> str:
        what = {"interception": "the interception does not happen and the pass reaches its target",
                "tackle": "the tackle fails and the carrier keeps the ball",
                "shot": "the shot is not taken and the player keeps the ball"}[self.event_type]
        return f"Next {self.event_type} by {self.team_id} reversed: {what}."


class ShiftPlayer(_IV):
    type: Literal["shift_player"] = "shift_player"
    player_id: str
    dx: float
    dy: float

    def describe(self) -> str:
        return f"{self.player_id} positioned {self.dx:+.1f} m / {self.dy:+.1f} m from where he was."


class Tactic(_IV):
    type: Literal["tactic"] = "tactic"
    team_id: str
    press: float | None = None
    line: float | None = None

    def describe(self) -> str:
        parts = [f"press {self.press:.2f}" if self.press is not None else "",
                 f"line height {self.line:.2f}" if self.line is not None else ""]
        return f"{self.team_id} plays with " + " and ".join(p for p in parts if p) + "."


Intervention = Annotated[FlipEvent | ShiftPlayer | Tactic, Field(discriminator="type")]


class RolloutMetrics(BaseModel):
    """Means over rollouts. `xt_gain` is the possession-weighted threat balance over the
    horizon: the ball's expected-threat value while the team has it, minus the
    opponent's while they have it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_for: float
    goal_against: float
    xt_gain: float


def is_supported(ci: tuple[float, float]) -> bool:
    return ci[0] > 0 or ci[1] < 0


def _apply(eng: MatchEngine, iv: FlipEvent | ShiftPlayer | Tactic) -> None:
    if isinstance(iv, Tactic):
        k = eng.club_ids.index(iv.team_id)
        p, line, d, w, tempo = (float(v) for v in eng.s.styles[k])
        sv = StyleVector(press=p if iv.press is None else iv.press, line=line if iv.line is None else iv.line,
                         directness=d, width=w, tempo=tempo)
        eng.override(tactics={iv.team_id: sv})
    elif isinstance(iv, ShiftPlayer):
        eng.override(shift={iv.player_id: (iv.dx, iv.dy)})
    else:
        eng.override(flip_next_event=iv.event_type, flip_team=iv.team_id)


def _one(eng: MatchEngine, snapshot: EngineState, iv, team_id: str, horizon_ms: int,
         seed: int) -> tuple[float, float, float]:
    eng.restore(snapshot)
    eng.s.rng = np.random.default_rng(seed)
    for flags in eng.s.tactic_flags:
        flags.add("locked")
    if iv is not None:
        _apply(eng, iv)
    k = eng.club_ids.index(team_id)
    end = eng.t + horizon_ms
    gf = ga = 0.0
    threat = 0.0
    ticks = 0
    while eng.t < end and not eng.done:
        _, events = eng.step()
        for e in events:
            if e.type == EventType.goal:
                if e.team_id == team_id:
                    gf = 1.0
                else:
                    ga = 1.0
        bx, by = float(eng.s.ball[0]), float(eng.s.ball[1])
        if eng.s.possession_team == k:
            threat += eng.xt.value(bx, by, eng.attacking_right(k))
        else:
            threat -= eng.xt.value(bx, by, eng.attacking_right(1 - k))
        ticks += 1
    return gf, ga, threat / max(1, ticks)


def _chunk(args) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
    factory, snapshot, iv, team_id, horizon_ms, seeds = args
    eng = factory()
    return [(_one(eng, snapshot, None, team_id, horizon_ms, sd), _one(eng, snapshot, iv, team_id, horizon_ms, sd))
            for sd in seeds]


def _ci(diff: np.ndarray) -> tuple[float, float]:
    if len(diff) < 2 or np.all(diff == diff[0]):
        m = float(diff.mean()) if len(diff) else 0.0
        return (m, m)
    m = float(diff.mean())
    h = 1.96 * float(diff.std(ddof=1)) / np.sqrt(len(diff))
    return (round(m - h, 6), round(m + h, 6))


def run_counterfactual(snapshot: EngineState, engine_factory: Callable[[], MatchEngine],
                       intervention: FlipEvent | ShiftPlayer | Tactic, team_id: str, n: int = 240,
                       horizon_s: int = 20, seed: int = 0, workers: int = 0,
                       pool: ProcessPoolExecutor | None = None
                       ) -> tuple[RolloutMetrics, RolloutMetrics, dict]:
    seeds = [seed * 100003 + i for i in range(n)]
    horizon_ms = horizon_s * 1000
    if workers > 0 or pool is not None:
        w = workers or pool._max_workers  # type: ignore[attr-defined]
        parts = [seeds[i::w] for i in range(w)]
        jobs = [(engine_factory, snapshot, intervention, team_id, horizon_ms, p) for p in parts if p]
        if pool is not None:
            chunks = list(pool.map(_chunk, jobs))
        else:
            with ProcessPoolExecutor(max_workers=w) as ex:
                chunks = list(ex.map(_chunk, jobs))
        by_seed = {}
        for part, res in zip([p for p in parts if p], chunks):
            by_seed.update(dict(zip(part, res)))
        pairs = [by_seed[s] for s in seeds]
    else:
        pairs = _chunk((engine_factory, snapshot, intervention, team_id, horizon_ms, seeds))
    base = np.array([b for b, _ in pairs])
    cf = np.array([c for _, c in pairs])
    diff = cf - base
    stats = {
        "effect_goal_for": float(diff[:, 0].mean()), "ci95_goal_for": _ci(diff[:, 0]),
        "effect_goal_against": float(diff[:, 1].mean()), "ci95_goal_against": _ci(diff[:, 1]),
        "effect_xt": round(float(diff[:, 2].mean()), 6), "ci95_xt": _ci(diff[:, 2]),
        "n": n, "horizon_s": horizon_s,
    }
    mean = lambda a: RolloutMetrics(goal_for=float(a[:, 0].mean()), goal_against=float(a[:, 1].mean()),
                                    xt_gain=round(float(a[:, 2].mean()), 6))
    return mean(base), mean(cf), stats
