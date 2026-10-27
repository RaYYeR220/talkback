"""The Archivist as a stand-alone agent (Foundry hosted agent / A2A server).

The caller sends the moment and the match's story board in the prompt; the
agent can look up any player or club in the season data of the run the
prompt names (talkback.hosted.runs) with its tools.
"""

from __future__ import annotations

from agent_framework import Agent

from talkback.gallery.agents.archivist import INSTRUCTIONS, archivist_tools
from talkback.gallery.llm import make_client
from talkback.gallery.world import World
from talkback.hosted.runs import RunCache, RunScope, current, default_run, prewarm
from talkback.hosted.runstore import run_dir


class RunWorld:
    """Stands in for a World: every lookup goes to the world of the current prompt's run."""

    def __init__(self, worlds: RunCache[World]):
        self._worlds = worlds

    def __getattr__(self, name: str):
        return getattr(self._worlds.get(current()), name)


def load_world(run_id: str) -> World:
    return World.load(run_dir(run_id) / "world.json")


def build_agent() -> Agent:
    worlds = RunCache(load_world)
    prewarm(worlds, default_run())
    return Agent(client=make_client("strong"), instructions=INSTRUCTIONS, name="archivist",
                 description="Finds the season storylines a moment makes worth saying.",
                 tools=archivist_tools(RunWorld(worlds), board=None), middleware=[RunScope(warm=worlds.get)],
                 default_options={"store": False})
