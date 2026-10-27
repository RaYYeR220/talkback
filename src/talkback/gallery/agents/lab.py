"""Lab: earns the gallery's causal words by replaying a moment with one thing changed.

The model chooses an experiment from a typed menu; the simulator decides the
answer. A causal claim is only ever marked supported when the 95% interval of
the paired effect excludes zero — that check is code, not prompt.
"""

from __future__ import annotations

import asyncio
import zlib
from concurrent.futures import ProcessPoolExecutor
from typing import Annotated, Callable, Literal

from agent_framework import Agent, tool
from pydantic import BaseModel, Field

from talkback.gallery.jsonio import ParseError, parse_json
from talkback.gallery.snapshots import SnapshotStore, engine_factory
from talkback.gallery.world import World
from talkback.schemas.models import Event, EventType, Experiment, Outcome
from talkback.sim.rollout import FlipEvent, Tactic, is_supported, run_counterfactual

ExperimentKind = Literal["complete_intercepted_pass", "cancel_shot", "keep_pressing", "sit_deeper"]

INSTRUCTIONS = (
    "You are the Lab in a football production gallery. You can replay a moment of the match many times in "
    "the simulator with one thing changed, and measure the difference. Pick at most two experiments from "
    "the menu that would show why this moment mattered, run them with the run_experiment tool, then state "
    "the conclusion in one sentence. Say there is a clear effect only if the tool reports supported=true; "
    "otherwise say 'no clear effect'. Answer only with JSON: "
    '{"experiments": ["<experiment id>"], "conclusion": "...", "supported": true}'
)


class LabAnswer(BaseModel):
    experiments: list[str]
    conclusion: str = Field(max_length=300)
    supported: bool


class LabResult(BaseModel):
    experiments: list[Experiment]
    conclusion: str
    supported: bool
    status: str = "ok"


class LabBackend:
    def __init__(self, store: SnapshotStore, world: World, event_lookup: Callable[[str], Event | None],
                 pool: ProcessPoolExecutor | None = None, n: int = 160, horizon_s: int = 15):
        self.store = store
        self.world = world
        self.event_lookup = event_lookup
        self.pool = pool
        self.n = n
        self.horizon_s = horizon_s
        self.results: dict[str, Experiment] = {}
        self._count = 0

    def run(self, moment_id: str, match_id: str, event_id: str, kind: str) -> list[Experiment]:
        ev = self.event_lookup(event_id)
        if ev is None:
            raise ValueError(f"unknown event {event_id}")
        _, h, a = self.world.fixture(match_id)
        home, away = self.world.club(h), self.world.club(a)
        team = ev.team_id
        other = a if team == h else h
        horizon, n = self.horizon_s, self.n
        if kind == "complete_intercepted_pass":
            if not (ev.type == EventType.pass_ and ev.outcome == Outcome.fail):
                raise ValueError("complete_intercepted_pass needs a failed pass event")
            anchor, iv, perspective = ev.t + 100, FlipEvent(event_type="interception", team_id=other), team
        elif kind == "cancel_shot":
            if ev.type != EventType.shot:
                raise ValueError("cancel_shot needs a shot event")
            anchor, iv, perspective = ev.t + 100, FlipEvent(event_type="shot", team_id=team), team
        elif kind in ("keep_pressing", "sit_deeper"):
            k = 0 if team == h else 1
            state = self.store.state_at(match_id, ev.t, home, away)
            if state is None:
                raise ValueError("no snapshot before this moment")
            press, line = float(state.styles[k][0]), float(state.styles[k][1])
            iv = (Tactic(team_id=team, press=min(1.0, press + 0.3)) if kind == "keep_pressing"
                  else Tactic(team_id=team, line=max(0.0, line - 0.3)))
            anchor, perspective, horizon, n = ev.t, team, 120, 60
        else:
            raise ValueError(f"unknown experiment {kind}")
        state = self.store.state_at(match_id, anchor, home, away)
        if state is None:
            raise ValueError("no snapshot before this moment")
        base, cf, st = run_counterfactual(state, engine_factory(match_id, home, away), iv, perspective, n=n,
                                          horizon_s=horizon, seed=zlib.crc32(event_id.encode()) % 10_000, pool=self.pool)
        self._count += 1
        out = []
        for metric, b, c, eff, ci in (("threat", base.xt_gain, cf.xt_gain, st["effect_xt"], st["ci95_xt"]),
                                      ("goal_for", base.goal_for, cf.goal_for, st["effect_goal_for"], st["ci95_goal_for"])):
            x = Experiment(id=f"X-{match_id}-{ev.seq}-{kind}-{metric}", moment_id=moment_id,
                           intervention={"kind": kind, "event_id": event_id, "team_id": perspective,
                                         "describe": iv.describe()},
                           n=n, metric=metric, baseline=round(b, 6), counterfactual=round(c, 6),
                           effect=round(eff, 6), ci95=(round(float(ci[0]), 6), round(float(ci[1]), 6)),
                           seed=zlib.crc32(event_id.encode()) % 10_000)
            self.results[x.id] = x
            out.append(x)
        return out


def lab_tools(backend: LabBackend, moment_id: str, match_id: str) -> list:
    @tool(description="Replay the moment in the simulator with one change and measure the paired effect.")
    async def run_experiment(
        event_id: Annotated[str, Field(description="id of the event to change (a failed pass or a shot)")],
        experiment: Annotated[ExperimentKind, Field(description="which change to make")],
    ) -> dict:
        try:
            xs = await asyncio.to_thread(backend.run, moment_id, match_id, event_id, experiment)
        except ValueError as exc:
            return {"error": str(exc)}
        return {x.id: {"metric": x.metric, "effect": x.effect, "ci95": x.ci95, "supported": is_supported(x.ci95),
                       "change": x.intervention["describe"]} for x in xs}

    return [run_experiment]


def make_lab(client, backend: LabBackend, moment_id: str, match_id: str) -> Agent:
    return Agent(client=client, instructions=INSTRUCTIONS, name="lab",
                 description="Counterfactual experiments on match moments.",
                 tools=lab_tools(backend, moment_id, match_id))


def finalize(answer_text: str, backend: LabBackend) -> LabResult:
    """Keep only experiments that really ran; `supported` is recomputed from their intervals."""
    try:
        answer = parse_json(answer_text, LabAnswer)
    except ParseError:
        return LabResult(experiments=[], conclusion="", supported=False, status="parse")
    xs = [backend.results[i] for i in answer.experiments if i in backend.results]
    supported = any(x.metric == "threat" and is_supported(x.ci95) for x in xs)
    conclusion = answer.conclusion if supported or not answer.supported else "no clear effect"
    return LabResult(experiments=xs, conclusion=conclusion, supported=supported)
