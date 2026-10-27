import math

from talkback.models.passing import pass_completion
from talkback.models.xg import goal_geometry, penalty_xg, shot_xg
from talkback.models.xt import load_xt_grid


def _central(d):
    dist, ang = goal_geometry(105 - d, 34, attacking_right=True)
    return shot_xg(dist, ang, under_pressure=False, header=False, from_set_piece=False)


def test_xg_monotone_distance():
    assert _central(6) > _central(18) > _central(30)


def test_xg_range():
    for d in (2, 6, 11, 18, 25, 40):
        assert 0.01 <= _central(d) <= 0.95
    assert 0.12 <= _central(11) <= 0.30
    assert penalty_xg() == 0.76


def test_goal_geometry_mirror():
    d1, a1 = goal_geometry(95, 30, attacking_right=True)
    d2, a2 = goal_geometry(10, 38, attacking_right=False)
    assert math.isclose(d1, d2) and math.isclose(a1, a2)


def test_pass_completion_short_easy():
    assert pass_completion(8, 5, 5, 70, lofted=False) > 0.9
    assert pass_completion(40, 1, 2, 70, lofted=True) < 0.4


def test_xt_increases_toward_goal():
    g = load_xt_grid()
    assert g.value(95, 34, True) > g.value(60, 34, True) > g.value(20, 34, True)
    assert g.value(10, 34, False) > g.value(45, 34, False) > g.value(85, 34, False)
