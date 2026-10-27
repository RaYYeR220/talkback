"""Archivist: decides which of the season's storylines this moment makes worth saying."""

from __future__ import annotations

from typing import Annotated

from agent_framework import Agent, tool
from pydantic import BaseModel, Field

from talkback.gallery.jsonio import ParseError, parse_json
from talkback.gallery.spotter import Moment
from talkback.gallery.storyboard import StoryBoard
from talkback.gallery.world import World
from talkback.schemas.models import Storyline

INSTRUCTIONS = (
    "You are the Archivist in a football production gallery. You know the season: careers, previous clubs, "
    "the table, streaks and records. For the moment you are given, choose which storylines from the story "
    "board are worth saying now, and why now, in one short clause each. Prefer stories that a fan of either "
    "club would feel cheated to miss (milestones, farewells, debuts, reunions, races, relegation stakes). "
    "Never invent a storyline or a number: use only storyline ids from the board. Use the tools if you need "
    "more context. Answer only with JSON: "
    '{"storylines": [{"storyline_id": "...", "why_now": "..."}]} (an empty list is a valid answer).'
)


class StoryPick(BaseModel):
    storyline_id: str
    why_now: str = Field(max_length=200)


class ArchivistAnswer(BaseModel):
    storylines: list[StoryPick]


def archivist_tools(world: World, board: StoryBoard | None) -> list:
    """Season lookups, plus the story board when the agent runs next to it (it is in the prompt otherwise)."""
    @tool(description="Storylines on this match's story board, with their status (latent, live, surfaced, resolved).")
    def story_board() -> list[dict]:
        return [{"id": s.id, "kind": s.kind, "status": s.status, "summary": s.summary, "facts": s.facts}
                for s in board.stories.values()]

    @tool(description="Career and season profile of one player.")
    def player_profile(player_id: Annotated[str, Field(description="player id, e.g. C05-P20")]) -> dict:
        p = world.player(player_id)
        season = world.player_season.get(player_id, {})
        return {"name": p.name, "club": world.club(p.club_id).name, "age": p.age, "position": p.position,
                "career_goals": p.career.career_goals, "career_apps": p.career.career_apps,
                "previous_clubs": [world.club(c).name for c in p.career.previous_clubs], "season": season}

    @tool(description="Table position, points, form and manager of one club.")
    def club_profile(club_id: Annotated[str, Field(description="club id, e.g. C07")]) -> dict:
        c = world.club(club_id)
        r = world.row(club_id)
        return {"name": c.name, "position": world.position(club_id), "points": r.pts, "form": r.form,
                "unbeaten_run": r.unbeaten_run, "manager": c.manager.name,
                "manager_games": c.manager.games_in_charge}

    return [story_board, player_profile, club_profile] if board is not None else [player_profile, club_profile]


def make_archivist(client, world: World, board: StoryBoard) -> Agent:
    return Agent(client=client, instructions=INSTRUCTIONS, name="archivist",
                 description="Finds the season storylines a moment makes worth saying.",
                 tools=archivist_tools(world, board))


def moment_prompt(moment: Moment, board: StoryBoard, world: World) -> str:
    ctx = world.fixture_context(board.fixture_id)
    live = [f"- {s.id} [{s.status}] {s.summary}" for s in board.stories.values()]
    return (f"Match: {ctx['home']['club']} v {ctx['away']['club']} (matchday {ctx['matchday']}).\n"
            f"Moment: {moment.kind} at {moment.t // 60_000}' subject={moment.subject} detail={moment.detail}.\n"
            "Story board:\n" + ("\n".join(live) if live else "(empty)"))


async def pick_storylines(agent: Agent, moment: Moment, board: StoryBoard, world: World) -> list[Storyline]:
    """Run the Archivist; unknown ids are dropped, a malformed answer yields no storylines."""
    result = await agent.run(moment_prompt(moment, board, world))
    return stories_from_answer(result.text, board)


def stories_from_answer(text: str, board: StoryBoard) -> list[Storyline]:
    try:
        answer = parse_json(text, ArchivistAnswer)
    except ParseError:
        return []
    picked = []
    for pick in answer.storylines:
        s = board.stories.get(pick.storyline_id)
        if s is not None:
            picked.append(s.model_copy(update={"facts": {**s.facts, "why_now": pick.why_now}}))
    return picked
