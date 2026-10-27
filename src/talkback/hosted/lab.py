"""The Lab as a stand-alone agent (Foundry hosted agent / A2A server).

The model picks and runs experiments with its tool; a middleware then seals
the answer: the reply carries the experiments exactly as the simulator
returned them and `supported` recomputed from their intervals, so no number
ever passes through the model's retelling. Experiments run on the run the
prompt names (talkback.hosted.runs).
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

from agent_framework import (
    Agent, AgentContext, AgentMiddleware, AgentResponse, AgentResponseUpdate, Message, ResponseStream, tool,
)
from pydantic import Field

from talkback.gallery.agents.lab import INSTRUCTIONS, ExperimentKind, LabBackend, finalize
from talkback.gallery.llm import make_client
from talkback.gallery.world import World
from talkback.hosted.runs import RunCache, RunScope, current, default_run, prewarm, run_of
from talkback.hosted.runstore import run_dir, snapshot_store
from talkback.schemas.models import Event
from talkback.sim.rollout import is_supported

REMOTE_INSTRUCTIONS = INSTRUCTIONS + (
    " The prompt names the match id and the moment id; pass them to run_experiment."
)


def remote_tools(backends: RunCache[LabBackend]) -> list:
    @tool(description="Replay a moment in the simulator with one change and measure the paired effect.")
    async def run_experiment(
        match_id: Annotated[str, Field(description="fixture id, e.g. MD12-F03")],
        moment_id: Annotated[str, Field(description="moment id from the prompt")],
        event_id: Annotated[str, Field(description="id of the event to change (a failed pass or a shot)")],
        experiment: Annotated[ExperimentKind, Field(description="which change to make")],
    ) -> dict:
        backend = backends.get(current())
        try:
            xs = await asyncio.to_thread(backend.run, moment_id, match_id, event_id, experiment)
        except ValueError as exc:
            return {"error": str(exc)}
        return {x.id: {"metric": x.metric, "effect": x.effect, "ci95": x.ci95, "supported": is_supported(x.ci95),
                       "change": x.intervention["describe"]} for x in xs}

    return [run_experiment]


class SealResult(AgentMiddleware):
    def __init__(self, backends: RunCache[LabBackend]):
        self.backends = backends

    async def process(self, context: AgentContext, call_next) -> None:
        await call_next()
        if context.result is None:
            return
        run = run_of(context.messages)
        if not context.stream:
            context.result = AgentResponse(messages=[Message(role="assistant", contents=[self._seal(
                context.result.text, run)])])
            return
        # The Foundry host streams. The model's own words are read to the end and dropped; the caller gets one
        # update carrying the sealed result.
        inner = context.result

        async def sealed():
            answer = await inner.get_final_response()
            yield AgentResponseUpdate(role="assistant", contents=[{"type": "text", "text": self._seal(answer.text, run)}])

        context.result = ResponseStream(sealed(), finalizer=AgentResponse.from_updates)

    def _seal(self, answer_text: str, run: str) -> str:
        return finalize(answer_text, self.backends.get(run)).model_dump_json()


def load_backend(run_id: str) -> LabBackend:
    root = run_dir(run_id)
    world = World.load(root / "world.json")
    events: dict[str, Event] = {}
    with open(root / "events.jsonl", encoding="utf-8") as fh:
        for line in fh:
            e = Event.model_validate(json.loads(line))
            events[e.id] = e
    return LabBackend(snapshot_store(root, run_id), world, events.get, n=120, horizon_s=15)


def build_agent() -> Agent:
    backends = RunCache(load_backend)
    prewarm(backends, default_run())
    return Agent(client=make_client("strong"), instructions=REMOTE_INSTRUCTIONS, name="lab",
                 description="Counterfactual experiments on match moments.", tools=remote_tools(backends),
                 middleware=[RunScope(warm=backends.get), SealResult(backends)], default_options={"store": False})
