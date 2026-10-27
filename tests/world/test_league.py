import statistics

from talkback.world.league import generate_league
from talkback.world.names import BANNED_CLUB_NAMES


def test_shape():
    lg = generate_league(7)
    assert len(lg.clubs) == 20
    for c in lg.clubs:
        assert len(c.squad) == 25
        assert sum(p.position == "GK" for p in c.squad) == 3


def test_deterministic():
    assert generate_league(7).model_dump() == generate_league(7).model_dump()
    assert generate_league(7).model_dump() != generate_league(8).model_dump()


def test_no_real_club_names():
    lg = generate_league(7)
    for c in lg.clubs:
        for banned in BANNED_CLUB_NAMES:
            b = banned.lower()
            assert b not in c.name.lower() and b not in c.city.lower(), (c.name, banned)


def test_unique_ids_and_shirts():
    lg = generate_league(7)
    ids = [p.id for c in lg.clubs for p in c.squad]
    assert len(ids) == len(set(ids))
    for c in lg.clubs:
        shirts = [p.shirt for p in c.squad]
        assert len(shirts) == len(set(shirts))


def test_styles_vary():
    lg = generate_league(7)
    assert statistics.pstdev([c.style.press for c in lg.clubs]) > 0.15


def test_lookups_and_formations():
    lg = generate_league(7)
    assert lg.club("C05").id == "C05"
    assert lg.player("C05-P03").club_id == "C05"
    forms = [c.formation for c in lg.clubs]
    for f in ("4-3-3", "4-2-3-1", "4-4-2", "3-5-2"):
        assert forms.count(f) >= 3
