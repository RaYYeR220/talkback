import asyncio
import json

from agent_framework import Agent

from talkback.gallery.llm import ScriptedClient, message_text
from talkback.gallery.spotter import Spotter, Triggers, rule_moments
from talkback.models.xt import load_xt_grid
from talkback.schemas.models import Event, EventType, Outcome, event_id
from talkback.stats.desk import StatsDesk
from talkback.world.league import generate_league


def _desk():
    lg = generate_league(7)
    h, a = lg.club("C03"), lg.club("C11")
    return StatsDesk("SP", h, a, load_xt_grid()), h, a


def _ev(seq, t, etype, team, x, outcome=Outcome.success, player=None, **q):
    return Event(id=event_id("SP", seq), match_id="SP", seq=seq, t=t, period=1, type=etype, team_id=team,
                 player_id=player or f"{team}-P05", x=x, y=34.0, end_x=x + 3, end_y=34.0, outcome=outcome,
                 possession_id=seq, qualifiers=q)


def test_goal_is_always_a_strong_moment():
    desk, h, a = _desk()
    g = _ev(1, 60_000, EventType.goal, h.id, 100.0, Outcome.goal)
    desk.ingest(g)
    cands = Triggers(desk).scan([g], 60_000)
    moments = rule_moments(cands)
    goal = next(m for m in moments if m.kind == "goal")
    assert goal.salience >= 0.8 and goal.event_ids == [g.id]


def test_pressing_surge_detected():
    desk, h, a = _desk()
    seq = 0
    evs = []
    # first 10 minutes: away passes freely in its own 60% against few home actions -> high PPDA
    for n in range(40):
        seq += 1
        evs.append(_ev(seq, n * 14_000, EventType.pass_, a.id, 80.0))
    for n in range(3):
        seq += 1
        evs.append(_ev(seq, 100_000 + n * 100_000, EventType.tackle, h.id, 70.0))
    # next 10 minutes: the home side presses -> PPDA collapses
    for n in range(12):
        seq += 1
        evs.append(_ev(seq, 600_000 + n * 45_000, EventType.pass_, a.id, 80.0))
    for n in range(8):
        seq += 1
        evs.append(_ev(seq, 610_000 + n * 60_000, EventType.tackle, h.id, 70.0))
    for e in evs:
        desk.ingest(e)
    cands = Triggers(desk).scan([], 1_200_000)
    surge = [c for c in cands if c.kind == "pressing_surge"]
    assert surge and surge[0].subject == h.id
    assert surge[0].detail["ppda_now"] < surge[0].detail["ppda_before"]


def test_model_ranks_batch_and_goal_floor_holds():
    desk, h, a = _desk()
    g = _ev(1, 60_000, EventType.goal, h.id, 100.0, Outcome.goal)
    s = _ev(2, 70_000, EventType.save, a.id, 5.0)
    for e in (g, s):
        desk.ingest(e)
    cands = Triggers(desk).scan([g, s], 70_000)

    def script(msgs):
        ids = [line.split(":")[0].strip("- ").strip() for line in message_text(msgs).splitlines() if line.startswith("- C-")]
        return json.dumps({"ranking": [{"candidate_id": i, "salience": 0.1, "rationale": "scripted"} for i in ids]})

    spotter = Spotter(Agent(client=ScriptedClient(script), instructions="rank"))
    moments = asyncio.run(spotter.rank(cands))
    by_kind = {m.kind: m for m in moments}
    assert by_kind["goal"].salience == 0.8 and by_kind["goal"].ranked_by == "model"
    assert by_kind["big_save"].salience == 0.1


def test_ranking_failure_falls_back_to_rules():
    desk, h, a = _desk()
    g = _ev(1, 60_000, EventType.goal, h.id, 100.0, Outcome.goal)
    desk.ingest(g)
    cands = Triggers(desk).scan([g], 60_000)
    spotter = Spotter(Agent(client=ScriptedClient(lambda m: "I think the goal matters most."), instructions="rank"))
    moments = asyncio.run(spotter.rank(cands))
    assert all(m.ranked_by == "rules" for m in moments)
