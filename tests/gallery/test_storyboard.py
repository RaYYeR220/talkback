import asyncio
import json

import pytest

from talkback.gallery.agents.archivist import make_archivist, pick_storylines
from talkback.gallery.llm import ScriptedClient, message_text
from talkback.gallery.spotter import Moment
from talkback.gallery.storyboard import StoryBoard
from talkback.gallery.world import World
from talkback.schemas.models import Event, EventType, Outcome, event_id
from talkback.world.matchday import prepare_matchday


@pytest.fixture(scope="module")
def md_world():
    md = prepare_matchday(2026)
    return md, World(json.loads(json.dumps(md.public_world())))


def _milestone(md):
    p = next(p for p in md.planted if p.storyline.kind == "milestone_goals")
    return p.storyline.fixture_id, p.storyline.subjects[0]


def _goal(fid, pid, t=4_000_000):
    return Event(id=event_id(fid, 900), match_id=fid, seq=900, t=t, period=2, type=EventType.goal,
                 team_id=pid.split("-")[0], player_id=pid, x=100.0, y=34.0, outcome=Outcome.goal, possession_id=1)


def test_kickoff_makes_pre_match_stories_live(md_world):
    md, world = md_world
    debut = next(p.storyline for p in md.planted if p.storyline.kind == "debut")
    board = StoryBoard(world, debut.fixture_id)
    live = board.kickoff()
    assert any(s.kind == "debut" and s.subjects == debut.subjects for s in live)


def test_milestone_goes_live_on_the_goal(md_world):
    md, world = md_world
    fid, pid = _milestone(md)
    board = StoryBoard(world, fid)
    board.kickoff()
    changed = board.on_event(_goal(fid, pid))
    m = next(s for s in changed if s.kind == "milestone_goals")
    assert m.status == "live" and m.facts["reached"] == 100


def test_archivist_picks_only_board_ids(md_world):
    md, world = md_world
    fid, pid = _milestone(md)
    board = StoryBoard(world, fid)
    board.kickoff()
    board.on_event(_goal(fid, pid))
    sid = next(s.id for s in board.stories.values() if s.kind == "milestone_goals")

    def script(msgs):
        assert sid in message_text(msgs)
        return json.dumps({"storylines": [{"storyline_id": sid, "why_now": "this is his 100th"},
                                          {"storyline_id": "S-invented", "why_now": "made up"}]})

    agent = make_archivist(ScriptedClient(script), world, board)
    moment = Moment(id="M-1", match_id=fid, t=4_000_000, kind="goal", subject=pid, salience=0.95,
                    rationale="goal", event_ids=[f"{fid}-000900"])
    picked = asyncio.run(pick_storylines(agent, moment, board, world))
    assert [s.id for s in picked] == [sid]
    assert picked[0].facts["why_now"] == "this is his 100th"


def test_archivist_prose_means_no_storylines(md_world):
    md, world = md_world
    fid, _ = _milestone(md)
    board = StoryBoard(world, fid)
    agent = make_archivist(ScriptedClient(lambda m: "The milestone, obviously."), world, board)
    moment = Moment(id="M-2", match_id=fid, t=60_000, kind="big_save", subject=None, salience=0.5,
                    rationale="x", event_ids=[])
    assert asyncio.run(pick_storylines(agent, moment, board, world)) == []
