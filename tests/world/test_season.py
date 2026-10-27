from itertools import combinations

from talkback.world.league import generate_league
from talkback.world.schedule import double_round_robin
from talkback.world.season import backfill_season


def test_schedule():
    ids = [f"C{i:02d}" for i in range(1, 21)]
    s = double_round_robin(ids, seed=4)
    assert len(s) == 38 and all(len(md) == 10 for md in s)
    for md in s:
        teams = [t for f in md for t in f]
        assert len(set(teams)) == 20
    fixtures = [f for md in s for f in md]
    for x, y in combinations(ids, 2):
        assert fixtures.count((x, y)) == 1 and fixtures.count((y, x)) == 1


def test_backfill_consistent():
    st = backfill_season(generate_league(7), matchdays=11, seed=11)
    assert all(r.played == 11 for r in st.table)
    assert sum(r.gf for r in st.table) == sum(r.ga for r in st.table)
    draws = sum(r.drawn for r in st.table) // 2
    decisive = sum(r.won for r in st.table)
    assert sum(r.pts for r in st.table) == 3 * decisive + 2 * draws
    assert len(st.fixtures_next) == 10
    assert st.matchday == 11


def test_backfill_deterministic():
    a = backfill_season(generate_league(7), matchdays=11, seed=11)
    b = backfill_season(generate_league(7), matchdays=11, seed=11)
    assert [r.model_dump() for r in a.table] == [r.model_dump() for r in b.table]
