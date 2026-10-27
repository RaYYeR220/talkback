"""The Archivist as a stand-alone agent (Foundry hosted agent / A2A server).

The caller sends the moment and the match's story board in the prompt; the
agent can look up any player or club in the season data with its tools.
"""

from __future__ import annotations

from agent_framework import Agent

from talkback.gallery.agents.archivist import INSTRUCTIONS, archivist_tools
from talkback.gallery.llm import make_client
from talkback.gallery.world import World
from talkback.hosted.runstore import run_dir


def build_agent() -> Agent:
    world = World.load(run_dir() / "world.json")
    return Agent(client=make_client("strong"), instructions=INSTRUCTIONS, name="archivist",
                 description="Finds the season storylines a moment makes worth saying.",
                 tools=archivist_tools(world, board=None), default_options={"store": False})
