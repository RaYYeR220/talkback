import json

import pytest

from talkback.gallery.miners import mine_fixture
from talkback.gallery.world import World
from talkback.world.matchday import prepare_matchday

ALIASES = {"manager_100": "manager_milestone"}


@pytest.fixture(scope="module")
def md_world():
    md = prepare_matchday(2026)
    return md, World(json.loads(json.dumps(md.public_world())))


def test_world_has_no_storylines(md_world):
    _, world = md_world
    assert "storylines" not in world.data


def test_every_planted_kind_is_minable(md_world):
    md, world = md_world
    found = {(c.kind, c.fixture_id) for fid, _, _ in md.fixtures for c in mine_fixture(world, fid)}
    for p in md.planted:
        s = p.storyline
        assert (ALIASES.get(s.kind, s.kind), s.fixture_id) in found, s.kind


def test_trivia_not_mined(md_world):
    md, world = md_world
    mined = [c for fid, _, _ in md.fixtures for c in mine_fixture(world, fid)]
    assert mined and all(not c.kind.startswith("trivia") for c in mined)
    assert len(world.trivia) == 8
