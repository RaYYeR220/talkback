import asyncio
import json

import pytest
from agent_framework import Agent

from talkback.gallery.agents.lab import LabBackend, finalize, make_lab
from talkback.gallery.llm import ScriptedClient
from talkback.gallery.snapshots import SNAPSHOT_EVERY_MS, SnapshotStore
from talkback.gallery.world import World
from talkback.schemas.models import EventType, Outcome
from talkback.sim.engine import MatchEngine
from talkback.world.matchday import prepare_matchday


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    md = prepare_matchday(2026)
    world = World(json.loads(json.dumps(md.public_world())))
    fid, h, a = md.fixtures[0]
    store = SnapshotStore(tmp_path_factory.mktemp("snaps"))
    eng = MatchEngine(fid, md.league.club(h), md.league.club(a), md.seeds[fid], start_xi=tuple(md.lineups[fid]))
    events = list(eng._events)
    store.save(fid, eng.snapshot())
    while eng.t < 12 * 60_000:
        _, evs = eng.step()
        events.extend(evs)
        if eng.t % SNAPSHOT_EVERY_MS == 0:
            store.save(fid, eng.snapshot())
    by_id = {e.id: e for e in events}
    return md, world, fid, store, events, by_id


def test_cancel_shot_runs_real_rollouts(setup):
    md, world, fid, store, events, by_id = setup
    shot = next(e for e in events if e.type == EventType.shot)
    lab = LabBackend(store, world, by_id.get, n=24, horizon_s=8)
    xs = lab.run("M-1", fid, shot.id, "cancel_shot")
    assert {x.metric for x in xs} == {"threat", "goal_for"}
    assert all(x.id in lab.results and x.n == 24 for x in xs)
    assert xs[0].ci95[0] <= xs[0].effect <= xs[0].ci95[1]


def test_wrong_event_for_experiment_is_rejected(setup):
    md, world, fid, store, events, by_id = setup
    ok_pass = next(e for e in events if e.type == EventType.pass_ and e.outcome == Outcome.success)
    lab = LabBackend(store, world, by_id.get, n=8, horizon_s=4)
    with pytest.raises(ValueError):
        lab.run("M-2", fid, ok_pass.id, "complete_intercepted_pass")


def test_no_snapshot_before_kickoff(setup):
    md, world, fid, store, events, by_id = setup
    empty = SnapshotStore(store.root / "nothing")
    lab = LabBackend(empty, world, by_id.get, n=8, horizon_s=4)
    shot = next(e for e in events if e.type == EventType.shot)
    with pytest.raises(ValueError, match="no snapshot"):
        lab.run("M-3", fid, shot.id, "cancel_shot")


def test_supported_is_recomputed_in_code(setup):
    md, world, fid, store, events, by_id = setup
    shot = next(e for e in events if e.type == EventType.shot)
    lab = LabBackend(store, world, by_id.get, n=16, horizon_s=6)
    xs = lab.run("M-4", fid, shot.id, "cancel_shot")
    claim = json.dumps({"experiments": [xs[0].id, "X-invented"], "conclusion": "It decided the game.",
                        "supported": True})
    res = finalize(claim, lab)
    assert [x.id for x in res.experiments] == [xs[0].id]
    lo, hi = xs[0].ci95
    expect = lo > 0 or hi < 0
    assert res.supported == expect
    if not expect:
        assert res.conclusion == "no clear effect"


def test_lab_agent_calls_backend_through_tool(setup):
    md, world, fid, store, events, by_id = setup
    shot = next(e for e in events if e.type == EventType.shot)
    lab = LabBackend(store, world, by_id.get, n=8, horizon_s=4)
    agent = make_lab(ScriptedClient(lambda m: '{"experiments": [], "conclusion": "no clear effect", "supported": false}'),
                     lab, "M-5", fid)
    assert isinstance(agent, Agent)
    res = finalize(asyncio.run(agent.run(f"event {shot.id}")).text, lab)
    assert res.supported is False and res.experiments == []
