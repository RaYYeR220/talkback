import json

import pytest

from talkback.gallery.director import Director, LiveScore, LiveTable, swings
from talkback.gallery.spotter import Moment
from talkback.gallery.world import World
from talkback.world.matchday import prepare_matchday


@pytest.fixture(scope="module")
def world_md():
    md = prepare_matchday(2026)
    return md, World(json.loads(json.dumps(md.public_world())))


def _scores(md, minute=60, override=None):
    out = []
    for fid, h, a in md.fixtures:
        s = LiveScore(fixture_id=fid, home=h, away=a, minute=minute)
        if override and fid in override:
            s = s.model_copy(update=override[fid])
        out.append(s)
    return out


def test_title_chances_sum_to_one(world_md):
    md, world = world_md
    ch = LiveTable(world, n=1000).chances(_scores(md))
    assert abs(sum(c.title for c in ch) - 1) < 1e-9
    assert abs(sum(c.relegation for c in ch) - 3) < 1e-9
    assert [c.position for c in ch] == list(range(1, 21))


def test_six_pointer_goal_moves_both_clubs_and_is_attributed(world_md):
    md, world = world_md
    six = next(p.storyline for p in md.planted if p.storyline.kind == "relegation_six_pointer")
    fid = six.fixture_id
    home, away = six.subjects
    table = LiveTable(world, n=3000)
    before = table.chances(_scores(md, minute=70))
    after = table.chances(_scores(md, minute=70, override={fid: {"home_goals": 1}}))
    sw = swings(before, after, caused_by=fid)
    rel = {s.club_id: s for s in sw if s.metric == "relegation"}
    assert home in rel and rel[home].after < rel[home].before
    assert away in rel and rel[away].after > rel[away].before
    assert all(s.caused_by == fid for s in sw)


def test_as_it_stands_updates_points(world_md):
    md, world = world_md
    fid, h, a = md.fixtures[0]
    base = {c: p for c, p, _ in LiveTable(world).as_it_stands(_scores(md))}
    after = {c: p for c, p, _ in LiveTable(world).as_it_stands(_scores(md, override={fid: {"home_goals": 2}}))}
    assert after[h] == base[h] + 2 and after[a] == base[a] - 1


def test_director_cuts_to_the_goal_and_holds_briefly():
    d = Director()
    m1 = Moment(id="M1", match_id="F1", t=100_000, kind="big_chance", subject=None, salience=0.6,
                rationale="", event_ids=[])
    m2 = Moment(id="M2", match_id="F2", t=110_000, kind="goal", subject=None, salience=0.95,
                rationale="", event_ids=[])
    r = d.rundown([m1, m2], {}, 112_000, {"F1": "A v B", "F2": "C v D"})
    assert r.match_id == "F2" and "goal" in r.reason
    m3 = Moment(id="M3", match_id="F1", t=115_000, kind="big_save", subject=None, salience=0.65,
                rationale="", event_ids=[])
    r2 = d.rundown([m1, m2, m3], {}, 118_000, {})
    assert r2.match_id == "F2"  # held on screen for at least 20 s unless something much bigger happens
